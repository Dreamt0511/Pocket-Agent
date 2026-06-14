#!/usr/bin/env python3
"""
Rich UI 组件 - 美化终端界面
参考 CyberClaw 的 UI 设计
"""

import sys
import os
import time
import asyncio
from datetime import datetime
from typing import Optional, List

from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.live import Live
from rich.markdown import Markdown
from rich.rule import Rule

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style
from prompt_toolkit.key_binding import KeyBindings


class SlashCompleter(Completer):
    """自动补全：/命令 和 技能名"""

    def __init__(self):
        self.slash_commands = {
            "/resume": "恢复历史会话",
            "/undo": "撤回上一条消息",
            "/clear": "清空对话历史并清屏",
        }
        self.skills: List[str] = []
        self.skill_descs: dict = {}

    def update_skills(self, skills: List[str], descriptions: dict = None):
        """更新技能列表"""
        self.skills = skills
        self.skill_descs = descriptions or {}

    def _get_slash_completions(self, word: str) -> list:
        """返回匹配的 / 命令补全"""
        word_lower = word.lower()
        matches = []
        for cmd, desc in self.slash_commands.items():
            if cmd.startswith(word_lower):
                display_meta = f" 📋 {desc}" if desc else ""
                matches.append(Completion(cmd, -len(word), display_meta=display_meta))
        return matches

    def _get_skill_completions(self, word: str) -> list:
        """返回匹配的技能补全"""
        word_lower = word.lower()
        matches = []
        stripped = word_lower[1:] if word_lower.startswith('/') else word_lower
        for skill in self.skills:
            skill_lower = skill.lower()
            if skill_lower.startswith(stripped) or stripped in skill_lower:
                desc = self.skill_descs.get(skill, "")
                display_meta = f" 📖 {desc[:40]}" if desc else ""
                matches.append(Completion(f"/{skill}", -len(word), display_meta=display_meta))
        return matches

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith('/'):
            return
        yield from self._get_slash_completions(text)
        if not any(text == cmd for cmd in self.slash_commands):
            yield from self._get_skill_completions(text)


class PocketUI:
    """
    Pocket-Agent 的 Rich UI 管理
    """

    def __init__(self):
        self.console = Console()
        # 初始化输入会话，带历史记录
        history_path = os.path.expanduser("~/.pocket_agent_history")
        self._completer = SlashCompleter()
        self._kb = KeyBindings()
        @self._kb.add('escape')
        def _(event):
            event.app.exit(exception=KeyboardInterrupt())
        self._style = Style([
            ('completion-menu', 'bg: #000000 fg: #cccccc'),
            ('completion-menu.completion', 'bg: #000000 fg: #cccccc'),
            ('completion-menu.completion.current', 'bg: #333333 fg: #ffffff'),
        ])
        self.prompt_session = PromptSession(
            history=FileHistory(history_path),
            completer=self._completer,
            complete_while_typing=True,
            style=self._style,
            key_bindings=self._kb,
        )

    def update_skill_completions(self, skills: List[str], descriptions: dict = None):
        """更新技能补全列表"""
        self._completer.update_skills(skills, descriptions)

    def print_banner(self, model_name: str = "", body_url: str = ""):
        """打印首页横幅"""
        model_line = f"\n{model_name}" if model_name else ""
        body_line = f"\n前往 {body_url} 与机器人交互" if body_url else ""
        banner = f"""

  █▀█ █▀█ █▀▀ █ █ █▀▀ ▀█▀   █▀█ █▀▀ █▀▀ █▀█ ▀█▀
 █▀▀ █ █ █   █▀▄ █▀▀  █    █▀█ █ █ █▀▀ █ █  █
 ▀   ▀▀▀ ▀▀▀ ▀ ▀ ▀▀▀  ▀    ▀ ▀ ▀▀▀ ▀▀▀ ▀ ▀  ▀

  Pocket-Agent — 移动端AI代理帮手

  轻量、快速、智能{model_line}{body_line}
        """

        self.console.print(Panel(
            Text(banner, justify="center", style="bold cyan"),
            border_style="blue",
            padding=(1, 2)
        ))
        # 底部指令提示（仅一开头打印一次）
        self.console.print("[#666666]/resume 恢复会话 | /undo 撤回 | /clear 清屏 | q 退出 | ESC打断 | Tab补全[/#666666]")

    def print_tool_call(self, tool_name: str, params: dict):
        """打印工具调用"""
        params_text = ", ".join([f"{k}={v}" for k, v in params.items()])

        self.console.print(Panel(
            f"✨ 调用 {tool_name}({params_text})",
            border_style="green",
            padding=(0, 1)
        ))

    def print_tool_result(self, result: str):
        """打印工具结果"""
        self.console.print(Panel(
            result[:500] + "..." if len(result) > 500 else result,
            title="✅ 工具返回",
            border_style="cyan",
            padding=(0, 1)
        ))

    def print_agent_thinking(self):
        """打印代理思考中"""
        self.console.print(
            Panel(
                Text(" ⏳ 代理正在思考...", style="italic yellow"),
                border_style="yellow",
                padding=(0, 1)
            )
        )

    def print_agent_response(self, response: str):
        """打印AI回复 - 渲染Markdown格式"""
        # 移除首尾空白，保留结构
        response = response.strip()
        # 使用Rich的Markdown渲染
        self.console.print(Markdown(response))
        self.console.print()

    def print_user_input_prompt(self):
        """同步版本用户输入提示 - 捕获所有异常避免报错栈"""
        try:
            # 非交互模式
            if not sys.stdin.isatty():
                self.console.print("[bold green]🪀 你:[/bold green] ", end="")
                input_text = sys.stdin.readline().rstrip('\n')
                return input_text

            # 交互模式：简单分隔线 + 输入提示符
            self.console.print()
            self.console.print(Rule(style="dim cyan"))

            # 使用prompt_toolkit输入
            user_input = self.prompt_session.prompt(
                "🪀 你: ",
                enable_history_search=True
            )
            return user_input
        except (EOFError, KeyboardInterrupt, SystemExit):
            # 处理所有退出相关的异常
            self.console.print()
            return "exit"
        except Exception:
            # 捕获其他任何异常，避免报错栈输出
            self.console.print()
            return "exit"

    async def async_print_user_input_prompt(self):
        """异步用户输入 — 使用prompt_toolkit支持退格删除和编辑"""
        try:
            if not sys.stdin.isatty():
                self.console.print("[bold green]🪀 你:[/bold green] ", end="")
                loop = asyncio.get_event_loop()
                input_text = await loop.run_in_executor(None, sys.stdin.readline)
                return input_text.rstrip('\n')

            self.console.print()
            self.console.print(Rule(style="dim cyan"))

            # 使用prompt_toolkit的异步输入，支持退格/方向键/历史
            # 注意：不使用patch_stdout避免CPU高占用
            user_input = await self.prompt_session.prompt_async("🪀 你: ")
            # 确保返回值被正确清理
            return user_input.strip() if user_input else ""
        except (EOFError, KeyboardInterrupt):
            self.console.print()
            return "exit"
        except Exception:
            self.console.print()
            return "exit"


    def print_memory_info(self, memory_content: str):
        """打印记忆信息"""
        self.console.print(Panel(
            memory_content[:300] + "..." if len(memory_content) > 300 else memory_content,
            title="📚 记忆提取",
            border_style="magenta",
            padding=(0, 1)
        ))

    def print_system_info(self, info: str):
        """打印系统信息"""
        self.console.print(
            Panel(
                info,
                title="💭 系统信息",
                border_style="dim",
                padding=(0, 1)
            )
        )

    def show_loading_spinner(self, task_description: str):
        """显示加载中动画"""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True
        ) as progress:
            progress.add_task(task_description, total=None)
            time.sleep(1)  # 模拟加载

    def print_stream_chunk(self, chunk: str):
        """逐字打印流式输出块，模拟打字机效果（和横幅一样的青蓝色）"""
        self.console.print(chunk, end="", style="bold cyan", no_wrap=True, overflow="crop")
        self.console.file.flush()

    def print_streaming(self, text: str):
        """打印流式文本"""
        self.console.print(f"[cyan]正在流式输出: {text}[/cyan]", end="", flush=True)

    def print_error(self, error_msg: str):
        """打印错误信息"""
        self.console.print(
            Panel(
                f"⚠️ {error_msg}",
                border_style="red",
                style="bold red"
            )
        )

    def print_conversation_stats(self, tool_calls: int, tools_available: int):
        """打印对话统计信息"""
        self.console.print(
            Panel(
                f"📊 对话统计\n• 工具调用次数: {tool_calls}\n• 可用工具数: {tools_available}",
                title="💡 统计",
                border_style="dim cyan",
                padding=(0, 1)
            )
        )

    def print_success(self, msg: str):
        """打印成功信息"""
        self.console.print(f"[bold green]{msg}[/bold green]")

    def print_info(self, msg: str):
        """打印提示信息"""
        self.console.print(f"[dim yellow]💡 {msg}[/dim yellow]")

    def print_warning(self, msg: str):
        """打印警告信息"""
        self.console.print(f"[bold orange]⚠️  {msg}[/bold orange]")

    def create_ascii_art(self, text: str) -> str:
        """生成简单的ASCII艺术"""
        ascii_art = f"""
{'=' * (len(text) + 4)}
  {text}
{'=' * (len(text) + 4)}
        """
        return ascii_art.strip()

    def show_welcome_screen(self, model_name: str = "", body_url: str = ""):
        """显示欢迎界面 — 只保留蓝框横幅"""
        self.console.clear()
        self.print_banner(model_name, body_url)

    def create_progress_display(self):
        """创建实时进度显示，使用Live组件实现单行更新"""
        return ProgressDisplay(self.console)

    @staticmethod
    def format_context_bar(usage: dict) -> str:
        """生成图形化上下文用量条
        Args:
            usage: {"current": int, "max": int, "percentage": float}
        Returns:
            Rich标记格式的字符串，如 "████████░░░░ 45% (58K/128K)"
        """
        current = usage.get("current", 0)
        max_tokens = usage.get("max", 128000)
        pct = usage.get("percentage", 0.0)

        # 20格的Unicode进度条
        bar_width = 20
        filled = int(bar_width * pct / 100)
        filled = max(0, min(bar_width, filled))
        bar = "█" * filled + "░" * (bar_width - filled)

        # 数值格式化：统一添加tok单位
        def fmt(n):
            if n >= 1000000:
                return f"{n/1000000:.1f}M"
            elif n >= 1000:
                return f"{n//1000}K"
            return str(n)

        # 颜色随用量变化：绿(<50%) → 黄(50-80%) → 红(>80%)
        if pct < 50:
            color = "green"
        elif pct < 80:
            color = "yellow"
        else:
            color = "red"

        return f"[dim]|[/dim] [{color}]{bar}[/{color}] [dim]{pct}% ({fmt(current)}/{fmt(max_tokens)})[/dim]"


class _TimerRenderable:
    """动态渲染器：每次Live刷新时重新计算耗时，无需外部触发"""

    def __init__(self, display: "ProgressDisplay"):
        self.display = display

    def __rich_console__(self, console, options):
        if not self.display.step_start_time:
            yield Text("⏳ 初始化...")
        else:
            elapsed = int((datetime.now() - self.display.step_start_time).total_seconds())
            yield Text.from_markup(
                f"⏳ {self.display.current_step} [dim][已耗时 {elapsed} 秒][/dim]"
            )


class ProgressDisplay:
    """实时进度显示器，单行更新不累积"""

    def __init__(self, console):
        self.console = console
        self.live = None
        self.current_step = ""
        self.step_start_time = None  # 当前步骤的开始时间
        self.total_start_time = None  # 整个进度的开始时间
        self.total_seconds = 0  # 总耗时，__exit__时记录

    def _update_display(self):
        """强制刷新显示（仅在步骤变化时外部调用，Live会自动以refresh_per_second刷新 _TimerRenderable）"""
        if self.live:
            self.live.update(_TimerRenderable(self))

    def __enter__(self):
        self.live = Live(
            _TimerRenderable(self),  # 传入动态渲染器，每秒自动重算耗时
            console=self.console,
            refresh_per_second=4,
            transient=False
        )
        self.live.__enter__()
        self.total_start_time = datetime.now()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.live:
            self.live.__exit__(exc_type, exc_val, exc_tb)
            if exc_type is None:
                self.total_seconds = int((datetime.now() - self.total_start_time).total_seconds())

    def print_completion(self, suffix: str = ""):
        """打印完成状态行，可选后缀（如token用量条）"""
        self.console.print(f"✅ [dim cyan]完成 (总耗时 {self.total_seconds} 秒)[/dim cyan] {suffix}")

    def update(self, step: str = None):
        """更新当前进度
        Args:
            step: 进度描述，如果为None则只刷新时间
        """
        if not self.live:
            return

        # 如果是新的步骤，重置步骤开始时间
        if step is not None and step != self.current_step:
            self.current_step = step
            self.step_start_time = datetime.now()

        # Live 以 refresh_per_second 自动重新渲染 _TimerRenderable，无需手动调用 live.update()
        # step 变化时重新设置 renderable 以触发新组件的创建
        self._update_display()
