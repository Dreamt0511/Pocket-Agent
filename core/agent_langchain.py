#!/usr/bin/env python3
"""
基于LangChain的PocketAgent实现
完全兼容原有接口，替换自定义Agent循环
"""

import os
import uuid
from typing import List, Tuple, Dict, Any
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.callbacks import CallbackManager, BaseCallbackHandler
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver

# 导入适配层
from core.langchain_adapter import (
    PocketCheckpointer,
    anti_loop_middleware,
    mcp_health_check_middleware,
    superpowers_command,
    convert_all_tools
)

# 导入现有工具 - 失败时使用空列表不影响基础功能
BASIC_TOOLS = []
ALL_MCP_TOOLS = []
try:
    from tools.basic_tools import ALL_TOOLS as BASIC_TOOLS
except Exception as e:
    print(f"⚠️  基础工具加载失败: {str(e)}")
try:
    from tools.mcp_tools import ALL_MCP_TOOLS
except Exception as e:
    print(f"⚠️  MCP工具加载失败: {str(e)}")


# ── 流式输出回调 ──────────────────────────────────────────────
class StreamingUICallback(BaseCallbackHandler):
    """流式输出回调，对接现有UI系统"""
    def __init__(self, ui=None):
        self.ui = ui
        self.buffer = []

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        """新token回调"""
        if token and self.ui and hasattr(self.ui, 'print_stream_chunk'):
            self.ui.print_stream_chunk(token)
        self.buffer.append(token)

    def get_full_response(self) -> str:
        """获取完整的响应内容"""
        return "".join(self.buffer)


# ── Agent 核心实现 ──────────────────────────────────────────────
class LangChainPocketAgent:
    """
    基于LangChain的PocketAgent实现
    完全兼容原有PocketAgent接口，可以直接替换
    """

    def __init__(
        self,
        model_name: str = "pocket-agent-v1",
        system_prompt: str = "",
        max_iterations: int = 10,
        llm_config: Dict[str, Any] = None,
        ui=None,
    ):
        """
        初始化Agent，参数与原有PocketAgent保持一致

        Args:
            model_name: 模型名称（兼容参数，实际使用llm_config中的配置）
            system_prompt: 系统提示词
            max_iterations: 最大工具调用迭代次数
            llm_config: LLM配置字典，包含base_url、api_key、model等参数
            ui: UI实例，用于流式输出
        """
        self.model_name = model_name
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.ui = ui
        self.llm_config = llm_config or {}

        # 初始化LLM
        self._init_llm()

        # 加载并转换所有工具
        self._init_tools()

        # 初始化持久化记忆
        self.checkpointer = PocketCheckpointer()

        # 初始化会话配置
        self._reset_session()

        # 创建Agent
        self._create_agent()

    def _init_llm(self) -> None:
        """初始化LLM客户端"""
        default_config = {
            "base_url": "http://127.0.0.1:8080/v1",
            "api_key": "dummy",
            "model": "gelab-zero-4b-preview",
            "temperature": 0.7,
            "max_tokens": 8000,
            "timeout": 30,  # 缩短超时时间方便调试
        }
        # 合并配置
        config = {**default_config, **self.llm_config}
        self.llm_config = config  # 保存配置便于调试

        # 创建流式回调
        self.streaming_callback = StreamingUICallback(self.ui)
        callbacks = [self.streaming_callback] if self.ui else []

        # 初始化ChatOpenAI客户端（连接本地llama-server）
        self.llm = ChatOpenAI(
            base_url=config["base_url"],
            api_key=config["api_key"],
            model=config["model"],
            temperature=config["temperature"],
            max_tokens=config["max_tokens"],
            timeout=config["timeout"],
            streaming=True,
            callbacks=callbacks,
            # 禁用客户端日志，减少输出
            verbose=False
        )

    def _init_tools(self) -> None:
        """加载并转换所有工具为LangChain标准格式"""
        self.tools: List[StructuredTool] = []

        # 转换基础工具
        if BASIC_TOOLS:
            try:
                self.tools.extend(convert_all_tools(BASIC_TOOLS))
            except:
                pass

        # 转换MCP工具
        if ALL_MCP_TOOLS:
            try:
                self.tools.extend(convert_all_tools(ALL_MCP_TOOLS))
            except:
                pass

        # 添加superpowers命令工具
        self.tools.append(superpowers_command)

    def _reset_session(self) -> None:
        """重置会话，生成新的thread_id"""
        self.thread_id = str(uuid.uuid4())
        self.config = {
            "configurable": {
                "thread_id": self.thread_id
            },
            # 最大递归深度，防止死循环
            "recursion_limit": self.max_iterations
        }
        # 清空流式缓冲区
        if hasattr(self, 'streaming_callback'):
            self.streaming_callback.buffer.clear()

    def _create_agent(self) -> None:
        """创建LangChain Agent"""
        # 创建Agent
        self.agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=self.system_prompt,
            checkpointer=self.checkpointer,
            # 中间件
            middleware=[
                anti_loop_middleware,
                mcp_health_check_middleware
            ]
        )

    async def run_conversation(self, user_message: str) -> Tuple[str, bool]:
        """
        运行对话，接口与原有实现完全一致

        Args:
            user_message: 用户输入消息

        Returns:
            (响应内容, 是否使用了流式输出)
        """
        import traceback
        try:
            # 清空流式缓冲区
            self.streaming_callback.buffer.clear()

            # 1. 先测试LLM是否正常工作（排除Agent流程问题）
            if hasattr(self, '_debug_mode') and self._debug_mode:
                test_response = await self.llm.ainvoke(f"请回复: 你好，我是测试助手")
                return (f"LLM测试正常: {test_response.content}", False)

            # 调用Agent
            result = await self.agent.ainvoke(
                {"messages": [HumanMessage(content=user_message)]},
                config=self.config
            )

            # 获取最后一条回复
            last_message = result["messages"][-1]

            # 如果已经通过流式输出显示了内容，不需要再返回
            if self.streaming_callback.buffer:
                full_response = self.streaming_callback.get_full_response()
                return (full_response.strip(), True)
            else:
                return (str(last_message.content).strip(), False)

        except Exception as e:
            # 详细错误信息，方便调试
            error_details = traceback.format_exc()
            error_msg = f"❌ Agent 执行错误: {str(e)}\n{error_details[:500]}..."
            return (error_msg, False)

    def clear_history(self) -> None:
        """清空对话历史，创建新会话"""
        self._reset_session()

    def add_message(self, role: Any, content: str, **kwargs) -> None:
        """
        兼容原有接口，添加消息到历史
        注意：LangChain Agent会自动管理消息历史，此方法仅作为兼容保留
        """
        # 对于LangChain，我们不需要手动管理消息，中间件会自动处理
        pass

    def save_conversation(self, filepath: str) -> None:
        """兼容原有接口，保存对话到文件"""
        # LangChain的Checkpointer已经自动持久化，这里可以扩展实现导出功能
        pass

    def load_conversation(self, filepath: str) -> None:
        """兼容原有接口，从文件加载对话"""
        # 可以扩展实现导入功能
        pass
