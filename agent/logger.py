#!/usr/bin/env python3
"""
Agent 审计日志系统 - 按天归档，记录每个任务的完整执行链条
"""

import os
import json
from datetime import datetime
from typing import Optional


class AgentLogger:
    """Agent 审计日志记录器"""

    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def _get_today_file(self) -> str:
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"{today}.md")

    def _ts(self) -> str:
        return datetime.now().strftime("[%H:%M:%S]")

    def _write(self, content: str):
        filepath = self._get_today_file()
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(content + "\n")

    # ── 对话生命周期 ──

    def log_conversation_start(self, task_id: str, user_message: str):
        """记录用户输入和对话开始"""
        ts = self._ts()
        self._write(f"\n## {ts} 对话 {task_id}")
        self._write(f"- **用户**: {user_message[:200]}")

    def log_tool_call(self, task_id: str, step_num: int, tool_name: str, args: dict, result: str):
        """记录工具调用及结果"""
        ts = self._ts()
        args_str = json.dumps(args, ensure_ascii=False)[:300]
        result_str = result[:200].replace("\n", " ").strip()
        self._write(f"  {ts} 步骤{step_num} | {tool_name}({args_str})")
        self._write(f"  → {result_str}")

    def log_conversation_end(self, task_id: str, summary: str, tool_count: int, elapsed: int):
        """记录对话结束和统计"""
        ts = self._ts()
        self._write(f"- **完成**: {ts} 耗时{elapsed}s, 调用工具{tool_count}次")
        if summary:
            self._write(f"- **回复摘要**: {summary[:200]}")

    # ── 子Agent执行 ──
    _executor_start_time = None  # 类级别追踪

    def log_executor_start(self, task_id: str, objective: str):
        """记录子Agent任务开始"""
        self._executor_start_time = datetime.now()
        ts = self._ts()
        self._write(f"\n  ### {ts} 子Agent {task_id}")
        self._write(f"  - **目标**: {objective}")

    def log_executor_step(self, task_id: str, step_num: int, tool_name: str, args: dict):
        """记录子Agent的单个执行步骤（调用前）"""
        ts = self._ts()
        args_str = json.dumps(args, ensure_ascii=False)[:300]
        # 计算从上一步到这一步的耗时
        if hasattr(self, '_executor_step_time') and self._executor_step_time:
            elapsed = int((datetime.now() - self._executor_step_time).total_seconds())
            self._write(f"    {ts} 步骤{step_num} | {tool_name}({args_str})  [耗时{elapsed}s]")
        else:
            self._write(f"    {ts} 步骤{step_num} | {tool_name}({args_str})")
        self._executor_step_time = datetime.now()

    def log_executor_end(self, task_id: str, status: str):
        """记录子Agent任务结束"""
        ts = self._ts()
        # 计算总耗时
        if self._executor_start_time:
            total = int((datetime.now() - self._executor_start_time).total_seconds())
            self._write(f"  - **{status}**: {ts}  ⏱️ 子Agent总耗时{total}s")
        else:
            self._write(f"  - **{status}**: {ts}")

    def log_executor_result(self, task_id: str, tool_name: str, result: str):
        """记录子Agent工具执行结果"""
        ts = self._ts()
        result_str = result[:200].replace("\n", " ").strip()
        self._write(f"    → {result_str}")

    # ── 子Agent人工介入 ──

    def log_executor_reasoning(self, task_id: str, reasoning: str):
        """记录子Agent的思考过程（便于排查问题）"""
        if not reasoning or not reasoning.strip():
            return
        ts = self._ts()
        # 取前300字，太长截断
        text = reasoning.strip().replace("\n", " ")[:300]
        self._write(f"    💭 {ts} {text}")

    def log_executor_intervention(self, task_id: str, detail: str, outcome: str = "pending"):
        """记录子Agent申请人工介入的全过程"""
        ts = self._ts()
        if outcome == "pending":
            self._write(f"    🆘 [人工介入] {ts}: {detail}")
            self._write(f"    ⏳ 等待用户手动操作（30秒）...")
        elif outcome == "resolved":
            self._write(f"    ✅ [人工介入已解决] {ts}: {detail}")
        elif outcome == "failed":
            self._write(f"    ❌ [人工介入失败] {ts}: {detail}")

    # ── 简单日志接口（兼容旧调用） ──

    def log_event(self, event_type: str, detail: str, task_id: str = ""):
        """记录单行事件"""
        ts = self._ts()
        tag = f"[{task_id}] " if task_id else ""
        self._write(f"{ts} {tag}{event_type}: {detail[:200]}")
