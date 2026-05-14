#!/usr/bin/env python3
"""
LangChain 适配层
包含持久化 Checkpointer、工具封装、中间件实现
"""

import os
import json
import asyncio
from typing import Optional, Dict, Any, List, Callable
from collections import defaultdict
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint
from langchain.agents.middleware import wrap_tool_call
from langchain_core.tools import tool, StructuredTool
from pydantic import BaseModel, create_model

# 懒加载superpowers实例，避免Windows编码问题
pocket_superpowers = None

def _get_superpowers():
    """延迟加载superpowers"""
    global pocket_superpowers
    if pocket_superpowers is None:
        try:
            from core.superpowers import pocket_superpowers as _pocket_superpowers
            pocket_superpowers = _pocket_superpowers
        except ImportError:
            pocket_superpowers = None
    return pocket_superpowers


# ── 持久化 Checkpointer 实现 ──────────────────────────────────────────────
class PocketCheckpointer(BaseCheckpointSaver):
    """自定义持久化检查点，保存对话状态到本地JSON文件"""

    def __init__(self, save_path: str = "memory/conversations"):
        self.save_path = save_path
        os.makedirs(save_path, exist_ok=True)

    def get(self, config: Dict[str, Any]) -> Optional[Checkpoint]:
        thread_id = config["configurable"]["thread_id"]
        file_path = os.path.join(self.save_path, f"{thread_id}.json")
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    # Checkpoint 是 dict 子类，直接构造
                    return Checkpoint(data)
            except Exception as e:
                # 文件损坏时返回None，自动创建新会话
                return None
        return None

    def put(self, config: Dict[str, Any], checkpoint: Checkpoint) -> None:
        thread_id = config["configurable"]["thread_id"]
        file_path = os.path.join(self.save_path, f"{thread_id}.json")
        try:
            # Checkpoint 是 dict 子类，直接序列化
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(dict(checkpoint), f, ensure_ascii=False, indent=2)
        except Exception as e:
            # 保存失败时静默处理，不影响对话
            pass

    def list(self, config: Optional[Dict[str, Any]] = None) -> List[str]:
        """列出所有历史会话ID"""
        if not os.path.exists(self.save_path):
            return []
        return [f[:-5] for f in os.listdir(self.save_path) if f.endswith(".json")]


# ── 中间件实现 ──────────────────────────────────────────────
# 反死循环状态
_tool_call_counts = defaultdict(int)
_recent_responses = []
_loop_detection_enabled = True

@wrap_tool_call
async def anti_loop_middleware(tool_call, next_middleware):
    """反死循环检测中间件"""
    if not _loop_detection_enabled:
        return await next_middleware(tool_call)

    tool_name = tool_call["name"]

    # 检测同一工具连续调用超过5次
    _tool_call_counts[tool_name] += 1
    if _tool_call_counts[tool_name] > 5:
        # 重置计数器
        _tool_call_counts.clear()
        return f"⚠️ 工具 {tool_name} 连续调用超过5次，已中断。请尝试其他方式解决问题。"

    # 执行工具
    result = await next_middleware(tool_call)

    # 检测重复响应
    result_str = str(result)[:200]
    _recent_responses.append(result_str)
    if len(_recent_responses) > 10:
        _recent_responses.pop(0)

    if len(_recent_responses) >= 3 and len(set(_recent_responses[-3:])) == 1:
        # 检测到重复响应，重置状态
        _recent_responses.clear()
        _tool_call_counts.clear()
        return "⚠️ 检测到重复响应，疑似死循环。请重新表述问题。"

    return result


@wrap_tool_call
async def mcp_health_check_middleware(tool_call, next_middleware):
    """MCP服务健康检测中间件"""
    tool_name = tool_call["name"]

    # 安卓工具调用前检测NeuralBridge服务
    if tool_name.startswith("android_"):
        try:
            proc = await asyncio.create_subprocess_shell(
                "nc -zv 127.0.0.1 7474 || curl -s http://127.0.0.1:7474/health",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return "❌ NeuralBridge服务未运行，请先启动安卓控制服务。"
        except:
            # 检测失败时继续执行，让工具自己处理错误
            pass

    # Context7工具调用前检测服务
    elif tool_name.startswith("context7_"):
        try:
            proc = await asyncio.create_subprocess_shell(
                "nc -zv 127.0.0.1 3007 || curl -s http://127.0.0.1:3007/health",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                return "❌ Context7文档服务未运行。"
        except:
            pass

    # 执行工具
    try:
        result = await next_middleware(tool_call)
        return result
    except Exception as e:
        return f"❌ 工具执行失败: {str(e)}"


# ── Superpowers 技能适配器 ──────────────────────────────────────────────
@tool
def superpowers_command(command: str) -> str:
    """
    执行superpowers技能命令。
    使用格式: superpowers <子命令> [参数]
    可用子命令: help/analyze/generate-docs/review-code/debug

    Args:
        command: 完整的superpowers命令，如 "superpowers analyze ."
    """
    sp = _get_superpowers()
    if not sp:
        return "❌ superpowers功能未启用"

    cmd_parts = command.lower().split()
    if len(cmd_parts) < 2:
        return sp.skill.help()

    action = cmd_parts[1]
    if action == 'help':
        return sp.skill.help()
    elif action == 'analyze':
        path = cmd_parts[2] if len(cmd_parts) > 2 else "."
        return sp.analyze_project(path)
    elif action == 'generate-docs':
        return sp.generate_docs()
    elif action == 'review-code':
        file_path = cmd_parts[2] if len(cmd_parts) > 2 else "main.py"
        return sp.review_code(file_path)
    elif action == 'debug':
        debug_desc = " ".join(cmd_parts[2:]) if len(cmd_parts) > 2 else ""
        return sp.debug_system(debug_desc)
    else:
        return f"❌ 未知命令: {action}\n请使用 'superpowers help' 查看可用命令"


# ── 现有工具到LangChain工具转换器 ──────────────────────────────────────────────
def convert_to_langchain_tool(old_tool: Callable) -> StructuredTool:
    """
    将现有带有_tool_info属性的工具转换为LangChain标准StructuredTool
    """
    if not hasattr(old_tool, "_tool_info"):
        raise ValueError(f"工具 {old_tool.__name__} 没有_tool_info属性")

    tool_info = old_tool._tool_info
    name = tool_info["name"]
    description = tool_info["description"]
    parameters = tool_info["parameters"]

    # 从JSON Schema创建Pydantic模型
    properties = parameters.get("properties", {})
    required = parameters.get("required", [])

    # 构建字段定义
    fields = {}
    for param_name, param_def in properties.items():
        param_type = param_def.get("type", "string")
        param_desc = param_def.get("description", "")

        # 类型映射
        type_mapping = {
            "string": str,
            "integer": int,
            "boolean": bool,
            "number": float,
            "array": list,
            "object": dict
        }
        python_type = type_mapping.get(param_type, str)

        # 设置默认值
        if param_name in required:
            fields[param_name] = (python_type, ...)
        else:
            default = param_def.get("default", None)
            fields[param_name] = (python_type, default)

    # 创建Pydantic模型
    ToolSchema = create_model(f"{name}Schema", **fields)

    # 创建LangChain工具
    langchain_tool = StructuredTool(
        name=name,
        description=description,
        func=old_tool,
        args_schema=ToolSchema
    )

    return langchain_tool


def convert_all_tools(old_tools: List[Callable]) -> List[StructuredTool]:
    """批量转换工具列表"""
    return [convert_to_langchain_tool(tool) for tool in old_tools]
