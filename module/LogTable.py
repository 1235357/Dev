"""
LinguaGacha - Log Table Module
==============================

参照 KeywordGacha 项目实现，提供详细的 LLM 任务日志表格。

核心功能：
1. 使用 Rich Table 实现表格化日志输出
2. 颜色区分任务状态（绿色=成功，黄色=警告，红色=失败）
3. 完整显示：请求内容、模型思考、响应内容
4. 支持翻译任务的原文/译文对比显示
5. 实时更新的流式统计信息
"""

import itertools
from typing import Optional

import rich
from rich import box
from rich import markup
from rich.table import Table
from rich.console import Console
from rich.text import Text
from rich.live import Live

from base.Base import Base
from base.LogManager import LogManager


class LogTable(Base):
    """
    LLM 操作详细日志打印器
    
    用于在专家模式下显示完整的请求/响应内容，
    帮助用户理解翻译过程中发生了什么。
    """
    
    # 控制台宽度限制
    CONSOLE_WIDTH = 120
    
    @classmethod
    def get_console(cls) -> Console:
        """获取控制台实例"""
        return LogManager.get().console
    
    # ==================== 阶段标题 ====================
    
    @classmethod
    def print_stage_header(cls, stage_name: str, stage_num: int = 0) -> None:
        """打印阶段标题（醒目的分隔线）"""
        console = cls.get_console()
        if stage_num > 0:
            title = f"阶段 {stage_num}: {stage_name}"
        else:
            title = stage_name
        console.print("")
        console.rule(f"[bold cyan]{title}[/]", style="cyan")
        console.print("")
    
    # ==================== 批量任务汇总 ====================
    
    @classmethod
    def print_batch_summary(
        cls,
        task_name: str,
        total: int,
        success: int,
        failed: int,
        elapsed_time: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """
        打印批量任务汇总
        """
        console = cls.get_console()
        
        # 计算成功率
        success_rate = (success / total * 100) if total > 0 else 0
        
        # 选择颜色
        if failed == 0:
            status_color = "green"
            status_icon = "✓"
        elif success > 0:
            status_color = "yellow"
            status_icon = "⚠"
        else:
            status_color = "red"
            status_icon = "✗"
        
        # 构建汇总消息
        token_info = f" | Token: {input_tokens}+{output_tokens}" if input_tokens or output_tokens else ""
        summary = (
            f"[{status_color}]{status_icon}[/] [{task_name}] 完成 | "
            f"总计: {total} | 成功: [green]{success}[/] | 失败: [red]{failed}[/] | "
            f"成功率: {success_rate:.1f}% | 耗时: {elapsed_time:.1f}s{token_info}"
        )
        
        console.print("")
        console.rule(summary, style=status_color)
        console.print("")
    
    # ==================== 核心：LLM 任务日志表格 ====================
    
    @classmethod
    def print_log_table(
        cls,
        task_name: str,
        status: str,  # "success", "warning", "error", "info"
        message: str,
        srcs: list[str] = None,
        dsts: list[str] = None,
        request_content: Optional[str] = None,
        response_think: Optional[str] = None,
        response_result: Optional[str] = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        elapsed_time: float = 0,
        extra_info: Optional[dict] = None,
        expert_mode: bool = False,
    ) -> None:
        """
        打印 LLM 任务日志表格
        
        Args:
            task_name: 任务名称（如 "翻译"、"术语提取"）
            status: 状态 ("success", "warning", "error", "info")
            message: 主要消息
            srcs: 原文列表
            dsts: 译文列表
            request_content: 请求内容（专家模式显示）
            response_think: 模型思考内容（专家模式显示）
            response_result: 模型回复内容（专家模式显示）
            input_tokens: 输入 token 数
            output_tokens: 输出 token 数
            elapsed_time: 耗时（秒）
            extra_info: 额外信息字典
            expert_mode: 是否专家模式（显示详细内容）
        """
        console = cls.get_console()
        
        # 状态颜色映射
        style_map = {
            "success": "green",
            "warning": "yellow",
            "error": "red",
            "info": "blue",
        }
        style = style_map.get(status, "white")
        
        # 构建日志行
        rows = []
        
        # 第一行：任务信息
        time_info = f"{elapsed_time:.2f}s" if elapsed_time > 0 else ""
        token_info = f"Token: {input_tokens}+{output_tokens}" if input_tokens or output_tokens else ""
        info_parts = [f"[{task_name}]"]
        if time_info:
            info_parts.append(time_info)
        if token_info:
            info_parts.append(token_info)
        rows.append(f"{message} ({' | '.join(info_parts)})")
        
        # 额外信息
        if extra_info:
            info_str = " | ".join(f"{k}: {v}" for k, v in extra_info.items() if v)
            if info_str:
                rows.append(info_str)
        
        # 专家模式：显示详细内容
        if expert_mode:
            # 请求内容
            if request_content:
                rows.append(f"[bold blue]【请求内容】[/]\n{markup.escape(request_content)}")
            
            # 模型思考
            if response_think:
                rows.append(f"[bold magenta]【模型思考】[/]\n{markup.escape(response_think)}")
            
            # 响应内容
            if response_result:
                rows.append(f"[bold green]【模型回复】[/]\n{markup.escape(response_result)}")
        
        # 原文译文对比
        if srcs and dsts:
            pair = ""
            for src, dst in itertools.zip_longest(srcs or [], dsts or [], fillvalue=""):
                pair = pair + "\n" + f"{markup.escape(src)} [bright_blue]-->[/] {markup.escape(dst)}"
            rows.append(pair.strip())
        
        # 生成并打印表格
        table = cls._generate_log_table(rows, style)
        console.print(table)
    
    @classmethod
    def _generate_log_table(cls, rows: list, style: str) -> Table:
        """
        生成日志表格
        """
        table = Table(
            box=box.ASCII2,
            expand=True,
            title=" ",
            caption=" ",
            highlight=True,
            show_lines=True,
            show_header=False,
            show_footer=False,
            collapse_padding=True,
            border_style=style,
        )
        table.add_column("", style="white", ratio=1, overflow="fold")
        
        for row in rows:
            if isinstance(row, str):
                table.add_row(row)
            else:
                table.add_row(*row)
        
        return table
    
    # ==================== 翻译任务专用日志 ====================
    
    @classmethod
    def print_translation_result(
        cls,
        status: str,
        message: str,
        srcs: list[str],
        dsts: list[str],
        input_tokens: int = 0,
        output_tokens: int = 0,
        elapsed_time: float = 0,
        response_think: Optional[str] = None,
        response_result: Optional[str] = None,
        expert_mode: bool = False,
        preceding_lines: Optional[list[str]] = None,
        glossary_used: Optional[list[dict]] = None,
    ) -> None:
        """
        打印翻译结果日志
        
        专门为翻译任务设计的日志格式，包含：
        - 参考上文
        - 术语表
        - 原文/译文对比
        - 模型思考/回复（专家模式）
        """
        console = cls.get_console()
        
        # 状态颜色映射
        style_map = {
            "success": "green",
            "warning": "yellow",
            "error": "red",
        }
        style = style_map.get(status, "white")
        
        # 构建日志行
        rows = []
        
        # 第一行：状态信息
        time_info = f"{elapsed_time:.2f}s" if elapsed_time > 0 else ""
        token_info = f"Token: {input_tokens}+{output_tokens}" if input_tokens or output_tokens else ""
        info_parts = ["[翻译]"]
        if time_info:
            info_parts.append(time_info)
        if token_info:
            info_parts.append(token_info)
        rows.append(f"{message} ({' | '.join(info_parts)})")
        
        # 参考上文
        if preceding_lines and expert_mode:
            preceding_text = "\n".join(markup.escape(line) for line in preceding_lines[-10:])  # 只显示最后10行
            if len(preceding_lines) > 10:
                preceding_text = f"... (省略 {len(preceding_lines) - 10} 行)\n" + preceding_text
            rows.append(f"[bold cyan]参考上文：[/]\n{preceding_text}")
        
        # 术语表
        if glossary_used and expert_mode:
            glossary_text = "\n".join(
                f"{markup.escape(g.get('src', ''))} -> {markup.escape(g.get('dst', ''))}"
                for g in glossary_used[:20]  # 只显示前20条
            )
            if len(glossary_used) > 20:
                glossary_text += f"\n... (省略 {len(glossary_used) - 20} 条)"
            rows.append(f"[bold yellow]术语表：[/]\n{glossary_text}")
        
        # 模型思考（专家模式）
        if response_think and expert_mode:
            think_display = response_think
            if len(think_display) > 2000:
                think_display = think_display[:1000] + f"\n... [dim](省略 {len(think_display) - 2000} 字符)[/dim] ...\n" + think_display[-1000:]
            rows.append(f"[bold magenta]模型思考内容：[/]\n{markup.escape(think_display)}")
        
        # 模型回复（专家模式）
        if response_result and expert_mode:
            result_display = response_result
            if len(result_display) > 3000:
                result_display = result_display[:1500] + f"\n... [dim](省略 {len(result_display) - 3000} 字符)[/dim] ...\n" + result_display[-1500:]
            rows.append(f"[bold green]模型回复内容：[/]\n{markup.escape(result_display)}")
        
        # 原文译文对比
        if srcs and dsts:
            pair = ""
            for i, (src, dst) in enumerate(itertools.zip_longest(srcs, dsts, fillvalue="")):
                pair = pair + "\n" + f"[dim]{i}:[/] {markup.escape(src)} [bright_blue]-->[/] {markup.escape(dst)}"
            rows.append(pair.strip())
        
        # 生成并打印表格
        table = cls._generate_log_table(rows, style)
        console.print(table)
    
    # ==================== 错误/警告日志 ====================
    
    @classmethod
    def print_error_table(
        cls,
        error_type: str,
        message: str,
        details: Optional[str] = None,
        srcs: list[str] = None,
        dsts: list[str] = None,
    ) -> None:
        """
        打印错误日志表格
        """
        rows = [f"[bold red]{error_type}[/]: {message}"]
        
        if details:
            rows.append(f"[dim]{markup.escape(details)}[/]")
        
        if srcs and dsts:
            pair = ""
            for src, dst in itertools.zip_longest(srcs or [], dsts or [], fillvalue=""):
                pair = pair + "\n" + f"{markup.escape(src)} [bright_blue]-->[/] {markup.escape(dst)}"
            rows.append(pair.strip())
        
        table = cls._generate_log_table(rows, "red")
        cls.get_console().print(table)
    
    @classmethod
    def print_retry_info(
        cls,
        retry_count: int,
        max_retry: int,
        reason: str,
    ) -> None:
        """打印重试信息"""
        console = cls.get_console()
        console.print(f"[yellow][重试 {retry_count}/{max_retry}][/] {reason}")
    
    # ==================== 流式输出状态 ====================
    
    @classmethod
    def create_stream_live(cls) -> Live:
        """
        创建流式输出的 Live 实时显示对象
        """
        console = cls.get_console()
        return Live(
            cls._build_stream_status("准备中", 0, 0, 0),
            console=console,
            refresh_per_second=4,
            transient=True,
        )
    
    @classmethod
    def _build_stream_status(cls, phase: str, chunk_count: int, think_len: int, reply_len: int) -> Text:
        """
        构建流式状态显示文本
        """
        if phase == "思考中":
            icon = "🧠"
            color = "magenta"
        elif phase == "接收回复":
            icon = "📝"
            color = "cyan"
        elif phase == "完成":
            icon = "✓"
            color = "green"
        else:
            icon = "⏳"
            color = "yellow"
        
        status_text = Text()
        status_text.append(f"  {icon} ", style=f"bold {color}")
        status_text.append(f"[流式] ", style="dim")
        status_text.append(f"{phase}", style=f"bold {color}")
        status_text.append(f" | ", style="dim")
        status_text.append(f"数据块: ", style="dim")
        status_text.append(f"{chunk_count}", style="bold white")
        
        if think_len > 0:
            status_text.append(f" | ", style="dim")
            status_text.append(f"思考: ", style="dim")
            status_text.append(f"{think_len} 字", style="magenta")
        
        if reply_len > 0:
            status_text.append(f" | ", style="dim")
            status_text.append(f"回复: ", style="dim")
            status_text.append(f"{reply_len} 字", style="cyan")
        
        return status_text
    
    @classmethod
    def update_stream_live(
        cls,
        live: Live,
        phase: str,
        chunk_count: int,
        think_len: int = 0,
        reply_len: int = 0,
    ) -> None:
        """
        更新流式输出的实时进度
        """
        live.update(cls._build_stream_status(phase, chunk_count, think_len, reply_len))


# ==================== 便捷函数 ====================

def print_log_table(*args, **kwargs):
    """便捷函数：打印日志表格"""
    LogTable.print_log_table(*args, **kwargs)

def print_stage_header(*args, **kwargs):
    """便捷函数：打印阶段标题"""
    LogTable.print_stage_header(*args, **kwargs)

def print_batch_summary(*args, **kwargs):
    """便捷函数：打印批量汇总"""
    LogTable.print_batch_summary(*args, **kwargs)

def print_translation_result(*args, **kwargs):
    """便捷函数：打印翻译结果"""
    LogTable.print_translation_result(*args, **kwargs)

def print_error_table(*args, **kwargs):
    """便捷函数：打印错误表格"""
    LogTable.print_error_table(*args, **kwargs)
