from __future__ import annotations

import io
import re
from pathlib import Path

from ase.io import read as ase_read
from ase.io import write as ase_write

from services.competition_inputs import MAX_ATOMS, InputValidationError, parse_structure_bytes
from services.competition_agent.structures import list_structure_catalog
from services.competition_agent.structure_library import search_structures
from services.competition_agent.tools import prepared_structure_workspace


STEP_TEMPLATES = {
    "relax": "17_2d_material_relax.INCAR",
    "scf": "13_band_scf.INCAR",
    "band": "06_band_nscf.INCAR",
    "dos": "05_dos.INCAR",
}
MAX_AGENT_STRUCTURE_ATOMS = 2000

EDITABLE_PARAMETERS = {
    "SYSTEM", "ENCUT", "ISPIN", "ISMEAR", "SIGMA", "ISYM", "NBANDS",
}


def _formula(prompt: str) -> str | None:
    matches = re.findall(r"(?<![A-Za-z])(?:[A-Z][a-z]?\d*){2,}(?![A-Za-z])", prompt)
    return matches[0] if matches else None


def _steps(prompt: str) -> list[str]:
    lowered = prompt.casefold()
    if "能带" in prompt or "band" in lowered:
        return ["relax", "scf", "band"]
    if "态密度" in prompt or "dos" in lowered:
        return ["relax", "scf", "dos"]
    return ["relax"]


def _template_root() -> Path:
    return Path(__file__).resolve().parents[2] / "competition_templates" / "vasp-incar-library" / "templates"


def _uploaded_structure(file: dict[str, object]) -> tuple[dict[str, object], dict[str, object]] | None:
    if file.get("category") != "structure":
        return None
    name = str(file.get("name") or "")
    content = str(file.get("content") or "")
    suffix = Path(name).suffix.casefold()
    file_format = "cif" if suffix == ".cif" else "vasp"
    try:
        atoms = ase_read(io.StringIO(content), format=file_format)
        if len(atoms) < 1 or len(atoms) > MAX_AGENT_STRUCTURE_ATOMS:
            return None
    except Exception:
        return None
    formula = atoms.get_chemical_formula(mode="metal")
    workflow_compatible = False
    canonical_poscar = ""
    try:
        parsed = parse_structure_bytes(content.encode("utf-8"), name)
        formula = str(parsed.summary["formula"])
        canonical_poscar = parsed.canonical_poscar.decode("utf-8")
        workflow_compatible = True
    except InputValidationError:
        output = io.StringIO()
        ase_write(output, atoms, format="vasp", direct=True, vasp5=True, sort=False)
        canonical_poscar = output.getvalue()
    lengths = [float(value) for value in atoms.cell.lengths()]
    mesh = [max(1, min(15, round(30 / value))) if value > 0 else 1 for value in lengths]
    item = {
        "kind": "structure",
        "id": str(file["id"]),
        "source": "user-upload",
        "formula": formula,
        "name": name,
        "workflow_compatible": workflow_compatible,
    }
    workspace = {
        "material_id": str(file["id"]),
        "workflow_compatible": workflow_compatible,
        "source": "user-upload",
        "parameters": {"kpoints_source": "manual", "kpoints_mesh": mesh},
        "kpoints": {"source": "manual", "mesh": mesh, "advisory": True, "provider": "application"},
        "summary": {
            "formula": formula,
            "atom_count": len(atoms),
            "elements": sorted(set(atoms.get_chemical_symbols())),
            "layers": None,
            "cell_lengths_angstrom": lengths,
        },
        "structure": {
            "symbols": atoms.get_chemical_symbols(),
            "positions": [[float(value) for value in row] for row in atoms.positions],
            "cell": [[float(value) for value in row] for row in atoms.cell.array],
            "pbc": [bool(value) for value in atoms.pbc],
        },
        "files": {"POSCAR": canonical_poscar},
    }
    return item, workspace


def _structure_identity(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def calculation_plan(prompt: str, uploaded_files: list[dict[str, object]] | None = None) -> dict[str, object]:
    formula = _formula(prompt)
    uploaded = [candidate for file in (uploaded_files or []) if (candidate := _uploaded_structure(file))]
    if not formula and uploaded:
        formula = str(uploaded[0][0]["formula"])
    if not formula:
        return {"needs_upload": True, "reason": "material-not-identified", "structures": [], "templates": [], "steps": _steps(prompt)}
    if len(uploaded) > 1:
        requested = _structure_identity(formula)
        matched = [
            item for item in uploaded
            if _structure_identity(item[0]["formula"]) == requested
            or requested in _structure_identity(Path(str(item[0]["name"])).stem)
        ]
        uploaded = matched
    # A single explicitly mounted structure is authoritative. Its normalized
    # chemical formula may differ from a material nickname used in the prompt.
    curated = [item for item in list_structure_catalog() if item["formula"].casefold() == formula.casefold()]
    public = [item for item in search_structures(formula, 20)["items"] if str(item["formula"]).casefold() == formula.casefold()]
    structures = [item for item, _workspace in uploaded] + [
        {"kind": "structure", "id": item["id"], "source": "curated", "formula": item["formula"], "name": item["name"]}
        for item in curated
    ] + [{"kind": "structure", **item} for item in public]
    steps = _steps(prompt)
    templates = []
    root = _template_root()
    for step in steps:
        filename = STEP_TEMPLATES[step]
        path = root / filename
        templates.append({
            "kind": "template",
            "id": filename.removesuffix(".INCAR"),
            "step": step,
            "filename": filename,
            "content": path.read_text(encoding="utf-8"),
            "rendered_content": path.read_text(encoding="utf-8"),
            "editable_parameters": sorted(EDITABLE_PARAMETERS.intersection(
                match.group(1) for match in re.finditer(r"(?m)^\s*([A-Z][A-Z0-9_]*)\s*=\s*\{\{", path.read_text(encoding="utf-8"))
            )),
        })
    return {
        "material_formula": formula,
        "needs_upload": not structures,
        "reason": None if structures else "structure-not-found",
        "structures": structures[:10],
        "templates": templates,
        "steps": steps,
        "prepared_structure": uploaded[0][1] if uploaded else None,
    }


def prepare_calculation_workspace(plan: dict[str, object]) -> dict[str, object] | None:
    prepared = plan.get("prepared_structure")
    if isinstance(prepared, dict):
        return prepared
    structures = plan.get("structures")
    if not isinstance(structures, list) or not structures:
        return None
    selected = structures[0]
    if isinstance(selected, dict) and selected.get("source") == "curated":
        return prepared_structure_workspace(str(selected["id"]))
    return None


def apply_parameter_changes(plan: dict[str, object], changes: object) -> dict[str, object]:
    templates = plan.get("templates")
    if not isinstance(templates, list) or not isinstance(changes, list):
        return plan
    by_id = {str(item.get("id")): item for item in templates if isinstance(item, dict)}
    accepted = []
    for change in changes[:24]:
        if not isinstance(change, dict):
            continue
        template = by_id.get(str(change.get("template_id") or ""))
        parameter = str(change.get("parameter") or "").upper()
        value = str(change.get("value") or "").strip()
        reason = str(change.get("reason") or "").strip()
        if (
            template is None
            or parameter not in template.get("editable_parameters", [])
            or not value
            or len(value) > 120
            or any(char in value for char in "\r\n;`$")
        ):
            continue
        content = str(template.get("rendered_content") or template.get("content") or "")
        template["rendered_content"] = re.sub(
            rf"(?m)^(\s*{re.escape(parameter)}\s*=\s*).*$",
            lambda match: f"{match.group(1)}{value}",
            content,
            count=1,
        )
        accepted.append({
            "template_id": template["id"],
            "parameter": parameter,
            "value": value,
            "reason": reason[:500],
        })
    plan["parameter_changes"] = accepted
    return plan


def structure_analyses(structure_ids: list[str]) -> list[dict[str, object]]:
    from services.competition_agent.structure_library import vasp_library_record

    results = []
    for structure_id in structure_ids:
        record = vasp_library_record(f"qmof:{structure_id}")
        if not record or not record["vasp_detail"]["structure"]:
            continue
        structure = record["vasp_detail"]["structure"]
        results.append({
            "analyzer": "structure_summary_v1",
            "structure_id": structure_id,
            "formula": record["formula"],
            "atom_count": len(structure["symbols"]),
            "elements": sorted(set(structure["symbols"])),
            "cell": structure["cell"],
        })
    return results
