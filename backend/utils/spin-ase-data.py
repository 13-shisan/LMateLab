#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# backend/utils/spin-ase-data.py

import os
import re
import json
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Tuple, Optional

import numpy as np
from ase.io import read
from ase.db import connect
from ase import Atoms
from ase.calculators.singlepoint import SinglePointCalculator

from pymatgen.io.vasp import Vasprun, Locpot
from pymatgen.io.vasp.outputs import Eigenval
from pymatgen.io.ase import AseAtomsAdaptor

# 可选：对称性（空间群/反演）解析
try:
    import spglib  # type: ignore
except Exception:
    spglib = None

print("PID:", os.getpid(), flush=True)

# ============================================================
# Manifest（成功/失败记录）与内容指纹 signature
# ============================================================

def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

def manifest_path_from_db_path(db_path: str) -> str:
    # 与 db_path 强绑定：xxx.db -> xxx.db.manifest.jsonl
    return db_path + ".manifest.jsonl"

def load_manifest_map(manifest_path: str) -> Dict[str, Dict[str, Any]]:
    """
    读取 jsonl manifest，返回 dict: signature -> last_record
    """
    m: Dict[str, Dict[str, Any]] = {}
    if not os.path.isfile(manifest_path):
        return m
    try:
        with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    sig = rec.get("signature", None)
                    if isinstance(sig, str) and sig:
                        m[sig] = rec
                except Exception:
                    continue
    except Exception:
        return m
    return m

def load_manifest_map_multi(paths: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    合并多个 manifest jsonl 为 signature->record 的 map。
    策略：
      - 同一 signature：只要任一来源为 status=ok，则最终视为 ok（除非 --force）
      - 否则取“最后出现/更新”的记录（load_manifest_map 本身是 last write wins）
    """
    merged: Dict[str, Dict[str, Any]] = {}

    for p in (paths or []):
        if not p:
            continue
        ap = os.path.abspath(p)
        if not os.path.isfile(ap) or os.path.getsize(ap) == 0:
            continue

        m = load_manifest_map(ap)
        for sig, rec in m.items():
            if not sig:
                continue

            prev = merged.get(sig)
            if prev is None:
                merged[sig] = rec
                continue

            # ok 优先：出现过 ok 就保持 ok
            if prev.get("status") == "ok":
                continue
            if rec.get("status") == "ok":
                merged[sig] = rec
                continue

            # 都非 ok：用新覆盖旧（近似“更新的优先”）
            merged[sig] = rec

    return merged

def append_manifest_record(manifest_path: str, record: Dict[str, Any]) -> None:
    """
    追加写一行 jsonl（可中断可恢复）
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(manifest_path)), exist_ok=True)
    except Exception:
        pass

    with open(manifest_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.flush()

def _choose_signature_file(calc_dir: str) -> Optional[str]:
    """
    选择用于计算内容指纹的代表文件（优先更稳定/更能代表结果的）。
    """
    candidates = [
        "vasprun.xml.gz",
        "vasprun.xml",
        "OUTCAR",
        "XDATCAR",
        "OSZICAR",
        "EIGENVAL",
        "LOCPOT",
    ]
    for name in candidates:
        p = os.path.join(calc_dir, name)
        if os.path.isfile(p):
            return p
    return None

def _fast_file_fingerprint(path: str, head_bytes: int = 1024 * 1024, tail_bytes: int = 1024 * 1024) -> str:
    """
    快速文件指纹：hash(文件大小 + 头部N字节 + 尾部N字节)
    比全文件 sha256 快很多，适合 OUTCAR/vasprun 这种大文件。
    """
    st = os.stat(path)
    size = st.st_size

    h = hashlib.sha256()
    h.update(str(size).encode("utf-8"))
    h.update(b"|")

    with open(path, "rb") as f:
        head = f.read(head_bytes)
        h.update(head)

        if size > tail_bytes:
            try:
                f.seek(max(0, size - tail_bytes))
                tail = f.read(tail_bytes)
                h.update(tail)
            except Exception:
                pass

    return h.hexdigest()

def calc_dir_signature(calc_dir: str) -> Optional[str]:
    """
    对一个计算目录生成“内容签名”：
    - 路径改名/移动但文件内容不变 -> signature 不变
    """
    sig_file = _choose_signature_file(calc_dir)
    if sig_file is None:
        return None
    try:
        fp = _fast_file_fingerprint(sig_file)
        base = os.path.basename(sig_file)
        return f"vaspdir:v1:{base}:{fp}"
    except Exception:
        return None

def read_targets_file(path: str) -> List[str]:
    """
    读取 targets 文件（chunk_XXX.txt / targets.txt）：
    - 每行一个目录
    - 允许空行与 # 注释
    - 去重但保持顺序
    """
    out: List[str] = []
    seen = set()
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = (line or "").strip()
            if not s or s.startswith("#"):
                continue
            d = os.path.abspath(s)
            if d not in seen:
                out.append(d)
                seen.add(d)
    return out

# ============================================================
# 基础工具
# ============================================================

def load_incar_params(path: Optional[str]) -> Dict[str, Any]:
    """
    通用 INCAR 解析：
    - 支持同一行多个 KEY = VALUE（常见用 ; 分隔）
    - VALUE 只取第一个 token，避免 '0 ; SIGMA=0.02' 或 '100.;' 这种导致类型转换失败
    - 自动转 bool/int/float，否则保留字符串 token
    """
    params: Dict[str, Any] = {}
    if not path or not os.path.isfile(path):
        return params

    def _to_bool(v: str) -> Optional[bool]:
        u = v.strip().upper()
        if u in ("T", ".TRUE.", "TRUE"):
            return True
        if u in ("F", ".FALSE.", "FALSE"):
            return False
        return None

    def _first_token(s: str) -> str:
        s = (s or "").strip()
        return s.split()[0] if s else s

    def _cast_token(tok: str):
        b = _to_bool(tok)
        if b is not None:
            return bool(b)
        try:
            return int(tok)
        except Exception:
            pass
        try:
            return float(tok)
        except Exception:
            pass
        return tok

    assign_re = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\s;]+)")

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue

            if "#" in s:
                s = s.split("#", 1)[0].strip()
                if not s:
                    continue

            if "=" not in s:
                continue

            for m in assign_re.finditer(s):
                k = m.group(1).strip().upper()
                vtok = _first_token(m.group(2))
                params[k] = _cast_token(vtok)

    return params

def _safe_float(x: str) -> Optional[float]:
    try:
        return float(x)
    except Exception:
        return None

def parse_oszicar_energies(path: str) -> List[float]:
    if not os.path.isfile(path):
        return []
    energies: List[float] = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            mE = re.search(r'\bE=\s*([-\d\.Ee+]+)', line)
            mF = re.search(r'\bF=\s*([-\d\.Ee+]+)', line)
            val = None
            if mE:
                val = _safe_float(mE.group(1))
            elif mF:
                val = _safe_float(mF.group(1))
            if val is not None:
                energies.append(val)
    return energies

def parse_kpoints_file_general(kpoints_path: str) -> Dict[str, Any]:
    kpoints_info: Dict[str, Any] = {}
    if not os.path.isfile(kpoints_path):
        return kpoints_info
    try:
        with open(kpoints_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()

        divisions_found = None
        shift_found = None
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split()
            if len(parts) == 3:
                try:
                    numbers = [int(x) for x in parts]
                    if divisions_found is None:
                        divisions_found = numbers
                    continue
                except ValueError:
                    pass
                try:
                    numbers = [float(x) for x in parts]
                    if shift_found is None:
                        shift_found = numbers
                except ValueError:
                    continue

        if divisions_found:
            kpoints_info['divisions'] = divisions_found
        if shift_found:
            kpoints_info['usershift'] = shift_found

        if not divisions_found and len(lines) >= 4:
            line_index = 3
            while line_index < len(lines):
                line = lines[line_index].strip()
                if line and not line.startswith('#'):
                    try:
                        divisions = [int(x) for x in line.split()]
                        if len(divisions) == 3:
                            kpoints_info['divisions'] = divisions
                            if line_index + 1 < len(lines):
                                next_line = lines[line_index + 1].strip()
                                if next_line:
                                    try:
                                        shift = [float(x) for x in next_line.split()]
                                        if len(shift) == 3:
                                            kpoints_info['usershift'] = shift
                                    except Exception:
                                        pass
                            break
                    except Exception:
                        pass
                line_index += 1

    except Exception as e:
        print(f"[WARN] 通用KPOINTS解析失败: {e}")
    return kpoints_info

def parse_outcar_last_energy(path: str) -> Optional[float]:
    if not os.path.isfile(path):
        return None
    last = None
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            m = re.search(r'free\s+energy\s+TOTEN\s*=\s*([-\d\.Ee+]+)', line)
            if m:
                val = _safe_float(m.group(1))
                if val is not None:
                    last = val
            else:
                m2 = re.search(r'energy\s+without\s+entropy\s*=\s*([-\d\.Ee+]+)', line)
                if m2:
                    val = _safe_float(m2.group(1))
                    if val is not None:
                        last = val
    return last

def parse_outcar_efermi(outcar_path: str) -> Optional[float]:
    if not os.path.isfile(outcar_path):
        return None
    try:
        with open(outcar_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        tail = lines[-5000:] if len(lines) > 5000 else lines
        for line in reversed(tail):
            m = re.search(r"E-fermi\s*:\s*([-\d\.Ee+]+)", line)
            if m:
                return float(m.group(1))
    except Exception:
        return None
    return None

def parse_outcar_forces(path: str) -> Optional[np.ndarray]:
    if not os.path.isfile(path):
        return None
    forces: List[List[float]] = []
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    i = len(lines) - 1
    while i >= 0:
        if 'TOTAL-FORCE (eV/Angst)' in lines[i]:
            forces = []
            i += 2
            while i < len(lines) and lines[i].strip():
                parts = lines[i].split()
                if len(parts) >= 6:
                    fx, fy, fz = parts[3], parts[4], parts[5]
                    f3 = [_safe_float(fx), _safe_float(fy), _safe_float(fz)]
                    if None not in f3:
                        forces.append([float(f3[0]), float(f3[1]), float(f3[2])])
                i += 1
            break
        i -= 1
    if forces:
        return np.array(forces, dtype=float)
    return None

def parse_outcar_stress_voigt_ev_per_a3(path: str) -> Optional[np.ndarray]:
    if not os.path.isfile(path):
        return None
    kb_to_ev_per_a3 = 0.0006241509
    last_voigt = None
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    for i in range(len(lines) - 1, -1, -1):
        if 'in kB' in lines[i]:
            for j in range(i + 1, min(i + 8, len(lines))):
                nums = re.findall(r'([-\d\.Ee+]+)', lines[j])
                if len(nums) >= 6:
                    vals = [_safe_float(x) for x in nums[:6]]
                    if None not in vals:
                        last_voigt = np.array(vals, dtype=float) * kb_to_ev_per_a3
                        break
            if last_voigt is not None:
                break

    return last_voigt

def parse_outcar_magmoms(path: str) -> Optional[np.ndarray]:
    if not os.path.isfile(path):
        return None
    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()

    start = None
    for i in range(len(lines) - 1, -1, -1):
        if 'magnetization' in lines[i].lower():
            start = i
            break
    if start is None:
        return None

    magmoms: List[float] = []
    for j in range(start, min(start + 400, len(lines))):
        parts = lines[j].split()
        if not parts:
            continue
        if 'tot' in parts:
            try:
                idx = parts.index('tot')
                val = _safe_float(parts[idx + 1])
                if val is not None:
                    magmoms.append(float(val))
            except Exception:
                pass

    if magmoms:
        return np.array(magmoms, dtype=float)
    return None


# ============================================================
# 几何/2D slab 辅助（可直接从结构算）
# ============================================================

def compute_slab_thickness_A(at: Atoms, axis: int = 2) -> float:
    pos = np.asarray(at.positions, dtype=float)
    z = pos[:, axis]
    return float(z.max() - z.min())

def compute_cell_area_A2(at: Atoms, axis: int = 2) -> float:
    cell = np.asarray(at.cell.array, dtype=float)
    a = cell[0]
    b = cell[1]
    area = np.linalg.norm(np.cross(a, b))
    return float(area)

def compute_vacuum_thickness_A(at: Atoms, axis: int = 2) -> float:
    cell = np.asarray(at.cell.array, dtype=float)
    L = float(np.linalg.norm(cell[axis]))
    thick = compute_slab_thickness_A(at, axis=axis)
    return float(max(0.0, L - thick))


# ============================================================
# 对称性（可选：spglib）
# ============================================================

def spglib_symmetry_info(at: Atoms, symprec: float = 1e-5) -> Dict[str, Any]:
    if spglib is None:
        return {}

    info: Dict[str, Any] = {}
    cell = (at.cell.array, at.get_scaled_positions(), at.numbers)

    try:
        s = spglib.get_symmetry_dataset(cell, symprec=symprec)
        if hasattr(s, "number"):
            num = getattr(s, "number", None)
            intl = getattr(s, "international", None)
        else:
            num = s.get("number", None)
            intl = s.get("international", None)

        if num is not None:
            info["phys_spacegroup_number"] = int(num)
        if intl is not None:
            info["phys_spacegroup_international"] = str(intl)
    except Exception:
        pass

    try:
        symm = spglib.get_symmetry(cell, symprec=symprec)
        rots = symm.get("rotations", [])
        has_inv = False
        if rots is not None:
            for R in rots:
                R = np.asarray(R, dtype=int)
                if np.array_equal(R, -np.eye(3, dtype=int)):
                    has_inv = True
                    break
        info["phys_has_inversion_symmetry"] = bool(has_inv)
    except Exception:
        pass

    return info


# ============================================================
# 偶极矩（OUTCAR 可读则补）
# ============================================================

def parse_outcar_dipole_moment(outcar_path: str) -> Optional[List[float]]:
    if not os.path.isfile(outcar_path):
        return None
    try:
        with open(outcar_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return None

    tail = lines[-20000:] if len(lines) > 20000 else lines
    patterns = [
        r"dipolmoment.*?\(\s*e.*?A.*?\)\s*[:=]?\s*([-\d\.Ee+]+)\s+([-\d\.Ee+]+)\s+([-\d\.Ee+]+)",
        r"Dipole\s+moment.*?[:=]\s*([-\d\.Ee+]+)\s+([-\d\.Ee+]+)\s+([-\d\.Ee+]+)",
    ]
    for line in reversed(tail):
        for pat in patterns:
            m = re.search(pat, line, flags=re.IGNORECASE)
            if m:
                try:
                    return [float(m.group(1)), float(m.group(2)), float(m.group(3))]
                except Exception:
                    pass
    return None


# ============================================================
# 收敛性判断（只看最后一个离子步）
# ============================================================

def _vasprun_laststep_convergence(vxml_path: str) -> Tuple[bool, bool]:
    vas = Vasprun(
        vxml_path,
        parse_eigen=False,
        parse_projected_eigen=False,
        parse_dos=False
    )
    ionic_ok = bool(getattr(vas, "converged_ionic", False))
    elec_ok = bool(getattr(vas, "converged_electronic", False))

    try:
        ionic_steps = getattr(vas, "ionic_steps", None)
        if ionic_steps and isinstance(ionic_steps, list):
            last = ionic_steps[-1]
            if isinstance(last, dict):
                es = last.get("electronic_steps", None)
                if es and isinstance(es, list) and isinstance(es[-1], dict) and ("converged" in es[-1]):
                    elec_ok = bool(es[-1]["converged"])
    except Exception:
        pass

    return ionic_ok, elec_ok

_outcar_int_re = re.compile(r'\bNSW\s*=\s*(\d+)')
def _outcar_guess_nsw(outcar_path: str) -> Optional[int]:
    if not os.path.isfile(outcar_path):
        return None
    try:
        with open(outcar_path, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read()
        m = _outcar_int_re.search(txt)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None

def _outcar_laststep_convergence(outcar_path: str) -> Tuple[bool, bool]:
    if not os.path.isfile(outcar_path):
        return (False, False)

    nsw = _outcar_guess_nsw(outcar_path)
    ionic_ok = True if (nsw == 0) else False
    elec_ok = False

    try:
        with open(outcar_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception:
        return (False, False)

    tail = lines[-4000:] if len(lines) > 4000 else lines
    tail_txt = "".join(tail)

    elec_patterns = [
        r"aborting loop because EDIFF is reached",
        r"EDIFF is reached",
        r"reached required accuracy - stopping SCF",
        r"reached required accuracy",
    ]
    for pat in elec_patterns:
        if re.search(pat, tail_txt):
            elec_ok = True
            break

    if not ionic_ok:
        ionic_patterns = [
            r"reached required accuracy - stopping structural energy minimisation",
            r"reached required accuracy - stopping ionic steps",
            r"reached required accuracy",
        ]
        for pat in ionic_patterns:
            if re.search(pat, tail_txt):
                ionic_ok = True
                break

    return (ionic_ok, elec_ok)

def should_skip_dir_by_convergence(
    n_ionic_steps: int,
    ionic_ok_last: Optional[bool],
    elec_ok_last: Optional[bool]
) -> bool:
    if ionic_ok_last is None or elec_ok_last is None:
        return True
    return (not ionic_ok_last) or (not elec_ok_last)


# ============================================================
# LOCPOT 真空能级
# ============================================================

def vacuum_level_from_planar(
    pot3d: np.ndarray,
    vacuum_direction: int = 2,
    smooth_window: int = 9,
    top_fraction: float = 0.12
) -> float:
    pot3d = np.asarray(pot3d)
    if pot3d.ndim != 3:
        raise ValueError(f"pot3d.ndim must be 3, got {pot3d.ndim}")

    axes = [0, 1, 2]
    axes.remove(vacuum_direction)
    vz = pot3d.mean(axis=tuple(axes))  # V(z)

    w = int(max(1, smooth_window))
    if w % 2 == 0:
        w += 1
    if 1 < w < len(vz):
        kernel = np.ones(w) / w
        vz_s = np.convolve(vz, kernel, mode="same")
    else:
        vz_s = vz

    n = len(vz_s)
    m = max(1, int(n * float(top_fraction)))
    idx = np.argsort(vz_s)[-m:]
    return float(vz_s[idx].mean())

def _get_locpot_total_3d(calc_dir: str) -> Optional[np.ndarray]:
    locpot_path = os.path.join(calc_dir, "LOCPOT")
    if not os.path.isfile(locpot_path):
        return None
    try:
        lp = Locpot.from_file(locpot_path)
        if isinstance(lp.data, dict):
            pot = lp.data.get("total", None)
        else:
            pot = lp.data
        if pot is None:
            return None
        pot = np.asarray(pot)
        if pot.ndim != 3:
            return None
        return pot
    except Exception as e:
        print(f"[WARN] pymatgen 读取 LOCPOT 失败: {calc_dir}/LOCPOT -> {e}")
        return None


# ============================================================
# 自旋分辨 band edges（EIGENVAL）——兜底用
# ============================================================

def band_edges_from_eigenval(eigenval_path: str, occ_tol: float = 1e-6) -> Dict[str, float]:
    ev = Eigenval(eigenval_path)

    vbm_by_spin: Dict[Any, float] = {}
    cbm_by_spin: Dict[Any, float] = {}

    for spin, arr in ev.eigenvalues.items():
        a = np.asarray(arr)
        if a.ndim != 3 or a.shape[-1] < 2:
            continue
        energies = a[:, :, 0].ravel()
        occs = a[:, :, 1].ravel()

        occ_mask = occs > occ_tol
        unocc_mask = ~occ_mask

        if np.any(occ_mask):
            vbm_by_spin[spin] = float(np.max(energies[occ_mask]))
        if np.any(unocc_mask):
            cbm_by_spin[spin] = float(np.min(energies[unocc_mask]))

    out: Dict[str, float] = {}

    spins = list(set(vbm_by_spin.keys()) | set(cbm_by_spin.keys()))

    def _spin_name(s) -> str:
        n = getattr(s, "name", str(s)).lower()
        if "up" in n or str(s) == "1":
            return "up"
        if "down" in n or str(s) == "-1":
            return "down"
        return n

    for s in spins:
        tag = _spin_name(s)
        if s in vbm_by_spin:
            out[f"vbm_eV_{tag}"] = float(vbm_by_spin[s])
        if s in cbm_by_spin:
            out[f"cbm_eV_{tag}"] = float(cbm_by_spin[s])
        if (s in vbm_by_spin) and (s in cbm_by_spin):
            out[f"bandgap_eV_{tag}"] = float(max(0.0, cbm_by_spin[s] - vbm_by_spin[s]))

    if vbm_by_spin:
        out["vbm_eV"] = float(max(vbm_by_spin.values()))
    if cbm_by_spin:
        out["cbm_eV"] = float(min(cbm_by_spin.values()))
    if ("vbm_eV" in out) and ("cbm_eV" in out):
        out["bandgap_eV"] = float(max(0.0, out["cbm_eV"] - out["vbm_eV"]))

    return out


# ============================================================
# vasprun 电子信息提取（稳定输出 up/down）
# ============================================================

def extract_electronic_info_from_vasprun(
    vxml_path: str,
    calc_dir: str,
    vacuum_direction: int = 2
) -> Dict[str, float]:
    info: Dict[str, float] = {}

    vas = Vasprun(
        vxml_path,
        parse_eigen=True,
        parse_projected_eigen=False,
        parse_dos=False
    )

    try:
        info["fermi_eV"] = float(vas.efermi)
        info["fermi_eV_up"] = float(vas.efermi)
        info["fermi_eV_down"] = float(vas.efermi)
    except Exception:
        pass

    try:
        ev = getattr(vas, "eigenvalues", None)
        if isinstance(ev, dict) and ev:
            vbm_by_spin: Dict[Any, float] = {}
            cbm_by_spin: Dict[Any, float] = {}

            for spin, arr in ev.items():
                a = np.asarray(arr)
                if a.ndim != 3 or a.shape[-1] < 2:
                    continue

                energies = a[:, :, 0].ravel()
                occs = a[:, :, 1].ravel()

                occ_mask = occs > 1e-6
                unocc_mask = ~occ_mask

                if np.any(occ_mask):
                    vbm_by_spin[spin] = float(np.max(energies[occ_mask]))
                if np.any(unocc_mask):
                    cbm_by_spin[spin] = float(np.min(energies[unocc_mask]))

            def _spin_name(s) -> str:
                n = getattr(s, "name", str(s)).lower()
                if "up" in n or str(s) == "1":
                    return "up"
                if "down" in n or str(s) == "-1":
                    return "down"
                return n

            for s, v in vbm_by_spin.items():
                info[f"vbm_eV_{_spin_name(s)}"] = float(v)
            for s, c in cbm_by_spin.items():
                info[f"cbm_eV_{_spin_name(s)}"] = float(c)
            for s in set(vbm_by_spin) & set(cbm_by_spin):
                tag = _spin_name(s)
                info[f"bandgap_eV_{tag}"] = float(max(0.0, cbm_by_spin[s] - vbm_by_spin[s]))

            if vbm_by_spin:
                info["vbm_eV"] = float(max(vbm_by_spin.values()))
            if cbm_by_spin:
                info["cbm_eV"] = float(min(cbm_by_spin.values()))
            if ("vbm_eV" in info) and ("cbm_eV" in info):
                info["bandgap_eV"] = float(max(0.0, info["cbm_eV"] - info["vbm_eV"]))
    except Exception as e:
        print(f"[WARN] 用 vas.eigenvalues 计算 band edges 失败({calc_dir}): {e}")

    if (("vbm_eV_up" not in info) or ("vbm_eV_down" not in info) or
        ("cbm_eV_up" not in info) or ("cbm_eV_down" not in info)):
        eigenval_path = os.path.join(calc_dir, "EIGENVAL")
        if os.path.isfile(eigenval_path):
            try:
                info.update(band_edges_from_eigenval(eigenval_path))
            except Exception as e:
                print(f"[WARN] EIGENVAL 兜底 band edges 失败({calc_dir}): {e}")

    pot = _get_locpot_total_3d(calc_dir)
    if pot is not None:
        try:
            evac = vacuum_level_from_planar(
                pot,
                vacuum_direction=vacuum_direction,
                smooth_window=9,
                top_fraction=0.12
            )
            info["vacuum_level_eV"] = float(evac)
        except Exception as e:
            print(f"[WARN] 真空能级计算失败({calc_dir}): {e}")

    if ("vacuum_level_eV" in info) and ("fermi_eV" in info):
        info["work_function_eV"] = float(info["vacuum_level_eV"] - info["fermi_eV"])

    return info


# ============================================================
# OUTCAR rich 解析 helper（必须完整定义）
# ============================================================

def _to_bool_token(x: str) -> Optional[bool]:
    u = x.strip().upper()
    if u in ("T", ".TRUE.", "TRUE"):
        return True
    if u in ("F", ".FALSE.", "FALSE"):
        return False
    return None

def _parse_number_list_from_match(m: re.Match) -> List[float]:
    s = m.group(1)
    nums = re.findall(r'[-+]?\d*\.?\d+(?:[Ee][+-]?\d+)?', s)
    return [float(x) for x in nums]

def _extract_section_text(txt: str, header_regex: str, max_lines: int = 300) -> str:
    m = re.search(header_regex, txt, flags=re.IGNORECASE | re.MULTILINE)
    if not m:
        return ""
    tail = txt[m.end():]
    lines = tail.splitlines()
    return "\n".join(lines[:max_lines])

def _extract_float_in_section(section_txt: str, key: str) -> Optional[float]:
    if not section_txt:
        return None
    m = re.search(
        rf"^\s*{re.escape(key)}\s*=\s*([-\d\.Ee+]+)",
        section_txt,
        flags=re.MULTILINE
    )
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None

def _extract_int_in_section(section_txt: str, key: str) -> Optional[int]:
    if not section_txt:
        return None
    m = re.search(
        rf"^\s*{re.escape(key)}\s*=\s*([-\d]+)",
        section_txt,
        flags=re.MULTILINE
    )
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def _extract_bool_TF_in_section(section_txt: str, key: str) -> Optional[bool]:
    if not section_txt:
        return None
    m = re.search(
        rf"^\s*{re.escape(key)}\s*=\s*([TF])\b",
        section_txt,
        flags=re.MULTILINE
    )
    if not m:
        return None
    return _to_bool_token(m.group(1))


# ============================================================
# OUTCAR 参数提取（legacy / rich）
# ============================================================

def parse_vasp_parameters_from_outcar_legacy(outcar_path: str) -> Dict[str, Any]:
    parameters: Dict[str, Any] = {}
    if not os.path.isfile(outcar_path):
        return parameters
    try:
        with open(outcar_path, 'r', encoding='utf-8', errors='ignore') as f:
            outcar_content = f.read()
    except Exception:
        return parameters

    dimension_patterns = {
        'NKPTS': r'NKPTS\s*=\s*(\d+)',
        'NKDIM': r'NKDIM\s*=\s*(\d+)',
        'NBANDS': r'NBANDS=\s*(\d+)',
        'NEDOS': r'NEDOS\s*=\s*(\d+)',
        'NIONS': r'NIONS\s*=\s*(\d+)',
        'NGX': r'NGX\s*=\s*(\d+)',
        'NGY': r'NGY\s*=\s*(\d+)',
        'NGZ': r'NGZ\s*=\s*(\d+)',
        'NGXF': r'NGXF\s*=\s*(\d+)',
        'NGYF': r'NGYF\s*=\s*(\d+)',
        'NGZF': r'NGZF\s*=\s*(\d+)'
    }
    for key, pattern in dimension_patterns.items():
        match = re.search(pattern, outcar_content)
        if match:
            parameters[key] = int(match.group(1))

    system_match = re.search(r'SYSTEM\s*=\s*(.+)', outcar_content)
    if system_match:
        parameters['SYSTEM'] = system_match.group(1).strip()

    if parameters:
        parameters['calculator'] = 'vasp'
        parameters['source'] = 'OUTCAR_LEGACY'
    return parameters

def parse_vasp_parameters_from_outcar_rich(outcar_path: str) -> Dict[str, Any]:
    if not os.path.isfile(outcar_path):
        return {}

    try:
        with open(outcar_path, "r", encoding="utf-8", errors="ignore") as f:
            txt = f.read()
    except Exception:
        return {}

    params: Dict[str, Any] = {}

    def _first_token(s: str) -> str:
        s = (s or "").strip()
        return s.split()[0] if s else s

    def _cast_token(tok: str):
        if tok is None:
            return None
        b = _to_bool_token(tok)
        if b is not None:
            return bool(b)
        try:
            return int(tok)
        except Exception:
            pass
        try:
            return float(tok)
        except Exception:
            pass
        return tok

    assign_re = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^\s;]+)")

    for line in txt.splitlines():
        if "=" not in line:
            continue
        for m in assign_re.finditer(line):
            key = m.group(1).strip().upper()
            val_tok = _first_token(m.group(2))
            casted = _cast_token(val_tok)
            if casted is not None:
                params[key] = casted

    def _add(name: str, pattern: str, cast):
        m = re.search(pattern, txt, flags=re.MULTILINE)
        if not m:
            return
        raw = m.group(1).strip()
        token = raw.split()[0] if raw else raw
        try:
            params[name] = cast(token)
        except Exception:
            params[name] = token

    def _add_bool(name: str, pattern: str):
        m = re.search(pattern, txt, flags=re.MULTILINE)
        if not m:
            return
        raw = m.group(1).strip()
        token = raw.split()[0] if raw else raw
        b = _to_bool_token(token)
        if b is None:
            return
        params[name] = bool(b)

    def _add_numlist(name: str, pattern: str):
        m = re.search(pattern, txt, flags=re.MULTILINE)
        if not m:
            return
        try:
            params[name] = _parse_number_list_from_match(m)
        except Exception:
            pass

    _add("NKPTS", r"NKPTS\s*=\s*(\d+)", int)
    _add("NKDIM", r"NKDIM\s*=\s*(\d+)", int)
    _add("NBANDS", r"NBANDS\s*=\s*(\d+)", int)
    _add("NEDOS", r"NEDOS\s*=\s*(\d+)", int)
    _add("NIONS", r"NIONS\s*=\s*(\d+)", int)
    _add("NGX", r"NGX\s*=\s*(\d+)", int)
    _add("NGY", r"NGY\s*=\s*(\d+)", int)
    _add("NGZ", r"NGZ\s*=\s*(\d+)", int)
    _add("NGXF", r"NGXF\s*=\s*(\d+)", int)
    _add("NGYF", r"NGYF\s*=\s*(\d+)", int)
    _add("NGZF", r"NGZF\s*=\s*(\d+)", int)

    m = re.search(r"^\s*SYSTEM\s*=\s*(.+)$", txt, flags=re.MULTILINE)
    if m:
        params["SYSTEM"] = m.group(1).strip()

    _add("NWRITE", r"^\s*NWRITE\s*=\s*(.+)$", int)
    _add("PREC", r"^\s*PREC\s*=\s*(.+)$", lambda x: x.strip())
    _add("ISTART", r"^\s*ISTART\s*=\s*(.+)$", int)
    _add("ICHARG", r"^\s*ICHARG\s*=\s*(.+)$", int)
    _add("ISPIN", r"^\s*ISPIN\s*=\s*(.+)$", int)
    _add_bool("LNONCOLLINEAR", r"^\s*LNONCOLLINEAR\s*=\s*(.+)$")
    _add_bool("LSORBIT", r"^\s*LSORBIT\s*=\s*(.+)$")
    _add("INIWAV", r"^\s*INIWAV\s*=\s*(.+)$", int)
    _add_bool("LASPH", r"^\s*LASPH\s*=\s*(.+)$")

    _add("ENCUT", r"^\s*ENCUT\s*=\s*(.+)$", float)
    _add("ENINI", r"^\s*ENINI\s*=\s*(.+)$", float)
    _add("ENAUG", r"^\s*ENAUG\s*=\s*(.+)$", float)
    _add("NELM", r"^\s*NELM\s*=\s*(.+)$", int)
    _add("NELMIN", r"^\s*NELMIN\s*=\s*(.+)$", int)
    _add("NELMDL", r"^\s*NELMDL\s*=\s*(.+)$", int)
    _add("EDIFF", r"^\s*EDIFF\s*=\s*(.+)$", float)

    m = re.search(r"^\s*LREAL\s*=\s*(.+)$", txt, flags=re.MULTILINE)
    if m:
        raw = m.group(1).strip()
        token = raw.split()[0] if raw else raw
        b = _to_bool_token(token)
        params["LREAL"] = b if b is not None else token

    _add_bool("NLSPLINE", r"^\s*NLSPLINE\s*=\s*(.+)$")
    _add_bool("LCOMPAT", r"^\s*LCOMPAT\s*=\s*(.+)$")
    _add_bool("GGA_COMPAT", r"^\s*GGA_COMPAT\s*=\s*(.+)$")
    _add("LMAXPAW", r"^\s*LMAXPAW\s*=\s*(.+)$", int)
    _add("LMAXMIX", r"^\s*LMAXMIX\s*=\s*(.+)$", int)
    _add("VOSKOWN", r"^\s*VOSKOWN\s*=\s*(.+)$", int)

    m = re.search(r"^\s*ROPT\s*=\s*([-\d\.Ee+]+)\s+([-\d\.Ee+]+)", txt, flags=re.MULTILINE)
    if m:
        try:
            params["ROPT"] = [float(m.group(1)), float(m.group(2))]
        except Exception:
            pass

    _add("EDIFFG", r"^\s*EDIFFG\s*=\s*(.+)$", float)
    _add("NSW", r"^\s*NSW\s*=\s*(.+)$", int)
    _add("NBLOCK", r"^\s*NBLOCK\s*=\s*(.+)$", int)
    _add("KBLOCK", r"^\s*KBLOCK\s*=\s*(.+)$", int)
    _add("IBRION", r"^\s*IBRION\s*=\s*(.+)$", int)
    _add("NFREE", r"^\s*NFREE\s*=\s*(.+)$", int)
    _add("ISIF", r"^\s*ISIF\s*=\s*(.+)$", int)
    _add("IWAVPR", r"^\s*IWAVPR\s*=\s*(.+)$", int)
    _add("ISYM", r"^\s*ISYM\s*=\s*(.+)$", int)
    _add_bool("LCORR", r"^\s*LCORR\s*=\s*(.+)$")

    _add("POTIM", r"^\s*POTIM\s*=\s*(.+)$", float)
    _add("TEIN", r"^\s*TEIN\s*=\s*(.+)$", float)
    _add("TEBEG", r"^\s*TEBEG\s*=\s*(.+)$", float)
    _add("TEEND", r"^\s*TEEND\s*=\s*(.+)$", float)
    _add("SMASS", r"^\s*SMASS\s*=\s*(.+)$", float)
    _add("SCALEE", r"^\s*SCALEE\s*=\s*(.+)$", float)
    _add("NPACO", r"^\s*NPACO\s*=\s*(.+)$", int)
    _add("APACO", r"^\s*APACO\s*=\s*(.+)$", float)
    _add("PSTRESS", r"^\s*PSTRESS\s*=\s*(.+)$", float)

    _add_numlist("POMASS", r"^\s*POMASS\s*=\s*([-\d\.\sEe+]+)$")
    _add_numlist("ZVAL", r"^\s*ZVAL\s*=\s*([-\d\.\sEe+]+)$")
    _add_numlist("RWIGS", r"^\s*RWIGS\s*=\s*([-\d\.\sEe+]+)$")
    _add_numlist("VCA", r"^\s*VCA\s*=\s*([-\d\.\sEe+]+)$")

    _add("NELECT", r"^\s*NELECT\s*=\s*(.+)$", float)
    _add("NUPDOWN", r"^\s*NUPDOWN\s*=\s*(.+)$", float)

    _add("EMIN", r"^\s*EMIN\s*=\s*(.+)$", float)
    _add("EMAX", r"^\s*EMAX\s*=\s*(.+)$", float)
    _add("EFERMI", r"^\s*EFERMI\s*=\s*(.+)$", float)
    _add("ISMEAR", r"^\s*ISMEAR\s*=\s*(.+)$", int)
    _add("SIGMA", r"^\s*SIGMA\s*=\s*(.+)$", float)

    _add("IALGO", r"^\s*IALGO\s*=\s*(.+)$", int)
    _add_bool("LDIAG", r"^\s*LDIAG\s*=\s*(.+)$")
    _add_bool("LSUBROT", r"^\s*LSUBROT\s*=\s*(.+)$")
    _add("TURBO", r"^\s*TURBO\s*=\s*(.+)$", int)
    _add("IRESTART", r"^\s*IRESTART\s*=\s*(.+)$", int)
    _add("NREBOOT", r"^\s*NREBOOT\s*=\s*(.+)$", int)
    _add("NMIN", r"^\s*NMIN\s*=\s*(.+)$", int)
    _add("EREF", r"^\s*EREF\s*=\s*(.+)$", float)
    _add("IMIX", r"^\s*IMIX\s*=\s*(.+)$", int)
    _add("AMIX", r"^\s*AMIX\s*=\s*(.+)$", float)
    _add("BMIX", r"^\s*BMIX\s*=\s*(.+)$", float)
    _add("AMIX_MAG", r"^\s*AMIX_MAG\s*=\s*(.+)$", float)
    _add("BMIX_MAG", r"^\s*BMIX_MAG\s*=\s*(.+)$", float)
    _add("AMIN", r"^\s*AMIN\s*=\s*(.+)$", float)
    _add("WC", r"^\s*WC\s*=\s*(.+)$", float)
    _add("INIMIX", r"^\s*INIMIX\s*=\s*(.+)$", int)
    _add("MIXPRE", r"^\s*MIXPRE\s*=\s*(.+)$", int)
    _add("MAXMIX", r"^\s*MAXMIX\s*=\s*(.+)$", int)
    _add("WEIMIN", r"^\s*WEIMIN\s*=\s*(.+)$", float)
    _add("EBREAK", r"^\s*EBREAK\s*=\s*(.+)$", float)
    _add("DEPER", r"^\s*DEPER\s*=\s*(.+)$", float)
    _add("TIME", r"^\s*TIME\s*=\s*(.+)$", float)

    _add_bool("LWAVE", r"^\s*LWAVE\s*=\s*(.+)$")
    _add_bool("LDOWNSAMPLE", r"^\s*LDOWNSAMPLE\s*=\s*(.+)$")
    _add_bool("LCHARG", r"^\s*LCHARG\s*=\s*(.+)$")
    _add_bool("LVTOT", r"^\s*LVTOT\s*=\s*(.+)$")
    _add_bool("LVHAR", r"^\s*LVHAR\s*=\s*(.+)$")
    _add_bool("LELF", r"^\s*LELF\s*=\s*(.+)$")
    _add("LORBIT", r"^\s*LORBIT\s*=\s*(.+)$", int)

    _add_bool("LMONO", r"^\s*LMONO\s*=\s*(.+)$")
    _add_bool("LDIPOL", r"^\s*LDIPOL\s*=\s*(.+)$")
    _add("IDIPOL", r"^\s*IDIPOL\s*=\s*(.+)$", int)
    _add("EPSILON", r"^\s*EPSILON\s*=\s*(.+)$", float)

    m = re.search(r"^\s*GGA\s*=\s*(.+)$", txt, flags=re.MULTILINE)
    if m:
        params["GGA"] = m.group(1).strip()
    m = re.search(r"^\s*LEXCH\s*=\s*(.+)$", txt, flags=re.MULTILINE)
    if m:
        params["LEXCH"] = m.group(1).strip()
    _add_bool("LHFCALC", r"^\s*LHFCALC\s*=\s*(.+)$")
    _add_bool("LHFONE", r"^\s*LHFONE\s*=\s*(.+)$")
    _add("AEXX", r"^\s*AEXX\s*=\s*(.+)$", float)

    lr_sec = _extract_section_text(txt, header_regex=r"^\s*Linear\s+response\s+parameters", max_lines=260)
    rf_sec = _extract_section_text(txt, header_regex=r"^\s*Response\s+functions", max_lines=520)

    lr_cshift = _extract_float_in_section(lr_sec, "CSHIFT")
    lr_omegamax = _extract_float_in_section(lr_sec, "OMEGAMAX")
    lr_deg = _extract_float_in_section(lr_sec, "DEG_THRESHOLD")
    lr_rtime = _extract_float_in_section(lr_sec, "RTIME")
    lr_kinter = _extract_int_in_section(lr_sec, "KINTER")

    if lr_cshift is not None:
        params["CSHIFT_linear_response"] = float(lr_cshift)
    if lr_omegamax is not None:
        params["OMEGAMAX_linear_response"] = float(lr_omegamax)
    if lr_deg is not None:
        params["DEG_THRESHOLD"] = float(lr_deg)
    if lr_rtime is not None:
        params["RTIME"] = float(lr_rtime)
    if lr_kinter is not None:
        params["KINTER"] = int(lr_kinter)

    if lr_sec:
        for k in ["LEPSILON", "LRPA", "LNABLA", "LVEL", "LINTERFAST"]:
            b = _extract_bool_TF_in_section(lr_sec, k)
            if b is not None:
                params[k] = bool(b)

    rf_omegamax = _extract_float_in_section(rf_sec, "OMEGAMAX")
    rf_cshift = _extract_float_in_section(rf_sec, "CSHIFT")
    rf_omegamin = _extract_float_in_section(rf_sec, "OMEGAMIN")
    rf_omegatl = _extract_float_in_section(rf_sec, "OMEGATL")
    rf_omegagrid = _extract_int_in_section(rf_sec, "OMEGAGRID")

    if rf_omegamax is not None:
        params["OMEGAMAX_response_functions"] = float(rf_omegamax)
    if rf_cshift is not None:
        params["CSHIFT_response_functions"] = float(rf_cshift)
    if rf_omegamin is not None:
        params["OMEGAMIN"] = float(rf_omegamin)
    if rf_omegatl is not None:
        params["OMEGATL"] = float(rf_omegatl)
    if rf_omegagrid is not None:
        params["OMEGAGRID"] = int(rf_omegagrid)

    if rf_omegamax is not None:
        params["OMEGAMAX"] = float(rf_omegamax)
    elif lr_omegamax is not None:
        params["OMEGAMAX"] = float(lr_omegamax)

    if rf_cshift is not None:
        params["CSHIFT"] = float(rf_cshift)
    elif lr_cshift is not None:
        params["CSHIFT"] = float(lr_cshift)

    if params:
        params["calculator"] = "vasp"
        params["source"] = "OUTCAR_RICH"
    return params

def parse_vasp_parameters_from_vasprun(vxml_path: str) -> Dict[str, Any]:
    """
    从 vasprun.xml(.gz) 提取输入参数（通常等价于 INCAR + 其它参数摘要）。
    适用于上传场景：只有 vasprun，没有 OUTCAR/INCAR/KPOINTS。
    """
    if not vxml_path or (not os.path.isfile(vxml_path)):
        return {}

    try:
        vas = Vasprun(
            vxml_path,
            parse_eigen=False,
            parse_projected_eigen=False,
            parse_dos=False
        )
    except Exception:
        return {}

    params: Dict[str, Any] = {}

    # 1) 优先：incar（pymatgen Incar 对象，通常可 dict()）
    try:
        incar = getattr(vas, "incar", None)
        if incar:
            d = dict(incar)
            # 统一 key 大写
            params.update({str(k).upper(): v for k, v in d.items()})
    except Exception:
        pass

    # 2) 兜底：vas.parameters（有时更全）
    try:
        p2 = getattr(vas, "parameters", None)
        if isinstance(p2, dict) and p2:
            for k, v in p2.items():
                kk = str(k).upper()
                # 不覆盖 incar 已有的键（你也可以反过来覆盖）
                params.setdefault(kk, v)
    except Exception:
        pass

    if params:
        params["calculator"] = "vasp"
        params["source"] = "VASPRUN"

    return params


# ============================================================
# 去重 hash（保持你原来的“内容 hash + step_idx”逻辑）
# ============================================================

def _hash_atoms(at: Atoms, step_props: Dict[str, Any]) -> str:
    payload: Dict[str, Any] = {}
    payload["numbers"] = np.asarray(at.numbers, dtype=int).tolist()
    payload["positions"] = np.asarray(at.positions, dtype=float).round(12).tolist()
    payload["cell"] = np.asarray(at.cell.array, dtype=float).round(12).tolist()
    payload["pbc"] = np.asarray(at.pbc, dtype=bool).tolist()
    if step_props.get("energy_eV") is not None:
        payload["energy_eV"] = float(step_props["energy_eV"])
    s = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def make_canonical_key(at: Atoms, step_props: Dict[str, Any], step_idx: int) -> str:
    struct_hash = _hash_atoms(at, step_props)
    return f"{struct_hash}|step={step_idx}"

def preload_existing_keys(db) -> set:
    keys = set()
    try:
        for row in db.select():
            k = getattr(row, "key", None)
            if k and "|step=" in k:
                keys.add(k)
    except Exception as e:
        print(f"[WARN] 预加载已有键失败：{e}")
    return keys


# ============================================================
# 参数键 universe：补齐非-vasprun 的 calculator_parameters 键集合
# ============================================================

def build_parameter_key_universe_from_db(db) -> set:
    keys = set()
    try:
        for row in db.select():
            try:
                cp = row.calculator_parameters
            except Exception:
                cp = None
            if isinstance(cp, dict):
                keys.update(cp.keys())
    except Exception as e:
        print(f"[WARN] 构建参数键宇宙失败: {e}")
    return keys

def pad_calc_params_to_universe(calc_params: Dict[str, Any], key_universe: set) -> Dict[str, Any]:
    if not key_universe:
        return calc_params
    out = dict(calc_params)
    for k in key_universe:
        out.setdefault(k, None)
    return out


# ============================================================
# 确保顶层 calculator_parameters 被写入（无 vasprun 时）
# ============================================================

def ensure_calculator_parameters_on_atoms(
    at: Atoms,
    calc_params: Dict[str, Any],
    step_props: Dict[str, Any]
) -> None:
    if not calc_params:
        return

    if at.calc is not None:
        try:
            cname = getattr(at.calc, "name", "")
        except Exception:
            cname = ""

        if cname == "vasp":
            try:
                params = getattr(at.calc, "parameters", None)
            except Exception:
                params = None

            if isinstance(params, dict) and len(params) > 0:
                return

            try:
                at.calc.parameters = dict(calc_params)
            except Exception:
                pass
            return

        try:
            params = getattr(at.calc, "parameters", None)
            if not isinstance(params, dict) or len(params) == 0:
                at.calc.parameters = dict(calc_params)
        except Exception:
            pass
        return

    sp_kwargs = {}
    if step_props.get("energy_eV") is not None:
        sp_kwargs["energy"] = float(step_props["energy_eV"])
    if step_props.get("forces_eV_per_A") is not None:
        sp_kwargs["forces"] = np.asarray(step_props["forces_eV_per_A"], dtype=float)
    if step_props.get("stress_eV_per_A3") is not None:
        sp_kwargs["stress"] = np.asarray(step_props["stress_eV_per_A3"], dtype=float).ravel()

    at.calc = SinglePointCalculator(at, **sp_kwargs)

    try:
        at.calc.parameters = dict(calc_params)
    except Exception:
        pass


# ============================================================
# 解析 VASP 输出（vasprun / OUTCAR / XDATCAR）
# ============================================================

def parse_vasp_any(calc_dir: str) -> Tuple[List[Atoms], Dict[int, Dict[str, Any]], str, str, Dict[str, Any]]:
    meta: Dict[str, Any] = {"ionic_ok_last": None, "elec_ok_last": None}

    vxml_path = None
    for name in ("vasprun.xml", "vasprun.xml.gz"):
        p = os.path.join(calc_dir, name)
        if os.path.isfile(p):
            vxml_path = p
            break

    props_map: Dict[int, Dict[str, Any]] = {}
    structures: List[Atoms] = []

    if vxml_path is not None:
        try:
            ionic_ok, elec_ok = _vasprun_laststep_convergence(vxml_path)
            meta["ionic_ok_last"] = ionic_ok
            meta["elec_ok_last"] = elec_ok
        except Exception as e:
            raise RuntimeError(f"vasprun 收敛性解析失败：{e}")

        try:
            structures = read(vxml_path, index=":")
        except Exception as e_ase:
            try:
                vas_tmp = Vasprun(
                    vxml_path,
                    parse_eigen=False,
                    parse_projected_eigen=False,
                    parse_dos=False
                )
                adaptor = AseAtomsAdaptor()
                structures = [adaptor.get_atoms(s) for s in vas_tmp.structures]
                print(f"[INFO] ASE 读 vasprun 失败({e_ase})，改用 pymatgen->ASE，nsteps={len(structures)}")
            except Exception as e_pm:
                raise RuntimeError(f"ASE 读取 {os.path.basename(vxml_path)} 失败：{e_ase}; pymatgen 也失败：{e_pm}")

        if not structures:
            raise RuntimeError("vasprun 里没有离子步")

        last_idx = len(structures) - 1

        for i, at in enumerate(structures):
            p: Dict[str, Any] = {}
            calc = at.calc
            if calc is not None:
                try:
                    p["energy_eV"] = float(calc.get_potential_energy())
                    p["energy_eV_fallback"] = False
                except Exception:
                    pass
                try:
                    forces = calc.get_forces(at)
                    if forces is not None:
                        p["forces_eV_per_A"] = np.asarray(forces, dtype=float)
                        p["forces_eV_per_A_fallback"] = False
                except Exception:
                    pass
                try:
                    s = calc.get_stress(at)
                    if s is not None:
                        p["stress_eV_per_A3"] = np.asarray(s, dtype=float).ravel()
                        p["stress_eV_per_A3_fallback"] = False
                except Exception:
                    pass
            props_map[i] = p

        try:
            elec = extract_electronic_info_from_vasprun(vxml_path=vxml_path, calc_dir=calc_dir, vacuum_direction=2)
            props_map[last_idx].update(elec)
        except Exception as e:
            print(f"[WARN] vasprun 电子性质提取失败({calc_dir}): {e}")

        return structures, props_map, os.path.basename(vxml_path), "vasprun", meta

    outcar_path = os.path.join(calc_dir, "OUTCAR")
    if os.path.isfile(outcar_path):
        try:
            structures = read(outcar_path, index=":", format='vasp-out')
            if not structures:
                raise RuntimeError("OUTCAR 读取到 0 个离子步")

            ionic_ok, elec_ok = _outcar_laststep_convergence(outcar_path)
            meta["ionic_ok_last"] = ionic_ok
            meta["elec_ok_last"] = elec_ok

            for i, at in enumerate(structures):
                p: Dict[str, Any] = {}
                try:
                    p["energy_eV"] = float(at.get_potential_energy())
                    p["energy_eV_fallback"] = True
                except Exception:
                    pass
                try:
                    forces = at.get_forces()
                    if forces is not None:
                        p["forces_eV_per_A"] = np.asarray(forces, dtype=float)
                        p["forces_eV_per_A_fallback"] = True
                except Exception:
                    pass
                try:
                    stress = at.get_stress()
                    if stress is not None:
                        p["stress_eV_per_A3"] = np.asarray(stress, dtype=float).ravel()
                        p["stress_eV_per_A3_fallback"] = True
                except Exception:
                    pass
                props_map[i] = p

            last_idx = len(structures) - 1
            p_last = props_map[last_idx]

            ef = parse_outcar_efermi(outcar_path)
            if ef is not None:
                p_last["fermi_eV"] = float(ef)
                p_last["fermi_eV_up"] = float(ef)
                p_last["fermi_eV_down"] = float(ef)

            eigenval_path = os.path.join(calc_dir, "EIGENVAL")
            if os.path.isfile(eigenval_path):
                try:
                    p_last.update(band_edges_from_eigenval(eigenval_path))
                except Exception as e:
                    print(f"[WARN] EIGENVAL 解析失败({calc_dir}): {e}")

            pot = _get_locpot_total_3d(calc_dir)
            if pot is not None:
                try:
                    evac = vacuum_level_from_planar(pot, vacuum_direction=2, smooth_window=9, top_fraction=0.12)
                    p_last["vacuum_level_eV"] = float(evac)
                except Exception as e:
                    print(f"[WARN] LOCPOT 真空能级计算失败({calc_dir}): {e}")

            if ("vacuum_level_eV" in p_last) and ("fermi_eV" in p_last):
                p_last["work_function_eV"] = float(p_last["vacuum_level_eV"] - p_last["fermi_eV"])

            dip = parse_outcar_dipole_moment(outcar_path)
            if dip is not None:
                p_last["dipole_eAng"] = dip

            return structures, props_map, "OUTCAR", "outcar", meta

        except Exception as e:
            print(f"[WARN] 解析 OUTCAR 失败，将回退到 XDATCAR：{e}")

    xdatcar = os.path.join(calc_dir, "XDATCAR")
    if not os.path.isfile(xdatcar):
        raise FileNotFoundError(f"未找到 {calc_dir} 的 vasprun.xml(.gz)、OUTCAR 或 XDATCAR")

    structures = read(xdatcar, index=":")
    if not structures:
        raise RuntimeError("XDATCAR 读取到 0 个离子步")

    if os.path.isfile(outcar_path):
        ionic_ok, elec_ok = _outcar_laststep_convergence(outcar_path)
        meta["ionic_ok_last"] = ionic_ok
        meta["elec_ok_last"] = elec_ok
    else:
        meta["ionic_ok_last"] = None
        meta["elec_ok_last"] = None

    oszicar = os.path.join(calc_dir, "OSZICAR")
    energies = parse_oszicar_energies(oszicar)
    if not energies and os.path.isfile(outcar_path):
        lastE = parse_outcar_last_energy(outcar_path)
        if lastE is not None:
            energies = [lastE] * len(structures)

    forces_last = parse_outcar_forces(outcar_path) if os.path.isfile(outcar_path) else None
    stress_last = parse_outcar_stress_voigt_ev_per_a3(outcar_path) if os.path.isfile(outcar_path) else None
    magmoms_last = parse_outcar_magmoms(outcar_path) if os.path.isfile(outcar_path) else None

    props_map = {}
    n = len(structures)
    for i in range(n):
        p: Dict[str, Any] = {}
        if energies:
            idx = min(i, len(energies) - 1)
            if energies[idx] is not None:
                p["energy_eV"] = float(energies[idx])
                p["energy_eV_fallback"] = True

        if i == n - 1:
            if forces_last is not None:
                p["forces_eV_per_A"] = np.asarray(forces_last, dtype=float)
                p["forces_eV_per_A_fallback"] = True
            if stress_last is not None:
                p["stress_eV_per_A3"] = np.asarray(stress_last, dtype=float).ravel()
                p["stress_eV_per_A3_fallback"] = True
            if magmoms_last is not None:
                p["magmoms_muB"] = np.asarray(magmoms_last, dtype=float)
                p["magmoms_muB_fallback"] = True
                p["magmom_muB"] = float(np.sum(magmoms_last))
                p["magmom_muB_fallback"] = True

        props_map[i] = p

    last_idx = n - 1
    p_last = props_map[last_idx]

    if os.path.isfile(outcar_path):
        ef = parse_outcar_efermi(outcar_path)
        if ef is not None:
            p_last["fermi_eV"] = float(ef)
            p_last["fermi_eV_up"] = float(ef)
            p_last["fermi_eV_down"] = float(ef)

    eigenval_path = os.path.join(calc_dir, "EIGENVAL")
    if os.path.isfile(eigenval_path):
        try:
            p_last.update(band_edges_from_eigenval(eigenval_path))
        except Exception as e:
            print(f"[WARN] EIGENVAL 解析失败({calc_dir}): {e}")

    pot = _get_locpot_total_3d(calc_dir)
    if pot is not None:
        try:
            evac = vacuum_level_from_planar(pot, vacuum_direction=2, smooth_window=9, top_fraction=0.12)
            p_last["vacuum_level_eV"] = float(evac)
        except Exception as e:
            print(f"[WARN] LOCPOT 真空能级计算失败({calc_dir}): {e}")

    if ("vacuum_level_eV" in p_last) and ("fermi_eV" in p_last):
        p_last["work_function_eV"] = float(p_last["vacuum_level_eV"] - p_last["fermi_eV"])

    if os.path.isfile(outcar_path):
        dip = parse_outcar_dipole_moment(outcar_path)
        if dip is not None:
            p_last["dipole_eAng"] = dip

    return structures, props_map, os.path.basename(xdatcar), "fallback", meta


# ============================================================
# 写库（data 中不保存 vasp_input_parameters）
# ============================================================

def attach_properties_to_atoms(
    at: Atoms,
    step_props: Dict[str, Any],
    step_idx: int,
    calc_dir: str,
    source_name: str,
    source_from: str
):
    at.info["calculator"] = "VASP"
    at.info["source_dir"] = os.path.abspath(calc_dir)
    at.info["source_file"] = source_name
    at.info["source_from"] = source_from
    at.info["step_index"] = step_idx

    if step_props.get("energy_eV") is not None:
        at.info["phys_energy_eV"] = float(step_props["energy_eV"])
        if "energy_eV_fallback" in step_props:
            at.info["phys_energy_eV_fallback"] = bool(step_props["energy_eV_fallback"])

    if step_props.get("forces_eV_per_A") is not None:
        at.arrays["phys_forces_eV_per_A"] = np.asarray(step_props["forces_eV_per_A"], dtype=float)
        if "forces_eV_per_A_fallback" in step_props:
            at.info["phys_forces_eV_per_A_fallback"] = bool(step_props["forces_eV_per_A_fallback"])

    if step_props.get("stress_eV_per_A3") is not None:
        stress = np.asarray(step_props["stress_eV_per_A3"], dtype=float).ravel()
        at.info["phys_stress_voigt_eV_per_A3"] = stress.tolist()
        if "stress_eV_per_A3_fallback" in step_props:
            at.info["phys_stress_voigt_eV_per_A3_fallback"] = bool(step_props["stress_eV_per_A3_fallback"])


def add_record(
    db,
    existing_keys: set,
    at: Atoms,
    step_props: Dict[str, Any],
    calc_params: Dict[str, Any],
    description: str,
    datatype: str,
    step_idx: int,
    calc_dir: str,
    source_name: str,
    source_from: str,
    signature: Optional[str]
) -> bool:
    key = make_canonical_key(at, step_props, step_idx)
    if key in existing_keys:
        print(f"[INFO] 记录已存在（内容+步号重复），跳过: {key}")
        return False

    # 如果本步不想写 calculator_parameters，就把已有的 calc.parameters 清空
    if not calc_params:
        if at.calc is not None:
            try:
                if isinstance(getattr(at.calc, "parameters", None), dict):
                    at.calc.parameters = {}
            except Exception:
                pass

    ensure_calculator_parameters_on_atoms(at, calc_params, step_props)

    data_to_save: Dict[str, Any] = {
        "source_from": source_from,
        "source_file": source_name,
        "step_index": step_idx,
        "source_dir": os.path.abspath(calc_dir),
    }

    # 额外写入 signature（用于追踪/并行合并后定位来源）
    if signature:
        data_to_save["source_signature"] = str(signature)

    if step_props.get("energy_eV") is not None:
        data_to_save["phys_energy_eV"] = float(step_props["energy_eV"])
        if "energy_eV_fallback" in step_props:
            data_to_save["phys_energy_eV_fallback"] = bool(step_props["energy_eV_fallback"])

    mapping = {
        "bandgap_eV": "phys_bandgap_eV",
        "vbm_eV": "phys_vbm_eV",
        "cbm_eV": "phys_cbm_eV",
        "fermi_eV": "phys_fermi_eV",
        "bandgap_eV_up": "phys_bandgap_eV_up",
        "bandgap_eV_down": "phys_bandgap_eV_down",
        "vbm_eV_up": "phys_vbm_eV_up",
        "vbm_eV_down": "phys_vbm_eV_down",
        "cbm_eV_up": "phys_cbm_eV_up",
        "cbm_eV_down": "phys_cbm_eV_down",
        "fermi_eV_up": "phys_fermi_eV_up",
        "fermi_eV_down": "phys_fermi_eV_down",
        "vacuum_level_eV": "phys_vacuum_level_eV",
        "work_function_eV": "phys_work_function_eV",
    }
    for k_in, k_out in mapping.items():
        if step_props.get(k_in) is not None:
            data_to_save[k_out] = float(step_props[k_in])

    if step_props.get("dipole_eAng") is not None:
        dip = [float(x) for x in step_props["dipole_eAng"]]
        if len(dip) == 3:
            data_to_save["phys_dipole_eAng"] = dip
            data_to_save["phys_dipole_z_eAng"] = float(dip[2])

    try:
        data_to_save["phys_thickness_A"] = compute_slab_thickness_A(at, axis=2)
        data_to_save["phys_vacuum_thickness_A"] = compute_vacuum_thickness_A(at, axis=2)
        data_to_save["phys_area_A2"] = compute_cell_area_A2(at, axis=2)
    except Exception:
        pass

    try:
        data_to_save.update(spglib_symmetry_info(at, symprec=1e-5))
    except Exception:
        pass

    attach_properties_to_atoms(at, step_props, step_idx, calc_dir, source_name, source_from)

    try:
        db.write(
            at,
            key=key,
            description=description,
            datatype=datatype,
            data=data_to_save
        )
        existing_keys.add(key)
        print(f"[INFO] 写入记录: {key} (来自 {source_name}, {source_from})")
        return True
    except Exception as e:
        print(f"[WARN] 写入失败: {key} → {e}")
        return False


# ============================================================
# 遍历目录与 DB 设置
# ============================================================

def is_target_dir(d: str) -> bool:
    try:
        files = set(os.listdir(d))
    except Exception:
        return False
    return bool(files.intersection({"vasprun.xml", "vasprun.xml.gz", "OUTCAR", "XDATCAR"}))

def find_target_dirs(root_dir: str) -> List[str]:
    targets: List[str] = []
    for d, _, files in os.walk(root_dir):
        if (("vasprun.xml" in files) or ("vasprun.xml.gz" in files) or
            ("OUTCAR" in files) or ("XDATCAR" in files)):
            targets.append(d)
    return targets

def _apply_sqlite_pragmas(db):
    conn = getattr(db, "connection", None) or getattr(db, "raw_connection", None)
    if conn is None:
        return
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA temp_store=MEMORY;")
        cur.execute("PRAGMA cache_size=-200000;")
        conn.commit()
    except Exception as e:
        print(f"[WARN] 设置 SQLite PRAGMA 失败：{e}")


# ============================================================
# 目录处理：组装 calc_params（legacy + rich + INCAR + KPOINTS）并补齐 keys
# ============================================================

def process_one_dir(
    db,
    existing_keys: set,
    calc_dir: str,
    description: str,
    datatype: str,
    key_universe: set,
    signature: Optional[str]
) -> Tuple[int, str, Dict[str, Any]]:
    """
    返回：(写入条数, status, extra_meta)
    status ∈ {"ok", "skip_unconverged", "fail"}
    """
    print(f"[INFO] 处理目录 {calc_dir} 的所有离子步骤...")

    try:
        structures, props_map, source_name, source_from, meta = parse_vasp_any(calc_dir)
    except Exception as e:
        print(f"[WARN] 处理目录 {calc_dir} 失败：{e}")
        return 0, "fail", {"error": str(e)}

    n_steps = len(structures)
    ionic_ok_last = meta.get("ionic_ok_last", None)
    elec_ok_last = meta.get("elec_ok_last", None)

    if should_skip_dir_by_convergence(n_steps, ionic_ok_last, elec_ok_last):
        print(f"[WARN] 跳过目录（最后步不收敛或无法确认收敛）: "
              f"{calc_dir} | nsteps={n_steps} ionic_ok_last={ionic_ok_last} elec_ok_last={elec_ok_last}")
        return 0, "skip_unconverged", {
            "nsteps": int(n_steps),
            "ionic_ok_last": ionic_ok_last,
            "elec_ok_last": elec_ok_last
        }

    # --- 1) vasprun 参数（上传只有 vasprun 时关键）---
    vxml_path = None
    for name in ("vasprun.xml", "vasprun.xml.gz"):
        p = os.path.join(calc_dir, name)
        if os.path.isfile(p):
            vxml_path = p
            break

    vasprun_params = parse_vasp_parameters_from_vasprun(vxml_path) if vxml_path else {}

    # --- 2) INCAR / OUTCAR / KPOINTS（如果目录里有，就继续补全）---
    incar_path = os.path.join(calc_dir, "INCAR")
    incar_params = load_incar_params(incar_path) if os.path.isfile(incar_path) else {}

    outcar_path = os.path.join(calc_dir, "OUTCAR")
    outcar_params_legacy = parse_vasp_parameters_from_outcar_legacy(outcar_path) if os.path.isfile(outcar_path) else {}
    outcar_params_rich = parse_vasp_parameters_from_outcar_rich(outcar_path) if os.path.isfile(outcar_path) else {}

    # 合并优先级建议：vasprun < outcar_legacy < outcar_rich < INCAR（存在即覆盖）
    calc_params: Dict[str, Any] = {
        **vasprun_params,
        **outcar_params_legacy,
        **outcar_params_rich,
        **incar_params,
    }

    kpoints_path = os.path.join(calc_dir, "KPOINTS")
    if os.path.isfile(kpoints_path):
        kpoints_info = parse_kpoints_file_general(kpoints_path)
        if kpoints_info:
            calc_params["kpoints_generation"] = kpoints_info

    count = 0
    last_idx = len(structures) - 1

    for i, at in enumerate(structures):
        if i == last_idx:
            # 最后一步才写 calculator_parameters
            calc_params_i = calc_params

            # universe 逻辑也放到最后一步做
            if source_from != "vasprun":
                calc_params_i = pad_calc_params_to_universe(calc_params_i, key_universe)
            else:
                # vasprun 情况下也允许扩展 universe（你的原逻辑保留）
                key_universe.update(calc_params_i.keys())
        else:
            calc_params_i = {}

        ok = add_record(
            db=db,
            existing_keys=existing_keys,
            at=at,
            step_props=props_map.get(i, {}),
            calc_params=calc_params_i,
            description=description,
            datatype=datatype,
            step_idx=i,
            calc_dir=calc_dir,
            source_name=source_name,
            source_from=source_from,
            signature=signature
        )
        if ok:
            count += 1

    print(f"[DONE] {calc_dir}（{source_name}, {source_from}）写入 {count} 条记录")
    return count, "ok", {
        "nsteps": int(n_steps),
        "ionic_ok_last": ionic_ok_last,
        "elec_ok_last": elec_ok_last,
        "source_file": source_name,
        "source_from": source_from
    }


# ============================================================
# main
# ============================================================

def main(
    calc_dir=".",
    db_path="ase.db",
    description="VASP ionic steps",
    datatype="any",
    retry_nonok: bool = False,
    retry_failed_only: bool = False,
    force: bool = False,
    recursive: bool = True,
    targets_file: str = "",
    base_manifests: Optional[List[str]] = None,
):
    """
    retry_nonok / retry_failed_only:
      - 只重试 manifest status in {"fail","skip_unconverged"}
      - 不会重跑 ok（除非 force=True）

    force:
      - 强制重跑，包括 manifest 里 status=ok 的目录
    """

    if targets_file:
        tf = os.path.abspath(targets_file)
        if not os.path.isfile(tf):
            print(f"[ERROR] targets_file not found: {tf}")
            return
        target_dirs = read_targets_file(tf)
    else:
        if recursive:
            target_dirs = find_target_dirs(calc_dir)
        else:
            target_dirs = [calc_dir] if is_target_dir(calc_dir) else []

    if not target_dirs:
        print("[ERROR] 未找到目标目录（当前目录不含 marker，或递归下无 marker）。")
        return

    db = connect(db_path)
    _apply_sqlite_pragmas(db)

    existing_keys = preload_existing_keys(db)
    key_universe = build_parameter_key_universe_from_db(db)

    manifest_path = manifest_path_from_db_path(db_path)

    all_manifests: List[str] = []
    if base_manifests:
        all_manifests.extend([x for x in base_manifests if x])

    # 把“本 worker 自己的 manifest”也纳入（本次运行内 resume）
    all_manifests.append(manifest_path)

    manifest_map = load_manifest_map_multi(all_manifests)

    total = 0
    skipped_ok = 0
    skipped_manifest_nonok = 0
    failed = 0

    # 统一判断：是否允许重试 non-ok
    allow_retry_nonok = bool(retry_nonok or retry_failed_only)

    n_all = len(target_dirs)

    for idx, d in enumerate(target_dirs, start=1):
        absd = os.path.abspath(d)
        print(f"[INFO] ({idx}/{n_all}) processing: {absd}", flush=True)

        sig = calc_dir_signature(d)
        if not sig:
            failed += 1
            rec = {
                "time": _utc_now_iso(),
                "signature": None,
                "status": "fail",
                "reason": "no_signature_file",
                "source_dir": absd,
                "db_path": os.path.abspath(db_path),
            }
            append_manifest_record(manifest_path, rec)
            print(f"[WARN] {d} 无法计算 signature（缺少代表文件），已记入 manifest fail。")
            continue

        prev = manifest_map.get(sig)

        # ------------------------------
        # 新的 manifest 跳过/重试策略（核心修改点）
        # ok 永远跳过（除非 --force）
        # fail/skip_unconverged 默认跳过；只有开启 retry_* 才重试
        # ------------------------------
        if isinstance(prev, dict) and (not force):
            prev_status = prev.get("status", None)

            if prev_status == "ok":
                skipped_ok += 1
                continue

            if prev_status in ("fail", "skip_unconverged"):
                if not allow_retry_nonok:
                    skipped_manifest_nonok += 1
                    continue
                # 否则允许重试：继续往下处理

        try:
            written, status, extra = process_one_dir(db, existing_keys, d, description, datatype, key_universe, sig)
            total += written
            if status == "fail":
                failed += 1

            rec = {
                "time": _utc_now_iso(),
                "signature": sig,
                "status": status,
                "source_dir": absd,
                "db_path": os.path.abspath(db_path),
                "written": int(written),
            }
            if isinstance(extra, dict):
                rec.update(extra)

            append_manifest_record(manifest_path, rec)
            manifest_map[sig] = rec

        except Exception as e:
            failed += 1
            rec = {
                "time": _utc_now_iso(),
                "signature": sig,
                "status": "fail",
                "source_dir": absd,
                "db_path": os.path.abspath(db_path),
                "error": str(e),
            }
            append_manifest_record(manifest_path, rec)
            manifest_map[sig] = rec
            print(f"[WARN] 处理目录 {d} 失败：{e}")

    print(f"[SUMMARY] 共写入 {total} 条记录到 {db_path}，共处理/扫描 {len(target_dirs)} 个目录。")
    print(f"[SUMMARY] manifest: {manifest_path}")
    print(f"[SUMMARY] 跳过已成功(ok)目录: {skipped_ok}")
    print(f"[SUMMARY] 跳过非ok目录(默认策略): {skipped_manifest_nonok}")
    print(f"[SUMMARY] 本次失败目录: {failed}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Recursively save ionic steps from VASP outputs into ASE DB, skipping unconverged last-step runs, with manifest-based resume."
    )
    parser.add_argument("--calc_dir", type=str, default=".", help="包含计算结果的顶层目录（递归搜索）")
    parser.add_argument("--db_path", type=str, default="ase.db", help="输出数据库路径")
    parser.add_argument("--description", type=str, default="VASP ionic steps", help="记录描述")
    parser.add_argument("--datatype", type=str, default="any", help="数据类型标签")
    parser.add_argument(
        "--targets_file",
        type=str,
        default="",
        help="从文件读取要处理的目录列表（每行一个目录）。若提供则优先使用（推荐用于 chunk worker）。"
    )
    parser.add_argument(
        "--base_manifest",
        action="append",
        default=[],
        help="额外指定一个(或多个) manifest.jsonl 作为全局已处理记录（可重复指定多次）。"
    )

    # 保留原参数名，但“语义修正”为：只重试 fail/skip_unconverged，不会重跑 ok
    parser.add_argument(
        "--retry_nonok",
        action="store_true",
        help="若指定，则会重新尝试处理 manifest 里 status=fail/skip_unconverged 的目录（仍会跳过 status=ok）。"
    )

    # 新增更明确的别名参数（与 retry_nonok 等价）
    parser.add_argument(
        "--retry_failed_only",
        action="store_true",
        help="只重试 manifest 里 status=fail/skip_unconverged 的目录（仍会跳过 status=ok）。"
    )

    # 新增强制重跑参数
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制重新处理，即使 manifest 里 status=ok 也会重跑。"
    )

    parser.add_argument("--recursive", type=int, default=1, help="1=递归扫描子目录(默认); 0=只处理calc_dir本身")
    args = parser.parse_args()

    main(
        args.calc_dir,
        args.db_path,
        args.description,
        args.datatype,
        args.retry_nonok,
        args.retry_failed_only,
        args.force,
        recursive=bool(args.recursive),
        targets_file=args.targets_file,
        base_manifests=args.base_manifest,
    )
