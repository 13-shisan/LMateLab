# /home/software/LMateLab/backend/alembic_digest/env.py
import os
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ✅ 把 /home/software/LMateLab/backend 加入 sys.path
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

config = context.config

# ✅ digest 用 DIGEST_DATABASE_URL
db_url = os.getenv("DIGEST_DATABASE_URL")
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ✅ 关键：导入 DigestBase，并确保 digest_models 被 import（注册表到 metadata）
from digest_database import DigestBase  # noqa: E402
import digest_models  # noqa: F401, E402

target_metadata = DigestBase.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,  # SQLite 下改表结构必备
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # 可选：避免和主库同名版本表混淆（强烈推荐）
        version_table="alembic_version_digest",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=True,
            version_table="alembic_version_digest",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

