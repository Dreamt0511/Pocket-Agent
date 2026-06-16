#!/usr/bin/env python3
"""
Pocket-Agent 主程序
轻量级移动端AI代理 - 真正的 agent loop
"""

import asyncio
import sys
import os
import sqlite3
import time
import subprocess
import warnings
import termios
from datetime import datetime
# 过滤 langgraph/langchain 的版本兼容警告
warnings.filterwarnings("ignore", message=".*allowed_objects.*")
warnings.filterwarnings("ignore", message=".*serde.*")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="langgraph")
# 必须在 import agent 模块之前加载 .env，否则 config.py 读不到环境变量
from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'), override=True)
from agent.ui import PocketUI
from agent.agent_langchain import LangChainPocketAgent
from agent.config import (
    MAX_ITERATIONS, PROJECT_ROOT,
    EMBEDDING_BASE_URL, EMBEDDING_API_KEY, EMBEDDING_MODEL, EMBEDDING_SERVER_URL,
)
from agent.prompts.system_base import prompt as system_base_prompt
from agent.embedding import EmbeddingClient, VectorStore
from agent.tools.basic_tools import set_memory_refs, set_current_conversation_id


DB_PATH = os.path.join(PROJECT_ROOT, "pocket_agent.db")


def _init_db():
    """同步初始化 SQLite 数据库：表 + FTS5 索引（与 app.py 共用同一个 pocket_agent.db）"""
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '新会话',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id)")

        # 兼容字段
        for col, ddl in [
            ("importance", "ALTER TABLE messages ADD COLUMN importance INTEGER DEFAULT 1"),
            ("last_access_at", "ALTER TABLE messages ADD COLUMN last_access_at INTEGER DEFAULT 0"),
            ("memory_type", "ALTER TABLE messages ADD COLUMN memory_type TEXT DEFAULT NULL"),
        ]:
            try:
                conn.execute(ddl)
            except Exception:
                pass

        # FTS5 trigram 全文索引
        existing_fts = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='messages_fts'"
        ).fetchall()
        fts_was_created = False
        if existing_fts and "trigram" not in (existing_fts[0][0] or ""):
            conn.execute("DROP TABLE IF EXISTS messages_fts")
            conn.execute("DROP TRIGGER IF EXISTS messages_fts_ai")
            conn.execute("DROP TRIGGER IF EXISTS messages_fts_ad")
            conn.execute("DROP TRIGGER IF EXISTS messages_fts_au")
            existing_fts = []  # 强制重建
        if not existing_fts:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content, content=messages, content_rowid=id, tokenize='trigram')
            """)
            fts_was_created = True
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_ai AFTER INSERT ON messages BEGIN
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_ad AFTER DELETE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS messages_fts_au AFTER UPDATE ON messages BEGIN
                INSERT INTO messages_fts(messages_fts, rowid, content) VALUES('delete', old.id, old.content);
                INSERT INTO messages_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)
        # 只有首次建表时才需要全量重建，后续由 trigger 增量维护
        if fts_was_created:
            conn.execute("INSERT INTO messages_fts(messages_fts) VALUES('rebuild')")
        conn.commit()
    finally:
        conn.close()


def _init_vector_store():
    """初始化 EmbeddingClient + VectorStore（只存向量索引，内容在 messages 表）"""
    base_url = EMBEDDING_SERVER_URL or EMBEDDING_BASE_URL
    api_key = EMBEDDING_API_KEY
    embedding_client = EmbeddingClient(base_url, api_key, EMBEDDING_MODEL)
    return VectorStore(db_path=DB_PATH, embedding_client=embedding_client)


async def _init_checkpointer():
    """初始化 AsyncSqliteSaver 持久化 checkpoint（与 app.py 一致）"""
    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
        conn = await aiosqlite.connect(DB_PATH)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA busy_timeout=30000")
        saver = AsyncSqliteSaver(conn)
        await saver.setup()
        return saver
    except Exception as e:
        print(f"⚠️  AsyncSqliteSaver 初始化失败，降级为 MemorySaver: {e}")
        from langgraph.checkpoint.memory import MemorySaver
        return MemorySaver()


def _cleanup_old_messages(vector_store):
    """清理低重要性旧记忆的向量索引（与 app.py 一致：30天+importance<=2）"""
    thirty_days_ago = int((time.time() - 30 * 24 * 3600) * 1000)
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            rows = conn.execute(
                "SELECT id FROM messages WHERE role = 'memory' AND importance <= 2 AND timestamp < ?",
                (thirty_days_ago,)
            ).fetchall()
            for row in rows:
                vector_store.delete(row[0])
            if rows:
                print(f"已清理 {len(rows)} 条低重要性旧记忆的向量索引")
        finally:
            conn.close()
    except Exception:
        pass


def _ensure_conversation(conversation_id: str, title: str = "终端会话"):
    """确保会话记录存在（与 app.py 的 conversations 表管理一致）"""
    now = int(time.time() * 1000)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        existing = conn.execute(
            "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchall()
        if not existing:
            conn.execute(
                "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (conversation_id, title, now, now)
            )
        else:
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (now, conversation_id)
            )
        conn.commit()
    finally:
        conn.close()


def _save_message(conversation_id: str, role: str, content: str):
    """保存消息到 messages 表（与 app.py 的消息持久化一致）"""
    now = int(time.time() * 1000)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute(
            "INSERT INTO messages (conversation_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
            (conversation_id, role, content, now)
        )
        # 如果是第一条用户消息，更新会话标题
        if role == "user":
            msg_count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND role = 'user'",
                (conversation_id,)
            ).fetchone()[0]
            if msg_count == 1:
                # 用第一条用户消息的前20个字符作为标题
                title = content[:20].replace('\n', ' ').strip()
                if title:
                    conn.execute(
                        "UPDATE conversations SET title = ? WHERE id = ?",
                        (title, conversation_id)
                    )
        conn.commit()
    finally:
        conn.close()


def _load_history(conversation_id: str, limit: int = 0) -> list:
    """从 SQLite 加载历史消息，恢复会话上下文（与 app.py 一致）

    Args:
        limit: 最多返回条数，0 表示不限制
    """
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            if limit > 0:
                rows = conn.execute(
                    "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (conversation_id, limit)
                ).fetchall()
                rows = list(reversed(rows))
            else:
                rows = conn.execute(
                    "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC",
                    (conversation_id,)
                ).fetchall()
            return [{"role": row[0], "content": row[1]} for row in rows]
        finally:
            conn.close()
    except Exception:
        return []


def _list_conversations() -> list:
    """查询所有会话，按最后更新时间倒序"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT id, title, created_at, updated_at FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
            return [
                {"id": r["id"], "title": r["title"],
                 "created_at": r["created_at"], "updated_at": r["updated_at"]}
                for r in rows
            ]
        finally:
            conn.close()
    except Exception:
        return []


def _get_message_count(conversation_id: str) -> int:
    """获取会话的消息数量"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                (conversation_id,)
            ).fetchone()
            return row[0] if row else 0
        finally:
            conn.close()
    except Exception:
        return 0


async def _select_conversation(ui, conversations: list) -> str | None:
    """显示会话列表，输入序号选择，返回 conversation_id 或 None（取消）"""
    from rich.table import Table
    from datetime import datetime
    from prompt_toolkit import PromptSession

    if not conversations:
        ui.console.print("[dim]暂无历史会话[/dim]")
        return None

    # 显示带编号的列表
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("#", width=3, style="bold yellow")
    table.add_column("会话", min_width=30)
    table.add_column("消息数", width=6, justify="right")
    table.add_column("最后更新", width=17)

    for i, conv in enumerate(conversations):
        ts = datetime.fromtimestamp(conv["updated_at"] / 1000).strftime("%m-%d %H:%M")
        count = _get_message_count(conv["id"])
        table.add_row(str(i + 1), conv["title"][:35], str(count), ts)

    ui.console.print(table)
    ui.console.print()

    # 读取用户选择
    try:
        session = PromptSession()
        choice = await session.prompt_async("输入序号选择会话 (0=取消): ")
        choice = choice.strip()
        if not choice or choice == "0":
            return None
        idx_val = int(choice) - 1
        if 0 <= idx_val < len(conversations):
            return conversations[idx_val]["id"]
        else:
            ui.console.print("[red]无效序号[/red]")
            return None
    except (ValueError, EOFError, KeyboardInterrupt):
        return None


async def _resume_conversation(ui, agent, conversations: list) -> str | None:
    """处理 /resume 命令：选择会话并恢复。返回选中的 conversation_id 或 None。"""
    conv_id = await _select_conversation(ui, conversations)
    if conv_id is None:
        ui.console.print("[dim]已取消[/dim]")
        return None

    # 切换 agent 到目标会话
    # conv_id 是 SQLite 的会话 ID，同时也作为 checkpoint 的 thread_id
    agent.switch_conversation(conv_id)
    set_current_conversation_id(conv_id)

    # 加载并显示最近几条消息作为上下文提示
    history = _load_history(conv_id, limit=6)
    if history:
        ui.console.print(f"\n[dim cyan]── 最近 {len(history)} 条消息 ──[/dim cyan]")
        for msg in history:
            role = "🪀 你" if msg["role"] == "user" else "🤖 AI"
            content = msg["content"][:120] + ("..." if len(msg["content"]) > 120 else "")
            style = "green" if msg["role"] == "user" else "cyan"
            ui.console.print(f"  [{style}]{role}: {content}[/{style}]")
        ui.console.print(f"[dim cyan]─────────────────────[/dim cyan]")

    ui.console.print(f"[bold green]已恢复会话: {conv_id}[/bold green]")
    ui.console.print("[dim]对话历史已从 checkpoint 加载，继续对话即可[/dim]")
    return conv_id


async def main():
    """主函数"""
    ui = PocketUI()

    # ── 初始化基础设施（与 app.py 共用同一个 pocket_agent.db）──
    _init_db()
    vector_store = _init_vector_store()
    set_memory_refs(vector_store, DB_PATH)
    checkpointer = await _init_checkpointer()
    _cleanup_old_messages(vector_store)

    # 终端模式会话ID：每次启动生成新的 UUID，与 agent 的 thread_id 保持一致
    import uuid
    conversation_id = str(uuid.uuid4())
    set_current_conversation_id(conversation_id)

    async def _start_body_server():
        """异步启动 3D 服务，返回 URL 或空串"""
        loop = asyncio.get_event_loop()
        try:
            from agent.tools.body_control_tool import start_body_server
            await loop.run_in_executor(None, start_body_server)
            return "http://localhost:18081"
        except Exception:
            return ""

    loop = asyncio.get_event_loop()

    # 并行启动两个后台服务
    from agent.embedding import start_embedding_server
    embed_task = asyncio.ensure_future(asyncio.to_thread(start_embedding_server))
    body_task = asyncio.ensure_future(_start_body_server())
    await asyncio.gather(embed_task, body_task)
    body_url = body_task.result()

    # 显示 banner
    model_name = os.getenv("LLM_MODEL", "gelab-zero-4b-preview")
    ui.show_welcome_screen(model_name + " (LangChain)", body_url)

    # 嵌入状态检测（语义检索为可选项，无模型直接跳过）
    _emb_ok = False
    _emb_enabled = embed_task.result()  # start_embedding_server 返回 True 表示有模型且已启动
    if _emb_enabled and vector_store.embedding_client:
        delay = 1
        for i in range(4):  # 0s, 1s, 3s, 7s 指数退避
            if i > 0:
                await asyncio.sleep(delay)
                delay *= 2
            if await loop.run_in_executor(None, vector_store.embedding_client.is_available):
                _emb_ok = True
                break
    ui.print_embed_status(_emb_ok)

    # 系统提示词直接从prompts模块导入
    base_system_prompt = system_base_prompt

    # LLM配置 - 完全从环境变量读取，适配电脑/手机双环境
    # 安全读取数字参数，配置错误时使用默认值
    try:
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.7"))
        # 温度值必须在0-2之间
        temperature = max(0.0, min(2.0, temperature))
    except (ValueError, TypeError):
        temperature = 0.7

    try:
        max_tokens = int(os.getenv("LLM_MAX_TOKENS", "8000"))
        # max_tokens必须为正整数
        max_tokens = max(1, max_tokens)
    except (ValueError, TypeError):
        max_tokens = 8000

    llm_config = {
        "base_url": os.getenv("DEFAULT_LLM_BASE_URL", "http://127.0.0.1:8080/v1"),
        "api_key": os.getenv("LLM_API_KEY", "dummy"),
        "model": model_name,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # 创建LangChain Agent
    agent = LangChainPocketAgent(
        system_prompt=base_system_prompt,
        max_iterations=MAX_ITERATIONS,  # 从配置文件读取最大迭代次数
        llm_config=llm_config,
        ui=ui,
        checkpointer=checkpointer,
        thread_id=conversation_id,  # 使用与 conversation_id 相同的 UUID
    )

    # 更新 UI 自动补全的技能列表
    try:
        from agent.agent_langchain import load_skills_for_completer
        skill_names, skill_descs, skill_info = load_skills_for_completer("main")
        ui.update_skill_completions(skill_names, skill_descs)
    except Exception:
        skill_info = {}

    loop = asyncio.get_event_loop()

    # 互动式对话循环
    current_task = None  # 记录当前正在执行的任务
    is_processing = False  # 标记是否正在处理用户请求

    # 后台任务：处理浏览器消息（asyncio.Event 无轮询，主协程阻塞）
    async def browser_message_loop():
        from agent.tools.body_server import (init_browser_event,
            get_browser_event, get_browser_message, push_response_event)
        init_browser_event(asyncio.get_event_loop())
        ev = get_browser_event()
        while True:
            # 先看队列是否有积压
            msg = get_browser_message()
            if not msg:
                ev.clear()
                msg = get_browser_message()  # double-check：防止 clear 和 wait 之间消息到达
                if not msg:
                    await ev.wait()
                    msg = get_browser_message()
            if is_processing or not msg:
                continue
            # 打印分隔线和浏览器消息（与终端输入风格一致）
            ui.console.print()
            ui.console.rule(style="dim cyan")
            ui.console.print(f"[bold green]🪀 浏览器:[/bold green] {msg}")
            _save_message(conversation_id, "user", msg)
            push_response_event('thinking', {})
            try:
                async for chunk in agent.stream_conversation(msg):
                    etype = chunk.get('type', '')
                    if etype == 'token':
                        push_response_event('token', {'content': chunk.get('content', '')})
                    elif etype == 'tool_start':
                        push_response_event('tool_start', {'name': chunk.get('name', '')})
                    elif etype == 'tool_end':
                        push_response_event('tool_end', {'name': chunk.get('name', '')})
                    elif etype == 'done':
                        _save_message(conversation_id, "assistant", chunk.get('response', ''))
                        push_response_event('done', {'response': chunk.get('response', '')})
                    elif etype == 'error':
                        push_response_event('error', {'message': chunk.get('message', '')})
            except Exception as e:
                push_response_event('error', {'message': str(e)})

    browser_task = asyncio.create_task(browser_message_loop())

    while True:
        try:
            # 等待用户输入，捕获所有输入相关异常
            try:
                user_input = await ui.async_print_user_input_prompt()
            except (KeyboardInterrupt, EOFError, SystemExit):
                # 输入时按Ctrl+C直接退出
                ui.print_success("\n\n再见！")
                break
            except Exception:
                # 其他输入异常，继续下一轮
                continue

            # 确保 user_input 是字符串
            if user_input is None:
                user_input = ""

            # 检查退出命令 - 处理可能的空白字符
            user_input_stripped = user_input.strip().lower()
            if user_input_stripped in ['q', 'quit', 'exit', 'bye', '退出']:
                ui.print_success("再见！")
                break

            if user_input_stripped == 'help':
                help_text = """**常用指令**:
- 直接输入问题 → AI agent 自动调用工具回答
- 询问技能 → 直接说"有哪些技能"或"加载XX技能"
- `/resume` → 选择并恢复历史会话
- `/undo` → 撤回上一条发送的消息
- `q` → 退出程序
- **ESC** → agent 执行时按一次打断，输入阶段按清空当前输入
- Ctrl+C → 强制退出程序"""
                ui.print_agent_response(help_text)
                continue

            # 恢复历史会话
            if user_input_stripped == '/resume':
                conversations = _list_conversations()
                new_id = await _resume_conversation(ui, agent, conversations)
                if new_id:
                    conversation_id = new_id
                continue

            # 撤回消息功能
            if user_input_stripped == '/undo':
                # LangChain版本：创建新会话，清空历史
                agent.clear_history()
                # 生成新的会话 ID，确保与 agent 的 thread_id 一致
                conversation_id = agent._default_thread_id
                set_current_conversation_id(conversation_id)
                ui.print_success("✅ 已清空对话历史，你可以重新输入")
                continue

            # 清空对话历史
            if user_input_stripped == '/clear':
                agent.clear_history()
                # 生成新的会话 ID，确保与 agent 的 thread_id 一致
                conversation_id = agent._default_thread_id
                set_current_conversation_id(conversation_id)
                # 清屏并重新显示欢迎界面
                ui.show_welcome_screen(model_name + " (LangChain)", body_url)
                if vector_store.embedding_client:
                    _emb_ok = await loop.run_in_executor(None, vector_store.embedding_client.is_available)
                    ui.print_embed_status(_emb_ok)
                continue

            if not user_input_stripped:
                continue

            # ── 拦截 /技能名 [+ 用户需求] 输入，转换为读取技能指令 ──
            if user_input.startswith('/') and user_input_stripped not in ['/resume', '/undo', '/clear', '/help']:
                parts = user_input.lstrip('/').strip().split(' ', 1)
                skill_name = parts[0].strip()
                user_request = parts[1].strip() if len(parts) > 1 else ""
                if skill_name in skill_info:
                    skill_path = skill_info[skill_name]['path']
                    if user_request:
                        user_input = f"请读取 {skill_name} 技能（{skill_path}），然后按指导执行：{user_request}"
                    else:
                        user_input = f"请读取 {skill_name} 技能（{skill_path}）并按指导执行"
                    user_input_stripped = user_input.strip().lower()

            # ── 消息持久化（与 app.py 一致）──
            _ensure_conversation(conversation_id)
            _save_message(conversation_id, "user", user_input)

            # ── 真正的 agent loop ──

            try:
                is_processing = True
                current_task = asyncio.create_task(agent.run_conversation(user_input))

                # ── ESC 中断监听 ──
                _esc_ref = [current_task]
                fd = sys.stdin.fileno()
                stdin_is_tty = sys.stdin.isatty()
                _raw_settings = None
                if stdin_is_tty:
                    # 不要用 tty.setraw()——它会禁用 OPOST（输出处理），导致终端输出乱掉
                    _raw_settings = termios.tcgetattr(fd)
                    new_attr = list(_raw_settings)
                    # 只改输入属性：关闭 ICANON（行缓冲）、ECHO、ISIG（信号字符）
                    # 保留输出属性（OPOST），确保 Live/console.print 正常渲染
                    new_attr[0] = new_attr[0] & ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP | termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
                    new_attr[3] = new_attr[3] & ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
                    new_attr[6][termios.VMIN] = 1
                    new_attr[6][termios.VTIME] = 0
                    termios.tcsetattr(fd, termios.TCSADRAIN, new_attr)

                def _on_stdin():
                    t = _esc_ref[0]
                    if t is None or t.done():
                        return
                    try:
                        data = sys.stdin.buffer.read1(1024)
                        if data and b'\x1b' in data:
                            t.cancel()
                    except Exception:
                        pass
                loop.add_reader(fd, _on_stdin)

                try:
                    response, used_streaming, call_count = await current_task
                finally:
                    try:
                        loop.remove_reader(fd)
                    except Exception:
                        pass
                    if _raw_settings is not None:
                        try:
                            termios.tcsetattr(fd, termios.TCSADRAIN, _raw_settings)
                        except Exception:
                            pass
                        try:
                            termios.tcflush(fd, termios.TCIFLUSH)
                        except Exception:
                            pass

            except (asyncio.CancelledError, KeyboardInterrupt):
                ui.console.print()
                ui.print_warning("⏹️  已打断当前思考，你可以输入新的问题或指令")
                try:
                    _save_message(conversation_id, "assistant", "[已打断]")
                except Exception:
                    pass
                response = None
                used_streaming = False
            except Exception as e:
                response = f"❌ Agent 执行错误: {str(e)}"
                used_streaming = False
            finally:
                is_processing = False
                current_task = None

        except KeyboardInterrupt:
            ui.print_success("\n\n再见！")
            break
        except Exception as e:
            ui.print_error(f"发现错误: {e}")
            break

    # ── 退出清理（取消后台任务、释放端口）──
    browser_task.cancel()
    try:
        from agent.tools.body_control_tool import stop_body_server
        stop_body_server()
    except Exception:
        pass
    from agent.embedding import stop_embedding_server
    stop_embedding_server()


if __name__ == "__main__":
    # 确保所有文件都可以被导入
    project_root = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, project_root)

    # 强制兼容所有事件循环场景
    try:
        import nest_asyncio
        nest_asyncio.apply()
    except ImportError:
        print("⚠️  请先安装依赖：pip install nest_asyncio prompt_toolkit")
        sys.exit(1)

    # 全局异常处理，确保干净退出
    try:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(main())
        # nest_asyncio 不会停止事件循环，强制退出
        os._exit(0)
    except (KeyboardInterrupt, SystemExit):
        os._exit(0)
    except Exception as e:
        exc_str = str(type(e)) + str(e)
        if "KeyboardInterrupt" not in exc_str and "CancelledError" not in exc_str:
            print(f"\n❌ 程序异常退出: {str(e)}")
        os._exit(1)
