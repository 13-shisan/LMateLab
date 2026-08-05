# backend/routers/vasp_stats.py
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List

import sqlite3
from fastapi import APIRouter, Query, HTTPException, Depends

from vasp_db import get_log_conn  # 直连 db/log_vasp.db
from auth import get_current_user
from authz_db import get_allowed_user

router = APIRouter(
    prefix="",
    tags=["vasp-stats"],
)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


# ===========================
#  1. 统计接口 /api/overall-stats
# ===========================
@router.get("/overall-stats")
def overall_stats(
    start: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    end: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    current_user=Depends(get_current_user),
):
    """
    统计每日任务数量 + 状态分布
    数据来自 db/log_vasp.db 的 vasp_log 表。
    """
    start_date = _parse_date(start)
    end_date = _parse_date(end)

    # 默认：最近 7 天（含今天）
    if not start_date and not end_date:
        end_date = date.today()
        start_date = end_date - timedelta(days=6)
    elif start_date and not end_date:
        end_date = date.today()
    elif end_date and not start_date:
        start_date = end_date - timedelta(days=6)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    cond = "WHERE 1=1"
    params: List[Any] = []
    
    alias = (current_user.alias or "").strip()
    me = get_allowed_user(alias)
    is_root = (me.role or "").strip().lower() == "root"

    if not is_root:
        cond += " AND Username = ?"
        params.append(alias)

    cond += " AND DATE(SubmitTime) >= ?"
    params.append(start_date.isoformat())
    cond += " AND DATE(SubmitTime) <= ?"
    params.append(end_date.isoformat())

    sql_daily = f"""
        SELECT DATE(SubmitTime) AS date, COUNT(*) AS cnt
        FROM   vasp_log
        {cond}
        GROUP  BY DATE(SubmitTime)
        ORDER  BY DATE(SubmitTime)
    """

    sql_status = f"""
        SELECT LOWER(REPLACE(Status,'_',' ')) AS status, COUNT(*) AS cnt
        FROM   vasp_log
        {cond}
        GROUP BY LOWER(REPLACE(Status,'_',' '))
    """

    with get_log_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        daily_rows = cur.execute(sql_daily, params).fetchall()
        status_rows = cur.execute(sql_status, params).fetchall()

    date_cnt = {row["date"]: row["cnt"] for row in daily_rows}

    dates: List[str] = []
    counts: List[int] = []
    cur_day = start_date
    while cur_day <= end_date:
        ds = cur_day.strftime("%Y-%m-%d")
        dates.append(ds)
        counts.append(int(date_cnt.get(ds, 0)))
        cur_day += timedelta(days=1)

    status_stats: Dict[str, int] = {}
    for row in status_rows:
        key = row["status"] or "unknown"
        status_stats[key] = int(row["cnt"])

    return {
        "daily_stats": {
            "dates": dates,
            "counts": counts,
        },
        "status_stats": status_stats,
    }


# ===========================
#  2. 列表接口 /api/vasp-tasks
# ===========================
@router.get("/vasp-tasks")
def vasp_tasks(
    start: str | None = Query(None, description="开始日期 YYYY-MM-DD"),
    end: str | None = Query(None, description="结束日期 YYYY-MM-DD"),
    keyword: str | None = Query(
        None, description="兼容旧版的简单关键字（已不推荐）"
    ),
    kw_and: str | None = Query(None, description="AND 关键字，以空格分隔"),
    kw_or: str | None = Query(None, description="OR 关键字，以空格分隔"),
    kw_not: str | None = Query(None, description="NOT 关键字，以空格分隔"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    ignore_date: bool = Query(False, description="是否忽略日期过滤"),
    current_user=Depends(get_current_user),
):
    """
    VASP 任务列表 + 分页。
    - ignore_date = True：忽略日期过滤，查全库
    - ignore_date = False：按 start/end（或默认最近 7 天）过滤
    """

    start_date = _parse_date(start)
    end_date = _parse_date(end)

    cond = "WHERE 1=1"
    params: List[Any] = []
    
    alias = (current_user.alias or "").strip()
    me = get_allowed_user(alias)
    is_root = (me.role or "").strip().lower() == "root"

    if not is_root:
        cond += " AND Username = ?"
        params.append(alias)

    if not ignore_date:
        if not start_date and not end_date:
            end_date = date.today()
            start_date = end_date - timedelta(days=6)
        elif start_date and not end_date:
            end_date = date.today()
        elif end_date and not start_date:
            start_date = end_date - timedelta(days=6)

        if start_date > end_date:
            start_date, end_date = end_date, start_date

        cond += " AND DATE(SubmitTime) >= ?"
        params.append(start_date.isoformat())
        cond += " AND DATE(SubmitTime) <= ?"
        params.append(end_date.isoformat())

    # ---------- 关键字筛选 ----------
    fields = [
        'Username', '"User"', 'Hostname', 'Path', 'JobType',
        'Status', 'SubmitTime', 'EndTime', 'Runtime'
    ]

    # AND：所有词都要匹配
    if kw_and:
        for tok in kw_and.split():
            tok = tok.strip()
            if not tok:
                continue
            like = f"%{tok}%"
            cond_parts = [f"{f} LIKE ?" for f in fields]
            cond += " AND (" + " OR ".join(cond_parts) + ")"
            params.extend([like] * len(fields))

    # OR：任意一个词即可
    if kw_or:
        or_conditions: List[str] = []
        or_params: List[Any] = []
        for tok in kw_or.split():
            tok = tok.strip()
            if not tok:
                continue
            like = f"%{tok}%"
            or_conditions.extend([f"{f} LIKE ?" for f in fields])
            or_params.extend([like] * len(fields))
        if or_conditions:
            cond += " AND (" + " OR ".join(or_conditions) + ")"
            params.extend(or_params)

    # NOT：排除包含这些词的记录
    if kw_not:
        for tok in kw_not.split():
            tok = tok.strip()
            if not tok:
                continue
            like = f"%{tok}%"
            not_parts = [f"{f} NOT LIKE ?" for f in fields]
            cond += " AND (" + " AND ".join(not_parts) + ")"
            params.extend([like] * len(fields))

    # 兼容旧的 keyword（简单 OR）
    if keyword and not (kw_and or kw_or or kw_not):
        kw = f"%{keyword.strip()}%"
        simple_fields = [
            'Username', '"User"', 'Hostname', 'Path', 'JobType',
            'Status', 'SubmitTime', 'EndTime'
            # Runtime 如有需要再加
        ]
        cond_parts = [f"{f} LIKE ?" for f in simple_fields]
        cond += " AND (" + " OR ".join(cond_parts) + ")"
        params.extend([kw] * len(simple_fields))

    sql_count = f"SELECT COUNT(*) AS c FROM vasp_log {cond}"

    offset = (page - 1) * page_size
    sql_page = f"""
        SELECT
            Path,
            JobID,
            Username,
            "User"      AS user_cn,
            Hostname,
            JobType,
            SubmitTime,
            EndTime,
            Runtime,
            Status
        FROM vasp_log
        {cond}
        ORDER BY SubmitTime DESC
        LIMIT ? OFFSET ?
    """

    with get_log_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        total = cur.execute(sql_count, params).fetchone()["c"]
        rows = cur.execute(sql_page, params + [page_size, offset]).fetchall()

    items = [
        {
            "path": r["Path"],
            "job_id": r["JobID"],
            "username": r["Username"],
            "user_cn": r["user_cn"],
            "hostname": r["Hostname"],
            "job_type": r["JobType"],
            "submit_time": r["SubmitTime"],
            "end_time": r["EndTime"],
            "runtime": r["Runtime"],
            "status": r["Status"],
        }
        for r in rows
    ]

    return {
        "total": int(total),
        "page": page,
        "page_size": page_size,
        "items": items,
    }


# ===========================
#  3. 详情接口 /api/vasp-task-detail
# ===========================
@router.get("/vasp-task-detail")
def vasp_task_detail(
    job_id: str = Query(..., description="JobID，如 Dell_1756864310"),
    current_user=Depends(get_current_user),
):
    """
    单个任务详情。
    直接从 vasp_log 把整行字段取出来，按列名转成 JSON。
    """
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id 不能为空")

    with get_log_conn() as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        row = cur.execute(
            "SELECT * FROM vasp_log WHERE JobID = ? LIMIT 1", (job_id,)
        ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="未找到该任务")

    alias = (current_user.alias or "").strip()
    me = get_allowed_user(alias)
    is_root = (me.role or "").strip().lower() == "root"

    owner = (row["Username"] or "").strip()
    if (not is_root) and owner != alias:
        raise HTTPException(status_code=403, detail="permission denied")

    detail = {k: row[k] for k in row.keys()}
    return detail