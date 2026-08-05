# backend/tasks/vasp_custom_add_all.py
from __future__ import annotations

from typing import Any, Dict
from celery import shared_task

from authz_db import resolve_dbset_for_request
from services.vasp_custom_service import add_all_to_custom


@shared_task(bind=True)
def vasp_custom_add_all_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    payload：来自 router 的 AddAllToCustomReq.model_dump() + alias
    """
    def progress(meta: Dict[str, Any]) -> None:
        self.update_state(state="PROGRESS", meta=meta)

    return add_all_to_custom(
        alias=str(payload.get("alias") or "").strip(),
        target=str(payload.get("target") or ""),
        db=payload.get("db"),
        scope=str(payload.get("scope") or "all"),
        only_last=int(payload.get("only_last") or 0),
        elems=payload.get("elems"),
        elem_mode=str(payload.get("elem_mode") or "at_least"),
        cp_filters=payload.get("cp_filters"),
        query=str(payload.get("query") or ""),
        max_rows=int(payload.get("max_rows") or 0),
        resolve_dbset_for_request=resolve_dbset_for_request,  # ✅ 注入
        progress_cb=progress,  # ✅ 进度回调
    )
