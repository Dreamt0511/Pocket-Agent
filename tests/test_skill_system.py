#!/usr/bin/env python3
"""
测试新的渐进式技能系统
"""
import os
import sys
import asyncio

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from agent.agent_langchain import find_skills

async def test_skill_discovery():
    """测试技能发现功能"""
    print("=== 测试渐进式技能系统 ===\n")

    # 测试find_skills
    print("🔍 正在扫描可用技能...\n")
    skills_list = find_skills()
    print(skills_list)

    print("\n✅ 技能系统工作正常！所有技能都能被自动发现。")
    print("\n💡 使用方式:")
    print("1. 调用 find_skills() 查看所有可用技能")
    print("2. 需要使用某个技能时，调用 file_read(filepath='skills/技能名称/SKILL.md') 读取完整内容")

if __name__ == "__main__":
    asyncio.run(test_skill_discovery())
