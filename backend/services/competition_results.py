from __future__ import annotations

import hashlib
import io
import json
import math
import re
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Protocol

from sqlalchemy.orm import Session

from models_workflow import WorkflowAttempt, WorkflowFile, WorkflowRun, WorkflowStep, canonical_json
from services.competition_bundle import BundleError, build_evidence_bundle
from services.competition_vasp import AcceptanceReport


FIXED_STEPS = ("relax", "scf", "band", "dos")
RESULT_ARTIFACT_KINDS = frozenset(
    {"structure-cif", "structure-poscar", "band-data", "dos-data", "evidence-bundle"}
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_JOB_ID_RE = re.compile(r"[1-9][0-9]{0,99}")
_HASH_CHUNK_BYTES = 1024 * 1024


class ResultServiceError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        step_key: str | None = None,
        missing_files: tuple[str, ...] = (),
    ):
        super().__init__(message)
        self.code = code
        self.step_key = step_key
        self.missing_files = missing_files


@dataclass(frozen=True)
class VerifiedArtifact:
    path: Path
    relative_path: str
    logical_path: str
    sha256: str
    size_bytes: int
    attempt_id: str | None
    step_key: str | None


@dataclass(frozen=True)
class ResultArtifact:
    content: bytes
    filename: str
    media_type: str


class ScientificParser(Protocol):
    def build_detail(
        self, workflow_id: str, sources: Mapping[str, VerifiedArtifact]
    ) -> dict[str, Any]: ...

    def render_plot(self, kind: str, source: VerifiedArtifact) -> str: ...

    def export_artifact(
        self, kind: str, sources: Mapping[str, VerifiedArtifact]
    ) -> bytes: ...


def _metadata(value: str | Mapping[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not value:
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _timestamp(value) -> str | None:
    return value.isoformat() if value is not None else None


def _source_label(source_kind: str) -> str:
    return "uploaded structure" if source_kind == "upload" else "built-in MoS2"


def _latest_attempt(step: WorkflowStep) -> WorkflowAttempt | None:
    return max(step.attempts, key=lambda item: item.attempt_number, default=None)


def _finite_or_none(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


class ExistingVaspScientificParser:
    """Adapter around the existing VASP plot/data parsers and ASE structures."""

    @staticmethod
    def _legacy_parsers():
        from routers import vasp_db

        return vasp_db

    @staticmethod
    def _atoms(source: VerifiedArtifact):
        from ase.io import read as ase_read

        return ase_read(str(source.path), format="vasp")

    def build_detail(
        self, workflow_id: str, sources: Mapping[str, VerifiedArtifact]
    ) -> dict[str, Any]:
        import numpy as np
        from pymatgen.io.ase import AseAtomsAdaptor
        from pymatgen.io.vasp.outputs import Vasprun

        atoms = self._atoms(sources["relax"])
        scf = Vasprun(
            str(sources["scf"].path),
            parse_projected_eigen=False,
            parse_potcar_file=False,
        )
        band_run = Vasprun(
            str(sources["band"].path),
            parse_projected_eigen=False,
            parse_potcar_file=False,
        )
        band = band_run.get_band_structure(line_mode=True)
        gap = band.get_band_gap()
        vbm = band.get_vbm()
        cbm = band.get_cbm()
        positions = atoms.get_positions().tolist()
        cell = atoms.cell.array.tolist()
        pbc = [bool(item) for item in atoms.pbc]
        lengths = atoms.cell.lengths().tolist()
        angles = atoms.cell.angles().tolist()
        volume = float(atoms.get_volume())
        density = None
        if volume > 0:
            density = float(sum(atoms.get_masses())) / 6.02214076e23 / (volume * 1e-24)
        scaled = atoms.get_scaled_positions(wrap=False)
        atomic_positions = [
            {"element": symbol, "x": float(position[0]), "y": float(position[1]), "z": float(position[2])}
            for symbol, position in zip(atoms.get_chemical_symbols(), scaled, strict=True)
        ]
        structure = AseAtomsAdaptor.get_structure(atoms)
        try:
            symbol, number = structure.get_space_group_info()
            spacegroup = f"{symbol} ({number})"
        except Exception:
            spacegroup = None
        efermi = _finite_or_none(band.efermi)
        vbm_energy = _finite_or_none(vbm.get("energy"))
        cbm_energy = _finite_or_none(cbm.get("energy"))
        return {
            "db": {"dbname": "107 Cup workflow results"},
            "row": {
                "id": workflow_id,
                "formula": atoms.get_chemical_formula(mode="hill"),
                "energy": _finite_or_none(scf.final_energy),
                "fmax": None,
                "natoms": len(atoms),
                "pbc": pbc,
            },
            "properties": {
                "spacegroup": spacegroup,
                "bandgap_eV": _finite_or_none(gap.get("energy")),
                "vbm_eV": vbm_energy - efermi if vbm_energy is not None and efermi is not None else None,
                "cbm_eV": cbm_energy - efermi if cbm_energy is not None and efermi is not None else None,
            },
            "structure": {
                "symbols": atoms.get_chemical_symbols(),
                "numbers": atoms.get_atomic_numbers().tolist(),
                "positions": positions,
                "cell": cell,
                "pbc": pbc,
            },
            "crystal": {
                "lattice": {
                    "a": float(lengths[0]),
                    "b": float(lengths[1]),
                    "c": float(lengths[2]),
                    "alpha": float(angles[0]),
                    "beta": float(angles[1]),
                    "gamma": float(angles[2]),
                    "volume": volume,
                },
                "density_g_cm3": density,
                "dimensionality": int(np.count_nonzero(atoms.pbc)),
                "atomic_positions_frac": atomic_positions,
            },
            "capabilities": {
                "structure_export": True,
                "band_plot": True,
                "dos_plot": True,
                "band_data": True,
                "dos_data": True,
            },
        }

    def render_plot(self, kind: str, source: VerifiedArtifact) -> str:
        parsers = self._legacy_parsers()
        if kind == "band":
            ok, value = parsers._read_vasprun_band_png_b64(str(source.path))
        elif kind == "dos":
            ok, value = parsers._read_vasprun_dos_png_b64(str(source.path), emin=-3.0, emax=3.0)
        else:
            raise ValueError("unsupported plot kind")
        if not ok:
            raise ValueError("scientific plot could not be rendered")
        return value

    def export_artifact(
        self, kind: str, sources: Mapping[str, VerifiedArtifact]
    ) -> bytes:
        if kind in {"structure-cif", "structure-poscar"}:
            from ase.io import write as ase_write

            atoms = self._atoms(sources["relax"])
            if kind == "structure-cif":
                buffer = io.BytesIO()
                ase_write(buffer, atoms, format="cif")
                return buffer.getvalue()
            else:
                buffer = io.StringIO()
                ase_write(buffer, atoms, format="vasp", vasp5=True, direct=True)
                return buffer.getvalue().encode("utf-8")
        parsers = self._legacy_parsers()
        if kind == "band-data":
            return parsers._band_dat_text_from_vasprun(str(sources["band"].path)).encode("utf-8")
        if kind == "dos-data":
            return parsers._dos_zip_bytes_from_vasprun(str(sources["dos"].path))
        raise ValueError("unsupported scientific artifact")


class CompetitionResultService:
    def __init__(
        self,
        *,
        workflow_root: Path,
        releases_root: Path | None = None,
        parser: ScientificParser | None = None,
    ):
        self.workflow_root = Path(workflow_root)
        self.releases_root = Path(releases_root) if releases_root is not None else self.workflow_root.parent.parent / "releases"
        self.parser = parser or ExistingVaspScientificParser()

    def _safe_acceptance(self, attempt: WorkflowAttempt) -> dict[str, Any]:
        metadata = _metadata(attempt.metadata_json)
        value = metadata.get("scientific_acceptance")
        digest = metadata.get("scientific_acceptance_sha256")
        if not isinstance(value, dict) or not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise ResultServiceError("acceptance_invalid", "scientific acceptance is invalid")
        try:
            report = AcceptanceReport(
                accepted=value.get("accepted"),
                reason_code=value.get("reason_code"),
                checks=tuple(value.get("checks", ())),
                measurements=value.get("measurements", {}),
                artifacts=tuple(value.get("artifacts", ())),
            )
            result = report.as_dict()
        except (AttributeError, TypeError, ValueError):
            raise ResultServiceError("acceptance_invalid", "scientific acceptance is invalid") from None
        calculated = hashlib.sha256(canonical_json(result).encode("utf-8")).hexdigest()
        expected_status = "succeeded" if report.accepted else "scientific_failed"
        if calculated != digest or attempt.status != expected_status:
            raise ResultServiceError("acceptance_invalid", "scientific acceptance is invalid")
        return result

    def _safe_scheduler(self, attempt: WorkflowAttempt) -> dict[str, Any]:
        value = _metadata(attempt.metadata_json).get("scheduler_observation")
        if not isinstance(value, dict):
            raise ResultServiceError("scheduler_evidence_invalid", "scheduler evidence is invalid")
        if (
            value.get("job_id") != attempt.slurm_job_id
            or value.get("state") != "succeeded"
            or value.get("raw_state") != "COMPLETED"
            or value.get("exit_code") != "0:0"
            or value.get("stale") is not False
            or value.get("error_code") is not None
            or not isinstance(attempt.slurm_job_id, str)
            or _JOB_ID_RE.fullmatch(attempt.slurm_job_id) is None
        ):
            raise ResultServiceError("scheduler_evidence_invalid", "scheduler evidence is invalid")
        return value

    def _validate_attempt_directory(self, run: WorkflowRun, attempt: WorkflowAttempt) -> None:
        expected = self.workflow_root / run.id / "attempts" / attempt.id
        if not attempt.working_directory or Path(attempt.working_directory) != expected:
            raise ResultServiceError(
                "attempt_path_invalid", "attempt identity is invalid", step_key=attempt.step.step_key
            )
        try:
            identity = expected.lstat()
            root = self.workflow_root.resolve(strict=True)
            resolved = expected.resolve(strict=True)
        except OSError:
            raise ResultServiceError(
                "attempt_path_invalid", "attempt identity is invalid", step_key=attempt.step.step_key
            ) from None
        if stat.S_ISLNK(identity.st_mode) or not stat.S_ISDIR(identity.st_mode) or root not in resolved.parents:
            raise ResultServiceError(
                "attempt_path_invalid", "attempt identity is invalid", step_key=attempt.step.step_key
            )

    def _verify_row(self, row: WorkflowFile) -> VerifiedArtifact:
        relative = PurePosixPath(row.relative_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or "\\" in row.relative_path
            or "\x00" in row.relative_path
            or relative.as_posix() != row.relative_path
        ):
            raise ResultServiceError("artifact_path_invalid", "artifact path is invalid")
        candidate = self.workflow_root.joinpath(*relative.parts)
        try:
            root_identity = self.workflow_root.lstat()
            root = self.workflow_root.resolve(strict=True)
            current = self.workflow_root
            for part in relative.parts:
                current = current / part
                identity = current.lstat()
                if stat.S_ISLNK(identity.st_mode):
                    raise ResultServiceError("artifact_path_invalid", "artifact path is invalid")
            resolved = candidate.resolve(strict=True)
            identity = candidate.lstat()
        except ResultServiceError:
            raise
        except OSError:
            raise ResultServiceError("artifact_missing", "artifact is unavailable") from None
        if (
            stat.S_ISLNK(root_identity.st_mode)
            or not stat.S_ISDIR(root_identity.st_mode)
            or root not in resolved.parents
            or not stat.S_ISREG(identity.st_mode)
        ):
            raise ResultServiceError("artifact_path_invalid", "artifact path is invalid")
        if identity.st_size != row.size_bytes:
            raise ResultServiceError("artifact_hash_mismatch", "artifact changed")
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with candidate.open("rb") as handle:
                while chunk := handle.read(_HASH_CHUNK_BYTES):
                    size_bytes += len(chunk)
                    digest.update(chunk)
        except OSError:
            raise ResultServiceError("artifact_read_failed", "artifact is unavailable") from None
        if size_bytes != row.size_bytes or digest.hexdigest() != row.sha256:
            raise ResultServiceError("artifact_hash_mismatch", "artifact changed")
        metadata = _metadata(row.metadata_json)
        return VerifiedArtifact(
            path=candidate,
            relative_path=relative.as_posix(),
            logical_path=str(metadata.get("logical_path") or candidate.name),
            sha256=row.sha256,
            size_bytes=row.size_bytes,
            attempt_id=row.attempt_id,
            step_key=metadata.get("step_key"),
        )

    def _source_for(self, run: WorkflowRun, attempt: WorkflowAttempt, logical_path: str) -> VerifiedArtifact:
        expected_relative = f"{run.id}/attempts/{attempt.id}/{logical_path}"
        matches = []
        for row in run.files:
            metadata = _metadata(row.metadata_json)
            if row.attempt_id == attempt.id and metadata.get("logical_path") == logical_path:
                matches.append(row)
        if len(matches) != 1:
            raise ResultServiceError(
                "artifact_missing",
                "required result artifact is unavailable",
                step_key=attempt.step.step_key,
                missing_files=(logical_path,),
            )
        row = matches[0]
        metadata = _metadata(row.metadata_json)
        if (
            row.relative_path != expected_relative
            or row.source_kind != "attempt_output"
            or metadata.get("accepted") is not True
            or metadata.get("step_key") != attempt.step.step_key
            or metadata.get("release_commit") != run.release_commit
        ):
            raise ResultServiceError(
                "artifact_path_invalid", "result artifact identity is invalid", step_key=attempt.step.step_key
            )
        try:
            return self._verify_row(row)
        except ResultServiceError as exc:
            raise ResultServiceError(
                exc.code,
                str(exc),
                step_key=attempt.step.step_key,
                missing_files=(logical_path,) if exc.code == "artifact_missing" else (),
            ) from None

    def _success_context(self, run: WorkflowRun) -> tuple[dict[str, WorkflowAttempt], dict[str, VerifiedArtifact]]:
        if run.status != "succeeded":
            raise ResultServiceError("result_not_successful", "workflow is not successful")
        steps = sorted(run.steps, key=lambda item: item.position)
        if [step.step_key for step in steps] != list(FIXED_STEPS) or [step.position for step in steps] != list(range(4)):
            raise ResultServiceError("result_contract_invalid", "workflow result is incomplete")
        attempts = {}
        for step in steps:
            attempt = _latest_attempt(step)
            if step.status != "succeeded" or attempt is None:
                raise ResultServiceError(
                    "result_contract_invalid", "workflow result is incomplete", step_key=step.step_key
                )
            self._validate_attempt_directory(run, attempt)
            self._safe_scheduler(attempt)
            acceptance = self._safe_acceptance(attempt)
            if acceptance.get("accepted") is not True:
                raise ResultServiceError(
                    "result_contract_invalid", "workflow result is incomplete", step_key=step.step_key
                )
            attempts[step.step_key] = attempt
        sources = {
            "relax": self._source_for(run, attempts["relax"], "CONTCAR"),
            "scf": self._source_for(run, attempts["scf"], "vasprun.xml"),
            "band": self._source_for(run, attempts["band"], "vasprun.xml"),
            "dos": self._source_for(run, attempts["dos"], "vasprun.xml"),
        }
        return attempts, sources

    def _step_payload(self, step: WorkflowStep) -> dict[str, Any]:
        attempt = _latest_attempt(step)
        observation = {}
        acceptance = None
        if attempt is not None:
            metadata = _metadata(attempt.metadata_json)
            raw_observation = metadata.get("scheduler_observation")
            observation = raw_observation if isinstance(raw_observation, dict) else {}
            try:
                acceptance = self._safe_acceptance(attempt)
            except ResultServiceError:
                acceptance = None
        return {
            "key": step.step_key,
            "status": "failed" if step.status == "scientific_failed" else step.status,
            "job_id": attempt.slurm_job_id if attempt is not None else None,
            "attempt": attempt.attempt_number if attempt is not None else 0,
            "attempt_id": attempt.id if attempt is not None else None,
            "attempt_dir": (
                f"{step.workflow_id}/attempts/{attempt.id}" if attempt is not None else None
            ),
            "slurm_state": observation.get("raw_state"),
            "exit_code": observation.get("exit_code"),
            "reason": (
                acceptance.get("reason_code") if acceptance is not None else observation.get("error_code")
            ),
            "accepted": acceptance.get("accepted") if acceptance is not None else None,
            "resources": acceptance.get("measurements", {}) if acceptance is not None else {},
            "updated_at": _timestamp(attempt.updated_at if attempt is not None else step.updated_at),
        }

    def _base_payload(self, run: WorkflowRun) -> dict[str, Any]:
        steps = sorted(run.steps, key=lambda item: item.position)
        attempts = [(step, _latest_attempt(step)) for step in steps]
        attempts = [(step, attempt) for step, attempt in attempts if attempt is not None]
        latest = max(attempts, key=lambda item: item[1].updated_at, default=None)
        current_step = "done" if run.status == "succeeded" else latest[0].step_key if latest else None
        return {
            "id": run.id,
            "workflow_id": run.id,
            "material": run.material,
            "formula": run.material,
            "source": _source_label(run.source_kind),
            "status": run.status,
            "current_step": current_step,
            "latest_job_id": latest[1].slurm_job_id if latest is not None else None,
            "updated_at": _timestamp(run.updated_at),
            "completed_at": _timestamp(run.updated_at),
            "creator": run.owner.alias or run.owner.name,
            "template_version": run.template_version,
            "input_sha256": run.input_sha256,
            "release_commit": run.release_commit,
            "data_kind": "live",
            "steps": [self._step_payload(step) for step in steps],
        }

    def _failure_payload(
        self, run: WorkflowRun, error: ResultServiceError | None = None
    ) -> dict[str, Any]:
        payload = self._base_payload(run)
        failed_step = next(
            (step for step in sorted(run.steps, key=lambda item: item.position) if step.status in {"scientific_failed", "failed"}),
            None,
        )
        if error is not None and error.step_key:
            failed_step = next((step for step in run.steps if step.step_key == error.step_key), failed_step)
        attempt = _latest_attempt(failed_step) if failed_step is not None else None
        observation = _metadata(attempt.metadata_json).get("scheduler_observation", {}) if attempt else {}
        observation = observation if isinstance(observation, dict) else {}
        acceptance = None
        if attempt is not None:
            try:
                acceptance = self._safe_acceptance(attempt)
            except ResultServiceError:
                acceptance = None
        reason = error.code if error is not None else None
        if reason is None and acceptance is not None:
            reason = acceptance.get("reason_code")
        reason = reason or observation.get("error_code") or "workflow_failed"
        expected_files = []
        if acceptance is not None:
            expected_files = [artifact["name"] for artifact in acceptance.get("artifacts", [])]
        if not expected_files:
            expected_files = list(error.missing_files) if error is not None else ["OUTCAR"]
        payload["status"] = "parse-error" if error is not None else "failed"
        payload["artifacts"] = ["evidence-bundle"]
        payload["failure_evidence"] = {
            "step": error.step_key if error is not None and error.step_key else failed_step.step_key if failed_step else "relax",
            "job_id": attempt.slurm_job_id if attempt is not None else "unavailable",
            "exit_code": observation.get("exit_code") or "unavailable",
            "reason": reason,
            "expected_files": expected_files,
            "missing_files": list(error.missing_files) if error is not None else [],
            "log_tail": [
                f"scientific_acceptance: {reason}",
                f"slurm: {observation.get('raw_state') or 'unavailable'}/{observation.get('exit_code') or 'unavailable'}",
            ],
            "data_kind": "live",
        }
        return payload

    @staticmethod
    def _provenance(sources: Mapping[str, VerifiedArtifact]) -> dict[str, Any]:
        return {
            key: {
                "attempt_id": source.attempt_id,
                "relative_path": source.relative_path,
                "logical_path": source.logical_path,
                "size_bytes": source.size_bytes,
                "sha256": source.sha256,
            }
            for key, source in sources.items()
        }

    @staticmethod
    def _validate_detail_contract(detail: Any) -> None:
        if not isinstance(detail, dict):
            raise ResultServiceError(
                "scientific_contract_invalid", "scientific result is incomplete"
            )
        row = detail.get("row")
        properties = detail.get("properties")
        structure = detail.get("structure")
        crystal = detail.get("crystal")
        capabilities = detail.get("capabilities")
        if not all(isinstance(value, dict) for value in (row, properties, structure, crystal, capabilities)):
            raise ResultServiceError(
                "scientific_contract_invalid", "scientific result is incomplete"
            )
        symbols = structure.get("symbols")
        positions = structure.get("positions")
        cell = structure.get("cell")
        pbc = structure.get("pbc")
        is_vector = lambda value: (
            isinstance(value, list)
            and len(value) == 3
            and all(type(item) in {int, float} and math.isfinite(item) for item in value)
        )
        natoms = row.get("natoms")
        lattice = crystal.get("lattice")
        coordinates = crystal.get("atomic_positions_frac")
        numeric_properties = ("bandgap_eV", "vbm_eV", "cbm_eV")
        row_pbc = row.get("pbc")
        row_numbers = ("energy", "fmax")
        if (
            not isinstance(detail.get("db"), dict)
            or not isinstance(detail["db"].get("dbname"), str)
            or not detail["db"]["dbname"]
            or not isinstance(row.get("id"), (str, int))
            or not isinstance(row.get("formula"), str)
            or not row["formula"]
            or type(natoms) is not int
            or natoms <= 0
            or not isinstance(row_pbc, list)
            or len(row_pbc) != 3
            or not all(type(value) is bool for value in row_pbc)
            or not all(
                key in row
                and (
                    row[key] is None
                    or (type(row[key]) in {int, float} and math.isfinite(row[key]))
                )
                for key in row_numbers
            )
            or not isinstance(symbols, list)
            or len(symbols) != natoms
            or not all(isinstance(symbol, str) and symbol for symbol in symbols)
            or not isinstance(positions, list)
            or len(positions) != natoms
            or not all(is_vector(value) for value in positions)
            or not isinstance(cell, list)
            or len(cell) != 3
            or not all(is_vector(value) for value in cell)
            or not isinstance(pbc, list)
            or len(pbc) != 3
            or not all(type(value) is bool for value in pbc)
            or not isinstance(lattice, dict)
            or not all(
                type(lattice.get(key)) in {int, float} and math.isfinite(lattice[key])
                for key in ("a", "b", "c", "alpha", "beta", "gamma", "volume")
            )
            or min(lattice["a"], lattice["b"], lattice["c"], lattice["volume"]) <= 0
            or not all(0 < lattice[key] <= 180 for key in ("alpha", "beta", "gamma"))
            or not isinstance(coordinates, list)
            or len(coordinates) != natoms
            or not all(
                isinstance(value, dict)
                and isinstance(value.get("element"), str)
                and all(
                    type(value.get(key)) in {int, float} and math.isfinite(value[key])
                    for key in ("x", "y", "z")
                )
                for value in coordinates
            )
            or type(crystal.get("density_g_cm3")) not in {int, float}
            or not math.isfinite(crystal["density_g_cm3"])
            or crystal["density_g_cm3"] <= 0
            or type(crystal.get("dimensionality")) is not int
            or not 0 <= crystal["dimensionality"] <= 3
            or not all(key in properties for key in ("spacegroup", *numeric_properties))
            or not all(
                properties.get(key) is None
                or (
                    type(properties.get(key)) in {int, float}
                    and math.isfinite(properties[key])
                )
                for key in numeric_properties
            )
            or properties.get("spacegroup") is not None
            and not isinstance(properties.get("spacegroup"), str)
            or not all(
                capabilities.get(key) is True
                for key in ("structure_export", "band_plot", "dos_plot", "band_data", "dos_data")
            )
        ):
            raise ResultServiceError(
                "scientific_contract_invalid", "scientific result is incomplete"
            )

    def summary(self, run: WorkflowRun) -> dict[str, Any]:
        if run.status == "succeeded":
            detail = self.detail(run)
            if detail.get("status") == "parse-error":
                return detail
            return self._base_payload(run)
        if run.status == "failed":
            return self._failure_payload(run)
        raise ResultServiceError("result_not_terminal", "workflow result is not terminal")

    def detail(self, run: WorkflowRun) -> dict[str, Any]:
        if run.status == "failed":
            return self._failure_payload(run)
        try:
            _, sources = self._success_context(run)
            detail = self.parser.build_detail(run.id, sources)
            canonical_json(detail)
            self._validate_detail_contract(detail)
            for source in sources.values():
                self._verify_source_unchanged(source)
        except ResultServiceError as error:
            return self._failure_payload(run, error)
        except Exception:
            return self._failure_payload(
                run, ResultServiceError("scientific_parse_failed", "scientific result could not be parsed")
            )
        payload = self._base_payload(run)
        detail["provenance"] = self._provenance(sources)
        detail["data_kind"] = "live"
        payload["vasp_detail"] = detail
        payload["artifacts"] = [
            "structure-cif",
            "structure-poscar",
            "band-data",
            "dos-data",
            "evidence-bundle",
        ]
        return payload

    def _verify_source_unchanged(self, source: VerifiedArtifact) -> None:
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with source.path.open("rb") as handle:
                while chunk := handle.read(_HASH_CHUNK_BYTES):
                    size_bytes += len(chunk)
                    digest.update(chunk)
        except OSError:
            raise ResultServiceError("artifact_read_failed", "artifact is unavailable") from None
        if size_bytes != source.size_bytes or digest.hexdigest() != source.sha256:
            raise ResultServiceError("artifact_hash_mismatch", "artifact changed", step_key=source.step_key)

    def plot(self, run: WorkflowRun, kind: str) -> dict[str, Any]:
        if kind not in {"band", "dos"}:
            raise ResultServiceError("plot_kind_invalid", "plot kind is invalid")
        _, sources = self._success_context(run)
        try:
            value = self.parser.render_plot(kind, sources[kind])
            self._verify_source_unchanged(sources[kind])
        except ResultServiceError:
            raise
        except Exception:
            raise ResultServiceError("scientific_parse_failed", "scientific plot could not be parsed") from None
        if not isinstance(value, str) or not value:
            raise ResultServiceError("scientific_parse_failed", "scientific plot could not be parsed")
        return {
            "ok": True,
            "workflow_id": run.id,
            "image_base64": value,
            "data_kind": "live",
            "provenance": self._provenance({kind: sources[kind]})[kind],
        }

    def artifact(self, session: Session, run: WorkflowRun, kind: str) -> ResultArtifact:
        if kind not in RESULT_ARTIFACT_KINDS:
            raise ResultServiceError("artifact_kind_invalid", "artifact kind is invalid")
        sources: dict[str, VerifiedArtifact] = {}
        if run.status == "succeeded":
            _, sources = self._success_context(run)
        elif run.status != "failed":
            raise ResultServiceError("result_not_terminal", "workflow result is not terminal")
        if kind == "evidence-bundle":
            try:
                content = build_evidence_bundle(
                    session,
                    run,
                    releases_root=self.releases_root,
                    verify_file=self._verify_row,
                    provenance=self._provenance(sources),
                )
            except BundleError as error:
                raise ResultServiceError(error.code, str(error)) from None
            return ResultArtifact(
                content=content,
                filename=f"{run.id}-evidence-bundle.json",
                media_type="application/json",
            )
        if run.status != "succeeded":
            raise ResultServiceError("artifact_unavailable", "scientific artifact is unavailable")
        try:
            content = self.parser.export_artifact(kind, sources)
            for source in sources.values():
                self._verify_source_unchanged(source)
        except ResultServiceError:
            raise
        except Exception:
            raise ResultServiceError("scientific_parse_failed", "scientific artifact could not be parsed") from None
        if not isinstance(content, bytes) or not content:
            raise ResultServiceError("scientific_parse_failed", "scientific artifact could not be parsed")
        specs = {
            "structure-cif": (f"{run.id}.cif", "chemical/x-cif; charset=utf-8"),
            "structure-poscar": (f"{run.id}.vasp", "text/plain; charset=utf-8"),
            "band-data": (f"{run.id}-band.dat", "text/plain; charset=utf-8"),
            "dos-data": (f"{run.id}-dos-data.zip", "application/zip"),
        }
        filename, media_type = specs[kind]
        return ResultArtifact(content=content, filename=filename, media_type=media_type)

    def database_record(self, run: WorkflowRun) -> dict[str, Any]:
        detail = self.detail(run)
        scientific = detail.get("vasp_detail")
        try:
            from ase.formula import Formula

            formula_elements = list(Formula(run.material).count())
        except Exception:
            formula_elements = []
        if not isinstance(scientific, dict):
            scientific = {
                "db": {"dbname": "107 Cup workflow results"},
                "row": {
                    "id": run.id,
                    "formula": run.material,
                    "energy": None,
                    "fmax": None,
                    "natoms": 0,
                    "pbc": [True, True, True],
                },
                "properties": {"spacegroup": None, "bandgap_eV": None, "vbm_eV": None, "cbm_eV": None},
                "structure": {"symbols": [], "positions": [], "cell": [], "pbc": [True, True, True]},
                "crystal": {"lattice": {}, "density_g_cm3": None, "dimensionality": 0, "atomic_positions_frac": []},
                "capabilities": {
                    "structure_export": False,
                    "band_plot": False,
                    "dos_plot": False,
                    "band_data": False,
                    "dos_data": False,
                },
                "data_kind": "live",
            }
        properties = scientific.get("properties", {})
        row = scientific.get("row", {})
        structure = scientific.get("structure", {})
        return {
            "id": run.id,
            "formula": str(row.get("formula") or run.material),
            "elements": list(dict.fromkeys(structure.get("symbols", []))) or formula_elements,
            "source": _source_label(run.source_kind),
            "workflow_id": run.id,
            "status": detail["status"],
            "bandgap_eV": properties.get("bandgap_eV"),
            "energy": row.get("energy"),
            "completed_at": _timestamp(run.updated_at),
            "latest_job_id": detail.get("latest_job_id"),
            "data_kind": "live",
            "vasp_detail": scientific,
            "artifacts": detail.get("artifacts", ["evidence-bundle"] if run.status == "failed" else []),
        }
