# tasks/vasp_scan.py
from __future__ import annotations

import time
import os
import json
import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from ase.db import connect

from celery_app import celery_app
from services.scan_lock import set_current_task_id, clear_current_task_id

logger = logging.getLogger(__name__)

CACHE_DIR = os.getenv("VASP_ELEMENTS_CACHE_DIR", "/tmp")
UPDATE_EVERY = int(os.getenv("VASP_SCAN_PROGRESS_EVERY", "1000"))


def _cache_file_path(dbpath_str: str) -> str:
    h = hashlib.sha1(dbpath_str.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"vasp_elements_cache_{h}.json")


def _write_file_cache(dbpath_str: str, mtime: float, elems: List[str]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_file_path(dbpath_str)
    tmp = f"{path}.tmp.{os.getpid()}"
    payload = {"mtime": mtime, "elements": elems, "updated_at": time.time()}
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)


def _normalize_symbol(sym: str) -> str:
    s = str(sym).strip()
    if not s:
        return ""
    if len(s) == 1:
        return s.upper()
    return s[0].upper() + s[1:].lower()


@celery_app.task(bind=True, name="tasks.vasp_scan.scan_vasp_elements")
def scan_vasp_elements(self, dbpath_str: str) -> Dict[str, Any]:
    task_id = getattr(self.request, "id", None)
    set_current_task_id(dbpath_str, str(task_id), ttl_seconds=60 * 60)

    logger.info(f"[celery] scanning elements db={dbpath_str}, task_id={task_id}")

    p = Path(dbpath_str)
    mtime = p.stat().st_mtime

    elements = set()

    db = connect(dbpath_str)
    try:
        total = int(db.count())
    except Exception:
        total = 0

    current = 0
    self.update_state(
        state="PROGRESS",
        meta={"current": 0, "total": total, "percent": 0.0, "elements_found": 0},
    )

    try:
        for row in db.select():
            current += 1
            try:
                atoms = row.toatoms()
                elements.update(atoms.get_chemical_symbols())
            except Exception as e:
                logger.warning(f"[celery] skip bad row id={getattr(row, 'id', None)}: {e}")

            if current == 1 or (current % UPDATE_EVERY == 0) or (total > 0 and current >= total):
                percent: Optional[float]
                if total > 0:
                    percent = round(current * 100.0 / max(total, 1), 2)
                else:
                    percent = None
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "current": current,
                        "total": total,
                        "percent": percent,
                        "elements_found": len(elements),
                    },
                )

        elems = sorted({_normalize_symbol(s) for s in elements if s})
        _write_file_cache(dbpath_str, mtime, elems)

        return {"mtime": mtime, "elements": elems, "updated_at": time.time(), "total": total}

    finally:
        # 不管成功失败，都清掉“当前 task_id 记录”，避免一直显示扫描中
        clear_current_task_id(dbpath_str, task_id=str(task_id))
