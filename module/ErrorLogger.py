
import json
import os
import re
import threading
import time
from datetime import datetime
from typing import Any

class ErrorLogger:
    """
    详细错误日志记录器
    用于记录导致翻译失败或校验错误的完整上下文信息
    """
    
    _lock = threading.Lock()
    _log_file = "log/error_detail.log"
    _re_secret_tokens = [
        re.compile(r"\b(nvapi-[A-Za-z0-9_\-]{20,})\b"),
        re.compile(r"\b(sk-[A-Za-z0-9_\-]{20,})\b"),
        re.compile(r"\b(AIza[0-9A-Za-z\-_]{20,})\b"),
        re.compile(r"\b(xox[baprs]-[0-9A-Za-z\-]{10,})\b"),
        re.compile(r"(?i)\bBearer\s+([A-Za-z0-9\.\-_]{20,})\b"),
    ]
    _secret_keys = {
        "api_key",
        "apikey",
        "api-key",
        "authorization",
        "auth",
        "token",
        "access_token",
        "access-token",
        "secret",
        "password",
    }

    @classmethod
    def _redact_token(cls, s: Any) -> Any:
        if not isinstance(s, str):
            return s
        if len(s) <= 12:
            return "***"
        return f"{s[:6]}…{s[-4:]}"

    @classmethod
    def _redact_secrets_in_text(cls, s: str) -> str:
        redacted = s
        for pat in cls._re_secret_tokens:
            def repl(m):
                token = m.group(1)
                return cls._redact_token(token)
            redacted = pat.sub(repl, redacted)
        return redacted

    @classmethod
    def _sanitize(cls, obj: Any) -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in cls._secret_keys:
                    if isinstance(v, list):
                        out[k] = [cls._redact_token(x) for x in v]
                    else:
                        out[k] = cls._redact_token(v)
                    continue
                out[k] = cls._sanitize(v)
            return out
        if isinstance(obj, list):
            return [cls._sanitize(v) for v in obj]
        if isinstance(obj, str):
            return cls._redact_secrets_in_text(obj)
        return obj
    
    @classmethod
    def log(cls, error_type: str, message: str, context: dict[str, Any] = None) -> None:
        """
        记录错误详情
        
        Args:
            error_type: 错误类型 (e.g., "LineCountError", "ConnectionError")
            message: 简短错误描述
            context: 上下文数据，包含 prompt, response, think, parsed_result 等
        """
        if context is None:
            context = {}
        safe_context = cls._sanitize(context)
            
        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error_type": error_type,
            "message": message,
            "context": safe_context
        }
        
        # 确保日志目录存在
        os.makedirs(os.path.dirname(cls._log_file), exist_ok=True)
        
        with cls._lock:
            try:
                if not os.path.exists(cls._log_file) or os.path.getsize(cls._log_file) == 0:
                    f = open(cls._log_file, "w", encoding="utf-8-sig")
                else:
                    f = open(cls._log_file, "a", encoding="utf-8")
                with f:
                    f.write(json.dumps(entry, ensure_ascii=False, indent=2))
                    f.write("\n" + "-"*80 + "\n") # 分隔符
            except Exception as e:
                print(f"ErrorLogger failed to write log: {e}")
