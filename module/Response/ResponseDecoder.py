import json_repair as repair

from base.Base import Base

class ResponseDecoder(Base):

    def __init__(self) -> None:
        super().__init__()

    # 解析文本
    def decode(self, response: str) -> tuple[list[str], list[dict[str, str]]]:
        dsts: list[str] = []
        glossarys: list[dict[str, str]] = []

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
                prev = indexed_dsts.get(idx)
                if prev is None:
                    indexed_dsts[idx] = value
                    return
                if isinstance(prev, str) and prev.strip() == "" and value.strip() != "":
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

        # 按行解析失败时，尝试按照普通 JSON 字典进行解析
        if len(dsts) == 0:
            json_data = repair.loads(response)
            if isinstance(json_data, dict):
                # 仍然优先按数字 key 对齐
                indexed_dsts = {}
                for k, v in json_data.items():
                    if isinstance(v, str):
                        try:
                            idx = int(str(k))
                            indexed_dsts[idx] = v
                        except Exception:
                            dsts.append(v)
                if len(indexed_dsts) > 0:
                    max_idx = max(indexed_dsts.keys())
                    dsts = [indexed_dsts.get(i, "") for i in range(max_idx + 1)]

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
                        try:
                            idx = int(str(k))
                            indexed_dsts[idx] = v
                        except Exception:
                            dsts.append(v)
                    continue

                # 翻译结果（普通 JSON：一个对象里包含多个数字 key）
                for k, v in json_data.items():
                    if isinstance(v, str):
                        try:
                            idx = int(str(k))
                            indexed_dsts[idx] = v
                        except Exception:
                            pass

            if len(indexed_dsts) > 0:
                max_idx = max(indexed_dsts.keys())
                dsts = [indexed_dsts.get(i, "") for i in range(max_idx + 1)]

        # 返回默认值
        return dsts, glossarys