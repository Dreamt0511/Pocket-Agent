#!/usr/bin/env python3
"""
测试目录重构是否成功
"""
import sys
import os

# 测试导入
print("Testing imports...")
try:
    from agent.agent_langchain import LangChainPocketAgent
    print("✅ agent.agent_langchain 导入成功")

    # 测试工具加载
    from agent.agent_langchain import list_skills, load_skill
    print("✅ 工具函数导入成功")

    # 测试技能路径是否正确
    skills = list_skills()
    print(f"✅ 技能列表加载成功，共发现 {len(skills.splitlines())-1} 个技能")

    print("\n🎉 目录重构成功！所有路径都已正确更新。")

except Exception as e:
    print(f"❌ 导入失败: {e}")
    import traceback
    traceback.print_exc()
