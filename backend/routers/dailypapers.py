# backend/routers/dailypapers.py

import json
from datetime import date
from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import desc
from digest_database import get_digest_db
from digest_models import DailyDigest
from schemas import DigestListResponse, DigestDetailResponse

router = APIRouter(prefix="/dailypapers", tags=["dailypapers"])

def _paper_blob_text(p: dict) -> str:
    """把一篇 paper 里可能要匹配的字段拼成一个大字符串，统一做 contains。"""
    parts = []
    for k in ("title", "keywords", "abstract_text", "abstract_raw", "summary_text", "doi", "link"):
        v = p.get(k)
        if not v:
            continue
        if isinstance(v, list):
            parts.extend([str(x) for x in v if x is not None])
        else:
            parts.append(str(v))
    # authors 常见是 list
    authors = p.get("authors")
    if authors:
        if isinstance(authors, list):
            parts.extend([str(x) for x in authors if x is not None])
        else:
            parts.append(str(authors))

    return " \n ".join(parts)

def _paper_matches_query(p: dict, q: str) -> bool:
    ql = (q or "").strip().lower()
    if not ql:
        return False
    try:
        return ql in _paper_blob_text(p).lower()
    except Exception:
        return False


def _paper_brief(p: dict) -> dict:
    # 只返回前端列表展示需要的字段，避免 payload 太大
    return {
        "title": (p.get("title") or "").strip(),
        "published": (p.get("published") or "").strip(),
        "doi": (p.get("doi") or "").strip(),
        "authors": p.get("authors") or [],
        "link": (p.get("link") or "").strip(),
    }

def _digest_matches_query(r: DailyDigest, q: str) -> bool:
    """判断一个 digest（含 papers_json）是否命中关键词 q。"""
    if not q:
        return True
    ql = q.strip().lower()
    if not ql:
        return True

    # 先在导读自身字段里匹配（可选但很有用）
    base = " \n ".join([
        str(r.title or ""),
        str(r.journal or ""),
        str(r.code or ""),
        str(r.category or ""),
        str(r.content or ""),
    ]).lower()
    if ql in base:
        return True

    # 再在 papers_json 里匹配
    try:
        papers = json.loads(r.papers_json or "[]")
    except Exception:
        papers = []

    for p in papers or []:
        try:
            blob = _paper_blob_text(p).lower()
        except Exception:
            continue
        if ql in blob:
            return True

    return False


@router.get("", response_model=DigestListResponse)
def list_digests(
    from_: date = Query(..., alias="from"),
    to: date = Query(...),
    journal: Optional[str] = None,
    category: Optional[str] = None,
    q: Optional[str] = None,   # ✅ 新增：关键词搜索
    db: Session = Depends(get_digest_db),
):
    if from_ > to:
        raise HTTPException(status_code=422, detail="'from' must be <= 'to'")

    qset = db.query(DailyDigest).filter(DailyDigest.date >= from_, DailyDigest.date <= to)

    if journal:
        qset = qset.filter(DailyDigest.journal == journal)

    if category:
        qset = qset.filter(DailyDigest.category.isnot(None)).filter(DailyDigest.category.contains(category))

    rows = qset.order_by(desc(DailyDigest.date), desc(DailyDigest.created_at)).all()

    # ✅ 新增：关键词过滤（在 Python 层过滤）
    if q:
        rows = [r for r in rows if _digest_matches_query(r, q)]

    items = []
    for r in rows:
        hit_papers = []

        if q:
            try:
                papers = json.loads(r.papers_json or "[]")
            except Exception:
                papers = []

            # 收集命中的 papers（这里默认最多返回前 3 个，防止列表太长）
            for p in papers or []:
                if _paper_matches_query(p, q):
                    hit_papers.append(_paper_brief(p))
                    if len(hit_papers) >= 3:
                        break

        items.append({
            "id": r.id,
            "date": r.date.isoformat() if r.date else None,
            "time": r.created_at.strftime("%H:%M") if r.created_at else "",
            "journal": r.journal,
            "code": r.code,
            "category": r.category,
            "title": r.title,

            # ✅ 新增：命中的文章信息（仅 q 存在时才会有）
            "hit_count": len(hit_papers),
            "hit_papers": hit_papers,
        })

    return {"items": items}

@router.get("/{digest_id}", response_model=DigestDetailResponse)
def get_digest(digest_id: int, db: Session = Depends(get_digest_db)):
    r = db.query(DailyDigest).filter(DailyDigest.id == digest_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Not found")

    return {
        "id": r.id,
        "title": r.title,
        "content": r.content,
        "papers": json.loads(r.papers_json or "[]"),
        "date": r.date.isoformat(),
        "journal": r.journal,
    }
