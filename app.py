"""
Pocket-Agent FastAPI 服务 — 运行在 Termux 中，为 Android App 提供 AI Agent HTTP API
启动方式: cd /sdcard/Pocket-Agent && source .venv/bin/activate && uvicorn app:app --host 0.0.0.0 --port 8000
"""
import os
import sys
import json
import subprocess
import asyncio
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pocket-agent-api")

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

app = FastAPI(title="Pocket-Agent API")

# ─── .env 配置加载 ─────────────────────────────

def _load_env_config() -> dict:
    """从 .env 文件加载 LLM 配置，转成 agent 所需的 key 格式"""
    env_file = os.path.join(PROJECT_ROOT, ".env")
    if not os.path.exists(env_file):
        # 首次运行从 .env.example 复制
        example = os.path.join(PROJECT_ROOT, ".env.example")
        if os.path.exists(example):
            import shutil
            shutil.copy2(example, env_file)
        else:
            return {}

    config = {}
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip(""'")
            config[k] = v

    # 映射到 agent 使用的 key 格式
    mapping = {
        "DEFAULT_LLM_BASE_URL": "base_url",
        "LLM_BASE_URL": "base_url",
        "LLM_API_KEY": "api_key",
        "LLM_MODEL": "model",
        "LLM_TEMPERATURE": "temperature",
        "LLM_MAX_TOKENS": "max_tokens",
    }
    result = {}
    for env_key, agent_key in mapping.items():
        if env_key in config:
            result[agent_key] = config[env_key]
    return result


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
    req_config = data.get("config", {})

    # 合并配置：.env 为基础，请求参数覆盖（优先级最高）
    llm_config = {**_load_env_config(), **req_config}

    async def generate():
        try:
            from agent.agent_langchain import LangChainPocketAgent
            agent = LangChainPocketAgent(llm_config=llm_config)
            result, success, iterations = await agent.run_conversation(message)
            # 按 SSE 格式逐块推送
            for chunk in result.split("
"):
                if chunk.strip():
                    yield f"data: {chunk.strip()}

"
            yield f"data: [DONE]

"
        except Exception as e:
            logger.exception("Chat execution failed")
            yield f"data: [ERROR] {str(e)}

"
            yield f"data: [DONE]

"

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
                    config[k.strip()] = v.strip().strip(""'")
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
            f.write(f"{k}={v}
")
    return {"status": "ok"}



# ─── 服务关闭 ─────────────────────────────────

@app.post("/shutdown")
async def shutdown():
    """关闭 FastAPI 服务自身"""
    import os, signal, asyncio
    async def _die():
        await asyncio.sleep(0.3)
        os.kill(os.getpid(), signal.SIGTERM)
    asyncio.create_task(_die())
    return {"status": "shutting_down"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
