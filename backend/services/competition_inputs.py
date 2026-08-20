from __future__ import annotations

import hashlib
import io
import json
import math
import os
import shutil
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from ase import Atoms
from ase.io import read as ase_read
from ase.io import write as ase_write


MAX_STRUCTURE_BYTES = 1024 * 1024
MAX_ATOMS = 200
TEMPLATE_VERSION = "mos2_v1"
FIXED_STEPS = ("relax", "scf", "band", "dos")
TEMPLATE_ROOT = Path(__file__).resolve().parents[1] / "competition_templates"


class InputValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedStructure:
    source_format: str
    original_filename: str
    summary: dict[str, Any]
    canonical_poscar: bytes


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _reject_json_constant(value: str) -> None:
    raise InputValidationError(f"non-finite JSON number is not allowed: {value}")


def _safe_filename(filename: str) -> str:
    if not isinstance(filename, str) or not filename.strip():
        raise InputValidationError("a non-empty audit filename is required")
    try:
        encoded = filename.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise InputValidationError("structure filename must be valid UTF-8") from exc
    if (
        filename != filename.strip()
        or len(encoded) > 255
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
        or "/" in filename
        or "\\" in filename
        or ".." in filename
    ):
        raise InputValidationError("structure filename must not contain path components")
    return filename


def _decode_structure(content: bytes) -> str:
    if not isinstance(content, bytes):
        raise InputValidationError("structure content must be bytes")
    if not content or not content.strip():
        raise InputValidationError("structure file is empty")
    if len(content) > MAX_STRUCTURE_BYTES:
        raise InputValidationError("structure file exceeds 1 MiB")
    if b"\x00" in content:
        raise InputValidationError("binary structure content is not allowed")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InputValidationError("structure file must be UTF-8 text") from exc


def _vasp_element_order(text: str) -> list[str]:
    lines = text.splitlines()
    if len(lines) < 7:
        raise InputValidationError("VASP structure is missing the element header")
    symbols = lines[5].split()
    if symbols != ["Mo", "S"]:
        raise InputValidationError("POSCAR element order must be exactly 'Mo S'")
    return symbols


def _preflight_vasp_header(text: str) -> bool:
    lines = text.splitlines()
    if len(lines) < 7:
        return False
    try:
        scale_tokens = lines[1].split()
        lattice_tokens = [line.split() for line in lines[2:5]]
        if len(scale_tokens) not in (1, 3) or any(len(row) != 3 for row in lattice_tokens):
            return False
        numeric_header = []
        for token in scale_tokens:
            numeric_header.append(float(token))
        for row in lattice_tokens:
            for token in row:
                numeric_header.append(float(token))
    except ValueError:
        return False
    if not all(math.isfinite(value) for value in numeric_header):
        raise InputValidationError("VASP scale and lattice vectors must be finite")

    symbols = lines[5].split()
    count_tokens = lines[6].split()
    if not symbols or len(symbols) != len(count_tokens):
        return False
    if any(not symbol.isalpha() or len(symbol) > 3 for symbol in symbols):
        return False
    if any(not token.isascii() or not token.isdecimal() for token in count_tokens):
        return False
    if any(len(token) > 12 for token in count_tokens):
        raise InputValidationError(f"VASP structure exceeds {MAX_ATOMS} atoms")

    counts = [int(token) for token in count_tokens]
    if any(count <= 0 for count in counts):
        return False
    if sum(counts) > MAX_ATOMS:
        raise InputValidationError(f"VASP structure exceeds {MAX_ATOMS} atoms")
    if symbols != ["Mo", "S"]:
        raise InputValidationError("POSCAR element order must be exactly 'Mo S'")
    return True


def _read_structure(text: str, try_vasp: bool) -> tuple[Atoms, str]:
    errors: list[str] = []
    if try_vasp:
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message="invalid value encountered in matmul",
                    category=RuntimeWarning,
                    module=r"ase\.cell",
                )
                atoms = ase_read(io.StringIO(text), format="vasp")
            _vasp_element_order(text)
            return atoms, "vasp"
        except Exception as exc:
            errors.append(f"vasp: {exc}")
    else:
        errors.append("vasp: header/counts are not safely recognizable")

    try:
        atoms = ase_read(io.StringIO(text), format="cif")
        return atoms, "cif"
    except Exception as exc:
        errors.append(f"cif: {exc}")

    raise InputValidationError(
        "structure could not be parsed as vasp or cif (" + "; ".join(errors) + ")"
    )


def _validate_and_order_atoms(atoms: Atoms, source_format: str) -> Atoms:
    symbols = atoms.get_chemical_symbols()
    if not symbols:
        raise InputValidationError("structure contains no atoms")
    if len(symbols) > MAX_ATOMS:
        raise InputValidationError(f"structure exceeds {MAX_ATOMS} atoms")
    if set(symbols) != {"Mo", "S"}:
        raise InputValidationError("structure may contain only Mo and S")
    mo_count = symbols.count("Mo")
    s_count = symbols.count("S")
    if mo_count <= 0 or s_count != 2 * mo_count:
        raise InputValidationError("structure stoichiometry must be Mo:S = 1:2")

    if source_format == "vasp":
        expected = ["Mo"] * mo_count + ["S"] * s_count
        if symbols != expected:
            raise InputValidationError("POSCAR atom groups must follow element order 'Mo S'")
        return atoms

    order = [index for index, symbol in enumerate(symbols) if symbol == "Mo"]
    order.extend(index for index, symbol in enumerate(symbols) if symbol == "S")
    return atoms[order]


def _validate_geometry(atoms: Atoms) -> None:
    if not bool(np.all(atoms.pbc)):
        raise InputValidationError("structure must be periodic in all three cell directions")
    cell = np.asarray(atoms.cell.array, dtype=float)
    positions = np.asarray(atoms.positions, dtype=float)
    if cell.shape != (3, 3) or not np.isfinite(cell).all():
        raise InputValidationError("structure cell must contain finite lattice vectors")
    if positions.shape != (len(atoms), 3) or not np.isfinite(positions).all():
        raise InputValidationError("structure positions must be finite")
    if np.linalg.matrix_rank(cell, tol=1e-10) != 3 or abs(float(np.linalg.det(cell))) <= 1e-8:
        raise InputValidationError("structure cell must be non-degenerate")
    try:
        scaled_positions = np.asarray(atoms.get_scaled_positions(wrap=False), dtype=float)
    except (ValueError, np.linalg.LinAlgError) as exc:
        raise InputValidationError("structure scaled positions are invalid") from exc
    if not np.isfinite(scaled_positions).all():
        raise InputValidationError("structure scaled positions must be finite")


def _write_poscar(atoms: Atoms) -> bytes:
    output = io.StringIO()
    try:
        ase_write(output, atoms, format="vasp", direct=True, vasp5=True, sort=False)
    except Exception as exc:
        raise InputValidationError("structure could not be written as canonical POSCAR") from exc
    return output.getvalue().encode("utf-8")


def parse_structure_bytes(content: bytes, filename: str) -> ParsedStructure:
    audit_filename = _safe_filename(filename)
    text = _decode_structure(content)
    atoms, source_format = _read_structure(text, _preflight_vasp_header(text))
    atoms = _validate_and_order_atoms(atoms, source_format)
    _validate_geometry(atoms)
    symbols = atoms.get_chemical_symbols()
    mo_count = symbols.count("Mo")
    s_count = symbols.count("S")
    cell_lengths = [float(value) for value in atoms.cell.lengths()]
    summary = {
        "atom_count": len(symbols),
        "cell_lengths_angstrom": cell_lengths,
        "counts": {"Mo": mo_count, "S": s_count},
        "elements": ["Mo", "S"],
        "formula": "MoS2",
        "periodic": [bool(value) for value in atoms.pbc],
    }
    return ParsedStructure(
        source_format=source_format,
        original_filename=audit_filename,
        summary=summary,
        canonical_poscar=_write_poscar(atoms),
    )


def load_template(template_version: str) -> dict[str, Any]:
    if template_version != TEMPLATE_VERSION:
        raise InputValidationError("only template 'mos2_v1' is allowed")
    path = TEMPLATE_ROOT / TEMPLATE_VERSION / "template.json"
    try:
        template = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=_reject_json_constant,
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise InputValidationError("fixed template is unavailable or invalid") from exc
    if template.get("template_version") != TEMPLATE_VERSION:
        raise InputValidationError("fixed template version does not match its directory")
    if tuple(step.get("key") for step in template.get("steps", ())) != FIXED_STEPS:
        raise InputValidationError("fixed template step definition is invalid")
    return template


def _validate_parameter_value(step: str, key: str, value: Any, rule: dict[str, Any]) -> Any:
    if isinstance(value, bool) or type(value) not in (int, float):
        raise InputValidationError(f"{step}.{key} must be a numeric JSON value")
    if not math.isfinite(value):
        raise InputValidationError(f"{step}.{key} must be finite")
    if rule["type"] == "integer" and type(value) is not int:
        raise InputValidationError(f"{step}.{key} must be an integer")
    if value < rule["minimum"] or value > rule["maximum"]:
        raise InputValidationError(f"{step}.{key} is outside the allowed range")
    return value


def validate_draft_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InputValidationError("draft payload must be an object")
    required = {"template_version", "source_kind", "steps", "parameters"}
    optional = {"structure_upload_id"}
    if set(payload) - required - optional or required - set(payload):
        raise InputValidationError("draft payload fields do not match the fixed contract")

    template = load_template(payload["template_version"])
    source_kind = payload["source_kind"]
    if source_kind not in ("builtin", "upload"):
        raise InputValidationError("source_kind must be builtin or upload")
    upload_id = payload.get("structure_upload_id")
    if source_kind == "builtin" and upload_id is not None:
        raise InputValidationError("builtin source must not include structure_upload_id")
    if source_kind == "upload":
        try:
            if not isinstance(upload_id, str) or str(uuid.UUID(upload_id)) != upload_id:
                raise ValueError
        except ValueError as exc:
            raise InputValidationError("upload source requires a canonical UUID") from exc

    if type(payload["steps"]) is not list or tuple(payload["steps"]) != FIXED_STEPS:
        raise InputValidationError("workflow steps must be relax, scf, band, dos in order")
    parameters = payload["parameters"]
    if not isinstance(parameters, dict):
        raise InputValidationError("parameters must be an object")
    schema = template["parameter_schema"]
    normalized_parameters: dict[str, dict[str, Any]] = {}
    for step, values in parameters.items():
        if step not in schema or not isinstance(values, dict):
            raise InputValidationError(f"unknown parameter step: {step}")
        normalized_values: dict[str, Any] = {}
        for key, value in values.items():
            if key not in schema[step]:
                raise InputValidationError(f"unknown INCAR parameter: {step}.{key}")
            normalized_values[key] = _validate_parameter_value(
                step,
                key,
                value,
                schema[step][key],
            )
        normalized_parameters[step] = dict(sorted(normalized_values.items()))

    normalized: dict[str, Any] = {
        "parameters": dict(sorted(normalized_parameters.items())),
        "source_kind": source_kind,
        "steps": list(FIXED_STEPS),
        "template_version": TEMPLATE_VERSION,
    }
    if upload_id is not None:
        normalized["structure_upload_id"] = upload_id
    return {**normalized, "canonical_json": _canonical_json(normalized)}


def _format_incar_number(value: int | float) -> str:
    if type(value) is int:
        return str(value)
    return format(value, ".15g").replace("e", "E")


def _render_incar(base_content: str, overrides: dict[str, Any]) -> bytes:
    lines = base_content.splitlines()
    positions: dict[str, int] = {}
    for index, line in enumerate(lines):
        if "=" in line:
            positions[line.split("=", 1)[0].strip()] = index
    for key, value in sorted(overrides.items()):
        if key not in positions:
            raise InputValidationError(f"fixed INCAR is missing overridable key {key}")
        lines[positions[key]] = f"{key} = {_format_incar_number(value)}"
    return ("\n".join(lines) + "\n").encode("utf-8")


def _render_kpoints(definition: dict[str, Any]) -> bytes:
    mode = definition.get("mode")
    if mode == "gamma":
        mesh = definition["mesh"]
        return (
            "Automatic mesh\n0\nGamma\n"
            f"{mesh[0]} {mesh[1]} {mesh[2]}\n0 0 0\n"
        ).encode("ascii")
    if mode == "line":
        lines = [
            "MoS2 high-symmetry path",
            str(definition["points_per_segment"]),
            "Line-mode",
            "Reciprocal",
        ]
        points = definition["segments"]
        for index in range(len(points) - 1):
            for label, coordinates in (points[index], points[index + 1]):
                lines.append(
                    " ".join(format(value, ".15g") for value in coordinates)
                    + f" ! {label}"
                )
            if index != len(points) - 2:
                lines.append("")
        return ("\n".join(lines) + "\n").encode("ascii")
    raise InputValidationError("fixed KPOINTS definition is invalid")


def _ensure_inside(path: Path, root: Path) -> None:
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise InputValidationError("generated input path escapes workflow root") from exc


def _write_private(path: Path, content: bytes) -> dict[str, Any]:
    path.write_bytes(content)
    path.chmod(0o600)
    actual = path.read_bytes()
    return {
        "size_bytes": len(actual),
        "sha256": hashlib.sha256(actual).hexdigest(),
    }


def materialize_inputs(
    workflow_root: str | os.PathLike[str],
    structure: ParsedStructure | None,
    payload: dict[str, Any],
    *,
    _scf_incar_transform: Callable[[bytes], bytes] | None = None,
) -> dict[str, Any]:
    payload_to_validate = {key: value for key, value in payload.items() if key != "canonical_json"}
    validated = validate_draft_payload(payload_to_validate)
    if validated["source_kind"] == "builtin":
        if structure is not None:
            raise InputValidationError("builtin source must use the fixed structure")
        builtin_path = TEMPLATE_ROOT / TEMPLATE_VERSION / "POSCAR"
        parsed_structure = parse_structure_bytes(builtin_path.read_bytes(), "POSCAR")
    else:
        if not isinstance(structure, ParsedStructure):
            raise InputValidationError("upload source requires a parsed structure")
        parsed_structure = structure

    root = Path(workflow_root).resolve()
    if root.exists() and not root.is_dir():
        raise InputValidationError("workflow root is not a directory")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    root.chmod(0o700)

    directory_id = str(uuid.uuid4())
    completed_dir = root / directory_id
    staging_dir = root / f".tmp-{directory_id}"
    _ensure_inside(completed_dir, root)
    _ensure_inside(staging_dir, root)
    if completed_dir.exists() or staging_dir.exists():
        raise InputValidationError("generated workflow directory already exists")

    template = load_template(TEMPLATE_VERSION)
    records: list[dict[str, Any]] = []
    try:
        staging_dir.mkdir(mode=0o700)
        staging_dir.chmod(0o700)
        for step_definition in template["steps"]:
            step = step_definition["key"]
            step_dir = staging_dir / step
            _ensure_inside(step_dir, root)
            step_dir.mkdir(mode=0o700)
            step_dir.chmod(0o700)
            base_incar = (TEMPLATE_ROOT / TEMPLATE_VERSION / f"INCAR.{step}").read_text(
                encoding="utf-8"
            )
            contents = {
                "INCAR": _render_incar(base_incar, validated["parameters"].get(step, {})),
                "KPOINTS": _render_kpoints(step_definition["kpoints"]),
                "POSCAR": parsed_structure.canonical_poscar,
                "POTCAR.spec": ("\n".join(template["potcar_symbols"]) + "\n").encode("ascii"),
            }
            if step == "scf" and _scf_incar_transform is not None:
                transformed = _scf_incar_transform(contents["INCAR"])
                if not isinstance(transformed, bytes) or transformed == contents["INCAR"]:
                    raise InputValidationError("internal SCF transform is invalid")
                contents["INCAR"] = transformed
            for filename, content in contents.items():
                path = step_dir / filename
                _ensure_inside(path, root)
                file_metadata = _write_private(path, content)
                records.append(
                    {
                        "relative_path": f"{directory_id}/{step}/{filename}",
                        "step_key": step,
                        **file_metadata,
                    }
                )
        staging_dir.replace(completed_dir)
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    return {
        "directory": str(completed_dir),
        "directory_id": directory_id,
        "files": records,
        "structure_summary": parsed_structure.summary,
        "template_version": TEMPLATE_VERSION,
    }
