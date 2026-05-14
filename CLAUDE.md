# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Pocket-Agent is a lightweight mobile AI agent with a real agent loop, designed for efficient operation on both mobile devices and servers. It supports tool calling, skill integration, long-term memory, and MCP (Model Control Protocol) service integration for extended capabilities like Android device control.

## High-Level Architecture
```
├── main.py                 # 主程序入口，包含对话循环和命令处理
├── core/                   # 核心功能模块
│   ├── agent.py            # PocketAgent 核心实现，处理对话和工具调用
│   ├── init.py             # 代理初始化，加载工具和技能
│   ├── llm.py              # LLM 管理器，支持多提供商（OpenAI兼容、Ollama等）
│   ├── memory.py           # 长期记忆系统
│   ├── ui.py               # 终端UI组件（基于rich）
│   └── superpowers/        # 内置superpowers技能实现
├── agents/                 # 基础代理实现
│   └── pocket_base.py      # PocketAgent 基类
├── skills/                 # 可加载技能目录，遵循superpowers技能规范
│   ├── brainstorming/      # 头脑风暴技能
│   ├── code-review/        # 代码审查技能
│   ├── systematic-debugging/ # 系统调试技能
│   └── writing-plans/      # 计划编写技能
├── tools/                  # 可用工具实现
│   ├── basic_tools.py      # 基础工具（shell执行、文件操作等）
│   └── mcp_tools.py        # MCP服务集成工具（安卓控制、文档查询等）
├── memory/                 # 长期记忆数据存储目录
├── requirements.txt        # 项目依赖
└── .env                    # 环境变量配置（从.env.example复制）
```

### Core Component Flow
1. **初始化**: `main.py` 加载环境变量 → 初始化LLM管理器 → 创建PocketAgent实例 → 加载所有工具和技能 → 启动对话循环
2. **对话处理**: 用户输入 → 命令解析（内置命令/技能调用/普通对话）→ Agent 处理 → 工具调用（如需要）→ 生成回复 → 记忆存储
3. **技能系统**: 技能从 `skills/` 目录自动加载，遵循superpowers技能规范，可通过 `superpowers <command>` 调用

## Common Development Commands
### 1. 安装依赖
```bash
pip install -r requirements.txt
# 额外依赖（可选，用于事件循环兼容）
pip install nest_asyncio prompt_toolkit
```

### 2. 运行应用
```bash
python main.py
```

### 3. 环境配置
复制 `.env.example` 到 `.env` 并修改配置：
- `MCP_SERVER_URL`: MCP服务地址（默认：http://127.0.0.1:7474/mcp）
- `DEFAULT_LLM_BASE_URL`: 默认LLM API地址（兼容OpenAI格式）
- `OLLAMA_BASE_URL`: 本地Ollama服务地址
- `LLM_API_KEY`: LLM API密钥（可选）
- `LLM_MODEL`: 默认使用的LLM模型名称（可选）

## Key Conventions
### Tool Calling
- 工具调用必须严格使用格式：`<|FunctionCallBegin|>[{"name":"工具名","parameters":{"参数名":"值"}}]<|FunctionCallEnd|>`
- 禁止编造不存在的工具，所有工具从 `tools/` 目录中定义的列表选择
- MCP工具调用失败时，先执行服务健康检测再提示用户

### Response Rules
- 普通回复使用纯文本，禁止Markdown格式（包括加粗、标题、代码块等）
- 回复简洁明了，避免冗余内容
- 严格按照实际可用功能回答，禁止编造不存在的限制或功能

### Skill Development
- 新技能放置在 `skills/` 目录下，遵循superpowers技能规范
- 技能会被自动加载，无需修改核心代码

### MCP Integration
- 内置支持两个MCP服务：
  1. NeuralBridge (127.0.0.1:7474): 安卓设备控制
  2. Context7 (127.0.0.1:3007): 文档查询服务
- 服务健康检测命令：
  - NeuralBridge: `curl -s http://127.0.0.1:7474/health || nc -zv 127.0.0.1 7474`
  - Context7: `curl -s http://127.0.0.1:3007/health || nc -zv 127.0.0.1 3007`
