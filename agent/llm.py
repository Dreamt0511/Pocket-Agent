#!/usr/bin/env python3
"""
LLM 模型配置和调用 - 完整版
支持多种提供商和工具调用(tool calling)
"""

import os
import json
import asyncio
from typing import Optional, Dict, Any, AsyncGenerator


class MockProvider:
    """本地模拟LLM提供者（无API时降级使用）"""

    def __init__(self, model: str = "local-lite"):
        self.model = model

    async def chat_completion(self, messages: list, **kwargs) -> str:
        """本地模拟对话完成"""
        user_message = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_message = msg.get("content", "")

        if "工具" in user_message or "skill" in user_message:
            return (
                "**可用工具 (6个):**\n"
                "- file_read: 读取文件内容\n"
                "- file_write: 写入文件\n"
                "- file_search: 搜索文件\n"
                "- directory_list: 列出目录\n"
                "- json_read: JSON数据处理\n"
                "- system_info: 获取系统信息\n"
            )
        elif "文件" in user_message or "目录" in user_message:
            return "✅ 请使用 directory_list 或 file_read 工具来查看文件。"
        else:
            return f"我收到了你的消息: {user_message}\n\n请告诉我你有什么具体需求！"

    async def chat_with_tools(self, messages: list, tools: list) -> dict:
        """模拟工具调用 - 不支持真正的 tool calling"""
        return {"content": await self.chat_completion(messages), "tool_calls": None}

    async def stream_chat(self, messages: list, **kwargs) -> AsyncGenerator[str, None]:
        response = await self.chat_completion(messages)
        # 逐字输出模拟流式
        for char in response:
            yield char
            await asyncio.sleep(0.01)


class OpenAICompatProvider:
    """OpenAI 兼容 API 提供商（支持 OpenRouter、LongCat 等）"""

    def __init__(self, base_url: str, api_key: str, model: str):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model

    async def _post(self, payload: dict, stream: bool = False):
        """发送请求"""
        try:
            import aiohttp
        except ImportError:
            # 降级到 requests
            return await self._post_sync(payload, stream)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload
            ) as response:
                if stream:
                    return response  # 返回 response 对象用于流式读取
                else:
                    data = await response.json()
                    if response.status != 200:
                        return {"error": f"API错误 {response.status}: {data}"}
                    return data

    async def _post_sync(self, payload: dict, stream: bool = False):
        """同步 fallback"""
        import requests
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        response = requests.post(
            f"{self.base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
            stream=stream
        )
        if stream:
            return response
        if response.status_code != 200:
            return {"error": f"API错误 {response.status_code}: {response.text}"}
        return response.json()

    async def chat_completion(self, messages: list, **kwargs) -> str:
        """普通对话完成"""
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            **kwargs
        }
        result = await self._post(payload)
        if isinstance(result, dict) and "error" in result:
            return f"❌ {result['error']}"
        try:
            return result['choices'][0]['message']['content'] or ""
        except (KeyError, IndexError):
            return "❌ 无法解析API响应"

    async def chat_with_tools(self, messages: list, tools: list) -> dict:
        """
        带工具调用的对话
        返回 {"content": str, "tool_calls": list|None}
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "stream": False,
        }
        result = await self._post(payload)
        if isinstance(result, dict) and "error" in result:
            return {"content": f"❌ {result['error']}", "tool_calls": None}

        try:
            choice = result['choices'][0]
            msg = choice.get('message', {})
            return {
                "content": msg.get('content') or "",
                "tool_calls": msg.get('tool_calls', None)
            }
        except (KeyError, IndexError):
            return {"content": "❌ 无法解析API响应", "tool_calls": None}

    async def stream_chat(self, messages: list, **kwargs) -> AsyncGenerator[str, None]:
        """流式对话"""
        # 简化：先尝试使用普通对话，后续再优化流式
        try:
            content = await self.chat_completion(messages, **kwargs)
            # 将内容分块模拟流式输出
            chunk_size = 3  # 每块3个字符，模拟真实流式
            for i in range(0, len(content), chunk_size):
                chunk = content[i:i + chunk_size]
                if chunk:
                    yield chunk
                    await asyncio.sleep(0.05)  # 添加小延迟模拟流式
        except Exception as e:
            yield f"❌ 流式调用失败: {str(e)}"


class OpenAIProvider(OpenAICompatProvider):
    """OpenAI 提供商（继承 OpenAICompatProvider）"""
    pass


class OllamaProvider:
    """Ollama 本地模型"""

    def __init__(self, base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"), model: str = "phi3"):
        self.base_url = base_url.rstrip('/')
        self.model = model

    async def chat_completion(self, messages: list, **kwargs) -> str:
        try:
            import aiohttp
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                **kwargs
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data['message']['content']
                    return f"Ollama API错误: {response.status}"
        except Exception as e:
            return f"Ollama调用失败: {str(e)}"

    async def chat_with_tools(self, messages: list, tools: list) -> dict:
        """Ollama 也支持 tools"""
        try:
            import aiohttp
            payload = {
                "model": self.model,
                "messages": messages,
                "tools": tools,
                "stream": False,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        msg = data.get('message', {})
                        return {
                            "content": msg.get('content', '') or '',
                            "tool_calls": msg.get('tool_calls', None)
                        }
                    return {"content": f"Ollama API错误: {response.status}", "tool_calls": None}
        except Exception as e:
            return {"content": f"Ollama调用失败: {str(e)}", "tool_calls": None}

    async def stream_chat(self, messages: list, **kwargs) -> AsyncGenerator[str, None]:
        try:
            import aiohttp
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": True,
                **kwargs
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as response:
                    if response.status == 200:
                        async for line in response.content:
                            decoded = line.decode('utf-8').strip()
                            if decoded:
                                try:
                                    chunk = json.loads(decoded)
                                    content = chunk.get('message', {}).get('content', '')
                                    if content:
                                        yield content
                                except json.JSONDecodeError:
                                    continue
                    else:
                        yield f"Ollama API错误: {response.status}"
        except Exception as e:
            yield f"Ollama调用失败: {str(e)}"


class LLMManager:
    """LLM 管理器"""

    def __init__(self):
        self.provider = None
        self.config = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        default_config = {
            "provider": "mock",
            "base_url": os.getenv("DEFAULT_LLM_BASE_URL", "https://api.longcat.chat/openai/v1"),
            "model": "longcat-flash-lite",
            "api_key": ""
        }

        # 从 .env 文件读取
        env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
        env_file = os.path.normpath(env_file)
        if os.path.exists(env_file):
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, _, val = line.partition('=')
                        key = key.strip()
                        val = val.strip().strip('"').strip("'")
                        if key == 'LLM_API_KEY' and val:
                            default_config['api_key'] = val
                        elif key == 'LLM_PROVIDER':
                            default_config['provider'] = val
                        elif key == 'LLM_BASE_URL':
                            default_config['base_url'] = val
                        elif key == 'LLM_MODEL':
                            default_config['model'] = val

        # 有 API key 就自动切 custom
        if default_config['api_key']:
            default_config['provider'] = 'custom'

        # 环境变量覆盖
        return {
            "provider": os.getenv("LLM_PROVIDER", default_config["provider"]),
            "base_url": os.getenv("LLM_BASE_URL", default_config["base_url"]),
            "api_key": os.getenv("LLM_API_KEY", default_config["api_key"]),
            "model": os.getenv("LLM_MODEL", default_config["model"])
        }

    def setup_provider(self):
        """设置LLM提供商"""
        provider_type = self.config["provider"].lower()

        if provider_type in ("custom", "openai", "openrouter"):
            if not self.config["api_key"]:
                print(f"⚠️  {provider_type} 需要API密钥，切换到模拟模式...")
                self.provider = MockProvider(self.config["model"])
            else:
                self.provider = OpenAICompatProvider(
                    self.config["base_url"],
                    self.config["api_key"],
                    self.config["model"]
                )
        elif provider_type == "ollama":
            self.provider = OllamaProvider(
                self.config["base_url"],
                self.config["model"]
            )
        else:
            print(f"⚠️  未知提供商 '{provider_type}'，切换到模拟模式...")
            self.provider = MockProvider(self.config["model"])

    async def chat(self, user_message: str, system_prompt: str = None) -> str:
        """普通对话"""
        if not self.provider:
            self.setup_provider()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_message})

        return await self.provider.chat_completion(messages)

    async def chat_with_tools(
        self,
        messages: list,
        tools: list
    ) -> dict:
        """
        带工具定义的对话
        messages: [{"role": "system"|"user"|"assistant"|"tool", "content": str, ...}]
        tools: [{"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}]
        返回: {"content": str, "tool_calls": list|None}
        """
        if not self.provider:
            self.setup_provider()

        return await self.provider.chat_with_tools(messages, tools)

    async def stream_chat(self, messages: list) -> AsyncGenerator[str, None]:
        """流式对话"""
        if not self.provider:
            self.setup_provider()

        async for chunk in self.provider.stream_chat(messages):
            yield chunk


# 全局 LLM 管理器
llm_manager = LLMManager()