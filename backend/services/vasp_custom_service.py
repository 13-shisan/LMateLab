# backend/services/vasp_custom_service.py
# 这个 service 会实现：

# 解析/规范化筛选条件（elems / only_last / cp_filters）
# 扫描源库得到匹配的 row_id
# 写入目标自定义库（批量查重 set）
# 支持 progress 回调（给 celery 更新 meta）

from __future__ import annotations

import os
import re
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ase.db import connect
from ase.formula import Formula


# -----------------------------
# paths / helpers (不依赖 router)
# -----------------------------
CUSTOM_DB_ROOT = Path(os.getenv(
    "VASP_CUSTOM_DB_ROOT",
    "/app/var/Customized_database/vasp"
)).resolve()

DEFAULT_MAX_ROWS = int(os.getenv("VASP_CUSTOM_ADD_ALL_MAX_ROWS_DEFAULT", "200000"))
HARD_MAX_ROWS = int(os.getenv("VASP_CUSTOM_ADD_ALL_MAX_ROWS_HARD_LIMIT", "200000"))

def safe_db_name(name: str) -> str:
    s = (name or "").strip()
    if not s:
        raise ValueError("数据库名不能为空")
    s = re.sub(r"[^\w\u4e00-\u9fff\- ]+", "_", s)
    s = s.strip().replace(" ", "_")
    if len(s) < 1:
        raise ValueError("数据库名非法")
    if len(s) > 64:
        raise ValueError("数据库名过长（>64）")
    return s


def scope_norm(scope: Optional[str]) -> str:
    s = (scope or "all").strip().lower()
    return s if s in ("all", "personal", "upload", "custom") else "all"


def custom_user_dir(alias: str) -> Path:
    return (CUSTOM_DB_ROOT / alias).resolve()


def custom_db_path(alias: str, safe_name: str) -> Path:
    p = (custom_user_dir(alias) / f"{safe_name}.db").resolve()
    if custom_user_dir(alias) not in p.parents:
        raise ValueError("invalid custom db path")
    return p


def normalize_elem_list(elems: Optional[str]) -> List[str]:
    if not elems:
        return []
    out: List[str] = []
    for x in str(elems).split(","):
        s = x.strip()
        if not s:
            continue
        if len(s) == 1:
            s = s.upper()
        else:
            s = s[0].upper() + s[1:].lower()
        out.append(s)
    seen = set()
    uniq: List[str] = []
    for s in out:
        if s not in seen:
            uniq.append(s)
            seen.add(s)
    return uniq


def parse_formula_elements(formula: Any) -> List[str]:
    if not formula:
        return []
    try:
        f = Formula(str(formula))
        return list(f.count().keys())
    except Exception:
        return []


def jsonify(v: Any) -> Any:
    if v is None:
        return None

    # numpy
    try:
        import numpy as np
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
    if isinstance(v, Path):
        return str(v)

    # datetime
    try:
        import datetime as dt
        if isinstance(v, (dt.datetime, dt.date)):
            return v.isoformat()
    except Exception:
        pass

    if isinstance(v, dict):
        return {str(k): jsonify(val) for k, val in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonify(x) for x in v]

    return v


def sanitize_kvp(kv: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(kv, dict):
        return {}

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
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", ks):
            continue
        out[ks] = v
    return out


def as_dict_maybe(x: Any) -> Dict[str, Any]:
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
    try:
        if hasattr(x, "items"):
            return dict(x.items())
    except Exception:
        pass
    return {}


def get_calc_params_from_row(row) -> Dict[str, Any]:
    cp = as_dict_maybe(getattr(row, "calculator_parameters", None))
    if cp:
        return cp

    d = getattr(row, "data", None)
    if isinstance(d, dict):
        cp2 = as_dict_maybe(d.get("calculator_parameters"))
        if cp2:
            return cp2

    try:
        td = row.todict()
        if isinstance(td, dict):
            cp3 = as_dict_maybe(td.get("calculator_parameters"))
            if cp3:
                return cp3
    except Exception:
        pass

    return {}


def normalize_cp_path(path: str) -> str:
    p = (path or "").strip()
    if not p:
        return p
    if p.startswith("data.calculator_parameters."):
        p = p[len("data.calculator_parameters."):]
    elif p == "data.calculator_parameters":
        p = ""
    if p.startswith("calculator_parameters."):
        p = p[len("calculator_parameters."):]
    elif p == "calculator_parameters":
        p = ""
    return p


def get_by_path(d: Any, path: str) -> Any:
    if not isinstance(d, dict):
        return None
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def cp_value(row, path: str) -> Any:
    cp = get_calc_params_from_row(row)
    if not isinstance(cp, dict):
        return None
    p = normalize_cp_path(path)
    if not p:
        return cp
    return get_by_path(cp, p)


def cp_canon(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return format(v, ".12g")
    if isinstance(v, (list, tuple, dict)):
        try:
            return json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        except Exception:
            return str(v)
    if isinstance(v, str):
        s = v.strip()
        if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
            try:
                obj = json.loads(s)
                return cp_canon(obj)
            except Exception:
                return s
        try:
            f = float(s)
            return format(f, ".12g")
        except Exception:
            return s
    return str(v)


def parse_cp_filters_any(cp_filters: Any) -> List[Dict[str, Any]]:
    if cp_filters is None or cp_filters == "":
        return []
    if isinstance(cp_filters, str):
        try:
            obj = json.loads(cp_filters)
        except Exception:
            return []
    elif isinstance(cp_filters, list):
        obj = cp_filters
    else:
        try:
            obj = json.loads(json.dumps(cp_filters, ensure_ascii=False))
        except Exception:
            return []

    if not isinstance(obj, list):
        return []

    out: List[Dict[str, Any]] = []
    for it in obj:
        if not isinstance(it, dict):
            continue
        path = normalize_cp_path(str(it.get("path", "")).strip())
        op = str(it.get("op", "eq")).strip().lower()
        val = it.get("value", None)
        if not path:
            continue
        if op not in ("eq",):
            op = "eq"
        out.append({"path": path, "op": op, "value": val})
    return out


def row_match_filters(
    row,
    selected_elems: List[str],
    elem_mode: str,
    cp_flts: List[Dict[str, Any]],
    query: str = "",
) -> bool:
    query2 = str(query or "").strip().lower()
    if query2:
        row_id = str(getattr(row, "id", "") or "")
        formula = str(getattr(row, "formula", "") or "").lower()
        if query2.isdigit():
            if row_id != query2:
                return False
        elif query2 not in formula:
            return False

    # elems filter
    if selected_elems:
        syms = set(parse_formula_elements(getattr(row, "formula", None)))
        sel = set(selected_elems)

        if elem_mode == "only":
            if not syms:
                return False
            if not syms.issubset(sel):
                return False
        else:
            # at_least
            if not sel.issubset(syms):
                return False

    # cp_filters AND
    for flt in cp_flts:
        if flt.get("op") != "eq":
            continue
        got = cp_canon(cp_value(row, flt["path"]))
        want = cp_canon(flt.get("value"))
        if got != want:
            return False

    return True


def pick_only_last_ids(con) -> List[int]:
    """
    only_last=1：每个 source_dir 只保留 step_index 最大的行 id
    """
    best: Dict[str, Tuple[int, int]] = {}  # src -> (step, row_id)
    for r in con.select():
        d = getattr(r, "data", None) or {}
        if not isinstance(d, dict):
            continue
        src = d.get("source_dir")
        if not src:
            continue
        step = d.get("step_index", -1)
        try:
            step_i = int(step)
        except Exception:
            step_i = -1

        rid = getattr(r, "id", None)
        if rid is None:
            continue

        prev = best.get(src)
        if prev is None or step_i > prev[0]:
            best[src] = (step_i, int(rid))

    ids = [rid for (_step, rid) in best.values()]
    ids.sort()
    return ids


ProgressCb = Optional[Callable[[Dict[str, Any]], None]]


def add_all_to_custom(
    *,
    alias: str,
    target: str,
    db: Optional[str],
    scope: str,
    only_last: int,
    elems: Optional[str],
    elem_mode: str,
    cp_filters: Any,
    query: str,
    max_rows: int,
    resolve_dbset_for_request,   # 注入依赖（来自 authz_db）
    progress_cb: ProgressCb = None,
) -> Dict[str, Any]:
    """
    纯 service：不 import FastAPI/router。
    """
    if not alias:
        raise ValueError("alias is empty")

    target_safe = safe_db_name(target)
    dst_path = custom_db_path(alias, target_safe)
    if not dst_path.exists():
        raise FileNotFoundError("目标自定义数据库不存在")
    if not dst_path.is_file():
        raise ValueError("目标自定义数据库不是有效文件")

    scope2 = scope_norm(scope)
    selected_db = (db or "").strip() if isinstance(db, str) else db

    # refs 来自 authz_db（不在 service 内 import router）
    refs = resolve_dbset_for_request(alias, selected_db, scope=scope2)

    # scope filter（复制你 router 的规则，但不依赖 router）
    def is_custom_ref(ref) -> bool:
        k = str(getattr(ref, "key", "") or "")
        kind = str(getattr(ref, "kind", "") or "")
        if k.startswith("custom:"):
            return True
        if kind in ("custom", "vasp_custom"):
            return True
        return False

    if scope2 == "custom":
        if selected_db and not str(selected_db).strip().startswith("custom:"):
            raise ValueError("custom database is not allowed in scope=all/personal/upload")
        refs = [r for r in refs if is_custom_ref(r)]
    else:
        refs = [r for r in refs if not is_custom_ref(r)]

    refs_ok = [
        r for r in refs
        if bool(getattr(r, "exists", True))
        and getattr(r, "dbpath", None)
        and Path(str(getattr(r, "dbpath"))).is_file()
    ]
    if not refs_ok:
        raise FileNotFoundError("没有可用的源数据库")

    sel = normalize_elem_list(elems or "")
    mode = (elem_mode or "at_least").strip().lower()
    if mode not in ("at_least", "only"):
        mode = "at_least"

    only_last2 = 1 if int(only_last) == 1 else 0

    max_rows2 = int(max_rows or 0)
    if max_rows2 <= 0:
        max_rows2 = DEFAULT_MAX_ROWS
    if max_rows2 > HARD_MAX_ROWS:
        raise ValueError(f"max_rows 过大（>{HARD_MAX_ROWS}），请分批操作")

    cp_flts = parse_cp_filters_any(cp_filters)

    # --- 先扫描每个库，得到匹配 ids（保证 total_candidates 可用）---
    per_db_ids: Dict[str, List[int]] = {}
    per_db_ref: Dict[str, Any] = {r.key: r for r in refs_ok}

    for ref in refs_ok:
        with connect(str(ref.dbpath)) as con:
            if only_last2 == 1:
                base_ids = pick_only_last_ids(con)
                rows_iter = (con.get(id=rid) for rid in base_ids)
            else:
                # 全表遍历：用 select() 拿 row（含 id）
                rows_iter = con.select()

            ids: List[int] = []
            for r in rows_iter:
                if r is None:
                    continue
                rid = getattr(r, "id", None)
                if rid is None:
                    continue
                if row_match_filters(r, sel, mode, cp_flts, query=query):
                    ids.append(int(rid))
                    # 这里不截断 ids，因为我们还要算 total_candidates；
                    # 真正写入时会按 max_rows 截断 processed。
            ids.sort()
            per_db_ids[ref.key] = ids

    total_candidates = sum(len(v) for v in per_db_ids.values())
    if total_candidates == 0:
        return {
            "ok": True,
            "target": target_safe,
            "total_candidates": 0,
            "processed": 0,
            "inserted": 0,
            "exists": 0,
            "skipped": 0,
            "truncated": False,
            "message": "当前筛选结果为空，无需收藏",
        }

    inserted = exists = skipped = processed = 0
    truncated = False

    def update_progress():
        if progress_cb:
            progress_cb({
                "total_candidates": total_candidates,
                "processed": processed,
                "inserted": inserted,
                "exists": exists,
                "skipped": skipped,
                "truncated": truncated,
            })

    # --- 写入目标库（一次性读 sig set）---
    with connect(str(dst_path)) as dst_con:
        existing_sigs: set[str] = set()
        try:
            for r in dst_con.select():
                kv = getattr(r, "key_value_pairs", None) or {}
                sig0 = kv.get("custom_signature")
                if sig0:
                    existing_sigs.add(str(sig0))
        except Exception:
            existing_sigs = set()

        update_progress()

        for dbKey in sorted(per_db_ids.keys()):
            ref = per_db_ref.get(dbKey)
            if ref is None:
                continue

            ids = per_db_ids.get(dbKey) or []
            if not ids:
                continue

            with connect(str(ref.dbpath)) as src_con:
                for rid in ids:
                    if processed >= max_rows2:
                        truncated = True
                        update_progress()
                        break

                    processed += 1
                    sig = f"{ref.key}#{int(rid)}"

                    if sig in existing_sigs:
                        exists += 1
                        if processed % 200 == 0:
                            update_progress()
                        continue

                    row = src_con.get(id=int(rid))
                    if row is None:
                        skipped += 1
                        if processed % 200 == 0:
                            update_progress()
                        continue

                    atoms = row.toatoms()
                    kv = dict(getattr(row, "key_value_pairs", {}) or {})
                    data = dict(getattr(row, "data", {}) or {})

                    calc = getattr(row, "calculator", None) or (data.get("calculator") if isinstance(data, dict) else None)
                    cp = get_calc_params_from_row(row)

                    if calc is not None:
                        data["calculator"] = calc
                    if cp:
                        data["calculator_parameters"] = cp

                    data["_custom_src_db_key"] = str(ref.key)
                    data["_custom_src_row_id"] = int(rid)
                    data["_custom_signature"] = sig

                    kv = sanitize_kvp(kv)
                    kv["custom_signature"] = sig

                    kv2 = jsonify(kv)
                    data2 = jsonify(data)

                    try:
                        dst_con.write(
                            atoms,
                            key_value_pairs=kv2 if isinstance(kv2, dict) else {},
                            data=data2 if isinstance(data2, dict) else {},
                        )
                        inserted += 1
                        existing_sigs.add(sig)
                    except Exception:
                        # 失败就算 skipped（并发极少发生，因为 worker 通常 concurrency=1）
                        skipped += 1

                    if processed % 200 == 0:
                        update_progress()

            if truncated:
                break

        update_progress()

    msg = f"全部收藏完成：新增 {inserted} 条，已存在 {exists} 条，跳过/失败 {skipped} 条"
    if truncated:
        msg += f"（已达到 max_rows={max_rows2}，剩余未处理）"

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
