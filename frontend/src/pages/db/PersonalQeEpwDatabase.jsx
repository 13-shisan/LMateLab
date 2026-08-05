// frontend/src/pages/db/PersonalQeEpwDatabase.jsx
import React, { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useLocation, Link } from "react-router-dom";
import DbLayout from "./DbLayout";
import CenterLoadingOverlay from "../../components/CenterLoadingOverlay";
import { API_BASE } from "../../api/config";
import { fetchJson } from "../../api/fetchJson";
import { uploadFiles } from "../../api/uploadFiles";
import { downloadAuthedFile } from "../../api/downloadAuthedFile";
import { getPostJsonErrorDetail, postJson } from "../../api/postJson";
import {
  getQePresetStorageKey,
  loadPresetState,
  savePresetState,
} from "../../utils/presetStorage";
import { normalizeElementSymbol } from "../../utils/elementUtils";
import { hexToRgba } from "../../utils/colorUtils";
import { flattenObjectToPairs, parseCpValue } from "../../utils/cpValueUtils";
import { CATEGORY_BY_SYMBOL, CATEGORY_COLOR } from "../../utils/elementCategory";
import { QE_CP_CATALOG } from "../../data/qeCpCatalog";

function renderCellValue(v) {
  if (v === null || v === undefined) return "-";
  if (typeof v === "object") return JSON.stringify(v); // ✅ 防止 React child 报错
  return String(v);
}


// 周期表数据（你复制自 VASP 页，保持不变即可）
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

// --------- 元素分类上色（移植自 VASP） ----------
// 这些字段只在外面的 runs 列表显示，不在详情里重复显示
const OUTER_ONLY_FIELDS = [
  "epw_params.ncarrier",
  "epw_params.nk",
  "epw_params.nkf",
  "epw_params.nq",
  "epw_params.nqf",
];

const UPLOAD_MERGED_KEY = "__upload_merged__";

export default function PersonalQeEpwDatabase() {
  const [dbList, setDbList] = useState([]);
  const [selectedDbKey, setSelectedDbKey] = useState("");
  const [loadingDbList, setLoadingDbList] = useState(false);
  const [error, setError] = useState("");
  // ✅ 用于强制刷新 /available 列表（即使 dbScope 没变化）
  const [dbListNonce, setDbListNonce] = useState(0);
  

  // ✅ scope + upload（仿 VASP）
  const [dbScope, setDbScope] = useState("all"); // all | personal | upload | custom
  const [uploading, setUploading] = useState(false);
  const [showUploadModal, setShowUploadModal] = useState(false);
  const [selectedUploadFiles, setSelectedUploadFiles] = useState([]); // File[]
  const filePickRef = useRef(null);

  const [elementsStatus, setElementsStatus] = useState("idle"); // idle|ready|error
  const [elementsSet, setElementsSet] = useState(() => new Set());
  const [highlightElemsSet, setHighlightElemsSet] = useState(() => new Set());
  const [selectedElems, setSelectedElems] = useState([]); // ["H","O"]
  const [elemMode, setElemMode] = useState("at_least");   // "at_least" | "only"

  // 表格
  const [tasks, setTasks] = useState([]);
  const [tasksTotal, setTasksTotal] = useState(0);
  const [tasksPage, setTasksPage] = useState(1);
  const [tasksPageSize, setTasksPageSize] = useState(20);
  const [tasksLoadedOnce, setTasksLoadedOnce] = useState(false);
  const [loadingTasks, setLoadingTasks] = useState(false);

  const [allColumns, setAllColumns] = useState([]);
  const [defaultColumns, setDefaultColumns] = useState([]);
  const [selectedColumns, setSelectedColumns] = useState([]);
  const [showColumnPicker, setShowColumnPicker] = useState(false);
  const [loadingColumns, setLoadingColumns] = useState(false);

  // 详情弹窗
  const [showParamModal, setShowParamModal] = useState(false);
  const [paramModalTitle, setParamModalTitle] = useState("");
  const [paramItems, setParamItems] = useState([]); // [{k,v}]
  const [loadingParams, setLoadingParams] = useState(false);
  const [paramsError, setParamsError] = useState("");

  // ✅ 输入参数筛选
  const [showCpFilter, setShowCpFilter] = useState(false);
  const [cpFilters, setCpFilters] = useState([]); // 已应用：[{path,op,value}]
  const [cpDraft, setCpDraft] = useState([{ path: "", op: "eq", valueText: "" }]); // 草稿：[{path,op,valueText}]
  const [cpPathOptions, setCpPathOptions] = useState([]); // datalist 可选 path
  const [cpPresets, setCpPresets] = useState([]); // [{name, filters:[{path,op,valueText}]}]
  const [selectedPresetName, setSelectedPresetName] = useState("");

  // 详情字段选择（像主表“选择列”）
  const [showDetailFieldPicker, setShowDetailFieldPicker] = useState(false);
  const [allDetailFields, setAllDetailFields] = useState([]);       // ["code","calc_type",...]
  const [defaultDetailFields, setDefaultDetailFields] = useState([]); // 默认勾选
  const [selectedDetailFields, setSelectedDetailFields] = useState([]); // 当前勾选

  // mobility 表格（把 mobility_rows 拆成列）
  const [mobilityRows, setMobilityRows] = useState([]);           // [{carrier,temp_K,...}, ...]
  const [showMobilityColPicker, setShowMobilityColPicker] = useState(false);
  const [mobilityAllCols, setMobilityAllCols] = useState([]);     // 所有可选列
  const [mobilitySelectedCols, setMobilitySelectedCols] = useState([]); // 当前勾选列

  const tableWrapRef = useRef(null);
  const [cellSize, setCellSize] = useState(44);
  const GAP = 6;

  const navigate = useNavigate();
  const location = useLocation();

  function saveCpPresets(nextPresets, defaultPreset = selectedPresetName) {
    setCpPresets(nextPresets);
    try {
      savePresetState(getQePresetStorageKey(normNow.scope, normNow.dbKey || ""), nextPresets, defaultPreset);
    } catch {}
  }

  // 收藏弹窗
  const [showAddToCustomModal, setShowAddToCustomModal] = useState(false);
  const [customTargets, setCustomTargets] = useState([]); // items from /custom/list
  const [customTargetName, setCustomTargetName] = useState(""); // safe name (stem)
  const [addingToCustom, setAddingToCustom] = useState(false);
  const [addCustomErr, setAddCustomErr] = useState("");
  const [addCustomRow, setAddCustomRow] = useState(null); // { _rowId, _dbKey, _dbName }

  // 删除弹窗
  const [removingRowId, setRemovingRowId] = useState(0);
  const [forceReloadTick, setForceReloadTick] = useState(0); // ✅ 用于强制刷新 tasks

  // ✅ 全部收藏（QE）
  const [showAddAllModal, setShowAddAllModal] = useState(false);
  const [addingAll, setAddingAll] = useState(false);
  const [addAllErr, setAddAllErr] = useState("");
  const addAllPollRef = useRef(null);
  const [addAllJobId, setAddAllJobId] = useState("");
  const [addAllProgress, setAddAllProgress] = useState(null);

  function stopAddAllPoll() {
    if (addAllPollRef.current) {
      clearInterval(addAllPollRef.current);
      addAllPollRef.current = null;
    }
  }
  useEffect(() => () => stopAddAllPoll(), []);

  const elemPollTimerRef = useRef(null);
  // ✅ 组件卸载时：停止“刷新元素”的轮询，避免泄漏/重复请求
  useEffect(() => {
    return () => {
      if (elemPollTimerRef.current) {
        window.clearInterval(elemPollTimerRef.current);
        elemPollTimerRef.current = null;
      }
    };
  }, []);

  // ✅ 预加载自定义库列表（对齐 VASP：收藏按钮只负责打开弹窗）
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await fetchJson(`${API_BASE}/api/db/qe_epw/custom/list`);
        const items = Array.isArray(data?.items) ? data.items : [];
        if (!alive) return;
        setCustomTargets(items || []);
      } catch {
        if (!alive) return;
        setCustomTargets([]);
      }
    })();
    return () => { alive = false; };
  }, []);

  function normalizeScopeDb(scope, dbKey) {
    const s = String(scope || "all");
    const k = String(dbKey || "");

    const isCustom = k.startsWith("custom_qe_epw:");
    const isUploadMerged = (s === "upload" && k === UPLOAD_MERGED_KEY);

    // upload 合并视图允许 dbKey 是特殊 key
    if (isUploadMerged) return { scope: s, dbKey: k };

    // ✅ scope != custom：不允许 custom dbKey
    if (s !== "custom" && isCustom) return { scope: s, dbKey: "" };

    // ✅ scope == custom：只允许 custom dbKey（否则清空，让后端用 scope=custom 合并或让前端默认选）
    if (s === "custom" && k && !isCustom) return { scope: s, dbKey: "" };

    return { scope: s, dbKey: k };
  }
  
  // ✅ 统一的“当前合法 scope/dbKey”，必须在任何 useEffect 使用它之前声明
  const normNow = normalizeScopeDb(dbScope, selectedDbKey);
  const isUploadMerged2 = (normNow.scope === "upload" && normNow.dbKey === UPLOAD_MERGED_KEY);

  const dbParam =
    (!normNow.dbKey || isUploadMerged2)
      ? ""
      : `db=${encodeURIComponent(normNow.dbKey)}&`;

  // URL 同步：只保留基本参数（db/page/page_size）
  function readQuery() {
    const sp = new URLSearchParams(location.search);
    const page = Math.max(1, parseInt(sp.get("page") || "1", 10) || 1);
    const pageSize = [10, 20, 50].includes(parseInt(sp.get("page_size") || "20", 10))
      ? parseInt(sp.get("page_size") || "20", 10)
      : 20;

    let scope = sp.get("scope") || "all";
    let dbKey = sp.get("db") || "";

    const elemMode2 = (sp.get("elem_mode") || "at_least").trim();
    const selectedElems2 = (sp.get("elems") || "")
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    // 用统一裁剪
    const norm = normalizeScopeDb(scope, dbKey);
    scope = norm.scope;
    dbKey = norm.dbKey;

    let cpFilters2 = [];
    try {
      const raw = sp.get("cp_filters");
      cpFilters2 = raw ? JSON.parse(raw) : [];
    } catch {
      cpFilters2 = [];
    }

    return { page, pageSize, dbKey, scope, elemMode: elemMode2, selectedElems: selectedElems2, cpFilters: cpFilters2 };
  }

  function writeQuery(next) {
    const sp = new URLSearchParams();
    if (next.dbKey) sp.set("db", next.dbKey);
    if (next.scope) sp.set("scope", next.scope);

    sp.set("page", String(next.page || 1));
    sp.set("page_size", String(next.pageSize || 20));

    if (next.elemMode) sp.set("elem_mode", next.elemMode);
    if (next.selectedElems && next.selectedElems.length) {
      sp.set("elems", next.selectedElems.join(","));
    }
    if (next.cpFilters && next.cpFilters.length) {
      sp.set("cp_filters", JSON.stringify(next.cpFilters));
    }

    return sp.toString();
  }

  const didInitFromUrlRef = useRef(false);
  useEffect(() => {
    if (didInitFromUrlRef.current) return;
    didInitFromUrlRef.current = true;

    const q = readQuery();
    setTasksPage(q.page);
    setTasksPageSize(q.pageSize);

    if (q.scope) setDbScope(q.scope);

    if (q.elemMode) setElemMode(q.elemMode);
    if (Array.isArray(q.selectedElems)) setSelectedElems(q.selectedElems);

    if (q.dbKey) setSelectedDbKey(q.dbKey);
    if (Array.isArray(q.cpFilters)) setCpFilters(q.cpFilters);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const lastSyncedQsRef = useRef("");
  useEffect(() => {
    if (!didInitFromUrlRef.current) return;

    const norm = normalizeScopeDb(dbScope, selectedDbKey);

    const qs = writeQuery({
      page: tasksPage,
      pageSize: tasksPageSize,
      dbKey: norm.dbKey,
      scope: norm.scope,
      elemMode,
      selectedElems,
      cpFilters,
    });

    const curQs = new URLSearchParams(location.search).toString();
    const nextQs = new URLSearchParams(qs).toString();

    if (lastSyncedQsRef.current === nextQs) return;
    if (curQs === nextQs) return;

    lastSyncedQsRef.current = nextQs;
    navigate(`${location.pathname}?${nextQs}`, { replace: true });
  }, [
    tasksPage,
    tasksPageSize,
    selectedDbKey,
    dbScope,
    elemMode,
    selectedElems,
    cpFilters,
    location.pathname,
    location.search,
    navigate,
  ]);

  // 周期表响应式
  useEffect(() => {
    const el = tableWrapRef.current;
    if (!el) return;

    const MAX = 44;
    const MIN = 30;

    const ro = new ResizeObserver(() => {
      const w = el.clientWidth || 0;
      const usable = Math.max(0, w - 24);
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
      userSelect: "none",
      boxSizing: "border-box",
      transition: "all .15s ease",
    }),
    [cellSize]
  );

  function renderElementCell(el) {
    const sym = el.symbol;

    // 是否在当前 DB 中出现（或“当前筛选条件”下可用）
    const present = highlightElemsSet.has(sym);

    // 是否被用户选中
    const active = selectedElems.includes(sym);

    const category = CATEGORY_BY_SYMBOL[sym] || "unknown";
    const catColor = CATEGORY_COLOR[category] || CATEGORY_COLOR.unknown;

    // present：实色；不 present：淡色+变暗
    const bg = present ? catColor : hexToRgba(catColor, 0.18);

    const style = {
      ...cellBase,
      gridColumn: el.col,
      gridRow: el.row,

      background: bg,
      opacity: present ? 1 : 0.35,
      borderColor: active ? "rgba(59,130,246,1)" : (present ? "rgba(17,24,39,.18)" : "rgba(229,231,235,1)"),
      boxShadow: active ? "0 0 0 3px rgba(59,130,246,.25)" : "none",
      filter: present ? "none" : "grayscale(0.2)",
      cursor: "pointer",
    };

    const title = `${sym} (Z=${el.Z}) ${el.name}${present ? "" : " — not in current DB"}`;

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
        <div style={{ fontSize: Math.max(9, Math.floor(cellSize * 0.23)), color: "rgba(17,24,39,.55)" }}>
          {el.Z}
        </div>
        <div style={{ fontSize: Math.max(11, Math.floor(cellSize * 0.34)), fontWeight: 800, color: "rgba(17,24,39,.85)" }}>
          {sym}
        </div>
      </div>
    );
  }

  // 1) load available db list
  useEffect(() => {
    console.log("[qe] dbScope state =", dbScope, "location.search =", location.search);
    let alive = true;

    (async () => {
      setLoadingDbList(true);
      setError("");
      try {
        const data = await fetchJson(`${API_BASE}/api/db/qe_epw/available?scope=${encodeURIComponent(normNow.scope)}`);
        if (!alive) return;

        let list0 = Array.isArray(data) ? data : [];
        if (normNow.scope === "all") {
          list0 = list0.filter((x) => !String(x?.key || "").startsWith("custom_qe_epw:"));
        }

        // ✅ scope=upload：插入一个“合并视图”选项（key 为空字符串）
        const list =
          normNow.scope === "upload" ? [
                  {
                  kind: "upload_merged",
                  key: UPLOAD_MERGED_KEY,               
                  label: "上传库（合并）",
                  dbname: "(merged)",
                  exists: true,
                  missingReason: null,
                  },
                  ...list0,
              ]
              : list0;

        setDbList(list);

        setSelectedDbKey((prev) => {
          // 1) 之前的选择还在列表里 → 继续用
          if (prev && list.some((x) => x.key === prev)) return prev;

          if (!list.length) return "";

          // 2) scope=all / personal：默认优先选 owner（个人库 merged），而不是 upload
          if (normNow.scope === "all" || normNow.scope === "personal") {
            const ownerFirst =
              list.find((x) => x?.kind === "owner") ||
              list.find((x) => String(x?.key || "").startsWith("owner:"));
            if (ownerFirst?.key) return ownerFirst.key;
          }

          // 3) scope=upload：默认选 upload 第一条
          return list[0].key || "";
        });
      } catch (e) {
        if (!alive) return;
        setError(String(e?.message || e));
        setDbList([]);
      } finally {
        if (alive) setLoadingDbList(false);
      }
    })();

    return () => { alive = false; };
  }, [normNow.scope, normNow.dbKey, dbListNonce]);

  const selectedDb = useMemo(() => dbList.find((d) => d.key === selectedDbKey) || null, [dbList, selectedDbKey]);
  const isUploadMerged = (dbScope === "upload" && selectedDbKey === UPLOAD_MERGED_KEY);

  useEffect(() => {
    const norm = normalizeScopeDb(dbScope, selectedDbKey);
    if (norm.dbKey !== selectedDbKey) setSelectedDbKey(norm.dbKey);
    // 不自动 setDbScope，避免 scope 抖动
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dbScope, selectedDbKey]);

  // ✅ 关键：当没有可用库（比如 scope=upload 但列表为空）时，清空旧数据显示
  useEffect(() => {
    const isUploadMerged = (dbScope === "upload" && selectedDbKey === UPLOAD_MERGED_KEY);

    // ✅ upload 合并视图不应被当成“没选库”
    if ((!selectedDbKey && !isUploadMerged) || (selectedDb && selectedDb.exists === false)) {
        setElementsStatus("idle");
        setElementsSet(new Set());
        setHighlightElemsSet(new Set());

        setAllColumns([]);
        setDefaultColumns([]);
        setSelectedColumns([]);
        setShowColumnPicker(false);

        setTasks([]);
        setTasksTotal(0);
        setLoadingTasks(false);
        setTasksLoadedOnce(true);
        return;
    }
    }, [selectedDbKey, selectedDb, dbScope]);

  // 2) load elements (for highlight) — 缓存优先 + scanning 轮询
  useEffect(() => {
    let alive = true;
    let timer = null;

    if (!selectedDbKey) return;
    if (selectedDb && selectedDb.exists === false) return;

    async function getElements(refresh = 0) {
      const url =
        `${API_BASE}/api/db/qe_epw/elements?${dbParam}scope=${encodeURIComponent(normNow.scope)}&refresh=${refresh ? 1 : 0}`;
      return await fetchJson(url);
    }

    async function start() {
      try {
        setError("");
        setElementsStatus("idle");

        // 1) 先用 refresh=0（命中内存/文件缓存最省）
        let data = await getElements(0);
        if (!alive) return;

        let status = String(data?.status || "ready");
        setElementsStatus(status);

        if (status === "ready") {
          const arr = Array.isArray(data?.elements) ? data.elements : [];
          const s = new Set(arr.map(normalizeElementSymbol));
          setElementsSet(s);
          setHighlightElemsSet(s);
          return;
        }

        // 2) 若是 scanning/refreshing：轮询 refresh=0 直到 ready（最多 120s）
        const t0 = Date.now();
        timer = window.setInterval(async () => {
          try {
            if (!alive) return;

            if (Date.now() - t0 > 120000) {
              window.clearInterval(timer);
              timer = null;
              setError("元素扫描超时（库较大或服务器繁忙），稍后再试或点击刷新元素。");
              return;
            }

            const d2 = await getElements(0);
            if (!alive) return;

            const st2 = String(d2?.status || "ready");
            setElementsStatus(st2);

            if (st2 === "ready") {
              const arr2 = Array.isArray(d2?.elements) ? d2.elements : [];
              const s2 = new Set(arr2.map(normalizeElementSymbol));
              setElementsSet(s2);
              setHighlightElemsSet(s2);

              window.clearInterval(timer);
              timer = null;
            }
          } catch (e) {
            window.clearInterval(timer);
            timer = null;
            if (!alive) return;
            setElementsStatus("error");
            setError(String(e?.message || e));
          }
        }, 1500);
      } catch (e) {
        if (!alive) return;
        setElementsStatus("error");
        setError(String(e?.message || e));
      }
    }

    start();

    return () => {
      alive = false;
      if (timer) window.clearInterval(timer);
    };
  }, [selectedDbKey, selectedDb, dbScope, dbParam]);

  async function handleRefreshElements() {
    if ((!selectedDbKey && dbScope !== "upload") || (selectedDb && selectedDb.exists === false)) return;

    // ✅ 开始新一轮刷新前，先清掉旧的轮询（防止多条 interval 并发）
    if (elemPollTimerRef.current) {
      window.clearInterval(elemPollTimerRef.current);
      elemPollTimerRef.current = null;
    }

    try {
      setError("");
      setElementsStatus("refreshing");

      // 1) 触发后台重算
      await fetchJson(
        `${API_BASE}/api/db/qe_epw/elements?${dbParam}scope=${encodeURIComponent(normNow.scope)}&refresh=1`
      );

      // 2) 轮询直到 ready
      const t0 = Date.now();

      elemPollTimerRef.current = window.setInterval(async () => {
        try {
          const data = await fetchJson(
            `${API_BASE}/api/db/qe_epw/elements?${dbParam}scope=${encodeURIComponent(normNow.scope)}&refresh=0`
          );

          const status = String(data?.status || "ready");
          setElementsStatus(status);

          if (status === "ready") {
            const arr = Array.isArray(data?.elements) ? data.elements : [];
            const s = new Set(arr.map(normalizeElementSymbol));
            setElementsSet(s);
            setHighlightElemsSet(s);

            if (elemPollTimerRef.current) {
              window.clearInterval(elemPollTimerRef.current);
              elemPollTimerRef.current = null;
            }
            return;
          }

          if (Date.now() - t0 > 120000) {
            if (elemPollTimerRef.current) {
              window.clearInterval(elemPollTimerRef.current);
              elemPollTimerRef.current = null;
            }
            setError("元素刷新超时（库较大或服务器繁忙），稍后再试。");
          }
        } catch (e) {
          if (elemPollTimerRef.current) {
            window.clearInterval(elemPollTimerRef.current);
            elemPollTimerRef.current = null;
          }
          setElementsStatus("error");
          setError(String(e?.message || e));
        }
      }, 1500);
    } catch (e) {
      // ✅ refresh=1 本身请求失败
      if (elemPollTimerRef.current) {
        window.clearInterval(elemPollTimerRef.current);
        elemPollTimerRef.current = null;
      }
      setElementsStatus("error");
      setError(String(e?.message || e));
    }
  }

  // 3) load columns
  useEffect(() => {
    if (!selectedDbKey) return;  
    if (selectedDb && selectedDb.exists === false) return;

    const controller = new AbortController();
    (async () => {
      setLoadingColumns(true);
      try {
        const url = `${API_BASE}/api/db/qe_epw/columns?${dbParam}scope=${encodeURIComponent(normNow.scope)}&sample=2000`;
        const data = await fetchJson(url, { signal: controller.signal });

        const all = Array.isArray(data?.all) ? data.all : [];
        const def = Array.isArray(data?.default) ? data.default : [];

        setAllColumns(all);
        setDefaultColumns(def);
        setSelectedColumns((prev) => (prev && prev.length > 0 ? prev : def));
      } catch (e) {
        if (e?.name !== "AbortError") {
          setAllColumns([]);
          setDefaultColumns([]);
          setSelectedColumns([]);
        }
      } finally {
        setLoadingColumns(false);
      }
    })();

    return () => controller.abort();
  }, [selectedDbKey, selectedDb, dbScope]);

  // 4) load tasks
  const tasksReqIdRef = useRef(0);
  useEffect(() => {
    const allowMerged =
      normNow.scope === "upload" || normNow.scope === "custom" || normNow.scope === "all" || normNow.scope === "personal";

    // 如果 scope 允许 merged（db 为空），就不应该因为 dbKey 为空直接 return
    if (!normNow.dbKey && !allowMerged) return;

    // 只要库明确不存在就 return
    if (selectedDb && selectedDb.exists === false) return;

    const controller = new AbortController();
    const reqId = ++tasksReqIdRef.current;

    (async () => {
      // ✅ 发起请求前先清空旧数据，防止“闪旧数据”
      setTasks([]);
      setTasksTotal(0);
      setLoadingTasks(true);
      setTasksLoadedOnce(false);

      try {
        const cols = (selectedColumns && selectedColumns.length > 0)
          ? `&columns=${encodeURIComponent(selectedColumns.join(","))}`
          : "";

        const elems = selectedElems.length
          ? `&elems=${encodeURIComponent(selectedElems.join(","))}`
          : "";
        const mode = `&elem_mode=${encodeURIComponent(elemMode)}`;

        const cp =
          (cpFilters && cpFilters.length)
            ? `&cp_filters=${encodeURIComponent(JSON.stringify(cpFilters))}`
            : "";

        const url =
          `${API_BASE}/api/db/qe_epw/tasks?${dbParam}scope=${encodeURIComponent(normNow.scope)}` +
          `&page=${tasksPage}&page_size=${tasksPageSize}${cols}${elems}${mode}${cp}`;

        const data = await fetchJson(url, { signal: controller.signal });

        // ✅ 若期间又发起了新请求，丢弃旧结果
        if (reqId !== tasksReqIdRef.current) return;

        setTasks(Array.isArray(data?.items) ? data.items : []);
        setTasksTotal(Number.isFinite(data?.total) ? data.total : 0);
      } catch (e) {
        if (e?.name === "AbortError") return;
        if (reqId !== tasksReqIdRef.current) return;

        setTasks([]);
        setTasksTotal(0);
      } finally {
        if (reqId !== tasksReqIdRef.current) return;
        setLoadingTasks(false);
        setTasksLoadedOnce(true);
      }
    })();

    return () => controller.abort();
  }, [selectedDbKey, selectedDb, dbScope, tasksPage, tasksPageSize, selectedColumns, selectedElems, elemMode, cpFilters, forceReloadTick]);

  useEffect(() => {
    let alive = true;

    (async () => {
      try {
        if (!showCpFilter) return;
        if ((!selectedDbKey && dbScope !== "upload") || (selectedDb && selectedDb.exists === false)) return;

        const url =
          `${API_BASE}/api/db/qe_epw/cp_keys?${dbParam}scope=${encodeURIComponent(normNow.scope)}` +
          `&sample=2000&max_depth=4`;

        const data = await fetchJson(url);
        if (!alive) return;

        const keys = Array.isArray(data?.keys) ? data.keys.map(String) : [];
        setCpPathOptions(keys);
      } catch {
        if (!alive) return;
        setCpPathOptions([]);
      }
    })();

    return () => { alive = false; };
  }, [showCpFilter, selectedDbKey, dbScope, selectedDb, dbParam, normNow.scope]);

  useEffect(() => {
    try {
      const { presets, defaultPreset: defName } = loadPresetState(
        getQePresetStorageKey(normNow.scope, normNow.dbKey || "")
      );
      setCpPresets(presets);

      setSelectedPresetName(defName);

      // 若存在默认预设：把它加载进草稿（不自动应用，避免困惑）
      if (defName) {
        const p = presets.find((x) => x?.name === defName);
        if (p?.filters) setCpDraft(p.filters);
      }
    } catch {
      setCpPresets([]);
      setSelectedPresetName("");
    }
    // 注意：这里跟随“当前库”变化
  }, [normNow.scope, normNow.dbKey]); 

  function openAddToCustom(row) {
    const rowId = row?._rowId;
    const rowDbKey = row?._dbKey;
    if (!rowId || !rowDbKey) return;

    setAddCustomErr("");
    setAddCustomRow(row); // ✅ 对齐 VASP：直接用整行（含 _dbKey/_rowId/_dbName）
    setCustomTargetName(customTargets?.[0]?.name || customTargets?.[0]?.safe_name || "");
    setShowAddToCustomModal(true);
  }

  async function handleRemoveFromCustom(row) {
    // 只在 custom scope + 当前选中的是某个 custom_qe_epw 单库时允许
    if (dbScope !== "custom") return;
    if (!String(selectedDbKey || "").startsWith("custom_qe_epw:")) return;

    const rid = row?._rowId;
    const dbk = row?._dbKey;
    if (!rid || !dbk) return;

    // 保险：必须是当前选中的这个自定义库
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

      const { resp, data } = await postJson(`${API_BASE}/api/db/qe_epw/custom/remove`, body);

      if (!resp.ok) {
        const detail = getPostJsonErrorDetail(resp, data);
        throw new Error(detail || `移除失败（${resp.status}）`);
      }

      // 成功提示
      const msg = (data && typeof data === "object") ? data.message : "";
      alert(msg || "已移除");

      // ✅ 强制刷新列表（最稳）
      setForceReloadTick((x) => x + 1);
    } catch (e) {
      alert("移除失败：" + String(e?.message || e));
    } finally {
      setRemovingRowId(0);
    }
  }

  async function openCalcParams(row) {
    const rowId = row?._rowId;
    const rowDbKey = row?._dbKey;
    if (!rowId || !rowDbKey) return;

    setShowParamModal(true);
    setLoadingParams(true);
    setParamsError("");
    setParamModalTitle(`详情（id=${rowId}）`);
    setParamItems([]);
    setShowDetailFieldPicker(false);
    setAllDetailFields([]);
    setDefaultDetailFields([]);
    setSelectedDetailFields([]);

    setMobilityRows([]);
    setShowMobilityColPicker(false);
    setMobilityAllCols([]);
    setMobilitySelectedCols([]);

    try {
      const url = `${API_BASE}/api/db/qe_epw/task/${encodeURIComponent(rowId)}/calculator_parameters?db=${encodeURIComponent(rowDbKey)}`;
      const data = await fetchJson(url);

      const cp = (data?.calculator_parameters && typeof data.calculator_parameters === "object")
        ? data.calculator_parameters
        : {};

      setParamModalTitle(`详情（db=${row?._dbName || rowDbKey}, id=${rowId}）`);

      // 1) mobility：详情里展示“非 300K”的行（300K 已在外表作为列）
      const allMob = Array.isArray(cp?.mobility) ? cp.mobility : [];

      const non300 = allMob.filter((r) => {
        const t = Number(r?.temp_K);
        if (!Number.isFinite(t)) return true; // temp_K 缺失就先展示出来
        return Math.abs(t - 300.0) > 1e-6;
      });

      setMobilityRows(non300);

      // 计算 mobility 可选列
      const mobColSet = new Set();
      for (const r of non300) {
        if (r && typeof r === "object") {
          Object.keys(r).forEach((k) => mobColSet.add(k));
        }
      }
      const mobAll = Array.from(mobColSet).sort();
      setMobilityAllCols(mobAll);

      // mobility 默认列（你要的 carrier 等）
      const mobDefault = ["carrier", "temp_K", "fermi_ev", "density_cm2", "mu_x_cm2Vs", "mu_y_cm2Vs"]
        .filter((c) => mobColSet.has(c));
      setMobilitySelectedCols((prev) => (prev && prev.length > 0 ? prev : (mobDefault.length ? mobDefault : mobAll.slice(0, 8))));

      // 2) 详情字段：为了避免把 mobility_rows/file_refs 变成一坨巨大的 JSON 字符串
      //    我们先把它们从 cp 里剔除，再 flatten（mobility_rows 用表格展示，file_refs 可另做表格，先 stringify 也行）
      const cp2 = { ...(cp || {}) };

      // mobility 用表格展示（并且我们只展示非300K），不参与 flatten
      delete cp2.mobility;

      // 兼容旧字段（如果某些库/旧后端还返回 mobility_rows）
      delete cp2.mobility_rows;

      let pairs = flattenObjectToPairs(cp2);

      // 外表专用字段：不在详情里重复展示
      pairs = pairs.filter(({ k }) => !OUTER_ONLY_FIELDS.includes(k));

      pairs.sort((a, b) => a.k.localeCompare(b.k));
      setParamItems(pairs);

      // 3) 详情字段选择：构建“可勾选字段列表”
      const keys = pairs.map((x) => x.k);
      setAllDetailFields(keys);

      // 默认勾选：常用字段 + meta/epw_params
      const def = keys.filter((k) =>
        k === "code" ||
        k === "calc_type" ||
        k === "qe_in_path" ||
        k === "epw_in_path" ||
        k === "prefix" ||
        k === "out_path" ||
        k === "workdir" ||
        k.startsWith("meta.") ||
        k.startsWith("epw_params.") ||
        k.startsWith("structure.")
      );
      setDefaultDetailFields(def.length ? def : keys.slice(0, 30));
      setSelectedDetailFields((prev) => (prev && prev.length > 0 ? prev : (def.length ? def : keys.slice(0, 30))));
    } catch (e) {
      setParamsError(String(e?.message || e));
    } finally {
      setLoadingParams(false);
    }
  }

  const totalPages = Math.max(1, Math.ceil((tasksTotal || 0) / (tasksPageSize || 20)));
  const page3 = (() => {
    let start = Math.max(1, tasksPage - 1);
    let end = Math.min(totalPages, start + 2);
    start = Math.max(1, end - 2);
    const arr = [];
    for (let p = start; p <= end; p++) arr.push(p);
    return arr;
  })();

  const pagerBtnStyle = (disabled) => ({
    height: 34,
    borderRadius: 10,
    padding: "0 10px",
    border: "1px solid rgba(209,213,219,1)",
    background: disabled ? "rgba(243,244,246,1)" : "white",
    color: disabled ? "#9ca3af" : "#111827",
    cursor: disabled ? "not-allowed" : "pointer",
  });

  const pagerNumStyle = (active) => ({
    height: 34,
    minWidth: 34,
    borderRadius: 10,
    padding: "0 10px",
    border: active ? "1px solid rgba(37,99,235,1)" : "1px solid rgba(209,213,219,1)",
    background: active ? "rgba(37,99,235,0.10)" : "white",
    color: active ? "#1d4ed8" : "#111827",
    fontWeight: active ? 800 : 500,
    cursor: active ? "default" : "pointer",
  });

  const lanActLabelStyle = {
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    paddingRight: 10,
    color: "#6b7280",
    fontSize: Math.max(11, Math.floor(cellSize * 0.28)),
    userSelect: "none",
  };

  return (
    <DbLayout currentSubPath="/dashboard/db/personal" currentDbType="qe_epw" showDbTypeSelector={true}>
      <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: "calc(100vh - 120px)", paddingBottom: 24 }}>
        <div>
          <h2 style={{ marginBottom: 6 }}>QE + EPW 数据库（个人 / 授权访问）</h2>
          <p style={{ marginTop: 0, color: "#4b5563", fontSize: 14 }}>
            上方周期表展示库中出现过的元素（高亮）；下方为 runs 列表（分页表格）。
          </p>
        </div>

        {/* Toolbar */}
        <div className="glass-card" style={{ padding: 14, borderRadius: 14, border: "1px solid rgba(229,231,235,1)", background: "rgba(255,255,255,.6)" }}>
          <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", justifyContent: "space-between" }}>
            <div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
              {/* 范围 + 上传 */}
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={{ fontSize: 13, color: "#374151", minWidth: 80 }}>数据库范围</div>

                <select
                  value={dbScope}
                  onChange={(e) => {
                    const next = e.target.value;

                    setTasksPage(1);
                    setShowColumnPicker(false);

                    // ✅ 立刻清空当前选择，防止短暂显示上一次库的数据
                    setSelectedDbKey("");
                    if (elemPollTimerRef.current) {
                      window.clearInterval(elemPollTimerRef.current);
                      elemPollTimerRef.current = null;
                    }
                    setDbList([]);

                    // ✅ 同步清空旧数据（用户体验更干净）
                    setElementsStatus("idle");
                    setElementsSet(new Set());
                    setHighlightElemsSet(new Set());
                    setAllColumns([]);
                    setDefaultColumns([]);
                    setSelectedColumns([]);
                    setTasks([]);
                    setTasksTotal(0);
                    setTasksLoadedOnce(true);

                    setDbScope(next);

                    // ✅ 立刻写 URL，避免被旧 URL / 旧 state 再写回 custom
                    const qs = writeQuery({
                      page: 1,
                      pageSize: tasksPageSize,
                      dbKey: "",            // ✅ 清空 db
                      scope: next,          // ✅ 用新 scope
                      elemMode,
                      selectedElems,
                    });

                    // 写入锁同步更新，避免后面的 URL 同步 effect 又写一次造成抖动
                    lastSyncedQsRef.current = new URLSearchParams(qs).toString();
                    navigate(`${location.pathname}?${lastSyncedQsRef.current}`, { replace: true });
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
                  <option value="personal">个人库</option>
                  <option value="upload">上传库</option>
                  <option value="custom">自定义库</option>
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
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <div style={{ fontSize: 13, color: "#374151", minWidth: 80 }}>选择数据库</div>

                <select
                  value={selectedDbKey}
                  onChange={(e) => {
                    setTasksPage(1);
                    setShowColumnPicker(false);
                    setSelectedDbKey(e.target.value);
                  }}
                  disabled={loadingDbList || dbList.length === 0}
                  style={{ height: 36, borderRadius: 10, border: "1px solid rgba(209,213,219,1)", padding: "0 10px", background: "white", minWidth: 280 }}
                >
                  {dbList.length === 0 ? (
                    <option value="">{loadingDbList ? "加载中..." : "暂无可用数据库"}</option>
                  ) : (
                    dbList.map((d) => (
                      <option key={`${d.kind}:${d.key || d.dbname || "(merged)"}`} value={d.key}>
                        {d.label} — {d.dbname}{d.exists ? "" : "（不存在）"}
                      </option>
                    ))
                  )}
                </select>

                <div style={{ fontSize: 12, color: "#6b7280" }}>
                  {selectedDb && selectedDb.exists === false ? `数据库不存在：${selectedDb.missingReason || ""}` : (elementsStatus === "ready" ? "已加载元素" : "元素加载中…")}
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <div style={{ fontSize: 12, color: "#6b7280" }}>
                高亮元素数：{" "}
                <span style={{ color: "#111827", fontWeight: 700 }}>{highlightElemsSet.size}</span>
              </div>

              <button
                type="button"
                onClick={handleRefreshElements}
                disabled={(!selectedDbKey && dbScope !== "upload") || (selectedDb && selectedDb.exists === false)}
                style={{
                  height: 36,
                  borderRadius: 10,
                  padding: "0 12px",
                  border: "1px solid rgba(209,213,219,1)",
                  background: "white",
                  cursor: (!selectedDbKey && dbScope !== "upload") ? "not-allowed" : "pointer",
                }}
              >
                刷新元素
              </button>
            </div>
          </div>

          {error ? (
            <div style={{ marginTop: 10, padding: "10px 12px", borderRadius: 12, background: "rgba(254,242,242,.9)", border: "1px solid rgba(252,165,165,.8)", color: "#991b1b", fontSize: 13 }}>
              {error}
            </div>
          ) : null}
        </div>

        {/* Periodic Table */}
        <div className="glass-card" style={{ flex: "0 0 auto", padding: 14, borderRadius: 14, border: "1px solid rgba(229,231,235,1)", background: "rgba(255,255,255,.6)", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ color: "#374151", fontSize: 13 }}>
            元素周期表（该 QE+EPW 库中出现过的元素将高亮） · 共 {elementsSet.size} 种
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

          <div
            ref={tableWrapRef}
            style={{ overflowX: "auto", overflowY: "auto", display: "flex", justifyContent: "center", paddingBottom: 4 }}
          >
            <div style={{ width: "fit-content", minWidth: 18 * 44 + 17 * GAP + 24, padding: "6px 10px" }}>
              <div style={gridStyle}>
                {ELEMENTS.map(renderElementCell)}
                <div style={{ gridColumn: "1 / span 3", gridRow: 8, ...lanActLabelStyle }}>Lanthanides →</div>
                <div style={{ gridColumn: "1 / span 3", gridRow: 9, ...lanActLabelStyle }}>Actinides →</div>
              </div>
            </div>
          </div>

          <div style={{ color: "#6b7280", fontSize: 12 }}>
            说明：QE 元素来自 runs.structure_json 的 ATOMIC_POSITIONS 解析结果。
          </div>
        </div>

        {/* Table */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
          <div style={{ color: "#374151", fontSize: 13, display: "flex", alignItems: "center", gap: 10 }}>
            <span>Runs 列表</span>
            <span style={{ color: "#6b7280", fontSize: 12 }}>
              {loadingColumns ? "列加载中…" : `已选 ${selectedColumns.length || defaultColumns.length} 列`}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 10, color: "#6b7280", fontSize: 12 }}>
            <button
              type="button"
              onClick={async () => {
                try {
                  if (!selectedDbKey && dbScope !== "upload") return;

                  const colsArr =
                    (selectedColumns && selectedColumns.length > 0)
                      ? selectedColumns
                      : (defaultColumns && defaultColumns.length > 0 ? defaultColumns : []);

                  const cols = colsArr.length ? `&columns=${encodeURIComponent(colsArr.join(","))}` : "";
                  const elems = (selectedElems && selectedElems.length) ? `&elems=${encodeURIComponent(selectedElems.join(","))}` : "";
                  const mode = `&elem_mode=${encodeURIComponent(elemMode || "at_least")}`;

                  const cp =
                    (cpFilters && cpFilters.length)
                      ? `&cp_filters=${encodeURIComponent(JSON.stringify(cpFilters))}`
                      : "";

                  const url =
                    `${API_BASE}/api/db/qe_epw/export?${dbParam}scope=${encodeURIComponent(normNow.scope)}` +
                    `${cols}${elems}${mode}${cp}`;

                  await downloadAuthedFile(url, "qe_epw_export.zip");
                } catch (e) {
                  alert(String(e?.message || e));
                }
              }}
              disabled={(!selectedDbKey && dbScope !== "upload") || (selectedDb && selectedDb.exists === false)}
              style={{
                height: 34,
                borderRadius: 10,
                padding: "0 10px",
                border: "1px solid rgba(209,213,219,1)",
                background: "white",
                cursor: (!selectedDbKey && dbScope !== "upload") ? "not-allowed" : "pointer",
              }}
            >
              导出
            </button>

            <button
              type="button"
              onClick={() => setShowColumnPicker((v) => !v)}
              disabled={(!selectedDbKey && dbScope !== "upload") || (selectedDb && selectedDb.exists === false) || loadingColumns || allColumns.length === 0}
              style={{
                height: 34,
                borderRadius: 10,
                padding: "0 10px",
                border: "1px solid rgba(209,213,219,1)",
                background: "white",
                cursor: (!selectedDbKey && dbScope !== "upload") ? "not-allowed" : "pointer",
              }}
            >
              选择列
            </button>

            <button
              type="button"
              onClick={() => setShowCpFilter((v) => !v)}
              disabled={(!selectedDbKey && dbScope !== "upload") || (selectedDb && selectedDb.exists === false)}
              style={{
                height: 34,
                borderRadius: 10,
                padding: "0 10px",
                border: "1px solid rgba(209,213,219,1)",
                background: showCpFilter ? "rgba(59,130,246,0.10)" : "white",
                cursor: (!selectedDbKey && dbScope !== "upload") ? "not-allowed" : "pointer",
              }}
              title="value 支持 JSON：如 0.00001 或 [2,3,1]"
            >
              输入参数筛选{cpFilters.length ? `（${cpFilters.length}）` : ""}
            </button>

            <button
              type="button"
              onClick={() => {
                setAddAllErr("");
                setAddAllJobId("");
                setAddAllProgress(null);
                setCustomTargetName(customTargets?.[0]?.name || "");
                setShowAddAllModal(true);
              }}
              disabled={customTargets.length === 0 || loadingTasks || ((!selectedDbKey && dbScope !== "upload") || (selectedDb && selectedDb.exists === false))}
              style={{
                height: 34,
                borderRadius: 10,
                padding: "0 10px",
                border: "1px solid rgba(209,213,219,1)",
                background: "white",
                cursor: (customTargets.length === 0 || loadingTasks) ? "not-allowed" : "pointer",
              }}
              title={customTargets.length === 0 ? "暂无自定义库（请先创建）" : (loadingTasks ? "列表更新中，请稍等" : "收藏当前筛选结果的全部样本（所有页）")}
            >
              全部收藏
            </button>

            <span>共 <b style={{ color: "#111827" }}>{tasksTotal}</b> 条</span>
            <span>页码 {tasksPage}</span>
          </div>
        </div>

        {/* ✅ Columns picker（放在“选择列”按钮下方） */}
        {showColumnPicker ? (
          <div style={{ padding: 12, borderRadius: 12, border: "1px solid rgba(229,231,235,1)", background: "rgba(255,255,255,.75)" }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
              <button
                type="button"
                onClick={() => { setTasksPage(1); setSelectedColumns(defaultColumns); }}
                style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
              >
                恢复默认列
              </button>

              <button
                type="button"
                onClick={() => { setTasksPage(1); setSelectedColumns(allColumns); }}
                style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
              >
                全选
              </button>

              <button
                type="button"
                onClick={() => { setTasksPage(1); setSelectedColumns([]); }}
                style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
              >
                清空
              </button>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
              {allColumns.map((col) => {
                const checked = selectedColumns.includes(col);
                return (
                  <label key={col} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "#374151" }}>
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
                    <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{col}</span>
                  </label>
                );
              })}
            </div>
          </div>
        ) : null}

        {/* ✅ 输入参数筛选面板（对齐 VASP：常用/预设/保存/默认/删除 + datalist） */}
        {showCpFilter ? (
          <div style={{ padding: 12, borderRadius: 12, border: "1px solid rgba(229,231,235,1)", background: "rgba(255,255,255,.75)" }}>
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10, flexWrap: "wrap" }}>
              <button
                type="button"
                onClick={() => {
                  setTasksPage(1);

                  const rows = (cpDraft || [])
                    .map((x) => ({
                      path: String(x.path || "").trim(),
                      op: String(x.op || "eq").trim().toLowerCase(),
                      value: parseCpValue(x.valueText),
                      valueText: String(x.valueText ?? "").trim(),
                    }))
                    .filter((x) => x.path && x.valueText !== ""); // 空值不参与

                  // ✅ 合并同 path 的多个 eq 条件 -> in
                  // 例：calc_type=epw2 + calc_type=epw3 => {path:"calc_type", op:"in", value:["epw2","epw3"]}
                  const map = new Map(); // key = `${op}|${path}`

                  for (const r of rows) {
                    const key = `${r.op}|${r.path}`;
                    if (!map.has(key)) map.set(key, []);
                    map.get(key).push(r.value);
                  }

                  const applied = [];
                  for (const [key, values] of map.entries()) {
                    const [op, path] = key.split("|");

                    // 只有 eq 才自动合并为 in；你后面扩展 gt/lt 时不会受影响
                    if (op === "eq" && values.length >= 2) {
                      // 去重（按 canon 前端简单去重：JSON.stringify）
                      const uniq = [];
                      const seen = new Set();
                      for (const v of values) {
                        const sig = JSON.stringify(v);
                        if (seen.has(sig)) continue;
                        seen.add(sig);
                        uniq.push(v);
                      }
                      applied.push({ path, op: "in", value: uniq });
                    } else {
                      // 单条：保持原样
                      applied.push({ path, op, value: values[0] });
                    }
                  }

                  setCpFilters(applied);
                }}
                style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white", cursor: "pointer" }}
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
                style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white", cursor: "pointer" }}
              >
                清空筛选
              </button>

              <button
                type="button"
                onClick={() => setCpDraft((prev) => [...prev, { path: "", op: "eq", valueText: "" }])}
                style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white", cursor: "pointer" }}
              >
                + 添加条件
              </button>

              <div style={{ color: "#6b7280", fontSize: 12 }}>
                value 支持 JSON：<b>0.00001</b> / <b>[2,3,1]</b>；mobility 支持：<b>mobility.electron.mu_x_cm2Vs@300K</b>
              </div>
            </div>

            {/* 常用 chips（对齐 VASP） */}
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
              <div style={{ color: "#6b7280", fontSize: 12 }}>常用：</div>
              {QE_CP_CATALOG.map((it) => (
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

            {/* 预设（对齐 VASP） */}
            <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
              <div style={{ color: "#6b7280", fontSize: 12 }}>预设：</div>

              <select
                value={selectedPresetName}
                onChange={(e) => {
                  const name = e.target.value;
                  setSelectedPresetName(name);
                  const p = cpPresets.find((x) => x?.name === name);
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
                  const next = [...cpPresets.filter((x) => x.name !== name), newPreset];
                  saveCpPresets(next, selectedPresetName);
                }}
                style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white", cursor: "pointer" }}
              >
                保存为预设
              </button>

              <button
                type="button"
                  onClick={() => {
                    if (!selectedPresetName) return;
                    try {
                      savePresetState(
                        getQePresetStorageKey(normNow.scope, normNow.dbKey || ""),
                        cpPresets,
                        selectedPresetName
                      );
                    } catch {}
                  }}
                disabled={!selectedPresetName}
                style={{
                  height: 32,
                  borderRadius: 10,
                  padding: "0 10px",
                  border: "1px solid rgba(209,213,219,1)",
                  background: "white",
                  cursor: !selectedPresetName ? "not-allowed" : "pointer",
                  opacity: !selectedPresetName ? 0.6 : 1,
                }}
              >
                设为默认
              </button>

              <button
                type="button"
                onClick={() => {
                  if (!selectedPresetName) return;
                  const next = cpPresets.filter((x) => x.name !== selectedPresetName);
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
                  cursor: !selectedPresetName ? "not-allowed" : "pointer",
                  opacity: !selectedPresetName ? 0.6 : 1,
                }}
              >
                删除预设
              </button>
            </div>

            {/* datalist：path 下拉 */}
            <datalist id="qe-cp-path-list">
              {cpPathOptions.map((p) => (
                <option key={p} value={p} />
              ))}
            </datalist>

            {(cpDraft || []).map((f, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 2fr auto", gap: 8, marginBottom: 8 }}>
                <input
                  value={f.path}
                  list="qe-cp-path-list"
                  onChange={(e) => setCpDraft((prev) => prev.map((x, idx) => idx === i ? { ...x, path: e.target.value } : x))}
                  placeholder="输入/选择 path，例如 calc_type / epw_params.nk / mobility.electron.mu_x_cm2Vs@300K"
                  style={{ height: 34, borderRadius: 10, border: "1px solid rgba(209,213,219,1)", padding: "0 10px" }}
                />

                <select
                  value={f.op}
                  onChange={(e) => setCpDraft((prev) => prev.map((x, idx) => idx === i ? { ...x, op: e.target.value } : x))}
                  style={{ height: 34, borderRadius: 10, border: "1px solid rgba(209,213,219,1)", padding: "0 10px", background: "white" }}
                >
                  <option value="eq">=</option>
                </select>

                <input
                  value={f.valueText}
                  onChange={(e) => setCpDraft((prev) => prev.map((x, idx) => idx === i ? { ...x, valueText: e.target.value } : x))}
                  placeholder='value，例如 "scf" / 16 / [2,3,1]'
                  style={{ height: 34, borderRadius: 10, border: "1px solid rgba(209,213,219,1)", padding: "0 10px" }}
                />

                <button
                  type="button"
                  onClick={() => setCpDraft((prev) => prev.filter((_, idx) => idx !== i))}
                  style={{ height: 34, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white", cursor: "pointer" }}
                  title="删除该条件"
                >
                  删除
                </button>
              </div>
            ))}
          </div>
        ) : null}

        {/* Runs table body */}
        <div
          className="glass-card"
          style={{
            position: "relative",
            padding: 12,
            borderRadius: 14,
            border: "1px solid rgba(229,231,235,1)",
            background: "rgba(255,255,255,.6)",
            overflowX: "auto",
          }}
        >
          {loadingTasks ? <CenterLoadingOverlay text="加载 runs 列表…" /> : null}

          <table style={{ width: "100%", borderCollapse: "collapse", background: "rgba(255,255,255,.75)" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid rgba(229,231,235,1)" }}>
                {/* 数据列 */}
                {((selectedColumns && selectedColumns.length > 0 ? selectedColumns : defaultColumns) || []).map((c) => (
                  <th
                    key={c}
                    style={{ padding: "10px 8px", fontSize: 12, color: "#374151", whiteSpace: "nowrap" }}
                    title={c}
                  >
                    {c}
                  </th>
                ))}

                {/* 操作列（放最后） */}
                <th style={{ padding: "10px 8px", fontSize: 12, color: "#374151", whiteSpace: "nowrap" }}>
                  操作
                </th>
              </tr>
            </thead>

            <tbody>
              {loadingTasks && !tasksLoadedOnce ? (
                <tr>
                  <td
                    colSpan={(((selectedColumns && selectedColumns.length > 0 ? selectedColumns : defaultColumns) || []).length + 1)}
                    style={{ padding: 14, fontSize: 13, color: "#6b7280" }}
                  >
                    正在加载，请不要重复点击和刷新界面…
                  </td>
                </tr>
              ) : (!tasks || tasks.length === 0) ? (
                <tr>
                  <td
                    colSpan={(((selectedColumns && selectedColumns.length > 0 ? selectedColumns : defaultColumns) || []).length + 1)}
                    style={{ padding: 14, fontSize: 13, color: "#6b7280" }}
                  >
                    当前页无数据（共 {tasksTotal} 条）。
                  </td>
                </tr>
              ) : (
                (tasks || []).map((row, idx) => (
                  <tr key={`${row?._dbKey || "db"}:${row?._rowId || idx}`} style={{ borderBottom: "1px solid rgba(243,244,246,1)" }}>
                    {((selectedColumns && selectedColumns.length > 0 ? selectedColumns : defaultColumns) || []).map((c) => {
                      const v = row?.[c];

                      // ✅ 识别“id 列”（兼容 3 种）
                      const isIdCol = c === "_rowId" || c === "row_id" || c === "id";

                      if (isIdCol) {
                        const rid = row?._rowId ?? row?.row_id ?? row?.id ?? v;
                        const dbk = row?._dbKey;

                        // 没有必要字段就退化为普通文本
                        if (!rid || !dbk) {
                          return (
                            <td
                              key={c}
                              style={{
                                padding: "10px 8px",
                                fontSize: 12,
                                color: "#111827",
                                whiteSpace: "nowrap",
                                maxWidth: 320,
                                overflow: "hidden",
                                textOverflow: "ellipsis",
                              }}
                              title={renderCellValue(rid)}
                            >
                              {renderCellValue(rid)}
                            </td>
                          );
                        }

                        // ✅ 路由用 qe-epw（和你 App.jsx 的 /dashboard/db/personal/qe-epw 对齐）
                        const to = `/dashboard/db/qe-epw/task/${encodeURIComponent(dbk)}/${encodeURIComponent(String(rid))}`;

                        return (
                          <td key={c} style={{ padding: "10px 8px", fontSize: 12, whiteSpace: "nowrap" }}>
                            <Link
                              to={to}
                              state={{
                                backTo: `${location.pathname}${location.search}`,
                                fromRow: {
                                  structure: row?.structure ?? row?.["structure"] ?? null,
                                  nat: row?.["structure.nat"] ?? null,
                                  ntyp: row?.["structure.ntyp"] ?? null,
                                },
                              }}
                              style={{
                                color: "#2563eb",
                                textUnderlineOffset: 2,
                                fontWeight: 800,
                              }}
                              title="打开任务详情（支持新标签页）"
                            >
                              {String(rid)}
                            </Link>
                          </td>
                        );
                      }

                      // 其它列：保持原样
                      return (
                        <td
                          key={c}
                          style={{
                            padding: "10px 8px",
                            fontSize: 12,
                            color: "#111827",
                            whiteSpace: "nowrap",
                            maxWidth: 320,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                          }}
                          title={renderCellValue(v)}
                        >
                          {renderCellValue(v)}
                        </td>
                      );
                    })}

                    <td style={{ padding: "10px 8px", whiteSpace: "nowrap", display: "flex", gap: 8 }}>
                      <button
                        type="button"
                        onClick={() => openCalcParams(row)}
                        style={{
                          height: 28,
                          borderRadius: 8,
                          padding: "0 10px",
                          border: "1px solid rgba(209,213,219,1)",
                          background: "white",
                          cursor: "pointer",
                          fontSize: 12,
                        }}
                      >
                        详情
                      </button>

                      <button
                        type="button"
                        onClick={() => openAddToCustom(row)}
                        disabled={customTargets.length === 0}
                        title={customTargets.length === 0 ? "暂无自定义库（请先创建）" : "收藏到自定义库"}
                        style={{
                          height: 28,
                          borderRadius: 8,
                          padding: "0 10px",
                          border: "1px solid rgba(209,213,219,1)",
                          background: "white",
                          cursor: customTargets.length === 0 ? "not-allowed" : "pointer",
                          fontSize: 12,
                          opacity: customTargets.length === 0 ? 0.6 : 1,
                        }}
                      >
                        收藏
                      </button>

                      {/* ✅ 只在自定义数据库时显示“移除” */}
                      {dbScope === "custom" && String(selectedDbKey || "").startsWith("custom_qe_epw:") ? (
                        <button
                          type="button"
                          onClick={() => handleRemoveFromCustom(row)}
                          disabled={removingRowId === row?._rowId}
                          title="从当前自定义库移除（不影响个人/上传库）"
                          style={{
                            height: 28,
                            borderRadius: 8,
                            padding: "0 10px",
                            border: "1px solid rgba(239,68,68,0.55)",
                            background: removingRowId === row?._rowId ? "rgba(243,244,246,1)" : "rgba(254,242,242,1)",
                            color: removingRowId === row?._rowId ? "#6b7280" : "#991b1b",
                            cursor: removingRowId === row?._rowId ? "not-allowed" : "pointer",
                            fontSize: 12,
                            fontWeight: 800,
                          }}
                        >
                          {removingRowId === row?._rowId ? "移除中…" : "移除"}
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {/* ✅ 分页控件：放在 Runs 表格右下角 */}
          <div
            style={{
              marginTop: 10,
              display: "flex",
              justifyContent: "flex-end",
              alignItems: "center",
              gap: 10,
            }}
          >
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
                <option value={10}>10</option>
                <option value={20}>20</option>
                <option value={50}>50</option>
              </select>
            </div>

            <button
              type="button"
              onClick={() => setTasksPage(1)}
              disabled={tasksPage <= 1}
              style={pagerBtnStyle(tasksPage <= 1)}
            >
              首页
            </button>

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

            <button
              type="button"
              onClick={() => setTasksPage(totalPages)}
              disabled={tasksPage >= totalPages}
              style={pagerBtnStyle(tasksPage >= totalPages)}
            >
              尾页
            </button>

            <div style={{ color: "#6b7280", fontSize: 12, marginLeft: 6 }}>
              第 {tasksPage} / {totalPages} 页
            </div>
          </div>
      </div>

      {/* Detail modal */}
      {showParamModal ? (
        <div
          onClick={() => setShowParamModal(false)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)", display: "flex", alignItems: "center", justifyContent: "center", padding: 18, zIndex: 9999 }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{ width: "min(980px, 96vw)", maxHeight: "85vh", overflow: "auto", borderRadius: 14, background: "white", border: "1px solid rgba(229,231,235,1)", padding: 14 }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
              <div style={{ fontSize: 14, fontWeight: 800, color: "#111827" }}>{paramModalTitle}</div>

              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <button
                  type="button"
                  onClick={() => setShowDetailFieldPicker((v) => !v)}
                  style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white", cursor: "pointer" }}
                  disabled={loadingParams || !!paramsError}
                  title="勾选决定详情里显示哪些字段"
                >
                  选择字段
                </button>

                <button
                  type="button"
                  onClick={() => setShowParamModal(false)}
                  style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white", cursor: "pointer" }}
                >
                  关闭
                </button>
              </div>
            </div>

            {loadingParams ? (
              <div style={{ marginTop: 10, color: "#6b7280", fontSize: 13 }}>加载中…</div>
            ) : paramsError ? (
              <div style={{ marginTop: 10, color: "#991b1b", fontSize: 13 }}>{paramsError}</div>
            ) : paramItems.length === 0 ? (
              <div style={{ marginTop: 10, color: "#6b7280", fontSize: 13 }}>无详情数据。</div>
            ) : (
              <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 12 }}>
                {/* 详情字段选择面板 */}
                {showDetailFieldPicker ? (
                  <div style={{ padding: 12, borderRadius: 12, border: "1px solid rgba(229,231,235,1)", background: "rgba(249,250,251,1)" }}>
                    <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
                      <button
                        type="button"
                        onClick={() => setSelectedDetailFields(defaultDetailFields)}
                        style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
                      >
                        恢复默认
                      </button>

                      <button
                        type="button"
                        onClick={() => setSelectedDetailFields(allDetailFields)}
                        style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
                      >
                        全选
                      </button>

                      <button
                        type="button"
                        onClick={() => setSelectedDetailFields([])}
                        style={{ height: 32, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
                      >
                        清空
                      </button>

                      <div style={{ fontSize: 12, color: "#6b7280" }}>
                        已选 {selectedDetailFields.length} / {allDetailFields.length}
                      </div>
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 8 }}>
                      {allDetailFields.map((col) => {
                        const checked = selectedDetailFields.includes(col);
                        return (
                          <label key={col} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "#374151" }}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => {
                                setSelectedDetailFields((prev) => {
                                  const s = new Set(prev);
                                  if (s.has(col)) s.delete(col);
                                  else s.add(col);
                                  return Array.from(s);
                                });
                              }}
                            />
                            <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{col}</span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ) : null}

                {/* 详情卡片（按勾选过滤） */}
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 10 }}>
                  {(selectedDetailFields && selectedDetailFields.length > 0
                    ? paramItems.filter(({ k }) => selectedDetailFields.includes(k))
                    : paramItems
                  ).map(({ k, v }) => (
                    <div key={k} style={{ border: "1px solid rgba(229,231,235,1)", borderRadius: 12, padding: 10, background: "rgba(249,250,251,1)" }}>
                      <div style={{ fontSize: 12, color: "#374151", fontWeight: 700, wordBreak: "break-word" }}>{k}</div>
                      <div style={{ marginTop: 6, fontSize: 12, color: "#111827", wordBreak: "break-word" }}>{v}</div>
                    </div>
                  ))}
                </div>

                {/* Mobility（拆开成表格） */}
                {mobilityRows && mobilityRows.length > 0 ? (
                  <div style={{ border: "1px solid rgba(229,231,235,1)", borderRadius: 12, padding: 12, background: "rgba(255,255,255,1)" }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                      <div style={{ fontSize: 13, fontWeight: 800, color: "#111827" }}>Mobility（拆分展示）</div>

                      <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                        <button
                          type="button"
                          onClick={() => setShowMobilityColPicker((v) => !v)}
                          style={{ height: 30, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white", cursor: "pointer", fontSize: 12 }}
                        >
                          选择列
                        </button>
                        <div style={{ fontSize: 12, color: "#6b7280" }}>
                          行数：{mobilityRows.length}
                        </div>
                      </div>
                    </div>

                    {showMobilityColPicker ? (
                      <div style={{ marginTop: 10, padding: 12, borderRadius: 12, border: "1px solid rgba(229,231,235,1)", background: "rgba(249,250,251,1)" }}>
                        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 10 }}>
                          <button
                            type="button"
                            onClick={() => setMobilitySelectedCols(mobilityAllCols)}
                            style={{ height: 30, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
                          >
                            全选
                          </button>
                          <button
                            type="button"
                            onClick={() => setMobilitySelectedCols([])}
                            style={{ height: 30, borderRadius: 10, padding: "0 10px", border: "1px solid rgba(209,213,219,1)", background: "white" }}
                          >
                            清空
                          </button>
                          <div style={{ fontSize: 12, color: "#6b7280" }}>
                            已选 {mobilitySelectedCols.length} / {mobilityAllCols.length}
                          </div>
                        </div>

                        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 8 }}>
                          {mobilityAllCols.map((c) => {
                            const checked = mobilitySelectedCols.includes(c);
                            return (
                              <label key={c} style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 12, color: "#374151" }}>
                                <input
                                  type="checkbox"
                                  checked={checked}
                                  onChange={() => {
                                    setMobilitySelectedCols((prev) => {
                                      const s = new Set(prev);
                                      if (s.has(c)) s.delete(c);
                                      else s.add(c);
                                      return Array.from(s);
                                    });
                                  }}
                                />
                                <span style={{ whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c}</span>
                              </label>
                            );
                          })}
                        </div>
                      </div>
                    ) : null}

                    <div style={{ marginTop: 10, overflowX: "auto" }}>
                      <table style={{ width: "100%", borderCollapse: "collapse", background: "rgba(255,255,255,.75)", borderRadius: 12 }}>
                        <thead>
                          <tr style={{ textAlign: "left", borderBottom: "1px solid rgba(229,231,235,1)" }}>
                            {(mobilitySelectedCols && mobilitySelectedCols.length > 0 ? mobilitySelectedCols : mobilityAllCols.slice(0, 8)).map((c) => (
                              <th key={c} style={{ padding: "8px 8px", fontSize: 12, color: "#374151", whiteSpace: "nowrap" }}>{c}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {mobilityRows.map((r, idx) => (
                            <tr key={r?.id || idx} style={{ borderBottom: "1px solid rgba(243,244,246,1)" }}>
                              {(mobilitySelectedCols && mobilitySelectedCols.length > 0 ? mobilitySelectedCols : mobilityAllCols.slice(0, 8)).map((c) => (
                                <td key={c} style={{ padding: "8px 8px", fontSize: 12, color: "#111827", whiteSpace: "nowrap" }}>
                                  {(() => {
                                    const v = r?.[c];
                                    if (v === null || v === undefined) return "-";
                                    if (typeof v === "object") return JSON.stringify(v);
                                    return String(v);
                                  })()}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                ) : null}
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
              <div style={{ fontSize: 14, fontWeight: 900, color: "#111827" }}>上传 QE+EPW 文件</div>
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

            <div style={{ marginTop: 10, display: "grid", gridTemplateColumns: "1fr", gap: 10 }}>
              <div
                style={{
                  border: "1px solid rgba(229,231,235,1)",
                  background: "rgba(239,246,255,1)",
                  borderRadius: 12,
                  padding: 12,
                }}
              >
                <div style={{ fontWeight: 900, color: "#1d4ed8", marginBottom: 6 }}>说明</div>
                <div style={{ fontSize: 13, color: "#374151", lineHeight: 1.7 }}>
                  你可以一次上传多个文件。系统会把文件永久保存到服务器目录，并且：
                  <br />
                  - 如果文件中包含一个可用的 QE/EPW sqlite（带 <code>runs</code> 表，后缀 .sqlite 或 .db），会自动注册成“上传库”，上传后你就能在数据库下拉框里直接选择它。
                  <br />
                  - 如果没有检测到可用 sqlite，也会保存文件（便于后续排查/补传）。
                  <br />
                  - 上传文件包括： QE 输出文件：scf.out/bands.out/ph.out/matdyn.out/q2r.out; EPW 输出文件：epw.out。但建议同时上传输入文件                 
                  <br />
                  - 上传的文件不会被其他用户访问到，请放心上传你的数据文件。
                </div>
              </div>
            </div>

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
                  background: uploading ? "rgba(243,244,246,1)" : "rgba(37,99,235,1)",
                  color: uploading ? "#6b7280" : "white",
                  fontWeight: 900,
                  cursor: uploading ? "not-allowed" : "pointer",
                }}
              >
                选择文件
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
                onClick={() => setSelectedUploadFiles([])}
                disabled={uploading}
                style={{
                  height: 36,
                  borderRadius: 12,
                  padding: "0 14px",
                  border: "1px solid rgba(209,213,219,1)",
                  background: uploading ? "rgba(243,244,246,1)" : "white",
                  color: uploading ? "#9ca3af" : "#111827",
                  cursor: uploading ? "not-allowed" : "pointer",
                }}
              >
                清空选择
              </button>

              <button
                type="button"
                disabled={uploading}
                onClick={async () => {
                  try {
                    if (!selectedUploadFiles.length) {
                      alert("请先选择文件");
                      return;
                    }

                    setUploading(true);
                    const resp = await uploadFiles(`${API_BASE}/api/db/qe_epw/upload_qe_epw_files`, selectedUploadFiles);

                    setShowUploadModal(false);
                    setSelectedUploadFiles([]);

                    // ✅ 上传成功后切到 upload scope，并优先选中 upload_db_key（如果后端识别出了可用 sqlite）
                    setDbScope("upload");
                    setDbListNonce((n) => n + 1); // ✅ 强制重新拉 /available?scope=upload
                    // ✅ 默认选“上传库（合并）”
                    setSelectedDbKey(UPLOAD_MERGED_KEY);
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
                  background: uploading ? "rgba(243,244,246,1)" : "rgba(37,99,235,1)",
                  color: uploading ? "#6b7280" : "white",
                  fontWeight: 900,
                  cursor: uploading ? "not-allowed" : "pointer",
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
            <div style={{ fontSize: 14, fontWeight: 900, color: "#111827" }}>收藏到 QE+EPW 自定义库</div>
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
              disabled={addingToCustom || customTargets.length === 0}
              style={{ height: 36, borderRadius: 10, border: "1px solid #d1d5db", padding: "0 10px", background: "white", width: "100%" }}
            >
              {customTargets.length === 0 ? (
                <option value="">暂无自定义库（请先在入口创建）</option>
              ) : (
                customTargets.map((x) => (
                  <option key={x.key} value={x.name || x.safe_name}>
                    {x.name || x.safe_name}
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

                    const { resp, data } = await postJson(`${API_BASE}/api/db/qe_epw/custom/add`, body);

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

                  // ✅ 成功（后端会返回 message/status）
                  setShowAddToCustomModal(false);
                  const msg = (data && typeof data === "object") ? data.message : "";
                  alert(msg || "收藏成功");
                } catch (e) {
                  setAddCustomErr("收藏失败：" + String(e?.message || e));
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
            说明：将按你当前筛选条件（元素 / 模式）把“所有页”的结果批量收藏到指定自定义库。
          </div>

          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 12, color:"#374151", fontWeight: 700, marginBottom: 6 }}>选择目标自定义库</div>
            <select
              value={customTargetName}
              onChange={(e) => setCustomTargetName(e.target.value)}
              disabled={addingAll || customTargets.length === 0}
              style={{ height: 36, borderRadius: 10, border: "1px solid #d1d5db", padding: "0 10px", background: "white", width: "100%" }}
            >
              {customTargets.length === 0 ? (
                <option value="">暂无自定义库（请先创建）</option>
              ) : (
                customTargets.map((x) => (
                  <option key={x.key} value={x.name || x.safe_name}>
                    {x.name || x.safe_name}
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
              disabled={addingAll || !customTargetName}
              onClick={async () => {
                try {
                  setAddAllErr("");
                  setAddingAll(true);
                  setAddAllJobId("");
                  setAddAllProgress(null);

                  const isCustomScope = (dbScope === "custom");
                  const isCustomDbKey = String(selectedDbKey || "").startsWith("custom_qe_epw:");

                  const body = {
                    target: customTargetName,
                    scope: normNow.scope,

                    // ✅ custom 合并：scope=custom 且没选具体 custom db → db 传 null
                    db: (normNow.scope === "custom" && !String(normNow.dbKey || "").startsWith("custom_qe_epw:"))
                      ? null
                      : (normNow.dbKey || null),

                    elems: selectedElems.length ? selectedElems.join(",") : null,
                    elem_mode: elemMode,

                    // ✅ 新增：输入参数筛选（与 /tasks 一致）
                    cp_filters: (cpFilters && cpFilters.length) ? JSON.stringify(cpFilters) : null,

                    max_rows: 0,
                  };

                  // 1) 启动后台任务
                  const { resp, data } = await postJson(`${API_BASE}/api/db/qe_epw/custom/add_all_async`, body);
                  if (!resp.ok) {
                    const detail = getPostJsonErrorDetail(resp, data);
                    throw new Error(detail || `启动任务失败（${resp.status}）`);
                  }

                  const jobId = data?.job_id;
                  if (!jobId) throw new Error("未获取到 job_id");
                  setAddAllJobId(jobId);

                  // 2) 轮询
                  stopAddAllPoll();
                  addAllPollRef.current = setInterval(async () => {
                    try {
                      const st = await fetchJson(`${API_BASE}/api/db/qe_epw/custom/add_all_status/${encodeURIComponent(jobId)}`);
                      const state = st?.state;
                      const meta = st?.meta;
                      const result = st?.result;
                      const error = st?.error;

                      if (meta && typeof meta === "object") setAddAllProgress(meta);

                      if (state === "SUCCESS") {
                        stopAddAllPoll();
                        setAddingAll(false);
                        setShowAddAllModal(false);
                        alert(result?.message || "全部收藏完成");

                        // ✅ 触发刷新列表
                        setTasksPage(1);
                        setDbListNonce((n) => n + 1);
                      }

                      if (state === "FAILURE") {
                        stopAddAllPoll();
                        setAddingAll(false);
                        setAddAllErr("后台任务失败：" + String(error || "unknown"));
                      }
                    } catch (e) {
                      console.error("poll qe add_all_status failed:", e);
                    }
                  }, 800);
                } catch (e) {
                  setAddAllErr("全部收藏失败：" + String(e?.message || e));
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
