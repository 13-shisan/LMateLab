# whitelist.py
import json
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "var" / "data" / "allowed_users.json"

def load_whitelist(path: Path = DEFAULT_PATH) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def find_allowed_user(name_cn: str, data: dict) -> dict | None:
    name_cn = (name_cn or "").strip()
    if not name_cn:
        return None

    for u in data.get("users", []):
        if u.get("enabled", True) and u.get("nameCN") == name_cn:
            return u
    return None
