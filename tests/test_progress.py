#!/usr/bin/env python3
"""
测试进度显示功能
"""
import asyncio
from agent.agent_langchain import LangChainPocketAgent
from agent.prompts.system_base import prompt as system_base_prompt
from agent.ui import PocketUI

async def test_progress_display():
    """测试进度显示功能"""
    ui = PocketUI()
    ui.show_welcome_screen("测试模型")

    # 初始化Agent
    agent = LangChainPocketAgent(
        system_prompt=system_base_prompt,
        llm_config={
            "base_url": "http://127.0.0.1:8080/v1",
            "api_key": "test",
            "model": "test-model"
        },
        ui=ui
    )

    # 测试进度显示
    print("\n测试进度显示功能...")
    print("=" * 50)

    # 测试进度条
    with ui.create_progress_display() as progress:
        progress.update("正在初始化...")
        await asyncio.sleep(1)
        progress.update("加载工具...")
        await asyncio.sleep(1)
        progress.update("调用工具: file_read")
        await asyncio.sleep(1)
        progress.update("工具 file_read 执行完成")
        await asyncio.sleep(1)
        progress.update("生成回复...")
        await asyncio.sleep(1)

    print("\n✅ 进度显示测试完成!")

    # 测试实际对话（需要本地LLM服务运行）
    print("\n" + "=" * 50)
    print("测试实际对话进度显示（需要本地LLM服务在8080端口运行）...")
    try:
        response, is_stream = await agent.run_conversation("你好，请介绍一下你自己")
        print(f"\n回复: {response}")
    except Exception as e:
        print(f"\n⚠️  对话测试失败（如果没有启动LLM服务属于正常情况）: {e}")

if __name__ == "__main__":
    asyncio.run(test_progress_display())