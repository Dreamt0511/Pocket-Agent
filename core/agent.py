#!/usr/bin/env python3
"""
Pocket-Agent - 轻量级移动端AI代理核心
真正的 agent loop，支持 LLM 工具调用
"""

import json
import logging
import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict

# 导入 Skill 类
try:
    from core.superpowers import Skill
except ImportError:
    # 如果无法导入，定义一个简单的占位符类
    class Skill:
        def __init__(self, name: str = "", description: str = "", content: str = ""):
            self.name = name
            self.description = description
            self.content = content


class MessageRole(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    role: MessageRole
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict]] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> Dict:
        result = {"role": self.role.value, "content": self.content}
        if self.name:
            result["name"] = self.name
        if self.tool_calls:
            result["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    func: Callable


class AgentLoopError(Exception):
    """Agent 循环异常（用于中断死循环）"""
    pass


class PocketAgent:
    """
    轻量级AI代理核心类
    真正的 agent loop：LLM 思考 → 工具调用 → 结果反馈 → 再思考 → 最终回复
    """

    def __init__(
        self,
        model_name: str = "default",
        system_prompt: str = "",
        max_iterations: int = 10,
        llm_manager=None,
        ui=None,
    ):
        self.model_name = model_name
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.tools: Dict[str, Tool] = {}
        self.messages: List[Message] = []
        self.skills: Dict[str, Any] = {}
        self.llm_manager = llm_manager
        self.ui = ui  # 添加UI实例用于流式输出

        # 反死循环机制
        self._tool_call_history: List[str] = []       # 记录最近工具调用
        self._recent_responses: List[str] = []         # 记录最近 LLM 响应
        self._tool_call_counts: Dict[str, int] = defaultdict(int)  # 每轮工具调用计数

        # 初始化日志 - 设置为 WARNING 级别以减少冗余信息
        logging.basicConfig(level=logging.WARNING)
        self.logger = logging.getLogger(__name__)

        # 添加系统消息
        if system_prompt:
            self.add_message(MessageRole.SYSTEM, system_prompt)

    def add_tool(self, tool: Tool) -> None:
        """添加工具"""
        self.tools[tool.name] = tool
        # 减少冗余日志输出
        # self.logger.info(f"添加工具: {tool.name}")

    def add_message(
        self,
        role: MessageRole,
        content: str,
        name: Optional[str] = None,
        tool_calls: Optional[List[Dict]] = None,
        tool_call_id: Optional[str] = None,
    ) -> None:
        """添加消息到对话历史"""
        message = Message(
            role=role,
            content=content,
            name=name,
            tool_calls=tool_calls,
            tool_call_id=tool_call_id,
        )
        self.messages.append(message)

    def add_skill(self, name: str, skill: Skill) -> None:
        """添加技能"""
        self.skills[name] = skill
        # 减少冗余日志输出
        # self.logger.info(f"添加技能: {name}")

    def get_available_tools(self) -> List[Dict]:
        """获取可用工具列表（OpenAI tool calling 格式）"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self.tools.values()
        ]

    async def execute_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """执行工具调用"""
        if tool_name not in self.tools:
            return f"错误: 工具 '{tool_name}' 不存在"

        try:
            tool = self.tools[tool_name]
            if asyncio.iscoroutinefunction(tool.func):
                result = await tool.func(**args)
            else:
                result = tool.func(**args)
            return str(result)
        except Exception as e:
            return f"工具执行错误: {str(e)}"

    def _check_safe_guards(self, iteration: int, tool_calls: List[Dict]) -> None:
        """
        反死循环检查，发现异常抛出 AgentLoopError
        """
        # 1. 最大迭代次数（由 for 循环控制，这里做额外提示）
        if iteration >= self.max_iterations:
            raise AgentLoopError(f"达到最大迭代次数 ({self.max_iterations})")

        # 2. 同一轮工具调用太多
        call_sig = json.dumps(
            [[tc["function"]["name"], tc["function"]["arguments"]] for tc in tool_calls],
            sort_keys=True,
        )

        # 检测最近 3 次是否完全重复
        self._tool_call_history.append(call_sig)
        if len(self._tool_call_history) > 4:
            self._tool_call_history.pop(0)

        if len(self._tool_call_history) >= 3:
            last_three = self._tool_call_history[-3:]
            if last_three[0] == last_three[1] == last_three[2]:
                raise AgentLoopError(
                    "检测到重复工具调用循环，中断执行。"
                    f" 重复调用: {[tc['function']['name'] for tc in tool_calls]}"
                )

        # 3. 每轮工具调用累积计数（防止 LLM 无限调用同一个工具）
        for tc in tool_calls:
            self._tool_call_counts[tc["function"]["name"]] += 1
        max_calls_per_tool = max(self._tool_call_counts.values()) if self._tool_call_counts else 0
        if max_calls_per_tool > 5:
            worst = max(self._tool_call_counts, key=self._tool_call_counts.get)
            raise AgentLoopError(f"工具 '{worst}' 被调用了 {max_calls_per_tool} 次，疑似死循环")

        # 4. LLM 连续返回相同内容
        # (在 generate_response 里检测)

    async def generate_response(self, messages: List[Dict]) -> tuple:
        """
        生成响应 — 真正调用 LLM
        返回: (响应字典, 是否使用了流式输出)
        """
        if not self.llm_manager or not self.llm_manager.provider:
            # 没有 LLM 时返回一个提示
            return ({
                "role": "assistant",
                "content": (
                    "⚠️ 未配置 LLM 模型，无法生成智能响应。\n"
                    "请在 .env 中配置 LLM_API_KEY 和相关参数。\n"
                    f"可用工具: {', '.join(self.tools.keys())}"
                ),
                "tool_calls": None,
            }, False)

        tools = self.get_available_tools() if self.tools else None

        try:
            # 尝试使用流式对话（如果有stream_chat方法）
            if hasattr(self.llm_manager, 'stream_chat') and callable(getattr(self.llm_manager, 'stream_chat')):
                content_parts = []
                stream_failed = False
                
                async for chunk in self.llm_manager.stream_chat(messages):
                    # 检查是否是错误消息
                    if isinstance(chunk, str) and chunk.startswith("❌"):
                        stream_failed = True
                        break
                    
                    # 处理字节类型的chunk（某些LLM提供者返回bytes）
                    if isinstance(chunk, bytes):
                        chunk = chunk.decode('utf-8')
                    elif not isinstance(chunk, str):
                        chunk = str(chunk)
                    
                    content_parts.append(chunk)
                    
                    # 实时打印流式输出
                    if hasattr(self, 'ui') and self.ui:
                        self.ui.print_stream_chunk(chunk)
                
                if stream_failed or not content_parts:
                    # 回退到普通对话模式
                    result = await self.llm_manager.chat_with_tools(messages, tools or [])
                else:
                    # 流式完成后换行
                    if hasattr(self, 'ui') and self.ui:
                        self.ui.console.print()
                    
                    content = "".join(content_parts)
                    # 检测流式返回中是否包含工具调用
                    tool_calls = None
                    if "<|FunctionCallBegin|>" in content and "<|FunctionCallEnd|>" in content:
                        try:
                            import re
                            # 提取工具调用内容
                            func_match = re.search(r"<\|FunctionCallBegin\|>(.*?)<\|FunctionCallEnd\|>", content, re.DOTALL)
                            if func_match:
                                func_json = func_match.group(1).strip()
                                func_list = json.loads(func_json)
                                # 转换为OpenAI格式的tool_calls
                                tool_calls = []
                                for i, func in enumerate(func_list):
                                    tool_calls.append({
                                        "id": f"call_{i}",
                                        "type": "function",
                                        "function": {
                                            "name": func["name"],
                                            "arguments": json.dumps(func["parameters"], ensure_ascii=False)
                                        }
                                    })
                                # 清空content，只保留工具调用
                                content = ""
                        except Exception as e:
                            # 解析失败，当做普通文本处理
                            pass
                    
                    return ({
                        "role": "assistant",
                        "content": content,
                        "tool_calls": tool_calls,
                    }, True)  # 标记使用了流式输出
            else:
                # 回退到普通对话
                result = await self.llm_manager.chat_with_tools(messages, tools or [])
        except Exception as e:
            return ({
                "role": "assistant",
                "content": f"❌ LLM 调用失败: {str(e)}",
                "tool_calls": None,
            }, False)

        content = result.get("content") or ""
        tool_calls = result.get("tool_calls")

        # 反死循环：检测连续相同响应
        self._recent_responses.append(content[:200])  # 只比较前200字符
        if len(self._recent_responses) > 4:
            self._recent_responses.pop(0)
        if len(self._recent_responses) >= 3 and len(set(self._recent_responses)) == 1:
            raise AgentLoopError(
                "LLM 连续返回相同内容，疑似死循环。\n"
                f"重复内容: {self._recent_responses[0][:100]}..."
            )

        return ({
            "role": "assistant",
            "content": content,
            "tool_calls": tool_calls,
        }, False)  # 没有使用流式输出

    async def run_conversation(self, user_message: str) -> tuple:
        """
        运行对话循环 — 真正的 agent loop
        返回: (响应内容, 是否使用了流式输出)
        """
        self.add_message(MessageRole.USER, user_message)

        # 重置本轮计数器
        self._tool_call_counts.clear()
        self._tool_call_history.clear()
        self._recent_responses.clear()
        
        # 标记是否使用了流式输出
        used_streaming = False

        for iteration in range(self.max_iterations):
            # 减少冗余日志输出
            # self.logger.info(f"迭代 {iteration + 1}/{self.max_iterations}")

            # 准备消息
            messages_for_api = [msg.to_dict() for msg in self.messages]

            try:
                response, was_streaming = await self.generate_response(messages_for_api)
                if was_streaming:
                    used_streaming = True
            except AgentLoopError as e:
                self.logger.warning(f"Agent 循环中断: {e}")
                msg = f"⚠️ {e}"
                self.add_message(MessageRole.ASSISTANT, msg)
                return (msg, used_streaming)

            # 处理工具调用
            if response.get("tool_calls"):
                # 在工具调用情况下，我们需要记录流式状态但不立即返回
                self.add_message(
                    MessageRole.ASSISTANT,
                    response.get("content") or "",
                    tool_calls=response["tool_calls"],
                )

                # 安全检查（可能抛 AgentLoopError）
                try:
                    self._check_safe_guards(iteration, response["tool_calls"])
                except AgentLoopError as e:
                    self.logger.warning(f"安全中断: {e}")
                    msg = f"⚠️ {e}"
                    self.add_message(MessageRole.ASSISTANT, msg)
                    return (msg, used_streaming)

                # 执行所有工具调用
                for tool_call in response["tool_calls"]:
                    tool_name = tool_call["function"]["name"]
                    try:
                        tool_args = json.loads(tool_call["function"]["arguments"])
                    except json.JSONDecodeError:
                        tool_args = {}

                    # 减少冗余日志输出
                    # self.logger.info(f"执行工具: {tool_name}({tool_args})")
                    result = await self.execute_tool(tool_name, tool_args)

                    # 截断过长结果
                    if len(result) > 4000:
                        result = result[:4000] + "\n...(结果已截断)"

                    self.add_message(
                        MessageRole.TOOL,
                        result,
                        name=tool_name,
                        tool_call_id=tool_call.get("id", ""),
                    )

                continue  # 返回循环，让 LLM 看到工具结果后继续思考

            # 没有工具调用，返回最终响应
            final_response = response.get("content", "")
            self.add_message(MessageRole.ASSISTANT, final_response)
            return (final_response, used_streaming)

        return ("⚠️ 达到最大迭代次数，对话结束。", used_streaming)

    def save_conversation(self, filepath: str) -> None:
        """保存对话历史"""
        data = {
            "model": self.model_name,
            "system_prompt": self.system_prompt,
            "messages": [msg.to_dict() for msg in self.messages],
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_conversation(self, filepath: str) -> None:
        """加载对话历史"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.model_name = data.get("model", self.model_name)
        self.system_prompt = data.get("system_prompt", self.system_prompt)
        self.messages = []
        for msg_data in data.get("messages", []):
            role = MessageRole(msg_data["role"])
            self.add_message(role, msg_data["content"], msg_data.get("name"))


# ── 工具装饰器 ──────────────────────────────────────────────

def tool(name: str, description: str, parameters: Dict[str, Any]):
    """工具装饰器"""
    def decorator(func):
        func._tool_info = {
            "name": name,
            "description": description,
            "parameters": parameters,
        }
        return func
    return decorator


# ── 示例工具 ────────────────────────────────────────────────

@tool(
    name="get_weather",
    description="获取指定位置的天气信息",
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string", "description": "位置名称"}
        },
        "required": ["location"],
    },
)
def get_weather(location: str) -> str:
    """模拟天气查询"""
    return f"{location}的天气: 晴朗, 25°C"


@tool(
    name="calculate",
    description="执行数学计算",
    parameters={
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式"}
        },
        "required": ["expression"],
    },
)
def calculate(expression: str) -> str:
    """简单计算器"""
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return f"{expression} = {result}"
    except Exception as e:
        return f"计算错误: {str(e)}"