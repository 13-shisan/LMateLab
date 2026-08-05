# 用于更新日志，永远保存在一个文件，一直更新，并且"只允许 root 上传和记录"
# backend/routers/changelog.py
import os, time
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime
from zoneinfo import ZoneInfo

from auth import get_current_user

router = APIRouter(prefix="/changelog", tags=["changelog"])

CHANGELOG_PATH = Path(os.getenv("CHANGELOG_PATH", "/app/var/config/changelog.md")).resolve()

class AppendReq(BaseModel):
    title: str
    body: str

def _is_root(user) -> bool:
    return getattr(user, "role", None) == "root"

@router.get("")
def get_changelog(current_user=Depends(get_current_user)):
    if not CHANGELOG_PATH.exists():
        return {"content": ""}
    return {"content": CHANGELOG_PATH.read_text(encoding="utf-8", errors="replace")}

@router.post("")
def append_changelog(req: AppendReq, current_user=Depends(get_current_user)):
    if not _is_root(current_user):
        raise HTTPException(status_code=403, detail="only root can write changelog")

    title = (req.title or "").strip()
    body = (req.body or "").strip()
    if not title or not body:
        raise HTTPException(status_code=400, detail="title/body required")

    CHANGELOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
    entry = f"\n\n## {ts} — {title}\n\n{body}\n"

    is_new = not CHANGELOG_PATH.exists()

    with open(CHANGELOG_PATH, "a", encoding="utf-8") as f:
        if is_new:
            f.write("# 平台更新日志\n\n")
        f.write(entry)

    return {"ok": True}
