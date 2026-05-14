#!/usr/bin/env python3
"""
测试LLM连接是否正常
"""
import asyncio
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

async def test_llm_connection():
    """测试LLM基本连接"""
    llm_config = {
        "base_url": os.getenv("DEFAULT_LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        "api_key": os.getenv("LLM_API_KEY", "dummy"),
        "model": os.getenv("LLM_MODEL", "gelab-zero-4b-preview"),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "100")),
        "timeout": 10,
    }

    print(f"测试LLM连接: {llm_config['base_url']}")
    print(f"模型: {llm_config['model']}")
    print(f"API密钥: {'已配置' if llm_config['api_key'] != 'dummy' else '默认（dummy）'}")

    try:
        llm = ChatOpenAI(
            base_url=llm_config["base_url"],
            api_key=llm_config["api_key"],
            model=llm_config["model"],
            temperature=llm_config["temperature"],
            max_tokens=llm_config["max_tokens"],
            timeout=llm_config["timeout"],
            streaming=False
        )

        print("\n发送测试消息...")
        response = await llm.ainvoke("你好，请简单介绍一下你自己，不要超过30字。")
        print(f"✅ LLM响应正常: {response.content}")
        return True

    except Exception as e:
        print(f"❌ LLM连接失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import nest_asyncio
    nest_asyncio.apply()

    loop = asyncio.get_event_loop()
    success = loop.run_until_complete(test_llm_connection())

    if success:
        print("\n🎉 LLM连接正常，可以使用Agent功能")
    else:
        print("\n⚠️  请先确保llama-server已经启动，并且.env配置正确")
        print("   启动命令参考: ./llama-server -m 模型路径 -c 29000 --host 0.0.0.0 --port 8080 -ngl 100")
