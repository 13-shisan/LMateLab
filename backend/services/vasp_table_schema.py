import hashlib
import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


DEFAULT_VASP_COLUMNS = [
    "id",
    "formula",
    "energy",
    "natoms",
    "fmax",
    "pbc",
    "data.phys_spacegroup_international",
    "data.phys_bandgap_eV",
    "data.phys_vbm_eV",
    "data.phys_cbm_eV",
    "data.source_dir",
    "data.step_index",
]


_COLUMN_METADATA: Dict[str, Dict[str, Any]] = {
    "id": {"label": "记录 ID", "kind": "integer", "priority": 1},
    "formula": {"label": "化学式", "kind": "text", "priority": 1},
    "energy": {"label": "总能量", "unit": "eV", "decimals": 6, "kind": "number", "priority": 1},
    "natoms": {"label": "原子数", "kind": "integer", "priority": 2},
    "fmax": {"label": "最大力", "unit": "eV/Å", "decimals": 4, "kind": "number", "priority": 1},
    "pbc": {"label": "周期边界", "kind": "text", "priority": 3},
    "data.phys_spacegroup_international": {"label": "空间群", "kind": "text", "priority": 2},
    "data.phys_bandgap_eV": {"label": "带隙", "unit": "eV", "decimals": 4, "kind": "number", "priority": 1},
    "data.phys_vbm_eV": {"label": "VBM", "unit": "eV", "decimals": 4, "kind": "number", "priority": 3},
    "data.phys_cbm_eV": {"label": "CBM", "unit": "eV", "decimals": 4, "kind": "number", "priority": 3},
    "data.source_dir": {"label": "计算目录", "kind": "path", "priority": 1},
    "data.step_index": {"label": "离子步", "kind": "integer", "priority": 2},
}


def _fallback_label(key: str) -> str:
    leaf = str(key).split(".")[-1].replace("_", " ").strip()
    if not leaf:
        return str(key)
    return leaf[:1].upper() + leaf[1:]


def column_metadata(columns: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for raw_key in columns:
        key = str(raw_key)
        meta = dict(_COLUMN_METADATA.get(key, {}))
        if not meta:
            meta = {
                "label": _fallback_label(key),
                "kind": "json" if key.startswith("calculator_parameters.") else "text",
                "priority": 4,
            }
        meta["key"] = key
        out[key] = meta
    return out


def build_filtered_cache_identity(
    *,
    dbpath: str,
    only_last: int,
    elem_mode: str,
    selected: List[str],
    cp_filters: List[Dict[str, Any]],
    row_filters: List[Dict[str, Any]],
    query: str,
) -> str:
    payload = {
        "db": str(dbpath),
        "only_last": int(only_last),
        "mode": str(elem_mode),
        "elems": list(selected),
        "cp": cp_filters,
        "rows": row_filters,
        "query": str(query or "").strip().lower(),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(encoded.encode("utf-8")).hexdigest()


def order_ids(ids: Iterable[int], sort_order: str) -> List[int]:
    reverse = str(sort_order or "desc").lower() != "asc"
    return sorted((int(value) for value in ids), reverse=reverse)


def build_relax_ids_sqlite(dbpath: str) -> List[int]:
    """Build final-record IDs without deserializing every ASE row in Python."""
    uri = f"file:{Path(dbpath).resolve()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        rows = connection.execute(
            """
            WITH decoded AS (
                SELECT
                    id,
                    CASE
                        WHEN typeof(data) = 'blob' THEN CAST(substr(data, 9) AS TEXT)
                        ELSE CAST(data AS TEXT)
                    END AS payload
                FROM systems
            ), ranked AS (
                SELECT
                    id,
                    row_number() OVER (
                        PARTITION BY json_extract(payload, '$.source_dir')
                        ORDER BY
                            CAST(json_extract(payload, '$.step_index') AS INTEGER) DESC,
                            id ASC
                    ) AS rank_in_source
                FROM decoded
                WHERE json_valid(payload)
                  AND json_extract(payload, '$.source_dir') IS NOT NULL
            )
            SELECT id
            FROM ranked
            WHERE rank_in_source = 1
            ORDER BY id
            """
        ).fetchall()
        return [int(row[0]) for row in rows]
    finally:
        connection.close()


def search_formula_ids(dbpath: str, query: str) -> List[int]:
    text = str(query or "").strip()
    if not text:
        return []

    uri = f"file:{Path(dbpath).resolve()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        if text.isdigit():
            row = con.execute("select id from systems where id = ?", (int(text),)).fetchone()
            return [int(row[0])] if row else []
        rows = con.execute(
            "select id from systems where lower(formula) like ? order by id",
            (f"%{text.lower()}%",),
        ).fetchall()
        return [int(row[0]) for row in rows]
    finally:
        con.close()


def summarize_database_refs(
    refs: Iterable[Any],
    *,
    now_timestamp: float | None = None,
    stale_days: int = 30,
) -> Dict[str, Any]:
    now = float(now_timestamp if now_timestamp is not None else time.time())
    sources: List[Dict[str, Any]] = []
    latest_mtime: float | None = None

    for ref in refs:
        path = Path(getattr(ref, "dbpath", ""))
        exists = bool(getattr(ref, "exists", path.exists())) and path.is_file()
        mtime = path.stat().st_mtime if exists else None
        if mtime is not None and (latest_mtime is None or mtime > latest_mtime):
            latest_mtime = float(mtime)
        sources.append(
            {
                "kind": str(getattr(ref, "kind", "")),
                "key": str(getattr(ref, "key", "")),
                "dbname": str(getattr(ref, "dbname", path.name)),
                "exists": exists,
                "missingReason": None if exists else getattr(ref, "missingReason", "database file not found"),
                "updatedAt": datetime.fromtimestamp(mtime, timezone.utc).isoformat() if mtime is not None else None,
            }
        )

    existing_sources = [source for source in sources if source["exists"]]
    stale_after = max(1, int(stale_days)) * 86400
    stale = bool(latest_mtime is not None and now - latest_mtime > stale_after)
    missing_reasons = [source["missingReason"] for source in sources if source.get("missingReason")]

    return {
        "exists": bool(existing_sources),
        "sources": sources,
        "latestUpdatedAt": datetime.fromtimestamp(latest_mtime, timezone.utc).isoformat() if latest_mtime is not None else None,
        "stale": stale,
        "staleDays": max(1, int(stale_days)),
        "missingReason": None if existing_sources else "; ".join(missing_reasons) or "no existing database files",
    }
