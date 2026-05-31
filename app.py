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
import contextlib
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
import logging
import aiosqlite

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pocket-agent-api")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "pocket_agent.db")

@contextlib.asynccontextmanager
async def get_db():
    """获取带 WAL + busy_timeout 的数据库连接"""
    db = await aiosqlite.connect(DB_PATH)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=30000")
    try:
        yield db
    finally:
        await db.close()

app = FastAPI(title="Pocket-Agent API")

# ─── 服务启动时间 ──────────────────────────────
_start_time = time.time()

# ─── 心跳机制 ──────────────────────────────────
_last_heartbeat = time.time()
_HEARTBEAT_TIMEOUT = 60  # 秒，超过此时间未收到心跳则自动关闭


async def _add_to_vector_store(message_id: int, content: str, conversation_id: str, importance: int):
    """异步添加消息到向量索引"""
    try:
        if _vector_store:
            _vector_store.add(message_id, content, {
                "conversation_id": conversation_id,
                "importance": importance
            })
    except Exception:
        logger.warning(f"向量索引添加失败: message_id={message_id}")


# ─── SQLite 初始化（会话 + 消息表）──────────────

async def _init_db():
    """创建会话和消息表（如果不存在）"""
    async with get_db() as db:
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

        # 兼容旧数据库：添加 importance 字段
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN importance INTEGER DEFAULT 1")
        except Exception:
            pass  # duplicate column — 已存在

        # 兼容旧数据库：添加 last_access_at 字段
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN last_access_at INTEGER DEFAULT 0")
        except Exception:
            pass  # duplicate column — 已存在

        # 兼容旧数据库：添加 memory_type 字段（区分 fact/episodic 记忆）
        try:
            await db.execute("ALTER TABLE messages ADD COLUMN memory_type TEXT DEFAULT NULL")
        except Exception:
            pass  # duplicate column — 已存在

        # FTS5 虚拟表 —— 会话历史全文搜索（使用 trigram tokenizer 支持中文搜索）
        # 检查是否需要重建为 trigram tokenizer
        existing_fts = await db.execute_fetchall(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        )
        if existing_fts and "trigram" not in (existing_fts[0][0] or ""):
            # 旧表需要重建
            await db.execute("DROP TABLE IF EXISTS messages_fts")
            await db.execute("DROP TRIGGER IF EXISTS messages_fts_ai")
            await db.execute("DROP TRIGGER IF EXISTS messages_fts_ad")
            await db.execute("DROP TRIGGER IF EXISTS messages_fts_au")
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, content=messages, content_rowid=id, tokenize='trigram')
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
        # UPDATE 同步触发器
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)
        # 重建 FTS 索引（确保数据一致）
        await db.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")

        await db.commit()


async def _cleanup_old_messages():
    """清理低重要性旧记忆的向量索引（保留策略：30天+importance<=2 的记忆释放embedding）"""
    thirty_days_ago = int((time.time() - 30 * 24 * 3600) * 1000)
    try:
        async with get_db() as db:
            # 查询需要清理的记忆 ID（只清理 memory 类型的消息）
            old_message_ids = await db.execute_fetchall(
                """SELECT id FROM messages
                   WHERE role = 'memory' AND importance <= 2 AND timestamp < ?""",
                (thirty_days_ago,)
            )
            # 同时清理向量索引
            if _vector_store:
                for row in old_message_ids:
                    _vector_store.delete(row[0])
            logger.info(f"已清理 {len(old_message_ids)} 条低重要性旧记忆的向量索引")
    except Exception:
        logger.warning("清理旧记忆向量索引失败", exc_info=True)


@app.on_event("startup")
async def startup():
    global _checkpoint_conn, _checkpoint_saver, _vector_store
    # 同步强制设置 WAL 模式（确保在任何异步连接之前生效）
    _sync_conn = sqlite3.connect(DB_PATH, timeout=30)
    _sync_conn.execute("PRAGMA journal_mode=WAL")
    _sync_conn.execute("PRAGMA busy_timeout=30000")
    _sync_conn.close()
    logger.info("数据库 WAL 模式已强制设置")
    await _init_db()
    # 初始化持久化 checkpointer（AsyncSqliteSaver，失败则降级为 MemorySaver）
    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        _checkpoint_conn = await aiosqlite.connect(DB_PATH)
        await _checkpoint_conn.execute("PRAGMA journal_mode=WAL")
        await _checkpoint_conn.execute("PRAGMA busy_timeout=30000")
        _checkpoint_saver = AsyncSqliteSaver(_checkpoint_conn)
        await _checkpoint_saver.setup()
        logger.info("AsyncSqliteSaver checkpoint 已初始化")
    except Exception as e:
        logger.warning(f"AsyncSqliteSaver 初始化失败，降级为 MemorySaver: {e}")
        from langgraph.checkpoint.memory import MemorySaver
        _checkpoint_saver = MemorySaver()
        logger.info("MemorySaver checkpoint 已初始化（会话历史不持久化）")

    # 初始化 SQLite 向量存储（BGE-M3 本地 embedding）
    from agent.embedding import EmbeddingClient, VectorStore
    from agent.config import EMBEDDING_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL, EMBEDDING_SERVER_URL
    env_config = _load_env_config()
    _embedding_client = EmbeddingClient(
        EMBEDDING_SERVER_URL or EMBEDDING_BASE_URL or env_config.get("base_url", ""),
        EMBEDDING_API_KEY or env_config.get("api_key", ""),
        EMBEDDING_MODEL
    )
    _vector_store = VectorStore(
        db_path=DB_PATH,
        embedding_client=_embedding_client
    )
    # embeddings FTS5 索引（与 VectorStore 共用同一个 SQLite 文件）
    async with get_db() as db:
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS embeddings_fts
            USING fts5(content, tokenize='trigram')
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS embeddings_fts_ai AFTER INSERT ON embeddings BEGIN
                INSERT INTO embeddings_fts(rowid, content) VALUES (new.rowid, new.content);
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS embeddings_fts_ad AFTER DELETE ON embeddings BEGIN
                INSERT INTO embeddings_fts(embeddings_fts, rowid, content) VALUES('delete', old.rowid, old.content);
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS embeddings_fts_au AFTER UPDATE ON embeddings BEGIN
                INSERT INTO embeddings_fts(embeddings_fts, rowid, content) VALUES('delete', old.rowid, old.content);
                INSERT INTO embeddings_fts(rowid, content) VALUES (new.rowid, new.content);
            END
        """)
        await db.execute("INSERT INTO embeddings_fts(embeddings_fts) VALUES('rebuild')")
        await db.commit()
    logger.info("embeddings FTS5 索引已初始化")

    # 注入引用到工具模块，避免 HTTP 自调用死锁
    from agent.tools.basic_tools import set_memory_refs
    set_memory_refs(_vector_store, DB_PATH)
    logger.info("SQLite 向量存储已初始化")

    # 清理低重要性旧消息的 embedding（遗忘机制）
    await _cleanup_old_messages()

    # 启动心跳看门狗：App 被杀后超时自动关闭 uvicorn
    import signal, threading
    def _heartbeat_watchdog():
        while True:
            time.sleep(30)
            if time.time() - _last_heartbeat > _HEARTBEAT_TIMEOUT:
                logger.info(f"心跳超时 {_HEARTBEAT_TIMEOUT}s，自动关闭服务")
                # 停止 llama-server embedding 服务
                try:
                    subprocess.run(["sh", "-c", "pkill -f 'llama-server.*8080' 2>/dev/null || kill $(pgrep -f 'llama-server.*8080') 2>/dev/null"], timeout=3)
                except Exception:
                    pass
                os.kill(os.getpid(), signal.SIGTERM)
                break
    threading.Thread(target=_heartbeat_watchdog, daemon=True).start()
    logger.info(f"心跳看门狗已启动（超时 {_HEARTBEAT_TIMEOUT}s）")

# ─── Agent 单例缓存 ──────────────────────────────
# 共享同一个 agent 实例，通过不同 thread_id 隔离各会话历史
# 仅当 LLM 配置变化时才重建 agent
_agent_instance = None
_agent_llm_config_key = None
_checkpoint_conn = None  # AsyncSqliteSaver 的底层连接
_checkpoint_saver = None  # 持久化 checkpointer
_vector_store = None  # SQLite 向量存储


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


@app.get("/uptime")
async def uptime():
    """返回服务运行时长（秒）"""
    elapsed = int(time.time() - _start_time)
    return {
        "uptime_seconds": elapsed,
        "started_at": _start_time,
    }


@app.post("/heartbeat")
async def heartbeat():
    global _last_heartbeat
    _last_heartbeat = time.time()
    return {"status": "ok"}


@app.get("/version")
async def version():
    """返回当前代码版本（git commit SHA 前 7 位）"""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        sha = result.stdout.strip()[:7] if result.returncode == 0 else "unknown"
    except Exception:
        sha = "unknown"
    return {"version": sha}


VERSION_HISTORY_FILE = os.path.expanduser("~/.pocket-agent-versions")
MAX_VERSION_HISTORY = 5


def _get_current_commit_info():
    """获取当前 commit 的 sha、message、timestamp"""
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h|%s|%at"],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        if result.returncode == 0:
            parts = result.stdout.strip().split("|", 2)
            if len(parts) == 3:
                return {"sha": parts[0], "message": parts[1], "timestamp": int(parts[2]) * 1000}
    except Exception:
        pass
    return None


def _record_installed_version():
    """将当前版本记录到安装历史文件（最多保留 MAX_VERSION_HISTORY 条）"""
    info = _get_current_commit_info()
    if not info:
        return
    try:
        history = []
        if os.path.isfile(VERSION_HISTORY_FILE):
            with open(VERSION_HISTORY_FILE) as f:
                history = json.load(f)
        # 去重：如果当前 SHA 已在列表中，先移除
        history = [h for h in history if h["sha"] != info["sha"]]
        history.insert(0, info)
        history = history[:MAX_VERSION_HISTORY]
        with open(VERSION_HISTORY_FILE, "w") as f:
            json.dump(history, f, ensure_ascii=False)
    except Exception:
        pass


@app.get("/version/history")
async def version_history():
    """返回用户安装过的版本历史（最多 5 个）"""
    try:
        if os.path.isfile(VERSION_HISTORY_FILE):
            with open(VERSION_HISTORY_FILE) as f:
                history = json.load(f)
            return {"history": history}
        # 文件不存在时，返回当前版本作为唯一记录
        info = _get_current_commit_info()
        return {"history": [info] if info else []}
    except Exception as e:
        return {"history": [], "error": str(e)}


@app.post("/version/rollback")
async def version_rollback(request: Request):
    """回退到指定 commit"""
    body = await request.json()
    sha = body.get("sha", "").strip()
    if not sha:
        return {"status": "error", "message": "缺少 sha 参数"}
    try:
        result = subprocess.run(
            ["git", "checkout", sha],
            capture_output=True, text=True, cwd=PROJECT_ROOT
        )
        if result.returncode != 0:
            return {"status": "error", "message": result.stderr.strip()}
        _record_installed_version()
        return {"status": "ok", "version": sha}
    except Exception as e:
        return {"status": "error", "message": str(e)}


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

    # 设置当前会话ID，供 search_memory 工具使用
    from agent.tools.basic_tools import set_current_conversation_id
    set_current_conversation_id(conversation_id)

    # 合并配置：.env 为基础，请求参数覆盖（优先级最高）
    llm_config = {**_load_env_config(), **req_config}

    # 调试记录最近一次请求
    _chat_debug.clear()
    _chat_debug.update({"message": message, "config": req_config})

    # 确保会话存在
    now = int(time.time() * 1000)
    async with get_db() as db:
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
        # 保存用户消息（原始对话不设 importance）
        cursor = await db.execute(
            "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (conversation_id, "user", message, now)
        )
        await db.commit()
        user_message_id = cursor.lastrowid

    # 已禁用自动嵌入：改为 Agent 主动调用 save_memory 工具
    # import asyncio
    # asyncio.create_task(_add_to_vector_store(user_message_id, message, conversation_id))

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
                async with get_db() as db:
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
                elif event["type"] == "progress":
                    # 工具执行进度推送
                    yield f"data: [TOOL] {json.dumps(event, ensure_ascii=False)}\n\n"
                elif event["type"] == "tool_start":
                    tool_name = event.get("name", "工具")
                    tool_args = event.get("args", {})
                    args_str = json.dumps(tool_args, ensure_ascii=False) if isinstance(tool_args, dict) else str(tool_args)
                    full_response += f"\n\n[__TOOL_CALL__]{tool_name}: {args_str}[__TOOL_CALL_END__]\n"
                    yield f"data: [TOOL] {json.dumps(event, ensure_ascii=False)}\n\n"
                elif event["type"] in ("tool_end", "thinking", "executor_start", "executor_done", "skill_condense", "skill_verify"):
                    yield f"data: [TOOL] {json.dumps(event, ensure_ascii=False)}\n\n"
                elif event["type"] == "done":
                    # 保留已累积的内容（含工具调用标记），仅在为空时用 agent 的 response
                    if not full_response:
                        full_response = event.get("response", "")
                    elapsed = event.get("elapsed", 0)
                    if elapsed > 0:
                        yield f"data: [TOOL] {json.dumps({'type': 'done_stats', 'elapsed': elapsed}, ensure_ascii=False)}\n\n"
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
                async with get_db() as db:
                    cursor = await db.execute(
                        "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                        (conversation_id, "assistant", full_response, int(time.time() * 1000))
                    )
                    await db.commit()
                    ai_message_id = cursor.lastrowid
                # 已禁用自动嵌入：改为 Agent 主动调用 save_memory 工具
                # asyncio.create_task(_add_to_vector_store(ai_message_id, full_response, conversation_id))
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

    # 拉取成功后记录版本
    if result.returncode == 0:
        _record_installed_version()

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
    async with get_db() as db:
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
    async with get_db() as db:
        db.row_factory = sqlite3.Row
        rows = await db.execute_fetchall(
            "SELECT id, role, content, timestamp FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
            (conversation_id,)
        )
        return [
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "timestamp": row["timestamp"],
            }
            for row in rows
        ]


@app.delete("/messages/{message_id}")
async def delete_message(message_id: int):
    """删除单条消息"""
    async with get_db() as db:
        cursor = await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
        await db.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="消息不存在")
    return {"status": "ok"}


@app.get("/conversations/{conversation_id}/search")
async def search_messages(conversation_id: str, q: str, cross_session: bool = False):
    """FTS5 全文搜索消息。cross_session=True 时搜索所有会话。"""
    if not q.strip():
        return []
    # 转义 FTS5 特殊字符，用双引号包裹整个 query
    safe_q = f'"{q}"'
    async with get_db() as db:
        if cross_session:
            rows = await db.execute_fetchall(
                """SELECT m.role, m.content, m.timestamp, m.conversation_id, m.importance
                   FROM messages_fts fts
                   JOIN messages m ON fts.rowid = m.id
                   WHERE messages_fts MATCH ?
                   ORDER BY m.importance DESC, rank LIMIT 20""",
                (safe_q,)
            )
            return [{"role": r[0], "content": r[1], "timestamp": r[2], "conversation_id": r[3], "importance": r[4]} for r in rows]
        else:
            rows = await db.execute_fetchall(
                """SELECT m.role, m.content, m.timestamp, m.importance
                   FROM messages_fts fts
                   JOIN messages m ON fts.rowid = m.id
                   WHERE messages_fts MATCH ? AND m.conversation_id = ?
                   ORDER BY m.importance DESC, rank LIMIT 20""",
                (safe_q, conversation_id)
            )
            return [{"role": r[0], "content": r[1], "timestamp": r[2], "importance": r[3]} for r in rows]



@app.get("/messages/vector_search")
async def vector_search(q: str, conversation_id: str = None, limit: int = 20):
    """向量语义搜索"""
    if not _vector_store:
        return []
    where = {"conversation_id": conversation_id} if conversation_id else None
    results = _vector_store.query(q, n_results=limit, where=where)
    return results


@app.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str):
    """删除指定 ID 的向量记忆"""
    if not _vector_store:
        return {"error": "vector store not available"}
    _vector_store.delete(int(memory_id))
    return {"ok": True, "deleted": memory_id}


@app.post("/memory/save")
async def save_memory_endpoint(request: Request):
    """保存记忆到对应存储"""
    try:
        body = await request.json()
        content = body.get("content", "")
        mem_type = body.get("type", "fact")
        importance = max(1, min(10, body.get("importance", 5)))
        conversation_id = body.get("conversation_id")

        if not content:
            return {"error": "content is required"}

        if mem_type == "fact":
            if _vector_store:
                metadata = {"importance": importance, "type": "fact"}
                _vector_store.add(
                    message_id=hash(content) % (2**31),
                    content=content,
                    metadata=metadata
                )
            return {"ok": True, "type": "fact"}

        elif mem_type == "episodic":
            if not conversation_id:
                return {"error": "conversation_id required for episodic"}
            async with get_db() as db:
                await db.execute(
                    "INSERT INTO messages (conversation_id, role, content, timestamp, importance) VALUES (?, ?, ?, ?, ?)",
                    (conversation_id, "memory", content, int(time.time() * 1000), importance)
                )
                await db.commit()
            if _vector_store:
                metadata = {"importance": importance, "type": "episodic", "conversation_id": conversation_id}
                _vector_store.add(
                    message_id=hash(content) % (2**31),
                    content=content,
                    metadata=metadata
                )
            return {"ok": True, "type": "episodic"}

        return {"error": f"unknown type: {mem_type}"}
    except Exception as e:
        logger.error(f"save_memory error: {e}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/conversations/all")
async def clear_all_conversations():
    """清空所有会话、消息和 checkpoint（保留 embeddings 记忆）"""
    async with get_db() as db:
        await db.execute("DELETE FROM messages")
        await db.execute("DELETE FROM conversations")
        await db.execute("DELETE FROM checkpoints")
        await db.execute("DELETE FROM writes")
        await db.commit()
    if _agent_instance is not None:
        _agent_instance.clear_history()
    return {"status": "ok", "message": "已清空所有会话（记忆已保留）"}


@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str):
    """删除指定会话及其所有消息、checkpoint"""
    async with get_db() as db:
        await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
        await db.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        await db.execute("DELETE FROM checkpoints WHERE thread_id = ?", (conversation_id,))
        await db.execute("DELETE FROM writes WHERE thread_id = ?", (conversation_id,))
        await db.commit()
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
    """取消当前正在执行的推理（包括子Agent）"""
    global _cancel_requested
    _cancel_requested = True
    # 尝试中断 agent 的 LLM 调用
    if _agent_instance is not None:
        try:
            if hasattr(_agent_instance, 'cancel'):
                _agent_instance.cancel()
            # 取消子Agent任务
            if hasattr(_agent_instance, '_executor_task') and _agent_instance._executor_task:
                _agent_instance._executor_task.cancel()
        except Exception:
            pass
    return {"ok": True}


# ─── 服务关闭 ─────────────────────────────────

@app.post("/shutdown")
async def shutdown():
    """关闭 FastAPI 服务和 embedding 服务"""
    import os, signal, asyncio
    # 清理 agent 实例
    if _agent_instance is not None:
        try:
            await _agent_instance.cleanup()
        except Exception:
            pass
    # 停止 llama-server embedding 服务
    try:
        subprocess.run(["pkill", "-f", "llama-server.*8080"], timeout=3)
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
