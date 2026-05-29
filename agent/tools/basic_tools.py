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

        if info_type in ["all", "network"]:
            result.append("📶 WiFi信息:")
            result.append(_run_termux_cmd("termux-wifi-connectioninfo"))
            result.append("")

        if info_type in ["all", "device"]:
            result.append("🔧 设备信息:")
            result.append(_run_termux_cmd("termux-telephony-deviceinfo"))
            result.append("")

        if info_type in ["all", "wifi"]:
            result.append("📶 WiFi信息:")
            result.append(_run_termux_cmd("termux-wifi-connectioninfo"))
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

def _fts_search(query: str, conversation_id: str = None, days: int = None, msg_type: str = None) -> list:
    """FTS5 全文搜索 + LIKE 搜索混合（trigram 对短中文词支持差，用 LIKE 补充）"""
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

        where_extra = (" AND " + " AND ".join(conditions)) if conditions else ""

        # 将查询拆分为关键词，分别用 FTS 和 LIKE 搜索
        keywords = query.split()
        if not keywords:
            keywords = [query]

        # 策略1: FTS trigram 搜索（>=3字符的关键词）
        # 策略2: LIKE 搜索（所有关键词，作为补充）
        seen_ids = set()
        results = []

        # LIKE 搜索（能覆盖所有中文关键词）
        like_conditions = [f"m.content LIKE ?" for _ in keywords]
        like_params = [f"%{k}%" for k in keywords]
        like_clause = " OR ".join(like_conditions)
        rows = conn.execute(
            f"""SELECT m.id, m.conversation_id, m.role, m.content, m.importance, m.last_access_at, m.timestamp
                FROM messages m WHERE ({like_clause}){where_extra}
                ORDER BY m.timestamp DESC LIMIT 20""",
            like_params + params
        ).fetchall()
        for r in rows:
            if r[0] not in seen_ids:
                seen_ids.add(r[0])
                results.append({"id": r[0], "conversation_id": r[1], "role": r[2], "content": r[3], "importance": r[4], "last_access_at": r[5], "timestamp": r[6]})

        # FTS 搜索（>=3字符的关键词，提高排序精度）
        long_keywords = [k for k in keywords if len(k) >= 3]
        if long_keywords:
            try:
                fts_query = " OR ".join(long_keywords)
                fts_rows = conn.execute(
                    f"""SELECT m.id, m.conversation_id, m.role, m.content, m.importance, m.last_access_at, m.timestamp
                        FROM messages_fts fts JOIN messages m ON fts.rowid = m.id
                        WHERE fts MATCH ?{where_extra}
                        ORDER BY rank LIMIT 20""",
                    [fts_query] + params
                ).fetchall()
                for r in fts_rows:
                    if r[0] not in seen_ids:
                        seen_ids.add(r[0])
                        results.append({"id": r[0], "conversation_id": r[1], "role": r[2], "content": r[3], "importance": r[4], "last_access_at": r[5], "timestamp": r[6]})
            except Exception:
                pass  # FTS 搜索失败不影响 LIKE 结果

        return results
    except Exception:
        return []
    finally:
        if conn:
            conn.close()

def _vector_search(query: str, conversation_id: str = None, days: int = None, msg_type: str = None) -> list:
    """向量语义搜索（直接查询，避免 HTTP 自调用死锁）"""
    if not _vector_store_ref:
        return []
    try:
        where = {}
        if conversation_id:
            where["conversation_id"] = conversation_id
        if msg_type:
            where["role"] = msg_type

        results = _vector_store_ref.query(query, n_results=20, where=where if where else None)

        # 应用时间过滤
        if days:
            cutoff_time = int((time.time() - days * 86400) * 1000)
            results = [r for r in results if r.get("metadata", {}).get("timestamp", 0) > cutoff_time]

        return [{
            "id": r.get("id", ""),
            "role": r.get("metadata", {}).get("role", ""),
            "content": r.get("document", ""),
            "conversation_id": r.get("metadata", {}).get("conversation_id", ""),
            "importance": r.get("metadata", {}).get("importance", 3),
            "last_access_at": r.get("metadata", {}).get("last_access_at", 0),
            "similarity": 1 - r.get("distance", 0),
        } for r in results]
    except Exception:
        return []

def _rrf_merge(fts_results: list, vec_results: list, k: int = 60, alpha: float = 0.45, beta: float = 0.25, gamma: float = 0.3) -> list:
    """综合排序：RRF + 时间衰减 + 重要性
    参考 EchoMind 设计：语义相关性(0.45) > 重要性(0.3) > 时间衰减(0.25)
    """
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

        # 时间衰减：使用 last_access_at（最近访问时间）
        # 被频繁访问的记忆保持优先级，符合"常用记忆更容易被检索"的逻辑
        last_access = msg.get("last_access_at", current_time)
        if last_access == 0:
            last_access = current_time
        hours_passed = (current_time - last_access) / 3600000  # 转换为小时
        recency_score = DECAY_RATE ** hours_passed

        # 重要性
        importance_score = msg.get("importance", 3) / 10  # 归一化到 0-1

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


@tool
async def update_user_profile(section: str, content: str) -> str:
    """
    记录用户明确提到的个人偏好、习惯、要求等信息到用户画像中。

    触发条件（用户提到以下信息时务必调用）：
    - 基本信息：姓名、职业、兴趣爱好等
    - 偏好设置：喜欢的风格、关注话题、饮食偏好、生活习惯等
    - 特殊要求：回答要求、需避免的内容等

    Args:
        section: 要更新的部分（基本信息/偏好设置/特殊要求）
        content: 新的内容，完整替换该章节下的所有内容
    """
    if not _memory_instance:
        return "❌ 记忆系统未初始化，无法更新用户画像"

    valid_sections = ["基本信息", "偏好设置", "特殊要求"]
    if section not in valid_sections:
        return f"❌ 无效的章节 '{section}'，只能更新: {', '.join(valid_sections)}"

    try:
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
        type: "fact" 存入向量数据库（跨会话），"episodic" 同时存入消息表和向量数据库（带会话上下文）。两者都支持语义搜索和关键词搜索。
        importance: 重要性 1-10，自行判断打分。大多数记忆应在 3-5 分，只有真正影响后续决策的才值得 7 分以上。

        打分参考（仅供大致参考，不必死板遵守）：
        - 1-2: 临时性信息，很快就会过时
        - 3-4: 一般有用，比如用户的某个偏好、一次普通操作的结果
        - 5-6: 比较重要，比如项目架构决定、关键技术选型
        - 7-8: 很重要，比如影响后续多次决策的结论、重大问题的根因
        - 9-10: 极其重要，比如用户明确强调的关键需求、不可逆的重大决定

        注意：不要每条都打高分，大部分记忆 3-5 分即可。高分要留给真正值得反复回忆的内容。
    """
    try:
        t0 = time.monotonic()
        current_timestamp = int(time.time() * 1000)

        if type == "fact":
            # 存入 messages 表
            if _current_conversation_id and _db_path_ref:
                conn = None
                try:
                    conn = sqlite3.connect(_db_path_ref, timeout=30)
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA busy_timeout=30000")
                    conn.execute(
                        "INSERT INTO messages (conversation_id, role, content, timestamp, importance) VALUES (?, ?, ?, ?, ?)",
                        (_current_conversation_id, "memory", content, current_timestamp, importance)
                    )
                    conn.commit()
                finally:
                    if conn:
                        conn.close()
            # 存入向量数据库（包含 timestamp 用于时间过滤）
            if _vector_store_ref:
                _vector_store_ref.add(
                    message_id=hash(content) % (2**31),
                    content=content,
                    metadata={"importance": importance, "type": "fact", "timestamp": current_timestamp}
                )
            elapsed = round(time.monotonic() - t0, 2)
            return f"已保存事实记忆: {content[:50]}... (耗时 {elapsed}s)"

        elif type == "episodic":
            if not _current_conversation_id:
                return "保存失败: episodic 类型需要 conversation_id"
            if _db_path_ref:
                conn = None
                try:
                    conn = sqlite3.connect(_db_path_ref, timeout=30)
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA busy_timeout=30000")
                    conn.execute(
                        "INSERT INTO messages (conversation_id, role, content, timestamp, importance) VALUES (?, ?, ?, ?, ?)",
                        (_current_conversation_id, "memory", content, current_timestamp, importance)
                    )
                    conn.commit()
                finally:
                    if conn:
                        conn.close()
            # 存入向量数据库（包含 timestamp 用于时间过滤）
            if _vector_store_ref:
                _vector_store_ref.add(
                    message_id=hash(content) % (2**31),
                    content=content,
                    metadata={"importance": importance, "type": "episodic", "conversation_id": _current_conversation_id, "timestamp": current_timestamp}
                )
            elapsed = round(time.monotonic() - t0, 2)
            return f"已保存事件记忆: {content[:50]}... (耗时 {elapsed}s)"

        else:
            return "type 必须是 'fact' 或 'episodic'"
    except Exception as e:
        elapsed = round(time.monotonic() - t0, 2)
        return f"保存出错: {e} (耗时 {elapsed}s)"


@tool
def search_memory(query: str, scope: str = "all", days: int = None, msg_type: str = None) -> str:
    """搜索历史消息和跨会话记忆，找回遗忘的细节。当你不确定某个信息、需要回忆之前的对话内容、或想查找用户之前提到过的决定/偏好时，应该调用此工具。

    Args:
        query: 搜索关键词或短语，尽量具体（比如 "SQLite 配置" 而不是 "数据库"）
        scope: 搜索范围
               - "all"（默认）: 搜索全部——当前会话记录 + 跨会话的事实记忆和事件记忆，混合排序返回最相关的结果
               - "session": 只搜索当前会话的对话记录，适合回溯本轮对话中提到过的细节,当你的上下文中有内容时无需检索此项
        days: 时间过滤，只返回过去 N 天内的消息（如 days=7 表示过去 7 天）
        msg_type: 消息类型过滤
                  - "user": 只搜用户消息
                  - "assistant": 只搜 AI 回复
                  - "memory": 只搜记忆
    """
    try:
        fts_results = []
        vec_results = []

        if scope == "session":
            # 只搜当前会话
            fts_results = _fts_search(query, conversation_id=_current_conversation_id, days=days, msg_type=msg_type)
        else:
            # "all" — 当前会话 + 跨会话记忆
            fts_results = _fts_search(query, days=days, msg_type=msg_type)
            vec_results = _vector_search(query, days=days, msg_type=msg_type)

        # 综合排序
        if fts_results and vec_results:
            results = _rrf_merge(fts_results, vec_results)
        elif vec_results:
            results = vec_results[:5]
        else:
            results = fts_results[:5]

        if not results:
            return "未找到相关消息"

        # 更新 last_access_at
        if results and _db_path_ref:
            current_timestamp = int(time.time() * 1000)
            conn = None
            try:
                conn = sqlite3.connect(_db_path_ref, timeout=30)
                conn.execute("PRAGMA busy_timeout=5000")
                for msg in results:
                    if msg.get("id"):
                        conn.execute(
                            "UPDATE messages SET last_access_at = ? WHERE id = ?",
                            (current_timestamp, msg["id"])
                        )
                conn.commit()
            except Exception:
                pass  # 更新失败不影响返回结果
            finally:
                if conn:
                    conn.close()

        lines = []
        for msg in results:  # _rrf_merge 已返回 5 条，无需再切片
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

    Args:
        description: 自然语言描述任务目标和内容
        tasks_json: (必填) 按原子粒度分解后的任务定义。
                    包含 objective 和 steps（steps 每个元素是单步操作）。
                    例如：{"objective": "打开拼多多买衣服", "steps": [{"id": 1, "desc": "打开拼多多APP"}, {"id": 2, "desc": "搜索黑色鞋子"}, {"id": 3, "desc": "筛选价格100左右"}]}
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
    task_data.setdefault("status", "pending")
    # 主Agent必须传 tasks_json 分解步骤，不传时整段描述作为单个步骤
    if "steps" not in task_data or not task_data["steps"]:
        task_data["steps"] = [{"id": 1, "desc": description[:200], "status": "pending"}]

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


ALL_TOOLS = [
    file_read, file_write, file_search, directory_list, system_info, shell_exec, update_user_profile, mcp_call, delegate_task, tts_speak, save_memory, search_memory
]
