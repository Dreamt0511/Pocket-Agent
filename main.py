#!/usr/bin/env python3
"""
Pocket-Agent 主程序
轻量级移动端AI代理 - 真正的 agent loop
"""

import asyncio
import sys
import os
from dotenv import load_dotenv

# 加载.env环境变量
load_dotenv()

from datetime import datetime
from agent.memory import LongTermMemory
from agent.ui import PocketUI
from agent.agent_langchain import LangChainPocketAgent
from agent.config import MAX_ITERATIONS
from agent.prompts.system_base import prompt as system_base_prompt


async def main():
    """主函数"""
    ui = PocketUI()

    # 新版LangChain Agent实现
    model_name = os.getenv("LLM_MODEL", "gelab-zero-4b-preview")
    ui.show_welcome_screen(model_name + " (LangChain)")  # 展示欢迎界面

    # 系统提示词直接从prompts模块导入
    base_system_prompt = system_base_prompt

    # LLM配置 - 完全从环境变量读取，适配电脑/手机双环境
    llm_config = {
        "base_url": os.getenv("DEFAULT_LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        "api_key": os.getenv("LLM_API_KEY", "dummy"),
        "model": model_name,
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "8000")),
    }

    # 创建LangChain Agent
    agent = LangChainPocketAgent(
        system_prompt=base_system_prompt,
        max_iterations=MAX_ITERATIONS,  # 从配置文件读取最大迭代次数
        llm_config=llm_config,
        ui=ui
    )

    # 初始化记忆系统
    memory = LongTermMemory()

    # 互动式对话循环
    tool_call_count = 0
    current_task = None  # 记录当前正在执行的任务
    is_processing = False  # 标记是否正在处理用户请求

    while True:
        try:
            user_input = ui.print_user_input_prompt()

            if user_input.lower() in ['q', 'quit', 'exit', 'bye', '退出']:
                ui.print_success("再见！")
                break

            if user_input.lower() == 'help':
                help_text = """**常用指令**:
- 直接输入问题 → AI agent 自动调用工具回答
- 询问技能 → 直接说"有哪些技能"或"加载XX技能"
- `/undo` 或 `/撤回` → 撤回上一条发送的消息
- `q` → 退出程序
- Ctrl+C → 正在思考时打断，等待输入时退出"""
                ui.print_agent_response(help_text)
                continue

            # 撤回消息功能
            if user_input.lower() in ['/undo', '/撤回']:
                # LangChain版本：创建新会话，清空历史
                agent.clear_history()
                ui.print_success("✅ 已清空对话历史，你可以重新输入")
                continue

            if not user_input.strip():
                continue

            # 记录用户输入到记忆
            try:
                memory.add_memory(
                    content=f"用户问：{user_input}",
                    category="对话",
                    importance=2,
                    tags=["用户输入"]
                )
            except Exception:
                pass

            # ── 真正的 agent loop ──
            # ui.print_info("Agent 思考中...")  # 减少冗余提示

            try:
                # 标记开始处理
                is_processing = True
                # 创建任务以便可以取消
                current_task = asyncio.create_task(agent.run_conversation(user_input))
                response, used_streaming = await current_task
            except asyncio.CancelledError:
                # 任务被取消（用户打断）
                # 确保光标在新的一行
                ui.console.print()
                ui.print_warning("⏹️  已打断当前思考，你可以输入新的问题或指令")
                response = None
                used_streaming = False
            except Exception as e:
                response = f"❌ Agent 执行错误: {str(e)}"
                used_streaming = False
            finally:
                # 标记处理结束
                is_processing = False
                current_task = None

            # 显示AI回复（如果没有被打断）
            if response is not None:
                # 如果使用了流式输出，内容已实时显示，不需要再用Panel显示
                if not used_streaming:
                    ui.print_agent_response(response)
                else:
                    # 如果使用了流式输出，确保添加一个换行避免格式混乱
                    ui.console.print()

                # 记录AI回复到记忆
                try:
                    memory.add_memory(
                        content=f"AI回答：{response}",
                        category="对话",
                        importance=1,
                        tags=["AI回复"]
                    )
                except Exception:
                    pass

                tool_call_count += 1
                if tool_call_count % 10 == 0:
                    ui.print_conversation_stats(tool_call_count, len(agent.tools))

        except KeyboardInterrupt:
            if is_processing and current_task is not None:
                # 正在处理中，取消当前任务
                current_task.cancel()
                # 等待任务取消完成
                try:
                    await current_task
                except asyncio.CancelledError:
                    pass
            else:
                # 没有在处理，直接退出
                ui.print_success("\n\n再见！")
                break
        except Exception as e:
            ui.print_error(f"发现错误: {e}")


if __name__ == "__main__":
    # 确保所有文件都可以被导入
    project_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, project_root)

    # 强制兼容所有事件循环场景，彻底避免冲突
    import asyncio
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        print("⚠️  请先安装依赖：pip install nest_asyncio prompt_toolkit")
        sys.exit(1)

    # 统一使用get_event_loop，不使用asyncio.run
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
