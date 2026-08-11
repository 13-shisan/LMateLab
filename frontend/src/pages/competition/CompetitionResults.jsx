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

function readResultFilters(searchParams) {
  const query = searchParams.get('query') || '';
  const requestedStatus = searchParams.get('status') || 'all';
  const status = ['all', 'succeeded', 'failed', 'parse-error'].includes(requestedStatus)
    ? requestedStatus
    : 'all';
  return { query, status };
}

function writeResultFilters(searchParams, { query, status }) {
  const nextParams = new URLSearchParams(searchParams);
  if (query) nextParams.set('query', query);
  else nextParams.delete('query');
  if (status && status !== 'all') nextParams.set('status', status);
  else nextParams.delete('status');
  return nextParams;
}

function resultDetailUrl(item) {
  if (item === null || typeof item !== 'object' || Array.isArray(item)) return null;
  const workflowId = [item.id, item.workflow_id].find((value) => (
    typeof value === 'string'
    && value.trim() !== ''
    && value === value.trim()
  ));
  return workflowId ? `/dashboard/results/${encodeURIComponent(workflowId)}` : null;
}

function selectCompletedResults(payload) {
  if (!Array.isArray(payload?.items)) return [];
  return payload.items.filter((item) => (
    item !== null
    && typeof item === 'object'
    && !Array.isArray(item)
    && ['succeeded', 'failed', 'parse-error'].includes(item.status)
  ));
}

export default function CompetitionResults() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { provider, mode } = useCompetitionData();
  const { query, status } = readResultFilters(searchParams);
  const loadResults = useCallback(() => provider.listResults({ query, status }), [provider, query, status]);
  const state = useCompetitionResource(loadResults);

  const updateFilters = useCallback((changes) => {
    const nextFilters = writeResultFilters(searchParams, { query, status, ...changes });
    setSearchParams(nextFilters, { replace: true });
  }, [query, searchParams, setSearchParams, status]);

  const openResult = useCallback((result) => {
    const destination = resultDetailUrl(result);
    if (!destination) return;
    navigate(destination);
  }, [navigate]);

  const items = state.status === 'ready' ? selectCompletedResults(state.data) : [];

  return (
    <main className="competition-results-page">
      {mode === 'demo' ? <DemoDataBanner /> : null}

      <header className="competition-results-header">
        <div>
          <h1>计算结果</h1>
          <p>查看已完成结果、解析失败记录和可核验失败证据</p>
        </div>
      </header>

      <section className="competition-results-surface" aria-labelledby="competition-results-title">
        <div className="competition-result-filters">
          <label className="competition-result-search" htmlFor="competition-result-query">
            <span>搜索</span>
            <div>
              <Search size={16} aria-hidden="true" />
              <input
                id="competition-result-query"
                type="search"
                value={query}
                placeholder="材料、来源或工作流 ID"
                onChange={(event) => updateFilters({ query: event.target.value })}
              />
            </div>
          </label>
          <label className="competition-result-status" htmlFor="competition-result-status">
            <span>状态</span>
            <select
              id="competition-result-status"
              value={status}
              onChange={(event) => updateFilters({ status: event.target.value })}
            >
              <option value="all">全部</option>
              <option value="succeeded">已验收</option>
              <option value="failed">失败</option>
              <option value="parse-error">解析失败</option>
            </select>
          </label>
        </div>

        <div className="competition-results-heading">
          <h2 id="competition-results-title">结果记录</h2>
          {state.status === 'ready' ? <span>{items.length} 条可信结果记录</span> : null}
        </div>

        {state.status !== 'ready' ? (
          <CompetitionState status={state.status} message={state.error?.message} />
        ) : items.length === 0 ? (
          <CompetitionState status="empty" message="暂无匹配结果" />
        ) : (
          <CompetitionTable items={items} kind="result" onOpen={openResult} />
        )}
      </section>
    </main>
  );
}
