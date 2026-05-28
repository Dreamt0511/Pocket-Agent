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
MAX_ITERATIONS = 300

# LangGraph底层递归限制（兜底防护，建议设置为MAX_ITERATIONS的2倍）
RECURSION_LIMIT = 600

# ==============================
# 上下文窗口配置
# ==============================
# 云端API模型的上下文窗口大小（如DeepSeek、Qwen等均为128K）
MAX_CONTEXT_TOKENS = 128000

# ==============================
# 技能系统配置
# ==============================
# 主Agent技能目录
SKILLS_DIR = os.path.join(PROJECT_ROOT, "agent", "skills", "main-skills")

# 技能文件名称（支持大小写）
SKILL_FILE_NAMES = ["SKILL.md", "skill.md"]

# 主Agent LLM 默认参数（会被 .env 覆盖）
LLM_DEFAULT_CONFIG = {
    "temperature": 0.7,
    "max_tokens": 8000,
}

# 子Agent（Executor）LLM 配置
# 从 .env 中读取 EXECUTOR_LLM_BASE_URL、EXECUTOR_API_KEY、EXECUTOR_MODEL、
# EXECUTOR_TEMPERATURE、EXECUTOR_MAX_TOKENS
# 未设置的字段自动继承主Agent的对应值（共用同一模型）
EXECUTOR_LLM_CONFIG = {
    "base_url": os.getenv("EXECUTOR_LLM_BASE_URL"),
    "api_key": os.getenv("EXECUTOR_API_KEY"),
    "model": os.getenv("EXECUTOR_MODEL"),
    "temperature": os.getenv("EXECUTOR_TEMPERATURE"),
    "max_tokens": os.getenv("EXECUTOR_MAX_TOKENS"),
}

# ==============================
# 子Agent系统配置
# ==============================
# 子Agent技能目录
EXECUTOR_SKILLS_DIR = os.path.join(PROJECT_ROOT, "agent", "skills", "executor-skills")

# 自动沉淀技能目录
AUTO_SKILLS_DIR = os.path.join(PROJECT_ROOT, "agent", "skills", "auto-skills")

# 任务文件存储目录
TASKS_DIR = os.path.join(PROJECT_ROOT, "tasks")

# ==============================
# Embedding 配置
# ==============================
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL", "")
EMBEDDING_API_KEY = os.getenv("EMBEDDING_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "bge-m3")
EMBEDDING_SERVER_URL = os.getenv("EMBEDDING_SERVER_URL", "http://127.0.0.1:8080/v1")
EMBEDDING_MODEL_PATH = os.getenv("EMBEDDING_MODEL_PATH", "")

# ==============================
# 日志配置
# ==============================
# 日志目录
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

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
