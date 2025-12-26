import os
import re
import copy
import shutil
import zipfile
import warnings

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from lxml import etree

from base.Base import Base
from base.BaseLanguage import BaseLanguage
from module.Cache.CacheItem import CacheItem
from module.Config import Config
from module.Localizer.Localizer import Localizer

# 忽略 BeautifulSoup 的 XML 解析警告
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

class EPUB(Base):

    # 显式引用以避免打包问题
    etree

    # EPUB 文件中读取的标签范围
    EPUB_TAGS = ("p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li", "td")

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

    # 读取
    def read_from_path(self, abs_paths: list[str]) -> list[CacheItem]:
        items:list[CacheItem] = []
        for abs_path in abs_paths:
            # 获取相对路径
            rel_path = os.path.relpath(abs_path, self.input_path)

            # 将原始文件复制一份
            os.makedirs(os.path.dirname(f"{self.output_path}/cache/temp/{rel_path}"), exist_ok = True)
            shutil.copy(abs_path, f"{self.output_path}/cache/temp/{rel_path}")

            # 数据处理
            with zipfile.ZipFile(abs_path, "r") as zip_reader:
                for path in zip_reader.namelist():
                    if path.lower().endswith((".htm", ".html", ".xhtml")):
                        with zip_reader.open(path) as reader:
                            # 使用智能解析方法（lxml-xml + fallback + 属性修复）
                            bs = EPUB._parse_xml(reader.read().decode("utf-8-sig"))
                            for dom in bs.find_all(EPUB.EPUB_TAGS):
                                # 跳过空标签或嵌套标签
                                if dom.get_text().strip() == "" or dom.find(EPUB.EPUB_TAGS) != None:
                                    continue

                                # 添加数据
                                items.append(CacheItem.from_dict({
                                    "src": dom.get_text(),
                                    "dst": dom.get_text(),
                                    "tag": path,
                                    "row": len(items),
                                    "file_type": CacheItem.FileType.EPUB,
                                    "file_path": rel_path,
                                }))
                    elif path.lower().endswith(".ncx"):
                        with zip_reader.open(path) as reader:
                            # NCX 文件也使用智能解析方法
                            bs = EPUB._parse_xml(reader.read().decode("utf-8-sig"))
                            for dom in bs.find_all("text"):
                                # 跳过空标签
                                if dom.get_text().strip() == "":
                                    continue

                                items.append(CacheItem.from_dict({
                                    "src": dom.get_text(),
                                    "dst": dom.get_text(),
                                    "tag": path,
                                    "row": len(items),
                                    "file_type": CacheItem.FileType.EPUB,
                                    "file_path": rel_path,
                                }))

        return items

    # 写入
    def write_to_path(self, items: list[CacheItem]) -> None:

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
                    item = target.pop(0)
                    dom_a = dom.find("a")
                    if dom_a != None:
                        dom_a.string = item.get_dst()
                    else:
                        dom.string = item.get_dst()

                # 将修改后的内容写回去（使用智能输出方法）
                zip_writer.writestr(path, EPUB._soup_to_string(bs))

        def process_html(zip_reader: zipfile.ZipFile, path: str, items: list[CacheItem], bilingual: bool) -> None:
            # 使用智能解析方法（一劳永逸的解决方案）
            # - lxml-xml 保持 SVG/MathML 属性大小写（viewBox、preserveAspectRatio）
            # - 自动补全缺失的命名空间声明（xmlns:xlink 等）
            # - fallback 到 html.parser + 属性修复（处理格式错误的文件）
            with zip_reader.open(path) as reader:
                target = [item for item in items if item.get_tag() == path]
                bs = EPUB._parse_xml(reader.read().decode("utf-8-sig"))

                # 判断是否是导航页
                is_nav_page = bs.find("nav", attrs = {"epub:type": "toc"}) != None

                # 移除竖排样式
                for dom in bs.find_all():
                    class_content: str = re.sub(r"[hv]rtl|[hv]ltr", "", " ".join(dom.get("class", "")))
                    if class_content == "":
                        dom.attrs.pop("class", None)
                    else:
                        dom["class"] = class_content.split(" ")
                    style_content: str = re.sub(r"[^;\s]*writing-mode\s*:\s*vertical-rl;*", "", dom.get("style", ""))
                    if style_content == "":
                        dom.attrs.pop("style", None)
                    else:
                        dom["style"] = style_content

                for dom in bs.find_all(EPUB.EPUB_TAGS):
                    # 跳过空标签或嵌套标签
                    if dom.get_text().strip() == "" or dom.find(EPUB.EPUB_TAGS) != None:
                        continue

                    # 取数据
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
            items = sorted(items, key = lambda x: x.get_row())

            # 数据处理
            abs_path = f"{self.output_path}/{rel_path}"
            os.makedirs(os.path.dirname(abs_path), exist_ok = True)
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
                            process_html(zip_reader, path, items, False)
                        else:
                            zip_writer.writestr(path, zip_reader.read(path))

        # 分别处理每个文件（双语）
        for rel_path, items in group.items():
            # 按行号排序
            items = sorted(items, key = lambda x: x.get_row())

            # 数据处理
            abs_path = f"{self.output_path}/{Localizer.get().path_bilingual}/{rel_path}"
            os.makedirs(os.path.dirname(abs_path), exist_ok = True)
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
                            process_html(zip_reader, path, items, True)
                        else:
                            zip_writer.writestr(path, zip_reader.read(path))