# backend/services/agents/vector_store.py
import chromadb
from chromadb.config import Settings
from .rag_config import CHROMA_DIR

_client = None


def get_chroma_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=CHROMA_DIR)
    return _client


def get_client():
    return get_chroma_client()


def get_collection(name: str):
    client = get_chroma_client()
    return client.get_or_create_collection(name=name)
