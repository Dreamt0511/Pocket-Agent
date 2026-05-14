#!/usr/bin/env python3
"""
轻量级工具集合
"""

import json
import os
import re
from typing import Dict, List, Optional
from ..agent import tool


@tool(
    name="file_read",
    description="读取文件内容",
    parameters={
        "type": "object",
        "properties": {
            "filepath": {"type": "string", "description": "文件路径"},
            "max_lines": {"type": "integer", "description": "最大行数", "default": 100}
        },
        "required": ["filepath"]
    }
)
def file_read(filepath: str, max_lines: int = 100) -> str:
    """读取文件内容"""
    try:
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


@tool(
    name="file_write",
    description="写入文件内容",
    parameters={
        "type": "object",
        "properties": {
            "filepath": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的内容"},
            "append": {"type": "boolean", "description": "是否追加模式", "default": False}
        },
        "required": ["filepath", "content"]
    }
)
def file_write(filepath: str, content: str, append: bool = False) -> str:
    """写入文件"""
    try:
        mode = 'a' if append else 'w'
        with open(filepath, mode, encoding='utf-8') as f:
            f.write(content)
        
        action = "追加" if append else "写入"
        return f"文件{action}成功: {filepath}"
    except Exception as e:
        return f"写入文件错误: {str(e)}"


@tool(
    name="file_search",
    description="搜索文件内容",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "正则表达式模式"},
            "filepath": {"type": "string", "description": "要搜索的文件"},
            "context_lines": {"type": "integer", "description": "上下文行数", "default": 2}
        },
        "required": ["pattern", "filepath"]
    }
)
def file_search(pattern: str, filepath: str, context_lines: int = 2) -> str:
    """在文件中搜索内容"""
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


@tool(
    name="directory_list",
    description="列出目录内容",
    parameters={
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "目录路径"},
            "pattern": {"type": "string", "description": "文件名筛选模式", "default": "*"}
        },
        "required": ["directory"]
    }
)
def directory_list(directory: str, pattern: str = "*") -> str:
    """列出目录内容"""
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


@tool(
    name="json_read",
    description="读取JSON文件",
    parameters={
        "type": "object",
        "properties": {
            "filepath": {"type": "string", "description": "JSON文件路径"},
            "path": {"type": "string", "description": "JSON路径（选择性）"}
        },
        "required": ["filepath"]
    }
)
def json_read(filepath: str, path: Optional[str] = None) -> str:
    """读取JSON文件"""
    try:
        if not os.path.exists(filepath):
            return f"JSON文件不存在: {filepath}"
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if path:
            # 简单的路径支持，例如 "user.name"
            keys = path.split('.')
            for key in keys:
                if isinstance(data, dict) and key in data:
                    data = data[key]
                else:
                    return f"JSON路径 '{path}' 不存在"
        
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as e:
        return f"读取JSON错误: {str(e)}"


@tool(
    name="system_info",
    description="获取系统信息",
    parameters={
        "type": "object",
        "properties": {
            "info_type": {
                "type": "string", 
                "description": "信息类型",
                "enum": ["disk", "memory", "cpu", "network"],
                "default": "disk"
            }
        }
    }
)
def system_info(info_type: str = "disk") -> str:
    """获取系统信息"""
    try:
        if info_type == "disk":
            stat = os.statvfs("/")
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bavail * stat.f_frsize
            used = total - free
            
            return (f"磁盘信息:\n"
                   f"总空间: {total // (1024**3)} GB\n"
                   f"已使用: {used // (1024**3)} GB\n"
                   f"可用: {free // (1024**3)} GB")
        
        elif info_type == "memory":
            # 简单的内存信息（实际中可以使用 psutil）
            return "内存信息: 请安装 psutil 获取更详细信息"
        
        else:
            return f"系统信息 '{info_type}': 暂时不支持"
    
    except Exception as e:
        return f"获取系统信息错误: {str(e)}"


@tool(
    name="shell_exec",
    description="执行shell命令，返回命令输出，仅可执行安全的非高危命令",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的shell命令"}
        },
        "required": ["command"]
    }
)
def shell_exec(command: str) -> str:
    """执行shell命令"""
    import subprocess
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
            return f"命令执行失败 (错误码 {result.returncode}):\n{error}"
        return output if output else "命令执行成功，无输出"
    except subprocess.TimeoutExpired:
        return "命令执行超时"
    except Exception as e:
        return f"执行命令错误: {str(e)}"


# 所有工具函数
ALL_TOOLS = [
    file_read, file_write, file_search, directory_list,
    json_read, system_info, shell_exec
]