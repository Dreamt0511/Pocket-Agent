# Pocket-Agent

轻量级移动端 AI Agent，支持在手机（Termux/Android）和服务器上运行。基于 LangChain + LangGraph 构建，支持工具调用、技能系统、分层记忆和 MCP 服务集成。

## 特性

- **LangChain Agent**：使用官方 `create_agent` 创建，支持中间件链
- **分层记忆系统**：用户画像 + 事实记忆 + 事件记忆 + 程序记忆
- **混合检索**：FTS5 全文搜索 + BGE-M3 向量搜索，RRF 融合排序
- **技能系统**：自动发现 SKILL.md，支持主 Agent 和子 Agent 技能
- **MCP 集成**：通过 NeuralBridge 控制安卓设备
- **持久化对话**：AsyncSqliteSaver 保存 LangGraph 状态，重启后恢复

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 配置环境

复制 `.env.example` 为 `.env`，配置以下变量：

```env
# LLM 配置（兼容 OpenAI 格式）
DEFAULT_LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=gpt-4o

# Embedding 配置（本地 llama-server）
EMBEDDING_SERVER_URL=http://127.0.0.1:8080/v1
EMBEDDING_MODEL=bge-m3
EMBEDDING_MODEL_PATH=/sdcard/Pocket-Agent/bge-m3-Q4_K_M.gguf

# MCP 服务
MCP_SERVER_URL=http://127.0.0.1:7474/mcp
```

### 运行

```bash
# 终端交互模式
python main.py

# HTTP API 模式（供 Android App 调用）
# Android App 会自动通过 Termux 启动此服务，无需手动执行
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

### 嵌入模型（语义检索）

语义检索需要本地 embedding 模型服务。

**前提条件：** 需要编译带 embedding 后端支持的 llama.cpp。

**模型下载：**
```bash
# BGE-M3 GGUF（推荐，支持中英文，最大 8192 token）
wget -O /sdcard/Pocket-Agent/bge-m3-Q4_K_M.gguf \
  https://hf-mirror.com/gpustack/bge-m3-GGUF/blob/main/bge-m3-Q4_K_M.gguf
```

**配置模型路径：**

在 `.env` 文件中设置 `EMBEDDING_MODEL_PATH` 为 GGUF 模型文件的绝对路径：
```env
EMBEDDING_MODEL_PATH=/sdcard/Pocket-Agent/bge-m3-Q4_K_M.gguf
```

**手动启动参数：**
```bash
# 从 .env 读取模型路径
EMBED_MODEL="$(grep '^EMBEDDING_MODEL_PATH=' ~/Pocket-Agent/.env | cut -d= -f2 | tr -d '\"')"

cd ~/llama.cpp
./build/bin/llama-server \
  -m "$EMBED_MODEL" \
  --embedding \
  -c 8192 \
  --port 8080 \
  --host 0.0.0.0 \
  -np 4 \
  -b 1024 \
  -ub 1024 \
  -t 4
```

> App 启动时会自动读取 `.env` 中的 `EMBEDDING_MODEL_PATH` 并拉起 llama-server。未配置路径或文件不存在时，全文搜索（FTS5）仍可用，语义搜索自动跳过。

## 架构

```
├── app.py                    # FastAPI HTTP 服务（SSE 流式聊天）
├── main.py                   # 终端交互式入口
├── agent/
│   ├── agent_langchain.py    # LangChainPocketAgent 核心实现
│   ├── config.py             # 全局配置
│   ├── embedding.py          # EmbeddingClient + VectorStore（SQLite + numpy）
│   ├── memory.py             # 用户画像管理
│   ├── tools/
│   │   └── basic_tools.py    # 内置工具集
│   ├── skills/               # 技能目录
│   │   ├── main-skills/      # 主 Agent 技能
│   │   ├── executor-skills/  # 子 Agent 技能
│   │   └── auto-skills/      # 自动沉淀的技能
│   └── prompts/              # 系统提示词
├── memory/                   # 用户画像存储
└── pocket_agent.db           # SQLite 数据库
```

## 记忆系统

### 四层架构

| 层级 | 存储 | 用途 | 工具 |
|------|------|------|------|
| 用户画像 | `memory/user_profile.md` | 永久性个人信息 | `update_user_profile` |
| 事实记忆 | SQLite 向量索引 | 项目决定、技术选型 | `save_memory(type="fact")` |
| 事件记忆 | SQLite FTS5 + 向量索引 | 重要事件结果 | `save_memory(type="episodic")` |
| 程序记忆 | `auto-skills/main/` SKILL.md | 操作流程 | `file_write` |

### 记忆工具

```python
# 存储记忆（importance: 1-10，大部分记忆 3-5 分即可）
save_memory(content="项目使用 SQLite 作为数据库", type="fact", importance=5)

# 检索记忆
search_memory(query="数据库选型", scope="all")  # scope: "all" / "session"

# 更新用户画像
update_user_profile(section="偏好设置", content="喜欢简洁的回答风格")
```

### 记忆判断规则

- **用户画像**：换了项目/场景仍然成立（姓名、职业、永久偏好）
- **事实记忆**：跟具体项目/任务相关（技术决定、工作上下文）
- **事件记忆**：重要事件结果（部署成功、问题解决）
- **不记忆**：普通闲聊、工具执行细节

## 工具列表

| 工具 | 功能 |
|------|------|
| `file_read` | 读取文件 |
| `file_write` | 写入文件 |
| `file_search` | 文件内容搜索 |
| `directory_list` | 列出目录 |
| `system_info` | 获取系统信息 |
| `shell_exec` | 执行 shell 命令 |
| `update_user_profile` | 更新用户画像 |
| `save_memory` | 保存记忆 |
| `search_memory` | 检索记忆 |
| `mcp_call` | 调用 MCP 服务 |
| `delegate_task` | 委托子 Agent 任务 |
| `tts_speak` | 语音播报 |

## 技能系统

### 技能目录结构

```
agent/skills/
├── main-skills/       # 主 Agent 手动技能
│   └── dev/
│       └── skill-creator/  # 技能创建指南
├── executor-skills/   # 子 Agent 技能
│   └── skill-creator/     # 子 Agent 技能沉淀规范
└── auto-skills/       # 自动沉淀的技能
    └── main/              # 主 Agent 自动技能
```

### 创建技能

1. 在 `agent/skills/main-skills/dev/` 下创建目录
2. 编写 `SKILL.md`，格式参考 `skill-creator/SKILL.md`
3. Agent 会自动发现并加载

## HTTP API

### 聊天（SSE 流式）

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好", "conversation_id": "test-123"}'
```

### 搜索消息

```bash
# FTS5 关键词搜索
curl "http://localhost:8000/conversations/test-123/search?q=数据库"

# 跨会话搜索
curl "http://localhost:8000/conversations/_/search?q=SQLite&cross_session=true"

# 向量语义搜索
curl "http://localhost:8000/messages/vector_search?q=数据库选型"
```

### 保存记忆

```bash
curl -X POST http://localhost:8000/memory/save \
  -H "Content-Type: application/json" \
  -d '{"content": "项目使用 SQLite", "type": "fact", "tags": ["技术选型"]}'
```

## 配置说明

### agent/config.py

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MAX_ITERATIONS` | 300 | 最大工具调用轮数 |
| `RECURSION_LIMIT` | 600 | LangGraph 递归限制（建议设为 MAX_ITERATIONS 的 2 倍） |
| `MAX_CONTEXT_TOKENS` | 128000 | 上下文窗口大小 |
| `EMBEDDING_MODEL` | bge-m3 | Embedding 模型名称 |
| `EMBEDDING_SERVER_URL` | http://127.0.0.1:8080/v1 | 本地 embedding 服务地址 |
| `EMBEDDING_MODEL_PATH` | （空） | GGUF 模型文件绝对路径，App 据此自动拉起 llama-server |

### 环境变量

| 变量 | 说明 |
|------|------|
| `DEFAULT_LLM_BASE_URL` | LLM API 地址（兼容 OpenAI 格式） |
| `LLM_API_KEY` | API 密钥 |
| `LLM_MODEL` | 模型名称 |
| `EMBEDDING_SERVER_URL` | 本地 embedding 服务地址（默认 localhost:8080） |
| `EMBEDDING_MODEL` | Embedding 模型名称 |
| `EMBEDDING_MODEL_PATH` | GGUF 模型文件绝对路径 |
| `EMBEDDING_BASE_URL` | 远程 Embedding API 地址（使用远程服务时填写） |
| `EMBEDDING_API_KEY` | 远程 Embedding API 密钥 |

## 依赖

- Python 3.10+
- LangChain / LangGraph
- numpy（向量计算）
- FastAPI / Uvicorn（HTTP 服务）
- aiosqlite（异步 SQLite）
- rich（终端 UI）

## 许可证

MIT
