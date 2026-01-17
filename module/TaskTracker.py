"""
LinguaGacha - Task Tracker Module
==================================

参照 KeywordGacha 项目实现，提供底部常驻的动态进度条。

【Windows 兼容性修复】
- 在模块加载时启用 Windows VT100 转义序列支持
- 使用 Console(force_terminal=True, legacy_windows=False)
- 适当的刷新频率避免闪烁
- 压缩布局（2-3行），减少光标回退难度

功能：
1. 追踪并发任务的状态（等待中、思考中、接收回复、完成）
2. 统计成功/失败/重试次数
3. 显示实时进度条和详细统计信息
4. 原地更新，不刷屏
5. 与 LogTable 协同工作，日志在上方打印

使用方式：
    tracker = TaskTracker(total=100, task_name="翻译")
    with tracker:
        tracker.start_task(task_id)
        tracker.update_task(task_id, "thinking", think_chars=100)
        tracker.complete_task(task_id, success=True)
"""

import os
import sys
import time
import threading
from typing import Optional, Dict, List
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict

from rich import box
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.console import Console, Group
from rich.progress import (
    Progress, 
    BarColumn, 
    TextColumn, 
    TimeElapsedColumn, 
    TimeRemainingColumn, 
    TaskProgressColumn, 
    SpinnerColumn
)

from base.LogManager import LogManager


# ==================== 日志抑制控制 ====================
_suppress_logging: bool = False


def is_logging_suppressed() -> bool:
    """检查是否应该抑制日志输出"""
    return _suppress_logging


def set_logging_suppressed(value: bool) -> None:
    """设置日志抑制状态"""
    global _suppress_logging
    _suppress_logging = value


class TaskStatus(Enum):
    """任务状态枚举"""
    WAITING = "waiting"
    SENDING = "sending"
    THINKING = "thinking"
    RECEIVING = "receiving"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskState:
    """单个任务的状态"""
    task_id: str
    description: str = ""
    status: TaskStatus = TaskStatus.WAITING
    start_time: float = 0
    end_time: float = 0
    think_chars: int = 0
    reply_chars: int = 0
    chunks: int = 0
    error: Optional[str] = None
    retry_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


class TaskTracker:
    """
    全局任务追踪器
    
    【Windows 兼容性】
    - Console(force_terminal=True, legacy_windows=False)
    - 启用 VT100 转义序列支持
    - 紧凑布局（2-3行）减少光标回退问题
    
    【状态分类】
    - success: 完全成功（无任何问题）
    - warning: 部分成功（有告警但完成了翻译）
    - error: 失败（需要重试）
    """
    
    # 当 max_workers 超过此阈值时，视为"无限并发"（RPM 限流模式）
    UNLIMITED_WORKERS_THRESHOLD: int = 1000
    
    def __init__(
        self,
        total: int,
        task_name: str = "任务",
        max_concurrent: int = 5,
    ):
        self.total = total
        self.task_name = task_name
        self.max_concurrent = max_concurrent
        
        # 核心计数（三分类）
        self.success_count = 0      # 完全成功
        self.warning_count = 0      # 部分成功（有告警）
        self.failed_in_round = 0    # 失败
        self.retry_round = 0
        
        # 任务状态映射
        self._tasks: Dict[str, TaskState] = {}
        self._lock = threading.Lock()
        
        # 响应时间统计
        self._response_times: List[float] = []
        self._failed_reasons: Dict[str, int] = defaultdict(int)
        
        # Token 统计
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        
        # 时间追踪
        self.start_time = time.time()
        
        # 【关键】使用全局统一的 Console 实例（来自 LogManager）
        # 这样 LogTable 的输出才能正确被 Live 上下文管理器捕获和处理
        self._console = LogManager.get().console
        self._live: Optional[Live] = None
        
        # 创建内部进度条
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=40),
            TaskProgressColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("/"),
            TimeRemainingColumn(),
            console=self._console,
            expand=False,
        )
        self._progress_task = None
    
    def __enter__(self):
        """进入上下文：启动 Live 显示"""
        self._progress_task = self._progress.add_task(
            f"[cyan]{self.task_name}",
            total=self.total
        )
        
        # 【关键】Live 配置
        # - refresh_per_second=2: 降低刷新频率减少闪烁
        # - screen=False: 不使用全屏模式
        # - transient=False: 完成后保留
        # - redirect_stdout=True: 重定向标准输出，让 print 正常工作
        # - redirect_stderr=True: 重定向标准错误
        self._live = Live(
            self._build_panel(),
            console=self._console,
            refresh_per_second=2,  # 降低刷新频率
            transient=False,
            screen=False,
            redirect_stdout=True,
            redirect_stderr=True,
        )
        self._live.__enter__()
        
        # 【关键修复】将 Console 输出重定向到 Live 的代理流
        if hasattr(self._console, "file"):
            self._original_console_file = self._console.file
            self._console.file = sys.stdout
            
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出上下文：停止 Live 显示"""
        # 恢复 Console 的原始文件句柄
        if hasattr(self, "_original_console_file") and self._console:
            self._console.file = self._original_console_file

        if self._live:
            # 最终更新一次
            self._live.update(self._build_panel())
            self._live.__exit__(exc_type, exc_val, exc_tb)
        return False
    
    def _build_panel(self) -> Group:
        """
        构建紧凑版面板（移除 Panel 边框，改为 Group 组合）
        
        【Windows 兼容性修复】
        将所有信息压缩到 2-3 行，移除 Panel 边框，减少垂直高度，
        从而大幅降低控制台光标回退的难度，避免刷屏。
        """
        # 统计各状态数量
        status_counts = {status: 0 for status in TaskStatus}
        total_think_chars = 0
        total_reply_chars = 0
        total_chunks = 0
        
        with self._lock:
            for task in self._tasks.values():
                status_counts[task.status] += 1
                total_think_chars += task.think_chars
                total_reply_chars += task.reply_chars
                total_chunks += task.chunks
        
        # 计算活跃任务数
        active_count = (
            status_counts[TaskStatus.SENDING] +
            status_counts[TaskStatus.THINKING] +
            status_counts[TaskStatus.RECEIVING]
        )
        
        # 计算待处理数（总数 - 成功 - 警告 = 尚未完成）
        completed_count = self.success_count + self.warning_count
        pending_count = self.total - completed_count
        
        # 计算平均响应时间
        avg_time = 0.0
        if self._response_times:
            avg_time = sum(self._response_times) / len(self._response_times)
        
        # === 紧凑行：统计信息合并 ===
        # 新格式: 📊 活跃:3 │ ✓12 ⚠2 ✗1 │ 📈 14/30 │ ⏱️ 1.2s │ 🔤 10k+5k
        
        line_info = Text()
        
        # 1. 活跃任务部分（简化显示）
        line_info.append("📊 ", style="bold")
        
        # 显示逻辑修正：活跃数不应超过最大并发数（除非是无限模式）
        display_active = active_count
        if self.max_concurrent < __class__.UNLIMITED_WORKERS_THRESHOLD:
            display_active = min(active_count, self.max_concurrent)
            
        line_info.append(f"{display_active}", style="bold cyan")
        
        # 显示并发限制（当不是无限模式时）
        if self.max_concurrent < __class__.UNLIMITED_WORKERS_THRESHOLD:
            line_info.append(f"/{self.max_concurrent}", style="dim cyan")
        else:
            line_info.append("/∞", style="dim cyan")
        
        # 活跃状态细节
        details = []
        if status_counts[TaskStatus.SENDING] > 0:
            details.append(f"发:{status_counts[TaskStatus.SENDING]}")
        if status_counts[TaskStatus.THINKING] > 0:
            details.append(f"思:{status_counts[TaskStatus.THINKING]}")
        if status_counts[TaskStatus.RECEIVING] > 0:
            details.append(f"收:{status_counts[TaskStatus.RECEIVING]}")
            
        if details:
            line_info.append(f" ({' '.join(details)})", style="dim")
            
        line_info.append(" │ ", style="dim")
        
        # 2. 成功/警告/错误 三分类统计
        # 格式: ✓12 ⚠2 ✗1 （始终显示三个分类，便于用户理解）
        line_info.append("✓", style="bold green")
        line_info.append(f"{self.success_count}", style="green")
        line_info.append(" ", style="dim")
        line_info.append("⚠", style="bold yellow")
        line_info.append(f"{self.warning_count}", style="yellow")
        line_info.append(" ", style="dim")
        line_info.append("✗", style="bold red")
        line_info.append(f"{self.failed_in_round}", style="red")
            
        line_info.append(" │ ", style="dim")
        
        # 3. 进度部分
        line_info.append("📈 ", style="bold")
        line_info.append(f"{completed_count}/{self.total}", style="bold green")
        
        prog_details = []
        if pending_count > 0:
            prog_details.append(f"待:{pending_count}")
        if self.retry_round > 0:
            prog_details.append(f"轮:{self.retry_round}")
            
        if prog_details:
            line_info.append(f" ({' '.join(prog_details)})", style="dim")
            
        line_info.append(" │ ", style="dim")
        
        # 3. 耗时部分
        line_info.append("⏱️ ", style="bold")
        if avg_time > 0:
            color = "green" if avg_time < 60 else "yellow"
            line_info.append(f"{avg_time:.1f}s", style=f"bold {color}")
        else:
            line_info.append("--", style="dim")
        
        # 4. Token 统计
        if self._total_input_tokens > 0 or self._total_output_tokens > 0:
            line_info.append(" │ ", style="dim")
            line_info.append("🔤 ", style="bold")
            line_info.append(f"{self._format_number(self._total_input_tokens)}+{self._format_number(self._total_output_tokens)}", style="dim")
        
        # 5. 流式统计（如果有）
        if total_chunks > 0:
            line_info.append(" │ ", style="dim")
            line_info.append(f"块:{total_chunks}", style="dim")
        
        # 如果有失败原因，合并显示在同一行
        if self._failed_reasons:
            line_info.append(" │ ", style="dim")
            line_info.append("❌ ", style="bold red")
            reasons = sorted(self._failed_reasons.items(), key=lambda x: -x[1])[:2]  # 只显示 top 2
            for r, c in reasons:
                line_info.append(f"{r}({c}) ", style="red")
            
        return Group(self._progress, line_info)
    
    def _format_number(self, n: int) -> str:
        """格式化数字（k/M）"""
        if n >= 1000000:
            return f"{n/1000000:.1f}M"
        elif n >= 1000:
            return f"{n/1000:.1f}k"
        return str(n)
    
    def start_task(self, task_id: str, description: str = "") -> None:
        """开始一个任务"""
        with self._lock:
            self._tasks[task_id] = TaskState(
                task_id=task_id,
                description=description,
                status=TaskStatus.SENDING,
                start_time=time.time(),
            )
        self._refresh()
    
    def update_task(
        self,
        task_id: str,
        status: str,
        think_chars: int = 0,
        reply_chars: int = 0,
        chunks: int = 0,
    ) -> None:
        """更新任务状态"""
        status_map = {
            "waiting": TaskStatus.WAITING,
            "sending": TaskStatus.SENDING,
            "thinking": TaskStatus.THINKING,
            "receiving": TaskStatus.RECEIVING,
        }
        
        with self._lock:
            if task_id in self._tasks:
                task = self._tasks[task_id]
                if status in status_map:
                    task.status = status_map[status]
                task.think_chars = think_chars
                task.reply_chars = reply_chars
                task.chunks = chunks
        self._refresh()
    
    def complete_task(
        self, 
        task_id: str, 
        success: bool = True, 
        warning: bool = False,
        error: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """
        完成一个任务
        
        Args:
            task_id: 任务ID
            success: 是否成功（False表示需要重试）
            warning: 是否有警告（成功但有问题，如行数对齐、假名容忍等）
            error: 错误信息
            input_tokens: 输入token数
            output_tokens: 输出token数
        """
        with self._lock:
            task = self._tasks.get(task_id)
            elapsed = 0
            if task:
                task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
                task.error = error
                task.end_time = time.time()
                task.input_tokens = input_tokens
                task.output_tokens = output_tokens
                elapsed = task.end_time - task.start_time
            
            if success:
                if warning:
                    self.warning_count += 1
                else:
                    self.success_count += 1
                if elapsed > 0:
                    self._response_times.append(elapsed)
            else:
                self.failed_in_round += 1
                if error:
                    short_error = self._simplify_error(error)
                    self._failed_reasons[short_error] += 1
            
            # 累计 Token
            self._total_input_tokens += input_tokens
            self._total_output_tokens += output_tokens
        
        # 更新进度条（成功和警告都算完成）
        if success and self._progress_task is not None:
            completed = self.success_count + self.warning_count
            self._progress.update(self._progress_task, completed=completed)
        self._refresh()
    
    def _simplify_error(self, error: str) -> str:
        """简化错误信息"""
        error = str(error)
        
        if "超时" in error or "timeout" in error.lower():
            return "超时"
        if "假名残留" in error:
            return "假名残留"
        if "韩文残留" in error or "谚文残留" in error:
            return "韩文残留"
        if "模型退化" in error or "退化" in error:
            return "退化"
        if "翻译失效" in error or "相似度" in error:
            return "翻译失效"
        if "行数不一致" in error:
            return "行数错误"
        if "数据解析" in error or "解析失败" in error:
            return "解析失败"
        if "敏感内容" in error or "contentFilter" in error:
            return "敏感内容"
        if "429" in error or "rate" in error.lower():
            return "限流(429)"
        if "连接" in error or "connect" in error.lower():
            return "网络连接"
        
        return error[:15] if len(error) > 15 else error
    
    def start_retry_round(self) -> None:
        """开始新的重试轮次"""
        with self._lock:
            self.retry_round += 1
            self.failed_in_round = 0
            # 清理已完成的任务
            self._tasks = {k: v for k, v in self._tasks.items() 
                          if v.status not in (TaskStatus.COMPLETED, TaskStatus.FAILED)}
        self._refresh()
    
    def add_retry(self) -> None:
        """增加重试计数（兼容旧接口）"""
        self.start_retry_round()
    
    def set_description(self, description: str) -> None:
        """设置进度条描述"""
        if self._progress_task is not None:
            self._progress.update(self._progress_task, description=description)
        self._refresh()
    
    def _refresh(self) -> None:
        """刷新显示"""
        if self._live:
            self._live.update(self._build_panel())
    
    def remove_task(self, task_id: str) -> None:
        """移除任务"""
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        with self._lock:
            avg_time = sum(self._response_times) / len(self._response_times) if self._response_times else 0
            completed = self.success_count + self.warning_count
            return {
                "total": self.total,
                "success": self.success_count,
                "warning": self.warning_count,
                "completed": completed,
                "pending": self.total - completed,
                "failed_in_round": self.failed_in_round,
                "retry_round": self.retry_round,
                "avg_response_time": avg_time,
                "failed_reasons": dict(self._failed_reasons),
                "total_input_tokens": self._total_input_tokens,
                "total_output_tokens": self._total_output_tokens,
                "elapsed_time": time.time() - self.start_time,
            }

    def increase_total(self, delta: int) -> None:
        delta = int(delta or 0)
        if delta <= 0:
            return
        with self._lock:
            self.total += delta
        if self._progress_task is not None:
            self._progress.update(self._progress_task, total=self.total)
        self._refresh()
    
    def print_final_summary(self) -> None:
        """打印最终统计摘要"""
        stats = self.get_stats()
        elapsed = stats["elapsed_time"]
        
        self._console.print("")
        self._console.rule(f"[bold cyan]📊 {self.task_name} 完成统计[/]", style="cyan")
        
        # 基础统计（三分类）
        completed = stats["completed"]
        success_rate = (completed / stats["total"] * 100) if stats["total"] > 0 else 0
        color = "green" if success_rate >= 90 else ("yellow" if success_rate >= 70 else "red")
        
        # 显示 ✓成功 ⚠警告 ✗失败
        summary_parts = []
        summary_parts.append(f"总计: [bold]{stats['total']}[/]")
        summary_parts.append(f"[green]✓成功: {stats['success']}[/]")
        if stats["warning"] > 0:
            summary_parts.append(f"[yellow]⚠警告: {stats['warning']}[/]")
        summary_parts.append(f"[red]✗失败: {stats['total'] - completed}[/]")
        summary_parts.append(f"完成率: [{color}]{success_rate:.1f}%[/]")
        
        self._console.print(f"  {' | '.join(summary_parts)}")
        
        # 时间统计
        if stats["avg_response_time"] > 0:
            self._console.print(f"  平均响应: [bold]{stats['avg_response_time']:.2f}s[/] | 总耗时: [bold]{elapsed:.1f}s[/]")
        
        # Token 统计
        if stats["total_input_tokens"] > 0:
            self._console.print(f"  Token: 输入 [bold]{self._format_number(stats['total_input_tokens'])}[/] | 输出 [bold]{self._format_number(stats['total_output_tokens'])}[/]")
        
        # 错误分布
        if stats["failed_reasons"]:
            reasons_str = " | ".join(f"{k}: {v}" for k, v in sorted(stats["failed_reasons"].items(), key=lambda x: -x[1])[:5])
            self._console.print(f"  [red]错误分布:[/] {reasons_str}")
        
        self._console.print("")


# ==================== 全局 Tracker 管理 ====================
_current_tracker: Optional[TaskTracker] = None


def get_current_tracker() -> Optional[TaskTracker]:
    """获取当前活跃的 tracker"""
    return _current_tracker


def set_current_tracker(tracker: Optional[TaskTracker]) -> None:
    """设置当前活跃的 tracker"""
    global _current_tracker
    _current_tracker = tracker
