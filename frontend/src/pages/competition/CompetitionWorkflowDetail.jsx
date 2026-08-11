import { useCallback, useState } from 'react';
import { CircleX, RotateCcw } from 'lucide-react';
import { useParams } from 'react-router-dom';

import { canWriteCompetitionData } from '../../config/competitionAccess';
import {
  useCompetitionData,
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
      && step.status === 'failed'
      && ['relax', 'scf', 'band', 'dos'].includes(step.key)
    ) return step;
  }
  return null;
}

export default function CompetitionWorkflowDetail() {
  const { workflowId } = useParams();
  const { provider, mode } = useCompetitionData();
  const [commandError, setCommandError] = useState('');
  const [commandPending, setCommandPending] = useState(false);
  const user = readStoredUser();
  const readOnly = mode === 'demo' || !canWriteCompetitionData(user);
  const loadWorkflow = useCallback(
    () => (workflowId ? provider.getWorkflow(workflowId) : Promise.resolve(null)),
    [provider, workflowId],
  );
  const state = useCompetitionResource(loadWorkflow);
  const detailState = normalizeWorkflowDetailState(state, workflowId);

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

  const workflow = detailState.workflow;
  const dataKindLabel = workflowDataKindLabel(workflow.data_kind);
  const workflowSteps = Array.isArray(workflow.steps) ? workflow.steps : [];
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
