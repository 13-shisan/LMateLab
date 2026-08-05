# services/ase_db_service.py
from __future__ import annotations
from pathlib import Path
from typing import Set
from fastapi import HTTPException
from services.elements_cache import get_cached, set_cached

def get_elements_in_ase_db(dbpath: Path) -> Set[str]:
    cached = get_cached(dbpath)
    if cached is not None:
        return set(cached)

    if not dbpath.exists() or not dbpath.is_file():
        raise HTTPException(status_code=404, detail=f"database file not found: {dbpath}")

    try:
        from ase.db import connect
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ase not available in backend env: {e}")

    elements: Set[str] = set()
    try:
        with connect(str(dbpath)) as db:
            for row in db.select():
                atoms = row.toatoms()
                elements.update(atoms.get_chemical_symbols())
    except Exception as e:
        raise HTTPException(status_code=500, detail={"message": "failed to scan ase db", "error": str(e)})

    out = sorted(elements)
    set_cached(dbpath, out)
    return set(out)
