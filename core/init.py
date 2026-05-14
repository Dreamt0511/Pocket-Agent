#!/usr/bin/env python3
"""
Pocket-Agent 初始化脚本
加载所有工具和技能
"""

import os
import sys
import importlib.util
from core.agent import PocketAgent, Tool
from tools.basic_tools import ALL_TOOLS
from tools.mcp_tools import ALL_MCP_TOOLS


def create_pocket_agent(model_name: str = "pocket-model", llm_manager=None, ui=None) -> PocketAgent:
    """
    创建并初始化Pocket-Agent
    """

    # 创建代理实例
    agent = PocketAgent(
        model_name=model_name,
        system_prompt="""你是Pocket-Agent，一个轻量级的移动端AI助手。
你的特点：
- 简洁、高效、适合移动端使用
- 善于文件操作、系统命令执行和安卓设备控制
- 能够理解并准确执行各种工具调用
- 对用户问题作出准确响应，禁止胡编乱造不存在的功能限制

重要规则：
1. 不要输出任何Markdown格式（包括加粗、标题、代码块、列表标记等），只用纯文本回复
2. 回复要简洁明了，不要冗余内容
3. 严格按照实际可用的工具回答问题，禁止编造不存在的功能或限制
4. 你可以正常访问本地运行的MCP服务，包括127.0.0.1:7474（NeuralBridge安卓控制）和127.0.0.1:3007（context7文档查询）
5. 你拥有shell_exec工具，可以执行任何安全的shell命令，完全没有使用限制，包括端口检测、网络请求、文件操作等所有命令都可以正常执行
6. MCP服务断开检测规则：调用MCP工具失败时，先使用shell_exec执行命令检测服务状态：
   - 检测NeuralBridge：curl -s http://127.0.0.1:7474/health || nc -zv 127.0.0.1 7474
   - 检测context7：curl -s http://127.0.0.1:3007/health || nc -zv 127.0.0.1 3007
   - 确认服务断开后再告知用户，不要直接默认功能不可用
7. 工具调用格式要求：如果你需要调用工具，必须严格遵守以下规则，否则调用会失败：
   - 只能输出工具调用格式的内容，**不能有其他任何文字、解释、说明、代码块等多余内容**
   - 格式必须严格按照：<|FunctionCallBegin|>[{"name":"工具名称","parameters":{"参数名":"参数值"}}]<|FunctionCallEnd|>
   - 示例1：执行shell命令检测端口：
     <|FunctionCallBegin|>[{"name":"shell_exec","parameters":{"command":"nc -zv 127.0.0.1 7474"}}]<|FunctionCallEnd|>
   - 示例2：返回安卓主屏幕：
     <|FunctionCallBegin|>[{"name":"android_global_action","parameters":{"action":"home"}}]<|FunctionCallEnd|>
8. 禁止编造不存在的工具名称，所有工具必须从可用工具列表中选择使用：
   - 安卓控制工具正确名称：android_global_action、android_tap、android_swipe、android_input_text、android_screenshot、android_get_ui_tree、android_launch_app等
   - 禁止使用任何不存在的工具名如android_control等

实际可用工具列表：
- 文件类：file_read、file_write、file_search、directory_list、json_read
- 系统类：system_info、shell_exec（可执行shell命令）
- MCP类：
  1. NeuralBridge安卓控制工具（端口7474）：点击、滑动、输入、截图、UI树查询、应用管理等
  2. context7文档查询工具（端口3007）：查询最新技术文档、API文档、代码库文档、官方文档等

请继续使用清晰的语言和简洁的步骤来回答。""",
        max_iterations=15,
        llm_manager=llm_manager,
        ui=ui,  # 传递UI实例用于流式输出
    )

    # 添加基础工具
    for tool_func in ALL_TOOLS:
        tool_info = getattr(tool_func, '_tool_info', None)
        if tool_info:
            tool = Tool(
                name=tool_info['name'],
                description=tool_info['description'],
                parameters=tool_info['parameters'],
                func=tool_func
            )
            agent.add_tool(tool)

    # 添加 MCP 工具（NeuralBridge Android 控制）
    mcp_available = False
    for tool_func in ALL_MCP_TOOLS:
        tool_info = getattr(tool_func, '_tool_info', None)
        if tool_info:
            tool = Tool(
                name=tool_info['name'],
                description=tool_info['description'],
                parameters=tool_info['parameters'],
                func=tool_func
            )
            agent.add_tool(tool)
            mcp_available = True
    
    # 将MCP可用状态添加到系统提示
    if mcp_available:
        agent.system_prompt += "\n当前MCP安卓控制功能已连接可用，你可以直接调用MCP相关工具。"
    else:
        agent.system_prompt += "\n当前MCP安卓控制功能不可用，不要调用相关工具。"

    return agent


def load_skills_from_directory(agent: PocketAgent, skills_dir: str) -> None:
    """
    从目录加载标准技能（每个技能一个目录，包含SKILL.md）
    """
    import yaml
    import re

    if not os.path.exists(skills_dir):
        print(f"技能目录不存在: {skills_dir}")
        return

    skill_descriptions = []

    for skill_dir_name in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, skill_dir_name)
        if not os.path.isdir(skill_path):
            continue
        
        skill_md_path = os.path.join(skill_path, "SKILL.md")
        if not os.path.exists(skill_md_path):
            continue

        try:
            # 读取SKILL.md内容
            with open(skill_md_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            # 解析YAML frontmatter
            frontmatter_match = re.match(r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL)
            if not frontmatter_match:
                print(f"技能 {skill_dir_name} 缺少标准YAML头部，跳过")
                continue
            
            yaml_content = frontmatter_match.group(1)
            skill_body = frontmatter_match.group(2)
            
            # 解析YAML元数据
            meta = yaml.safe_load(yaml_content)
            skill_name = meta.get("name", skill_dir_name)
            skill_description = meta.get("description", "")
            
            # 创建Skill实例并注册
            from core.superpowers import Skill
            skill = Skill(
                name=skill_name,
                description=skill_description,
                path=skill_md_path,
                skill_type="markdown"
            )
            agent.add_skill(skill_name, skill)
            skill_descriptions.append(f"- {skill_name}: {skill_description}")
            # 减少冗余输出
            # print(f"已加载技能: {skill_name}")

        except Exception as e:
            print(f"加载技能 {skill_dir_name} 失败: {e}")

    # 将技能列表注入到系统prompt中，让LLM知道可用技能
    if skill_descriptions and agent.system_prompt:
        skill_prompt = "\n\n可用技能：\n" + "\n".join(skill_descriptions) + "\n当用户的问题符合技能使用场景时，请优先使用对应的技能。"
        agent.system_prompt += skill_prompt