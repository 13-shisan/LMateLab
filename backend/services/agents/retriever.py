# backend/services/agents/retriever.py
from typing import List, Dict, Any
from .embeddings import embed_query
from .vector_store import get_collection
from .rag_config import RAG_TOP_K, RAG_ENABLED


def retrieve(domain: str, query: str, top_k: int | None = None) -> List[Dict[str, Any]]:
    if not RAG_ENABLED:
        return []

    query = (query or "").strip()
    if not query:
        return []

    k = top_k or RAG_TOP_K

    try:
        collection = get_collection(f"knowledge_{domain}")
        query_vector = embed_query(query)

        result = collection.query(
            query_embeddings=[query_vector],
            n_results=k,
        )

        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0] if result.get("distances") else []

        items = []
        for i, doc in enumerate(docs):
            items.append({
                "text": doc,
                "metadata": metas[i] if i < len(metas) else {},
                "distance": distances[i] if i < len(distances) else None,
            })

        return items
    except Exception as e:
        print(f"[retriever] retrieve failed domain={domain} error={e}", flush=True)
        return []


def format_retrieved_context(items: List[Dict[str, Any]]) -> str:
    if not items:
        return ""

    parts = ["以下是检索到的相关知识，请优先参考这些内容回答："]
    for idx, item in enumerate(items, start=1):
        meta = item.get("metadata", {}) or {}
        source = meta.get("source", "unknown")
        text = item.get("text", "").strip()
        if not text:
            continue
        parts.append(f"[资料{idx}] 来源: {source}\n{text}")

    return "\n\n".join(parts)
