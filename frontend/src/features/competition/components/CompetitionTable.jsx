import { ArrowRight } from 'lucide-react';

import { StatusBadge } from './CompetitionState.jsx';

const KIND_LABELS = {
  workflow: '工作流',
  result: '结果',
  database: '数据库记录',
};

const STEP_LABELS = {
  relax: '结构优化',
  scf: '自洽计算',
  band: '能带',
  dos: '态密度',
  done: '已完成',
};

function display(value) {
  return value === null || value === undefined || value === '' ? '-' : value;
}

function formatUpdatedAt(value) {
  if (!value) return '-';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'short',
    timeStyle: 'short',
  }).format(parsed);
}

export default function CompetitionTable({ items = [], kind = 'workflow', onOpen }) {
  const kindLabel = KIND_LABELS[kind] || '记录';

  return (
    <div className="competition-table-scroll">
      <table className="competition-table">
        <thead>
          <tr>
            <th>材料</th>
            <th>来源</th>
            <th>状态</th>
            <th>当前步骤</th>
            <th>最新 Job ID</th>
            <th>更新时间</th>
            <th><span className="competition-visually-hidden">操作</span></th>
          </tr>
        </thead>
        <tbody>
          {items.length === 0 ? (
            <tr>
              <td className="competition-table-empty" colSpan={7}>暂无匹配记录</td>
            </tr>
          ) : items.map((item, index) => {
            const material = display(item.material || item.formula);
            const openLabel = `打开${kindLabel}详情：${material}`;
            return (
              <tr key={item.id || item.workflow_id || index}>
                <td><strong>{material}</strong></td>
                <td>{display(item.source)}</td>
                <td><StatusBadge status={item.status} /></td>
                <td>{STEP_LABELS[item.current_step] || display(item.current_step)}</td>
                <td className="competition-table-job">{display(item.latest_job_id)}</td>
                <td><time dateTime={item.updated_at || undefined}>{formatUpdatedAt(item.updated_at)}</time></td>
                <td className="competition-table-action">
                  <button
                    type="button"
                    onClick={() => onOpen?.(item)}
                    disabled={typeof onOpen !== 'function'}
                    title={openLabel}
                    aria-label={openLabel}
                  >
                    <ArrowRight size={16} aria-hidden="true" />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
