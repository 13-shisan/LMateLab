from __future__ import annotations

import hashlib
import re
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final


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
_MAX_METADATA_BYTES: Final = 8192
_MAX_TITLE_LINE_BYTES: Final = 4096
_HASH_CHUNK_BYTES: Final = 64 * 1024


class VaspPolicyError(RuntimeError):
    """A stable, non-disclosing VASP policy rejection."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


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
    _validate_attempt_directory(root)
    files = {name: _required_regular_file(root / name) for name in _REQUIRED_FILES}

    expected_spec = b"".join(symbol.encode("ascii") + b"\n" for symbol in contract.symbols)
    if _read_metadata(files["POTCAR.spec"]) != expected_spec:
        raise VaspPolicyError("potcar_spec_invalid", "POTCAR specification does not match policy")

    evidence = _read_metadata(files["potcar-source-sha256.txt"])
    expected_evidence = b"".join(
        digest.encode("ascii") + b"  " + symbol.encode("ascii") + b"\n"
        for digest, symbol in zip(contract.source_sha256, contract.symbols, strict=True)
    )
    if evidence != expected_evidence:
        raise VaspPolicyError(
            "potcar_source_evidence_invalid",
            "POTCAR source checksum evidence does not match policy",
        )

    vaspkit_text = _decode_metadata(_read_metadata(files["vaspkit-version.txt"]))
    expected_banner = f"VASPKIT Standard Edition {contract.vaspkit_version}"
    if vaspkit_text.splitlines() != [expected_banner]:
        raise VaspPolicyError("vaspkit_version_invalid", "VASPKIT version does not match policy")

    potcar_path = files["POTCAR"]
    try:
        size_bytes = potcar_path.stat().st_size
    except OSError as error:
        raise VaspPolicyError("potcar_file_invalid", "POTCAR could not be read") from error
    if size_bytes == 0:
        raise VaspPolicyError("potcar_empty", "POTCAR is empty")
    titles = _extract_titles(potcar_path, contract.titles)
    if titles != list(contract.titles):
        raise VaspPolicyError("potcar_titles_invalid", "POTCAR titles do not match policy")
    digest = _sha256_file(potcar_path)
    if digest != contract.combined_sha256:
        raise VaspPolicyError("potcar_sha256_mismatch", "POTCAR checksum does not match policy")

    return {
        "sha256": digest,
        "titles": list(contract.titles),
        "symbols": list(contract.symbols),
        "source_sha256": list(contract.source_sha256),
        "vaspkit_version": contract.vaspkit_version,
        "size_bytes": size_bytes,
    }


def _validate_attempt_directory(root: Path) -> None:
    try:
        mode = root.lstat().st_mode
    except OSError as error:
        raise VaspPolicyError("attempt_directory_invalid", "attempt directory is unavailable") from error
    if stat.S_ISLNK(mode):
        raise VaspPolicyError("attempt_directory_symlink", "attempt directory must not be a symlink")
    if not stat.S_ISDIR(mode):
        raise VaspPolicyError("attempt_directory_invalid", "attempt directory is invalid")


def _required_regular_file(path: Path) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise VaspPolicyError("potcar_file_missing", "required POTCAR evidence is unavailable") from error
    if stat.S_ISLNK(mode):
        raise VaspPolicyError("potcar_symlink", "POTCAR evidence must not be a symlink")
    if not stat.S_ISREG(mode):
        raise VaspPolicyError("potcar_file_invalid", "POTCAR evidence must be a regular file")
    return path


def _read_metadata(path: Path) -> bytes:
    try:
        with path.open("rb") as handle:
            content = handle.read(_MAX_METADATA_BYTES + 1)
    except OSError as error:
        raise VaspPolicyError("potcar_file_invalid", "POTCAR evidence could not be read") from error
    if len(content) > _MAX_METADATA_BYTES:
        raise VaspPolicyError("potcar_metadata_too_large", "POTCAR metadata exceeds the policy limit")
    return content


def _decode_metadata(content: bytes) -> str:
    try:
        return content.decode("ascii")
    except UnicodeDecodeError as error:
        raise VaspPolicyError("vaspkit_version_invalid", "VASPKIT version evidence is invalid") from error


def _extract_titles(path: Path, expected_titles: tuple[str, ...]) -> list[str]:
    titles: list[str] = []
    try:
        with path.open("rb") as handle:
            while line := handle.readline(_MAX_TITLE_LINE_BYTES + 1):
                if len(line) > _MAX_TITLE_LINE_BYTES:
                    raise VaspPolicyError(
                        "potcar_titles_invalid", "POTCAR title metadata exceeds the policy limit"
                    )
                if not line.startswith(b"TITEL"):
                    continue
                try:
                    text = line.decode("ascii").rstrip("\r\n")
                except UnicodeDecodeError as error:
                    raise VaspPolicyError(
                        "potcar_titles_invalid", "POTCAR title metadata is invalid"
                    ) from error
                match = re.fullmatch(r"TITEL\s*=\s*(.+)", text)
                if match is None:
                    raise VaspPolicyError("potcar_titles_invalid", "POTCAR title metadata is invalid")
                titles.append(_canonical_title(match.group(1), expected_titles))
    except VaspPolicyError:
        raise
    except OSError as error:
        raise VaspPolicyError("potcar_file_invalid", "POTCAR could not be read") from error
    return titles


def _canonical_title(value: str, expected_titles: tuple[str, ...]) -> str:
    for title in expected_titles:
        if value == title or value.startswith(title + " "):
            return title
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as error:
        raise VaspPolicyError("potcar_file_invalid", "POTCAR could not be read") from error
    return digest.hexdigest()
