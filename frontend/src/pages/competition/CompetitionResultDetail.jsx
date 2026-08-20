import { useCallback, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Download } from 'lucide-react';

import {
  useCompetitionData,
  useCompetitionResource,
} from '../../features/competition/CompetitionDataContext';
import {
  CompetitionState,
  DemoDataBanner,
  StatusBadge,
} from '../../features/competition/components/CompetitionState';
import WorkflowTimeline from '../../features/competition/components/WorkflowTimeline';
import VaspCrystalDetails from '../db/vasp-detail/VaspCrystalDetails';
import VaspElectronicProperties from '../db/vasp-detail/VaspElectronicProperties';
import VaspStructureViewer from '../db/vasp-detail/VaspStructureViewer';
import VaspTaskSummary from '../db/vasp-detail/VaspTaskSummary';
import '../db/vasp-detail/VaspTaskDetail.css';
import './CompetitionPages.css';

const RESULT_ARTIFACT_KINDS = new Set([
  'structure-cif',
  'structure-poscar',
  'band-data',
  'dos-data',
  'evidence-bundle',
]);

function inferArtifactKind(path, filename) {
  const hasSuppliedFilename = filename !== undefined
    && filename !== null
    && String(filename).trim() !== '';
  const filenameLeaf = String(hasSuppliedFilename ? filename : path)
    .trim()
    .toLowerCase()
    .split(/[\\/]/)
    .pop()
    .split(/[?#]/)[0];
  if (filenameLeaf.endsWith('.cif')) return 'structure-cif';
  if (filenameLeaf.endsWith('.vasp') || /(?:^|[-_])poscar$/.test(filenameLeaf)) {
    return 'structure-poscar';
  }
  if (/(?:^|[-_])band(?:[-_]?data)?\.dat$/.test(filenameLeaf)) return 'band-data';
  if (/(?:^|[-_])dos(?:[-_]?data)?\.(?:dat|zip)$/.test(filenameLeaf)) return 'dos-data';
  if (/(?:^|[-_])evidence(?:[-_]?bundle)?\.json$/.test(filenameLeaf)) {
    return 'evidence-bundle';
  }
  if (hasSuppliedFilename) throw new Error('未知科学工件类型');

  const pathText = String(path).trim().toLowerCase();
  const queryStart = pathText.indexOf('?');
  const pathname = queryStart === -1 ? pathText : pathText.slice(0, queryStart);
  const query = queryStart === -1 ? '' : pathText.slice(queryStart + 1).split('#')[0];
  const terminal = pathname.split('/').filter(Boolean).pop() || '';
  const terminalKinds = {
    'band-data': 'band-data',
    'band-dat': 'band-data',
    'dos-data': 'dos-data',
    'dos-dat': 'dos-data',
    'structure-cif': 'structure-cif',
    'structure-poscar': 'structure-poscar',
    'evidence-bundle': 'evidence-bundle',
  };
  if (Object.hasOwn(terminalKinds, terminal)) return terminalKinds[terminal];
  if (terminal === 'export') {
    const format = new URLSearchParams(query).get('format');
    if (format === 'cif') return 'structure-cif';
    if (format === 'poscar') return 'structure-poscar';
  }
  throw new Error('未知科学工件类型');
}

function inferPlotKind(path) {
  const pathname = String(path).trim().toLowerCase().split(/[?#]/)[0];
  const terminal = pathname.split('/').filter(Boolean).pop() || '';
  if (terminal === 'band-plot') return 'band';
  if (terminal === 'dos-plot') return 'dos';
  throw new Error('未知科学图类型');
}

function requestScientificArtifact(provider, workflowId, path, filename) {
  const kind = inferArtifactKind(path, filename);
  return provider.downloadArtifact(workflowId, kind);
}

function requestScientificPlot(provider, workflowId, path) {
  const kind = inferPlotKind(path);
  return provider.loadPlot(workflowId, kind);
}

function normalizeResultDetailState(resource, workflowId) {
  const isPlainObject = (value) => {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
  };
  const hasText = (value) => typeof value === 'string' && value.trim() !== '';
  const isFiniteNumber = (value) => typeof value === 'number' && Number.isFinite(value);
  const isPbc = (value) => (
    Array.isArray(value)
    && value.length === 3
    && value.every((entry) => typeof entry === 'boolean')
  );
  const isVector = (value) => (
    Array.isArray(value)
    && value.length === 3
    && value.every(isFiniteNumber)
  );
  const emptyMessage = workflowId ? '未找到结果' : '缺少工作流 ID';
  const emptyState = {
    status: 'empty', message: emptyMessage, variant: null, result: null,
  };

  if (!isPlainObject(resource)) return emptyState;
  if (resource.status !== 'ready') {
    if (resource.status === 'empty') return emptyState;
    const status = ['loading', 'forbidden', 'parse-error', 'error'].includes(resource.status)
      ? resource.status
      : 'error';
    return {
      status,
      message: resource.error?.message,
      variant: null,
      result: null,
    };
  }

  const result = resource.data;
  if (!isPlainObject(result)) return emptyState;
  const resultWorkflowId = Object.hasOwn(result, 'workflow_id')
    ? result.workflow_id
    : result.id;
  const hasValidWorkflowId = typeof resultWorkflowId === 'string'
    && resultWorkflowId.trim() !== ''
    && resultWorkflowId === resultWorkflowId.trim();
  if (!hasValidWorkflowId) {
    return {
      status: 'parse-error', message: '结果身份无效', variant: null, result: null,
    };
  }
  if (resultWorkflowId !== workflowId) {
    return {
      status: 'parse-error', message: '结果身份不一致', variant: null, result: null,
    };
  }
  if (!['demo', 'live'].includes(result.data_kind)) {
    return {
      status: 'parse-error', message: '结果数据来源未验证', variant: null, result: null,
    };
  }
  if (['failed', 'parse-error'].includes(result.status)) {
    return { status: 'ready', message: undefined, variant: 'failure', result };
  }
  if (result.status !== 'succeeded') {
    return {
      status: 'parse-error', message: '结果状态不受支持', variant: null, result: null,
    };
  }

  const requiredStepKeys = ['relax', 'scf', 'band', 'dos'];
  const hasValidJobId = (value) => (
    (typeof value === 'string' && value.trim() !== '')
    || (Number.isInteger(value) && value > 0)
  );
  const acceptedStepsAreComplete = Array.isArray(result.steps)
    && result.steps.length === requiredStepKeys.length
    && result.steps.every(isPlainObject)
    && new Set(result.steps.map((step) => step.key)).size === requiredStepKeys.length
    && requiredStepKeys.every((key) => result.steps.some((step) => (
      step.key === key
      && step.status === 'succeeded'
      && step.accepted === true
      && hasValidJobId(step.job_id)
      && (step.exit_code === '0:0' || step.exit_code === 0)
    )));
  if (!acceptedStepsAreComplete) {
    return {
      status: 'parse-error', message: '结果验收合同不完整', variant: null, result: null,
    };
  }

  const detail = result.vasp_detail;
  const db = detail?.db;
  const row = detail?.row;
  const properties = detail?.properties;
  const structure = detail?.structure;
  const crystal = detail?.crystal;
  const lattice = crystal?.lattice;
  const capabilities = detail?.capabilities;
  const coordinateRows = crystal?.atomic_positions_frac;
  const dbIsComplete = isPlainObject(db) && hasText(db.dbname);
  const rowIsComplete = isPlainObject(row)
    && ((typeof row.id === 'number' && Number.isFinite(row.id)) || hasText(row.id))
    && hasText(row.formula)
    && ['energy', 'fmax'].every((key) => (
      Object.hasOwn(row, key) && (row[key] === null || isFiniteNumber(row[key]))
    ))
    && Number.isInteger(row.natoms)
    && row.natoms > 0
    && isPbc(row.pbc);
  const propertiesAreComplete = isPlainObject(properties)
    && Object.hasOwn(properties, 'spacegroup')
    && (properties.spacegroup === null || hasText(properties.spacegroup))
    && ['bandgap_eV', 'vbm_eV', 'cbm_eV'].every((key) => (
      Object.hasOwn(properties, key)
      && (properties[key] === null || isFiniteNumber(properties[key]))
    ));
  const structureIsComplete = isPlainObject(structure)
    && Array.isArray(structure.symbols)
    && structure.symbols.length > 0
    && structure.symbols.every(hasText)
    && Array.isArray(structure.positions)
    && structure.positions.length === structure.symbols.length
    && structure.positions.every(isVector)
    && Array.isArray(structure.cell)
    && structure.cell.length === 3
    && structure.cell.every(isVector)
    && isPbc(structure.pbc)
    && rowIsComplete
    && structure.symbols.length === row.natoms;
  const latticeIsComplete = isPlainObject(lattice)
    && ['a', 'b', 'c', 'alpha', 'beta', 'gamma', 'volume']
      .every((key) => isFiniteNumber(lattice[key]))
    && lattice.a > 0
    && lattice.b > 0
    && lattice.c > 0
    && lattice.volume > 0
    && [lattice.alpha, lattice.beta, lattice.gamma]
      .every((angle) => angle > 0 && angle <= 180);
  const coordinateRowsAreComplete = Array.isArray(coordinateRows)
    && rowIsComplete
    && coordinateRows.length === row.natoms
    && coordinateRows.every((position) => (
      isPlainObject(position)
      && hasText(position.element)
      && ['x', 'y', 'z'].every((key) => isFiniteNumber(position[key]))
    ));
  const crystalIsComplete = isPlainObject(crystal)
    && latticeIsComplete
    && isFiniteNumber(crystal.density_g_cm3)
    && crystal.density_g_cm3 > 0
    && Number.isInteger(crystal.dimensionality)
    && crystal.dimensionality >= 0
    && crystal.dimensionality <= 3
    && coordinateRowsAreComplete;
  const detailIsComplete = isPlainObject(detail)
    && dbIsComplete
    && rowIsComplete
    && propertiesAreComplete
    && structureIsComplete
    && crystalIsComplete
    && isPlainObject(capabilities)
    && ['structure_export', 'band_plot', 'dos_plot', 'band_data', 'dos_data']
      .every((key) => capabilities[key] === true);
  if (!detailIsComplete) {
    return {
      status: 'parse-error', message: '科学结果合同不完整', variant: null, result: null,
    };
  }
  return { status: 'ready', message: undefined, variant: 'success', result };
}

function displayIdentity(value) {
  if (typeof value === 'string' && value.trim() !== '') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'boolean') return String(value);
  return '-';
}

function normalizeResultSteps(steps) {
  const stepKeys = ['relax', 'scf', 'band', 'dos'];
  const measurementKeys = ['elapsed_wall_seconds', 'process_tree_peak_rss_kbytes'];
  const artifactNames = new Set([
    'OUTCAR', 'vasprun.xml', 'OSZICAR', 'CONTCAR', 'CHGCAR', 'WAVECAR', 'EIGENVAL', 'DOSCAR',
  ]);
  const statuses = new Set([
    'waiting', 'queued', 'running', 'succeeded', 'failed', 'blocked', 'stale',
    'parse-error', 'render-error',
  ]);
  const byKey = new Map();
  if (Array.isArray(steps)) {
    for (const step of steps) {
      if (step === null || typeof step !== 'object' || Array.isArray(step)) continue;
      if (!stepKeys.includes(step.key) || byKey.has(step.key)) continue;
      byKey.set(step.key, step);
    }
  }
  const normalizeScalar = (value) => {
    if (typeof value === 'string' && value.trim() !== '') return value;
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'boolean') return String(value);
    return null;
  };
  const normalizeResources = (value) => {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return {};
    return Object.fromEntries(measurementKeys.flatMap((key) => (
      typeof value[key] === 'number' && Number.isFinite(value[key]) && value[key] >= 0
        ? [[key, value[key]]]
        : []
    )));
  };
  const normalizeAcceptance = (value) => {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null;
    const artifacts = Array.isArray(value.artifacts)
      ? value.artifacts.flatMap((artifact) => (
        artifact
        && typeof artifact === 'object'
        && !Array.isArray(artifact)
        && artifactNames.has(artifact.name)
        && typeof artifact.sha256 === 'string'
        && /^[0-9a-f]{64}$/.test(artifact.sha256)
        && Number.isInteger(artifact.size_bytes)
        && artifact.size_bytes >= 0
          ? [{
            name: artifact.name,
            sha256: artifact.sha256,
            size_bytes: artifact.size_bytes,
          }]
          : []
      ))
      : [];
    return { artifacts };
  };
  return stepKeys
    .filter((key) => byKey.has(key))
    .map((key) => {
      const step = byKey.get(key);
      return {
        key,
        status: statuses.has(step.status) ? step.status : 'waiting',
        job_id: normalizeScalar(step.job_id),
        attempt: normalizeScalar(step.attempt),
        attempt_dir: normalizeScalar(step.attempt_dir),
        slurm_state: normalizeScalar(step.slurm_state),
        exit_code: normalizeScalar(step.exit_code),
        reason: normalizeScalar(step.reason),
        accepted: typeof step.accepted === 'boolean' ? step.accepted : null,
        resources: normalizeResources(step.resources),
        acceptance: normalizeAcceptance(step.acceptance),
      };
    });
}

function resultDataKindLabel(dataKind) {
  if (dataKind === 'demo') return '演示数据';
  if (dataKind === 'live') return '真实数据';
  return '来源未验证';
}

function resultDbKey(dataKind) {
  if (dataKind === 'demo') return '107cup-demo';
  if (dataKind === 'live') return '107cup-live';
  return '107cup-result';
}

function normalizeResultArtifacts(value) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.filter((kind) => (
    typeof kind === 'string' && RESULT_ARTIFACT_KINDS.has(kind)
  )))];
}

function displayFailureValue(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') return value;
  if (typeof value === 'boolean') return String(value);
  return '-';
}

function normalizeEvidenceLines(value) {
  if (!Array.isArray(value)) return ['-'];
  const lines = value
    .filter((entry) => (
      (typeof entry === 'string' && entry.trim() !== '')
      || (typeof entry === 'number' && Number.isFinite(entry))
      || typeof entry === 'boolean'
    ))
    .map(String);
  return lines.length > 0 ? lines : ['-'];
}

function hasCompleteFailureEvidence(evidence) {
  if (evidence === null || typeof evidence !== 'object' || Array.isArray(evidence)) return false;
  const hasText = (value) => typeof value === 'string' && value.trim() !== '';
  const hasValidJobId = (value) => (
    hasText(value) || (Number.isInteger(value) && value > 0)
  );
  const hasValidExitCode = (value) => (
    hasText(value) || (Number.isInteger(value) && value >= 0)
  );
  const hasStringArray = (value, allowEmpty) => (
    Array.isArray(value)
    && (allowEmpty || value.length > 0)
    && value.every(hasText)
  );
  return ['relax', 'scf', 'band', 'dos'].includes(evidence.step)
    && hasValidJobId(evidence.job_id)
    && hasValidExitCode(evidence.exit_code)
    && hasText(evidence.reason)
    && hasStringArray(evidence.expected_files, false)
    && hasStringArray(evidence.missing_files, true)
    && hasStringArray(evidence.log_tail, false);
}

function EvidenceList({ values }) {
  const lines = normalizeEvidenceLines(values);
  return (
    <ul>
      {lines.map((line, index) => <li key={`${line}-${index}`}>{line}</li>)}
    </ul>
  );
}

function ResultFailureEvidence({ result }) {
  const suppliedEvidence = result?.failure_evidence;
  const evidence = suppliedEvidence !== null
    && typeof suppliedEvidence === 'object'
    && !Array.isArray(suppliedEvidence)
    ? suppliedEvidence
    : {};
  const evidenceComplete = hasCompleteFailureEvidence(suppliedEvidence);

  return (
    <section className="competition-result-failure" aria-labelledby="competition-result-failure-title">
      <div className="competition-result-section-heading">
        <h2 id="competition-result-failure-title">
          {result.status === 'parse-error' ? '解析失败证据' : '计算失败证据'}
        </h2>
        <span>未渲染科学成功区</span>
      </div>
      {!evidenceComplete ? (
        <p className="competition-result-failure-warning" role="alert">
          失败证据不完整：部分字段缺失或格式无效。
        </p>
      ) : null}
      <dl className="competition-result-failure-grid">
        <div><dt>失败步骤</dt><dd>{displayFailureValue(evidence.step)}</dd></div>
        <div><dt>Job ID</dt><dd>{displayFailureValue(evidence.job_id)}</dd></div>
        <div><dt>ExitCode</dt><dd>{displayFailureValue(evidence.exit_code)}</dd></div>
        <div><dt>原因</dt><dd>{displayFailureValue(evidence.reason)}</dd></div>
        <div><dt>预期文件</dt><dd><EvidenceList values={evidence.expected_files} /></dd></div>
        <div><dt>缺失文件</dt><dd><EvidenceList values={evidence.missing_files} /></dd></div>
      </dl>
      <div className="competition-result-log-block">
        <h3>最后日志</h3>
        <pre className="competition-result-log">{normalizeEvidenceLines(evidence.log_tail).join('\n')}</pre>
      </div>
    </section>
  );
}

function ResultEvidenceDownload({ artifacts, workflowId, downloadFile }) {
  const [downloading, setDownloading] = useState(false);
  const [actionError, setActionError] = useState('');
  if (!artifacts.includes('evidence-bundle')) return null;

  async function downloadEvidence() {
    setActionError('');
    setDownloading(true);
    try {
      const encodedId = encodeURIComponent(workflowId);
      await downloadFile(
        `/api/competition/results/${encodedId}/artifacts/evidence-bundle`,
        `${workflowId}-evidence.json`,
      );
    } catch (error) {
      setActionError(String(error?.message || error));
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div className="competition-result-download-action">
      <button
        className="vasp-detail-button competition-result-download-button"
        type="button"
        disabled={downloading}
        onClick={downloadEvidence}
      >
        <Download size={15} aria-hidden="true" />
        {downloading ? '正在下载证据包…' : '下载证据包'}
      </button>
      {actionError ? (
        <div className="competition-result-download-error" role="alert">
          下载失败：{actionError}
        </div>
      ) : null}
    </div>
  );
}

export default function CompetitionResultDetail() {
  const { workflowId } = useParams();
  const { provider, mode } = useCompetitionData();
  const loadResult = useCallback(
    () => (workflowId ? provider.getResult(workflowId) : Promise.resolve(null)),
    [provider, workflowId],
  );
  const state = useCompetitionResource(loadResult);
  const detailState = normalizeResultDetailState(state, workflowId);

  const fetchScientificJson = useCallback((path) => {
    return requestScientificPlot(provider, workflowId, path);
  }, [provider, workflowId]);

  const downloadScientificFile = useCallback(async (path, filename) => {
    let href = '';
    let anchor = null;
    try {
      const artifact = await requestScientificArtifact(provider, workflowId, path, filename);
      if (!artifact?.blob || typeof artifact.filename !== 'string' || artifact.filename === '') {
        throw new Error('科学工件合同不完整');
      }
      href = URL.createObjectURL(artifact.blob);
      anchor = document.createElement('a');
      anchor.href = href;
      anchor.download = artifact.filename;
      document.body.appendChild(anchor);
      anchor.click();
    } finally {
      anchor?.remove();
      if (href) URL.revokeObjectURL(href);
    }
  }, [provider, workflowId]);

  if (detailState.status !== 'ready') {
    return (
      <main className="competition-result-detail-page">
        {mode === 'demo' ? <DemoDataBanner /> : null}
        <CompetitionState status={detailState.status} message={detailState.message} />
      </main>
    );
  }

  const result = detailState.result;
  const dataKindLabel = resultDataKindLabel(result.data_kind);
  const resultSteps = normalizeResultSteps(result.steps);
  const materialLabel = displayIdentity(result.material);
  const scientificDbKey = resultDbKey(result.data_kind);
  const resultArtifacts = normalizeResultArtifacts(result.artifacts);

  return (
    <main className="competition-result-detail-page">
      {mode === 'demo' ? <DemoDataBanner /> : null}

      <header className="competition-result-detail-header">
        <div>
          <div className="competition-result-title-line">
            <h1>{materialLabel === '-' ? 'VASP 计算结果' : materialLabel}</h1>
            <StatusBadge status={result.status} />
            {result.data_kind === 'demo' ? <span className="competition-result-demo-label">演示内容</span> : null}
          </div>
          <p>{workflowId}</p>
        </div>
        <ResultEvidenceDownload
          artifacts={resultArtifacts}
          workflowId={workflowId}
          downloadFile={downloadScientificFile}
        />
      </header>

      <section className="competition-result-evidence" aria-labelledby="competition-result-identity-title">
        <div className="competition-result-section-heading">
          <h2 id="competition-result-identity-title">不可变标识</h2>
          <span>{dataKindLabel}</span>
        </div>
        <dl className="competition-result-identity">
          <div><dt>工作流 ID</dt><dd>{displayIdentity(workflowId)}</dd></div>
          <div><dt>创建人</dt><dd>{displayIdentity(result.creator)}</dd></div>
          <div><dt>模板版本</dt><dd>{displayIdentity(result.template_version)}</dd></div>
          <div><dt>输入 SHA-256</dt><dd>{displayIdentity(result.input_sha256)}</dd></div>
          <div><dt>发布提交</dt><dd>{displayIdentity(result.release_commit)}</dd></div>
          <div><dt>数据类型</dt><dd>{dataKindLabel}</dd></div>
        </dl>
      </section>

      <section className="competition-result-evidence" aria-labelledby="competition-result-timeline-title">
        <div className="competition-result-section-heading">
          <h2 id="competition-result-timeline-title">工作流证据</h2>
          <span>完整 relax → SCF → BAND / DOS</span>
        </div>
        <WorkflowTimeline steps={resultSteps} />
      </section>

      {detailState.variant === 'success' ? (
        <section className="competition-result-science" aria-labelledby="competition-result-science-title">
          <div className="competition-result-section-heading">
            <h2 id="competition-result-science-title">科学结果</h2>
            <span>{result.data_kind === 'demo' ? '演示内容' : '真实结果'}</span>
          </div>
          <VaspTaskSummary
            detail={result.vasp_detail}
            dbKey={scientificDbKey}
            rowId={workflowId}
            viewer={<VaspStructureViewer structure={result.vasp_detail.structure} />}
            downloadFile={downloadScientificFile}
          />
          <div className="competition-result-science-section">
            <h3>晶体参数</h3>
            <VaspCrystalDetails detail={result.vasp_detail} />
          </div>
          <div className="competition-result-science-section">
            <h3>电子性质</h3>
            <VaspElectronicProperties
              rowId={workflowId}
              dbKey={scientificDbKey}
              capabilities={result.vasp_detail.capabilities}
              fetchJson={fetchScientificJson}
              downloadFile={downloadScientificFile}
            />
          </div>
        </section>
      ) : (
        <ResultFailureEvidence result={result} />
      )}
    </main>
  );
}
