# backend/tasks/qe_epw_custom_add_all.py
from __future__ import annotations

from typing import Any, Dict
from celery import shared_task


@shared_task(bind=True)
def qe_epw_custom_add_all_task(self, payload: Dict[str, Any]) -> Dict[str, Any]:
    from routers.qe_epw_db import add_all_rows_to_custom_qe_sync_core  
    def progress(meta: Dict[str, Any]) -> None:
        self.update_state(state="PROGRESS", meta=meta)

    return add_all_rows_to_custom_qe_sync_core(payload, progress_cb=progress)
