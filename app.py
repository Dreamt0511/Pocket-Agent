"""
Pocket-Agent FastAPI 服务 — 运行在 Termux 中，为 Android App 提供 AI Agent HTTP API
启动方式: cd /sdcard/Pocket-Agent && source .venv/bin/activate && uvicorn app:app --host 0.0.0.0 --port 8000
"""
import os
import sys
import json
import subprocess
import asyncio
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pocket-agent-api")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

app = FastAPI(title="Pocket-Agent API")


# ─── 健康检查 ─────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "python": sys.version,
        "project_root": PROJECT_ROOT,
    }


# ─── 安装依赖 ─────────────────────────────────

@app.post("/setup")
async def setup():
    req_file = os.path.join(PROJECT_ROOT, "requirements.txt")
    if not os.path.exists(req_file):
        return {"status": "error", "message": f"requirements.txt not found at {req_file}"}
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", req_file],
        capture_output=True, text=True, cwd=PROJECT_ROOT
    )
    return {
        "status": "ok" if result.returncode == 0 else "error",
        "output": result.stdout[-2000:],
        "error": result.stderr[-2000:],
    }


# ─── 聊天执行（SSE 流式） ──────────────────────

@app.post("/chat")
async def chat(request: Request):
    data = await request.json()
    message = data.get("message", "")

    async def generate():
        try:
            from agent.agent_langchain import LangChainPocketAgent
            agent = LangChainPocketAgent()
            result, success, iterations = await agent.run_conversation(message)
            # 按 SSE 格式逐块推送
            for chunk in result.split("\n"):
                if chunk.strip():
                    yield f"data: {chunk.strip()}\n\n"
            yield f"data: [DONE]\n\n"
        except Exception as e:
            logger.exception("Chat execution failed")
            yield f"data: [ERROR] {str(e)}\n\n"
            yield f"data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# ─── 代码同步 ─────────────────────────────────

@app.post("/sync")
async def sync():
    result = subprocess.run(
        ["git", "pull", "origin", "main"],
        capture_output=True, text=True, cwd=PROJECT_ROOT
    )
    return {
        "status": "ok" if result.returncode == 0 else "error",
        "output": result.stdout,
        "error": result.stderr,
    }


# ─── 配置读写 ─────────────────────────────────

@app.get("/config")
async def get_config():
    config = {}
    env_file = os.path.join(PROJECT_ROOT, ".env")
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    config[k.strip()] = v.strip().strip("\"'")
    return config


@app.post("/config")
async def set_config(request: Request):
    data = await request.json()
    env_file = os.path.join(PROJECT_ROOT, ".env")
    existing = {}
    if os.path.exists(env_file):
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    existing[k.strip()] = v.strip()
    existing.update(data)
    with open(env_file, "w") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
