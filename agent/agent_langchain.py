#!/usr/bin/env python3
"""
【主版本】基于LangChain官方create_agent实现 - 参考EchoMind架构
✅  内置工具调用限制，解决递归死循环问题
✅  性能优异，智能性更高
✅  完全兼容原有接口
"""

import os
import json
import re
import subprocess
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional, Callable
from langchain_core.tools import StructuredTool
from langchain.agents import create_agent
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, AIMessageChunk
from langgraph.checkpoint.memory import MemorySaver
from langchain_openai import ChatOpenAI
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from .config import (
    MAX_ITERATIONS,
    RECURSION_LIMIT,
    SKILLS_DIR,
    SKILL_FILE_NAMES,
    TERMUX_API_CHECK_CMD,
    TERMUX_API_INSTALL_GUIDE
)
from .prompts.agent_enhance import prompt as agent_enhance_prompt


# ── 基础工具实现（保持原有功能）─────────────────────────────────────────────
def file_read(filepath: str, max_lines: int = 100) -> str:
    """
    读取文件内容。

    Args:
        filepath: 文件路径（支持相对于项目根目录的相对路径）
        max_lines: 最大读取行数，默认100
    """
    try:
        # 支持相对路径：优先尝试相对于项目根目录
        if not os.path.isabs(filepath):
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            filepath = os.path.join(project_root, filepath)

        if not os.path.exists(filepath):
            return f"文件不存在: {filepath}"

        with open(filepath, 'r', encoding='utf-8') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append("... (已截止)")
                    break
                lines.append(f"{i+1:3d}| {line.rstrip()}")

        return "\n".join(lines)
    except Exception as e:
        return f"读取文件错误: {str(e)}"

def file_write(filepath: str, content: str, append: bool = False) -> str:
    """
    写入文件内容。

    Args:
        filepath: 文件路径
        content: 要写入的内容
        append: 是否追加模式，默认False
    """
    try:
        mode = 'a' if append else 'w'
        with open(filepath, mode, encoding='utf-8') as f:
            f.write(content)

        action = "追加" if append else "写入"
        return f"文件{action}成功: {filepath}"
    except Exception as e:
        return f"写入文件错误: {str(e)}"

def file_search(pattern: str, filepath: str, context_lines: int = 2) -> str:
    """
    在文件中搜索内容。

    Args:
        pattern: 正则表达式模式
        filepath: 要搜索的文件路径
        context_lines: 上下文行数，默认2
    """
    try:
        if not os.path.exists(filepath):
            return f"文件不存在: {filepath}"

        matches = []
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if re.search(pattern, line):
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)

                context = []
                for j in range(start, end):
                    marker = ">>> " if j == i else "    "
                    context.append(f"{marker}{j+1:3d}| {lines[j].rstrip()}")

                matches.append("\n".join(context))

        if matches:
            return f"找到 {len(matches)} 个匹配:\n\n" + "\n\n".join(matches)
        else:
            return f"未找到匹配 '{pattern}' 的内容"
    except Exception as e:
        return f"搜索错误: {str(e)}"

def directory_list(directory: str, pattern: str = "*") -> str:
    """
    列出目录内容。

    Args:
        directory: 目录路径
        pattern: 文件名筛选模式，默认*
    """
    try:
        if not os.path.exists(directory):
            return f"目录不存在: {directory}"

        items = []
        for item in os.listdir(directory):
            full_path = os.path.join(directory, item)
            if os.path.isdir(full_path):
                items.append(f"{item}/")
            else:
                size = os.path.getsize(full_path)
                items.append(f"{item} ({size} bytes)")

        if items:
            return f"目录 '{directory}' 内容:\n" + "\n".join(sorted(items))
        else:
            return f"目录 '{directory}' 为空"
    except Exception as e:
        return f"查看目录错误: {str(e)}"


def system_info(info_type: str = "all") -> str:
    """
    【Termux专用】获取手机系统信息。
    需要先安装Termux API：pkg install termux-api && 安装手机端Termux:API应用

    Args:
        info_type: 信息类型: all/battery/cpu/memory/disk/network/device/wifi，默认all
    """
    def _run_termux_cmd(cmd: str) -> str:
        """执行Termux API命令，处理异常"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                try:
                    # 尝试格式化JSON输出
                    data = json.loads(result.stdout.strip())
                    return json.dumps(data, ensure_ascii=False, indent=2)
                except:
                    return result.stdout.strip()
            else:
                return f"命令执行失败: {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "命令执行超时"
        except Exception as e:
            return f"执行错误: {str(e)}"

    try:
        # 检测是否安装了termux-api
        check = subprocess.run(TERMUX_API_CHECK_CMD, shell=True, capture_output=True)
        if check.returncode != 0:
            return TERMUX_API_INSTALL_GUIDE + "\n基础存储信息：\n" + _run_termux_cmd("df -h /sdcard")

        result = []
        info_type = info_type.lower()

        if info_type in ["all", "battery"]:
            result.append("📱 电池信息:")
            result.append(_run_termux_cmd("termux-battery-status"))
            result.append("")

        if info_type in ["all", "cpu"]:
            result.append("⚡ CPU信息:")
            result.append(_run_termux_cmd("termux-cpu-info"))
            result.append("")

        if info_type in ["all", "memory"]:
            result.append("💾 内存信息:")
            result.append(_run_termux_cmd("termux-memory-info"))
            result.append("")

        if info_type in ["all", "disk", "storage"]:
            result.append("💽 存储信息:")
            result.append(_run_termux_cmd("df -h /sdcard"))
            result.append(_run_termux_cmd("df -h /data"))
            result.append("")

        if info_type in ["all", "network"]:
            result.append("🌐 网络信息:")
            result.append(_run_termux_cmd("termux-network-status"))
            result.append("")

        if info_type in ["all", "device"]:
            result.append("🔧 设备信息:")
            result.append(_run_termux_cmd("termux-telephony-deviceinfo"))
            result.append("")

        if info_type in ["all", "wifi"]:
            result.append("📶 WiFi信息:")
            result.append(_run_termux_cmd("termux-wifi-connectioninfo"))
            result.append("")

        if not result:
            return f"不支持的信息类型 '{info_type}'\n支持的类型: all/battery/cpu/memory/disk/network/device/wifi"

        return "\n".join(result).strip()

    except Exception as e:
        return f"获取系统信息错误: {str(e)}"

def shell_exec(command: str) -> str:
    """
    执行shell命令，返回命令输出。

    Args:
        command: 要执行的shell命令
    """
    # 截断过长的命令显示（最多50字符）
    def truncate_cmd(cmd: str, max_len: int = 50) -> str:
        return cmd[:max_len] + "..." if len(cmd) > max_len else cmd

    truncated_cmd = truncate_cmd(command)

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        output = result.stdout.strip()
        error = result.stderr.strip()

        if result.returncode != 0:
            return f"执行命令: {truncated_cmd}\n命令执行失败 (错误码 {result.returncode}):\n{error}"

        if output:
            return f"执行命令: {truncated_cmd}\n{output}"
        else:
            return f"执行命令: {truncated_cmd}\n命令执行成功，无输出"

    except subprocess.TimeoutExpired:
        return f"执行命令: {truncated_cmd}\n命令执行超时"
    except Exception as e:
        return f"执行命令: {truncated_cmd}\n执行命令错误: {str(e)}"

def load_skills_list() -> str:
    """
    预加载所有可用技能的名称和描述，用于系统提示词
    返回格式化为列表的技能信息
    """
    skills_dir = SKILLS_DIR

    if not os.path.exists(skills_dir):
        return "暂无可用技能。"

    skills = []
    for d in os.listdir(skills_dir):
        skill_dir = os.path.join(skills_dir, d)
        if not os.path.isdir(skill_dir):
            continue

        # 支持配置的技能文件名称（大小写）
        skill_path = None
        for filename in SKILL_FILE_NAMES:
            candidate_path = os.path.join(skill_dir, filename)
            if os.path.exists(candidate_path):
                skill_path = candidate_path
                break

        if os.path.exists(skill_path):
            # 只读取技能元数据（名称+描述），不读取完整内容
            try:
                with open(skill_path, 'r', encoding='utf-8') as f:
                    desc = ""
                    # 只读取前20行找description，避免大文件占用token
                    for _ in range(20):
                        line = f.readline()
                        if not line:
                            break
                        if line.startswith("description:"):
                            desc = line.split(":", 1)[1].strip()
                            break
                skills.append(f"- {d}: {desc}")
            except Exception as e:
                skills.append(f"- {d}: 无描述")

    if not skills:
        return "暂无可用技能。"

    skills_text = "\n".join(skills)
    usage_note = f"\n\n使用说明：需要使用某个技能时，用file_read工具读取对应SKILL.md文件即可，例如：file_read(filepath='{SKILLS_DIR}/neuralbridge-operation-standard/SKILL.md')"

    return skills_text + usage_note


# ── 工具初始化 ──────────────────────────────────────────────
ALL_TOOLS = [
    StructuredTool.from_function(file_read),
    StructuredTool.from_function(file_write),
    StructuredTool.from_function(file_search),
    StructuredTool.from_function(directory_list),
    StructuredTool.from_function(system_info),
    StructuredTool.from_function(shell_exec),
]




# ── 工具调用ID修复中间件 ──────────────────────────────────────────────
# 某些LLM（如GLM系列）生成的tool_call缺少id字段，
# 导致LangGraph的ToolNode创建ToolMessage时tool_call_id为空报错
import uuid

class ToolCallIdMiddleware(AgentMiddleware):
    """确保所有工具调用都有有效的id字段"""

    def wrap_model_call(self, request, handler):
        response = handler(request)
        return self._fix_tool_call_ids(response)

    async def awrap_model_call(self, request, handler):
        response = await handler(request)
        return self._fix_tool_call_ids(response)

    def _fix_tool_call_ids(self, response):
        result = list(response.result)
        modified = False
        for i, msg in enumerate(result):
            if isinstance(msg, AIMessage) and hasattr(msg, 'tool_calls') and msg.tool_calls:
                fixed_calls = []
                for tc in msg.tool_calls:
                    if not tc.get("id") or not isinstance(tc["id"], str) or tc["id"] == "":
                        tc = dict(tc)
                        tc["id"] = f"call_{uuid.uuid4().hex[:12]}"
                        fixed_calls.append(tc)
                        modified = True
                    else:
                        fixed_calls.append(tc)
                if modified:
                    result[i] = AIMessage(
                        content=msg.content,
                        tool_calls=fixed_calls,
                        additional_kwargs=msg.additional_kwargs,
                        response_metadata=msg.response_metadata,
                        id=msg.id,
                    )
        if modified:
            return ModelResponse(result=result, structured_response=response.structured_response)
        return response


# ── Agent 核心实现 ──────────────────────────────────────────────
class LangChainPocketAgent:
    """
    基于LangChain官方create_agent实现的PocketAgent
    参考EchoMind架构，内置工具调用限制，解决递归死循环问题
    """

    def __init__(
        self,
        system_prompt: str = "",
        llm_config: Dict[str, Any] = None,
        ui=None,
        max_iterations: int = 50,
    ):
        self.ui = ui
        self.base_system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.llm_config = llm_config or {}

        # 初始化LLM
        self._init_llm()

        # 创建Agent
        self._create_agent()

        # 会话配置：recursion_limit从配置文件读取，作为极端情况的底层兜底
        # 正常情况下max_iterations会先生效，优雅停止；极端情况recursion_limit兜底报错
        self.config = {
            "configurable": {
                "thread_id": "default-session"
            },
            "recursion_limit": RECURSION_LIMIT
        }

        # 暴露工具列表
        self.tools = ALL_TOOLS

    def _init_llm(self) -> None:
        """初始化LLM客户端"""
        default_config = {
            "base_url": "http://127.0.0.1:8080/v1",
            "api_key": "dummy",
            "model": "gelab-zero-4b-preview",
            "temperature": 0.7,
            "max_tokens": 8000,
            "timeout": 30,
        }
        config = {**default_config, **self.llm_config}

        # 初始化ChatOpenAI客户端
        self.llm = ChatOpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"],
            model=config["model"],
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            timeout=config["timeout"],
            streaming=True,
            verbose=False
        )

    def _create_agent(self) -> None:
        """使用官方create_agent创建Agent，内置中间件限制工具调用"""
        # 预加载技能列表
        skills_list = load_skills_list()

        # 动态注入工具列表和技能列表到增强提示词
        tool_names = ", ".join([tool.name for tool in ALL_TOOLS])
        enhanced_system_prompt = self.base_system_prompt + "\n\n" + agent_enhance_prompt.format(
            tool_names=tool_names,
            skills_list=skills_list
        )

        # 配置中间件
        middleware = [
            # 修复工具调用ID：某些LLM生成的tool_call缺少id字段
            ToolCallIdMiddleware(),
            # 模型调用次数限制：单次运行最多调用MAX_ITERATIONS次模型（对应最多MAX_ITERATIONS轮迭代）
            # 达到限制后自动优雅结束，不会报错
            ModelCallLimitMiddleware(
                run_limit=MAX_ITERATIONS,
                exit_behavior="end",
            )
        ]

        # 持久化存储
        self.checkpointer = MemorySaver()

        # 使用官方create_agent创建Agent，递归限制在config中配置
        self.agent = create_agent(
            model=self.llm,
            tools=ALL_TOOLS,
            system_prompt=enhanced_system_prompt,
            checkpointer=self.checkpointer,
            middleware=middleware,
        )

    async def run_conversation(self, user_message: str) -> Tuple[str, bool]:
        """
        运行对话
        Args:
            user_message: 用户输入消息
        Returns:
            (响应内容, 是否使用了流式输出)
        """
        try:
            full_response = ""
            progress_display = None

            # 初始化进度显示
            if self.ui and hasattr(self.ui, 'create_progress_display'):
                progress_display = self.ui.create_progress_display()
                progress_display.__enter__()
                progress_display.update("思考中")

            # 使用多种stream模式同时获取消息流和执行更新
            async for chunk in self.agent.astream(
                {"messages": [HumanMessage(content=user_message)]},
                config=self.config,
                stream_mode=["messages", "updates"],
                version="v2"
            ):
                # 刷新进度时间（每次收到chunk都更新，让时间走动）
                if progress_display:
                    progress_display.update()

                # 处理消息流（用于流式输出回复内容）
                if chunk["type"] == "messages":
                    message_chunk, metadata = chunk["data"]
                    node = metadata.get("langgraph_node", "")

                    if node == "model" and hasattr(message_chunk, "content") and message_chunk.content:
                        # 如果是首次收到内容，先关闭进度显示
                        if progress_display:
                            progress_display.__exit__(None, None, None)
                            progress_display = None

                        # 实时输出到UI
                        if self.ui and hasattr(self.ui, 'print_stream_chunk'):
                            self.ui.print_stream_chunk(message_chunk.content)
                        # 收集完整响应
                        full_response += message_chunk.content

                # 处理更新事件（用于进度显示）
                elif chunk["type"] == "updates" and progress_display:
                    for source, update in chunk["data"].items():
                        if source == "model":
                            # 模型正在思考或生成工具调用
                            message = update["messages"][-1]
                            if hasattr(message, 'tool_calls') and message.tool_calls:
                                # 检测到工具调用
                                for tc in message.tool_calls:
                                    tool_name = tc["name"]
                                    tool_args = tc["args"]

                                    # 特殊处理shell_exec，显示命令内容
                                    if tool_name == "shell_exec" and "command" in tool_args:
                                        command = tool_args["command"]
                                        # 截断过长的命令
                                        display_cmd = command[:50] + "..." if len(command) > 50 else command
                                        if self.ui and hasattr(self.ui, 'print_info'):
                                            self.ui.print_info(f"执行命令: {command}")
                                        progress_display.update(f"执行: {display_cmd}")
                                    else:
                                        # 其他工具显示名称和参数
                                        args_text = ", ".join([f"{k}={v}" for k, v in tool_args.items()])
                                        args_text = args_text[:30] + "..." if len(args_text) > 30 else args_text
                                        progress_display.update(f"调用: {tool_name}({args_text})")
                            else:
                                progress_display.update("思考中")
                        elif source == "tools":
                            # 工具执行完成
                            message = update["messages"][-1]
                            tool_name = message.name if hasattr(message, 'name') else "工具"
                            progress_display.update(f"处理 {tool_name} 结果")

            # 关闭进度显示
            if progress_display:
                progress_display.__exit__(None, None, None)

            # 如果stream没有返回内容（极端情况），回退到ainvoke
            if not full_response:
                result = await self.agent.ainvoke(
                    {"messages": [HumanMessage(content=user_message)]},
                    config=self.config
                )
                last_message = result["messages"][-1]
                full_response = str(last_message.content).strip()

            # 回复结束后换行
            if self.ui and full_response:
                self.ui.console.print()

            return (full_response.strip(), True)

        except Exception as e:
            # 确保进度显示被关闭
            if 'progress_display' in locals() and progress_display:
                progress_display.__exit__(type(e), e, None)

            import traceback
            error_details = traceback.format_exc()
            error_msg = f"Agent 执行错误: {str(e)}\n{error_details[:800]}"
            return (error_msg, False)

    def clear_history(self) -> None:
        """清空对话历史"""
        # 生成新的thread_id，重置会话
        import uuid
        self.config = {
            "configurable": {
                "thread_id": str(uuid.uuid4())
            },
            "recursion_limit": self.max_iterations
        }
