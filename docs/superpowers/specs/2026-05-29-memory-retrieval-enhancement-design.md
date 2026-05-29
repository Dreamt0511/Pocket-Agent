# 记忆检索增强设计文档

## 背景问题

当前记忆检索系统存在以下问题：

1. **FTS5 搜索逻辑问题**：使用 AND 逻辑，模型搜索时添加额外关键词导致匹配失败
   - 用户原句："未来有什么安排吗"
   - 模型搜索 query："暑假 实习 安排 担心"
   - FTS5 需要同时包含四个词，导致找不到原句

2. **缺少过滤条件**：无法按时间范围、消息类型过滤

3. **存储逻辑不一致**：fact 类型只存向量数据库，episodic 同时存 messages 表和向量数据库

4. **缺少综合排序**：只按相关性排序，没有考虑时间衰减和重要性

## 设计方案

### 1. FTS5 搜索改为 OR 逻辑

**修改位置**：`agent/tools/basic_tools.py` 的 `_fts_search` 函数

**修改内容**：
```python
# 修改前
WHERE messages_fts MATCH ?

# 修改后
WHERE messages_fts MATCH ?  -- query 中的关键词用 OR 连接
```

**实现方式**：
- 将用户传入的 query 按空格分词
- 用 OR 连接各关键词
- 例如："暑假 实习 安排 担心" → "暑假 OR 实习 OR 安排 OR 担心"

### 2. search_memory 添加新参数

**修改位置**：`agent/tools/basic_tools.py` 的 `search_memory` 函数

**新参数**：
```python
def search_memory(
    query: str, 
    scope: str = "all",
    days: int = None,        # 过去 N 天
    msg_type: str = None     # "user" / "assistant" / "memory"
) -> str:
```

**参数说明**：
- `days`：时间过滤，只返回过去 N 天内的消息
  - 计算方式：`timestamp > int((time.time() - days * 86400) * 1000)`
- `msg_type`：消息类型过滤
  - "user"：只搜用户消息
  - "assistant"：只搜 AI 回复
  - "memory"：只搜记忆

**SQL 查询修改**：
```python
# 基础查询
SELECT m.id, m.conversation_id, m.role, m.content, m.importance, m.timestamp
FROM messages_fts fts 
JOIN messages m ON fts.rowid = m.id
WHERE messages_fts MATCH ?

# 添加过滤条件
if days:
    query += " AND m.timestamp > ?"
    params.append(int((time.time() - days * 86400) * 1000))

if msg_type:
    query += " AND m.role = ?"
    params.append(msg_type)
```

### 3. 修改 save_memory 存储逻辑

**修改位置**：`agent/tools/basic_tools.py` 的 `save_memory` 函数

**修改内容**：
- `fact` 类型：同时存 messages 表和向量数据库
- `episodic` 类型：同时存 messages 表和向量数据库（已有）

**修改后的逻辑**：
```python
if type == "fact":
    # 存入 messages 表
    if _db_path_ref:
        conn = sqlite3.connect(_db_path_ref, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, timestamp, importance) VALUES (?, ?, ?, ?, ?)",
            (_current_conversation_id, "memory", content, int(time.time() * 1000), importance)
        )
        conn.commit()
        conn.close()
    # 存入向量数据库
    if _vector_store_ref:
        _vector_store_ref.add(...)
```

### 4. 添加 last_access_at 字段

**修改位置**：`app.py` 的数据库初始化

**修改内容**：
```python
# messages 表添加 last_access_at 字段
await db.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        importance INTEGER DEFAULT 1,
        last_access_at INTEGER DEFAULT 0,
        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
    )
""")

# 兼容旧数据库
try:
    await db.execute("ALTER TABLE messages ADD COLUMN last_access_at INTEGER DEFAULT 0")
except Exception:
    pass
```

### 5. 综合排序算法

**借鉴 EchoMind 设计**，使用 RRF + 时间衰减 + 重要性的综合排序：

```python
def _rrf_merge_with_scores(
    fts_results: list, 
    vec_results: list, 
    k: int = 60,
    alpha: float = 0.45,  # 语义相关性权重
    beta: float = 0.25,   # 时间衰减权重
    gamma: float = 0.3    # 重要性权重
) -> list:
    """综合排序：RRF + 时间衰减 + 重要性"""
    current_time = time.time() * 1000  # 毫秒
    DECAY_RATE = 0.995  # 每小时衰减
    
    scores = {}
    
    # FTS5 结果按 rank 排序
    for rank, msg in enumerate(fts_results):
        key = (msg.get("conversation_id", ""), msg.get("content", "")[:50])
        rrf_score = 1 / (k + rank + 1)
        scores[key] = {"rrf": rrf_score, "msg": msg}
    
    # 向量结果按 similarity 排序
    for rank, msg in enumerate(vec_results):
        key = (msg.get("conversation_id", ""), msg.get("content", "")[:50])
        rrf_score = 1 / (k + rank + 1)
        if key in scores:
            scores[key]["rrf"] += rrf_score
        else:
            scores[key] = {"rrf": rrf_score, "msg": msg}
    
    # 计算综合分数
    for key, data in scores.items():
        msg = data["msg"]
        
        # 语义相关性（RRF 分数）
        semantic_score = data["rrf"]
        
        # 时间衰减
        last_access = msg.get("last_access_at", current_time)
        hours_passed = (current_time - last_access) / 3600000  # 转换为小时
        recency_score = DECAY_RATE ** hours_passed
        
        # 重要性
        importance_score = msg.get("importance", 1) / 10  # 归一化到 0-1
        
        # 综合分数
        data["final_score"] = (
            alpha * semantic_score + 
            beta * recency_score + 
            gamma * importance_score
        )
    
    # 按综合分数排序
    sorted_items = sorted(scores.values(), key=lambda x: x["final_score"], reverse=True)
    
    # 返回最相关的 5 条
    return [item["msg"] for item in sorted_items[:5]]
```

### 6. 检索后更新 last_access_at

**修改位置**：`agent/tools/basic_tools.py` 的 `search_memory` 函数

**修改内容**：
```python
# 检索完成后更新 last_access_at
if results:
    current_timestamp = int(time.time() * 1000)
    conn = sqlite3.connect(_db_path_ref, timeout=30)
    for msg in results:
        conn.execute(
            "UPDATE messages SET last_access_at = ? WHERE id = ?",
            (current_timestamp, msg.get("id"))
        )
    conn.commit()
    conn.close()
```

## 文件修改清单

1. **`agent/tools/basic_tools.py`**：
   - 修改 `_fts_search` 函数：AND 改为 OR
   - 修改 `search_memory` 函数：添加 days、msg_type 参数
   - 修改 `save_memory` 函数：fact 类型也存 messages 表
   - 修改 `_rrf_merge` 函数：添加综合排序

2. **`app.py`**：
   - 修改 messages 表结构：添加 `last_access_at` 字段

3. **`agent/prompts/agent_enhance.py`**：
   - 更新 search_memory 工具说明，提示新参数

## 测试用例

1. **FTS5 OR 搜索测试**：
   - 用户原句："未来有什么安排吗"
   - 搜索 query："暑假 实习 安排 担心"
   - 预期：能找到包含"安排"的原句

2. **时间过滤测试**：
   - `search_memory(query="安排", days=1)`
   - 预期：只返回过去 1 天的消息

3. **消息类型过滤测试**：
   - `search_memory(query="安排", msg_type="user")`
   - 预期：只返回用户消息

4. **综合排序测试**：
   - 验证返回结果按相关性 + 时间衰减 + 重要性排序

## 参考设计

- EchoMind 记忆管理器：`/storage/emulated/0/本地项目开发/EchoMind/backend/memory_manager.py`
- 混合检索：稠密向量 + BM25，RRF 排序
- 综合排序：`alpha * semantic_score + beta * recency_score + gamma * importance_score`
- 时间衰减：`DECAY_RATE ** hours_passed`
