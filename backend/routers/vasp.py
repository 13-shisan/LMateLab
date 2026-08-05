# routers/vasp.py
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List

from services.vasp_service import TaskQuery, query_user_stats

from auth import get_current_user  # 需要稍微改下 auth.py，见后述

router = APIRouter(prefix="/vasp", tags=["vasp"])

class VaspUserStatsRequest(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    keyword: str = ""
    status: Optional[str] = None   # 用逗号分隔多个
    page: int = 1
    limit: int = 10
    elements: str = ""
    exact: bool = False
    full: bool = False

@router.get("/user-stats")
def get_user_stats_api(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    kw: str = Query("", alias="kw"),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=1000),
    elements: str = Query("", alias="elements"),
    exact: bool = Query(False),
    full: bool = Query(False, alias="full"),
    current_user = Depends(get_current_user),
):
    """
    VASP 任务按用户统计（只查本机 vasp_log），
    参数命名与原 Flask /api/user-stats 尽量兼容。
    """
    status_list = None
    if status:
        status_list = [s.strip() for s in status.split(",") if s.strip()]

    q = TaskQuery(
        user=current_user.email,          # 或者 current_user.name，看你希望和 vasp_log.Username 对齐哪个
        is_root=(current_user.role == "admin"),
        start=start,
        end=end,
        keyword=kw or "",
        status_list=status_list,
        page=page,
        limit=limit,
        elements=elements or "",
        exact=exact,
        full_details=full,
    )

    try:
        data = query_user_stats(q)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return data

