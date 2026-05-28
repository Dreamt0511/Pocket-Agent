#!/usr/bin/env python3
"""
Embedding 模块 — 通过本地 llama-server 或远程 API 生成向量嵌入

存储方案: SQLite + numpy（替代 ChromaDB，无需编译 Rust 依赖）
"""

import struct
import math
import json
import sqlite3
import requests
import numpy as np
from typing import List, Optional


class EmbeddingClient:
    """通过 OpenAI 兼容的 /embeddings 端点生成向量"""

    def __init__(self, base_url: str, api_key: str, model: str = "bge-m3"):
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self._available: Optional[bool] = None

    def is_available(self) -> bool:
        """检测 API 是否支持 embeddings（结果缓存）"""
        if self._available is not None:
            return self._available
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": "test"},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=10
            )
            self._available = resp.status_code == 200
        except Exception:
            self._available = False
        return self._available

    def embed(self, text: str) -> Optional[List[float]]:
        """生成单条文本的 embedding"""
        if not self.is_available():
            return None
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                json={"model": self.model, "input": text},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=15
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["data"][0]["embedding"]
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


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算两个向量的余弦相似度"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore:
    """基于 SQLite + numpy 的向量存储（替代 ChromaDB）"""

    def __init__(self, db_path: str, embedding_client: EmbeddingClient = None):
        """
        Args:
            db_path: SQLite 数据库路径（与主数据库共用）
            embedding_client: 用于生成 embedding 的客户端
        """
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
        """创建 embeddings 表"""
        conn = self._get_conn()
        try:
            conn.execute("""CREATE TABLE IF NOT EXISTS embeddings (
                id TEXT PRIMARY KEY,
                content TEXT,
                metadata TEXT,
                embedding BLOB
            )""")
            conn.commit()
        finally:
            conn.close()

    def add(self, message_id: int, content: str, metadata: dict = None) -> bool:
        """添加消息到向量索引"""
        if not self.embedding_client or not self.embedding_client.is_available():
            return False
        embedding = self.embedding_client.embed(content)
        if not embedding:
            return False
        blob = EmbeddingClient.embedding_to_blob(embedding)
        conn = self._get_conn()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO embeddings (id, content, metadata, embedding) VALUES (?, ?, ?, ?)",
                (str(message_id), content, json.dumps(metadata or {}), blob)
            )
            conn.commit()
            return True
        finally:
            conn.close()

    def query(self, text: str, n_results: int = 20, where: dict = None) -> list:
        """语义搜索

        Args:
            text: 查询文本
            n_results: 返回结果数
            where: 过滤条件（如 {"conversation_id": "xxx"}）
        Returns:
            [{"id": str, "document": str, "metadata": dict, "distance": float}, ...]
        """
        if not self.embedding_client or not self.embedding_client.is_available():
            return []
        query_embedding = self.embedding_client.embed(text)
        if not query_embedding:
            return []

        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT id, content, metadata, embedding FROM embeddings").fetchall()
        finally:
            conn.close()

        if not rows:
            return []

        # 过滤（按 metadata 中的 conversation_id）
        if where and "conversation_id" in where:
            cid = where["conversation_id"]
            rows = [r for r in rows if json.loads(r[2]).get("conversation_id") == cid]

        # numpy 批量计算余弦相似度
        query_vec = np.array(query_embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []

        ids, documents, metadatas, distances = [], [], [], []
        for row_id, content, meta_json, blob in rows:
            try:
                vec = np.frombuffer(blob, dtype=np.float32)
            except Exception:
                continue
            vec_norm = np.linalg.norm(vec)
            if vec_norm == 0:
                sim = 0.0
            else:
                sim = float(np.dot(query_vec, vec) / (query_norm * vec_norm))
            ids.append(row_id)
            documents.append(content)
            metadatas.append(json.loads(meta_json))
            # distance = 1 - similarity（与 ChromaDB 语义一致）
            distances.append(1.0 - sim)

        # 按 distance 升序排序，取 top-n
        indices = sorted(range(len(distances)), key=lambda i: distances[i])[:n_results]
        return [
            {
                "id": ids[i],
                "document": documents[i],
                "metadata": metadatas[i],
                "distance": distances[i],
            }
            for i in indices
        ]

    def delete(self, message_id: int):
        """删除消息"""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM embeddings WHERE id = ?", (str(message_id),))
            conn.commit()
        finally:
            conn.close()
