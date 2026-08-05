export function getVaspPresetStorageKey(dbKey) {
  return `vasp_cp_presets:${dbKey || "default"}`;
}

export function getQePresetStorageKey(scope, dbKey) {
  return `qe_epw_cp_presets:${String(scope || "all")}:${String(dbKey || "merged")}`;
}

export function loadPresetState(storageKey) {
  const raw = localStorage.getItem(storageKey);
  const obj = raw ? JSON.parse(raw) : null;

  return {
    presets: Array.isArray(obj?.presets) ? obj.presets : [],
    defaultPreset: typeof obj?.defaultPreset === "string" ? obj.defaultPreset : "",
  };
}

export function savePresetState(storageKey, presets, defaultPreset = "") {
  localStorage.setItem(
    storageKey,
    JSON.stringify({ presets, defaultPreset: defaultPreset || "" })
  );
}
