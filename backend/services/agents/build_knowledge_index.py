# backend/services/agents/build_knowledge_index.py
import os
import json
from .knowledge_loader import build_chunks_for_domain
from .embeddings import embed_texts
from .vector_store import get_collection, get_client
from .rag_config import PROCESSED_DIR


def save_chunks_jsonl(path: str, chunks: list[dict]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in chunks:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def recreate_collection(collection_name: str):
    client = get_client()

    try:
        client.delete_collection(collection_name)
        print(
            f"[build_knowledge_index] deleted old collection={collection_name}",
            flush=True
        )
    except Exception as e:
        print(
            f"[build_knowledge_index] delete old collection skipped: {collection_name}, error={e}",
            flush=True
        )

    return get_collection(collection_name)


def rebuild_domain(domain: str):
    print(f"[build_knowledge_index] rebuilding domain={domain}", flush=True)

    chunks = build_chunks_for_domain(domain)
    if not chunks:
        print(f"[build_knowledge_index] no chunks found for domain={domain}", flush=True)
        return

    processed_path = os.path.join(PROCESSED_DIR, f"chunks_{domain}.jsonl")
    save_chunks_jsonl(processed_path, chunks)

    texts = [c["text"] for c in chunks]
    ids = [c["id"] for c in chunks]
    metadatas = [
        {
            "domain": c["domain"],
            "source": c["source"],
            "chunk_index": c["chunk_index"],
            "paper_id": c.get("paper_id", ""),
            "title": c.get("title", ""),
            "chunk_type": c.get("chunk_type", ""),
        }
        for c in chunks
    ]


    print(
        f"[build_knowledge_index] embedding texts for domain={domain}, count={len(texts)}",
        flush=True
    )
    vectors = embed_texts(texts)

    collection_name = f"knowledge_{domain}"
    collection = recreate_collection(collection_name)

    batch_size = 5000
    total = len(ids)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        print(
            f"[build_knowledge_index] adding to collection={collection_name}, batch={start}:{end}/{total}",
            flush=True
        )
        collection.add(
            ids=ids[start:end],
            documents=texts[start:end],
            metadatas=metadatas[start:end],
            embeddings=vectors[start:end],
        )

    print(
        f"[build_knowledge_index] done domain={domain}, chunks={len(chunks)}, saved={processed_path}",
        flush=True
    )


def main():
    rebuild_domain("platform")
    rebuild_domain("research")
    rebuild_domain("papers")


if __name__ == "__main__":
    main()
