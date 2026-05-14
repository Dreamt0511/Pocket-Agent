#!/usr/bin/env python3
"""
测试优化后的LangChain Agent性能
"""
import asyncio
import os
import sys
import time
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

# 导入优化后的Agent
from agent.agent_langchain import LangChainPocketAgent

class MockUI:
    """模拟UI类，用于测试"""
    def print_stream_chunk(self, token):
        """模拟流式输出"""
        print(token, end='', flush=True)

    def print_info(self, msg):
        print(f"\nℹ️ {msg}")

    def print_error(self, msg):
        print(f"\n❌ {msg}")

async def test_agent_performance():
    """测试Agent性能"""
    print("=== 测试优化后的LangChain Agent性能 ===\n")

    # 创建模拟UI
    ui = MockUI()

    # LLM配置
    llm_config = {
        "base_url": os.getenv("DEFAULT_LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        "api_key": os.getenv("LLM_API_KEY", "dummy"),
        "model": os.getenv("LLM_MODEL", "gelab-zero-4b-preview"),
        "temperature": 0.7,
        "max_tokens": 100,  # 限制输出长度，加快测试
    }

    # 创建Agent
    print("创建Agent实例...")
    agent = LangChainPocketAgent(
        system_prompt="你是一个高效的AI助手，回答简洁明了。",
        llm_config=llm_config,
        ui=ui,
        max_iterations=3,
    )

    # 测试多次对话
    test_queries = [
        "你好，请介绍一下你自己。",
        "2+2等于几？",
        "Python中如何实现列表去重？",
    ]

    for i, query in enumerate(test_queries, 1):
        print(f"\n\n--- 测试 {i}/{len(test_queries)} ---")
        print(f"用户输入: {query}")
        print("Agent响应: ", end='', flush=True)

        start_time = time.time()

        try:
            response, used_streaming = await agent.run_conversation(query)
            end_time = time.time()

            print(f"\n\n响应长度: {len(response)} 字符")
            print(f"响应时间: {end_time - start_time:.2f} 秒")
            print(f"是否使用流式: {used_streaming}")

        except Exception as e:
            print(f"\n❌ 错误: {e}")
            import traceback
            traceback.print_exc()

    print("\n\n=== 测试完成 ===")
    print("\n优化效果说明:")
    print("1. 移除了低效的流式chunk处理，直接使用LLM回调实现流式输出")
    print("2. 启用了v2版本API，获得性能提升")
    print("3. 移除了不必要的LLM预热调用，减少启动延迟")
    print("4. 消除了可能导致双重LLM调用的逻辑")
    print("5. 简化了响应收集逻辑，减少CPU开销")

if __name__ == "__main__":
    # 兼容事件循环
    import asyncio
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        pass

    asyncio.run(test_agent_performance())
