# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Pocket-Agent is a lightweight mobile AI agent designed for efficient operation on both mobile devices (Termux/Android) and servers. It uses LangChain + LangGraph for the agent loop, supports tool calling, a skill system, long-term memory, and MCP service integration for Android device control.

## High-Level Architecture

```
├── main.py                          # 入口：加载环境变量 → 创建LangChainPocketAgent → 对话循环
├── agent/                           # 核心包
│   ├── agent_langchain.py           # LangChainPocketAgent：基于create_agent的主实现，含中间件链
│   ├── config.py                    # 全局配置（MAX_ITERATIONS, RECURSION_LIMIT, SKILLS_DIR等）
│   ├── llm.py                       # LLMManager：多提供商支持（OpenAI兼容/Ollama/Mock）
│   ├── memory.py                    # LongTermMemory：按日期的Markdown记忆文件 + 用户画像
│   ├── ui.py                        # PocketUI：基于rich的终端UI（流式输出、进度条、上下文用量条）
│   ├── prompts/                     # 提示词模块
│   │   ├── system_base.py           # 基础系统人设
│   │   └── agent_enhance.py         # 工具规则、技能系统说明、MCP调用规则（动态注入tool_names和skills_list）
│   ├── tools/
│   │   ├── basic_tools.py           # 6个内置工具：file_read, file_write, file_search, directory_list, system_info, shell_exec
│   │   └── mcp_tools.py            # MCP工具动态生成（当前版本未预加载，由模型通过shell_exec调用curl）
│   └── skills/                      # 技能目录，每个子目录含SKILL.md，自动发现
├── memory/                          # 记忆数据存储（每日.md文件 + user_profile.md）
├── .env.example                     # 环境变量模板
└── requirements.txt                 # 依赖
```

### Agent Loop Flow
1. `main.py` 加载 `.env` → 创建 `LangChainPocketAgent`（内部初始化 ChatOpenAI + `create_agent` + 中间件链）→ 启动对话循环
2. 用户输入 → `agent.run_conversation()` → LangGraph astream 处理 → 工具调用/流式输出 → 返回结果
3. 对话历史通过 LangGraph MemorySaver 持久化，`/undo` 命令通过更换 thread_id 清空历史

### Middleware Chain (agent_langchain.py)
Agent 使用 LangChain 官方 `create_agent` 创建，配置了5个中间件按顺序执行：
- **MCPToolResultMiddleware**: 将MCP返回的图片base64转为文本描述，避免token爆炸
- **ImageOptimizationMiddleware**: 移除历史消息中的图片base64数据
- **ToolCallIdMiddleware**: 修复某些LLM（如GLM系列）生成的tool_call缺少id字段
- **SummarizationMiddleware**: token超过64K时自动压缩历史，保留最近20条
- **ModelCallLimitMiddleware**: 单次运行最多调用MAX_ITERATIONS次模型，达到后优雅结束

## Common Development Commands

### 安装依赖
```bash
pip install -r requirements.txt
# nest_asyncio和prompt_toolkit在requirements.txt中已包含
```

### 运行应用
```bash
python main.py
```

### 环境配置
复制 `.env.example` 为 `.env` 并修改。关键变量：
- `DEFAULT_LLM_BASE_URL`: LLM API地址（兼容OpenAI格式，默认 `http://127.0.0.1:8080/v1`）
- `LLM_API_KEY`: API密钥（本地llama-server用 `dummy`）
- `LLM_MODEL`: 模型名称（默认 `gelab-zero-4b-preview`）
- `LLM_TEMPERATURE` / `LLM_MAX_TOKENS`: 生成参数
- `NEURALBRIDGE_MCP_URL`: NeuralBridge MCP地址（默认 `http://127.0.0.1:7474/mcp`）

### 测试和验证
- 运行SSH命令测试：`python test_ssh_cmd.py "<command>"`
- 运行嵌入测试：`python my_test_scripts/test_long_embedding.py`
- 运行聊天测试：`python my_test_scripts/chat.py`
- 使用技能进行测试驱动开发：参考 `agent/skills/test-driven-development/` 中的指南

### 代码质量
- 代码格式化：`black .` （使用pyproject.toml中的配置）
- 导入排序：`isort .` （使用pyproject.toml中的配置）
- 运行所有检查：`black . --check && isort . --check`

### 代码变更验证（强制执行）
**修改代码后必须先运行验证再报告完成，禁止写完不跑。**
- Python 文件：`python3 -c "import ast; ast.parse(open('文件路径').read())"` 验证语法
- 能直接运行的代码（如测试、脚本）必须实际执行确认无报错
- 对于运行环境受限无法完整运行的情况，至少完成语法验证并说明限制

## Key Conventions

### Tool System
- 内置工具定义在 `agent/tools/basic_tools.py`，使用 `@tool` 装饰器（LangChain），返回 `ALL_TOOLS` 列表
- MCP工具不预加载，模型通过 `shell_exec` 执行 `curl` 调用MCP服务的 JSON-RPC 接口
- 工具调用由LangChain/LangGraph原生处理，不需要手动解析格式

### Skill System
- 技能目录：`agent/skills/`，每个子目录含 `SKILL.md`
- 技能自动发现：`load_skills_list()` 扫描目录，将名称和描述注入系统提示词
- 使用技能时模型通过 `file_read` 读取对应 SKILL.md 的完整内容
- 现有技能：brainstorming, code-review, neuralbridge-operation-standard, phone-control-guide, systematic-debugging, test-driven-development, verification-before-completion, writing-plans

### MCP Integration
- **NeuralBridge** (127.0.0.1:7474): 安卓设备控制，通过MCP JSON-RPC协议调用
- **Context7** (mcp.context7.com): 远程文档查询，需要API Key
- 模型通过 `agent/prompts/agent_enhance.py` 中的规则学习如何调用MCP服务

### Memory System
- 按日期存储：`memory/YYYY-MM-DD.md`，每次对话自动记录用户输入和AI回复
- 用户画像：`memory/user_profile.md`

### Configuration (agent/config.py)
- `MAX_ITERATIONS = 100`: 最大工具调用轮数
- `RECURSION_LIMIT = 200`: LangGraph底层递归限制（兜底）
- `MAX_CONTEXT_TOKENS = 128000`: 上下文窗口大小
- `SKILLS_DIR`: 技能目录路径
