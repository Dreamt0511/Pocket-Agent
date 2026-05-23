#!/usr/bin/env python3
"""
长期记忆系统
使用 Markdown 文件实现每天一个记忆文件
"""

import os
import json
import datetime
from typing import Dict, List, Optional
from pathlib import Path


class LongTermMemory:
    """
    长期记忆管理系统
    每天生成一个 Markdown 记忆文件
    """
    
    def __init__(self, memory_dir: str):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(exist_ok=True)
        
        # 使用今天的日期作为文件名
        today = datetime.datetime.now().strftime("%Y-%m-%d")
        self.today_file = self.memory_dir / f"{today}.md"
        
        # 用户画像文件
        self.profile_file = self.memory_dir / "user_profile.md"
        
        # 初始化用户画像
        self._init_user_profile()
    
    def _init_user_profile(self):
        """
        初始化用户画像文件
        """
        if not self.profile_file.exists():
            default_profile = """# 用户画像

## 基本信息
- **姓名**: 未知
- **职业**: 未知
- **兴趣**: 未知

## 偏好设置
- 喜欢的风格: 简洁、明确
- 话题偏好: 技术、生活、学习

## 特殊要求
- 回答要求: 准确、有用
- 避免内容: 原则性问题
"""
            with open(self.profile_file, 'w', encoding='utf-8') as f:
                f.write(default_profile)
    
    def add_memory(self, content: str, category: str = "对话", 
                  importance: int = 1, tags: List[str] = None):
        """
        添加新的记忆
        
        Args:
            content: 记忆内容
            category: 分类 (对话、任务、学习等)
            importance: 重要性 (1-5)
            tags: 标签列表
        """
        if tags is None:
            tags = []
        
        # 获取当前时间
        now = datetime.datetime.now()
        timestamp = now.strftime("%H:%M:%S")
        
        # 格式化记忆条目
        memory_entry = f"\n## {timestamp} - {category} ⭐{importance}\n\n"
        
        # 添加标签
        if tags:
            memory_entry += f"**标签**: {', '.join(tags)}\n\n"
        
        # 添加内容
        memory_entry += f"{content}\n"
        
        # 写入今天的记忆文件
        with open(self.today_file, 'a', encoding='utf-8') as f:
            f.write(memory_entry)
    
    def get_today_memory(self) -> str:
        """
        获取今天的记忆
        """
        if not self.today_file.exists():
            return "今天还没有记忆"
        
        with open(self.today_file, 'r', encoding='utf-8') as f:
            return f.read()
    
    def get_user_profile(self) -> str:
        """
        获取用户画像
        """
        if not self.profile_file.exists():
            return "用户画像未定义"
        
        with open(self.profile_file, 'r', encoding='utf-8') as f:
            return f.read()
    
    def update_user_profile(self, section: str, content: str):
        """
        更新用户画像
        
        Args:
            section: 要更新的部分
            content: 新内容
        """
        # 读取当前画像
        profile = self.get_user_profile()
        
        # 简单的更新逻辑，实际中可以使用更复杂的 Markdown 解析
        lines = profile.split('\n')
        updated_lines = []
        in_section = False
        
        for line in lines:
            if line.startswith(f"## {section}"):
                in_section = True
                updated_lines.append(line)
                updated_lines.append(content)
            elif line.startswith("## ") and in_section:
                in_section = False
                updated_lines.append(line)
            elif not in_section:
                updated_lines.append(line)
        
        # 写入更新后的画像
        with open(self.profile_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(updated_lines))
    
    def search_memory(self, keyword: str, days: int = 7) -> List[str]:
        """
        搜索记忆
        
        Args:
            keyword: 搜索关键词
            days: 搜索天数
        
        Returns:
            匹配的记忆列表
        """
        matches = []
        
        # 获取最近的文件
        today = datetime.datetime.now()
        
        for i in range(days):
            date = today - datetime.timedelta(days=i)
            file_path = self.memory_dir / f"{date.strftime('%Y-%m-%d')}.md"
            
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                if keyword.lower() in content.lower():
                    # 找到匹配的行
                    lines = content.split('\n')
                    for line in lines:
                        if keyword.lower() in line.lower():
                            matches.append(f"{date.strftime('%Y-%m-%d')}: {line.strip()}")
        
        return matches
    
    def get_recent_memories(self, days: int = 3) -> str:
        """
        获取最近几天的记忆
        """
        result = []
        today = datetime.datetime.now()
        
        for i in range(days):
            date = today - datetime.timedelta(days=i)
            file_path = self.memory_dir / f"{date.strftime('%Y-%m-%d')}.md"
            
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if content.strip():
                    result.append(f"\n\n=== {date.strftime('%Y-%m-%d')} ===\n{content}")
        
        return "\n".join(result) if result else "近期没有明显记忆"