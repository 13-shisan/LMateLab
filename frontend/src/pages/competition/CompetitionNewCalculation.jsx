import { useRef, useState } from 'react';
import { Save, Send, X } from 'lucide-react';

import { canWriteCompetitionData } from '../../config/competitionAccess';
import {
  useCompetitionData,
} from '../../features/competition/CompetitionDataContext';
import { PreviewReadOnlyNotice } from '../../features/competition/components/CompetitionState';
import { DEMO_STRUCTURE } from '../../features/competition/data/demoFixtures';
import VaspStructureViewer from '../db/vasp-detail/VaspStructureViewer';
import '../db/vasp-detail/VaspTaskDetail.css';
import './CompetitionPages.css';

const WORKFLOW_STEPS = [
  { key: 'relax', label: 'relax', dependsOn: [], purpose: '优化离子位置与晶格' },
  { key: 'scf', label: 'SCF', dependsOn: ['relax'], purpose: '生成已验收自洽电荷密度' },
  { key: 'band', label: 'BAND', dependsOn: ['scf'], purpose: '沿固定高对称路径计算能带' },
  { key: 'dos', label: 'DOS', dependsOn: ['scf'], purpose: '基于自洽结果计算态密度' },
];

const STEP_PARAMETERS = {
  relax: {
    ENCUT: '520 eV',
    'k-point': '12 x 12 x 1',
    convergence: 'EDIFF 1e-6 / EDIFFG -0.01',
  },
  scf: {
    ENCUT: '520 eV',
    'k-point': '18 x 18 x 1',
    convergence: 'EDIFF 1e-7',
  },
  band: {
    ENCUT: '520 eV',
    'k-point': '固定高对称路径',
    convergence: '复用已验收 SCF 电荷密度',
  },
  dos: {
    ENCUT: '520 eV',
    'k-point': '24 x 24 x 1',
    convergence: '复用已验收 SCF 电荷密度',
  },
};

const DEFAULT_PARAMETERS = {
  relax: { ENCUT: 520, EDIFF: 0.000001, EDIFFG: -0.01, NSW: 120, SIGMA: 0.05 },
  scf: { ENCUT: 520, EDIFF: 0.0000001, NELM: 120, SIGMA: 0.05 },
  band: { ENCUT: 520, EDIFF: 0.0000001, NELM: 120, SIGMA: 0.05 },
  dos: { ENCUT: 520, EDIFF: 0.0000001, NELM: 120, SIGMA: 0.05, NEDOS: 3000 },
};

const PARAMETER_LIMITS = {
  ENCUT: { min: 400, max: 700, step: 1 },
  EDIFF: { min: 0.00000001, max: 0.0001, step: 0.00000001 },
  EDIFFG: { min: -0.1, max: -0.001, step: 0.001 },
  NSW: { min: 1, max: 300, step: 1 },
  NELM: { min: 20, max: 300, step: 1 },
  SIGMA: { min: 0.01, max: 0.2, step: 0.01 },
  NEDOS: { min: 100, max: 10000, step: 100 },
};

function readStoredUser(storage) {
  try {
    const selectedStorage = storage === undefined ? globalThis.localStorage : storage;
    return JSON.parse(selectedStorage?.getItem('user') || 'null');
  } catch {
    return null;
  }
}

function isBusinessWriteAllowed(mode, user) {
  return mode === 'live' && canWriteCompetitionData(user);
}

async function runLockedWrite(lock, allowed, write) {
  if (!allowed || lock.current) return null;
  lock.current = true;
  try {
    return await write();
  } finally {
    lock.current = false;
  }
}

function buildDraftPayload({ sourceKind, structureUpload, parameters }) {
  if (sourceKind === 'upload' && !structureUpload?.id) {
    throw new Error('请先上传并通过服务端解析结构文件。');
  }
  const payload = {
    template_version: 'mos2_v1',
    source_kind: sourceKind,
    steps: ['relax', 'scf', 'band', 'dos'],
    parameters,
  };
  if (sourceKind === 'upload') payload.structure_upload_id = structureUpload.id;
  return payload;
}

function invalidateServerState(current = {}, { clearUpload = false } = {}) {
  return {
    structureUpload: clearUpload ? null : current.structureUpload || null,
    workflow: null,
    confirmation: null,
    error: '',
  };
}

function shouldClearConsumedUpload(sourceKind, serverState = {}) {
  return sourceKind === 'upload' && Boolean(serverState.workflow?.id);
}

function describeCommandStatus({
  sourceKind,
  serverState = {},
  uploadPending = false,
  savePending = false,
  confirmPending = false,
}) {
  if (uploadPending) return '正在上传并等待服务端解析结构';
  if (savePending) return '正在保存草稿';
  if (confirmPending) return '正在执行提交前校验';
  if (serverState.confirmation) {
    return `已校验，等待 Slurm 适配器 · ${serverState.confirmation.id}`;
  }
  if (serverState.workflow) {
    return `${serverState.workflow.id} · ${serverState.workflow.status} · SHA-256 ${serverState.workflow.input_sha256}`;
  }
  if (serverState.structureUpload) {
    return `结构已由服务端解析 · 上传 ID ${serverState.structureUpload.id}`;
  }
  return `未保存 · mos2_v1 · ${sourceKind === 'builtin' ? '内置 MoS2' : '上传结构'}`;
}

export default function CompetitionNewCalculation() {
  const { provider, mode } = useCompetitionData();
  const [sourceKind, setSourceKind] = useState('builtin');
  const [selectedStep, setSelectedStep] = useState('relax');
  const [parameters, setParameters] = useState(() => structuredClone(DEFAULT_PARAMETERS));
  const [originalFileName, setOriginalFileName] = useState('');
  const [fileInputKey, setFileInputKey] = useState(0);
  const [serverState, setServerState] = useState(() => invalidateServerState());
  const [uploadPending, setUploadPending] = useState(false);
  const [savePending, setSavePending] = useState(false);
  const [confirmPending, setConfirmPending] = useState(false);
  const uploadLock = useRef(false);
  const saveLock = useRef(false);
  const confirmLock = useRef(false);
  const inputVersion = useRef(0);
  const user = readStoredUser();
  const readOnly = mode === 'demo' || !canWriteCompetitionData(user);
  const canWrite = isBusinessWriteAllowed(mode, user);
  const activeStep = WORKFLOW_STEPS.find(({ key }) => key === selectedStep) || WORKFLOW_STEPS[0];
  const uploadReady = sourceKind === 'builtin' || Boolean(serverState.structureUpload?.id);
  const canSave = canWrite && uploadReady && !uploadPending && !serverState.workflow?.id;
  const canConfirm = canWrite
    && Boolean(serverState.workflow?.id)
    && !serverState.confirmation;

  function clearPersistedState({ clearUpload }) {
    inputVersion.current += 1;
    setServerState((current) => invalidateServerState(current, { clearUpload }));
  }

  function handleSourceKindChange(nextSourceKind) {
    if (nextSourceKind === sourceKind) return;
    setSourceKind(nextSourceKind);
    setOriginalFileName('');
    setFileInputKey((current) => current + 1);
    clearPersistedState({ clearUpload: true });
  }

  async function handleStructureFileChange(event) {
    if (!canWrite || uploadLock.current) return;
    const file = event.target.files?.[0] || null;
    const requestVersion = inputVersion.current + 1;
    inputVersion.current = requestVersion;
    setOriginalFileName(file?.name || '');
    setServerState((current) => invalidateServerState(current, { clearUpload: true }));
    if (!file) return;

    setUploadPending(true);
    try {
      const result = await runLockedWrite(
        uploadLock,
        canWrite,
        () => provider.uploadStructure(file),
      );
      if (result && inputVersion.current === requestVersion) {
        setServerState((current) => ({ ...current, structureUpload: result, error: '' }));
      }
    } catch (error) {
      if (inputVersion.current === requestVersion) {
        setServerState((current) => ({
          ...invalidateServerState(current, { clearUpload: true }),
          error: error?.message || '结构上传失败',
        }));
      }
    } finally {
      setUploadPending(false);
    }
  }

  function handleClearStructureFile() {
    if (uploadPending) return;
    setOriginalFileName('');
    setFileInputKey((current) => current + 1);
    clearPersistedState({ clearUpload: true });
  }

  function handleParameterChange(stepKey, parameterKey, rawValue) {
    const value = Number(rawValue);
    if (!Number.isFinite(value)) return;
    setParameters((current) => ({
      ...current,
      [stepKey]: { ...current[stepKey], [parameterKey]: value },
    }));
    const clearUpload = shouldClearConsumedUpload(sourceKind, serverState);
    if (clearUpload) {
      setOriginalFileName('');
      setFileInputKey((current) => current + 1);
    }
    clearPersistedState({ clearUpload });
  }

  async function handleSaveDraft() {
    if (!canSave || saveLock.current) return;
    const requestVersion = inputVersion.current;
    setServerState((current) => ({ ...current, error: '' }));
    setSavePending(true);
    try {
      const payload = buildDraftPayload({
        sourceKind,
        structureUpload: serverState.structureUpload,
        parameters,
      });
      const result = await runLockedWrite(saveLock, canSave, () => provider.saveDraft(payload));
      if (result && inputVersion.current === requestVersion) {
        setServerState((current) => ({
          ...current,
          workflow: result,
          confirmation: null,
          error: '',
        }));
      }
    } catch (error) {
      if (inputVersion.current === requestVersion) {
        setServerState((current) => ({
          ...current,
          workflow: null,
          confirmation: null,
          error: error?.message || '草稿保存失败',
        }));
      }
    } finally {
      setSavePending(false);
    }
  }

  async function handleSubmitWorkflow() {
    if (!canConfirm || confirmLock.current) return;
    const requestVersion = inputVersion.current;
    setServerState((current) => ({ ...current, error: '' }));
    setConfirmPending(true);
    try {
      const result = await runLockedWrite(
        confirmLock,
        canConfirm,
        () => provider.submitWorkflow(serverState.workflow.id),
      );
      if (result && inputVersion.current === requestVersion) {
        setServerState((current) => ({
          ...current,
          workflow: result,
          confirmation: result,
          error: '',
        }));
      }
    } catch (error) {
      if (inputVersion.current === requestVersion) {
        setServerState((current) => ({
          ...current,
          confirmation: null,
          error: error?.message || '工作流确认失败',
        }));
      }
    } finally {
      setConfirmPending(false);
    }
  }

  return (
    <main className="competition-calculation-page">
      <header className="competition-calculation-header">
        <div>
          <h1>新建 VASP 计算</h1>
          <p>单层 MoS2 固定四步工作流审阅</p>
        </div>
        {readOnly ? <PreviewReadOnlyNotice /> : null}
      </header>

      <section className="competition-work-section" aria-labelledby="competition-source-title">
        <div className="competition-section-heading">
          <div>
            <span>01</span>
            <h2 id="competition-source-title">来源与结构</h2>
          </div>
          <p>模板 mos2_v1 · 输入 SHA-256：保存草稿后由服务端生成</p>
        </div>

        <div className="competition-source-segment" role="group" aria-label="结构来源">
          <button
            className={sourceKind === 'builtin' ? 'is-active' : ''}
            type="button"
            aria-pressed={sourceKind === 'builtin'}
            disabled={readOnly}
            onClick={() => handleSourceKindChange('builtin')}
          >
            内置 MoS2
          </button>
          <button
            className={sourceKind === 'upload' ? 'is-active' : ''}
            type="button"
            aria-pressed={sourceKind === 'upload'}
            disabled={readOnly}
            onClick={() => handleSourceKindChange('upload')}
          >
            上传结构
          </button>
        </div>

        <div className="competition-calculation-grid">
          <div className="competition-structure-viewer">
            {sourceKind === 'builtin' ? (
              <VaspStructureViewer structure={DEMO_STRUCTURE} />
            ) : (
              <div className="competition-upload-placeholder">
                <label htmlFor="competition-structure-file">结构文件</label>
                <input
                  key={fileInputKey}
                  id="competition-structure-file"
                  type="file"
                  accept=".vasp,.poscar,.cif"
                  disabled={readOnly || uploadPending}
                  onChange={handleStructureFileChange}
                />
                <strong>{uploadPending ? '服务端解析中' : (originalFileName || '未选择文件')}</strong>
                <span>POSCAR/CIF 文本，最大 1 MiB，最多 200 个原子</span>
                <small>结构内容仅由服务端解析；文件名仅用于审计显示</small>
                {originalFileName && !uploadPending ? (
                  <button
                    className="competition-upload-clear"
                    type="button"
                    disabled={readOnly}
                    onClick={handleClearStructureFile}
                    title="清除结构文件"
                  >
                    <X size={15} aria-hidden="true" />
                    清除
                  </button>
                ) : null}
              </div>
            )}
          </div>

          {sourceKind === 'builtin' ? (
            <aside className="competition-structure-summary" aria-label="晶格摘要">
              <h3>晶格摘要</h3>
              <dl>
                <div><dt>化学式</dt><dd>MoS2</dd></div>
                <div><dt>原子数</dt><dd>{DEMO_STRUCTURE.symbols.length}</dd></div>
                <div><dt>a</dt><dd>3.158 Å</dd></div>
                <div><dt>b</dt><dd>3.158 Å</dd></div>
                <div><dt>c</dt><dd>20.000 Å</dd></div>
                <div><dt>周期性</dt><dd>x / y</dd></div>
              </dl>
              <p>内置结构 · 演示数据</p>
            </aside>
          ) : (
            <aside className="competition-structure-summary" aria-label="上传结构状态">
              <h3>结构状态</h3>
              <dl>
                <div><dt>文件</dt><dd>{originalFileName || '待选择'}</dd></div>
                <div>
                  <dt>解析</dt>
                  <dd>
                    {uploadPending
                      ? '服务端解析中'
                      : (serverState.structureUpload?.summary?.formula || '未解析')}
                  </dd>
                </div>
                <div>
                  <dt>原子数</dt>
                  <dd>{serverState.structureUpload?.summary?.atom_count ?? '—'}</dd>
                </div>
                <div>
                  <dt>格式</dt>
                  <dd>{serverState.structureUpload?.source_format?.toUpperCase() || '—'}</dd>
                </div>
                <div>
                  <dt>元素</dt>
                  <dd>{serverState.structureUpload?.summary?.elements?.join(' / ') || '—'}</dd>
                </div>
                <div>
                  <dt>提交</dt>
                  <dd>{serverState.structureUpload?.id ? '可保存草稿' : '不可提交'}</dd>
                </div>
              </dl>
              <p>
                {serverState.structureUpload?.id
                  ? `服务端上传 ID · ${serverState.structureUpload.id}`
                  : '上传来源 · 等待服务端解析'}
              </p>
            </aside>
          )}
        </div>
      </section>

      <section className="competition-work-section" aria-labelledby="competition-workflow-title">
        <div className="competition-section-heading">
          <div>
            <span>02</span>
            <h2 id="competition-workflow-title">不可变依赖</h2>
          </div>
          <p>relax → SCF → BAND / DOS</p>
        </div>

        <div className="competition-workflow-scroll">
          <ol className="competition-workflow-graph" aria-label="固定四步工作流">
            {WORKFLOW_STEPS.map((step) => (
              <li
                className={`competition-workflow-step is-${step.key}`}
                key={step.key}
              >
                <button
                  className={selectedStep === step.key ? 'is-active' : ''}
                  type="button"
                  aria-pressed={selectedStep === step.key}
                  onClick={() => setSelectedStep(step.key)}
                >
                  <span>{step.label}</span>
                  <small>
                    {step.dependsOn.length === 0
                      ? '起点'
                      : `依赖 ${step.dependsOn.map((key) => key.toUpperCase()).join(' + ')}`}
                  </small>
                </button>
                <p>{step.purpose}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="competition-work-section" aria-labelledby="competition-review-title">
        <div className="competition-section-heading">
          <div>
            <span>03</span>
            <h2 id="competition-review-title">参数与资源审阅</h2>
          </div>
          <p>参数在服务端按模板白名单和值域再次校验</p>
        </div>

        <div className="competition-review-grid">
          <div className="competition-parameter-review">
            <h3>{activeStep.label} · 参数</h3>
            <div className="competition-parameter-fields">
              {Object.entries(parameters[activeStep.key]).map(([key, value]) => (
                <label key={key}>
                  <span>{key}</span>
                  <input
                    type="number"
                    value={value}
                    min={PARAMETER_LIMITS[key]?.min}
                    max={PARAMETER_LIMITS[key]?.max}
                    step={PARAMETER_LIMITS[key]?.step}
                    disabled={readOnly}
                    onChange={(event) => (
                      handleParameterChange(activeStep.key, key, event.target.value)
                    )}
                  />
                </label>
              ))}
            </div>
            <p className="competition-parameter-note">
              固定 k-point：{STEP_PARAMETERS[activeStep.key]['k-point']} · {STEP_PARAMETERS[activeStep.key].convergence}
            </p>
          </div>

          <div className="competition-resource-review">
            <h3>Slurm 资源 · 计划参数</h3>
            <dl>
              <div><dt>Partition</dt><dd>P107-RTX5090<small>阶段 6 接入</small></dd></div>
              <div><dt>资源上限</dt><dd>最大 4 GPU / 16 CPU<small>阶段 6 接入</small></dd></div>
              <div><dt>证据单位</dt><dd>每步独立一个 Job / attempt 证据记录<small>阶段 6 接入</small></dd></div>
            </dl>
          </div>
        </div>
      </section>

      <footer className="competition-command-bar">
        <div>
          <strong>{serverState.confirmation ? '工作流已确认' : '工作流草稿'}</strong>
          <span aria-live="polite">
            {describeCommandStatus({
              sourceKind,
              serverState,
              uploadPending,
              savePending,
              confirmPending,
            })}
          </span>
          {serverState.error ? <p role="alert">{serverState.error}</p> : null}
        </div>
        <div className="competition-command-actions">
          <button
            className="competition-command-button is-secondary"
            type="button"
            disabled={!canSave || savePending}
            onClick={handleSaveDraft}
          >
            <Save size={16} aria-hidden="true" />
            {savePending ? '保存中' : '保存草稿'}
          </button>
          <button
            className="competition-command-button is-primary"
            type="button"
            disabled={!canConfirm || confirmPending}
            onClick={handleSubmitWorkflow}
          >
            <Send size={16} aria-hidden="true" />
            {confirmPending ? '校验中' : '确认并校验'}
          </button>
        </div>
      </footer>
    </main>
  );
}
