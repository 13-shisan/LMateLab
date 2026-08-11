import { useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Database,
  SquarePlus,
} from 'lucide-react';

import {
  useCompetitionData,
  useCompetitionResource,
} from '../features/competition/CompetitionDataContext';
import CompetitionTable from '../features/competition/components/CompetitionTable';
import {
  CompetitionState,
  DemoDataBanner,
} from '../features/competition/components/CompetitionState';
import WorkflowTimeline from '../features/competition/components/WorkflowTimeline';
import './Dashboard.css';


export default function CompetitionDashboard() {
  const navigate = useNavigate();
  const { provider, mode } = useCompetitionData();
  const loadDashboard = useCallback(() => provider.getDashboard(), [provider]);
  const state = useCompetitionResource(loadDashboard);
  const openWorkflow = useCallback((workflow) => {
    if (!workflow?.id) return;
    navigate(`/dashboard/workflows/${encodeURIComponent(workflow.id)}`);
  }, [navigate]);

  if (state.status !== 'ready') {
    return (
      <main className="competition-page">
        {mode === 'demo' ? <DemoDataBanner /> : null}
        <CompetitionState status={state.status} message={state.error?.message} />
      </main>
    );
  }

  const {
    summary = {},
    recent_workflows = [],
    active_workflow = null,
    slurm = {},
  } = state.data || {};

  return (
    <main className="competition-page">
      {mode === 'demo' ? <DemoDataBanner /> : null}

      <header className="lm-dashboard-welcome">
        <div>
          <h2>107 杯 VASP 计算工作台</h2>
          <p>结构到 BAND/DOS 的固定可追溯闭环</p>
        </div>
        <Link
          className="lm-primary-action"
          to="/dashboard/calculations/new"
          aria-label="新建计算"
          title="新建计算"
        >
          <SquarePlus size={17} aria-hidden="true" />
          <span>新建计算</span>
        </Link>
      </header>

      <section className="lm-overview-grid" aria-label="工作流概览">
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>总工作流</span>
            <span className="lm-overview-icon"><Database size={16} aria-hidden="true" /></span>
          </div>
          <strong>{summary.total ?? '-'}</strong>
          <small>已记录工作流</small>
        </article>
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>运行中</span>
            <span className="lm-overview-icon"><Activity size={16} aria-hidden="true" /></span>
          </div>
          <strong>{summary.running ?? '-'}</strong>
          <small>当前计算</small>
        </article>
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>最近成功</span>
            <span className="lm-overview-icon"><CheckCircle2 size={16} aria-hidden="true" /></span>
          </div>
          <strong>{summary.recent_succeeded ?? '-'}</strong>
          <small>近期验收记录</small>
        </article>
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>需关注</span>
            <span className="lm-overview-icon"><AlertTriangle size={16} aria-hidden="true" /></span>
          </div>
          <strong>{summary.needs_attention ?? '-'}</strong>
          <small>失败或阻断</small>
        </article>
      </section>

      <section className="lm-dashboard-grid competition-dashboard-grid">
        <section className="competition-dashboard-band">
          <div className="competition-band-header">
            <h3>最近工作流</h3>
            <p>按最近更新时间排列</p>
          </div>
          <CompetitionTable items={recent_workflows} kind="workflow" onOpen={openWorkflow} />
        </section>

        <aside className="competition-dashboard-band competition-active-workflow">
          <div className="competition-band-header">
            <h3>当前工作流</h3>
            <p>{active_workflow?.material || '固定四步计算状态'}</p>
          </div>
          {active_workflow ? (
            <WorkflowTimeline steps={active_workflow.steps} compact />
          ) : (
            <CompetitionState status="empty" message="暂无当前工作流" />
          )}
        </aside>
      </section>

      <section className="competition-slurm-summary" aria-labelledby="competition-slurm-title">
        <div className="competition-slurm-header">
          <h3 id="competition-slurm-title">Slurm 资源</h3>
          {mode === 'demo' ? <span className="competition-slurm-snapshot">演示快照</span> : null}
        </div>
        <dl className="competition-slurm-details">
          <div>
            <dt>Partition</dt>
            <dd>{slurm.partition ?? '-'}</dd>
          </div>
          <div>
            <dt>排队 / 运行</dt>
            <dd>{slurm.queued ?? '-'} / {slurm.running ?? '-'}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>{mode === 'demo' ? '演示快照' : (slurm.state ?? '-')}</dd>
          </div>
          <div>
            <dt>最近更新时间</dt>
            <dd><time dateTime={slurm.updated_at || undefined}>{slurm.updated_at ?? '-'}</time></dd>
          </div>
        </dl>
      </section>
    </main>
  );
}
