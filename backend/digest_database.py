# backend/digest_database.py
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

DIGEST_DATABASE_URL = os.getenv(
    "DIGEST_DATABASE_URL",
    "sqlite:////app/var/db/digests.db",
)

digest_engine = create_engine(
    DIGEST_DATABASE_URL,
    connect_args={"check_same_thread": False} if DIGEST_DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)

# ✅ SQLite PRAGMA：外键 + 避免 WAL（解决目录不可写导致 unable to open database file）
if DIGEST_DATABASE_URL.startswith("sqlite"):

    @event.listens_for(digest_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON;")
            # 关键：不要用 WAL，这样不会在同目录创建 digests.db-wal / digests.db-shm
            cursor.execute("PRAGMA journal_mode=DELETE;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=5000;")
        finally:
            cursor.close()

DigestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=digest_engine)

DigestBase = declarative_base()

def get_digest_db():
    db = DigestSessionLocal()
    try:
        yield db
    finally:
        db.close()
