#!/usr/bin/env python3
"""
轻量级工具集合
"""

import json
import os
import re
import subprocess
import sqlite3
import time
from typing import Dict, List, Optional
from langchain_core.tools import tool
import requests

# 由 app.py startup 注入，避免 HTTP 自调用死锁
_vector_store_ref = None
_db_path_ref = None


def _notify_progress(message: str):
    """安全地推送工具执行进度（如果在 LangGraph 上下文中）"""
    try:
        from langgraph.config import get_stream_writer
        writer = get_stream_writer()
        if writer:
            writer({"type": "progress", "message": message})
    except Exception:
        pass  # 不在 LangGraph 上下文中时静默忽略

def set_memory_refs(vector_store, db_path):
    global _vector_store_ref, _db_path_ref
    _vector_store_ref = vector_store
    _db_path_ref = db_path


@tool
def file_read(filepath: str, max_lines: int = 100) -> str:
    """
    读取文件内容，支持相对于项目根目录的相对路径。

    Args:
        filepath: 文件路径（支持相对路径）
        max_lines: 最大读取行数，默认100
    """
    try:
        # 支持相对路径：优先尝试相对于项目根目录
        if not os.path.isabs(filepath):
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            project_root = os.path.dirname(project_root)  # 从agent/tools/到项目根目录
            filepath = os.path.join(project_root, filepath)

        if not os.path.exists(filepath):
            return f"文件不存在: {filepath}"

        with open(filepath, 'r', encoding='utf-8') as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_lines:
                    lines.append("... (已截止)")
                    break
                lines.append(f"{i+1:3d}| {line.rstrip()}")

        return "\n".join(lines)
    except Exception as e:
        return f"读取文件错误: {str(e)}"


@tool
def file_write(filepath: str, content: str, append: bool = False) -> str:
    """
    写入文件内容。

    Args:
        filepath: 文件路径
        content: 要写入的内容
        append: 是否追加模式，默认False
    """
    try:
        # ── 任务完成门禁：写入 task.json 且 all_completed=true 时，检查所有 steps 是否都已完成 ──
        if not append and filepath.endswith("task.json"):
            try:
                task_data = json.loads(content)
                if task_data.get("all_completed") is True:
                    steps = task_data.get("steps", [])
                    unfinished = [s for s in steps if s.get("status") != "completed"]
                    if unfinished:
                        first = unfinished[0]
                        return (
                            f"❌ 门禁拦截：任务还有 {len(unfinished)} 个步骤未完成，不能标记 all_completed。"
                            f"第一个未完成的步骤：步骤{first.get('id')} - {first.get('desc')}。"
                            f"请继续执行该步骤，完成后再标记 all_completed。"
                        )
            except (json.JSONDecodeError, AttributeError):
                pass

        mode = 'a' if append else 'w'
        with open(filepath, mode, encoding='utf-8') as f:
            f.write(content)

        action = "追加" if append else "写入"
        return f"文件{action}成功: {filepath}"
    except Exception as e:
        return f"写入文件错误: {str(e)}"


@tool
def file_search(pattern: str, filepath: str, context_lines: int = 2) -> str:
    """
    在文件中搜索内容。

    Args:
        pattern: 正则表达式模式
        filepath: 要搜索的文件路径
        context_lines: 上下文行数，默认2
    """
    try:
        if not os.path.exists(filepath):
            return f"文件不存在: {filepath}"

        matches = []
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        for i, line in enumerate(lines):
            if re.search(pattern, line):
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)

                context = []
                for j in range(start, end):
                    marker = ">>> " if j == i else "    "
                    context.append(f"{marker}{j+1:3d}| {lines[j].rstrip()}")

                matches.append("\n".join(context))

        if matches:
            return f"找到 {len(matches)} 个匹配:\n\n" + "\n\n".join(matches)
        else:
            return f"未找到匹配 '{pattern}' 的内容"
    except Exception as e:
        return f"搜索错误: {str(e)}"


@tool
def directory_list(directory: str, pattern: str = "*") -> str:
    """
    列出目录内容。

    Args:
        directory: 目录路径
        pattern: 文件名筛选模式，默认*
    """
    try:
        if not os.path.exists(directory):
            return f"目录不存在: {directory}"

        items = []
        for item in os.listdir(directory):
            full_path = os.path.join(directory, item)
            if os.path.isdir(full_path):
                items.append(f"📁 {item}/")  # 文件夹图标
            else:
                size = os.path.getsize(full_path)
                items.append(f"📄 {item} ({size} bytes)")  # 文件图标

        if items:
            return f"目录 '{directory}' 内容:\n" + "\n".join(sorted(items))
        else:
            return f"目录 '{directory}' 为空"
    except Exception as e:
        return f"查看目录错误: {str(e)}"


@tool
def system_info(info_type: str = "all") -> str:
    """
    获取手机系统信息。
    需要先安装Termux API：pkg install termux-api && 安装手机端Termux:API应用
    """
    TERMUX_API_CHECK_CMD = "command -v termux-battery-status"
    TERMUX_API_INSTALL_GUIDE = """⚠️  请先安装Termux API:
1. 执行: pkg install termux-api
2. 在手机应用商店安装 Termux:API 应用
"""

    def _run_termux_cmd(cmd: str) -> str:
        """执行Termux API命令，处理异常"""
        try:
            result = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                try:
                    # 尝试格式化JSON输出
                    data = json.loads(result.stdout.strip())
                    return json.dumps(data, ensure_ascii=False, indent=2)
                except:
                    return result.stdout.strip()
            else:
                return f"命令执行失败: {result.stderr.strip()}"
        except subprocess.TimeoutExpired:
            return "命令执行超时"
        except Exception as e:
            return f"执行错误: {str(e)}"

    try:
        # 检测是否安装了termux-api
        check = subprocess.run(TERMUX_API_CHECK_CMD, shell=True, capture_output=True)
        if check.returncode != 0:
            return TERMUX_API_INSTALL_GUIDE + "\n基础存储信息：\n" + _run_termux_cmd("df -h /sdcard")

        result = []
        info_type = info_type.lower()

        if info_type in ["all", "battery"]:
            result.append("📱 电池信息:")
            result.append(_run_termux_cmd("termux-battery-status"))
            result.append("")

        if info_type in ["all", "cpu"]:
            result.append("⚡ CPU信息:")
            # 显示CPU核心数和关键信息，而不是前30行
            cpu_cores = _run_termux_cmd("cat /proc/cpuinfo | grep -c processor")
            cpu_model = _run_termux_cmd("cat /proc/cpuinfo | grep 'model name' | head -1 | cut -d: -f2 | sed 's/^ *//'")
            cpu_info = _run_termux_cmd("cat /proc/cpuinfo | grep 'Hardware' | head -1 | cut -d: -f2 | sed 's/^ *//'")
            result.append(f"核心数: {cpu_cores.strip() if cpu_cores else '未知'}")
            result.append(f"型号: {cpu_model.strip() if cpu_model else '未知'}")
            result.append(f"硬件: {cpu_info.strip() if cpu_info else '未知'}")
            result.append("")

        if info_type in ["all", "memory"]:
            result.append("💾 内存信息:")
            result.append(_run_termux_cmd("cat /proc/meminfo | head -10"))
            result.append("")

        if info_type in ["all", "disk", "storage"]:
            result.append("💽 存储信息:")
            result.append(_run_termux_cmd("df -h /sdcard"))
            result.append(_run_termux_cmd("df -h /data"))
            result.append("")

        if info_type in ["all", "network", "wifi"]:
            result.append("📶 WiFi信息:")
            result.append(_run_termux_cmd("termux-wifi-connectioninfo"))
            result.append("")

        if info_type in ["all", "device"]:
            result.append("🔧 设备信息:")
            result.append(_run_termux_cmd("termux-telephony-deviceinfo"))
            result.append("")

        if not result:
            return f"不支持的信息类型 '{info_type}'\n支持的类型: all/battery/cpu/memory/disk/network/device/wifi"

        return "\n".join(result).strip()

    except Exception as e:
        return f"获取系统信息错误: {str(e)}"


@tool
def shell_exec(command: str) -> str:
    """执行shell命令"""
    # 截断过长的命令显示（最多50字符）
    def truncate_cmd(cmd: str, max_len: int = 50) -> str:
        return cmd[:max_len] + "..." if len(cmd) > max_len else cmd

    # 检测是否在纯Termux终端环境下调用安卓控制命令
    def check_android_command_environment(cmd: str) -> Optional[str]:
        """检查安卓控制命令是否可以在当前环境下运行"""
        android_commands = [
            "android_click", "android_swipe", "android_input", "android_screenshot",
            "android_get_installed_apps", "android_launch_app", "android_stop_app"
        ]

        # 检查是否是安卓控制命令
        is_android_cmd = any(cmd_name in cmd for cmd_name in android_commands)
        if not is_android_cmd:
            return None

        # 跳过MCP/NeuralBridge的curl调用（MCP走HTTP协议，不需要INJECT_EVENTS权限）
        # 命令中的android_xxx是JSON-RPC参数名，不是直接调用的命令
        if "curl" in cmd and "mcp" in cmd.lower():
            return None

        # 检测是否在Termux环境下
        is_termux = os.path.exists("/data/data/com.termux")
        if not is_termux:
            return None

        # 检测是否有图形界面（DISPLAY环境变量）
        has_display = os.getenv("DISPLAY") is not None
        if has_display:
            return None

        # 纯Termux终端环境，没有图形界面
        return """⚠️  安卓控制功能需要图形界面环境才能使用：
1. 请在Android系统的图形界面下使用本功能
2. 或在Termux中配置VNC/GUI环境后再使用
3. 纯终端命令行环境下无法执行屏幕点击、输入等操作"""

    # 先检查环境
    env_error = check_android_command_environment(command)
    if env_error:
        return env_error

    truncated_cmd = truncate_cmd(command)

    # termux-tts-speak 必须后台运行，否则会阻塞或超时被杀死
    if command.strip().startswith("termux-tts-speak"):
        subprocess.run(
            command + " &>/dev/null &",
            shell=True,
            capture_output=False,
            timeout=3,
        )
        return "✅ 已执行"

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        output = result.stdout.strip()
        error = result.stderr.strip()

        if result.returncode != 0:
            return f"执行命令: {truncated_cmd}\n命令执行失败 (错误码 {result.returncode}):\n{error}"

        if output:
            return f"执行命令: {truncated_cmd}\n{output}"
        else:
            return f"执行命令: {truncated_cmd}\n命令执行成功，无输出"

    except subprocess.TimeoutExpired:
        return f"执行命令: {truncated_cmd}\n命令执行超时"
    except Exception as e:
        return f"执行命令: {truncated_cmd}\n执行命令错误: {str(e)}"


# 全局记忆系统实例（用于工具调用）
_memory_instance = None

def set_memory_instance(memory):
    """设置全局记忆实例，供工具调用"""
    global _memory_instance
    _memory_instance = memory

# 当前会话ID（用于会话历史搜索）
_current_conversation_id = None

def set_current_conversation_id(conversation_id: str):
    """设置当前会话ID，供 search_memory 工具使用"""
    global _current_conversation_id
    _current_conversation_id = conversation_id


# ── 混合检索辅助函数 ──────────────────────────────────────────────

def _split_chinese_query(query: str) -> list:
    """中文查询分词：空格分割 + 无空格中文按2字切分"""
    import re
    tokens = []
    for part in query.split():
        # 检测是否含中文且无空格（连续中文≥4字则按2字切分）
        if re.search(r'[一-鿿]{4,}', part):
            chars = re.findall(r'[一-鿿]', part)
            if len(chars) >= 4:
                for i in range(len(chars) - 1):
                    tokens.append(chars[i] + chars[i + 1])
            else:
                tokens.append(part)
        else:
            tokens.append(part)
    return tokens


def _fts_search(query: str, conversation_id: str = None, days: int = None, msg_type: str = None, memory_type: str = None) -> list:
    """FTS5 trigram 搜索为主，搜不到时用 LIKE 补充"""
    if not _db_path_ref:
        return []
    conn = None
    try:
        conn = sqlite3.connect(_db_path_ref, timeout=10)
        conn.execute("PRAGMA busy_timeout=5000")

        # 构建通用过滤条件
        conditions = []
        params = []
        if conversation_id:
            conditions.append("m.conversation_id = ?")
            params.append(conversation_id)
        if days:
            conditions.append("m.timestamp > ?")
            params.append(int((time.time() - days * 86400) * 1000))
        if msg_type:
            valid_types = ("user", "assistant", "memory")
            if msg_type not in valid_types:
                return []
            conditions.append("m.role = ?")
            params.append(msg_type)
        if memory_type:
            conditions.append("m.memory_type = ?")
            params.append(memory_type)

        where_extra = (" AND " + " AND ".join(conditions)) if conditions else ""
        fts_where_extra = (" AND " + " AND ".join(conditions)) if conditions else ""

        keywords = query.split()
        if not keywords:
            keywords = [query]

        seen_ids = set()
        results = []

        def _add(rows):
            for r in rows:
                if r[0] not in seen_ids:
                    seen_ids.add(r[0])
                    results.append({"id": r[0], "conversation_id": r[1], "role": r[2], "content": r[3], "importance": r[4], "last_access_at": r[5], "timestamp": r[6], "memory_type": r[7] if len(r) > 7 else None})

        # 策略1: FTS5 trigram 搜索（>=3字符的关键词）
        long_keywords = [k for k in keywords if len(k) >= 3]
        if long_keywords:
            try:
                fts_query = " OR ".join(long_keywords)
                fts_rows = conn.execute(
                    f"""SELECT m.id, m.conversation_id, m.role, m.content, m.importance, m.last_access_at, m.timestamp, m.memory_type
                        FROM messages_fts fts JOIN messages m ON fts.rowid = m.id
                        WHERE fts MATCH ?{fts_where_extra}
                        ORDER BY rank LIMIT 20""",
                    [fts_query] + params
                ).fetchall()
                _add(fts_rows)
            except Exception:
                pass

        # 策略2: LIKE 补充（短词 <3字符，或 FTS 没搜到时）
        # 中文无空格时按2字切分（如"动作舞蹈"→["动作","舞蹈"]）
        short_keywords = [k for k in keywords if len(k) < 3]
        if short_keywords or not results:
            fallback_keywords = short_keywords if short_keywords else _split_chinese_query(query)
            fallback_keywords = list(dict.fromkeys(fallback_keywords))  # 去重保序
            if fallback_keywords:
                like_conditions = ["m.content LIKE ?" for _ in fallback_keywords]
                like_params = [f"%{k}%" for k in fallback_keywords]
                like_clause = " OR ".join(like_conditions)
                rows = conn.execute(
                    f"""SELECT m.id, m.conversation_id, m.role, m.content, m.importance, m.last_access_at, m.timestamp, m.memory_type
                        FROM messages m WHERE ({like_clause}){where_extra}
                        ORDER BY length(m.content) ASC, m.timestamp DESC LIMIT 20""",
                    like_params + params
                ).fetchall()
                _add(rows)

        return results
    except Exception:
        return []
    finally:
        if conn:
            conn.close()

def _vector_search(query: str, conversation_id: str = None, days: int = None, msg_type: str = None, memory_type: str = None) -> list:
    """向量语义搜索：embeddings 表查向量 → 回 messages 表取原文"""
    if not _vector_store_ref or not _db_path_ref:
        return []
    try:
        # 第一步：向量搜索（过滤条件下推到 SQL 层，只对匹配的向量计算相似度）
        vec_results = _vector_store_ref.query(
            query, n_results=20,
            conversation_id=conversation_id,
            msg_type=msg_type,
            days=days,
            memory_type=memory_type,
        )
        if not vec_results:
            return []

        # 过滤低相似度结果
        MIN_SIMILARITY = 0.35
        vec_results = [r for r in vec_results if (1 - r["distance"]) >= MIN_SIMILARITY]
        if not vec_results:
            return []

        # 第二步：用 id 回 messages 表取原文（过滤已在 query 中完成）
        ids = [r["id"] for r in vec_results]
        id_to_distance = {r["id"]: r["distance"] for r in vec_results}

        conn = sqlite3.connect(_db_path_ref, timeout=10)
        conn.execute("PRAGMA busy_timeout=5000")
        try:
            placeholders = ",".join(["?"] * len(ids))
            rows = conn.execute(
                f"SELECT id, conversation_id, role, content, importance, last_access_at, timestamp, memory_type FROM messages WHERE id IN ({placeholders})",
                ids
            ).fetchall()
        finally:
            conn.close()

        results = []
        for row_id, conv_id, role, content, importance, last_access, ts, mem_type in rows:
            results.append({
                "id": row_id,
                "role": role,
                "content": content,
                "conversation_id": conv_id,
                "importance": importance or 3,
                "last_access_at": last_access or 0,
                "memory_type": mem_type,
                "similarity": 1 - id_to_distance.get(str(row_id), 0),
            })

        return results
    except Exception:
        return []

def _rrf_merge(fts_results: list, vec_results: list, k: int = 60, top_n: int = 20) -> list:
    """纯 RRF 融合：将 FTS5 和向量检索结果通过 Reciprocal Rank Fusion 合并。

    RRF 分数 = 1/(k + rank + 1)，出现在两路中的结果分数累加。
    仅做融合排序，不做加权——加权由上游 _rerank_memories 负责。

    参数：
        k: RRF 平滑参数（越大越平滑，默认 60）
        top_n: 返回候选数（默认 20，给上游 rerank 留足空间）
    """
    scores = {}

    # FTS5 结果已按 rank 排序
    for rank, msg in enumerate(fts_results):
        key = msg.get("id")
        scores[key] = {"rrf": 1 / (k + rank + 1), "msg": msg}

    # 向量结果按 similarity 降序排列后算 RRF
    sorted_vec = sorted(vec_results, key=lambda x: x.get("similarity", 0), reverse=True)
    for rank, msg in enumerate(sorted_vec):
        key = msg.get("id")
        rrf_score = 1 / (k + rank + 1)
        if key in scores:
            scores[key]["rrf"] += rrf_score
        else:
            scores[key] = {"rrf": rrf_score, "msg": msg}

    # 按纯 RRF 分数排序
    sorted_items = sorted(scores.values(), key=lambda x: x["rrf"], reverse=True)

    return [item["msg"] for item in sorted_items[:top_n]]


def _rerank_memories(memories: list, alpha: float = 0.45, beta: float = 0.25, gamma: float = 0.3, top_k: int = 5) -> list:
    """对 RRF 融合后的候选记忆二次排序。

    综合分 = α·语义相似度 + β·时间衰减 + γ·重要性
    三个维度归一化到 0~1 后加权，确保量级一致。

    参数：
        alpha: 语义权重（默认 0.45）
        beta:   时间衰减权重（默认 0.25）
        gamma:  重要性权重（默认 0.3）
        top_k:  返回条数（默认 5）
    """
    if not memories:
        return []

    current_time = time.time() * 1000  # 毫秒
    DECAY_RATE = 0.995  # 每小时衰减

    for mem in memories:
        # 语义相似度：向量结果有 similarity，FTS 结果用 0.5 兜底
        similarity = mem.get("similarity", 0.5)

        # 时间衰减：last_access_at 越近越高
        last_access = mem.get("last_access_at", current_time)
        if last_access == 0:
            last_access = current_time
        hours_passed = (current_time - last_access) / 3600000
        recency_score = DECAY_RATE ** hours_passed

        # 重要性：1~10 归一化到 0~1
        importance = mem.get("importance", 3)
        importance_score = min(importance / 10.0, 1.0)

        # 加权综合
        mem["_final_score"] = (
            alpha * similarity +
            beta * recency_score +
            gamma * importance_score
        )

    memories.sort(key=lambda x: x["_final_score"], reverse=True)
    return memories[:top_k]


@tool
async def update_user_profile(section: str, content: str) -> str:
    """
    记录用户明确提到的个人信息到用户画像中。

    什么时候记录：
    - 用户主动说出个人信息（姓名、职业、位置等）
    - 用户表达偏好或习惯（沟通方式、饮食、作息等）
    - 用户提出行为要求（"不要废话""等我确认再执行"等）
    - 用户反馈纠正你的行为（记住并写入行为要求）

    什么时候不记录：
    - 普通闲聊内容
    - 一次性任务指令
    - 已经在记忆中的重复信息

    可用 section（也可以自定义新 section）：
    - 基本信息：姓名、职业、位置、兴趣
    - 沟通偏好：回答风格、语言习惯、交互方式
    - 行为要求：对 agent 的约束和规则
    - 反馈：用户对 agent 表现的评价、建议、不满
    - 其他：不属于以上分类的信息

    Args:
        section: 画像章节名（可用预设名称或自定义）
        content: 该章节的内容（追加或替换，保持简洁）
    """
    if not _memory_instance:
        return "❌ 记忆系统未初始化，无法更新用户画像"

    try:
        _notify_progress("正在更新用户画像...")
        # 异步执行更新，不阻塞主流程
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _memory_instance.update_user_profile, section, content)
        return f"✅ 已更新用户画像 [{section}]"
    except Exception as e:
        return f"❌ 更新用户画像失败: {str(e)}"


@tool
async def mcp_call(server_url: str, tool_name: str, arguments: Optional[str] = None) -> str:
    """
    调用 MCP 服务的工具。支持任何 MCP 协议的 JSON-RPC 服务。
    注意：NeuralBridge 的 MCP 地址为 http://127.0.0.1:7474/mcp

    Args:
        server_url: MCP 服务地址（如 http://127.0.0.1:7474/mcp）
        tool_name: 工具名（如 android_tap、android_screenshot、android_get_ui_tree）
        arguments: 工具参数的 JSON 字符串，如 '{"x": 315, "y": 1002}'。没有参数时传 "{}" 或不传。
    """
    try:
        # 解析 arguments JSON 字符串 → dict
        if isinstance(arguments, str):
            if not arguments.strip():
                arguments = None
            else:
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    import ast
                    try:
                        arguments = ast.literal_eval(arguments)
                    except (ValueError, SyntaxError):
                        return f"❌ mcp_call 参数解析失败: arguments={arguments[:100]}, 应传入 JSON 字符串如 '{{\"x\": 315, \"y\": 1002}}'"

        # tools/list 是 MCP 协议级别的查询方法，不是具体工具，不走 tools/call 包装
        if tool_name == "tools/list":
            payload = {
                "jsonrpc": "2.0",
                "method": "tools/list",
                "id": 1
            }
        else:
            payload = {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments or {}
                },
                "id": 1
            }
        import asyncio
        loop = asyncio.get_running_loop()
        resp = await loop.run_in_executor(
            None,
            lambda: requests.post(server_url, json=payload, timeout=30)
        )
        resp.raise_for_status()
        result = resp.json()

        if "error" in result:
            return f"❌ MCP 调用失败: {result['error']}"

        # tools/list 返回 result.tools 数组，不是 result.content
        if tool_name == "tools/list":
            tools = result.get("result", {}).get("tools", [])
            if not tools:
                return "✅ 服务已连接，但无可用工具"
            lines = [f"📦 可用工具 ({len(tools)} 个):"]
            for t in tools:
                name = t.get("name", "?")
                desc = t.get("description", "")
                lines.append(f"  - {name}: {desc[:100]}")
            return "\n".join(lines)

        # 提取 content 中的文本
        content = result.get("result", {}).get("content", [])
        texts = []
        for item in content:
            if item.get("type") == "text":
                texts.append(item["text"])
            elif item.get("type") == "image":
                img_data = item.get("data", "")
                size_kb = len(img_data) * 3 / 4 / 1024
                texts.append(f"[截图: {item.get('width','?')}x{item.get('height','?')}, {size_kb:.0f}KB]")

        return "\n".join(texts) if texts else "✅ 调用成功，无返回内容"
    except requests.exceptions.Timeout:
        return "❌ MCP 请求超时（30秒），请检查服务是否运行"
    except requests.exceptions.ConnectionError:
        return f"❌ 无法连接 MCP 服务 {server_url}，请确认服务是否启动"
    except Exception as e:
        return f"❌ MCP 调用异常: {str(e)}"


@tool
async def tts_speak(text: str) -> str:
    """
    朗读文字，手机会发出声音。自动后台执行，不阻塞当前对话。

    内部调用 termux-tts-speak 并后台运行，你不需要关心具体的 shell 命令。
    如果朗读失败，静默忽略即可，正常文字回复。

    Args:
        text: 要朗读的文字
    """
    import asyncio, subprocess
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: subprocess.run(
            f'termux-tts-speak "{text}" &>/dev/null &',
            shell=True, timeout=5,
        ))
        return "✅ 已执行"
    except Exception:
        return "⚠️ 执行失败"


def _extract_embed_text(content: str) -> str:
    """提取适合嵌入的文本。动作JSON数据只取名称+描述，避免超长无语义内容。"""
    # 检测是否包含动作JSON数组（以 [{"action": 开头的JSON块）
    json_start = content.find('[{"action":')
    if json_start == -1:
        json_start = content.find("[{'action':")
    if json_start > 0:
        # 取JSON之前的文字描述部分
        desc = content[:json_start].strip().rstrip("：:，,\n")
        if desc:
            return desc
    # 非动作数据，正常返回（过长时截断到2000字符）
    if len(content) > 2000:
        return content[:2000]
    return content


@tool
def save_memory(content: str, type: str = "fact", importance: int = 5) -> str:
    """保存重要信息到记忆系统。只在值得记的内容时调用，不要每条对话都存。

    何时调用：
    - 用户提到的项目决定、技术选型
    - 重要的事件结果（部署成功/失败、问题解决方案）
    - 用户的工作上下文（在做什么项目、当前目标）
    - 值得以后回忆的关键信息

    何时不调用：
    - 普通闲聊、问候
    - 工具执行的技术细节（shell 输出、文件内容）
    - 已经在用户画像中的信息（姓名、永久偏好）

    Args:
        content: 要记忆的内容，简洁明确
        type: "fact" 事实记忆（用户偏好、技术决定、知识性信息），"episodic" 事件记忆（操作结果、问题解决方案、时间相关事件），"dance" 舞蹈动作记忆（编舞数据、动作序列、姿态信息）。三者都同时存入消息表（支持关键词搜索）和向量数据库（支持语义搜索）。
        importance: 重要性 1-10，自行判断打分。大多数记忆应在 3-5 分，只有真正影响后续决策的才值得 7 分以上。

        打分参考（仅供大致参考，不必死板遵守）：
        - 1-2: 临时性信息，很快就会过时
        - 3-4: 一般有用，比如用户的某个偏好、一次普通操作的结果
        - 5-6: 比较重要，比如项目架构决定、关键技术选型
        - 7-8: 很重要，比如影响后续多次决策的结论、重大问题的根因
        - 9-10: 极其重要，比如用户明确强调的关键需求、不可逆的重大决定

        注意：不要每条都打高分，大部分记忆 3-5 分即可。高分要留给真正值得反复回忆的内容。
    """
    t0 = time.monotonic()
    try:
        current_timestamp = int(time.time() * 1000)

        if type not in ("fact", "episodic", "dance"):
            return "type 必须是 'fact'、'episodic' 或 'dance'"

        if not _current_conversation_id:
            return "保存失败: 需要 conversation_id（请在会话中调用）"

        # 存入 messages 表，用 lastrowid 作为关联 ID
        _notify_progress("正在写入数据库...")
        msg_id = None
        if _current_conversation_id and _db_path_ref:
            conn = None
            try:
                conn = sqlite3.connect(_db_path_ref, timeout=30)
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA busy_timeout=30000")
                cursor = conn.execute(
                    "INSERT INTO messages (conversation_id, role, content, timestamp, importance, memory_type) VALUES (?, ?, ?, ?, ?, ?)",
                    (_current_conversation_id, "memory", content, current_timestamp, importance, type)
                )
                conn.commit()
                msg_id = cursor.lastrowid
            finally:
                if conn:
                    conn.close()

        # 存入向量索引（用 messages 表的自增 ID 作为关联）
        _notify_progress("正在更新向量索引...")
        if _vector_store_ref and msg_id is not None:
            embed_text = _extract_embed_text(content)
            _vector_store_ref.add(message_id=msg_id, text=embed_text)

        elapsed = round(time.monotonic() - t0, 2)
        label = {"fact": "事实记忆", "episodic": "事件记忆", "dance": "舞蹈动作记忆"}.get(type, "记忆")
        return f"已保存{label}: {content[:50]}... (耗时 {elapsed}s)"

    except Exception as e:
        elapsed = round(time.monotonic() - t0, 2)
        return f"保存出错: {e} (耗时 {elapsed}s)"


@tool
def search_memory(query: str, scope: str = "memory", memory_type: str = None, days: int = None) -> str:
    """深度搜索历史记忆，找回上下文中没有的细节。

    系统已自动为你注入了 top 3 相关记忆到上下文中（标记为 [相关记忆]），**但不包含舞蹈类记忆（dance）**，防止 token 浪费。
    以下情况需要你主动调用本工具深入搜索：
    - 上下文中的 [相关记忆] 不够用，需要更多记忆
    - 用户明确提到"之前""上次""记得"，需要精准回溯
    - 需要按类型过滤（只搜事实/只搜事件/只搜舞蹈动作）
    - 需要按时间过滤（最近 7 天）
    - 搜索当前会话的原始对话（scope="session"）

    参数选择：
    - scope="session": 回溯本轮对话细节，确认用户刚说过什么。5 条结果。
    - scope="memory":（默认）搜索跨会话记忆，用语义+关键词混合检索。
      - memory_type=None: 不限类型，搜全部记忆
      - memory_type="fact": 只搜事实记忆（用户偏好、技术决定、知识性信息）
      - memory_type="episodic": 只搜事件记忆（操作结果、问题解决方案、时间相关事件）
      - memory_type="dance": 只搜舞蹈动作记忆（编舞数据、动作序列、姿态信息）
    - days=7: 只返回过去 7 天内的结果

    Args:
        query: 搜索内容。优先用完整句子（如"用户之前提到的实习安排"），保留语义信息搜索更准。
        scope: "memory"（默认）搜跨会话记忆，"session" 搜当前会话原始对话。
        memory_type: 记忆类型过滤，仅 scope="memory" 时生效。"fact"/"episodic"/"dance"，不传则全部。
        days: 时间过滤，只返回过去 N 天内的结果。
    """
    # 容错：清理 scope 参数中的引号和空格
    scope = scope.strip().strip("'\"")
    try:
        if scope == "session":
            # 只搜当前会话的原始对话 — 关键词检索，不做权重排序
            _notify_progress("正在搜索当前会话...")
            results = _fts_search(query, conversation_id=_current_conversation_id, days=days)
            results = [r for r in results if r.get("role") != "memory"][:5]
        elif scope == "memory":
            # 搜跨会话记忆：messages FTS5 关键词 + 向量语义 → RRF 融合
            _notify_progress("正在搜索关键词...")
            fts_results = _fts_search(query, days=days, msg_type="memory", memory_type=memory_type)
            _notify_progress("正在语义搜索...")
            vec_results = _vector_search(query, days=days, msg_type="memory", memory_type=memory_type)
            _notify_progress("正在融合排序...")
            merged = _rrf_merge(fts_results, vec_results, top_n=12)
            _notify_progress("正在综合排序...")
            results = _rerank_memories(merged, top_k=5)
        else:
            return f"无效的 scope '{scope}'，只能是 'memory' 或 'session'"

        if not results:
            return "未找到相关消息"

        # 更新 last_access_at（只更新记忆）
        if results and _db_path_ref:
            current_timestamp = int(time.time() * 1000)
            conn = None
            try:
                conn = sqlite3.connect(_db_path_ref, timeout=30)
                conn.execute("PRAGMA busy_timeout=5000")
                for msg in results:
                    if msg.get("id") and msg.get("role") == "memory":
                        conn.execute(
                            "UPDATE messages SET last_access_at = ? WHERE id = ?",
                            (current_timestamp, msg["id"])
                        )
                conn.commit()
            except Exception:
                pass
            finally:
                if conn:
                    conn.close()

        lines = []
        for msg in results:
            role_label = {"user": "用户", "assistant": "AI", "memory": "记忆"}.get(msg.get("role", ""), msg.get("role", ""))
            session_tag = f" [会话:{msg.get('conversation_id','')[:8]}]" if msg.get("conversation_id") else ""
            lines.append(f"[{role_label}]{session_tag} {msg['content']}")
        return "\n---\n".join(lines)
    except Exception as e:
        return f"搜索出错: {e}"


# ── 后台任务派发 ──────────────────────────────────────────────
# 当主Agent调用delegate_task时，请求被暂存到此队列
# agent_langchain.py 的 run_conversation 会在流结束后读取并启动后台执行器
_pending_background_tasks: list[dict] = []

def consume_pending_tasks() -> list[dict]:
    """消费并返回所有待处理的后台任务"""
    global _pending_background_tasks
    tasks = _pending_background_tasks.copy()
    _pending_background_tasks.clear()
    return tasks


@tool
def delegate_task(description: str, tasks_json: str = "") -> str:
    """
    派发任务给子Agent在后台异步执行。不影响当前对话 — 调用后立即返回。

    一旦判断需要派发给子Agent，不要自己做任何准备工作（查包名、启动应用等），
    直接把整个任务全盘委托，子Agent会从头开始自己处理。

    ⚠️ 必须先分解任务再派发：tasks_json 中的 steps 必须按原子粒度分解，
    每个步骤是单步操作（如"打开拼多多APP"），禁止合并（如"去拼多多买件衣服"）。
    不分解会导致子Agent无法执行。

    ⚠️ 任务目标必须清晰，必须包含明确的终止条件和注意事项：
    - objective 要写清楚"做什么"和"做到什么程度算完成"
    - 最后一个步骤应该是"汇报完成情况"或"保存结果"，确保任务有明确收尾
    - 如果有注意事项（如"不要倍速""必须保存到笔记"），写在 guidance 字段中

    ⚠️ steps 中每个步骤必须包含 status 字段，初始化为 "pending"：
    - 子Agent每完成一步会把对应 status 改为 "completed"
    - 所有步骤都 completed 后才能标记整体任务完成

    Args:
        description: 自然语言描述任务目标和内容
        tasks_json: (必填) 按原子粒度分解后的任务定义。
                    包含 objective、steps（每个step必须有id、desc、status）、可选 guidance。
                    例如：{"objective": "在拼多多搜索树莓派并咨询客服", "steps": [{"id": 1, "desc": "打开拼多多APP", "status": "pending"}, {"id": 2, "desc": "搜索树莓派", "status": "pending"}, {"id": 3, "desc": "咨询客服", "status": "pending"}, {"id": 4, "desc": "汇报结果", "status": "pending"}], "guidance": "必须在拼多多内操作"}
                    不提供时整段描述作为单个步骤，子Agent可能无法正确执行。
    """
    from datetime import datetime
    from agent.config import TASKS_DIR

    if not description or not description.strip():
        return "❌ delegate_task 调用失败：description 参数不能为空。请提供任务描述后再调用。"

    global _pending_background_tasks

    task_id = f"task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    task_dir = os.path.join(TASKS_DIR, task_id)
    task_file = os.path.join(task_dir, "task.json")

    os.makedirs(task_dir, exist_ok=True)

    if tasks_json:
        try:
            task_data = json.loads(tasks_json)
        except json.JSONDecodeError:
            task_data = {}
    else:
        task_data = {}

    task_data.setdefault("objective", description)
    task_data.setdefault("all_completed", False)
    # 主Agent必须传 tasks_json 分解步骤，不传时整段描述作为单个步骤
    if "steps" not in task_data or not task_data["steps"]:
        task_data["steps"] = [{"id": 1, "desc": description[:200], "status": "pending"}]
    # 兜底：确保每个 step 都有 status 字段
    for step in task_data["steps"]:
        step.setdefault("status", "pending")

    with open(task_file, "w", encoding="utf-8") as f:
        json.dump(task_data, f, ensure_ascii=False, indent=2)

    _pending_background_tasks.append({
        "task_id": task_id,
        "task_path": task_file,
        "description": description,
        "subagent_type": "executor",
    })
    return (
        f"✅ 任务已派发到后台执行 (task_id: {task_id})。"
        f"子Agent完成后会自动沉淀技能。"
        f"任务进度可通过 file_read 查看 {task_file}"
    )


# 导入身体控制工具
try:
    from .body_control_tool import control_body, move_body, body_script, body_idle
    BODY_TOOLS = [control_body, move_body, body_script, body_idle]
except Exception:
    BODY_TOOLS = []

ALL_TOOLS = [
    file_read, file_write, file_search, directory_list, system_info, shell_exec, update_user_profile, mcp_call, delegate_task, tts_speak, save_memory, search_memory
] + BODY_TOOLS
