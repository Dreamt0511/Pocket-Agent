"""
Pocket-Agent FastAPI 服务 — 运行在 Termux 中，为 Android App 提供 AI Agent HTTP API
启动方式: cd /sdcard/Pocket-Agent && source .venv/bin/activate && uvicorn app:app --host 0.0.0.0 --port 8000
"""
import os
import sys
import json
import sqlite3
import subprocess
import time
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import logging
import aiosqlite

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pocket-agent-api")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "pocket_agent.db")

app = FastAPI(title="Pocket-Agent API")


# ─── SQLite 初始化（会话 + 消息表）──────────────

async def _init_db():
    """创建会话和消息表（如果不存在）"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '新会话',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        await db.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)")

        # FTS5 虚拟表 —— 会话历史全文搜索
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, content=messages, content_rowid=id)
        """)
        # INSERT 同步触发器
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)
        # DELETE 同步触发器
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
            END
        """)

        await db.commit()


@app.on_event("startup")
async def startup():
    global _checkpoint_conn, _checkpoint_saver
    await _init_db()
    # 初始化持久化 checkpointer（AsyncSqliteSaver）
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    _checkpoint_conn = await aiosqlite.connect(DB_PATH)
    _checkpoint_saver = AsyncSqliteSaver(_checkpoint_conn)
    await _checkpoint_saver.setup()
    logger.info("AsyncSqliteSaver checkpoint 已初始化")

# ─── Agent 单例缓存 ──────────────────────────────
# 共享同一个 agent 实例，通过不同 thread_id 隔离各会话历史
# 仅当 LLM 配置变化时才重建 agent
_agent_instance = None
_agent_llm_config_key = None
_checkpoint_conn = None  # AsyncSqliteSaver 的底层连接
_checkpoint_saver = None  # 持久化 checkpointer


def _get_or_create_agent(llm_config: dict):
    """获取或创建 Agent 单例，配置变化时自动重建"""
    global _agent_instance, _agent_llm_config_key
    config_key = json.dumps(llm_config, sort_keys=True)
    if _agent_instance is not None and _agent_llm_config_key == config_key:
        return _agent_instance
    if _agent_instance is not None:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(_agent_instance.cleanup())
            else:
                loop.run_until_complete(_agent_instance.cleanup())
        except Exception:
            pass
    from agent.agent_langchain import LangChainPocketAgent
    _agent_instance = LangChainPocketAgent(llm_config=llm_config, checkpointer=_checkpoint_saver)
    _agent_llm_config_key = config_key
    return _agent_instance


# ─── 调试：记录最后一次 /chat 请求参数 ──────────
_chat_debug: dict = {}

# ─── .env 配置加载 ─────────────────────────────

def _load_env_config() -> dict:
    """从 .env 文件加载 LLM 配置，转成 agent 所需的 key 格式"""
    env_file = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_file):
        # 首次运行从 .env.example 复制
        example = os.path.join(PROJECT_ROOT, ".env.example")
        if os.path.exists(example):
            import shutil
            shutil.copy2(example, env_file)
        else:
            return {}

    config = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"')
            config[k] = v

    # 映射到 agent 使用的 key 格式
    mapping = {
        "DEFAULT_LLM_BASE_URL": "base_url",
        "LLM_BASE_URL": "base_url",
        "LLM_API_KEY": "api_key",
        "LLM_MODEL": "model",
        "LLM_TEMPERATURE": "temperature",
        "LLM_MAX_TOKENS": "max_tokens",
    }
    result = {}
    for env_key, agent_key in mapping.items():
        if env_key in config:
            result[agent_key] = config[env_key]
    return result


# ─── 健康检查 ─────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "python": sys.version,
        "project_root": PROJECT_ROOT,
    }


# ─── 安装依赖 ─────────────────────────────────

@app.post("/setup")
async def setup():
    req_file = os.path.join(PROJECT_ROOT, "requirements.txt")
    if not os.path.exists(req_file):
        return {"status": "error", "message": f"requirements.txt not found at {req_file}"}
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file],
        capture_output=True, text=True, cwd=PROJECT_ROOT
    )
    return {
        "status": "ok" if result.returncode == 0 else "error",
        "output": result.stdout[-2000:],
        "error": result.stderr[-2000:],
    }


# ─── 聊天执行（SSE 流式） ──────────────────────

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    message = data.get("message", "")
    req_config = data.get("config", {})
    conversation_id = data.get("conversation_id", "default-session")

    # 设置当前会话ID，供 read_conversation_history 工具使用
    from agent.tools.basic_tools import set_current_conversation_id
    set_current_conversation_id(conversation_id)

    # 合并配置：.env 为基础，请求参数覆盖（优先级最高）
    llm_config = {**_load_env_config(), **req_config}

    # 调试记录最近一次请求
    _chat_debug.clear()
    _chat_debug.update({"message": message, "config": req_config})

    # 确保会话存在
    now = int(time.time() * 1000)
    async with aiosqlite.connect(DB_PATH) as db:
        existing = await db.execute_fetchall(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        )
        if not existing:
            title = message[:30] if message else "新会话"
            await db.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, title, now, now)
            )
        else:
            await db.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id)
            )
        # 保存用户消息
        await db.execute(
            "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (conversation_id, "user", message, now)
        )
        await db.commit()

    async def generate():
        global _cancel_requested
        _cancel_requested = False  # 新请求开始，重置取消标志
        yield ":ok\n\n"  # SSE comment，强制触发响应头发送
        yield "retry: 1000\n\n"  # SSE reconnect interval，同时触发响应头立即发送
        full_response = ""
        try:
            agent = _get_or_create_agent(llm_config)

            # 从 SQLite 加载历史消息，恢复会话上下文（MemorySaver 重启后丢失）
            history = []
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    rows = await db.execute_fetchall(
                        "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
                        (conversation_id,)
                    )
                    # 排除最后一条（当前用户消息，已保存）
                    for row in rows[:-1]:
                        history.append({"role": row[0], "content": row[1]})
            except Exception:
                pass

            async for event in agent.stream_conversation(message, thread_id=conversation_id, history=history):
                if _cancel_requested:
                    yield f"data: [已中断]\n\n"
                    yield f"data: [DONE]\n\n"
                    break
                if event["type"] == "token":
                    full_response += event["content"]
                    yield f"data: {json.dumps(event['content'], ensure_ascii=False)}\n\n"
                elif event["type"] in ("tool_start", "tool_end", "thinking"):
                    yield f"data: [TOOL] {json.dumps(event, ensure_ascii=False)}\n\n"
                elif event["type"] == "done":
                    full_response = event.get("response", full_response)
                    yield f"data: [DONE]\n\n"
                elif event["type"] == "error":
                    full_response = event.get("message", "")
                    yield f"data: [ERROR] {event['message']}\n\n"
                    yield f"data: [DONE]\n\n"

        except Exception as e:
            logger.exception("Chat execution failed")
            full_response = str(e)
            yield f"data: [ERROR] {str(e)}\n\n"
            yield f"data: [DONE]\n\n"

        # 保存 AI 回复
        if full_response:
            try:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                        (conversation_id, "assistant", full_response, int(time.time() * 1000))
                    )
                    await db.commit()
            except Exception:
                logger.exception("Failed to save assistant message")

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )


# ─── 调试：查看最近一次 /chat 请求参数 ──────────

@app.get("/debug_chat")
async def debug_chat():
    return _chat_debug


# ─── 代码同步 ─────────────────────────────────

@app.post("/sync")
async def sync(request: Request):
    # 拉取前记录 requirements.txt 的内容
    req_file = os.path.join(PROJECT_ROOT, "requirements.txt")
    old_req = ""
    if os.path.isfile(req_file):
        with open(req_file) as f:
            old_req = f.read()

    result = subprocess.run(
        ["git", "pull", "origin", "main"],
        capture_output=True, text=True, cwd=PROJECT_ROOT
    )
    resp = {
        "status": "ok" if result.returncode == 0 else "error",
        "output": result.stdout,
        "error": result.stderr,
    }

    # 拉取成功后检查 requirements.txt 是否有变化
    if result.returncode == 0 and os.path.isfile(req_file):
        with open(req_file) as f:
            new_req = f.read()
        if new_req != old_req:
            # 有新依赖，执行 pip install
            body = await request.json() if request.headers.get("content-type", "").startswith("application/json") else {}
            mirror = body.get("mirror", "")
            env = os.environ.copy()
            if mirror:
                env["PIP_INDEX_URL"] = mirror
            pip_result = subprocess.run(
                ["pip", "install", "-q", "-r", "requirements.txt"],
                capture_output=True, text=True, cwd=PROJECT_ROOT, env=env,
                timeout=300
            )
            resp["pip_updated"] = True
            resp["pip_output"] = pip_result.stdout[-500:] if pip_result.stdout else ""
            resp["pip_error"] = pip_result.stderr[-500:] if pip_result.stderr else ""

    return resp


# ─── 配置读写 ─────────────────────────────────

@app.get("/config")
async def get_config():
    config = {}
    env_file = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip().strip('"')
    return config


@app.post("/config")
async def set_config(request: Request):
    data = await request.json()
    env_file = os.path.join(PROJECT_ROOT, ".env")
    existing = {}
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip().strip('"')
    existing.update(data)
    with open(env_file, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    return {"status": "ok"}


# ─── 清除对话历史 ───────────────────────────────

@app.post("/clear_history")
async def clear_history(request: Request):
    """清除指定会话的对话历史（重置 MemorySaver 中的 thread）"""
    data = await request.json()
    conversation_id = data.get("conversation_id", "default-session")
    if _agent_instance is not None:
        _agent_instance.clear_history(thread_id=conversation_id)
        return {"status": "ok", "message": f"会话 {conversation_id} 的对话历史已清除"}
    return {"status": "ok", "message": "Agent 未初始化，无需清除"}


# ─── 会话管理 API ───────────────────────────────

@app.get("/conversations")
async def list_conversations():
    """返回所有会话列表"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = await db.execute_fetchall(
            "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
        )
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]


@app.get("/conversations/{conversation_id}/messages")
async def get_messages(conversation_id: str):
    """返回指定会话的消息列表"""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = await db.execute_fetchall(
            "SELECT role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
            (conversation_id,)
        )
        return [
            {
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]


@app.get("/conversations/{conversation_id}/search")
async def search_messages(conversation_id: str, q: str):
    """FTS5 全文搜索指定会话的消息"""
    if not q.strip():
        return []
    # 转义 FTS5 特殊字符，用双引号包裹整个 query
    safe_q = f'"{q}"'
    async with aiosqlite.connect(DB_PATH) as db:
        rows = await db.execute_fetchall(
            """SELECT m.role, m.content, m.timestamp
               FROM messages_fts fts
               JOIN messages m ON fts.rowid = m.id
               WHERE messages_fts MATCH ? AND m.conversation_id = ?
               ORDER BY rank LIMIT 20""",
            (safe_q, conversation_id)
        )
        return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """删除指定会话及其所有消息"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        await db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        await db.commit()
    # 同时清除 LangGraph checkpoint 中的历史
    if _agent_instance is not None:
        _agent_instance.clear_history(thread_id=conversation_id)
    return {"status": "ok"}


# ─── 技能列表 ─────────────────────────────────

@app.get("/skills")
async def list_skills():
    """返回所有技能列表"""
    skills_dir = os.path.join(PROJECT_ROOT, "agent", "skills")
    result = {"main_skills": [], "executor_skills": [], "auto_skills": []}

    category_map = {
        "main-skills": "main_skills",
        "executor-skills": "executor_skills",
        "auto-skills": "auto_skills",
    }

    for cat_dir, key in category_map.items():
        cat_path = os.path.join(skills_dir, cat_dir)
        if not os.path.exists(cat_path):
            continue
        for root, dirs, files in os.walk(cat_path):
            for f in files:
                if f.upper() == "SKILL.MD":
                    rel_path = os.path.relpath(root, skills_dir)
                    name = os.path.basename(root)
                    description = ""
                    content = ""
                    try:
                        with open(os.path.join(root, f), encoding="utf-8") as fp:
                            content = fp.read()
                            if content.startswith("---"):
                                end = content.find("---", 3)
                                if end > 0:
                                    fm = content[3:end]
                                    for line in fm.split("\n"):
                                        line = line.strip()
                                        if line.startswith("name:"):
                                            name = line[5:].strip().strip('"')
                                        elif line.startswith("description:"):
                                            description = line[12:].strip().strip('"')
                    except Exception:
                        pass
                    result[key].append({
                        "name": name,
                        "description": description,
                        "path": rel_path.replace("\\", "/"),
                        "content": content
                    })
    return result


def _validate_skill_path(rel_path: str) -> str | None:
    """校验技能相对路径，防止路径穿越。返回规范化路径或 None（非法）"""
    import os
    skills_dir = os.path.join(PROJECT_ROOT, "agent", "skills")
    target = os.path.normpath(os.path.join(skills_dir, rel_path))
    if not target.startswith(os.path.normpath(skills_dir) + os.sep) and target != os.path.normpath(skills_dir):
        return None
    # 禁止 .. 组件
    if ".." in rel_path.split("/"):
        return None
    return target


@app.post("/skills")
async def create_skill(request: Request):
    """创建新技能"""
    import os
    body = await request.json()
    name = body.get("name", "").strip()
    description = body.get("description", "").strip()
    content = body.get("content", "").strip()
    category = body.get("category", "auto-skills").strip()

    if not name or not content:
        return JSONResponse({"error": "name 和 content 不能为空"}, status_code=400)

    skills_dir = os.path.join(PROJECT_ROOT, "agent", "skills")
    cat_dir = os.path.join(skills_dir, category)
    if not os.path.exists(cat_dir):
        return JSONResponse({"error": f"分类 {category} 不存在"}, status_code=400)

    # 用户技能放在分类下的 user/ 子目录
    skill_dir = os.path.join(cat_dir, "user", name)
    if os.path.exists(skill_dir):
        return JSONResponse({"error": f"技能 {name} 已存在"}, status_code=409)

    os.makedirs(skill_dir, exist_ok=True)
    frontmatter = f"---\nname: {name}\ndescription: {description}\n---\n\n{content}\n"
    with open(os.path.join(skill_dir, "SKILL.md"), "w", encoding="utf-8") as f:
        f.write(frontmatter)

    rel_path = os.path.relpath(skill_dir, skills_dir).replace("\\", "/")
    return {"path": rel_path, "name": name}


@app.put("/skills/{path:path}")
async def update_skill(path: str, request: Request):
    """更新技能内容"""
    import os
    target = _validate_skill_path(path)
    if target is None:
        return JSONResponse({"error": "非法路径"}, status_code=400)

    skill_file = None
    for fname in ("SKILL.md", "skill.md", "Skill.md"):
        fp = os.path.join(target, fname)
        if os.path.isfile(fp):
            skill_file = fp
            break
    if skill_file is None:
        return JSONResponse({"error": "技能不存在"}, status_code=404)

    body = await request.json()
    name = body.get("name", "").strip()
    description = body.get("description", "").strip()
    content = body.get("content", "").strip()

    if not name or not content:
        return JSONResponse({"error": "name 和 content 不能为空"}, status_code=400)

    frontmatter = f"---\nname: {name}\ndescription: {description}\n---\n\n{content}\n"
    with open(skill_file, "w", encoding="utf-8") as f:
        f.write(frontmatter)

    return {"ok": True}


@app.delete("/skills/{path:path}")
async def delete_skill(path: str):
    """删除技能"""
    import os, shutil
    target = _validate_skill_path(path)
    if target is None:
        return JSONResponse({"error": "非法路径"}, status_code=400)

    if not os.path.isdir(target):
        return JSONResponse({"error": "技能不存在"}, status_code=404)

    # 不允许删除系统预装技能（main-skills/xxx 或 executor-skills/xxx 直接子目录）
    # 允许删除: user/ 下的、auto-skills/ 下的、executor/ 下的
    parts = path.split("/")
    is_system = (parts[0] in ("main-skills", "executor-skills") and "user" not in parts and "executor" not in parts)
    if is_system:
        return JSONResponse({"error": "不能删除系统预装技能"}, status_code=403)

    shutil.rmtree(target)
    return {"ok": True}


# ─── 打断当前执行 ─────────────────────────────

_cancel_requested = False

@app.post("/cancel")
async def cancel_execution():
    """取消当前正在执行的推理"""
    global _cancel_requested
    _cancel_requested = True
    # 尝试中断 agent 的 LLM 调用
    if _agent_instance is not None:
        try:
            if hasattr(_agent_instance, 'cancel'):
                _agent_instance.cancel()
        except Exception:
            pass
    return {"ok": True}


# ─── 服务关闭 ─────────────────────────────────

@app.post("/shutdown")
async def shutdown():
    """关闭 FastAPI 服务自身"""
    import os, signal, asyncio
    # 清理 agent 实例，关闭 HTTP 客户端
    if _agent_instance is not None:
        try:
            await _agent_instance.cleanup()
        except Exception:
            pass
    async def _die():
        await asyncio.sleep(0.3)
        os.kill(os.getpid(), signal.SIGTERM)
    asyncio.create_task(_die())
    return {"status": "shutting_down"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
