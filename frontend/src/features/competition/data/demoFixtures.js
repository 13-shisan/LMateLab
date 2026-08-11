const DATA_KIND = 'demo';

function markDemoCollection(collection) {
  Object.defineProperty(collection, 'data_kind', {
    value: DATA_KIND,
    enumerable: false,
  });
  return collection;
}

const STEP_LABELS = {
  relax: '结构优化',
  scf: '自洽计算',
  band: '能带',
  dos: '态密度',
};

const SLURM_STATES = {
  succeeded: 'COMPLETED',
  running: 'RUNNING',
  failed: 'FAILED',
};

function createStep(key, status, jobId = null, overrides = {}) {
  return {
    key,
    label: STEP_LABELS[key],
    status,
    job_id: jobId,
    attempt: jobId ? 1 : null,
    attempt_dir: jobId ? `attempt-1/${key}` : null,
    slurm_state: SLURM_STATES[status] || null,
    exit_code: status === 'succeeded' ? '0:0' : status === 'failed' ? '1:0' : null,
    accepted: status === 'succeeded',
    data_kind: DATA_KIND,
    ...overrides,
  };
}

export const DEMO_STRUCTURE = {
  symbols: ['Mo', 'S', 'S'],
  positions: [[0, 0, 10], [1.579, 0.912, 11.568], [1.579, 0.912, 8.432]],
  cell: [[3.158, 0, 0], [-1.579, 2.735, 0], [0, 0, 20]],
  pbc: [true, true, false],
  data_kind: DATA_KIND,
};

const commonWorkflow = {
  material: 'MoS2',
  data_kind: DATA_KIND,
  creator: 'demo-operator',
  template_version: 'mos2-v1',
  release_commit: 'demo-preview',
};

export const DEMO_WORKFLOWS = markDemoCollection([
  {
    ...commonWorkflow,
    id: 'wf-demo-mos2-success',
    source: '内置单层 MoS2',
    status: 'succeeded',
    current_step: 'done',
    latest_job_id: 'DEMO-41004',
    input_sha256: 'demo-6b7340d4c85d',
    updated_at: '2026-08-10T09:40:00+08:00',
    steps: [
      createStep('relax', 'succeeded', 'DEMO-41001'),
      createStep('scf', 'succeeded', 'DEMO-41002'),
      createStep('band', 'succeeded', 'DEMO-41003'),
      createStep('dos', 'succeeded', 'DEMO-41004'),
    ],
  },
  {
    ...commonWorkflow,
    id: 'wf-demo-mos2-running',
    source: 'POSCAR 草稿示例',
    status: 'running',
    current_step: 'scf',
    latest_job_id: 'DEMO-41012',
    input_sha256: 'demo-73d80fe429da',
    updated_at: '2026-08-10T10:05:00+08:00',
    steps: [
      createStep('relax', 'succeeded', 'DEMO-41011'),
      createStep('scf', 'running', 'DEMO-41012'),
      createStep('band', 'waiting'),
      createStep('dos', 'waiting'),
    ],
  },
  {
    ...commonWorkflow,
    id: 'wf-demo-mos2-failed',
    source: '人为失败算例',
    status: 'failed',
    current_step: 'scf',
    latest_job_id: 'DEMO-41022',
    input_sha256: 'demo-2f91fbbe1327',
    updated_at: '2026-08-10T10:18:00+08:00',
    steps: [
      createStep('relax', 'succeeded', 'DEMO-41021'),
      createStep('scf', 'failed', 'DEMO-41022', {
        reason: '演示：电子步未收敛',
        accepted: false,
      }),
      createStep('band', 'blocked'),
      createStep('dos', 'blocked'),
    ],
  },
]);

const vaspDetail = {
  db: { dbname: '107 Cup Demo Database' },
  row: {
    id: 1,
    formula: 'MoS2',
    energy: -22.418731,
    fmax: 0.0062,
    natoms: 3,
    pbc: [true, true, false],
  },
  properties: {
    spacegroup: 'P-6m2',
    bandgap_eV: 1.78,
    vbm_eV: 0,
    cbm_eV: 1.78,
  },
  structure: DEMO_STRUCTURE,
  crystal: {
    lattice: {
      a: 3.158,
      b: 3.158,
      c: 20,
      alpha: 90,
      beta: 90,
      gamma: 120,
      volume: 172.75,
    },
    density_g_cm3: 0.873,
    dimensionality: 2,
    atomic_positions_frac: [
      { element: 'Mo', x: 0, y: 0, z: 0.5 },
      { element: 'S', x: 0.666667, y: 0.333333, z: 0.5784 },
      { element: 'S', x: 0.666667, y: 0.333333, z: 0.4216 },
    ],
  },
  capabilities: {
    structure_export: true,
    band_plot: true,
    dos_plot: true,
    band_data: true,
    dos_data: true,
  },
  data_kind: DATA_KIND,
};

const unavailableVaspDetail = {
  ...vaspDetail,
  capabilities: {
    structure_export: false,
    band_plot: false,
    dos_plot: false,
    band_data: false,
    dos_data: false,
  },
};

const [successfulWorkflow, runningWorkflow, failedWorkflow] = DEMO_WORKFLOWS;

export const DEMO_DASHBOARD = {
  data_kind: DATA_KIND,
  summary: {
    total: 3,
    running: 1,
    recent_succeeded: 1,
    needs_attention: 1,
  },
  recent_workflows: DEMO_WORKFLOWS,
  active_workflow: runningWorkflow,
  slurm: {
    partition: 'P107-RTX5090',
    state: '演示快照',
    queued: 1,
    running: 1,
    updated_at: '2026-08-10T10:20:00+08:00',
  },
};

export const DEMO_RESULTS_BY_ID = markDemoCollection({
  [successfulWorkflow.id]: {
    ...successfulWorkflow,
    vasp_detail: vaspDetail,
    artifacts: ['structure-cif', 'structure-poscar', 'band-data', 'dos-data', 'evidence-bundle'],
  },
  [failedWorkflow.id]: {
    ...failedWorkflow,
    vasp_detail: unavailableVaspDetail,
    failure_evidence: {
      step: 'scf',
      job_id: 'DEMO-41022',
      exit_code: '1:0',
      reason: '演示：电子步未收敛',
      expected_files: ['OUTCAR', 'vasprun.xml'],
      missing_files: ['vasprun.xml'],
      log_tail: ['DEMO LOG', 'electronic minimization did not converge'],
      data_kind: DATA_KIND,
    },
  },
});

export const DEMO_DATABASE_ROWS = markDemoCollection(DEMO_WORKFLOWS.map((workflow, index) => {
  const succeeded = workflow.status === 'succeeded';
  const id = `db-demo-${index + 1}`;
  return {
    id,
    _rowId: id,
    formula: 'MoS2',
    elements: ['Mo', 'S'],
    source: workflow.source,
    workflow_id: workflow.id,
    status: workflow.status,
    latest_job_id: workflow.latest_job_id,
    data_kind: DATA_KIND,
    bandgap_eV: 1.78,
    energy: -22.418731,
    completed_at: succeeded ? workflow.updated_at : null,
    vasp_detail: succeeded ? vaspDetail : unavailableVaspDetail,
  };
}));

export const DEMO_DATABASE_METADATA = markDemoCollection({
  source: { label: '来源', kind: 'text', priority: 1 },
  workflow_id: { label: '工作流', kind: 'text', priority: 1 },
  status: { label: '状态', kind: 'text', priority: 1 },
  bandgap_eV: { label: '带隙', unit: 'eV', decimals: 4, kind: 'number', priority: 1 },
  completed_at: { label: '完成时间', kind: 'text', priority: 2 },
});

export const DEMO_BAND_DATA = '# DEMO MoS2 band data\n# k_distance energy_eV\n0.0 -1.20\n0.5 -0.18\n1.0 0.00\n1.5 1.78\n';
export const DEMO_DOS_DATA = '# DEMO MoS2 DOS data\n# energy_eV dos\n-2.0 0.20\n-1.0 1.40\n0.0 0.00\n1.78 0.10\n2.5 1.20\n';
export const DEMO_POSCAR = 'DEMO MoS2\n1.0\n3.158 0 0\n-1.579 2.735 0\n0 0 20\nMo S\n1 2\nDirect\n0 0 0.5\n0.666667 0.333333 0.5784\n0.666667 0.333333 0.4216\n';
export const DEMO_CIF = 'data_DEMO_MoS2\n_cell_length_a 3.158\n_cell_length_b 3.158\n_cell_length_c 20.0\n_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 120\nloop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\nMo1 Mo 0 0 0.5\nS1 S 0.666667 0.333333 0.5784\nS2 S 0.666667 0.333333 0.4216\n';

export const DEMO_PLOTS = {
  band: '/competition-fixtures/mos2-band-demo.svg',
  dos: '/competition-fixtures/mos2-dos-demo.svg',
  data_kind: DATA_KIND,
};
