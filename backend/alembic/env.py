import sys
import os
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from alembic import context

# 让 alembic 能 import 到 backend 目录下的 database.py / models.py
sys.path.append(str(Path(__file__).resolve().parents[1]))

# Alembic Config 对象
config = context.config

# ✅ 让 alembic 使用环境变量里的数据库地址（与 backend/worker 完全一致）
db_url = os.getenv("DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 导入 Base，并确保 models 被导入从而注册到 Base.metadata
from database import Base
import models  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,

        # autogenerate 精确度增强
        compare_type=True,
        compare_server_default=True,

        # SQLite 推荐：batch 模式（即使 offline 也加上，保持一致）
        render_as_batch=True,

        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,

            # autogenerate 精确度增强
            compare_type=True,
            compare_server_default=True,

            # ✅ SQLite 下改表结构必备（新增列/改约束等）
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
