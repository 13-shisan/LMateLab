// frontend/src/pages/db/QeEpwTaskDetail.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import DbLayout from "./DbLayout";
import { API_BASE } from "../../api/config";
import { colorForElement } from "../../utils/elementColors";

function getAuthHeaders() {
    const token =
        localStorage.getItem("token") ||
        localStorage.getItem("access_token") ||
        sessionStorage.getItem("token") ||
        "";
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
}

async function fetchJson(url) {
    const resp = await fetch(url, { method: "GET", headers: getAuthHeaders() });
    const ct = resp.headers.get("content-type") || "";
    const data = ct.includes("application/json") ? await resp.json() : null;
    if (!resp.ok) {
        const msg =
        typeof data?.detail === "string"
            ? data.detail
            : data?.detail
            ? JSON.stringify(data.detail)
            : `请求失败（${resp.status}）`;
        throw new Error(msg);
    }
    return data;
}

function flattenObjectToPairs(obj, prefix = "", out = []) {
    if (obj === null || obj === undefined) return out;

    if (Array.isArray(obj)) {
        out.push({ k: prefix || "(array)", v: JSON.stringify(obj) });
        return out;
    }
    if (typeof obj !== "object") {
        out.push({ k: prefix || "(value)", v: String(obj) });
        return out;
    }

    const keys = Object.keys(obj).sort();
    for (const key of keys) {
        const val = obj[key];
        const nextPrefix = prefix ? `${prefix}.${key}` : key;

        if (val && typeof val === "object" && !Array.isArray(val)) {
        flattenObjectToPairs(val, nextPrefix, out);
        } else if (Array.isArray(val)) {
        out.push({ k: nextPrefix, v: JSON.stringify(val) });
        } else {
        out.push({ k: nextPrefix, v: String(val) });
        }
    }
    return out;
}

function safeNum(x) {
    const n = Number(x);
    return Number.isFinite(n) ? n : null;
}

const AVOGADRO = 6.02214076e23; // mol^-1

function norm3(v) {
  const x = Number(v?.[0]) || 0;
  const y = Number(v?.[1]) || 0;
  const z = Number(v?.[2]) || 0;
  return Math.sqrt(x * x + y * y + z * z);
}

// 由 a,b,c,alpha,beta,gamma 构造 3×3 cell（Å），行向量分别是 a,b,c
function latticeToCell(a, b, c, alphaDeg, betaDeg, gammaDeg) {
  const alpha = (Number(alphaDeg) || 0) * Math.PI / 180;
  const beta = (Number(betaDeg) || 0) * Math.PI / 180;
  const gamma = (Number(gammaDeg) || 0) * Math.PI / 180;

  const ca = Math.cos(alpha), cb = Math.cos(beta), cg = Math.cos(gamma);
  const sg = Math.sin(gamma);

  // a 向量
  const ax = Number(a) || 0, ay = 0, az = 0;

  // b 向量
  const bx = (Number(b) || 0) * cg;
  const by = (Number(b) || 0) * sg;
  const bz = 0;

  // c 向量（通用三斜）
  const cx = (Number(c) || 0) * cb;
  const cy = (Number(c) || 0) * ((ca - cb * cg) / (sg || 1e-12));
  const cz2 = (Number(c) || 0) * (Number(c) || 0) - cx * cx - cy * cy;
  const cz = cz2 > 0 ? Math.sqrt(cz2) : 0;

  return [
    [ax, ay, az],
    [bx, by, bz],
    [cx, cy, cz],
  ];
}

function fracToCart(frac, cell) {
  const u = Number(frac?.[0]) || 0;
  const v = Number(frac?.[1]) || 0;
  const w = Number(frac?.[2]) || 0;

  const a = cell[0], b = cell[1], c = cell[2];
  return [
    u * a[0] + v * b[0] + w * c[0],
    u * a[1] + v * b[1] + w * c[1],
    u * a[2] + v * b[2] + w * c[2],
  ];
}

function computeDensityGcm3({ elemCounts, atomicSpecies, volumeA3 }) {
  const V = Number(volumeA3);
  if (!Number.isFinite(V) || V <= 0) return null;

  // atomicSpecies 可能是 [{element, mass}, ...]
  const massMap = new Map();
  if (Array.isArray(atomicSpecies)) {
    for (const it of atomicSpecies) {
      const el = String(it?.element || "").trim();
      const m = Number(it?.mass);
      if (el && Number.isFinite(m)) massMap.set(el, m);
    }
  }

  let massAmu = 0;
  for (const [el, n] of Object.entries(elemCounts || {})) {
    const m = massMap.get(el);
    if (!Number.isFinite(m)) return null; // 没质量就算不了
    massAmu += m * (Number(n) || 0);
  }

  const massG = massAmu / AVOGADRO;     // amu == g/mol
  const volumeCm3 = V * 1e-24;          // Å^3 -> cm^3
  return massG / volumeCm3;
}

function latticeParamsFromCell(cell) {
    if (!Array.isArray(cell) || cell.length !== 3) return null;
    const a = cell[0], b = cell[1], c = cell[2];
    const la = norm3(a), lb = norm3(b), lc = norm3(c);

    function dot(u, v) {
        return (Number(u?.[0])||0)*(Number(v?.[0])||0) +
            (Number(u?.[1])||0)*(Number(v?.[1])||0) +
            (Number(u?.[2])||0)*(Number(v?.[2])||0);
    }
    function clamp(x) { return Math.max(-1, Math.min(1, x)); }
    const alpha = Math.acos(clamp(dot(b, c) / ((lb*lc) || 1e-12))) * 180 / Math.PI;
    const beta  = Math.acos(clamp(dot(a, c) / ((la*lc) || 1e-12))) * 180 / Math.PI;
    const gamma = Math.acos(clamp(dot(a, b) / ((la*lb) || 1e-12))) * 180 / Math.PI;

    // volume = |a · (b × c)|
    const bx = Number(b?.[0])||0, by = Number(b?.[1])||0, bz = Number(b?.[2])||0;
    const cx = Number(c?.[0])||0, cy = Number(c?.[1])||0, cz = Number(c?.[2])||0;
    const bxc = [by*cz - bz*cy, bz*cx - bx*cz, bx*cy - by*cx];
    const ax = Number(a?.[0])||0, ay = Number(a?.[1])||0, az = Number(a?.[2])||0;
    const volume = Math.abs(ax*bxc[0] + ay*bxc[1] + az*bxc[2]);

    return { a: la, b: lb, c: lc, alpha, beta, gamma, volume };
}

// ✅ 新版：按你后端实际结构解析
// 返回：用于 UI + 3Dmol 的统一对象
function parseQeStructureFromCp(cp) {
    const s = cp?.structure;
    if (!s || typeof s !== "object") return null;

    // 结构名：后端建议用 cp.structure_name，这里只是兜底
    const structureName = (typeof s?.structure === "string" && s.structure.trim())
        ? s.structure.trim()
        : "";

    const natoms = Number.isFinite(Number(s?.nat)) ? Number(s.nat) : null;
    const ntyp = Number.isFinite(Number(s?.ntyp)) ? Number(s.ntyp) : null;

    // ---- 原子分数坐标：structure.atomic_positions.atoms ----
    const ap = s?.atomic_positions;
    const apUnit = String(ap?.unit || "").toLowerCase().trim(); // 期望 "crystal"
    const atoms = Array.isArray(ap?.atoms) ? ap.atoms : [];

    const symbols = [];
    const atomsFrac = [];
    const elemCounts = {};

    for (const a of atoms) {
        const el = a?.element ? String(a.element).trim() : "";
        const c = Array.isArray(a?.coord) ? a.coord : null;
        if (!el || !c || c.length < 3) continue;

        symbols.push(el);
        const frac = [Number(c[0]) || 0, Number(c[1]) || 0, Number(c[2]) || 0];
        atomsFrac.push(frac);
        elemCounts[el] = (elemCounts[el] || 0) + 1;
    }

    // ---- 晶格：structure.cell_parameters.lattice（你这边是 3×3 矩阵）----
    const latRaw = s?.cell_parameters?.lattice ?? null;

    let cell = null;
    if (Array.isArray(latRaw) && latRaw.length === 3 && Array.isArray(latRaw[0])) {
        cell = latRaw.map((row) => row.map((v) => Number(v) || 0));
    } else if (Array.isArray(s?.cell_parameters?.cell) && s.cell_parameters.cell.length === 3) {
        // 兼容未来字段
        cell = s.cell_parameters.cell.map((row) => row.map((v) => Number(v) || 0));
    } else {
        cell = null;
    }

    // ---- 生成 positions（Å）：crystal + cell -> cart ----
    let positions = null;
    if (apUnit === "crystal" && cell && atomsFrac.length) {
        positions = atomsFrac.map((f) => fracToCart(f, cell));
    } else {
        positions = null;
    }

    // ---- dimensionality：优先用 assume_isolated，其次用 c/a 比例兜底 ----
    const assumeIso = String(s?.assume_isolated ?? "").toLowerCase();
    let dimensionality = 3;
    if (assumeIso && assumeIso !== "0" && assumeIso !== "none" && assumeIso !== "false") {
        dimensionality = 2;
    }

    const lattice = latticeParamsFromCell(cell);
    if (dimensionality === 3 && lattice?.c && lattice?.a && lattice.c > 2.5 * Math.max(lattice.a, lattice.b || 0)) {
        dimensionality = 2;
    }

    const atomicSpecies = Array.isArray(s?.atomic_species) ? s.atomic_species : [];

    return {
        structureName,
        natoms: natoms ?? (symbols.length || null),
        ntyp,

        symbols,
        elemCounts,

        atomsFrac,
        positions,
        cell,

        lattice,          // a,b,c,alpha,beta,gamma,volume（从 cell 推出来）
        dimensionality,   // 2 or 3
        atomicSpecies,
    };
}

export default function QeEpwTaskDetail() {
    const { dbKey, rowId } = useParams(); // 路由：/dashboard/db/qe_epw/task/:dbKey/:rowId
    const navigate = useNavigate();
    const location = useLocation();

    const dbKeyDecoded = useMemo(() => {
        try { return decodeURIComponent(dbKey || ""); } catch { return dbKey || ""; }
    }, [dbKey]);

    const [err, setErr] = useState("");
    const [loading, setLoading] = useState(true);

    const [cp, setCp] = useState(null);              // calculator_parameters 原始对象
    const [qeStruct, setQeStruct] = useState(null);  // 解析后的结构（positions/cell/symbols）
    const [paramItems, setParamItems] = useState([]); // [{k,v}]
    const [title, setTitle] = useState("");

    // Properties tabs（对齐 VASP）
    const [propTab, setPropTab] = useState("band"); // band | dos | phonon
    const [bandImg, setBandImg] = useState("");
    const [bandLoading, setBandLoading] = useState(false);
    const [bandErr, setBandErr] = useState("");
    const [bandMeta, setBandMeta] = useState(null);

    // Atomic Positions 是否展开（对齐 VASP）
    const [apOpen, setApOpen] = useState(false);

    // 3D viewer ref（对齐 VASP）
    const viewerRef = useRef(null);

    // ✅ 目录滚动（复用 VASP ）
    function scrollToId(id) {
        const el = document.getElementById(id);
        if (!el) return;
        const HEADER = 96;
        const top = window.scrollY + el.getBoundingClientRect().top - HEADER;
        window.scrollTo({ top, behavior: "smooth" });
    }

    useEffect(() => {
        let alive = true;
        (async () => {
        setErr("");
        setLoading(true);
        setParamItems([]);
        try {
            // ✅ 直接复用你现成的 QE 接口
            const url =
            `${API_BASE}/api/db/qe_epw/task/${encodeURIComponent(rowId)}/calculator_parameters` +
            `?db=${encodeURIComponent(dbKeyDecoded)}`;

            const data = await fetchJson(url);
            if (!alive) return;

            const cp0 =
                (data?.calculator_parameters && typeof data.calculator_parameters === "object")
                    ? data.calculator_parameters
                    : {};

            setCp(cp0);

            const st = parseQeStructureFromCp(cp0);
            setQeStruct(st);

            setTitle(`QE+EPW 任务详情（db=${dbKeyDecoded}, id=${rowId}）`);

            const pairs = flattenObjectToPairs(cp0);
            pairs.sort((a, b) => a.k.localeCompare(b.k));
            setParamItems(pairs);

            // 切换任务时默认折叠
            setApOpen(false);
        } catch (e) {
            if (!alive) return;
            setErr(String(e?.message || e));
        } finally {
            if (!alive) return;
            setLoading(false);
        }
        })();
        return () => { alive = false; };
    }, [dbKeyDecoded, rowId]);

    useEffect(() => {
        let alive = true;

        (async () => {
            if (!dbKeyDecoded || !rowId) return;

            // 切换任务先清空
            setBandImg("");
            setBandErr("");
            setBandMeta(null);


            // 只在 tab=band 时再拉（可选；你也可以不加这个条件）
            // if (propTab !== "band") return;

            setBandLoading(true);
            try {
            const url =
                `${API_BASE}/api/db/qe_epw/task/${encodeURIComponent(rowId)}/band-plot` +
                `?db=${encodeURIComponent(dbKeyDecoded)}`;

            const data = await fetchJson(url);
            if (!alive) return;

            setBandImg(data?.image_base64 || "");
            setBandMeta(data || null);
            } catch (e) {
            if (!alive) return;
            setBandErr(String(e?.message || e));
            } finally {
            if (alive) setBandLoading(false);
            }
        })();

        return () => { alive = false; };
    }, [dbKeyDecoded, rowId /*, propTab */]);

    useEffect(() => {
        if (!qeStruct?.positions || !viewerRef.current) return;

        const $3Dmol = window.$3Dmol;
        if (!$3Dmol) return;

        const { positions, cell, symbols } = qeStruct;
        if (!Array.isArray(positions) || positions.length === 0) return;

        // ---- 1) 组装 XYZ ----
        let xyz = "";
        xyz += `${positions.length}\n`;
        xyz += `generated\n`;
        for (let i = 0; i < positions.length; i++) {
            const s = symbols?.[i] || "X";
            const [x, y, z] = positions[i];
            xyz += `${s} ${x} ${y} ${z}\n`;
        }

        // ---- 2) 初始化 viewer ----
        viewerRef.current.innerHTML = "";
        const viewer = $3Dmol.createViewer(viewerRef.current, { backgroundColor: "white" });
        viewer.addModel(xyz, "xyz");
        viewer.setStyle({}, {});

        // 按元素分别上色
        const uniq = Array.from(new Set((symbols || []).filter(Boolean)));
        for (const el of uniq) {
            viewer.setStyle(
            { elem: el },
            {
                stick: { radius: 0.18, color: colorForElement(el) },
                sphere: { scale: 0.25, color: colorForElement(el) },
            }
            );
        }
        if (uniq.length === 0) {
            viewer.setStyle({}, { stick: { radius: 0.18 }, sphere: { scale: 0.25 } });
        }

        // ---- 3) 画晶格框线（如果有 cell=3x3）----
        if (Array.isArray(cell) && cell.length === 3) {
            function vAdd(a, b) { return { x: a.x + b.x, y: a.y + b.y, z: a.z + b.z }; }
            function vMul(a, s) { return { x: a.x * s, y: a.y * s, z: a.z * s }; }

            const a = { x: cell?.[0]?.[0] || 0, y: cell?.[0]?.[1] || 0, z: cell?.[0]?.[2] || 0 };
            const b = { x: cell?.[1]?.[0] || 0, y: cell?.[1]?.[1] || 0, z: cell?.[1]?.[2] || 0 };
            const c = { x: cell?.[2]?.[0] || 0, y: cell?.[2]?.[1] || 0, z: cell?.[2]?.[2] || 0 };

            const o   = { x: 0, y: 0, z: 0 };
            const A   = a;
            const B   = b;
            const C   = c;
            const AB  = vAdd(a, b);
            const AC  = vAdd(a, c);
            const BC  = vAdd(b, c);
            const ABC = vAdd(AB, c);

            const edges = [
            [o, A], [o, B], [o, C],
            [A, AB], [A, AC],
            [B, AB], [B, BC],
            [C, AC], [C, BC],
            [AB, ABC], [AC, ABC], [BC, ABC],
            ];

            const cellColor = "#111827";
            for (const [p1, p2] of edges) {
            viewer.addLine({ start: p1, end: p2, color: cellColor, linewidth: 2 });
            }

            // a/b/c 轴
            const scale = 0.25;
            const aEnd = vMul(a, scale);
            const bEnd = vMul(b, scale);
            const cEnd = vMul(c, scale);

            viewer.addArrow({ start: o, end: aEnd, color: "#ef4444", radius: 0.06, radiusRatio: 1.6, mid: 0.9 });
            viewer.addArrow({ start: o, end: bEnd, color: "#22c55e", radius: 0.06, radiusRatio: 1.6, mid: 0.9 });
            viewer.addArrow({ start: o, end: cEnd, color: "#3b82f6", radius: 0.06, radiusRatio: 1.6, mid: 0.9 });

            const aLab = vMul(aEnd, 1.08);
            const bLab = vMul(bEnd, 1.08);
            const cLab = vMul(cEnd, 1.08);

            viewer.addLabel("a", { position: aLab, fontColor: "#ef4444", backgroundColor: "rgba(255,255,255,0.0)", fontSize: 16 });
            viewer.addLabel("b", { position: bLab, fontColor: "#22c55e", backgroundColor: "rgba(255,255,255,0.0)", fontSize: 16 });
            viewer.addLabel("c", { position: cLab, fontColor: "#3b82f6", backgroundColor: "rgba(255,255,255,0.0)", fontSize: 16 });
        }

        try { viewer.setProjection("orthographic"); } catch {}
        viewer.zoomTo();
        viewer.render();
        }, [qeStruct]);

    return (
        <DbLayout currentSubPath="/dashboard/db/personal" currentDbType="qe_epw" showDbTypeSelector={true}>
        <div style={{ display: "grid", gridTemplateColumns: "240px 1fr", gap: 14, paddingBottom: 24 }}>
            {/* 左侧目录（复用 VASP 样式） */}
                <aside
                    style={{
                        position: "sticky",
                        top: 84,
                        alignSelf: "start",
                        height: "fit-content",
                        borderRadius: 14,
                        border: "1px solid rgba(229,231,235,1)",
                        background: "rgba(255,255,255,.65)",
                        padding: 12,
                    }}
                >
                <div style={{ fontWeight: 900, marginBottom: 10 }}>TABLE OF CONTENTS</div>

                <button
                    type="button"
                    onClick={() => scrollToId("summary")}
                    style={{ display: "block", padding: "8px 8px", border: "none", background: "transparent", textAlign: "left", width: "100%", cursor: "pointer", fontSize: 14 }}
                >
                    Summary
                </button>

                <button
                    type="button"
                    onClick={() => scrollToId("calculator-parameters")}
                    style={{ display: "block", padding: "8px 8px", border: "none", background: "transparent", textAlign: "left", width: "100%", cursor: "pointer", fontSize: 14 }}
                >
                    Calculator Parameters
                </button>
                <button
                    type="button"
                    onClick={() => scrollToId("crystal-structure")}
                    style={{ display: "block", padding: "8px 8px", border: "none", background: "transparent", textAlign: "left", width: "100%", cursor: "pointer", fontSize: 14 }}
                    >
                    Crystal Structure
                </button>

                <button
                    type="button"
                    onClick={() => scrollToId("electronic-properties")}
                    style={{ display: "block", padding: "8px 8px", border: "none", background: "transparent", textAlign: "left", width: "100%", cursor: "pointer", fontSize: 14 }}
                    >
                    Properties
                </button>
            </aside>

            {/* 右侧内容 */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <section id="summary" style={{ scrollMarginTop: 96 }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
                <h2 style={{ margin: 0 }}>{title || "任务详情"}</h2>

                <button
                    type="button"
                    onClick={() => {
                        const backTo = location.state?.backTo;
                        if (typeof backTo === "string" && backTo.startsWith("/")) {
                            navigate(backTo, { replace: true });
                            return;
                        }
                        navigate(`/dashboard/db/personal/qe-epw?db=${encodeURIComponent(dbKeyDecoded)}`, { replace: true });
                    }}
                    style={{
                    height: 34,
                    borderRadius: 10,
                    padding: "0 12px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    cursor: "pointer",
                    fontSize: 13,
                    }}
                >
                    返回列表
                </button>
                </div>

                {err ? (
                <div style={{ marginTop: 10, padding: 12, borderRadius: 12, background: "rgba(254,242,242,.9)", border: "1px solid rgba(252,165,165,.8)", color: "#991b1b" }}>
                    {err}
                </div>
                ) : null}
            </section>

            <section id="structure" style={{ scrollMarginTop: 96 }}>
                <div className="glass-card" style={{ padding: 14, borderRadius: 14, border: "1px solid rgba(229,231,235,1)", background: "rgba(255,255,255,.6)" }}>
                    <h3 style={{ marginTop: 0 }}>结构区</h3>

                    <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 12 }}>
                    <div>
                        <div
                        ref={viewerRef}
                        style={{
                            width: "100%",
                            height: 460,
                            borderRadius: 12,
                            border: "1px solid rgba(229,231,235,1)",
                            background: "white",
                        }}
                        />
                        {!qeStruct?.positions ? (
                        <div style={{ marginTop: 8, fontSize: 12, color: "#6b7280" }}>
                            结构数据不足，无法绘制 3D（需要 atomic_positions + cell_parameters）。
                        </div>
                        ) : null}
                    </div>

                    <div style={{ fontSize: 13, color: "#111827" }}>
                        <div><b>db</b>: {dbKey}</div>
                        <div><b>row_id</b>: {rowId}</div>

                        <div style={{ marginTop: 8 }}><b>code</b>: {cp?.code ?? "-"}</div>
                        <div><b>calc_type</b>: {cp?.calc_type ?? "-"}</div>

                        <div style={{ marginTop: 8 }}>
                            <b>structure</b>: {cp?.structure_name || "-"}
                        </div>

                        <div><b>natoms</b>: {qeStruct?.natoms ?? "-"}</div>

                        <div style={{ marginTop: 8 }}>
                            <b>composition</b>:{" "}
                            {qeStruct?.elemCounts
                                ? Object.entries(qeStruct.elemCounts)
                                    .sort((a, b) => a[0].localeCompare(b[0]))
                                    .map(([el, n]) => `${el}:${n}`)
                                    .join(", ")
                                : "-"}
                        </div>

                        {/* 元素图例（复用 VASP 的 style） */}
                        <div style={{ marginTop: 12 }}>
                        <div style={{ fontWeight: 800, marginBottom: 6 }}>元素图例</div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
                            {Array.isArray(qeStruct?.symbols) && qeStruct.symbols.length ? (
                            Array.from(new Set(qeStruct.symbols)).sort().map((el) => (
                                <div key={el} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <span style={{ width: 10, height: 10, borderRadius: 999, background: colorForElement(el), border: "1px solid rgba(0,0,0,.15)" }} />
                                <span style={{ fontSize: 12, color: "#374151" }}>{el}</span>
                                </div>
                            ))
                            ) : (
                            <span style={{ color: "#6b7280", fontSize: 12 }}>（无元素信息）</span>
                            )}
                        </div>
                        </div>
                    </div>
                    </div>
                </div>

                {/* Crystal Structure（对齐 VASP：lattice + atomic positions） */}
                <div
                    id="crystal-structure"
                    className="glass-card"
                    style={{ scrollMarginTop: 110, marginTop: 14, padding: 14, borderRadius: 14, border: "1px solid rgba(229,231,235,1)", background: "rgba(255,255,255,.6)" }}
                >
                    <h3 style={{ marginTop: 0 }}>Crystal Structure</h3>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
                    {/* Lattice */}
                    <div style={{ background: "white", border: "1px solid rgba(229,231,235,1)", borderRadius: 12, padding: 12 }}>
                        <div style={{ fontWeight: 900, marginBottom: 10 }}>Lattice (Conventional)</div>

                        {qeStruct?.lattice?.a ? (
                        <div style={{ display: "grid", gridTemplateColumns: "80px 1fr", rowGap: 8, columnGap: 10, fontSize: 13 }}>
                            <div><b>a</b></div><div>{Number(qeStruct.lattice.a).toFixed(4)} Å</div>
                            <div><b>b</b></div><div>{Number(qeStruct.lattice.b).toFixed(4)} Å</div>
                            <div><b>c</b></div><div>{Number(qeStruct.lattice.c).toFixed(4)} Å</div>
                            <div><b>α</b></div><div>{Number(qeStruct.lattice.alpha).toFixed(2)} °</div>
                            <div><b>β</b></div><div>{Number(qeStruct.lattice.beta).toFixed(2)} °</div>
                            <div><b>γ</b></div><div>{Number(qeStruct.lattice.gamma).toFixed(2)} °</div>
                            <div><b>Volume</b></div><div>{qeStruct.lattice.volume != null ? `${Number(qeStruct.lattice.volume).toFixed(3)} Å³` : "-"}</div>
                        </div>
                        ) : (
                        <div style={{ color: "#6b7280", fontSize: 13 }}>暂无晶格参数（structure.cell_parameters.lattice 缺失）</div>
                        )}
                    </div>

                    {/* Properties（先占位） */}
                    <div style={{ background: "white", border: "1px solid rgba(229,231,235,1)", borderRadius: 12, padding: 12 }}>
                        <div style={{ fontWeight: 900, marginBottom: 10 }}>Properties</div>

                        <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", rowGap: 8, columnGap: 10, fontSize: 13 }}>
                        <div><b>Number of Atoms</b></div><div>{qeStruct?.natoms ?? "-"}</div>

                        <div><b>Dimensionality</b></div>
                        <div>{qeStruct?.dimensionality != null ? `${qeStruct.dimensionality}D` : "-"}</div>

                        <div><b>Element Types (ntyp)</b></div><div>{qeStruct?.ntyp ?? "-"}</div>

                        <div><b>Composition</b></div>
                        <div>
                            {qeStruct?.elemCounts
                            ? Object.entries(qeStruct.elemCounts)
                                .sort((a, b) => a[0].localeCompare(b[0]))
                                .map(([el, n]) => `${el}:${n}`)
                                .join(", ")
                            : "-"}
                        </div>
                        </div>

                        {/* atomic_species：元素质量表 */}
                        {Array.isArray(qeStruct?.atomicSpecies) && qeStruct.atomicSpecies.length ? (
                        <div style={{ marginTop: 12, borderTop: "1px solid rgba(229,231,235,1)", paddingTop: 10 }}>
                            <div style={{ fontWeight: 800, marginBottom: 6, fontSize: 13 }}>Atomic Species</div>
                            <div style={{ overflowX: "auto" }}>
                            <table style={{ width: "100%", borderCollapse: "collapse" }}>
                                <thead>
                                <tr style={{ textAlign: "left", borderBottom: "1px solid rgba(229,231,235,1)" }}>
                                    <th style={{ padding: "8px 6px", fontSize: 12, color: "#374151" }}>Element</th>
                                    <th style={{ padding: "8px 6px", fontSize: 12, color: "#374151" }}>Mass (amu)</th>
                                </tr>
                                </thead>
                                <tbody>
                                {qeStruct.atomicSpecies.map((x, i) => (
                                    <tr key={i} style={{ borderBottom: "1px solid rgba(243,244,246,1)" }}>
                                    <td style={{ padding: "8px 6px", fontSize: 13 }}>{x?.element ?? "-"}</td>
                                    <td style={{ padding: "8px 6px", fontSize: 13 }}>
                                        {x?.mass != null ? Number(x.mass).toFixed(6) : "-"}
                                    </td>
                                    </tr>
                                ))}
                                </tbody>
                            </table>
                            </div>
                        </div>
                        ) : null}
                    </div>
                    </div>

                    {/* Atomic Positions（fractional） */}
                    <div style={{ marginTop: 12, background: "white", border: "1px solid rgba(229,231,235,1)", borderRadius: 12, padding: 12 }}>
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 10 }}>
                        <div style={{ fontWeight: 900 }}>Atomic Positions (fractional)</div>

                        {Array.isArray(qeStruct?.atomsFrac) && qeStruct.atomsFrac.length > 10 ? (
                        <button
                            type="button"
                            onClick={() => setApOpen(v => !v)}
                            style={{ height: 30, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white", cursor: "pointer", fontSize: 12, fontWeight: 800 }}
                        >
                            {apOpen ? "收起" : `展开（共 ${qeStruct.atomsFrac.length} 行）`}
                        </button>
                        ) : null}
                    </div>

                    {Array.isArray(qeStruct?.atomsFrac) && qeStruct.atomsFrac.length ? (
                        <div style={{ overflowX: "auto" }}>
                            <table style={{ width: "100%", borderCollapse: "collapse" }}>
                            <thead>
                                <tr style={{ textAlign: "left", borderBottom: "1px solid rgba(229,231,235,1)" }}>
                                <th style={{ padding: "8px 6px", fontSize: 12, color: "#374151" }}>Element</th>
                                <th style={{ padding: "8px 6px", fontSize: 12, color: "#374151" }}>x</th>
                                <th style={{ padding: "8px 6px", fontSize: 12, color: "#374151" }}>y</th>
                                <th style={{ padding: "8px 6px", fontSize: 12, color: "#374151" }}>z</th>
                                </tr>
                            </thead>
                            <tbody>
                                {(apOpen ? qeStruct.atomsFrac : qeStruct.atomsFrac.slice(0, 10)).map((p, i) => (
                                <tr key={i} style={{ borderBottom: "1px solid rgba(243,244,246,1)" }}>
                                    <td style={{ padding: "8px 6px", fontSize: 13 }}>{qeStruct.symbols?.[i] ?? "-"}</td>
                                    <td style={{ padding: "8px 6px", fontSize: 13 }}>{Number(p[0]).toFixed(6)}</td>
                                    <td style={{ padding: "8px 6px", fontSize: 13 }}>{Number(p[1]).toFixed(6)}</td>
                                    <td style={{ padding: "8px 6px", fontSize: 13 }}>{Number(p[2]).toFixed(6)}</td>
                                </tr>
                                ))}
                            </tbody>
                            </table>

                            {!apOpen && qeStruct.atomsFrac.length > 10 ? (
                            <div style={{ marginTop: 8, color: "#6b7280", fontSize: 12 }}>
                                仅显示前 10 行（共 {qeStruct.atomsFrac.length} 行）
                            </div>
                            ) : null}
                        </div>
                        ) : (
                        <div style={{ color: "#6b7280", fontSize: 13 }}>
                            暂无原子分数坐标（需要 structure.atomic_positions.atoms）
                        </div>
                        )}
                    </div>
                </div>
                </section>

            <section id="calculator-parameters" style={{ scrollMarginTop: 96 }}>
                <div className="glass-card" style={{ padding: 14, borderRadius: 14, border: "1px solid rgba(229,231,235,1)", background: "rgba(255,255,255,.6)" }}>
                <h3 style={{ marginTop: 0 }}>Calculator Parameters</h3>

                {loading ? (
                    <div style={{ color: "#6b7280" }}>加载中…</div>
                ) : paramItems.length === 0 ? (
                    <div style={{ color: "#6b7280" }}>暂无 calculator_parameters。</div>
                ) : (
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
                    {paramItems.map(({ k, v }) => (
                        <div key={k} style={{ border: "1px solid rgba(229,231,235,1)", borderRadius: 12, padding: 10, background: "rgba(249,250,251,1)" }}>
                        <div style={{ fontSize: 12, color: "#374151", fontWeight: 800, wordBreak: "break-word" }}>{k}</div>
                        <div style={{ marginTop: 6, fontSize: 12, color: "#111827", wordBreak: "break-word" }}>{v}</div>
                        </div>
                    ))}
                    </div>
                )}
                </div>
            </section>
            <section id="properties" style={{ scrollMarginTop: 96 }}>
                <div
                    id="electronic-properties"
                    className="glass-card"
                    style={{ scrollMarginTop: 110, padding: 14, borderRadius: 14, border: "1px solid rgba(229,231,235,1)", background: "rgba(255,255,255,.6)" }}
                >
                    <h3 style={{ marginTop: 0 }}>电子性质区</h3>

                    <div style={{ display: "flex", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
                    <button
                        type="button"
                        onClick={() => setPropTab("band")}
                        style={{
                        height: 34,
                        borderRadius: 999,
                        padding: "0 14px",
                        border: "1px solid rgba(229,231,235,1)",
                        background: propTab === "band" ? "rgba(37,99,235,0.12)" : "white",
                        color: propTab === "band" ? "#1d4ed8" : "#111827",
                        cursor: "pointer",
                        fontWeight: 800,
                        }}
                    >
                        能带
                    </button>

                    <button
                        type="button"
                        onClick={() => setPropTab("dos")}
                        style={{
                        height: 34,
                        borderRadius: 999,
                        padding: "0 14px",
                        border: "1px solid rgba(229,231,235,1)",
                        background: propTab === "dos" ? "rgba(37,99,235,0.12)" : "white",
                        color: propTab === "dos" ? "#1d4ed8" : "#111827",
                        cursor: "pointer",
                        fontWeight: 800,
                        }}
                    >
                        态密度
                    </button>

                    <button
                        type="button"
                        onClick={() => setPropTab("phonon")}
                        style={{
                        height: 34,
                        borderRadius: 999,
                        padding: "0 14px",
                        border: "1px solid rgba(229,231,235,1)",
                        background: propTab === "phonon" ? "rgba(37,99,235,0.12)" : "white",
                        color: propTab === "phonon" ? "#1d4ed8" : "#111827",
                        cursor: "pointer",
                        fontWeight: 800,
                        }}
                    >
                        声子
                    </button>
                    </div>

                    <div style={{ border: "1px solid rgba(229,231,235,1)", borderRadius: 12, background: "white", padding: 10 }}>
                    {propTab === "band" ? (
                        <>
                            <div style={{ fontWeight: 800, marginBottom: 6 }}>能带</div>

                            {bandImg ? (
                                <>
                                    <img
                                    alt="qe-band"
                                    style={{ width: "100%", height: 520, objectFit: "contain", display: "block" }}
                                    src={`data:image/png;base64,${bandImg}`}
                                    />

                                    {/* ✅ 对齐 VASP：显示 bandgap / VBM / CBM */}
                                    <div style={{ marginTop: 10, fontSize: 13 }}>
                                        <b>Ef (xml)</b>: {bandMeta?.fermi_ev_used != null ? `${Number(bandMeta.fermi_ev_used).toFixed(6)} eV` : "-"} &nbsp; | &nbsp;
                                        <b>VBM (xml)</b>: {bandMeta?.vbm_ev_xml != null ? `${Number(bandMeta.vbm_ev_xml).toFixed(6)} eV` : "-"} &nbsp; | &nbsp;
                                        <b>CBM (xml)</b>: {bandMeta?.cbm_ev_xml != null ? `${Number(bandMeta.cbm_ev_xml).toFixed(6)} eV` : "-"} &nbsp; | &nbsp;
                                        <b>Gap (xml)</b>: {bandMeta?.bandgap_xml_eV != null ? `${Number(bandMeta.bandgap_xml_eV).toFixed(6)} eV` : "-"}
                                    </div>
                                </>
                                ) : bandLoading ? (
                                <div style={{ color: "#6b7280" }}>正在加载能带图…</div>
                                ) : bandErr ? (
                                <div style={{ color: "#991b1b" }}>能带图获取失败：{bandErr}</div>
                                ) : (
                                <div style={{ color: "#6b7280" }}>暂无能带图</div>
                                )}
                        </>
                    ) : propTab === "dos" ? (
                        <div style={{ color: "#6b7280" }}>态密度：后端接口待实现（先保留框架）。</div>
                    ) : (
                        <div style={{ color: "#6b7280" }}>声子：后端接口待实现（先保留框架）。</div>
                    )}
                    </div>
                </div>
            </section>        
            </div>
        </div>
        </DbLayout>
    );
}
