import { useCallback, useState } from 'react';
import { CircleX, RotateCcw } from 'lucide-react';
import { useParams } from 'react-router-dom';

import { canWriteCompetitionData } from '../../config/competitionAccess';
import {
  useCompetitionData,
  useCompetitionPollingResource,
  useCompetitionResource,
} from '../../features/competition/CompetitionDataContext';
import {
  CompetitionState,
  DemoDataBanner,
  PreviewReadOnlyNotice,
  StatusBadge,
} from '../../features/competition/components/CompetitionState';
import WorkflowTimeline from '../../features/competition/components/WorkflowTimeline';
import './CompetitionPages.css';

function readStoredUser(storage) {
  try {
    const selectedStorage = storage === undefined ? globalThis.localStorage : storage;
    return JSON.parse(selectedStorage?.getItem('user') || 'null');
  } catch {
    return null;
  }
}

async function executeWorkflowCommand({
  mode,
  user,
  command,
  workflowId,
  step,
  pending,
  write,
}) {
  const validWorkflowId = typeof workflowId === 'string'
    && workflowId.trim() !== ''
    && workflowId === workflowId.trim();
  if (
    mode !== 'live'
    || !canWriteCompetitionData(user)
    || !['cancel', 'retry'].includes(command)
    || !validWorkflowId
    || pending !== false
    || typeof write !== 'function'
  ) return false;
  if (command === 'retry' && !['relax', 'scf', 'band', 'dos'].includes(step)) return false;
  await write();
  return true;
}

function displayIdentity(value) {
  return value === null || value === undefined || value === '' ? '-' : value;
}

function workflowDataKindLabel(dataKind) {
  if (dataKind === 'demo') return '演示数据';
  if (dataKind === 'live') return '真实数据';
  return '来源未验证';
}

function normalizeWorkflowDetailState(resource, workflowId) {
  const emptyMessage = workflowId ? '未找到工作流' : '缺少工作流 ID';
  if (resource === null || typeof resource !== 'object' || Array.isArray(resource)) {
    return { status: 'empty', message: emptyMessage, workflow: null };
  }
  if (resource.status !== 'ready') {
    if (resource.status === 'empty') {
      return { status: 'empty', message: emptyMessage, workflow: null };
    }
    return {
      status: resource.status,
      message: resource.error?.message,
      workflow: null,
    };
  }

  const workflow = resource.data;
  const prototype = workflow && typeof workflow === 'object'
    ? Object.getPrototypeOf(workflow)
    : undefined;
  const isPlainWorkflow = prototype === Object.prototype || prototype === null;
  if (!isPlainWorkflow) {
    return { status: 'empty', message: emptyMessage, workflow: null };
  }
  if (
    typeof workflow.id !== 'string'
    || workflow.id.trim() === ''
    || workflow.id !== workflow.id.trim()
  ) {
    return { status: 'parse-error', message: '工作流身份无效', workflow: null };
  }
  if (workflow.id !== workflowId) {
    return { status: 'parse-error', message: '工作流身份不一致', workflow: null };
  }
  if (!['demo', 'live'].includes(workflow.data_kind)) {
    return { status: 'parse-error', message: '工作流数据来源未验证', workflow: null };
  }
  return { status: 'ready', message: undefined, workflow };
}

function findRetryableFailedStep(steps) {
  if (!Array.isArray(steps)) return null;
  for (const step of steps) {
    if (
      step
      && typeof step === 'object'
      && ['failed', 'scientific_failed'].includes(step.status)
      && ['relax', 'scf', 'band', 'dos'].includes(step.key)
    ) return step;
  }
  return null;
}

function shouldPollWorkflow(mode, status) {
  return mode === 'live'
    && [
      'preparing',
      'submitting',
      'queued',
      'running',
      'awaiting_acceptance',
      'cancelling',
    ].includes(status);
}

function isSafeAttemptIdentifier(value) {
  return typeof value === 'string'
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(value);
}

function selectLatestAttemptStep(steps, selectedStepKey) {
  if (!Array.isArray(steps)) return null;
  const candidates = steps.filter((step) => (
    step
    && typeof step === 'object'
    && ['relax', 'scf', 'band', 'dos'].includes(step.key)
    && isSafeAttemptIdentifier(step.attempt_id)
  ));
  const selected = candidates.find((step) => step.key === selectedStepKey);
  return selected || candidates[candidates.length - 1] || null;
}

function normalizeAttemptLogState(resource, expectedStream, attemptId) {
  if (!isSafeAttemptIdentifier(attemptId)) {
    return { status: 'empty', message: '当前步骤暂无日志', content: '' };
  }
  if (!resource || typeof resource !== 'object' || Array.isArray(resource)) {
    return { status: 'error', message: '日志暂时不可用', content: '' };
  }
  if (resource.status === 'loading') {
    return { status: 'loading', message: '日志加载中', content: '' };
  }
  if (resource.status !== 'ready') {
    return resource.status === 'empty'
      ? { status: 'empty', message: '当前日志为空', content: '' }
      : { status: 'error', message: '日志暂时不可用', content: '' };
  }
  const data = resource.data;
  const prototype = data && typeof data === 'object' ? Object.getPrototypeOf(data) : undefined;
  if (
    (prototype !== Object.prototype && prototype !== null)
    || data.stream !== expectedStream
    || typeof data.content !== 'string'
  ) {
    return { status: 'error', message: '日志暂时不可用', content: '' };
  }
  if (data.content === '') {
    return { status: 'empty', message: '当前日志为空', content: '' };
  }
  return { status: 'ready', message: '', content: data.content };
}

export default function CompetitionWorkflowDetail() {
  const { workflowId } = useParams();
  const { provider, mode } = useCompetitionData();
  const [commandError, setCommandError] = useState('');
  const [commandPending, setCommandPending] = useState(false);
  const [selectedStepKey, setSelectedStepKey] = useState('');
  const [logStream, setLogStream] = useState('stdout');
  const user = readStoredUser();
  const readOnly = mode === 'demo' || !canWriteCompetitionData(user);
  const loadWorkflow = useCallback(
    () => (workflowId ? provider.getWorkflow(workflowId) : Promise.resolve(null)),
    [provider, workflowId],
  );
  const state = useCompetitionPollingResource(loadWorkflow, {
    enabled: (current) => shouldPollWorkflow(mode, current?.status),
  });
  const detailState = normalizeWorkflowDetailState(state, workflowId);
  const workflow = detailState.status === 'ready' ? detailState.workflow : null;
  const workflowSteps = Array.isArray(workflow?.steps) ? workflow.steps : [];
  const loggableSteps = workflowSteps.filter((step) => isSafeAttemptIdentifier(step?.attempt_id));
  const selectedAttemptStep = selectLatestAttemptStep(workflowSteps, selectedStepKey);
  const selectedAttemptId = selectedAttemptStep?.attempt_id || null;
  const loadAttemptLog = useCallback(
    () => (
      workflow && selectedAttemptId
        ? provider.getAttemptLog(workflow.id, selectedAttemptId, logStream)
        : Promise.resolve(null)
    ),
    [provider, workflow, selectedAttemptId, logStream],
  );
  const logResource = useCompetitionResource(loadAttemptLog);
  const logState = normalizeAttemptLogState(logResource, logStream, selectedAttemptId);

  if (detailState.status !== 'ready') {
    return (
      <main className="competition-workflow-detail-page">
        {mode === 'demo' ? <DemoDataBanner /> : null}
        <CompetitionState
          status={detailState.status}
          message={detailState.message}
        />
      </main>
    );
  }

  const dataKindLabel = workflowDataKindLabel(workflow.data_kind);
  const failedStep = findRetryableFailedStep(workflowSteps);

  async function handleCancel() {
    setCommandError('');
    if (commandPending) return;
    setCommandPending(true);
    try {
      await executeWorkflowCommand({
        mode,
        user,
        command: 'cancel',
        workflowId: workflow.id,
        step: null,
        pending: commandPending,
        write: () => provider.cancelWorkflow(workflow.id),
      });
    } catch (error) {
      setCommandError(error?.message || '工作流取消失败');
    } finally {
      setCommandPending(false);
    }
  }

  async function handleRetry() {
    setCommandError('');
    if (commandPending || failedStep === null) return;
    setCommandPending(true);
    try {
      await executeWorkflowCommand({
        mode,
        user,
        command: 'retry',
        workflowId: workflow.id,
        step: failedStep.key,
        pending: commandPending,
        write: () => provider.retryWorkflow({ id: workflow.id, step: failedStep.key }),
      });
    } catch (error) {
      setCommandError(error?.message || '工作流重试失败');
    } finally {
      setCommandPending(false);
    }
  }

  return (
    <main className="competition-workflow-detail-page">
      {mode === 'demo' ? <DemoDataBanner /> : null}

      <header className="competition-workflow-detail-header">
        <div>
          <div className="competition-workflow-title-line">
            <h1>{workflow.material || '工作流证据'}</h1>
            <StatusBadge status={workflow.status} />
          </div>
          <p>{workflow.id}</p>
        </div>
        {readOnly ? <PreviewReadOnlyNotice /> : null}
      </header>

      <section className="competition-workflow-evidence" aria-labelledby="competition-workflow-identity-title">
        <div className="competition-workflow-section-heading">
          <h2 id="competition-workflow-identity-title">不可变标识</h2>
          <span>{dataKindLabel}</span>
        </div>
        <dl className="competition-workflow-identity">
          <div><dt>工作流 ID</dt><dd>{displayIdentity(workflow.id)}</dd></div>
          <div><dt>创建人</dt><dd>{displayIdentity(workflow.creator)}</dd></div>
          <div><dt>模板版本</dt><dd>{displayIdentity(workflow.template_version)}</dd></div>
          <div><dt>输入 SHA-256</dt><dd>{displayIdentity(workflow.input_sha256)}</dd></div>
          <div><dt>发布提交</dt><dd>{displayIdentity(workflow.release_commit)}</dd></div>
          <div><dt>数据类型</dt><dd>{dataKindLabel}</dd></div>
        </dl>
      </section>

      <section className="competition-workflow-evidence" aria-labelledby="competition-workflow-timeline-title">
        <div className="competition-workflow-section-heading">
          <h2 id="competition-workflow-timeline-title">步骤与调度证据</h2>
          <span>固定 relax → SCF → BAND / DOS</span>
        </div>
        <WorkflowTimeline steps={workflowSteps} />
      </section>

      <section className="competition-workflow-evidence" aria-labelledby="competition-workflow-log-title">
        <div className="competition-workflow-section-heading">
          <h2 id="competition-workflow-log-title">有界日志</h2>
          <span>当前 latest attempt · 单次响应不累积</span>
        </div>
        {loggableSteps.length > 0 ? (
          <>
            <div className="competition-workflow-filters">
              <label className="competition-workflow-status">
                <span>步骤</span>
                <select
                  value={selectedAttemptStep?.key || ''}
                  onChange={(event) => setSelectedStepKey(event.target.value)}
                >
                  {loggableSteps.map((step) => (
                    <option key={step.key} value={step.key}>
                      {step.key.toUpperCase()} · attempt {step.attempt}
                    </option>
                  ))}
                </select>
              </label>
              <div className="competition-source-segment" role="group" aria-label="日志流">
                {['stdout', 'stderr'].map((stream) => (
                  <button
                    className={logStream === stream ? 'is-active' : ''}
                    key={stream}
                    type="button"
                    aria-pressed={logStream === stream}
                    onClick={() => setLogStream(stream)}
                  >
                    {stream}
                  </button>
                ))}
              </div>
            </div>
            {logState.status === 'ready' ? (
              <pre className="competition-result-log">{logState.content}</pre>
            ) : (
              <p
                className="competition-workflow-log-state"
                role={logState.status === 'error' ? 'alert' : 'status'}
              >
                {logState.message}
              </p>
            )}
          </>
        ) : (
          <p className="competition-workflow-log-state" role="status">当前步骤暂无日志</p>
        )}
      </section>

      <footer className="competition-workflow-command-bar">
        <div>
          <strong>工作流命令</strong>
          <span>写操作仅面向未来 live Operator</span>
          {commandError ? <p role="alert">{commandError}</p> : null}
        </div>
        <div className="competition-workflow-command-actions">
          <button
            className="competition-workflow-command-button is-cancel"
            type="button"
            disabled={readOnly || commandPending}
            onClick={handleCancel}
          >
            <CircleX size={16} aria-hidden="true" />
            取消工作流
          </button>
          <button
            className="competition-workflow-command-button is-retry"
            type="button"
            disabled={readOnly || commandPending || failedStep === null}
            onClick={handleRetry}
          >
            <RotateCcw size={16} aria-hidden="true" />
            重试失败步骤
          </button>
        </div>
      </footer>
    </main>
  );
}
