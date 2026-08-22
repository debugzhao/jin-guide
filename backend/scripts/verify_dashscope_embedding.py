"""Quick connectivity/sanity check for the DashScope embedding config added to
the repo-root .env (see backend/docs/04_rag_pipeline.md §9 for why DashScope
was picked over the now-403'd Moonshot embedding model).

Uses plain httpx against DashScope's OpenAI-compatible /embeddings endpoint —
the same call shape as app/engine/embedding.py::embed_batch — instead of the
`dashscope` SDK, since that's not an existing project dependency and this is
just a one-off config check, not new production code.

Only uses the workspace-dedicated endpoint (embedding_openAiCompatible_url) —
it worked on the first try, so the public-endpoint/dashscope-native-protocol
fallbacks (embedding_base_url / embedding_dashScope_url) were never needed and
are commented out in .env.

Usage:
    docker compose exec backend python -m scripts.verify_dashscope_embedding
"""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import numpy as np
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

API_KEY = os.environ["embedding_apiKey"]
MODEL = os.environ["embedding_model"]
BASE_URL = os.environ["embedding_openAiCompatible_url"]
DIMENSION = 1024


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va, vb = np.array(a), np.array(b)
    return float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb)))


def embed(texts: list[str]) -> list[list[float]]:
    resp = httpx.post(
        f"{BASE_URL}/embeddings",
        headers={"Authorization": f"Bearer {API_KEY}"},
        json={"model": MODEL, "input": texts, "dimension": DIMENSION},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]


def semantic_search(
    query: str, documents: list[str], top_k: int = 2
) -> list[tuple[str, float]]:
    query_embedding = embed([query])[0]
    doc_embeddings = embed(documents)
    scored = [
        (documents[i], cosine_similarity(query_embedding, doc_emb))
        for i, doc_emb in enumerate(doc_embeddings)
    ]
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def main() -> None:
    documents = [
        "人工智能是计算机科学的一个分支",
        "机器学习是实现人工智能的重要方法",
        "深度学习是机器学习的一个子领域",
    ]
    query = "什么是AI？"

    print(f"=== {BASE_URL} ===")
    results = semantic_search(query, documents, top_k=2)
    print("成功，语义检索结果：")
    for doc, sim in results:
        print(f"  相似度 {sim:.3f} | {doc}")


if __name__ == "__main__":
    main()
