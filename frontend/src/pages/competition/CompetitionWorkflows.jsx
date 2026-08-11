import { useCallback } from 'react';
import { Search } from 'lucide-react';
import { useNavigate, useSearchParams } from 'react-router-dom';

import {
  useCompetitionData,
  useCompetitionResource,
} from '../../features/competition/CompetitionDataContext';
import CompetitionTable from '../../features/competition/components/CompetitionTable';
import {
  CompetitionState,
  DemoDataBanner,
} from '../../features/competition/components/CompetitionState';
import './CompetitionPages.css';

function readWorkflowFilters(searchParams) {
  const query = searchParams.get('query') || '';
  const requestedStatus = searchParams.get('status') || 'all';
  const status = ['all', 'running', 'succeeded', 'failed'].includes(requestedStatus)
    ? requestedStatus
    : 'all';
  return { query, status };
}

function writeWorkflowFilters(searchParams, { query, status }) {
  const nextParams = new URLSearchParams(searchParams);
  if (query) nextParams.set('query', query);
  else nextParams.delete('query');
  if (status && status !== 'all') nextParams.set('status', status);
  else nextParams.delete('status');
  return nextParams;
}

export default function CompetitionWorkflows() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { provider, mode } = useCompetitionData();
  const { query, status } = readWorkflowFilters(searchParams);
  const loadWorkflows = useCallback(() => provider.listWorkflows({ query, status }), [provider, query, status]);
  const state = useCompetitionResource(loadWorkflows);

  const updateFilters = useCallback((changes) => {
    const nextFilters = writeWorkflowFilters(searchParams, { query, status, ...changes });
    setSearchParams(nextFilters, { replace: true });
  }, [query, searchParams, setSearchParams, status]);

  const openWorkflow = useCallback((workflow) => {
    if (!workflow?.id) return;
    navigate(`/dashboard/workflows/${encodeURIComponent(workflow.id)}`);
  }, [navigate]);

  const items = Array.isArray(state.data?.items) ? state.data.items : [];

  return (
    <main className="competition-workflows-page">
      {mode === 'demo' ? <DemoDataBanner /> : null}

      <header className="competition-workflows-header">
        <div>
          <h1>工作流</h1>
          <p>按状态检索固定四步 VASP 计算记录</p>
        </div>
      </header>

      <section className="competition-workflows-surface" aria-labelledby="competition-workflows-title">
        <div className="competition-workflow-filters">
          <label className="competition-workflow-search" htmlFor="competition-workflow-query">
            <span>搜索</span>
            <div>
              <Search size={16} aria-hidden="true" />
              <input
                id="competition-workflow-query"
                type="search"
                value={query}
                placeholder="材料、来源或工作流 ID"
                onChange={(event) => updateFilters({ query: event.target.value })}
              />
            </div>
          </label>
          <label className="competition-workflow-status" htmlFor="competition-workflow-status">
            <span>状态</span>
            <select
              id="competition-workflow-status"
              value={status}
              onChange={(event) => updateFilters({ status: event.target.value })}
            >
              <option value="all">全部</option>
              <option value="running">运行中</option>
              <option value="succeeded">已验收</option>
              <option value="failed">失败</option>
            </select>
          </label>
        </div>

        <div className="competition-workflows-heading">
          <h2 id="competition-workflows-title">工作流记录</h2>
          {state.status === 'ready' ? <span>{state.data?.total ?? items.length} 条</span> : null}
        </div>

        {state.status !== 'ready' ? (
          <CompetitionState status={state.status} message={state.error?.message} />
        ) : items.length === 0 ? (
          <CompetitionState status="empty" message="暂无匹配工作流" />
        ) : (
          <CompetitionTable items={items} kind="workflow" onOpen={openWorkflow} />
        )}
      </section>
    </main>
  );
}
