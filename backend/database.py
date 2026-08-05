# backend/database.py
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:////app/var/db/eln.db")  # ✅ 优先用环境变量

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # 仅 sqlite 需要
    pool_pre_ping=True,                         # 连接健康检查（更稳）
)

# ✅ SQLite 默认不强制外键约束，需要手动打开
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    try:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()
    except Exception:
        # 如果换成非 SQLite（如 PostgreSQL），这里会无影响或直接跳过
        pass

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# 依赖函数：在每个请求中获得一个独立 session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
