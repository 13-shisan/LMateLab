from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

try:
    from .import_qmof_structure_index import QMOF_ID_PATTERN, import_index
except ImportError:  # Direct execution from backend/scripts.
    from import_qmof_structure_index import QMOF_ID_PATTERN, import_index


@dataclass(frozen=True)
class DatasetSpec:
    version: str
    doi: str
    figshare_file_id: str
    authority_url: str
    transport_url: str
    transport_revision: str
    archive_name: str
    archive_size: int
    archive_md5: str
    archive_sha256: str
    csv_member: str
    csv_size: int
    csv_sha256: str
    cif_archive_member: str
    cif_archive_size: int
    cif_archive_sha256: str
    expected_count: int
    expected_cif_bytes: int


QMOF_V18 = DatasetSpec(
    version="v18",
    doi="10.6084/m9.figshare.13147324.v18",
    figshare_file_id="59573735",
    authority_url="https://figshare.com/articles/dataset/QMOF_Database/13147324/18",
    transport_url=(
        "https://huggingface.co/datasets/StructureCloud/QMOF/resolve/"
        "24fc459339583e2f7b876296b6daec8d6d0a22a5/raw/qmof_database.zip?download=true"
    ),
    transport_revision="24fc459339583e2f7b876296b6daec8d6d0a22a5",
    archive_name="qmof_database.zip",
    archive_size=392_088_304,
    archive_md5="0d89aaf66f2c306e86e47fd91cb1346e",
    archive_sha256="97d23c0b4f9e5a30888e53dc16222b90443ad7167c3284d2258615d9f44eceef",
    csv_member="qmof_database/qmof.csv",
    csv_size=21_573_509,
    csv_sha256="9991b2d51d71a6cc4c97affd8ca36ac18d5b75554b4f3f1ac9ebb35bc9995f26",
    cif_archive_member="qmof_database/relaxed_structures.zip",
    cif_archive_size=119_306_809,
    cif_archive_sha256="c7b18fbb042900a91fc481405dabda81196f88eff004c3a092ecaff393521211",
    expected_count=20_372,
    expected_cif_bytes=338_639_762,
)

MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TOTAL_CIF_BYTES = 1024 * 1024 * 1024
MANIFEST_PATTERN = re.compile(r"([0-9a-f]{64})  (qmof-[0-9a-f]+\.cif)")


class QmofInstallError(RuntimeError):
    pass


def _hashes(path: Path) -> tuple[str, str, int]:
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest(), size


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_archive(archive: Path, spec: DatasetSpec = QMOF_V18) -> dict[str, object]:
    if archive.is_symlink():
        raise QmofInstallError("archive path must not be a symlink")
    archive = archive.resolve(strict=True)
    md5, sha256, size = _hashes(archive)
    if size != spec.archive_size:
        raise QmofInstallError(
            f"archive size mismatch: expected {spec.archive_size}, found {size}"
        )
    if md5 != spec.archive_md5:
        raise QmofInstallError(f"archive MD5 mismatch: expected {spec.archive_md5}, found {md5}")
    if sha256 != spec.archive_sha256:
        raise QmofInstallError(
            f"archive SHA-256 mismatch: expected {spec.archive_sha256}, found {sha256}"
        )
    return {"size": size, "md5": md5, "sha256": sha256}


def _safe_member(info: zipfile.ZipInfo) -> PurePosixPath:
    normalized = info.filename.replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in ("", ".", "..") for part in path.parts)
        or ":" in path.parts[0]
    ):
        raise QmofInstallError(f"unsafe ZIP member: {info.filename!r}")
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode and stat.S_ISLNK(mode):
        raise QmofInstallError(f"ZIP symlink is not allowed: {info.filename!r}")
    return path


def _validated_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    result: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        path = _safe_member(info)
        name = path.as_posix()
        if name in result:
            raise QmofInstallError(f"duplicate ZIP member: {name}")
        result[name] = info
    return result


def _copy_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
    *,
    expected_size: int | None = None,
) -> tuple[int, str]:
    if info.is_dir():
        raise QmofInstallError(f"required ZIP member is a directory: {info.filename}")
    if expected_size is not None and info.file_size != expected_size:
        raise QmofInstallError(
            f"member size mismatch for {info.filename}: expected {expected_size}, found {info.file_size}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    copied = 0
    with archive.open(info, "r") as source, destination.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            copied += len(chunk)
            if expected_size is None and copied > MAX_MEMBER_BYTES:
                raise QmofInstallError(f"ZIP member is too large: {info.filename}")
            output.write(chunk)
            digest.update(chunk)
        output.flush()
        os.fsync(output.fileno())
    if copied != info.file_size:
        raise QmofInstallError(f"truncated ZIP member: {info.filename}")
    destination.chmod(0o600)
    return copied, digest.hexdigest()


def _csv_ids(source_csv: Path, expected_count: int) -> set[str]:
    ids: set[str] = set()
    with source_csv.open(newline="", encoding="utf-8") as source:
        rows = csv.DictReader(source)
        if "qmof_id" not in (rows.fieldnames or ()):
            raise QmofInstallError("QMOF CSV has no qmof_id column")
        for line, row in enumerate(rows, start=2):
            structure_id = (row.get("qmof_id") or "").strip()
            if not QMOF_ID_PATTERN.fullmatch(structure_id):
                raise QmofInstallError(f"line {line}: invalid QMOF id")
            if structure_id in ids:
                raise QmofInstallError(f"line {line}: duplicate QMOF id {structure_id}")
            ids.add(structure_id)
    if len(ids) != expected_count:
        raise QmofInstallError(
            f"CSV record count mismatch: expected {expected_count}, found {len(ids)}"
        )
    return ids


def _extract_cifs(
    cif_archive: Path,
    destination: Path,
    *,
    expected_count: int,
    expected_bytes: int,
) -> tuple[set[str], str]:
    destination.mkdir(mode=0o700)
    ids: set[str] = set()
    entries: list[str] = []
    total_bytes = 0
    try:
        with zipfile.ZipFile(cif_archive) as archive:
            members = _validated_members(archive)
            for name, info in members.items():
                if info.is_dir():
                    continue
                path = PurePosixPath(name)
                if len(path.parts) != 2 or path.parts[0] != "relaxed_structures":
                    raise QmofInstallError(f"unexpected relaxed-structure member: {name}")
                if path.suffix != ".cif" or not QMOF_ID_PATTERN.fullmatch(path.stem):
                    raise QmofInstallError(f"invalid QMOF CIF member: {name}")
                if path.stem in ids:
                    raise QmofInstallError(f"duplicate QMOF CIF id: {path.stem}")
                copied, digest = _copy_member(archive, info, destination / path.name)
                total_bytes += copied
                if total_bytes > MAX_TOTAL_CIF_BYTES:
                    raise QmofInstallError("relaxed CIF archive exceeds the extraction limit")
                ids.add(path.stem)
                entries.append(f"{digest}  {path.name}")
    except zipfile.BadZipFile as exc:
        raise QmofInstallError("relaxed_structures.zip is invalid") from exc
    if len(ids) != expected_count:
        raise QmofInstallError(
            f"CIF count mismatch: expected {expected_count}, found {len(ids)}"
        )
    if total_bytes != expected_bytes:
        raise QmofInstallError(
            f"CIF byte count mismatch: expected {expected_bytes}, found {total_bytes}"
        )
    manifest = destination.parent / "cif-manifest.sha256"
    with manifest.open("x", encoding="ascii", newline="\n") as handle:
        handle.write("\n".join(sorted(entries)) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    manifest.chmod(0o600)
    return ids, _sha256(manifest)


def _write_provenance(path: Path, payload: dict[str, object]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _manifest_ids(version_root: Path, expected_count: int) -> set[str]:
    manifest = version_root / "cif-manifest.sha256"
    if manifest.is_symlink() or not manifest.is_file():
        raise QmofInstallError("installed CIF manifest is missing or unsafe")
    cif_root = version_root / "relaxed_structures"
    if cif_root.is_symlink() or not cif_root.is_dir():
        raise QmofInstallError("installed CIF root is missing or unsafe")
    ids: set[str] = set()
    with manifest.open(encoding="ascii") as handle:
        for line_number, line in enumerate(handle, start=1):
            match = MANIFEST_PATTERN.fullmatch(line.rstrip("\n"))
            if not match:
                raise QmofInstallError(f"invalid CIF manifest line {line_number}")
            digest, name = match.groups()
            path = cif_root / name
            if path.is_symlink() or not path.is_file():
                raise QmofInstallError(f"manifest CIF is missing or unsafe: {name}")
            if _sha256(path) != digest:
                raise QmofInstallError(f"CIF hash mismatch: {name}")
            structure_id = Path(name).stem
            if structure_id in ids:
                raise QmofInstallError(f"duplicate CIF manifest id: {structure_id}")
            ids.add(structure_id)
    if len(ids) != expected_count:
        raise QmofInstallError(
            f"CIF manifest count mismatch: expected {expected_count}, found {len(ids)}"
        )
    children = list(cif_root.iterdir())
    if any(path.is_symlink() or not path.is_file() or path.suffix != ".cif" for path in children):
        raise QmofInstallError("CIF directory contains an unexpected entry")
    actual_names = {path.stem for path in children}
    if actual_names != ids:
        raise QmofInstallError("CIF directory and manifest ID sets differ")
    return ids


def verify_version(version_root: Path, spec: DatasetSpec = QMOF_V18) -> dict[str, object]:
    if version_root.is_symlink():
        raise QmofInstallError("installed version must not be a symlink")
    version_root = version_root.resolve(strict=True)
    required = {
        "qmof.csv": spec.csv_sha256,
        "relaxed_structures.zip": spec.cif_archive_sha256,
    }
    for name, expected_hash in required.items():
        path = version_root / name
        if path.is_symlink() or not path.is_file() or _sha256(path) != expected_hash:
            raise QmofInstallError(f"installed file validation failed: {name}")
    provenance_path = version_root / "provenance.json"
    if provenance_path.is_symlink() or not provenance_path.is_file():
        raise QmofInstallError("installed provenance is missing or unsafe")
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QmofInstallError("installed provenance is missing or invalid") from exc
    expected_metadata = {
        "dataset": "QMOF",
        "version": spec.version,
        "doi": spec.doi,
        "figshare_file_id": spec.figshare_file_id,
        "archive_size": spec.archive_size,
        "archive_md5": spec.archive_md5,
        "archive_sha256": spec.archive_sha256,
        "csv_sha256": spec.csv_sha256,
        "cif_archive_sha256": spec.cif_archive_sha256,
        "record_count": spec.expected_count,
        "cif_count": spec.expected_count,
        "cif_uncompressed_bytes": spec.expected_cif_bytes,
    }
    for key, value in expected_metadata.items():
        if provenance.get(key) != value:
            raise QmofInstallError(f"installed provenance mismatch: {key}")
    if provenance.get("cif_manifest_sha256") != _sha256(version_root / "cif-manifest.sha256"):
        raise QmofInstallError("installed CIF manifest hash mismatch")
    csv_ids = _csv_ids(version_root / "qmof.csv", spec.expected_count)
    cif_ids = _manifest_ids(version_root, spec.expected_count)
    if csv_ids != cif_ids:
        raise QmofInstallError("installed CSV and CIF ID sets differ")
    database = version_root / "structures.sqlite"
    if database.is_symlink() or not database.is_file():
        raise QmofInstallError("installed structure index is missing or unsafe")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise QmofInstallError("installed structure index failed integrity_check")
        count = connection.execute("SELECT COUNT(*) FROM structures").fetchone()[0]
        db_ids = {row[0] for row in connection.execute("SELECT id FROM structures")}
        db_provenance = dict(connection.execute("SELECT key, value FROM provenance"))
    if count != spec.expected_count or db_ids != csv_ids:
        raise QmofInstallError("installed structure index does not match the source CSV")
    if db_provenance.get("archive_sha256") != spec.archive_sha256:
        raise QmofInstallError("structure index provenance does not match the archive")
    return {
        "version": spec.version,
        "record_count": count,
        "cif_count": len(cif_ids),
        "database": str(database),
        "cif_root": str(version_root / "relaxed_structures"),
    }


def _switch_current(data_root: Path, version_root: Path) -> None:
    current = data_root / "current"
    if current.exists() and not current.is_symlink():
        raise QmofInstallError("QMOF current exists but is not a symlink")
    temporary = data_root / f".current.{os.getpid()}"
    temporary.unlink(missing_ok=True)
    try:
        os.symlink(version_root.name, temporary, target_is_directory=True)
        os.replace(temporary, current)
    finally:
        temporary.unlink(missing_ok=True)


def install_dataset(
    archive: Path,
    data_root: Path,
    *,
    spec: DatasetSpec = QMOF_V18,
    source_commit: str = "unknown",
    transport_url_used: str | None = None,
    switch_current: bool = True,
) -> dict[str, object]:
    archive_metadata = verify_archive(archive, spec)
    data_root = data_root.resolve(strict=False)
    data_root.mkdir(parents=True, exist_ok=True)
    data_root.chmod(0o700)
    version_root = data_root / spec.version
    if version_root.exists():
        result = verify_version(version_root, spec)
        if switch_current:
            _switch_current(data_root, version_root)
        return {**result, "reused": True}

    staging = Path(tempfile.mkdtemp(prefix=f".{spec.version}.", dir=data_root))
    staging.chmod(0o700)
    try:
        csv_path = staging / "qmof.csv"
        cif_archive_path = staging / "relaxed_structures.zip"
        try:
            with zipfile.ZipFile(archive) as outer:
                members = _validated_members(outer)
                try:
                    csv_info = members[spec.csv_member]
                    cif_info = members[spec.cif_archive_member]
                except KeyError as exc:
                    raise QmofInstallError(f"required QMOF member is missing: {exc.args[0]}") from exc
                csv_size, csv_sha256 = _copy_member(
                    outer, csv_info, csv_path, expected_size=spec.csv_size
                )
                cif_archive_size, cif_archive_sha256 = _copy_member(
                    outer,
                    cif_info,
                    cif_archive_path,
                    expected_size=spec.cif_archive_size,
                )
        except zipfile.BadZipFile as exc:
            raise QmofInstallError("QMOF archive is invalid") from exc
        if csv_sha256 != spec.csv_sha256 or cif_archive_sha256 != spec.cif_archive_sha256:
            raise QmofInstallError("QMOF component hash validation failed")
        csv_ids = _csv_ids(csv_path, spec.expected_count)
        cif_ids, cif_manifest_sha256 = _extract_cifs(
            cif_archive_path,
            staging / "relaxed_structures",
            expected_count=spec.expected_count,
            expected_bytes=spec.expected_cif_bytes,
        )
        if csv_ids != cif_ids:
            raise QmofInstallError("QMOF CSV and CIF ID sets differ")
        database = staging / "structures.sqlite"
        import_index(
            csv_path,
            database,
            expected_count=spec.expected_count,
            provenance={
                "dataset": "QMOF",
                "version": spec.version,
                "doi": spec.doi,
                "archive_sha256": spec.archive_sha256,
                "source_commit": source_commit,
            },
        )
        actual_transport_url = transport_url_used or spec.transport_url
        provenance = {
            "schema": "lmatelab-qmof-install-v1",
            "dataset": "QMOF",
            "version": spec.version,
            "license": "CC BY 4.0",
            "doi": spec.doi,
            "figshare_file_id": spec.figshare_file_id,
            "authority_url": spec.authority_url,
            "transport_url": actual_transport_url,
            "transport_revision": spec.transport_revision,
            "transport_note": (
                "Hash-identical mirror used only as the transfer channel."
                if actual_transport_url == spec.transport_url
                else "Temporary relay used only as the transfer channel; official hashes verified."
            ),
            "archive_name": spec.archive_name,
            "archive_size": archive_metadata["size"],
            "archive_md5": archive_metadata["md5"],
            "archive_sha256": archive_metadata["sha256"],
            "csv_size": csv_size,
            "csv_sha256": csv_sha256,
            "cif_archive_size": cif_archive_size,
            "cif_archive_sha256": cif_archive_sha256,
            "cif_manifest_sha256": cif_manifest_sha256,
            "record_count": len(csv_ids),
            "cif_count": len(cif_ids),
            "cif_uncompressed_bytes": spec.expected_cif_bytes,
            "source_commit": source_commit,
            "installed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        _write_provenance(staging / "provenance.json", provenance)
        os.replace(staging, version_root)
        result = verify_version(version_root, spec)
        if switch_current:
            _switch_current(data_root, version_root)
        return {**result, "reused": False}
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--source-commit", default="unknown")
    parser.add_argument("--transport-url-used")
    parser.add_argument("--verify-archive-only", action="store_true")
    parser.add_argument("--verify-installed", action="store_true")
    args = parser.parse_args()
    if args.verify_archive_only:
        result = verify_archive(args.archive)
    elif args.verify_installed:
        if args.data_root is None:
            parser.error("--data-root is required with --verify-installed")
        result = verify_version(args.data_root / QMOF_V18.version)
    else:
        if args.data_root is None:
            parser.error("--data-root is required for installation")
        result = install_dataset(
            args.archive,
            args.data_root,
            source_commit=args.source_commit,
            transport_url_used=args.transport_url_used,
        )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
