import logging
import os
import shutil
import threading
import time
import traceback
from logging.handlers import TimedRotatingFileHandler
from typing import Self

from rich.console import Console
from rich.logging import RichHandler

from module.ProgressBar import ProgressBar

class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):

    """Windows 下更稳健的按日轮转 Handler。

    现象：TimedRotatingFileHandler 在 doRollover() 中会尝试 os.rename(app.log -> app.log.YYYY-MM-DD)。
    若该文件正被其他进程占用（常见：编辑器/杀软/另一个程序实例），rename 会抛 WinError 32，
    且之后每次写日志都会重复触发 rollover，导致控制台刷屏 "--- Logging error ---"。

    策略：rename 失败时退化为“复制到目标文件 + 截断源文件”，并吞掉异常以避免刷屏。
    """

    def rotate(self, source: str, dest: str) -> None:
        try:
            return super().rotate(source, dest)
        except PermissionError:
            # 目标：尽量完成轮转；若依然失败，也要避免抛出导致 emit() 重复报错。
            last_exc: Exception | None = None
            for attempt in range(5):
                try:
                    if os.path.exists(source) == False:
                        return

                    # dest 已存在时尽量覆盖（避免因为历史残留导致再次失败）
                    if os.path.exists(dest):
                        try:
                            os.remove(dest)
                        except OSError:
                            pass

                    # 复制 source -> dest
                    with open(source, "rb") as sf, open(dest, "wb") as df:
                        shutil.copyfileobj(sf, df, length = 1024 * 1024)

                    # 截断 source（保留 app.log 作为继续写入的文件）
                    try:
                        with open(source, "wb"):
                            pass
                    except OSError:
                        # 截断失败也不抛异常，避免刷屏
                        pass

                    return
                except Exception as e:
                    last_exc = e
                    # 简单退避，给系统/占用者一点时间释放句柄
                    time.sleep(0.15 * (attempt + 1))

            # 最终兜底：彻底吞掉异常，避免 logging 模块重复输出 "--- Logging error ---"
            _ = last_exc
            return

class LogManager():

    PATH: str = "./log"
    _INSTANCE_LOCK: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        super().__init__()

        # 控制台实例
        self.console = Console()

        # 文件日志实例
        os.makedirs(__class__.PATH, exist_ok = True)
        self.file_handler = SafeTimedRotatingFileHandler(
            f"{__class__.PATH}/app.log",
            when = "midnight",
            interval = 1,
            encoding = "utf-8",
            backupCount = 3,
        )
        self.file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt = "%Y-%m-%d %H:%M:%S"))
        self.file_logger = logging.getLogger("linguagacha_file")
        self.file_logger.propagate = False
        self.file_logger.setLevel(logging.DEBUG)
        # 避免重复添加 handler（多实例/热重载/并发初始化会导致同一文件被多次打开，进而轮转失败）
        self.file_logger.handlers.clear()
        self.file_logger.addHandler(self.file_handler)

        # 控制台日志实例
        self.console_handler = RichHandler(
            console = self.console,
            markup = True,
            show_path = False,
            rich_tracebacks = False,
            tracebacks_extra_lines = 0,
            log_time_format = "[%X]",
            omit_repeated_times = False,
        )
        self.console_logger = logging.getLogger("linguagacha_console")
        self.console_logger.propagate = False
        self.console_logger.setLevel(logging.INFO)
        self.console_logger.handlers.clear()
        self.console_logger.addHandler(self.console_handler)

    @classmethod
    def get(cls) -> Self:
        if getattr(cls, "__instance__", None) is None:
            with cls._INSTANCE_LOCK:
                if getattr(cls, "__instance__", None) is None:
                    cls.__instance__ = cls()

        return cls.__instance__

    def is_expert_mode(self) -> bool:
        if getattr(self, "expert_mode", None) is None:
            from module.Config import Config
            self.expert_mode = Config().load().expert_mode
            self.console_logger.setLevel(logging.DEBUG if self.expert_mode == True else logging.INFO)

        return self.expert_mode

    def print(self, msg: str, e: Exception = None, file: bool = True, console: bool = True) -> None:
        msg_e: str = f"{msg} {e}" if msg != "" else f"{e}"
        if e == None:
            self.file_logger.info(f"{msg}") if file == True else None
            self.console.print(f"{msg}") if console == True else None
        elif self.is_expert_mode() == False:
            self.file_logger.info(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console.print(msg_e) if console == True else None
        else:
            self.file_logger.info(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console.print(f"{msg_e}\n{self.get_trackback(e)}\n") if console == True else None

    def debug(self, msg: str, e: Exception = None, file: bool = True, console: bool = True) -> None:
        msg_e: str = f"{msg} {e}" if msg != "" else f"{e}"
        if e == None:
            self.file_logger.debug(f"{msg}") if file == True else None
            self.console_logger.debug(f"{msg}") if console == True else None
        elif self.is_expert_mode() == False:
            self.file_logger.debug(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console_logger.debug(msg_e) if console == True else None
        else:
            self.file_logger.debug(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console_logger.debug(f"{msg_e}\n{self.get_trackback(e)}\n") if console == True else None

    def info(self, msg: str, e: Exception = None, file: bool = True, console: bool = True) -> None:
        msg_e: str = f"{msg} {e}" if msg != "" else f"{e}"
        if e == None:
            self.file_logger.info(f"{msg}") if file == True else None
            self.console_logger.info(f"{msg}") if console == True else None
        elif self.is_expert_mode() == False:
            self.file_logger.info(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console_logger.info(msg_e) if console == True else None
        else:
            self.file_logger.info(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console_logger.info(f"{msg_e}\n{self.get_trackback(e)}\n") if console == True else None

    def error(self, msg: str, e: Exception = None, file: bool = True, console: bool = True) -> None:
        msg_e: str = f"{msg} {e}" if msg != "" else f"{e}"
        if e == None:
            self.file_logger.error(f"{msg}") if file == True else None
            self.console_logger.error(f"{msg}") if console == True else None
        elif self.is_expert_mode() == False:
            self.file_logger.error(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console_logger.error(msg_e) if console == True else None
        else:
            self.file_logger.error(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console_logger.error(f"{msg_e}\n{self.get_trackback(e)}\n") if console == True else None

    def warning(self, msg: str, e: Exception = None, file: bool = True, console: bool = True) -> None:
        msg_e: str = f"{msg} {e}" if msg != "" else f"{e}"
        if e == None:
            self.file_logger.warning(f"{msg}") if file == True else None
            self.console_logger.warning(f"{msg}") if console == True else None
        elif self.is_expert_mode() == False:
            self.file_logger.warning(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console_logger.warning(msg_e) if console == True else None
        else:
            self.file_logger.warning(f"{msg_e}\n{self.get_trackback(e)}\n") if file == True else None
            self.console_logger.warning(f"{msg_e}\n{self.get_trackback(e)}\n") if console == True else None

    def get_trackback(self, e: Exception) -> str:
        return f"{("".join(traceback.format_exception(e))).strip()}"