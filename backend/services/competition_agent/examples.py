from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path


EXAMPLES = {
    "cr2c12o6f6-scf": {"directory": "Cr2C12O6F6_SCF", "formula": "Cr2C12O6F6", "task": "SCF"},
    "cr2c12se6f6-scf": {"directory": "Cr2C12Se6F6_SCF", "formula": "Cr2C12Se6F6", "task": "SCF"},
}
ALLOWED_FILES = ("INCAR", "KPOINTS", "POSCAR", "CONTCAR", "OUTCAR", "OSZICAR", "EIGENVAL", "DOSCAR", "IBZKPT", "XDATCAR")


class ExampleBundleError(ValueError):
    pass


def examples_root() -> Path:
    configured = os.environ.get("LMATELAB_AGENT_EXAMPLES_ROOT")
    if configured:
        return Path(configured).resolve()
    return (Path(__file__).resolve().parents[2] / "competition_examples" / "dawn5").resolve()


def _directory(example_id: str) -> Path:
    try:
        directory_name = str(EXAMPLES[example_id]["directory"])
    except KeyError as exc:
        raise ExampleBundleError("example is unavailable") from exc
    root = examples_root()
    candidates = [root / directory_name, root / directory_name.casefold()]
    directory = next((item for item in candidates if item.is_dir()), None)
    if directory is None:
        raise ExampleBundleError("example files are unavailable")
    return directory


def list_examples() -> list[dict[str, object]]:
    rows = []
    for example_id, metadata in EXAMPLES.items():
        try:
            directory = _directory(example_id)
        except ExampleBundleError:
            continue
        files = [
            {"name": name, "size_bytes": (directory / name).stat().st_size}
            for name in ALLOWED_FILES
            if (directory / name).is_file()
        ]
        rows.append({
            "id": example_id,
            "formula": metadata["formula"],
            "task": metadata["task"],
            "source": "Dawn5",
            "files": files,
        })
    return rows


def build_example_bundle(example_id: str) -> bytes:
    directory = _directory(example_id)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ALLOWED_FILES:
            path = directory / name
            if path.is_file():
                archive.writestr(name, path.read_bytes())
        archive.writestr(
            "MANIFEST.txt",
            "LMateLab Dawn5 completed calculation example\n"
            "POTCAR, WAVECAR, CHGCAR, scheduler scripts and absolute paths are excluded.\n",
        )
    if len(output.getvalue()) > 20 * 1024 * 1024:
        raise ExampleBundleError("example bundle exceeds the download limit")
    return output.getvalue()
