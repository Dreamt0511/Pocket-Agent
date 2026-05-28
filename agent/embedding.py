#!/usr/bin/env python3
"""
Embedding 客户端 — 通过用户配置的 LLM API 生成向量嵌入
支持 OpenAI 兼容的 /embeddings 端点
"""

import struct
import math
import requests
from typing import List, Optional


class EmbeddingClient:
    """通过 LLM API 的 /embeddings 端点生成向量"""

    def __init__(self, base_url: str, api_key: str, model: str = "text-embedding-3-small"):
        """
        Args:
            base_url: LLM API 地址（如 https://api.openai.com/v1）
            api_key: API 密钥
            model: embedding 模型名称
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self._available: Optional[bool] = None  # 缓存可用性

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
                # 按 index 排序，确保顺序一致
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


import chromadb


class VectorStore:
    """基于 ChromaDB 的向量存储（HNSW 索引）"""

    def __init__(self, persist_dir: str, embedding_client: EmbeddingClient = None):
        """
        Args:
            persist_dir: ChromaDB 持久化目录
            embedding_client: 用于生成 embedding 的客户端
        """
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collection = self.client.get_or_create_collection(
            name="messages",
            metadata={"hnsw:space": "cosine"}
        )
        self.embedding_client = embedding_client

    def add(self, message_id: int, content: str, metadata: dict = None):
        """添加消息到向量索引"""
        if not self.embedding_client or not self.embedding_client.is_available():
            return False
        embedding = self.embedding_client.embed(content)
        if not embedding:
            return False
        self.collection.add(
            ids=[str(message_id)],
            embeddings=[embedding],
            documents=[content],
            metadatas=[metadata or {}]
        )
        return True

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
        embedding = self.embedding_client.embed(text)
        if not embedding:
            return []
        kwargs = {
            "query_embeddings": [embedding],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where
        results = self.collection.query(**kwargs)
        items = []
        for i in range(len(results["ids"][0])):
            items.append({
                "id": results["ids"][0][i],
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0,
            })
        return items

    def delete(self, message_id: int):
        """删除消息"""
        try:
            self.collection.delete(ids=[str(message_id)])
        except Exception:
            pass
