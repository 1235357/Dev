"""
进度条模块
=========

参考兄弟项目 KeywordGacha 的简洁进度条设计：
- 描述文字 • 进度条 • 完成/总数 • 已用时间/剩余时间

保留流式统计功能，但以更简洁的方式显示。
"""

from types import TracebackType
from typing import Any
from typing import Self

from rich.progress import BarColumn
from rich.progress import Progress
from rich.progress import TaskID
from rich.progress import TextColumn
from rich.progress import TimeElapsedColumn
from rich.progress import TimeRemainingColumn


class ProgressBar():

    # 类变量
    progress: Progress | None = None

    def __init__(self, transient: bool) -> None:
        super().__init__()

        # 初始化
        self.tasks: dict[TaskID, dict[str, Any]] = {}
        self.transient: bool = transient

    def __enter__(self) -> Self:
        if not isinstance(__class__.progress, Progress):
            # 参考 KeywordGacha 项目的简洁进度条设计
            # 格式：描述 • 进度条 • 完成/总数 • 已用时间/剩余时间
            __class__.progress = Progress(
                TextColumn("{task.description}", justify="right"),
                "•",
                BarColumn(bar_width=None),
                "•",
                TextColumn("{task.completed}/{task.total}", justify="right"),
                "•",
                TimeElapsedColumn(),
                "/",
                TimeRemainingColumn(),
                transient=self.transient,
                refresh_per_second=4,
            )
            __class__.progress.start()

        return self

    def __exit__(self, exc_type: BaseException, exc_val: BaseException, exc_tb: TracebackType) -> None:
        for id, attr in self.tasks.items():
            attr["running"] = False
            __class__.progress.stop_task(id)
            __class__.progress.remove_task(id) if self.transient == True else None

        task_ids: set[TaskID] = {k for k, v in self.tasks.items() if v.get("running") == False}
        if all(v in task_ids for v in __class__.progress.task_ids):
            __class__.progress.stop()
            __class__.progress = None

    def new(self) -> TaskID:
        if __class__.progress is None:
            return None
        else:
            id = __class__.progress.add_task("", total = None)
            self.tasks[id] = {
                "running": True,
            }
            return id

    def update(self, id: TaskID, *, total: int = None, advance: int = None, completed: int = None) -> None:
        if __class__.progress is None:
            pass
        else:
            __class__.progress.update(id, total = total, advance = advance, completed = completed)