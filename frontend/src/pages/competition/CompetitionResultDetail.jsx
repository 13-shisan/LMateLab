import { useCallback } from 'react';
import { useParams } from 'react-router-dom';

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

function inferArtifactKind(value) {
  const text = String(value).toLowerCase();
  if (text.includes('band')) return 'band-data';
  if (text.includes('dos')) return 'dos-data';
  if (text.includes('cif')) return 'structure-cif';
  if (text.includes('poscar') || text.includes('.vasp')) return 'structure-poscar';
  return 'evidence-bundle';
}

function normalizeResultDetailState(resource, workflowId) {
  const isPlainObject = (value) => {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
    const prototype = Object.getPrototypeOf(value);
    return prototype === Object.prototype || prototype === null;
  };
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
  const resultWorkflowId = [result.id, result.workflow_id].find((value) => (
    typeof value === 'string'
    && value.trim() !== ''
    && value === value.trim()
  ));
  if (!resultWorkflowId) {
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

  const detail = result.vasp_detail;
  const structure = detail?.structure;
  const crystal = detail?.crystal;
  const capabilities = detail?.capabilities;
  const coordinateRows = crystal?.atomic_positions_frac;
  const structureIsComplete = isPlainObject(structure)
    && Array.isArray(structure.symbols)
    && structure.symbols.length > 0
    && structure.symbols.every((symbol) => typeof symbol === 'string' && symbol.trim() !== '')
    && Array.isArray(structure.positions)
    && structure.positions.length === structure.symbols.length
    && structure.positions.every((position) => (
      Array.isArray(position)
      && position.length === 3
      && position.every((value) => Number.isFinite(Number(value)))
    ))
    && Array.isArray(structure.cell)
    && structure.cell.length === 3
    && structure.cell.every((vector) => (
      Array.isArray(vector)
      && vector.length === 3
      && vector.every((value) => Number.isFinite(Number(value)))
    ));
  const detailIsComplete = isPlainObject(detail)
    && isPlainObject(detail.db)
    && isPlainObject(detail.row)
    && isPlainObject(detail.properties)
    && structureIsComplete
    && isPlainObject(crystal)
    && isPlainObject(crystal.lattice)
    && Array.isArray(coordinateRows)
    && coordinateRows.length > 0
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
  return value === null || value === undefined || value === '' ? '-' : value;
}

function resultDataKindLabel(dataKind) {
  if (dataKind === 'demo') return '演示数据';
  if (dataKind === 'live') return '真实数据';
  return '来源未验证';
}

function displayFailureValue(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') return value;
  return '-';
}

function normalizeEvidenceLines(value) {
  if (!Array.isArray(value)) return ['-'];
  const lines = value
    .filter((entry) => (
      (typeof entry === 'string' && entry.trim() !== '')
      || (typeof entry === 'number' && Number.isFinite(entry))
    ))
    .map(String);
  return lines.length > 0 ? lines : ['-'];
}

function hasCompleteFailureEvidence(evidence) {
  if (evidence === null || typeof evidence !== 'object' || Array.isArray(evidence)) return false;
  return ['step', 'job_id', 'exit_code', 'reason']
    .every((key) => displayFailureValue(evidence[key]) !== '-')
    && Array.isArray(evidence.expected_files)
    && Array.isArray(evidence.missing_files)
    && Array.isArray(evidence.log_tail);
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
    const kind = String(path).includes('band-plot') ? 'band' : 'dos';
    return provider.loadPlot(workflowId, kind);
  }, [provider, workflowId]);

  const downloadScientificFile = useCallback(async (path, filename) => {
    let href = '';
    let anchor = null;
    try {
      const artifact = await provider.downloadArtifact(workflowId, inferArtifactKind(`${path} ${filename}`));
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
  const resultSteps = Array.isArray(result.steps) ? result.steps : [];

  return (
    <main className="competition-result-detail-page">
      {mode === 'demo' ? <DemoDataBanner /> : null}

      <header className="competition-result-detail-header">
        <div>
          <div className="competition-result-title-line">
            <h1>{result.material || 'VASP 计算结果'}</h1>
            <StatusBadge status={result.status} />
            {result.data_kind === 'demo' ? <span className="competition-result-demo-label">演示内容</span> : null}
          </div>
          <p>{workflowId}</p>
        </div>
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
            dbKey="107cup-demo"
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
              dbKey="107cup-demo"
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
