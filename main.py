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

# ==============================================================================
# 切换开关：设置为True使用新版LangChain实现，设置为False使用原有实现（回滚用）
USE_LANGCHAIN = True
# ==============================================================================

from datetime import datetime
from core.memory import LongTermMemory
from core.ui import PocketUI
from core.llm import llm_manager
from core.superpowers import pocket_superpowers

# 条件导入
if not USE_LANGCHAIN:
    from core.init import create_pocket_agent, load_skills_from_directory
    from core.agent import MessageRole
else:
    # 新版LangChain实现
    from core.agent_langchain import LangChainPocketAgent
    MessageRole = None  # 兼容占位


async def execute_superpowers_command(input_str: str) -> str:
    """执行Superpowers命令"""
    cmd_parts = input_str.lower().split()

    if len(cmd_parts) < 2:
        return pocket_superpowers.skill.help()

    action = cmd_parts[1]

    if action == 'help':
        return pocket_superpowers.skill.help()
    elif action == 'analyze':
        path = cmd_parts[2] if len(cmd_parts) > 2 else "."
        return pocket_superpowers.analyze_project(path)
    elif action == 'generate-docs':
        return pocket_superpowers.generate_docs()
    elif action == 'review-code':
        file_path = cmd_parts[2] if len(cmd_parts) > 2 else "main.py"
        return pocket_superpowers.review_code(file_path)
    elif action == 'optimize-workflow':
        return "⚙️ 工作流优化功能正在开发中..."
    else:
        return f"❌ 未知命令: {action}\n请使用 'superpowers help' 查看可用命令"


async def main():
    """主函数"""
    ui = PocketUI()

    # 展示欢迎界面（只一个蓝框，包含模型名）
    model_name = llm_manager.config.get("model", "")
    ui.show_welcome_screen(model_name)

    # 初始化 LLM
    try:
        if not USE_LANGCHAIN:
            llm_manager.setup_provider()
    except Exception as e:
        ui.print_error(f"LLM初始化失败: {e}")

    # 创建代理
    if not USE_LANGCHAIN:
        # 原有自定义Agent实现
        agent = create_pocket_agent("pocket-agent-v1", llm_manager=llm_manager, ui=ui)
        # 加载技能
        skills_dir = os.path.join(os.path.dirname(__file__), "skills")
        load_skills_from_directory(agent, skills_dir)
    else:
        # 新版LangChain Agent实现
        model_name = os.getenv("LLM_MODEL", "gelab-zero-4b-preview")
        ui.show_welcome_screen(model_name + " (LangChain)")  # 更新欢迎界面显示

        # 系统提示词（与原有保持一致）
        system_prompt = """你是Pocket-Agent，一个轻量级的移动端AI助手。
你的特点：
- 简洁、高效、适合移动端使用
- 善于文件操作、系统命令执行和安卓设备控制
- 能够理解并准确执行各种工具调用
- 对用户问题作出准确响应，禁止胡编乱造不存在的功能限制

重要规则：
1. 回复要简洁明了，不要冗余内容
2. 严格按照实际可用的工具回答问题，禁止编造不存在的功能或限制
3. 你可以正常访问本地运行的MCP服务，包括127.0.0.1:7474（NeuralBridge安卓控制）
4. 工具调用会自动处理，不需要输出特殊格式
"""

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
            model_name="pocket-agent-v1",
            system_prompt=system_prompt,
            max_iterations=10,
            llm_config=llm_config,
            ui=ui
        )

    # 初始化记忆系统
    memory = LongTermMemory()

    # 互动式对话循环
    tool_call_count = 0

    while True:
        try:
            user_input = ui.print_user_input_prompt()

            if user_input.lower() in ['q', 'quit', 'exit', 'bye', '退出']:
                ui.print_success("再见！")
                break

            if user_input.lower() == 'help':
                help_text = """**常用指令**:
- 直接输入问题 → AI agent 自动调用工具回答
- `superpowers help` → Superpowers技能帮助
- `/undo` 或 `/撤回` → 撤回上一条发送的消息
- `q` → 退出程序"""
                ui.print_agent_response(help_text)
                continue

            # 撤回消息功能
            if user_input.lower() in ['/undo', '/撤回']:
                if not USE_LANGCHAIN:
                    # 原有实现
                    if len(agent.messages) > 1:
                        # 从后往前找最后一条用户消息
                        last_user_idx = None
                        for i in range(len(agent.messages)-1, -1, -1):
                            if agent.messages[i].role == MessageRole.USER:
                                last_user_idx = i
                                break
                        if last_user_idx and last_user_idx > 0:
                            # 删除从最后一条用户消息开始的所有后续消息
                            agent.messages = agent.messages[:last_user_idx]
                            ui.print_success("✅ 已撤回上一条消息，你可以重新输入")
                        else:
                            ui.print_error("❌ 没有可撤回的消息")
                    else:
                        ui.print_error("❌ 没有可撤回的消息")
                else:
                    # LangChain版本：创建新会话，清空历史
                    agent.clear_history()
                    ui.print_success("✅ 已清空对话历史，你可以重新输入")
                continue

            # Superpowers技能处理
            if user_input.lower().startswith('superpowers'):
                superpowers_result = await execute_superpowers_command(user_input)
                if superpowers_result:
                    ui.print_agent_response(superpowers_result)
                continue

            # Debug 命令 - 使用 systematic-debugging skill
            if user_input.lower().startswith('debug '):
                debug_desc = user_input[6:].strip()
                if debug_desc:
                    debug_result = pocket_superpowers.debug_system(debug_desc)
                    ui.print_agent_response(debug_result)
                else:
                    ui.print_agent_response("请提供问题描述，例如: `debug Agent报错AttributeError`")
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
                response, used_streaming = await agent.run_conversation(user_input)
            except Exception as e:
                response = f"❌ Agent 执行错误: {str(e)}"
                used_streaming = False

            # 显示AI回复
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
            ui.print_success("\n\n被中断，再见！")
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