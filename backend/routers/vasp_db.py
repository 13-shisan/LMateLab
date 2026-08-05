# backend/routers/vasp_db.py
from __future__ import annotations

import os
import re
import json
import time
import hashlib
import gzip
import pickle
from threading import Lock, Thread
import uuid
from typing import Any, Dict, List, Optional, Tuple
from ase.db import connect
from ase.formula import Formula
import tempfile
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel
import base64
from io import BytesIO
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from starlette.background import BackgroundTask
import numpy as np

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from ase.io import write as ase_write
try:
    import redis  # pip install redis
except Exception:
    redis = None

from auth import get_current_user
from authz_db import (
    list_accessible_owners,
    resolve_dbset_for_request,
    resolve_db_for_request,   # 兼容：你某些地方如果还想单库用
)

from services.ase_db_service import get_elements_in_ase_db
from services.vasp_table_schema import (
    DEFAULT_VASP_COLUMNS,
    build_relax_ids_sqlite,
    build_filtered_cache_identity,
    column_metadata,
    order_ids,
    search_formula_ids,
    summarize_database_refs,
)
from services.vasp_task_detail import build_public_task_detail, get_optional_ase_row

import subprocess
from fastapi import UploadFile, File, HTTPException, Body

from services.user_uploads import (
    is_alias_allowed,
    ensure_user_upload_dir,
    user_upload_db_path,
)

from celery.result import AsyncResult

VASP_IMPORT_SCRIPT = os.getenv(
    "VASP_IMPORT_SCRIPT",
    "/app/utils/spin-ase-data.py",
)
VASP_IMPORT_TIMEOUT = int(os.getenv("VASP_IMPORT_TIMEOUT", "1800"))  # 30min
MAX_UPLOAD_BYTES = int(os.getenv("VASP_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024 * 1024)))  # 10000MB

router = APIRouter(prefix="/db/vasp", tags=["vasp-db"])

UPLOADS_ROOT = Path(os.getenv(
    "VASP_UPLOADS_ROOT",
    "/app/var/uploads"
)).resolve()

CUSTOM_DB_ROOT = Path(os.getenv(
    "VASP_CUSTOM_DB_ROOT",
    "/app/var/Customized_database/vasp"
)).resolve()

AVOGADRO = 6.02214076e23  # mol^-1

# -----------------------------
# Config (env)
# -----------------------------
VASP_SCAN_BACKEND = os.getenv("VASP_SCAN_BACKEND", "daemon").lower()  # daemon | celery
CACHE_DIR = os.getenv("VASP_ELEMENTS_CACHE_DIR", "/tmp")
print("VASP_ELEMENTS_CACHE_DIR =", CACHE_DIR)

CACHE_VERSION = "v3"  # 改逻辑就改这里，自动失效旧缓存

# 用现有 celery broker 作为锁的 redis
REDIS_LOCK_URL = os.getenv("CELERY_BROKER_URL", "")
REDIS_LOCK_ENABLED = bool(REDIS_LOCK_URL) and (redis is not None)

_redis_client = None
_redis_client_lock = Lock()

def _get_redis():
    global _redis_client
    if not REDIS_LOCK_ENABLED:
        return None
    with _redis_client_lock:
        if _redis_client is None:
            _redis_client = redis.Redis.from_url(REDIS_LOCK_URL, decode_responses=True)
        return _redis_client

def _acquire_dist_lock(lock_key: str, ttl: int = 300) -> Optional[str]:
    """
    简易 Redis 锁：SET key value NX EX ttl
    返回 token（成功）或 None（失败）
    """
    r = _get_redis()
    if r is None:
        return None
    token = str(uuid.uuid4())
    ok = r.set(lock_key, token, nx=True, ex=int(ttl))
    return token if ok else None


def _release_dist_lock(lock_key: str, token: str) -> None:
    """
    只释放自己持有的锁（compare-and-del）。
    """
    r = _get_redis()
    if r is None:
        return
    # Lua: if get(key)==token then del(key) end
    lua = """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    else
        return 0
    end
    """
    try:
        r.eval(lua, 1, lock_key, token)
    except Exception:
        pass


def _wait_for_file(path: str, timeout: float = 60.0, interval: float = 0.2) -> bool:
    """
    等待另一个进程生成缓存文件（用于锁没抢到时）。
    """
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(path):
            return True
        time.sleep(interval)
    return os.path.exists(path)

# Redis dedupe configs (only used in celery mode)
SCAN_ENQUEUE_LOCK_TTL = int(os.getenv("VASP_SCAN_ENQUEUE_LOCK_TTL", str(60 * 2)))   # 秒：防重复入队
SCAN_TASK_ID_TTL = int(os.getenv("VASP_SCAN_TASK_ID_TTL", str(60 * 60)))            # 秒：记录当前 task_id

# -----------------------------
# In-memory elements cache
# key: dbpath str
# value: (mtime, elements_list, updated_at, source)
# -----------------------------
_cache_lock = Lock()
_elements_cache: Dict[str, Tuple[float, List[str], float, str]] = {}
_scanning: Dict[str, Dict[str, Any]] = {}  # key -> {started_at, task_id?}  (daemon 模式主要用这个)

# -----------------------------
# In-memory relax cache
# key: dbpath str
# value: (mtime, ids_list) where ids_list contains "best row id" per source_dir
# -----------------------------
_relax_cache: Dict[str, Tuple[float, List[int]]] = {}
_relax_cache_lock = Lock()

# -----------------------------
# In-memory elements index cache (for filtering by formula elements)
# key: dbpath str
# value: (mtime, index) where index: symbol -> sorted list[int(row_id)]
# -----------------------------
_elem_index_cache: Dict[str, Tuple[float, Dict[str, List[int]]]] = {}
_elem_index_lock = Lock()

# -----------------------------
# In-memory cp index cache
# key: (dbpath_str, mtime, only_last, cp_path)
# value: (mtime, index) where index: canon_value -> sorted list[int(row_id)]
# -----------------------------
_cp_index_cache: Dict[Tuple[str, float, int, str], Dict[str, List[int]]] = {}
_cp_index_lock = Lock()

# -----------------------------
# In-memory highlight cache
# key: (dbpath_str, mtime, only_last, mode, tuple(selected_elems))
# value: sorted list[str]  (highlight elements)
# -----------------------------
_highlight_cache: Dict[Tuple[str, float, int, str, Tuple[str, ...]], List[str]] = {}
_highlight_cache_lock = Lock()

# -----------------------------
# In-memory filtered-ids cache (for export/tasks merge)
# key: (dbpath_str, mtime, only_last, elem_mode, tuple(selected_elems), cp_key)
# value: sorted list[int(row_id)] or None means "full table"
# -----------------------------
_filtered_ids_cache: Dict[Tuple[str, float, int, str, Tuple[str, ...], str], Optional[List[int]]] = {}
_filtered_ids_lock = Lock()

# -----------------------------
# Aggregated elements cache for owner/scope (memory + file)
# key: sha1(requested+scope+filters+refs mtimes)
# value: sorted list[str]
# -----------------------------
_agg_elems_lock = Lock()
_agg_elems_mem: Dict[str, Dict[str, Any]] = {}  # key -> {"mt":time, "elements":[...], "payload":...}

_all_ids_cache: Dict[Tuple[str, float], List[int]] = {}
_all_ids_lock = Lock()

def _all_ids_file_path(dbpath_str: str) -> str:
    h = hashlib.sha1(dbpath_str.encode("utf-8")).hexdigest()
    return os.path.join(CACHE_DIR, f"vasp_all_ids_{h}.json")

def _get_all_ids_cached(con, dbpath_str: str, mtime: float) -> List[int]:
    key = (dbpath_str, float(mtime))

    with _all_ids_lock:
        hit = _all_ids_cache.get(key)
        if hit is not None:
            return hit

    # file
    fp = _all_ids_file_path(dbpath_str)
    if os.path.exists(fp):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict) and abs(float(payload.get("mtime", -1)) - float(mtime)) <= 1e-6:
                ids = payload.get("ids")
                if isinstance(ids, list):
                    out = [int(x) for x in ids]
                    with _all_ids_lock:
                        _all_ids_cache[key] = out
                    return out
        except Exception:
            pass

    # compute (lock optional)
    ids_all: List[int] = []
    for r in con.select():
        rid = getattr(r, "id", None)
        if rid is not None:
            ids_all.append(int(rid))
    ids_all.sort()

    with _all_ids_lock:
        _all_ids_cache[key] = ids_all

    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = f"{fp}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"mtime": float(mtime), "ids": ids_all, "updated_at": time.time()}, f, ensure_ascii=False)
        os.replace(tmp, fp)
    except Exception:
        pass

    return ids_all

# -----------------------------
# File cache for filtered-ids (optional but requested)
# persist across reload/restart
# -----------------------------
def _filtered_ids_cache_file_name(
    dbpath_str: str,
    only_last: int,
    elem_mode: str,
    selected: List[str],
    cp_flts: List[Dict[str, Any]],
    row_flts: List[Dict[str, Any]],
    query: str,
) -> str:
    h = build_filtered_cache_identity(
        dbpath=dbpath_str,
        only_last=only_last,
        elem_mode=elem_mode,
        selected=selected,
        cp_filters=cp_flts,
        row_filters=row_flts,
        query=query,
    )
    return f"vasp_filtered_ids_{h}.pkl.gz"

def _filtered_ids_cache_file_path(dbpath_str: str, only_last: int, elem_mode: str, selected: List[str], cp_flts: List[Dict[str, Any]], row_flts: List[Dict[str, Any]], query: str) -> str:
    return os.path.join(CACHE_DIR, _filtered_ids_cache_file_name(dbpath_str, only_last, elem_mode, selected, cp_flts, row_flts, query))

def _read_filtered_ids_file_cache(dbpath_str: str, mtime: float, only_last: int, elem_mode: str, selected: List[str], cp_flts: List[Dict[str, Any]], row_flts: List[Dict[str, Any]], query: str) -> Optional[Optional[List[int]]]:
    path = _filtered_ids_cache_file_path(dbpath_str, only_last, elem_mode, selected, cp_flts, row_flts, query)
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rb") as f:
            payload = pickle.load(f)
        if not isinstance(payload, dict):
            return None
        cached_mtime = float(payload.get("mtime", -1))
        if abs(cached_mtime - mtime) > 1e-6:
            return None
        # ids 可以是 list 或 None（None 表示“全表”）
        ids = payload.get("ids", None)
        if ids is None:
            return None  # 这里我们不缓存 “全表 None”，避免误导（全表直接扫）
        if not isinstance(ids, list):
            return None
        out: List[int] = []
        for x in ids:
            try:
                out.append(int(x))
            except Exception:
                continue
        return out
    except Exception:
        return None

def _write_filtered_ids_file_cache(dbpath_str: str, mtime: float, only_last: int, elem_mode: str, selected: List[str], cp_flts: List[Dict[str, Any]], row_flts: List[Dict[str, Any]], query: str, ids: List[int]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _filtered_ids_cache_file_path(dbpath_str, only_last, elem_mode, selected, cp_flts, row_flts, query)
    tmp = f"{path}.tmp.{os.getpid()}"
    payload = {"mtime": float(mtime), "ids": [int(x) for x in ids], "updated_at": time.time()}
    with gzip.open(tmp, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)

# -----------------------------
# Fast path cache for: selected_elems size == 1 and mode == "at_least"
# We cache union-of-elements for each single element.
# key: (dbpath_str, mtime, only_last)
# value: {elem_symbol -> sorted list[str]}
# -----------------------------
_single_atleast_cache: Dict[Tuple[str, float, int], Dict[str, List[str]]] = {}
_single_atleast_lock = Lock()

def _parse_formula_elements(formula: Any) -> List[str]:
    """从 row.formula 解析元素符号列表（去重后返回）"""
    if not formula:
        return []
    try:
        f = Formula(str(formula))
        # f.count() -> dict {sym: n}
        return list(f.count().keys())
    except Exception:
        return []

def _get_cp_index(dbpath_str: str, mtime: float, only_last: int, cp_path: str) -> Dict[str, List[int]]:
    """
    构建/读取 cp_path 的倒排索引：
    canon_value -> [row_id...]
    """
    cp_path = _normalize_cp_path(cp_path)  # ✅ 统一 path，避免重复索引/缓存命中失败
    key = (dbpath_str, mtime, int(only_last), cp_path)

    # 1) 内存
    with _cp_index_lock:
        hit = _cp_index_cache.get(key)
        if hit is not None:
            return hit

    # 2) 文件
    file_idx = _read_cp_index_file_cache(dbpath_str, mtime, only_last, cp_path)
    if file_idx is not None:
        with _cp_index_lock:
            _cp_index_cache[key] = file_idx
        return file_idx

    # 3) 计算（加分布式锁防并发重复构建）
    lock_key = f"vasp:cp_index:{hashlib.sha1((dbpath_str+'|'+cp_path).encode('utf-8')).hexdigest()}:{mtime}:relax{int(only_last)}"
    token = _acquire_dist_lock(lock_key, ttl=1200)

    if token is None and REDIS_LOCK_ENABLED:
        _wait_for_file(_cp_index_cache_file_path(dbpath_str, only_last, cp_path), timeout=240.0, interval=0.25)
        file_idx2 = _read_cp_index_file_cache(dbpath_str, mtime, only_last, cp_path)
        if file_idx2 is not None:
            with _cp_index_lock:
                _cp_index_cache[key] = file_idx2
            return file_idx2

    try:
        idx: Dict[str, List[int]] = {}
        with connect(dbpath_str) as con:
            base_ids = _get_base_ids_for_elements(con, dbpath_str, mtime, int(only_last))

            if base_ids is None:
                rows_iter = con.select()
            else:
                rows_iter = (con.get(id=rid) for rid in base_ids)

            for r in rows_iter:
                if r is None:
                    continue
                rid = getattr(r, "id", None)
                if rid is None:
                    continue

                v = _get_cp_value(r, cp_path)
                cv = _cp_canon(v)
                idx.setdefault(cv, []).append(int(rid))

        for k in idx.keys():
            idx[k].sort()

        try:
            _write_cp_index_file_cache(dbpath_str, mtime, only_last, cp_path, idx)
        except Exception:
            pass

        with _cp_index_lock:
            _cp_index_cache[key] = idx

        return idx
    finally:
        if token:
            _release_dist_lock(lock_key, token)

def _get_elem_index(dbpath_str: str, mtime: float) -> Dict[str, List[int]]:
    """返回元素->row_id列表的倒排索引（按 db mtime 缓存；支持落盘）"""

    # 1) 内存缓存
    with _elem_index_lock:
        item = _elem_index_cache.get(dbpath_str)
        if item and abs(item[0] - mtime) <= 1e-6:
            return item[1]

    # 2) 文件缓存（跨重启/多进程）
    file_idx = _read_elem_index_file_cache(dbpath_str, mtime)
    if file_idx is not None:
        with _elem_index_lock:
            _elem_index_cache[dbpath_str] = (mtime, file_idx)
        return file_idx

    # 3) 全库扫描构建（加分布式锁，避免并发重复构建）
    lock_key = f"vasp:elem_index:{hashlib.sha1(dbpath_str.encode('utf-8')).hexdigest()}:{mtime}"
    token = _acquire_dist_lock(lock_key, ttl=1800)  # 10 分钟够扫 20~30 万行了

    if token is None and REDIS_LOCK_ENABLED:
        # 没抢到锁：说明别人正在构建 → 等它写好文件，然后再读一次文件缓存
        _wait_for_file(_elem_index_cache_file_path(dbpath_str), timeout=120.0, interval=0.25)
        file_idx2 = _read_elem_index_file_cache(dbpath_str, mtime)
        if file_idx2 is not None:
            with _elem_index_lock:
                _elem_index_cache[dbpath_str] = (mtime, file_idx2)
            return file_idx2
        # 等不到/读不到就退化为自己构建（容错）

    try:
        index: Dict[str, List[int]] = {}
        with connect(dbpath_str) as con:
            for r in con.select():
                rid = getattr(r, "id", None)
                if rid is None:
                    continue
                syms = _parse_formula_elements(getattr(r, "formula", None))
                for s in syms:
                    index.setdefault(s, []).append(int(rid))

        for s in index.keys():
            index[s].sort()

        # 写缓存：文件 + 内存
        try:
            _write_elem_index_file_cache(dbpath_str, mtime, index)
        except Exception:
            pass

        with _elem_index_lock:
            _elem_index_cache[dbpath_str] = (mtime, index)

        return index
    finally:
        if token:
            _release_dist_lock(lock_key, token)

def _intersect_sorted(a: List[int], b: List[int]) -> List[int]:
    i = j = 0
    out: List[int] = []
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            out.append(a[i]); i += 1; j += 1
        elif a[i] < b[j]:
            i += 1
        else:
            j += 1
    return out

def _union_sorted(a: List[int], b: List[int]) -> List[int]:
    i = j = 0
    out: List[int] = []
    while i < len(a) and j < len(b):
        if a[i] == b[j]:
            out.append(a[i]); i += 1; j += 1
        elif a[i] < b[j]:
            out.append(a[i]); i += 1
        else:
            out.append(b[j]); j += 1
    if i < len(a):
        out.extend(a[i:])
    if j < len(b):
        out.extend(b[j:])
    return out

def _group_cp_filters_or(cp_flts: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """
    把 cp_filters 按 path 分组：
      - 同 path 多个 value => OR
      - 允许 value 直接是 list，例如 {"path":"ediff","value":[1e-5,1e-4]}
    return: path -> list[canon_value]
    """
    g: Dict[str, List[str]] = {}
    for flt in cp_flts:
        path = str(flt.get("path", "")).strip()
        if not path:
            continue
        v = flt.get("value", None)
        vals = v if isinstance(v, list) else [v]
        for one in vals:
            g.setdefault(path, []).append(_cp_target_canon(one))

    # 去重（保序）
    for p, arr in g.items():
        seen = set()
        uniq: List[str] = []
        for x in arr:
            if x not in seen:
                uniq.append(x); seen.add(x)
        g[p] = uniq

    return g

from heapq import heappush, heappop
from typing import Iterator

def _merge_page_pairs_kway(
    per_db_ids: Dict[str, List[int]],
    offset: int,
    limit: int,
    sort_order: str = "asc",
) -> List[Tuple[str, int]]:
    """
    多路归并：per_db_ids 每个列表都要求已排序（你的 filtered_ids 本来就 sort 了）。
    返回按 (dbKey, rowId) 排序后的第 offset..offset+limit-1 条。
    复杂度：O((offset+limit) log K)，不会 O(N log N)。
    """
    if limit <= 0:
        return []

    # 为了和你原来 merged.sort(key=(dbKey,rowId)) 一致，dbKey 也要参与排序
    keys = sorted(per_db_ids.keys())

    descending = str(sort_order or "asc").lower() == "desc"
    heap: List[Tuple[str, int, int]] = []  # (dbKey, sortable rowId, idx_in_list)
    for k in keys:
        ids = per_db_ids.get(k) or []
        if ids:
            idx = len(ids) - 1 if descending else 0
            rid = int(ids[idx])
            heappush(heap, (k, -rid if descending else rid, idx))

    out: List[Tuple[str, int]] = []
    need = offset + limit
    seen = 0

    while heap and seen < need:
        k, sortable_rid, idx = heappop(heap)
        rid = -sortable_rid if descending else sortable_rid
        if seen >= offset:
            out.append((k, rid))
        seen += 1

        ids = per_db_ids.get(k) or []
        nxt = idx - 1 if descending else idx + 1
        if 0 <= nxt < len(ids):
            next_rid = int(ids[nxt])
            heappush(heap, (k, -next_rid if descending else next_rid, nxt))

    return out

def _normalize_elem_list(elems: Optional[str]) -> List[str]:
    if not elems:
        return []
    out = []
    for x in elems.split(","):
        s = x.strip()
        if not s:
            continue
        if len(s) == 1:
            s = s.upper()
        else:
            s = s[0].upper() + s[1:].lower()
        out.append(s)
    # 去重但保持顺序
    seen = set()
    uniq = []
    for s in out:
        if s not in seen:
            uniq.append(s); seen.add(s)
    return uniq

def _get_base_ids_for_elements(con, dbpath_str: str, mtime: float, only_last: int) -> Optional[List[int]]:
    """
    返回 base_ids:
    - only_last=0: None （表示后续可用 con.select() 全表；但我们会尽量走索引）
    - only_last=1: 返回 relax_ids（已排序）
    """
    if only_last != 1:
        return None

    relax_ids = _get_relax_ids_cache(dbpath_str, mtime)
    if relax_ids is not None:
        return relax_ids

    lock_key = f"vasp:relax_ids:{hashlib.sha1((dbpath_str + '|' + str(mtime)).encode('utf-8')).hexdigest()}"
    token = _acquire_dist_lock(lock_key, ttl=300)
    if not token:
        _wait_for_file(_relax_cache_file_path(dbpath_str), timeout=180.0, interval=0.25)
        relax_ids = _get_relax_ids_cache(dbpath_str, mtime)
        if relax_ids is not None:
            return relax_ids

    try:
        # Recheck after taking the lock because another worker may have just completed it.
        relax_ids = _get_relax_ids_cache(dbpath_str, mtime)
        if relax_ids is not None:
            return relax_ids

        try:
            relax_ids = build_relax_ids_sqlite(dbpath_str)
        except Exception:
            # Compatibility fallback for non-standard ASE databases.
            best: Dict[str, Tuple[int, int]] = {}
            for row in con.select():
                data = getattr(row, "data", None) or {}
                if not isinstance(data, dict):
                    continue
                source_dir = data.get("source_dir")
                if not source_dir:
                    continue
                try:
                    step = int(data.get("step_index", -1))
                except Exception:
                    step = -1
                row_id = getattr(row, "id", None)
                if row_id is None:
                    continue
                previous = best.get(source_dir)
                if previous is None or step > previous[0]:
                    best[source_dir] = (step, int(row_id))
            relax_ids = sorted(row_id for _step, row_id in best.values())

        _set_relax_ids_cache(dbpath_str, mtime, relax_ids)
        _write_relax_file_cache(dbpath_str, mtime, relax_ids)
        return relax_ids
    finally:
        if token:
            _release_dist_lock(lock_key, token)


def _get_single_atleast_map(dbpath_str: str, mtime: float, only_last: int) -> Dict[str, List[str]]:
    """
    预计算：对每个元素 e，所有包含 e 的结构里出现过的元素 union（准确）。
    用于 “只选一个元素 + at_least” 的极速响应。
    支持落盘缓存，避免重启/多进程重复扫描。
    """
    key = (dbpath_str, mtime, int(only_last))

    # 1) 内存缓存
    with _single_atleast_lock:
        hit = _single_atleast_cache.get(key)
        if hit is not None:
            return hit

    # 2) 文件缓存
    file_map = _read_single_atleast_file_cache(dbpath_str, mtime, only_last)
    if file_map is not None:
        with _single_atleast_lock:
            _single_atleast_cache[key] = file_map
        return file_map

    # 3) 计算（首次慢一次；加分布式锁避免并发重复构建）
    lock_key = f"vasp:single_atleast:{hashlib.sha1(dbpath_str.encode('utf-8')).hexdigest()}:{mtime}:relax{int(only_last)}"
    token = _acquire_dist_lock(lock_key, ttl=1800)

    if token is None and REDIS_LOCK_ENABLED:
        # 没抢到锁：等对方写好文件再读
        _wait_for_file(_single_atleast_cache_file_path(dbpath_str, only_last), timeout=120.0, interval=0.25)
        file_map2 = _read_single_atleast_file_cache(dbpath_str, mtime, only_last)
        if file_map2 is not None:
            with _single_atleast_lock:
                _single_atleast_cache[key] = file_map2
            return file_map2
        # 等不到就退化为自己算（容错）

    try:
        union_map: Dict[str, set] = {}
        with connect(dbpath_str) as con:
            base_ids = _get_base_ids_for_elements(con, dbpath_str, mtime, only_last)

            if base_ids is None:
                rows_iter = con.select()
            else:
                rows_iter = (con.get(id=rid) for rid in base_ids)

            for r in rows_iter:
                if r is None:
                    continue
                syms = _parse_formula_elements(getattr(r, "formula", None))
                if not syms:
                    continue
                sset = set(syms)
                for e in sset:
                    union_map.setdefault(e, set()).update(sset)

        out: Dict[str, List[str]] = {e: sorted(list(v)) for e, v in union_map.items()}

        try:
            _write_single_atleast_file_cache(dbpath_str, mtime, only_last, out)
        except Exception:
            pass

        with _single_atleast_lock:
            _single_atleast_cache[key] = out

        return out
    finally:
        if token:
            _release_dist_lock(lock_key, token)

# -----------------------------
# File cache helpers
# -----------------------------
# -----------------------------
# Relax file cache helpers (persist across reload/restart)
# -----------------------------
def _relax_cache_file_name(dbpath_str: str) -> str:
    h = hashlib.sha1(dbpath_str.encode("utf-8")).hexdigest()
    return f"vasp_relax_ids_cache_{h}.json"


def _relax_cache_file_path(dbpath_str: str) -> str:
    return os.path.join(CACHE_DIR, _relax_cache_file_name(dbpath_str))


def _read_relax_file_cache(dbpath_str: str, mtime: float) -> Optional[List[int]]:
    """
    Read relax_ids cache file if exists and mtime matches.
    """
    path = _relax_cache_file_path(dbpath_str)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None

        cached_mtime = float(data.get("mtime", -1))
        if abs(cached_mtime - mtime) > 1e-6:
            return None

        ids = data.get("ids")
        if not isinstance(ids, list):
            return None

        out: List[int] = []
        for x in ids:
            try:
                out.append(int(x))
            except Exception:
                continue
        return out
    except Exception:
        return None


def _write_relax_file_cache(dbpath_str: str, mtime: float, ids: List[int]) -> None:
    """
    Write relax_ids cache file (atomic replace).
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _relax_cache_file_path(dbpath_str)
    tmp = f"{path}.tmp.{os.getpid()}"

    payload = {
        "mtime": mtime,
        "ids": [int(x) for x in ids],
        "updated_at": time.time(),
    }

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    os.replace(tmp, path)
    
def _band_dat_text_from_vasprun(vasprun_path: str, align: str = "fermi") -> str:
    from pymatgen.io.vasp import Vasprun
    from pymatgen.electronic_structure.core import Spin

    vr = Vasprun(vasprun_path)
    bs = vr.get_band_structure(line_mode=True)

    distances = bs.distance
    efermi = float(bs.efermi)
    shift = efermi if (align or "fermi").lower() == "fermi" else 0.0

    lines: List[str] = []
    lines.append("# band.dat generated (vasprun)")
    lines.append(f"# EFERMI(eV): {efermi:.8f}")
    lines.append(f"# ALIGN: {align}")
    lines.append("# Columns: k_dist  energy_eV")
    lines.append("")

    for sp in bs.bands.keys():
        sp_label = "up" if sp == Spin.up else "down"
        lines.append(f"# Spin: {sp_label}")
        arr = bs.bands[sp]  # (nbands, nkpts)
        for ib in range(arr.shape[0]):
            lines.append(f"# Band-Index: {ib+1}")
            es = arr[ib] - shift
            for ik, d in enumerate(distances):
                lines.append(f"{float(d):10.5f} {float(es[ik]):14.6f}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"

# 导出： band.dat 与 dos_data.zip
def _band_dat_text_from_outcar(outcar_path: str, align: str = "fermi") -> str:
    parsed = _parse_outcar_band(outcar_path)
    efermi = float(parsed["efermi"] or 0.0)
    shift = efermi if (align or "fermi").lower() == "fermi" else 0.0
    dists = _k_distances_frac(parsed["kpoints"])
    spins_arrays: Dict[int, np.ndarray] = parsed["eigenvals"]

    lines: List[str] = []
    lines.append("# band.dat generated (OUTCAR fallback)")
    lines.append(f"# EFERMI(eV): {efermi:.8f}")
    lines.append(f"# ALIGN: {align}")
    lines.append("# Columns: k_dist  energy_eV")
    lines.append("")

    for sp, arr in spins_arrays.items():
        if len(spins_arrays) > 1:
            lines.append(f"# Spin: {'up' if sp == 1 else 'down'}")
        for ib in range(arr.shape[0]):
            lines.append(f"# Band-Index: {ib+1}")
            es = arr[ib] - shift
            for ik, d in enumerate(dists):
                lines.append(f"{float(d):10.5f} {float(es[ik]):14.6f}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"

import zipfile
import io

def _dos_zip_bytes_from_vasprun(vasprun_path: str, align: str = "fermi", decimate: int = 1) -> bytes:
    from pymatgen.io.vasp import Vasprun
    from pymatgen.electronic_structure.core import Spin

    decimate = max(1, int(decimate))
    vr = Vasprun(vasprun_path, parse_projected_eigen=False, parse_potcar_file=False)
    dos = vr.complete_dos
    efermi = float(dos.efermi)

    energies = dos.energies
    if (align or "fermi").lower() == "fermi":
        energies = energies - efermi

    energies = energies[::decimate]
    up = dos.densities.get(Spin.up)
    dn = dos.densities.get(Spin.down)

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        def _write(name: str, header: str, y: np.ndarray):
            lines = []
            lines.append(header)
            lines.append(f"# EFERMI(eV): {efermi:.8f}")
            lines.append(f"# ALIGN: {align}")
            lines.append("# Energy  DOS")
            for i in range(len(y)):
                lines.append(f"{float(energies[i]):12.6f}{float(y[i]):12.6f}")
            zf.writestr(name, "\n".join(lines) + "\n")

        if up is not None and dn is not None:
            up = up[::decimate]
            dn = dn[::decimate]
            _write("TDOS_up.dat", "# TDOS up (up>0)", up)
            _write("TDOS_down.dat", "# TDOS down (stored negative)", -dn)
            _write("TDOS_total.dat", "# TDOS total (up+down)", up + dn)
        else:
            tot = dos.get_densities()[::decimate]
            _write("TDOS.dat", "# TDOS (non-spin)", tot)

    bio.seek(0)
    return bio.read()

def _dos_zip_bytes_from_outcar(outcar_path: str, align: str = "fermi", decimate: int = 1) -> bytes:
    decimate = max(1, int(decimate))
    energies_raw, col2, col3, efermi = _parse_outcar_dos_simple(outcar_path)

    energies = energies_raw
    if (align or "fermi").lower() == "fermi":
        energies = energies - float(efermi)

    energies = energies[::decimate]
    col2 = col2[::decimate]
    col3 = col3[::decimate] if (col3 is not None and len(col3) >= len(col2)) else None

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        def _write(name: str, header: str, y: np.ndarray):
            lines = []
            lines.append(header)
            lines.append(f"# EFERMI(eV): {float(efermi):.8f}")
            lines.append(f"# ALIGN: {align}")
            lines.append("# Energy  DOS")
            for i in range(len(y)):
                lines.append(f"{float(energies[i]):12.6f}{float(y[i]):12.6f}")
            zf.writestr(name, "\n".join(lines) + "\n")

        if col3 is not None and len(col3) == len(col2):
            _write("TDOS_up.dat", "# TDOS up (OUTCAR, up>0)", col2)
            _write("TDOS_down.dat", "# TDOS down (OUTCAR, stored negative)", -col3)
            _write("TDOS_total.dat", "# TDOS total (OUTCAR, up+down)", col2 + col3)
        else:
            _write("TDOS.dat", "# TDOS (OUTCAR, non-spin)", col2)

    bio.seek(0)
    return bio.read()

    
# -----------------------------
# Elem index file cache helpers (persist across reload/restart)
# -----------------------------
def _elem_index_cache_file_name(dbpath_str: str) -> str:
    h = hashlib.sha1(dbpath_str.encode("utf-8")).hexdigest()
    return f"vasp_elem_index_cache_{h}.pkl.gz"


def _elem_index_cache_file_path(dbpath_str: str) -> str:
    return os.path.join(CACHE_DIR, _elem_index_cache_file_name(dbpath_str))

def _cp_index_cache_file_name(dbpath_str: str, only_last: int, cp_path: str) -> str:
    h = hashlib.sha1((dbpath_str + "|" + cp_path).encode("utf-8")).hexdigest()
    return f"vasp_cp_index_cache_{h}_relax{int(only_last)}.pkl.gz"

def _cp_index_cache_file_path(dbpath_str: str, only_last: int, cp_path: str) -> str:
    return os.path.join(CACHE_DIR, _cp_index_cache_file_name(dbpath_str, only_last, cp_path))

def _read_cp_index_file_cache(dbpath_str: str, mtime: float, only_last: int, cp_path: str) -> Optional[Dict[str, List[int]]]:
    path = _cp_index_cache_file_path(dbpath_str, only_last, cp_path)
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rb") as f:
            payload = pickle.load(f)
        if not isinstance(payload, dict):
            return None
        cached_mtime = float(payload.get("mtime", -1))
        if abs(cached_mtime - mtime) > 1e-6:
            return None
        idx = payload.get("index")
        if not isinstance(idx, dict):
            return None
        return idx
    except Exception:
        return None

def _write_cp_index_file_cache(dbpath_str: str, mtime: float, only_last: int, cp_path: str, index: Dict[str, List[int]]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cp_index_cache_file_path(dbpath_str, only_last, cp_path)
    tmp = f"{path}.tmp.{os.getpid()}"

    payload = {"mtime": mtime, "only_last": int(only_last), "cp_path": cp_path, "index": index, "updated_at": time.time()}
    with gzip.open(tmp, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def _read_elem_index_file_cache(dbpath_str: str, mtime: float) -> Optional[Dict[str, List[int]]]:
    """
    Read elem_index cache (gzip+pickle). Returns index or None.
    """
    path = _elem_index_cache_file_path(dbpath_str)
    if not os.path.exists(path):
        return None
    try:
        with gzip.open(path, "rb") as f:
            payload = pickle.load(f)
        if not isinstance(payload, dict):
            return None
        cached_mtime = float(payload.get("mtime", -1))
        if abs(cached_mtime - mtime) > 1e-6:
            return None
        index = payload.get("index")
        if not isinstance(index, dict):
            return None
        # 简单校验：value 应该是 list
        for k, v in index.items():
            if not isinstance(k, str) or not isinstance(v, list):
                return None
        return index
    except Exception:
        return None


def _write_elem_index_file_cache(dbpath_str: str, mtime: float, index: Dict[str, List[int]]) -> None:
    """
    Write elem_index cache (gzip+pickle), atomic replace.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _elem_index_cache_file_path(dbpath_str)
    tmp = f"{path}.tmp.{os.getpid()}"

    payload = {
        "mtime": mtime,
        "index": index,
        "updated_at": time.time(),
    }

    with gzip.open(tmp, "wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)

    os.replace(tmp, path)
    
# -----------------------------
# Single-atleast file cache helpers
# key: (dbpath_str, mtime, only_last)
# value: {elem_symbol -> sorted list[str]}
# -----------------------------
def _single_atleast_cache_file_name(dbpath_str: str, only_last: int) -> str:
    h = hashlib.sha1(dbpath_str.encode("utf-8")).hexdigest()
    return f"vasp_single_atleast_cache_{h}_relax{int(only_last)}.json"


def _single_atleast_cache_file_path(dbpath_str: str, only_last: int) -> str:
    return os.path.join(CACHE_DIR, _single_atleast_cache_file_name(dbpath_str, only_last))


def _read_single_atleast_file_cache(dbpath_str: str, mtime: float, only_last: int) -> Optional[Dict[str, List[str]]]:
    path = _single_atleast_cache_file_path(dbpath_str, only_last)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return None
        cached_mtime = float(payload.get("mtime", -1))
        if abs(cached_mtime - mtime) > 1e-6:
            return None
        m = payload.get("map")
        if not isinstance(m, dict):
            return None
        out: Dict[str, List[str]] = {}
        for k, v in m.items():
            if not isinstance(k, str) or not isinstance(v, list):
                continue
            out[k] = [str(x) for x in v]
        return out
    except Exception:
        return None


def _write_single_atleast_file_cache(dbpath_str: str, mtime: float, only_last: int, m: Dict[str, List[str]]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _single_atleast_cache_file_path(dbpath_str, only_last)
    tmp = f"{path}.tmp.{os.getpid()}"
    payload = {
        "mtime": mtime,
        "only_last": int(only_last),
        "map": m,
        "updated_at": time.time(),
    }
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)

def _cache_file_name(dbpath_str: str) -> str:
    h = hashlib.sha1(dbpath_str.encode("utf-8")).hexdigest()
    return f"vasp_elements_cache_{h}.json"


def _cache_file_path(dbpath_str: str) -> str:
    return os.path.join(CACHE_DIR, _cache_file_name(dbpath_str))


def _read_file_cache(dbpath_str: str, mtime: float) -> Optional[List[str]]:
    """
    Read cache file if exists and mtime matches.
    Returns elements list or None.
    """
    path = _cache_file_path(dbpath_str)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        cached_mtime = float(data.get("mtime", -1))
        if abs(cached_mtime - mtime) > 1e-6:
            return None
        elems = data.get("elements")
        if not isinstance(elems, list):
            return None
        elems = [str(x) for x in elems]
        return elems
    except Exception:
        return None


def _write_file_cache(dbpath_str: str, mtime: float, elems: List[str]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = _cache_file_path(dbpath_str)
    tmp = f"{path}.tmp.{os.getpid()}"
    payload = {
        "mtime": mtime,
        "elements": elems,
        "updated_at": time.time(),
    }
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)  # atomic replace


# -----------------------------
# Memory cache helpers
# -----------------------------
def _get_cache(dbpath_str: str, mtime: float) -> Optional[List[str]]:
    with _cache_lock:
        item = _elements_cache.get(dbpath_str)
        if not item:
            return None
        cached_mtime, elems, _updated_at, _source = item
        if abs(cached_mtime - mtime) > 1e-6:
            return None
        return elems


def _set_cache(dbpath_str: str, mtime: float, elems: List[str], source: str) -> None:
    with _cache_lock:
        _elements_cache[dbpath_str] = (mtime, elems, time.time(), source)
        _scanning.pop(dbpath_str, None)


def _mark_scanning(dbpath_str: str, task_id: Optional[str] = None) -> None:
    with _cache_lock:
        if dbpath_str not in _scanning:
            _scanning[dbpath_str] = {"started_at": time.time(), "task_id": task_id}
        else:
            if task_id and not _scanning[dbpath_str].get("task_id"):
                _scanning[dbpath_str]["task_id"] = task_id


def _is_scanning(dbpath_str: str) -> bool:
    with _cache_lock:
        return dbpath_str in _scanning


def _get_task_id_memory(dbpath_str: str) -> Optional[str]:
    with _cache_lock:
        return (_scanning.get(dbpath_str) or {}).get("task_id")


# -----------------------------
# Scan implementations
# -----------------------------
def _scan_and_cache_daemon(dbpath) -> None:
    """
    Daemon thread scan: safe for uvicorn --reload (won't block shutdown).
    Also writes file cache to survive reload.
    """
    dbpath_str = str(dbpath)

    try:
        mtime = dbpath.stat().st_mtime
    except Exception:
        with _cache_lock:
            _scanning.pop(dbpath_str, None)
        return

    try:
        elems = sorted(set(get_elements_in_ase_db(dbpath)))
        _write_file_cache(dbpath_str, mtime, elems)
        _set_cache(dbpath_str, mtime, elems, source="daemon")
    except Exception:
        with _cache_lock:
            _scanning.pop(dbpath_str, None)
        return


def _kickoff_scan_daemon(dbpath) -> Optional[str]:
    t = Thread(target=_scan_and_cache_daemon, args=(dbpath,), daemon=True)
    t.start()
    return None


def _kickoff_scan_celery_dedup(dbpath) -> Optional[str]:
    """
    Celery 模式：Redis 去重。
    - 若已有 task_id：直接复用，不重复 enqueue
    - 否则抢一个短锁（只保护 enqueue 这一瞬间），抢到才 enqueue
    """
    from services.scan_lock import (
        acquire_scan_lock,
        release_scan_lock,
        get_current_task_id,
        set_current_task_id,
    )
    from tasks.vasp_scan import scan_vasp_elements  # local import

    dbpath_str = str(dbpath)

    # 1) 有正在扫描的 task_id → 直接复用
    existing = get_current_task_id(dbpath_str)
    if existing:
        return existing

    # 2) 抢 enqueue 锁：防止并发请求同时 enqueue
    lock = acquire_scan_lock(dbpath_str, ttl_seconds=SCAN_ENQUEUE_LOCK_TTL)
    if lock is None:
        # 有人正在 enqueue；再读一次 task_id（可能马上就写进去了）
        return get_current_task_id(dbpath_str)

    try:
        # 双重检查：锁到手后再确认一次
        existing = get_current_task_id(dbpath_str)
        if existing:
            return existing

        async_result = scan_vasp_elements.delay(dbpath_str)
        set_current_task_id(dbpath_str, async_result.id, ttl_seconds=SCAN_TASK_ID_TTL)
        return async_result.id
    finally:
        release_scan_lock(lock)


def _kickoff_scan(dbpath) -> Optional[str]:
    """
    Switchable scan backend via env VASP_SCAN_BACKEND:
    - daemon: background thread
    - celery: distributed task queue (with redis dedupe)
    """
    if VASP_SCAN_BACKEND == "celery":
        return _kickoff_scan_celery_dedup(dbpath)
    return _kickoff_scan_daemon(dbpath)

def _db_meta(ref) -> Dict[str, Any]:
    return {"kind": ref.kind, "key": ref.key, "label": ref.label, "dbname": ref.dbname}

def _missing_detail(ref) -> str:
    return getattr(ref, "missingReason", None) or f"database file not found: {ref.dbpath}"

def _scope_norm(scope: Optional[str]) -> str:
    s = (scope or "all").strip().lower()
    return s if s in ("all", "personal", "upload", "custom") else "all"

def _is_custom_ref(ref) -> bool:
    """
    判定一个 ref 是否为“自定义库”。
    兼容不同 resolver 实现：优先看 key 前缀，其次看 kind。
    """
    k = str(getattr(ref, "key", "") or "")
    kind = str(getattr(ref, "kind", "") or "")
    if k.startswith("custom:"):
        return True
    # 兜底：如果你的 authz_db 里用 kind 标识 custom，也能过滤掉
    if kind in ("custom", "vasp_custom"):
        return True
    return False


def _filter_refs_by_scope(scope2: str, refs: List[Any], requested_db: Optional[str]) -> List[Any]:
    """
    规则：
    - scope != custom：永远不返回 custom refs
    - scope == custom：只返回 custom refs；如果请求的 db 不是 custom: 则报错（避免混用）
    """
    scope2 = _scope_norm(scope2)

    if scope2 == "custom":
        if requested_db and not str(requested_db).strip().startswith("custom:"):
            raise HTTPException(status_code=400, detail="custom database is not allowed in scope=all/personal/upload")
        return [r for r in refs if _is_custom_ref(r)]

    # all/personal/upload：剔除 custom
    return [r for r in refs if not _is_custom_ref(r)]

def _refs_meta(refs) -> List[Dict[str, Any]]:
    out = []
    for r in refs:
        out.append({
            "kind": r.kind,
            "key": r.key,
            "label": r.label,
            "dbname": r.dbname,
            "exists": bool(getattr(r, "exists", True)),
            "missingReason": getattr(r, "missingReason", None),
        })
    return out

def _existing_refs(refs):
    """过滤不存在的库文件（exists=False 的不参与合并查询）。"""
    ok = []
    for r in refs:
        if bool(getattr(r, "exists", True)) and r.dbpath and str(r.dbpath):
            ok.append(r)
    return ok

def _agg_elems_cache_key(requested: Optional[str], scope2: str, only_last: int, selected: List[str], mode: str, cp_flts: List[Dict[str, Any]], refs_ok) -> str:
    mtimes = []
    for r in refs_ok:
        try:
            mt = float(r.dbpath.stat().st_mtime)
        except Exception:
            mt = 0.0
        mtimes.append((r.key, mt))
    mtimes.sort(key=lambda x: x[0])

    obj = {
        "version": CACHE_VERSION,
        "requested": str(requested or ""),
        "scope": scope2,
        "only_last": int(only_last),
        "mode": str(mode),
        "elems": list(selected),
        "cp": cp_flts,
        "dbs": mtimes,
    }
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def _agg_elems_file_path(h: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"vasp_agg_elements_{h}.json")

# 你要求：DB 里的 /storage/... 变成 /mnt/storage/...
MNT_PREFIX = os.getenv("VASP_TASK_MNT_PREFIX", "/mnt").rstrip("/")

# 允许访问的根（务必收敛范围，避免用户通过 DB 注入任意路径）
ALLOWED_TASK_ROOTS = [
    Path("/mnt/storage").resolve(),
    Path("/mnt/home").resolve(),
    Path("/mnt/public").resolve(),
]

def _mnt_join_source_dir(source_dir: str) -> Path:
    """
    "/storage/xxx" -> "/mnt/storage/xxx"
    "/mnt/storage/xxx" -> "/mnt/storage/xxx" (不重复加)
    """
    s = (source_dir or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="row.data.source_dir is empty")

    # 统一绝对路径
    if not s.startswith("/"):
        # 你 DB 应该给绝对路径；不是的话也给它纠正一下
        s = "/" + s

    if s.startswith(MNT_PREFIX + "/"):
        p = Path(s)
    else:
        p = Path(MNT_PREFIX + s)

    return p.resolve()

def _assert_allowed_task_path(p: Path) -> None:
    rp = p.resolve()
    for root in ALLOWED_TASK_ROOTS:
        try:
            if rp == root or root in rp.parents:
                return
        except Exception:
            pass
    raise HTTPException(status_code=403, detail=f"path not allowed: {rp}")

def _pick_vasp_files(workdir: Path) -> dict:
    """
    在 workdir 下选文件：
      - vasprun.xml / vasprun.xml.gz / vasprun.xml.xz (优先)
      - OUTCAR (fallback)
    """
    cand_vr = [
        workdir / "vasprun.xml",
        workdir / "vasprun.xml.gz",
        workdir / "vasprun.xml.xz",
    ]
    vr = next((p for p in cand_vr if p.exists() and p.is_file()), None)
    outcar = (workdir / "OUTCAR")
    outcar = outcar if outcar.exists() and outcar.is_file() else None
    return {"vasprun": vr, "outcar": outcar}

def _read_vasprun_band_png_b64(vasprun_path: str) -> tuple[bool, str]:
    """
    返回 (ok, base64_png or error)
    """
    try:
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.core import Spin
        from pymatgen.electronic_structure.plotter import BSPlotter

        vr = Vasprun(vasprun_path)
        bs = vr.get_band_structure(line_mode=True)

        efermi = bs.efermi
        distances = bs.distance
        spin_polarized = bs.is_spin_polarized

        plotter = BSPlotter(bs)
        ticks = plotter.get_ticks()
        tick_distances = ticks["distance"]
        tick_labels = ["Γ" if lab == "GAMMA" else lab for lab in ticks["label"]]

        plt.figure(figsize=(8, 8))
        ax = plt.gca()

        if spin_polarized:
            up = bs.bands[Spin.up]
            dn = bs.bands[Spin.down]
            for ib in range(up.shape[0]):
                ax.plot(distances, up[ib] - efermi, color="red", linewidth=1)
            for ib in range(dn.shape[0]):
                ax.plot(distances, dn[ib] - efermi, color="blue", linewidth=1)
        else:
            b = bs.bands[Spin.up]
            for ib in range(b.shape[0]):
                ax.plot(distances, b[ib] - efermi, color="black", linewidth=1)

        for d in tick_distances:
            ax.axvline(d, color="black", linestyle="--", linewidth=0.6, alpha=0.5)

        ax.axhline(0, color="gray", linestyle="--", linewidth=1)
        ax.set_xlim(distances[0], distances[-1])
        ax.set_ylim(-3, 3)
        ax.set_ylabel("Energy (E - E_F) / eV", fontsize=16)
        ax.set_xticks(tick_distances)
        ax.set_xticklabels(tick_labels, fontsize=13)
        ax.set_title("Band Structure", fontsize=18, pad=10)

        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=220, bbox_inches="tight")
        plt.close()
        buf.seek(0)
        return True, base64.b64encode(buf.read()).decode("utf-8")
    except Exception as e:
        try:
            plt.close("all")
        except Exception:
            pass
        return False, f"band plot failed: {e}"

def _read_vasprun_dos_png_b64(vasprun_path: str, emin: float = -3.0, emax: float = 3.0) -> tuple[bool, str]:
    try:
        import numpy as np
        from pymatgen.io.vasp import Vasprun
        from pymatgen.electronic_structure.core import Spin

        vr = Vasprun(vasprun_path, parse_projected_eigen=False, parse_potcar_file=False)
        dos = vr.complete_dos
        efermi = dos.efermi
        energies = dos.energies - efermi

        # window mask
        mask = (energies >= emin) & (energies <= emax)
        energies = energies[mask]

        up = dos.densities.get(Spin.up)
        dn = dos.densities.get(Spin.down)

        plt.figure(figsize=(8, 8))
        ax = plt.gca()

        if up is not None and dn is not None:
            up = up[mask]
            dn = dn[mask]
            ax.plot(energies, up, color="black", lw=1.4, label="TDOS up")
            ax.fill_between(energies, 0, up, color="#fca5a5", alpha=0.55)
            ax.plot(energies, -dn, color="black", lw=1.4, ls="--", label="TDOS down")
            ax.fill_between(energies, 0, -dn, color="#93c5fd", alpha=0.55)
            ax.text(0.99, 0.02, "up>0, down<0", transform=ax.transAxes, ha="right", va="bottom", fontsize=9, color="gray")
        else:
            tot = dos.get_densities()[mask]
            ax.plot(energies, tot, color="black", lw=1.4, label="TDOS")
            ax.fill_between(energies, 0, tot, color="#bdbdbd", alpha=0.45)
            ax.set_ylim(bottom=0)   # ✅ 无自旋：DOS 从 0 开始

        ax.axvline(0, color="black", lw=1, ls="--")
        ax.set_xlim(emin, emax)
        ax.set_xlabel("E - E_F (eV)")
        ax.set_ylabel("DOS (states/eV)")
        ax.set_title("Density of States", fontsize=16)
        ax.legend(fontsize=9)

        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=220, bbox_inches="tight")
        plt.close()
        buf.seek(0)
        return True, base64.b64encode(buf.read()).decode("utf-8")
    except Exception as e:
        try:
            plt.close("all")
        except Exception:
            pass
        return False, f"dos plot failed: {e}"
    
# ===== OUTCAR fallback: band =====
OUTCAR_KPT_RE = re.compile(r'^\s*k-point\s+(\d+)\s*:\s*([-\d\.Ee+]+)\s+([-\d\.Ee+]+)\s+([-\d\.Ee+]+)')
OUTCAR_EFERMI_RE = re.compile(r'^\s*E-fermi\s*:\s*([-\d\.Ee+]+)')
OUTCAR_SPIN_RE = re.compile(r'^\s*spin component\s+(\d+)', re.I)
OUTCAR_BAND_LINE_RE = re.compile(r'^\s*(\d+)\s+([-\d\.Ee+]+)\s+([0-2]\.\d+)')  # band energy occ

def _parse_outcar_band(outcar_path: str) -> Dict[str, Any]:
    """
    从 OUTCAR 提取简化能带数据：
      return {efermi: float|None, kpoints:[(kx,ky,kz)], eigenvals:{spin:int -> np.ndarray(nbands,nkpts)}}
    说明：这是 fallback，不含高对称点标签。
    """
    efermi = None
    kpts_all: List[Tuple[float, float, float]] = []
    eigenvals_raw: Dict[int, List[List[float]]] = {}
    current_spin = 1
    collecting = False
    cur_k_index = None

    with open(outcar_path, "r", errors="ignore") as f:
        for line in f:
            m = OUTCAR_EFERMI_RE.match(line)
            if m:
                try:
                    efermi = float(m.group(1))
                except Exception:
                    pass
                continue

            m = OUTCAR_SPIN_RE.match(line)
            if m:
                current_spin = int(m.group(1))
                collecting = False
                cur_k_index = None
                continue

            m = OUTCAR_KPT_RE.match(line)
            if m:
                cur_k_index = int(m.group(1))
                kx, ky, kz = float(m.group(2)), float(m.group(3)), float(m.group(4))
                kpts_all.append((kx, ky, kz))
                eigenvals_raw.setdefault(current_spin, []).append([])
                collecting = True
                continue

            if collecting:
                if not line.strip():
                    collecting = False
                    continue
                mb = OUTCAR_BAND_LINE_RE.match(line)
                if mb and cur_k_index is not None:
                    try:
                        energy = float(mb.group(2))
                        eigenvals_raw[current_spin][-1].append(energy)
                    except Exception:
                        pass

    if not kpts_all or not eigenvals_raw:
        raise ValueError("OUTCAR: no kpoints/eigenvals parsed")

    # 对齐 kpoint 数（防截断）
    min_kpts = min(len(v) for v in eigenvals_raw.values())
    kpts_all = kpts_all[:min_kpts]
    for sp in list(eigenvals_raw.keys()):
        eigenvals_raw[sp] = eigenvals_raw[sp][:min_kpts]

    # 过滤空 k点（所有 spin 该点都要有 band）
    valid = []
    for i in range(min_kpts):
        ok = True
        for sp in eigenvals_raw:
            if i >= len(eigenvals_raw[sp]) or len(eigenvals_raw[sp][i]) == 0:
                ok = False
                break
        if ok:
            valid.append(i)
    if not valid:
        raise ValueError("OUTCAR: all kpoints empty after filtering")

    kpts = [kpts_all[i] for i in valid]

    # 统一 nbands：取所有有效 k点最小 band 数
    spins_arrays: Dict[int, np.ndarray] = {}
    for sp, k_list in eigenvals_raw.items():
        band_counts = [len(k_list[i]) for i in valid]
        nb = min(band_counts)
        nk = len(valid)
        arr = np.zeros((nb, nk), dtype=float)
        for col, idx in enumerate(valid):
            arr[:, col] = np.array(k_list[idx][:nb], dtype=float)
        spins_arrays[sp] = arr

    return {"efermi": efermi, "kpoints": kpts, "eigenvals": spins_arrays}

def _k_distances_frac(kpts: List[Tuple[float, float, float]]) -> np.ndarray:
    """简化距离：用分数坐标欧氏距离累加（fallback 用）"""
    d = [0.0]
    for i in range(1, len(kpts)):
        x1, y1, z1 = kpts[i - 1]
        x2, y2, z2 = kpts[i]
        dd = float(((x2 - x1)**2 + (y2 - y1)**2 + (z2 - z1)**2) ** 0.5)
        d.append(d[-1] + dd)
    return np.array(d, dtype=float)

def _read_band_png_b64_with_fallback(workdir: Path) -> Tuple[bool, str]:
    """
    band plot:
      1) vasprun.xml(.gz/.xz) -> pymatgen
      2) OUTCAR -> fallback
    """
    files = _pick_vasp_files(workdir)
    vr = files.get("vasprun")
    outcar = files.get("outcar")

    # 1) vasprun
    if vr:
        return _read_vasprun_band_png_b64(str(vr))

    # 2) OUTCAR fallback
    if not outcar:
        return False, "vasprun.xml(.gz/.xz) and OUTCAR not found"

    try:
        parsed = _parse_outcar_band(str(outcar))
        efermi = float(parsed["efermi"] or 0.0)
        dists = _k_distances_frac(parsed["kpoints"])
        spins_arrays: Dict[int, np.ndarray] = parsed["eigenvals"]

        plt.figure(figsize=(8, 8))
        ax = plt.gca()

        # 画 band
        if 1 in spins_arrays and 2 in spins_arrays:
            up = spins_arrays[1]
            dn = spins_arrays[2]
            for ib in range(up.shape[0]):
                ax.plot(dists, up[ib] - efermi, color="red", lw=1)
            for ib in range(dn.shape[0]):
                ax.plot(dists, dn[ib] - efermi, color="blue", lw=1)
        else:
            arr = spins_arrays.get(1) if 1 in spins_arrays else next(iter(spins_arrays.values()))
            for ib in range(arr.shape[0]):
                ax.plot(dists, arr[ib] - efermi, color="black", lw=1)

        ax.axhline(0, color="gray", ls="--", lw=1)
        ax.set_xlim(float(dists[0]), float(dists[-1]))
        ax.set_ylim(-3, 3)
        ax.set_ylabel("Energy (E - E_F) / eV", fontsize=16)
        ax.set_xticks([])
        ax.set_title("Band Structure (OUTCAR fallback)", fontsize=18, pad=10)

        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=220, bbox_inches="tight")
        plt.close()
        buf.seek(0)
        return True, base64.b64encode(buf.read()).decode("utf-8")
    except Exception as e:
        try:
            plt.close("all")
        except Exception:
            pass
        return False, f"OUTCAR band fallback failed: {e}"

# ===== OUTCAR fallback: DOS (TDOS only) =====
OUTCAR_DOS_HEAD_RE = re.compile(r'^\s*energy\s+dos', re.I)

def _parse_outcar_dos_simple(outcar_path: str) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray], float]:
    """
    从 OUTCAR 的 DOS 区域提取（非常简化）：
      return energies_raw(eV), dos_col2, dos_col3(optional), efermi
    说明：OUTCAR 是否有 DOS 取决于 VASP 输出设置；没有就会失败。
    """
    efermi = 0.0
    with open(outcar_path, "r", errors="ignore") as f:
        lines = f.readlines()

    for ln in lines:
        m = OUTCAR_EFERMI_RE.match(ln)
        if m:
            try:
                efermi = float(m.group(1))
            except Exception:
                pass

    start = None
    for i in range(len(lines) - 1, -1, -1):
        if OUTCAR_DOS_HEAD_RE.search(lines[i]):
            start = i + 1
            break
    if start is None:
        raise ValueError("OUTCAR: DOS header not found (need DOS written)")

    e_list: List[float] = []
    c2: List[float] = []
    c3: List[float] = []

    for j in range(start, len(lines)):
        s = lines[j].strip()
        if not s:
            if len(e_list) > 20:
                break
            continue
        parts = re.split(r"\s+", s)
        try:
            e = float(parts[0])
            v2 = float(parts[1])
            v3 = float(parts[2]) if len(parts) >= 3 else None
        except Exception:
            if len(e_list) > 20:
                break
            continue

        e_list.append(e)
        c2.append(v2)
        if v3 is not None:
            c3.append(v3)

    if not e_list:
        raise ValueError("OUTCAR: no DOS data parsed")

    energies = np.array(e_list, dtype=float)
    dos2 = np.array(c2, dtype=float)
    dos3 = np.array(c3, dtype=float) if len(c3) == len(c2) else None
    return energies, dos2, dos3, float(efermi)

def _read_dos_png_b64_with_fallback(workdir: Path, emin: float, emax: float) -> Tuple[bool, str]:
    """
    dos plot:
      1) vasprun -> pymatgen TDOS
      2) OUTCAR -> simple TDOS fallback
    """
    files = _pick_vasp_files(workdir)
    vr = files.get("vasprun")
    outcar = files.get("outcar")

    if vr:
        return _read_vasprun_dos_png_b64(str(vr), emin=float(emin), emax=float(emax))

    if not outcar:
        return False, "vasprun.xml(.gz/.xz) and OUTCAR not found"

    try:
        energies_raw, col2, col3, efermi = _parse_outcar_dos_simple(str(outcar))
        energies = energies_raw - efermi

        mask = (energies >= float(emin)) & (energies <= float(emax))
        energies = energies[mask]
        col2 = col2[mask]
        col3 = col3[mask] if (col3 is not None and len(col3) == len(mask)) else None

        plt.figure(figsize=(8, 8))
        ax = plt.gca()

        if col3 is not None and len(col3) == len(col2):
            # 约定：up>0, down<0
            ax.plot(energies, col2, color="black", lw=1.4, label="TDOS up")
            ax.fill_between(energies, 0, col2, color="#fca5a5", alpha=0.55)
            ax.plot(energies, -col3, color="black", lw=1.4, ls="--", label="TDOS down")
            ax.fill_between(energies, 0, -col3, color="#93c5fd", alpha=0.55)
        else:
            ax.plot(energies, col2, color="black", lw=1.4, label="TDOS")
            ax.fill_between(energies, 0, col2, color="#bdbdbd", alpha=0.45)
            ax.set_ylim(bottom=0)

        ax.axvline(0, color="black", lw=1, ls="--")
        ax.set_xlim(float(emin), float(emax))
        ax.set_xlabel("E - E_F (eV)")
        ax.set_ylabel("DOS (states/eV)")
        ax.set_title("Density of States (OUTCAR fallback)", fontsize=16)
        ax.legend(fontsize=9)

        buf = BytesIO()
        plt.savefig(buf, format="png", dpi=220, bbox_inches="tight")
        plt.close()
        buf.seek(0)
        return True, base64.b64encode(buf.read()).decode("utf-8")
    except Exception as e:
        try:
            plt.close("all")
        except Exception:
            pass
        return False, f"OUTCAR dos fallback failed: {e}"

# -----------------------------
# Routes
# -----------------------------
@router.get("/available")
def available(
    scope: str = Query(default="all", description="all | personal | upload"),
    current_user=Depends(get_current_user),
) -> List[Dict[str, Any]]:
    alias = (current_user.alias or "").strip()

    scope2 = (scope or "all").strip().lower()
    if scope2 not in ("all", "personal", "upload", "custom"):
        scope2 = "all"

    owners = list_accessible_owners(alias, scope=scope2)
    if scope2 == "custom":
        # 返回“每个自定义库”一条，支持前端点击哪个就进入哪个
        udir = _custom_user_dir(alias)
        if not udir.exists():
            return []

        out: List[Dict[str, Any]] = []
        for fp in sorted(udir.glob("*.db")):
            safe = fp.stem
            out.append({
                "kind": "db",
                # ✅ 单库 key：custom:{alias}:{dbname}（包含 .db）
                "key": f"custom:{alias}:{fp.name}",
                "label": f"自定义库 ({alias})",
                "dbname": fp.name,
                "exists": fp.exists(),
                "missingReason": None if fp.exists() else "file missing",
            })
        return out

    # 调试：可选
    print("[/available owners] alias =", alias, "scope =", scope2)
    print("[/available owners] owners =", [{"key": o.key, "label": o.label} for o in owners])

    stale_days = int(os.getenv("VASP_DB_STALE_DAYS", "30"))
    out: List[Dict[str, Any]] = []
    for owner in owners:
        refs = resolve_dbset_for_request(alias, owner.key, scope=scope2)
        refs = _filter_refs_by_scope(scope2, refs, owner.key)
        summary = summarize_database_refs(refs, stale_days=stale_days)
        existing_names = [source["dbname"] for source in summary["sources"] if source["exists"]]
        out.append(
            {
                "kind": "owner",
                "key": owner.key,
                "label": owner.label,
                "dbname": " + ".join(existing_names) if existing_names else "不可用",
                **summary,
            }
        )
    return out

class CreateCustomDbReq(BaseModel):
    name: str  # 显示名 + 文件名基准

def _safe_db_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="数据库名不能为空")
    # 只允许：中文/英文/数字/下划线/中划线/空格，其他替换为下划线
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "_", s)
    s = s.strip().replace(" ", "_")
    if len(s) < 1:
        raise HTTPException(status_code=400, detail="数据库名非法")
    if len(s) > 64:
        raise HTTPException(status_code=400, detail="数据库名过长（>64）")
    return s

def _custom_user_dir(alias: str) -> Path:
    return (CUSTOM_DB_ROOT / alias).resolve()

def _custom_db_path(alias: str, safe_name: str) -> Path:
    p = (_custom_user_dir(alias) / f"{safe_name}.db").resolve()
    # 安全：必须在用户目录内
    if _custom_user_dir(alias) not in p.parents:
        raise HTTPException(status_code=400, detail="invalid custom db path")
    return p

@router.get("/custom/list")
def list_custom_dbs(current_user=Depends(get_current_user)) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    udir = _custom_user_dir(alias)
    if not udir.exists():
        return {"alias": alias, "items": []}

    items = []
    for fp in sorted(udir.glob("*.db")):
        if not fp.is_file():
            continue
        # key 给前端/后端统一使用
        safe = fp.stem
        items.append({
            "name": safe,           # 显示名（你也可以另存更漂亮的 displayName）
            "safe_name": safe,
            "path": str(fp),
            "key": f"custom:{alias}:{fp.name}",  # 统一 key 形式
            "exists": fp.is_file(),
        })
    return {"alias": alias, "items": items}

@router.post("/custom/create")
def create_custom_db(req: CreateCustomDbReq, current_user=Depends(get_current_user)) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    safe = _safe_db_name(req.name)
    udir = _custom_user_dir(alias)
    os.makedirs(udir, exist_ok=True)

    dbp = _custom_db_path(alias, safe)
    if dbp.exists():
        if dbp.is_file():
            raise HTTPException(status_code=409, detail="该自定义数据库已存在")
        raise HTTPException(status_code=400, detail="目标自定义数据库路径不是有效文件")

    # 创建空 ASE DB
    with connect(str(dbp)) as _:
        pass

    return {"ok": True, "key": f"custom:{alias}:{dbp.name}", "name": safe, "path": str(dbp)}

# --- VASP: delete custom db ---

@router.delete("/custom/delete")
def delete_custom_vasp_db(
    key: str = Query(..., description="custom db key: custom:{alias}:{file}.db"),
    delete_file: int = Query(1, ge=0, le=1, description="1=delete actual .db file"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    if not alias:
        raise HTTPException(status_code=403, detail="invalid user alias")

    s = (key or "").strip()
    if not s.startswith("custom:"):
        raise HTTPException(status_code=400, detail="invalid key (not custom)")

    parts = s.split(":", 2)  # custom, owner_alias, filename
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="invalid key format")

    _tag, owner_alias, fname = parts[0], parts[1].strip(), parts[2].strip()
    if not owner_alias or not fname:
        raise HTTPException(status_code=400, detail="invalid key")

    # ✅ 核心权限：只能删自己的；root 也不允许删别人的
    if owner_alias != alias:
        raise HTTPException(status_code=403, detail="只能删除自己的自定义库")

    if not fname.endswith(".db"):
        raise HTTPException(status_code=400, detail="invalid custom db filename")

    safe_stem = Path(fname).stem
    dbp = _custom_db_path(alias, safe_stem)

    if int(delete_file) == 1:
        if dbp.exists():
            if not dbp.is_file():
                raise HTTPException(status_code=400, detail="目标自定义数据库不是有效文件")
            try:
                dbp.unlink()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"delete file failed: {e}")
        else:
            return {"ok": True, "status": "missing", "message": "文件不存在（已视为删除完成）", "key": key}

    return {"ok": True, "status": "deleted", "message": "删除成功", "key": key}

@router.get("/elements")
def elements(
    db: Optional[str] = Query(default=None, description="group key / owner aliasEN / dbname"),
    scope: str = Query(default="all", description="all | personal | upload"),
    refresh: int = Query(default=0, ge=0, le=1, description="1=trigger background rescan"),
    elems: Optional[str] = Query(default=None, description="元素筛选，逗号分隔，如 H,O,Li"),
    elem_mode: str = Query(default="at_least", description="at_least | only"),
    only_last: int = Query(default=0, ge=0, le=1, description="1=每个 source_dir 只保留 step_index 最大的记录"),
    cp_filters: Optional[str] = Query(default=None, description="JSON list filters, e.g. [{path:'ediff',op:'eq',value:1e-5}]"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    给元素周期表用：返回该库中出现过的元素集合。

    响应：
    - status: ready | scanning | refreshing | error
    - elements: list[str]
    - task_id: celery 模式下可能返回（用于前端轮询进度）
    """
    alias = (current_user.alias or "").strip()
    scope2 = _scope_norm(scope)

    # 解析为多个 refs（owner:xxx 时多库；否则单库 list）
    refs = resolve_dbset_for_request(alias, db, scope=scope2)
    refs = _filter_refs_by_scope(scope2, refs, db)
    refs_ok = _existing_refs(refs)

    if not refs_ok:
        return {
            "status": "error",
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "elements": [],
            "detail": "no existing database files for this selection",
        }

    selected = _normalize_elem_list(elems)
    mode = (elem_mode or "at_least").strip().lower()
    if mode not in ("at_least", "only"):
        mode = "at_least"

    # 多库元素合并：默认返回并集
    # 若传了 elems/cp_filters/only_last，则对每个库用你现有逻辑算 highlight，再做并集
    union_set: set[str] = set()

    cp_flts = _parse_cp_filters(cp_filters)
    need_hl = (len(selected) > 0) or (len(cp_flts) > 0) or (int(only_last) == 1)

    # ✅ 聚合缓存：仅在 refresh=0 时启用
    if int(refresh) == 0:
        h = _agg_elems_cache_key(db, scope2, int(only_last), selected, mode, cp_flts, refs_ok)
        fpath = _agg_elems_file_path(h)

        with _agg_elems_lock:
            hit = _agg_elems_mem.get(h)
            if hit and isinstance(hit.get("elements"), list):
                return {
                    "status": "ready",
                    "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
                    "elements": hit["elements"],
                    "filter": {"elems": selected, "mode": mode, "only_last": int(only_last), "cp_filters": cp_flts} if need_hl else None,
                    "backend": VASP_SCAN_BACKEND,
                    "task_id": None,
                    "source": "agg_memory",
                }

        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                arr = payload.get("elements")
                if isinstance(arr, list):
                    arr2 = [str(x) for x in arr]
                    with _agg_elems_lock:
                        _agg_elems_mem[h] = {"elements": arr2, "updated_at": time.time()}
                    return {
                        "status": "ready",
                        "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
                        "elements": arr2,
                        "filter": {"elems": selected, "mode": mode, "only_last": int(only_last), "cp_filters": cp_flts} if need_hl else None,
                        "backend": VASP_SCAN_BACKEND,
                        "task_id": None,
                        "source": "agg_file",
                    }
            except Exception:
                pass

    # -------- 无缓存命中：正常计算 --------
    task_ids: List[str] = []

    for ref in refs_ok:
        dbpath = ref.dbpath
        dbpath_str = str(dbpath)

        # refresh=1：触发后台扫描，不在这里同步扫
        if int(refresh) == 1:
            try:
                _mark_scanning(dbpath_str)  # 记忆态：这个库正在扫描
                tid = _kickoff_scan(dbpath)  # celery 模式下会返回 task_id
                if tid:
                    task_ids.append(tid)
            except Exception:
                pass
            continue  # ✅ 不做下面的同步计算

        try:
            mtime = dbpath.stat().st_mtime
        except Exception:
            continue

        def _compute_highlight_one_db() -> List[str]:
            cp_key = json.dumps(cp_flts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            cache_key = (CACHE_VERSION, dbpath_str, mtime, int(only_last), mode, tuple(selected), cp_key)
            with _highlight_cache_lock:
                cached_hl = _highlight_cache.get(cache_key)
                if cached_hl is not None:
                    return cached_hl

            if len(selected) == 1 and mode == "at_least":
                one = selected[0]
                one_map = _get_single_atleast_map(dbpath_str, mtime, int(only_last))
                hl = one_map.get(one, [])
                with _highlight_cache_lock:
                    _highlight_cache[cache_key] = hl
                return hl

            highlight: set[str] = set()
            with connect(str(dbpath)) as con:
                base_ids = _get_base_ids_for_elements(con, dbpath_str, mtime, int(only_last))

                ids: List[int] = []
                if selected:
                    idx = _get_elem_index(dbpath_str, mtime)
                    ids = idx.get(selected[0], [])
                    for s in selected[1:]:
                        ids = _intersect_sorted(ids, idx.get(s, []))
                        if not ids:
                            break
                    if base_ids is not None and ids:
                        ids = _intersect_sorted(ids, base_ids)
                else:
                    ids = base_ids[:] if base_ids is not None else []

                if cp_flts:
                    groups = _group_cp_filters_or(cp_flts)

                    cp_ids: Optional[List[int]] = None
                    for path, wants in groups.items():
                        idx_cp = _get_cp_index(dbpath_str, mtime, int(only_last), path)

                        ids_one_path: List[int] = []
                        first = True
                        for want in wants:
                            ids_v = idx_cp.get(want, [])
                            if first:
                                ids_one_path = list(ids_v)
                                first = False
                            else:
                                ids_one_path = _union_sorted(ids_one_path, ids_v)

                        cp_ids = ids_one_path if cp_ids is None else _intersect_sorted(cp_ids, ids_one_path)
                        if not cp_ids:
                            break

                    if cp_ids is None:
                        ids = []
                    elif not ids:
                        ids = cp_ids
                    else:
                        ids = _intersect_sorted(ids, cp_ids)

                if not ids:
                    hl = []
                    with _highlight_cache_lock:
                        _highlight_cache[cache_key] = hl
                    return hl

                if mode == "only":
                    sel_set = set(selected)
                    only_ids: List[int] = []
                    for rid in ids:
                        r = con.get(id=rid)
                        if r is None:
                            continue
                        syms = set(_parse_formula_elements(getattr(r, "formula", None)))
                        if syms and syms.issubset(sel_set):
                            only_ids.append(int(rid))
                    ids = only_ids

                for rid in ids:
                    r = con.get(id=rid)
                    if r is None:
                        continue
                    syms = _parse_formula_elements(getattr(r, "formula", None))
                    if syms:
                        highlight.update(syms)

            hl = sorted(highlight)
            with _highlight_cache_lock:
                _highlight_cache[cache_key] = hl
            return hl

        if need_hl:
            arr = _compute_highlight_one_db()
        else:
            try:
                arr = sorted(set(get_elements_in_ase_db(dbpath)))
            except Exception:
                arr = []

        for s in arr:
            if s:
                union_set.add(str(s))

    out_list = sorted(union_set)

    # ✅ 写聚合缓存（refresh=0 才写）
    if int(refresh) == 0:
        try:
            h = _agg_elems_cache_key(db, scope2, int(only_last), selected, mode, cp_flts, refs_ok)
            fpath = _agg_elems_file_path(h)
            with _agg_elems_lock:
                _agg_elems_mem[h] = {"elements": out_list, "updated_at": time.time()}
            tmp = f"{fpath}.tmp.{os.getpid()}"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"elements": out_list, "updated_at": time.time()}, f, ensure_ascii=False)
            os.replace(tmp, fpath)
        except Exception:
            pass
    
    if int(refresh) == 1:
        return {
            "status": "refreshing",
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "elements": [],
            "backend": VASP_SCAN_BACKEND,
            "task_id": task_ids[0] if task_ids else None,   # 简化：先给第一个
            "task_ids": task_ids,  # ✅ 如果你愿意前端支持多任务
        }

    return {
        "status": "ready",
        "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
        "elements": out_list,
        "filter": {"elems": selected, "mode": mode, "only_last": int(only_last), "cp_filters": cp_flts} if need_hl else None,
        "backend": VASP_SCAN_BACKEND,
        "task_id": None,
    }

# -----------------------------
# Celery task status endpoint (progress meta)
# -----------------------------
@router.get("/elements/task/{task_id}")
def get_task_status(task_id: str, current_user=Depends(get_current_user)) -> Dict[str, Any]:
    """
    查询 celery 任务状态，并返回 progress meta（update_state 写入的 meta）。
    """
    if VASP_SCAN_BACKEND != "celery":
        return {"task_id": task_id, "state": "DISABLED", "detail": "VASP_SCAN_BACKEND is not celery"}

    from celery.result import AsyncResult

    r = AsyncResult(task_id, app=celery_app)

    payload: Dict[str, Any] = {
        "task_id": task_id,
        "state": r.state,  # PENDING / STARTED / PROGRESS / SUCCESS / FAILURE
        "meta": r.info if isinstance(r.info, dict) else None,  # ✅ 关键：把进度 meta 透出
    }

    if r.state == "SUCCESS":
        payload["result"] = r.result
    elif r.state == "FAILURE":
        payload["error"] = str(r.info)

    return payload

# -----------------------------
# Columns endpoint for ASE DB
# -----------------------------
EXCLUDE_DATA_KEYS = {"source_signature"}

DEFAULT_COLS = DEFAULT_VASP_COLUMNS

_columns_response_cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
_columns_response_cache_lock = Lock()

def _flatten_data_keys(d: Any) -> List[str]:
    if not isinstance(d, dict):
        return []
    out = []
    for k in d.keys():
        if k in EXCLUDE_DATA_KEYS:
            continue
        out.append(f"data.{k}")
    return out

EXCLUDE_CALC_PARAM_KEYS: set[str] = set()  # 需要排除巨大的键时再加，例如 {"some_big_blob"}

def _flatten_calcparam_keys(obj: Any, max_depth: int = 3) -> List[str]:
    """
    把 calculator_parameters 递归展开成列名：
    calculator_parameters.a.b.c
    - max_depth 控制展开深度，避免列爆炸
    """
    out: List[str] = []

    def walk(x: Any, path: List[str], depth: int):
        if depth > max_depth:
            # 深度超限：把当前路径当成一个“整体列”
            if path:
                out.append("calculator_parameters." + ".".join(path))
            return

        if isinstance(x, dict):
            if not x:
                return
            for k, v in x.items():
                ks = str(k)
                if ks in EXCLUDE_CALC_PARAM_KEYS:
                    continue
                walk(v, path + [ks], depth + 1)
            return

        # list/tuple/标量：作为叶子列
        if path:
            out.append("calculator_parameters." + ".".join(path))

    if isinstance(obj, dict):
        walk(obj, [], 1)

    return sorted(set(out))

def _get_by_path(d: Any, path: str) -> Any:
    """
    从 dict 中按 'a.b.c' 取值；中途不是 dict 或 key 不存在就返回 None
    """
    if not isinstance(d, dict):
        return None
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        if part not in cur:
            return None
        cur = cur[part]
    return cur

@router.get("/columns")
def columns(
    db: Optional[str] = Query(default=None, description="group key / owner aliasEN / dbname"),
    scope: str = Query(default="all", description="all | personal | upload"),
    sample: int = Query(default=2000, ge=50, le=20000, description="扫描多少行来汇总 keys（越大越全，越慢）"),
    only_last: int = Query(default=0, ge=0, le=1),
    elems: Optional[str] = Query(default=None),
    elem_mode: str = Query(default="at_least"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    scope2 = _scope_norm(scope)

    refs = resolve_dbset_for_request(alias, db, scope=scope2)
    refs = _filter_refs_by_scope(scope2, refs, db)
    refs_ok = _existing_refs(refs)

    if not refs_ok:
        return {
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "default": DEFAULT_COLS,
            "data": [],
            "calculator_parameters": [],
            "all": DEFAULT_COLS,
            "metadata": column_metadata(DEFAULT_COLS),
            "excluded_data_keys": sorted(EXCLUDE_DATA_KEYS),
            "sample": int(sample),
            "detail": "no existing database files for this selection",
        }

    data_cols_set = set()
    calc_cols_set = set()

    sel = _normalize_elem_list(elems)
    mode = (elem_mode or "at_least").strip().lower()
    if mode not in ("at_least", "only"):
        mode = "at_least"

    ref_versions = tuple(
        (str(ref.dbpath), float(ref.dbpath.stat().st_mtime))
        for ref in refs_ok
    )
    cache_key = (ref_versions, int(sample), int(only_last), tuple(sel), mode)
    with _columns_response_cache_lock:
        cached = _columns_response_cache.get(cache_key)
        if cached is not None:
            return cached

    for ref in refs_ok:
        dbpath = ref.dbpath
        dbpath_str = str(dbpath)
        try:
            mtime = dbpath.stat().st_mtime
        except Exception:
            mtime = time.time()

        try:
            with connect(str(dbpath)) as con:
                base_ids: Optional[List[int]] = None
                if int(only_last) == 1:
                    base_ids = _get_base_ids_for_elements(con, dbpath_str, mtime, only_last=1)

                filtered_ids: Optional[List[int]] = base_ids
                if sel:
                    idx = _get_elem_index(dbpath_str, mtime)
                    ids = idx.get(sel[0], [])
                    for s in sel[1:]:
                        ids = _intersect_sorted(ids, idx.get(s, []))
                        if not ids:
                            break

                    if filtered_ids is not None:
                        ids = _intersect_sorted(ids, filtered_ids)

                    if mode == "only" and ids:
                        sel_set = set(sel)
                        only_ids: List[int] = []
                        for rid in ids[: max(sample * 3, 2000)]:
                            r = con.get(id=rid)
                            if r is None:
                                continue
                            syms = set(_parse_formula_elements(getattr(r, "formula", None)))
                            if syms and syms.issubset(sel_set):
                                only_ids.append(int(rid))
                                if len(only_ids) >= sample:
                                    break
                        filtered_ids = only_ids
                    else:
                        filtered_ids = ids

                if filtered_ids is None:
                    rows_iter = con.select(limit=sample)
                else:
                    page_ids = filtered_ids[:sample]
                    rows_iter = (con.get(id=rid) for rid in page_ids)

                for row in rows_iter:
                    if row is None:
                        continue
                    d = getattr(row, "data", None)
                    data_cols_set.update(_flatten_data_keys(d))

                    cp = getattr(row, "calculator_parameters", None)
                    if (cp is None or cp == {}) and isinstance(d, dict):
                        cp = d.get("calculator_parameters")
                    calc_cols_set.update(_flatten_calcparam_keys(cp, max_depth=3))
        except Exception:
            continue

    data_cols = sorted(data_cols_set)
    calc_cols = sorted(calc_cols_set)
    all_cols = DEFAULT_COLS + data_cols + calc_cols

    response = {
        "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
        "default": DEFAULT_COLS,
        "data": data_cols,
        "calculator_parameters": calc_cols,
        "all": all_cols,
        "metadata": column_metadata(all_cols),
        "excluded_data_keys": sorted(EXCLUDE_DATA_KEYS),
        "sample": int(sample),
    }
    with _columns_response_cache_lock:
        if len(_columns_response_cache) >= 128:
            _columns_response_cache.clear()
        _columns_response_cache[cache_key] = response
    return response
    
def _get_relax_ids_cache(dbpath_str: str, mtime: float) -> Optional[List[int]]:
    # 1) 内存缓存（最快）
    with _relax_cache_lock:
        item = _relax_cache.get(dbpath_str)
        if item:
            cached_mtime, ids = item
            if abs(cached_mtime - mtime) <= 1e-6:
                return ids

    # 2) 文件缓存（跨重启）
    ids2 = _read_relax_file_cache(dbpath_str, mtime)
    if ids2 is not None:
        # 回填内存，后续更快
        _set_relax_ids_cache(dbpath_str, mtime, ids2)
        return ids2

    return None

def _set_relax_ids_cache(dbpath_str: str, mtime: float, ids: List[int]) -> None:
    with _relax_cache_lock:
        _relax_cache[dbpath_str] = (mtime, ids)

def _jsonify(v: Any) -> Any:
    """把 ASE/NumPy 等类型转换成可 JSON 序列化的 Python 原生类型。"""
    if v is None:
        return None

    # numpy: ndarray / scalar
    try:
        import numpy as np  # noqa
        if isinstance(v, np.ndarray):
            return v.tolist()
        if isinstance(v, np.generic):
            return v.item()
    except Exception:
        pass

    # bytes
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8", errors="replace")
        except Exception:
            return str(v)

    # pathlib.Path
    try:
        from pathlib import Path
        if isinstance(v, Path):
            return str(v)
    except Exception:
        pass

    # datetime
    try:
        import datetime as dt
        if isinstance(v, (dt.datetime, dt.date)):
            return v.isoformat()
    except Exception:
        pass

    # 常见容器：递归
    if isinstance(v, dict):
        return {str(k): _jsonify(val) for k, val in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonify(x) for x in v]

    # 兜底：原样返回（必须是 JSON 支持的类型：str/int/float/bool）
    return v

def _as_dict_maybe(x: Any) -> Dict[str, Any]:
    """把可能是 dict / JSON str / bytes 的 calculator_parameters 统一转成 dict。"""
    if x is None:
        return {}
    if isinstance(x, dict):
        return x
    if isinstance(x, (bytes, bytearray)):
        try:
            x = x.decode("utf-8", errors="replace")
        except Exception:
            return {}
    if isinstance(x, str):
        s = x.strip()
        if not s:
            return {}
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) else {}
        except Exception:
            return {}
    # 其它类型：尽力转（有些 ASE 版本可能是 AtomsRowDict / mapping）
    try:
        if hasattr(x, "items"):
            return dict(x.items())
    except Exception:
        pass
    return {}

def _get_calc_params_from_row(row) -> Dict[str, Any]:
    # 1) 优先：row.calculator_parameters（ASE 顶层字段）
    cp = _as_dict_maybe(getattr(row, "calculator_parameters", None))
    if cp:
        return cp

    # 2) fallback：row.data["calculator_parameters"]
    d = getattr(row, "data", None)
    if isinstance(d, dict):
        cp2 = _as_dict_maybe(d.get("calculator_parameters"))
        if cp2:
            return cp2

    # 3) 再兜底：row.todict()（有些情况下 ase db --json 展示来自这里）
    try:
        td = row.todict()
        if isinstance(td, dict):
            cp3 = _as_dict_maybe(td.get("calculator_parameters"))
            if cp3:
                return cp3
    except Exception:
        pass

    return {}

def _normalize_cp_path(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return p
    # ✅ 兼容用户写法：允许带 calculator_parameters. 或 data.calculator_parameters.
    if p.startswith("data.calculator_parameters."):
        p = p[len("data.calculator_parameters."):]
    elif p == "data.calculator_parameters":
        p = ""
    if p.startswith("calculator_parameters."):
        p = p[len("calculator_parameters."):]
    elif p == "calculator_parameters":
        p = ""
    return p

def _get_cp_value(row, path: str) -> Any:
    cp = _get_calc_params_from_row(row)  # row 或 data 两处找
    if not isinstance(cp, dict):
        return None

    p = _normalize_cp_path(path)
    if not p:
        return cp
    return _get_by_path(cp, p)

def _parse_cp_filters(cp_filters: Optional[str]) -> List[Dict[str, Any]]:
    if not cp_filters:
        return []
    try:
        obj = json.loads(cp_filters)
    except Exception:
        return []
    if not isinstance(obj, list):
        return []
    out = []
    for it in obj:
        if not isinstance(it, dict):
            continue
        path = str(it.get("path", "")).strip()
        path = _normalize_cp_path(path)
        op = str(it.get("op", "eq")).strip().lower()
        val = it.get("value", None)
        if not path:
            continue
        if op not in ("eq",):  # 先只做 eq，后续你想加 gt/lt 我再给你扩展
            op = "eq"
        out.append({"path": path, "op": op, "value": val})
    return out

def _parse_cp_filters_any(cp_filters: Any) -> List[Dict[str, Any]]:
    """
    兼容：
      - None
      - JSON string
      - list[dict] (前端直接传对象数组)
    """
    if cp_filters is None or cp_filters == "":
        return []
    if isinstance(cp_filters, list):
        # 直接走你的规范化逻辑：把它 dump 成字符串再 parse（复用 _parse_cp_filters）
        try:
            return _parse_cp_filters(json.dumps(cp_filters, ensure_ascii=False))
        except Exception:
            return []
    if isinstance(cp_filters, str):
        return _parse_cp_filters(cp_filters)
    # 其它类型：兜底
    try:
        return _parse_cp_filters(json.dumps(cp_filters, ensure_ascii=False))
    except Exception:
        return []
    
def _get_row_col_value(row, col: str) -> Any:
    c = (col or "").strip()
    if not c:
        return None

    if c.startswith("data."):
        d = getattr(row, "data", None)
        if not isinstance(d, dict):
            return None
        return d.get(c[len("data."):])

    return getattr(row, c, None)

def _parse_row_filters(row_filters: Optional[str]) -> List[Dict[str, Any]]:
    if not row_filters:
        return []
    try:
        obj = json.loads(row_filters)
    except Exception:
        return []
    if not isinstance(obj, list):
        return []

    out: List[Dict[str, Any]] = []
    for it in obj:
        if not isinstance(it, dict):
            continue
        col = str(it.get("col", "")).strip()
        if not col:
            continue
        op = str(it.get("op", "eq")).strip().lower()
        if op not in ("eq", "in", "gt", "ge", "lt", "le", "contains"):
            op = "eq"
        out.append({"col": col, "op": op, "value": it.get("value", None)})
    return out

def _row_filter_match_value(v: Any, op: str, target: Any) -> bool:
    if op == "contains":
        if v is None:
            return False
        return str(target) in str(v)

    if op == "in":
        if not isinstance(target, list):
            target = [target]
        # 用你已有的 canon 统一比较（兼容 1e-5 vs 0.00001）
        tv = {_cp_canon(x) for x in target}
        return _cp_canon(v) in tv

    if op in ("gt", "ge", "lt", "le"):
        try:
            fv = float(v)
            ft = float(target)
        except Exception:
            return False
        if op == "gt":
            return fv > ft
        if op == "ge":
            return fv >= ft
        if op == "lt":
            return fv < ft
        if op == "le":
            return fv <= ft

    # eq
    return _cp_canon(v) == _cp_canon(target)

def _row_filters_match_row(row, row_flts: List[Dict[str, Any]]) -> bool:
    """
    规则：同 col 多条 => OR；不同 col => AND
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for f in row_flts:
        groups.setdefault(f["col"], []).append(f)

    for col, flist in groups.items():
        v = _get_row_col_value(row, col)
        ok_one_col = False
        for f in flist:
            if _row_filter_match_value(v, f["op"], f["value"]):
                ok_one_col = True
                break
        if not ok_one_col:
            return False

    return True

def _compute_filtered_ids_for_db(
    con,
    dbpath_str: str,
    mtime: float,
    only_last: int,
    selected: List[str],
    elem_mode: str,
    cp_flts: List[Dict[str, Any]],
    row_flts: List[Dict[str, Any]],
    query: str = "",
) -> Optional[List[int]]:
    """
    返回 filtered_ids：
      - None 表示“全表”（only_last=0 且没有 elems/cp_filters）
      - list[int] 表示满足筛选条件的 row_id（已排序）

    带缓存：
      1) 内存 _filtered_ids_cache
      2) 文件缓存（可选，按 mtime 校验）
      3) 分布式锁避免并发重复构建（文件缓存会更有意义）
    """
    mode = (elem_mode or "at_least").strip().lower()
    if mode not in ("at_least", "only"):
        mode = "at_least"

    # no filter -> full table
    query2 = str(query or "").strip()
    if int(only_last) == 0 and (not selected) and (not cp_flts) and (not row_flts) and (not query2):
        return None

    cp_key = json.dumps(cp_flts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    row_key = json.dumps(row_flts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    cache_key = (dbpath_str, float(mtime), int(only_last), mode, tuple(selected), cp_key, row_key, query2.lower())

    # 1) 内存缓存
    with _filtered_ids_lock:
        if cache_key in _filtered_ids_cache:
            return _filtered_ids_cache[cache_key]

    # 2) 文件缓存（只缓存 list，不缓存 None）
    ids_file = _read_filtered_ids_file_cache(dbpath_str, mtime, int(only_last), mode, selected, cp_flts, row_flts, query2)
    if ids_file is not None:
        with _filtered_ids_lock:
            _filtered_ids_cache[cache_key] = ids_file
        return ids_file

    # 3) 计算（加分布式锁，避免并发重复算）
    lock_key = "vasp:filtered_ids:" + hashlib.sha1(
        (dbpath_str + "|" + str(mtime) + "|" + str(int(only_last)) + "|" + mode + "|" + ",".join(selected) + "|" + cp_key + "|" + row_key + "|" + query2.lower()).encode("utf-8")
    ).hexdigest()

    token = _acquire_dist_lock(lock_key, ttl=1800)

    if token is None and REDIS_LOCK_ENABLED:
        # 没抢到锁：稍等文件缓存（可能对方会写）
        _wait_for_file(_filtered_ids_cache_file_path(dbpath_str, int(only_last), mode, selected, cp_flts, row_flts, query2), timeout=120.0, interval=0.25)
        ids_file2 = _read_filtered_ids_file_cache(dbpath_str, mtime, int(only_last), mode, selected, cp_flts, row_flts, query2)
        if ids_file2 is not None:
            with _filtered_ids_lock:
                _filtered_ids_cache[cache_key] = ids_file2
            return ids_file2
        # 读不到就自己算（容错）

    try:
        # ---- base ids: only_last ----
        base_ids: Optional[List[int]] = None
        if int(only_last) == 1:
            base_ids = _get_base_ids_for_elements(con, dbpath_str, mtime, only_last=1)

        filtered_ids: Optional[List[int]] = base_ids

        # ---- elems filter ----
        if selected:
            idx = _get_elem_index(dbpath_str, mtime)
            ids = idx.get(selected[0], [])
            for s in selected[1:]:
                ids = _intersect_sorted(ids, idx.get(s, []))
                if not ids:
                    break

            if filtered_ids is not None:
                ids = _intersect_sorted(ids, filtered_ids)

            if mode == "only" and ids:
                sel_set = set(selected)
                only_ids: List[int] = []
                for rid in ids:
                    r = con.get(id=rid)
                    if r is None:
                        continue
                    syms = set(_parse_formula_elements(getattr(r, "formula", None)))
                    if syms and syms.issubset(sel_set):
                        only_ids.append(int(rid))
                filtered_ids = only_ids
            else:
                filtered_ids = ids

        # ---- cp_filters: (same path OR) AND (different paths AND) ----
        if cp_flts:
            groups = _group_cp_filters_or(cp_flts)

            cp_ids: Optional[List[int]] = None

            for path, wants in groups.items():
                idx_cp = _get_cp_index(dbpath_str, mtime, int(only_last), path)

                # 同一个 path：OR -> union
                ids_one_path: List[int] = []
                first = True
                for want in wants:
                    ids_v = idx_cp.get(want, [])
                    if first:
                        ids_one_path = list(ids_v)
                        first = False
                    else:
                        ids_one_path = _union_sorted(ids_one_path, ids_v)

                # 不同 path：AND -> intersect
                cp_ids = ids_one_path if cp_ids is None else _intersect_sorted(cp_ids, ids_one_path)
                if not cp_ids:
                    break

            if cp_ids is None:
                filtered_ids = []
            elif filtered_ids is None:
                filtered_ids = cp_ids
            else:
                filtered_ids = _intersect_sorted(filtered_ids, cp_ids)

        if query2:
            query_ids = search_formula_ids(dbpath_str, query2)
            if filtered_ids is None:
                filtered_ids = query_ids
            else:
                filtered_ids = _intersect_sorted(filtered_ids, query_ids)
                
        # ---- row_filters ----
        if row_flts:
            # 如果此时还是 None（理论上只会出现在“无筛选”被提前 return 的情况），这里兜底
            if filtered_ids is None:
                filtered_ids = _get_all_ids_cached(con, dbpath_str, mtime)

            keep: List[int] = []
            for rid in filtered_ids:
                r = con.get(id=int(rid))
                if r is None:
                    continue
                if _row_filters_match_row(r, row_flts):
                    keep.append(int(rid))
            filtered_ids = keep

        # 兜底：None 表示全表，但我们前面已经排除了“无筛选”情况，这里一般不会 None
        if filtered_ids is None:
            filtered_ids = []

        # 排序保证稳定
        filtered_ids = list(map(int, filtered_ids))
        filtered_ids.sort()

        # 写缓存：文件 + 内存
        try:
            _write_filtered_ids_file_cache(dbpath_str, mtime, int(only_last), mode, selected, cp_flts, row_flts, query2, filtered_ids)
        except Exception:
            pass

        with _filtered_ids_lock:
            _filtered_ids_cache[cache_key] = filtered_ids

        return filtered_ids
    finally:
        if token:
            _release_dist_lock(lock_key, token)

def _cp_canon(v: Any) -> str:
    """
    把 cp 的值标准化成可比较/可做索引的字符串：
    - dict/list => json.dumps(sort_keys=True)
    - float => 统一精度
    - 其它 => str
    """
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        # 避免 0.00001 vs 1e-05 的字符串差异
        return format(v, ".12g")
    if isinstance(v, (list, tuple)):
        try:
            return json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        except Exception:
            return str(v)
    if isinstance(v, dict):
        try:
            return json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        except Exception:
            return str(v)
    if isinstance(v, str):
        s = v.strip()
        # 如果是 json 字符串，尽量规范化
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                obj = json.loads(s)
                return _cp_canon(obj)
            except Exception:
                return s
        # 如果是数字字符串，规范成数字
        try:
            f = float(s)
            return format(f, ".12g")
        except Exception:
            return s
    return str(v)


def _cp_target_canon(target: Any) -> str:
    return _cp_canon(target)

def _cp_match(row, flt: Dict[str, Any]) -> bool:
    path = flt["path"]
    op = flt["op"]
    target = flt["value"]

    v = _get_cp_value(row, path)

    if op == "eq":
        return _cp_canon(v) == _cp_target_canon(target)

    return False

@router.get("/tasks")
def tasks(
    db: Optional[str] = Query(default=None, description="owner key / group key / db key / dbname"),
    scope: str = Query(default="all", description="all | personal | upload"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    columns: Optional[str] = Query(default=None, description="逗号分隔列名；为空则返回 DEFAULT_COLS"),
    only_last: int = Query(default=0, ge=0, le=1),
    elems: Optional[str] = Query(default=None, description="元素筛选，逗号分隔，如 H,O,Li"),
    elem_mode: str = Query(default="at_least", description="at_least | only"),
    cp_filters: Optional[str] = Query(default=None, description="JSON list filters, e.g. [{path:'ediff',op:'eq',value:1e-5}]"),
    row_filters: Optional[str] = Query(default=None, description="JSON list filters for table columns"),
    query: str = Query(default="", max_length=120, description="numeric row ID or formula fragment"),
    sort_order: str = Query(default="desc", description="desc | asc"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    scope2 = _scope_norm(scope)
    query2 = str(query or "").strip()
    sort2 = str(sort_order or "desc").strip().lower()
    if sort2 not in ("asc", "desc"):
        sort2 = "desc"

    # 解析列
    if columns and columns.strip():
        wanted_cols = [c.strip() for c in columns.split(",") if c.strip()]
    else:
        wanted_cols = DEFAULT_COLS

    refs = resolve_dbset_for_request(alias, db, scope=scope2)
    refs = _filter_refs_by_scope(scope2, refs, db)
    refs_ok = _existing_refs(refs)

    if not refs_ok:
        return {
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "page": page,
            "page_size": page_size,
            "total": 0,
            "columns": wanted_cols,
            "only_last": int(only_last),
            "query": query2,
            "sort_order": sort2,
            "filter": {"elems": [], "mode": "at_least"},
            "items": [],
            "detail": "no existing database files for this selection",
        }

    offset = (page - 1) * page_size

    def _flatten_data(d: Any) -> Dict[str, Any]:
        if not isinstance(d, dict):
            return {}
        out: Dict[str, Any] = {}
        for k, v in d.items():
            if k in EXCLUDE_DATA_KEYS:
                continue
            out[f"data.{k}"] = v
        return out

    def _row_to_item(row, dbKey: str, dbname: str) -> Dict[str, Any]:
        dflat = _flatten_data(getattr(row, "data", None))
        item: Dict[str, Any] = {}

        # ✅ 核心：加来源信息，避免跨库 id 冲突
        item["_dbKey"] = dbKey
        item["_dbName"] = dbname
        item["_rowId"] = int(getattr(row, "id", 0) or 0)

        for col in wanted_cols:
            if col.startswith("data."):
                item[col] = _jsonify(dflat.get(col, None))
            else:
                item[col] = _jsonify(getattr(row, col, None))

        if "pbc" in item and item["pbc"] is not None:
            try:
                pbc = item["pbc"]
                if isinstance(pbc, list) and len(pbc) == 3:
                    item["pbc"] = "".join(["T" if bool(x) else "F" for x in pbc])
            except Exception:
                pass

        return item

    sel = _normalize_elem_list(elems)
    mode = (elem_mode or "at_least").strip().lower()
    if mode not in ("at_least", "only"):
        mode = "at_least"

    cp_flts = _parse_cp_filters(cp_filters)
    row_flts = _parse_row_filters(row_filters)

    # 1) 先对每个库算“符合筛选条件的 row_ids”（只算 id，不拉整行）
    per_db_ids: Dict[str, List[int]] = {}  # dbKey -> sorted ids
    per_db_ref: Dict[str, Any] = {r.key: r for r in refs_ok}

    for ref in refs_ok:
        dbpath = ref.dbpath
        dbpath_str = str(dbpath)

        try:
            mtime = dbpath.stat().st_mtime
        except Exception:
            mtime = time.time()

        try:
            with connect(str(dbpath)) as con:
                # ✅ 统一用缓存版筛选
                filtered_ids = _compute_filtered_ids_for_db(
                    con=con,
                    dbpath_str=dbpath_str,
                    mtime=mtime,
                    only_last=int(only_last),
                    selected=sel,
                    elem_mode=mode,
                    cp_flts=cp_flts,
                    row_flts=row_flts,
                    query=query2,
                )

                if filtered_ids is None:
                    # 全表：这里仍然需要 ids 列表用于合并分页
                    per_db_ids[ref.key] = _get_all_ids_cached(con, dbpath_str, mtime)
                else:
                    tmp_ids = list(filtered_ids)
                    tmp_ids.sort()
                    per_db_ids[ref.key] = tmp_ids

        except Exception:
            per_db_ids[ref.key] = []

    # 2) total 仍然可以用长度求和（快）
    total = sum(len(v) for v in per_db_ids.values())

    # 3) ✅ 关键：用多路归并拿“当前页”，不构造全量 merged
    page_pairs = _merge_page_pairs_kway(per_db_ids, offset=offset, limit=page_size, sort_order=sort2)

    # 4) 拉取本页行数据
    items: List[Dict[str, Any]] = []
    # 按 dbKey 分组，减少 connect 次数
    group: Dict[str, List[int]] = {}
    for dbKey, rid in page_pairs:
        group.setdefault(dbKey, []).append(rid)

    for dbKey, ids in group.items():
        ref = per_db_ref.get(dbKey)
        if ref is None:
            continue
        try:
            with connect(str(ref.dbpath)) as con:
                for rid in ids:
                    row = con.get(id=int(rid))
                    if row is None:
                        continue
                    items.append(_row_to_item(row, dbKey=dbKey, dbname=ref.dbname))
        except Exception:
            continue

    # items 的顺序要和 page_pairs 一致（上面按 dbKey 分组会打乱顺序）
    idx_map = {(it["_dbKey"], it["_rowId"]): it for it in items}
    items_sorted: List[Dict[str, Any]] = []
    for dbKey, rid in page_pairs:
        it = idx_map.get((dbKey, rid))
        if it is not None:
            items_sorted.append(it)

    return {
        "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
        "page": page,
        "page_size": page_size,
        "total": total,
        "columns": wanted_cols,
        "only_last": int(only_last),
        "query": query2,
        "sort_order": sort2,
        "filter": {"elems": sel, "mode": mode, "cp_filters": cp_flts},
        "items": items_sorted,
    }
    
@router.get("/task/{row_id}/calculator_parameters")
def task_calculator_parameters(
    row_id: int,
    db: Optional[str] = Query(default=None, description="db key (personal:/upload:/group:)"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    ref = resolve_db_for_request(alias, db)
    
    if not getattr(ref, "exists", True):
        return {
            "db": _db_meta(ref),
            "id": int(row_id),
            "calculator": None,
            "calculator_parameters": {},
            "detail": _missing_detail(ref),
        }

    try:
        with connect(str(ref.dbpath)) as con:
            row = get_optional_ase_row(con, row_id)
            if row is None:
                return {
                    "db": {"kind": ref.kind, "key": ref.key, "label": ref.label, "dbname": ref.dbname},
                    "id": row_id,
                    "calculator": None,
                    "calculator_parameters": {},
                    "detail": "row not found",
                }

            cp = _get_calc_params_from_row(row)
            calc = getattr(row, "calculator", None)
            if calc is None and isinstance(getattr(row, "data", None), dict):
                calc = row.data.get("calculator")

            return {
                "db": {"kind": ref.kind, "key": ref.key, "label": ref.label, "dbname": ref.dbname},
                "id": int(row_id),
                "calculator": _jsonify(calc),
                "calculator_parameters": _jsonify(cp),
            }
    except Exception as e:
        return {
            "db": {"kind": ref.kind, "key": ref.key, "label": ref.label, "dbname": ref.dbname},
            "id": row_id,
            "calculator": None,
            "calculator_parameters": {},
            "detail": f"read db failed: {e}",
        }
    
@router.get("/export")
def export_ase_db(
    db: Optional[str] = Query(default=None, description="owner key / group key / db key / dbname"),
    scope: str = Query(default="all", description="all | personal | upload"),
    only_last: int = Query(default=0, ge=0, le=1),
    elems: Optional[str] = Query(default=None),
    elem_mode: str = Query(default="at_least"),
    cp_filters: Optional[str] = Query(default=None, description="JSON list filters, e.g. [{path:'ediff',op:'eq',value:1e-5}]"),
    row_filters: Optional[str] = Query(default=None, description="JSON list filters for table columns"),
    query: str = Query(default="", max_length=120),
    current_user=Depends(get_current_user),
):
    """
    导出筛选后的所有行到一个新的 ASE sqlite db（.db）文件。
    - 导出“所有符合筛选条件的样本”，不是当前页。
    """
    alias = (current_user.alias or "").strip()
    scope2 = _scope_norm(scope)

    refs = resolve_dbset_for_request(alias, db, scope=scope2)
    refs = _filter_refs_by_scope(scope2, refs, db)
    refs_ok = _existing_refs(refs)
    

    if not refs_ok:
        return {
            "ok": False,
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "detail": "no existing database files for this selection",
        }

    sel = _normalize_elem_list(elems)
    mode = (elem_mode or "at_least").strip().lower()
    if mode not in ("at_least", "only"):
        mode = "at_least"

    cp_flts = _parse_cp_filters(cp_filters)
    row_flts = _parse_row_filters(row_filters)

    # 生成临时输出文件
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_fd, out_path = tempfile.mkstemp(prefix=f"ase_export_{ts}_", suffix=".db")
    os.close(out_fd)

    def _cleanup():
        try:
            os.remove(out_path)
        except Exception:
            pass

    # 导出文件名（owner 模式给一个更清晰的名字）
    safe_name = "export"
    try:
        if isinstance(db, str) and db.startswith("owner:"):
            safe_name = db.replace("owner:", "owner_")
        elif isinstance(db, str) and db:
            safe_name = db.replace(":", "_")
    except Exception:
        pass
    filename = f"{safe_name}_{scope2}_filtered_{ts}.db"

    try:
        # 先创建 outdb（即使最后空也返回文件）
        with connect(out_path) as outdb:
            pass

        wrote = 0

        with connect(out_path) as outdb:
            for ref in refs_ok:
                src_path = str(ref.dbpath)
                dbpath_str = str(ref.dbpath)

                try:
                    mtime = ref.dbpath.stat().st_mtime
                except Exception:
                    mtime = time.time()

                try:
                    with connect(src_path) as con:
                        # ✅ 使用“筛选 ids 缓存”
                        filtered_ids = _compute_filtered_ids_for_db(
                            con=con,
                            dbpath_str=dbpath_str,
                            mtime=mtime,
                            only_last=int(only_last),
                            selected=sel,
                            elem_mode=mode,
                        cp_flts=cp_flts,
                        row_flts=row_flts,
                        query=query,
                    )

                        # filtered_ids is None => 全表
                        if filtered_ids is None:
                            rows_iter = con.select()
                        else:
                            if len(filtered_ids) == 0:
                                continue
                            rows_iter = (con.get(id=rid) for rid in filtered_ids)

                        for r in rows_iter:
                            if r is None:
                                continue

                            atoms = r.toatoms()

                            kv = dict(getattr(r, "key_value_pairs", {}) or {})
                            data = dict(getattr(r, "data", {}) or {})

                            # ---- 把来源信息写入 data（放在 jsonify 前）----
                            data["_src_db_key"] = ref.key
                            data["_src_dbname"] = ref.dbname
                            data["_src_row_id"] = int(getattr(r, "id", 0) or 0)

                            # ---- 统一把 calculator/cp 放到 data（更兼容）----
                            calc = getattr(r, "calculator", None)
                            if calc is None and isinstance(getattr(r, "data", None), dict):
                                calc = r.data.get("calculator")

                            cp = getattr(r, "calculator_parameters", None)
                            if (cp is None or cp == {}) and isinstance(getattr(r, "data", None), dict):
                                cp = r.data.get("calculator_parameters")

                            if calc is not None:
                                data["calculator"] = calc
                            if cp not in (None, {}, ""):
                                data["calculator_parameters"] = cp

                            # ---- 清洗 + JSON 化（关键）----
                            kv = _sanitize_kvp(kv)
                            kv2 = _jsonify(kv)
                            data2 = _jsonify(data)

                            # 再兜底一次：确保 dict
                            if not isinstance(kv2, dict):
                                kv2 = {}
                            if not isinstance(data2, dict):
                                data2 = {}

                            outdb.write(
                                atoms,
                                key_value_pairs=kv2,
                                data=data2,
                            )
                            wrote += 1
                except Exception as e:
                    # 单个库坏了不影响整体导出（你也可以选择 raise）
                    print("[export] failed on db =", src_path, "err =", repr(e))
                    continue
        
        if wrote == 0:
            _cleanup()
            raise HTTPException(status_code=404, detail="导出结果为空：没有任何记录被成功写入（可能是写入异常被跳过或筛选条件无匹配）")
        # 如果一个都没写，也返回空库文件（和你原逻辑一致）
        return FileResponse(
            out_path,
            media_type="application/octet-stream",
            filename=filename,
            background=BackgroundTask(_cleanup),
        )

    except Exception:
        _cleanup()
        raise

@router.get("/cp_keys")
def cp_keys(
    db: Optional[str] = Query(default=None, description="owner key / group key / db key / dbname"),
    scope: str = Query(default="all", description="all | personal | upload"),
    sample: int = Query(default=2000, ge=50, le=20000),
    only_last: int = Query(default=1, ge=0, le=1),
    max_depth: int = Query(default=4, ge=1, le=10),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    scope2 = _scope_norm(scope)

    refs = resolve_dbset_for_request(alias, db, scope=scope2)
    refs = _filter_refs_by_scope(scope2, refs, db)
    refs_ok = _existing_refs(refs)

    if not refs_ok:
        return {
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "only_last": int(only_last),
            "sample": int(sample),
            "max_depth": int(max_depth),
            "keys": [],
            "detail": "no existing database files for this selection",
        }

    # -------------------------
    # 聚合缓存（owner+scope+only_last+sample+max_depth + 各库 mtime）
    # -------------------------
    try:
        mtimes = []
        for r in refs_ok:
            try:
                mt = float(r.dbpath.stat().st_mtime)
            except Exception:
                mt = 0.0
            mtimes.append((r.key, mt))
        mtimes.sort(key=lambda x: x[0])
    except Exception:
        mtimes = []

    cache_key_obj = {
        "requested": str(db or ""),
        "scope": scope2,
        "only_last": int(only_last),
        "sample": int(sample),
        "max_depth": int(max_depth),
        "dbs": mtimes,
    }
    cache_key_s = json.dumps(cache_key_obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    h = hashlib.sha1(cache_key_s.encode("utf-8")).hexdigest()
    mem_key = f"cp_keys:{h}"

    # 内存缓存
    if not hasattr(cp_keys, "_mem"):
        cp_keys._mem = {}  # type: ignore[attr-defined]
        cp_keys._lock = Lock()  # type: ignore[attr-defined]

    with cp_keys._lock:  # type: ignore[attr-defined]
        hit = cp_keys._mem.get(mem_key)  # type: ignore[attr-defined]
        if hit is not None:
            return hit

    # 文件缓存
    os.makedirs(CACHE_DIR, exist_ok=True)
    file_path = os.path.join(CACHE_DIR, f"vasp_cp_keys_agg_{h}.json")
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict) and payload.get("key") == mem_key:
                resp = payload.get("resp")
                if isinstance(resp, dict):
                    with cp_keys._lock:  # type: ignore[attr-defined]
                        cp_keys._mem[mem_key] = resp  # type: ignore[attr-defined]
                    return resp
        except Exception:
            pass

    # -------------------------
    # 计算：多库 keys 并集
    # -------------------------
    keys_set: set[str] = set()

    for ref in refs_ok:
        dbpath = ref.dbpath
        dbpath_str = str(dbpath)
        try:
            try:
                mtime = dbpath.stat().st_mtime
            except Exception:
                mtime = time.time()

            with connect(str(dbpath)) as con:
                base_ids: Optional[List[int]] = None
                if int(only_last) == 1:
                    base_ids = _get_relax_ids_cache(dbpath_str, mtime)
                    if base_ids is None:
                        base_ids = _get_base_ids_for_elements(con, dbpath_str, mtime, only_last=1)

                if base_ids is None:
                    rows_iter = con.select(limit=sample)
                else:
                    rows_iter = (con.get(id=rid) for rid in base_ids[:sample])

                for row in rows_iter:
                    if row is None:
                        continue
                    cp = _get_calc_params_from_row(row)
                    cols = _flatten_calcparam_keys(cp, max_depth=int(max_depth))
                    for c in cols:
                        s = str(c)
                        if s.startswith("calculator_parameters."):
                            keys_set.add(s[len("calculator_parameters."):])
        except Exception:
            continue

    out = sorted(keys_set)

    resp = {
        "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
        "only_last": int(only_last),
        "sample": int(sample),
        "max_depth": int(max_depth),
        "keys": out,
    }

    # 写缓存：内存 + 文件
    with cp_keys._lock:  # type: ignore[attr-defined]
        cp_keys._mem[mem_key] = resp  # type: ignore[attr-defined]

    try:
        tmp = f"{file_path}.tmp.{os.getpid()}"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"key": mem_key, "resp": resp, "updated_at": time.time()}, f, ensure_ascii=False)
        os.replace(tmp, file_path)
    except Exception:
        pass

    return resp
        
@router.post("/upload_vasprun")
async def upload_vasprun(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    上传 vasprun.xml / vasprun.xml.gz
    - 文件永久保存到：{UPLOADS_ROOT}/{alias}/runs/{run_id}/vasprun.xml(.gz)
    - 导入结果写入：{UPLOADS_ROOT}/{alias}/{alias}-uploads.db
    - 关键：导入脚本的 calc_dir 使用这个永久目录，使 DB 中的 data.source_dir 可追溯、可用于绘图
    """
    alias = (current_user.alias or "").strip()

    if not is_alias_allowed(alias):
        raise HTTPException(status_code=403, detail="该用户不在 allowed_users 或已禁用")

    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=400, detail="缺少文件名")

    is_gz = filename.endswith(".gz")
    ok_name = (filename.endswith("vasprun.xml") or filename.endswith("vasprun.xml.gz"))
    if not ok_name:
        raise HTTPException(status_code=400, detail="仅允许上传 vasprun.xml 或 vasprun.xml.gz")

    # 目标 DB（用户目录没有就创建）
    ensure_user_upload_dir(alias)
    out_db = str(user_upload_db_path(alias))

    # ✅ 永久保存目录：/.../uploads/{alias}/runs/{run_id}/
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:12]
    run_dir = (UPLOADS_ROOT / alias / "runs" / run_id).resolve()
    os.makedirs(run_dir, exist_ok=True)

    # ✅ 保存文件名固定，方便 pick：vasprun.xml 或 vasprun.xml.gz
    saved_name = "vasprun.xml.gz" if is_gz else "vasprun.xml"
    saved_path = (run_dir / saved_name).resolve()

    # ✅ 安全：确保写入路径仍在 UPLOADS_ROOT 下（防止奇怪路径注入）
    if UPLOADS_ROOT not in saved_path.parents:
        raise HTTPException(status_code=400, detail="invalid upload path")

    # 1) 保存上传文件到永久目录（限制大小）
    size = 0
    try:
        with open(saved_path, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail=f"文件过大，限制 {MAX_UPLOAD_BYTES} bytes")
                f.write(chunk)
    except HTTPException:
        # 清理这个 run_dir（避免半截文件）
        try:
            if saved_path.exists():
                saved_path.unlink()
            # 只有空目录才删
            if run_dir.exists() and not any(run_dir.iterdir()):
                run_dir.rmdir()
        except Exception:
            pass
        raise

    # 2) 运行导入脚本：calc_dir 用 run_dir（永久存在）
    cmd = [
        "python3",
        VASP_IMPORT_SCRIPT,
        "--calc_dir", str(run_dir),
        "--db_path", out_db,
        "--description", f"uploaded by {alias}",
        "--datatype", "upload",
        "--recursive", "0",
    ]

    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=VASP_IMPORT_TIMEOUT,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="导入超时（vasprun 太大或解析太慢）")

    if p.returncode != 0:
        err_tail = (p.stderr or "")[-4000:]

        # 导入失败时：保留文件还是删除？
        # 推荐保留，方便排查；如果你想删，把下面注释取消即可。
        # try:
        #     if saved_path.exists():
        #         saved_path.unlink()
        #     if run_dir.exists() and not any(run_dir.iterdir()):
        #         run_dir.rmdir()
        # except Exception:
        #     pass

        raise HTTPException(status_code=500, detail=f"导入失败：{err_tail}")

    # ✅ 可选：写一个小 meta 文件，方便将来追溯
    try:
        meta = {
            "alias": alias,
            "run_id": run_id,
            "original_filename": filename,
            "saved_path": str(saved_path),
            "bytes": int(size),
            "import_cmd": cmd,
            "created_at": time.time(),
        }
        with open(run_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    return {
        "ok": True,
        "aliasEN": alias,
        "upload_db_key": f"upload:{alias}:{alias}-uploads.db",
        "upload_db_path": out_db,
        "run_id": run_id,
        "saved_dir": str(run_dir),
        "saved_file": str(saved_path),
        "message": "导入完成（vasprun 已永久保存）",
    }

@router.post("/upload_vasp_files")
async def upload_vasp_files(
    files: List[UploadFile] = File(...),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    多文件上传：
    - 必须包含 vasprun.xml 或 vasprun.xml.gz
    - 其它文件可选：KPOINTS, INCAR, OUTCAR, POSCAR, CONTCAR, OSZICAR 等
    - 所有文件保存到同一个 run_dir，然后用 run_dir 调用导入脚本
    """
    alias = (current_user.alias or "").strip()
    if not is_alias_allowed(alias):
        raise HTTPException(status_code=403, detail="该用户不在 allowed_users 或已禁用")

    if not files or len(files) == 0:
        raise HTTPException(status_code=400, detail="未收到文件")

    # 必须包含 vasprun
    names = [(f.filename or "").strip() for f in files]
    has_vasprun = ("vasprun.xml" in names) or ("vasprun.xml.gz" in names)
    if not has_vasprun:
        raise HTTPException(status_code=400, detail="必须包含 vasprun.xml 或 vasprun.xml.gz")

    # 目标 DB（用户目录没有就创建）
    ensure_user_upload_dir(alias)
    out_db = str(user_upload_db_path(alias))

    # run 目录
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:12]
    run_dir = (UPLOADS_ROOT / alias / "runs" / run_id).resolve()
    os.makedirs(run_dir, exist_ok=True)

    # 保存文件（按原文件名保存；但要做安全清洗）
    total_bytes = 0
    saved = []

    def _safe_name(fn: str) -> str:
        # 去路径、去空
        base = os.path.basename((fn or "").strip())
        if not base:
            return ""
        # 可选：进一步限制长度/字符
        return base

    try:
        for uf in files:
            fn = _safe_name(uf.filename or "")
            if not fn:
                continue

            dst = (run_dir / fn).resolve()
            if UPLOADS_ROOT not in dst.parents:
                raise HTTPException(status_code=400, detail=f"invalid filename: {fn}")

            size = 0
            with open(dst, "wb") as f:
                while True:
                    chunk = await uf.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    total_bytes += len(chunk)
                    if total_bytes > MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail=f"文件总大小超过限制 {MAX_UPLOAD_BYTES} bytes")
                    f.write(chunk)

            saved.append({"name": fn, "bytes": int(size)})

        # 再次确认：run_dir 里确实有 vasprun
        if not ((run_dir / "vasprun.xml").exists() or (run_dir / "vasprun.xml.gz").exists()):
            raise HTTPException(status_code=400, detail="未找到 vasprun.xml 或 vasprun.xml.gz（可能文件名不正确）")

        # 调用导入脚本
        cmd = [
            "python3",
            VASP_IMPORT_SCRIPT,
            "--calc_dir", str(run_dir),
            "--db_path", out_db,
            "--description", f"uploaded by {alias}",
            "--datatype", "upload",
            "--recursive", "0",
        ]

        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=VASP_IMPORT_TIMEOUT,
            env=os.environ.copy(),
        )

        if p.returncode != 0:
            err_tail = (p.stderr or "")[-4000:]
            raise HTTPException(status_code=500, detail=f"导入失败：{err_tail}")

        # 写 meta
        try:
            meta = {
                "alias": alias,
                "run_id": run_id,
                "saved": saved,
                "total_bytes": int(total_bytes),
                "import_cmd": cmd,
                "created_at": time.time(),
            }
            with open(run_dir / "meta.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return {
            "ok": True,
            "aliasEN": alias,
            "upload_db_key": f"upload:{alias}:{alias}-uploads.db",
            "upload_db_path": out_db,
            "run_id": run_id,
            "saved_dir": str(run_dir),
            "saved": saved,
            "message": "导入完成（文件已永久保存）",
        }

    except HTTPException:
        # 出错时：保留 run_dir 便于排查（你也可以选择清理）
        raise

@router.get("/task/{row_id}/detail")
def task_detail(
    row_id: int,
    db: Optional[str] = Query(default=None, description="db key (personal:/upload:/group:)"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    返回单行的详情（轻量 JSON），用于详情页展示：
    - 基本字段（id/formula/energy/natoms/pbc 等）
    - data（去掉敏感/巨大的字段你可后续加黑名单）
    - calculator / calculator_parameters
    - 结构：cell/positions/numbers/symbols/pbc
    """
    alias = (current_user.alias or "").strip()
    ref = resolve_db_for_request(alias, db)

    if not getattr(ref, "exists", True):
        raise HTTPException(status_code=404, detail=_missing_detail(ref))

    try:
        with connect(str(ref.dbpath)) as con:
            row = get_optional_ase_row(con, row_id)
            if row is None:
                raise HTTPException(status_code=404, detail="row not found")

            atoms = row.toatoms()
            
            symbols = [str(s) for s in atoms.get_chemical_symbols()]

            # 结构信息（前端画结构用）
            try:
                numbers = atoms.get_atomic_numbers().tolist()
            except Exception:
                numbers = []
            try:
                positions = atoms.get_positions().tolist()
            except Exception:
                positions = []
            try:
                cell = atoms.get_cell().array.tolist()
            except Exception:
                cell = []
            try:
                pbc = list(map(bool, atoms.get_pbc()))
            except Exception:
                pbc = []
                
            # ---- crystal derived ----
            try:
                cell_obj = atoms.get_cell()
                lengths = cell_obj.lengths().tolist()   # [a,b,c] in Å
                angles = cell_obj.angles().tolist()     # [α,β,γ] in degrees
                volume = float(cell_obj.volume)         # Å^3
            except Exception:
                lengths, angles, volume = [None, None, None], [None, None, None], None

            # density: g/cm^3
            density = None
            try:
                if volume and volume > 0:
                    mass_amu = float(sum(atoms.get_masses()))  # amu == g/mol
                    mass_g = mass_amu / AVOGADRO
                    volume_cm3 = float(volume) * 1e-24
                    density = mass_g / volume_cm3
            except Exception:
                density = None

            # fractional coords
            scaled_positions = []
            try:
                sp = atoms.get_scaled_positions(wrap=False)
                scaled_positions = sp.tolist() if hasattr(sp, "tolist") else [list(x) for x in sp]
            except Exception:
                scaled_positions = []

            atomic_positions = []
            try:
                syms = atoms.get_chemical_symbols()
                for i, el in enumerate(syms):
                    if i < len(scaled_positions):
                        x, y, z = scaled_positions[i]
                        atomic_positions.append({
                            "element": str(el),
                            "x": float(x),
                            "y": float(y),
                            "z": float(z),
                        })
            except Exception:
                atomic_positions = []

            dimensionality = None
            try:
                pbc = list(map(bool, atoms.get_pbc()))
                dimensionality = int(sum(1 for x in pbc if x))
            except Exception:
                dimensionality = None

            has_vasprun = False
            has_outcar = False
            data = getattr(row, "data", None) or {}
            source_dir = data.get("source_dir") if isinstance(data, dict) else None
            if source_dir:
                try:
                    workdir = _mnt_join_source_dir(str(source_dir))
                    _assert_allowed_task_path(workdir)
                    files = _pick_vasp_files(workdir)
                    has_vasprun = bool(files.get("vasprun"))
                    has_outcar = bool(files.get("outcar"))
                except HTTPException:
                    pass

            return build_public_task_detail(
                row=row,
                db=_db_meta(ref),
                has_vasprun=has_vasprun,
                has_outcar=has_outcar,
                structure={
                    "symbols": symbols,
                    "numbers": numbers,
                    "positions": positions,
                    "cell": cell,
                    "pbc": pbc,
                },
                crystal={
                    "lattice": {
                        "a": lengths[0], "b": lengths[1], "c": lengths[2],
                        "alpha": angles[0], "beta": angles[1], "gamma": angles[2],
                        "volume": volume,
                    },
                    "density_g_cm3": density,
                    "dimensionality": dimensionality,
                    "atomic_positions_frac": atomic_positions,
                },
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"read db failed: {e}")

@router.get("/task/{row_id}/export")
def task_export_structure(
    row_id: int,
    db: Optional[str] = Query(default=None, description="db key (personal:/upload:/group:/custom:)"),
    format: str = Query(default="poscar", description="poscar | cif"),
    current_user=Depends(get_current_user),
):
    """
    导出结构文件：
    - format=poscar -> POSCAR
    - format=cif    -> CIF
    返回纯文本下载（带 Content-Disposition）
    """
    fmt = (format or "poscar").strip().lower()
    if fmt not in ("poscar", "cif"):
        raise HTTPException(status_code=400, detail="format must be poscar or cif")

    alias = (current_user.alias or "").strip()
    ref = resolve_db_for_request(alias, db)

    if not getattr(ref, "exists", True):
        raise HTTPException(status_code=404, detail=_missing_detail(ref))

    with connect(str(ref.dbpath)) as con:
        row = con.get(id=int(row_id))
        if row is None:
            raise HTTPException(status_code=404, detail="row not found")
        atoms = row.toatoms()

    # 用 ase.io.write 写到内存
    from io import StringIO

    buf = StringIO()

    if fmt == "poscar":
        ase_write(buf, atoms, format="vasp", vasp5=True, direct=True)
        filename = f"{row_id}.vasp"
        content_type = "text/plain; charset=utf-8"
    else:
        ase_write(buf, atoms, format="cif")
        filename = f"{row_id}.cif"
        content_type = "chemical/x-cif; charset=utf-8"

    text = buf.getvalue()
    return PlainTextResponse(
        text,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

def _confirm_str(x: Any) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    return s if s else None

@router.get("/task/{row_id}/workdir")
def task_workdir(
    row_id: int,
    db: Optional[str] = Query(default=None, description="db key (personal:/upload:/group:)"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    ref = resolve_db_for_request(alias, db)

    with connect(str(ref.dbpath)) as con:
        row = con.get(id=int(row_id))
        if row is None:
            raise HTTPException(status_code=404, detail="row not found")
        d = getattr(row, "data", None) or {}
        src_dir = (d.get("source_dir") if isinstance(d, dict) else None) or ""

    workdir = _mnt_join_source_dir(src_dir)
    _assert_allowed_task_path(workdir)

    files = _pick_vasp_files(workdir)
    return {
        "ok": True,
        "db": _db_meta(ref),
        "id": int(row_id),
        "files": {
            "vasprun": bool(files["vasprun"]),
            "outcar": bool(files["outcar"]),
        },
    }


@router.get("/task/{row_id}/band-plot")
def task_band_plot(
    row_id: int,
    db: Optional[str] = Query(default=None, description="db key (personal:/upload:/group:)"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    ref = resolve_db_for_request(alias, db)

    with connect(str(ref.dbpath)) as con:
        row = con.get(id=int(row_id))
        if row is None:
            raise HTTPException(status_code=404, detail="row not found")
        d = getattr(row, "data", None) or {}
        src_dir = (d.get("source_dir") if isinstance(d, dict) else None) or ""

    workdir = _mnt_join_source_dir(src_dir)
    _assert_allowed_task_path(workdir)
    
    ok, out = _read_band_png_b64_with_fallback(workdir)
    if not ok:
        raise HTTPException(status_code=404, detail=out)

    return {
        "ok": True,
        "db": _db_meta(ref),
        "id": int(row_id),
        "image_base64": out,
    }


@router.get("/task/{row_id}/dos-plot")
def task_dos_plot(
    row_id: int,
    db: Optional[str] = Query(default=None, description="db key (personal:/upload:/group:)"),
    emin: float = Query(default=-3.0),
    emax: float = Query(default=3.0),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    ref = resolve_db_for_request(alias, db)

    with connect(str(ref.dbpath)) as con:
        row = con.get(id=int(row_id))
        if row is None:
            raise HTTPException(status_code=404, detail="row not found")
        d = getattr(row, "data", None) or {}
        src_dir = (d.get("source_dir") if isinstance(d, dict) else None) or ""

    workdir = _mnt_join_source_dir(src_dir)
    _assert_allowed_task_path(workdir)
    
    ok, out = _read_dos_png_b64_with_fallback(workdir, emin=float(emin), emax=float(emax))
    if not ok:
        raise HTTPException(status_code=404, detail=out)

    return {
        "ok": True,
        "db": _db_meta(ref),
        "id": int(row_id),
        "window": [float(emin), float(emax)],
        "image_base64": out,
    }
    
@router.get("/task/{row_id}/band-dat")
def task_band_dat(
    row_id: int,
    db: Optional[str] = Query(default=None, description="db key (personal:/upload:/group:/custom:)"),
    align: str = Query(default="fermi", description="fermi | none"),
    current_user=Depends(get_current_user),
):
    alias = (current_user.alias or "").strip()
    ref = resolve_db_for_request(alias, db)

    with connect(str(ref.dbpath)) as con:
        row = con.get(id=int(row_id))
        if row is None:
            raise HTTPException(status_code=404, detail="row not found")
        d = getattr(row, "data", None) or {}
        src_dir = (d.get("source_dir") if isinstance(d, dict) else None) or ""

    workdir = _mnt_join_source_dir(src_dir)
    _assert_allowed_task_path(workdir)
    files = _pick_vasp_files(workdir)

    try:
        if files.get("vasprun"):
            text = _band_dat_text_from_vasprun(str(files["vasprun"]), align=align)
        elif files.get("outcar"):
            text = _band_dat_text_from_outcar(str(files["outcar"]), align=align)
        else:
            raise HTTPException(status_code=404, detail="vasprun.xml(.gz/.xz) and OUTCAR not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"band.dat build failed: {e}")

    filename = f"{row_id}_band.dat"
    return PlainTextResponse(
        text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

@router.get("/task/{row_id}/dos-dat")
def task_dos_dat(
    row_id: int,
    db: Optional[str] = Query(default=None, description="db key (personal:/upload:/group:/custom:)"),
    align: str = Query(default="fermi", description="fermi | none"),
    decimate: int = Query(default=1, ge=1, le=100),
    current_user=Depends(get_current_user),
):
    alias = (current_user.alias or "").strip()
    ref = resolve_db_for_request(alias, db)

    with connect(str(ref.dbpath)) as con:
        row = con.get(id=int(row_id))
        if row is None:
            raise HTTPException(status_code=404, detail="row not found")
        d = getattr(row, "data", None) or {}
        src_dir = (d.get("source_dir") if isinstance(d, dict) else None) or ""

    workdir = _mnt_join_source_dir(src_dir)
    _assert_allowed_task_path(workdir)
    files = _pick_vasp_files(workdir)

    try:
        if files.get("vasprun"):
            blob = _dos_zip_bytes_from_vasprun(str(files["vasprun"]), align=align, decimate=int(decimate))
        elif files.get("outcar"):
            blob = _dos_zip_bytes_from_outcar(str(files["outcar"]), align=align, decimate=int(decimate))
        else:
            raise HTTPException(status_code=404, detail="vasprun.xml(.gz/.xz) and OUTCAR not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"dos zip build failed: {e}")

    filename = f"{row_id}_dos_data.zip"
    return StreamingResponse(
        iter([blob]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
    
class AddToCustomReq(BaseModel):
    target: str   # 目标自定义库 safe_name，例如 "myset1"
    src_db: str   # 源 db key，例如 owner:xxx / upload:xxx / custom_owner...（一般来自行的 _dbKey）
    row_id: int
    
class RemoveFromCustomReq(BaseModel):
    db_key: str   # custom:{alias}:{file}.db
    row_id: int
    missing_ok: int = 1   # 1=如果该行不存在也当成功（幂等）
    
class AddAllToCustomReq(BaseModel):
    target: str                 # 目标自定义库 safe_name
    db: Optional[str] = None    # 当前列表选择的 db key（例如 owner:xxx / upload:... / custom:...）
    scope: str = "all"          # all | personal | upload | custom

    only_last: int = 0
    elems: Optional[str] = None
    elem_mode: str = "at_least"
    cp_filters: Optional[Any] = None  # 前端传数组/或字符串都行，我们做兼容
    query: str = ""

    max_rows: int = 0       # 安全阈值：最多收藏多少条（防止误点把几十万条写爆）

def _sanitize_kvp(kv: Dict[str, Any]) -> Dict[str, Any]:
    """
    ASE DB 的 key_value_pairs key 有限制；有些 key（如 calculator）会触发 Bad key。
    这里做保守过滤：遇到不合规 key 就丢弃/改名。
    """
    if not isinstance(kv, dict):
        return {}

    # 这些在 ASE DB 里经常被认为是保留/非法/容易冲突的字段名
    banned = {
        "calculator",
        "calculator_parameters",
        "data",
        "id",
        "unique_id",
        "mtime",
        "ctime",
        "user",
        "numbers",
        "positions",
        "cell",
        "pbc",
        "constraints",
    }

    out: Dict[str, Any] = {}
    for k, v in kv.items():
        ks = str(k).strip()
        if not ks:
            continue
        if ks in banned:
            continue
        # 可选：进一步限制 key 字符（更稳）
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", ks):
            continue
        out[ks] = v
    return out

@router.post("/custom/add")
def add_row_to_custom(req: AddToCustomReq, current_user=Depends(get_current_user)) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    target_safe = _safe_db_name(req.target)

    # 目标库路径
    dst_path = _custom_db_path(alias, target_safe)
    if not dst_path.exists():
        raise HTTPException(status_code=404, detail="目标自定义数据库不存在")
    if not dst_path.is_file():
        raise HTTPException(status_code=400, detail="目标自定义数据库不是有效文件")

    # 源库 ref：用现成的 resolve_db_for_request 来拿 dbpath
    src_ref = resolve_db_for_request(alias, req.src_db)
    if not getattr(src_ref, "exists", True):
        raise HTTPException(status_code=404, detail="源数据库不存在")

    # ✅ 幂等去重键：同一条“源库+源row_id”只写一次
    sig = f"{src_ref.key}#{int(req.row_id)}"

    # ✅ 先查目标库：已存在则直接返回 ok（像 QE 那样）
    try:
        with connect(str(dst_path)) as dst_con:
            hit = list(dst_con.select(custom_signature=sig, limit=1))
            if hit:
                return {"ok": True, "target": target_safe, "status": "exists", "message": "数据已存在"}
    except Exception:
        # 查重失败不影响主流程（容错），继续尝试写入
        pass

    # 读源行 → 写入目标库
    with connect(str(src_ref.dbpath)) as src_con:
        row = src_con.get(id=int(req.row_id))
        if row is None:
            raise HTTPException(status_code=404, detail="源行不存在")

        atoms = row.toatoms()
        kv = dict(getattr(row, "key_value_pairs", {}) or {})
        data = dict(getattr(row, "data", {}) or {})

        calc = getattr(row, "calculator", None) or (data.get("calculator") if isinstance(data, dict) else None)
        cp = _get_calc_params_from_row(row)

        # ✅ calculator/cp 放 data
        if calc is not None:
            data["calculator"] = calc
        if cp:
            data["calculator_parameters"] = cp

        # ✅ 写追溯标记（data + kvp 都写一份，方便查询）
        data["_custom_src_db_key"] = str(src_ref.key)
        data["_custom_src_row_id"] = int(req.row_id)
        data["_custom_signature"] = sig

        # ✅ 清洗 kvp 后再加 signature（避免被 sanitize 丢掉）
        kv = _sanitize_kvp(kv)
        kv["custom_signature"] = sig  # 用于 ASE DB 快速查询

        # 再 jsonify
        kv2 = _jsonify(kv)
        data2 = _jsonify(data)

        # ✅ 最终写入（如果并发导致刚写入，这里也不该报错）
        try:
            with connect(str(dst_path)) as dst_con:
                dst_con.write(
                    atoms,
                    key_value_pairs=kv2 if isinstance(kv2, dict) else {},
                    data=data2 if isinstance(data2, dict) else {},
                )
        except Exception as e:
            # ✅ 并发/重复写入兜底：再查一次，有就当成功
            try:
                with connect(str(dst_path)) as dst_con:
                    hit2 = list(dst_con.select(custom_signature=sig, limit=1))
                    if hit2:
                        return {"ok": True, "target": target_safe, "status": "exists", "message": "数据已存在"}
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"写入自定义库失败: {e}")

    return {"ok": True, "target": target_safe, "status": "inserted", "message": "收藏成功"}

@router.post("/custom/add_all")
def add_all_rows_to_custom(req: AddAllToCustomReq, current_user=Depends(get_current_user)) -> Dict[str, Any]:
    from services.vasp_custom_service import add_all_to_custom
    from authz_db import resolve_dbset_for_request

    alias = (current_user.alias or "").strip()

    try:
        return add_all_to_custom(
            alias=alias,
            target=req.target,
            db=req.db,
            scope=req.scope,
            only_last=int(req.only_last or 0),
            elems=req.elems,
            elem_mode=req.elem_mode,
            cp_filters=req.cp_filters,
            query=req.query,
            max_rows=int(req.max_rows or 0),
            resolve_dbset_for_request=resolve_dbset_for_request,
            progress_cb=None,  # 同步接口不需要进度
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.post("/custom/add_all_async")
def add_all_rows_to_custom_async(req: AddAllToCustomReq, current_user=Depends(get_current_user)) -> Dict[str, Any]:
    from tasks.vasp_custom_add_all import vasp_custom_add_all_task
    
    alias = (current_user.alias or "").strip()

    payload = req.model_dump()
    payload["alias"] = alias
    
    ar = vasp_custom_add_all_task.delay(payload)
    return {"ok": True, "job_id": ar.id}

@router.get("/custom/add_all_status/{job_id}")
def add_all_rows_to_custom_status(job_id: str, current_user=Depends(get_current_user)) -> Dict[str, Any]:
    from celery_app import celery_app
    # ✅ 可选：这里也可以校验 job_id 属于该用户（更严谨要自己存 job->alias 映射）
    r = AsyncResult(job_id, app=celery_app)
    resp: Dict[str, Any] = {
        "ok": True,
        "job_id": job_id,
        "state": r.state,  # PENDING/STARTED/PROGRESS/SUCCESS/FAILURE
        "meta": r.info if isinstance(r.info, dict) else None,
    }
    if r.state == "SUCCESS":
        resp["result"] = r.result
    if r.state == "FAILURE":
        resp["error"] = str(r.info)
    return resp

@router.post("/custom/remove")
def remove_row_from_custom(
    req: RemoveFromCustomReq,
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    从“自定义库”移除一条记录（只影响自定义库文件，不影响源库）。
    """
    alias = (current_user.alias or "").strip()
    if not alias:
        raise HTTPException(status_code=403, detail="invalid user alias")

    db_key = (req.db_key or "").strip()
    if not db_key.startswith("custom:"):
        raise HTTPException(status_code=400, detail="db_key must start with custom:")

    parts = db_key.split(":", 2)  # custom, owner_alias, filename
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="invalid custom db_key format")

    _tag, owner_alias, fname = parts[0], parts[1].strip(), parts[2].strip()
    if not owner_alias or not fname:
        raise HTTPException(status_code=400, detail="invalid custom db_key")

    # ✅ 核心权限：只能操作自己的自定义库（root 也不允许越权）
    if owner_alias != alias:
        raise HTTPException(status_code=403, detail="只能操作自己的自定义库")

    if not fname.endswith(".db"):
        raise HTTPException(status_code=400, detail="invalid custom db filename")

    safe_stem = Path(fname).stem
    dbp = _custom_db_path(alias, safe_stem)
    if not dbp.exists():
        raise HTTPException(status_code=404, detail="目标自定义数据库不存在")
    if not dbp.is_file():
        raise HTTPException(status_code=400, detail="目标自定义数据库不是有效文件")

    rid = int(req.row_id)

    try:
        with connect(str(dbp)) as con:
            row = con.get(id=rid)
            if row is None:
                if int(req.missing_ok) == 1:
                    return {"ok": True, "status": "missing", "message": "该记录不存在（已视为移除完成）", "row_id": rid}
                raise HTTPException(status_code=404, detail="row not found in custom db")

            # ✅ 兼容不同 ASE 版本：有的要 list，有的可直接 int
            try:
                con.delete([rid])
            except Exception:
                con.delete(rid)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"remove failed: {e}")

    return {"ok": True, "status": "removed", "message": "已从自定义库移除", "row_id": rid}
