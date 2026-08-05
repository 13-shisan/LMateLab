# backend/routers/issues.py
import os
import re
import json
import time
import shutil
from pathlib import Path
from typing import Literal, Optional, List
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth import get_current_user

router = APIRouter(prefix="/issues", tags=["issues"])

ISSUES_DIR = Path(os.getenv("ISSUES_DIR", "/app/var/issues")).resolve()
TZ = ZoneInfo("Asia/Shanghai")

BADWORDS_PATH = Path(os.getenv("BADWORDS_PATH", "/app/data/badwords.txt"))
_badwords_cache = None

def _load_badwords() -> list[str]:
    global _badwords_cache
    if _badwords_cache is not None:
        return _badwords_cache
    if not BADWORDS_PATH.exists():
        _badwords_cache = []
        return _badwords_cache
    words = []
    for line in BADWORDS_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
        w = line.strip()
        if not w or w.startswith("#"):
            continue
        words.append(w)
    _badwords_cache = words
    return _badwords_cache

def _contains_badword(text: str) -> Optional[str]:
    if not text:
        return None
    t = text.lower()
    for w in _load_badwords():
        if w.lower() in t:
            return w
    return None

def _reject_if_bad(text: str, field_name: str):
    hit = _contains_badword(text)
    if hit:
        raise HTTPException(status_code=400, detail=f"{field_name} 含屏蔽词：{hit}")

def _is_root(user) -> bool:
    return getattr(user, "role", None) == "root"

def _now_ts() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

def _user_display(user) -> dict:
    # 根据你 user 结构调整：尽量别信前端 localStorage
    return {
        "email": getattr(user, "email", None),
        "alias": getattr(user, "alias", None),
        "role": getattr(user, "role", None),
    }
    
def _can_delete_comment(current_user, comment_obj: dict) -> bool:
    if _is_root(current_user):
        return True
    me_email = getattr(current_user, "email", None)
    author_email = (comment_obj.get("author") or {}).get("email")
    return bool(me_email) and me_email == author_email

def _issue_dir(issue_id: int) -> Path:
    return ISSUES_DIR / f"{issue_id:08d}"

def _read_json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))

def _write_json_atomic(p: Path, obj: dict):
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)

class CreateIssueReq(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    labels: List[str] = Field(default_factory=list, max_length=20)

class AddCommentReq(BaseModel):
    body: str = Field(min_length=1, max_length=20000)

class IssueListItem(BaseModel):
    id: int
    title: str
    state: Literal["open", "closed"]
    created_at: str
    updated_at: str
    author: dict
    comments: int
    labels: List[str] = []

class IssueDetail(BaseModel):
    id: int
    title: str
    state: Literal["open", "closed"]
    created_at: str
    updated_at: str
    author: dict
    body: str
    comments: List[dict]
    labels: List[str] = []
    
class UpdateLabelsReq(BaseModel):
    labels: List[str] = Field(default_factory=list, max_length=20)

def _acquire_lock(lock_path: Path, timeout_sec: float = 5.0):
    start = time.time()
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return
        except FileExistsError:
            if time.time() - start > timeout_sec:
                raise HTTPException(status_code=503, detail="busy, retry later")
            time.sleep(0.05)

def _release_lock(lock_path: Path):
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass

def _next_issue_id() -> int:
    ISSUES_DIR.mkdir(parents=True, exist_ok=True)
    seq_path = ISSUES_DIR / "seq.txt"
    lock_path = ISSUES_DIR / ".seq.lock"

    _acquire_lock(lock_path)
    try:
        if not seq_path.exists():
            seq_path.write_text("0", encoding="utf-8")
        cur = int(seq_path.read_text(encoding="utf-8").strip() or "0")
        nxt = cur + 1
        seq_path.write_text(str(nxt), encoding="utf-8")
        return nxt
    finally:
        _release_lock(lock_path)

@router.get("", response_model=list[IssueListItem])
def list_issues(
    state: Literal["open", "closed", "all"] = Query("open"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user=Depends(get_current_user),
):
    if not ISSUES_DIR.exists():
        return []

    # 简单扫描目录（小规模完全够用）
    items = []
    for d in sorted(ISSUES_DIR.glob("[0-9]" * 8), reverse=True):
        meta_path = d / "issue.json"
        if not meta_path.exists():
            continue
        meta = _read_json(meta_path)
        if state != "all" and meta.get("state") != state:
            continue
        items.append(meta)

    # updated_at 倒序更像 GitHub
    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end]

@router.post("")
def create_issue(req: CreateIssueReq, current_user=Depends(get_current_user)):
    issue_id = _next_issue_id()
    d = _issue_dir(issue_id)
    (d / "comments").mkdir(parents=True, exist_ok=True)

    ts = _now_ts()
    author = _user_display(current_user)
    _reject_if_bad(req.title, "标题")
    _reject_if_bad(req.body, "正文")

    (d / "body.md").write_text(req.body.strip() + "\n", encoding="utf-8")

    meta = {
        "id": issue_id,
        "title": req.title.strip(),
        "state": "open",
        "created_at": ts,
        "updated_at": ts,
        "author": author,
        "comments": 0,
        "labels": [x.strip() for x in req.labels if x.strip()][:20],
    }
    _write_json_atomic(d / "issue.json", meta)

    return {"id": issue_id, "ok": True}

@router.get("/{issue_id}", response_model=IssueDetail)
def get_issue(issue_id: int, current_user=Depends(get_current_user)):
    d = _issue_dir(issue_id)
    meta_path = d / "issue.json"
    body_path = d / "body.md"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="issue not found")

    meta = _read_json(meta_path)
    body = body_path.read_text(encoding="utf-8", errors="replace") if body_path.exists() else ""

    comments_dir = d / "comments"
    comments = []
    if comments_dir.exists():
        for p in sorted(comments_dir.glob("*.json")):
            comments.append(_read_json(p))

    return {
        **meta,
        "body": body,
        "comments": comments,
    }

@router.post("/{issue_id}/comments")
def add_comment(issue_id: int, req: AddCommentReq, current_user=Depends(get_current_user)):
    d = _issue_dir(issue_id)
    meta_path = d / "issue.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="issue not found")

    lock_path = d / ".lock"
    _acquire_lock(lock_path)
    try:
        meta = _read_json(meta_path)
        cdir = d / "comments"
        cdir.mkdir(exist_ok=True)

        # 评论自增序号
        existing = sorted([p.stem for p in cdir.glob("*.json")])
        next_n = int(existing[-1]) + 1 if existing else 1
        cid = f"{next_n:06d}"
        _reject_if_bad(req.body, "评论")

        ts = _now_ts()
        comment = {
            "id": next_n,
            "created_at": ts,
            "author": _user_display(current_user),
            "body": req.body.strip(),
        }
        _write_json_atomic(cdir / f"{cid}.json", comment)

        meta["comments"] = int(meta.get("comments", 0)) + 1
        meta["updated_at"] = ts
        _write_json_atomic(meta_path, meta)
    finally:
        _release_lock(lock_path)

    return {"ok": True}

@router.post("/{issue_id}/close")
def close_issue(issue_id: int, current_user=Depends(get_current_user)):
    if not _is_root(current_user):
        raise HTTPException(status_code=403, detail="only root can close")

    d = _issue_dir(issue_id)
    meta_path = d / "issue.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="issue not found")

    ts = _now_ts()
    meta = _read_json(meta_path)
    meta["state"] = "closed"
    meta["updated_at"] = ts
    _write_json_atomic(meta_path, meta)
    return {"ok": True}

@router.post("/{issue_id}/reopen")
def reopen_issue(issue_id: int, current_user=Depends(get_current_user)):
    if not _is_root(current_user):
        raise HTTPException(status_code=403, detail="only root can reopen")

    d = _issue_dir(issue_id)
    meta_path = d / "issue.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="issue not found")

    ts = _now_ts()
    meta = _read_json(meta_path)
    meta["state"] = "open"
    meta["updated_at"] = ts
    _write_json_atomic(meta_path, meta)
    return {"ok": True}


@router.patch("/{issue_id}/labels")
def update_labels(issue_id: int, req: UpdateLabelsReq, current_user=Depends(get_current_user)):
    d = _issue_dir(issue_id)
    meta_path = d / "issue.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="issue not found")

    lock_path = d / ".lock"
    _acquire_lock(lock_path)
    try:
        meta = _read_json(meta_path)

        # 仅作者或 root 可改（推荐）
        author_email = (meta.get("author") or {}).get("email")
        me_email = getattr(current_user, "email", None)
        if not _is_root(current_user) and (not me_email or me_email != author_email):
            raise HTTPException(status_code=403, detail="only author/root can edit labels")

        cleaned = []
        for x in req.labels:
            x = (x or "").strip()
            if not x:
                continue
            if len(x) > 24:
                x = x[:24]
            cleaned.append(x)
        # 去重保序 + 限制数量
        seen = set()
        uniq = []
        for x in cleaned:
            if x.lower() in seen:
                continue
            seen.add(x.lower())
            uniq.append(x)
        meta["labels"] = uniq[:20]

        ts = _now_ts()
        meta["updated_at"] = ts
        _write_json_atomic(meta_path, meta)
    finally:
        _release_lock(lock_path)

    return {"ok": True, "labels": meta["labels"]}

@router.delete("/{issue_id}/comments/{comment_id}")
def delete_comment(issue_id: int, comment_id: int, current_user=Depends(get_current_user)):
    d = _issue_dir(issue_id)
    meta_path = d / "issue.json"
    cdir = d / "comments"

    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="issue not found")

    comment_path = cdir / f"{comment_id:06d}.json"
    if not comment_path.exists():
        raise HTTPException(status_code=404, detail="comment not found")

    lock_path = d / ".lock"
    _acquire_lock(lock_path)
    try:
        meta = _read_json(meta_path)
        comment_obj = _read_json(comment_path)

        if not _can_delete_comment(current_user, comment_obj):
            raise HTTPException(status_code=403, detail="no permission to delete this comment")

        # 删除评论文件
        comment_path.unlink(missing_ok=True)

        # 更新计数与更新时间（防止变负数）
        meta["comments"] = max(0, int(meta.get("comments", 0)) - 1)
        meta["updated_at"] = _now_ts()
        _write_json_atomic(meta_path, meta)
    finally:
        _release_lock(lock_path)

    return {"ok": True}

@router.delete("/{issue_id}")
def delete_issue(issue_id: int, current_user=Depends(get_current_user)):
    d = _issue_dir(issue_id)
    meta_path = d / "issue.json"
    if not meta_path.exists():
        raise HTTPException(status_code=404, detail="issue not found")

    # 权限：root 或 作者本人
    meta = _read_json(meta_path)
    author_email = (meta.get("author") or {}).get("email")
    me_email = getattr(current_user, "email", None)
    if not _is_root(current_user) and (not me_email or me_email != author_email):
        raise HTTPException(status_code=403, detail="only author/root can delete issue")

    lock_path = d / ".lock"
    _acquire_lock(lock_path)
    try:
        # 删除整个 issue 目录（包含 body.md、issue.json、comments/）
        if d.exists():
            shutil.rmtree(d)
    finally:
        # 目录可能已经被删了，释放锁要容错
        try:
            _release_lock(lock_path)
        except Exception:
            pass

    return {"ok": True}
