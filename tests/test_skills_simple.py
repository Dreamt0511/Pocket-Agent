import os
import sys
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from agent.agent_langchain import find_skills

print("Testing skill discovery...")
result = find_skills()
print(result)
