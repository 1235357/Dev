"""
流式请求统计追踪器
==================

用于追踪并发流式请求的实时状态，供 ProgressBar 显示。
不使用 Rich Live，避免与现有 ProgressBar 冲突。

功能：
1. 追踪并发任务的状态（发送中、思考中、接收中、完成）
2. 统计成功/失败/重试次数
3. 统计数据块、思考字符、回复字符
4. 提供格式化的统计摘要供 ProgressBar 显示
5. 详细的错误类型分布、平均时间、兜底策略使用统计
"""

import time
import threading
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict


class TaskStatus(Enum):
    """任务状态枚举"""
    WAITING = "waiting"      # 等待中
    SENDING = "sending"      # 发送请求中
    THINKING = "thinking"    # 模型思考中
    RECEIVING = "receiving"  # 接收回复中
    COMPLETED = "completed"  # 已完成
    FAILED = "failed"        # 已失败


@dataclass
class TaskState:
    """单个任务的状态"""
    task_id: str
    status: TaskStatus = TaskStatus.WAITING
    start_time: float = 0
    first_think_time: float = 0      # 首次收到思考内容的时间
    first_reply_time: float = 0      # 首次收到回复内容的时间
    end_time: float = 0              # 任务结束时间
    think_chars: int = 0
    reply_chars: int = 0
    chunks: int = 0
    error: Optional[str] = None


class StreamingStats:
    """
    流式请求统计追踪器 (类级别单例)
    
    使用类变量实现全局状态追踪，避免多实例问题。
    线程安全。
    """
    
    # 类变量 - 全局状态
    _lock: threading.Lock = threading.Lock()
    _tasks: dict[str, TaskState] = {}
    _task_counter: int = 0
    
    # 基础统计计数
    _total: int = 0
    _completed: int = 0
    _success_count: int = 0
    _failed_count: int = 0
    _retry_count: int = 0
    
    # 详细错误统计 - 按错误类型分类
    _error_types: dict[str, int] = defaultdict(int)
    
    # 警告统计
    _warning_count: int = 0
    _warning_types: dict[str, int] = defaultdict(int)
    
    # 兜底策略使用统计
    _fallback_thinking_extract: int = 0  # 从思考内容提取翻译
    _fallback_line_tolerance: int = 0    # 行数容错
    _fallback_empty_tolerance: int = 0   # 空行容错
    _fallback_kana_tolerance: int = 0    # 假名容错
    
    # 时间统计（用于计算平均值）
    _think_times: list[float] = []       # 思考耗时列表
    _reply_times: list[float] = []       # 回复耗时列表
    _total_times: list[float] = []       # 总耗时列表
    
    # 累计字符统计
    _total_think_chars: int = 0
    _total_reply_chars: int = 0
    _total_chunks: int = 0
    
    # Token 统计
    _total_input_tokens: int = 0
    _total_output_tokens: int = 0
    
    # 时间追踪
    _start_time: float = 0
    _enabled: bool = False
    
    @classmethod
    def reset(cls) -> None:
        """重置所有统计"""
        with cls._lock:
            cls._tasks.clear()
            cls._task_counter = 0
            cls._total = 0
            cls._completed = 0
            cls._success_count = 0
            cls._failed_count = 0
            cls._retry_count = 0
            cls._error_types = defaultdict(int)
            cls._warning_count = 0
            cls._warning_types = defaultdict(int)
            cls._fallback_thinking_extract = 0
            cls._fallback_line_tolerance = 0
            cls._fallback_empty_tolerance = 0
            cls._fallback_kana_tolerance = 0
            cls._think_times = []
            cls._reply_times = []
            cls._total_times = []
            cls._total_think_chars = 0
            cls._total_reply_chars = 0
            cls._total_chunks = 0
            cls._total_input_tokens = 0
            cls._total_output_tokens = 0
            cls._start_time = time.time()
            cls._enabled = False
    
    @classmethod
    def enable(cls, total: int = 0) -> None:
        """启用统计追踪"""
        with cls._lock:
            cls._enabled = True
            cls._total = total
            cls._start_time = time.time()
    
    @classmethod
    def disable(cls) -> None:
        """禁用统计追踪"""
        with cls._lock:
            cls._enabled = False
    
    @classmethod
    def is_enabled(cls) -> bool:
        """检查是否启用"""
        return cls._enabled
    
    @classmethod
    def generate_task_id(cls) -> str:
        """生成唯一任务 ID"""
        with cls._lock:
            cls._task_counter += 1
            return f"task_{cls._task_counter}"
    
    @classmethod
    def start_task(cls, task_id: str) -> None:
        """开始一个任务"""
        with cls._lock:
            cls._tasks[task_id] = TaskState(
                task_id=task_id,
                status=TaskStatus.SENDING,
                start_time=time.time(),
            )
    
    @classmethod
    def update_task(
        cls,
        task_id: str,
        status: str | TaskStatus,
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
            "completed": TaskStatus.COMPLETED,
            "failed": TaskStatus.FAILED,
        }
        
        with cls._lock:
            if task_id in cls._tasks:
                task = cls._tasks[task_id]
                now = time.time()
                
                # 状态转换
                if isinstance(status, str) and status in status_map:
                    new_status = status_map[status]
                elif isinstance(status, TaskStatus):
                    new_status = status
                else:
                    new_status = task.status
                
                # 记录首次进入思考状态的时间
                if new_status == TaskStatus.THINKING and task.first_think_time == 0:
                    task.first_think_time = now
                
                # 记录首次进入接收状态的时间
                if new_status == TaskStatus.RECEIVING and task.first_reply_time == 0:
                    task.first_reply_time = now
                
                task.status = new_status
                task.think_chars = think_chars
                task.reply_chars = reply_chars
                task.chunks = chunks
    
    @classmethod
    def complete_task(cls, task_id: str, success: bool = True, error: Optional[str] = None) -> None:
        """完成一个任务"""
        with cls._lock:
            now = time.time()
            
            if task_id in cls._tasks:
                task = cls._tasks[task_id]
                task.status = TaskStatus.COMPLETED if success else TaskStatus.FAILED
                task.error = error
                task.end_time = now
                
                # 计算时间统计
                if task.start_time > 0:
                    total_time = now - task.start_time
                    cls._total_times.append(total_time)
                    
                    # 思考时间（从开始到首次回复）
                    if task.first_reply_time > 0 and task.first_think_time > 0:
                        think_time = task.first_reply_time - task.first_think_time
                        cls._think_times.append(think_time)
                    
                    # 回复时间（从首次回复到结束）
                    if task.first_reply_time > 0:
                        reply_time = now - task.first_reply_time
                        cls._reply_times.append(reply_time)
                
                # 累计字符和块数
                cls._total_think_chars += task.think_chars
                cls._total_reply_chars += task.reply_chars
                cls._total_chunks += task.chunks
            
            cls._completed += 1
            if success:
                cls._success_count += 1
            else:
                cls._failed_count += 1
                # 记录错误类型
                if error:
                    error_type = cls._categorize_error(error)
                    cls._error_types[error_type] += 1
    
    @classmethod
    def _categorize_error(cls, error: str) -> str:
        """将错误消息分类"""
        error_lower = error.lower()
        if "timeout" in error_lower:
            return "超时"
        elif "connection" in error_lower or "network" in error_lower:
            return "网络错误"
        elif "rate" in error_lower or "limit" in error_lower or "429" in error_lower:
            return "限流"
        elif "auth" in error_lower or "key" in error_lower or "401" in error_lower or "403" in error_lower:
            return "认证失败"
        elif "blacklist" in error_lower or "banned" in error_lower:
            return "封禁"
        else:
            return "其他"
    
    @classmethod
    def add_retry(cls) -> None:
        """增加重试计数"""
        with cls._lock:
            cls._retry_count += 1
    
    @classmethod
    def add_warning(cls, warning_type: str = "通用") -> None:
        """增加警告计数"""
        with cls._lock:
            cls._warning_count += 1
            cls._warning_types[warning_type] += 1
    
    @classmethod
    def add_fallback_usage(cls, fallback_type: str) -> None:
        """记录兜底策略使用"""
        with cls._lock:
            if fallback_type == "thinking_extract":
                cls._fallback_thinking_extract += 1
            elif fallback_type == "line_tolerance":
                cls._fallback_line_tolerance += 1
            elif fallback_type == "empty_tolerance":
                cls._fallback_empty_tolerance += 1
            elif fallback_type == "kana_tolerance":
                cls._fallback_kana_tolerance += 1
    
    @classmethod
    def add_tokens(cls, input_tokens: int, output_tokens: int) -> None:
        """累计 Token 使用量"""
        with cls._lock:
            if input_tokens and input_tokens > 0:
                cls._total_input_tokens += input_tokens
            if output_tokens and output_tokens > 0:
                cls._total_output_tokens += output_tokens
    
    @classmethod
    def remove_task(cls, task_id: str) -> None:
        """移除任务（用于清理已完成的任务）"""
        with cls._lock:
            if task_id in cls._tasks:
                del cls._tasks[task_id]
    
    @classmethod
    def get_stats(cls) -> dict:
        """
        获取完整统计信息
        """
        with cls._lock:
            status_counts = {status: 0 for status in TaskStatus}
            active_chunks = 0
            active_think_chars = 0
            active_reply_chars = 0
            
            for task in cls._tasks.values():
                status_counts[task.status] += 1
                active_chunks += task.chunks
                active_think_chars += task.think_chars
                active_reply_chars += task.reply_chars
            
            active_count = (
                status_counts[TaskStatus.SENDING] +
                status_counts[TaskStatus.THINKING] +
                status_counts[TaskStatus.RECEIVING]
            )
            
            # 计算平均时间
            avg_think_time = sum(cls._think_times) / len(cls._think_times) if cls._think_times else 0
            avg_reply_time = sum(cls._reply_times) / len(cls._reply_times) if cls._reply_times else 0
            avg_total_time = sum(cls._total_times) / len(cls._total_times) if cls._total_times else 0
            
            # 计算兜底策略总使用次数
            fallback_total = (
                cls._fallback_thinking_extract +
                cls._fallback_line_tolerance +
                cls._fallback_empty_tolerance +
                cls._fallback_kana_tolerance
            )
            
            return {
                # 活跃任务状态
                "active_count": active_count,
                "sending_count": status_counts[TaskStatus.SENDING],
                "thinking_count": status_counts[TaskStatus.THINKING],
                "receiving_count": status_counts[TaskStatus.RECEIVING],
                
                # 活跃任务数据
                "active_chunks": active_chunks,
                "active_think_chars": active_think_chars,
                "active_reply_chars": active_reply_chars,
                
                # 累计数据
                "total_chunks": cls._total_chunks + active_chunks,
                "total_think_chars": cls._total_think_chars + active_think_chars,
                "total_reply_chars": cls._total_reply_chars + active_reply_chars,
                
                # 结果统计
                "success_count": cls._success_count,
                "failed_count": cls._failed_count,
                "retry_count": cls._retry_count,
                "completed": cls._completed,
                "total": cls._total,
                
                # 警告统计
                "warning_count": cls._warning_count,
                "warning_types": dict(cls._warning_types),
                
                # 错误类型分布
                "error_types": dict(cls._error_types),
                
                # 兜底策略统计
                "fallback_total": fallback_total,
                "fallback_thinking_extract": cls._fallback_thinking_extract,
                "fallback_line_tolerance": cls._fallback_line_tolerance,
                "fallback_empty_tolerance": cls._fallback_empty_tolerance,
                "fallback_kana_tolerance": cls._fallback_kana_tolerance,
                
                # 时间统计（秒）
                "avg_think_time": avg_think_time,
                "avg_reply_time": avg_reply_time,
                "avg_total_time": avg_total_time,
                "elapsed_time": time.time() - cls._start_time,
                
                # Token 统计
                "total_input_tokens": cls._total_input_tokens,
                "total_output_tokens": cls._total_output_tokens,
            }
    
    @classmethod
    def get_summary_text(cls) -> str:
        """
        获取格式化的统计摘要文本
        
        用于在 ProgressBar 描述中显示
        示例: "🚀2 🧠3 📝1 | ✓10 ✗0 ↻2"
        """
        stats = cls.get_stats()
        
        parts = []
        
        # 活跃状态
        if stats["sending_count"] > 0:
            parts.append(f"🚀{stats['sending_count']}")
        if stats["thinking_count"] > 0:
            parts.append(f"🧠{stats['thinking_count']}")
        if stats["receiving_count"] > 0:
            parts.append(f"📝{stats['receiving_count']}")
        
        # 结果统计
        result_parts = []
        result_parts.append(f"✓{stats['success_count']}")
        if stats["failed_count"] > 0:
            result_parts.append(f"✗{stats['failed_count']}")
        if stats["retry_count"] > 0:
            result_parts.append(f"↻{stats['retry_count']}")
        
        if parts:
            return " ".join(parts) + " | " + " ".join(result_parts)
        else:
            return " ".join(result_parts)
    
    @classmethod
    def get_streaming_text(cls) -> str:
        """
        获取流式统计文本
        
        示例: "块:156 思:2.3k 复:1.8k"
        """
        stats = cls.get_stats()
        
        if stats["total_chunks"] == 0 and stats["active_count"] == 0:
            return ""
        
        def format_count(n: int) -> str:
            if n >= 1000000:
                return f"{n/1000000:.1f}M"
            elif n >= 1000:
                return f"{n/1000:.1f}k"
            return str(n)
        
        parts = []
        if stats["total_chunks"] > 0:
            parts.append(f"块:{stats['total_chunks']}")
        if stats["total_think_chars"] > 0:
            parts.append(f"思:{format_count(stats['total_think_chars'])}")
        if stats["total_reply_chars"] > 0:
            parts.append(f"复:{format_count(stats['total_reply_chars'])}")
        
        return " ".join(parts)
    
    @classmethod
    def get_detail_lines(cls) -> list[str]:
        """
        获取详细统计信息（多行）
        
        返回多行文本，供扩展的进度条显示
        """
        stats = cls.get_stats()
        lines = []
        
        # 第一行：时间统计
        if stats["avg_total_time"] > 0:
            time_parts = []
            time_parts.append(f"平均响应:{stats['avg_total_time']:.1f}s")
            if stats["avg_think_time"] > 0:
                time_parts.append(f"思考:{stats['avg_think_time']:.1f}s")
            if stats["avg_reply_time"] > 0:
                time_parts.append(f"回复:{stats['avg_reply_time']:.1f}s")
            lines.append(" | ".join(time_parts))
        
        # 第二行：Token 统计
        if stats["total_input_tokens"] > 0 or stats["total_output_tokens"] > 0:
            def format_tokens(n: int) -> str:
                if n >= 1000000:
                    return f"{n/1000000:.2f}M"
                elif n >= 1000:
                    return f"{n/1000:.1f}k"
                return str(n)
            
            token_parts = []
            token_parts.append(f"输入:{format_tokens(stats['total_input_tokens'])}")
            token_parts.append(f"输出:{format_tokens(stats['total_output_tokens'])}")
            lines.append("Token " + " ".join(token_parts))
        
        # 第三行：兜底策略使用情况
        if stats["fallback_total"] > 0:
            fallback_parts = [f"⚡兜底:{stats['fallback_total']}次"]
            if stats["fallback_thinking_extract"] > 0:
                fallback_parts.append(f"思考提取:{stats['fallback_thinking_extract']}")
            if stats["fallback_line_tolerance"] > 0:
                fallback_parts.append(f"行容错:{stats['fallback_line_tolerance']}")
            if stats["fallback_empty_tolerance"] > 0:
                fallback_parts.append(f"空行:{stats['fallback_empty_tolerance']}")
            if stats["fallback_kana_tolerance"] > 0:
                fallback_parts.append(f"假名:{stats['fallback_kana_tolerance']}")
            lines.append(" ".join(fallback_parts))
        
        # 第四行：警告统计
        if stats["warning_count"] > 0:
            warning_parts = [f"⚠警告:{stats['warning_count']}"]
            for wtype, count in list(stats["warning_types"].items())[:3]:
                warning_parts.append(f"{wtype}:{count}")
            lines.append(" ".join(warning_parts))
        
        # 第五行：错误类型分布
        if stats["failed_count"] > 0 and stats["error_types"]:
            error_parts = [f"❌错误分布:"]
            for etype, count in list(stats["error_types"].items())[:3]:
                error_parts.append(f"{etype}:{count}")
            lines.append(" ".join(error_parts))
        
        return lines
    
    @classmethod
    def get_final_report(cls) -> str:
        """
        获取最终报告（翻译结束时显示）
        """
        stats = cls.get_stats()
        
        lines = []
        lines.append("=" * 50)
        lines.append("📊 流式请求统计报告")
        lines.append("=" * 50)
        
        # 基础统计
        lines.append(f"总任务: {stats['total']} | 完成: {stats['completed']}")
        lines.append(f"成功: {stats['success_count']} | 失败: {stats['failed_count']} | 重试: {stats['retry_count']}")
        
        # 时间统计
        if stats["avg_total_time"] > 0:
            lines.append(f"平均响应时间: {stats['avg_total_time']:.2f}s")
            if stats["avg_think_time"] > 0:
                lines.append(f"  - 思考阶段: {stats['avg_think_time']:.2f}s")
            if stats["avg_reply_time"] > 0:
                lines.append(f"  - 回复阶段: {stats['avg_reply_time']:.2f}s")
        
        # Token 统计
        if stats["total_input_tokens"] > 0:
            lines.append(f"Token 消耗: 输入 {stats['total_input_tokens']:,} | 输出 {stats['total_output_tokens']:,}")
        
        # 字符统计
        lines.append(f"思考字符: {stats['total_think_chars']:,} | 回复字符: {stats['total_reply_chars']:,}")
        lines.append(f"数据块总数: {stats['total_chunks']:,}")
        
        # 兜底策略
        if stats["fallback_total"] > 0:
            lines.append(f"\n⚡ 兜底策略使用 ({stats['fallback_total']}次):")
            if stats["fallback_thinking_extract"] > 0:
                lines.append(f"  - 思考内容提取: {stats['fallback_thinking_extract']}次")
            if stats["fallback_line_tolerance"] > 0:
                lines.append(f"  - 行数容错: {stats['fallback_line_tolerance']}次")
            if stats["fallback_empty_tolerance"] > 0:
                lines.append(f"  - 空行容错: {stats['fallback_empty_tolerance']}次")
            if stats["fallback_kana_tolerance"] > 0:
                lines.append(f"  - 假名容错: {stats['fallback_kana_tolerance']}次")
        
        # 警告统计
        if stats["warning_count"] > 0:
            lines.append(f"\n⚠ 警告统计 ({stats['warning_count']}次):")
            for wtype, count in stats["warning_types"].items():
                lines.append(f"  - {wtype}: {count}次")
        
        # 错误统计
        if stats["failed_count"] > 0 and stats["error_types"]:
            lines.append(f"\n❌ 错误分布:")
            for etype, count in stats["error_types"].items():
                lines.append(f"  - {etype}: {count}次")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)
