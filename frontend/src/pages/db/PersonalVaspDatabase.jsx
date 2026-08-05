// frontend/src/pages/db/PersonalVaspDatabase.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import DbLayout from "./DbLayout";
import { API_BASE } from "../../api/config";
import { fetchJson } from "../../api/fetchJson";
import { uploadFiles } from "../../api/uploadFiles";
import { downloadAuthedFile } from "../../api/downloadAuthedFile";
import { getPostJsonErrorDetail, postJson } from "../../api/postJson";
import {
  getVaspPresetStorageKey,
  loadPresetState,
  savePresetState,
} from "../../utils/presetStorage";
import { normalizeElementSymbol } from "../../utils/elementUtils";
import { hexToRgba } from "../../utils/colorUtils";
import { flattenObjectToPairs, parseCpValue } from "../../utils/cpValueUtils";
import { CATEGORY_BY_SYMBOL, CATEGORY_COLOR } from "../../utils/elementCategory";
import VaspDataTable from "./VaspDataTable";
import "./PersonalVaspDatabase.css";

const ELEMENTS = [
  { Z: 1, symbol: "H", name: "Hydrogen", row: 1, col: 1 },
  { Z: 2, symbol: "He", name: "Helium", row: 1, col: 18 },
  { Z: 3, symbol: "Li", name: "Lithium", row: 2, col: 1 },
  { Z: 4, symbol: "Be", name: "Beryllium", row: 2, col: 2 },
  { Z: 5, symbol: "B", name: "Boron", row: 2, col: 13 },
  { Z: 6, symbol: "C", name: "Carbon", row: 2, col: 14 },
  { Z: 7, symbol: "N", name: "Nitrogen", row: 2, col: 15 },
  { Z: 8, symbol: "O", name: "Oxygen", row: 2, col: 16 },
  { Z: 9, symbol: "F", name: "Fluorine", row: 2, col: 17 },
  { Z: 10, symbol: "Ne", name: "Neon", row: 2, col: 18 },
  { Z: 11, symbol: "Na", name: "Sodium", row: 3, col: 1 },
  { Z: 12, symbol: "Mg", name: "Magnesium", row: 3, col: 2 },
  { Z: 13, symbol: "Al", name: "Aluminium", row: 3, col: 13 },
  { Z: 14, symbol: "Si", name: "Silicon", row: 3, col: 14 },
  { Z: 15, symbol: "P", name: "Phosphorus", row: 3, col: 15 },
  { Z: 16, symbol: "S", name: "Sulfur", row: 3, col: 16 },
  { Z: 17, symbol: "Cl", name: "Chlorine", row: 3, col: 17 },
  { Z: 18, symbol: "Ar", name: "Argon", row: 3, col: 18 },
  { Z: 19, symbol: "K", name: "Potassium", row: 4, col: 1 },
  { Z: 20, symbol: "Ca", name: "Calcium", row: 4, col: 2 },
  { Z: 21, symbol: "Sc", name: "Scandium", row: 4, col: 3 },
  { Z: 22, symbol: "Ti", name: "Titanium", row: 4, col: 4 },
  { Z: 23, symbol: "V", name: "Vanadium", row: 4, col: 5 },
  { Z: 24, symbol: "Cr", name: "Chromium", row: 4, col: 6 },
  { Z: 25, symbol: "Mn", name: "Manganese", row: 4, col: 7 },
  { Z: 26, symbol: "Fe", name: "Iron", row: 4, col: 8 },
  { Z: 27, symbol: "Co", name: "Cobalt", row: 4, col: 9 },
  { Z: 28, symbol: "Ni", name: "Nickel", row: 4, col: 10 },
  { Z: 29, symbol: "Cu", name: "Copper", row: 4, col: 11 },
  { Z: 30, symbol: "Zn", name: "Zinc", row: 4, col: 12 },
  { Z: 31, symbol: "Ga", name: "Gallium", row: 4, col: 13 },
  { Z: 32, symbol: "Ge", name: "Germanium", row: 4, col: 14 },
  { Z: 33, symbol: "As", name: "Arsenic", row: 4, col: 15 },
  { Z: 34, symbol: "Se", name: "Selenium", row: 4, col: 16 },
  { Z: 35, symbol: "Br", name: "Bromine", row: 4, col: 17 },
  { Z: 36, symbol: "Kr", name: "Krypton", row: 4, col: 18 },
  { Z: 37, symbol: "Rb", name: "Rubidium", row: 5, col: 1 },
  { Z: 38, symbol: "Sr", name: "Strontium", row: 5, col: 2 },
  { Z: 39, symbol: "Y", name: "Yttrium", row: 5, col: 3 },
  { Z: 40, symbol: "Zr", name: "Zirconium", row: 5, col: 4 },
  { Z: 41, symbol: "Nb", name: "Niobium", row: 5, col: 5 },
  { Z: 42, symbol: "Mo", name: "Molybdenum", row: 5, col: 6 },
  { Z: 43, symbol: "Tc", name: "Technetium", row: 5, col: 7 },
  { Z: 44, symbol: "Ru", name: "Ruthenium", row: 5, col: 8 },
  { Z: 45, symbol: "Rh", name: "Rhodium", row: 5, col: 9 },
  { Z: 46, symbol: "Pd", name: "Palladium", row: 5, col: 10 },
  { Z: 47, symbol: "Ag", name: "Silver", row: 5, col: 11 },
  { Z: 48, symbol: "Cd", name: "Cadmium", row: 5, col: 12 },
  { Z: 49, symbol: "In", name: "Indium", row: 5, col: 13 },
  { Z: 50, symbol: "Sn", name: "Tin", row: 5, col: 14 },
  { Z: 51, symbol: "Sb", name: "Antimony", row: 5, col: 15 },
  { Z: 52, symbol: "Te", name: "Tellurium", row: 5, col: 16 },
  { Z: 53, symbol: "I", name: "Iodine", row: 5, col: 17 },
  { Z: 54, symbol: "Xe", name: "Xenon", row: 5, col: 18 },
  { Z: 55, symbol: "Cs", name: "Caesium", row: 6, col: 1 },
  { Z: 56, symbol: "Ba", name: "Barium", row: 6, col: 2 },
  { Z: 57, symbol: "La", name: "Lanthanum", row: 6, col: 3, isLanActMark: true },
  { Z: 72, symbol: "Hf", name: "Hafnium", row: 6, col: 4 },
  { Z: 73, symbol: "Ta", name: "Tantalum", row: 6, col: 5 },
  { Z: 74, symbol: "W", name: "Tungsten", row: 6, col: 6 },
  { Z: 75, symbol: "Re", name: "Rhenium", row: 6, col: 7 },
  { Z: 76, symbol: "Os", name: "Osmium", row: 6, col: 8 },
  { Z: 77, symbol: "Ir", name: "Iridium", row: 6, col: 9 },
  { Z: 78, symbol: "Pt", name: "Platinum", row: 6, col: 10 },
  { Z: 79, symbol: "Au", name: "Gold", row: 6, col: 11 },
  { Z: 80, symbol: "Hg", name: "Mercury", row: 6, col: 12 },
  { Z: 81, symbol: "Tl", name: "Thallium", row: 6, col: 13 },
  { Z: 82, symbol: "Pb", name: "Lead", row: 6, col: 14 },
  { Z: 83, symbol: "Bi", name: "Bismuth", row: 6, col: 15 },
  { Z: 84, symbol: "Po", name: "Polonium", row: 6, col: 16 },
  { Z: 85, symbol: "At", name: "Astatine", row: 6, col: 17 },
  { Z: 86, symbol: "Rn", name: "Radon", row: 6, col: 18 },
  { Z: 87, symbol: "Fr", name: "Francium", row: 7, col: 1 },
  { Z: 88, symbol: "Ra", name: "Radium", row: 7, col: 2 },
  { Z: 89, symbol: "Ac", name: "Actinium", row: 7, col: 3, isLanActMark: true },
  { Z: 104, symbol: "Rf", name: "Rutherfordium", row: 7, col: 4 },
  { Z: 105, symbol: "Db", name: "Dubnium", row: 7, col: 5 },
  { Z: 106, symbol: "Sg", name: "Seaborgium", row: 7, col: 6 },
  { Z: 107, symbol: "Bh", name: "Bohrium", row: 7, col: 7 },
  { Z: 108, symbol: "Hs", name: "Hassium", row: 7, col: 8 },
  { Z: 109, symbol: "Mt", name: "Meitnerium", row: 7, col: 9 },
  { Z: 110, symbol: "Ds", name: "Darmstadtium", row: 7, col: 10 },
  { Z: 111, symbol: "Rg", name: "Roentgenium", row: 7, col: 11 },
  { Z: 112, symbol: "Cn", name: "Copernicium", row: 7, col: 12 },
  { Z: 113, symbol: "Nh", name: "Nihonium", row: 7, col: 13 },
  { Z: 114, symbol: "Fl", name: "Flerovium", row: 7, col: 14 },
  { Z: 115, symbol: "Mc", name: "Moscovium", row: 7, col: 15 },
  { Z: 116, symbol: "Lv", name: "Livermorium", row: 7, col: 16 },
  { Z: 117, symbol: "Ts", name: "Tennessine", row: 7, col: 17 },
  { Z: 118, symbol: "Og", name: "Oganesson", row: 7, col: 18 },
  { Z: 58, symbol: "Ce", name: "Cerium", row: 8, col: 4 },
  { Z: 59, symbol: "Pr", name: "Praseodymium", row: 8, col: 5 },
  { Z: 60, symbol: "Nd", name: "Neodymium", row: 8, col: 6 },
  { Z: 61, symbol: "Pm", name: "Promethium", row: 8, col: 7 },
  { Z: 62, symbol: "Sm", name: "Samarium", row: 8, col: 8 },
  { Z: 63, symbol: "Eu", name: "Europium", row: 8, col: 9 },
  { Z: 64, symbol: "Gd", name: "Gadolinium", row: 8, col: 10 },
  { Z: 65, symbol: "Tb", name: "Terbium", row: 8, col: 11 },
  { Z: 66, symbol: "Dy", name: "Dysprosium", row: 8, col: 12 },
  { Z: 67, symbol: "Ho", name: "Holmium", row: 8, col: 13 },
  { Z: 68, symbol: "Er", name: "Erbium", row: 8, col: 14 },
  { Z: 69, symbol: "Tm", name: "Thulium", row: 8, col: 15 },
  { Z: 70, symbol: "Yb", name: "Ytterbium", row: 8, col: 16 },
  { Z: 71, symbol: "Lu", name: "Lutetium", row: 8, col: 17 },
  { Z: 90, symbol: "Th", name: "Thorium", row: 9, col: 4 },
  { Z: 91, symbol: "Pa", name: "Protactinium", row: 9, col: 5 },
  { Z: 92, symbol: "U", name: "Uranium", row: 9, col: 6 },
  { Z: 93, symbol: "Np", name: "Neptunium", row: 9, col: 7 },
  { Z: 94, symbol: "Pu", name: "Plutonium", row: 9, col: 8 },
  { Z: 95, symbol: "Am", name: "Americium", row: 9, col: 9 },
  { Z: 96, symbol: "Cm", name: "Curium", row: 9, col: 10 },
  { Z: 97, symbol: "Bk", name: "Berkelium", row: 9, col: 11 },
  { Z: 98, symbol: "Cf", name: "Californium", row: 9, col: 12 },
  { Z: 99, symbol: "Es", name: "Einsteinium", row: 9, col: 13 },
  { Z: 100, symbol: "Fm", name: "Fermium", row: 9, col: 14 },
  { Z: 101, symbol: "Md", name: "Mendelevium", row: 9, col: 15 },
  { Z: 102, symbol: "No", name: "Nobelium", row: 9, col: 16 },
  { Z: 103, symbol: "Lr", name: "Lawrencium", row: 9, col: 17 },
];

// --------- 元素分类上色（尽量像你第二张图） ----------
const CP_CATALOG = [
  { path: "ediff", label: "EDIFF (电子收敛)", type: "number", defaultValue: 0.00001 },
  { path: "ediffg", label: "EDIFFG (离子收敛)", type: "number", defaultValue: -0.01 },
  { path: "enmax", label: "ENMAX/ENCUT (截断能)", type: "number", defaultValue: 520 },
  { path: "gga", label: "GGA", type: "string", defaultValue: "PE" },
  { path: "hfscreen", label: "HFSCREEN", type: "number", defaultValue: 0 },
  { path: "ibrion", label: "IBRION", type: "number", defaultValue: 2 },
  { path: "isif", label: "ISIF", type: "number", defaultValue: 2 },
  { path: "kgamma", label: "KGAMMA", type: "bool", defaultValue: true },
  { path: "kpoints_generation.divisions", label: "KPOINTS divisions", type: "json", defaultValue: [2, 3, 1] },
  { path: "ispin", label: "ISPIN", type: "number", defaultValue: 2 },
  { path: "sigma", label: "SIGMA", type: "number", defaultValue: 0.05 },
];

export default function PersonalVaspDatabase() {
  const [dbList, setDbList] = useState([]);
  const [selectedDbKey, setSelectedDbKey] = useState("");
  const [elementsSet, setElementsSet] = useState(() => new Set());
  const [elementsStatus, setElementsStatus] = useState("idle"); // idle|scanning|refreshing|ready
  const [loadingDbList, setLoadingDbList] = useState(false);
  const [error, setError] = useState("");

  // 表格（tasks）相关
  const [tasks, setTasks] = useState([]);
  const [tasksTotal, setTasksTotal] = useState(0);
  const [tasksPage, setTasksPage] = useState(1);
  const [tasksPageSize, setTasksPageSize] = useState(20); // ✅ 默认 20
  const [tasksLoadedOnce, setTasksLoadedOnce] = useState(false);
  const [loadingTasks, setLoadingTasks] = useState(true);
  const [allColumns, setAllColumns] = useState([]);        // 后端返回的 all
  const [defaultColumns, setDefaultColumns] = useState([]); // 后端返回的 default
  const [selectedColumns, setSelectedColumns] = useState([]); // 当前勾选要显示的列
  const [columnMetadata, setColumnMetadata] = useState({});
  const [columnsReady, setColumnsReady] = useState(false);
  const [showColumnPicker, setShowColumnPicker] = useState(false);
  const [loadingColumns, setLoadingColumns] = useState(false);
  const [onlyRelax, setOnlyRelax] = useState(true);
  const [sortOrder, setSortOrder] = useState("desc");
  const [query, setQuery] = useState("");
  const [queryDraft, setQueryDraft] = useState("");
  const [selectedElems, setSelectedElems] = useState([]); // ["H","O"]
  const [elemMode, setElemMode] = useState("at_least");   // "at_least" | "only"
  const [highlightElemsSet, setHighlightElemsSet] = useState(() => new Set());

  const [showParamModal, setShowParamModal] = useState(false);
  const [paramModalTitle, setParamModalTitle] = useState("");
  const [paramItems, setParamItems] = useState([]); // [{k, v}]
  const [loadingParams, setLoadingParams] = useState(false);
  const [paramsError, setParamsError] = useState("");
  const [showCpFilter, setShowCpFilter] = useState(false);
  const [cpFilters, setCpFilters] = useState([]);        // 已应用的 filters
  const [cpDraft, setCpDraft] = useState(() => {
    // 默认先用 catalog 的第一项（ediff）
    const d = CP_CATALOG[0];
    return [{ path: d.path, op: "eq", valueText: JSON.stringify(d.defaultValue) }];
  });
  const [cpPresets, setCpPresets] = useState([]); // [{name, filters:[{path,op,valueText}]}]
  const [selectedPresetName, setSelectedPresetName] = useState("");
  const [cpPathOptions, setCpPathOptions] = useState([]);

  const [dbScope, setDbScope] = useState("all"); // all | personal | upload
  const [uploading, setUploading] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [selectedUploadFiles, setSelectedUploadFiles] = useState([]); // File[]
  const filePickRef = useRef(null);
  const navigate = useNavigate();
  const pollTimerRef = useRef(null);
  const [customDbs, setCustomDbs] = useState([]);
  // ✅ 防止旧请求的 finally 把 loading 关掉（解决“闪一下”）
  const tasksReqIdRef = useRef(0);

  // 收藏弹窗（对齐 QE）
  const [showAddToCustomModal, setShowAddToCustomModal] = useState(false);
  const [customTargetName, setCustomTargetName] = useState(""); // safe_name
  const [addingToCustom, setAddingToCustom] = useState(false);
  const [addCustomErr, setAddCustomErr] = useState("");
  const [addCustomRow, setAddCustomRow] = useState(null); // {_rowId,_dbKey,_dbName}
  const [removingRowId, setRemovingRowId] = useState(0);

  // ✅ 全部收藏弹窗
  const [showAddAllModal, setShowAddAllModal] = useState(false);
  const [addingAll, setAddingAll] = useState(false);
  const [addAllErr, setAddAllErr] = useState("");
  const [forceReloadTick, setForceReloadTick] = useState(0);
  // ✅ add_all 后台任务轮询
  const addAllPollRef = useRef(null);
  const [addAllJobId, setAddAllJobId] = useState("");
  const [addAllProgress, setAddAllProgress] = useState(null); // meta

  // ✅ 让 loading 至少显示一小会儿，用户更有感知
  const TASKS_MIN_LOADING_MS = 300;
  

  // 周期表响应式：动态格子大小
  const tableWrapRef = useRef(null);
  const [cellSize, setCellSize] = useState(44);
  const GAP = 6;
  const location = useLocation();

  function stopAddAllPoll() {
    if (addAllPollRef.current) {
      clearInterval(addAllPollRef.current);
      addAllPollRef.current = null;
    }
  }

  useEffect(() => {
    return () => stopAddAllPoll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  // 解析 URL -> state
  function readQuery() {
    const sp = new URLSearchParams(location.search);

    const page = Math.max(1, parseInt(sp.get("page") || "1", 10) || 1);
    const pageSize = [10, 20, 50].includes(parseInt(sp.get("page_size") || "20", 10))
      ? parseInt(sp.get("page_size") || "20", 10)
      : 20;

    const onlyRelax = sp.has("only_last") ? sp.get("only_last") === "1" : true;
    const sortOrder = sp.get("sort_order") === "asc" ? "asc" : "desc";
    const query = (sp.get("query") || "").trim();

    const elemMode = (sp.get("elem_mode") || "at_least");
    const selectedElems = (sp.get("elems") || "")
      .split(",")
      .map(s => s.trim())
      .filter(Boolean);

    let cpFilters = [];
    try {
      const raw = sp.get("cp_filters");
      cpFilters = raw ? JSON.parse(raw) : [];
    } catch {
      cpFilters = [];
    }

    const rawScope = sp.get("scope") || "all";
    const scope = ["all", "personal", "upload", "custom"].includes(rawScope) ? rawScope : "all";
    const dbKey = sp.get("db") || "";

    return { page, pageSize, onlyRelax, sortOrder, query, elemMode, selectedElems, cpFilters, scope, dbKey };
  }

  // state -> URL
  function writeQuery(next) {
    const sp = new URLSearchParams();

    if (next.dbKey) sp.set("db", next.dbKey);
    if (next.scope) sp.set("scope", next.scope);

    sp.set("page", String(next.page || 1));
    sp.set("page_size", String(next.pageSize || 20));
    sp.set("only_last", next.onlyRelax ? "1" : "0");
    sp.set("sort_order", next.sortOrder === "asc" ? "asc" : "desc");
    if (next.query) sp.set("query", next.query);

    if (next.elemMode) sp.set("elem_mode", next.elemMode);

    if (next.selectedElems && next.selectedElems.length) {
      sp.set("elems", next.selectedElems.join(","));
    }

    if (next.cpFilters && next.cpFilters.length) {
      sp.set("cp_filters", JSON.stringify(next.cpFilters));
    }

    return sp.toString();
  }

  const selectedDb = useMemo(() => {
    return dbList.find((d) => d.key === selectedDbKey) || null;
  }, [dbList, selectedDbKey]);

  useEffect(() => {
    if (!selectedDbKey || (selectedDb && selectedDb.exists === false)) {
      // 没有可用库时：停止 loading，并认为“已结束一次加载”（否则可能一直显示 loading 文案）
      setLoadingTasks(false);
      setTasksLoadedOnce(true);
      setTasks([]);
      setTasksTotal(0);
      return;
    }
  }, [selectedDbKey, selectedDb]);

  useEffect(() => {
    (async () => {
      try {
        const data = await fetchJson(`${API_BASE}/api/db/vasp/custom/list`);
        setCustomDbs(data?.items || []);
      } catch {
        setCustomDbs([]);
      }
    })();
  }, []);

  const didInitFromUrlRef = useRef(false);

  useEffect(() => {
    if (didInitFromUrlRef.current) return;
    didInitFromUrlRef.current = true;

    const q = readQuery();

    // 注意：这些 set 会触发你的 tasks/elements 拉取
    setTasksPage(q.page);
    setTasksPageSize(q.pageSize);
    setOnlyRelax(q.onlyRelax);
    setSortOrder(q.sortOrder);
    setQuery(q.query);
    setQueryDraft(q.query);
    setElemMode(q.elemMode);
    setSelectedElems(q.selectedElems);
    setCpFilters(Array.isArray(q.cpFilters) ? q.cpFilters : []);

    // scope/db：也从 URL 恢复（如果 URL 没有就保持默认）
    if (q.scope) setDbScope(q.scope);
    if (q.dbKey) setSelectedDbKey(q.dbKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const lastSyncedQsRef = useRef("");

  useEffect(() => {
    if (!didInitFromUrlRef.current) return;

    const qs = writeQuery({
      page: tasksPage,
      pageSize: tasksPageSize,
      onlyRelax,
      sortOrder,
      query,
      elemMode,
      selectedElems,
      cpFilters,
      scope: ["all", "personal", "upload", "custom"].includes(dbScope) ? dbScope : "all",
      dbKey: selectedDbKey,
    });

    // 关键：把 query 规范化，避免“同语义不同字符串”导致无限跳转
    const curQs = new URLSearchParams(location.search).toString();
    const nextQs = new URLSearchParams(qs).toString();

    // 写入锁：如果我们刚写过同一个 nextQs，就不要再写
    if (lastSyncedQsRef.current === nextQs) return;

    // 已一致则不导航
    if (curQs === nextQs) return;

    lastSyncedQsRef.current = nextQs;
    navigate(`${location.pathname}?${nextQs}`, { replace: true });
  }, [
    tasksPage,
    tasksPageSize,
    onlyRelax,
    sortOrder,
    query,
    elemMode,
    selectedElems,
    cpFilters,
    dbScope,
    selectedDbKey,
    location.pathname,
    location.search,
    navigate,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(queryDraft.trim()), 300);
    return () => window.clearTimeout(timer);
  }, [queryDraft]);

    useEffect(() => {
      if (!selectedDbKey) return;
      try {
        const { presets, defaultPreset: defName } = loadPresetState(getVaspPresetStorageKey(selectedDbKey));
        setCpPresets(presets);

        // 读默认 preset
        setSelectedPresetName(defName);

        // 如果有默认 preset，就把它加载到 cpDraft（但不自动应用，避免用户困惑）
        if (defName) {
        const p = presets.find(x => x?.name === defName);
        if (p?.filters) setCpDraft(p.filters);
        }
    } catch {
        setCpPresets([]);
        setSelectedPresetName("");
    }
  }, [selectedDbKey]);

  useEffect(() => {
    const el = tableWrapRef.current;
    if (!el) return;

    const MAX = 44;
    const MIN = 30; // 小屏可读下限（你可调 28~34）

    const ro = new ResizeObserver(() => {
      const w = el.clientWidth || 0;
      const usable = Math.max(0, w - 24); // 预留 padding
      const size = Math.floor((usable - GAP * 17) / 18);
      const clamped = Math.max(MIN, Math.min(MAX, size));
      setCellSize(clamped);
    });

    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const gridStyle = useMemo(
    () => ({
      display: "grid",
      gridTemplateColumns: `repeat(18, ${cellSize}px)`,
      gridAutoRows: `${cellSize}px`,
      gap: `${GAP}px`,
      alignItems: "stretch",
    }),
    [cellSize]
  );

  const cellBase = useMemo(
    () => ({
      borderRadius: Math.max(8, Math.floor(cellSize * 0.22)),
      border: "1px solid rgba(229,231,235,1)",
      padding: Math.max(4, Math.floor(cellSize * 0.13)),
      lineHeight: 1.05,
      cursor: "default",
      userSelect: "none",
      boxSizing: "border-box",
      transition: "all .15s ease",
    }),
    [cellSize]
  );
  
  function saveCpPresets(nextPresets, defaultPreset = selectedPresetName) {
    setCpPresets(nextPresets);
    try {
        savePresetState(getVaspPresetStorageKey(selectedDbKey), nextPresets, defaultPreset);
    } catch {}
  }

  function renderElementCell(el) {
    const sym = el.symbol;

    // ✅ 高亮集合来自后端“当前筛选条件”返回的 elements
    const present = highlightElemsSet.has(sym);

    // ✅ 是否被用户选中
    const active = selectedElems.includes(sym);

    const category = CATEGORY_BY_SYMBOL[sym] || "unknown";
    const catColor = CATEGORY_COLOR[category] || CATEGORY_COLOR.unknown;

    const bg = present ? catColor : hexToRgba(catColor, 0.18);

    const style = {
        ...cellBase,
        gridColumn: el.col,
        gridRow: el.row,

        background: bg,
        opacity: present ? 1 : 0.35,
        borderColor: active ? "rgba(59,130,246,1)" : (present ? "rgba(17,24,39,.18)" : "rgba(229,231,235,1)"),
        boxShadow: active ? "0 0 0 3px rgba(59,130,246,.25)" : (present ? "0 0 0 3px rgba(59,130,246,.10)" : "none"),
        filter: present ? "none" : "grayscale(0.2)",
        cursor: "pointer",
    };

    const title = `${sym} (Z=${el.Z}) ${el.name}${present ? "" : " — not in current filter"}`;

    const zFont = Math.max(9, Math.floor(cellSize * 0.23));
    const symFont = Math.max(11, Math.floor(cellSize * 0.34));

    return (
        <div
        key={el.Z}
        style={style}
        title={title}
        onClick={() => {
            setTasksPage(1);
            setSelectedElems((prev) => {
            const s = new Set(prev);
            if (s.has(sym)) s.delete(sym);
            else s.add(sym);
            return Array.from(s);
            });
        }}
        >
        <div style={{ fontSize: zFont, color: "rgba(17,24,39,.55)" }}>{el.Z}</div>
        <div style={{ fontSize: symFont, fontWeight: 800, color: "rgba(17,24,39,.85)" }}>
            {sym}
        </div>
        </div>
    );
  }

  // 1) 加载可用数据库列表
  useEffect(() => {
    let alive = true;

    async function loadAvailable() {
      setLoadingDbList(true);
      setError("");

      try {
        const data = await fetchJson(`${API_BASE}/api/db/vasp/available?scope=${encodeURIComponent(dbScope)}`);
        if (!alive) return;

        const list = Array.isArray(data) ? data : [];
        setDbList(list);
        setColumnsReady(false);

        // ✅ 只在“当前选择不在列表里”时才自动切换
        setSelectedDbKey((prev) => {
          if (prev && list.some(x => x.key === prev && x.exists !== false)) return prev;
          return list.find(x => x.exists !== false)?.key || "";
        });
      } catch (e) {
        if (!alive) return;
        setError(String(e?.message || e));
        setDbList([]);
        // ✅ 不要 setSelectedDbKey("")：避免触发一连串 effect/URL 同步导致请求风暴
      } finally {
        setLoadingDbList(false);
      }
    }

    loadAvailable();
    return () => { alive = false; };
  }, [dbScope]);

  // 2) 拉 elements（支持后台扫描状态 + 轮询）
  useEffect(() => {
    let alive = true;

    async function loadElementsOnce({ refresh = 0 } = {}) {
      if (!selectedDbKey) return;
      if (selectedDb && selectedDb.exists === false) return;

      const url = `${API_BASE}/api/db/vasp/elements?db=${encodeURIComponent(selectedDbKey)}&scope=${encodeURIComponent(dbScope)}&refresh=${refresh ? 1 : 0}`;

      const data = await fetchJson(url);

      if (!alive) return;

      const status = data?.status || "ready";
      setElementsStatus(status);

      const elems = Array.isArray(data?.elements) ? data.elements : [];
      setElementsSet(new Set(elems.map(normalizeElementSymbol)));
    }

    function clearPoll() {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    }

    async function startLoadAndPoll() {
      setError("");
      setElementsSet(new Set());
      setElementsStatus("idle");
      clearPoll();

      if (!selectedDbKey) return;
      if (selectedDb && selectedDb.exists === false) return;

      try {
        await loadElementsOnce({ refresh: 0 });

        const start = Date.now();
        pollTimerRef.current = setInterval(async () => {
          try {
            if (!alive) return;

            const elapsed = Date.now() - start;
            if (elapsed > 120000) {
              clearPoll();
              if (alive) setError("元素扫描超时（库较大或服务器繁忙），稍后再试或点击刷新。");
              return;
            }

            const url = `${API_BASE}/api/db/vasp/elements?db=${encodeURIComponent(selectedDbKey)}&scope=${encodeURIComponent(dbScope)}`;
            const data = await fetchJson(url);
            if (!alive) return;

            const status = data?.status || "ready";
            setElementsStatus(status);

            const elems = Array.isArray(data?.elements) ? data.elements : [];
            setElementsSet(new Set(elems.map(normalizeElementSymbol)));

            if (status === "ready") clearPoll();
          } catch (e) {
            clearPoll();
            if (alive) setError(String(e?.message || e));
          }
        }, 1500);
      } catch (e) {
        if (!alive) return;
        setError(String(e?.message || e));
      }
    }

    startLoadAndPoll();

    return () => {
      alive = false;
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [selectedDbKey, selectedDb]);

  // 2-B) 根据筛选条件刷新“高亮元素集合”（用于周期表变暗/高亮）
  useEffect(() => {
    if (!selectedDbKey) return;
    if (loadingTasks) return;  // ✅ 表格加载时先不刷高亮，减少一次重请求
    if (selectedDb && selectedDb.exists === false) return;

    const controller = new AbortController();

    const t = setTimeout(async () => {
      try {
        const only = onlyRelax ? "&only_last=1" : "";
        const elems = selectedElems.length
          ? `&elems=${encodeURIComponent(selectedElems.join(","))}`
          : "";
        const mode = `&elem_mode=${encodeURIComponent(elemMode)}`;
        const cp = cpFilters.length
          ? `&cp_filters=${encodeURIComponent(JSON.stringify(cpFilters))}`
          : "";

        const url =
          `${API_BASE}/api/db/vasp/elements?db=${encodeURIComponent(selectedDbKey)}` +
          `&scope=${encodeURIComponent(dbScope)}` +
          `${only}${elems}${mode}${cp}`;

        const data = await fetchJson(url, { signal: controller.signal });

        const arr = Array.isArray(data?.elements) ? data.elements : [];
        setHighlightElemsSet(new Set(arr.map(normalizeElementSymbol)));
      } catch (e) {
        if (e?.name !== "AbortError") {
          setHighlightElemsSet(new Set());
          console.error("loadHighlightElements failed:", e);
        }
      }
    }, 150);

    return () => {
      clearTimeout(t);
      controller.abort();
    };
  }, [selectedDbKey, selectedDb, selectedElems, elemMode, onlyRelax, cpFilters, dbScope, loadingTasks, forceReloadTick]);

  // 3) 拉 tasks（下面表格用）
  useEffect(() => {
    if (!selectedDbKey) return;
    if (selectedDb && selectedDb.exists === false) return;
    if (!columnsReady) return;

    const controller = new AbortController();
    const reqId = ++tasksReqIdRef.current;
    const t0 = Date.now();

    (async () => {
      setTasksLoadedOnce(false);
      setLoadingTasks(true);

      try {
        const cols = (selectedColumns && selectedColumns.length > 0)
          ? `&columns=${encodeURIComponent(selectedColumns.join(","))}`
          : "";

        // ✅ 显式传 0/1，避免有时带参数、有时不带导致 URL 抖动
        const only = `&only_last=${onlyRelax ? 1 : 0}`;

        const elems = selectedElems.length
          ? `&elems=${encodeURIComponent(selectedElems.join(","))}`
          : "";
        const mode = `&elem_mode=${encodeURIComponent(elemMode)}`;
        const cp = cpFilters.length
          ? `&cp_filters=${encodeURIComponent(JSON.stringify(cpFilters))}`
          : "";
        const search = query ? `&query=${encodeURIComponent(query)}` : "";
        const sort = `&sort_order=${encodeURIComponent(sortOrder)}`;

        const url =
          `${API_BASE}/api/db/vasp/tasks?db=${encodeURIComponent(selectedDbKey)}` +
          `&scope=${encodeURIComponent(dbScope)}` +
          `&page=${tasksPage}&page_size=${tasksPageSize}` +
          `${cols}${only}${elems}${mode}${cp}${search}${sort}`;

        const data = await fetchJson(url, { signal: controller.signal });

        // ✅ 如果期间又发起了新请求，旧请求结果丢弃
        if (reqId !== tasksReqIdRef.current) return;

        setTasks(Array.isArray(data?.items) ? data.items : []);
        setTasksTotal(Number.isFinite(data?.total) ? data.total : 0);
      } catch (e) {
        if (e?.name === "AbortError") return;
        if (reqId !== tasksReqIdRef.current) return;

        console.error("loadTasks failed:", e);
        setTasks([]);
        setTasksTotal(0);
      } finally {
        if (reqId !== tasksReqIdRef.current) return;

        const dt = Date.now() - t0;
        const wait = dt < TASKS_MIN_LOADING_MS ? (TASKS_MIN_LOADING_MS - dt) : 0;

        window.setTimeout(() => {
          // 仍然要再确认一次，避免 timeout 期间又来了新请求
          if (reqId !== tasksReqIdRef.current) return;
          setLoadingTasks(false);
          setTasksLoadedOnce(true);
        }, wait);
      }
    })();

    return () => controller.abort();
  }, [
    selectedDbKey,
    selectedDb,
    columnsReady,
    tasksPage,
    tasksPageSize,
    selectedColumns,
    onlyRelax,
    selectedElems,
    elemMode,
    cpFilters,
    query,
    sortOrder,
    dbScope,
    forceReloadTick,
  ]);

  // 3-A) 拉 columns（表头用）
  useEffect(() => {
    setColumnsReady(false);
    if (!selectedDbKey) {
      setLoadingColumns(false);
      return;
    }
    if (selectedDb && selectedDb.exists === false) {
      setLoadingColumns(false);
      return;
    }

    const controller = new AbortController();

    (async () => {
      setLoadingColumns(true);
      try {
        const only = onlyRelax ? "&only_last=1" : "";
        const url = `${API_BASE}/api/db/vasp/columns?db=${encodeURIComponent(selectedDbKey)}&scope=${encodeURIComponent(dbScope)}&sample=2000${only}`;

        const data = await fetchJson(url, { signal: controller.signal });
        const all = Array.isArray(data?.all) ? data.all : [];
        const def = Array.isArray(data?.default) ? data.default : [];

        setAllColumns(all);
        setDefaultColumns(def);
        setColumnMetadata(data?.metadata && typeof data.metadata === "object" ? data.metadata : {});

        setSelectedColumns((prev) => {
          const valid = (prev || []).filter((column) => all.includes(column));
          return valid.length > 0 ? valid : def;
        });
        setColumnsReady(true);
      } catch (e) {
        if (e?.name !== "AbortError") {
          setAllColumns([]);
          setDefaultColumns([]);
          setSelectedColumns([]);
          setColumnMetadata({});
          console.error("loadColumns failed:", e);
        }
      } finally {
        setLoadingColumns(false);
      }
    })();

    return () => controller.abort();
  }, [selectedDbKey, selectedDb, onlyRelax, dbScope]);

  useEffect(() => {
    let alive = true;

    async function loadCpKeys() {
        if (!selectedDbKey) return;
        if (selectedDb && selectedDb.exists === false) return;
        if (!showCpFilter) return; // ✅ 面板不开就不拉
        try {
        const only = onlyRelax ? "&only_last=1" : "&only_last=0";
        const url = `${API_BASE}/api/db/vasp/cp_keys?db=${encodeURIComponent(selectedDbKey)}&scope=${encodeURIComponent(dbScope)}&sample=2000${only}&max_depth=4`;
        const data = await fetchJson(url);
        if (!alive) return;
        const keys = Array.isArray(data?.keys) ? data.keys : [];
        setCpPathOptions(keys.map(String));
        } catch {
        if (!alive) return;
        setCpPathOptions([]);
        }
    }

    loadCpKeys();
    return () => { alive = false; };
  }, [selectedDbKey, selectedDb, onlyRelax, showCpFilter]);

  const statusText = useMemo(() => {
    if (!selectedDbKey) return "";
    if (selectedDb && selectedDb.exists === false) {
      return selectedDb.missingReason ? `数据库不存在：${selectedDb.missingReason}` : "数据库不存在";
    }
    if (elementsStatus === "scanning") return "正在扫描元素（后台）…";
    if (elementsStatus === "refreshing") return "正在刷新元素（后台）…";
    if (elementsStatus === "ready") return selectedDb ? `已加载：${selectedDb.dbname}` : "已加载";
    return "准备中…";
  }, [elementsStatus, selectedDbKey, selectedDb]);

  async function handleRefreshElements() {
    if (!selectedDbKey) return;
    if (selectedDb && selectedDb.exists === false) return;
    setError("");

    try {
      const url = `${API_BASE}/api/db/vasp/elements?db=${encodeURIComponent(selectedDbKey)}&scope=${encodeURIComponent(dbScope)}&refresh=1`;
      const data = await fetchJson(url);

      const status = data?.status || "scanning";
      setElementsStatus(status);

      const elems = Array.isArray(data?.elements) ? data.elements : [];
      setElementsSet(new Set(elems.map(normalizeElementSymbol)));
    } catch (e) {
      setError(String(e?.message || e));
    }
  }

  const lanActLabelStyle = {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    paddingRight: 10,
    color: "#6b7280",
    fontSize: Math.max(11, Math.floor(cellSize * 0.28)),
    userSelect: "none",
  };

  const presentElements = useMemo(() => {
    const s = elementsSet;
    return ELEMENTS
        .filter((e) => s.has(e.symbol))
        .sort((a, b) => a.Z - b.Z);
  }, [elementsSet]);

  const totalPages = Math.max(1, Math.ceil((tasksTotal || 0) / (tasksPageSize || 20)));

  // 保证始终给 3 个页码按钮（边界自动贴边）
  const page3 = (() => {
    let start = Math.max(1, tasksPage - 1);
    let end = Math.min(totalPages, start + 2);
    start = Math.max(1, end - 2);

    const arr = [];
    for (let p = start; p <= end; p++) arr.push(p);
    return arr;
  })();

  async function openCalcParams(row) {
    const rowId = row?._rowId;
    const rowDbKey = row?._dbKey;
    if (!rowId || !rowDbKey) return;
    if (!selectedDbKey || !rowId) return;
    if (selectedDb && selectedDb.exists === false) return;

    setShowParamModal(true);
    setLoadingParams(true);
    setParamsError("");
    setParamModalTitle(`输入参数（id=${rowId}）`);
    setParamItems([]);

    try {
        const url = `${API_BASE}/api/db/vasp/task/${encodeURIComponent(rowId)}/calculator_parameters?db=${encodeURIComponent(rowDbKey)}`;
        const data = await fetchJson(url);

        const calc = data?.calculator ? String(data.calculator) : "";
        const cp = data?.calculator_parameters && typeof data.calculator_parameters === "object"
        ? data.calculator_parameters
        : {};

        setParamModalTitle(`输入参数（db=${row?._dbName || rowDbKey}, id=${rowId}）`);

        const pairs = flattenObjectToPairs(cp);
        // 保证顺序稳定
        pairs.sort((a, b) => a.k.localeCompare(b.k));
        setParamItems(pairs);
    } catch (e) {
        setParamsError(String(e?.message || e));
    } finally {
        setLoadingParams(false);
    }
  }

  async function handleRemoveFromCustom(row) {
    // 只允许在 scope=custom + 当前 db 是 custom 时使用
    if (dbScope !== "custom") return;
    if (!selectedDbKey || !String(selectedDbKey).startsWith("custom:")) return;

    const rid = row?._rowId;
    const dbk = row?._dbKey;
    if (!rid || !dbk) return;

    // 保险：必须是当前选中的那个自定义库
    if (dbk !== selectedDbKey) return;

    const ok = window.confirm(`确认从该自定义数据库移除该条记录？（id=${rid}）`);
    if (!ok) return;

    setRemovingRowId(Number(rid) || 0);
    try {
      const body = {
        db_key: selectedDbKey,
        row_id: Number(rid),
        missing_ok: 1,
      };
      const { resp, data } = await postJson(`${API_BASE}/api/db/vasp/custom/remove`, body);
      if (!resp.ok) {
        const detail = getPostJsonErrorDetail(resp, data);
        throw new Error(detail || `移除失败（${resp.status}）`);
      }
      alert(data?.message || "已移除");

      // ✅ 刷新当前列表（最稳）
      setForceReloadTick((x) => x + 1);

      // 可选：如果你想立刻在 UI 上消失（不等后端刷新），可以加：
      // setTasks((prev) => prev.filter((x) => x._rowId !== rid));
    } catch (err) {
      const detail = err?.message || String(err);
      alert("移除失败：" + String(detail));
    } finally {
      setRemovingRowId(0);
    }
  }

  const pagerBtnStyle = (disabled) => ({
    height: 34,
    borderRadius: 10,
    padding: "0 10px",
    border: "1px solid rgba(209,213,219,1)",
    background: disabled ? "rgba(243,244,246,1)" : "white",
    color: disabled ? "#9ca3af" : "#111827",
    cursor: disabled ? "not-allowed" : "pointer",
  });

  const uiBtn = (disabled = false) => ({
    cursor: disabled ? "not-allowed" : "pointer",
  });

  const uiIconBtn = (disabled = false) => ({
    cursor: disabled ? "not-allowed" : "pointer",
  });

  const pagerNumStyle = (active) => ({
    height: 34,
    minWidth: 34,
    borderRadius: 10,
    padding: "0 10px",
    border: active ? "1px solid rgba(59,130,246,1)" : "1px solid rgba(209,213,219,1)",
    background: active ? "rgba(59,130,246,0.10)" : "white",
    color: active ? "#1d4ed8" : "#111827",
    fontWeight: active ? 800 : 500,
    cursor: active ? "default" : "pointer",
  });

  return (
    <DbLayout currentSubPath="/dashboard/db/personal" currentDbType="vasp" showDbTypeSelector={true}>
      <div
        className="vasp-db-page"
        style={{
            display: "flex",
            flexDirection: "column",
            // ✅ 不要固定高度，否则你只能靠“内部滚动”
            gap: 12,
            minHeight: "calc(100vh - 120px)", // ✅ 至少铺满一屏，但允许更高
            paddingBottom: 24,
        }}
      >
        {/* Header */}
        <div>
          <h2 style={{ marginBottom: 6 }}>VASP 数据库（个人 / 授权访问）</h2>
          <p style={{ marginTop: 0, color: "#4b5563", fontSize: 14 }}>
            上方为元素周期表高亮；下方为结构与任务记录。
          </p>
        </div>

        {/* Toolbar */}
        <div
          className="glass-card"
          style={{
            padding: 14,
            borderRadius: 14,
            border: "1px solid rgba(229,231,235,1)",
            background: "rgba(255,255,255,.6)",
          }}
        >
          <div
            className="vasp-db-selector-bar"
            style={{
              display: "flex",
              gap: 12,
              alignItems: "center",
              flexWrap: "wrap",
              justifyContent: "space-between",
            }}
          >
            {/* 左侧：范围 + 上传 + 选择数据库 + 状态 */}
            <div className="vasp-db-selector-fields" style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
              {/* 范围 + 上传 */}
              <div className="vasp-db-selector-row" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={{ fontSize: 13, color: "#374151", minWidth: 80 }}>数据库范围</div>

                <select
                  value={dbScope}
                  onChange={(e) => {
                    setTasksPage(1);
                    setShowColumnPicker(false);
                    setColumnsReady(false);
                    setDbScope(e.target.value);
                  }}
                  style={{
                    height: 36,
                    borderRadius: 10,
                    border: "1px solid rgba(209,213,219,1)",
                    padding: "0 10px",
                    background: "white",
                    minWidth: 160,
                  }}
                >
                  <option value="all">所有数据库</option>
                  <option value="personal">只读个人库（asedbdir）</option>
                  <option value="upload">只读上传库</option>
                  <option value="custom">自定义数据库</option>
                </select>

                <button
                  type="button"
                  onClick={() => {
                    setSelectedUploadFiles([]);
                    setShowUploadModal(true);
                  }}
                  disabled={uploading}
                  style={{
                    height: 36,
                    borderRadius: 10,
                    padding: "0 12px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: uploading ? "rgba(243,244,246,1)" : "white",
                    cursor: uploading ? "not-allowed" : "pointer",
                  }}
                >
                  {uploading ? "上传中…" : "上传文件…"}
                </button>
              </div>

              {/* 选择数据库 */}
              <div className="vasp-db-selector-row" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={{ fontSize: 13, color: "#374151", minWidth: 80 }}>选择数据库</div>

                <select
                  value={selectedDbKey}
                  onChange={(e) => {
                    setTasksPage(1);
                    setShowColumnPicker(false);
                    setColumnsReady(false);
                    setSelectedDbKey(e.target.value);
                  }}
                  disabled={loadingDbList || dbList.length === 0}
                  style={{
                    height: 36,
                    borderRadius: 10,
                    border: "1px solid rgba(209,213,219,1)",
                    padding: "0 10px",
                    background: "white",
                    minWidth: 260,
                  }}
                >
                  {dbList.length === 0 ? (
                    <option value="">{loadingDbList ? "加载中..." : "暂无可用数据库"}</option>
                  ) : (
                    dbList.map((d) => (
                      <option key={d.key} value={d.key} disabled={d.exists === false}>
                        {d.label} — {d.dbname}
                        {d.exists ? "" : "（不存在）"}
                      </option>
                    ))
                  )}
                </select>

                <div>
                  <div style={{ fontSize: 12, color: "#6b7280" }}>{statusText}</div>
                  {selectedDb?.latestUpdatedAt ? (
                    <div className={`vasp-freshness${selectedDb.stale ? " is-stale" : ""}`}>
                      数据更新于 {new Date(selectedDb.latestUpdatedAt).toLocaleString("zh-CN")}
                      {selectedDb.stale ? `，已超过 ${selectedDb.staleDays || 30} 天` : ""}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            {/* 右侧：刷新元素 */}
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <div style={{ fontSize: 12, color: "#6b7280" }}>
                高亮元素数：{" "}
                <span style={{ color: "#111827", fontWeight: 700 }}>{highlightElemsSet.size}</span>
              </div>

              <button
                type="button"
                onClick={handleRefreshElements}
                disabled={!selectedDbKey || (selectedDb && selectedDb.exists === false)}
                style={{
                  height: 36,
                  borderRadius: 10,
                  padding: "0 12px",
                  border: "1px solid rgba(209,213,219,1)",
                  background: "white",
                  cursor: !selectedDbKey || (selectedDb && selectedDb.exists === false) ? "not-allowed" : "pointer",
                }}
              >
                刷新元素
              </button>
            </div>
          </div>

          {error ? (
            <div
              style={{
                marginTop: 10,
                padding: "10px 12px",
                borderRadius: 12,
                background: "rgba(254,242,242,.9)",
                border: "1px solid rgba(252,165,165,.8)",
                color: "#991b1b",
                fontSize: 13,
              }}
            >
              {error}
            </div>
          ) : null}
        </div>

        {/* Top: Periodic Table */}
        <div
          className="glass-card"
          style={{
            flex: "0 0 auto",
            padding: 14,
            borderRadius: 14,
            border: "1px solid rgba(229,231,235,1)",
            background: "rgba(255,255,255,.6)",
            display: "flex",
            flexDirection: "column",
            gap: 10,
            minHeight: 0,
          }}
        >
          <div style={{ color: "#374151", fontSize: 13 }}>
            元素周期表（存在于该 DB 的元素会高亮）
          </div>

          <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <button
                type="button"
                onClick={() => { setTasksPage(1); setElemMode("only"); }}
                style={{
                height: 34,
                borderRadius: 10,
                padding: "0 10px",
                border: elemMode === "only" ? "1px solid rgba(59,130,246,1)" : "1px solid rgba(209,213,219,1)",
                background: elemMode === "only" ? "rgba(59,130,246,0.10)" : "white",
                color: "#111827",
                cursor: "pointer",
                fontWeight: elemMode === "only" ? 800 : 500,
                }}
            >
                只含所选元素
            </button>

            <button
                type="button"
                onClick={() => { setTasksPage(1); setElemMode("at_least"); }}
                style={{
                height: 34,
                borderRadius: 10,
                padding: "0 10px",
                border: elemMode === "at_least" ? "1px solid rgba(59,130,246,1)" : "1px solid rgba(209,213,219,1)",
                background: elemMode === "at_least" ? "rgba(59,130,246,0.10)" : "white",
                color: "#111827",
                cursor: "pointer",
                fontWeight: elemMode === "at_least" ? 800 : 500,
                }}
            >
                至少含有所选元素
            </button>

            <button
                type="button"
                onClick={() => { setTasksPage(1); setSelectedElems([]); }}
                style={{
                height: 34,
                borderRadius: 10,
                padding: "0 10px",
                border: "1px solid rgba(209,213,219,1)",
                background: "white",
                color: "#111827",
                cursor: "pointer",
                }}
            >
                清空选择
            </button>

            <div style={{ fontSize: 12, color: "#6b7280" }}>
                已选：<span style={{ color: "#111827", fontWeight: 700 }}>{selectedElems.join(", ") || "无"}</span>
            </div>
          </div>

          {/* ✅ 不截断：横向滚动兜底 + 宽屏居中 */}
          <div
            ref={tableWrapRef}
            className="vasp-periodic-scroll"
            style={{
              flex: "1 1 auto",
              minHeight: 0,
              overflowX: "auto",
              overflowY: "auto",
              display: "flex",
              justifyContent: "center",
              paddingBottom: 4,
            }}
          >
            <div
              style={{
                width: "fit-content",
                // 最小宽度按“最大格子尺寸”估计，保证大屏/默认情况下不被挤压
                minWidth: 18 * 44 + 17 * GAP + 24,
                padding: "6px 10px",
              }}
            >
              <div style={gridStyle}>
                {ELEMENTS.map(renderElementCell)}

                <div style={{ gridColumn: "1 / span 3", gridRow: 8, ...lanActLabelStyle }}>
                  Lanthanides →
                </div>
                <div style={{ gridColumn: "1 / span 3", gridRow: 9, ...lanActLabelStyle }}>
                  Actinides →
                </div>
              </div>
            </div>
          </div>

          <div style={{ color: "#6b7280", fontSize: 12 }}>
            说明：首次进入某个库可能需要后台扫描一次；扫描完成后会被缓存，后续打开将非常快。
          </div>
        </div>

        {/* Bottom: Table */}
        <div
            className="glass-card"
            style={{
                flex: "0 0 auto",          // ✅ 不要强行占满剩余高度
                overflow: "visible",       // ✅ 取消内部滚动
                padding: 14,
                borderRadius: 14,
                border: "1px solid rgba(229,231,235,1)",
                background: "rgba(255,255,255,.6)",
            }}
          >
          <div className="vasp-table-toolbar">
            <div style={{ color: "#374151", fontSize: 13, display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                <strong>结构与任务记录</strong>
                <span style={{ color: "#6b7280", fontSize: 12 }}>
                {loadingColumns ? "列加载中…" : `共 ${tasksTotal} 条 · 第 ${tasksPage} 页 · ${selectedColumns.length || defaultColumns.length} 列`}
                {loadingTasks ? "（更新中…）" : ""}
                </span>
            </div>

            <div className="vasp-query-controls">
              <input
                type="search"
                value={queryDraft}
                onChange={(event) => {
                  setTasksPage(1);
                  setQueryDraft(event.target.value);
                }}
                placeholder="搜索记录 ID 或化学式"
                aria-label="搜索记录 ID 或化学式"
              />
              <select
                value={sortOrder}
                onChange={(event) => {
                  setTasksPage(1);
                  setSortOrder(event.target.value);
                }}
                aria-label="记录排序"
              >
                <option value="desc">最新记录优先</option>
                <option value="asc">最早记录优先</option>
              </select>
              <div className="vasp-mode-control" aria-label="记录范围">
                <button
                  type="button"
                  className={onlyRelax ? "" : "is-active"}
                  disabled={loadingTasks}
                  onClick={() => { setTasksPage(1); setColumnsReady(false); setOnlyRelax(false); }}
                >
                  全部离子步
                </button>
                <button
                  type="button"
                  className={onlyRelax ? "is-active" : ""}
                  disabled={loadingTasks}
                  onClick={() => { setTasksPage(1); setColumnsReady(false); setOnlyRelax(true); }}
                >
                  每个目录最终记录
                </button>
              </div>
            </div>

            <div className="vasp-table-actions" style={{ color: "#6b7280", fontSize: 12 }}>
                <button
                    type="button"
                    onClick={async () => {
                        if (!selectedDbKey) return;

                        const only = onlyRelax ? "&only_last=1" : "";
                        const elems = selectedElems.length ? `&elems=${encodeURIComponent(selectedElems.join(","))}` : "";
                        const mode = `&elem_mode=${encodeURIComponent(elemMode)}`;

                        const cp = (cpFilters && cpFilters.length)
                            ? `&cp_filters=${encodeURIComponent(JSON.stringify(cpFilters))}`
                            : "";
                        const search = query ? `&query=${encodeURIComponent(query)}` : "";

                        const url = `${API_BASE}/api/db/vasp/export?db=${encodeURIComponent(selectedDbKey)}&scope=${encodeURIComponent(dbScope)}${only}${elems}${mode}${cp}${search}`;

                        try {
                          await downloadAuthedFile(url, "export.db");
                        } catch (e) {
                        alert(String(e?.message || e));
                        }
                    }}
                    disabled={!selectedDbKey || (selectedDb && selectedDb.exists === false)}
                    style={{
                        height: 34,
                        borderRadius: 10,
                        padding: "0 10px",
                        border: "1px solid rgba(209,213,219,1)",
                        background: "white",
                        cursor: !selectedDbKey ? "not-allowed" : "pointer",
                    }}
                    >
                    导出
                </button>

                <button
                type="button"
                onClick={() => setShowColumnPicker((v) => !v)}
                disabled={!selectedDbKey || (selectedDb && selectedDb.exists === false) || loadingColumns || allColumns.length === 0}
                style={{
                    height: 34,
                    borderRadius: 10,
                    padding: "0 10px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    cursor: !selectedDbKey ? "not-allowed" : "pointer",
                }}
                >
                选择列
                </button>

                <button
                  type="button"
                  onClick={() => {
                    setAddAllErr("");
                    setCustomTargetName(customDbs?.[0]?.safe_name || "");
                    setShowAddAllModal(true);
                  }}
                  disabled={!selectedDbKey || (selectedDb && selectedDb.exists === false) || customDbs.length === 0 || loadingTasks}
                  style={{
                    height: 34,
                    borderRadius: 10,
                    padding: "0 10px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    cursor:
                      !selectedDbKey || customDbs.length === 0 || loadingTasks
                        ? "not-allowed"
                        : "pointer",
                  }}
                  title={
                    customDbs.length === 0
                      ? "暂无自定义库（请先创建）"
                      : loadingTasks
                        ? "列表正在更新中，请稍等"
                        : "收藏当前筛选结果的全部样本（所有页）"
                  }
                >
                  全部收藏
                </button>

                <button
                    type="button"
                    onClick={() => setShowCpFilter((v) => !v)}
                    disabled={!selectedDbKey || (selectedDb && selectedDb.exists === false)}
                    style={{
                        height: 34,
                        borderRadius: 10,
                        padding: "0 10px",
                        border: "1px solid rgba(209,213,219,1)",
                        background: showCpFilter ? "rgba(59,130,246,0.10)" : "white",
                        cursor: !selectedDbKey ? "not-allowed" : "pointer",
                    }}
                    title="支持 JSON：如 0.00001 或 [2,3,1]"
                    >
                    输入参数筛选{cpFilters.length ? `（${cpFilters.length}）` : ""}
                </button>

            </div>
           </div>

          {showColumnPicker ? (
            <div
                style={{
                marginTop: 10,
                padding: 12,
                borderRadius: 12,
                border: "1px solid rgba(229,231,235,1)",
                background: "rgba(255,255,255,.75)",
                }}
            >
                <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
                <button
                    type="button"
                    onClick={() => {
                    setTasksPage(1);
                    setSelectedColumns(defaultColumns);
                    }}
                    style={{
                    height: 32,
                    borderRadius: 10,
                    padding: "0 10px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    }}
                >
                    恢复默认列
                </button>

                <button
                    type="button"
                    onClick={() => {
                    setTasksPage(1);
                    setSelectedColumns(allColumns);
                    }}
                    style={{
                    height: 32,
                    borderRadius: 10,
                    padding: "0 10px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    }}
                >
                    全选
                </button>

                <button
                    type="button"
                    onClick={() => {
                    setTasksPage(1);
                    setSelectedColumns([]);
                    }}
                    style={{
                    height: 32,
                    borderRadius: 10,
                    padding: "0 10px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    }}
                >
                    清空
                </button>
                </div>

                {/* 普通列（排除 calculator_parameters.*） */}
                <div className="vasp-column-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
                    {allColumns
                        .filter((c) => !String(c).startsWith("calculator_parameters."))
                        .map((col) => {
                        const checked = selectedColumns.includes(col);
                        return (
                            <label
                            key={col}
                            style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "#374151" }}
                            >
                            <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => {
                                setTasksPage(1);
                                setSelectedColumns((prev) => {
                                    const s = new Set(prev);
                                    if (s.has(col)) s.delete(col);
                                    else s.add(col);
                                    return Array.from(s);
                                });
                                }}
                            />
                            <span
                              title={`原始字段：${col}`}
                              style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}
                            >
                                {columnMetadata[col]?.label || col}
                            </span>
                            </label>
                        );
                    })}
                </div>

                <div style={{ marginTop: 10, color: "#6b7280", fontSize: 12 }}>
                说明：data.* 列来自后端扫描的 data keys（已排除 source_signature）。
                </div>
            </div>
          ) : null}

          {showCpFilter ? (
            <div
                style={{
                marginTop: 10,
                padding: 12,
                borderRadius: 12,
                border: "1px solid rgba(229,231,235,1)",
                background: "rgba(255,255,255,.75)",
                }}
            >
                <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
                <button
                    type="button"
                    onClick={() => {
                    setTasksPage(1);
                    setCpFilters(cpDraft.map(x => ({ path: x.path, op: x.op, value: parseCpValue(x.valueText) })));
                    }}
                    style={{
                    height: 32,
                    borderRadius: 10,
                    padding: "0 10px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    ...uiBtn(false),
                    }}
                >
                    应用筛选
                </button>

                <button
                    type="button"
                    onClick={() => {
                    setTasksPage(1);
                    setCpFilters([]);
                    setCpDraft([{ path: "", op: "eq", valueText: "" }]);
                    }}
                    style={{
                    height: 32,
                    borderRadius: 10,
                    padding: "0 10px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    ...uiBtn(false),
                    }}
                >
                    清空筛选
                </button>

                <button
                    type="button"
                    onClick={() => setCpDraft((prev) => [...prev, { path: "", op: "eq", valueText: "" }])}
                    style={{
                    height: 32,
                    borderRadius: 10,
                    padding: "0 10px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    ...uiBtn(false),
                    }}
                >
                    + 添加条件
                </button>

                <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
                    <div style={{ color: "#6b7280", fontSize: 12 }}>常用：</div>
                    {CP_CATALOG.map((it) => (
                        <button
                        key={it.path}
                        type="button"
                        onClick={() => {
                            setCpDraft((prev) => [
                            ...prev,
                            { path: it.path, op: "eq", valueText: JSON.stringify(it.defaultValue) },
                            ]);
                        }}
                        style={{
                            height: 28,
                            borderRadius: 999,
                            padding: "0 10px",
                            border: "1px solid rgba(209,213,219,1)",
                            background: "white",
                            fontSize: 12,
                            cursor: "pointer",
                        }}
                        title={it.path}
                        >
                        {it.label}
                        </button>
                    ))}
                    </div>

                    <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
                    <div style={{ color: "#6b7280", fontSize: 12 }}>预设：</div>

                    <select
                        value={selectedPresetName}
                        onChange={(e) => {
                        const name = e.target.value;
                        setSelectedPresetName(name);
                        const p = cpPresets.find(x => x?.name === name);
                        if (p?.filters) setCpDraft(p.filters);
                        }}
                        style={{
                        height: 34,
                        borderRadius: 10,
                        border: "1px solid rgba(209,213,219,1)",
                        padding: "0 10px",
                        background: "white",
                        minWidth: 220,
                        }}
                    >
                        <option value="">（不使用预设）</option>
                        {cpPresets.map((p) => (
                        <option key={p.name} value={p.name}>
                            {p.name}
                        </option>
                        ))}
                    </select>

                    <button
                        type="button"
                        onClick={() => {
                        const name = prompt("预设名称：");
                        if (!name) return;
                        const newPreset = { name, filters: cpDraft };
                        const next = [...cpPresets.filter(x => x.name !== name), newPreset];
                        saveCpPresets(next, selectedPresetName);
                        }}
                        style={{
                          height: 32,
                          borderRadius: 10,
                          padding: "0 10px",
                          border: "1px solid rgba(209,213,219,1)",
                          background: "white",
                          ...uiBtn(false),
                        }}
                    >
                        保存为预设
                    </button>

                    <button
                        type="button"
                          onClick={() => {
                              if (!selectedPresetName) return;
                              try {
                                  savePresetState(getVaspPresetStorageKey(selectedDbKey), cpPresets, selectedPresetName);
                              } catch {}
                          }}
                        disabled={!selectedPresetName}
                        style={{
                          height: 32,
                          borderRadius: 10,
                          padding: "0 10px",
                          border: "1px solid rgba(209,213,219,1)",
                          background: "white",
                          ...uiBtn(!selectedPresetName),
                        }}
                    >
                        设为默认
                    </button>

                    <button
                        type="button"
                        onClick={() => {
                        if (!selectedPresetName) return;
                        const next = cpPresets.filter(x => x.name !== selectedPresetName);
                        saveCpPresets(next, "");
                        setSelectedPresetName("");
                        }}
                        disabled={!selectedPresetName}
                        style={{
                          height: 32,
                          borderRadius: 10,
                          padding: "0 10px",
                          border: "1px solid rgba(209,213,219,1)",
                          background: "white",
                          ...uiBtn(!selectedPresetName),
                        }}
                    >
                        删除预设
                    </button>
                </div>

                <div style={{ color: "#6b7280", fontSize: 12 }}>
                    value 支持 JSON：例如 <b>0.00001</b> 或 <b>[2,3,1]</b>（筛选 kpoints_generation.divisions）
                </div>
                </div>

                <datalist id="cp-path-list">
                    {cpPathOptions.map((p) => (
                        <option key={p} value={p} />
                    ))}
                </datalist>

                {cpDraft.map((f, i) => (
                <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 2fr auto", gap: 8, marginBottom: 8 }}>
                    <input
                        value={f.path}
                        list="cp-path-list"
                        onChange={(e) => setCpDraft(prev => prev.map((x, idx) => idx === i ? { ...x, path: e.target.value } : x))}
                        placeholder="输入/选择 path，例如 ediff 或 kpoints_generation.divisions"
                        style={{
                            height: 34,
                            borderRadius: 10,
                            border: "1px solid rgba(209,213,219,1)",
                            padding: "0 10px",
                        }}
                    />

                    <select
                    value={f.op}
                    onChange={(e) => setCpDraft(prev => prev.map((x, idx) => idx === i ? { ...x, op: e.target.value } : x))}
                    style={{
                        height: 34,
                        borderRadius: 10,
                        border: "1px solid rgba(209,213,219,1)",
                        padding: "0 10px",
                        background: "white",
                    }}
                    >
                    <option value="eq">=</option>
                    </select>

                    <input
                    value={f.valueText}
                    onChange={(e) => setCpDraft(prev => prev.map((x, idx) => idx === i ? { ...x, valueText: e.target.value } : x))}
                    placeholder='value，例如 0.00001 或 [2,3,1]'
                    style={{
                        height: 34,
                        borderRadius: 10,
                        border: "1px solid rgba(209,213,219,1)",
                        padding: "0 10px",
                    }}
                    />

                    <button
                    type="button"
                    onClick={() => setCpDraft(prev => prev.filter((_, idx) => idx !== i))}
                    style={{
                      height: 34,
                      borderRadius: 10,
                      padding: "0 10px",
                      border: "1px solid rgba(209,213,219,1)",
                      background: "white",
                      ...uiBtn(false),
                    }}
                    title="删除该条件"
                    >
                    删除
                    </button>
                </div>
                ))}
            </div>
          ) : null}

          <VaspDataTable
            tasks={tasks}
            columns={selectedColumns.length > 0 ? selectedColumns : defaultColumns}
            metadata={columnMetadata}
            loading={loadingTasks}
            loadedOnce={tasksLoadedOnce}
            customDbs={customDbs}
            dbScope={dbScope}
            removingRowId={removingRowId}
            onOpenParams={openCalcParams}
            onCollect={(item) => {
              setAddCustomErr("");
              setAddCustomRow(item);
              setCustomTargetName(customDbs?.[0]?.safe_name || "");
              setShowAddToCustomModal(true);
            }}
            onRemove={handleRemoveFromCustom}
          />

          {/* ✅ 分页控件（右下角：每页 + 首页/3页码/尾页） */}
          <div
            className="vasp-pagination"
            style={{
                marginTop: 12,
                display: "flex",
                justifyContent: "flex-end",
                alignItems: "center",
                gap: 10,
            }}
            >
            {/* 每页多少条 */}
            <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ color: "#6b7280", fontSize: 12 }}>每页</span>
                <select
                value={tasksPageSize}
                onChange={(e) => {
                    setTasksPage(1);
                    setTasksPageSize(Number(e.target.value) || 20);
                }}
                style={{
                    height: 34,
                    borderRadius: 10,
                    border: "1px solid rgba(209,213,219,1)",
                    padding: "0 10px",
                    background: "white",
                }}
                >
                {[10, 20, 50].map((n) => (
                    <option key={n} value={n}>
                    {n}
                    </option>
                ))}
                </select>
            </div>

            {/* 首页 */}
            <button
                type="button"
                onClick={() => setTasksPage(1)}
                disabled={tasksPage <= 1}
                style={pagerBtnStyle(tasksPage <= 1)}
            >
                首页
            </button>

            {/* 3 个页码按钮（你已经算好了 page3） */}
            {page3.map((p) => {
                const active = p === tasksPage;
                return (
                <button
                    key={p}
                    type="button"
                    onClick={() => setTasksPage(p)}
                    disabled={active}
                    style={pagerNumStyle(active)}
                    title={`第 ${p} 页`}
                >
                    {p}
                </button>
                );
            })}

            {/* 尾页 */}
            <button
                type="button"
                onClick={() => setTasksPage(totalPages)}
                disabled={tasksPage >= totalPages}
                style={pagerBtnStyle(tasksPage >= totalPages)}
            >
                尾页
            </button>

            {/* 可选：页信息（同样放右下角） */}
            <div style={{ color: "#6b7280", fontSize: 12, marginLeft: 6 }}>
                第 {tasksPage} / {totalPages} 页
            </div>
          </div>
        </div>
      </div>
      {showParamModal ? (
        <div
            onClick={() => setShowParamModal(false)}
            style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 18,
            zIndex: 9999,
            }}
        >
            <div
            onClick={(e) => e.stopPropagation()}
            style={{
                width: "min(980px, 96vw)",
                maxHeight: "85vh",
                overflow: "auto",
                borderRadius: 14,
                background: "white",
                border: "1px solid rgba(229,231,235,1)",
                padding: 14,
            }}
            >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                <div style={{ fontSize: 14, fontWeight: 800, color: "#111827" }}>{paramModalTitle}</div>
                <button
                type="button"
                onClick={() => setShowParamModal(false)}
                style={{
                    height: 32,
                    borderRadius: 10,
                    padding: "0 10px",
                    border: "1px solid rgba(209,213,219,1)",
                    background: "white",
                    cursor: "pointer",
                }}
                >
                关闭
                </button>
            </div>

            {loadingParams ? (
                <div style={{ marginTop: 10, color: "#6b7280", fontSize: 13 }}>加载中…</div>
            ) : paramsError ? (
                <div style={{ marginTop: 10, color: "#991b1b", fontSize: 13 }}>{paramsError}</div>
            ) : paramItems.length === 0 ? (
                <div style={{ marginTop: 10, color: "#6b7280", fontSize: 13 }}>该行没有 calculator_parameters。</div>
            ) : (
                <div
                style={{
                    marginTop: 12,
                    display: "grid",
                    gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
                    gap: 10,
                }}
                >
                {paramItems.map(({ k, v }) => (
                    <div
                        key={k}
                        style={{
                        border: "1px solid rgba(229,231,235,1)",
                        borderRadius: 12,
                        padding: 10,
                        background: "rgba(249,250,251,1)",
                        }}
                    >
                        <div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "flex-start" }}>
                        <div style={{ fontSize: 12, color: "#374151", fontWeight: 700, wordBreak: "break-word" }}>
                            {k}
                        </div>

                        <button
                            type="button"
                            onClick={() => {
                            setShowCpFilter(true);
                            setCpDraft((prev) => [...prev, { path: k, op: "eq", valueText: v }]);
                            }}
                            style={{
                            height: 22,
                            borderRadius: 8,
                            padding: "0 8px",
                            border: "1px solid rgba(209,213,219,1)",
                            background: "white",
                            cursor: "pointer",
                            fontSize: 12,
                            color: "#111827",
                            whiteSpace: "nowrap",
                            }}
                            title="加入输入参数筛选"
                        >
                            加入筛选
                        </button>
                        </div>

                        <div style={{ marginTop: 6, fontSize: 12, color: "#111827", wordBreak: "break-word" }}>
                        {v}
                        </div>
                    </div>
                ))}
                </div>
            )}
            </div>
        </div>
      ) : null}
      {showUploadModal ? (
        <div
          onClick={() => setShowUploadModal(false)}
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0,0,0,0.35)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 18,
            zIndex: 9999,
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              width: "min(860px, 96vw)",
              borderRadius: 14,
              background: "white",
              border: "1px solid rgba(229,231,235,1)",
              padding: 14,
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
              <div style={{ fontSize: 14, fontWeight: 900, color: "#111827" }}>上传 VASP 文件</div>
              <button
                type="button"
                onClick={() => setShowUploadModal(false)}
                style={{
                  height: 32,
                  borderRadius: 10,
                  padding: "0 10px",
                  border: "1px solid rgba(209,213,219,1)",
                  background: "white",
                  cursor: "pointer",
                }}
              >
                关闭
              </button>
            </div>

            {/* ✅ 说明区：分块展示 */}
            <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
              {/* 必须 */}
              <div
                style={{
                  border: "1px solid rgba(229,231,235,1)",
                  background: "rgba(240,253,244,1)", // 绿色浅底
                  borderRadius: 12,
                  padding: 12,
                }}
              >
                <div style={{ fontWeight: 900, color: "#065f46", marginBottom: 6 }}>必须包含（必传）</div>
                <div style={{ fontSize: 13, color: "#111827", lineHeight: 1.7 }}>
                  <code>vasprun.xml</code> 或 <code>vasprun.xml.gz</code>  
                  <span style={{ color: "#374151" }}>（用于解析结构、能量、电子性质，并为 DOS / 能带绘图提供基础数据）。</span>
                </div>
              </div>

              {/* 能带 */}
              <div
                style={{
                  border: "1px solid rgba(229,231,235,1)",
                  background: "rgba(239,246,255,1)", // 蓝色浅底
                  borderRadius: 12,
                  padding: 12,
                }}
              >
                <div style={{ fontWeight: 900, color: "#1d4ed8", marginBottom: 6 }}>能带（Band）相关（建议上传）</div>
                <div style={{ fontSize: 13, color: "#111827", lineHeight: 1.7 }}>
                  建议额外上传 <code>KPOINTS</code>。  
                  <div style={{ marginTop: 6, color: "#374151" }}>
                    - 如果是<b>沿高对称路径的线模式 KPOINTS</b>，更容易绘制带有 <b>Γ–X–…</b> 等标记的能带图。<br />
                    - 若缺少 <code>KPOINTS</code>，能带可能只能绘制简化版本，或无法绘制（取决于数据完整性）。
                  </div>
                </div>
              </div>

              {/* 可选 */}
              <div
                style={{
                  border: "1px solid rgba(229,231,235,1)",
                  background: "rgba(249,250,251,1)", // 灰色浅底
                  borderRadius: 12,
                  padding: 12,
                }}
              >
                <div style={{ fontWeight: 900, color: "#111827", marginBottom: 6 }}>可选上传（按需求）</div>
                <div style={{ fontSize: 13, color: "#374151", lineHeight: 1.7 }}>
                  <code>INCAR</code>、<code>POSCAR</code>/<code>CONTCAR</code>、<code>OUTCAR</code>、<code>OSZICAR</code>、<code>XDATCAR</code> 等。  
                  这些文件可用于后续扩展解析（例如检查计算参数、补充信息、诊断是否收敛）。
                </div>
              </div>

              {/* 上传方式 */}
              <div
                style={{
                  border: "1px dashed rgba(209,213,219,1)",
                  background: "white",
                  borderRadius: 12,
                  padding: 12,
                }}
              >
                <div style={{ fontWeight: 900, color: "#111827", marginBottom: 6 }}>上传方式</div>
                <div style={{ fontSize: 13, color: "#374151", lineHeight: 1.7 }}>
                  你可以一次选择多个文件；系统会把它们保存到同一个任务目录，并导入到你的“上传库”中。
                </div>
              </div>

              {/* 小提示 */}
              <div style={{ fontSize: 12, color: "#6b7280", lineHeight: 1.6 }}>
                小提示：只上传 <code>vasprun.xml</code> 通常也能查看结构，并尝试绘制 DOS；但能带图更推荐同时提供 <code>KPOINTS</code>。
              </div>
            </div>

            {/* ✅ 选择文件：隐藏 input + 用按钮触发（更突出） */}
            <div style={{ marginTop: 12, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <input
                ref={filePickRef}
                type="file"
                multiple
                style={{ display: "none" }}
                onChange={(e) => {
                  const arr = Array.from(e.target.files || []);
                  setSelectedUploadFiles(arr);
                }}
              />

              <button
                type="button"
                onClick={() => filePickRef.current?.click()}
                disabled={uploading}
                style={{
                  height: 42,
                  borderRadius: 12,
                  padding: "0 16px",
                  border: "1px solid rgba(37,99,235,1)",
                  background: uploading ? "rgba(243,244,246,1)" : "rgba(37,99,235,1)",  // ✅ 主按钮填充
                  color: uploading ? "#6b7280" : "white",
                  fontWeight: 900,
                  cursor: uploading ? "not-allowed" : "pointer",  // ✅ hover 小手
                }}
              >
                选择文件（必含 vasprun.xml）
              </button>

              <div style={{ fontSize: 12, color: "#6b7280" }}>
                {selectedUploadFiles.length ? (
                  <>已选择：<b style={{ color: "#111827" }}>{selectedUploadFiles.length}</b> 个文件</>
                ) : (
                  <>未选择任何文件</>
                )}
              </div>
            </div>

            {selectedUploadFiles.length ? (
              <div style={{ marginTop: 10, maxHeight: 160, overflow: "auto", border: "1px solid rgba(229,231,235,1)", borderRadius: 12, padding: 10 }}>
                {selectedUploadFiles.map((f) => (
                  <div key={`${f.name}-${f.size}-${f.lastModified}`} style={{ fontSize: 12, color: "#374151", display: "flex", justifyContent: "space-between", gap: 10 }}>
                    <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{f.name}</span>
                    <span style={{ color: "#6b7280" }}>{Math.round(f.size / 1024)} KB</span>
                  </div>
                ))}
              </div>
            ) : null}

            <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button
                type="button"
                onClick={() => {
                  setSelectedUploadFiles([]);
                }}
                disabled={uploading}
                style={{
                  height: 36,
                  borderRadius: 12,
                  padding: "0 14px",
                  border: "1px solid rgba(209,213,219,1)",
                  background: uploading ? "rgba(243,244,246,1)" : "white",
                  color: uploading ? "#9ca3af" : "#111827",
                  cursor: uploading ? "not-allowed" : "pointer",  // ✅ hover 小手
                }}
              >
                清空选择
              </button>

              <button
                type="button"
                disabled={uploading}
                onClick={async () => {
                  try {
                    // ✅ 前端校验：必须包含 vasprun.xml/vasprun.xml.gz
                    const hasVasprun = selectedUploadFiles.some((f) => f.name === "vasprun.xml" || f.name === "vasprun.xml.gz");
                    if (!hasVasprun) {
                      alert("必须包含 vasprun.xml 或 vasprun.xml.gz");
                      return;
                    }

                    setUploading(true);
                    await uploadFiles(`${API_BASE}/api/db/vasp/upload_vasp_files`, selectedUploadFiles);

                    setShowUploadModal(false);
                    setSelectedUploadFiles([]);

                    // 上传成功后切到 upload scope（触发 available 刷新）
                    setDbScope("upload");
                  } catch (e) {
                    alert(String(e?.message || e));
                  } finally {
                    setUploading(false);
                  }
                }}
                style={{
                  height: 36,
                  borderRadius: 12,
                  padding: "0 14px",
                  border: "1px solid rgba(37,99,235,1)",
                  background: uploading ? "rgba(243,244,246,1)" : "rgba(37,99,235,1)", // ✅ 主按钮实心
                  color: uploading ? "#6b7280" : "white",
                  fontWeight: 900,
                  cursor: uploading ? "not-allowed" : "pointer", // ✅ hover 小手
                }}
              >
                {uploading ? "上传中…" : "开始上传"}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {showAddToCustomModal ? (
        <div
          onClick={() => { if (!addingToCustom) setShowAddToCustomModal(false); }}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 18, zIndex: 9999 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ width: "min(560px, 96vw)", borderRadius: 14, background: "white", border: "1px solid rgba(229,231,235,1)", padding: 14 }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
              <div style={{ fontSize: 14, fontWeight: 900, color: "#111827" }}>收藏到 VASP 自定义库</div>
              <button
                type="button"
                disabled={addingToCustom}
                onClick={() => setShowAddToCustomModal(false)}
                style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
              >
                关闭
              </button>
            </div>

            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, color:"#374151", fontWeight: 700, marginBottom: 6 }}>选择目标自定义库</div>
              <select
                value={customTargetName}
                onChange={(e) => setCustomTargetName(e.target.value)}
                disabled={addingToCustom || customDbs.length === 0}
                style={{ height: 36, borderRadius: 10, border: "1px solid #d1d5db", padding: "0 10px", background: "white", width: "100%" }}
              >
                {customDbs.length === 0 ? (
                  <option value="">暂无自定义库（请先在入口创建）</option>
                ) : (
                  customDbs.map((x) => (
                    <option key={x.safe_name} value={x.safe_name}>
                      {x.name}
                    </option>
                  ))
                )}
              </select>
            </div>

            {addCustomErr ? (
              <div style={{ marginTop: 10, padding: "10px 12px", borderRadius: 12, background: "rgba(254,242,242,.9)", border: "1px solid rgba(252,165,165,.8)", color: "#991b1b", fontSize: 13 }}>
                {addCustomErr}
              </div>
            ) : null}

            <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button
                type="button"
                disabled={addingToCustom}
                onClick={() => setShowAddToCustomModal(false)}
                style={{ height: 36, borderRadius: 12, padding: "0 14px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
              >
                取消
              </button>

              <button
                type="button"
                disabled={addingToCustom || !customTargetName || !addCustomRow?._rowId || !addCustomRow?._dbKey}
                onClick={async () => {
                  try {
                    setAddCustomErr("");
                    setAddingToCustom(true);

                    const body = {
                      target: customTargetName,
                      src_db: addCustomRow._dbKey,
                      row_id: addCustomRow._rowId,
                    };

                    const { resp, data } = await postJson(`${API_BASE}/api/db/vasp/custom/add`, body);

                    if (!resp.ok) {
                      const detail = getPostJsonErrorDetail(resp, data);

                      const looksLikeDup =
                        resp.status === 409 ||
                        String(detail).includes("already") ||
                        String(detail).includes("exists") ||
                        String(detail).includes("UNIQUE") ||
                        String(detail).includes("重复") ||
                        String(detail).includes("已存在");

                      if (looksLikeDup) {
                        setShowAddToCustomModal(false);
                        alert("该结构已在目标自定义库中（无需重复收藏）");
                        return;
                      }

                      throw new Error(detail || "收藏失败");
                    }

                    setShowAddToCustomModal(false);

                    const msg = data?.message;
                    alert(msg || "收藏成功");
                  } catch (err) {
                    const detail = err?.message || String(err);
                    setAddCustomErr("收藏失败：" + String(detail));
                  } finally {
                    setAddingToCustom(false);
                  }
                }}
                style={{ height: 36, borderRadius: 12, padding: "0 14px", border: "1px solid rgba(37,99,235,1)", background: "rgba(37,99,235,1)", color: "white", fontWeight: 900 }}
              >
                {addingToCustom ? "收藏中…" : "确认收藏"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
      {showAddAllModal ? (
        <div
          onClick={() => { if (!addingAll) setShowAddAllModal(false); }}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 18, zIndex: 9999 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ width: "min(560px, 96vw)", borderRadius: 14, background: "white", border: "1px solid rgba(229,231,235,1)", padding: 14 }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
              <div style={{ fontSize: 14, fontWeight: 900, color: "#111827" }}>全部收藏（当前列表所有页）</div>
              <button
                type="button"
                disabled={addingAll}
                onClick={() => setShowAddAllModal(false)}
                style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
              >
                关闭
              </button>
            </div>

            <div style={{ marginTop: 10, color: "#6b7280", fontSize: 12, lineHeight: 1.6 }}>
              将按当前记录范围、搜索、元素和输入参数筛选，把所有匹配记录收藏到指定自定义库。
            </div>

            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 12, color:"#374151", fontWeight: 700, marginBottom: 6 }}>选择目标自定义库</div>
              <select
                value={customTargetName}
                onChange={(e) => setCustomTargetName(e.target.value)}
                disabled={addingAll || customDbs.length === 0}
                style={{ height: 36, borderRadius: 10, border: "1px solid #d1d5db", padding: "0 10px", background: "white", width: "100%" }}
              >
                {customDbs.length === 0 ? (
                  <option value="">暂无自定义库（请先创建）</option>
                ) : (
                  customDbs.map((x) => (
                    <option key={x.safe_name} value={x.safe_name}>
                      {x.name}
                    </option>
                  ))
                )}
              </select>
            </div>

            {addAllErr ? (
              <div style={{ marginTop: 10, padding: "10px 12px", borderRadius: 12, background: "rgba(254,242,242,.9)", border: "1px solid rgba(252,165,165,.8)", color: "#991b1b", fontSize: 13 }}>
                {addAllErr}
              </div>
            ) : null}

            {addAllJobId ? (
              <div style={{ marginTop: 10, fontSize: 12, color: "#374151", lineHeight: 1.6 }}>
                任务ID：{addAllJobId}
                {addAllProgress ? (
                  <div style={{ marginTop: 6, color: "#6b7280" }}>
                    进度：{addAllProgress.processed}/{addAllProgress.total_candidates}
                    ，新增 {addAllProgress.inserted}，已存在 {addAllProgress.exists}，跳过 {addAllProgress.skipped}
                    {addAllProgress.truncated ? "（已截断）" : ""}
                  </div>
                ) : (
                  <div style={{ marginTop: 6, color: "#6b7280" }}>正在获取进度…</div>
                )}
              </div>
            ) : null}

            <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button
                type="button"
                disabled={addingAll}
                onClick={() => setShowAddAllModal(false)}
                style={{ height: 36, borderRadius: 12, padding: "0 14px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
              >
                取消
              </button>

              <button
                type="button"
                disabled={addingAll || !customTargetName || !selectedDbKey}
                onClick={async () => {
                  try {
                    setAddAllErr("");
                    setAddingAll(true);
                    setAddAllJobId("");
                    setAddAllProgress(null);

                    const body = {
                      target: customTargetName,
                      db: selectedDbKey,
                      scope: dbScope,
                      only_last: onlyRelax ? 1 : 0,
                      elems: selectedElems.length ? selectedElems.join(",") : null,
                      elem_mode: elemMode,
                      cp_filters: cpFilters,   // ✅ 直接传数组
                      query,
                    };

                    // ✅ 1) 启动后台任务（很快返回）
                    const { resp, data } = await postJson(`${API_BASE}/api/db/vasp/custom/add_all_async`, body);
                    if (!resp.ok) {
                      const detail = getPostJsonErrorDetail(resp, data);
                      throw new Error(detail || `启动任务失败（${resp.status}）`);
                    }
                    const jobId = data?.job_id;
                    if (!jobId) throw new Error("未获取到 job_id");

                    setAddAllJobId(jobId);

                    // ✅ 2) 开始轮询状态
                    stopAddAllPoll();
                    addAllPollRef.current = setInterval(async () => {
                      try {
                        const st = await fetchJson(`${API_BASE}/api/db/vasp/custom/add_all_status/${encodeURIComponent(jobId)}`);
                        const state = st?.state;
                        const meta = st?.meta;
                        const result = st?.result;
                        const error = st?.error;

                        if (meta && typeof meta === "object") setAddAllProgress(meta);

                        if (state === "SUCCESS") {
                          stopAddAllPoll();
                          setAddingAll(false);
                          setShowAddAllModal(false);

                          const msg = result?.message || "全部收藏完成";
                          alert(msg);

                          // ✅ 完成后强制刷新（防竞态“串台”）
                          setTasksPage(1);
                          setForceReloadTick((x) => x + 1);
                        }

                        if (state === "FAILURE") {
                          stopAddAllPoll();
                          setAddingAll(false);
                          setAddAllErr("后台任务失败：" + String(error || "unknown"));
                        }
                      } catch (e) {
                        // 轮询出错：不中断，让下一轮继续
                        console.error("poll add_all_status failed:", e);
                      }
                    }, 800);
                  } catch (err) {
                    const detail = err?.response?.data?.detail || err?.message || String(err);
                    setAddAllErr("全部收藏失败：" + String(detail));
                    setAddingAll(false);
                  }
                }}
                style={{ height: 36, borderRadius: 12, padding: "0 14px", border: "1px solid rgba(37,99,235,1)", background: "rgba(37,99,235,1)", color: "white", fontWeight: 900 }}
              >
                {addingAll ? "收藏中…" : "确认全部收藏"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </DbLayout>
  );
}
