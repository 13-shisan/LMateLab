from __future__ import annotations

import os
import sqlite3
import re
from pathlib import Path


class StructureLibraryError(ValueError):
    pass


def database_path() -> Path:
    return Path(os.environ.get("LMATELAB_STRUCTURE_LIBRARY_DB", "data/competition-agent/structures.sqlite")).resolve()


def search_structures(query: str = "", limit: int = 30) -> dict[str, object]:
    path = database_path()
    if not path.is_file():
        return {"items": [], "total": 0, "sources": []}
    needle = query.strip()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        where = ""
        params: list[object] = []
        if needle:
            where = " WHERE id LIKE ? OR name LIKE ? OR formula LIKE ? OR topology LIKE ?"
            token = f"%{needle}%"
            params = [token, token, token, token]
        total = connection.execute(f"SELECT COUNT(*) FROM structures{where}", params).fetchone()[0]
        rows = connection.execute(
            f"SELECT id, source, name, formula, topology, natoms, bandgap, energy, doi FROM structures{where} ORDER BY id LIMIT ?",
            [*params, limit],
        ).fetchall()
        sources = [row[0] for row in connection.execute("SELECT DISTINCT source FROM structures ORDER BY source")]
    return {"items": [dict(row) for row in rows], "total": total, "sources": sources}


def selected_structures(ids: list[str]) -> list[dict[str, object]]:
    if not ids:
        return []
    path = database_path()
    if not path.is_file():
        raise StructureLibraryError("structure library is unavailable")
    placeholders = ",".join("?" for _ in ids)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"SELECT id, source, name, formula, topology, natoms, bandgap, energy, doi FROM structures WHERE id IN ({placeholders})",
            ids,
        ).fetchall()
    if len(rows) != len(set(ids)):
        raise StructureLibraryError("one or more structures are unavailable")
    by_id = {row["id"]: dict(row) for row in rows}
    return [{"kind": "structure", **by_id[item]} for item in dict.fromkeys(ids)]


def formula_elements(formula: str) -> list[str]:
    return sorted(set(re.findall(r"[A-Z][a-z]?", formula)))


def vasp_library_records(
    query: str = "",
    elements: list[str] | None = None,
    element_mode: str = "at_least",
) -> list[dict[str, object]]:
    result = search_structures(query, 100000)
    required = set(elements or [])
    records = []
    for item in result["items"]:
        present = set(formula_elements(str(item["formula"])))
        if required and (present != required if element_mode == "only" else not required.issubset(present)):
            continue
        records.append({
            "id": f"qmof:{item['id']}",
            "formula": item["formula"],
            "elements": sorted(present),
            "source": "QMOF",
            "workflow_id": item["id"],
            "status": "succeeded",
            "bandgap_eV": item["bandgap"],
            "energy": item["energy"],
            "completed_at": None,
            "data_kind": "live",
        })
    return records


def vasp_library_record(record_id: str) -> dict[str, object] | None:
    if not record_id.startswith("qmof:"):
        return None
    structure_id = record_id.removeprefix("qmof:")
    try:
        matches = selected_structures([structure_id])
    except StructureLibraryError:
        return None
    if not matches:
        return None
    item = matches[0]
    structure = None
    cif_root = os.environ.get("LMATELAB_QMOF_CIF_ROOT", "").strip()
    if cif_root and re.fullmatch(r"qmof-[0-9a-f]+", structure_id):
        cif_path = Path(cif_root) / f"{structure_id}.cif"
        if cif_path.is_file():
            from pymatgen.core import Structure

            parsed = Structure.from_file(cif_path)
            structure = {
                "symbols": [str(site.specie.symbol) for site in parsed],
                "positions": [[float(value) for value in site.coords] for site in parsed],
                "cell": [[float(value) for value in vector] for vector in parsed.lattice.matrix],
                "pbc": [True, True, True],
            }
    return {
        "id": record_id,
        "formula": item["formula"],
        "elements": formula_elements(str(item["formula"])),
        "source": "QMOF",
        "workflow_id": item["id"],
        "status": "succeeded",
        "bandgap_eV": item["bandgap"],
        "energy": item["energy"],
        "completed_at": "",
        "latest_job_id": "",
        "data_kind": "live",
        "artifacts": [],
        "vasp_detail": {
            "capabilities": {
                "structure_export": False,
                "band_plot": False,
                "dos_plot": False,
                "band_data": False,
                "dos_data": False,
            },
            "structure": structure,
            "library": item,
        },
    }
