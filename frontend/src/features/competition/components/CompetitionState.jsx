import { FlaskConical, LockKeyhole } from 'lucide-react';

import './competitionComponents.css';

const STATE_PRESENTATION = {
  loading: { title: '正在加载...', className: 'is-loading', role: 'status' },
  empty: { title: '暂无匹配记录', className: 'is-empty', role: 'status' },
  stale: {
    title: '状态陈旧',
    fallback: '显示最后可信状态和更新时间',
    className: 'is-stale',
    role: 'status',
  },
  forbidden: {
    title: '权限不足',
    fallback: '当前身份不能读取此数据',
    className: 'is-error',
    role: 'alert',
  },
  'parse-error': {
    title: '解析失败',
    fallback: '未生成可验收结果',
    className: 'is-error',
    role: 'alert',
  },
  'render-error': {
    title: '渲染失败',
    fallback: '请查看原始数据',
    className: 'is-error',
    role: 'alert',
  },
  error: {
    title: '加载失败',
    fallback: '服务暂时不可用',
    className: 'is-error',
    role: 'alert',
  },
};

const STATUS_LABELS = {
  succeeded: '已验收',
  running: '运行中',
  waiting: '等待',
  queued: '排队中',
  blocked: '已阻断',
  failed: '失败',
  stale: '状态陈旧',
  'parse-error': '解析失败',
  'render-error': '渲染失败',
};

export function DemoDataBanner() {
  return (
    <div className="competition-demo-banner" role="status">
      <FlaskConical size={15} aria-hidden="true" />
      <span>演示数据：不会写入数据库或提交 Slurm 作业</span>
    </div>
  );
}

export function CompetitionState({ status, message }) {
  const presentation = STATE_PRESENTATION[status];
  if (!presentation) return null;

  const detail = message || presentation.fallback;
  return (
    <div
      className={`competition-state ${presentation.className}`}
      role={presentation.role}
    >
      <strong>{presentation.title}</strong>
      {detail ? <span>{detail}</span> : null}
    </div>
  );
}

export function StatusBadge({ status }) {
  const knownStatus = Object.hasOwn(STATUS_LABELS, status) ? status : 'unknown';
  return (
    <span className={`competition-status is-${knownStatus}`}>
      {STATUS_LABELS[status] || status || '未知'}
    </span>
  );
}

export function PreviewReadOnlyNotice() {
  return (
    <p className="competition-readonly-notice">
      <LockKeyhole size={14} aria-hidden="true" />
      <span>预览环境不会写入或提交</span>
    </p>
  );
}
