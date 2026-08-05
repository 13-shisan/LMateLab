from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


PROPERTY_FIELDS = {
    "spacegroup": "phys_spacegroup_international",
    "bandgap_eV": "phys_bandgap_eV",
    "vbm_eV": "phys_vbm_eV",
    "cbm_eV": "phys_cbm_eV",
}


def get_optional_ase_row(connection: Any, row_id: int) -> Any:
    try:
        return connection.get(id=int(row_id))
    except KeyError:
        return None


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    if hasattr(value, "tolist"):
        return _json_value(value.tolist())
    if hasattr(value, "item"):
        return _json_value(value.item())
    return str(value)


def _mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _property_value(row: Any, key: str) -> Any:
    data = _mapping(getattr(row, "data", None))
    if data.get(key) is not None:
        return data[key]
    key_value_pairs = _mapping(getattr(row, "key_value_pairs", None))
    return key_value_pairs.get(key)


def output_capabilities(*, has_vasprun: bool, has_outcar: bool) -> Dict[str, bool]:
    has_electronic_source = bool(has_vasprun or has_outcar)
    return {
        "structure_export": True,
        "band_plot": has_electronic_source,
        "band_data": has_electronic_source,
        "dos_plot": has_electronic_source,
        "dos_data": has_electronic_source,
    }


def build_public_task_detail(
    *,
    row: Any,
    db: Dict[str, Any],
    structure: Dict[str, Any],
    crystal: Dict[str, Any],
    has_vasprun: bool,
    has_outcar: bool,
) -> Dict[str, Any]:
    properties = {
        public_key: _json_value(_property_value(row, source_key))
        for public_key, source_key in PROPERTY_FIELDS.items()
    }
    return {
        "ok": True,
        "db": _json_value(db),
        "row": {
            "id": int(getattr(row, "id", 0) or 0),
            "formula": str(getattr(row, "formula", "") or "") or None,
            "energy": _json_value(getattr(row, "energy", None)),
            "fmax": _json_value(getattr(row, "fmax", None)),
            "natoms": _json_value(getattr(row, "natoms", None)),
            "pbc": _json_value(getattr(row, "pbc", None)),
        },
        "properties": properties,
        "capabilities": output_capabilities(
            has_vasprun=has_vasprun,
            has_outcar=has_outcar,
        ),
        "structure": _json_value(structure),
        "crystal": _json_value(crystal),
    }
