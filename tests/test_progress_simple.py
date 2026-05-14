#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单测试进度显示功能，不需要完整UI
"""
import asyncio
from datetime import datetime
from rich.console import Console
from rich.live import Live


class SimpleProgressDisplay:
    """简单的进度显示器，用于测试"""

    def __init__(self, console):
        self.console = console
        self.live = None
        self.current_step = ""
        self.start_time = None

    def __enter__(self):
        self.live = Live(console=self.console, refresh_per_second=4, transient=True)
        self.live.__enter__()
        self.start_time = datetime.now()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.live:
            self.live.__exit__(exc_type, exc_val, exc_tb)
            # 最后显示完成状态
            if exc_type is None:
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.console.print(f"[green]OK[/green] [dim cyan]Finished [{timestamp}][/dim cyan]")

    def update(self, step: str, show_time: bool = True):
        """更新当前进度"""
        if not self.live:
            return

        self.current_step = step
        timestamp = datetime.now().strftime("%H:%M:%S") if show_time else ""

        # 构建显示内容
        if show_time:
            display_text = f"[yellow]...[/yellow] {step} [dim][{timestamp}][/dim]"
        else:
            display_text = f"[yellow]...[/yellow] {step}"

        self.live.update(display_text)


async def test_progress_display():
    """测试进度显示功能"""
    console = Console()

    print("Testing progress display...")
    print("=" * 50)

    # 测试进度条
    with SimpleProgressDisplay(console) as progress:
        progress.update("Initializing...")
        await asyncio.sleep(1)
        progress.update("Loading tools...")
        await asyncio.sleep(1)
        progress.update("Calling tool: file_read")
        await asyncio.sleep(1)
        progress.update("Tool file_read completed")
        await asyncio.sleep(1)
        progress.update("Generating response...")
        await asyncio.sleep(1)

    print("\n[green]Progress display test completed![/green]")
    print("\nFeatures:")
    print("- Single line update, no message accumulation")
    print("- Timestamp shown for each step")
    print("- Checkmark and finish time when done")
    print("- Progress bar disappears when response starts streaming")


if __name__ == "__main__":
    asyncio.run(test_progress_display())