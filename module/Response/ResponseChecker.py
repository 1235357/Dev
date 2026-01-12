import re
from enum import StrEnum

from base.Base import Base
from base.BaseLanguage import BaseLanguage
from module.Text.TextHelper import TextHelper
from module.Cache.CacheItem import CacheItem
from module.Config import Config
from module.Filter.RuleFilter import RuleFilter
from module.Filter.LanguageFilter import LanguageFilter
from module.TextProcessor import TextProcessor

class ResponseChecker(Base):

    class Error(StrEnum):

        NONE = "NONE"
        UNKNOWN = "UNKNOWN"
        FAIL_DATA = "FAIL_DATA"
        FAIL_LINE_COUNT = "FAIL_LINE_COUNT"
        LINE_ERROR_KANA = "LINE_ERROR_KANA"
        LINE_ERROR_HANGEUL = "LINE_ERROR_HANGEUL"
        LINE_ERROR_FAKE_REPLY = "LINE_ERROR_FAKE_REPLY"
        LINE_ERROR_EMPTY_LINE = "LINE_ERROR_EMPTY_LINE"
        LINE_ERROR_SIMILARITY = "LINE_ERROR_SIMILARITY"
        LINE_ERROR_DEGRADATION = "LINE_ERROR_DEGRADATION"

    LINE_ERROR: tuple[StrEnum] = (
        Error.LINE_ERROR_KANA,
        Error.LINE_ERROR_HANGEUL,
        Error.LINE_ERROR_FAKE_REPLY,
        Error.LINE_ERROR_EMPTY_LINE,
        Error.LINE_ERROR_SIMILARITY,
        Error.LINE_ERROR_DEGRADATION,
    )

    # 重试次数阈值
    RETRY_COUNT_THRESHOLD: int = 2

    # 行数不一致容错阈值 - 允许自动补全的最大缺失行数
    LINE_COUNT_TOLERANCE: int = 3

    # 假名残留容错阈值 - 假名字符占比小于等于此值时予以容忍
    KANA_TOLERANCE_RATIO: float = 0.10

    # 退化检测规则
    RE_DEGRADATION = re.compile(r"(.{1,3})\1{16,}", flags = re.IGNORECASE)

    # 阿里云百炼 DeepSeek 模型识别
    RE_DASHSCOPE_DEEPSEEK_URL: re.Pattern = re.compile(r"api-inference\.modelscope\.cn", flags = re.IGNORECASE)
    RE_DASHSCOPE_DEEPSEEK_MODEL: re.Pattern = re.compile(r"deepseek-ai", flags = re.IGNORECASE)

    def __init__(self, config: Config, items: list[CacheItem], platform: dict = None) -> None:
        super().__init__()

        # 初始化
        self.items = items
        self.config = config
        self.platform = platform if platform is not None else {}

    # 判断是否为阿里云百炼 DeepSeek 模型
    def is_dashscope_deepseek(self) -> bool:
        api_url = self.platform.get("api_url", "")
        model = self.platform.get("model", "")
        return (
            __class__.RE_DASHSCOPE_DEEPSEEK_URL.search(api_url) is not None and
            __class__.RE_DASHSCOPE_DEEPSEEK_MODEL.search(model) is not None
        )

    # 检查
    def check(self, srcs: list[str], dsts: list[str], text_type: CacheItem.TextType) -> tuple[list[str], list[str]]:
        # 数据解析失败
        if len(dsts) == 0 or all(v == "" or v == None for v in dsts):
            return [__class__.Error.FAIL_DATA] * len(srcs), dsts

        # 当翻译任务为单条目任务，且此条目已经是第二次单独重试时，直接返回，不进行后续判断
        if len(self.items) == 1 and self.items[0].get_retry_count() >= __class__.RETRY_COUNT_THRESHOLD:
            return [__class__.Error.NONE] * len(srcs), dsts

        # 行数检查 - 添加容错机制
        if len(srcs) != len(dsts):
            # 系统级容错：若译文缺少行数 <= LINE_COUNT_TOLERANCE，自动补空字符串；否则仍判定为行数错误
            missing_lines = len(srcs) - len(dsts)
            if 0 < missing_lines <= __class__.LINE_COUNT_TOLERANCE:
                # 自动补全缺失的行
                dsts = dsts + [""] * missing_lines
                self.warning(
                    f"[行数容错] 译文行数不足，自动补全 {missing_lines} 行空字符串 (原文: {len(srcs)} 行, 译文: {len(dsts) - missing_lines} 行)"
                )
            else:
                return [__class__.Error.FAIL_LINE_COUNT] * len(srcs), dsts

        # 逐行检查
        checks = self.check_lines(srcs, dsts, text_type)
        if any(v != __class__.Error.NONE for v in checks):
            return checks, dsts

        # 默认无错误
        return [__class__.Error.NONE] * len(srcs), dsts

    # 计算假名字符占比
    def calculate_kana_ratio(self, text: str) -> float:
        if len(text) == 0:
            return 0.0
        kana_count = sum(1 for c in text if TextHelper.JA.hiragana(c) or TextHelper.JA.katakana(c))
        return kana_count / len(text)

    # 统计平假名/片假名数量
    def count_kana(self, text: str) -> tuple[int, int, int]:
        hiragana_count = 0
        katakana_count = 0
        for c in text:
            if TextHelper.JA.hiragana(c):
                hiragana_count += 1
            elif TextHelper.JA.katakana(c):
                katakana_count += 1
        return hiragana_count, katakana_count, hiragana_count + katakana_count

    # 逐行检查错误
    def check_lines(self, srcs: list[str], dsts: list[str], text_type: CacheItem.TextType) -> list[Error]:
        checks: list[__class__.Error] = []

        # 系统级容错：允许少量“原文非空但译文为空”的情况（通常源于流式/解析缺失/输出格式错乱）
        allow_empty_missing = True
        empty_missing_count = 0

        tolerated_empty_samples: list[tuple[int, str, str]] = []
        failed_empty_samples: list[tuple[int, str, str]] = []

        for i, (src_raw, dst_raw) in enumerate(zip(srcs, dsts)):
            src = src_raw.strip()
            dst = dst_raw.strip()

            # 原文不为空而译文为空时，判断为错误翻译
            if src != "" and dst == "":
                if allow_empty_missing and empty_missing_count < __class__.LINE_COUNT_TOLERANCE:
                    empty_missing_count += 1
                    tolerated_empty_samples.append((i, src[:40], repr(dst_raw)))
                    # 容忍该行，避免触发整段重试
                    checks.append(__class__.Error.NONE)
                    continue
                failed_empty_samples.append((i, src[:40], repr(dst_raw)))
                checks.append(__class__.Error.LINE_ERROR_EMPTY_LINE)
                continue

            # 原文内容符合规则过滤条件时，判断为正确翻译
            if RuleFilter.filter(src) == True:
                checks.append(__class__.Error.NONE)
                continue

            # 原文内容符合语言过滤条件时，判断为正确翻译
            if LanguageFilter.filter(src, self.config.source_language) == True:
                checks.append(__class__.Error.NONE)
                continue

            # 当原文中不包含重复文本但是译文中包含重复文本时，判断为 退化
            if __class__.RE_DEGRADATION.search(src) == None and __class__.RE_DEGRADATION.search(dst) != None:
                checks.append(__class__.Error.LINE_ERROR_DEGRADATION)
                continue

            # 排除代码保护规则覆盖的文本以后再继续进行检查
            rule: re.Pattern = TextProcessor(self.config, None).get_re_sample(
                custom = self.config.text_preserve_enable,
                text_type = text_type,
            )
            if rule is not None:
                src = rule.sub("", src)
                dst = rule.sub("", dst)

            # 当原文语言为日语，且译文中包含平假名或片假名字符时，判断为 假名残留
            if self.config.source_language == BaseLanguage.Enum.JA and (TextHelper.JA.any_hiragana(dst) or TextHelper.JA.any_katakana(dst)):
                # 针对阿里百炼 DeepSeek 模型：假名残留占比 <= KANA_TOLERANCE_RATIO 时予以容忍
                # 注：像「コ」字形这类形状描述符是合理保留，占比极低，应予以放过
                if self.is_dashscope_deepseek():
                    kana_ratio = self.calculate_kana_ratio(dst)
                    if kana_ratio <= __class__.KANA_TOLERANCE_RATIO:
                        self.warning(
                            f"[阿里百炼DeepSeek容错] 假名占比={kana_ratio:.1%} <= {__class__.KANA_TOLERANCE_RATIO:.0%}，予以容忍"
                        )
                        checks.append(__class__.Error.NONE)
                        continue
                checks.append(__class__.Error.LINE_ERROR_KANA)
                continue

            # 当原文语言为韩语，且译文中包含谚文字符时，判断为 谚文残留
            if self.config.source_language == BaseLanguage.Enum.KO and TextHelper.KO.any_hangeul(dst):
                checks.append(__class__.Error.LINE_ERROR_HANGEUL)
                continue

            # 判断是否包含或相似
            if src in dst or dst in src or TextHelper.check_similarity_by_jaccard(src, dst) > 0.80 == True:
                # 日翻中时，只有译文至少包含一个平假名或片假名字符时，才判断为 相似
                if self.config.source_language == BaseLanguage.Enum.JA and self.config.target_language == BaseLanguage.Enum.ZH:
                    if TextHelper.JA.any_hiragana(dst) or TextHelper.JA.any_katakana(dst):
                        checks.append(__class__.Error.LINE_ERROR_SIMILARITY)
                        continue
                # 韩翻中时，只有译文至少包含一个谚文字符时，才判断为 相似
                elif self.config.source_language == BaseLanguage.Enum.KO and self.config.target_language == BaseLanguage.Enum.ZH:
                    if TextHelper.KO.any_hangeul(dst):
                        checks.append(__class__.Error.LINE_ERROR_SIMILARITY)
                        continue
                # 其他情况，只要原文译文相同或相似就可以判断为 相似
                else:
                    checks.append(__class__.Error.LINE_ERROR_SIMILARITY)
                    continue

            # 默认为无错误
            checks.append(__class__.Error.NONE)

        # 返回结果
        if empty_missing_count > 0:
            # 仅记录简要样例，避免刷屏
            self.warning(
                f"[空行诊断] 原文非空但译文为空/空白：已容忍 {empty_missing_count}/{__class__.LINE_COUNT_TOLERANCE} 行；"
                f" 样例(索引,src前40,原始dst)= {tolerated_empty_samples[:3]}"
            )
        if len(failed_empty_samples) > 0:
            self.warning(
                f"[空行诊断] 原文非空但译文为空/空白：超出阈值(>{__class__.LINE_COUNT_TOLERANCE})，"
                f"失败行数={len(failed_empty_samples)}； 样例(索引,src前40,原始dst)= {failed_empty_samples[:3]}"
            )
        return checks