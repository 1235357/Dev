#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EPUB 日文原文还原脚本（批量）

目标：
- 批量处理指定目录下的所有 .epub
- 删除“夹带的中文译文”（常见于自动注入双语对照的 EPUB）
- 可选：移除 ruby 注音（<ruby>/<rt>/<rb>），保留正文汉字

实现思路：
- EPUB 本质是 ZIP。
- 读取 ZIP 内的 XHTML/HTML 文档，做定向清理，再重新打包为 EPUB。
- 重新打包时必须确保：mimetype 文件第一项写入，且不压缩（ZIP_STORED）。

兼容的“中文译文注入”形态（按优先级）：
1) opacity 双语模式（auto-novel 的注入特征）：
   - 原文段落会被设置 style="opacity:0.4/0.5"（变浅）
   - 译文段落通常紧挨原文出现，且没有 opacity
   => 删除紧邻的“无 opacity 段落/标题”，并移除保留段落上的 opacity。

2) class 双语模式（例如 calibre3/4）：
   - 中文与日文使用不同的 class（如 calibre3 vs calibre4）
   - 日文段落更可能包含假名（平/片假名）
   => 统计每个 class 的“含假名比例”，推断哪个 class 是日文并保留。

3) 兜底：基于内容的粗判（可通过 --aggressive 启用/加强）

注意：
- ruby（注音）在 EPUB3 中是合法的；这里只是按你的需求做“去注音还原为一行”。

用法示例：
  python main.py --in "D:/books" --out "D:/books_jp" --recursive

"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

import xml.etree.ElementTree as ET


XHTML_NS = "http://www.w3.org/1999/xhtml"
OPS_NS = "http://www.idpf.org/2007/ops"  # 常用于 epub:type


def _register_namespaces() -> None:
    # 避免输出出现 ns0 前缀（尽量保持默认命名空间）
    try:
        ET.register_namespace("", XHTML_NS)
        ET.register_namespace("epub", OPS_NS)
    except Exception:
        # 极端情况下注册失败也不影响功能
        pass


def _q(tag: str) -> str:
    return f"{{{XHTML_NS}}}{tag}"


_KANA_RE = re.compile(r"[\u3040-\u309F\u30A0-\u30FF]")
_OPACITY_RE = re.compile(r"(?:^|;)\s*opacity\s*:\s*([0-9]*\.?[0-9]+)\s*(?:;|$)", re.I)

# 典型“简体中文译文”会包含大量简化字（在日文 EPUB 中出现概率极低）。
# 这不是完备的简繁判定，只作为高置信度的“中文译文”提示。
_SIMPLIFIED_HINT_RE = re.compile(
    "["
    "这那吗么们还没将把被于与并为从经预变竖采载"
    "发后该会让应当现给点进过种时图书页体术"
    "语蓝诅咒赏译译者简体"
    "]"
)

_CSS_OPACITY_DECL_RE = re.compile(r"\bopacity\s*:\s*([0-9]*\.?[0-9]+)\s*;?", re.I)
_STYLE_COLOR_RE = re.compile(r"(?:^|;)\s*color\s*:\s*([^;]+)\s*(?:;|$)", re.I)

_XML_LANG_KEY = "{http://www.w3.org/XML/1998/namespace}lang"


def has_kana(text: str) -> bool:
    return _KANA_RE.search(text) is not None


def contains_simplified_hints(text: str) -> bool:
    return _SIMPLIFIED_HINT_RE.search(text) is not None


def extract_opacity(style: str) -> Optional[float]:
    m = _OPACITY_RE.search(style)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def extract_color(style: str) -> Optional[str]:
    m = _STYLE_COLOR_RE.search(style)
    if not m:
        return None
    val = (m.group(1) or "").strip().strip("\"")
    return val or None


def _normalize_color_value(val: str) -> str:
    v = (val or "").strip().lower().replace(" ", "")
    return v


_BILINGUAL_COLOR_VALUES = {
    "#ff0000",
    "#f00",
    "rgb(255,0,0)",
    "red",
    "#000000",
    "#000",
    "rgb(0,0,0)",
    "black",
}


def strip_color(style: str) -> str:
    # 移除 style 中的 color:... 片段
    style2 = re.sub(r"(?:^|;)\s*color\s*:\s*[^;]+\s*", ";", style, flags=re.I)
    style2 = re.sub(r"\s*;\s*", ";", style2).strip(" ;")
    return style2


def get_lang(el: ET.Element) -> str:
    # 兼容 lang / xml:lang
    lang = (el.get("lang") or el.get(_XML_LANG_KEY) or "").strip().lower()
    return lang


def strip_opacity(style: str) -> str:
    # 移除 style 中的 opacity:... 片段
    style2 = re.sub(r"(?:^|;)\s*opacity\s*:\s*[0-9]*\.?[0-9]+\s*", ";", style, flags=re.I)
    # 清理多余分号与空白
    style2 = re.sub(r"\s*;\s*", ";", style2).strip(" ;")
    return style2


def clean_css_bytes(data: bytes) -> tuple[bytes, int]:
    """清理 CSS 中的 opacity 声明。

    说明：
    - 有些双语 EPUB 会在样式表里把“原文 class”整体设置为 opacity:0.4。
      即使我们移除了 XHTML 行内 style，这个规则仍会让正文发灰。
    - 这里仅移除 opacity < 1 的声明，避免破坏本来就不透明的样式。
    """

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # 宽容处理：不强行猜测其它编码，避免写坏文件
        text = data.decode("utf-8", "replace")

    removed = 0

    def _repl(m: re.Match[str]) -> str:
        nonlocal removed
        val_s = m.group(1)
        try:
            val = float(val_s)
        except ValueError:
            return m.group(0)
        if val < 0.999:
            removed += 1
            return ""
        return m.group(0)

    new_text = _CSS_OPACITY_DECL_RE.sub(_repl, text)

    # 清理可能产生的 ";;" 或多余空白（保守处理，不做大规模格式化）
    if removed:
        new_text = re.sub(r";\s*;", ";", new_text)

    return new_text.encode("utf-8"), removed


def is_texty(s: str) -> bool:
    return s.strip() != ""


def looks_like_chinese(text: str) -> bool:
    """粗略判定：这段文本更像“中文译文”。

    说明：
    - 我们优先用更可靠的结构特征（opacity/class）。
    - 这里只做兜底，宁可保守。
    """
    s = re.sub(r"\s+", "", text)
    if not s:
        return False

    # 有假名基本可判定为日文
    if has_kana(s):
        return False

    # 简体字提示：高置信度判断为中文译文
    if contains_simplified_hints(s):
        return True

    # 常见中文标点/语气词/语法助词（在日文中出现概率低）
    if "，" in s or "：" in s or "；" in s:
        return True

    # 低置信度的中文语气/语法提示。
    # 注意：避免使用在日文中也常见的“的/了”（例如：目的/了解），减少误杀。
    zh_markers = [
        "这",
        "那",
        "着",
        "么",
        "吗",
        "们",
        "还",
        "没",
        "将",
        "把",
        "被",
        "于",
        "与",
        "并",
        "此外",
        "根据",
        "可能",
        "出现",
        "采用",
        "封面",
        "下载",
        "未经",
        "预告",
        "变更",
        "竖排",
        "阅读",
        "系统",
        "显示",
        "差异",
    ]
    if any(m in s for m in zh_markers):
        return True

    return False


BLOCK_TAGS = {
    _q("p"),
    _q("h1"),
    _q("h2"),
    _q("h3"),
    _q("h4"),
    _q("h5"),
    _q("h6"),
}


CONTAINER_TAGS = {
    _q("div"),
    _q("section"),
    _q("article"),
    _q("aside"),
    _q("blockquote"),
    _q("li"),
}


def _iter_parents(root: ET.Element) -> Iterable[ET.Element]:
    # ElementTree 没有 parent 指针，只能遍历所有元素当作 parent
    yield root
    for el in root.iter():
        yield el


def _remove_child_preserve_tail(parent: ET.Element, child: ET.Element) -> None:
    children = list(parent)
    try:
        idx = children.index(child)
    except ValueError:
        return

    tail = child.tail or ""
    if tail:
        if idx == 0:
            parent.text = (parent.text or "") + tail
        else:
            prev = children[idx - 1]
            prev.tail = (prev.tail or "") + tail

    parent.remove(child)


def _replace_child_with_text(parent: ET.Element, child: ET.Element, text: str) -> None:
    children = list(parent)
    try:
        idx = children.index(child)
    except ValueError:
        return

    merged = text + (child.tail or "")
    if merged:
        if idx == 0:
            parent.text = (parent.text or "") + merged
        else:
            prev = children[idx - 1]
            prev.tail = (prev.tail or "") + merged

    parent.remove(child)


@dataclass
class XhtmlCleanStats:
    removed_translation_blocks: int = 0
    removed_ruby_rt: int = 0
    unwrapped_ruby: int = 0
    stripped_opacity: int = 0
    removed_by_class: int = 0
    removed_by_heuristic: int = 0
    removed_by_lang: int = 0
    stripped_color: int = 0


def _remove_rt_rp(root: ET.Element, stats: XhtmlCleanStats) -> None:
    # 删除 <rt> / <rp>
    for parent in _iter_parents(root):
        for child in list(parent):
            if child.tag in (_q("rt"), _q("rp")):
                stats.removed_ruby_rt += 1
                _remove_child_preserve_tail(parent, child)
            else:
                # 继续深入
                pass


def _unwrap_ruby(root: ET.Element, stats: XhtmlCleanStats) -> None:
    # 把 <ruby>...</ruby> 变成纯文本（优先取 <rb>）
    for parent in _iter_parents(root):
        for child in list(parent):
            if child.tag == _q("ruby"):
                rbs = child.findall(".//" + _q("rb"))
                if rbs:
                    base = "".join("".join(rb.itertext()).strip() for rb in rbs)
                else:
                    base = "".join(t.strip() for t in child.itertext())
                stats.unwrapped_ruby += 1
                _replace_child_with_text(parent, child, base)


def _strip_opacity_in_tree(root: ET.Element, stats: XhtmlCleanStats) -> None:
    # 去掉所有元素 style 里的 opacity
    for el in root.iter():
        style = el.get("style")
        if not style:
            continue
        if extract_opacity(style) is None:
            continue
        new_style = strip_opacity(style)
        stats.stripped_opacity += 1
        if new_style:
            el.set("style", new_style)
        else:
            el.attrib.pop("style", None)


def _strip_color_in_tree(root: ET.Element, stats: XhtmlCleanStats) -> None:
    # 去掉所有元素 style 里的 color（该类双语 EPUB 常用红/黑区分语言，恢复为默认颜色更适合阅读）
    for el in root.iter():
        style = el.get("style")
        if not style:
            continue
        col = extract_color(style)
        if col is None:
            continue
        # 保守：仅移除常见“中日区分用”的红/黑色，避免误伤原书的正常彩色排版。
        if _normalize_color_value(col) not in _BILINGUAL_COLOR_VALUES:
            continue
        new_style = strip_color(style)
        stats.stripped_color += 1
        if new_style:
            el.set("style", new_style)
        else:
            el.attrib.pop("style", None)


def _remove_translation_by_lang(root: ET.Element, stats: XhtmlCleanStats) -> None:
    # 规则：删除所有 lang/xml:lang 为 zh* 的块级元素。
    # 该类型 EPUB 往往中日共用同一个 class，仅靠 class/kana 推断会失败；lang 是最高置信度信号。
    for parent in _iter_parents(root):
        for child in list(parent):
            if child.tag not in BLOCK_TAGS and child.tag not in CONTAINER_TAGS:
                continue
            lang = get_lang(child)
            if lang.startswith("zh"):
                txt = "".join(child.itertext()).strip()
                # 为空也删掉（避免留下空行/空块），但不计入统计。
                if txt:
                    stats.removed_by_lang += 1
                _remove_child_preserve_tail(parent, child)


def _collect_text_blocks(root: ET.Element) -> list[ET.Element]:
    blocks: list[ET.Element] = []
    for el in root.iter():
        if el.tag in BLOCK_TAGS:
            txt = "".join(el.itertext())
            if is_texty(txt):
                blocks.append(el)
    return blocks


def _has_dim_style(el: ET.Element) -> bool:
    style = el.get("style")
    if not style:
        return False
    op = extract_opacity(style)
    return op is not None and op < 0.999


def _remove_translation_by_opacity(root: ET.Element, stats: XhtmlCleanStats) -> None:
    # 以“原文变浅 opacity、译文紧邻且无 opacity”为特征清理。
    # 支持一个原文对应多条译文：会删除紧邻原文的一整段连续“无 opacity 块”。
    for parent in _iter_parents(root):
        children = list(parent)
        if not children:
            continue

        to_remove: set[int] = set()

        for i, el in enumerate(children):
            if el.tag not in BLOCK_TAGS:
                continue
            txt = "".join(el.itertext()).strip()
            if not txt:
                continue
            if not _has_dim_style(el):
                continue

            # 向前删：同 tag + 无 opacity + 有文本
            j = i - 1
            while j >= 0:
                sib = children[j]
                if sib.tag != el.tag:
                    break
                st = "".join(sib.itertext()).strip()
                if not st:
                    break
                if _has_dim_style(sib):
                    break
                to_remove.add(j)
                j -= 1

            # 向后删
            j = i + 1
            while j < len(children):
                sib = children[j]
                if sib.tag != el.tag:
                    break
                st = "".join(sib.itertext()).strip()
                if not st:
                    break
                if _has_dim_style(sib):
                    break
                to_remove.add(j)
                j += 1

        if to_remove:
            for idx in sorted(to_remove, reverse=True):
                stats.removed_translation_blocks += 1
                parent.remove(children[idx])


def _infer_keep_class_by_kana(blocks: list[ET.Element]) -> tuple[Optional[str], bool]:
    # 仅统计 p 标签更靠谱（标题类可能不稳定）
    # value: (total, kana_count, zh_hint_count)
    per_class: dict[str, list[int]] = {}
    for el in blocks:
        if el.tag != _q("p"):
            continue
        cls = el.get("class")
        if not cls:
            continue
        txt = "".join(el.itertext())
        total, kana_cnt, zh_cnt = per_class.get(cls, [0, 0, 0])
        total += 1
        if has_kana(txt):
            kana_cnt += 1
        if looks_like_chinese(txt):
            zh_cnt += 1
        per_class[cls] = [total, kana_cnt, zh_cnt]

    if len(per_class) < 2:
        return None, False

    # 便于挑两个“主 class”做判断：
    # 小页面（比如版权/注意事项）段落数很少，但仍然可能是明显中日双语。
    items = []
    for cls, (total, kana_cnt, zh_cnt) in per_class.items():
        if total <= 0:
            continue
        kana_ratio = kana_cnt / total
        zh_ratio = zh_cnt / total
        items.append((total, kana_cnt, kana_ratio, zh_cnt, zh_ratio, cls))

    if len(items) < 2:
        return None, False

    # 先按 total 排序，取出现最多的两个 class（通常就是中/日两类）
    items.sort(reverse=True)
    top2 = items[:2]
    (t1, k1, r1, z1, zr1, c1), (t2, k2, r2, z2, zr2, c2) = top2

    # 特判：一方出现假名、另一方完全没有，并且“无假名侧”中文提示明显
    # => 高置信度认为有假名的一方是日文。
    if k1 > 0 and k2 == 0 and zr2 >= 0.25:
        return c1, True
    if k2 > 0 and k1 == 0 and zr1 >= 0.25:
        return c2, True

    # 若某个 class 中文提示比例很高，则倾向保留另一个 class。
    if zr1 >= 0.45 and zr2 <= 0.10:
        return c2, True
    if zr2 >= 0.45 and zr1 <= 0.10:
        return c1, True

    # 常规：按“含假名比例”选择，但只有差距足够明显才做推断。
    # 这里不再硬性要求 total>=8，以适配短页面；但会降低置信度。
    # 置信度用于后续删除策略：低置信度只删除“更像中文”的段落。
    if r1 >= r2:
        best_ratio, best_total, best_kana, best_zh_ratio, best_cls = r1, t1, k1, zr1, c1
        worst_ratio, worst_total, worst_kana, worst_zh_ratio, worst_cls = r2, t2, k2, zr2, c2
    else:
        best_ratio, best_total, best_kana, best_zh_ratio, best_cls = r2, t2, k2, zr2, c2
        worst_ratio, worst_total, worst_kana, worst_zh_ratio, worst_cls = r1, t1, k1, zr1, c1

    # 差距不明显则不做 class 推断
    if (best_ratio - worst_ratio) < 0.20:
        return None, False

    # 以“低假名侧也明显像中文”为强置信度条件，避免把日文标题 class 误删。
    strong = best_ratio >= 0.25 and worst_zh_ratio >= 0.25
    return best_cls, strong


def _remove_translation_by_class(
    root: ET.Element,
    keep_class: str,
    *,
    strong: bool,
    aggressive: bool,
    stats: XhtmlCleanStats,
) -> None:
    for parent in _iter_parents(root):
        children = list(parent)
        if not children:
            continue
        for child in children:
            if child.tag != _q("p"):
                continue
            txt = "".join(child.itertext()).strip()
            if not txt:
                continue
            cls = child.get("class")
            if not cls or cls == keep_class:
                continue

            # 强置信度（典型中日双语 interleave）时：优先删除非 keep_class。
            # 低置信度时：只删除“更像中文译文”的段落，避免误删日文不同排版 class。
            if strong:
                stats.removed_by_class += 1
                parent.remove(child)
                continue

            if looks_like_chinese(txt):
                stats.removed_by_class += 1
                parent.remove(child)
                continue

            if aggressive and not has_kana(txt):
                stats.removed_by_class += 1
                parent.remove(child)


def _remove_translation_by_heuristic(root: ET.Element, aggressive: bool, stats: XhtmlCleanStats) -> None:
    # 兜底：只对 <p>/<h*> 这种块级文本清理
    for parent in _iter_parents(root):
        children = list(parent)
        if not children:
            continue
        for child in children:
            if child.tag not in BLOCK_TAGS:
                continue
            txt = "".join(child.itertext()).strip()
            if not txt:
                continue

            if looks_like_chinese(txt):
                stats.removed_by_heuristic += 1
                parent.remove(child)

            # 非 aggressive 时，保持更保守（目前 looks_like_chinese 已经偏保守）
            # aggressive 参数保留给未来扩展：可加入更多规则。


def clean_xhtml_bytes(data: bytes, *, remove_ruby: bool, aggressive: bool) -> tuple[bytes, XhtmlCleanStats]:
    stats = XhtmlCleanStats()

    # 有些 EPUB XHTML 会带 BOM
    data2 = data.lstrip(b"\xef\xbb\xbf")

    try:
        parser = ET.XMLParser()
        root = ET.fromstring(data2, parser=parser)
    except Exception:
        # XML 解析失败时，尽量做“纯文本级”替换（降级策略）
        text = data2.decode("utf-8", "replace")

        if remove_ruby:
            # 删除 rt/rp
            text = re.sub(r"<\s*rt\b[^>]*>.*?<\s*/\s*rt\s*>", "", text, flags=re.I | re.S)
            text = re.sub(r"<\s*rp\b[^>]*>.*?<\s*/\s*rp\s*>", "", text, flags=re.I | re.S)
            # 去掉 rb/ruby 标签（保留内容）
            text = re.sub(r"<\s*/?\s*rb\b[^>]*>", "", text, flags=re.I)
            text = re.sub(r"<\s*/?\s*ruby\b[^>]*>", "", text, flags=re.I)

        # opacity 模式：删除紧邻 dim 段落很难用正则可靠完成，这里只做启发式
        if aggressive:
            # 删除明显中文的段落（简易）
            def _drop_p(m: re.Match[str]) -> str:
                seg = m.group(0)
                inner = re.sub(r"<[^>]+>", "", seg)
                if looks_like_chinese(inner):
                    stats.removed_by_heuristic += 1
                    return ""
                return seg

            text = re.sub(r"<p\b[^>]*>.*?</p>", _drop_p, text, flags=re.I | re.S)

        return text.encode("utf-8"), stats

    _register_namespaces()

    # 1) ruby 清理
    if remove_ruby:
        _remove_rt_rp(root, stats)
        _unwrap_ruby(root, stats)

    # 1.5) 最高置信度：按 lang=zh 删除中文块
    _remove_translation_by_lang(root, stats)

    # 2) 中文译文清理
    blocks = _collect_text_blocks(root)
    dim_count = sum(1 for el in blocks if _has_dim_style(el))

    if dim_count >= max(3, int(len(blocks) * 0.05)):
        # opacity 特征明显：优先用它（最可靠）
        _remove_translation_by_opacity(root, stats)
        _strip_opacity_in_tree(root, stats)
    else:
        # 尝试 class 推断
        keep_cls, strong = _infer_keep_class_by_kana(blocks)
        if keep_cls:
            _remove_translation_by_class(
                root,
                keep_cls,
                strong=strong,
                aggressive=aggressive,
                stats=stats,
            )
        else:
            # 兜底启发式
            _remove_translation_by_heuristic(root, aggressive=aggressive, stats=stats)

    # 3) 还原阅读体验：去掉用于区分语言的红/黑字色
    _strip_color_in_tree(root, stats)

    out = ET.tostring(root, encoding="utf-8", xml_declaration=True, method="xml")
    return out, stats


@dataclass
class EpubProcessStats:
    files_total: int = 0
    files_changed: int = 0
    xhtml_changed: int = 0
    removed_translation_blocks: int = 0
    removed_ruby_rt: int = 0
    unwrapped_ruby: int = 0
    stripped_opacity: int = 0
    removed_by_class: int = 0
    removed_by_heuristic: int = 0
    stripped_css_opacity: int = 0
    removed_by_lang: int = 0
    stripped_color: int = 0


def _is_doc_path(name: str) -> bool:
    low = name.lower()
    return low.endswith(".xhtml") or low.endswith(".html") or low.endswith(".htm")


def _is_css_path(name: str) -> bool:
    return name.lower().endswith(".css")


def process_epub(
    in_path: Path,
    out_path: Path,
    *,
    remove_ruby: bool,
    aggressive: bool,
    dry_run: bool,
    overwrite: bool,
) -> EpubProcessStats:
    st = EpubProcessStats(files_total=1)

    if out_path.exists() and not overwrite:
        raise FileExistsError(f"输出文件已存在（未开启 --overwrite）：{out_path}")

    changed_any = False

    with zipfile.ZipFile(in_path, "r") as zin:
        entries = zin.infolist()

        # 预读 mimetype
        mimetype_bytes = None
        try:
            mimetype_bytes = zin.read("mimetype")
        except KeyError:
            mimetype_bytes = b"application/epub+zip"

        if dry_run:
            # dry-run 只统计，不写文件
            for info in entries:
                if info.filename == "mimetype":
                    continue
                if _is_doc_path(info.filename):
                    data = zin.read(info.filename)
                    new_data, xst = clean_xhtml_bytes(
                        data,
                        remove_ruby=remove_ruby,
                        aggressive=aggressive,
                    )
                    if new_data != data:
                        changed_any = True
                        st.xhtml_changed += 1
                    st.removed_translation_blocks += xst.removed_translation_blocks
                    st.removed_ruby_rt += xst.removed_ruby_rt
                    st.unwrapped_ruby += xst.unwrapped_ruby
                    st.stripped_opacity += xst.stripped_opacity
                    st.removed_by_class += xst.removed_by_class
                    st.removed_by_heuristic += xst.removed_by_heuristic
                    st.removed_by_lang += xst.removed_by_lang
                    st.stripped_color += xst.stripped_color

                if _is_css_path(info.filename):
                    data = zin.read(info.filename)
                    new_data, removed = clean_css_bytes(data)
                    if new_data != data:
                        changed_any = True
                        # css 改动也计入 xhtml_changed 不合适；这里不新增计数维度，走 files_changed 即可
                        st.stripped_css_opacity += removed

            if changed_any:
                st.files_changed = 1
            return st

        out_path.parent.mkdir(parents=True, exist_ok=True)

        # 写出新 epub
        with zipfile.ZipFile(out_path, "w") as zout:
            # 1) mimetype 必须第一项且不压缩
            zout.writestr(
                "mimetype",
                mimetype_bytes,
                compress_type=zipfile.ZIP_STORED,
            )

            # 2) 其余条目
            for info in entries:
                name = info.filename
                if name == "mimetype":
                    continue

                # 目录条目
                if name.endswith("/"):
                    # zipfile 对目录条目支持一般，但写个空条目即可
                    zout.writestr(name, b"", compress_type=zipfile.ZIP_DEFLATED)
                    continue

                data = zin.read(name)

                if _is_doc_path(name):
                    new_data, xst = clean_xhtml_bytes(
                        data,
                        remove_ruby=remove_ruby,
                        aggressive=aggressive,
                    )
                    if new_data != data:
                        changed_any = True
                        st.xhtml_changed += 1
                        data = new_data

                    st.removed_translation_blocks += xst.removed_translation_blocks
                    st.removed_ruby_rt += xst.removed_ruby_rt
                    st.unwrapped_ruby += xst.unwrapped_ruby
                    st.stripped_opacity += xst.stripped_opacity
                    st.removed_by_class += xst.removed_by_class
                    st.removed_by_heuristic += xst.removed_by_heuristic
                    st.removed_by_lang += xst.removed_by_lang
                    st.stripped_color += xst.stripped_color

                elif _is_css_path(name):
                    new_data, removed = clean_css_bytes(data)
                    if new_data != data:
                        changed_any = True
                        data = new_data
                        st.stripped_css_opacity += removed

                zout.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)

    if changed_any:
        st.files_changed = 1

    return st


def iter_epubs(root: Path, recursive: bool) -> Iterable[Path]:
    if root.is_file() and root.suffix.lower() == ".epub":
        yield root
        return

    if not root.is_dir():
        return

    if recursive:
        yield from root.rglob("*.epub")
    else:
        yield from root.glob("*.epub")


def build_out_path(in_path: Path, in_root: Path, out_root: Path, suffix: str) -> Path:
    try:
        rel = in_path.relative_to(in_root)
    except Exception:
        rel = in_path.name

    rel_path = Path(rel)
    # 保持相对目录结构
    stem = rel_path.stem
    if suffix:
        out_name = f"{stem}{suffix}{rel_path.suffix}"
    else:
        out_name = rel_path.name
    return out_root / rel_path.parent / out_name


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="一键批量还原 EPUB：删除中文译文，仅保留日文原文（可选去 ruby 注音）")
    parser.add_argument(
        "--in",
        dest="in_path",
        default=r"D:\Downloads",
        help=r"输入：EPUB 文件或目录（默认：D:\Downloads）",
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        default="",
        help="输出目录（默认：与输入目录相同）",
    )
    parser.add_argument("--recursive", action="store_true", help="递归扫描子目录（默认不递归）")
    parser.add_argument("--suffix", default=".jp", help="输出文件名后缀（默认 .jp；空字符串表示覆盖文件名）")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖已存在的输出文件")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写文件")
    parser.add_argument("--keep-ruby", action="store_true", help="不移除 ruby 注音（默认会移除）")
    parser.add_argument(
        "--aggressive",
        action="store_true",
        help="启用更激进的中文识别兜底规则（当 opacity/class 推断失败时更倾向删除疑似中文段落）",
    )

    args = parser.parse_args(argv)

    in_path = Path(args.in_path).expanduser().resolve()
    if not in_path.exists():
        print(f"输入不存在：{in_path}", file=sys.stderr)
        return 2

    if in_path.is_file() and in_path.suffix.lower() != ".epub":
        print("--in 指向文件时必须是 .epub", file=sys.stderr)
        return 2

    if args.out_path:
        out_root = Path(args.out_path).expanduser().resolve()
    else:
        # 按你的要求：默认输出与输入同目录（便于“同一文件夹内一键还原”）
        out_root = in_path if in_path.is_dir() else in_path.parent

    remove_ruby = not args.keep_ruby

    # 批处理
    all_files = list(iter_epubs(in_path, recursive=args.recursive))
    if not all_files:
        print("未找到 .epub 文件。")
        return 0

    total = EpubProcessStats(files_total=0)

    for f in all_files:
        out_file = build_out_path(
            f,
            in_root=(in_path if in_path.is_dir() else in_path.parent),
            out_root=out_root,
            suffix=args.suffix,
        )

        try:
            st = process_epub(
                f,
                out_file,
                remove_ruby=remove_ruby,
                aggressive=args.aggressive,
                dry_run=args.dry_run,
                overwrite=args.overwrite,
            )
        except Exception as e:
            print(f"[失败] {f} -> {out_file}\n  {e}", file=sys.stderr)
            continue

        total.files_total += 1
        total.files_changed += st.files_changed
        total.xhtml_changed += st.xhtml_changed
        total.removed_translation_blocks += st.removed_translation_blocks
        total.removed_ruby_rt += st.removed_ruby_rt
        total.unwrapped_ruby += st.unwrapped_ruby
        total.stripped_opacity += st.stripped_opacity
        total.removed_by_class += st.removed_by_class
        total.removed_by_heuristic += st.removed_by_heuristic
        total.stripped_css_opacity += st.stripped_css_opacity
        total.removed_by_lang += st.removed_by_lang
        total.stripped_color += st.stripped_color

        flag = "OK" if st.files_changed else "SKIP"
        if args.dry_run:
            print(
                f"[{flag}] {f.name} | xhtml_changed={st.xhtml_changed} | rm_trans={st.removed_translation_blocks} | rm_ruby_rt={st.removed_ruby_rt} | unwrap_ruby={st.unwrapped_ruby} | strip_opacity={st.stripped_opacity}")
        else:
            print(
                f"[{flag}] {f.name} -> {out_file.name} | xhtml_changed={st.xhtml_changed} | rm_trans={st.removed_translation_blocks} | rm_ruby_rt={st.removed_ruby_rt} | unwrap_ruby={st.unwrapped_ruby} | strip_opacity={st.stripped_opacity}")

    print(
        "\n汇总："
        f"\n  EPUB 总数: {total.files_total}"
        f"\n  产生改动: {total.files_changed}"
        f"\n  改动文档: {total.xhtml_changed}"
        f"\n  删除译文块(opacity规则): {total.removed_translation_blocks}"
        f"\n  删除rt/rp: {total.removed_ruby_rt}"
        f"\n  展开ruby: {total.unwrapped_ruby}"
        f"\n  去除opacity: {total.stripped_opacity}"
        f"\n  class规则删除: {total.removed_by_class}"
        f"\n  兜底规则删除: {total.removed_by_heuristic}"
        f"\n  CSS去除opacity: {total.stripped_css_opacity}"
        f"\n  lang=zh规则删除: {total.removed_by_lang}"
        f"\n  去除color样式: {total.stripped_color}"
    )

    if not args.dry_run:
        print(f"\n输出目录：{out_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
