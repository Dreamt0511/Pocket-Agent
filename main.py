#!/usr/bin/env python3
"""
Pocket-Agent 主程序
轻量级移动端AI代理 - 真正的 agent loop
"""

import asyncio
import sys
import os
from datetime import datetime
from agent.memory import LongTermMemory
from agent.ui import PocketUI
from agent.agent_langchain import LangChainPocketAgent
from dotenv import load_dotenv
# 从脚本所在目录加载.env，override=True确保覆盖已有环境变量
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'), override=True)
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
    # 安全读取数字参数，配置错误时使用默认值
    try:
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        # 温度值必须在0-2之间
        temperature = max(0.0, min(2.0, temperature))
    except (ValueError, TypeError):
        temperature = 0.7

    try:
        max_tokens = int(os.getenv("LLM_MAX_TOKENS", "8000"))
        # max_tokens必须为正整数
        max_tokens = max(1, max_tokens)
    except (ValueError, TypeError):
        max_tokens = 8000

    llm_config = {
        "base_url": os.getenv("DEFAULT_LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        "api_key": os.getenv("LLM_API_KEY", "dummy"),
        "model": model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
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
            # 等待用户输入，捕获所有输入相关异常
            try:
                user_input = await ui.async_print_user_input_prompt()
            except (KeyboardInterrupt, EOFError, SystemExit):
                # 输入时按Ctrl+C直接退出
                ui.print_success("\n\n再见！")
                break
            except Exception:
                # 其他输入异常，继续下一轮
                continue

            if user_input.lower() in ['q', 'quit', 'exit', 'bye', '退出']:
                ui.print_success("再见！")
                break

            if user_input.lower() == 'help':
                help_text = """**常用指令**:
- 直接输入问题 → AI agent 自动调用工具回答
- 询问技能 → 直接说"有哪些技能"或"加载XX技能"
- `/undo` 或 `/撤回` → 撤回上一条发送的消息
- `q` → 退出程序
- Ctrl+C / 直接输入新内容 → 正在思考时打断，输入新问题"""
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
                response, used_streaming, call_count = await current_task
            except (asyncio.CancelledError, KeyboardInterrupt):
                # 一次Ctrl+C会同时触发CancelledError和KeyboardInterrupt，
                # 同时捕获避免后者传播到外层误触"再见！"退出
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

                tool_call_count += call_count
                if tool_call_count % 10 == 0 and call_count > 0:
                    ui.print_conversation_stats(tool_call_count, len(agent.tools))

        except KeyboardInterrupt:
            # 意外传播到外层的Ctrl+C（内层已捕获，此处仅作安全兜底）
            ui.print_success("\n\n再见！")
            break
        except Exception as e:
            # 忽略键盘中断相关的异常栈输出
            if not isinstance(e, KeyboardInterrupt) and "CancelledError" not in str(type(e)):
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

    # 全局异常处理，捕获所有可能的退出异常，确保绝对不会输出错误栈
    exit_cleanly = False
    try:
        # 统一使用get_event_loop，不使用asyncio.run
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
        exit_cleanly = True
    except (KeyboardInterrupt, SystemExit):
        # 直接的键盘中断或系统退出（输入阶段）
        print("\n再见！")
        exit_cleanly = True
    except Exception as e:
        # 检查是否是键盘中断相关的异常（包括嵌套的）
        exc_str = str(type(e)) + str(e)
        if "KeyboardInterrupt" in exc_str or "CancelledError" in exc_str:
            # 处理过程中的中断已经在内层输出了打断提示，不需要再输出再见
            exit_cleanly = True
        else:
            # 只输出真正的异常，不输出完整栈追踪
            print(f"\n❌ 程序异常退出: {str(e)}")
    finally:
        # 确保事件循环正常关闭，忽略所有关闭过程中的异常
        try:
            loop = asyncio.get_event_loop()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
        except:
            pass
