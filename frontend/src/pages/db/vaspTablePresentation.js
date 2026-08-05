const DEFAULT_PRESENTATION = {
  id: { label: '记录 ID', kind: 'integer', priority: 1 },
  formula: { label: '化学式', kind: 'text', priority: 1 },
  energy: { label: '总能量', unit: 'eV', decimals: 6, kind: 'number', priority: 1 },
  natoms: { label: '原子数', kind: 'integer', priority: 2 },
  fmax: { label: '最大力', unit: 'eV/Å', decimals: 4, kind: 'number', priority: 1 },
  pbc: { label: '周期边界', kind: 'text', priority: 3 },
  'data.phys_spacegroup_international': { label: '空间群', kind: 'text', priority: 2 },
  'data.phys_bandgap_eV': { label: '带隙', unit: 'eV', decimals: 4, kind: 'number', priority: 1 },
  'data.phys_vbm_eV': { label: 'VBM', unit: 'eV', decimals: 4, kind: 'number', priority: 3 },
  'data.phys_cbm_eV': { label: 'CBM', unit: 'eV', decimals: 4, kind: 'number', priority: 3 },
  'data.source_dir': { label: '计算目录', kind: 'path', priority: 1 },
  'data.step_index': { label: '离子步', kind: 'integer', priority: 2 },
};

function fallbackLabel(key) {
  const leaf = String(key).split('.').at(-1)?.replaceAll('_', ' ').trim();
  return leaf ? `${leaf[0].toUpperCase()}${leaf.slice(1)}` : String(key);
}

export function getVaspColumnPresentation(key, backendMetadata = {}) {
  const fromBackend = backendMetadata?.[key] || {};
  return {
    key,
    ...(DEFAULT_PRESENTATION[key] || {
      label: fallbackLabel(key),
      kind: key.startsWith('calculator_parameters.') ? 'json' : 'text',
      priority: 4,
    }),
    ...fromBackend,
  };
}

export function compactSourcePath(value, segments = 3) {
  const raw = String(value || '');
  const parts = raw.split('/').filter(Boolean);
  if (parts.length <= segments) return raw;
  return `.../${parts.slice(-segments).join('/')}`;
}

export function formatVaspValue(key, value, backendMetadata = {}) {
  if (value === null || value === undefined || value === '') {
    return { display: '-', raw: '' };
  }

  const meta = getVaspColumnPresentation(key, backendMetadata);
  const raw = typeof value === 'object' ? JSON.stringify(value) : String(value);

  if (meta.kind === 'path') {
    return { display: compactSourcePath(raw), raw };
  }
  if (meta.kind === 'integer' && Number.isFinite(Number(value))) {
    return { display: String(Math.trunc(Number(value))), raw };
  }
  if (meta.kind === 'number' && Number.isFinite(Number(value))) {
    const numeric = Number(value);
    const decimals = Number.isInteger(meta.decimals) ? meta.decimals : 6;
    return { display: numeric.toFixed(decimals), raw };
  }
  return { display: raw, raw };
}
