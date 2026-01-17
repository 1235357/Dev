import re
import json_repair as repair

from base.Base import Base

class ResponseDecoder(Base):
    """
    响应解码器
    
    负责从模型响应中提取 JSONLINE 格式的翻译结果。
    支持多种兜底策略，包括从思考内容中提取翻译。
    
    增强兼容性处理：
    1. 代码块包裹：```jsonline ... ``` 或每行单独 ```jsonline```
    2. 空行处理：剔除无实际内容的行后重新解析
    3. 多种 JSON 格式：JSONLINE、普通 JSON 字典、混合格式
    4. 行数不一致智能对齐：当译文行数与原文不匹配时，尝试智能剔除/补全
    """
    
    # 用于从思考内容中提取 JSONLINE 的模式
    # 匹配类似 {"49": "译文内容"} 的模式
    RE_JSONLINE_IN_THINKING = re.compile(
        r'\{\s*["\']?\d+["\']?\s*:\s*["\'].*?["\']\s*\}',
        flags=re.DOTALL
    )
    
    # 匹配更宽松的模式：{"数字": "任意内容"}
    RE_JSONLINE_LOOSE = re.compile(
        r'\{\s*["\'](\d+)["\']\s*:\s*["\']([^"\']*(?:[^"\'\\]|\\.)*)["\']?\s*\}',
        flags=re.DOTALL
    )
    
    # 代码块标记模式 - 增强版：支持跨行和各种变体
    RE_CODE_BLOCK_WRAPPER = re.compile(
        r'```(?:jsonline|json|jsonl)?\s*\n?(.*?)\n?```',
        flags=re.DOTALL | re.IGNORECASE
    )
    
    # 单行代码块模式（每行都被单独包裹）- 增强版：支持更复杂的 JSON 内容
    RE_SINGLE_LINE_CODE_BLOCK = re.compile(
        r'```(?:jsonline|json|jsonl)?\s*\n?(\{[^}]*\})\s*\n?```',
        flags=re.IGNORECASE | re.DOTALL
    )
    
    # 多行代码块中的单行 JSON 对象模式
    RE_JSONLINE_IN_BLOCK = re.compile(
        r'^\s*(\{"[^"]*":\s*"[^"]*"\})\s*$',
        flags=re.MULTILINE
    )

    def __init__(self) -> None:
        super().__init__()
        
        # 兜底策略使用标记
        self._used_thinking_fallback = False
        self._used_codeblock_cleanup = False
        self._used_empty_line_cleanup = False
        self._used_line_realignment = False  # 新增：行数重对齐标记

    @property
    def used_thinking_fallback(self) -> bool:
        """返回是否使用了思考内容兜底策略"""
        return self._used_thinking_fallback

    @property
    def used_codeblock_cleanup(self) -> bool:
        """返回是否使用了代码块清理策略"""
        return self._used_codeblock_cleanup

    @property
    def used_empty_line_cleanup(self) -> bool:
        """返回是否使用了空行清理策略"""
        return self._used_empty_line_cleanup

    @property
    def used_line_realignment(self) -> bool:
        """返回是否使用了行数重对齐策略"""
        return self._used_line_realignment

    def _preprocess_response(self, response: str) -> str:
        """
        预处理响应内容，处理各种格式异常
        
        1. 移除代码块包裹（```jsonline ... ```）
        2. 处理每行单独被代码块包裹的情况
        3. 清理多余的空行和空白字符
        
        增强处理（针对用户示例中的问题）：
        - 例子三格式：每个 JSON 对象都被单独的 ```jsonline\n...\n``` 包裹
        - 例子四/五格式：整体被 ```jsonline\n...\n``` 包裹，内部是标准 JSONLINE
        """
        self.debug(f"DEBUG: Original response: {response[:100]}...")
        original = response
        # 步骤1：处理每行单独被代码块包裹的情况（例子三格式）
        # 例如：```jsonline\n{"0": "译文"}\n```\n```jsonline\n{"1": "译文"}\n```
        # 使用更激进的模式匹配 - 改为使用非贪婪匹配，避免因 } 字符截断
        single_block_pattern = re.compile(
            r'```(?:jsonline|json|jsonl)?\s*\n?(.*?)\n?```',
            flags=re.IGNORECASE | re.DOTALL
        )
        
        if single_block_pattern.search(response):
            # 检查是否存在多个单独包裹的代码块
            matches = single_block_pattern.findall(response)
            if len(matches) > 1:
                # 提取所有内容，组合成标准 JSONLINE
                # 注意：matches 包含的是代码块内部的内容
                # 过滤空内容
                valid_matches = [m.strip() for m in matches if m.strip()]
                if valid_matches:
                    response = "\n".join(valid_matches)
                    self._used_codeblock_cleanup = True
        
        # 步骤2：处理整体代码块包裹（例子四/五格式）
        # 例如：```jsonline\n{"0": "译文"}\n{"1": "译文"}\n```
        if not self._used_codeblock_cleanup:
            # 尝试提取整体代码块内容
            block_match = self.RE_CODE_BLOCK_WRAPPER.search(response)
            if block_match:
                # 提取代码块内容
                block_content = block_match.group(1).strip()
                if block_content:
                    # 检查是否是有效的 JSONLINE 内容
                    if '{' in block_content and '}' in block_content:
                        response = block_content
                        self._used_codeblock_cleanup = True
        
        # 步骤3：清理残留的代码块标记
        # 有时模型会输出不完整的代码块标记
        response = re.sub(r'^```(?:jsonline|json|jsonl)?\s*$', '', response, flags=re.MULTILINE | re.IGNORECASE)
        response = re.sub(r'^\s*```\s*$', '', response, flags=re.MULTILINE)
        
        # 步骤4：清理每行开头/结尾的代码块标记（针对格式混乱的情况）
        lines = response.split('\n')
        cleaned_lines = []
        for line in lines:
            # 移除行首的 ``` 标记
            line = re.sub(r'^```(?:jsonline|json|jsonl)?\s*', '', line, flags=re.IGNORECASE)
            # 移除行尾的 ``` 标记
            line = re.sub(r'\s*```$', '', line)
            cleaned_lines.append(line)
        response = '\n'.join(cleaned_lines)
        
        # 步骤5：修复重复的开始花括号
        # 处理模型输出如：{"{"{"6":"..."}  →  {"6":"..."}
        # 这种情况是模型在每行开头多输出了一个或多个 {
        response = self._fix_duplicate_braces(response)
        
        # 步骤6：合并跨行的 JSON 对象
        # 处理模型将一个 JSON 对象拆分成多行的情况，例如：
        # {"0":
        # "译文内容"}
        # 需要合并为：{"0": "译文内容"}
        response = self._merge_split_json_lines(response)
        
        if response != original:
            self._used_codeblock_cleanup = True
        
        return response.strip()

    def _fix_duplicate_braces(self, response: str) -> str:
        """
        修复重复的开始花括号
        
        处理模型输出如：
            {"{"6":"..."}
            {"{"{"{"7":"..."}  （多个重复）
        
        将其修复为：
            {"6":"..."}
            {"7":"..."}
        
        原因：某些模型在输出时会错误地在每行开头多添加一个或多个 {
        """
        lines = response.split('\n')
        fixed_lines = []
        fixed_count = 0
        
        # 模式：匹配行首的 {"{ 或 {"{"{ 等重复模式
        # 即：{"{ 后面紧跟数字和引号
        pattern = re.compile(r'^(\{")+\{("\d+"\s*:)')
        
        for line in lines:
            stripped = line.strip()
            
            # 检测重复花括号模式
            match = pattern.match(stripped)
            if match:
                # 找到重复，只保留最后一个 { 和后面的内容
                fixed_line = '{' + match.group(2) + stripped[match.end():]
                fixed_lines.append(fixed_line)
                fixed_count += 1
            else:
                fixed_lines.append(line)
        
        result = '\n'.join(fixed_lines)
        
        if fixed_count > 0:
            self.debug(f"[预处理] 修复了 {fixed_count} 行重复的开始花括号")
        
        return result

    def _merge_split_json_lines(self, response: str) -> str:
        """
        合并被拆分到多行的 JSON 对象
        
        处理模型输出如：
            {"0":
            "译文内容"}
        
        将其合并为：
            {"0": "译文内容"}
        
        使用花括号计数来确定 JSON 对象边界。
        """
        lines = response.split('\n')
        merged_lines = []
        buffer = ""
        brace_count = 0
        
        for line in lines:
            stripped = line.strip()
            
            if not stripped:
                # 空行：如果不在累积状态，保留空行
                if not buffer:
                    merged_lines.append(line)
                continue
            
            if buffer:
                # 正在累积一个跨行的 JSON 对象
                buffer += " " + stripped
                brace_count += stripped.count('{') - stripped.count('}')
                
                if brace_count <= 0:
                    # JSON 对象完成
                    merged_lines.append(buffer)
                    buffer = ""
                    brace_count = 0
            elif stripped.startswith('{'):
                # 检查是否是完整的 JSON 对象
                brace_count = stripped.count('{') - stripped.count('}')
                if brace_count <= 0:
                    # 完整的单行 JSON
                    merged_lines.append(line)
                    brace_count = 0
                else:
                    # 不完整，需要继续累积
                    buffer = stripped
            else:
                # 普通行（非 JSON 开头）
                merged_lines.append(line)
        
        # 处理残留的不完整 buffer
        if buffer:
            merged_lines.append(buffer)
        
        result = '\n'.join(merged_lines)
        
        # 如果发生了合并，记录日志
        if result != response:
            self.debug(f"[预处理] 合并了跨行的 JSON 对象")
        
        return result

    def _extract_indexed_text_lines(self, text: str) -> dict[int, str]:
        if not text:
            return {}

        indexed: dict[int, str] = {}
        hits = 0

        patterns = (
            re.compile(r'^\s*(?:[-*]\s*)?(?:\[|\(|【)?\s*(\d{1,6})\s*(?:\]|\)|】)?\s*[:：.．、\-]\s*(.*?)\s*$'),
            re.compile(r'^\s*(?:[-*]\s*)?(?:\[|\(|【)?\s*(\d{1,6})\s*(?:\]|\)|】)?\s*[)\]]\s*(.*?)\s*$'),
        )

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue

            m = None
            for p in patterns:
                m = p.match(line)
                if m:
                    break
            if not m:
                continue

            try:
                idx = int(m.group(1))
            except Exception:
                continue

            value = (m.group(2) or "").rstrip("\n").strip()
            indexed[idx] = value
            hits += 1

        if hits < 3:
            return {}

        if 0 not in indexed and 1 not in indexed:
            return {}

        max_idx = max(indexed.keys())
        min_idx = min(indexed.keys())
        if max_idx > 20000:
            return {}

        # 防止误识别：如果编号过于稀疏（大量跳号），视为无效
        span = max_idx - min_idx + 1
        if span > hits + 2:
            return {}

        return indexed

    # 解析文本
    def decode(self, response: str, response_think: str = "") -> tuple[list[str], list[dict[str, str]]]:
        dsts: list[str] = []
        glossarys: list[dict[str, str]] = []
        preserve_trailing_empty = False
        
        # 重置状态标记
        self._used_thinking_fallback = False
        self._used_codeblock_cleanup = False
        self._used_empty_line_cleanup = False
        self._used_line_realignment = False
        
        # 预处理响应内容
        response = self._preprocess_response(response)

        def safe_loads(text: str):
            try:
                return repair.loads(text)
            except Exception:
                return None

        def extract_json_object_strings(text: str) -> list[str]:
            """从混杂文本中提取疑似 JSON 对象字符串（支持对象跨行），用于补救 JSONLINE 被拆行/包裹等情况。"""
            objects: list[str] = []
            depth = 0
            start = None
            in_string = False
            escape = False

            for i, ch in enumerate(text):
                if depth == 0:
                    if ch == "{":
                        depth = 1
                        start = i
                        in_string = False
                        escape = False
                    continue

                # depth > 0
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue

                # not in string
                if ch == '"':
                    in_string = True
                    continue
                if ch == "{":
                    depth += 1
                    continue
                if ch == "}":
                    depth -= 1
                    if depth == 0 and start is not None:
                        objects.append(text[start : i + 1])
                        start = None
                    continue

            return objects

        def extract_json_list_strings(text: str) -> list[str]:
            """从混杂文本中提取疑似 JSON 列表字符串"""
            objects: list[str] = []
            depth = 0
            start = None
            in_string = False
            escape = False

            for i, ch in enumerate(text):
                if depth == 0:
                    if ch == "[":
                        depth = 1
                        start = i
                        in_string = False
                        escape = False
                    continue

                # depth > 0
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue

                # not in string
                if ch == '"':
                    in_string = True
                    continue
                if ch in "[{":
                    depth += 1
                    continue
                if ch in "]}":
                    depth -= 1
                    if depth == 0 and start is not None:
                        # 确保闭合符号匹配
                        if ch == "]" and text[start] == "[":
                            objects.append(text[start : i + 1])
                        start = None
                    continue

            return objects

        # 翻译结果的临时映射（用于 JSONLINE / JSON 字典按序号对齐）
        indexed_dsts: dict[int, str] = {}

        # 按行解析（JSONLINE）
        for line in response.splitlines():
            json_data = safe_loads(line)
            if not isinstance(json_data, dict):
                continue

            # 翻译结果
            if len(json_data) == 1:
                k, v = list(json_data.items())[0]
                if isinstance(v, str):
                    # 清理译文行尾的换行符（模型可能在 JSONLINE 值末尾添加 \n）
                    v = v.rstrip("\n")
                    # 尝试按数字 key 对齐（"0", "1" ...）
                    try:
                        idx = int(str(k))
                        indexed_dsts[idx] = v
                    except Exception:
                        # 非数字 key，保持旧行为：按出现顺序追加
                        dsts.append(v)

            # 术语表条目
            if len(json_data) == 3:
                if any(v in json_data for v in ("src", "dst", "gender")):
                    src: str = json_data.get("src")
                    dst: str = json_data.get("dst")
                    gender: str = json_data.get("gender")
                    glossarys.append(
                        {
                            "src": src if isinstance(src, str) else "",
                            "dst": dst if isinstance(dst, str) else "",
                            "info": gender if isinstance(gender, str) else "",
                        }
                    )

        # 补救解析：无论按行解析是否成功，都扫描提取所有疑似 JSON 对象并合并结果（避免部分对象被拆行导致漏解析）
        for obj_str in extract_json_object_strings(response):
            json_data = safe_loads(obj_str)
            if not isinstance(json_data, dict):
                continue

            # 术语表条目
            if len(json_data) == 3 and any(v in json_data for v in ("src", "dst", "gender")):
                src: str = json_data.get("src")
                dst: str = json_data.get("dst")
                gender: str = json_data.get("gender")
                glossarys.append(
                    {
                        "src": src if isinstance(src, str) else "",
                        "dst": dst if isinstance(dst, str) else "",
                        "info": gender if isinstance(gender, str) else "",
                    }
                )
                continue

            def merge_indexed(idx: int, value: str) -> None:
                # 清理译文行尾的换行符
                value = value.rstrip("\n")
                prev = indexed_dsts.get(idx)
                # print(f"DEBUG: merge_indexed idx={idx}, value={value}, prev={prev}")
                
                # 策略更新：优先使用后出现的翻译结果（覆盖旧值）
                # 这有助于处理以下情况：
                # 1. 提示词泄漏（Example 在前，Real 在后 -> Real 覆盖 Example）
                # 2. 模型自我修正（Draft 在前，Final 在后 -> Final 覆盖 Draft）
                # 3. 重复输出（无害）
                indexed_dsts[idx] = value

            # 翻译结果（JSONLINE 单对象）
            if len(json_data) == 1:
                k, v = list(json_data.items())[0]
                if isinstance(v, str):
                    try:
                        idx = int(str(k))
                        merge_indexed(idx, v)
                    except Exception:
                        pass
                continue

            # 翻译结果（普通 JSON：一个对象里包含多个数字 key）
            for k, v in json_data.items():
                if isinstance(v, str):
                    try:
                        idx = int(str(k))
                        merge_indexed(idx, v)
                    except Exception:
                        pass

        # 如果按数字 key 解析到结果，则以最大序号为长度进行对齐（缺失项补空字符串）
        if len(indexed_dsts) > 0:
            max_idx = max(indexed_dsts.keys())
            dsts = [indexed_dsts.get(i, "") for i in range(max_idx + 1)]
            preserve_trailing_empty = True

        # 按行解析失败时，尝试按照普通 JSON 字典或列表进行解析
        if len(dsts) == 0:
            json_data = repair.loads(response)
            if isinstance(json_data, dict):
                # 仍然优先按数字 key 对齐
                indexed_dsts = {}
                for k, v in json_data.items():
                    if isinstance(v, str):
                        # 清理译文行尾的换行符
                        v = v.rstrip("\n")
                        try:
                            idx = int(str(k))
                            indexed_dsts[idx] = v
                        except Exception:
                            dsts.append(v)
                if len(indexed_dsts) > 0:
                    max_idx = max(indexed_dsts.keys())
                    dsts = [indexed_dsts.get(i, "") for i in range(max_idx + 1)]
                    preserve_trailing_empty = True
            
            # 新增：处理 JSON 列表格式 ["译文1", "译文2", ...]
            elif isinstance(json_data, list):
                self.debug(f"[解析策略] 检测到 JSON 列表格式，尝试解析")
                # 列表隐式包含顺序信息，直接作为有序结果
                list_dsts = []
                valid_list = True
                for item in json_data:
                    if isinstance(item, str):
                        list_dsts.append(item.rstrip("\n"))
                    elif isinstance(item, (int, float)):
                        list_dsts.append(str(item))
                    else:
                        # 如果列表中包含复杂对象，可能不是简单的译文列表
                        valid_list = False
                        break
                
                if valid_list and len(list_dsts) > 0:
                    dsts = list_dsts

        # 最终兜底：当输出混入多段 JSON / 符号混用导致逐行与整体解析都失败时，提取所有“疑似 JSON 对象”再解析
        # 目的：补救诸如同一行输出多个 {..}{..}、或 JSONLINE 被其他文本包裹等情况
        if len(dsts) == 0:
            indexed_dsts = {}

            for obj_str in extract_json_object_strings(response):
                json_data = safe_loads(obj_str)
                if not isinstance(json_data, dict):
                    continue

                # 术语表条目
                if len(json_data) == 3 and any(v in json_data for v in ("src", "dst", "gender")):
                    src: str = json_data.get("src")
                    dst: str = json_data.get("dst")
                    gender: str = json_data.get("gender")
                    glossarys.append(
                        {
                            "src": src if isinstance(src, str) else "",
                            "dst": dst if isinstance(dst, str) else "",
                            "info": gender if isinstance(gender, str) else "",
                        }
                    )
                    continue

                # 翻译结果（JSONLINE 单对象）
                if len(json_data) == 1:
                    k, v = list(json_data.items())[0]
                    if isinstance(v, str):
                        # 清理译文行尾的换行符
                        v = v.rstrip("\n")
                        try:
                            idx = int(str(k))
                            indexed_dsts[idx] = v
                        except Exception:
                            dsts.append(v)
                    continue

                # 翻译结果（普通 JSON：一个对象里包含多个数字 key）
                for k, v in json_data.items():
                    if isinstance(v, str):
                        # 清理译文行尾的换行符
                        v = v.rstrip("\n")
                        try:
                            idx = int(str(k))
                            indexed_dsts[idx] = v
                        except Exception:
                            pass

            if len(indexed_dsts) > 0:
                max_idx = max(indexed_dsts.keys())
                dsts = [indexed_dsts.get(i, "") for i in range(max_idx + 1)]
                preserve_trailing_empty = True

        # ========== 终极兜底：从思考内容中提取翻译结果 ==========
        # 当正式回复为空或解析失败，但思考内容包含大量 JSONLINE 时，尝试从思考内容中提取
        # 这是一种应急措施，会发出警告
        if len(dsts) > 0 and preserve_trailing_empty and response_think and len(response_think) > 100:
            thinking_indexed_dsts = self._extract_from_thinking(
                response_think,
                extract_json_object_strings,
                safe_loads,
                extract_json_list_strings,
            )
            if len(thinking_indexed_dsts) > 0:
                try:
                    max_idx = max(max(thinking_indexed_dsts.keys()), len(dsts) - 1)
                except Exception:
                    max_idx = len(dsts) - 1
                if max_idx >= len(dsts):
                    dsts = dsts + [""] * (max_idx + 1 - len(dsts))
                filled = 0
                for i in range(max_idx + 1):
                    if i < len(dsts) and dsts[i].strip() != "":
                        continue
                    v = thinking_indexed_dsts.get(i)
                    if isinstance(v, str) and v.strip() != "":
                        dsts[i] = v
                        filled += 1
                if filled > 0:
                    self._used_thinking_fallback = True

        if len(dsts) == 0 and response_think and len(response_think) > 100:
            thinking_indexed_dsts = self._extract_from_thinking(
                response_think, 
                extract_json_object_strings, 
                safe_loads,
                extract_json_list_strings
            )
            if len(thinking_indexed_dsts) > 0:
                self._used_thinking_fallback = True
                self.warning(
                    f"[兜底策略] 正式回复为空，从思考内容中提取到 {len(thinking_indexed_dsts)} 条翻译结果"
                )
                max_idx = max(thinking_indexed_dsts.keys())
                dsts = [thinking_indexed_dsts.get(i, "") for i in range(max_idx + 1)]

        # ========== 纯文本兜底：处理不遵循 JSON 格式的输出 ==========
        # 当上述所有 JSON 解析都失败，且响应内容非空时，尝试直接按行分割
        # 兼容 ModelScope/NVIDIA 等可能不遵循 JSONLINE 格式的模型
        if len(dsts) == 0 and response.strip():
            indexed_text = self._extract_indexed_text_lines(response)
            if indexed_text:
                max_idx = max(indexed_text.keys())
                dsts = [indexed_text.get(i, "") for i in range(max_idx + 1)]
                preserve_trailing_empty = True
                self.warning(f"[兜底策略] JSON 解析失败，从纯文本序号行提取到 {len(dsts)} 行")
            else:
                plain_lines = response.strip().splitlines()
                filtered_lines = []
                for line in plain_lines:
                    stripped = line.strip()
                    if not stripped or stripped.startswith("```") or stripped.endswith("```"):
                        continue
                    filtered_lines.append(line)
                
                if len(filtered_lines) > 0:
                    dsts = filtered_lines
                    self.warning(f"[兜底策略] JSON 解析失败，回退到纯文本按行分割模式 (提取到 {len(dsts)} 行)")

        # ========== 空行压缩兜底：处理译文中的空行导致行数不一致 ==========
        # 当解析结果包含连续空字符串时，尝试压缩空行
        # 这是为了处理模型在空行位置输出 {"5": ""} 的情况
        if len(dsts) > 0:
            # 检查是否存在连续的空字符串（可能是空行被错误处理）
            dsts = self._compact_empty_lines(dsts, preserve_trailing_empty = preserve_trailing_empty)

        # 返回默认值
        return dsts, glossarys
    
    def _compact_empty_lines(self, dsts: list[str], preserve_trailing_empty: bool = False) -> list[str]:
        """
        压缩译文列表中不必要的空行
        
        保留有意义的空行（原文也是空行的情况），
        但移除由于解析问题产生的多余空行。
        
        策略：
        1. 如果译文只有一个空字符串，保留
        2. 如果译文有多个连续空字符串，合并为一个
        3. 移除末尾的空字符串（通常是解析残留）
        """
        if len(dsts) <= 1:
            return dsts
        
        # 移除末尾的空字符串（通常是解析残留）
        if preserve_trailing_empty == False:
            while dsts and dsts[-1].strip() == "":
                dsts.pop()
                self._used_empty_line_cleanup = True
        
        # 压缩连续的空字符串
        result = []
        prev_empty = False
        for item in dsts:
            is_empty = item.strip() == ""
            if is_empty and prev_empty:
                # 跳过连续的空字符串
                self._used_empty_line_cleanup = True
                continue
            result.append(item)
            prev_empty = is_empty
        
        return result
    
    def _remove_garbage_lines(self, dsts: list[str]) -> list[str]:
        """
        清理明显的垃圾行和重复行
        """
        if len(dsts) <= 1:
            return dsts
            
        cleaned = []
        prev_line = None
        
        for line in dsts:
            stripped = line.strip()
            
            # 1. 跳过纯符号行 (长度<5且全是符号)
            # 例如: "..." 或 "---"
            if len(stripped) < 5 and not any(c.isalnum() for c in stripped) and \
               not any('\u4e00' <= c <= '\u9fff' for c in stripped): # 简单的中文检查
                 # 但要小心省略号 "……" 可能是合法的
                 # 如果是 "……" 且原文有对应，则不能删。但在对齐阶段我们不知道原文对应。
                 # 这里只删极短的纯ASCII符号?
                 if all(ord(c) < 128 for c in stripped):
                     continue
            
            # 2. 跳过重复行 (Stuttering)
            # 例如: {"1": "Hello"} {"2": "Hello"}
            if prev_line is not None and stripped == prev_line and stripped != "":
                continue
                
            cleaned.append(line)
            prev_line = stripped
            
        return cleaned

    def try_realign_to_sources(self, dsts: list[str], srcs: list[str]) -> list[str]:
        """
        尝试将译文列表重新对齐到原文列表
        
        当译文行数与原文行数不一致时，此方法会尝试智能对齐：
        1. 如果译文行数 > 原文行数：尝试剔除多余的空行、去重、合并拆分行
        2. 如果译文行数 < 原文行数：尝试在合适的位置补充空行
        3. 如果某行译文包含 \\n 且后续有连续空行：将该行拆分并填充
        
        核心策略：
        - 识别原文中的空行位置
        - 将译文中的非空行与原文中的非空行对齐
        - 在原文空行对应的位置插入空译文
        - 处理模型将多行合并为一行的情况（用 \\n 连接）
        
        Args:
            dsts: 译文列表
            srcs: 原文列表
            
        Returns:
            重新对齐后的译文列表，如果无法对齐则返回原列表
        """
        src_count = len(srcs)
        dst_count = len(dsts)
        
        # 如果行数已经一致，直接返回
        if src_count == dst_count:
            return dsts

        # ========== 策略 -1：预处理去噪（重复行、纯符号行） ==========
        # 如果译文行数 > 原文行数，先尝试清理明显的垃圾数据
        if dst_count > src_count:
            cleaned_dsts = self._remove_garbage_lines(dsts)
            if len(cleaned_dsts) < dst_count:
                dsts = cleaned_dsts
                dst_count = len(dsts)
                if dst_count == src_count:
                    self._used_line_realignment = True
                    self.warning(f"[行数重对齐] 清理垃圾/重复行后对齐：{len(dsts)} 行 -> {src_count} 行")
                    return dsts
        
        # ========== 策略0A：处理某行译文包含 \n 且后续有连续空行的情况 ==========
        # 模型有时会把多行内容合并成一行（用 \n 连接），然后后续行输出空字符串
        # 例如：原文106-114是歌词9行，模型输出 {"106": "歌词1\n歌词2\n..."} 然后 {"107": ""} ... {"114": ""}
        # 我们需要将第106行拆分，填充到107-114
        dsts_expanded = self._expand_merged_lines(dsts, srcs)
        if len(dsts_expanded) == src_count:
            self._used_line_realignment = True
            self.warning(
                f"[行数重对齐] 展开合并行后对齐：原文 {src_count} 行，"
                f"译文 {dst_count} 行 -> {src_count} 行"
            )
            return dsts_expanded
        
        # 使用展开后的结果继续处理
        if len(dsts_expanded) != len(dsts):
            dsts = dsts_expanded
            dst_count = len(dsts)
            if dst_count == src_count:
                return dsts
        
        # ========== 策略0B：当译文行数 < 原文行数时，尝试展开所有包含 \n 的行 ==========
        # 模型有时会把多行内容合并，但后续不是空行而是错位的内容
        # 例如：童谣9行，模型输出 {"106": "行1\n行2"} {"107": "行3\n行4"} ...
        # 此时 _expand_merged_lines 不会触发，需要全面展开
        if dst_count < src_count:
            dsts_full_expand = self._try_expand_all_newlines(dsts, srcs)
            if len(dsts_full_expand) == src_count:
                self._used_line_realignment = True
                self.warning(
                    f"[行数重对齐] 全面展开换行符后对齐：原文 {src_count} 行，"
                    f"译文 {dst_count} 行 -> {src_count} 行"
                )
                return dsts_full_expand
            # 更新为展开后的结果继续处理
            if len(dsts_full_expand) > dst_count:
                dsts = dsts_full_expand
                dst_count = len(dsts)
        
        # 策略1.5：如果译文行数 > 原文行数，尝试合并被拆分的行
        if dst_count > src_count:
            merged_dsts = self._try_merge_extra_lines(dsts, srcs)
            
            # 如果合并成功（完全对齐或有改善），更新 dsts
            if len(merged_dsts) < dst_count:
                dsts = merged_dsts
                dst_count = len(dsts)
                
                if dst_count == src_count:
                    self._used_line_realignment = True
                    self.warning(
                        f"[行数重对齐] 合并拆分行后对齐：{len(dsts)} 行 -> {src_count} 行"
                    )
                    return dsts

            # 策略1.6：如果仍然 > 原文行数，尝试激进合并 (Aggressive Merge)
            if dst_count > src_count:
                aggressive_dsts = self._try_aggressive_merge(dsts, srcs)
                if len(aggressive_dsts) < dst_count:
                    dsts = aggressive_dsts
                    dst_count = len(dsts)
                    
                    if dst_count == src_count:
                        self._used_line_realignment = True
                        self.warning(
                            f"[行数重对齐] 激进合并后对齐：{len(dsts)} 行 -> {src_count} 行"
                        )
                        return dsts

            # 策略1.7：如果仍然 > 原文行数，尝试强制截断 (Truncate)
            # 作为最后的手段，如果多出的行在末尾，可能是幻觉
            if dst_count > src_count:
                truncated_dsts = self._try_truncate_extra_lines(dsts, srcs)
                if len(truncated_dsts) == src_count:
                    self._used_line_realignment = True
                    return truncated_dsts

        # 识别原文中的空行位置
        src_empty_indices = set()
        src_non_empty_count = 0
        for i, src in enumerate(srcs):
            if src.strip() == "":
                src_empty_indices.add(i)
            else:
                src_non_empty_count += 1
        
        # 识别译文中的非空行
        dst_non_empty = [(i, dst) for i, dst in enumerate(dsts) if dst.strip() != ""]
        dst_non_empty_count = len(dst_non_empty)
        
        # 策略1：如果译文非空行数 == 原文非空行数，尝试按位置对齐
        if dst_non_empty_count == src_non_empty_count:
            result = [""] * src_count
            dst_idx = 0
            for src_idx in range(src_count):
                if src_idx in src_empty_indices:
                    # 原文是空行，译文也应该是空行
                    result[src_idx] = ""
                else:
                    # 原文非空，从译文的非空行中取值
                    if dst_idx < len(dst_non_empty):
                        result[src_idx] = dst_non_empty[dst_idx][1]
                        dst_idx += 1
                    else:
                        result[src_idx] = ""
            
            self._used_line_realignment = True
            self.warning(
                f"[行数重对齐] 成功对齐：原文 {src_count} 行（非空 {src_non_empty_count} 行），"
                f"译文 {dst_count} 行 -> {src_count} 行"
            )
            return result
        
        # 策略2：如果译文行数 > 原文行数，尝试剔除多余的空行后再对齐
        if dst_count > src_count:
            # 首先尝试剔除末尾空行
            trimmed_dsts = dsts.copy()
            while len(trimmed_dsts) > src_count and trimmed_dsts[-1].strip() == "":
                trimmed_dsts.pop()
            
            if len(trimmed_dsts) == src_count:
                self._used_line_realignment = True
                self.warning(
                    f"[行数重对齐] 剔除末尾空行后对齐：{dst_count} 行 -> {src_count} 行"
                )
                return trimmed_dsts
            
            # 尝试剔除连续的空行
            compacted = []
            prev_empty = False
            for dst in dsts:
                is_empty = dst.strip() == ""
                if is_empty and prev_empty:
                    continue
                compacted.append(dst)
                prev_empty = is_empty
            
            if len(compacted) == src_count:
                self._used_line_realignment = True
                self.warning(
                    f"[行数重对齐] 压缩连续空行后对齐：{dst_count} 行 -> {src_count} 行"
                )
                return compacted
            
            # 尝试只保留非空行对齐（最后手段）
            if dst_non_empty_count == src_non_empty_count and src_empty_indices:
                result = [""] * src_count
                dst_idx = 0
                for src_idx in range(src_count):
                    if src_idx in src_empty_indices:
                        result[src_idx] = ""
                    else:
                        if dst_idx < len(dst_non_empty):
                            result[src_idx] = dst_non_empty[dst_idx][1]
                            dst_idx += 1
                        else:
                            result[src_idx] = ""
                
                self._used_line_realignment = True
                self.warning(
                    f"[行数重对齐] 按非空行对齐：原文 {src_count} 行，"
                    f"译文 {dst_count} 行 -> {src_count} 行"
                )
                return result
        
        # 策略3：如果译文行数 < 原文行数，尝试在原文空行位置补充空行
        if dst_count < src_count:
            missing = src_count - dst_count
            
            # 如果缺失的行数与原文空行数匹配，可能是模型跳过了空行
            if missing <= len(src_empty_indices) and dst_non_empty_count == src_non_empty_count:
                result = [""] * src_count
                dst_idx = 0
                for src_idx in range(src_count):
                    if src_idx in src_empty_indices:
                        result[src_idx] = ""
                    else:
                        if dst_idx < len(dst_non_empty):
                            result[src_idx] = dst_non_empty[dst_idx][1]
                            dst_idx += 1
                        else:
                            result[src_idx] = ""
                
                self._used_line_realignment = True
                self.warning(
                    f"[行数重对齐] 补充空行后对齐：原文 {src_count} 行（含 {len(src_empty_indices)} 空行），"
                    f"译文 {dst_count} 行 -> {src_count} 行"
                )
                return result
            
            # 尝试简单地在末尾补充空行（保守策略）
            if missing <= 3:
                result = dsts + [""] * missing
                self._used_line_realignment = True
                self.warning(
                    f"[行数重对齐] 末尾补充 {missing} 行空行：{dst_count} 行 -> {src_count} 行"
                )
                return result
        
        # 无法对齐，返回原列表
        return dsts
    
    def _expand_merged_lines(self, dsts: list[str], srcs: list[str]) -> list[str]:
        """
        展开被合并的行
        
        处理模型将多行内容合并为一行的情况：
        - 某行译文包含 \\n 字符
        - 该行后面有连续的空字符串行
        - 将该行按 \\n 拆分，填充到后续的空行位置
        
        典型场景：
        原文106-114是歌词（9行），模型输出：
        {"106": "歌词1\\n歌词2\\n...歌词9"}
        {"107": ""}
        {"108": ""}
        ...
        {"114": ""}
        
        我们将第106行拆分，填充到106-114位置。
        
        Args:
            dsts: 译文列表
            srcs: 原文列表
            
        Returns:
            展开后的译文列表
        """
        if len(dsts) == 0:
            return dsts
        
        result = []
        i = 0
        expanded = False
        
        while i < len(dsts):
            current = dsts[i]
            
            # 检查当前行是否包含 \n（实际的换行符，不是转义字符串）
            if '\n' in current and current.strip() != "":
                # 统计后续连续空行的数量
                empty_count = 0
                j = i + 1
                while j < len(dsts) and dsts[j].strip() == "":
                    empty_count += 1
                    j += 1
                
                # 将当前行按 \n 拆分
                parts = current.split('\n')
                parts_count = len(parts)
                
                # 如果拆分后的行数 - 1 == 后续空行数，说明模型确实合并了多行
                # 例如：parts_count=9, empty_count=8 -> 9行歌词被合并，后面8个空行
                if parts_count > 1 and empty_count >= parts_count - 1:
                    # 将拆分后的每一行添加到结果中
                    for part in parts:
                        result.append(part)
                    
                    # 跳过当前行和被填充的空行
                    # 当前行已处理，跳过 parts_count - 1 个空行
                    i += 1 + (parts_count - 1)
                    expanded = True
                    
                    self.debug(
                        f"[行展开] 第 {len(result) - parts_count} 行包含 {parts_count - 1} 个换行符，"
                        f"拆分为 {parts_count} 行，跳过 {parts_count - 1} 个空行"
                    )
                    continue
                
                # 如果后续空行不足，但可能是部分合并的情况
                # 检查是否需要拆分以匹配原文结构
                elif parts_count > 1 and empty_count > 0:
                    # 计算如果拆分会产生多少行
                    potential_lines = parts_count
                    needed_empty = parts_count - 1
                    
                    # 如果空行数量正好等于需要的数量，进行拆分
                    if empty_count == needed_empty:
                        for part in parts:
                            result.append(part)
                        i += 1 + empty_count
                        expanded = True
                        continue
            
            # 默认行为：直接添加
            result.append(current)
            i += 1
        
        if expanded:
            self.warning(f"[行展开] 检测到合并行，已展开：{len(dsts)} 行 -> {len(result)} 行")
        
        return result
    
    def _try_expand_all_newlines(self, dsts: list[str], srcs: list[str]) -> list[str]:
        """
        尝试展开所有译文中的换行符
        
        当译文行数 < 原文行数，且译文中包含 \\n 时，
        尝试将所有包含 \\n 的行展开，看是否能更接近原文行数。
        
        典型场景：
        原文有10行童谣，模型输出：
        {"106": "行1\\n行2"}  # 2行内容
        {"107": "行3\\n行4"}  # 2行内容
        ...
        共5个JSON对象包含10行内容
        
        此方法会将这5个对象展开为10行。
        
        Args:
            dsts: 译文列表
            srcs: 原文列表
            
        Returns:
            展开后的译文列表，如果展开后不能更接近原文行数则返回原列表
        """
        src_count = len(srcs)
        dst_count = len(dsts)
        
        # 只处理译文行数 < 原文行数的情况
        if dst_count >= src_count:
            return dsts
        
        # 统计展开后会有多少行
        total_newlines = sum(dst.count('\n') for dst in dsts)
        expanded_count = dst_count + total_newlines
        
        # 如果没有换行符，无法展开
        if total_newlines == 0:
            return dsts
        
        # 如果展开后的行数不能更接近原文行数，不展开
        current_diff = abs(dst_count - src_count)
        expanded_diff = abs(expanded_count - src_count)
        
        if expanded_diff >= current_diff:
            return dsts
        
        # 执行展开
        result = []
        for dst in dsts:
            if '\n' in dst:
                parts = dst.split('\n')
                result.extend(parts)
            else:
                result.append(dst)
        
        self.debug(
            f"[全面展开] 译文中共有 {total_newlines} 个换行符，"
            f"展开后 {dst_count} 行 -> {len(result)} 行（目标 {src_count} 行）"
        )
        
        return result
    
    def _try_merge_extra_lines(self, dsts: list[str], srcs: list[str]) -> list[str]:
        """
        尝试合并多余的译文行
        
        当译文行数 > 原文行数时，可能是模型将长句拆分成了多行。
        此方法尝试通过标点符号和语境判断，将拆分的行合并回去。
        
        Args:
            dsts: 译文列表
            srcs: 原文列表
            
        Returns:
            合并后的译文列表
        """
        src_count = len(srcs)
        dst_count = len(dsts)
        diff = dst_count - src_count
        
        if diff <= 0:
            return dsts
            
        # 标点符号集合（表示句子结束）
        TERMINAL_PUNCTUATION = {'。', '！', '？', '…', '"', '”', '」', '』', '!', '?', '…', '.'}
        
        # 候选合并列表：(score, index)
        # score 越高表示越应该与下一行合并
        candidates = []
        
        for i in range(dst_count - 1):
            current = dsts[i].strip()
            next_line = dsts[i+1].strip()
            
            if not current or not next_line:
                continue
                
            # 基础分数：优先合并短行 (反比于长度)
            # 假设两行加起来不超过 50 字的更可能是被拆分的短句或对话
            total_len = len(current) + len(next_line)
            score = 100.0 / (total_len + 1.0)
            
            # 规则1：当前行不以结束标点结尾 (最强烈的信号)
            if current[-1] not in TERMINAL_PUNCTUATION:
                score += 500.0
                
            # 规则2：下一行以标点开头（如逗号）
            if next_line.startswith(('，', ',', '、', '。', '.')):
                score += 200.0
                
            # 规则3：当前行以 " 说：" 等对话引导结尾
            if current.endswith(('说：', '道：', '问道：', 'says:', 'said:')):
                score += 100.0
            
            # 过滤掉分数过低的候选项（避免强行合并两个无关的长句）
            if score < 10.0:
                continue
                
            candidates.append((score, i))
        
        # 按分数排序（从高到低）
        # 如果分数相同，优先合并靠前的（保持阅读顺序）
        candidates.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        
        # 执行合并
        merged_indices = set()
        merges_done = 0
        
        # 贪心策略：优先合并分数高的
        # 为了避免合并冲突（如 A+B 和 B+C），我们每次合并后要小心
        # 但这里为了简单，我们先收集所有互不冲突的高分合并
        
        final_merges = []
        
        for score, idx in candidates:
            if merges_done >= diff:
                break
                
            # 检查冲突
            if idx in merged_indices or (idx + 1) in merged_indices:
                continue
                
            merged_indices.add(idx)
            merged_indices.add(idx + 1)
            final_merges.append(idx)
            merges_done += 1
            
        # 如果还没达到目标，可能需要多轮合并（即 A+B+C）
        # 但目前的逻辑只支持两两合并。为了稳健，我们先只做这一轮。
        # 如果还需要合并，可以在下一次递归或迭代中处理（但当前架构不支持递归调用此方法）
        # 所以如果 diff 很大，一次可能不够。
        # 改进：如果 merges_done < diff，我们可以尝试放宽条件或允许连续合并
        
        if not final_merges:
            return dsts
            
        final_merges.sort()
        
        result = []
        i = 0
        while i < dst_count:
            if i in final_merges:
                # 合并 i 和 i+1
                current = dsts[i]
                next_line = dsts[i+1]
                
                # 智能连接
                if current and next_line and \
                   current[-1].isascii() and next_line[0].isascii() and \
                   not current.endswith(' ') and not next_line.startswith(' '):
                    current += " " + next_line
                else:
                    current += next_line
                    
                result.append(current)
                i += 2 # 跳过下一行
            else:
                result.append(dsts[i])
                i += 1
                
        # 递归调用以处理剩余差异（如果还需要合并）
        # 例如：A+B, C+D -> 结果可能还需要继续合并
        if len(result) > src_count and len(result) < dst_count:
             return self._try_merge_extra_lines(result, srcs)
             
        if len(result) != dst_count:
            self.debug(
                f"[行合并] 尝试合并拆分行：{dst_count} 行 -> {len(result)} 行 (目标 {src_count} 行)"
            )
            
        return result

    def _try_aggressive_merge(self, dsts: list[str], srcs: list[str]) -> list[str]:
        """
        激进合并策略
        当常规合并无法满足要求时，尝试更激进的合并：
        1. 强制合并极短的行 (< 10 字符)
        2. 强制合并非标点结尾的行 (即使下一行看起来也是新的句子)
        """
        src_count = len(srcs)
        dst_count = len(dsts)
        diff = dst_count - src_count
        
        if diff <= 0:
            return dsts
            
        # 候选列表：(score, index)
        candidates = []
        
        TERMINAL_PUNCTUATION = {'。', '！', '？', '…', '"', '”', '」', '』', '!', '?', '…', '.'}
        
        for i in range(dst_count - 1):
            current = dsts[i].strip()
            next_line = dsts[i+1].strip()
            
            if not current or not next_line:
                continue
                
            score = 0
            
            # 规则1：极短行 (非常可能是误拆分)
            if len(current) < 10:
                score += 1000
            elif len(current) < 20:
                score += 500
                
            # 规则2：不以标点结尾
            if current[-1] not in TERMINAL_PUNCTUATION:
                score += 300
                
            # 规则3：下一行以小写字母开头 (英文)
            if next_line[0].islower():
                score += 200
                
            # 规则4：两行加起来长度适中 (类似原文长度)
            # 这里简单处理，假设合并后不超过 100 字是安全的
            if len(current) + len(next_line) < 100:
                score += 100
                
            if score > 0:
                candidates.append((score, i))
                
        # 按分数排序
        candidates.sort(key=lambda x: (x[0], -x[1]), reverse=True)
        
        merged_indices = set()
        final_merges = []
        merges_done = 0
        
        for score, idx in candidates:
            if merges_done >= diff:
                break
            if idx in merged_indices or (idx + 1) in merged_indices:
                continue
                
            merged_indices.add(idx)
            merged_indices.add(idx + 1)
            final_merges.append(idx)
            merges_done += 1
            
        if not final_merges:
            return dsts
            
        final_merges.sort()
        result = []
        i = 0
        while i < dst_count:
            if i in final_merges:
                current = dsts[i]
                next_line = dsts[i+1]
                if current and next_line and \
                   current[-1].isascii() and next_line[0].isascii() and \
                   not current.endswith(' ') and not next_line.startswith(' '):
                    current += " " + next_line
                else:
                    current += next_line
                result.append(current)
                i += 2
            else:
                result.append(dsts[i])
                i += 1
                
        # 递归检查是否还需要合并
        if len(result) > src_count and len(result) < dst_count:
            return self._try_aggressive_merge(result, srcs)
            
        return result

    def _try_truncate_extra_lines(self, dsts: list[str], srcs: list[str]) -> list[str]:
        """
        尝试截断多余的译文行
        
        当所有合并策略都失败，且译文行数仍多于原文行数时，
        如果是尾部多出的行（可能是模型幻觉或过度生成），则尝试截断。
        
        Args:
            dsts: 译文列表
            srcs: 原文列表
            
        Returns:
            截断后的译文列表
        """
        src_count = len(srcs)
        dst_count = len(dsts)
        
        if dst_count <= src_count:
            return dsts
            
        # 截断
        truncated = dsts[:src_count]
        
        self.warning(
            f"[行数重对齐] 强制截断多余行：{dst_count} 行 -> {src_count} 行 (丢弃末尾 {dst_count - src_count} 行)"
        )
        return truncated

    def _extract_from_thinking(
        self,
        thinking_content: str,
        extract_json_object_strings,
        safe_loads,
        extract_json_list_strings=None,
    ) -> dict[int, str]:
        """
        从思考内容中提取 JSONLINE 格式的翻译结果
        
        模型有时会在思考过程中输出类似：
        {"48": "他试图追溯记忆。追溯之中，猛地倒吸一口凉气。"}
        我们选择：{"49": "就在这时，脚步声响起。"}
        
        或者输出列表格式：
        ["译文1", "译文2"]
        
        这个方法尝试识别并提取这些内容。
        """
        indexed_dsts: dict[int, str] = {}
        
        # 方法0：尝试提取 JSON 列表（如果有提供提取函数）
        # 列表通常是完整的翻译块，优先级较高
        if extract_json_list_strings:
            for list_str in extract_json_list_strings(thinking_content):
                json_data = safe_loads(list_str)
                if isinstance(json_data, list):
                    # 验证列表内容是否主要是字符串
                    valid_strings = 0
                    temp_dsts = {}
                    for i, item in enumerate(json_data):
                        if isinstance(item, str):
                            temp_dsts[i] = item.rstrip("\n")
                            valid_strings += 1
                        elif isinstance(item, (int, float)):
                            temp_dsts[i] = str(item)
                            valid_strings += 1
                    
                    # 如果列表大部分是有效的，且包含的内容比当前已有的更多，则采纳
                    if valid_strings > 0 and len(temp_dsts) > len(indexed_dsts):
                         indexed_dsts = temp_dsts

        # 方法1：使用通用的 JSON 对象提取函数
        for obj_str in extract_json_object_strings(thinking_content):
            json_data = safe_loads(obj_str)
            if not isinstance(json_data, dict):
                continue
            
            # 只处理单键值对的 JSONLINE 格式
            if len(json_data) == 1:
                k, v = list(json_data.items())[0]
                if isinstance(v, str):
                    v = v.rstrip("\n")
                    try:
                        idx = int(str(k))
                        # 只在该索引为空时填充，避免覆盖
                        if idx not in indexed_dsts or indexed_dsts[idx].strip() == "":
                            indexed_dsts[idx] = v
                    except (ValueError, TypeError):
                        pass
        
        # 方法2：使用正则表达式匹配更宽松的模式
        # 有些思考内容中的 JSON 可能格式不够严格
        if len(indexed_dsts) == 0:
            # 匹配 {"数字": "内容"} 或 {'数字': '内容'} 模式
            pattern = re.compile(
                r'\{\s*["\']?(\d+)["\']?\s*:\s*["\']([^"\'\\]*(?:\\.[^"\'\\]*)*)["\']?\s*\}',
                flags=re.DOTALL
            )
            for match in pattern.finditer(thinking_content):
                try:
                    idx = int(match.group(1))
                    value = match.group(2).rstrip("\n")
                    # 处理转义字符
                    value = value.replace('\\"', '"').replace("\\'", "'")
                    if idx not in indexed_dsts or indexed_dsts[idx].strip() == "":
                        indexed_dsts[idx] = value
                except (ValueError, TypeError):
                    pass
        
        # 方法3：查找类似 "我们选择：{...}" 或 "重构后：{...}" 的模式
        # 这些通常是模型最终决定的翻译
        if len(indexed_dsts) == 0:
            decision_patterns = [
                r'(?:我们选择|选择|重构后|文学化|译为|翻译为|输出)[：:]\s*(\{[^}]+\})',
                r'(\{"\d+":\s*"[^"]+"\})\s*[。，,.]?\s*$',  # 句末的 JSONLINE
            ]
            for pattern_str in decision_patterns:
                pattern = re.compile(pattern_str, flags=re.MULTILINE)
                for match in pattern.finditer(thinking_content):
                    try:
                        obj_str = match.group(1) if match.lastindex else match.group(0)
                        json_data = safe_loads(obj_str)
                        if isinstance(json_data, dict) and len(json_data) == 1:
                            k, v = list(json_data.items())[0]
                            if isinstance(v, str):
                                idx = int(str(k))
                                v = v.rstrip("\n")
                                if idx not in indexed_dsts or indexed_dsts[idx].strip() == "":
                                    indexed_dsts[idx] = v
                    except (ValueError, TypeError, Exception):
                        pass

        if len(indexed_dsts) == 0:
            indexed_text = self._extract_indexed_text_lines(thinking_content)
            if indexed_text:
                indexed_dsts = indexed_text
        
        return indexed_dsts
