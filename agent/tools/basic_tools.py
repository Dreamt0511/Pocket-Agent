#!/usr/bin/env python3
"""
轻量级工具集合
"""

import json
import os
import re
import subprocess
from typing import Dict, List, Optional
from langchain_core.tools import tool


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

@tool
def update_user_profile(section: str, content: str) -> str:
    """
    【重要】更新用户画像，仅用于记录用户明确提到的重要个人信息、偏好和特殊要求。
    禁止随意更新，只有当用户明确提到以下信息时才能使用：
    - 基本信息：姓名、职业、兴趣爱好等
    - 偏好设置：喜欢的回答风格、关注的话题领域等
    - 特殊要求：对回答的特殊要求、需要避免的内容等

    Args:
        section: 要更新的部分，必须是现有画像中的章节（基本信息/偏好设置/特殊要求）
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
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, _memory_instance.update_user_profile, section, content)
        return f"✅ 已异步更新用户画像 [{section}]"
    except Exception as e:
        return f"❌ 更新用户画像失败: {str(e)}"


# 所有工具函数
ALL_TOOLS = [
    file_read, file_write, file_search, directory_list, system_info, shell_exec, update_user_profile
]