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

async function executeWorkflowCommand({ mode, user, write }) {
  if (mode !== 'live' || !canWriteCompetitionData(user)) return false;
  await write();
  return true;
}

function displayIdentity(value) {
  return value === null || value === undefined || value === '' ? '-' : value;
}

function workflowDataKindLabel(dataKind) {
  return dataKind === 'demo' ? '演示数据' : '真实数据';
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
  return { status: 'ready', message: undefined, workflow };
}

export default function CompetitionWorkflowDetail() {
  const { workflowId } = useParams();
  const { provider, mode } = useCompetitionData();
  const [commandError, setCommandError] = useState('');
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
  const failedStep = workflowSteps.find((step) => step?.status === 'failed') || null;

  async function handleCancel() {
    setCommandError('');
    try {
      await executeWorkflowCommand({
        mode,
        user,
        write: () => provider.cancelWorkflow(workflow.id),
      });
    } catch (error) {
      setCommandError(error?.message || '工作流取消失败');
    }
  }

  async function handleRetry() {
    setCommandError('');
    if (failedStep === null) return;
    try {
      await executeWorkflowCommand({
        mode,
        user,
        write: () => provider.retryWorkflow({ id: workflow.id, step: failedStep.key }),
      });
    } catch (error) {
      setCommandError(error?.message || '工作流重试失败');
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
            disabled={readOnly}
            onClick={handleCancel}
          >
            <CircleX size={16} aria-hidden="true" />
            取消工作流
          </button>
          <button
            className="competition-workflow-command-button is-retry"
            type="button"
            disabled={readOnly || failedStep === null}
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
