#!/usr/bin/env python3
"""
Pocket-Agent 公共配置文件
存放非隐私的通用配置，隐私配置（API密钥、URL等）请在.env文件中设置
"""
import os

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ==============================
# Agent 运行配置
# ==============================
# Agent最大迭代次数：最多支持多少轮工具调用
MAX_ITERATIONS = 100

# LangGraph底层递归限制（兜底防护，建议设置为MAX_ITERATIONS的2倍）
RECURSION_LIMIT = 200

# ==============================
# 上下文窗口配置
# ==============================
# 云端API模型的上下文窗口大小（如DeepSeek、Qwen等均为128K）
MAX_CONTEXT_TOKENS = 128000

# ==============================
# 技能系统配置
# ==============================
# 技能目录路径
SKILLS_DIR = os.path.join(PROJECT_ROOT, "agent", "skills")

# 技能文件名称（支持大小写）
SKILL_FILE_NAMES = ["SKILL.md", "skill.md"]

# ==============================
# 提示词配置
# ==============================
# 提示词目录路径
PROMPTS_DIR = os.path.join(PROJECT_ROOT, "agent", "prompts")

# 提示词以Python模块形式存在于该目录下，直接导入使用
# 导入方式：from agent.prompts.xxx import prompt

# ==============================
# Termux API 配置
# ==============================
# Termux API检测命令
TERMUX_API_CHECK_CMD = "which termux-battery-status"

# Termux API安装提示
TERMUX_API_INSTALL_GUIDE = """❌ 未安装Termux API，请先执行：
1. pkg install termux-api
2. 在手机应用商店安装 Termux:API 应用
3. 授予Termux相应权限
"""

# 环境传感器采样命令（用于环境状态感知）
ENV_LIGHT_SENSOR_CMD = 'termux-sensor -s "tcs3760 Ambient Light Sensor Non-wakeup" -n 1'
ENV_ACCEL_SENSOR_CMD = 'termux-sensor -s "lsm6dsv Accelerometer Non-wakeup" -n 3'
ENV_TIME_CMD = 'date +"%H:%M"'
ENV_TIMEZONE_CMD = 'getprop persist.sys.timezone'
