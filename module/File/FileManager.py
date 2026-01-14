import os
import random
from datetime import datetime

import opencc

from base.Base import Base
from module.Cache.CacheItem import CacheItem
from module.Cache.CacheProject import CacheProject
from module.Config import Config
from module.File.ASS import ASS
from module.File.EPUB import EPUB
from module.File.KVJSON import KVJSON
from module.File.MD import MD
from module.File.MESSAGEJSON import MESSAGEJSON
from module.File.RENPY import RENPY
from module.File.SRT import SRT
from module.File.TRANS.TRANS import TRANS
from module.File.TXT import TXT
from module.File.WOLFXLSX import WOLFXLSX
from module.File.XLSX import XLSX
from module.Localizer.Localizer import Localizer

class FileManager(Base):

    # OpenCC 转换器（类级别，延迟加载）
    _opencc_t2s: opencc.OpenCC = None  # 繁体转简体
    _opencc_s2t: opencc.OpenCC = None  # 简体转繁体

    @classmethod
    def get_opencc_t2s(cls) -> opencc.OpenCC:
        """获取繁体转简体转换器（延迟加载）"""
        if cls._opencc_t2s is None:
            cls._opencc_t2s = opencc.OpenCC("t2s")  # 繁体到简体
        return cls._opencc_t2s

    @classmethod
    def get_opencc_s2t(cls) -> opencc.OpenCC:
        """获取简体转繁体转换器（延迟加载）"""
        if cls._opencc_s2t is None:
            cls._opencc_s2t = opencc.OpenCC("s2tw")  # 简体到台湾繁体
        return cls._opencc_s2t

    def __init__(self, config: Config) -> None:
        super().__init__()

        # 初始化
        self.config = config

    # 读
    def read_from_path(self) -> tuple[CacheProject, list[CacheItem]]:
        project: CacheProject = CacheProject.from_dict({
            "id": f"{datetime.now().strftime("%Y%m%d_%H%M%S")}_{random.randint(100000, 999999)}",
        })

        items: list[CacheItem] = []
        try:
            paths: list[str] = []
            input_folder: str = self.config.input_folder
            if os.path.isfile(input_folder):
                paths = [input_folder]
            elif os.path.isdir(input_folder):
                for root, _, files in os.walk(input_folder):
                    paths.extend([f"{root}/{file}".replace("\\", "/") for file in files])

            items.extend(MD(self.config).read_from_path([path for path in paths if path.lower().endswith(".md")]))
            items.extend(TXT(self.config).read_from_path([path for path in paths if path.lower().endswith(".txt")]))
            items.extend(ASS(self.config).read_from_path([path for path in paths if path.lower().endswith(".ass")]))
            items.extend(SRT(self.config).read_from_path([path for path in paths if path.lower().endswith(".srt")]))
            items.extend(EPUB(self.config).read_from_path([path for path in paths if path.lower().endswith(".epub")]))
            items.extend(XLSX(self.config).read_from_path([path for path in paths if path.lower().endswith(".xlsx")]))
            items.extend(WOLFXLSX(self.config).read_from_path([path for path in paths if path.lower().endswith(".xlsx")]))
            items.extend(RENPY(self.config).read_from_path([path for path in paths if path.lower().endswith(".rpy")]))
            items.extend(TRANS(self.config).read_from_path([path for path in paths if path.lower().endswith(".trans")]))
            items.extend(KVJSON(self.config).read_from_path([path for path in paths if path.lower().endswith(".json")]))
            items.extend(MESSAGEJSON(self.config).read_from_path([path for path in paths if path.lower().endswith(".json")]))
        except Exception as e:
            self.error(f"{Localizer.get().log_read_file_fail}", e)

        return project, items

    # 写
    def write_to_path(self, items: list[CacheItem]) -> None:
        try:
            # ========== 繁简转换预处理 ==========
            # 在写入所有文件之前，统一进行繁简转换（只转换一次）
            if getattr(self.config, 'simplified_chinese_enable', False):
                # 繁体转简体
                converter = FileManager.get_opencc_t2s()
                converted_count = 0
                for item in items:
                    dst = item.get_dst()
                    if dst:
                        item.set_dst(converter.convert(dst))
                        converted_count += 1
                self.info(f"[繁简转换] 已将 {converted_count} 条译文从繁体转换为简体")
            elif getattr(self.config, 'traditional_chinese_enable', False):
                # 简体转繁体
                converter = FileManager.get_opencc_s2t()
                converted_count = 0
                for item in items:
                    dst = item.get_dst()
                    if dst:
                        item.set_dst(converter.convert(dst))
                        converted_count += 1
                self.info(f"[繁简转换] 已将 {converted_count} 条译文从简体转换为繁体")

            # ========== 写入各文件格式 ==========
            MD(self.config).write_to_path(items)
            TXT(self.config).write_to_path(items)
            ASS(self.config).write_to_path(items)
            SRT(self.config).write_to_path(items)
            EPUB(self.config).write_to_path(items)
            XLSX(self.config).write_to_path(items)
            WOLFXLSX(self.config).write_to_path(items)
            RENPY(self.config).write_to_path(items)
            TRANS(self.config).write_to_path(items)
            KVJSON(self.config).write_to_path(items)
            MESSAGEJSON(self.config).write_to_path(items)
        except Exception as e:
            self.error(f"{Localizer.get().log_write_file_fail}", e)