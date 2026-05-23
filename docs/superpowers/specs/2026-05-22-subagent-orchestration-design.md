# 端云协同子智能体架构设计

## 问题背景

当前Agent执行复杂任务（如拼多多购物）需要几百轮工具调用、耗时十几分钟。主要原因：
- 所有操作在一个上下文中执行，历史消息膨胀导致token消耗大
- LLM需要不断"回忆"之前的操作状态
- 没有上下文隔离，一个分支失败拖慢整体

## 目标

1. 复杂任务自动分解为细粒度步骤
2. 主Agent负责分解+监督，子Agent负责执行（端云协同）
3. 任务状态本地落盘，子Agent按规划执行并动态调整
4. 任务完成后语音通知用户
5. 失败时申请人工介入
6. 按天归档日志

---

## 一、整体架构

```
┌─────────────────────────────────────────────────────┐
│  主Agent (supervisor)                                │
│  模型: 同当前配置(用户自行设置)                        │
│  系统提示词: 简化版                                   │
│  - 移除了所有手机操控细节(NeuralBridge/MCP/UI树等)     │
│  - 改为: "手机操作委托给 executor 子Agent处理"         │
│  Middleware:                                          │
│  ├─ TodoListMiddleware       → 任务分解,规划步骤       │
│  ├─ SubAgentMiddleware       → 提供 task() 工具       │
│  ├─ SummarizationMiddleware  → token压缩              │
│  └─ ModelCallLimitMiddleware → 总限制MAX_ITERATIONS   │
├─────────────────────────────────────────────────────┤
│  主Agent流程:                                         │
│  1. 接收用户请求                                       │
│  2. 分析任务,分解为细粒度步骤,写入todo列表               │
│  3. 生成 task.json -> file_write 写入临时目录          │
│  4. 调用 task(description=..., subagent_type="executor")│
│  5. 等待子Agent返回                                     │
│  6. 汇总结果 -> 语音通知用户                            │
│  7. 可选: 生成skill沉淀经验                             │
└─────────────────────────────────────────────────────┘
                        │
               task() 派发
                        ▼
┌─────────────────────────────────────────────────────┐
│  子Agent (executor)                                  │
│  模型: 同当前配置(用户可调整为便宜模型)                │
│  Middleware:                                          │
│  ├─ ToolCallIdMiddleware  → 修复tool_call_id          │
│  ├─ ModelCallLimitMiddleware → 总限制MAX_ITERATIONS   │
│  ├─ ToolRetryMiddleware   → MCP失败自动重试           │
│                                                       │
│  Tools:                                               │
│  ├─ shell_exec   → Android Shell/Termux API 优先      │
│  ├─ file_read    → 读任务文件、读skill                 │
│  ├─ file_write   → 更新任务进度、写执行日志             │
│  ├─ mcp_call     → NeuralBridge UI操控（兜底）         │
│  └─ system_info  → 查设备状态                          │
│                                                       │
│  System Prompt:                                        │
│  - 优先使用shell命令(Termux API)                       │
│  - 无法完成时降级MCP                                    │
│  - 每完成一步更新task.json中的状态                       │
│  - 失败时换方案重试，最多3次                             │
│  - 实在无法完成时语音通知用户申请人工介入                 │
└─────────────────────────────────────────────────────┘
```

---

## 二、系统提示词重构（关键收益点）

### 当前 main agent 提示词问题

`agent/prompts/agent_enhance.py` 中包含大量手机操控细节：

```
8. 【App内操控流程】打开App后要操作App内部界面...
   a. 调用 mcp_call 列出 NeuralBridge 工具
   b. 调用 android_get_ui_tree 获取UI树
   c. 分析 UI 树找到目标元素
   ...
11. 调用方式：curl -X POST http://127.0.0.1:7474/mcp ...
```

这些内容占总token的 **30-40%**，且只在操作手机时才用得到。用户不操作手机时纯属浪费。

### 重构后的提示词分配

| 内容 | 原来位置 | 重构后位置 |
|------|---------|-----------|
| 核心人设（Pocket-Agent） | system_base.py | system_base.py（不变） |
| NeuralBridge 操作规则 | agent_enhance.py | → 子Agent系统提示词 + executor-skills |
| MCP 调用格式 | agent_enhance.py | → 子Agent系统提示词 |
| 手机操控流程（UI树/点击/输入） | agent_enhance.py | → 子Agent系统提示词 |
| WebView输入框适配方案 | agent_enhance.py | → 子Agent系统提示词 |
| 技能系统说明（主Agent） | agent_enhance.py | agent_enhance.py（保留，只加载main-skills） |
| 工具使用规范 | agent_enhance.py | agent_enhance.py（保留） |
| 任务分解/多步骤执行 | agent_enhance.py | agent_enhance.py（保留） |
| ✅ 子Agent委托说明 | 无 | agent_enhance.py（新增，替代手机操控） |
| 失败处理/人工介入规则 | agent_enhance.py | → 子Agent+主Agent各保留基本版 |

### 技能目录分离

主Agent和子Agent各有独立的技能目录：

```
agent/
├── skills/                      # 主Agent技能
│   ├── brainstorming/
│   ├── code-review/
│   ├── systematic-debugging/
│   ├── test-driven-development/
│   ├── verification-before-completion/
│   └── writing-plans/
│
├── executor-skills/             # 子Agent技能（只操控手机）
│   ├── phone-control-guide/     # 原 skills/ 下移过来
│   └── neuralbridge-operation-standard/  # 原 skills/ 下移过来
│
├── auto-skills/                 # 主Agent自动沉淀的技能
│   └── ...（按需生成）
```

`load_skills_list()` 改为接受 `agent_type` 参数：
- `load_skills_list("main")` → 加载 `skills/` 目录
- `load_skills_list("executor")` → 加载 `executor-skills/` 目录

### 主Agent system prompt 变化

```
修改前: agent_enhance.py (约1500 token)
- 工具规范 (200)
- 回答规则 (100)
- 手机操控 (600) ← 这部分转移给子Agent
- MCP规则 (400) ← 这部分转移给子Agent
- 技能系统 (200) ← 也精简了（不再包含手机技能）

修改后: agent_enhance.py (约500 token)
- 工具规范 (200)
- 回答规则 (100)
- 子Agent委托说明 (150) ← 新增，简短的替代
- 技能系统 (50)  ← 只列main-skills
```

节省约 **1000 token/轮**。

### 子Agent system prompt 构成

```
子Agent系统提示词 = 固定模板（操控规则） + 主Agent的任务指导 + executor-skills列表
```

- **固定模板**：预写在代码中，包含手机操控全部细节
- **任务指导**：主Agent通过 task.json 的 guidance 字段传入特殊要求
- 拼接方式：SubAgentMiddleware 的 subagent system_prompt 中写入模板，指导由 task.json 提供

---

## 三、任务文件系统

### 文件路径

```
memory/tasks/{task_id}/task.json        ← 任务定义+状态
memory/tasks/{task_id}/result.json      ← 执行结果
```

### 任务粒度要求（子Agent可能用小模型）

**关键原则：每步必须是原子操作，小模型也能准确理解**

```
✅ 好的例子（细粒度）：
  "打开拼多多APP"
  "在搜索框输入'黑色体恤 男 短袖'"
  "点击搜索按钮"
  "点击'价格'筛选，设置范围50-80元"
  "点击第一个搜索结果"
  "向下滚动到评论区"
  "查找含'差评'、'质量'等关键词的评论"
  "长按评论内容，点击复制"
  "返回商品详情页"

❌ 不好的例子（太粗，小模型会懵）：
  "打开拼多多找件衣服"             ← 太模糊
  "筛选商品"                        ← 怎么筛选？
  "看看评论区有没有问题"            ← 看什么？标准是什么？
  "下单"                            ← 怎么下？点哪里？
```

主Agent拆解任务时，要想象自己在教一个**只会执行不会思考的实习生**。

### task.json 格式

```json
{
  "task_id": "task_20260522_001",
  "objective": "去拼多多买件黑色体恤，价格70左右",
  "created_at": "2026-05-22T10:30:00",
  "steps": [
    {"id": 1, "desc": "打开拼多多APP：用am start -p com.xunmeng.pinduoduo启动", "status": "pending"},
    {"id": 2, "desc": "等待首页加载，在搜索框输入'黑色体恤 男 短袖'并搜索", "status": "pending"},
    {"id": 3, "desc": "在搜索结果页，点击'筛选'，设置价格范围50-80元", "status": "pending"},
    {"id": 4, "desc": "从筛选结果中，点击第一个商品进入详情页", "status": "pending"},
    {"id": 5, "desc": "在详情页找到'问大家'或联系客服入口，询问尺码是否标准", "status": "pending"},
    {"id": 6, "desc": "等待客服回复后，下拉到评论区查看是否有差评", "status": "pending"},
    {"id": 7, "desc": "如无差评，点击'立即购买'，选择尺码和数量", "status": "pending"},
    {"id": 8, "desc": "进入付款页面后，调用语音通知用户", "status": "pending"}
  ],
  "guidance": "价格目标70元左右，注意看有没有优惠券可用",
  "voice_notify": true,
  "status": "running"
}
```

> **说明**：guidance 只写本次任务的特殊要求（价格、偏好、禁选项等），操作流程完全由子Agent系统提示词 + executor-skills 覆盖。

### 状态流转

```
pending → in_progress → completed
                       → failed → 换方案重试 → completed
                                            → NEED_HELP（语音通知用户）
```

---

## 四、子Agent设计

### 4.1 SubAgentMiddleware 配置

子Agent有自己的skill目录和增强提示词：

```python
# 子Agent的技能列表（从 executor-skills/ 加载）
executor_skills = load_skills_list("executor")
# 子Agent的增强提示词（包含手机操控规则）
executor_enhance = executor_enhance_prompt.format(
    tool_names=executor_tool_names,
    skills_list=executor_skills,
)

subagent_system_prompt = f"""你是一个手机操控执行助手...

{executor_enhance}
"""

```python
SubAgentMiddleware(
    backend=StateBackend(),
    subagents=[
        {
            "name": "executor",
            "description": "执行手机操控任务，按task.json规划逐步执行",
            "model": current_model,  # 与主Agent相同，用户可调整
            "system_prompt": executor_system_prompt,
            "tools": [
                shell_exec,      # Termux API / Android shell
                file_read,       # 读任务文件、读skill
                file_write,      # 更新进度、写日志
                mcp_call,        # NeuralBridge UI操控
                system_info,     # 设备状态查询
            ],
            "middleware": [
                ToolCallIdMiddleware(),
                ToolRetryMiddleware(max_attempts=2),
                ModelCallLimitMiddleware(run_limit=MAX_ITERATIONS),
            ],
        }
    ],
)
```

### 4.2 子Agent系统提示词（完整版）

```
你是一个手机操控执行助手，运行在 Android Termux 环境中。

## 核心原则
1. 聚焦手机操作——以 task.json 为路线图，但根据实际情况灵活调整
2. 优先使用 shell 命令（Termux API），无法完成时降级 MCP
3. 每完成一步，用 file_write 更新 task.json 中的 status
4. 语音仅用于申请人工介入或汇报关键节点，禁止不必要的对话

## 执行心态
- **步骤是路线图，不是铁律**。遇到实际情况和步骤描述不一致时，根据 objective 自行判断调整
- 比如步骤说"筛选价格50-80元"，但发现商品没有价格筛选功能，就换其他方式找低价商品
- 比如步骤说"点击第一个搜索结果"，但第一个明显不相关，就选更合适的
- **只要最终能达成 objective，路径可以自由变化**
- 如果发现更好的完成方式（比如更便宜的店铺、更好的商品），可以偏离原始步骤

## 执行流程
1. 用 file_read 读取 {task_path} 了解完整任务目标
2. 审视 steps 数组，理解整体意图
3. 按 steps 顺序逐个执行，但保持灵活
4. 当前步骤标记为 in_progress 后开始执行
5. 步骤完成后标记为 completed，继续下一步
6. 如果某步骤不适用或可以跳过，标记为 skipped 并说明原因

## 失败处理
- 失败后最多换3种不同方案重试
- 同一类方案（如坐标点击）的反复失败不算"不同方案"
- 全部失败后跳过该步骤（标记 failed），继续下一步
- 关键步骤失败才考虑人工介入

## 人工介入
- 只有所有可行方案都试过仍失败时才能申请
- 使用 shell_exec 执行 termux-tts-speak 语音通知用户
  例如: termux-tts-speak "我需要帮助：拼多多搜索框无法定位，已尝试UI树和坐标点击都不行"
- 通知后等待30秒，用户可能手动帮解决
- 如果用户帮忙后问题解决，继续执行剩余步骤
- 真的无法继续时，记录原因后返回给主Agent

## 返回要求
- 所有步骤执行完后，返回完整执行摘要
- 格式：
  ✅ 成功步骤: 步骤1, 2, 3, 5, 6
  ❌ 失败步骤: 步骤4（客服没回复，跳过）
  📝 最终结果: 商品已下单，预计明天到货
  🆘 人工介入: 无
```

### 4.3 任务派发流程

主Agent在调用 `task()` 前：
1. 分析用户请求，分解为细粒度steps
2. 写入 task.json
3. 调用 `task(description=f"执行任务: {objective}，任务文件路径: {task_path}", subagent_type="executor")`

子Agent返回后，主Agent：
1. 读取 result.json 或根据返回信息汇总结果
2. 调用 `termux-tts-speak` 语音通知用户
3. 可选：分析成功路径，生成skill沉淀到 skills/auto-xxx/SKILL.md

---

## 五、日志系统

### 日志文件

```
logs/YYYY-MM-DD.md
```

### 日志格式

每条日志包含：

```markdown
## [10:30:00] 任务 task_20260522_001
- 目标: 去拼多多买件黑色体恤
- 主Agent: DeepSeek-R1 (3轮，用时5s)
- 子Agent: same (42轮，用时342s)
- 结果: ✅ 成功

### 步骤详情
| 步骤 | 用时 | 结果 |
|------|------|------|
| 1. 打开拼多多 | 12s | ✅ |
| 2. 搜索黑色体恤 | 25s | ✅ 第2次尝试成功 |
| 3. 筛选价格 | 18s | ✅ |
| 4. 问客服 | 120s | ⚠️ 客服回复慢 |
| 5. 看评论区 | 45s | ✅ |
| 6. 下单 | 122s | ✅ |

### 关键事件
- 10:31:22 → 子Agent启动
- 10:31:45 → 步骤1完成
- 10:35:10 → 步骤4等待客服回复(阻塞)
- 10:37:10 → 步骤4完成，客服回复"尺码准"
- 10:42:30 → 任务完成，语音通知用户
```

### 日志工具函数

```python
# agent/logger.py
class AgentLogger:
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = log_dir
        
    def log_event(self, task_id, event_type, detail):
        """记录事件到当天日志"""
        
    def log_task_summary(self, task_id, summary: dict):
        """记录任务完成汇总"""
```

---

## 六、技能目录结构与沉淀

### 最终目录结构

```
agent/
├── config.py                     ← 新增 EXECUTOR_SKILLS_DIR 配置
├── skills/                       ★ 主Agent技能目录
│   ├── brainstorming/
│   ├── code-review/
│   ├── ...
│
├── executor-skills/              ★ 子Agent技能目录（新增）
│   ├── phone-control-guide/
│   └── neuralbridge-operation-standard/
│
├── auto-skills/main/             ★ 主Agent自动沉淀（新增）
├── auto-skills/executor/         ★ 子Agent自动沉淀（新增）
│
├── prompts/
│   ├── system_base.py
│   ├── agent_enhance.py          ← 只加载 main-skills
│   └── executor_enhance.py       ← 新增：子Agent增强提示词
```

### load_skills_list 改造

```python
# 改造前：没有参数，扫描单一目录
skills_list = load_skills_list()

# 改造后：指定 agent_type
main_skills = load_skills_list(agent_type="main")       # → skills/
executor_skills = load_skills_list(agent_type="executor") # → executor-skills/
```

### 技能沉淀

主Agent成功完成某类任务后，自动生成skill文件：

```
auto-skills/main/pdd-buy-clothes.md
```

下次主Agent遇到"拼多多买东西"请求时，可以通过file_read读取此skill，指导分解步骤。沉淀动作在主Agent汇总结果后执行（不阻塞语音通知）。

---

## 七、技术风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| 子Agent任务描述过长 | 全部写文件，描述只传路径+目标 |
| 子Agent执行中偏离规划 | 用task.json指导，步骤状态约束 |
| 子Agent无限循环 | ModelCallLimitMiddleware = MAX_ITERATIONS |
| 多个子Agent并发 | SubAgentMiddleware支持并发，任务文件独立 |
| 子Agent返回空结果 | 主Agent兜底读取result.json |
