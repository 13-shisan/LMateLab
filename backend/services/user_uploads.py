# services/user_uploads.py
from __future__ import annotations

import json
import os
from pathlib import Path

# 你在容器内的固定路径（你要求的 docker 路径）
ALLOWED_USERS_JSON = os.getenv(
    "ALLOWED_USERS_PATH",
    os.getenv("ALLOWED_USERS_JSON", "/app/var/data/allowed_users.json"),
)

UPLOADS_ROOT = os.getenv(
    "UPLOADS_ROOT",
    "/app/var/uploads",
)

def load_allowed_users() -> dict:
    with open(ALLOWED_USERS_JSON, "r", encoding="utf-8") as f:
        return json.load(f)

def is_alias_allowed(alias: str) -> bool:
    alias = (alias or "").strip()
    if not alias:
        return False
    data = load_allowed_users()
    for u in data.get("users", []):
        if u.get("aliasEN") == alias and bool(u.get("enabled", True)):
            return True
    return False

def _safe_alias(alias: str) -> str:
    # 防止路径穿越：只允许字母数字 _ -
    alias = (alias or "").strip()
    safe = "".join([c for c in alias if c.isalnum() or c in ("_", "-")])
    return safe

def user_upload_dir(alias: str) -> Path:
    safe = _safe_alias(alias)
    return Path(UPLOADS_ROOT) / safe

def ensure_user_upload_dir(alias: str) -> Path:
    d = user_upload_dir(alias)
    d.mkdir(parents=True, exist_ok=True)
    return d

def user_upload_db_path(alias: str) -> Path:
    safe = _safe_alias(alias)
    d = user_upload_dir(alias)
    return d / f"{safe}-uploads.db"
