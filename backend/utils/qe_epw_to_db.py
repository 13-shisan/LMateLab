#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# backend/utils/qe_epw_to_db.py

import os
import re
import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import xml.etree.ElementTree as ET
from utils.qe_epw_schema import SCHEMA_SQL

# -----------------------------
# Constants / markers
# -----------------------------
QE_DONE = "JOB DONE."
EPW_DONE = "Total program execution"

ELEC_HEADER_KEY = "Drift Elec mobility"
HOLE_HEADER_KEY = "Drift Hole mobility"

RE_FLOAT = r"[-+]?(?:\d+\.\d*|\d*\.\d+|\d+)(?:[Ee][-+]?\d+)?"
NUM_RX = re.compile(RE_FLOAT)

FINGERPRINT_HEAD_BYTES = 120_000
FINGERPRINT_TAIL_BYTES = 120_000

HARTREE_TO_EV = 27.211386245988  # 1 Ha = 27.211386245988 eV
RY_TO_EV = 13.605693122994       # 1 Ry = 13.605693122994 eV

# -----------------------------
# Regex for parsing QE/PH scalars from OUT
# -----------------------------
QE_RX = {
    "nat": re.compile(r"number of atoms/cell\s*=\s*(\d+)", re.I),
    "ntyp": re.compile(r"number of atomic types\s*=\s*(\d+)", re.I),
    "nelec": re.compile(r"number of electrons\s*=\s*(%s)" % RE_FLOAT, re.I),
    "nbnd": re.compile(r"number of Kohn-Sham states\s*=\s*(\d+)", re.I),
    "ecutwfc_ry": re.compile(r"kinetic-energy cut-?off\s*=\s*(%s)\s*Ry" % RE_FLOAT, re.I),
    "ecutrho_ry": re.compile(r"charge density cut-?off\s*=\s*(%s)\s*Ry" % RE_FLOAT, re.I),
    "alat_au": re.compile(r"lattice parameter\s*\(a(?:lat|_\s*0)\)\s*=\s*(%s)\s*a\.u\." % RE_FLOAT, re.I),
    "cell_volume_au3": re.compile(r"unit-cell volume\s*=\s*(%s)\s*\(a\.u\.\)\^3" % RE_FLOAT, re.I),
    "efermi_ev": re.compile(r"the Fermi energy is\s*(%s)\s*ev" % RE_FLOAT, re.I),
    "total_energy_ev": re.compile(r"!\s*total energy\s*=\s*(%s)\s*Ry" % RE_FLOAT, re.I),
}

PH_RX = {
    "qgrid": re.compile(r"Dynamical matrices for\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)\s*uniform grid", re.I),
    "nqpoints": re.compile(r"\(\s*(\d+)\s*q-points\)\s*:", re.I),
}

# -----------------------------
# QE input parsing helpers
# -----------------------------
CONTROL_CALC_RX = re.compile(
    r"^\s*calculation\s*=\s*(?:['\"]([^'\"]+)['\"]|([A-Za-z0-9_.\-]+))\s*,?\s*$",
    re.I | re.M
)
PREFIX_RX = re.compile(
    r"^\s*prefix\s*=\s*(?:['\"]([^'\"]+)['\"]|([A-Za-z0-9_.\-]+))\s*,?\s*$",
    re.I | re.M
)
FLFRC_RX = re.compile(r"^\s*flfrc\s*=\s*['\"]([^'\"]+)['\"]", re.I | re.M)
IBRAV_RX = re.compile(r"^\s*ibrav\s*=\s*([-\d]+)", re.I | re.M)
NAT_RX_IN = re.compile(r"^\s*nat\s*=\s*(\d+)", re.I | re.M)
NTYP_RX_IN = re.compile(r"^\s*ntyp\s*=\s*(\d+)", re.I | re.M)
ASSUME_ISO_RX = re.compile(r"^\s*assume_isolated\s*=\s*['\"]([^'\"]+)['\"]", re.I | re.M)

ATOMIC_POSITIONS_HDR = re.compile(
    r"^\s*ATOMIC_POSITIONS\s*(?:\(\s*([^)]+)\s*\)|\{\s*([^}]+)\s*\}|\s+([A-Za-z_]+))?\s*$",
    re.I | re.M
)
CELL_PARAMETERS_HDR = re.compile(
    r"^\s*CELL_PARAMETERS\s*(?:\(\s*([^)]+)\s*\)|\{\s*([^}]+)\s*\}|\s+([A-Za-z_]+))?\s*$",
    re.I | re.M
)
K_POINTS_HDR = re.compile(
    r"^\s*K_POINTS\s*(?:\(\s*([^)]+)\s*\)|\{\s*([^}]+)\s*\}|\s+([A-Za-z_]+))?\s*$",
    re.I | re.M
)

# -----------------------------
# DB helpers
# -----------------------------
def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.executescript(SCHEMA_SQL)
    return conn

def connect_db_existing(db_path: Path) -> sqlite3.Connection:
    if not db_path.exists():
        raise FileNotFoundError(f"DB not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

# -----------------------------
# Fingerprint / file IO
# -----------------------------
def file_fingerprint_sha256(path: Path,
                            head_bytes: int = FINGERPRINT_HEAD_BYTES,
                            tail_bytes: int = FINGERPRINT_TAIL_BYTES) -> str:
    st = path.stat()
    size = st.st_size

    h = hashlib.sha256()
    h.update(str(size).encode("utf-8"))
    h.update(b"\n")

    with path.open("rb") as f:
        head = f.read(min(head_bytes, size))
        h.update(head)
        if size > head_bytes:
            f.seek(max(0, size - tail_bytes), os.SEEK_SET)
            tail = f.read(tail_bytes)
            h.update(tail)

    return h.hexdigest()

def read_tail_text(path: Path, tail_bytes: int = 40000) -> str:
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        n = min(tail_bytes, size)
        f.seek(-n, os.SEEK_END)
        return f.read().decode(errors="ignore")

# -----------------------------
# Detection / parsing
# -----------------------------
def detect_finished_marker(tail_text: str) -> Optional[str]:
    if EPW_DONE in tail_text:
        return EPW_DONE
    if QE_DONE in tail_text:
        return QE_DONE
    return None

def code_from_marker(marker: str) -> str:
    if marker == EPW_DONE:
        return "epw"
    if marker == QE_DONE:
        return "qe"
    return "unknown"

def guess_calc_type_from_out(out_path: Path, text_head: str) -> str:
    head = text_head.lower()
    name = out_path.name.lower()

    if "program epw" in head:
        return "epw"
    if "program phonon" in head:
        return "ph"
    if "program q2r" in head:
        return "q2r"
    if "program matdyn" in head:
        return "matdyn"
    if "program pwscf" in head:
        if name.startswith("scf") or ".scf." in name:
            return "scf"
        if name.startswith("nscf") or ".nscf." in name:
            return "nscf"
        if name.startswith("bs") or "band" in name:
            return "bs"
        return "pwscf"

    if "epw" in name:
        return "epw"
    if name.startswith("ph"):
        return "ph"
    if name.startswith("q2r"):
        return "q2r"
    if name.startswith("matdyn"):
        return "matdyn"
    if name.startswith("scf"):
        return "scf"
    if name.startswith("nscf"):
        return "nscf"
    if name.startswith("bs"):
        return "bs"

    return "unknown"

def parse_scalars_from_out(text_head: str, calc_type: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}

    for k, rx in QE_RX.items():
        m = rx.search(text_head)
        if not m:
            continue
        v = m.group(1)
        if k in ("nat", "ntyp", "nbnd"):
            out[k] = int(v)
        else:
            fv = float(v)
            # .out 里 total energy 的单位是 Ry；我们数据库字段要存 eV
            if k == "total_energy_ev":
                fv = fv * RY_TO_EV
            out[k] = fv

    if calc_type == "ph":
        m = PH_RX["qgrid"].search(text_head)
        if m:
            out["qgrid"] = f"{m.group(1)} {m.group(2)} {m.group(3)}"
        m = PH_RX["nqpoints"].search(text_head)
        if m:
            out["nqpoints"] = int(m.group(1))

    return out

def _safe_float_from_xml_text(x: Optional[str]) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None

def find_data_file_schema_xml(workdir: Path, prefix: Optional[str]) -> Optional[Path]:
    """
    Prefer: workdir/prefix.save/data-file-schema.xml
    Fallback: if prefix missing, try to locate unique *.save/data-file-schema.xml in workdir.
    """
    if prefix:
        p = workdir / f"{prefix}.save" / "data-file-schema.xml"
        if p.exists():
            return p

    cands = sorted(workdir.glob("*.save/data-file-schema.xml"))
    if len(cands) == 1:
        return cands[0]
    return None

def parse_efermi_etot_from_data_file_schema(xml_path: Path) -> Dict[str, Optional[float]]:
    """
    Extract:
      <fermi_energy> (Hartree) -> eV
      <etot> (Hartree) -> eV
    """
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
    except Exception:
        return {}

    def find_text(tag_name: str) -> Optional[str]:
        for el in root.iter():
            t = el.tag
            if isinstance(t, str) and t.endswith(tag_name):
                return el.text
        return None

    fermi_ha = _safe_float_from_xml_text(find_text("fermi_energy"))
    etot_ha = _safe_float_from_xml_text(find_text("etot"))

    out: Dict[str, Optional[float]] = {}
    if fermi_ha is not None:
        out["efermi_ev"] = fermi_ha * HARTREE_TO_EV
    if etot_ha is not None:
        out["total_energy_ev"] = etot_ha * HARTREE_TO_EV
    return out


# -----------------------------
# Float extraction helper
# -----------------------------
def _extract_floats(line: str) -> List[float]:
    return [float(x) for x in NUM_RX.findall(line)]

# -----------------------------
# QE input parsing
# -----------------------------
def _clean_unit(u: Optional[str]) -> Optional[str]:
    if not u:
        return None
    return u.strip().lower()

def _guess_prefix_from_flfrc_value(v: str) -> Optional[str]:
    """
    v like 'Si.fc' or '/path/to/Si.fc' -> 'Si'
    """
    if not v:
        return None
    base = Path(v.strip().strip("'").strip('"')).name  # Si.fc
    if not base:
        return None
    token = base.split(".", 1)[0].strip()
    return token if token else None

def parse_qe_input(path: Path) -> Dict[str, Any]:
    txt = path.read_text(errors="ignore")
    d: Dict[str, Any] = {"in_path": str(path.resolve())}

    m = CONTROL_CALC_RX.search(txt)
    if m:
        d["calculation"] = (m.group(1) or m.group(2)).strip().lower()

    m = PREFIX_RX.search(txt)
    if m:
        d["prefix"] = (m.group(1) or m.group(2)).strip()

    # Fallback for q2r/matdyn: infer prefix from flfrc='Si.fc'
    if not d.get("prefix"):
        m2 = FLFRC_RX.search(txt)
        if m2:
            p = _guess_prefix_from_flfrc_value(m2.group(1))
            if p:
                d["prefix"] = p

    m = IBRAV_RX.search(txt)
    if m:
        try:
            d["ibrav"] = int(m.group(1))
        except Exception:
            pass

    m = NAT_RX_IN.search(txt)
    if m:
        try:
            d["nat"] = int(m.group(1))
        except Exception:
            pass

    m = NTYP_RX_IN.search(txt)
    if m:
        try:
            d["ntyp"] = int(m.group(1))
        except Exception:
            pass

    m = ASSUME_ISO_RX.search(txt)
    if m:
        d["assume_isolated"] = m.group(1).strip()

    lines = txt.splitlines()
    n = len(lines)

    # ATOMIC_SPECIES
    species = []
    i = 0
    while i < n:
        if re.match(r"^\s*ATOMIC_SPECIES\s*$", lines[i], re.I):
            i += 1
            while i < n:
                ln = lines[i].strip()
                if not ln:
                    i += 1
                    continue
                if re.match(r"^\s*(ATOMIC_POSITIONS|K_POINTS|CELL_PARAMETERS)\b", ln, re.I):
                    break
                parts = ln.split()
                if len(parts) >= 3:
                    try:
                        species.append({"element": parts[0], "mass": float(parts[1]), "pseudo": parts[2]})
                    except Exception:
                        pass
                i += 1
            break
        i += 1
    if species:
        d["atomic_species"] = species

    # ATOMIC_POSITIONS
    pos_hdr_idx = None
    pos_unit = None
    for i, ln in enumerate(lines):
        m = ATOMIC_POSITIONS_HDR.match(ln)
        if m:
            pos_hdr_idx = i
            pos_unit = _clean_unit(m.group(1) or m.group(2) or m.group(3) or "alat")
            break
    if pos_hdr_idx is not None:
        atoms = []
        nat = d.get("nat")
        i = pos_hdr_idx + 1
        while i < n:
            ln = lines[i].strip()
            if not ln:
                if nat and len(atoms) >= nat:
                    break
                i += 1
                continue
            if re.match(r"^\s*(K_POINTS|CELL_PARAMETERS|ATOMIC_SPECIES)\b", ln, re.I):
                break
            parts = ln.split()
            if len(parts) >= 4:
                try:
                    atoms.append({"element": parts[0], "coord": [float(parts[1]), float(parts[2]), float(parts[3])]})
                except Exception:
                    break
            i += 1
        if atoms:
            d["atomic_positions"] = {"unit": pos_unit, "atoms": atoms}

    # CELL_PARAMETERS
    cell_hdr_idx = None
    cell_unit = None
    for i, ln in enumerate(lines):
        m = CELL_PARAMETERS_HDR.match(ln)
        if m:
            cell_hdr_idx = i
            cell_unit = _clean_unit(m.group(1) or m.group(2) or m.group(3) or "alat")
            break
    if cell_hdr_idx is not None:
        cell = []
        i = cell_hdr_idx + 1
        while i < n and len(cell) < 3:
            ln = lines[i].strip()
            if not ln:
                i += 1
                continue
            parts = ln.split()
            if len(parts) < 3:
                break
            try:
                cell.append([float(parts[0]), float(parts[1]), float(parts[2])])
            except Exception:
                break
            i += 1
        if len(cell) == 3:
            d["cell_parameters"] = {"unit": cell_unit, "lattice": cell}

    # K_POINTS (automatic)
    k_hdr_idx = None
    k_mode = None
    for i, ln in enumerate(lines):
        m = K_POINTS_HDR.match(ln)
        if m:
            k_hdr_idx = i
            k_mode = _clean_unit(m.group(1) or m.group(2) or m.group(3) or "")
            break
    if k_hdr_idx is not None:
        i = k_hdr_idx + 1
        while i < n and not lines[i].strip():
            i += 1
        if i < n:
            ln = lines[i].strip()
            parts = ln.split()
            if (k_mode == "automatic") and len(parts) >= 6:
                try:
                    d["k_points"] = {
                        "mode": "automatic",
                        "grid": [int(parts[0]), int(parts[1]), int(parts[2])],
                        "shift": [int(parts[3]), int(parts[4]), int(parts[5])],
                    }
                except Exception:
                    pass
            else:
                d["k_points"] = {"mode": k_mode or "unknown", "first_line": ln}

    return d

def choose_best_qe_in(workdir: Path, out_name: str) -> Optional[Path]:
    ins = sorted([p for p in workdir.iterdir() if p.is_file() and p.suffix == ".in"])
    if not ins:
        return None
    stem = Path(out_name).stem
    cand = workdir / f"{stem}.in"
    if cand.exists():
        return cand
    for name in ("scf.in", "nscf.in", "bs.in"):
        cand2 = workdir / name
        if cand2.exists():
            return cand2
    return ins[0]

# -----------------------------
# EPW input parsing
# -----------------------------
EPW_KV_RX = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*(?:\(\s*\d+\s*\))?)\s*=\s*(.*?)\s*(?:!.*)?$", re.M)

def _parse_fortran_value(v: str) -> Any:
    s = v.strip().rstrip(",")
    if not s:
        return None

    # string
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]

    sl = s.lower()

    # logical
    if sl in (".true.", "true", "t"):
        return True
    if sl in (".false.", "false", "f"):
        return False

    try:
        if re.fullmatch(RE_FLOAT, s):
            if re.fullmatch(r"[-+]?\d+", s):
                return int(s)
            return float(s)
    except Exception:
        pass

    return s

def parse_epw_input(path: Path) -> Dict[str, Any]:
    txt = path.read_text(errors="ignore")
    d: Dict[str, Any] = {"in_path": str(path.resolve())}

    m = re.search(r"(?is)&\s*inputepw\b(.*?)(?:\n\s*/\s*\n|/\s*$)", txt)
    block = m.group(1) if m else txt

    params: Dict[str, Any] = {}
    for mm in EPW_KV_RX.finditer(block):
        k = mm.group(1).strip()
        v = mm.group(2).strip()
        params[k.lower()] = _parse_fortran_value(v)

    d["params"] = params
    if "prefix" in params:
        d["prefix"] = params.get("prefix")
    return d

def find_same_stem_in(workdir: Path, out_path: Path) -> Optional[Path]:
    stem = out_path.stem
    cand = workdir / f"{stem}.in"
    return cand if cand.exists() else None

def _get_int3(params: Dict[str, Any], base: str) -> Optional[List[int]]:
    k1, k2, k3 = f"{base}1", f"{base}2", f"{base}3"
    if k1 in params and k2 in params and k3 in params:
        try:
            return [int(params[k1]), int(params[k2]), int(params[k3])]
        except Exception:
            return None
    return None

def build_epw_extracted_params(epw_in: Dict[str, Any],
                              stem: str,
                              has_ele: bool,
                              has_hole: bool) -> Dict[str, Any]:
    p = epw_in.get("params", {})
    out: Dict[str, Any] = {}

    nk = _get_int3(p, "nk")
    nq = _get_int3(p, "nq")
    nkf = _get_int3(p, "nkf")
    nqf = _get_int3(p, "nqf")

    if nk is not None:
        out["nk"] = nk
    if nq is not None:
        out["nq"] = nq
    if nkf is not None:
        out["nkf"] = nkf
    if nqf is not None:
        out["nqf"] = nqf

    for key in ("lpolar", "system_2d", "int_mob", "scattering", "carrier", "iterative_bte", "ncarrier"):
        if key in p:
            out[key] = p[key]

    if "fsthick" in p:
        if (not has_ele) and (not has_hole):
            out[f"{stem}_fsthick"] = p["fsthick"]
        else:
            if has_ele:
                out["ele_fsthick"] = p["fsthick"]
            if has_hole:
                out["hole_fsthick"] = p["fsthick"]

    if "fermi_energy" in p:
        if has_ele:
            out["ele_epw_input_fermi_energy"] = p["fermi_energy"]
        if has_hole:
            out["hole_epw_input_fermi_energy"] = p["fermi_energy"]

    return out

# -----------------------------
# EPW mobility parsing
# -----------------------------
def _is_sep_line(s: str) -> bool:
    t = s.strip()
    return t.startswith("=") and len(t) >= 20

def has_mobility_block(full_text: str, which: str) -> bool:
    if which == "electron":
        return ELEC_HEADER_KEY.lower() in full_text.lower()
    if which == "hole":
        return HOLE_HEADER_KEY.lower() in full_text.lower()
    return False

def parse_last_mobility_table(full_text: str, carrier: str) -> List[Dict[str, Any]]:
    key = ELEC_HEADER_KEY if carrier == "electron" else HOLE_HEADER_KEY

    low = full_text.lower()
    idx = low.rfind(key.lower())
    if idx < 0:
        return []

    sub = full_text[idx:]
    lines = sub.splitlines()

    start_i = None
    for i, ln in enumerate(lines):
        if _is_sep_line(ln):
            start_i = i + 1
            break
    if start_i is None:
        return []

    rows: List[Dict[str, Any]] = []
    i = start_i

    while i < len(lines):
        ln = lines[i]

        if "max error" in ln.lower():
            break

        f1_probe = _extract_floats(ln)
        if len(f1_probe) >= 3:
            if i + 2 >= len(lines):
                break

            l1, l2, l3 = lines[i], lines[i + 1], lines[i + 2]
            f1, f2, f3 = _extract_floats(l1), _extract_floats(l2), _extract_floats(l3)

            if len(f1) < 3:
                i += 1
                continue

            temp_K = f1[0]
            fermi_ev = f1[1]
            density_cm2 = f1[2]

            if len(f1) >= 3 and len(f2) >= 3 and len(f3) >= 3:
                row1 = f1[-3:]
                row2 = f2[-3:]
                row3 = f3[-3:]
                mu_x = row1[0]
                mu_y = row2[1]
            else:
                row1 = row2 = row3 = None
                mu_x = mu_y = None

            rows.append({
                "carrier": carrier,
                "temp_K": temp_K,
                "fermi_ev": fermi_ev,
                "density_cm2": density_cm2,
                "mu_x_cm2Vs": mu_x,
                "mu_y_cm2Vs": mu_y,
                "tensor_3x3": [row1, row2, row3],
                "table_key": key,
            })
            i += 3
            continue

        i += 1

    return rows

# -----------------------------
# DB operations
# -----------------------------
def get_run_id_by_hash(conn: sqlite3.Connection, content_hash: str) -> Optional[int]:
    cur = conn.cursor()
    cur.execute("SELECT id FROM runs WHERE content_hash=?", (content_hash,))
    row = cur.fetchone()
    return int(row[0]) if row else None

def upsert_file_ref(conn: sqlite3.Connection, run_id: int, out_path: Path):
    st = out_path.stat()
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    mtime = datetime.utcfromtimestamp(st.st_mtime).isoformat(timespec="seconds") + "Z"
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO file_refs (run_id, out_path, workdir, mtime_utc, first_seen_utc, last_seen_utc)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id, out_path) DO UPDATE SET
          workdir=excluded.workdir,
          mtime_utc=excluded.mtime_utc,
          last_seen_utc=excluded.last_seen_utc
        """,
        (run_id, str(out_path.resolve()), str(out_path.parent.resolve()), mtime, now, now),
    )
    conn.commit()

def insert_run(conn: sqlite3.Connection, payload: Dict[str, Any]) -> int:
    cols = list(payload.keys())
    qs = ", ".join(["?"] * len(cols))
    col_sql = ", ".join(cols)

    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO runs ({col_sql}) VALUES ({qs})",
        [payload[c] for c in cols],
    )
    conn.commit()
    return int(cur.lastrowid)

def replace_mobility(conn: sqlite3.Connection, run_id: int, rows: List[Dict[str, Any]]):
    cur = conn.cursor()
    cur.execute("DELETE FROM mobility WHERE run_id=?", (run_id,))
    if rows:
        cur.executemany(
            """
            INSERT INTO mobility
            (run_id, carrier, temp_K, fermi_ev, density_cm2, mu_x_cm2Vs, mu_y_cm2Vs, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    r["carrier"],
                    r["temp_K"],
                    r.get("fermi_ev"),
                    r.get("density_cm2"),
                    r.get("mu_x_cm2Vs"),
                    r.get("mu_y_cm2Vs"),
                    json.dumps(r, ensure_ascii=False),
                )
                for r in rows
            ],
        )
    conn.commit()

# -----------------------------
# JSON export helpers
# -----------------------------
def fetch_run_as_dict(conn: sqlite3.Connection, run_id: int) -> Dict[str, Any]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT * FROM runs WHERE id=?", (run_id,))
    run = cur.fetchone()
    if run is None:
        raise ValueError(f"run_id not found: {run_id}")

    run_d = dict(run)

    cur.execute("SELECT * FROM file_refs WHERE run_id=? ORDER BY last_seen_utc DESC", (run_id,))
    run_d["file_refs"] = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT * FROM mobility WHERE run_id=? ORDER BY carrier, temp_K", (run_id,))
    mob = []
    for r in cur.fetchall():
        d = dict(r)
        try:
            d["raw"] = json.loads(d["raw_json"]) if d.get("raw_json") else None
        except Exception:
            d["raw"] = None
        mob.append(d)
    run_d["mobility"] = mob

    if run_d.get("meta_json"):
        try:
            run_d["meta"] = json.loads(run_d["meta_json"])
        except Exception:
            run_d["meta"] = None
    else:
        run_d["meta"] = None

    if run_d.get("structure_json"):
        try:
            run_d["structure_obj"] = json.loads(run_d["structure_json"])
        except Exception:
            run_d["structure_obj"] = None
    else:
        run_d["structure_obj"] = None

    if run_d.get("epw_params_json"):
        try:
            run_d["epw_params_obj"] = json.loads(run_d["epw_params_json"])
        except Exception:
            run_d["epw_params_obj"] = None
    else:
        run_d["epw_params_obj"] = None

    return run_d

def export_db_to_json(conn: sqlite3.Connection) -> Dict[str, Any]:
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT id FROM runs ORDER BY id")
    ids = [int(r["id"]) for r in cur.fetchall()]
    return {
        "schema": "qe_epw.sqlite.v4_epw_input_params",
        "exported_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "runs": [fetch_run_as_dict(conn, rid) for rid in ids],
    }

# -----------------------------
# Exclude helpers
# -----------------------------
def _normalize_excludes(root_path: Path, excludes: Optional[List[str]]) -> List[Path]:
    out: List[Path] = []
    if not excludes:
        return out

    for x in excludes:
        if not x:
            continue
        p = Path(x)
        if not p.is_absolute():
            p = (root_path / p)
        try:
            out.append(p.resolve())
        except Exception:
            out.append(Path(os.path.abspath(str(p))))

    uniq: List[Path] = []
    seen = set()
    for p in out:
        s = str(p)
        if s not in seen:
            seen.add(s)
            uniq.append(p)
    return uniq

def _is_under_any(path: Path, excluded_roots: List[Path]) -> bool:
    if not excluded_roots:
        return False
    try:
        rp = path.resolve()
    except Exception:
        rp = Path(os.path.abspath(str(path)))

    for ex in excluded_roots:
        if rp == ex:
            return True
        if ex in rp.parents:
            return True
    return False

# -----------------------------
# Structure fallback helpers (NEW)
# -----------------------------
def _norm_prefix(p: Optional[str]) -> Optional[str]:
    """Normalize prefix for matching: strip quotes/space and lower."""
    if p is None:
        return None
    s = str(p).strip()
    # remove wrapping quotes repeatedly
    for _ in range(2):
        if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
            s = s[1:-1].strip()
    s = s.strip()
    return s.lower() if s else None
def _qe_in_has_structure(qe_in_data: Optional[Dict[str, Any]]) -> bool:
    if not qe_in_data:
        return False
    ap = qe_in_data.get("atomic_positions")
    cp = qe_in_data.get("cell_parameters")
    if isinstance(ap, dict) and ap.get("atoms"):
        return True
    if isinstance(cp, dict) and cp.get("lattice"):
        return True
    return False

def _walk_find_scf_in_with_prefix(
    search_root: Path,
    want_prefix_norm: str,
    excluded_roots: List[Path],
    prune_roots: List[Path],
    debug: bool = False,
) -> Optional[Path]:
    """
    Search within search_root subtree for scf.in where parsed prefix matches want_prefix_norm.
    Prune:
      - global excluded_roots
      - prune_roots (already searched subtrees)
    """
    search_root = search_root.resolve()

    def should_prune_dir(d: Path) -> bool:
        if _is_under_any(d, excluded_roots):
            return True
        if _is_under_any(d, prune_roots):
            return True
        return False

    for dirpath, dirnames, filenames in os.walk(search_root):
        dpath = Path(dirpath)

        # prune dirs
        keep = []
        for dn in dirnames:
            cand = dpath / dn
            if should_prune_dir(cand):
                if debug:
                    print(f"    [PRUNE_STRUCT_SEARCH] {cand}", flush=True)
                continue
            keep.append(dn)
        dirnames[:] = keep

        if should_prune_dir(dpath):
            continue

        if "scf.in" in filenames:
            cand = dpath / "scf.in"
            try:
                qe_in = parse_qe_input(cand)
                pfx = _norm_prefix(qe_in.get("prefix"))
                if pfx == want_prefix_norm:
                    return cand
            except Exception as e:
                if debug:
                    print(f"    [WARN] failed parse scf.in {cand}: {e}", flush=True)
                continue

    return None

def find_structure_from_nearby_scf(
    start_dir: Path,
    prefix: str,
    excluded_roots: List[Path],
    max_up: int = 3,
    debug: bool = False,
    cache: Optional[Dict[Tuple[str, str], Optional[str]]] = None,
) -> Optional[Path]:
    """
    Starting from start_dir, search start_dir subtree first (for scf.in with same prefix),
    then go up one level and search that subtree excluding the previously searched subtree,
    and so on up to max_up levels.

    Returns Path to scf.in if found, else None.

    cache key: (start_dir_resolved, prefix_norm) -> scf_in_path_or_None
    """
    pfxn = _norm_prefix(prefix)
    if not pfxn:
        return None

    sdir = start_dir.resolve()
    cache_key = (str(sdir), pfxn)
    if cache is not None and cache_key in cache:
        v = cache[cache_key]
        return Path(v) if v else None

    prune_roots: List[Path] = []
    cur = sdir

    found: Optional[Path] = None
    for level in range(max_up + 1):
        if debug:
            print(f"    [STRUCT_SEARCH] level={level} root={cur} want_prefix={pfxn}", flush=True)

        cand = _walk_find_scf_in_with_prefix(
            search_root=cur,
            want_prefix_norm=pfxn,
            excluded_roots=excluded_roots,
            prune_roots=prune_roots,
            debug=debug,
        )
        if cand:
            found = cand
            break

        # after searching cur subtree, add it to prune list for next (upper) search
        prune_roots.append(cur)

        # go up
        if cur.parent == cur:
            break
        cur = cur.parent

    if cache is not None:
        cache[cache_key] = str(found) if found else None
    return found

# -----------------------------
# Scan to DB (exclude + pruning + progress + structure fallback)
# -----------------------------
def scan_to_db(root: str, db: str, debug: bool = False, excludes: Optional[List[str]] = None):
    root_path = Path(root).resolve()
    db_path = Path(db).resolve()
    conn = init_db(db_path)

    excluded_roots = _normalize_excludes(root_path, excludes)

    if excluded_roots:
        print("[INFO] exclude roots:", flush=True)
        for ex in excluded_roots:
            print(f"  - {ex}", flush=True)

    # cache for structure search to avoid repeated expensive walking
    scf_search_cache: Dict[Tuple[str, str], Optional[str]] = {}

    # pass 1: count all paths after pruning + count *.out
    total_all = 0
    out_count = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        dpath = Path(dirpath)

        # prune directories early
        keep_dirs = []
        for dn in dirnames:
            cand = dpath / dn
            if _is_under_any(cand, excluded_roots):
                if debug:
                    print(f"[PRUNE] {cand}", flush=True)
                continue
            keep_dirs.append(dn)
        dirnames[:] = keep_dirs

        if _is_under_any(dpath, excluded_roots):
            continue

        total_all += 1  # count directory

        for fn in filenames:
            fp = dpath / fn
            if _is_under_any(fp, excluded_roots):
                continue
            total_all += 1
            if fp.suffix == ".out":
                out_count += 1

    print(f"[INFO] total paths (files+dirs) under root (after excludes): {total_all}", flush=True)
    print(f"[INFO] total .out files under root (after excludes): {out_count}", flush=True)

    if out_count == 0:
        print("[INFO] no *.out found (after excludes), skip.", flush=True)
        conn.close()
        return

    # pass 2: iterate again for progress
    idx = 0

    for dirpath, dirnames, filenames in os.walk(root_path):
        dpath = Path(dirpath)

        # prune directories again
        keep_dirs = []
        for dn in dirnames:
            cand = dpath / dn
            if _is_under_any(cand, excluded_roots):
                continue
            keep_dirs.append(dn)
        dirnames[:] = keep_dirs

        if _is_under_any(dpath, excluded_roots):
            continue

        idx += 1
        pfx = f"[{idx}/{total_all}]"
        if debug:
            print(f"{pfx} [DIR] {dpath}", flush=True)

        for fn in filenames:
            fp = dpath / fn
            if _is_under_any(fp, excluded_roots):
                continue

            idx += 1
            pfx = f"[{idx}/{total_all}]"

            if fp.suffix != ".out":
                if debug:
                    print(f"{pfx} [SKIP:not out] {fp}", flush=True)
                continue

            out_path = fp

            try:
                if debug:
                    print(f"{pfx} scanning .out: {out_path}", flush=True)

                tail = read_tail_text(out_path, tail_bytes=40000)
                marker = detect_finished_marker(tail)
                if not marker:
                    if debug:
                        print(f"{pfx} [SKIP:not finished] {out_path}", flush=True)
                    continue

                chash = file_fingerprint_sha256(out_path)
                existing_id = get_run_id_by_hash(conn, chash)
                if existing_id is not None:
                    upsert_file_ref(conn, existing_id, out_path)
                    if debug:
                        print(f"{pfx} [DEDUP] {out_path.name} -> existing run_id={existing_id}", flush=True)
                    continue

                st = out_path.stat()
                workdir = out_path.parent
                code = code_from_marker(marker)

                full_text = out_path.read_text(errors="ignore")
                head = full_text[:250000]

                calc_type = guess_calc_type_from_out(out_path, head)
                scalars = parse_scalars_from_out(head, calc_type)

                # -----------------------------
                # Structure / prefix fields
                # -----------------------------
                qe_in_path = None
                qe_in_data = None
                calc_from_in = None
                prefix = None
                structure_name = None
                structure_json = None

                epw_in_path = None
                epw_params_json = None

                # QE (includes scf/nscf/bs/ph/q2r/matdyn/pwscf)
                if code == "qe":
                    qe_in_path = choose_best_qe_in(workdir, out_path.name)
                    if qe_in_path:
                        qe_in_data = parse_qe_input(qe_in_path)
                        calc_from_in = qe_in_data.get("calculation")
                        prefix = qe_in_data.get("prefix")
                        if calc_from_in:
                            # only override calc_type for QE PW-like runs; harmless otherwise
                            calc_type = calc_from_in

                        # store structure only if present in this input
                        if _qe_in_has_structure(qe_in_data):
                            structure_name = prefix
                            structure_json = json.dumps(qe_in_data, ensure_ascii=False)

                # EPW
                if code == "epw":
                    has_ele = has_mobility_block(full_text, "electron")
                    has_hole = has_mobility_block(full_text, "hole")

                    if (not has_ele) and (not has_hole):
                        calc_type = "epw1"
                    elif has_ele and (not has_hole):
                        calc_type = "epw2"
                    elif has_hole and (not has_ele):
                        calc_type = "epw3"
                    else:
                        calc_type = "epw23"

                    epw_in_path = find_same_stem_in(workdir, out_path)
                    if epw_in_path:
                        epw_in = parse_epw_input(epw_in_path)
                        prefix = epw_in.get("prefix") or prefix
                        if structure_name is None:
                            structure_name = prefix

                        epw_extracted = build_epw_extracted_params(
                            epw_in=epw_in,
                            stem=out_path.stem,
                            has_ele=has_ele,
                            has_hole=has_hole,
                        )
                        epw_extracted["epw_input_prefix"] = epw_in.get("prefix")
                        epw_extracted["epw_out_has_ele_mobility_block"] = bool(has_ele)
                        epw_extracted["epw_out_has_hole_mobility_block"] = bool(has_hole)
                        epw_params_json = json.dumps(epw_extracted, ensure_ascii=False)

                        if debug:
                            print(f"{pfx}    [DEBUG] epw_in: {epw_in_path.name} extracted_keys={list(epw_extracted.keys())}", flush=True)
                
                # -----------------------------
                # NEW(2): Structure fallback without prefix
                # If user uploads epw.out + scf.in (but no epw.in), prefix may be None.
                # In that case, just pick a best .in in the same workdir and reuse its structure if present.
                # -----------------------------
                if structure_json is None:
                    try:
                        cand_in = choose_best_qe_in(workdir, out_path.name)
                        if cand_in:
                            cand_data = parse_qe_input(cand_in)
                            if _qe_in_has_structure(cand_data):
                                structure_json = json.dumps(cand_data, ensure_ascii=False)
                                if structure_name is None:
                                    structure_name = cand_data.get("prefix") or structure_name
                                if qe_in_path is None:
                                    qe_in_path = cand_in
                                if prefix is None:
                                    prefix = cand_data.get("prefix")
                                if debug:
                                    print(f"{pfx}    [STRUCT_OK_NOPREFIX] from in: {cand_in}", flush=True)
                    except Exception as e:
                        if debug:
                            print(f"{pfx}    [STRUCT_FAIL_NOPREFIX] err={e}", flush=True)
                
                # -----------------------------
                # NEW: Structure fallback via nearby scf.in using prefix
                # For: ph/q2r/matdyn + all EPW + any future type with no structure_json
                # -----------------------------
                if (structure_json is None) and prefix:
                    scf_in = find_structure_from_nearby_scf(
                        start_dir=workdir,
                        prefix=str(prefix),
                        excluded_roots=excluded_roots,
                        max_up=3,
                        debug=debug,
                        cache=scf_search_cache,
                    )
                    if scf_in:
                        try:
                            scf_data = parse_qe_input(scf_in)
                            if _qe_in_has_structure(scf_data):
                                structure_json = json.dumps(scf_data, ensure_ascii=False)
                                if structure_name is None:
                                    structure_name = scf_data.get("prefix") or prefix
                                # 把 qe_in_path 指向真正提供结构的 scf.in（更符合你的目标）
                                qe_in_path = scf_in
                                if debug:
                                    print(f"{pfx}    [STRUCT_OK] from scf.in: {scf_in}", flush=True)
                            else:
                                if debug:
                                    print(f"{pfx}    [STRUCT_FAIL] scf.in found but has no structure: {scf_in}", flush=True)
                        except Exception as e:
                            if debug:
                                print(f"{pfx}    [STRUCT_FAIL] parse scf.in error: {scf_in} err={e}", flush=True)
                                
                # -----------------------------
                # NEW: efermi / etot from prefix.save/data-file-schema.xml (Hartree -> eV)
                # -----------------------------
                xml_path = find_data_file_schema_xml(workdir, str(prefix) if prefix is not None else None)
                if xml_path:
                    xml_scalars = parse_efermi_etot_from_data_file_schema(xml_path)
                    if xml_scalars:
                        scalars.update(xml_scalars)
                        if debug:
                            print(f"{pfx}    [XML] {xml_path} -> {xml_scalars}", flush=True)
                else:
                    if debug:
                        print(f"{pfx}    [XML] not found for prefix={prefix} under {workdir}", flush=True)

                payload = {
                    "content_hash": chash,
                    "structure": structure_name,
                    "code": code,
                    "calc_type": calc_type,
                    "out_path": str(out_path.resolve()),
                    "workdir": str(workdir.resolve()),
                    "mtime_utc": datetime.utcfromtimestamp(st.st_mtime).isoformat(timespec="seconds") + "Z",
                    "parsed_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    "finished_marker": marker,

                    "nat": None, "ntyp": None, "nelec": None, "nbnd": None,
                    "ecutwfc_ry": None, "ecutrho_ry": None,
                    "alat_au": None, "cell_volume_au3": None,
                    "efermi_ev": None,
                    "total_energy_ev": None,

                    "qgrid": None, "nqpoints": None,

                    "qe_in_path": str(qe_in_path.resolve()) if qe_in_path else None,
                    "calc_from_in": calc_from_in,
                    "prefix": str(prefix) if prefix is not None else None,
                    "structure_json": structure_json,

                    "epw_in_path": str(epw_in_path.resolve()) if epw_in_path else None,
                    "epw_params_json": epw_params_json,

                    "meta_json": json.dumps({"file": out_path.name, "size_bytes": st.st_size}, ensure_ascii=False),
                }
                payload.update(scalars)

                run_id = insert_run(conn, payload)
                upsert_file_ref(conn, run_id, out_path)

                if code == "epw":
                    elec_rows = parse_last_mobility_table(full_text, "electron")
                    hole_rows = parse_last_mobility_table(full_text, "hole")
                    if debug:
                        print(f"{pfx}    [DEBUG] {out_path.name}: electron_rows={len(elec_rows)} hole_rows={len(hole_rows)}", flush=True)
                    replace_mobility(conn, run_id, elec_rows + hole_rows)

                if debug and code == "qe" and qe_in_data:
                    print(f"{pfx}    [DEBUG] qe_in: calc={calc_from_in} prefix={prefix} has_structure={_qe_in_has_structure(qe_in_data)}", flush=True)

                print(
                    f"{pfx} [OK] {out_path.name} -> run_id={run_id} hash={chash[:12]} "
                    f"structure={structure_name} code={code} type={calc_type}",
                    flush=True
                )

            except Exception as e:
                print(f"{pfx} [FAIL] {out_path}: {e}", flush=True)

    conn.close()
    print(f"DB saved: {Path(db).resolve()}", flush=True)

# -----------------------------
# CLI
# -----------------------------
def _is_int_str(s: str) -> bool:
    try:
        int(s)
        return True
    except Exception:
        return False

def main():
    import argparse

    ap = argparse.ArgumentParser(
        description="Parse QE/EPW *.out -> SQLite (dedup by content hash), store QE structure from *.in, "
                    "parse EPW params from epw*.in, support exclude pruning and JSON export/printing. "
                    "Also supports structure fallback: use prefix to locate nearby scf.in and reuse its structure."
    )

    ap.add_argument("args", nargs="*", help="ROOT to scan and/or RUN_ID (depending on --json usage).")
    ap.add_argument("--db", default=None, help="SQLite db file path (default: qe_epw.sqlite).")
    ap.add_argument("--debug", action="store_true", help="Print debug info.")
    ap.add_argument("--exclude", action="append", default=[],
                    help="Exclude paths (can be used multiple times). If relative, it is treated as relative to ROOT.")
    ap.add_argument("--json", nargs="?", const=True, default=None,
                    help="JSON modes: "
                         "--db X.sqlite RUN_ID --json        (print one run). "
                         "--db X.sqlite --json out.json      (export whole DB).")

    ns = ap.parse_args()
    db_path = Path(ns.db if ns.db else "qe_epw.sqlite").resolve()

    # print one run
    if ns.json is True:
        run_ids = [int(x) for x in ns.args if _is_int_str(x)]
        if not run_ids:
            raise SystemExit("ERROR: print-one-run mode requires RUN_ID positional, e.g. --db qe_epw.sqlite 1 --json")
        run_id = run_ids[-1]
        conn = connect_db_existing(db_path)
        data = fetch_run_as_dict(conn, run_id)
        conn.close()
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return

    # export db to json
    if isinstance(ns.json, str) and len(ns.args) == 0:
        out_json = Path(ns.json).resolve()
        conn = connect_db_existing(db_path)
        data = export_db_to_json(conn)
        conn.close()
        out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[OK] exported DB -> {out_json}")
        return

    # scan to sqlite
    roots = [x for x in ns.args if not _is_int_str(x)]
    if not roots:
        raise SystemExit("ERROR: please provide ROOT directory to scan.")
    for root in roots:
    	scan_to_db(root, str(db_path), debug=ns.debug, excludes=ns.exclude)

if __name__ == "__main__":
    main()

