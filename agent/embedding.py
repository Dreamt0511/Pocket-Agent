#!/usr/bin/env python3
"""
Embedding 模块 — 通过本地 llama-server 或远程 API 生成向量嵌入

存储方案: SQLite + numpy（替代 ChromaDB，无需编译 Rust 依赖）
embeddings 表只存向量（id + embedding BLOB），原始内容在 messages 表
"""

import struct
import json
import os
import time
import socket
import shutil
import subprocess
import sqlite3
import requests
import numpy as np
from typing import List, Optional

# 嵌入服务子进程引用（与 body server 的 _server_thread/_server_instance 模式一致）
_embedding_process = None


class EmbeddingClient:
    """通过 OpenAI 兼容的 /embeddings 端点生成向量"""

    def __init__(self, base_url: str, api_key: str, model: str = "bge-m3"):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model

    def is_available(self) -> bool:
        """检测 API 是否支持 embeddings（本地服务，无缓存，每次直接检测）"""
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": "test"},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=3
            )
            return resp.status_code == 200
        except Exception:
            return False

    def embed(self, text: str) -> Optional[List[float]]:
        """生成单条文本的 embedding，超长时自动截断重试"""
        if not self.is_available():
            return None
        # 先尝试全文，失败则截断重试（batch_size=2048 tokens，约 4000 字符）
        for input_text in (text, text[:4000]):
            try:
                resp = requests.post(
                    f"{self.base_url}/embeddings",
                    json={"model": self.model, "input": input_text},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=15
                )
                if resp.status_code == 200:
                    return resp.json()["data"][0]["embedding"]
            except Exception:
                pass
        return None

    def embed_batch(self, texts: List[str]) -> List[Optional[List[float]]]:
        """批量生成 embedding（单次 API 调用）"""
        if not self.is_available() or not texts:
            return [None] * len(texts)
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": texts},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30
            )
            if resp.status_code == 200:
                data = resp.json()
                results = [None] * len(texts)
                for item in data["data"]:
                    results[item["index"]] = item["embedding"]
                return results
        except Exception:
            pass
        return [None] * len(texts)

    @staticmethod
    def embedding_to_blob(embedding: List[float]) -> bytes:
        """将 embedding 列表转为 BLOB（float32 数组）"""
        return struct.pack(f'{len(embedding)}f', *embedding)

    @staticmethod
    def blob_to_embedding(blob: bytes) -> List[float]:
        """将 BLOB 还原为 embedding 列表"""
        count = len(blob) // 4
        return list(struct.unpack(f'{count}f', blob))


class VectorStore:
    """基于 SQLite + numpy 的向量存储（替代 ChromaDB）

    只存向量索引（id + embedding），原始内容在 messages 表。
    向量搜索通过 id 回 messages 表取原文。
    """

    def __init__(self, db_path: str, embedding_client: EmbeddingClient = None):
        self.db_path = db_path
        self.embedding_client = embedding_client
        self._init_table()

    def _get_conn(self):
        """获取带 WAL 模式和 busy_timeout 的连接"""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_table(self):
        """创建 embeddings 表（只存向量，不存内容）。自动迁移旧 schema。"""
        conn = self._get_conn()
        try:
            # 检查旧表是否有 content 列（需要迁移）
            cols = {r[1] for r in conn.execute("PRAGMA table_info(embeddings)").fetchall()}
            if cols and "content" in cols:
                conn.execute("ALTER TABLE embeddings RENAME TO embeddings_old")
                conn.execute("""CREATE TABLE embeddings (
                    id TEXT PRIMARY KEY,
                    embedding BLOB
                )""")
                conn.execute("INSERT INTO embeddings (id, embedding) SELECT id, embedding FROM embeddings_old")
                conn.execute("DROP TABLE embeddings_old")
                conn.commit()
            else:
                conn.execute("""CREATE TABLE IF NOT EXISTS embeddings (
                    id TEXT PRIMARY KEY,
                    embedding BLOB
                )""")
                conn.commit()
        finally:
            conn.close()

    def add(self, message_id: int, text: str) -> bool:
        """为消息生成向量并存储（只存向量，内容在 messages 表）

        Args:
            message_id: messages 表的 id
            text: 用于生成 embedding 的文本（可以是内容的摘要或全文）
        """
        if not self.embedding_client or not self.embedding_client.is_available():
            return False
        embedding = self.embedding_client.embed(text)
        if not embedding:
            return False
        blob = EmbeddingClient.embedding_to_blob(embedding)
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO embeddings (id, embedding) VALUES (?, ?)",
                (str(message_id), blob)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def query(self, text: str, n_results: int = 20,
              conversation_id: str = None, msg_type: str = None,
              days: int = None, memory_type: str = None) -> list:
        """向量语义搜索，返回 id + distance（内容由调用方回 messages 表查询）

        Args:
            text: 查询文本
            n_results: 返回结果数
            conversation_id: 过滤会话 ID
            msg_type: 过滤消息类型 (user/assistant/memory)
            days: 只返回最近 N 天的结果
            memory_type: 过滤记忆类型 (fact/episodic/dance)
        Returns:
            [{"id": str, "distance": float}, ...]
        """
        if not self.embedding_client or not self.embedding_client.is_available():
            return []
        query_embedding = self.embedding_client.embed(text)
        if not query_embedding:
            return []

        # 构建 SQL 过滤条件，下推到数据库层
        conditions = []
        params = []
        if conversation_id:
            conditions.append("m.conversation_id = ?")
            params.append(conversation_id)
        if msg_type:
            conditions.append("m.role = ?")
            params.append(msg_type)
        if days:
            import time
            conditions.append("m.timestamp > ?")
            params.append(int((time.time() - days * 86400) * 1000))
        if memory_type:
            conditions.append("m.memory_type = ?")
            params.append(memory_type)

        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)
            sql = f"SELECT e.id, e.embedding FROM embeddings e JOIN messages m ON e.id = CAST(m.id AS TEXT) {where_clause}"
        else:
            sql = "SELECT id, embedding FROM embeddings"

        conn = self._get_conn()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        # numpy 批量计算余弦相似度
        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        results = []
        for row_id, blob in rows:
            try:
                vec = np.frombuffer(blob, dtype=np.float32)
            except Exception:
                continue
            vec_norm = np.linalg.norm(vec)
            if vec_norm == 0:
                sim = 0.0
            else:
                sim = float(np.dot(query_vec, vec) / (query_norm * vec_norm))
            results.append({"id": row_id, "distance": 1.0 - sim})

        results.sort(key=lambda x: x["distance"])
        return results[:n_results]

    def delete(self, message_id: int):
        """删除消息的向量索引"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM embeddings WHERE id = ?", (str(message_id),))
            conn.commit()
        finally:
            conn.close()


# ── 嵌入服务启动/停止（与 body_control_tool 的 start/stop 模式一致）──

def start_embedding_server(port: int = 8080) -> bool:
    """启动 llama-server 嵌入服务。已运行则跳过，否则杀旧启新。

    与 start_body_server() 模式一致：
    - 检查是否已在运行 → 跳过
    - 清理旧进程 → 启动新进程（带重试）
    """
    global _embedding_process

    # 检查子进程是否还活着
    if _embedding_process is not None and _embedding_process.poll() is None:
        return True

    emb_path = os.getenv("EMBEDDING_MODEL_PATH")
    if not emb_path or not os.path.exists(emb_path):
        return False
    if not shutil.which("llama-server"):
        return False

    # 端口已被占用 → 说明有服务在跑，直接复用
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            _embedding_process = None  # 不是我们启动的，不管理生命周期
            return True
    except (ConnectionRefusedError, OSError):
        pass

    # 清理旧进程
    stop_embedding_server()

    # 启动新进程（若端口冲突则等 0.3s 重试一次，与 body server 的 OSError 重试一致）
    for attempt in range(2):
        try:
            _embedding_process = subprocess.Popen(
                ["llama-server", "-m", emb_path,
                 "--embedding", "-c", "8192", "--port", str(port),
                 "--host", "0.0.0.0", "-np", "4", "-b", "2048", "-ub", "2048", "-t", "4"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
        except Exception:
            if attempt == 0:
                time.sleep(0.3)
    return False


def stop_embedding_server():
    """停止嵌入服务，释放端口"""
    global _embedding_process
    proc = _embedding_process
    _embedding_process = None
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
                proc.wait(timeout=2)
            except Exception:
                pass
    # 兜底：清理任何残留的 llama-server 进程
    subprocess.run(["pkill", "-f", "llama-server.*8080"],
                   timeout=2, stderr=subprocess.DEVNULL)
