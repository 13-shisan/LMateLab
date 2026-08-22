from __future__ import annotations

import hashlib
import io
import json
import math
import zipfile
from types import MappingProxyType
from typing import Any

import numpy as np
from ase import Atoms
from ase.build import graphene, mx2
from ase.io import write as ase_write

from services.competition_inputs import MAX_ATOMS


class StructureBuildError(ValueError):
    pass


_MATERIALS = (
    {"id": "MoS2_monolayer", "name": "2H-MoS2 单层", "formula": "MoS2", "family": "transition_metal_dichalcogenide", "builder": "mx2", "lattice_a_angstrom": 3.18, "layer_thickness_angstrom": 3.19, "species_order": ("Mo", "S"), "workflow_compatible": True},
    {"id": "WS2_monolayer", "name": "2H-WS2 单层", "formula": "WS2", "family": "transition_metal_dichalcogenide", "builder": "mx2", "lattice_a_angstrom": 3.18, "layer_thickness_angstrom": 3.14, "species_order": ("W", "S"), "workflow_compatible": False},
    {"id": "MoSe2_monolayer", "name": "2H-MoSe2 单层", "formula": "MoSe2", "family": "transition_metal_dichalcogenide", "builder": "mx2", "lattice_a_angstrom": 3.32, "layer_thickness_angstrom": 3.34, "species_order": ("Mo", "Se"), "workflow_compatible": False},
    {"id": "WSe2_monolayer", "name": "2H-WSe2 单层", "formula": "WSe2", "family": "transition_metal_dichalcogenide", "builder": "mx2", "lattice_a_angstrom": 3.32, "layer_thickness_angstrom": 3.36, "species_order": ("W", "Se"), "workflow_compatible": False},
    {"id": "graphene", "name": "石墨烯单层", "formula": "C2", "family": "honeycomb", "builder": "graphene", "lattice_a_angstrom": 2.46, "layer_thickness_angstrom": 0.0, "species_order": ("C",), "workflow_compatible": False},
    {"id": "hBN", "name": "六方氮化硼单层", "formula": "BN", "family": "honeycomb", "builder": "graphene", "lattice_a_angstrom": 2.50, "layer_thickness_angstrom": 0.0, "species_order": ("B", "N"), "workflow_compatible": False},
)

_BY_ID = MappingProxyType({item["id"]: item for item in _MATERIALS})
_FILE_NAMES = ("POSCAR", "INCAR", "KPOINTS", "POTCAR.spec", "README.txt", "manifest.json")


def _catalog_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "name": item["name"],
        "formula": item["formula"],
        "family": item["family"],
        "dimension": "2d",
        "workflow_compatible": item["workflow_compatible"],
        "source_kind": "curated_sample_builder",
        "source_name": "Atomic Simulation Environment structure builders",
        "source_version": "ASE 3.23.0",
        "provenance": "curated sample lattice; relaxation required",
    }


def list_structure_catalog() -> tuple[dict[str, Any], ...]:
    return tuple(_catalog_item(item) for item in _MATERIALS)


def _bounded_integer(name: str, value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise StructureBuildError(f"{name} must be between {minimum} and {maximum}")
    return value


def _bounded_float(name: str, value: object, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or type(value) not in (int, float):
        raise StructureBuildError(f"{name} must be between {minimum:g} and {maximum:g}")
    parsed = float(value)
    if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
        raise StructureBuildError(f"{name} must be between {minimum:g} and {maximum:g}")
    return parsed


def _primitive(item: dict[str, Any]) -> Atoms:
    if item["builder"] == "mx2":
        return mx2(
            item["formula"],
            kind="2H",
            a=item["lattice_a_angstrom"],
            thickness=item["layer_thickness_angstrom"],
            vacuum=1.0,
        )
    return graphene(formula=item["formula"], a=item["lattice_a_angstrom"], vacuum=1.0)


def _ordered(atoms: Atoms, species_order: tuple[str, ...]) -> Atoms:
    symbols = atoms.get_chemical_symbols()
    order = [index for species in species_order for index, symbol in enumerate(symbols) if symbol == species]
    if len(order) != len(symbols):
        raise StructureBuildError("generated structure contains unexpected elements")
    return atoms[order]


def _poscar(atoms: Atoms) -> str:
    output = io.StringIO()
    ase_write(output, atoms, format="vasp", direct=True, vasp5=True, sort=False)
    return output.getvalue()


def _incar(material_id: str) -> str:
    return f"""SYSTEM = {material_id} controlled 2D relaxation
PREC   = Accurate
ENCUT  = 520
EDIFF  = 1E-6
EDIFFG = -0.01
ALGO   = Normal
LREAL  = .FALSE.
LASPH  = .TRUE.
ADDGRID = .TRUE.
ISPIN  = 1
ISMEAR = 0
SIGMA  = 0.05
IBRION = 2
NSW    = 160
ISIF   = 2
ISYM   = 0
LWAVE  = .TRUE.
LCHARG = .TRUE.
"""


def _kpoint_mesh(source: object, mesh: object, repeat_a: int, repeat_b: int) -> tuple[int, int, int]:
    if source not in ("manual", "mock_qoder"):
        raise StructureBuildError("kpoints_source must be manual or mock_qoder")
    if source == "mock_qoder" and mesh is None:
        return max(1, round(15 / repeat_a)), max(1, round(15 / repeat_b)), 1
    if type(mesh) is not list or len(mesh) != 3 or any(type(value) is not int for value in mesh):
        raise StructureBuildError("kpoints_mesh must contain three integers")
    if not all(1 <= value <= 60 for value in mesh):
        raise StructureBuildError("KPOINTS mesh values must be between 1 and 60")
    return tuple(mesh)


def _kpoints(mesh: tuple[int, int, int]) -> str:
    return f"""Automatic Gamma-centered mesh
0
Gamma
{mesh[0]} {mesh[1]} {mesh[2]}
0 0 0
"""


def _manifest(files: dict[str, str], parameters: dict[str, Any], item: dict[str, Any]) -> str:
    payload = {
        "schema": "lmatelab-curated-structure-v1",
        "material_id": item["id"],
        "formula": item["formula"],
        "workflow_compatible": item["workflow_compatible"],
        "source": _catalog_item(item),
        "parameters": parameters,
        "files": {
            name: {
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "size_bytes": len(content.encode("utf-8")),
            }
            for name, content in sorted(files.items())
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def build_structure(
    *,
    material_id: str,
    repeat_a: int = 1,
    repeat_b: int = 1,
    layers: int = 1,
    vacuum_angstrom: float = 15.0,
    interlayer_spacing_angstrom: float = 6.2,
    strain_percent: float = 0.0,
    kpoints_source: str = "mock_qoder",
    kpoints_mesh: list[int] | None = None,
) -> dict[str, Any]:
    try:
        item = _BY_ID[material_id]
    except (KeyError, TypeError) as exc:
        raise StructureBuildError("material is unavailable") from exc
    repeat_a = _bounded_integer("repeat_a", repeat_a, 1, 6)
    repeat_b = _bounded_integer("repeat_b", repeat_b, 1, 6)
    layers = _bounded_integer("layers", layers, 1, 8)
    vacuum = _bounded_float("vacuum_angstrom", vacuum_angstrom, 8.0, 40.0)
    spacing = _bounded_float("interlayer_spacing_angstrom", interlayer_spacing_angstrom, 3.0, 10.0)
    strain = _bounded_float("strain_percent", strain_percent, -5.0, 5.0)
    mesh = _kpoint_mesh(kpoints_source, kpoints_mesh, repeat_a, repeat_b)

    primitive = _primitive(item)
    expected_atoms = len(primitive) * repeat_a * repeat_b * layers
    if expected_atoms > MAX_ATOMS:
        raise StructureBuildError(f"generated structure exceeds {MAX_ATOMS} atoms")

    strained_cell = np.asarray(primitive.cell.array, dtype=float)
    strained_cell[0] *= 1.0 + strain / 100.0
    strained_cell[1] *= 1.0 + strain / 100.0
    primitive.set_cell(strained_cell, scale_atoms=True)
    sheet = primitive.repeat((repeat_a, repeat_b, 1))
    positions = np.asarray(sheet.positions, dtype=float)
    positions[:, 2] -= float(positions[:, 2].min())
    sheet.positions = positions
    layer_thickness = float(np.ptp(positions[:, 2]))

    generated = Atoms(cell=sheet.cell, pbc=(True, True, True))
    for layer_index in range(layers):
        layer = sheet.copy()
        layer.translate((0.0, 0.0, layer_index * spacing))
        generated += layer
    slab_thickness = layer_thickness + (layers - 1) * spacing
    cell = np.asarray(sheet.cell.array, dtype=float)
    cell[2] = (0.0, 0.0, slab_thickness + 2.0 * vacuum)
    generated.set_cell(cell, scale_atoms=False)
    generated.translate((0.0, 0.0, vacuum))
    generated.wrap()
    generated = _ordered(generated, item["species_order"])

    symbols = generated.get_chemical_symbols()
    parameters = {
        "repeat_a": repeat_a,
        "repeat_b": repeat_b,
        "layers": layers,
        "vacuum_angstrom": vacuum,
        "interlayer_spacing_angstrom": spacing,
        "strain_percent": strain,
        "stacking": "AA",
        "kpoints_source": kpoints_source,
        "kpoints_mesh": list(mesh),
    }
    files = {
        "POSCAR": _poscar(generated),
        "INCAR": _incar(item["id"]),
        "KPOINTS": _kpoints(mesh),
        "POTCAR.spec": "\n".join(item["species_order"]) + "\n",
        "README.txt": (
            "Generated from LMateLab's bundled ASE structure catalog.\n"
            "POTCAR is not included. Resolve POTCAR.spec only inside the approved VASP runtime.\n"
            "Representative lattice values are starting points, not convergence evidence.\n"
            "The INCAR and KPOINTS are controlled drafts and require scientific review.\n"
        ),
    }
    files["manifest.json"] = _manifest(files, parameters, item)
    return {
        "material_id": item["id"],
        "workflow_compatible": item["workflow_compatible"],
        "parameters": parameters,
        "kpoints": {
            "source": kpoints_source,
            "mesh": list(mesh),
            "advisory": kpoints_source == "mock_qoder",
            "provider": "deterministic_mock" if kpoints_source == "mock_qoder" else "user",
        },
        "summary": {
            "formula": item["formula"],
            "atom_count": len(symbols),
            "elements": list(item["species_order"]),
            "layers": layers,
            "in_plane_repeat": [repeat_a, repeat_b],
            "vacuum_angstrom": vacuum,
            "cell_lengths_angstrom": [float(value) for value in generated.cell.lengths()],
        },
        "structure": {
            "symbols": symbols,
            "positions": [[float(value) for value in row] for row in generated.positions],
            "cell": [[float(value) for value in row] for row in generated.cell.array],
            "pbc": [True, True, True],
        },
        "files": files,
    }


def build_structure_bundle(**parameters: Any) -> bytes:
    result = build_structure(**parameters)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in _FILE_NAMES:
            archive.writestr(name, result["files"][name])
    return output.getvalue()
