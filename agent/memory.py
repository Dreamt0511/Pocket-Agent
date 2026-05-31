#!/usr/bin/env python3
"""
用户画像管理
保留 user_profile.md 供用户手动编辑，对话历史由 SQLite 存储
"""

from pathlib import Path


class LongTermMemory:
    """用户画像管理（对话记忆由 SQLite messages 表承担）"""

    def __init__(self, memory_dir: str):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(exist_ok=True)
        self.profile_file = self.memory_dir / "user_profile.md"
        self._init_user_profile()

    def _init_user_profile(self):
        if not self.profile_file.exists():
            default_profile = """# 用户画像

## 基本信息

## 沟通偏好

## 行为要求

## 反馈

## 其他
"""
            self.profile_file.write_text(default_profile, encoding='utf-8')

    def get_user_profile(self) -> str:
        if not self.profile_file.exists():
            return "用户画像未定义"
        return self.profile_file.read_text(encoding='utf-8')

    def update_user_profile(self, section: str, content: str):
        profile = self.get_user_profile()
        lines = profile.split('\n')
        updated_lines = []
        in_section = False
        section_found = False

        for line in lines:
            if line.startswith(f"## {section}"):
                in_section = True
                section_found = True
                updated_lines.append(line)
                updated_lines.append(content)
            elif line.startswith("## ") and in_section:
                in_section = False
                updated_lines.append(line)
            elif not in_section:
                updated_lines.append(line)

        if not section_found:
            updated_lines.append(f"\n## {section}")
            updated_lines.append(content)

        self.profile_file.write_text('\n'.join(updated_lines), encoding='utf-8')
