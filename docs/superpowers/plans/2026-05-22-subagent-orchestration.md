# 端云协同子智能体架构 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现主Agent+子Agent的端云协同架构，主Agent负责任务分解+监督，子Agent负责具体手机操控

**Architecture:** 主Agent通过SubAgentMiddleware的task()工具派发任务给子Agent，任务状态通过文件系统(memory/tasks/)同步。主Agent提示词瘦身(移除手机操控细节)，子Agent拥有完整手机操控提示词+独立技能目录(executor-skills/)

**Tech Stack:** Python, LangChain create_agent, deepagents SubAgentMiddleware, LangGraph

**前置条件:** deepagents 已安装 (pip install deepagents, 已执行)

---

## 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| 修改 | `agent/config.py` | 新增 EXECUTOR_SKILLS_DIR, AUTO_SKILLS_DIR, TASKS_DIR |
| 新建 | `agent/logger.py` | AgentLogger 日志系统 |
| 新建 | `agent/prompts/executor_enhance.py` | 子Agent增强提示词 |
| 修改 | `agent/prompts/agent_enhance.py` | 移除手机操控细节，加入子Agent委托说明 |
| 修改 | `agent/agent_langchain.py` | 集成 SubAgentMiddleware，重构 load_skills_list |
| 创建 | `agent/executor-skills/phone-control-guide/SKILL.md` | 从skills/移入 |
| 创建 | `agent/executor-skills/neuralbridge-operation-standard/SKILL.md` | 从skills/移入 |
| 创建 | `agent/auto-skills/main/.gitkeep` | 主Agent自动沉淀目录 |
| 创建 | `agent/auto-skills/executor/.gitkeep` | 子Agent自动沉淀目录 |
| 可选 | `main.py` | 如有接口变化则调整 |

---

### Task 1: 目录结构与配置更新

**Files:**
- Modify: `agent/config.py:29-33`
- Execute: mkdir 创建目录

- [ ] **Step 1: 更新 config.py，新增配置项**

在 `agent/config.py` 中，在 `SKILLS_DIR` 配置后面追加：

```python
# ==============================
# 子Agent系统配置
# ==============================
# 子Agent技能目录
EXECUTOR_SKILLS_DIR = os.path.join(PROJECT_ROOT, "agent", "executor-skills")

# 自动沉淀技能目录
AUTO_SKILLS_DIR = os.path.join(PROJECT_ROOT, "agent", "auto-skills")

# 任务文件存储目录
TASKS_DIR = os.path.join(PROJECT_ROOT, "memory", "tasks")

# ==============================
# 日志配置
# ==============================
# 日志目录
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")
```

- [ ] **Step 2: 创建目录结构**

```bash
# 从项目根目录执行
cd /mnt/sdcard/手机agent开发/Pocket-Agent

# 创建 executor-skills 目录（子Agent技能）
mkdir -p agent/executor-skills/phone-control-guide
mkdir -p agent/executor-skills/neuralbridge-operation-standard

# 移动现有技能文件到子Agent目录
cp agent/skills/phone-control-guide/SKILL.md agent/executor-skills/phone-control-guide/SKILL.md
cp agent/skills/neuralbridge-operation-standard/SKILL.md agent/executor-skills/neuralbridge-operation-standard/SKILL.md

# 注意：原 skills/ 下的这两个文件保留，之后 Task 5 修改 load_skills_list 后会按类型过滤
# 但为了清晰，可以直接删除原目录（后续Task再做）
# 创建自动沉淀目录
mkdir -p agent/auto-skills/main
mkdir -p agent/auto-skills/executor

# 创建日志目录
mkdir -p logs

# 给自动沉淀目录加 placeholder
touch agent/auto-skills/main/.gitkeep
touch agent/auto-skills/executor/.gitkeep
```

Expected output: 目录创建成功，无报错

- [ ] **Step 3: 验证目录结构**

```bash
ls -la agent/executor-skills/phone-control-guide/
ls -la agent/executor-skills/neuralbridge-operation-standard/
ls -la agent/auto-skills/main/
ls -la logs/
```

Expected: 各目录存在且有对应文件

---

### Task 2: AgentLogger 日志系统

**Files:**
- Create: `agent/logger.py`

- [ ] **Step 1: 创建 agent/logger.py**

```python
#!/usr/bin/env python3
"""
Agent 日志系统 - 按天归档，记录执行关键信息
"""

import os
import json
from datetime import datetime
from typing import Optional


class AgentLogger:
    """Agent 日志记录器，按天生成日志文件"""

    def __init__(self, log_dir: str):
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def _get_today_file(self) -> str:
        """获取今天的日志文件路径"""
        today = datetime.now().strftime("%Y-%m-%d")
        return os.path.join(self.log_dir, f"{today}.md")

    def _get_timestamp(self) -> str:
        """获取当前时间戳 [HH:MM:SS]"""
        return datetime.now().strftime("[%H:%M:%S]")

    def log(self, content: str):
        """写入日志到当天文件"""
        filepath = self._get_today_file()
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(content + "\n")

    def log_event(self, event_type: str, detail: str, task_id: str = ""):
        """记录单行事件"""
        ts = self._get_timestamp()
        tag = f"[{task_id}] " if task_id else ""
        self.log(f"{ts} {tag}{event_type}: {detail}")

    def log_task_start(self, task_id: str, objective: str, agent_type: str):
        """记录任务开始"""
        ts = self._get_timestamp()
        self.log(f"\n## {ts} 任务 {task_id}")
        self.log(f"- 目标: {objective}")
        self.log(f"- Agent类型: {agent_type}")
        self.log(f"- 状态: 进行中")

    def log_task_complete(
        self,
        task_id: str,
        objective: str,
        main_rounds: int,
        main_time_s: float,
        sub_rounds: int,
        sub_time_s: float,
        result: str,
        steps_detail: Optional[list[dict]] = None,
    ):
        """记录任务完成汇总"""
        ts = self._get_timestamp()
        self.log(f"\n## {ts} 任务 {task_id} - 完成")
        self.log(f"- 目标: {objective}")
        self.log(f"- 主Agent: ({main_rounds}轮, {main_time_s:.0f}s)")
        self.log(f"- 子Agent: ({sub_rounds}轮, {sub_time_s:.0f}s)")
        self.log(f"- 结果: {result}")

        if steps_detail:
            self.log(f"\n### 步骤详情")
            self.log(f"| 步骤 | 用时 | 结果 |")
            self.log(f"|------|------|------|")
            for step in steps_detail:
                self.log(f"| {step['id']}. {step['desc']} | {step.get('time', '?')}s | {step.get('status', '?')} |")

    def log_subagent_event(self, task_id: str, step_id: int, step_desc: str, event: str):
        """记录子Agent执行过程中的事件"""
        ts = self._get_timestamp()
        self.log(f"{ts} [{task_id}] 步骤{step_id}({step_desc}): {event}")
```

- [ ] **Step 2: 验证文件创建**

```bash
python3 -c "import sys; sys.path.insert(0, '.'); from agent.logger import AgentLogger; l = AgentLogger('logs'); l.log_event('test', 'logger ok'); print('Logger OK'); print(open('logs/' + __import__('datetime').datetime.now().strftime('%Y-%m-%d') + '.md').read())"
```

Expected: Logger OK + 日志内容包含测试事件

---

### Task 3: 子Agent增强提示词

**Files:**
- Create: `agent/prompts/executor_enhance.py`

- [ ] **Step 1: 创建 executor_enhance.py**

内容从当前的 `agent_enhance.py` 提取手机操控部分，加上子Agent专属规则。

```python
"""
子Agent增强提示词
包含手机操控完整规则、工具使用规范、故障排查、人工介入等
"""

prompt = """## 一、工具使用规则

你只能使用以下工具：{tool_names}

### shell_exec（首选方案）
- 打开App: `am start -p <包名>`
- Termux API: `termux-tts-speak`、`termux-notification`、`termux-clipboard-set/get`、`termux-battery-status` 等
- 系统信息: `getprop`、`pm list packages`
- 参考 executor-skills 中的 phone-control-guide 获取完整命令列表

### mcp_call（降级方案，仅在shell命令无法完成时使用）
- 需要UI交互时使用 NeuralBridge (http://127.0.0.1:7474/mcp)
- 先调用 mcp_call(server_url="http://127.0.0.1:7474/mcp", tool_name="tools/list") 获取可用工具
- 优先用 android_get_ui_tree 获取UI树（纯文本，零token消耗）
- 用 android_tap/android_input_text 操控
- 禁止猜测坐标，所有坐标来自UI树返回的 bounds
- 每次操作后调用 android_wait_for_idle 等待界面稳定
- 参考 executor-skills 中的 neuralbridge-operation-standard 获取完整操作规范

### file_read / file_write
- 读 task.json 了解任务目标和步骤
- 每完成一步用 file_write 更新对应步骤的 status
- 写执行日志供主Agent汇总

### system_info
- 用于快速获取设备状态（电量、网络等），帮助判断是否适合执行任务

## 二、执行规则

1. 【核心心态】步骤是路线图，不是铁律。遇到实际情况和步骤描述不一致时，根据 objective 自行判断调整。只要最终能达成目标，路径可以自由变化。

2. 【执行流程】
   a. 用 file_read 读取任务文件，理解完整目标
   b. 审视 steps 数组，理解整体意图
   c. 按 steps 顺序逐个执行，但保持灵活
   d. 当前步骤标记为 in_progress 后开始执行
   e. 完成后标记为 completed，继续下一步
   f. 不适用或可跳过的步骤标记为 skipped 并说明原因

3. 【快速失败】同一个方案失败后最多换2个替代方案再试，仍然失败就跳过该步骤。

4. 【人工介入】只有所有可行方案都试过仍失败时才能申请：
   - 用 shell_exec 执行 termux-tts-speak 语音通知用户
   - 通知后等待30秒，用户可能手动帮解决
   - 用户帮忙后问题解决则继续，否则标记失败返回主Agent

5. 【返回要求】所有步骤执行完后返回完整摘要：
   - 成功步骤列表
   - 失败/跳过步骤及原因
   - 最终结果
   - 是否申请了人工介入

## 三、可用技能

{skills_list}
```
"""
```

- [ ] **Step 2: 验证导入**

```bash
python3 -c "import sys; sys.path.insert(0, '.'); from agent.prompts.executor_enhance import prompt; print('OK, length:', len(prompt))"
```

Expected: OK, length: xxx

---

### Task 4: 重构 load_skills_list() 函数

**Files:**
- Modify: `agent/agent_langchain.py:42-89`

- [ ] **Step 1: 修改 load_skills_list() 接受 agent_type 参数**

将原来的函数改为：

```python
def load_skills_list(agent_type: str = "main") -> str:
    """
    根据agent类型加载对应技能列表
    Args:
        agent_type: "main" 或 "executor"
    """
    skills_dir = SKILLS_DIR if agent_type == "main" else EXECUTOR_SKILLS_DIR

    if not os.path.exists(skills_dir):
        return "暂无可用技能。"

    skills = []
    for d in os.listdir(skills_dir):
        skill_dir = os.path.join(skills_dir, d)
        if not os.path.isdir(skill_dir):
            continue

        skill_path = None
        for filename in SKILL_FILE_NAMES:
            candidate_path = os.path.join(skill_dir, filename)
            if os.path.exists(candidate_path):
                skill_path = candidate_path
                break

        if skill_path:
            try:
                with open(skill_path, 'r', encoding='utf-8') as f:
                    desc = ""
                    for _ in range(20):
                        line = f.readline()
                        if not line:
                            break
                        if line.startswith("description:"):
                            desc = line.split(":", 1)[1].strip()
                            break
                skills.append(f"- {d}: {desc}")
            except Exception:
                skills.append(f"- {d}: 无描述")

    if not skills:
        return "暂无可用技能。"

    skills_text = "\n".join(skills)
    usage_note = f"\n\n使用说明：用file_read工具读取对应SKILL.md文件即可"
    return skills_text + usage_note
```

- [ ] **Step 2: 更新原调用处**

在 `_create_agent()` 中，将：
```python
skills_list = load_skills_list()
```
改为：
```python
skills_list = load_skills_list("main")
```

- [ ] **Step 3: 验证改动**

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from agent.agent_langchain import load_skills_list
main_skills = load_skills_list('main')
executor_skills = load_skills_list('executor')
print('Main skills count:', len(main_skills))
print('Executor skills count:', len(executor_skills))
print('Main contains phone-control?', 'phone-control' in main_skills)
print('Executor contains phone-control?', 'phone-control' in executor_skills)
"
```

Expected:
- Main skills 不包含 phone-control-guide、neuralbridge
- Executor skills 包含 phone-control-guide、neuralbridge

---

### Task 5: 主Agent提示词瘦身

**Files:**
- Modify: `agent/prompts/agent_enhance.py`

- [ ] **Step 1: 移除手机操控相关段落**

从 `agent_enhance.py` 中删除以下内容：

1. 第7条 "【手机操控优化】"（优先读phone-control-guide skill等）
2. 第8条 "【App内操控流程】"（UI树/点击/输入等全部流程）
3. 第11条 "调用方式"（curl示例）
4. 第12条 "使用规则"（NeuralBridge规则）
5. 第8条中的WebView输入框适配方案

保留：
1. 第1、2条 工具使用规范
2. 第3条 回答规则（简洁）
3. 第5条 多步骤任务执行
4. 第6条 禁止角色扮演
5. 第13条 技能系统

删除后的 `agent_enhance.py`：

```python
prompt = """重要规则：

## 一、工具使用规范

1. 你只能使用以下工具：{tool_names}。禁止编造不存在的工具名称或功能。

2. 【必记规则】当用户主动说出任何个人信息、偏好、习惯、要求时，必须调用 `update_user_profile` 工具记录到画像中。

## 二、回答与执行规则

3. 回答要简洁，符合移动端使用场景。

4. 【文件操作】写入/修改文件优先使用`file_write`/`file_read`工具。

5. 【多步骤任务执行】当用户给的是多步骤任务时，你必须：
   a. 先用 write_todos 将任务分解为细粒度步骤，标记第一个为 in_progress
   b. 判断是否需要操作手机。如果需要，使用 task() 工具派发给 executor 子Agent执行
   c. 不需要操作手机的步骤（查资料、读文件、回答等）自己完成
   d. 待子Agent返回后，汇总结果，通知用户
   e. 【快速失败】同一个方案失败后最多换1个替代方案再试，仍然失败就告知用户

6. 【禁止角色扮演工具调用】说"正在语音播报"、"已调用XX工具"等描述时，必须有对应的实际工具调用在先。

## 三、子Agent使用规则

7. 【任务分解要求】派发给子Agent的任务必须分解到原子粒度（如"打开拼多多APP"、"在搜索框输入'黑色体恤'"，而不是"去拼多多买个衣服"）。因为子Agent可能使用本地小模型，步骤模糊会导致它无法执行。

8. 【任务文件】调用 task() 之前，先用 file_write 将任务写入 memory/tasks/ 目录。task() 的 description 中只需要告诉子Agent任务目标和文件路径。

9. 【子Agent返回后】汇总子Agent的执行结果，然后用 termux-tts-speak 语音通知用户。如子Agent申请了人工介入，在回复中提醒用户。

10. 【技能沉淀】成功完成某类任务后，可以回顾执行路径，生成一个SKILL.md 到 auto-skills/main/ 目录，方便下次复用。

## 四、技能系统

11. 【可用技能列表】：
{skills_list}
    - 需要用某个技能时，用file_read读取对应SKILL.md
    - 已经读过的技能不要重复读取
"""
```

> 注意：{tool_names} 和 {skills_list} 占位符保持不变

- [ ] **Step 2: 验证修改后格式**

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from agent.prompts.agent_enhance import prompt
# 测试格式化（工具名示例、技能列表示例）
formatted = prompt.format(tool_names='tool1, tool2', skills_list='- skill1: desc')
print('Format OK, length:', len(formatted))
# 验证不再包含手机操控关键词
assert 'NeuralBridge' not in formatted, 'Should not contain NeuralBridge'
assert 'android_get_ui_tree' not in formatted, 'Should not contain UI tree'
print('Verified: no phone control details in main prompt')
"
```

Expected: Format OK + no phone control details

---

### Task 6: 集成 SubAgentMiddleware

**Files:**
- Modify: `agent/agent_langchain.py`
  - 新增 import
  - 修改 _create_agent() 方法
  - 修改 __init__() 方法

- [ ] **Step 1: 在文件顶部添加导入**

在 `agent/agent_langchain.py` 的 import 区域增加：

```python
# 子Agent相关
from deepagents.middleware.subagents import SubAgentMiddleware
from deepagents.backends import StateBackend
from .config import (
    MAX_ITERATIONS,
    RECURSION_LIMIT,
    MAX_CONTEXT_TOKENS,
    SKILLS_DIR,
    EXECUTOR_SKILLS_DIR,
    SKILL_FILE_NAMES,
    PROJECT_ROOT,
    TASKS_DIR,
    LOGS_DIR,
    TERMUX_API_CHECK_CMD,
    TERMUX_API_INSTALL_GUIDE,
    ENV_LIGHT_SENSOR_CMD,
    ENV_ACCEL_SENSOR_CMD,
    ENV_TIME_CMD,
    ENV_TIMEZONE_CMD,
)
from .prompts.executor_enhance import prompt as executor_enhance_prompt
from .logger import AgentLogger
```

更新 `from .tools.basic_tools import ALL_TOOLS, set_memory_instance` 这行保持不变。

- [ ] **Step 2: 在 __init__() 中初始化日志和任务目录**

在 `self.memory = LongTermMemory(...)` 之后添加：

```python
# 初始化日志系统
self.logger = AgentLogger(log_dir=LOGS_DIR)
# 确保任务目录存在
os.makedirs(TASKS_DIR, exist_ok=True)

# 初始化子Agent相关属性（在_create_agent中会用到）
self._agent_type = "main"
```

- [ ] **Step 3: 修改 _create_agent() 方法，集成 SubAgentMiddleware**

在 `_create_agent()` 方法中，将 middleware 列表改为：

```python
def _create_agent(self) -> None:
    """使用官方create_agent创建Agent"""
    # 预加载主Agent技能列表
    skills_list = load_skills_list("main")
    
    # 预加载子Agent技能列表（用于构建子Agent system prompt）
    executor_skills = load_skills_list("executor")
    
    # 收集中间件工具名
    all_tool_names = [t.name for t in ALL_TOOLS]
    
    # ── 构建子Agent系统提示词 ──
    executor_tools = [t for t in ALL_TOOLS if t.name in (
        "shell_exec", "file_read", "file_write", "mcp_call", "system_info"
    )]
    executor_tool_names = ", ".join(t.name for t in executor_tools)
    
    executor_system_content = f"""你是一个手机操控执行助手，运行在 Android Termux 环境中。

## 核心原则
1. 以 task.json 为路线图，根据实际情况灵活调整
2. 优先使用 shell 命令（Termux API），无法完成时降级 MCP
3. 每完成一步，用 file_write 更新 task.json 中的 status
4. 语音仅用于申请人工介入

## 执行流程
1. 用 file_read 读取任务文件，理解完整目标和步骤
2. 按 steps 顺序逐个执行，但保持灵活——步骤是路线图不是铁律
3. 当前步骤标记为 in_progress 后开始执行
4. 完成后标记为 completed，继续下一步
5. 不适用或可跳过的步骤标记为 skipped 并说明原因
6. 发现更好的完成方式（更便宜的商品、更好的路径）可以自由调整

## 失败处理
- 失败后最多换2种不同方案重试
- 全部失败后跳过该步骤（标记 failed）
- 关键步骤失败才考虑人工介入

## 人工介入
- 所有方案都试过仍失败时申请人工介入
- shell_exec 执行 termux-tts-speak 语音通知用户
- 通知后等待30秒，用户可能手动帮解决
- 真的无法继续时返回 FAILED 给主Agent

## 返回要求（重要）
执行完成后返回完整执行摘要：
✅ 成功步骤: 步骤1, 2, 3, ...
❌ 失败步骤: 步骤4（原因）
📝 最终结果: ...
🆘 人工介入: 有/无

{executor_enhance_prompt.format(
    tool_names=executor_tool_names,
    skills_list=executor_skills
)}"""

    # ── 构建子Agent中间件（使用与主Agent相似的配置，但工具调用限制相同）──
    executor_middleware = [
        ToolCallIdMiddleware(),
        ModelCallLimitMiddleware(
            run_limit=MAX_ITERATIONS,
            exit_behavior="end",
        ),
    ]

    # ── 配置所有中间件 ──
    middleware = [
        # 主Agent中间件
        MCPToolResultMiddleware(),
        ImageOptimizationMiddleware(),
        ToolCallIdMiddleware(),
        TodoListMiddleware(),
        SubAgentMiddleware(
            backend=StateBackend(),
            subagents=[
                {
                    "name": "executor",
                    "description": "执行手机操控任务，按task.json规划逐步执行，适合所有需要操作手机的场景",
                    "model": self.llm,  # 使用与主Agent相同的模型（用户可自行调整）
                    "system_prompt": executor_system_content,
                    "tools": executor_tools,
                    "middleware": executor_middleware,
                }
            ],
            system_prompt=None,  # 不额外注入task说明，已在agent_enhance中说明
        ),
        SummarizationMiddleware(
            model=self.llm,
            trigger=("tokens", MAX_CONTEXT_TOKENS // 2),
            keep=("messages", 20),
        ),
        ModelCallLimitMiddleware(
            run_limit=MAX_ITERATIONS,
            exit_behavior="end",
        ),
    ]
    
    # 手机操控相关中间件（MCPToolResultMiddleware、ImageOptimizationMiddleware）
    # 对主Agent其实已经不需要了（主Agent不再直接调用MCP），但保留无害
    # 后续可以优化为按条件启用

    # 收集中间件工具名
    for mw in middleware:
        if hasattr(mw, 'tools') and mw.tools:
            all_tool_names.extend(t.name for t in mw.tools)
    tool_names_str = ", ".join(sorted(set(all_tool_names)))

    enhanced_system_prompt = self.base_system_prompt + "\n\n" + agent_enhance_prompt.format(
        tool_names=tool_names_str,
        skills_list=skills_list,
    )

    self.checkpointer = MemorySaver()
    self._system_prompt = enhanced_system_prompt

    self.agent = create_agent(
        model=self.llm,
        tools=ALL_TOOLS,
        system_prompt=enhanced_system_prompt,
        checkpointer=self.checkpointer,
        middleware=middleware,
    )
```

- [ ] **Step 4: 验证 import 和基本运行**

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from agent.agent_langchain import LangChainPocketAgent, load_skills_list
print('Import OK')
# 打印子Agent工具名
from agent.tools.basic_tools import ALL_TOOLS
executor_names = [t.name for t in ALL_TOOLS if t.name in ('shell_exec', 'file_read', 'file_write', 'mcp_call', 'system_info')]
print('Executor tools:', executor_names)
"
```

Expected: Import OK + Executor tools: ['shell_exec', 'file_read', 'file_write', 'system_info', 'mcp_call']

---

### Task 7: 主Agent任务分解与派发逻辑

**Files:**
- Modify: `agent/agent_langchain.py` (run_conversation方法)
- 注意：run_conversation 的改动是在系统提示词层面引导，不需要硬编码逻辑

- [ ] **Step 1: 在提示词中引导任务分解流程**

已在 Task 5 的 agent_enhance.py 第5条中体现。确保提示词明确要求主Agent：
1. 遇到复杂任务先 write_todos 分解
2. 需要操作手机时调用 task() 
3. task() description 中包含文件路径

不需要改动 run_conversation 的代码逻辑，因为主Agent会根据提示词自行决策。

- [ ] **Step 2: 添加 run_conversation 返回后的日志记录**

在 `run_conversation()` 方法的末尾，返回之前，添加日志记录：

```python
# 记录日志
try:
    elapsed = int((datetime.now() - start_time).total_seconds())
    if hasattr(self, 'logger'):
        task_id = f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        self.logger.log_event(
            "对话完成",
            f"耗时{elapsed}秒, 工具调用{tool_call_count}次",
            task_id=task_id,
        )
except Exception:
    pass  # 日志不影响主流程
```

这段代码放在 `run_conversation()` 中、`self.ui.console.print(...)` 后面即可。

【定位参考：agent/agent_langchain.py 第904行附近】

```python
# 计算总耗时并获取token用量，打印完成行 | 上下文条
elapsed = int((datetime.now() - start_time).total_seconds())
usage = await self.get_context_usage()
if self.ui:
    bar_text = ""
    if usage["current"] > 0:
        bar_text = self.ui.format_context_bar(usage)
    self.ui.console.print(
        f"\n\n✅ [dim cyan]完成 (总耗时 {elapsed} 秒)[/dim cyan] {bar_text}"
    )

# 【新增】记录日志
try:
    task_id = f"conv_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    self.logger.log_event(
        "对话完成",
        f"耗时{elapsed}秒, 工具调用{tool_call_count}次",
        task_id=task_id,
    )
except Exception:
    pass
```

---

### Task 8: 移除原 skills/ 中的手机操控目录

**Files:**
- Modify: 删除目录 `agent/skills/phone-control-guide/` 和 `agent/skills/neuralbridge-operation-standard/`

- [ ] **Step 1: 确认 executor-skills 中已有完整副本后删除原目录**

```bash
# 先确认已复制
diff agent/executor-skills/phone-control-guide/SKILL.md agent/skills/phone-control-guide/SKILL.md && echo "phone-control-guide identical"
diff agent/executor-skills/neuralbridge-operation-standard/SKILL.md agent/skills/neuralbridge-operation-standard/SKILL.md && echo "neuralbridge identical"

# 确认一致后删除原目录
rm -rf agent/skills/phone-control-guide
rm -rf agent/skills/neuralbridge-operation-standard
```

Expected: 两个diff返回一致，删除后原skills/下不再有这两个目录

---

### Task 9: 任务文件系统辅助工具（可选增强）

**Files:**
- Create: `agent/task_manager.py`

这个文件提供辅助函数，不是必须的（主Agent直接用file_read/file_write操作），但为了方便可以做一个轻量封装。

- [ ] **Step 1: 如果选择实现，创建 agent/task_manager.py**

```python
#!/usr/bin/env python3
"""
任务文件系统管理
提供任务文件的创建、读取、更新操作
主Agent通过 file_read/file_write 直接操作，本模块作为服务端辅助
"""

import os
import json
import uuid
from datetime import datetime
from typing import Optional


TASK_FILE = "task.json"
RESULT_FILE = "result.json"


def generate_task_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"task_{ts}"


def init_task(tasks_dir: str, objective: str, steps: list[dict], guidance: str = "") -> str:
    """创建新任务，返回 task_id"""
    task_id = generate_task_id()
    task_dir = os.path.join(tasks_dir, task_id)
    os.makedirs(task_dir, exist_ok=True)

    task_data = {
        "task_id": task_id,
        "objective": objective,
        "created_at": datetime.now().isoformat(),
        "steps": steps,
        "guidance": guidance,
        "voice_notify": True,
        "status": "running",
    }

    path = os.path.join(task_dir, TASK_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task_data, f, ensure_ascii=False, indent=2)

    return task_id


def get_task_path(tasks_dir: str, task_id: str) -> str:
    return os.path.join(tasks_dir, task_id, TASK_FILE)


def get_result_path(tasks_dir: str, task_id: str) -> str:
    return os.path.join(tasks_dir, task_id, RESULT_FILE)
```

（此文件可选实现，主Agent直接用 file_read/file_write 也可）

---

### Task 10: 最终集成验证

- [ ] **Step 1: 导入全部模块**

```bash
python3 -c "
import sys; sys.path.insert(0, '.')
from agent.config import SKILLS_DIR, EXECUTOR_SKILLS_DIR, AUTO_SKILLS_DIR, TASKS_DIR, LOGS_DIR
from agent.agent_langchain import LangChainPocketAgent, load_skills_list
from agent.logger import AgentLogger
from agent.prompts.agent_enhance import prompt as main_prompt
from agent.prompts.executor_enhance import prompt as executor_prompt

# 验证目录
assert os.path.exists(EXECUTOR_SKILLS_DIR), 'executor-skills dir missing'
assert os.path.exists(os.path.join(EXECUTOR_SKILLS_DIR, 'phone-control-guide', 'SKILL.md')), 'phone-control missing'
assert os.path.exists(os.path.join(EXECUTOR_SKILLS_DIR, 'neuralbridge-operation-standard', 'SKILL.md')), 'neuralbridge missing'

# 验证技能加载
main_skills = load_skills_list('main')
executor_skills = load_skills_list('executor')
assert 'phone-control' not in main_skills, 'main should not have phone-control'
assert 'phone-control' in executor_skills, 'executor should have phone-control'

# 验证日志
l = AgentLogger(log_dir=LOGS_DIR)
l.log_event('verify', 'all checks passed')

print('✅ All integration checks passed')
"
```

Expected: ✅ All integration checks passed

---

## 自检

**Spec对照：**
- ✅ 目标1（任务分解）: Task 5 提示词第5条 + Task 7
- ✅ 目标2（端云协同）: Task 6 SubAgentMiddleware
- ✅ 目标3（状态落盘）: Task 9 task.json 文件系统
- ✅ 目标4（语音通知）: Task 5 提示词第9条
- ✅ 目标5（人工介入）: Task 3 executor_enhance 第4条
- ✅ 目标6（日志系统）: Task 2 AgentLogger
- ✅ 技能目录分离: Task 1 + Task 4 + Task 8
- ✅ 主Agent提示词瘦身: Task 5
- ✅ 子Agent完整提示词: Task 3 + Task 6

**占位符检查：** 无TBD/TODO，所有代码块完整

**类型一致性：** 所有方法签名、工具名、配置名在任务间一致
