from __future__ import annotations

import re
from typing import Callable
from xml.etree import ElementTree


def _floats(pattern: str, content: str) -> list[float]:
    return [float(value) for value in re.findall(pattern, content, re.IGNORECASE)]


def _outcar(content: str) -> dict[str, object]:
    energies = _floats(r"free\s+energy\s+TOTEN\s*=\s*([-+0-9.eE]+)", content)
    force_blocks = re.findall(r"TOTAL-FORCE\s+\(eV/Angst\)(.*?)(?:\n\s*---+)", content, re.DOTALL)
    return {
        "final_energy_eV": energies[-1] if energies else None,
        "ionic_steps": len(energies),
        "force_blocks": len(force_blocks),
        "electronic_converged": "aborting loop because EDIFF is reached" in content,
        "ionic_converged": "reached required accuracy" in content,
    }


def _oszicar(content: str) -> dict[str, object]:
    energies = _floats(r"\bE0=\s*([-+0-9.eE]+)", content)
    free_energies = _floats(r"\bF=\s*([-+0-9.eE]+)", content)
    magnetic = _floats(r"\bmag=\s*([-+0-9.eE]+)", content)
    ionic_lines = re.findall(r"(?m)^\s*\d+\s+F=", content)
    return {
        "final_energy_e0_eV": energies[-1] if energies else None,
        "final_free_energy_eV": free_energies[-1] if free_energies else None,
        "final_magnetic_moment": magnetic[-1] if magnetic else None,
        "ionic_steps": len(ionic_lines),
    }


def _vasprun(content: str) -> dict[str, object]:
    root = ElementTree.fromstring(content)
    calculations = root.findall(".//calculation")
    energies = []
    for node in root.findall(".//calculation/energy/i[@name='e_0_energy']"):
        try:
            energies.append(float(node.text or ""))
        except ValueError:
            continue
    return {
        "calculation_steps": len(calculations),
        "final_energy_e0_eV": energies[-1] if energies else None,
        "xml_complete": content.rstrip().endswith("</modeling>"),
    }


def _eigenval(content: str) -> dict[str, object]:
    lines = content.splitlines()
    if len(lines) < 6:
        return {"parse_warning": "EIGENVAL header is incomplete"}
    fields = lines[5].split()
    if len(fields) < 3:
        return {"parse_warning": "EIGENVAL dimensions are unavailable"}
    return {
        "electrons": int(float(fields[0])),
        "kpoints": int(float(fields[1])),
        "bands": int(float(fields[2])),
    }


def _procar(content: str) -> dict[str, object]:
    match = re.search(
        r"#\s*of\s*k-points:\s*(\d+)\s*#\s*of\s*bands:\s*(\d+)\s*#\s*of\s*ions:\s*(\d+)",
        content,
        re.IGNORECASE,
    )
    if not match:
        return {"parse_warning": "PROCAR dimensions are unavailable"}
    return {"kpoints": int(match[1]), "bands": int(match[2]), "ions": int(match[3])}


def _doscar(content: str) -> dict[str, object]:
    lines = content.splitlines()
    if len(lines) < 6:
        return {"parse_warning": "DOSCAR header is incomplete"}
    fields = lines[5].split()
    if len(fields) < 4:
        return {"parse_warning": "DOSCAR energy grid is unavailable"}
    return {
        "energy_max_eV": float(fields[0]),
        "energy_min_eV": float(fields[1]),
        "grid_points": int(float(fields[2])),
        "fermi_energy_eV": float(fields[3]),
    }


def _structure(content: str) -> dict[str, object]:
    lines = [line.strip() for line in content.splitlines()]
    if len(lines) < 7:
        return {"parse_warning": "POSCAR/CONTCAR header is incomplete"}
    symbols = lines[5].split()
    try:
        counts = [int(value) for value in lines[6].split()]
    except ValueError:
        return {"parse_warning": "POSCAR/CONTCAR atom counts are invalid"}
    return {
        "title": lines[0],
        "elements": symbols if len(symbols) == len(counts) else [],
        "element_counts": counts,
        "atom_count": sum(counts),
        "coordinate_mode": lines[7] if len(lines) > 7 else "",
    }


ANALYZERS: dict[str, tuple[str, Callable[[str], dict[str, object]]]] = {
    "OUTCAR": ("outcar_summary_v1", _outcar),
    "OSZICAR": ("oszicar_summary_v1", _oszicar),
    "VASPRUN.XML": ("vasprun_summary_v1", _vasprun),
    "EIGENVAL": ("eigenval_header_v1", _eigenval),
    "PROCAR": ("procar_header_v1", _procar),
    "DOSCAR": ("doscar_header_v1", _doscar),
    "CONTCAR": ("structure_summary_v1", _structure),
    "POSCAR": ("structure_summary_v1", _structure),
}


def analyze_vasp_files(files: list[dict[str, object]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for item in files:
        name = str(item.get("name") or "")
        content = item.get("content")
        if not isinstance(content, str):
            continue
        analyzer = ANALYZERS.get(name.upper())
        if analyzer is None:
            results.append({
                "analyzer": "text_metadata_v1",
                "file_id": str(item.get("id") or ""),
                "file_name": name,
                "facts": {"line_count": len(content.splitlines()), "character_count": len(content)},
            })
            continue
        analyzer_id, parser = analyzer
        try:
            facts = parser(content)
        except (ElementTree.ParseError, ValueError, OverflowError):
            facts = {"parse_warning": f"{name} content could not be parsed completely"}
        results.append({
            "analyzer": analyzer_id,
            "file_id": str(item.get("id") or ""),
            "file_name": name,
            "facts": facts,
        })
    return results
