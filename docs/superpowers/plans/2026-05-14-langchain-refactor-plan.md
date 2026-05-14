# Pocket-Agent LangChain 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有自定义 Agent 替换为 LangChain 官方标准实现，保持所有功能不变，适配 llama-server 部署。

**Architecture:** 使用 `create_agent()` 作为核心，通过三层适配层（LLM/工具/记忆）对接现有系统，中间件实现原有特色功能，核心业务逻辑完全复用。

**Tech Stack:** LangChain, LangGraph, langchain-openai, 纯Python标准库持久化，无额外重依赖。

---

## 文件变更清单
| 文件路径 | 操作 | 说明 |
|---------|------|------|
| `requirements.txt` | 修改 | 添加 LangChain 相关依赖 |
| `core/langchain_adapter.py` | 新建 | 适配层：Checkpointer、工具封装、中间件实现 |
| `core/agent_langchain.py` | 新建 | 新的 LangChain Agent 核心实现 |
| `main.py` | 修改 | 替换 Agent 初始化逻辑，保持外部接口不变 |
| `core/agent.py` | 保留 | 原有自定义 Agent 作为回滚备用 |
| `tools/basic_tools.py` | 修改 | 添加 `@tool` 装饰器封装现有工具 |
| `tools/mcp_tools.py` | 修改 | 添加 `@tool` 装饰器封装现有 MCP 工具 |

---

## 回滚机制
所有修改都有备份：
1. 原有 `core/agent.py` 完全保留，不修改任何代码
2. `main.py` 修改仅替换 Agent 实例化，可一键切回原实现
3. 所有新功能都在单独文件中实现，不侵入现有业务逻辑

---

## 实施任务

### Task 1: 依赖安装与环境验证
**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 添加 LangChain 依赖到 requirements.txt**
```txt
# LangChain 相关依赖 (新增)
langchain>=0.2.0
langgraph>=0.2.0
langchain-openai>=0.1.0
python-multipart>=0.0.9
```

- [ ] **Step 2: 在 Termux 中安装依赖**
```bash
pip install -r requirements.txt
```
Expected: 安装成功，无错误

- [ ] **Step 3: 验证 llama-server 连接**
```python
from langchain_openai import ChatOpenAI
llm = ChatOpenAI(base_url="http://127.0.0.1:8080/v1", api_key="dummy")
response = llm.invoke("你好")
print(response.content)
```
Expected: 正常返回模型回复

- [ ] **Step 4: 提交依赖变更**
```bash
git add requirements.txt
git commit -m "feat: add LangChain dependencies"
```

---

### Task 2: 持久化 Checkpointer 实现
**Files:**
- Create: `core/langchain_adapter.py`

- [ ] **Step 1: 实现 PocketCheckpointer 类**
```python
import os
import json
from typing import Optional, Dict, Any
from langgraph.checkpoint.base import BaseCheckpointSaver, Checkpoint

class PocketCheckpointer(BaseCheckpointSaver):
    """自定义持久化检查点，保存对话状态到本地JSON文件"""
    
    def __init__(self, save_path: str = "memory/conversations"):
        self.save_path = save_path
        os.makedirs(save_path, exist_ok=True)
    
    def get(self, config: Dict[str, Any]) -> Optional[Checkpoint]:
        thread_id = config["configurable"]["thread_id"]
        file_path = os.path.join(self.save_path, f"{thread_id}.json")
        if os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                return Checkpoint(**json.load(f))
        return None
    
    def put(self, config: Dict[str, Any], checkpoint: Checkpoint) -> None:
        thread_id = config["configurable"]["thread_id"]
        file_path = os.path.join(self.save_path, f"{thread_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(checkpoint.dict(), f, ensure_ascii=False, indent=2)
    
    def list(self, config: Optional[Dict[str, Any]] = None) -> list:
        return [f[:-5] for f in os.listdir(self.save_path) if f.endswith(".json")]
```

- [ ] **Step 2: 验证 Checkpointer 功能**
```python
from langgraph.checkpoint.memory import MemorySaver
from core.langchain_adapter import PocketCheckpointer

checkpointer = PocketCheckpointer()
test_config = {"configurable": {"thread_id": "test-123"}}
test_checkpoint = Checkpoint(
    v=1,
    ts="2026-05-14T00:00:00Z",
    channel_values={},
    channel_versions={},
    versions_seen={}
)

checkpointer.put(test_config, test_checkpoint)
loaded = checkpointer.get(test_config)
assert loaded is not None
assert loaded.ts == "2026-05-14T00:00:00Z"
print("Checkpointer test passed")
```
Expected: 测试通过，文件保存在 `memory/conversations/test-123.json`

- [ ] **Step 3: 提交代码**
```bash
git add core/langchain_adapter.py
git commit -m "feat: implement PocketCheckpointer for persistent memory"
```

---

### Task 3: 现有工具封装为 LangChain 标准格式
**Files:**
- Modify: `tools/basic_tools.py`
- Modify: `tools/mcp_tools.py`

- [ ] **Step 1: 导入 `tool` 装饰器并封装基础工具**
```python
# 在文件顶部添加导入
from langchain_core.tools import tool

# 为每个现有工具添加 @tool 装饰器，保持原有实现不变
@tool
def shell_exec(command: str) -> str:
    """
    执行shell命令。
    可以执行任何安全的系统命令，包括文件操作、进程管理、网络检测等。
    
    Args:
        command: 要执行的shell命令
    """
    # 原有实现不变
    ...

# 对 ALL_TOOLS 列表中的所有工具重复上述操作
```

- [ ] **Step 2: 封装 MCP 工具**
```python
# 同样添加 @tool 装饰器到所有 MCP 工具
@tool
def android_global_action(action: str) -> str:
    """
    执行安卓全局操作。
    
    Args:
        action: 操作类型: home/back/recent_centers/power_menu/screenshot/volume_up/volume_down
    """
    # 原有实现不变
    ...
```

- [ ] **Step 3: 实现 Superpowers 通用工具适配器**
```python
# 添加到 core/langchain_adapter.py
from langchain_core.tools import tool
from core.superpowers import pocket_superpowers

@tool
def superpowers_command(command: str) -> str:
    """
    执行superpowers技能命令。
    使用格式: superpowers <子命令> [参数]
    可用子命令: help/analyze/generate-docs/review-code/debug
    
    Args:
        command: 完整的superpowers命令，如 "superpowers analyze ."
    """
    cmd_parts = command.lower().split()
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
    elif action == 'debug':
        debug_desc = " ".join(cmd_parts[2:]) if len(cmd_parts) > 2 else ""
        return pocket_superpowers.debug_system(debug_desc)
    else:
        return f"❌ 未知命令: {action}\n请使用 'superpowers help' 查看可用命令"
```

- [ ] **Step 4: 验证工具封装**
```python
from tools.basic_tools import shell_exec
from tools.mcp_tools import android_global_action
from core.langchain_adapter import superpowers_command

assert hasattr(shell_exec, "name")
assert hasattr(android_global_action, "description")
assert hasattr(superpowers_command, "args_schema")
print("All tools wrapped successfully")
```
Expected: 测试通过，所有工具都有正确的 LangChain 工具属性

- [ ] **Step 5: 提交代码**
```bash
git add tools/basic_tools.py tools/mcp_tools.py core/langchain_adapter.py
git commit -m "feat: wrap existing tools as LangChain standard tools"
```

---

### Task 4: 中间件实现
**Files:**
- Modify: `core/langchain_adapter.py`

- [ ] **Step 1: 实现反死循环中间件**
```python
from langchain.agents.middleware import wrap_tool_call
from collections import defaultdict

_tool_call_counts = defaultdict(int)
_recent_responses = []

@wrap_tool_call
async def anti_loop_middleware(tool_call, next_middleware):
    """反死循环检测中间件"""
    tool_name = tool_call["name"]
    
    # 检测同一工具连续调用超过5次
    _tool_call_counts[tool_name] += 1
    if _tool_call_counts[tool_name] > 5:
        return f"⚠️ 工具 {tool_name} 连续调用超过5次，已中断。请尝试其他方式解决问题。"
    
    # 检测重复响应
    if len(_recent_responses) >= 3 and len(set(_recent_responses[-3:])) == 1:
        return "⚠️ 检测到重复响应，疑似死循环。请重新表述问题。"
    
    # 执行工具
    result = await next_middleware(tool_call)
    
    # 记录响应
    _recent_responses.append(str(result)[:200])
    if len(_recent_responses) > 10:
        _recent_responses.pop(0)
    
    return result
```

- [ ] **Step 2: 实现 MCP 健康检测中间件**
```python
import asyncio

@wrap_tool_call
async def mcp_health_check_middleware(tool_call, next_middleware):
    """MCP服务健康检测中间件"""
    tool_name = tool_call["name"]
    
    # 安卓工具调用前检测NeuralBridge服务
    if tool_name.startswith("android_"):
        try:
            proc = await asyncio.create_subprocess_shell(
                "nc -zv 127.0.0.1 7474",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await proc.communicate()
            if proc.returncode != 0:
                return "❌ NeuralBridge服务未运行，请先启动安卓控制服务。"
        except:
            pass
    
    # 执行工具
    result = await next_middleware(tool_call)
    return result
```

- [ ] **Step 3: 提交代码**
```bash
git add core/langchain_adapter.py
git commit -m "feat: implement anti-loop and MCP health check middleware"
```

---

### Task 5: LangChain Agent 核心实现
**Files:**
- Create: `core/agent_langchain.py`

- [ ] **Step 1: 实现 Agent 核心类**
```python
from typing import List, Tuple, Dict, Any
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langchain_core.callbacks import CallbackManager, BaseCallbackHandler
from langgraph.checkpoint.memory import MemorySaver
from core.langchain_adapter import PocketCheckpointer, anti_loop_middleware, mcp_health_check_middleware, superpowers_command
from tools.basic_tools import ALL_TOOLS
from tools.mcp_tools import ALL_MCP_TOOLS

class StreamingUICallback(BaseCallbackHandler):
    """流式输出回调，对接现有UI"""
    def __init__(self, ui):
        self.ui = ui
    
    def on_llm_new_token(self, token: str, **kwargs) -> None:
        if token and self.ui:
            self.ui.print_stream_chunk(token)

class LangChainPocketAgent:
    """基于LangChain的PocketAgent实现"""
    
    def __init__(self, system_prompt: str = "", llm_config: Dict = None, ui=None):
        self.ui = ui
        self.system_prompt = system_prompt
        
        # 初始化LLM
        self.llm = ChatOpenAI(
            base_url=llm_config.get("base_url", "http://127.0.0.1:8080/v1"),
            api_key=llm_config.get("api_key", "dummy"),
            model=llm_config.get("model", "gelab-zero-4b-preview"),
            temperature=llm_config.get("temperature", 0.7),
            max_tokens=llm_config.get("max_tokens", 8000),
            streaming=True,
            callback_manager=CallbackManager([StreamingUICallback(ui)]) if ui else None
        )
        
        # 收集所有工具
        self.tools = ALL_TOOLS + ALL_MCP_TOOLS + [superpowers_command]
        
        # 初始化持久化记忆
        self.checkpointer = PocketCheckpointer()
        
        # 创建Agent
        self.agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
            checkpointer=self.checkpointer,
            middleware=[
                anti_loop_middleware,
                mcp_health_check_middleware
            ]
        )
        
        # 会话配置
        self.config = {"configurable": {"thread_id": "default-session"}}
        self.max_iterations = 10
    
    async def run_conversation(self, user_message: str) -> Tuple[str, bool]:
        """运行对话，保持与原有接口一致"""
        try:
            # 调用Agent
            result = await self.agent.ainvoke(
                {"messages": [HumanMessage(content=user_message)]},
                config={
                    **self.config,
                    "recursion_limit": self.max_iterations
                }
            )
            
            # 获取最后一条回复
            last_message = result["messages"][-1]
            return (last_message.content, True)  # 标记使用了流式输出
            
        except Exception as e:
            return (f"❌ Agent 执行错误: {str(e)}", False)
    
    def clear_history(self) -> None:
        """清空对话历史"""
        # 重置会话
        self.config = {"configurable": {"thread_id": f"session-{id(self)}"}}
```

- [ ] **Step 2: 验证 Agent 初始化**
```python
from core.agent_langchain import LangChainPocketAgent

agent = LangChainPocketAgent(
    system_prompt="你是一个 helpful assistant",
    llm_config={"base_url": "http://127.0.0.1:8080/v1"}
)
assert len(agent.tools) > 0
assert agent.agent is not None
print("Agent initialized successfully")
```
Expected: 初始化成功，无错误

- [ ] **Step 3: 提交代码**
```bash
git add core/agent_langchain.py
git commit -m "feat: implement LangChain PocketAgent core"
```

---

### Task 6: 主流程集成
**Files:**
- Modify: `main.py`

- [ ] **Step 1: 修改 main.py 适配新 Agent**
```python
# 替换原有Agent导入
# from core.init import create_pocket_agent
from core.agent_langchain import LangChainPocketAgent

# 在main()函数中替换Agent初始化
# agent = create_pocket_agent("pocket-agent-v1", llm_manager=llm_manager, ui=ui)
agent = LangChainPocketAgent(
    system_prompt="""你是Pocket-Agent，一个轻量级的移动端AI助手。
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
""",
    llm_config={
        "base_url": os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        "api_key": os.getenv("LLM_API_KEY", "dummy"),
        "model": os.getenv("LLM_MODEL", "gelab-zero-4b-preview"),
        "temperature": float(os.getenv("LLM_TEMPERATURE", "0.7")),
    },
    ui=ui
)
```

- [ ] **Step 2: 适配撤回消息功能**
```python
# 在撤回消息逻辑部分替换原有实现
if user_input.lower() in ['/undo', '/撤回']:
    # 重新初始化Agent，清空历史
    agent = LangChainPocketAgent(
        system_prompt=agent.system_prompt,
        llm_config={
            "base_url": os.getenv("LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
            "api_key": os.getenv("LLM_API_KEY", "dummy"),
            "model": os.getenv("LLM_MODEL", "gelab-zero-4b-preview"),
        },
        ui=ui
    )
    ui.print_success("✅ 已清空对话历史，你可以重新输入")
    continue
```

- [ ] **Step 3: 验证主程序启动**
```bash
python main.py
```
Expected: 正常启动，显示欢迎界面，可以正常对话

- [ ] **Step 4: 提交代码**
```bash
git add main.py
git commit -m "feat: integrate LangChain Agent into main flow"
```

---

### Task 7: 全功能测试与优化
**Files:**
- All modified files

- [ ] **Step 1: 基础功能测试**
  - [ ] 普通对话功能正常
  - [ ] 工具调用正常 (如 `执行shell命令 echo hello`)
  - [ ] Superpowers 命令正常 (如 `superpowers help`)
  - [ ] 撤回消息功能正常
  - [ ] 流式输出正常
  - [ ] 退出命令正常

- [ ] **Step 2: 边界测试**
  - [ ] 长文本输入不会导致闪退
  - [ ] 工具调用错误有友好提示
  - [ ] 网络错误能正常捕获
  - [ ] 连续对话10轮以上正常

- [ ] **Step 3: 性能测试**
  - [ ] Python进程内存占用 ≤ 150MB
  - [ ] 回复速度 ≥ 15 tokens/秒 (骁龙8 Gen2)
  - [ ] 启动时间 ≤ 3秒

- [ ] **Step 4: 提交最终版本**
```bash
git add .
git commit -m "feat: complete LangChain refactor, all features working"
```

---

## 验证标准
✅ 所有原有功能 100% 可用，用户无感知  
✅ 内存占用 ≤ 150MB  
✅ 连续运行24小时无崩溃  
✅ 上下文溢出自动保护生效

---

Plan complete and saved to `docs/superpowers/plans/2026-05-14-langchain-refactor-plan.md`. Two execution options:

**1. Inline Execution (recommended for this project)** - Execute tasks in this session using executing-plans, batch execution with checkpoints after each major task

**2. Subagent-Driven** - I dispatch a fresh subagent per task, review between tasks, fast iteration

Which approach would you prefer?
