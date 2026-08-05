import os

APP_DIR = os.getenv("APP_DIR", "/storage/software/LMateLab/var")

KNOWLEDGE_DIR = os.getenv(
    "AGENT_KNOWLEDGE_DIR",
    os.path.join(APP_DIR, "knowledge"),
)

PAPERS_ROOT_DIR = os.getenv(
    "PAPERS_ROOT_DIR",
    os.path.join(APP_DIR, "papers"),
)

PAPERS_INDEX_JSON = os.getenv(
    "PAPERS_INDEX_JSON",
    os.path.join(PAPERS_ROOT_DIR, "index", "papers_index.json"),
)

RAW_DIR = os.path.join(KNOWLEDGE_DIR, "raw")
PROCESSED_DIR = os.path.join(KNOWLEDGE_DIR, "processed")
CHROMA_DIR = os.path.join(KNOWLEDGE_DIR, "chroma_db")

EMBEDDING_MODEL_NAME = os.getenv(
    "AGENT_EMBEDDING_MODEL",
    os.path.join(APP_DIR, "models", "BAAI", "bge-m3"),
)

EMBEDDING_DEVICE = os.getenv("AGENT_EMBEDDING_DEVICE", "auto")
EMBEDDING_USE_FP16 = os.getenv("AGENT_EMBEDDING_USE_FP16", "1") == "1"
EMBEDDING_BATCH_SIZE = int(os.getenv("AGENT_EMBEDDING_BATCH_SIZE", "8"))
EMBEDDING_MAX_LENGTH = int(os.getenv("AGENT_EMBEDDING_MAX_LENGTH", "4096"))

RAG_TOP_K = int(os.getenv("AGENT_RAG_TOP_K", "4"))
RAG_ENABLED = os.getenv("AGENT_RAG_ENABLED", "1") == "1"
