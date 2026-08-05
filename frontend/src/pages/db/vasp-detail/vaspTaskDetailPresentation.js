const TASK_FIELD_PRESENTATION = {
  id: { label: '记录 ID', decimals: 0 },
  formula: { label: '化学式' },
  energy: { label: '总能量', unit: 'eV', decimals: 6 },
  fmax: { label: '最大力', unit: 'eV/Å', decimals: 4 },
  natoms: { label: '原子数', decimals: 0 },
  pbc: { label: '周期边界' },
  spacegroup: { label: '空间群' },
  bandgap_eV: { label: '带隙', unit: 'eV', decimals: 4 },
  vbm_eV: { label: 'VBM', unit: 'eV', decimals: 4 },
  cbm_eV: { label: 'CBM', unit: 'eV', decimals: 4 },
};

export function getTaskFieldPresentation(key) {
  return { key, ...(TASK_FIELD_PRESENTATION[key] || { label: key }) };
}

export function formatTaskValue(key, value) {
  const presentation = getTaskFieldPresentation(key);
  if (value === null || value === undefined || value === '') {
    return { display: '-', raw: '' };
  }
  if (key === 'pbc' && Array.isArray(value)) {
    return {
      display: value.map((item) => (item ? 'T' : 'F')).join(''),
      raw: JSON.stringify(value),
    };
  }
  if (typeof value === 'number' && Number.isFinite(value) && Number.isInteger(presentation.decimals)) {
    return { display: value.toFixed(presentation.decimals), raw: String(value) };
  }
  if (typeof value === 'object') {
    const raw = JSON.stringify(value);
    return { display: raw, raw };
  }
  return { display: String(value), raw: String(value) };
}
