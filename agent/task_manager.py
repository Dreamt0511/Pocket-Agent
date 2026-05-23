#!/usr/bin/env python3
"""
任务文件系统管理
提供任务文件的创建、读取、更新操作
主Agent通过 file_read/file_write 直接操作，本模块作为服务端辅助
"""

import os
import json
import uuid
from datetime import datetime
from typing import Optional


TASK_FILE = "task.json"
RESULT_FILE = "result.json"


def generate_task_id() -> str:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"task_{ts}"


def init_task(tasks_dir: str, objective: str, steps: list[dict], guidance: str = "") -> str:
    """创建新任务，返回 task_id"""
    task_id = generate_task_id()
    task_dir = os.path.join(tasks_dir, task_id)
    os.makedirs(task_dir, exist_ok=True)

    task_data = {
        "task_id": task_id,
        "objective": objective,
        "created_at": datetime.now().isoformat(),
        "steps": steps,
        "guidance": guidance,
        "voice_notify": True,
        "status": "running",
    }

    path = os.path.join(task_dir, TASK_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(task_data, f, ensure_ascii=False, indent=2)

    return task_id


def get_task_path(tasks_dir: str, task_id: str) -> str:
    return os.path.join(tasks_dir, task_id, TASK_FILE)


def get_result_path(tasks_dir: str, task_id: str) -> str:
    return os.path.join(tasks_dir, task_id, RESULT_FILE)
