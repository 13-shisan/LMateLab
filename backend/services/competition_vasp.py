from __future__ import annotations

import hashlib
import math
import os
import re
import stat
import xml.etree.ElementTree as ElementTree
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from types import MappingProxyType
from typing import BinaryIO, Callable, Final


FIXED_STAGE_ORDER: Final = ("relax", "scf", "band", "dos")
STAGE_REQUIRED_OUTPUTS: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType({
    "relax": ("OUTCAR", "vasprun.xml", "OSZICAR", "CONTCAR"),
    "scf": ("OUTCAR", "vasprun.xml", "CHGCAR", "WAVECAR"),
    "band": ("OUTCAR", "vasprun.xml", "EIGENVAL"),
    "dos": ("OUTCAR", "vasprun.xml", "DOSCAR"),
})

_REQUIRED_FILES: Final = (
    "POTCAR.spec",
    "POTCAR",
    "vaspkit-version.txt",
    "potcar-source-sha256.txt",
)
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_SYMBOL_RE: Final = re.compile(r"^[A-Za-z0-9_]+$")
_VERSION_RE: Final = re.compile(r"(?<![0-9.])(\d+\.\d+\.\d+)(?![0-9.])")
_VASPKIT_BANNER_RE: Final = re.compile(
    r"^VASPKIT Standard Edition (?P<version>\d+\.\d+\.\d+)$"
)
_MAX_METADATA_BYTES: Final = 8192
_MAX_TITLE_LINE_BYTES: Final = 4096
_HASH_CHUNK_BYTES: Final = 64 * 1024
_MAX_ACCEPTANCE_OUTPUT_BYTES: Final = 2 * 1024 * 1024 * 1024
_MAX_ACCEPTANCE_TEXT_BYTES: Final = 64 * 1024 * 1024
_MAX_OUTPUT_LINE_BYTES: Final = 64 * 1024
_OUTCAR_COMPLETION_MARKER: Final = (
    b" General timing and accounting informations for this job:"
)
_OUTCAR_VERSION_RE: Final = re.compile(
    rb"^\s*vasp\.(?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)"
)
_RUNTIME_ELAPSED_RE: Final = re.compile(
    r"^\s*Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*(?P<value>\S+)\s*$"
)
_RUNTIME_RSS_RE: Final = re.compile(
    r"^\s*Maximum resident set size \(kbytes\):\s*(?P<value>\S+)\s*$"
)
_INCAR_NEDOS_RE: Final = re.compile(r"^\s*NEDOS\s*=\s*(?P<value>\S+)\s*$")
_BAND_KPOINTS_SHA256: Final = (
    "70415ce261ae121768664a9e2477c418846a1fbe9799209030f25f9cdccd778c"
)
_DOS_KPOINTS_SHA256: Final = (
    "97e52b91d674b9d4ca7dc81c0fcb5ec5af614c71ec5317e13489ecb62298e1b8"
)
_COMMON_ACCEPTANCE_EVIDENCE: Final = (
    "vasp-exit-code.txt",
    "runtime-time.txt",
    "vaspkit-version.txt",
)
_POTCAR_ACCEPTANCE_EVIDENCE: Final = (
    "POTCAR.spec",
    "POTCAR",
    "potcar-source-sha256.txt",
)
_O_BINARY: Final = getattr(os, "O_BINARY", 0)
_O_CLOEXEC: Final = getattr(os, "O_CLOEXEC", 0)
_O_NONBLOCK: Final = getattr(os, "O_NONBLOCK", 0)
_O_NOFOLLOW: Final = getattr(os, "O_NOFOLLOW", 0)
_O_DIRECTORY: Final = getattr(os, "O_DIRECTORY", 0)
_HAS_SECURE_DIR_FD: Final = bool(
    _O_NOFOLLOW and _O_DIRECTORY and os.open in getattr(os, "supports_dir_fd", set())
)


class VaspPolicyError(RuntimeError):
    """A stable, non-disclosing VASP policy rejection."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _deep_freeze(value: object) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError("canonical mappings require string keys")
        frozen = {key: _deep_freeze(value[key]) for key in sorted(value)}
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item) for item in value)
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("value is outside the canonical JSON domain")


def _deep_thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _deep_thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_deep_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class AcceptanceReport:
    accepted: bool
    reason_code: str | None
    checks: tuple[Mapping[str, object], ...]
    measurements: Mapping[str, object]
    artifacts: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise ValueError("accepted must be boolean")
        frozen_checks = _deep_freeze(self.checks)
        frozen_measurements = _deep_freeze(self.measurements)
        frozen_artifacts = _deep_freeze(self.artifacts)
        if not isinstance(frozen_checks, tuple) or not all(
            isinstance(check, Mapping) for check in frozen_checks
        ):
            raise ValueError("checks must be a sequence of mappings")
        if not isinstance(frozen_measurements, Mapping):
            raise ValueError("measurements must be a mapping")
        if not isinstance(frozen_artifacts, tuple) or not all(
            isinstance(artifact, Mapping) for artifact in frozen_artifacts
        ):
            raise ValueError("artifacts must be a sequence of mappings")
        failed_checks = [check for check in frozen_checks if check.get("passed") is False]
        if self.accepted:
            if self.reason_code is not None or failed_checks:
                raise ValueError("accepted reports cannot contain failures")
        elif (
            not isinstance(self.reason_code, str)
            or not self.reason_code
            or not frozen_checks
            or not failed_checks
        ):
            raise ValueError("failed reports require a reason and failed check")
        object.__setattr__(self, "checks", frozen_checks)
        object.__setattr__(self, "measurements", frozen_measurements)
        object.__setattr__(self, "artifacts", frozen_artifacts)

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "reason_code": self.reason_code,
            "checks": _deep_thaw(self.checks),
            "measurements": _deep_thaw(self.measurements),
            "artifacts": _deep_thaw(self.artifacts),
        }


@dataclass(frozen=True)
class PotcarContract:
    symbols: tuple[str, ...]
    titles: tuple[str, ...]
    source_sha256: tuple[str, ...]
    combined_sha256: str
    vaspkit_version: str

    def __post_init__(self) -> None:
        for field_name in ("symbols", "titles", "source_sha256"):
            object.__setattr__(self, field_name, _owned_string_tuple(field_name, getattr(self, field_name)))
        expected_count = len(self.symbols)
        if expected_count == 0 or any(
            len(values) != expected_count
            for values in (self.titles, self.source_sha256)
        ):
            raise ValueError("POTCAR contract entries must have equal nonzero lengths")
        if any(not _SYMBOL_RE.fullmatch(symbol) for symbol in self.symbols):
            raise ValueError("POTCAR contract symbols are invalid")
        if any(not title or "\n" in title or "\r" in title for title in self.titles):
            raise ValueError("POTCAR contract titles are invalid")
        if any(not _SHA256_RE.fullmatch(digest) for digest in self.source_sha256):
            raise ValueError("POTCAR source SHA-256 values are invalid")
        if not isinstance(self.combined_sha256, str) or not _SHA256_RE.fullmatch(self.combined_sha256):
            raise ValueError("POTCAR combined SHA-256 is invalid")
        if not isinstance(self.vaspkit_version, str) or not _VERSION_RE.fullmatch(self.vaspkit_version):
            raise ValueError("VASPKIT version is invalid")


def _owned_string_tuple(field_name: str, value: object) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"POTCAR contract {field_name} must be a sequence of strings")
    owned = tuple(value)
    if any(not isinstance(item, str) for item in owned):
        raise ValueError(f"POTCAR contract {field_name} must be a sequence of strings")
    return owned


@dataclass(frozen=True)
class _OpenedEvidence:
    handle: BinaryIO
    size_bytes: int


@dataclass(frozen=True)
class _OpenedAcceptanceEvidence:
    name: str
    path: Path
    handle: BinaryIO
    identity: os.stat_result
    path_identity: os.stat_result
    maximum_bytes: int


DEFAULT_POTCAR_CONTRACT = PotcarContract(
    symbols=("Mo_sv", "S"),
    titles=("PAW_PBE Mo_sv", "PAW_PBE S"),
    source_sha256=(
        "2731df97e41766cc617548c5a8267718fdef1f509ac6bafa01e745abea2bdfaa",
        "0fc7481fb0695f01bdc6462160264c5c84044ae9ec85a907d398b887a2bc3132",
    ),
    combined_sha256="509d41b6c93c3d7495d976f7a04dcf3f6960cfc94f39f13a67d146a7ded33045",
    vaspkit_version="1.5.1",
)


def validate_potcar(
    attempt_directory: Path,
    *,
    contract: PotcarContract = DEFAULT_POTCAR_CONTRACT,
) -> dict[str, object]:
    """Validate fixed POTCAR evidence without returning source material or paths."""
    root = Path(attempt_directory)
    root_identity = _validate_attempt_directory(root)
    with ExitStack() as resources:
        directory_fd = _open_attempt_directory(root, root_identity, resources)
        files = {
            name: _open_required_file(root, name, directory_fd, resources)
            for name in _REQUIRED_FILES
        }
        if directory_fd is None:
            _verify_attempt_directory_identity(root, root_identity)

        expected_spec = b"".join(symbol.encode("ascii") + b"\n" for symbol in contract.symbols)
        if _read_metadata(files["POTCAR.spec"].handle) != expected_spec:
            raise VaspPolicyError(
                "potcar_spec_invalid", "POTCAR specification does not match policy"
            )

        evidence = _read_metadata(files["potcar-source-sha256.txt"].handle)
        expected_evidence = b"".join(
            digest.encode("ascii") + b"  " + symbol.encode("ascii") + b"\n"
            for digest, symbol in zip(contract.source_sha256, contract.symbols, strict=True)
        )
        if evidence != expected_evidence:
            raise VaspPolicyError(
                "potcar_source_evidence_invalid",
                "POTCAR source checksum evidence does not match policy",
            )

        vaspkit_text = _decode_metadata(_read_metadata(files["vaspkit-version.txt"].handle))
        _validate_vaspkit_banner(vaspkit_text, contract.vaspkit_version)

        potcar = files["POTCAR"]
        if potcar.size_bytes == 0:
            raise VaspPolicyError("potcar_empty", "POTCAR is empty")
        titles = _extract_titles(potcar.handle, contract.titles)
        if titles != list(contract.titles):
            raise VaspPolicyError("potcar_titles_invalid", "POTCAR titles do not match policy")
        _rewind(potcar.handle)
        digest = _sha256_file(potcar.handle)
        if digest != contract.combined_sha256:
            raise VaspPolicyError("potcar_sha256_mismatch", "POTCAR checksum does not match policy")

        return {
            "sha256": digest,
            "titles": list(contract.titles),
            "symbols": list(contract.symbols),
            "source_sha256": list(contract.source_sha256),
            "vaspkit_version": contract.vaspkit_version,
            "size_bytes": potcar.size_bytes,
        }


def _default_vasprun_loader(path: Path) -> object:
    from pymatgen.io.vasp.outputs import Vasprun

    return Vasprun(
        path,
        parse_dos=False,
        parse_eigen=False,
        parse_projected_eigen=False,
    )


def _default_structure_loader(path: Path) -> object:
    from pymatgen.core import Structure

    return Structure.from_file(path)


def _acceptance_report(
    *,
    accepted: bool,
    reason_code: str | None,
    checks: list[dict[str, object]],
    measurements: dict[str, object],
    artifacts: list[dict[str, object]],
) -> AcceptanceReport:
    return AcceptanceReport(
        accepted=accepted,
        reason_code=reason_code,
        checks=checks,
        measurements=measurements,
        artifacts=artifacts,
    )


def _failed_acceptance(
    *,
    check_name: str,
    reason_code: str,
    checks: list[dict[str, object]],
    measurements: dict[str, object],
    artifacts: list[dict[str, object]],
) -> AcceptanceReport:
    checks.append({"name": check_name, "passed": False})
    return _acceptance_report(
        accepted=False,
        reason_code=reason_code,
        checks=checks,
        measurements=measurements,
        artifacts=artifacts,
    )


def _passed_check(checks: list[dict[str, object]], name: str) -> None:
    checks.append({"name": name, "passed": True})


def _acceptance_evidence_names(stage: str) -> tuple[str, ...]:
    names = set(STAGE_REQUIRED_OUTPUTS[stage])
    names.update(_COMMON_ACCEPTANCE_EVIDENCE)
    names.update(_POTCAR_ACCEPTANCE_EVIDENCE)
    if stage == "band":
        names.add("KPOINTS")
    elif stage == "dos":
        names.update(("INCAR", "KPOINTS"))
    return tuple(sorted(names))


def _acceptance_size_limit(name: str) -> int:
    if name in {
        "INCAR",
        "KPOINTS",
        "POTCAR.spec",
        "potcar-source-sha256.txt",
        "runtime-time.txt",
        "vasp-exit-code.txt",
        "vaspkit-version.txt",
    }:
        return _MAX_METADATA_BYTES
    if name in {"CONTCAR", "OSZICAR", "OUTCAR"}:
        return _MAX_ACCEPTANCE_TEXT_BYTES
    return _MAX_ACCEPTANCE_OUTPUT_BYTES


def _private_evidence_mode(identity: os.stat_result) -> bool:
    return os.name == "nt" or not (stat.S_IMODE(identity.st_mode) & 0o077)


def _open_acceptance_evidence(
    root: Path,
    name: str,
    directory_fd: int | None,
    resources: ExitStack,
) -> _OpenedAcceptanceEvidence:
    path = root / name
    try:
        if directory_fd is None:
            before = path.lstat()
        else:
            before = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        raise VaspPolicyError("evidence_missing", "required evidence is unavailable") from None
    if stat.S_ISLNK(before.st_mode):
        raise VaspPolicyError("evidence_symlink", "required evidence must not be a symlink")
    if not stat.S_ISREG(before.st_mode):
        raise VaspPolicyError("evidence_nonregular", "required evidence must be a regular file")
    if not _private_evidence_mode(before):
        raise VaspPolicyError("evidence_not_private", "required evidence must be private")
    maximum = _acceptance_size_limit(name)
    if before.st_size == 0:
        raise VaspPolicyError("evidence_empty", "required evidence is empty")
    if before.st_size > maximum:
        raise VaspPolicyError("evidence_too_large", "required evidence exceeds the policy limit")

    descriptor: int | None = None
    flags = os.O_RDONLY | _O_BINARY | _O_CLOEXEC | _O_NONBLOCK | _O_NOFOLLOW
    try:
        if directory_fd is None:
            descriptor = os.open(path, flags)
        else:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened = os.fstat(descriptor)
    except OSError:
        _close_descriptor(descriptor)
        raise VaspPolicyError("evidence_open_failed", "required evidence could not be opened") from None
    if not stat.S_ISREG(opened.st_mode):
        _close_descriptor(descriptor)
        raise VaspPolicyError("evidence_nonregular", "required evidence must be a regular file")
    if not _same_file_identity(before, opened):
        _close_descriptor(descriptor)
        raise VaspPolicyError("evidence_changed", "required evidence changed while opening")
    if not _private_evidence_mode(opened):
        _close_descriptor(descriptor)
        raise VaspPolicyError("evidence_not_private", "required evidence must be private")
    if opened.st_size == 0:
        _close_descriptor(descriptor)
        raise VaspPolicyError("evidence_empty", "required evidence is empty")
    if opened.st_size > maximum:
        _close_descriptor(descriptor)
        raise VaspPolicyError("evidence_too_large", "required evidence exceeds the policy limit")
    try:
        handle = os.fdopen(descriptor, "rb", closefd=True)
    except OSError:
        _close_descriptor(descriptor)
        raise VaspPolicyError("evidence_open_failed", "required evidence could not be opened") from None
    resources.callback(_close_handle, handle)
    return _OpenedAcceptanceEvidence(
        name=name,
        path=path,
        handle=handle,
        identity=opened,
        path_identity=before,
        maximum_bytes=maximum,
    )


def _evidence_signature(identity: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        identity.st_dev,
        identity.st_ino,
        identity.st_mode,
        identity.st_size,
        identity.st_mtime_ns,
        identity.st_ctime_ns,
    )


def _verify_evidence_unchanged(opened: _OpenedAcceptanceEvidence) -> None:
    try:
        descriptor_identity = os.fstat(opened.handle.fileno())
        path_identity = opened.path.lstat()
    except OSError:
        raise VaspPolicyError("evidence_changed", "required evidence changed") from None
    if (
        stat.S_ISLNK(path_identity.st_mode)
        or not stat.S_ISREG(path_identity.st_mode)
        or not _same_file_identity(opened.identity, descriptor_identity)
        or not _same_file_identity(opened.identity, path_identity)
        or _evidence_signature(opened.identity) != _evidence_signature(descriptor_identity)
        or _evidence_signature(opened.path_identity) != _evidence_signature(path_identity)
    ):
        raise VaspPolicyError("evidence_changed", "required evidence changed")


def _rewind_acceptance(opened: _OpenedAcceptanceEvidence) -> None:
    try:
        opened.handle.seek(0)
    except OSError:
        raise VaspPolicyError("evidence_read_failed", "required evidence could not be read") from None


def _hash_opened_evidence(opened: _OpenedAcceptanceEvidence) -> dict[str, object]:
    _rewind_acceptance(opened)
    digest = hashlib.sha256()
    size_bytes = 0
    try:
        while chunk := opened.handle.read(_HASH_CHUNK_BYTES):
            size_bytes += len(chunk)
            if size_bytes > opened.maximum_bytes:
                raise VaspPolicyError(
                    "evidence_too_large", "required evidence exceeds the policy limit"
                )
            digest.update(chunk)
    except VaspPolicyError:
        raise
    except OSError:
        raise VaspPolicyError("evidence_read_failed", "required evidence could not be read") from None
    if size_bytes != opened.identity.st_size:
        raise VaspPolicyError("evidence_changed", "required evidence changed while reading")
    _verify_evidence_unchanged(opened)
    return {
        "name": opened.name,
        "sha256": digest.hexdigest(),
        "size_bytes": size_bytes,
    }


def _read_acceptance_metadata(opened: _OpenedAcceptanceEvidence) -> bytes:
    if opened.maximum_bytes != _MAX_METADATA_BYTES:
        raise VaspPolicyError("evidence_read_failed", "evidence is not bounded metadata")
    _rewind_acceptance(opened)
    try:
        content = opened.handle.read(_MAX_METADATA_BYTES + 1)
    except OSError:
        raise VaspPolicyError("evidence_read_failed", "required evidence could not be read") from None
    if len(content) > _MAX_METADATA_BYTES:
        raise VaspPolicyError("evidence_too_large", "required evidence exceeds the policy limit")
    if len(content) != opened.identity.st_size:
        raise VaspPolicyError("evidence_changed", "required evidence changed while reading")
    _verify_evidence_unchanged(opened)
    return content


def _parse_vasp_exit(content: bytes) -> int:
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError:
        raise VaspPolicyError("vasp_exit_invalid", "VASP exit evidence is invalid") from None
    lines = text.splitlines()
    if (
        len(lines) != 1
        or len(lines[0]) > 10
        or re.fullmatch(r"0|[1-9][0-9]*", lines[0]) is None
    ):
        raise VaspPolicyError("vasp_exit_invalid", "VASP exit evidence is invalid")
    return int(lines[0])


def _parse_runtime_evidence(content: bytes) -> tuple[float, int]:
    try:
        lines = content.decode("ascii").splitlines()
    except UnicodeDecodeError:
        raise VaspPolicyError("runtime_evidence_invalid", "runtime evidence is invalid") from None
    elapsed_candidates = [
        line for line in lines if line.lstrip().startswith("Elapsed (wall clock) time")
    ]
    rss_candidates = [
        line
        for line in lines
        if line.lstrip().startswith("Maximum resident set size (kbytes)")
    ]
    elapsed_matches = [
        match for line in elapsed_candidates if (match := _RUNTIME_ELAPSED_RE.fullmatch(line))
    ]
    rss_matches = [
        match for line in rss_candidates if (match := _RUNTIME_RSS_RE.fullmatch(line))
    ]
    if (
        len(elapsed_candidates) != 1
        or len(rss_candidates) != 1
        or len(elapsed_matches) != 1
        or len(rss_matches) != 1
    ):
        raise VaspPolicyError("runtime_evidence_invalid", "runtime evidence is invalid")
    elapsed = _parse_elapsed_wall_seconds(elapsed_matches[0].group("value"))
    rss_text = rss_matches[0].group("value")
    if len(rss_text) > 20 or re.fullmatch(r"0|[1-9][0-9]*", rss_text) is None:
        raise VaspPolicyError("runtime_evidence_invalid", "runtime evidence is invalid")
    return elapsed, int(rss_text)


def _parse_elapsed_wall_seconds(value: str) -> float:
    parts = value.split(":")
    if len(parts) not in (2, 3):
        raise VaspPolicyError("runtime_evidence_invalid", "runtime evidence is invalid")
    if any(
        len(part) > 12 or re.fullmatch(r"0|[1-9][0-9]*", part) is None
        for part in parts[:-1]
    ):
        raise VaspPolicyError("runtime_evidence_invalid", "runtime evidence is invalid")
    try:
        seconds = float(parts[-1])
    except ValueError:
        raise VaspPolicyError("runtime_evidence_invalid", "runtime evidence is invalid") from None
    if not math.isfinite(seconds) or seconds < 0 or seconds >= 60:
        raise VaspPolicyError("runtime_evidence_invalid", "runtime evidence is invalid")
    if len(parts) == 2:
        return int(parts[0]) * 60 + seconds
    minutes = int(parts[1])
    if minutes >= 60:
        raise VaspPolicyError("runtime_evidence_invalid", "runtime evidence is invalid")
    return int(parts[0]) * 3600 + minutes * 60 + seconds


def _parse_outcar(opened: _OpenedAcceptanceEvidence) -> str:
    _rewind_acceptance(opened)
    marker_count = 0
    version_candidates = 0
    versions: list[str] = []
    size_bytes = 0
    try:
        while line := opened.handle.readline(_MAX_OUTPUT_LINE_BYTES + 1):
            size_bytes += len(line)
            if len(line) > _MAX_OUTPUT_LINE_BYTES or size_bytes > opened.maximum_bytes:
                raise VaspPolicyError("outcar_invalid", "OUTCAR evidence is invalid")
            stripped = line.rstrip(b"\r\n")
            if stripped == _OUTCAR_COMPLETION_MARKER:
                marker_count += 1
            if stripped.lstrip().startswith(b"vasp."):
                version_candidates += 1
            if match := _OUTCAR_VERSION_RE.match(stripped):
                versions.append(match.group("version").decode("ascii"))
    except VaspPolicyError:
        raise
    except OSError:
        raise VaspPolicyError("evidence_read_failed", "OUTCAR evidence could not be read") from None
    if size_bytes != opened.identity.st_size:
        raise VaspPolicyError("evidence_changed", "OUTCAR evidence changed while reading")
    _verify_evidence_unchanged(opened)
    if marker_count != 1:
        raise VaspPolicyError("outcar_incomplete", "OUTCAR completion marker is absent")
    if version_candidates != 1 or len(versions) != 1:
        raise VaspPolicyError("outcar_version_invalid", "OUTCAR VASP version is invalid")
    return versions[0]


def _parse_vasprun_xml(opened: _OpenedAcceptanceEvidence) -> None:
    _rewind_acceptance(opened)
    try:
        ElementTree.parse(opened.handle)
    except (ElementTree.ParseError, OSError, ValueError):
        raise VaspPolicyError("vasprun_unparseable", "vasprun.xml is incomplete or invalid") from None
    _verify_evidence_unchanged(opened)


def _load_vasprun(
    opened: _OpenedAcceptanceEvidence,
    loader: Callable[[Path], object],
) -> object:
    _verify_evidence_unchanged(opened)
    try:
        parsed = loader(opened.path)
    except Exception:
        raise VaspPolicyError("vasprun_unparseable", "vasprun.xml could not be parsed") from None
    _verify_evidence_unchanged(opened)
    return parsed


def _load_contcar(
    opened: _OpenedAcceptanceEvidence,
    loader: Callable[[Path], object],
) -> None:
    _verify_evidence_unchanged(opened)
    try:
        loader(opened.path)
    except Exception:
        raise VaspPolicyError("contcar_unparseable", "CONTCAR could not be parsed") from None
    _verify_evidence_unchanged(opened)


def _parse_nedos(content: bytes) -> int:
    try:
        lines = content.decode("ascii").splitlines()
    except UnicodeDecodeError:
        raise VaspPolicyError("dos_nedos_invalid", "DOS NEDOS input is invalid") from None
    candidates = [line for line in lines if line.lstrip().startswith("NEDOS")]
    matches = [match for line in candidates if (match := _INCAR_NEDOS_RE.fullmatch(line))]
    if len(candidates) != 1 or len(matches) != 1:
        raise VaspPolicyError("dos_nedos_invalid", "DOS NEDOS input is invalid")
    value = matches[0].group("value")
    if len(value) > 5 or re.fullmatch(r"0|[1-9][0-9]*", value) is None:
        raise VaspPolicyError("dos_nedos_invalid", "DOS NEDOS input is invalid")
    nedos = int(value)
    if not 100 <= nedos <= 10000:
        raise VaspPolicyError("dos_nedos_invalid", "DOS NEDOS input is outside policy")
    return nedos


def accept_vasp_attempt(
    attempt_directory: Path,
    stage: str,
    *,
    scheduler_state: str,
    scheduler_exit_code: str,
    vasprun_loader: Callable[[Path], object] | None = None,
    structure_loader: Callable[[Path], object] | None = None,
    potcar_contract: PotcarContract = DEFAULT_POTCAR_CONTRACT,
) -> AcceptanceReport:
    """Read and scientifically accept one fixed-stage VASP attempt."""
    checks: list[dict[str, object]] = []
    measurements: dict[str, object] = {}
    artifacts: list[dict[str, object]] = []

    if stage not in FIXED_STAGE_ORDER:
        return _failed_acceptance(
            check_name="stage", reason_code="stage_invalid", checks=checks,
            measurements=measurements, artifacts=artifacts,
        )
    _passed_check(checks, "stage")
    if scheduler_state != "COMPLETED":
        return _failed_acceptance(
            check_name="scheduler_state", reason_code="scheduler_state_not_completed",
            checks=checks, measurements=measurements, artifacts=artifacts,
        )
    _passed_check(checks, "scheduler_state")
    if scheduler_exit_code != "0:0":
        return _failed_acceptance(
            check_name="scheduler_exit_code", reason_code="scheduler_exit_code_nonzero",
            checks=checks, measurements=measurements, artifacts=artifacts,
        )
    _passed_check(checks, "scheduler_exit_code")

    root = Path(attempt_directory)
    try:
        root_identity = _validate_attempt_directory(root)
    except VaspPolicyError as error:
        return _failed_acceptance(
            check_name="attempt_directory", reason_code=error.code, checks=checks,
            measurements=measurements, artifacts=artifacts,
        )
    _passed_check(checks, "attempt_directory")

    with ExitStack() as resources:
        try:
            directory_fd = _open_attempt_directory(root, root_identity, resources)
        except VaspPolicyError as error:
            return _failed_acceptance(
                check_name="attempt_directory", reason_code=error.code, checks=checks,
                measurements=measurements, artifacts=artifacts,
            )
        opened_files: dict[str, _OpenedAcceptanceEvidence] = {}
        for name in _acceptance_evidence_names(stage):
            try:
                opened = _open_acceptance_evidence(root, name, directory_fd, resources)
                artifact = _hash_opened_evidence(opened)
                _verify_evidence_unchanged(opened)
            except VaspPolicyError as error:
                return _failed_acceptance(
                    check_name=f"artifact:{name}", reason_code=error.code, checks=checks,
                    measurements=measurements, artifacts=artifacts,
                )
            opened_files[name] = opened
            artifacts.append(artifact)
            _passed_check(checks, f"artifact:{name}")

        try:
            vasp_exit_code = _parse_vasp_exit(
                _read_acceptance_metadata(opened_files["vasp-exit-code.txt"])
            )
        except VaspPolicyError as error:
            return _failed_acceptance(
                check_name="vasp_exit_code", reason_code=error.code, checks=checks,
                measurements=measurements, artifacts=artifacts,
            )
        measurements["vasp_exit_code"] = vasp_exit_code
        if vasp_exit_code != 0:
            return _failed_acceptance(
                check_name="vasp_exit_code", reason_code="vasp_exit_nonzero", checks=checks,
                measurements=measurements, artifacts=artifacts,
            )
        _passed_check(checks, "vasp_exit_code")

        try:
            vaspkit_text = _decode_metadata(
                _read_acceptance_metadata(opened_files["vaspkit-version.txt"])
            )
            _validate_vaspkit_banner(vaspkit_text, potcar_contract.vaspkit_version)
        except VaspPolicyError as error:
            return _failed_acceptance(
                check_name="vaspkit_version", reason_code=error.code, checks=checks,
                measurements=measurements, artifacts=artifacts,
            )
        measurements["vaspkit_version"] = potcar_contract.vaspkit_version
        _passed_check(checks, "vaspkit_version")

        try:
            potcar_result = validate_potcar(root, contract=potcar_contract)
        except VaspPolicyError as error:
            return _failed_acceptance(
                check_name="potcar", reason_code=error.code, checks=checks,
                measurements=measurements, artifacts=artifacts,
            )
        potcar_artifact = next(item for item in artifacts if item["name"] == "POTCAR")
        if potcar_result["sha256"] != potcar_artifact["sha256"]:
            return _failed_acceptance(
                check_name="potcar", reason_code="evidence_changed", checks=checks,
                measurements=measurements, artifacts=artifacts,
            )
        _passed_check(checks, "potcar")

        try:
            elapsed_seconds, peak_rss_kbytes = _parse_runtime_evidence(
                _read_acceptance_metadata(opened_files["runtime-time.txt"])
            )
        except VaspPolicyError as error:
            return _failed_acceptance(
                check_name="runtime_evidence", reason_code=error.code, checks=checks,
                measurements=measurements, artifacts=artifacts,
            )
        measurements["elapsed_wall_seconds"] = elapsed_seconds
        measurements["process_tree_peak_rss_kbytes"] = peak_rss_kbytes
        _passed_check(checks, "runtime_evidence")

        try:
            vasp_version = _parse_outcar(opened_files["OUTCAR"])
        except VaspPolicyError as error:
            return _failed_acceptance(
                check_name="outcar", reason_code=error.code, checks=checks,
                measurements=measurements, artifacts=artifacts,
            )
        measurements["vasp_version"] = vasp_version
        _passed_check(checks, "outcar")

        try:
            _parse_vasprun_xml(opened_files["vasprun.xml"])
            vasprun = _load_vasprun(
                opened_files["vasprun.xml"], vasprun_loader or _default_vasprun_loader
            )
        except VaspPolicyError as error:
            return _failed_acceptance(
                check_name="vasprun", reason_code=error.code, checks=checks,
                measurements=measurements, artifacts=artifacts,
            )
        _passed_check(checks, "vasprun")

        if getattr(vasprun, "converged_electronic", None) is not True:
            return _failed_acceptance(
                check_name="electronic_convergence", reason_code="electronic_not_converged",
                checks=checks, measurements=measurements, artifacts=artifacts,
            )
        _passed_check(checks, "electronic_convergence")

        if stage == "relax":
            if getattr(vasprun, "converged_ionic", None) is not True:
                return _failed_acceptance(
                    check_name="ionic_convergence", reason_code="ionic_not_converged",
                    checks=checks, measurements=measurements, artifacts=artifacts,
                )
            _passed_check(checks, "ionic_convergence")
            try:
                _load_contcar(
                    opened_files["CONTCAR"], structure_loader or _default_structure_loader
                )
            except VaspPolicyError as error:
                return _failed_acceptance(
                    check_name="contcar", reason_code=error.code, checks=checks,
                    measurements=measurements, artifacts=artifacts,
                )
            _passed_check(checks, "contcar")

        if stage == "scf":
            efermi = getattr(vasprun, "efermi", None)
            if isinstance(efermi, bool) or not isinstance(efermi, Real) or not math.isfinite(float(efermi)):
                return _failed_acceptance(
                    check_name="scf_efermi", reason_code="scf_efermi_invalid", checks=checks,
                    measurements=measurements, artifacts=artifacts,
                )
            measurements["efermi_ev"] = float(efermi)
            _passed_check(checks, "scf_efermi")

        if stage == "band":
            kpoints = next(item for item in artifacts if item["name"] == "KPOINTS")
            measurements["kpoints_sha256"] = kpoints["sha256"]
            if kpoints["sha256"] != _BAND_KPOINTS_SHA256:
                return _failed_acceptance(
                    check_name="band_kpoints", reason_code="band_kpoints_invalid", checks=checks,
                    measurements=measurements, artifacts=artifacts,
                )
            _passed_check(checks, "band_kpoints")

        if stage == "dos":
            kpoints = next(item for item in artifacts if item["name"] == "KPOINTS")
            measurements["kpoints_sha256"] = kpoints["sha256"]
            if kpoints["sha256"] != _DOS_KPOINTS_SHA256:
                return _failed_acceptance(
                    check_name="dos_kpoints", reason_code="dos_kpoints_invalid", checks=checks,
                    measurements=measurements, artifacts=artifacts,
                )
            _passed_check(checks, "dos_kpoints")
            try:
                nedos = _parse_nedos(_read_acceptance_metadata(opened_files["INCAR"]))
            except VaspPolicyError as error:
                return _failed_acceptance(
                    check_name="dos_nedos", reason_code=error.code, checks=checks,
                    measurements=measurements, artifacts=artifacts,
                )
            parameters = getattr(vasprun, "parameters", None)
            effective_nedos = parameters.get("NEDOS") if isinstance(parameters, Mapping) else None
            if (
                isinstance(effective_nedos, bool)
                or type(effective_nedos) is not int
                or effective_nedos != nedos
            ):
                return _failed_acceptance(
                    check_name="dos_nedos", reason_code="dos_nedos_mismatch", checks=checks,
                    measurements=measurements, artifacts=artifacts,
                )
            measurements["nedos"] = nedos
            _passed_check(checks, "dos_nedos")

        for opened in opened_files.values():
            try:
                _verify_evidence_unchanged(opened)
            except VaspPolicyError as error:
                return _failed_acceptance(
                    check_name="evidence_stability", reason_code=error.code, checks=checks,
                    measurements=measurements, artifacts=artifacts,
                )
        if directory_fd is None:
            try:
                _verify_attempt_directory_identity(root, root_identity)
            except VaspPolicyError as error:
                return _failed_acceptance(
                    check_name="evidence_stability", reason_code=error.code, checks=checks,
                    measurements=measurements, artifacts=artifacts,
                )
        _passed_check(checks, "evidence_stability")

    return _acceptance_report(
        accepted=True,
        reason_code=None,
        checks=checks,
        measurements=measurements,
        artifacts=artifacts,
    )


def _validate_attempt_directory(root: Path) -> os.stat_result:
    try:
        identity = root.lstat()
    except OSError:
        raise VaspPolicyError(
            "attempt_directory_invalid", "attempt directory is unavailable"
        ) from None
    if stat.S_ISLNK(identity.st_mode):
        raise VaspPolicyError("attempt_directory_symlink", "attempt directory must not be a symlink")
    if not stat.S_ISDIR(identity.st_mode):
        raise VaspPolicyError("attempt_directory_invalid", "attempt directory is invalid")
    return identity


def _open_attempt_directory(
    root: Path,
    expected_identity: os.stat_result,
    resources: ExitStack,
) -> int | None:
    if not _HAS_SECURE_DIR_FD:
        return None
    descriptor: int | None = None
    try:
        descriptor = os.open(
            root,
            os.O_RDONLY | _O_CLOEXEC | _O_DIRECTORY | _O_NOFOLLOW,
        )
        opened_identity = os.fstat(descriptor)
    except OSError:
        _close_descriptor(descriptor)
        raise VaspPolicyError(
            "attempt_directory_invalid", "attempt directory could not be opened"
        ) from None
    if not stat.S_ISDIR(opened_identity.st_mode) or not _same_file_identity(
        expected_identity, opened_identity
    ):
        _close_descriptor(descriptor)
        raise VaspPolicyError("attempt_directory_invalid", "attempt directory changed")
    resources.callback(_close_descriptor, descriptor)
    return descriptor


def _verify_attempt_directory_identity(
    root: Path, expected_identity: os.stat_result
) -> None:
    try:
        current_identity = root.lstat()
    except OSError:
        raise VaspPolicyError("attempt_directory_invalid", "attempt directory changed") from None
    if stat.S_ISLNK(current_identity.st_mode) or not _same_file_identity(
        expected_identity, current_identity
    ):
        raise VaspPolicyError("attempt_directory_invalid", "attempt directory changed")


def _open_required_file(
    root: Path,
    name: str,
    directory_fd: int | None,
    resources: ExitStack,
) -> _OpenedEvidence:
    path = root / name
    try:
        if directory_fd is None:
            expected_identity = path.lstat()
        else:
            expected_identity = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    except OSError:
        raise VaspPolicyError(
            "potcar_file_missing", "required POTCAR evidence is unavailable"
        ) from None
    if stat.S_ISLNK(expected_identity.st_mode):
        raise VaspPolicyError("potcar_symlink", "POTCAR evidence must not be a symlink")
    if not stat.S_ISREG(expected_identity.st_mode):
        raise VaspPolicyError("potcar_file_invalid", "POTCAR evidence must be a regular file")

    flags = os.O_RDONLY | _O_BINARY | _O_CLOEXEC | _O_NONBLOCK | _O_NOFOLLOW
    descriptor: int | None = None
    try:
        if directory_fd is None:
            descriptor = os.open(path, flags)
        else:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
        opened_identity = os.fstat(descriptor)
    except OSError:
        _close_descriptor(descriptor)
        raise VaspPolicyError(
            "potcar_file_invalid", "POTCAR evidence could not be opened"
        ) from None

    if not stat.S_ISREG(opened_identity.st_mode):
        _close_descriptor(descriptor)
        raise VaspPolicyError("potcar_file_invalid", "POTCAR evidence must be a regular file")
    if not _same_file_identity(expected_identity, opened_identity):
        _close_descriptor(descriptor)
        raise VaspPolicyError("potcar_file_changed", "POTCAR evidence changed while opening")
    if directory_fd is None:
        try:
            final_identity = path.lstat()
        except OSError:
            _close_descriptor(descriptor)
            raise VaspPolicyError("potcar_file_changed", "POTCAR evidence changed") from None
        if stat.S_ISLNK(final_identity.st_mode) or not _same_file_identity(
            opened_identity, final_identity
        ):
            _close_descriptor(descriptor)
            raise VaspPolicyError("potcar_file_changed", "POTCAR evidence changed")
    try:
        handle = os.fdopen(descriptor, "rb", closefd=True)
    except OSError:
        _close_descriptor(descriptor)
        raise VaspPolicyError(
            "potcar_file_invalid", "POTCAR evidence could not be opened"
        ) from None
    resources.callback(_close_handle, handle)
    return _OpenedEvidence(handle=handle, size_bytes=opened_identity.st_size)


def _same_file_identity(expected: os.stat_result, opened: os.stat_result) -> bool:
    return bool(
        expected.st_ino
        and opened.st_ino
        and expected.st_dev == opened.st_dev
        and expected.st_ino == opened.st_ino
    )


def _close_descriptor(descriptor: int | None) -> None:
    if descriptor is None:
        return
    try:
        os.close(descriptor)
    except OSError:
        pass


def _close_handle(handle: BinaryIO) -> None:
    try:
        handle.close()
    except OSError:
        pass


def _read_metadata(handle: BinaryIO) -> bytes:
    try:
        content = handle.read(_MAX_METADATA_BYTES + 1)
    except OSError:
        raise VaspPolicyError(
            "potcar_file_invalid", "POTCAR evidence could not be read"
        ) from None
    if len(content) > _MAX_METADATA_BYTES:
        raise VaspPolicyError("potcar_metadata_too_large", "POTCAR metadata exceeds the policy limit")
    return content


def _decode_metadata(content: bytes) -> str:
    try:
        return content.decode("ascii")
    except UnicodeDecodeError:
        raise VaspPolicyError(
            "vaspkit_version_invalid", "VASPKIT version evidence is invalid"
        ) from None


def _validate_vaspkit_banner(content: str, expected_version: str) -> None:
    lines = content.splitlines()
    banner_matches = [match for line in lines if (match := _VASPKIT_BANNER_RE.fullmatch(line))]
    product_lines = [line for line in lines if "VASPKIT" in line]
    version_identities = _VERSION_RE.findall(content)
    if (
        len(banner_matches) != 1
        or banner_matches[0].group("version") != expected_version
        or len(product_lines) != 1
        or version_identities != [expected_version]
    ):
        raise VaspPolicyError("vaspkit_version_invalid", "VASPKIT version does not match policy")


def _extract_titles(handle: BinaryIO, expected_titles: tuple[str, ...]) -> list[str]:
    titles: list[str] = []
    try:
        while line := handle.readline(_MAX_TITLE_LINE_BYTES + 1):
            if len(line) > _MAX_TITLE_LINE_BYTES:
                raise VaspPolicyError(
                    "potcar_titles_invalid", "POTCAR title metadata exceeds the policy limit"
                )
            if not line.startswith(b"TITEL"):
                continue
            if len(titles) >= len(expected_titles):
                raise VaspPolicyError("potcar_titles_invalid", "POTCAR has additional titles")
            try:
                text = line.decode("ascii").rstrip("\r\n")
            except UnicodeDecodeError:
                raise VaspPolicyError(
                    "potcar_titles_invalid", "POTCAR title metadata is invalid"
                ) from None
            match = re.fullmatch(r"TITEL\s*=\s*(.+)", text)
            if match is None:
                raise VaspPolicyError("potcar_titles_invalid", "POTCAR title metadata is invalid")
            titles.append(_canonical_title(match.group(1), expected_titles))
    except VaspPolicyError:
        raise
    except OSError:
        raise VaspPolicyError("potcar_file_invalid", "POTCAR could not be read") from None
    return titles


def _canonical_title(value: str, expected_titles: tuple[str, ...]) -> str:
    for title in expected_titles:
        if value == title or value.startswith(title + " "):
            return title
    return value


def _rewind(handle: BinaryIO) -> None:
    try:
        handle.seek(0)
    except OSError:
        raise VaspPolicyError("potcar_file_invalid", "POTCAR could not be read") from None


def _sha256_file(handle: BinaryIO) -> str:
    digest = hashlib.sha256()
    try:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    except OSError:
        raise VaspPolicyError("potcar_file_invalid", "POTCAR could not be read") from None
    return digest.hexdigest()
