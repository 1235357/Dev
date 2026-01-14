import os
import re
import copy
import shutil
import zipfile
import warnings
from enum import StrEnum
from typing import Generator

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning, NavigableString, Tag
from lxml import etree

from base.Base import Base
from base.BaseLanguage import BaseLanguage
from module.Cache.CacheItem import CacheItem
from module.Config import Config
from module.Localizer.Localizer import Localizer

# 忽略 BeautifulSoup 的 XML 解析警告
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

class EPUB(Base):
    """
    EPUB 文件处理器
    
    采用多策略并行竞争架构：
    1. Strategy.STANDARD - 原始标准方法（使用 <p> 等块级标签）
    2. Strategy.BR_SEPARATED - BR分隔方法（适用于 Calibre/Sigil 等编辑器输出）
    3. Strategy.EBOOKLIB - ebooklib 保底方法（最终兜底）
    
    读取时：并行运行所有策略，选择提取行数最多的结果
    写入时：根据读取时记录的结构类型，选择对应的写入策略
    """

    # 解析策略枚举
    class Strategy(StrEnum):
        STANDARD = "standard"           # 原始标准方法
        BR_SEPARATED = "br_separated"   # BR分隔方法
        EBOOKLIB = "ebooklib"           # ebooklib 保底方法
        MIXED = "mixed"                 # 混合方法

    # 显式引用以避免打包问题
    etree

    # EPUB 文件中读取的标签范围（块级标签）
    EPUB_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li", "td")

    # 内联标签（不作为独立文本单元，但需要保留其内容）
    INLINE_TAGS = ("span", "a", "em", "strong", "b", "i", "u", "ruby", "rt", "rp", "sub", "sup", "small", "mark", "code")

    # 换行标签
    BR_TAGS = ("br",)

    # 需要跳过的元素（导航、目录等 Calibre 生成的结构性元素）
    SKIP_CLASSES = (
        "calibreMeta", "calibreMetaTitle", "calibreMetaAuthor",
        "calibreToc", "calibreEbNav", "calibreEbNavTop",
        "calibreAPrev", "calibreANext", "calibreAHome"
    )

    # SVG/MathML 驼峰命名属性映射表（小写 → 正确大小写）
    # 用于在 html.parser fallback 时修复被小写化的属性
    CAMEL_CASE_ATTRS: dict[str, str] = {
        # SVG viewBox 相关
        "viewbox": "viewBox",
        "preserveaspectratio": "preserveAspectRatio",
        # SVG 渐变/图案
        "gradientunits": "gradientUnits",
        "gradienttransform": "gradientTransform",
        "patternunits": "patternUnits",
        "patterncontentunits": "patternContentUnits",
        "patterntransform": "patternTransform",
        "spreadmethod": "spreadMethod",
        # SVG 滤镜
        "filterunits": "filterUnits",
        "primitiveunits": "primitiveUnits",
        "stddeviation": "stdDeviation",
        "basefrequency": "baseFrequency",
        "numoctaves": "numOctaves",
        "stitchtiles": "stitchTiles",
        "surfacescale": "surfaceScale",
        "diffuseconstant": "diffuseConstant",
        "specularconstant": "specularConstant",
        "specularexponent": "specularExponent",
        "limitingconeangle": "limitingConeAngle",
        "kernelmatrix": "kernelMatrix",
        "kernelunitlength": "kernelUnitLength",
        "targetx": "targetX",
        "targety": "targetY",
        "edgemode": "edgeMode",
        # SVG 裁剪/蒙版
        "clippathunits": "clipPathUnits",
        "maskunits": "maskUnits",
        "maskcontentunits": "maskContentUnits",
        # SVG 文本
        "textlength": "textLength",
        "lengthadjust": "lengthAdjust",
        "startoffset": "startOffset",
        "glyphref": "glyphRef",
        # SVG 动画
        "attributename": "attributeName",
        "attributetype": "attributeType",
        "repeatcount": "repeatCount",
        "repeatdur": "repeatDur",
        "keytimes": "keyTimes",
        "keysplines": "keySplines",
        "keypoints": "keyPoints",
        "calcmode": "calcMode",
        # SVG 其他
        "baseprofile": "baseProfile",
        "contentscripttype": "contentScriptType",
        "contentstyletype": "contentStyleType",
        "markerwidth": "markerWidth",
        "markerheight": "markerHeight",
        "markerunits": "markerUnits",
        "refx": "refX",
        "refy": "refY",
        "tablevalues": "tableValues",
        "xchannelselector": "xChannelSelector",
        "ychannelselector": "yChannelSelector",
        "zoomandpan": "zoomAndPan",
        # MathML
        "mathvariant": "mathvariant",  # MathML 本身是小写
        "scriptlevel": "scriptlevel",
        "displaystyle": "displaystyle",
        "columnalign": "columnalign",
        "rowalign": "rowalign",
        "columnspan": "columnspan",
        "rowspan": "rowspan",
    }

    # 驼峰命名的SVG元素（标签名）
    CAMEL_CASE_TAGS: dict[str, str] = {
        "lineargradient": "linearGradient",
        "radialgradient": "radialGradient",
        "clippath": "clipPath",
        "textpath": "textPath",
        "foreignobject": "foreignObject",
        "fegaussianblur": "feGaussianBlur",
        "fecolormatrix": "feColorMatrix",
        "fecomposite": "feComposite",
        "femorphology": "feMorphology",
        "feblend": "feBlend",
        "feflood": "feFlood",
        "feimage": "feImage",
        "femerge": "feMerge",
        "femergenode": "feMergeNode",
        "feoffset": "feOffset",
        "fetile": "feTile",
        "feturbulence": "feTurbulence",
        "feconvolvematrix": "feConvolveMatrix",
        "fediffuselighting": "feDiffuseLighting",
        "fedisplacementmap": "feDisplacementMap",
        "fedistantlight": "feDistantLight",
        "fepointlight": "fePointLight",
        "fespotlight": "feSpotLight",
        "fespecularlighting": "feSpecularLighting",
        "animatetransform": "animateTransform",
        "animatemotion": "animateMotion",
        "animatecolor": "animateColor",
        "glyphref": "glyphRef",
        "altglyph": "altGlyph",
        "altglyphdef": "altGlyphDef",
        "altglyphitem": "altGlyphItem",
    }

    # 命名空间声明（用于自动补全）
    NAMESPACE_DECLARATIONS: dict[str, str] = {
        "xlink:": 'xmlns:xlink="http://www.w3.org/1999/xlink"',
        "epub:": 'xmlns:epub="http://www.idpf.org/2007/ops"',
        "xml:": 'xmlns:xml="http://www.w3.org/XML/1998/namespace"',
    }

    # 类变量：记录每个文件使用的解析策略
    _file_strategies: dict[str, "EPUB.Strategy"] = {}

    def __init__(self, config: Config) -> None:
        super().__init__()

        # 初始化
        self.config = config
        self.input_path: str = config.input_folder
        self.output_path: str = config.output_folder
        self.source_language: BaseLanguage.Enum = config.source_language
        self.target_language: BaseLanguage.Enum = config.target_language

    # 在扩展名前插入文本
    def insert_target(self, path: str) -> str:
        root, ext = os.path.splitext(path)
        return f"{root}.{self.target_language.lower()}{ext}"

    # 在扩展名前插入文本
    def insert_source_target(self, path: str) -> str:
        root, ext = os.path.splitext(path)
        return f"{root}.{self.source_language.lower()}.{self.target_language.lower()}{ext}"

    @classmethod
    def _auto_fix_namespaces(cls, content: str) -> str:
        """
        自动补全缺失的命名空间声明。
        某些EPUB文件可能使用 xlink:href 但忘记声明 xmlns:xlink，
        这会导致 lxml-xml 解析时丢弃 xlink 前缀。
        """
        for prefix, declaration in cls.NAMESPACE_DECLARATIONS.items():
            # 检测是否使用了该前缀但没有声明
            if prefix in content and declaration.split("=")[0] not in content:
                # 在 <html 或根元素中添加声明
                # 尝试在 <html 标签中添加
                if "<html" in content:
                    content = re.sub(
                        r"(<html\s[^>]*)(>)",
                        rf"\1 {declaration}\2",
                        content,
                        count=1
                    )
                # 如果没有 <html，尝试在第一个元素中添加
                elif re.search(r"<\w+\s", content):
                    content = re.sub(
                        r"(<\w+\s[^>]*)(>)",
                        rf"\1 {declaration}\2",
                        content,
                        count=1
                    )
        return content

    @classmethod
    def _fix_camel_case_attrs(cls, content: str) -> str:
        """
        修复被 html.parser 小写化的驼峰属性名。
        将 viewbox="..." 修复为 viewBox="..."
        """
        for lower, correct in cls.CAMEL_CASE_ATTRS.items():
            if lower != correct.lower():
                continue  # 跳过本身就是小写的属性
            # 使用正则替换属性名（确保是属性而非值的一部分）
            content = re.sub(
                rf'\b{lower}=',
                f'{correct}=',
                content,
                flags=re.IGNORECASE
            )
        return content

    @classmethod
    def _fix_camel_case_tags(cls, content: str) -> str:
        """
        修复被 html.parser 小写化的驼峰标签名。
        将 <lineargradient> 修复为 <linearGradient>
        """
        for lower, correct in cls.CAMEL_CASE_TAGS.items():
            # 修复开始标签
            content = re.sub(
                rf'<{lower}(\s|>|/>)',
                rf'<{correct}\1',
                content,
                flags=re.IGNORECASE
            )
            # 修复结束标签
            content = re.sub(
                rf'</{lower}>',
                rf'</{correct}>',
                content,
                flags=re.IGNORECASE
            )
        return content

    @classmethod
    def _parse_xml(cls, content: str) -> BeautifulSoup:
        """
        智能解析 XML/XHTML 内容。
        
        策略：
        1. 首先使用 lxml-xml（XML 模式），保持属性大小写
        2. 若解析失败，fallback 到 html.parser，然后修复属性大小写
        
        这是"一劳永逸"的解决方案：
        - lxml-xml 保持 SVG/MathML 属性的正确大小写
        - 命名空间自动补全确保 xlink:href 等属性不丢失前缀
        - fallback 机制处理格式错误的文件
        - 属性修复表处理 html.parser 的输出
        """
        # 预处理：自动补全缺失的命名空间声明
        content = cls._auto_fix_namespaces(content)
        
        try:
            # 主解析器：lxml-xml (XML 模式)
            # 优势：保持所有属性的原始大小写
            return BeautifulSoup(content, "lxml-xml")
        except Exception:
            # Fallback：html.parser
            # 注意：html.parser 会将所有属性名小写化
            soup = BeautifulSoup(content, "html.parser")
            return soup

    @classmethod
    def _soup_to_string(cls, soup: BeautifulSoup, used_fallback: bool = False) -> str:
        """
        将 BeautifulSoup 对象转换为字符串。
        如果使用了 html.parser fallback，需要修复驼峰属性。
        """
        result = str(soup)
        
        # 检测是否使用了 html.parser（通过检查是否有小写化的属性）
        # 如果有 viewbox= 但没有 viewBox=，说明使用了 html.parser
        if "viewbox=" in result.lower() and "viewBox=" not in result:
            result = cls._fix_camel_case_attrs(result)
            result = cls._fix_camel_case_tags(result)
        
        return result

    @classmethod
    def _should_skip_element(cls, element: Tag) -> bool:
        """
        判断元素是否应该被跳过（导航、目录等结构性元素）
        """
        if not hasattr(element, 'get'):
            return False
        
        classes = element.get("class", [])
        if isinstance(classes, str):
            classes = classes.split()
        
        for skip_class in cls.SKIP_CLASSES:
            if skip_class in classes:
                return True
        
        # 检查父元素
        parent = element.parent
        while parent:
            if hasattr(parent, 'get'):
                parent_classes = parent.get("class", [])
                if isinstance(parent_classes, str):
                    parent_classes = parent_classes.split()
                for skip_class in cls.SKIP_CLASSES:
                    if skip_class in parent_classes:
                        return True
            parent = parent.parent
        
        return False

    @classmethod
    def _extract_text_with_ruby(cls, element) -> str:
        """
        从元素中提取文本，正确处理 ruby 标签（保留主文本，忽略 rt/rp）
        """
        if isinstance(element, NavigableString):
            return str(element)
        
        if not hasattr(element, 'name'):
            return ""
        
        # rt 和 rp 是 ruby 的注音部分，不应包含在主文本中
        if element.name in ('rt', 'rp'):
            return ""
        
        text_parts = []
        for child in element.children:
            text_parts.append(cls._extract_text_with_ruby(child))
        
        return "".join(text_parts)

    @classmethod
    def _collect_line_elements(cls, container) -> Generator[tuple[str, list], None, None]:
        """
        从容器中收集用 <br> 分隔的文本行。
        返回 (文本内容, [相关DOM节点列表]) 的生成器。
        
        这个方法处理类似这样的结构：
        ```
        文本1<br/>
        文本2<ruby>注音<rt>读音</rt></ruby>文本3<br/>
        ```
        """
        current_line_text = []
        current_line_nodes = []
        
        for child in container.children:
            if isinstance(child, NavigableString):
                text = str(child)
                if text.strip():  # 有实际文本内容
                    current_line_text.append(text)
                    current_line_nodes.append(child)
            elif hasattr(child, 'name'):
                if child.name in cls.BR_TAGS:
                    # 遇到 <br>，产出当前行
                    line_text = "".join(current_line_text).strip()
                    if line_text:
                        yield (line_text, current_line_nodes.copy())
                    current_line_text = []
                    current_line_nodes = []
                elif child.name in cls.INLINE_TAGS:
                    # 内联标签，提取其文本
                    text = cls._extract_text_with_ruby(child)
                    if text:
                        current_line_text.append(text)
                        current_line_nodes.append(child)
                elif child.name == 'hr':
                    # 水平线，产出当前行并跳过
                    line_text = "".join(current_line_text).strip()
                    if line_text:
                        yield (line_text, current_line_nodes.copy())
                    current_line_text = []
                    current_line_nodes = []
                else:
                    # 其他块级标签，先产出当前行，然后递归处理
                    line_text = "".join(current_line_text).strip()
                    if line_text:
                        yield (line_text, current_line_nodes.copy())
                    current_line_text = []
                    current_line_nodes = []
                    
                    # 递归处理子元素
                    for item in cls._collect_line_elements(child):
                        yield item
        
        # 处理最后一行
        line_text = "".join(current_line_text).strip()
        if line_text:
            yield (line_text, current_line_nodes.copy())

    # ==================== 策略 1：标准方法（原始 Dev 项目方法）====================
    
    @classmethod
    def _extract_items_standard(cls, bs: BeautifulSoup, path: str, rel_path: str, start_row: int) -> list[CacheItem]:
        """
        策略 1：使用标准方法提取文本（适用于使用 <p> 等块级标签的 EPUB）
        
        这是原始 Dev 项目使用的基础解析方法。
        """
        items = []
        for dom in bs.find_all(cls.EPUB_TAGS):
            # 跳过空标签或嵌套标签
            if dom.get_text().strip() == "" or dom.find(cls.EPUB_TAGS) != None:
                continue
            
            # 跳过导航元素
            if cls._should_skip_element(dom):
                continue
            
            items.append(CacheItem.from_dict({
                "src": dom.get_text(),
                "dst": dom.get_text(),
                "tag": path,
                "row": start_row + len(items),
                "file_type": CacheItem.FileType.EPUB,
                "file_path": rel_path,
                "extra_field": {"strategy": cls.Strategy.STANDARD},
            }))
        return items

    # ==================== 策略 2：BR分隔方法（Calibre/Sigil 兼容）====================
    
    @classmethod
    def _extract_items_br_separated(cls, bs: BeautifulSoup, path: str, rel_path: str, start_row: int) -> list[CacheItem]:
        """
        策略 2：从 BR 分隔的结构中提取文本（适用于 Calibre/Sigil 转换的 EPUB）
        
        处理文本直接放在 <body> 中，用 <br> 分隔的结构。
        """
        items = []
        body = bs.find('body')
        if not body:
            return items
        
        for line_text, line_nodes in cls._collect_line_elements(body):
            # 跳过空行
            if not line_text.strip():
                continue
            
            # 检查是否在应跳过的元素内
            skip = False
            for node in line_nodes:
                if hasattr(node, 'parent') and cls._should_skip_element(node.parent):
                    skip = True
                    break
            if skip:
                continue
            
            items.append(CacheItem.from_dict({
                "src": line_text,
                "dst": line_text,
                "tag": path,
                "row": start_row + len(items),
                "file_type": CacheItem.FileType.EPUB,
                "file_path": rel_path,
                "extra_field": {"strategy": cls.Strategy.BR_SEPARATED},
            }))
        
        return items

    # ==================== 策略 3：ebooklib 保底方法 ====================
    
    @classmethod
    def _extract_items_ebooklib(cls, abs_path: str, rel_path: str, start_row: int) -> list[CacheItem]:
        """
        策略 3：使用 ebooklib 库作为最终保底解析方法
        
        当其他方法都失效或提取结果不理想时，使用 ebooklib 进行解析。
        ebooklib 是成熟的 EPUB 处理库，兼容性最好。
        """
        items = []
        
        try:
            # 延迟导入 ebooklib，避免未安装时报错
            import ebooklib
            from ebooklib import epub
            
            # 读取 EPUB 文件
            book = epub.read_epub(abs_path, options={"ignore_ncx": True})
            
            # 遍历所有文档类型的项目
            for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
                # 获取 HTML 内容
                content = item.get_content()
                if isinstance(content, bytes):
                    content = content.decode("utf-8-sig", errors="ignore")
                
                # 获取 body 内容
                try:
                    body_content = item.get_body_content()
                    if isinstance(body_content, bytes):
                        body_content = body_content.decode("utf-8-sig", errors="ignore")
                except Exception:
                    body_content = content
                
                # 使用 BeautifulSoup 解析
                bs = cls._parse_xml(body_content if body_content else content)
                
                # 获取文件路径作为 tag
                file_path = item.get_name() if hasattr(item, 'get_name') else str(item.id)
                
                # 提取文本 - 使用标准块级标签方法
                for dom in bs.find_all(cls.EPUB_TAGS):
                    text = dom.get_text().strip()
                    if not text:
                        continue
                    
                    # 跳过嵌套标签
                    if dom.find(cls.EPUB_TAGS) is not None:
                        continue
                    
                    # 跳过导航元素
                    if cls._should_skip_element(dom):
                        continue
                    
                    items.append(CacheItem.from_dict({
                        "src": text,
                        "dst": text,
                        "tag": file_path,
                        "row": start_row + len(items),
                        "file_type": CacheItem.FileType.EPUB,
                        "file_path": rel_path,
                        "extra_field": {"strategy": cls.Strategy.EBOOKLIB},
                    }))
                
                # 如果标准方法没有提取到内容，尝试提取所有文本
                if len(items) == 0:
                    # 尝试提取所有可见文本
                    all_text = bs.get_text(separator="\n", strip=True)
                    for line in all_text.split("\n"):
                        line = line.strip()
                        if line and len(line) > 1:  # 过滤单字符行
                            items.append(CacheItem.from_dict({
                                "src": line,
                                "dst": line,
                                "tag": file_path,
                                "row": start_row + len(items),
                                "file_type": CacheItem.FileType.EPUB,
                                "file_path": rel_path,
                                "extra_field": {"strategy": cls.Strategy.EBOOKLIB},
                            }))
            
            # 处理 NCX 导航文件
            for item in book.get_items_of_type(ebooklib.ITEM_NAVIGATION):
                content = item.get_content()
                if isinstance(content, bytes):
                    content = content.decode("utf-8-sig", errors="ignore")
                
                bs = cls._parse_xml(content)
                for dom in bs.find_all("text"):
                    text = dom.get_text().strip()
                    if not text:
                        continue
                    
                    file_path = item.get_name() if hasattr(item, 'get_name') else "nav"
                    items.append(CacheItem.from_dict({
                        "src": text,
                        "dst": text,
                        "tag": file_path,
                        "row": start_row + len(items),
                        "file_type": CacheItem.FileType.EPUB,
                        "file_path": rel_path,
                        "extra_field": {"strategy": cls.Strategy.EBOOKLIB},
                    }))
        
        except ImportError:
            # ebooklib 未安装，返回空列表
            pass
        except Exception as e:
            # 其他错误，记录但不中断
            pass
        
        return items

    # ==================== 策略选择器：并行竞争 ====================
    
    @classmethod
    def _extract_items_from_html_competitive(cls, content: str, path: str, rel_path: str, start_row: int) -> tuple[list[CacheItem], "EPUB.Strategy"]:
        """
        对单个 HTML 文件并行运行多个策略，选择提取行数最多的结果
        
        返回：(items, 使用的策略)
        """
        bs = cls._parse_xml(content)
        
        # 并行运行所有策略
        results: dict[EPUB.Strategy, list[CacheItem]] = {}
        
        # 策略 1：标准方法
        results[cls.Strategy.STANDARD] = cls._extract_items_standard(bs, path, rel_path, start_row)
        
        # 策略 2：BR分隔方法
        results[cls.Strategy.BR_SEPARATED] = cls._extract_items_br_separated(bs, path, rel_path, start_row)
        
        # 选择提取行数最多的策略
        best_strategy = cls.Strategy.STANDARD
        best_count = 0
        
        for strategy, items in results.items():
            if len(items) > best_count:
                best_count = len(items)
                best_strategy = strategy
        
        return results[best_strategy], best_strategy

    @classmethod
    def _extract_items_from_epub_competitive(cls, abs_path: str, rel_path: str) -> tuple[list[CacheItem], "EPUB.Strategy"]:
        """
        对整个 EPUB 文件并行运行多个策略，选择提取行数最多的结果
        
        这是最高级别的竞争选择器。
        
        返回：(items, 使用的主要策略)
        """
        results: dict[EPUB.Strategy, list[CacheItem]] = {
            cls.Strategy.STANDARD: [],
            cls.Strategy.BR_SEPARATED: [],
            cls.Strategy.EBOOKLIB: [],
        }
        
        # ===== 策略 1 & 2：使用 zipfile 手动解析 =====
        try:
            with zipfile.ZipFile(abs_path, "r") as zip_reader:
                for path in zip_reader.namelist():
                    if path.lower().endswith((".htm", ".html", ".xhtml")):
                        with zip_reader.open(path) as reader:
                            content = reader.read().decode("utf-8-sig")
                            bs = cls._parse_xml(content)
                            
                            # 策略 1：标准方法
                            standard_items = cls._extract_items_standard(
                                bs, path, rel_path, len(results[cls.Strategy.STANDARD])
                            )
                            results[cls.Strategy.STANDARD].extend(standard_items)
                            
                            # 策略 2：BR分隔方法
                            br_items = cls._extract_items_br_separated(
                                bs, path, rel_path, len(results[cls.Strategy.BR_SEPARATED])
                            )
                            results[cls.Strategy.BR_SEPARATED].extend(br_items)
                    
                    elif path.lower().endswith(".ncx"):
                        with zip_reader.open(path) as reader:
                            bs = cls._parse_xml(reader.read().decode("utf-8-sig"))
                            for dom in bs.find_all("text"):
                                text = dom.get_text().strip()
                                if not text:
                                    continue
                                
                                for strategy in [cls.Strategy.STANDARD, cls.Strategy.BR_SEPARATED]:
                                    results[strategy].append(CacheItem.from_dict({
                                        "src": text,
                                        "dst": text,
                                        "tag": path,
                                        "row": len(results[strategy]),
                                        "file_type": CacheItem.FileType.EPUB,
                                        "file_path": rel_path,
                                        "extra_field": {"strategy": strategy},
                                    }))
        except Exception:
            pass
        
        # ===== 策略 3：ebooklib 保底 =====
        results[cls.Strategy.EBOOKLIB] = cls._extract_items_ebooklib(abs_path, rel_path, 0)
        
        # ===== 选择最佳策略 =====
        best_strategy = cls.Strategy.STANDARD
        best_count = 0
        
        for strategy, items in results.items():
            count = len(items)
            if count > best_count:
                best_count = count
                best_strategy = strategy
        
        # 记录选择的策略
        cls._file_strategies[rel_path] = best_strategy
        
        return results[best_strategy], best_strategy

    # ==================== 读取入口 ====================
    
    def read_from_path(self, abs_paths: list[str]) -> list[CacheItem]:
        """
        从 EPUB 文件读取内容
        
        采用多策略并行竞争：同时运行标准方法、BR分隔方法、ebooklib保底方法，
        选择提取行数最多的结果。
        """
        items: list[CacheItem] = []
        
        for abs_path in abs_paths:
            # 获取相对路径
            rel_path = os.path.relpath(abs_path, self.input_path)
            
            # 将原始文件复制一份
            os.makedirs(os.path.dirname(f"{self.output_path}/cache/temp/{rel_path}"), exist_ok=True)
            shutil.copy(abs_path, f"{self.output_path}/cache/temp/{rel_path}")
            
            # 使用竞争选择器提取内容
            file_items, strategy = EPUB._extract_items_from_epub_competitive(abs_path, rel_path)
            
            # 重新编号
            for i, item in enumerate(file_items):
                item_dict = item.asdict()
                item_dict["row"] = len(items) + i
                items.append(CacheItem.from_dict(item_dict))
            
            # 记录使用的策略
            self.info(f"[EPUB] {os.path.basename(abs_path)}: 策略={strategy}, 提取={len(file_items)}行")
        
        return items

    # ==================== 写入逻辑 ====================

    def write_to_path(self, items: list[CacheItem]) -> None:
        """
        将翻译后的内容写入 EPUB 文件
        
        根据读取时记录的策略类型，选择对应的写入方法。
        
        注意：繁简转换已在 FileManager.write_to_path 中统一处理，
        此处不再重复转换。
        """

        def process_opf(zip_reader: zipfile.ZipFile, path: str) -> None:
            with zip_reader.open(path) as reader:
                zip_writer.writestr(
                    path,
                    reader.read().decode("utf-8-sig").replace("page-progression-direction=\"rtl\"", ""),
                )

        def process_css(zip_reader: zipfile.ZipFile, path: str) -> None:
            with zip_reader.open(path) as reader:
                zip_writer.writestr(
                    path,
                    re.sub(r"[^;\s]*writing-mode\s*:\s*vertical-rl;*", "", reader.read().decode("utf-8-sig")),
                )

        def process_ncx(zip_reader: zipfile.ZipFile, path: str, items: list[CacheItem]) -> None:
            with zip_reader.open(path) as reader:
                target = [item for item in items if item.get_tag() == path]
                # 使用智能解析方法
                bs = EPUB._parse_xml(reader.read().decode("utf-8-sig"))
                for dom in bs.find_all("text"):
                    # 跳过空标签
                    if dom.get_text().strip() == "":
                        continue

                    # 处理不同情况
                    if not target:
                        break
                    item = target.pop(0)
                    dom_a = dom.find("a")
                    if dom_a != None:
                        dom_a.string = item.get_dst()
                    else:
                        dom.string = item.get_dst()

                # 将修改后的内容写回去（使用智能输出方法）
                zip_writer.writestr(path, EPUB._soup_to_string(bs))

        def process_html_br_separated(bs: BeautifulSoup, path: str, target: list[CacheItem], bilingual: bool) -> None:
            """
            策略 2 的写入方法：处理 BR 分隔结构的 HTML 文件
            """
            body = bs.find('body')
            if not body:
                return
            
            # 收集所有文本行及其对应的节点
            lines_data = list(EPUB._collect_line_elements(body))
            
            # 创建一个映射：原文 -> 译文
            translation_map = {}
            for item in target:
                translation_map[item.get_src()] = item.get_dst()
            
            # 遍历每一行，进行替换
            for line_text, line_nodes in lines_data:
                if not line_text.strip():
                    continue
                
                if line_text not in translation_map:
                    continue
                
                dst_text = translation_map[line_text]
                
                # 检查是否需要跳过（导航元素）
                skip = False
                for node in line_nodes:
                    if hasattr(node, 'parent') and EPUB._should_skip_element(node.parent):
                        skip = True
                        break
                if skip:
                    continue
                
                # 处理双语输出
                if bilingual and (self.config.deduplication_in_bilingual != True or line_text != dst_text):
                    # 在第一个节点之前插入原文（带透明度）
                    if line_nodes:
                        first_node = line_nodes[0]
                        if hasattr(first_node, 'parent'):
                            # 创建带透明度的原文 span
                            new_span = bs.new_tag('span')
                            new_span['style'] = 'opacity:0.50;'
                            new_span.string = line_text
                            first_node.insert_before(new_span)
                            first_node.insert_before(bs.new_tag('br'))
                
                # 执行替换
                if len(line_nodes) == 1:
                    # 只有一个节点，直接替换
                    node = line_nodes[0]
                    if isinstance(node, NavigableString):
                        node.replace_with(dst_text)
                    elif hasattr(node, 'string') and node.string:
                        node.string = dst_text
                    else:
                        # 复杂节点（如包含 ruby），清空并替换
                        node.clear()
                        node.append(dst_text)
                else:
                    # 多个节点组成一行，需要更复杂的处理
                    # 策略：用第一个节点替换为完整译文，移除其他节点
                    if line_nodes:
                        first_node = line_nodes[0]
                        
                        # 移除后续节点（但保留 <br>）
                        for node in line_nodes[1:]:
                            if hasattr(node, 'decompose'):
                                node.decompose()
                            elif isinstance(node, NavigableString):
                                node.replace_with('')
                        
                        # 替换第一个节点的内容
                        if isinstance(first_node, NavigableString):
                            first_node.replace_with(dst_text)
                        elif hasattr(first_node, 'string'):
                            first_node.clear()
                            first_node.append(dst_text)

        def process_html_standard(bs: BeautifulSoup, path: str, target: list[CacheItem], bilingual: bool) -> None:
            """
            策略 1 的写入方法：处理标准结构的 HTML 文件
            """
            # 判断是否是导航页
            is_nav_page = bs.find("nav", attrs={"epub:type": "toc"}) != None

            for dom in bs.find_all(EPUB.EPUB_TAGS):
                # 跳过空标签或嵌套标签
                if dom.get_text().strip() == "" or dom.find(EPUB.EPUB_TAGS) != None:
                    continue
                
                # 跳过导航元素
                if EPUB._should_skip_element(dom):
                    continue

                # 取数据
                if not target:
                    break
                item = target.pop(0)

                # 输出双语
                if bilingual == True:
                    if (
                        self.config.deduplication_in_bilingual != True
                        or (self.config.deduplication_in_bilingual == True and item.get_src() != item.get_dst())
                    ):
                        line_src = copy.copy(dom)
                        line_src["style"] = line_src.get("style", "").removesuffix(";") + "opacity:0.50;"
                        dom.insert_before(line_src)
                        dom.insert_before("\n")

                # 根据不同类型的页面处理不同情况
                if item.get_src() in str(dom):
                    # 使用智能解析方法替换文本
                    dom.replace_with(EPUB._parse_xml(str(dom).replace(item.get_src(), item.get_dst())))
                elif is_nav_page == False:
                    dom.string = item.get_dst()
                else:
                    pass

        def process_html_ebooklib(bs: BeautifulSoup, path: str, target: list[CacheItem], bilingual: bool) -> None:
            """
            策略 3 的写入方法：使用标准方法写入（ebooklib 读取时使用的是标准结构）
            """
            # ebooklib 读取的内容使用标准结构，所以写入也使用标准方法
            process_html_standard(bs, path, target, bilingual)

        def detect_strategy_for_file(items: list[CacheItem], rel_path: str) -> "EPUB.Strategy":
            """
            检测该文件应该使用的写入策略
            
            优先级：
            1. 从 items 的 extra 中获取策略信息
            2. 从类变量 _file_strategies 中获取
            3. 默认使用 STANDARD
            """
            # 尝试从 items 获取
            for item in items:
                extra = item.get_extra_field() or {}
                if isinstance(extra, dict) and "strategy" in extra:
                    return EPUB.Strategy(extra["strategy"])
            
            # 从类变量获取
            if rel_path in EPUB._file_strategies:
                return EPUB._file_strategies[rel_path]
            
            return EPUB.Strategy.STANDARD

        def process_html(zip_reader: zipfile.ZipFile, path: str, items: list[CacheItem], bilingual: bool, strategy: "EPUB.Strategy") -> None:
            """
            根据策略选择对应的 HTML 处理方法
            
            注意：EPUB 重建只做一一映射替换，不改变原有格式排版。
            """
            with zip_reader.open(path) as reader:
                content = reader.read().decode("utf-8-sig")
                target = [item for item in items if item.get_tag() == path]
                bs = EPUB._parse_xml(content)

                # 移除竖排样式（仅移除 writing-mode: vertical-rl，不添加新样式）
                for dom in bs.find_all():
                    if hasattr(dom, 'get'):
                        class_content: str = re.sub(r"[hv]rtl|[hv]ltr", "", " ".join(dom.get("class", "") or []))
                        if class_content.strip() == "":
                            dom.attrs.pop("class", None)
                        else:
                            dom["class"] = class_content.split()
                        style_content: str = re.sub(r"[^;\s]*writing-mode\s*:\s*vertical-rl;*", "", dom.get("style", "") or "")
                        if style_content.strip() == "":
                            dom.attrs.pop("style", None)
                        else:
                            dom["style"] = style_content

                # 根据策略选择处理方法
                if strategy == EPUB.Strategy.BR_SEPARATED:
                    process_html_br_separated(bs, path, target, bilingual)
                elif strategy == EPUB.Strategy.EBOOKLIB:
                    process_html_ebooklib(bs, path, target, bilingual)
                else:  # STANDARD 或 MIXED
                    process_html_standard(bs, path, target, bilingual)

                # 将修改后的内容写回去（使用智能输出方法）
                zip_writer.writestr(path, EPUB._soup_to_string(bs))

        # 筛选
        target = [
            item for item in items
            if item.get_file_type() == CacheItem.FileType.EPUB
        ]

        # 按文件路径分组
        group: dict[str, list[str]] = {}
        for item in target:
            group.setdefault(item.get_file_path(), []).append(item)

        # 分别处理每个文件
        for rel_path, items in group.items():
            # 按行号排序
            items = sorted(items, key=lambda x: x.get_row())
            
            # 检测策略
            strategy = detect_strategy_for_file(items, rel_path)

            # 数据处理
            abs_path = f"{self.output_path}/{rel_path}"
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with zipfile.ZipFile(self.insert_target(abs_path), "w") as zip_writer:
                with zipfile.ZipFile(f"{self.output_path}/cache/temp/{rel_path}", "r") as zip_reader:
                    for path in zip_reader.namelist():
                        if path.lower().endswith(".css"):
                            process_css(zip_reader, path)
                        elif path.lower().endswith(".opf"):
                            process_opf(zip_reader, path)
                        elif path.lower().endswith(".ncx"):
                            process_ncx(zip_reader, path, items)
                        elif path.lower().endswith((".htm", ".html", ".xhtml")):
                            process_html(zip_reader, path, items, False, strategy)
                        else:
                            zip_writer.writestr(path, zip_reader.read(path))

        # 分别处理每个文件（双语）
        for rel_path, items in group.items():
            # 按行号排序
            items = sorted(items, key=lambda x: x.get_row())
            
            # 检测策略
            strategy = detect_strategy_for_file(items, rel_path)

            # 数据处理
            abs_path = f"{self.output_path}/{Localizer.get().path_bilingual}/{rel_path}"
            os.makedirs(os.path.dirname(abs_path), exist_ok=True)
            with zipfile.ZipFile(self.insert_source_target(abs_path), "w") as zip_writer:
                with zipfile.ZipFile(f"{self.output_path}/cache/temp/{rel_path}", "r") as zip_reader:
                    for path in zip_reader.namelist():
                        if path.lower().endswith(".css"):
                            process_css(zip_reader, path)
                        elif path.lower().endswith(".opf"):
                            process_opf(zip_reader, path)
                        elif path.lower().endswith(".ncx"):
                            process_ncx(zip_reader, path, items)
                        elif path.lower().endswith((".htm", ".html", ".xhtml")):
                            process_html(zip_reader, path, items, True, strategy)
                        else:
                            zip_writer.writestr(path, zip_reader.read(path))
