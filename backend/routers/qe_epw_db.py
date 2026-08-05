# backend/routers/qe_epw_db.py
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
import subprocess
import tempfile
import shutil
import hashlib
import base64
import io
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import zipfile
from threading import Lock, Thread
from pydantic import BaseModel
from datetime import datetime
from heapq import heappush, heappop
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from utils.qe_epw_schema import SCHEMA_SQL
import xml.etree.ElementTree as ET


from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from auth import get_current_user
from authz_db import (
    list_accessible_owners,
    list_accessible_qe_epw_dbs,
    resolve_qe_epw_dbset_for_request,
    resolve_qe_epw_db_for_request,
)

try:
    import redis  # pip install redis
except Exception:
    redis = None
    
from celery.result import AsyncResult

router = APIRouter(prefix="/db/qe_epw", tags=["qe-epw-db"])

QE_EPW_CACHE_DIR = os.getenv("QE_EPW_CACHE_DIR", "/tmp")

QE_EPW_REDIS_LOCK_URL = os.getenv("CELERY_BROKER_URL", "")  # 复用你现有 env
QE_EPW_REDIS_LOCK_ENABLED = bool(QE_EPW_REDIS_LOCK_URL) and (redis is not None)

QE_EPW_CUSTOM_ADD_ALL_MAX_ROWS_DEFAULT = int(os.getenv("QE_EPW_CUSTOM_ADD_ALL_MAX_ROWS_DEFAULT", "20000"))
QE_EPW_CUSTOM_ADD_ALL_MAX_ROWS_HARD_LIMIT = int(os.getenv("QE_EPW_CUSTOM_ADD_ALL_MAX_ROWS_HARD_LIMIT", "200000"))

_qe_redis_client = None
_qe_redis_client_lock = Lock()

def _qe_acquire_dist_lock(lock_key: str, ttl: int = 600) -> Optional[str]:
    """
    简易 Redis 锁：SET key value NX EX ttl
    返回 token（成功）或 None（失败）
    """
    r = _qe_get_redis()
    if r is None:
        return None
    token = str(uuid.uuid4())
    ok = r.set(lock_key, token, nx=True, ex=int(ttl))
    return token if ok else None

def _qe_release_dist_lock(lock_key: str, token: str) -> None:
    """
    compare-and-del：只释放自己持有的锁
    """
    r = _qe_get_redis()
    if r is None:
        return
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

def _qe_wait_for_file(path: str, timeout: float = 60.0, interval: float = 0.25) -> bool:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if os.path.exists(path):
            return True
        time.sleep(interval)
    return os.path.exists(path)

def _qe_lock_key_for_cache_key(cache_key: str) -> str:
    # cache_key 已经是 sha1 了，直接用很合适
    return f"qe_epw:elements_scan:{cache_key}"

def _qe_get_redis():
    global _qe_redis_client
    if not QE_EPW_REDIS_LOCK_ENABLED:
        return None
    with _qe_redis_client_lock:
        if _qe_redis_client is None:
            _qe_redis_client = redis.Redis.from_url(QE_EPW_REDIS_LOCK_URL, decode_responses=True)
        return _qe_redis_client

# -----------------------------
# QE elements cache (memory)
# key: cache_key -> {"mtime": float, "elements": [..], "updated_at": float}
# plus scanning state
# -----------------------------
_qe_elems_lock = Lock()
_qe_elems_cache: Dict[str, Dict[str, Any]] = {}
_qe_scanning: Dict[str, Dict[str, Any]] = {}

def _qe_cache_key_for_refs(refs_ok, scope2: str, db: Optional[str]) -> str:
    """
    用 db+scope + 每个库 mtime 拼一个稳定 key，库变化自动失效。
    """
    mt = []
    for r in refs_ok:
        try:
            m = float(r.dbpath.stat().st_mtime)
        except Exception:
            m = 0.0
        mt.append((r.key, m))
    mt.sort(key=lambda x: x[0])

    obj = {
        "db": str(db or ""),
        "scope": str(scope2),
        "dbs": mt,
    }
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def _qe_mark_scanning(key: str) -> None:
    with _qe_elems_lock:
        _qe_scanning[key] = {"started_at": time.time()}

def _qe_is_scanning(key: str) -> bool:
    with _qe_elems_lock:
        return key in _qe_scanning

def _qe_set_cache(key: str, elements: List[str]) -> None:
    # 先写内存 + 清 scanning
    with _qe_elems_lock:
        _qe_elems_cache[key] = {"elements": elements, "updated_at": time.time()}
        _qe_scanning.pop(key, None)

    # 再落盘（失败不影响主流程）
    try:
        _qe_write_file_cache(key, elements)
    except Exception:
        pass

def _qe_get_cache(key: str) -> Optional[List[str]]:
    with _qe_elems_lock:
        item = _qe_elems_cache.get(key)
        if not item:
            return None
        arr = item.get("elements")
        return arr if isinstance(arr, list) else None
    
def _qe_set_cache_memory_only(key: str, elements: List[str]) -> None:
    with _qe_elems_lock:
        _qe_elems_cache[key] = {"elements": elements, "updated_at": time.time()}
        _qe_scanning.pop(key, None)

def _qe_scan_elements_background(key: str, refs_ok, lock_token: Optional[str] = None) -> None:
    """
    后台线程扫描元素并写入缓存；如果传了 lock_token，则结束时释放 Redis 锁。
    """
    lock_key = _qe_lock_key_for_cache_key(key)
    try:
        elems: Set[str] = set()
        for ref in refs_ok:
            con = _connect_sqlite(str(ref.dbpath))
            try:
                if not _has_tables(con):
                    continue
                cur = con.execute("SELECT structure_json FROM runs WHERE structure_json IS NOT NULL")
                for r in cur.fetchall():
                    elems |= _extract_elements_from_structure_json(r["structure_json"])
            finally:
                con.close()

        out = sorted(elems)
        _qe_set_cache(key, out)
    except Exception:
        # 出错也要解除 scanning，避免永远卡 scanning
        with _qe_elems_lock:
            _qe_scanning.pop(key, None)
    finally:
        if lock_token:
            _qe_release_dist_lock(lock_key, lock_token)

def _qe_elems_cache_file_path(cache_key: str) -> str:
    os.makedirs(QE_EPW_CACHE_DIR, exist_ok=True)
    return os.path.join(QE_EPW_CACHE_DIR, f"qe_epw_elements_{cache_key}.json")

def _qe_read_file_cache(cache_key: str) -> Optional[List[str]]:
    path = _qe_elems_cache_file_path(cache_key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return None
        arr = payload.get("elements")
        if not isinstance(arr, list):
            return None
        return [str(x) for x in arr if str(x).strip()]
    except Exception:
        return None

def _qe_write_file_cache(cache_key: str, elements: List[str]) -> None:
    path = _qe_elems_cache_file_path(cache_key)
    tmp = f"{path}.tmp.{os.getpid()}"
    payload = {
        "cache_key": cache_key,
        "elements": [str(x) for x in elements],
        "updated_at": time.time(),
    }
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    os.replace(tmp, path)  # atomic replace

def _qe_kickoff_scan(key: str, refs_ok, lock_token: Optional[str] = None) -> None:
    t = Thread(target=_qe_scan_elements_background, args=(key, refs_ok, lock_token), daemon=True)
    t.start()

# -----------------------------
# Upload config (QE+EPW)
# -----------------------------
QE_EPW_UPLOADS_ROOT = Path(os.getenv(
    "QE_EPW_UPLOADS_ROOT",
    "/app/var/uploads/qe_epw",
)).resolve()

QE_EPW_MAX_UPLOAD_BYTES = int(os.getenv("QE_EPW_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024 * 1024)))  # 10000MB

QE_EPW_IMPORT_SCRIPT = os.getenv(
    "QE_EPW_IMPORT_SCRIPT",
    "/app/utils/qe_epw_to_db.py",
)
QE_EPW_IMPORT_TIMEOUT = int(os.getenv("QE_EPW_IMPORT_TIMEOUT", "1800"))  # 30min

QE_EPW_CUSTOM_DB_ROOT = Path(os.getenv(
    "QE_EPW_CUSTOM_DB_ROOT",
    "/app/var/Customized_database/qe_epw"
)).resolve()

def _qe_custom_user_dir(alias: str) -> Path:
    """
    仅用于落盘路径拼接（create/add）。
    列举/权限/解析由 authz_db.py 负责。
    """
    p = (QE_EPW_CUSTOM_DB_ROOT / (alias or "").strip()).resolve()
    # 防止路径穿越
    if QE_EPW_CUSTOM_DB_ROOT not in p.parents and p != QE_EPW_CUSTOM_DB_ROOT:
        raise HTTPException(status_code=400, detail="invalid custom user dir")
    return p

def _qe_custom_db_path(alias: str, safe_name: str) -> Path:
    udir = _qe_custom_user_dir(alias)
    p = (udir / f"{safe_name}.sqlite").resolve()
    if udir not in p.parents:
        raise HTTPException(status_code=400, detail="invalid custom db path")
    return p

UPLOAD_DB_PREFIX = "upload:"

def _safe_db_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        raise HTTPException(status_code=400, detail="数据库名不能为空")
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "_", s)
    s = s.strip().replace(" ", "_")
    if len(s) > 64:
        raise HTTPException(status_code=400, detail="数据库名过长（>64）")
    return s

class CreateCustomQeReq(BaseModel):
    name: str

class _DbRefLike:
    """
    轻量 ref：兼容你现有代码里用到的字段
    kind/key/label/dbname/dbpath/exists/missingReason
    """
    def __init__(self, *, kind: str, key: str, label: str, dbname: str, dbpath: Path, exists: bool, missingReason: Optional[str] = None):
        self.kind = kind
        self.key = key
        self.label = label
        self.dbname = dbname
        self.dbpath = dbpath
        self.exists = exists
        self.missingReason = missingReason

class AddToCustomQeReq(BaseModel):
    target: str   # 目标自定义库 safe name，例如 "myset1"
    src_db: str   # 源 db key（owner:... / upload:... / custom_qe_epw:...）
    row_id: int
    
class AddAllToCustomQeReq(BaseModel):
    target: str
    db: Optional[str] = None
    scope: str = "all"              # all | personal | upload | custom
    elems: Optional[str] = None
    elem_mode: str = "at_least"     # at_least | only
    cp_filters: Optional[str] = None  # ✅ 新增：与 /tasks 一致的 JSON string
    max_rows: int = 0
    
class RemoveFromCustomQeReq(BaseModel):
    db_key: str   # custom_qe_epw:{alias}:{file}.sqlite
    row_id: int
    missing_ok: int = 1   # 1=行不存在也当成功（幂等）
    
def _safe_name(fn: str) -> str:
    base = os.path.basename((fn or "").strip())
    if not base:
        return ""
    # 简单清洗：去掉奇怪字符
    # 允许：字母数字._-+
    out = []
    for ch in base:
        if ch.isalnum() or ch in "._-+":
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out)
    # 防止超长
    return s[:200]


def _upload_user_root(alias: str) -> Path:
    p = (QE_EPW_UPLOADS_ROOT / alias).resolve()
    if QE_EPW_UPLOADS_ROOT not in p.parents and p != QE_EPW_UPLOADS_ROOT:
        raise HTTPException(status_code=400, detail="invalid upload user root")
    return p


def _upload_runs_root(alias: str) -> Path:
    return (_upload_user_root(alias) / "runs").resolve()


def _upload_dbs_root(alias: str) -> Path:
    return (_upload_user_root(alias) / "dbs").resolve()


def _parse_upload_db_key(db_key: Optional[str], current_alias: str) -> Optional[_DbRefLike]:
    """
    支持 db=upload:{alias}:{filename}
    只允许访问自己的 upload db（避免越权读文件）。
    """
    if not db_key:
        return None
    s = str(db_key).strip()
    if not s.startswith(UPLOAD_DB_PREFIX):
        return None

    parts = s.split(":", 2)  # upload, alias, filename
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="invalid upload db key format, expected upload:{alias}:{filename}")

    _tag, alias, fname = parts[0], parts[1], parts[2]
    alias = (alias or "").strip()
    fname = _safe_name(fname)

    if not alias or not fname:
        raise HTTPException(status_code=400, detail="invalid upload db key")

    # ✅ 只允许访问自己的上传库
    if alias != (current_alias or "").strip():
        raise HTTPException(status_code=403, detail="forbidden: cannot access other user's upload db")

    dbpath = (_upload_dbs_root(alias) / fname).resolve()
    exists = dbpath.exists() and dbpath.is_file()
    miss = None if exists else "upload db file missing"

    return _DbRefLike(
        kind="db",
        key=f"{UPLOAD_DB_PREFIX}{alias}:{fname}",
        label=f"上传库 ({alias})",
        dbname=fname,
        dbpath=dbpath,
        exists=exists,
        missingReason=miss,
    )


def _list_upload_dbs(alias: str) -> List[_DbRefLike]:
    """
    列出该用户上传过的 db 文件（dbs 目录下 .sqlite/.db）
    """
    root = _upload_dbs_root(alias)
    if not root.exists():
        return []
    out: List[_DbRefLike] = []
    for fp in sorted(root.glob("*")):
        if not fp.is_file():
            continue
        if fp.suffix.lower() not in (".sqlite", ".db"):
            continue
        key = f"{UPLOAD_DB_PREFIX}{alias}:{fp.name}"
        out.append(_DbRefLike(
            kind="db",
            key=key,
            label=f"上传库 ({alias})",
            dbname=fp.name,
            dbpath=fp.resolve(),
            exists=True,
            missingReason=None,
        ))
    return out

DEFAULT_COLS = [
    "id",
    "structure",
    "code",
    "calc_type",
    "efermi_ev",
    "total_energy_ev",
    "ecutwfc_ry",
    "ecutrho_ry",
    "qgrid",
    "nqpoints",
    "out_path",
    "mtime_utc",
]

# -----------------------------
# Derived columns: mobility@300K (shown in outer runs table)
# -----------------------------
MOBILITY_300K_COLS: List[str] = [
    # electron @ 300K
    "mobility.electron.fermi_ev@300K",
    "mobility.electron.density_cm2@300K",
    "mobility.electron.mu_x_cm2Vs@300K",
    "mobility.electron.mu_y_cm2Vs@300K",
    "mobility.electron.table_key@300K",

    # hole @ 300K
    "mobility.hole.fermi_ev@300K",
    "mobility.hole.density_cm2@300K",
    "mobility.hole.mu_x_cm2Vs@300K",
    "mobility.hole.mu_y_cm2Vs@300K",
    "mobility.hole.table_key@300K",
]

# 外表默认显示哪些 300K mobility 列（你不想默认显示可改成 []）
MOBILITY_300K_DEFAULT: List[str] = [
    "mobility.electron.mu_x_cm2Vs@300K",
    "mobility.hole.mu_x_cm2Vs@300K",
]

# -----------------------------
# Derived columns: epw_params.* (shown in outer runs table)
# -----------------------------
EPW_PARAMS_COLS: List[str] = [
    "epw_params.ncarrier",
    "epw_params.nk",
    "epw_params.nkf",
    "epw_params.nq",
    "epw_params.nqf",
]

# 外表默认显示哪些 epw_params 列（你不想默认显示可改成 []）
EPW_PARAMS_DEFAULT: List[str] = [
    "epw_params.ncarrier",
    "epw_params.nk",
    "epw_params.nq",
]

def _is_temp_k(x: Any, target: float) -> bool:
    try:
        return abs(float(x) - float(target)) < 1e-6
    except Exception:
        return False

def _connect_sqlite(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con

def _has_tables(con: sqlite3.Connection) -> bool:
    cur = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {r["name"] for r in cur.fetchall()}
    return ("runs" in names)

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
    return [r for r in refs if bool(getattr(r, "exists", True)) and r.dbpath and str(r.dbpath)]

def _rows_to_items(rows: List[sqlite3.Row], dbKey: str, dbname: str, wanted_cols: List[str]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for r in rows:
        it: Dict[str, Any] = {
            "_dbKey": dbKey,
            "_dbName": dbname,
            "_rowId": int(r["id"]),
        }
        keys = set(r.keys())
        for c in wanted_cols:
            it[c] = r[c] if c in keys else None
        items.append(it)
    return items

def _extract_elements_from_structure_json(s: Optional[str]) -> Set[str]:
    if not s:
        return set()
    try:
        obj = json.loads(s)
    except Exception:
        return set()

    # 你脚本里 structure_json 是 parse_qe_input 的 dict
    # 其中 atomic_positions: { unit, atoms: [{element, coord:[...]}, ...] }
    ap = obj.get("atomic_positions") if isinstance(obj, dict) else None
    atoms = ap.get("atoms") if isinstance(ap, dict) else None
    if not isinstance(atoms, list):
        return set()

    out: Set[str] = set()
    for a in atoms:
        if not isinstance(a, dict):
            continue
        el = a.get("element")
        if not el:
            continue
        s2 = str(el).strip()
        if not s2:
            continue
        # 规范化：首字母大写，其余小写
        if len(s2) == 1:
            s2 = s2.upper()
        else:
            s2 = s2[0].upper() + s2[1:].lower()
        out.add(s2)
    return out

def _parse_elems_param(elems: Optional[str]) -> List[str]:
    """
    elems: "Si,O,  H" -> ["Si","O","H"] (去重、规范化、保持输入顺序尽量稳定)
    """
    if not elems:
        return []
    raw = [x.strip() for x in str(elems).split(",")]
    out: List[str] = []
    seen: Set[str] = set()
    for x in raw:
        if not x:
            continue
        # 规范化：首字母大写其余小写
        if len(x) == 1:
            x2 = x.upper()
        else:
            x2 = x[0].upper() + x[1:].lower()
        if x2 not in seen:
            seen.add(x2)
            out.append(x2)
    return out

def _get_by_path(obj: Any, path: str) -> Any:
    if obj is None:
        return None
    cur = obj
    for part in str(path or "").split("."):
        if part == "":
            continue
        if not isinstance(cur, dict):
            return None
        if part not in cur:
            return None
        cur = cur[part]
    return cur

def _normalize_cp_path_qe(p: str) -> str:
    s = (p or "").strip()
    if not s:
        return ""

    # 允许用户写 runs.xxx / structure.xxx / epw_params.xxx / meta.xxx
    # 也允许直接写 calc_type 这种 runs 列名
    if s.startswith("runs."):
        return s[len("runs."):]
    return s

def _parse_cp_filters_qe(cp_filters: Optional[str]) -> List[Dict[str, Any]]:
    if not cp_filters:
        return []
    try:
        obj = json.loads(cp_filters)
    except Exception:
        return []
    if not isinstance(obj, list):
        return []
    out: List[Dict[str, Any]] = []
    for it in obj:
        if not isinstance(it, dict):
            continue
        path = str(it.get("path", "")).strip()
        op = str(it.get("op", "eq")).strip().lower()
        val = it.get("value", None)
        if not path:
            continue
        if op not in ("eq", "in"):
            op = "eq"

        # in 的 value 必须是 list；否则退化成 eq
        if op == "in" and not isinstance(val, list):
            op = "eq"

        out.append({"path": path, "op": op, "value": val})
    return out

def _canon(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        try:
            return format(float(v), ".12g") if isinstance(v, float) else str(v)
        except Exception:
            return str(v)
    if isinstance(v, (list, dict)):
        try:
            return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            return str(v)
    if isinstance(v, str):
        s = v.strip()
        # 尝试把 JSON 字符串标准化
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                return _canon(json.loads(s))
            except Exception:
                return s
        # 尝试把数字字符串标准化
        try:
            f = float(s)
            return format(f, ".12g")
        except Exception:
            return s
    return str(v)

def _parse_mobility_path(path: str) -> Dict[str, Any]:
    """
    支持：
      mobility.<carrier>.<field>@300K
      mobility.<carrier>.<field>
      mobility.<field>@300K
      mobility.<field>

    返回：
      {
        "ok": bool,
        "carrier": "electron"|"hole"|None,
        "field": "mu_x_cm2Vs"|...,
        "temp_K": float|None
      }
    """
    s = (path or "").strip()
    if not s.startswith("mobility."):
        return {"ok": False}

    rest = s[len("mobility."):].strip()
    if not rest:
        return {"ok": False}

    # temp suffix: @300K
    temp_K = None
    if "@" in rest:
        left, right = rest.rsplit("@", 1)
        rest = left.strip()
        rr = right.strip().upper()
        if rr.endswith("K"):
            rr = rr[:-1].strip()
        try:
            temp_K = float(rr)
        except Exception:
            temp_K = None

    parts = [x.strip() for x in rest.split(".") if x.strip()]
    carrier = None
    field = None

    if len(parts) == 1:
        # mobility.mu_x_cm2Vs
        field = parts[0]
    elif len(parts) == 2:
        # mobility.electron.mu_x_cm2Vs
        if parts[0].lower() in ("electron", "hole"):
            carrier = parts[0].lower()
            field = parts[1]
        else:
            # mobility.xxx.yyy（不支持）
            return {"ok": False}
    else:
        return {"ok": False}

    # 允许筛的 mobility 列（与你 mobility 表结构对齐）
    allowed = {"temp_K", "fermi_ev", "density_cm2", "mu_x_cm2Vs", "mu_y_cm2Vs"}
    if field not in allowed:
        return {"ok": False}

    return {"ok": True, "carrier": carrier, "field": field, "temp_K": temp_K}


def _mobility_match(
    mob_rows_for_run: List[Dict[str, Any]],
    carrier: Optional[str],
    field: str,
    temp_K: Optional[float],
    target_value: Any,
) -> bool:
    """
    支持：
      - target_value 是标量：eq
      - target_value 是 list：in（任意一个命中）
    """
    targets = target_value if isinstance(target_value, list) else [target_value]
    want_set = set(_canon(x) for x in targets)

    for r in (mob_rows_for_run or []):
        try:
            c = str(r.get("carrier") or "").strip().lower()
        except Exception:
            c = ""

        if carrier and c != carrier:
            continue

        if temp_K is not None:
            try:
                if not _is_temp_k(r.get("temp_K"), float(temp_K)):
                    continue
            except Exception:
                continue

        v = r.get(field)
        if _canon(v) in want_set:
            return True

    return False

def _qe_match_one_filter(
    run_row: sqlite3.Row,
    struct_obj: Any,
    epw_obj: Any,
    meta_obj: Any,
    flt: Dict[str, Any],
    mob_map: Optional[Dict[int, List[Dict[str, Any]]]] = None,
) -> bool:
    path = str(flt.get("path") or "").strip()
    op = str(flt.get("op") or "eq").strip().lower()
    target = flt.get("value", None)

    # --- mobility.* ---
    if path.startswith("mobility."):
        parsed = _parse_mobility_path(path)
        if not parsed.get("ok"):
            return False
        rid = int(run_row["id"]) if ("id" in run_row.keys() and run_row["id"] is not None) else 0
        rows = (mob_map or {}).get(rid, [])

        if op in ("eq", "in"):
            return _mobility_match(
                mob_rows_for_run=rows,
                carrier=parsed.get("carrier"),
                field=parsed.get("field"),
                temp_K=parsed.get("temp_K"),
                target_value=target,
            )
        return False

    # --- structure/epw_params/meta/runs ---
    if path.startswith("structure."):
        v = _get_by_path(struct_obj, path[len("structure."):])
    elif path.startswith("epw_params."):
        v = _get_by_path(epw_obj, path[len("epw_params."):])
    elif path.startswith("meta."):
        v = _get_by_path(meta_obj, path[len("meta."):])
    else:
        col = _normalize_cp_path_qe(path)
        try:
            v = run_row[col] if (col in run_row.keys()) else None
        except Exception:
            v = None

    if op == "eq":
        return _canon(v) == _canon(target)

    if op == "in":
        if not isinstance(target, list):
            return False
        want = set(_canon(x) for x in target)
        return _canon(v) in want

    return False

def _stable_content_hash_for_run_dict(run_dict: Dict[str, Any]) -> str:
    """
    为 QE runs 行生成稳定 content_hash（用于自定义库去重）。
    优先使用“结构+关键json+关键字段”，避免把 id/时间戳带进去导致不稳定。
    """
    keys = [
        "code",
        "calc_type",
        "structure_json",
        "epw_params_json",
        "meta_json",
        "qe_in_path",
        "epw_in_path",
        "prefix",
        "out_path",
        "workdir",
    ]
    obj = {k: run_dict.get(k) for k in keys}
    s = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode("utf-8")).hexdigest()

def _match_elements(struct_elems: Set[str], selected: Set[str], mode: str) -> bool:
    """
    mode:
      - at_least: struct_elems ⊇ selected
      - only:     struct_elems == selected
    """
    if not selected:
        return True

    if mode == "only":
        return struct_elems == selected

    # default: at_least
    return struct_elems.issuperset(selected)

def _scope_norm(scope: Optional[str]) -> str:
    s = (scope or "all").strip().lower()
    return s if s in ("all", "personal", "upload", "custom") else "all"

def _merge_page_pairs_kway(per_db_ids: Dict[str, List[int]], offset: int, limit: int) -> List[tuple[str, int]]:
    """
    多路归并：每个列表必须已排序。
    输出排序规则与 VASP 保持一致：按 (dbKey, rowId) 排序。
    """
    if limit <= 0:
        return []

    keys = sorted(per_db_ids.keys())
    heap: List[tuple[str, int, int]] = []  # (dbKey, rowId, idx_in_list)

    for k in keys:
        ids = per_db_ids.get(k) or []
        if ids:
            heappush(heap, (k, int(ids[0]), 0))

    out: List[tuple[str, int]] = []
    need = offset + limit
    seen = 0

    while heap and seen < need:
        k, rid, idx = heappop(heap)
        if seen >= offset:
            out.append((k, rid))
        seen += 1

        ids = per_db_ids.get(k) or []
        nxt = idx + 1
        if nxt < len(ids):
            heappush(heap, (k, int(ids[nxt]), nxt))

    return out


def _resolve_qe_epw_refs_for_request(alias: str, db: Optional[str], scope: Optional[str]):
    """
    统一把 scope + db 解析成 refs（支持 upload + owner）。
    - db=upload:... -> 单库
    - scope=upload -> 只返回 upload 库列表（db 为空时，表示合并全部 upload）
    - scope=personal -> 只返回 owner refs
    - scope=all -> owner refs + upload refs（合并）
    """
    scope2 = _scope_norm(scope)

    # 1) 直接选择了 upload 单库
    up_ref = _parse_upload_db_key(db, alias)
    if up_ref is not None:
        return [up_ref], [up_ref] if up_ref.exists else []
    
    # 1.5) 选择了 custom 单库：交给 authz_db 解析（支持 custom_qe_epw:...）
    if db and str(db).strip().startswith("custom_qe_epw:"):
        if _scope_norm(scope) != "custom":
            raise HTTPException(status_code=400, detail="custom database is not allowed in scope=all/personal/upload")
        ref = resolve_qe_epw_db_for_request(alias, db)
        return [ref], [ref] if getattr(ref, "exists", True) else []
    # 2) scope=upload 且 db 为空：不要走 owner resolver（否则会触发 “root must specify owner or db”）
    if scope2 == "upload":
        upload_refs = _list_upload_dbs(alias)
        upload_ok = [r for r in upload_refs if r.exists]
        return upload_refs, upload_ok

    if scope2 == "custom":
        # authz_db 统一管理 custom
        custom_refs = list_accessible_qe_epw_dbs(alias, scope="custom")
        # 只取 qe_custom
        custom_refs = [r for r in custom_refs if getattr(r, "kind", "") == "qe_custom"]
        custom_ok = _existing_refs(custom_refs)
        return custom_refs, custom_ok

    # 3) owner refs（个人/授权库）
    owner_refs = resolve_qe_epw_dbset_for_request(alias, db, scope=scope2)

    # ✅ 修复：scope!=custom 时，强制剔除自定义库 refs（避免 all/personal 混入 custom）
    if scope2 != "custom":
        owner_refs = [
            r for r in owner_refs
            if getattr(r, "kind", "") != "qe_custom"
            and not str(getattr(r, "key", "")).startswith("custom_qe_epw:")
        ]

    owner_ok = _existing_refs(owner_refs)

    # 4) upload refs（用户上传库）
    upload_refs = _list_upload_dbs(alias)
    upload_ok = [r for r in upload_refs if r.exists]

    if scope2 == "personal":
        return owner_refs, owner_ok

    # scope2 == "all"
    merged_refs = list(owner_refs) + list(upload_refs)
    merged_ok = list(owner_ok) + list(upload_ok)

    # ✅ 兜底：all/personal/upload 永远不返回 custom refs
    if scope2 != "custom":
        merged_refs = [
            r for r in merged_refs
            if getattr(r, "kind", "") != "qe_custom"
            and not str(getattr(r, "key", "")).startswith("custom_qe_epw:")
        ]
        merged_ok = [
            r for r in merged_ok
            if getattr(r, "kind", "") != "qe_custom"
            and not str(getattr(r, "key", "")).startswith("custom_qe_epw:")
        ]

    return merged_refs, merged_ok


def _get_all_ids_sqlite(con: sqlite3.Connection) -> List[int]:
    rows = con.execute("SELECT id FROM runs ORDER BY id ASC").fetchall()
    return [int(r["id"]) for r in rows]


def _compute_filtered_ids_for_db_qe(
    con: sqlite3.Connection,
    selected_elems: Set[str],
    mode: str,
    cp_flts: List[Dict[str, Any]],
) -> Optional[List[int]]:
    """
    返回：
      - None: 表示“全表”（无 elems 筛选）
      - List[int]: 满足筛选条件的 run ids（升序）
    """
    mode2 = (mode or "at_least").strip().lower()
    if mode2 not in ("at_least", "only"):
        mode2 = "at_least"

    # 无筛选：全表（只有当 elems 为空 且 cp_flts 也为空）
    if (not selected_elems) and (not cp_flts):
        return None

    cand = con.execute("SELECT * FROM runs").fetchall()
    # --- mobility 预取（仅当筛选里出现 mobility.* 才做）---
    need_mob = any(str(f.get("path") or "").strip().startswith("mobility.") for f in (cp_flts or []))
    mob_map: Dict[int, List[Dict[str, Any]]] = {}

    if need_mob and _sqlite_table_exists(con, "mobility"):
        # 只取需要的列，避免 raw_json
        mob_rows = con.execute(
            """
            SELECT run_id, carrier, temp_K, fermi_ev, density_cm2, mu_x_cm2Vs, mu_y_cm2Vs
            FROM mobility
            """
        ).fetchall()

        for mr in mob_rows:
            try:
                rid = int(mr["run_id"])
            except Exception:
                continue
            mob_map.setdefault(rid, []).append({
                "carrier": mr["carrier"],
                "temp_K": mr["temp_K"],
                "fermi_ev": mr["fermi_ev"],
                "density_cm2": mr["density_cm2"],
                "mu_x_cm2Vs": mr["mu_x_cm2Vs"],
                "mu_y_cm2Vs": mr["mu_y_cm2Vs"],
            })

    matched: List[int] = []
    for rr in cand:
        rid = int(rr["id"])
        struct_json = rr["structure_json"] if "structure_json" in rr.keys() else None
        struct_elems = _extract_elements_from_structure_json(struct_json)
        if not _match_elements(struct_elems, selected_elems, mode2):
            continue

        # cp_filters
        if cp_flts:
            try:
                struct_obj = json.loads(rr["structure_json"]) if rr["structure_json"] else None
            except Exception:
                struct_obj = None
            try:
                epw_obj = json.loads(rr["epw_params_json"]) if ("epw_params_json" in rr.keys() and rr["epw_params_json"]) else None
            except Exception:
                epw_obj = None
            try:
                meta_obj = json.loads(rr["meta_json"]) if ("meta_json" in rr.keys() and rr["meta_json"]) else None
            except Exception:
                meta_obj = None

            ok = True
            for flt in cp_flts:
                if not _qe_match_one_filter(rr, struct_obj, epw_obj, meta_obj, flt, mob_map=mob_map):
                    ok = False
                    break
            if not ok:
                continue

        matched.append(rid)

    matched.sort()
    return matched

def _sqlite_table_exists(con: sqlite3.Connection, name: str) -> bool:
    r = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return r is not None


def _create_table_like(src_con: sqlite3.Connection, dst_con: sqlite3.Connection, table: str) -> None:
    """
    用 PRAGMA table_info 复制一个“近似 schema”：
    - 保留列名/类型
    - 尽量保留 pk（若存在）
    注意：不会复制索引/触发器/外键约束（够用且更稳）。
    """
    cols = src_con.execute(f"PRAGMA table_info({table})").fetchall()
    if not cols:
        raise HTTPException(status_code=400, detail=f"table not found or empty schema: {table}")

    col_defs = []
    pk_cols = []
    for c in cols:
        # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
        name = c[1]
        ctype = c[2] or ""
        notnull = bool(c[3])
        dflt = c[4]
        pk = int(c[5] or 0)

        if pk:
            pk_cols.append(name)

        s = f'"{name}" {ctype}'.strip()
        if notnull:
            s += " NOT NULL"
        if dflt is not None:
            # dflt_value 是 SQL literal，直接拼
            s += f" DEFAULT {dflt}"
        col_defs.append(s)

    pk_sql = ""
    if pk_cols:
        pk_sql = ", PRIMARY KEY (" + ",".join([f'"{x}"' for x in pk_cols]) + ")"

    sql = 'CREATE TABLE IF NOT EXISTS "{}" ({})'.format(table, ",".join(col_defs) + pk_sql)
    dst_con.execute(sql)

def _container_path_from_out_path(out_path: str) -> str:
    # 你要求：前面加 /mnt
    p = (out_path or "").strip()
    if not p:
        return ""
    if p.startswith("/mnt/"):
        return p
    if p.startswith("/"):
        return "/mnt" + p
    # 极端情况：不是绝对路径
    return "/mnt/" + p


def _parse_pwscf_bands_from_stdout(text: str):
    """
    解析 QE pw.x 的能带输出（如 bs.out 的内容），返回:
    {
        "energies": [[E_band1(k1), ...], ...],  # [nbands][nkpts]
        "kpoints": [(kx, ky, kz), ...],
        "x": [..],                              # [nkpts] 累计距离
        "label_indices": [..],                  # 默认每 20 个点一个（可被 bs.in 的高对称点覆盖）
        "fermi": None or float,
        "nbands": int,
        "nkpts": int
    }

    兼容点：
    - k 行可能出现数字黏连：0.1667-0.0000
    - bands (ev)/(eV) 大小写差异
    - 冒号可有可无，行尾可能跟着能量
    - ( ... PWs ) 部分格式可能不同
    """
    if not text:
        return None

    # nbands 仅参考（声明值）
    m_nb = re.search(r'number of Kohn-Sham states\s*=\s*(\d+)', text, re.IGNORECASE)
    nbands_decl = int(m_nb.group(1)) if m_nb else None

    # Fermi（bs.out 通常没有；有就抓）
    m_fe = re.search(r'Fermi energy\s+is\s+([-\d\.Ee+]+)\s*eV', text, re.IGNORECASE)
    fermi = float(m_fe.group(1)) if m_fe else None

    float_pat = r'[-+]?\d*\.?\d+(?:[Ee][+-]?\d+)?'

    head_pat = re.compile(
        r'^\s*k\s*=.*bands\s*\(\s*e?v\s*\)\s*:?.*$',
        re.M | re.I
    )

    def parse_k_from_head_line(line: str):
        # 只取 '=' 后面到 '(' 前，避免 PWs 等数字干扰
        if '=' not in line:
            return None
        tail = line.split('=', 1)[1]
        tail = tail.split('(', 1)[0]
        nums = re.findall(float_pat, tail)
        if len(nums) < 2:
            return None
        kx = float(nums[0])
        ky = float(nums[1])
        kz = float(nums[2]) if len(nums) >= 3 else 0.0
        return (kx, ky, kz)

    lines = text.splitlines()
    n = len(lines)

    kpoints = []
    energies_by_k = []

    i = 0
    while i < n:
        if not head_pat.match(lines[i]):
            i += 1
            continue

        kp = parse_k_from_head_line(lines[i])
        if kp is None:
            return None
        kpoints.append(kp)

        i += 1
        block = []
        empty_seen = 0

        while i < n:
            if head_pat.match(lines[i]):
                break

            nums = re.findall(float_pat, lines[i])
            if nums:
                block.extend(float(x) for x in nums)
                i += 1
                empty_seen = 0
                continue

            if not lines[i].strip():
                empty_seen += 1
                i += 1
                if empty_seen <= 2:
                    continue
                else:
                    break

            break

        energies_by_k.append(block)

    if not kpoints or not energies_by_k:
        return None

    lengths = [len(row) for row in energies_by_k]

    if nbands_decl and nbands_decl > 0:
        nbands = nbands_decl
    else:
        # ✅ 关键修复：取“最常见长度”，而不是 min()
        from collections import Counter
        nbands = Counter(lengths).most_common(1)[0][0] if lengths else 0

    if nbands <= 0:
        return None

    # 截断或补齐到 nbands
    fixed = []
    for row in energies_by_k:
        if len(row) >= nbands:
            fixed.append(row[:nbands])
        else:
            fixed.append(row + [None] * (nbands - len(row)))
    energies_by_k = fixed

    nk = len(energies_by_k)

    # 转置 [band][k]
    energies = []
    for b in range(nbands):
        energies.append([energies_by_k[k][b] for k in range(nk)])

    # x 轴累计距离
    x_path = [0.0]
    for j in range(1, len(kpoints)):
        x1, y1, z1 = kpoints[j - 1]
        x2, y2, z2 = kpoints[j]
        dx, dy, dz = x2 - x1, y2 - y1, z2 - z1
        x_path.append(x_path[-1] + (dx*dx + dy*dy + dz*dz) ** 0.5)

    # 默认 label_indices（后续如果 bs.in 能解析出高对称点，会覆盖它）
    label_indices = [0]
    idx = 20
    while idx < nk:
        label_indices.append(idx)
        idx += 20
    if label_indices[-1] != nk - 1:
        label_indices[-1] = nk - 1

    return {
        "energies": energies,              # [nbands][nk]
        "kpoints": kpoints,                # [(kx,ky,kz)]
        "x": x_path,                       # [nk]
        "label_indices": label_indices,    # [..]
        "fermi": fermi,
        "nkpts": nk,
        "nbands": nbands,
    }
    
HARTREE_TO_EV = 27.211386245988  # 1 Ha = 27.211386245988 eV

def _read_text_file(path: str, max_bytes: int = 50 * 1024 * 1024) -> str:
    """
    安全读文本：限制最大读取字节，避免意外读超大文件。
    """
    with open(path, "rb") as f:
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"file too large: {path}")
    return data.decode("utf-8", errors="ignore")

def _find_qe_save_xml_near_bsout(bsout_path: str, prefix_hint: Optional[str] = None) -> Optional[str]:
    """
    在 bs.out 同目录寻找能级 XML：
    优先：
      1) 同目录下 *.save/data-file-schema.xml
         - 若 prefix_hint 存在，优先选择目录名包含 prefix_hint 的 *.save
         - 否则选择 mtime 最新的 *.save
    fallback：
      2) 同目录直接存在 data-file-schema.xml
    找不到返回 None
    """
    d = os.path.dirname(bsout_path)
    if not d or not os.path.isdir(d):
        return None

    # --- fallback 2: 同目录直接放了 data-file-schema.xml（你上传的情况）---
    direct = os.path.join(d, "data-file-schema.xml")
    if os.path.exists(direct) and os.path.isfile(direct):
        return direct

    # --- fallback 1: *.save/data-file-schema.xml（原逻辑）---
    save_dirs = []
    for p in sorted(Path(d).glob("*.save")):
        if p.is_dir():
            xmlp = p / "data-file-schema.xml"
            if xmlp.exists() and xmlp.is_file():
                save_dirs.append((p, xmlp))

    if not save_dirs:
        return None

    ph = (prefix_hint or "").strip()
    if ph:
        for sd, xmlp in save_dirs:
            if ph in sd.name:
                return str(xmlp)

    save_dirs.sort(key=lambda t: float(t[0].stat().st_mtime), reverse=True)
    return str(save_dirs[0][1])

def _parse_qe_levels_from_data_file_schema(xml_path: str) -> Dict[str, Optional[float]]:
    """
    尽量解析 QE *.save/data-file-schema.xml 中的能级信息。
    由于 smearing/金属性体系可能缺失 lowestUnoccupiedLevel，这里允许返回 None。

    返回单位：eV
    {
      "fermi_ev": float or None,
      "vbm_ev": float or None,
      "cbm_ev": float or None,
    }
    """
    xml_text = _read_text_file(xml_path)
    root = ET.fromstring(xml_text)

    def get_tag_float_optional(tag: str) -> Optional[float]:
        el = root.find(f".//{tag}")
        if el is None or el.text is None:
            return None
        s = el.text.strip().replace("D", "E")
        try:
            return float(s)
        except Exception:
            return None

    ef_ha = get_tag_float_optional("fermi_energy")
    vbm_ha = get_tag_float_optional("highestOccupiedLevel")
    cbm_ha = get_tag_float_optional("lowestUnoccupiedLevel")

    return {
        "fermi_ev": (ef_ha * HARTREE_TO_EV) if ef_ha is not None else None,
        "vbm_ev": (vbm_ha * HARTREE_TO_EV) if vbm_ha is not None else None,
        "cbm_ev": (cbm_ha * HARTREE_TO_EV) if cbm_ha is not None else None,
    }

def _shift_bands_by_reference(bands: List[List[Any]], ref_ev: float) -> List[List[float]]:
    """
    bands: [nbands][nk], elements are float or None
    return: shifted bands with np.nan for None
    """
    out: List[List[float]] = []
    for row in (bands or []):
        yy = []
        for v in (row or []):
            if v is None:
                yy.append(np.nan)
            else:
                yy.append(float(v) - float(ref_ev))
        out.append(yy)
    return out

def _infer_cbm_from_bands_given_vbm(bands: List[List[Any]], vbm_ev: float, eps: float = 1e-6) -> Optional[float]:
    """
    当 XML 缺失 CBM 时，用 bs.out 的本征值估算：
      CBM = min{ E | E > VBM + eps }  (全 k 全 band)
    bands: [nbands][nk]，元素 float 或 None
    返回：cbm_ev 或 None（例如金属：可能找不到明显大于 VBM 的值）
    """
    if vbm_ev is None:
        return None

    cbm = None
    thr = float(vbm_ev) + float(eps)

    for b in (bands or []):
        for e in (b or []):
            if e is None:
                continue
            try:
                ee = float(e)
            except Exception:
                continue
            if ee > thr:
                if cbm is None or ee < cbm:
                    cbm = ee
    return cbm

def _infer_vbm_cbm_from_bands_near_fermi(
    bands: List[List[Any]],
    ef_ev: float,
    eps: float = 1e-6,
) -> Dict[str, Optional[float]]:
    """
    当 XML 只有 Ef、没有 VBM/CBM 时，用 bs.out 的本征值估算：
      VBM = max{ E | E <= Ef - eps }
      CBM = min{ E | E >= Ef + eps }
    若某一侧不存在（极端情况），则退化为“离 Ef 最近的一个值”。

    返回：
      {"vbm_ev": float|None, "cbm_ev": float|None}
    """
    if ef_ev is None:
        return {"vbm_ev": None, "cbm_ev": None}

    ef = float(ef_ev)
    vbm = None
    cbm = None

    # 退化：记录整体最近点（防止全在一侧）
    best_below = None  # 最大的 <= ef
    best_above = None  # 最小的 >= ef

    thr_lo = ef - float(eps)
    thr_hi = ef + float(eps)

    for b in (bands or []):
        for e in (b or []):
            if e is None:
                continue
            try:
                ee = float(e)
            except Exception:
                continue

            # 记录“<= ef”的最大值（弱条件）
            if ee <= ef:
                if best_below is None or ee > best_below:
                    best_below = ee

            # 记录“>= ef”的最小值（弱条件）
            if ee >= ef:
                if best_above is None or ee < best_above:
                    best_above = ee

            # 严格按 eps 分开（强条件）
            if ee <= thr_lo:
                if vbm is None or ee > vbm:
                    vbm = ee
            if ee >= thr_hi:
                if cbm is None or ee < cbm:
                    cbm = ee

    # 若 eps 条件下找不到，就退回到弱条件（最近的两侧）
    if vbm is None:
        vbm = best_below
    if cbm is None:
        cbm = best_above

    return {"vbm_ev": vbm, "cbm_ev": cbm}

def _parse_qe_kpath_from_in(text: str):
    """
    解析 QE 输入中的 K_POINTS {crystal_b} 路径。

    期望格式：
      K_POINTS {crystal_b}
        m
      kx ky kz n
      ...
    其中最后一行的 n 通常会被 QE 忽略（只作为终点）。
    返回:
      points: List[(kx,ky,kz)]  # crystal coord.
      seg_n:  List[int]         # 每段点数（长度 m-1）
    解析不到返回 None
    """
    if not text:
        return None

    lines = text.splitlines()
    # 找到 K_POINTS 行
    idx = None
    for i, ln in enumerate(lines):
        s = ln.strip().lower()
        if s.startswith("k_points") and "crystal_b" in s:
            idx = i
            break
    if idx is None:
        return None

    # 找 m
    j = idx + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines):
        return None

    try:
        m = int(lines[j].strip().split()[0])
    except Exception:
        return None
    if m < 2:
        return None

    # 读 m 行 k 点
    points = []
    seg_n = []
    j += 1
    got = 0
    while j < len(lines) and got < m:
        s = lines[j].strip()
        j += 1
        if not s or s.startswith("!"):
            continue
        parts = s.replace("D", "E").split()
        if len(parts) < 4:
            continue
        try:
            kx, ky, kz = float(parts[0]), float(parts[1]), float(parts[2])
            n = int(float(parts[3]))
        except Exception:
            continue

        points.append((kx, ky, kz))
        got += 1
        if got < m:  # 最后一行的 n 通常忽略
            seg_n.append(int(n))

    if len(points) != m or len(seg_n) != m - 1:
        return None

    return {"points": points, "seg_n": seg_n}

def _infer_lattice_type_from_qe_in(in_text: str) -> str:
    """
    返回一个粗粒度晶系标签：
      cubic | tetragonal | orthorhombic | hexagonal | unknown

    优先：
      1) ibrav（若 !=0）
      2) CELL_PARAMETERS 计算 a,b,c 和 αβγ 推断
    """
    if not in_text:
        return "unknown"

    # 1) ibrav
    m = re.search(r'^\s*ibrav\s*=\s*([-\d]+)\s*$', in_text, flags=re.MULTILINE | re.IGNORECASE)
    if m:
        try:
            ibrav = int(m.group(1))
        except Exception:
            ibrav = 0

        # QE 常见 ibrav 映射（只做我们需要的粗分类）
        # 1: cubic P, 2: cubic F, 3: cubic I
        if ibrav in (1, 2, 3):
            return "cubic"
        # 4: hexagonal, 6: tetragonal P, 7: tetragonal I
        if ibrav in (4,):
            return "hexagonal"
        if ibrav in (6, 7):
            return "tetragonal"
        # 8~11 多为 orthorhombic / monoclinic / triclinic（这里先粗归 unknown/orthorhombic）
        if ibrav in (8, 9, 10, 11):
            return "orthorhombic"

    # 2) CELL_PARAMETERS 推断
    # 找 CELL_PARAMETERS 后 3 行向量
    lines = in_text.splitlines()
    idx = None
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("cell_parameters"):
            idx = i
            break
    if idx is None or idx + 3 >= len(lines):
        return "unknown"

    def _parse_vec(s: str):
        parts = s.strip().replace("D", "E").split()
        if len(parts) < 3:
            return None
        try:
            return [float(parts[0]), float(parts[1]), float(parts[2])]
        except Exception:
            return None

    a = _parse_vec(lines[idx + 1])
    b = _parse_vec(lines[idx + 2])
    c = _parse_vec(lines[idx + 3])
    if not a or not b or not c:
        return "unknown"

    import math

    def norm(v): return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2) or 1e-12
    def dot(u, v): return u[0]*v[0] + u[1]*v[1] + u[2]*v[2]
    def angle(u, v):
        x = dot(u, v) / (norm(u) * norm(v))
        x = max(-1.0, min(1.0, x))
        return math.degrees(math.acos(x))

    la, lb, lc = norm(a), norm(b), norm(c)
    alpha = angle(b, c)
    beta  = angle(a, c)
    gamma = angle(a, b)

    def close(x, y, tol=1e-2):  # 1% 相对容差（长度）
        if y == 0:
            return abs(x) < tol
        return abs(x - y) / max(abs(y), 1e-12) < tol

    def ang_close(x, y, tol=1.5):  # 角度容差 1.5°
        return abs(x - y) < tol

    # hex: a≈b, γ≈120°, α≈β≈90°
    if close(la, lb) and ang_close(gamma, 120.0) and ang_close(alpha, 90.0) and ang_close(beta, 90.0):
        return "hexagonal"

    # cubic: a≈b≈c, α≈β≈γ≈90°
    if close(la, lb) and close(lb, lc) and ang_close(alpha, 90.0) and ang_close(beta, 90.0) and ang_close(gamma, 90.0):
        return "cubic"

    # tetragonal: a≈b != c, α≈β≈γ≈90°
    if close(la, lb) and (not close(lb, lc)) and ang_close(alpha, 90.0) and ang_close(beta, 90.0) and ang_close(gamma, 90.0):
        return "tetragonal"

    # orthorhombic: α≈β≈γ≈90°（a,b,c 不全等）
    if ang_close(alpha, 90.0) and ang_close(beta, 90.0) and ang_close(gamma, 90.0):
        return "orthorhombic"

    return "unknown"

def _parse_qe_structure_from_in(in_text: str) -> Optional[Dict[str, Any]]:
    """
    从 QE 输入文本解析结构信息：
    - CELL_PARAMETERS angstrom/bohr/alat
    - ATOMIC_POSITIONS crystal
    - ATOMIC_SPECIES（用于得到元素符号；seekpath/spglib 真正需要的是原子号）

    返回：
    {
      "cell_ang": [[...],[...],[...]],   # Å
      "symbols": ["Mo","S","S"],
      "positions_frac": [[fx,fy,fz], ...]
    }
    解析失败返回 None
    """
    if not in_text:
        return None

    lines = in_text.splitlines()

    # ---- 1) 解析 ATOMIC_SPECIES：拿到元素符号集合（主要用于 positions 行的元素名校验）----
    species: Set[str] = set()
    idx_species = None
    for i, ln in enumerate(lines):
        if ln.strip().lower() == "atomic_species":
            idx_species = i
            break
    if idx_species is not None:
        j = idx_species + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s or s.startswith("!"):
                j += 1
                continue
            # 遇到新卡片就停（很宽松）
            if re.match(r"^[A-Z_]+\b", s) and s.split()[0].isupper() and s.split()[0] not in ("Mo", "S"):
                # 这条规则不完美，但够用；后面 positions 才是关键
                pass
            parts = s.split()
            if len(parts) >= 1 and parts[0][0].isalpha():
                # 典型：Mo 69.723 Mo.upf
                species.add(parts[0])
                j += 1
                continue
            break

    # ---- 2) 解析 CELL_PARAMETERS（单位可能是 angstrom/bohr/alat）----
    idx_cell = None
    cell_unit = "angstrom"
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("cell_parameters"):
            idx_cell = i
            # 取 unit（如 "CELL_PARAMETERS angstrom"）
            parts = ln.strip().split()
            if len(parts) >= 2:
                cell_unit = parts[1].strip().lower()
            break
    if idx_cell is None or idx_cell + 3 >= len(lines):
        return None

    def _parse_vec(s: str):
        parts = s.strip().replace("D", "E").split()
        if len(parts) < 3:
            return None
        try:
            return [float(parts[0]), float(parts[1]), float(parts[2])]
        except Exception:
            return None

    cell = [
        _parse_vec(lines[idx_cell + 1]),
        _parse_vec(lines[idx_cell + 2]),
        _parse_vec(lines[idx_cell + 3]),
    ]
    if any(v is None for v in cell):
        return None

    # 单位换算到 Å
    BOHR_TO_ANG = 0.529177210903
    if cell_unit in ("bohr", "a.u.", "au"):
        cell_ang = [[x * BOHR_TO_ANG for x in row] for row in cell]
    elif cell_unit in ("angstrom", "ang"):
        cell_ang = cell
    elif cell_unit == "alat":
        # alat 需要 celldm(1) 或 A；这里尽量从 in_text 里找
        # QE: celldm(1) (in bohr) or A (in angstrom)
        mA = re.search(r"^\s*A\s*=\s*([-\d\.Ee+]+)", in_text, flags=re.M | re.I)
        mcelldm = re.search(r"^\s*celldm\s*\(\s*1\s*\)\s*=\s*([-\d\.Ee+]+)", in_text, flags=re.M | re.I)
        scale_ang = None
        if mA:
            scale_ang = float(mA.group(1))
        elif mcelldm:
            scale_ang = float(mcelldm.group(1)) * BOHR_TO_ANG
        if not scale_ang:
            return None
        cell_ang = [[x * scale_ang for x in row] for row in cell]
    else:
        # 未知单位，先当 Å（保守）
        cell_ang = cell

    # ---- 3) 解析 ATOMIC_POSITIONS crystal ----
    idx_ap = None
    ap_unit = ""
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("atomic_positions"):
            idx_ap = i
            parts = ln.strip().split()
            ap_unit = parts[1].strip().lower() if len(parts) >= 2 else ""
            break
    if idx_ap is None:
        return None
    if ap_unit not in ("crystal", "crystal_sg"):
        # seekpath/spglib 最稳是分数坐标；若不是 crystal，你也可以扩展支持 alat/angstrom
        return None

    symbols: List[str] = []
    pos_frac: List[List[float]] = []
    j = idx_ap + 1
    while j < len(lines):
        s = lines[j].strip()
        j += 1
        if not s or s.startswith("!"):
            continue
        # 下一张卡片就停
        if re.match(r"^(K_POINTS|CELL_PARAMETERS|ATOMIC_SPECIES|ATOMIC_FORCES|CONSTRAINTS|OCCUPATIONS)\b", s, flags=re.I):
            break
        parts = s.replace("D", "E").split()
        if len(parts) < 4:
            continue
        el = parts[0]
        try:
            fx, fy, fz = float(parts[1]), float(parts[2]), float(parts[3])
        except Exception:
            continue
        symbols.append(el)
        pos_frac.append([fx, fy, fz])

    if not symbols or not pos_frac or len(symbols) != len(pos_frac):
        return None

    return {"cell_ang": cell_ang, "symbols": symbols, "positions_frac": pos_frac}

def _seekpath_point_dict_from_structure(struct: Dict[str, Any]) -> Optional[Dict[str, tuple]]:
    """
    用 spglib + seekpath 从结构得到标准高对称点坐标字典：
      {"GAMMA": (0,0,0), "M": (...), ...}
    返回坐标是在 reciprocal primitive 的 “fractional” 表示（seekpath 的 conventions）。
    我们后面用“近邻匹配”给 bs.in 端点贴标签。
    """
    try:
        import spglib  # noqa: F401
        import seekpath
    except Exception:
        return None

    cell_ang = struct.get("cell_ang")
    symbols = struct.get("symbols")
    pos_frac = struct.get("positions_frac")

    if not cell_ang or not symbols or not pos_frac:
        return None

    # 元素符号 -> 原子序数
    # 用一个轻量映射；你也可以换成 periodictable/pymatgen
    ZMAP = {
        "H": 1, "He": 2,
        "Li": 3, "Be": 4, "B": 5, "C": 6, "N": 7, "O": 8, "F": 9, "Ne": 10,
        "Na": 11, "Mg": 12, "Al": 13, "Si": 14, "P": 15, "S": 16, "Cl": 17, "Ar": 18,
        "K": 19, "Ca": 20,
        "Sc": 21, "Ti": 22, "V": 23, "Cr": 24, "Mn": 25, "Fe": 26, "Co": 27, "Ni": 28, "Cu": 29, "Zn": 30,
        "Ga": 31, "Ge": 32, "As": 33, "Se": 34, "Br": 35, "Kr": 36,
        "Rb": 37, "Sr": 38, "Y": 39, "Zr": 40, "Nb": 41, "Mo": 42, "Tc": 43, "Ru": 44, "Rh": 45, "Pd": 46,
        "Ag": 47, "Cd": 48, "In": 49, "Sn": 50, "Sb": 51, "Te": 52, "I": 53, "Xe": 54,
        "Cs": 55, "Ba": 56, "La": 57, "Ce": 58, "Pr": 59, "Nd": 60, "Pm": 61, "Sm": 62, "Eu": 63,
        "Gd": 64, "Tb": 65, "Dy": 66, "Ho": 67, "Er": 68, "Tm": 69, "Yb": 70, "Lu": 71,
        "Hf": 72, "Ta": 73, "W": 74, "Re": 75, "Os": 76, "Ir": 77, "Pt": 78, "Au": 79, "Hg": 80,
        "Tl": 81, "Pb": 82, "Bi": 83, "Po": 84, "At": 85, "Rn": 86,
    }

    numbers = []
    for s in symbols:
        ss = str(s).strip()
        # 规范化：首字母大写其余小写
        if len(ss) >= 2:
            ss = ss[0].upper() + ss[1:].lower()
        else:
            ss = ss.upper()
        z = ZMAP.get(ss)
        if not z:
            return None
        numbers.append(int(z))

    # seekpath 输入 cell: (lattice, positions, numbers)
    spcell = (np.array(cell_ang, dtype=float), np.array(pos_frac, dtype=float), np.array(numbers, dtype=int))

    # get_path 返回：point_coords / path / primitive_lattice 等
    res = seekpath.get_path(spcell)

    point_coords = res.get("point_coords")
    if not isinstance(point_coords, dict) or not point_coords:
        return None

    # point_coords: {"GAMMA":[0,0,0], "M":[...], ...}
    out = {}
    for k, v in point_coords.items():
        vv = tuple(float(x) for x in v)
        out[str(k)] = vv
    return out

def _label_kpt_by_seekpath(kp: tuple, sp_points: Dict[str, tuple], tol: float = 8e-3) -> str:
    """
    把 bs.in 里的端点 kp=(kx,ky,kz) 与 seekpath 的 point_coords 做近邻匹配。
    命中则返回 label（Γ/GAMMA 会转成 Γ），否则返回 ""。
    """
    if not sp_points:
        return ""

    kx, ky, kz = float(kp[0]), float(kp[1]), float(kp[2])

    best_lab = ""
    best_d2 = None
    for lab, v in sp_points.items():
        dx, dy, dz = (float(v[0]) - kx), (float(v[1]) - ky), (float(v[2]) - kz)
        d2 = dx*dx + dy*dy + dz*dz
        if best_d2 is None or d2 < best_d2:
            best_d2 = d2
            best_lab = str(lab)

    if best_d2 is None or best_d2 > (tol * tol):
        return ""

    # 统一 Γ 显示
    if best_lab.upper() in ("GAMMA", "Γ"):
        return "Γ"
    return best_lab

def _label_for_kpt_crystal(k, lattice_type: str = "unknown", tol=5e-3) -> str:
    """
    根据晶系(lattice_type)给常见高对称点贴标签。
    lattice_type: cubic | tetragonal | orthorhombic | hexagonal | unknown
    """
    kx, ky, kz = float(k[0]), float(k[1]), float(k[2])

    def close(a, b):
        return abs(a - b) < tol

    # Γ 永远成立
    if close(kx, 0.0) and close(ky, 0.0) and close(kz, 0.0):
        return "Γ"

    lt = (lattice_type or "unknown").lower().strip()

    # --- hexagonal 常用 ---
    if lt == "hexagonal":
        # M: (1/2,0,0), K:(1/3,1/3,0)
        if close(kx, 0.5) and close(ky, 0.0) and close(kz, 0.0):
            return "M"
        if close(kx, 1.0/3.0) and close(ky, 1.0/3.0) and close(kz, 0.0):
            return "K"
        return ""

    # --- cubic / tetragonal / orthorhombic（最常用的点名）---
    # 这里采用“最常见的 simple cubic / tetragonal P 路径命名”
    # 在这些体系里 (0.5,0,0) 更常叫 X
    if lt in ("cubic", "tetragonal", "orthorhombic"):
        # fcc 常用：L(0.5,0.5,0.5), W(0.25,0.75,0.5), K(0.375,0.75,0.375), U(0.625,0.625,0.25)
        if close(kx, 0.5) and close(ky, 0.5) and close(kz, 0.5):
            return "L"
        if close(kx, 0.25) and close(ky, 0.75) and close(kz, 0.5):
            return "W"
        if close(kx, 0.375) and close(ky, 0.75) and close(kz, 0.375):
            return "K"
        if close(kx, 0.625) and close(ky, 0.625) and close(kz, 0.25):
            return "U"
        if close(kx, 0.5) and close(ky, 0.0) and close(kz, 0.0):
            return "X"
        if close(kx, 0.5) and close(ky, 0.5) and close(kz, 0.0):
            return "M"
        if close(kx, 0.0) and close(ky, 0.0) and close(kz, 0.5):
            return "Z"  # tetragonal/orthorhombic 常用；cubic 有时叫 X_z，这里统一给 Z
        if close(kx, 0.5) and close(ky, 0.0) and close(kz, 0.5):
            return "R"
        if close(kx, 0.5) and close(ky, 0.5) and close(kz, 0.5):
            return "A"
        return ""

    # unknown：不乱贴标签
    return ""

def _contcar_from_cell_and_frac(cell_ang: List[List[float]], symbols: List[str], pos_frac: List[List[float]], title: str = "structure") -> str:
    """
    生成 VASP CONTCAR 字符串：
    - cell_ang: 3x3, Å
    - symbols: e.g. ["Pt","O","O"]
    - pos_frac: Nx3 fractional
    """
    if not cell_ang or len(cell_ang) != 3:
        raise ValueError("invalid cell")
    if not symbols or not pos_frac or len(symbols) != len(pos_frac):
        raise ValueError("invalid symbols/positions")

    # 统计元素顺序与计数（保持出现顺序）
    order: List[str] = []
    counts: Dict[str, int] = {}
    for s in symbols:
        ss = str(s).strip()
        if not ss:
            continue
        if len(ss) == 1:
            ss = ss.upper()
        else:
            ss = ss[0].upper() + ss[1:].lower()
        if ss not in counts:
            order.append(ss)
            counts[ss] = 0
        counts[ss] += 1

    # 按元素顺序重排坐标（CONTCAR 常规写法：先写某元素的所有原子）
    grouped_pos: List[List[float]] = []
    for el in order:
        for i, s in enumerate(symbols):
            ss = str(s).strip()
            if len(ss) == 1:
                ss = ss.upper()
            else:
                ss = ss[0].upper() + ss[1:].lower()
            if ss == el:
                grouped_pos.append([float(x) for x in pos_frac[i]])

    lines: List[str] = []
    lines.append(str(title or "structure"))
    lines.append("1.0")
    for v in cell_ang:
        lines.append(f"{float(v[0]): .16f} {float(v[1]): .16f} {float(v[2]): .16f}")
    lines.append(" ".join(order))
    lines.append(" ".join(str(counts[x]) for x in order))
    lines.append("Direct")
    for p in grouped_pos:
        lines.append(f"{float(p[0]): .16f} {float(p[1]): .16f} {float(p[2]): .16f}")
    lines.append("")
    return "\n".join(lines)


def _try_get_cell_frac_from_structure_json(struct_obj: Any) -> Optional[Dict[str, Any]]:
    """
    严格对齐你给的 structure_json 格式：
    structure_json:
      {
        "atomic_positions": {"unit":"crystal","atoms":[{"element":"Pt","coord":[...]} ...]},
        "cell_parameters": {"unit":"angstrom","lattice":[[...],[...],[...]]}
      }
    返回：
      {"cell_ang": 3x3, "symbols": [...], "positions_frac": Nx3}
    """
    if not isinstance(struct_obj, dict):
        return None

    ap = struct_obj.get("atomic_positions")
    cp = struct_obj.get("cell_parameters")

    # --- cell_parameters.unit + cell_parameters.lattice ---
    cell_ang = None
    if isinstance(cp, dict):
        unit = str(cp.get("unit") or "").strip().lower()
        lattice = cp.get("lattice")

        if isinstance(lattice, list) and len(lattice) == 3:
            try:
                lat = [[float(x) for x in row[:3]] for row in lattice]
            except Exception:
                lat = None

            if lat is not None:
                BOHR_TO_ANG = 0.529177210903
                if unit in ("angstrom", "ang"):
                    cell_ang = lat
                elif unit in ("bohr", "a.u.", "au"):
                    cell_ang = [[x * BOHR_TO_ANG for x in row] for row in lat]
                else:
                    # unknown：保守当作 Å
                    cell_ang = lat

    # --- atomic_positions.unit + atoms[].element/coord ---
    symbols: List[str] = []
    pos_frac: List[List[float]] = []
    if isinstance(ap, dict):
        unit = str(ap.get("unit") or "").strip().lower()
        atoms = ap.get("atoms")
        if unit in ("crystal", "crystal_sg") and isinstance(atoms, list):
            for a in atoms:
                if not isinstance(a, dict):
                    continue
                el = a.get("element")
                coord = a.get("coord")
                if not el or not isinstance(coord, (list, tuple)) or len(coord) < 3:
                    continue
                symbols.append(str(el))
                pos_frac.append([float(coord[0]), float(coord[1]), float(coord[2])])

    if cell_ang and symbols and pos_frac and len(symbols) == len(pos_frac):
        return {"cell_ang": cell_ang, "symbols": symbols, "positions_frac": pos_frac}

    return None


def _build_contcar_for_run_row(run_row: sqlite3.Row) -> Optional[str]:
    """
    对单条 runs 行生成 CONTCAR 文本：
    1) 优先从 structure_json（按你格式）生成
    2) 若失败，fallback 读 qe_in_path 解析（你已有 _parse_qe_structure_from_in）
    """
    title = None
    try:
        title = (run_row["structure"] if ("structure" in run_row.keys()) else None) or "structure"
    except Exception:
        title = "structure"

    # --- 1) structure_json ---
    struct_obj = None
    try:
        if "structure_json" in run_row.keys() and run_row["structure_json"]:
            struct_obj = json.loads(run_row["structure_json"])
    except Exception:
        struct_obj = None

    got = _try_get_cell_frac_from_structure_json(struct_obj)
    if got:
        try:
            return _contcar_from_cell_and_frac(
                cell_ang=got["cell_ang"],
                symbols=got["symbols"],
                pos_frac=got["positions_frac"],
                title=str(title),
            )
        except Exception:
            pass

    # --- 2) fallback：qe_in_path ---
    in_path = None
    try:
        in_path = run_row["qe_in_path"] if ("qe_in_path" in run_row.keys()) else None
    except Exception:
        in_path = None

    if in_path:
        host_in = _container_path_from_out_path(str(in_path))
        if host_in and os.path.exists(host_in) and os.path.isfile(host_in):
            try:
                in_text = _read_text_file(host_in, max_bytes=50 * 1024 * 1024)
                st = _parse_qe_structure_from_in(in_text)
                if st:
                    return _contcar_from_cell_and_frac(
                        cell_ang=st["cell_ang"],
                        symbols=st["symbols"],
                        pos_frac=st["positions_frac"],
                        title=str(title),
                    )
            except Exception:
                pass

    return None


def _safe_zip_member_name(name: str) -> str:
    """
    防止 zip-slip：禁止 .. 或绝对路径。
    """
    s = str(name or "").replace("\\", "/")
    s = s.lstrip("/")
    # 去掉危险段
    parts = [p for p in s.split("/") if p not in ("", ".", "..")]
    return "/".join(parts) if parts else "file"


# -----------------------------
# Routes
# -----------------------------
@router.get("/available")
def available(
    scope: str = Query(default="all", description="all | personal | upload | custom"),
    current_user=Depends(get_current_user),
) -> List[Dict[str, Any]]:
    alias = (current_user.alias or "").strip()
    scope2 = (scope or "all").strip().lower()
    if scope2 not in ("all", "personal", "upload", "custom"):
        scope2 = "all"

    out: List[Dict[str, Any]] = []

    # owner：原逻辑
    if scope2 in ("all", "personal"):
        owners = list_accessible_owners(alias, scope=scope2)
        for o in owners:
            out.append({
                "kind": "owner",
                "key": o.key,
                "label": o.label,
                "dbname": "(merged)",
                "exists": True,
                "missingReason": None,
            })

    # upload：列出用户上传库
    if scope2 in ("all", "upload"):
        for r in _list_upload_dbs(alias):
            out.append({
                "kind": "db",  # ✅ 统一成 db（前端更好处理）
                "key": r.key,
                "label": r.label,
                "dbname": r.dbname,
                "exists": bool(r.exists),
                "missingReason": r.missingReason,
            })

    # custom：只在 scope=custom 时列出 QE+EPW 自定义库（all 不包含 custom）
    if scope2 == "custom":
        for r in list_accessible_qe_epw_dbs(alias, scope="custom"):
            # 只取 qe_custom（避免把 personal qe_epw 混进来）
            if getattr(r, "kind", "") != "qe_custom":
                continue
            out.append({
                "kind": "db",
                "key": r.key,          # custom_qe_epw:{alias}:{file}.sqlite
                "label": r.label,
                "dbname": r.dbname,
                "exists": bool(r.exists),
                "missingReason": r.missingReason,
            })

    return out

def _list_table_columns(con: sqlite3.Connection, table: str) -> List[str]:
    rows = con.execute(f"PRAGMA table_info({table})").fetchall()
    # PRAGMA table_info: cid, name, type, notnull, dflt_value, pk
    return [r[1] for r in rows]

@router.get("/columns")
def columns(
    db: Optional[str] = Query(default=None),
    scope: str = Query(default="all"),
    sample: int = Query(default=2000, ge=50, le=20000),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    scope2 = _scope_norm(scope)
    refs, refs_ok = _resolve_qe_epw_refs_for_request(alias, db, scope2)

    # 没库也返回一个兜底（否则前端列选择会空）
    if not refs_ok:
        return {
            "db": {"requested": db, "scope": scope2},
            "default": DEFAULT_COLS,
            "all": DEFAULT_COLS,
            "sample": int(sample),
        }

    ref0 = refs_ok[0]
    con = _connect_sqlite(str(ref0.dbpath))
    try:
        if not _has_tables(con):
            return {
                "db": {"requested": db, "scope": scope},
                "default": DEFAULT_COLS,
                "all": DEFAULT_COLS,
                "sample": int(sample),
            }

        real_cols = _list_table_columns(con, "runs")

        # all: runs真实列 + 虚拟列
        all_cols = list(real_cols) + list(EPW_PARAMS_COLS) + list(MOBILITY_300K_COLS)

        # default: DEFAULT_COLS(只保留真实存在的) + 虚拟列默认
        default_cols = [c for c in DEFAULT_COLS if c in set(real_cols)]
        default_cols += [c for c in EPW_PARAMS_DEFAULT if c in set(EPW_PARAMS_COLS)]
        default_cols += [c for c in MOBILITY_300K_DEFAULT if c in set(MOBILITY_300K_COLS)]

        # 兜底：避免 default 为空
        if not default_cols:
            default_cols = real_cols[: min(12, len(real_cols))]

        return {
            "db": {"requested": db, "scope": scope},
            "default": default_cols,
            "all": all_cols,
            "sample": int(sample),
        }
    finally:
        con.close()
        
@router.get("/cp_keys")
def cp_keys(
    db: Optional[str] = Query(default=None),
    scope: str = Query(default="all"),
    sample: int = Query(default=2000, ge=50, le=20000),
    max_depth: int = Query(default=4, ge=1, le=10),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    scope2 = _scope_norm(scope)
    refs, refs_ok = _resolve_qe_epw_refs_for_request(alias, db, scope2)

    if not refs_ok:
        return {"db": {"requested": db, "scope": scope2}, "keys": []}

    def _walk_keys(prefix: str, x: Any, depth: int, out: Set[str]):
        if depth > int(max_depth):
            return
        if isinstance(x, dict):
            for k, v in x.items():
                kk = str(k)
                p2 = f"{prefix}.{kk}" if prefix else kk
                out.add(p2)
                _walk_keys(p2, v, depth + 1, out)

    keys_set: Set[str] = set()

    # 1) runs 列
    ref0 = refs_ok[0]
    con0 = _connect_sqlite(str(ref0.dbpath))
    try:
        if _has_tables(con0):
            for c in _list_table_columns(con0, "runs"):
                keys_set.add(str(c))
    finally:
        con0.close()

    # 2) JSON keys：structure/epw_params/meta
    for ref in refs_ok:
        con = _connect_sqlite(str(ref.dbpath))
        try:
            if not _has_tables(con):
                continue
            rows = con.execute(
                "SELECT structure_json, epw_params_json, meta_json FROM runs LIMIT ?",
                (int(sample),),
            ).fetchall()

            for r in rows:
                try:
                    s_obj = json.loads(r["structure_json"]) if r["structure_json"] else None
                except Exception:
                    s_obj = None
                try:
                    e_obj = json.loads(r["epw_params_json"]) if r["epw_params_json"] else None
                except Exception:
                    e_obj = None
                try:
                    m_obj = json.loads(r["meta_json"]) if r["meta_json"] else None
                except Exception:
                    m_obj = None

                if isinstance(s_obj, dict):
                    tmp: Set[str] = set()
                    _walk_keys("", s_obj, 1, tmp)
                    for k in tmp:
                        keys_set.add("structure." + k)

                if isinstance(e_obj, dict):
                    tmp2: Set[str] = set()
                    _walk_keys("", e_obj, 1, tmp2)
                    for k in tmp2:
                        keys_set.add("epw_params." + k)

                if isinstance(m_obj, dict):
                    tmp3: Set[str] = set()
                    _walk_keys("", m_obj, 1, tmp3)
                    for k in tmp3:
                        keys_set.add("meta." + k)

            # 3) mobility keys（从 mobility 表 sample 一些温度）
            if _sqlite_table_exists(con, "mobility"):
                mob = con.execute(
                    "SELECT carrier, temp_K FROM mobility LIMIT ?",
                    (int(sample),),
                ).fetchall()

                temps = set()
                carriers = set()
                for mr in mob:
                    carriers.add(str(mr["carrier"] or "").strip().lower())
                    try:
                        temps.add(int(round(float(mr["temp_K"]))))
                    except Exception:
                        pass

                fields = ["fermi_ev", "density_cm2", "mu_x_cm2Vs", "mu_y_cm2Vs"]
                for f in fields:
                    # 任意 carrier
                    keys_set.add(f"mobility.{f}")
                    for t in sorted(list(temps))[:20]:
                        keys_set.add(f"mobility.{f}@{t}K")
                    # electron/hole
                    for c in ("electron", "hole"):
                        keys_set.add(f"mobility.{c}.{f}")
                        for t in sorted(list(temps))[:20]:
                            keys_set.add(f"mobility.{c}.{f}@{t}K")

        finally:
            con.close()

    return {"db": {"requested": db, "scope": scope2}, "keys": sorted(keys_set)}

@router.get("/tasks")
def tasks(
    db: Optional[str] = Query(default=None, description="owner:xxx 或 qe_epw:owner:dbname"),
    scope: str = Query(default="all"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    columns: Optional[str] = Query(default=None),

    # ✅ 新增：元素筛选
    elems: Optional[str] = Query(default=None, description="逗号分隔元素符号，例如 Si,O"),
    elem_mode: str = Query(default="at_least", description="at_least | only"),
    cp_filters: Optional[str] = Query(default=None, description="JSON list filters, e.g. [{path:'calc_type',op:'eq',value:'scf'}]"),

    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    scope2 = (scope or "all").strip().lower()

    wanted_cols = [c.strip() for c in (columns or "").split(",") if c.strip()] or DEFAULT_COLS
    # ✅ 解析元素筛选
    selected_elems = set(_parse_elems_param(elems))
    mode = (elem_mode or "at_least").strip().lower()
    cp_flts = _parse_cp_filters_qe(cp_filters)
    if mode not in ("at_least", "only"):
        mode = "at_least"

    refs, refs_ok = _resolve_qe_epw_refs_for_request(alias, db, scope2)

    if not refs_ok:
        return {
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "page": page,
            "page_size": page_size,
            "total": 0,
            "columns": wanted_cols,
            "items": [],
            "detail": "no existing qe_epw database files",
        }

    offset = (page - 1) * page_size

    # 1) per-db ids（只算 id，不拉整行）
    per_db_ids: Dict[str, List[int]] = {}
    per_db_ref: Dict[str, Any] = {r.key: r for r in refs_ok}

    for ref in refs_ok:
        try:
            con = _connect_sqlite(str(ref.dbpath))
            try:
                if not _has_tables(con):
                    per_db_ids[ref.key] = []
                    continue

                filtered_ids = _compute_filtered_ids_for_db_qe(
                    con=con,
                    selected_elems=selected_elems,
                    mode=mode,
                    cp_flts=cp_flts,
                )

                if filtered_ids is None:
                    per_db_ids[ref.key] = _get_all_ids_sqlite(con)
                else:
                    per_db_ids[ref.key] = filtered_ids
            finally:
                con.close()
        except Exception:
            per_db_ids[ref.key] = []

    # 2) total（快）
    total = sum(len(v) for v in per_db_ids.values())

    # 3) k-way merge 取当前页（不会构造全量 merged）
    page_pairs = _merge_page_pairs_kway(per_db_ids, offset=offset, limit=page_size)

    # 4) 拉取本页行数据（按 dbKey 分组减少 connect 次数）
    grouped: Dict[str, List[int]] = {}
    for dbKey, rid in page_pairs:
        grouped.setdefault(dbKey, []).append(int(rid))

    items_all: List[Dict[str, Any]] = []

    for dbKey, ids in grouped.items():
        ref = per_db_ref.get(dbKey)
        if ref is None:
            continue

        con = _connect_sqlite(str(ref.dbpath))
        try:
            if not _has_tables(con):
                continue

            # 取 rows（ORDER BY id 保证稳定）
            placeholders = ",".join(["?"] * len(ids))
            rows = con.execute(
                f"SELECT * FROM runs WHERE id IN ({placeholders}) ORDER BY id ASC",
                tuple(ids),
            ).fetchall()

            items = _rows_to_items(rows, dbKey=ref.key, dbname=ref.dbname, wanted_cols=wanted_cols)

            # ---- 填充 epw_params.* 虚拟列（沿用你原逻辑）----
            wanted_set = set(wanted_cols)
            need_epw = any(c in wanted_set for c in EPW_PARAMS_COLS)
            if need_epw and rows:
                for idx2, r in enumerate(rows):
                    epw_obj = None
                    try:
                        epw_obj = json.loads(r["epw_params_json"]) if ("epw_params_json" in r.keys() and r["epw_params_json"]) else None
                    except Exception:
                        epw_obj = None
                    if not isinstance(epw_obj, dict):
                        continue

                    mapping = {
                        "epw_params.ncarrier": "ncarrier",
                        "epw_params.nk": "nk",
                        "epw_params.nkf": "nkf",
                        "epw_params.nq": "nq",
                        "epw_params.nqf": "nqf",
                    }
                    for colname, key in mapping.items():
                        if colname in wanted_set:
                            items[idx2][colname] = epw_obj.get(key)

            # ---- 填充 mobility@300K 虚拟列（沿用你原逻辑）----
            need_mob300 = any(c in wanted_set for c in MOBILITY_300K_COLS)
            if need_mob300 and rows:
                run_ids = [int(r["id"]) for r in rows if "id" in r.keys() and r["id"] is not None]
                if run_ids:
                    ph2 = ",".join(["?"] * len(run_ids))
                    mob_rows = con.execute(
                        f"""
                        SELECT run_id, carrier, temp_K, fermi_ev, density_cm2, mu_x_cm2Vs, mu_y_cm2Vs, raw_json
                        FROM mobility
                        WHERE run_id IN ({ph2})
                        """,
                        tuple(run_ids),
                    ).fetchall()

                    mob_map: Dict[int, Dict[str, Any]] = {}
                    for mr in mob_rows:
                        rid = int(mr["run_id"])
                        carrier = str(mr["carrier"] or "").strip().lower()
                        if carrier not in ("electron", "hole"):
                            continue
                        if not _is_temp_k(mr["temp_K"], 300.0):
                            continue

                        d = mob_map.setdefault(rid, {})
                        d[f"mobility.{carrier}.fermi_ev@300K"] = mr["fermi_ev"]
                        d[f"mobility.{carrier}.density_cm2@300K"] = mr["density_cm2"]
                        d[f"mobility.{carrier}.mu_x_cm2Vs@300K"] = mr["mu_x_cm2Vs"]
                        d[f"mobility.{carrier}.mu_y_cm2Vs@300K"] = mr["mu_y_cm2Vs"]

                        table_key = None
                        try:
                            raw_obj = json.loads(mr["raw_json"]) if mr["raw_json"] else None
                            if isinstance(raw_obj, dict):
                                table_key = raw_obj.get("table_key")
                        except Exception:
                            table_key = None
                        d[f"mobility.{carrier}.table_key@300K"] = table_key

                    rid_to_item = {int(it["_rowId"]): it for it in items}
                    for rid, d in mob_map.items():
                        it = rid_to_item.get(rid)
                        if not it:
                            continue
                        for k, v in d.items():
                            if k in wanted_set:
                                it[k] = v

            items_all.extend(items)

        finally:
            con.close()

    # 5) 恢复 items 顺序（分组取数会打乱顺序）
    idx_map = {(it["_dbKey"], it["_rowId"]): it for it in items_all}
    items_sorted: List[Dict[str, Any]] = []
    for dbKey, rid in page_pairs:
        it = idx_map.get((dbKey, int(rid)))
        if it is not None:
            items_sorted.append(it)

    return {
        "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
        "page": page,
        "page_size": page_size,
        "total": int(total),
        "columns": wanted_cols,
        "items": items_sorted,
    }

@router.get("/elements")
def elements(
    db: Optional[str] = Query(default=None),
    scope: str = Query(default="all"),
    refresh: int = Query(default=0, ge=0, le=1, description="1=trigger background rescan"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    返回该库中出现过的元素集合（用于周期表高亮）
    从 runs.structure_json 里解析 atomic_positions.atoms[].element
    """
    alias = (current_user.alias or "").strip()

    scope2 = _scope_norm(scope)
    refs, refs_ok = _resolve_qe_epw_refs_for_request(alias, db, scope2)

    if not refs_ok:
        return {
            "status": "error",
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "elements": [],
            "detail": "no existing qe_epw database files",
        }

    cache_key = _qe_cache_key_for_refs(refs_ok, scope2, db)

    # refresh=0：优先命中缓存
    if int(refresh) == 0:
        # 1) 内存缓存
        hit = _qe_get_cache(cache_key)
        if hit is not None:
            return {
                "status": "ready",
                "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
                "elements": hit,
                "task_id": None,
                "source": "qe_memory_cache",
            }

        # 2) 文件缓存（重启后也能快）
        hit_file = _qe_read_file_cache(cache_key)
        if hit_file is not None:
            # 回填内存，后续更快
            _qe_set_cache_memory_only(cache_key, hit_file)
            return {
                "status": "ready",
                "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
                "elements": hit_file,
                "task_id": None,
                "source": "qe_file_cache",
            }

        # 没缓存但有人正在扫
        if _qe_is_scanning(cache_key):
            return {
                "status": "scanning",
                "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
                "elements": [],
                "task_id": None,
            }

        # 没缓存也没扫：尝试用分布式锁避免多进程重复扫
        lock_key = _qe_lock_key_for_cache_key(cache_key)
        token = _qe_acquire_dist_lock(lock_key, ttl=1800)

        if token:
            _qe_mark_scanning(cache_key)
            _qe_kickoff_scan(cache_key, refs_ok, lock_token=token)
            return {
                "status": "scanning",
                "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
                "elements": [],
                "task_id": None,
            }

        # 没抢到锁：说明别的进程正在扫（或刚抢到锁准备扫）
        # 稍等一下看看文件缓存是否马上写出来（可选）
        try:
            fp = _qe_elems_cache_file_path(cache_key)
            _qe_wait_for_file(fp, timeout=3.0, interval=0.25)
            hit_file2 = _qe_read_file_cache(cache_key)
            if hit_file2 is not None:
                _qe_set_cache_memory_only(cache_key, hit_file2)
                return {
                    "status": "ready",
                    "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
                    "elements": hit_file2,
                    "task_id": None,
                    "source": "qe_file_cache",
                }
        except Exception:
            pass

        # 返回 scanning，让前端轮询 refresh=0
        return {
            "status": "scanning",
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "elements": [],
            "task_id": None,
        }

    # refresh=1：强制触发后台重算（不阻塞）
    try:
        fp = _qe_elems_cache_file_path(cache_key)
        if os.path.exists(fp):
            os.remove(fp)
    except Exception:
        pass
    
    with _qe_elems_lock:
        _qe_elems_cache.pop(cache_key, None)

    lock_key = _qe_lock_key_for_cache_key(cache_key)
    token = _qe_acquire_dist_lock(lock_key, ttl=1800)

    # 抢到锁：我来扫
    if token:
        _qe_mark_scanning(cache_key)
        _qe_kickoff_scan(cache_key, refs_ok, lock_token=token)
        return {
            "status": "refreshing",
            "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
            "elements": [],
            "task_id": None,
        }

    # 没抢到锁：别人正在扫（或刚开始），我不重复扫
    _qe_mark_scanning(cache_key)
    return {
        "status": "refreshing",
        "db": {"requested": db, "scope": scope2, "refs": _refs_meta(refs)},
        "elements": [],
        "task_id": None,
        "detail": "scan already in progress (redis lock held)",
    }

@router.get("/task/{row_id}/calculator_parameters")
def task_calculator_parameters(
    row_id: int,
    db: Optional[str] = Query(default=None, description="qe_epw db key"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    # ✅ upload db key 直连（否则走原 authz_db）
    up_ref = _parse_upload_db_key(db, alias)
    if up_ref is not None:
        ref = up_ref
    else:
        ref = resolve_qe_epw_db_for_request(alias, db)

    if not getattr(ref, "exists", True):
        raise HTTPException(status_code=404, detail=getattr(ref, "missingReason", None) or "qe_epw db missing")

    con = _connect_sqlite(str(ref.dbpath))
    try:
        if not _has_tables(con):
            raise HTTPException(status_code=400, detail=f"Not a QE/EPW sqlite schema: {ref.dbpath}")

        r = con.execute("SELECT * FROM runs WHERE id=?", (int(row_id),)).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="row not found")

        cp: Dict[str, Any] = {}

        # 你想在弹窗里看的都放这里（先放 runs 的关键字段）
        for k in ("code", "calc_type", "qe_in_path", "epw_in_path", "prefix", "out_path", "workdir"):
            cp[k] = r[k] if k in r.keys() else None
            
        # ✅ 结构名称（runs 表的 structure 列），用于详情页显示：structure: MoS2
        cp["structure_name"] = r["structure"] if "structure" in r.keys() else None

        # JSON 字段解析
        for jk, col in (("structure", "structure_json"), ("epw_params", "epw_params_json"), ("meta", "meta_json")):
            try:
                cp[jk] = json.loads(r[col]) if (col in r.keys() and r[col]) else None
            except Exception:
                cp[jk] = r[col] if col in r.keys() else None

        # 子表：file_refs
        file_refs = con.execute(
            "SELECT * FROM file_refs WHERE run_id=? ORDER BY last_seen_utc DESC",
            (int(row_id),)
        ).fetchall()
        cp["file_refs"] = [dict(x) for x in file_refs]

        # 子表：mobility（详情用：所有温度；只要外层字段；不要 raw/raw_json）
        mob = con.execute(
            """
            SELECT
              id, run_id, carrier, temp_K, fermi_ev, density_cm2, mu_x_cm2Vs, mu_y_cm2Vs
            FROM mobility
            WHERE run_id=?
            ORDER BY carrier, temp_K
            """,
            (int(row_id),)
        ).fetchall()
        cp["mobility"] = [dict(x) for x in mob]

        return {
            "db": {"kind": ref.kind, "key": ref.key, "label": ref.label, "dbname": ref.dbname},
            "id": int(row_id),
            "calculator": r["code"],
            "calculator_parameters": cp,
        }
    finally:
        con.close()
        
@router.get("/task/{row_id}/band-plot")
def task_band_plot(
    row_id: int,
    db: Optional[str] = Query(default=None, description="qe_epw db key"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()

    # ✅ 复用你现有权限解析
    up_ref = _parse_upload_db_key(db, alias)
    if up_ref is not None:
        ref = up_ref
    else:
        ref = resolve_qe_epw_db_for_request(alias, db)

    if not getattr(ref, "exists", True):
        raise HTTPException(status_code=404, detail=getattr(ref, "missingReason", None) or "qe_epw db missing")

    con = _connect_sqlite(str(ref.dbpath))
    try:
        if not _has_tables(con):
            raise HTTPException(status_code=400, detail=f"Not a QE/EPW sqlite schema: {ref.dbpath}")

        r = con.execute("SELECT * FROM runs WHERE id=?", (int(row_id),)).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="row not found")
        def _get_float_col(col: str):
            try:
                if col in r.keys() and r[col] is not None:
                    return float(r[col])
            except Exception:
                return None
            return None

        # runs 表里如果有的话（保留这些字段用于返回给前端展示，但不再用于对齐）
        efermi = _get_float_col("efermi_ev")
        phys_gap = _get_float_col("phys_bandgap_eV")
        phys_vbm = _get_float_col("phys_vbm_eV")
        phys_cbm = _get_float_col("phys_cbm_eV")

        out_path = r["out_path"] if "out_path" in r.keys() else None
        if not out_path:
            raise HTTPException(status_code=400, detail="out_path is empty, cannot plot bands")

        host_path = _container_path_from_out_path(str(out_path))
        if not host_path or not os.path.exists(host_path):
            raise HTTPException(status_code=404, detail=f"out file not found in container: {host_path}")

        # 读取文件
        try:
            with open(host_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to read out file: {e}")

        band = _parse_pwscf_bands_from_stdout(text)
        if band is None:
            raise HTTPException(status_code=400, detail="不是可识别的 QE 能带输出（bs.out），无法绘制")

        kpts = band["kpoints"]
        bands = band["energies"]   # [nbands][nk]
        x = np.array(band["x"], dtype=float)
        
        # ✅ 新：从 bs.out 同目录的 *.save/data-file-schema.xml 读取 Ef/VBM/CBM（Hartree -> eV）
        prefix_hint = None
        try:
            prefix_hint = (r["prefix"] if ("prefix" in r.keys()) else None)
        except Exception:
            prefix_hint = None

        xml_path = _find_qe_save_xml_near_bsout(host_path, prefix_hint=prefix_hint)
        if not xml_path or not os.path.exists(xml_path):
            raise HTTPException(
                status_code=404,
                detail="未找到 data-file-schema.xml（支持 *.save/data-file-schema.xml 或当前目录 data-file-schema.xml），无法读取 Ef/VBM/CBM"
            )

        # --- 读取 Ef/VBM/CBM：XML 优先；缺失则 fallback ---
        levels = {"fermi_ev": None, "vbm_ev": None, "cbm_ev": None}
        xml_err = None
        try:
            levels = _parse_qe_levels_from_data_file_schema(xml_path)
        except Exception as e:
            xml_err = str(e)

        fermi_ev_xml = levels.get("fermi_ev")
        vbm_ev_xml = levels.get("vbm_ev")
        cbm_ev_xml = levels.get("cbm_ev")

        # ✅ Ef 必须要有：没有就 fallback 到 bs.out 里抓到的 fermi（再不行就 0）
        if fermi_ev_xml is None:
            fermi_ev_xml = float(band.get("fermi")) if band.get("fermi") is not None else 0.0

        # --- 补齐 VBM/CBM 的 fallback 逻辑 ---
        vbm_source = "qe_save_data-file-schema.xml:highestOccupiedLevel"
        cbm_source = "qe_save_data-file-schema.xml:lowestUnoccupiedLevel"

        # 1) 若 CBM 缺失但 VBM 有：沿用你已有逻辑（从 VBM 往上找）
        if cbm_ev_xml is None and vbm_ev_xml is not None:
            cbm_ev_xml = _infer_cbm_from_bands_given_vbm(bands, float(vbm_ev_xml), eps=1e-6)
            cbm_source = "estimated_from_bs.out:min(E>VBM)"

        # 2) ✅ 新增：若 VBM/CBM 都缺（常见于 smearing 金属/准金属），用 Ef 两侧最近值估算
        if vbm_ev_xml is None and cbm_ev_xml is None:
            near = _infer_vbm_cbm_from_bands_near_fermi(bands, float(fermi_ev_xml), eps=1e-6)
            vbm_ev_xml = near.get("vbm_ev")
            cbm_ev_xml = near.get("cbm_ev")
            vbm_source = "estimated_from_bs.out:max(E<=Ef)"
            cbm_source = "estimated_from_bs.out:min(E>=Ef)"

        # 3) bandgap（如果 cbm/vbm 都有）
        bandgap_xml_eV = (float(cbm_ev_xml) - float(vbm_ev_xml)) if (cbm_ev_xml is not None and vbm_ev_xml is not None) else None
        
        # ---- 同目录寻找 *.in（优先同名 bs.in），解析 K_POINTS {crystal_b} ----
        in_path = None
        kpath = None
        lattice_type = "unknown"

        try:
            d = os.path.dirname(host_path)
            stem = os.path.splitext(os.path.basename(host_path))[0]   # 例如 bs
            cand = os.path.join(d, stem + ".in")                      # bs.in

            if os.path.exists(cand) and os.path.isfile(cand):
                in_path = cand
            else:
                # ✅ 不再“随便挑一个 .in”，只挑包含 crystal_b 的输入
                for fn in sorted(os.listdir(d)):
                    if not fn.lower().endswith(".in"):
                        continue
                    p = os.path.join(d, fn)
                    try:
                        with open(p, "r", encoding="utf-8", errors="ignore") as f:
                            t = f.read().lower()
                        if ("k_points" in t) and ("crystal_b" in t):
                            in_path = p
                            break
                    except Exception:
                        continue

            sp_points = None  # ✅ 新增：seekpath 高对称点坐标字典

            if in_path:
                with open(in_path, "r", encoding="utf-8", errors="ignore") as f:
                    in_text = f.read()
                kpath = _parse_qe_kpath_from_in(in_text)
                lattice_type = _infer_lattice_type_from_qe_in(in_text)

                # ✅ 新增：从 bs.in 解析结构 -> seekpath 点表
                struct = _parse_qe_structure_from_in(in_text)
                if struct:
                    sp_points = _seekpath_point_dict_from_structure(struct)

        except Exception:
            in_path = None
            kpath = None
            lattice_type = "unknown"

        # 画图
        fig = plt.figure(figsize=(6.2, 4.6), dpi=160)
        ax = fig.add_subplot(111)

        # ✅ 新：以 Ef 为基准平移，使 Ef 位于 y=0：E_plot = E - Ef
        bands_plot = _shift_bands_by_reference(bands, fermi_ev_xml)
            
        for y in bands_plot:
            ax.plot(x, y, color="black", linewidth=0.8)

        # ---- 根据 bs.in 的 crystal_b 路径加高对称点刻度（按你定义的规则）----
        if kpath:
            pts = kpath.get("points") or []
            seg_n = [int(n) for n in (kpath.get("seg_n") or [])]

            nk = len(x)

            # 你定义的规则：boundary indices = [0, n1, n1+n2, ...]
            boundaries = [0]
            s = 0
            for n in seg_n:
                s += int(n)
                boundaries.append(s)  # 最后一个应为 sum(seg_n)

            # ✅ 主规则：bs.out 点数 = sum(seg_n) + 1  (比如 20,20,20 -> 61)
            ok_main = (nk == (sum(seg_n) + 1)) and (len(boundaries) == len(pts))

            # ✅ 兼容：有些输出会把段间公共端点重复写入 => nk = sum(seg_n) + (段数) + 1
            # 这种情况下 boundary 需要加上“已经重复了多少个端点”
            ok_dup = False
            boundaries2 = None
            if (not ok_main) and seg_n and pts:
                # 段数 = len(seg_n) = len(pts)-1
                nseg = len(seg_n)
                # 若每段都重复了端点，则总点数常见为 sum(seg_n) + nseg + 1
                if nk == (sum(seg_n) + nseg + 1) and (len(pts) == nseg + 1):
                    boundaries2 = [0]
                    s2 = 0
                    for i, n in enumerate(seg_n, start=1):
                        s2 += int(n)
                        boundaries2.append(s2 + (i - 1))  # 每走完一段，多了 (i-1) 个重复端点
                    ok_dup = True

            use_boundaries = boundaries if ok_main else (boundaries2 if ok_dup else None)

            if use_boundaries:
                xticks = []
                xlabels = []
                for bi, kp in zip(use_boundaries, pts):
                    bi = int(bi)
                    if 0 <= bi < nk:
                        xticks.append(float(x[bi]))
                        # ✅ 优先 seekpath 自动标签（覆盖面最大），不行再用你原来的粗规则猜
                        lab = _label_kpt_by_seekpath(kp, sp_points or {}, tol=1.2e-2) if 'sp_points' in locals() else ""
                        if not lab:
                            lab = _label_for_kpt_crystal(kp, lattice_type=lattice_type)
                        xlabels.append(lab if lab else "")
                        ax.axvline(float(x[bi]), color="black", linewidth=0.6, alpha=0.35)

                if xticks:
                    ax.set_xticks(xticks)
                    ax.set_xticklabels(xlabels)
                    ax.set_xlabel("k-path (high symmetry)")
                else:
                    ax.set_xlabel("k-path")
            else:
                # 兜底：不匹配就不画（避免标错）
                ax.set_xlabel("k-path")
        else:
            ax.set_xlabel("k-path")

        ax.set_ylabel("Energy (E - Ef) / eV")
        ax.set_title("Band Structure")
        ax.set_ylim(-3.0, 3.0)

        ax.grid(True, alpha=0.25)
        ax.axhline(0.0, color="red", linewidth=0.8, alpha=0.6)

        buf = io.BytesIO()
        fig.tight_layout()
        fig.savefig(buf, format="png")
        plt.close(fig)

        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return {
            "ok": True,
            "row_id": int(row_id),
            "out_path": str(out_path),
            "container_path": host_path,
            "in_path_used": in_path,
            "kpath_parsed": bool(kpath),
            "lattice_type": lattice_type,

            # ✅ 对齐信息（前端展示）
            "efermi_ev": efermi,
            "phys_bandgap_eV": phys_gap,
            "phys_vbm_eV": phys_vbm,
            "phys_cbm_eV": phys_cbm,

            # ✅ 本次绘图真正使用的（来自 XML）
            "xml_path_used": xml_path,
            "fermi_ev_used": fermi_ev_xml,
            "vbm_ev_xml": vbm_ev_xml,
            "cbm_ev_xml": cbm_ev_xml,
            "bandgap_xml_eV": bandgap_xml_eV,
            "xml_parse_error": xml_err,
            "cbm_source": cbm_source,
            "vbm_source": vbm_source,

            # ✅ 参考能量：Ef（用来让 Ef 位于 y=0）
            "eref_ev": fermi_ev_xml,
            "eref_source": "qe_save_data-file-schema.xml:fermi_energy",

            "image_base64": b64,
        }

    finally:
        con.close()


@router.get("/export")
def export_sqlite_file(
    db: Optional[str] = Query(default=None),
    scope: str = Query(default="all"),

    columns: Optional[str] = Query(default=None),
    elems: Optional[str] = Query(default=None),
    elem_mode: str = Query(default="at_least"),
    cp_filters: Optional[str] = Query(default=None),

    current_user=Depends(get_current_user),
):
    """
    导出“当前列表所呈现的全量内容”（跨库合并 + 筛选后的所有 runs），并同时导出结构文件：
    - 返回一个总 zip：
        - qe_epw.sqlite
        - <runs.id>-structure-CONTCAR   （注意：不放文件夹，直接单文件）
        - README.txt
    - sqlite 会重映射 runs.id（避免多库 id 冲突）
    - mobility/file_refs 会同步重映射 run_id，且重映射子表 id 避免冲突
    """
    alias = (current_user.alias or "").strip()
    scope2 = _scope_norm(scope)

    refs, refs_ok = _resolve_qe_epw_refs_for_request(alias, db, scope2)
    if not refs_ok:
        raise HTTPException(status_code=404, detail="no existing qe_epw database files")

    selected_elems = set(_parse_elems_param(elems))
    mode = (elem_mode or "at_least").strip().lower()
    cp_flts = _parse_cp_filters_qe(cp_filters)
    if mode not in ("at_least", "only"):
        mode = "at_least"

    wanted_cols = [c.strip() for c in (columns or "").split(",") if c.strip()] or DEFAULT_COLS

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    safe_name = "qe_epw_export"
    try:
        if isinstance(db, str) and db:
            safe_name = db.replace(":", "_")
    except Exception:
        pass

    zip_filename = f"{safe_name}_{scope2}_{ts}.zip"

    export_dir = Path(tempfile.mkdtemp(prefix=f"qe_epw_export_{ts}_")).resolve()
    sqlite_path = str((export_dir / "qe_epw.sqlite").resolve())
    zip_path = str((export_dir / zip_filename).resolve())

    # 结构文件先写到磁盘：export_dir/structures_files/
    structures_dir = (export_dir / "structures_files").resolve()
    os.makedirs(structures_dir, exist_ok=True)

    def _cleanup_dir():
        try:
            shutil.rmtree(str(export_dir), ignore_errors=True)
        except Exception:
            pass

    schema_ref = refs_ok[0]
    src0 = _connect_sqlite(str(schema_ref.dbpath))
    dst = _connect_sqlite(sqlite_path)

    wrote_runs = 0
    wrote_structs = 0
    skipped_structs = 0

    try:
        if not _has_tables(src0):
            raise HTTPException(status_code=400, detail=f"Not a QE/EPW sqlite schema: {schema_ref.dbpath}")

        with dst:
            _create_table_like(src0, dst, "runs")

            if _sqlite_table_exists(src0, "mobility"):
                _create_table_like(src0, dst, "mobility")
            if _sqlite_table_exists(src0, "file_refs"):
                _create_table_like(src0, dst, "file_refs")

            runs_cols = {r[1] for r in dst.execute("PRAGMA table_info(runs)").fetchall()}
            if "_src_db_key" not in runs_cols:
                dst.execute('ALTER TABLE runs ADD COLUMN "_src_db_key" TEXT')
            if "_src_dbname" not in runs_cols:
                dst.execute('ALTER TABLE runs ADD COLUMN "_src_dbname" TEXT')
            if "_src_run_id" not in runs_cols:
                dst.execute('ALTER TABLE runs ADD COLUMN "_src_run_id" INTEGER')

            dst.execute('CREATE TABLE IF NOT EXISTS "_export_meta" (k TEXT PRIMARY KEY, v TEXT)')
            meta_obj = {
                "db_requested": db,
                "scope": scope2,
                "elems": sorted(list(selected_elems)),
                "elem_mode": mode,
                "columns": wanted_cols,
                "created_at": time.time(),
            }
            dst.execute("DELETE FROM _export_meta")
            dst.execute(
                "INSERT OR REPLACE INTO _export_meta(k,v) VALUES(?,?)",
                ("meta", json.dumps(meta_obj, ensure_ascii=False)),
            )

            next_new_id = 1
            id_map: Dict[tuple[str, int], int] = {}

            next_mob_id = 1
            next_fr_id = 1

            dst_runs_cols = [r[1] for r in dst.execute("PRAGMA table_info(runs)").fetchall()]
            insert_runs_sql = (
                'INSERT INTO runs (' + ",".join([f'"{c}"' for c in dst_runs_cols]) + ") "
                "VALUES (" + ",".join(["?"] * len(dst_runs_cols)) + ")"
            )

            # --- 逐库导出 ---
            for ref in refs_ok:
                src = _connect_sqlite(str(ref.dbpath))
                try:
                    if not _has_tables(src):
                        continue

                    ids = _compute_filtered_ids_for_db_qe(
                        src,
                        selected_elems=selected_elems,
                        mode=mode,
                        cp_flts=cp_flts,
                    )
                    if ids is None:
                        ids = _get_all_ids_sqlite(src)
                    if not ids:
                        continue

                    ph = ",".join(["?"] * len(ids))
                    rows = src.execute(
                        f"SELECT * FROM runs WHERE id IN ({ph}) ORDER BY id ASC",
                        tuple(ids),
                    ).fetchall()

                    # --- runs + structure files ---
                    for r in rows:
                        old_id = int(r["id"])
                        new_id = next_new_id
                        next_new_id += 1
                        id_map[(ref.key, old_id)] = new_id

                        row_dict = dict(r)
                        row_dict["id"] = new_id
                        row_dict["_src_db_key"] = ref.key
                        row_dict["_src_dbname"] = ref.dbname
                        row_dict["_src_run_id"] = old_id

                        vals = [row_dict.get(c) for c in dst_runs_cols]
                        dst.execute(insert_runs_sql, vals)
                        wrote_runs += 1

                        # ✅ 结构文件：不放文件夹，文件名用 runs.structure（例如 Pt1O2）
                        try:
                            contcar = _build_contcar_for_run_row(r)
                            if contcar:
                                # 从 runs.structure 取名字
                                struct_name = ""
                                try:
                                    if "structure" in r.keys() and r["structure"] is not None:
                                        struct_name = str(r["structure"]).strip()
                                except Exception:
                                    struct_name = ""

                                # 清洗文件名（避免空格/斜杠等导致下载解压异常）
                                if not struct_name:
                                    struct_name = "structure"
                                struct_name = re.sub(r"[^\w\u4e00-\u9fff\-\.]+", "_", struct_name).strip("_")
                                if not struct_name:
                                    struct_name = "structure"

                                fn = f"{new_id}-{struct_name}-CONTCAR"
                                fn = _safe_zip_member_name(fn)

                                out_fp = (structures_dir / fn).resolve()
                                with open(out_fp, "w", encoding="utf-8") as f:
                                    f.write(contcar)
                                wrote_structs += 1
                            else:
                                skipped_structs += 1
                        except Exception:
                            skipped_structs += 1

                    # --- mobility ---
                    if _sqlite_table_exists(src0, "mobility") and _sqlite_table_exists(src, "mobility") and ids:
                        ph2 = ",".join(["?"] * len(ids))
                        mob_rows = src.execute(
                            f"SELECT * FROM mobility WHERE run_id IN ({ph2})",
                            tuple(ids),
                        ).fetchall()
                        if mob_rows:
                            dst_mob_cols = [c[1] for c in dst.execute("PRAGMA table_info(mobility)").fetchall()]
                            ins_mob = (
                                'INSERT INTO mobility (' + ",".join([f'"{c}"' for c in dst_mob_cols]) + ") "
                                "VALUES (" + ",".join(["?"] * len(dst_mob_cols)) + ")"
                            )
                            for mr in mob_rows:
                                d = dict(mr)
                                old_run_id = int(d.get("run_id") or 0)
                                new_run_id = id_map.get((ref.key, old_run_id))
                                if not new_run_id:
                                    continue
                                d["run_id"] = new_run_id
                                if "id" in dst_mob_cols:
                                    d["id"] = next_mob_id
                                    next_mob_id += 1
                                vals = [d.get(c) for c in dst_mob_cols]
                                dst.execute(ins_mob, vals)

                    # --- file_refs ---
                    if _sqlite_table_exists(src0, "file_refs") and _sqlite_table_exists(src, "file_refs") and ids:
                        ph3 = ",".join(["?"] * len(ids))
                        fr_rows = src.execute(
                            f"SELECT * FROM file_refs WHERE run_id IN ({ph3})",
                            tuple(ids),
                        ).fetchall()
                        if fr_rows:
                            dst_fr_cols = [c[1] for c in dst.execute("PRAGMA table_info(file_refs)").fetchall()]
                            ins_fr = (
                                'INSERT INTO file_refs (' + ",".join([f'"{c}"' for c in dst_fr_cols]) + ") "
                                "VALUES (" + ",".join(["?"] * len(dst_fr_cols)) + ")"
                            )
                            for fr in fr_rows:
                                d = dict(fr)
                                old_run_id = int(d.get("run_id") or 0)
                                new_run_id = id_map.get((ref.key, old_run_id))
                                if not new_run_id:
                                    continue
                                d["run_id"] = new_run_id
                                if "id" in dst_fr_cols:
                                    d["id"] = next_fr_id
                                    next_fr_id += 1
                                vals = [d.get(c) for c in dst_fr_cols]
                                dst.execute(ins_fr, vals)

                finally:
                    src.close()

            if wrote_runs == 0:
                raise HTTPException(status_code=404, detail="export empty: no rows matched current list filters")

        # ✅ 打包 zip：qe_epw.sqlite + 所有 <id>-structure-CONTCAR + README.txt
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(sqlite_path, arcname="qe_epw.sqlite")

            # 结构文件：直接放 zip 根目录
            for fp in sorted(structures_dir.glob("*")):
                if fp.is_file():
                    zf.write(str(fp), arcname=fp.name)

            readme = (
                f"QE/EPW export bundle\n"
                f"- created_at: {ts}\n"
                f"- scope: {scope2}\n"
                f"- db_requested: {db}\n"
                f"- runs_exported: {wrote_runs}\n"
                f"- structures_written: {wrote_structs}\n"
                f"- structures_skipped: {skipped_structs}\n"
                f"\n"
                f"Structure files are named as: <runs.id>-structure-CONTCAR\n"
            )
            zf.writestr("README.txt", readme)

    except HTTPException:
        try:
            src0.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass
        _cleanup_dir()
        raise
    except Exception as e:
        try:
            src0.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass
        _cleanup_dir()
        raise HTTPException(status_code=500, detail=f"export failed: {e}")
    finally:
        try:
            src0.close()
        except Exception:
            pass
        try:
            dst.close()
        except Exception:
            pass

    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=zip_filename,
        background=BackgroundTask(_cleanup_dir),
    )

@router.post("/upload_qe_epw_files")
async def upload_qe_epw_files(
    files: List[UploadFile] = File(...),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    QE+EPW 多文件上传：
    - 所有文件永久保存到：{QE_EPW_UPLOADS_ROOT}/{alias}/runs/{run_id}/
    - 如果文件中包含一个可用的 sqlite（.sqlite/.db，且包含 runs 表），会复制到：
        {QE_EPW_UPLOADS_ROOT}/{alias}/dbs/{safe_name}.sqlite
      并返回 upload_db_key 供前端直接切到该库。
    """
    alias = (current_user.alias or "").strip()
    if not alias:
        raise HTTPException(status_code=403, detail="invalid user alias")

    if not files:
        raise HTTPException(status_code=400, detail="未收到文件")

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:12]
    run_dir = (_upload_runs_root(alias) / run_id).resolve()
    os.makedirs(run_dir, exist_ok=True)
    os.makedirs(_upload_dbs_root(alias), exist_ok=True)

    total = 0
    saved: List[Dict[str, Any]] = []

    try:
        # 1) 保存所有上传文件
        for uf in files:
            fn0 = uf.filename or ""
            fn = _safe_name(fn0)
            if not fn:
                continue

            dst = (run_dir / fn).resolve()
            if QE_EPW_UPLOADS_ROOT not in dst.parents:
                raise HTTPException(status_code=400, detail=f"invalid filename: {fn0}")

            size = 0
            with open(dst, "wb") as f:
                while True:
                    chunk = await uf.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    total += len(chunk)
                    if total > QE_EPW_MAX_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail=f"文件总大小超过限制 {QE_EPW_MAX_UPLOAD_BYTES} bytes")
                    f.write(chunk)

            saved.append({"name": fn, "bytes": int(size)})

        if not saved:
            raise HTTPException(status_code=400, detail="没有任何有效文件被保存")

        # 2) 尝试用解析脚本生成 sqlite（推荐流程：用户上传 .out/.in 等原始文件）
        upload_db_key = None
        registered_db = None
        import_stdout_tail = ""
        import_stderr_tail = ""

        out_db = (_upload_dbs_root(alias) / f"qe_epw_{run_id}.sqlite").resolve()
        if QE_EPW_UPLOADS_ROOT not in out_db.parents:
            raise HTTPException(status_code=400, detail="invalid db output path")

        # 如果 run_dir 里有任何 .out，就认为可以尝试导入
        has_out = any((run_dir / it["name"]).suffix.lower() == ".out" for it in saved)

        if has_out:
            cmd = [
                "python3",
                QE_EPW_IMPORT_SCRIPT,
                "--db", str(out_db),
                str(run_dir),
            ]

            try:
                p = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=QE_EPW_IMPORT_TIMEOUT,
                    env=os.environ.copy(),
                )
                import_stdout_tail = (p.stdout or "")[-3000:]
                import_stderr_tail = (p.stderr or "")[-3000:]

                if p.returncode != 0:
                    # 解析失败：先不直接失败，继续走“用户自带 sqlite” fallback
                    pass
            except subprocess.TimeoutExpired:
                # 超时也不直接失败，fallback
                import_stderr_tail = "QE/EPW import timeout"
            except Exception as e:
                import_stderr_tail = f"QE/EPW import failed: {e}"

        # 3) 验证 out_db 是否生成成功并符合 schema
        if out_db.exists() and out_db.is_file():
            ok_schema = False
            try:
                con = _connect_sqlite(str(out_db))
                try:
                    ok_schema = _has_tables(con)
                finally:
                    con.close()
            except Exception:
                ok_schema = False

            if ok_schema:
                registered_db = str(out_db)
                upload_db_key = f"{UPLOAD_DB_PREFIX}{alias}:{out_db.name}"
            else:
                # 如果生成了但 schema 不对，避免污染 dbs：删掉
                try:
                    out_db.unlink()
                except Exception:
                    pass

        # 4) fallback：如果用户自己上传了 sqlite/db（runs 表存在），就注册它
        if upload_db_key is None:
            cand_db: Optional[Path] = None
            for it in saved:
                name = str(it["name"])
                p2 = (run_dir / name)
                if p2.suffix.lower() in (".sqlite", ".db") and p2.exists() and p2.is_file():
                    cand_db = p2
                    break

            if cand_db is not None:
                ok_schema2 = False
                try:
                    con = _connect_sqlite(str(cand_db))
                    try:
                        ok_schema2 = _has_tables(con)
                    finally:
                        con.close()
                except Exception:
                    ok_schema2 = False

                if ok_schema2:
                    safe_db_name = f"{cand_db.stem}_{run_id}{cand_db.suffix}"
                    dst_db = (_upload_dbs_root(alias) / safe_db_name).resolve()
                    if QE_EPW_UPLOADS_ROOT not in dst_db.parents:
                        raise HTTPException(status_code=400, detail="invalid db output path")

                    with open(cand_db, "rb") as fsrc, open(dst_db, "wb") as fdst:
                        while True:
                            buf = fsrc.read(1024 * 1024)
                            if not buf:
                                break
                            fdst.write(buf)

                    registered_db = str(dst_db)
                    upload_db_key = f"{UPLOAD_DB_PREFIX}{alias}:{dst_db.name}"

        # 3) 写 meta 便于追溯
        try:
            meta = {
                "alias": alias,
                "run_id": run_id,
                "saved": saved,
                "total_bytes": int(total),
                "created_at": time.time(),
                "registered_db": registered_db,
                "upload_db_key": upload_db_key,
                "has_out": bool(has_out),
                "import_script": QE_EPW_IMPORT_SCRIPT,
                "import_stdout_tail": import_stdout_tail,
                "import_stderr_tail": import_stderr_tail,
            }
            with open(run_dir / "meta.json", "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

        return {
            "ok": True,
            "aliasEN": alias,
            "run_id": run_id,
            "saved_dir": str(run_dir),
            "saved": saved,
            "total_bytes": int(total),
            "upload_db_key": upload_db_key,      # 如果识别出可用 sqlite，会有值
            "registered_db": registered_db,      # 复制到 dbs 的路径
            "message": "上传完成（文件已永久保存）" + ("；已生成并注册 sqlite" if upload_db_key else "；未能生成/识别可用 sqlite（仅保存文件）"),
        }

    except HTTPException:
        # 出错时保留 run_dir 方便排查（和你 vasp 一致）
        raise
    
@router.get("/custom/list")
def list_custom_qe_epw_dbs(current_user=Depends(get_current_user)):
    alias = (current_user.alias or "").strip()

    refs = list_accessible_qe_epw_dbs(alias, scope="custom")
    refs = [r for r in refs if getattr(r, "kind", "") == "qe_custom"]

    items = []
    for r in refs:
        if not bool(getattr(r, "exists", True)):
            continue
        if not getattr(r, "dbpath", None):
            continue
        if not Path(str(getattr(r, "dbpath"))).is_file():
            continue
        # r.dbname 是 "xxx.sqlite"
        stem = Path(r.dbname).stem
        items.append({
            "name": stem,                 # 前端用这个作为 target
            "path": str(r.dbpath),
            "key": r.key,                 # custom_qe_epw:{alias}:{xxx.sqlite}
            "exists": bool(getattr(r, "exists", True)),
        })

    return {"alias": alias, "items": items}


@router.post("/custom/create")
def create_custom_qe_epw_db(req: CreateCustomQeReq, current_user=Depends(get_current_user)):
    alias = (current_user.alias or "").strip()
    safe = _safe_db_name(req.name)

    # 目标库路径（落盘）
    dbp = _qe_custom_db_path(alias, safe)
    os.makedirs(dbp.parent, exist_ok=True)

    if dbp.exists():
        if dbp.is_file():
            raise HTTPException(status_code=409, detail="该自定义数据库已存在")
        raise HTTPException(status_code=400, detail="目标 QE+EPW 自定义数据库路径不是有效文件")

    # ✅ 创建空 QE+EPW schema
    con = sqlite3.connect(str(dbp))
    try:
        con.executescript(SCHEMA_SQL)
        con.commit()
    finally:
        con.close()

    return {"ok": True, "key": f"custom_qe_epw:{alias}:{dbp.name}", "name": safe, "path": str(dbp)}

# --- QE+EPW: delete custom db ---

@router.delete("/custom/delete")
def delete_custom_qe_epw_db(
    key: str = Query(..., description="custom db key: custom_qe_epw:{alias}:{file}.sqlite"),
    delete_file: int = Query(1, ge=0, le=1, description="1=delete actual sqlite file"),
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    if not alias:
        raise HTTPException(status_code=403, detail="invalid user alias")

    s = (key or "").strip()
    if not s.startswith("custom_qe_epw:"):
        raise HTTPException(status_code=400, detail="invalid key (not custom_qe_epw)")

    parts = s.split(":", 2)  # custom_qe_epw, owner_alias, filename
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="invalid key format")

    _tag, owner_alias, fname = parts[0], parts[1].strip(), parts[2].strip()
    if not owner_alias or not fname:
        raise HTTPException(status_code=400, detail="invalid key")

    # ✅ 核心权限：只能删自己的；root 也不允许删别人的
    if owner_alias != alias:
        raise HTTPException(status_code=403, detail="只能删除自己的自定义库")

    # 只允许删 .sqlite
    if not fname.endswith(".sqlite"):
        raise HTTPException(status_code=400, detail="invalid custom db filename")

    # 用你现有安全路径逻辑定位真实路径（防路径穿越）
    safe_stem = Path(fname).stem
    dbp = _qe_custom_db_path(alias, safe_stem)

    if int(delete_file) == 1:
        if dbp.exists():
            if not dbp.is_file():
                raise HTTPException(status_code=400, detail="目标 QE+EPW 自定义数据库不是有效文件")
            try:
                dbp.unlink()
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"delete file failed: {e}")
        else:
            # 文件不存在：按“已删除”处理即可（幂等）
            return {"ok": True, "status": "missing", "message": "文件不存在（已视为删除完成）", "key": key}

    return {"ok": True, "status": "deleted", "message": "删除成功", "key": key}

@router.post("/custom/add")
def add_run_to_custom_qe(req: AddToCustomQeReq, current_user=Depends(get_current_user)) -> Dict[str, Any]:
    alias = (current_user.alias or "").strip()
    target_safe = _safe_db_name(req.target)

    # 目标库路径
    dst_path = _qe_custom_db_path(alias, target_safe)
    if not dst_path.exists():
        raise HTTPException(status_code=404, detail="目标 QE+EPW 自定义数据库不存在")
    if not dst_path.is_file():
        raise HTTPException(status_code=400, detail="目标 QE+EPW 自定义数据库不是有效文件")

    # 源库 ref（允许：upload / owner / custom_qe_epw）
    src_ref = _parse_upload_db_key(req.src_db, alias)
    if src_ref is None:
        # authz_db 负责 personal qe_epw + custom_qe_epw
        src_ref = resolve_qe_epw_db_for_request(alias, req.src_db)

    if not getattr(src_ref, "exists", True):
        raise HTTPException(status_code=404, detail="源数据库不存在")

    src_con = _connect_sqlite(str(src_ref.dbpath))
    dst_con = _connect_sqlite(str(dst_path))

    try:
        if not _has_tables(src_con):
            raise HTTPException(status_code=400, detail=f"source is not a qe_epw sqlite: {src_ref.dbpath}")
        if not _has_tables(dst_con):
            raise HTTPException(status_code=400, detail=f"target is not a qe_epw sqlite: {dst_path}")

        src_con.row_factory = sqlite3.Row
        dst_con.row_factory = sqlite3.Row

        r = src_con.execute("SELECT * FROM runs WHERE id=?", (int(req.row_id),)).fetchone()
        if r is None:
            raise HTTPException(status_code=404, detail="源 run 不存在")

        run_dict = dict(r)

        # ✅ 统一幂等去重键：content_hash（没有就补一个稳定 hash）
        content_hash = (run_dict.get("content_hash") or "").strip() if isinstance(run_dict.get("content_hash"), str) else run_dict.get("content_hash")
        if not content_hash:
            content_hash = _stable_content_hash_for_run_dict(run_dict)
            run_dict["content_hash"] = content_hash

        # 先查目标库：已存在直接返回（幂等）
        hit = dst_con.execute("SELECT id FROM runs WHERE content_hash=? LIMIT 1", (content_hash,)).fetchone()
        if hit:
            return {
                "ok": True,
                "target": target_safe,
                "status": "exists",
                "run_id": int(hit["id"]),
                "message": "该结构已在目标自定义库中（无需重复收藏）",
            }

        # 1) 插入 runs（去掉 id，让目标库自增）
        run_dict.pop("id", None)

        cols = list(run_dict.keys())
        sql = "INSERT INTO runs (" + ",".join(cols) + ") VALUES (" + ",".join(["?"] * len(cols)) + ")"

        try:
            with dst_con:
                cur = dst_con.execute(sql, [run_dict[c] for c in cols])
                new_run_id = int(cur.lastrowid)

                # 2) 复制 mobility（id 自增；run_id 改成 new_run_id）
                mob_rows = src_con.execute("SELECT * FROM mobility WHERE run_id=?", (int(req.row_id),)).fetchall()
                for mr in mob_rows:
                    d = dict(mr)
                    d.pop("id", None)
                    d["run_id"] = new_run_id
                    mcols = list(d.keys())
                    msql = "INSERT INTO mobility (" + ",".join(mcols) + ") VALUES (" + ",".join(["?"] * len(mcols)) + ")"
                    dst_con.execute(msql, [d[c] for c in mcols])

                # 3) 复制 file_refs（id 自增；run_id 改成 new_run_id）
                fr_rows = src_con.execute("SELECT * FROM file_refs WHERE run_id=?", (int(req.row_id),)).fetchall()
                for fr in fr_rows:
                    d = dict(fr)
                    d.pop("id", None)
                    d["run_id"] = new_run_id
                    fcols = list(d.keys())
                    fsql = "INSERT INTO file_refs (" + ",".join(fcols) + ") VALUES (" + ",".join(["?"] * len(fcols)) + ")"
                    dst_con.execute(fsql, [d[c] for c in fcols])

            return {
                "ok": True,
                "target": target_safe,
                "status": "inserted",
                "run_id": new_run_id,
                "message": "收藏成功",
            }

        except sqlite3.IntegrityError:
            # ✅ 并发/重复写入兜底：再查一次，当作已存在
            hit2 = dst_con.execute("SELECT id FROM runs WHERE content_hash=? LIMIT 1", (content_hash,)).fetchone()
            if hit2:
                return {
                    "ok": True,
                    "target": target_safe,
                    "status": "exists",
                    "run_id": int(hit2["id"]),
                    "message": "该结构已在目标自定义库中（无需重复收藏）",
                }
            raise HTTPException(status_code=409, detail="该结构已在目标自定义库中（无需重复收藏）")
        
    finally:
        try: src_con.close()
        except Exception: pass
        try: dst_con.close()
        except Exception: pass
        
def add_all_rows_to_custom_qe_sync_core(payload: Dict[str, Any], progress_cb=None) -> Dict[str, Any]:
    alias = str(payload.get("alias") or "").strip()
    target = str(payload.get("target") or "").strip()
    if not alias or not target:
        raise HTTPException(status_code=400, detail="invalid payload")

    target_safe = _safe_db_name(target)
    dst_path = _qe_custom_db_path(alias, target_safe)
    if not dst_path.exists():
        raise HTTPException(status_code=404, detail="目标 QE+EPW 自定义数据库不存在")
    if not dst_path.is_file():
        raise ValueError("目标 QE+EPW 自定义数据库不是有效文件")

    scope = _scope_norm(str(payload.get("scope") or "all"))
    db = payload.get("db")
    elems = payload.get("elems")
    elem_mode = str(payload.get("elem_mode") or "at_least").strip().lower()
    if elem_mode not in ("at_least", "only"):
        elem_mode = "at_least"

    # ✅ 新增：输入参数筛选（cp_filters）
    cp_filters = payload.get("cp_filters")
    cp_flts = _parse_cp_filters_qe(cp_filters)

    max_rows = int(payload.get("max_rows") or 0)
    if max_rows <= 0:
        max_rows = QE_EPW_CUSTOM_ADD_ALL_MAX_ROWS_DEFAULT
    if max_rows > QE_EPW_CUSTOM_ADD_ALL_MAX_ROWS_HARD_LIMIT:
        raise HTTPException(
            status_code=400,
            detail=f"max_rows 过大（>{QE_EPW_CUSTOM_ADD_ALL_MAX_ROWS_HARD_LIMIT}），请分批操作"
        )

    # 解析 refs（与你 /tasks 一致）
    refs, refs_ok = _resolve_qe_epw_refs_for_request(alias, db, scope)
    if not refs_ok:
        raise HTTPException(status_code=404, detail="没有可用的源数据库")
    
    # 防止把目标库当作源库之一（会导致大量 exists/重复扫描）
    refs_ok = [
        r for r in refs_ok
        if getattr(r, "dbpath", None)
        and Path(str(getattr(r, "dbpath"))).is_file()
        and str(getattr(r, "dbpath", "")) != str(dst_path)
    ]
    if not refs_ok:
        return {"ok": True, "target": target_safe, "total_candidates": 0, "processed": 0, "inserted": 0, "exists": 0, "skipped": 0, "truncated": False, "message": "源库仅包含目标库本身，无需收藏"}

    selected_elems = set(_parse_elems_param(elems))

    # --- 计算每个库的匹配 ids（全量，不分页）---
    per_db_ids: Dict[str, List[int]] = {}
    per_db_ref: Dict[str, Any] = {r.key: r for r in refs_ok}

    for ref in refs_ok:
        con = _connect_sqlite(str(ref.dbpath))
        try:
            if not _has_tables(con):
                per_db_ids[ref.key] = []
                continue
            filtered_ids = _compute_filtered_ids_for_db_qe(
                con,
                selected_elems=selected_elems,
                mode=elem_mode,
                cp_flts=cp_flts,   # ✅ 关键：使用输入参数筛选
            )
            per_db_ids[ref.key] = _get_all_ids_sqlite(con) if filtered_ids is None else list(filtered_ids)
        finally:
            con.close()

    total_candidates = sum(len(v) for v in per_db_ids.values())
    if total_candidates == 0:
        return {"ok": True, "target": target_safe, "total_candidates": 0, "processed": 0, "inserted": 0, "exists": 0, "skipped": 0, "truncated": False, "message": "当前筛选结果为空，无需收藏"}

    inserted = exists = skipped = processed = 0
    truncated = False

    def update():
        if progress_cb:
            progress_cb({
                "total_candidates": int(total_candidates),
                "processed": int(processed),
                "inserted": int(inserted),
                "exists": int(exists),
                "skipped": int(skipped),
                "truncated": bool(truncated),
            })

    # --- 打开目标库，预读 content_hash 去重（O(1) 查重）---
    dst = _connect_sqlite(str(dst_path))
    try:
        if not _has_tables(dst):
            raise HTTPException(status_code=400, detail="target is not a qe_epw sqlite schema")

        # ✅ 目标库已有 content_hash
        existing_hash: set[str] = set()
        try:
            rows = dst.execute("SELECT content_hash FROM runs WHERE content_hash IS NOT NULL").fetchall()
            for r in rows:
                h = (r["content_hash"] or "").strip()
                if h:
                    existing_hash.add(h)
        except Exception:
            existing_hash = set()

        update()

        for dbKey in sorted(per_db_ids.keys()):
            ref = per_db_ref.get(dbKey)
            if ref is None:
                continue
            ids = per_db_ids.get(dbKey) or []
            if not ids:
                continue

            src = _connect_sqlite(str(ref.dbpath))
            try:
                if not _has_tables(src):
                    continue

                for rid in ids:
                    if processed >= max_rows:
                        truncated = True
                        update()
                        break

                    processed += 1

                    r = src.execute("SELECT * FROM runs WHERE id=?", (int(rid),)).fetchone()
                    if r is None:
                        skipped += 1
                        if processed % 200 == 0: update()
                        continue

                    run_dict = dict(r)

                    content_hash = (run_dict.get("content_hash") or "").strip() if isinstance(run_dict.get("content_hash"), str) else ""
                    if not content_hash:
                        content_hash = _stable_content_hash_for_run_dict(run_dict)
                        run_dict["content_hash"] = content_hash

                    if content_hash in existing_hash:
                        exists += 1
                        if processed % 200 == 0: update()
                        continue

                    # 插入 runs（去掉 id，让目标库自增）
                    run_dict.pop("id", None)

                    cols = list(run_dict.keys())
                    sql = "INSERT INTO runs (" + ",".join(cols) + ") VALUES (" + ",".join(["?"] * len(cols)) + ")"

                    try:
                        with dst:
                            cur = dst.execute(sql, [run_dict[c] for c in cols])
                            new_run_id = int(cur.lastrowid)

                            # mobility
                            if _sqlite_table_exists(src, "mobility") and _sqlite_table_exists(dst, "mobility"):
                                mob_rows = src.execute("SELECT * FROM mobility WHERE run_id=?", (int(rid),)).fetchall()
                                for mr in mob_rows:
                                    d = dict(mr)
                                    d.pop("id", None)
                                    d["run_id"] = new_run_id
                                    mcols = list(d.keys())
                                    msql = "INSERT INTO mobility (" + ",".join(mcols) + ") VALUES (" + ",".join(["?"] * len(mcols)) + ")"
                                    dst.execute(msql, [d[c] for c in mcols])

                            # file_refs
                            if _sqlite_table_exists(src, "file_refs") and _sqlite_table_exists(dst, "file_refs"):
                                fr_rows = src.execute("SELECT * FROM file_refs WHERE run_id=?", (int(rid),)).fetchall()
                                for fr in fr_rows:
                                    d = dict(fr)
                                    d.pop("id", None)
                                    d["run_id"] = new_run_id
                                    fcols = list(d.keys())
                                    fsql = "INSERT INTO file_refs (" + ",".join(fcols) + ") VALUES (" + ",".join(["?"] * len(fcols)) + ")"
                                    dst.execute(fsql, [d[c] for c in fcols])

                        inserted += 1
                        existing_hash.add(content_hash)
                    except sqlite3.IntegrityError:
                        # 并发/重复兜底
                        exists += 1
                        existing_hash.add(content_hash)
                    except Exception:
                        skipped += 1

                    if processed % 200 == 0:
                        update()

            finally:
                src.close()

            if truncated:
                break

        update()

    finally:
        dst.close()

    msg = f"全部收藏完成：新增 {inserted} 条，已存在 {exists} 条，跳过/失败 {skipped} 条"
    if truncated:
        msg += f"（已达到 max_rows={max_rows}，剩余未处理）"

    return {
        "ok": True,
        "target": target_safe,
        "total_candidates": int(total_candidates),
        "processed": int(processed),
        "inserted": int(inserted),
        "exists": int(exists),
        "skipped": int(skipped),
        "truncated": bool(truncated),
        "message": msg,
    }

@router.post("/custom/add_all_async")
def add_all_qe_async(req: AddAllToCustomQeReq, current_user=Depends(get_current_user)) -> Dict[str, Any]:
    from tasks.qe_epw_custom_add_all import qe_epw_custom_add_all_task  # ✅ 延迟 import

    alias = (current_user.alias or "").strip()
    payload = req.model_dump()
    payload["alias"] = alias

    ar = qe_epw_custom_add_all_task.delay(payload)
    return {"ok": True, "job_id": ar.id}

@router.get("/custom/add_all_status/{job_id}")
def add_all_qe_status(job_id: str, current_user=Depends(get_current_user)) -> Dict[str, Any]:
    from celery_app import celery_app
    r = AsyncResult(job_id, app=celery_app)
    resp: Dict[str, Any] = {
        "ok": True,
        "job_id": job_id,
        "state": r.state,
        "meta": r.info if isinstance(r.info, dict) else None,
    }
    if r.state == "SUCCESS":
        resp["result"] = r.result
    if r.state == "FAILURE":
        resp["error"] = str(r.info)
    return resp

@router.post("/custom/remove")
def remove_run_from_custom_qe(
    req: RemoveFromCustomQeReq,
    current_user=Depends(get_current_user),
) -> Dict[str, Any]:
    """
    从 QE+EPW 自定义库移除一条 run（只影响自定义库，不影响源库）。
    同步删除子表 mobility/file_refs 中 run_id 对应记录。
    """
    alias = (current_user.alias or "").strip()
    if not alias:
        raise HTTPException(status_code=403, detail="invalid user alias")

    db_key = (req.db_key or "").strip()
    if not db_key.startswith("custom_qe_epw:"):
        raise HTTPException(status_code=400, detail="db_key must start with custom_qe_epw:")

    parts = db_key.split(":", 2)  # custom_qe_epw, owner_alias, filename
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="invalid custom db_key format")

    _tag, owner_alias, fname = parts[0], parts[1].strip(), parts[2].strip()
    if not owner_alias or not fname:
        raise HTTPException(status_code=400, detail="invalid custom db_key")

    # ✅ 权限：只能操作自己的自定义库（root 也不允许越权）
    if owner_alias != alias:
        raise HTTPException(status_code=403, detail="只能操作自己的自定义库")

    if not fname.endswith(".sqlite"):
        raise HTTPException(status_code=400, detail="invalid custom db filename")

    safe_stem = Path(fname).stem
    dbp = _qe_custom_db_path(alias, safe_stem)
    if not dbp.exists():
        raise HTTPException(status_code=404, detail="目标 QE+EPW 自定义数据库不存在")
    if not dbp.is_file():
        raise HTTPException(status_code=400, detail="目标 QE+EPW 自定义数据库不是有效文件")

    rid = int(req.row_id)

    con = _connect_sqlite(str(dbp))
    try:
        if not _has_tables(con):
            raise HTTPException(status_code=400, detail="target is not a qe_epw sqlite schema")

        # 先确认 run 是否存在
        hit = con.execute("SELECT id FROM runs WHERE id=? LIMIT 1", (rid,)).fetchone()
        if hit is None:
            if int(req.missing_ok) == 1:
                return {"ok": True, "status": "missing", "message": "该记录不存在（已视为移除完成）", "row_id": rid}
            raise HTTPException(status_code=404, detail="row not found in custom db")

        # ✅ 事务：先删子表，再删主表
        with con:
            if _sqlite_table_exists(con, "mobility"):
                con.execute("DELETE FROM mobility WHERE run_id=?", (rid,))
            if _sqlite_table_exists(con, "file_refs"):
                con.execute("DELETE FROM file_refs WHERE run_id=?", (rid,))
            con.execute("DELETE FROM runs WHERE id=?", (rid,))

        return {"ok": True, "status": "removed", "message": "已从自定义库移除", "row_id": rid}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"remove failed: {e}")
    finally:
        try:
            con.close()
        except Exception:
            pass
