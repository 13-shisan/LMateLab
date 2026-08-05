# backend/routers/academic_reports.py
import json
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/academic-reports", tags=["AcademicReports"])

DATA_FILE = Path(os.getenv("ACADEMIC_REPORTS_FILE", "/var/config/academic_reports.json"))

def load_items():
    if not DATA_FILE.exists():
        return []
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    items = data.get("items", [])
    if not isinstance(items, list):
        return []
    # 按 startAt 新到旧排序
    items.sort(key=lambda x: x.get("startAt", ""), reverse=True)
    return items

@router.get("")
def list_reports(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
):
    items = load_items()
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "page_size": page_size,
    }

@router.get("/latest")
def latest_reports(limit: int = Query(2, ge=1, le=10)):
    items = load_items()
    return {"items": items[:limit]}

@router.get("/{report_id}")
def get_report(report_id: str):
    items = load_items()
    for it in items:
        if it.get("id") == report_id:
            return it
    raise HTTPException(status_code=404, detail="Report not found")
