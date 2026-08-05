import { useEffect, useMemo, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  RefreshCw,
  Server,
  Cpu,
  MemoryStick,
  HardDrive,
  Users,
  Boxes,
  Activity,
  Monitor,
  Layers3,
} from 'lucide-react';
import api from '../../api/client';
import ServerMonitorLayout from './ServerMonitorLayout';

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  return `${Number(value).toFixed(1)}%`;
}

function formatRatio(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) return '--';
  const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
  let val = Number(bytes);
  let idx = 0;
  while (val >= 1024 && idx < units.length - 1) {
    val /= 1024;
    idx += 1;
  }
  return `${val.toFixed(val >= 10 ? 1 : 2)} ${units[idx]}`;
}

function formatDateTime(text) {
  if (!text) return '--';
  const d = new Date(text);
  if (Number.isNaN(d.getTime())) return text;
  return d.toLocaleString('zh-CN', { hour12: false });
}

function StateBadge({ state }) {
  const s = String(state || '').toUpperCase();

  let bg = '#eef2ff';
  let color = '#4338ca';

  if (s === 'R' || s === 'RUNNING') {
    bg = '#dcfce7';
    color = '#166534';
  } else if (s === 'Q' || s === 'PENDING') {
    bg = '#fef3c7';
    color = '#92400e';
  } else if (s === 'C' || s === 'COMPLETED') {
    bg = '#e5e7eb';
    color = '#374151';
  } else if (s === 'E' || s === 'FAILED') {
    bg = '#fee2e2';
    color = '#b91c1c';
  }

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 10px',
        borderRadius: '999px',
        fontSize: 12,
        fontWeight: 600,
        background: bg,
        color,
        whiteSpace: 'nowrap',
      }}
    >
      {state || '--'}
    </span>
  );
}

function OverviewCard({ icon: Icon, title, value, subtext }) {
  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e5e7eb',
        borderRadius: 16,
        padding: 18,
        boxShadow: '0 4px 14px rgba(15, 23, 42, 0.04)',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: 10,
        }}
      >
        <div style={{ color: '#6b7280', fontSize: 14, fontWeight: 600 }}>{title}</div>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 10,
            background: '#f3f4f6',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#111827',
          }}
        >
          <Icon size={18} />
        </div>
      </div>

      <div style={{ fontSize: 28, fontWeight: 700, color: '#111827', lineHeight: 1.2 }}>
        {value}
      </div>

      <div style={{ marginTop: 6, color: '#6b7280', fontSize: 13 }}>
        {subtext || ' '}
      </div>
    </div>
  );
}

function SectionCard({ title, subtitle, children, right }) {
  return (
    <section
      style={{
        background: '#fff',
        borderRadius: 16,
        border: '1px solid #e5e7eb',
        overflow: 'hidden',
        marginBottom: 24,
      }}
    >
      <div
        style={{
          padding: '18px 20px',
          borderBottom: '1px solid #e5e7eb',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div style={{ fontSize: 18, fontWeight: 700, color: '#111827' }}>{title}</div>
          {subtitle ? (
            <div style={{ marginTop: 4, fontSize: 13, color: '#6b7280' }}>{subtitle}</div>
          ) : null}
        </div>
        {right || null}
      </div>

      <div>{children}</div>
    </section>
  );
}

function BlockTitle({ title, subtitle }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontSize: 22, fontWeight: 800, color: '#111827' }}>{title}</div>
      {subtitle ? (
        <div style={{ marginTop: 6, fontSize: 14, color: '#6b7280' }}>{subtitle}</div>
      ) : null}
    </div>
  );
}

function UsageProgressBar({ percent }) {
  const value = Number(percent);
  const safeValue = Number.isNaN(value) ? 0 : Math.max(0, Math.min(100, value));

  let color = '#22c55e';
  if (safeValue >= 85) {
    color = '#ef4444';
  } else if (safeValue >= 70) {
    color = '#f59e0b';
  }

  return (
    <div style={{ minWidth: 180 }}>
      <div
        style={{
          height: 8,
          background: '#e5e7eb',
          borderRadius: 999,
          overflow: 'hidden',
          marginBottom: 6,
        }}
      >
        <div
          style={{
            width: `${safeValue}%`,
            height: '100%',
            background: color,
            borderRadius: 999,
          }}
        />
      </div>
      <div style={{ fontSize: 12, color: '#6b7280' }}>{safeValue.toFixed(1)}%</div>
    </div>
  );
}

function GpuBusyBadge({ busy }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 10px',
        borderRadius: '999px',
        fontSize: 12,
        fontWeight: 600,
        background: busy ? '#dcfce7' : '#f3f4f6',
        color: busy ? '#166534' : '#6b7280',
        whiteSpace: 'nowrap',
      }}
    >
      {busy ? '忙碌' : '空闲'}
    </span>
  );
}

function ReviewBadge({ reviewed }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        padding: '2px 10px',
        borderRadius: '999px',
        fontSize: 12,
        fontWeight: 600,
        background: reviewed ? '#dcfce7' : '#fef3c7',
        color: reviewed ? '#166534' : '#92400e',
        whiteSpace: 'nowrap',
      }}
    >
      {reviewed ? '已复核' : '未复核'}
    </span>
  );
}

function QueueTagList({ queues }) {
  const items = Array.isArray(queues) ? queues : [];
  if (items.length === 0) {
    return <span style={{ color: '#6b7280' }}>--</span>;
  }

  return (
    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
      {items.map((q) => (
        <span
          key={q}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            padding: '2px 10px',
            borderRadius: '999px',
            fontSize: 12,
            fontWeight: 600,
            background: '#eff6ff',
            color: '#1d4ed8',
            whiteSpace: 'nowrap',
          }}
        >
          {q}
        </span>
      ))}
    </div>
  );
}


export default function ServerMonitorPage() {
  const { serverName = 'Dell' } = useParams();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [data, setData] = useState(null);
  const [activeTab, setActiveTab] = useState('scheduler');
  const [usageRange, setUsageRange] = useState('7d');
  const [usageLoading, setUsageLoading] = useState(false);
  const [usageError, setUsageError] = useState('');
  const [usageData, setUsageData] = useState(null);
  const [nodePage, setNodePage] = useState(1);

  const [userLimitsLoading, setUserLimitsLoading] = useState(false);
  const [userLimitsError, setUserLimitsError] = useState('');
  const [userLimitsData, setUserLimitsData] = useState(null);
  const [expandedLimitUsers, setExpandedLimitUsers] = useState({});

  const fetchData = async (silent = false) => {
    if (silent) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    setError('');
    try {
      const res = await api.get(`/server-monitor/status/${serverName}`);
      setData(res.data);
      setNodePage(1);
    } catch (e) {
      console.error(e);
      setError(e?.response?.data?.detail || e?.response?.data?.error || '获取服务器监控数据失败');
      setData(null);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const fetchUsage = async (rangeValue = usageRange) => {
    setUsageLoading(true);
    setUsageError('');

    try {
      const res = await api.get(`/server-monitor/usage/${serverName}?range=${rangeValue}`);
      setUsageData(res.data);
    } catch (e) {
      console.error(e);
      setUsageError(e?.response?.data?.detail || e?.response?.data?.error || '获取服务器使用分析失败');
      setUsageData(null);
    } finally {
      setUsageLoading(false);
    }
  };

  const fetchUserLimits = async () => {
    setUserLimitsLoading(true);
    setUserLimitsError('');

    try {
      const res = await api.get(`/server-monitor/user-limits/${serverName}`);
      setUserLimitsData(res.data);
      setExpandedLimitUsers({});
    } catch (e) {
      console.error(e);
      setUserLimitsError(e?.response?.data?.detail || e?.response?.data?.error || '当前服务器暂无权限配置数据');
      setUserLimitsData(null);
    } finally {
      setUserLimitsLoading(false);
    }
  };

  const toggleLimitUserExpand = (username) => {
    setExpandedLimitUsers((prev) => ({
      ...prev,
      [username]: !prev[username],
    }));
  };

  const overview = data?.overview || {};
  const host = data?.host || {};
  const scheduler = data?.scheduler || {};
  const serverDisplayName = data?.display_name || serverName;
  const jobs = scheduler?.jobs || [];
  const systemProcesses = data?.system_processes || [];
  const platformTasks = data?.platform_tasks || [];
  const gpu = overview?.gpu || {};
  const gpuDetail = data?.gpu_detail || {};
  const gpuItems = gpuDetail?.items || [];
  const diskMounts = overview?.disk_mounts || [];
  const queueStats = scheduler?.queue_stats || [];
  const nodesInfo = scheduler?.nodes || {};
  const nodeItems = nodesInfo?.items || [];
  const NODE_PAGE_SIZE = 10;
  const nodeTotalPages = Math.max(1, Math.ceil(nodeItems.length / NODE_PAGE_SIZE));

  const pagedNodeItems = useMemo(() => {
    const start = (nodePage - 1) * NODE_PAGE_SIZE;
    const end = start + NODE_PAGE_SIZE;
    return nodeItems.slice(start, end);
  }, [nodeItems, nodePage]);

  const usageOverview = usageData?.overview || {};
  const usageUserStats = usageData?.user_stats || [];
  const usageNodeStats = usageData?.node_stats || [];
  const usageQueueStats = usageData?.queue_stats || [];

  const userLimitsMeta = userLimitsData || {};
  const userLimitUsers = userLimitsData?.users || [];

  useEffect(() => {
    fetchData(false);
  }, [serverName]);

  useEffect(() => {
    fetchUsage(usageRange);
  }, [serverName, usageRange]);

  useEffect(() => {
    fetchUserLimits();
  }, [serverName]);

  useEffect(() => {
    setExpandedLimitUsers({});
  }, [serverName]);

  useEffect(() => {
    setNodePage(1);
  }, [serverName, data]);

  useEffect(() => {
    if (nodePage > nodeTotalPages) {
      setNodePage(nodeTotalPages);
    }
  }, [nodePage, nodeTotalPages]);

  const tabItems = useMemo(() => {
    return [
      { key: 'scheduler', label: `调度队列作业 (${jobs.length})` },
      { key: 'system', label: `系统进程 (${systemProcesses.length})` },
      { key: 'platform', label: `平台内部任务 (${platformTasks.length})` },
    ];
  }, [jobs.length, systemProcesses.length, platformTasks.length]);

  const currentRows = useMemo(() => {
    if (activeTab === 'system') return systemProcesses;
    if (activeTab === 'platform') return platformTasks;
    return jobs;
  }, [activeTab, jobs, systemProcesses, platformTasks]);

  return (
    <ServerMonitorLayout
      currentPath={`/dashboard/server-monitor/${serverName}`}
      currentServerKey={serverName}
    >
      <section
        style={{
          background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 100%)',
          color: '#fff',
          borderRadius: 20,
          padding: '28px 30px',
          marginBottom: 24,
          boxShadow: '0 10px 30px rgba(15, 23, 42, 0.18)',
        }}
      >
        <div
          style={{
            display: 'flex',
            gap: 16,
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
          }}
        >
          <div>
            <div style={{ fontSize: 13, letterSpacing: 1.2, opacity: 0.8, marginBottom: 10 }}>
              SERVER MONITOR
            </div>
            <h1 style={{ margin: 0, fontSize: 32, lineHeight: 1.2 }}>
              {serverDisplayName} 服务器监控
            </h1>
            <p style={{ margin: '10px 0 0', color: 'rgba(255,255,255,0.82)', fontSize: 15 }}>
              展示服务器资源概览、调度队列作业、节点状态、磁盘挂载点与队列统计。
            </p>

            <div
              style={{
                display: 'flex',
                gap: 10,
                flexWrap: 'wrap',
                marginTop: 16,
              }}
            >
              <span style={heroBadgeStyle}>
                <Server size={14} />
                主机：{host?.hostname || '--'}
              </span>

              <span style={heroBadgeStyle}>
                <Activity size={14} />
                调度器：{scheduler?.type || '--'}
              </span>

              <span style={heroBadgeStyle}>
                <RefreshCw size={14} />
                更新时间：{formatDateTime(data?.updated_at)}
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={() => fetchData(true)}
            disabled={refreshing}
            style={{
              border: 'none',
              borderRadius: 12,
              padding: '12px 16px',
              background: '#fff',
              color: '#111827',
              fontWeight: 600,
              cursor: refreshing ? 'not-allowed' : 'pointer',
              opacity: refreshing ? 0.7 : 1,
              display: 'inline-flex',
              alignItems: 'center',
              gap: 8,
            }}
          >
            <RefreshCw size={16} />
            {refreshing ? '刷新中...' : '刷新数据'}
          </button>
        </div>
      </section>

      {loading ? (
        <div
          style={{
            background: '#fff',
            borderRadius: 16,
            padding: 40,
            textAlign: 'center',
            color: '#6b7280',
            border: '1px solid #e5e7eb',
          }}
        >
          正在加载 {serverDisplayName} 服务器监控数据...
        </div>
      ) : error ? (
        <div
          style={{
            background: '#fff',
            borderRadius: 16,
            padding: 24,
            border: '1px solid #fecaca',
            color: '#b91c1c',
          }}
        >
          {serverDisplayName} 监控数据加载失败：{error}
        </div>
      ) : !data ? (
        <div
          style={{
            background: '#fff',
            borderRadius: 16,
            padding: 24,
            border: '1px solid #e5e7eb',
            color: '#6b7280',
          }}
        >
          当前服务器暂无监控数据。
        </div>
      ) : (
        <>
          <section style={{ marginBottom: 32 }}>
            <BlockTitle
              title="服务器资源"
              subtitle="展示当前服务器资源概览与磁盘挂载使用情况。"
            />

            <section style={{ marginBottom: 24 }}>
              <div style={{ marginBottom: 12, fontSize: 18, fontWeight: 700, color: '#111827' }}>
                资源概览
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  gap: 16,
                }}
              >
                <OverviewCard
                  icon={Cpu}
                  title="CPU 使用率"
                  value={formatPercent(overview.cpu_percent)}
                  subtext="当前宿主机 CPU 总体占用"
                />
                <OverviewCard
                  icon={MemoryStick}
                  title="内存使用率"
                  value={formatPercent(overview.memory_percent)}
                  subtext={`${formatBytes(overview.memory_used)} / ${formatBytes(overview.memory_total)}`}
                />
                <OverviewCard
                  icon={HardDrive}
                  title="系统盘 / 使用率"
                  value={formatPercent(overview.disk_percent)}
                  subtext={`${formatBytes(overview.disk_used)} / ${formatBytes(overview.disk_total)}`}
                />
                <OverviewCard
                  icon={Users}
                  title="当前登录用户数"
                  value={overview.logged_in_users ?? '--'}
                  subtext={`唯一用户 ${overview.logged_in_users ?? '--'} / 登录会话 ${overview.logged_in_session_count ?? '--'}`}
                />
                <OverviewCard
                  icon={Boxes}
                  title="当前运行任务数"
                  value={overview.running_task_count ?? '--'}
                  subtext="来自调度系统的运行中作业数量"
                />
                <OverviewCard
                  icon={Monitor}
                  title="当前活跃节点数"
                  value={overview.node_count ?? '--'}
                  subtext="当前参与作业运行的计算节点数"
                />
                <OverviewCard
                  icon={Layers3}
                  title="节点总数"
                  value={overview.node_total ?? '--'}
                  subtext={`忙碌 ${overview.node_busy ?? '--'} / 空闲 ${overview.node_free ?? '--'} / 宕机 ${overview.node_down ?? '--'}`}
                />
                <OverviewCard
                  icon={Server}
                  title="GPU 总数"
                  value={gpu.total ?? 0}
                  subtext={
                    gpu.available
                      ? `忙碌 ${gpu.busy ?? 0} / 空闲 ${gpu.idle ?? '--'}`
                      : '当前未检测到 GPU'
                  }
                />
              </div>
            </section>

            <SectionCard
              title="磁盘挂载点"
              subtitle="相比只看系统盘，这里更适合观察 /home、/data、/storage 的真实使用情况。"
            >
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
                  <thead>
                    <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                      <th style={thStyle}>挂载点</th>
                      <th style={thStyle}>使用率</th>
                      <th style={thStyle}>已用</th>
                      <th style={thStyle}>总量</th>
                      <th style={thStyle}>剩余</th>
                    </tr>
                  </thead>
                  <tbody>
                    {diskMounts.length === 0 ? (
                      <tr>
                        <td colSpan={5} style={emptyTdStyle}>暂无磁盘挂载点数据</td>
                      </tr>
                    ) : (
                      diskMounts.map((item, idx) => (
                        <tr key={item.mount || idx} style={{ borderTop: '1px solid #f1f5f9' }}>
                          <td style={tdStyle}>{item.mount || '--'}</td>
                          <td style={tdStyle}>
                            {item.error ? '获取失败' : <UsageProgressBar percent={item.percent} />}
                          </td>
                          <td style={tdStyle}>{item.error ? '--' : formatBytes(item.used)}</td>
                          <td style={tdStyle}>{item.error ? '--' : formatBytes(item.total)}</td>
                          <td style={tdStyle}>{item.error ? '--' : formatBytes(item.free)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </SectionCard>

            {gpu.available ? (
              <SectionCard
                title="GPU 详情"
                subtitle="展示每张 GPU 的利用率、显存使用、温度、功耗与当前是否忙碌。"
              >
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 1080 }}>
                    <thead>
                      <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                        <th style={thStyle}>GPU</th>
                        <th style={thStyle}>型号</th>
                        <th style={thStyle}>状态</th>
                        <th style={thStyle}>利用率</th>
                        <th style={thStyle}>显存使用</th>
                        <th style={thStyle}>显存占比</th>
                        <th style={thStyle}>温度</th>
                        <th style={thStyle}>功耗</th>
                        <th style={thStyle}>进程数</th>
                      </tr>
                    </thead>
                    <tbody>
                      {gpuItems.length === 0 ? (
                        <tr>
                          <td colSpan={9} style={emptyTdStyle}>暂无 GPU 明细数据</td>
                        </tr>
                      ) : (
                        gpuItems.map((item, idx) => (
                          <tr key={item.uuid || item.index || idx} style={{ borderTop: '1px solid #f1f5f9' }}>
                            <td style={tdStyle}>{item.index ?? '--'}</td>
                            <td style={tdStyle}>{item.name || '--'}</td>
                            <td style={tdStyle}>
                              <GpuBusyBadge busy={item.is_busy} />
                            </td>
                            <td style={tdStyle}>
                              {item.utilization_gpu !== undefined && item.utilization_gpu !== null
                                ? `${item.utilization_gpu}%`
                                : '--'}
                            </td>
                            <td style={tdStyle}>
                              {item.memory_used_mb !== undefined && item.memory_total_mb !== undefined
                                ? `${item.memory_used_mb} MB / ${item.memory_total_mb} MB`
                                : '--'}
                            </td>
                            <td style={tdStyle}>{formatRatio(item.memory_used_ratio)}</td>
                            <td style={tdStyle}>
                              {item.temperature_c !== undefined && item.temperature_c !== null
                                ? `${item.temperature_c} °C`
                                : '--'}
                            </td>
                            <td style={tdStyle}>
                              {item.power_draw_w !== undefined && item.power_draw_w !== null
                                ? `${item.power_draw_w} W`
                                : '--'}
                            </td>
                            <td style={tdStyle}>{item.process_count ?? 0}</td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </SectionCard>
            ) : null}
          </section>

          <section style={{ marginBottom: 32 }}>
            <BlockTitle
              title="实时信息"
              subtitle="直接基于当前监控快照文件展示队列、节点与任务明细。"
            />

            <SectionCard
              title="队列统计"
              subtitle="当前快照中的队列任务分布，包括总任务数、运行中、排队中与活跃用户数。"
            >
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 860 }}>
                  <thead>
                    <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                      <th style={thStyle}>队列</th>
                      <th style={thStyle}>总任务数</th>
                      <th style={thStyle}>运行中</th>
                      <th style={thStyle}>排队中</th>
                      <th style={thStyle}>其他状态</th>
                      <th style={thStyle}>活跃用户数</th>
                      <th style={thStyle}>排队比例</th>
                    </tr>
                  </thead>
                  <tbody>
                    {queueStats.length === 0 ? (
                      <tr>
                        <td colSpan={7} style={emptyTdStyle}>暂无队列统计数据</td>
                      </tr>
                    ) : (
                      queueStats.map((item, idx) => (
                        <tr key={`${item.queue}-${idx}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                          <td style={tdStyle}>{item.queue || '--'}</td>
                          <td style={tdStyle}>{item.total_jobs ?? '--'}</td>
                          <td style={tdStyle}>{item.running_jobs ?? '--'}</td>
                          <td style={tdStyle}>{item.queued_jobs ?? '--'}</td>
                          <td style={tdStyle}>{item.other_jobs ?? '--'}</td>
                          <td style={tdStyle}>{item.active_users ?? '--'}</td>
                          <td style={tdStyle}>{formatRatio(item.queue_ratio)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </SectionCard>

            <SectionCard
              title="节点详情"
              subtitle="展示总节点、忙碌节点、空闲节点，以及节点状态和对应标签/队列。"
              right={
                <div style={{ fontSize: 13, color: '#6b7280' }}>
                  总节点 {nodesInfo?.total ?? 0} / 忙碌 {nodesInfo?.busy ?? 0} / 空闲 {nodesInfo?.free ?? 0} / 宕机 {nodesInfo?.down ?? 0}
                </div>
              }
            >
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 980 }}>
                  <thead>
                    <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                      <th style={thStyle}>节点名</th>
                      <th style={thStyle}>状态</th>
                      <th style={thStyle}>队列/标签</th>
                      <th style={thStyle}>NP</th>
                      <th style={thStyle}>PCPUs</th>
                      <th style={thStyle}>Properties</th>
                      <th style={thStyle}>Jobs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nodeItems.length === 0 ? (
                      <tr>
                        <td colSpan={7} style={emptyTdStyle}>暂无节点详情数据</td>
                      </tr>
                    ) : (
                      pagedNodeItems.map((node, idx) => (
                        <tr key={node.name || `${nodePage}-${idx}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                          <td style={tdStyle}>{node.name || '--'}</td>
                          <td style={tdStyle}>{node.state || '--'}</td>
                          <td style={tdStyle}>{node.queue || '--'}</td>
                          <td style={tdStyle}>{node.np || '--'}</td>
                          <td style={tdStyle}>{node.pcpus || '--'}</td>
                          <td style={tdStyle}>{node.properties || '--'}</td>
                          <td style={tdStyle}>
                            <div
                              title={node.jobs || '--'}
                              style={{
                                maxWidth: 280,
                                whiteSpace: 'nowrap',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                              }}
                            >
                              {node.jobs || '--'}
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {nodeItems.length > 0 ? (
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    padding: '16px 20px 20px',
                    gap: 12,
                    flexWrap: 'wrap',
                  }}
                >
                  <div style={{ fontSize: 13, color: '#6b7280' }}>
                    第 {nodePage} / {nodeTotalPages} 页，每页 {NODE_PAGE_SIZE} 条，共 {nodeItems.length} 条
                  </div>

                  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <button
                      type="button"
                      onClick={() => setNodePage((p) => Math.max(1, p - 1))}
                      disabled={nodePage <= 1}
                      style={{
                        border: '1px solid #d1d5db',
                        background: nodePage <= 1 ? '#f9fafb' : '#fff',
                        color: nodePage <= 1 ? '#9ca3af' : '#374151',
                        borderRadius: 10,
                        padding: '8px 14px',
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: nodePage <= 1 ? 'not-allowed' : 'pointer',
                      }}
                    >
                      上一页
                    </button>

                    <button
                      type="button"
                      onClick={() => setNodePage((p) => Math.min(nodeTotalPages, p + 1))}
                      disabled={nodePage >= nodeTotalPages}
                      style={{
                        border: '1px solid #d1d5db',
                        background: nodePage >= nodeTotalPages ? '#f9fafb' : '#fff',
                        color: nodePage >= nodeTotalPages ? '#9ca3af' : '#374151',
                        borderRadius: 10,
                        padding: '8px 14px',
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: nodePage >= nodeTotalPages ? 'not-allowed' : 'pointer',
                      }}
                    >
                      下一页
                    </button>
                  </div>
                </div>
              ) : null}
            </SectionCard>

            <section
              style={{
                background: '#fff',
                borderRadius: 16,
                border: '1px solid #e5e7eb',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  padding: '18px 20px',
                  borderBottom: '1px solid #e5e7eb',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 12,
                  flexWrap: 'wrap',
                }}
              >
                <div>
                  <div style={{ fontSize: 18, fontWeight: 700, color: '#111827' }}>
                    当前任务列表
                  </div>
                  <div style={{ marginTop: 4, fontSize: 13, color: '#6b7280' }}>
                    刷新按钮会重新拉取后端当前监控快照；如果后端按 cron 定时采集，这里展示的是最近一次生成的数据。
                  </div>
                </div>

                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {tabItems.map((tab) => (
                    <button
                      key={tab.key}
                      type="button"
                      onClick={() => setActiveTab(tab.key)}
                      style={{
                        border: activeTab === tab.key ? '1px solid #2563eb' : '1px solid #d1d5db',
                        background: activeTab === tab.key ? '#eff6ff' : '#fff',
                        color: activeTab === tab.key ? '#1d4ed8' : '#374151',
                        borderRadius: 10,
                        padding: '8px 14px',
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>
              </div>

              {activeTab === 'scheduler' ? (
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 980 }}>
                    <thead>
                      <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                        <th style={thStyle}>Job ID</th>
                        <th style={thStyle}>用户</th>
                        <th style={thStyle}>作业名</th>
                        <th style={thStyle}>状态</th>
                        <th style={thStyle}>队列</th>
                        <th style={thStyle}>节点</th>
                        <th style={thStyle}>已用时长</th>
                        <th style={thStyle}>工作目录</th>
                      </tr>
                    </thead>
                    <tbody>
                      {currentRows.length === 0 ? (
                        <tr>
                          <td colSpan={8} style={emptyTdStyle}>
                            当前没有调度作业数据
                          </td>
                        </tr>
                      ) : (
                        currentRows.map((job, idx) => (
                          <tr key={job.job_id || idx} style={{ borderTop: '1px solid #f1f5f9' }}>
                            <td style={tdStyle}>{job.job_id || '--'}</td>
                            <td style={tdStyle}>{job.user || '--'}</td>
                            <td style={tdStyle}>{job.name || '--'}</td>
                            <td style={tdStyle}>
                              <StateBadge state={job.state} />
                            </td>
                            <td style={tdStyle}>{job.queue || job.partition || '--'}</td>
                            <td style={tdStyle}>{job.node || job.exec_host || job.node_or_reason || '--'}</td>
                            <td style={tdStyle}>{job.walltime_used || job.elapsed || '--'}</td>
                            <td style={tdStyle}>
                              <div
                                title={job.workdir || '--'}
                                style={{
                                  maxWidth: 320,
                                  whiteSpace: 'nowrap',
                                  overflow: 'hidden',
                                  textOverflow: 'ellipsis',
                                }}
                              >
                                {job.workdir || '--'}
                              </div>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div style={{ padding: 28, color: '#6b7280', fontSize: 14 }}>
                  {activeTab === 'system'
                    ? '系统进程区域已预留，后续接入宿主机进程采集后即可展示。'
                    : '平台内部任务区域已预留，后续接入 Celery / 平台任务状态后即可展示。'}
                </div>
              )}
            </section>
          </section>

          <section style={{ marginBottom: 32 }}>
            <BlockTitle
              title="权限信息"
              subtitle="展示管理员维护或自动采集生成的用户资源上限配置，包括全局限制与队列级限制。"
            />

            <SectionCard
              title="用户权限概览"
              subtitle="用于说明每个用户可使用的队列以及最大节点数、核数、运行任务数等限制。"
              right={
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <ReviewBadge reviewed={userLimitsMeta?.reviewed} />
                  <span style={{ fontSize: 13, color: '#6b7280' }}>
                    来源：{userLimitsMeta?.source || '--'}
                  </span>
                  <span style={{ fontSize: 13, color: '#6b7280' }}>
                    更新时间：{formatDateTime(userLimitsMeta?.updated_at)}
                  </span>
                </div>
              }
            >
              {userLimitsLoading ? (
                <div style={{ padding: 28, color: '#6b7280', fontSize: 14 }}>
                  正在加载用户权限配置...
                </div>
              ) : userLimitsError ? (
                <div style={{ padding: 28, color: '#6b7280', fontSize: 14 }}>
                  {userLimitsError}
                </div>
              ) : !userLimitsData ? (
                <div style={{ padding: 28, color: '#6b7280', fontSize: 14 }}>
                  当前服务器暂无用户权限配置数据。
                </div>
              ) : (
                <div style={{ padding: 20 }}>
                  <div style={{ marginBottom: 16, fontSize: 14, color: '#6b7280' }}>
                    {userLimitsMeta?.description || '暂无描述'}
                    <div style={{ marginTop: 6 }}>
                      复核人：{userLimitsMeta?.reviewed_by || '--'} / 复核时间：{formatDateTime(userLimitsMeta?.reviewed_at)}
                    </div>
                  </div>

                  <div style={{ overflowX: 'auto', marginTop: 16 }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: '#111827', marginBottom: 10 }}>
                      用户全局限制
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 1080 }}>
                      <thead>
                        <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                          <th style={thStyle}>用户</th>
                          <th style={thStyle}>状态</th>
                          <th style={thStyle}>可用队列</th>
                          <th style={thStyle}>最大运行任务数</th>
                          <th style={thStyle}>最大排队任务数</th>
                          <th style={thStyle}>最大节点数</th>
                          <th style={thStyle}>最大核数</th>
                          <th style={thStyle}>最大 GPU 数</th>
                          <th style={thStyle}>备注</th>
                          <th style={thStyle}>操作</th>
                        </tr>
                      </thead>
                      <tbody>
                        {userLimitUsers.length === 0 ? (
                          <tr>
                            <td colSpan={10} style={emptyTdStyle}>暂无用户权限数据</td>
                          </tr>
                        ) : (
                          userLimitUsers.flatMap((item, idx) => {
                            const expanded = !!expandedLimitUsers[item.user];
                            const queueCount = (item.queues || []).length;

                            return [
                              (
                                <tr key={`${item.user}-${idx}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                                  <td style={tdStyle}>{item.user || '--'}</td>
                                  <td style={tdStyle}>
                                    <span
                                      style={{
                                        display: 'inline-flex',
                                        alignItems: 'center',
                                        padding: '2px 10px',
                                        borderRadius: '999px',
                                        fontSize: 12,
                                        fontWeight: 600,
                                        background: item.enabled ? '#dcfce7' : '#f3f4f6',
                                        color: item.enabled ? '#166534' : '#6b7280',
                                      }}
                                    >
                                      {item.enabled ? '启用' : '禁用'}
                                    </span>
                                  </td>
                                  <td style={tdStyle}>
                                    <QueueTagList queues={item.available_queues} />
                                  </td>
                                  <td style={tdStyle}>{item.global_limits?.max_total_running_jobs ?? '--'}</td>
                                  <td style={tdStyle}>{item.global_limits?.max_total_queued_jobs ?? '--'}</td>
                                  <td style={tdStyle}>{item.global_limits?.max_total_nodes ?? '--'}</td>
                                  <td style={tdStyle}>{item.global_limits?.max_total_cores ?? '--'}</td>
                                  <td style={tdStyle}>{item.global_limits?.max_total_gpus ?? '--'}</td>
                                  <td style={tdStyle}>{item.remark || '--'}</td>
                                  <td style={tdStyle}>
                                    <button
                                      type="button"
                                      onClick={() => toggleLimitUserExpand(item.user)}
                                      style={{
                                        border: expanded ? '1px solid #2563eb' : '1px solid #d1d5db',
                                        background: expanded ? '#eff6ff' : '#fff',
                                        color: expanded ? '#1d4ed8' : '#374151',
                                        borderRadius: 10,
                                        padding: '6px 12px',
                                        fontSize: 13,
                                        fontWeight: 600,
                                        cursor: 'pointer',
                                        whiteSpace: 'nowrap',
                                      }}
                                    >
                                      {expanded ? '收起详情' : `查看详情${queueCount ? `（${queueCount} 个队列）` : ''}`}
                                    </button>
                                  </td>
                                </tr>
                              ),
                              expanded ? (
                                <tr key={`${item.user}-${idx}-detail`} style={{ background: '#fcfcfd' }}>
                                  <td colSpan={10} style={{ padding: 0 }}>
                                    <div
                                      style={{
                                        padding: '16px 20px 20px',
                                        borderTop: '1px solid #e5e7eb',
                                        background: '#fafafa',
                                      }}
                                    >
                                      <div
                                        style={{
                                          fontSize: 14,
                                          fontWeight: 700,
                                          color: '#111827',
                                          marginBottom: 12,
                                        }}
                                      >
                                        {item.user || '--'} 的队列级限制
                                      </div>

                                      <div style={{ overflowX: 'auto' }}>
                                        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 920, background: '#fff' }}>
                                          <thead>
                                            <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                                              <th style={thStyle}>队列</th>
                                              <th style={thStyle}>最大节点数</th>
                                              <th style={thStyle}>最大核数</th>
                                              <th style={thStyle}>最大运行任务数</th>
                                              <th style={thStyle}>最大排队任务数</th>
                                              <th style={thStyle}>最长运行时间</th>
                                              <th style={thStyle}>最大 GPU 数</th>
                                              <th style={thStyle}>说明</th>
                                            </tr>
                                          </thead>
                                          <tbody>
                                            {(item.queues || []).length === 0 ? (
                                              <tr>
                                                <td colSpan={8} style={emptyTdStyle}>暂无队列权限数据</td>
                                              </tr>
                                            ) : (
                                              (item.queues || []).map((q, qIdx) => (
                                                <tr key={`${item.user}-${q.queue}-${qIdx}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                                                  <td style={tdStyle}>{q.queue || '--'}</td>
                                                  <td style={tdStyle}>{q.max_nodes ?? '--'}</td>
                                                  <td style={tdStyle}>{q.max_cores ?? '--'}</td>
                                                  <td style={tdStyle}>{q.max_running_jobs ?? '--'}</td>
                                                  <td style={tdStyle}>{q.max_queued_jobs ?? '--'}</td>
                                                  <td style={tdStyle}>{q.max_walltime || '--'}</td>
                                                  <td style={tdStyle}>{q.max_gpus ?? '--'}</td>
                                                  <td style={tdStyle}>{q.note || '--'}</td>
                                                </tr>
                                              ))
                                            )}
                                          </tbody>
                                        </table>
                                      </div>
                                    </div>
                                  </td>
                                </tr>
                              ) : null,
                            ];
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </SectionCard>
          </section>

          <section style={{ marginBottom: 32 }}>
            <BlockTitle
              title="历史信息"
              subtitle="基于历史快照聚合所选时间范围内的服务器使用情况，展示用户、节点与队列的长期使用分布。"
            />

            <SectionCard
              title="使用分析"
              subtitle="按近 7 天、1 个月、3 个月、1 年聚合历史快照，用于观察长期使用情况。"
              right={
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {[
                    { key: '7d', label: '近7天' },
                    { key: '30d', label: '近1个月' },
                    { key: '90d', label: '近3个月' },
                    { key: '365d', label: '近1年' },
                  ].map((item) => (
                    <button
                      key={item.key}
                      type="button"
                      onClick={() => setUsageRange(item.key)}
                      style={{
                        border: usageRange === item.key ? '1px solid #2563eb' : '1px solid #d1d5db',
                        background: usageRange === item.key ? '#eff6ff' : '#fff',
                        color: usageRange === item.key ? '#1d4ed8' : '#374151',
                        borderRadius: 10,
                        padding: '8px 14px',
                        fontSize: 13,
                        fontWeight: 600,
                        cursor: 'pointer',
                      }}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              }
            >
              {usageLoading ? (
                <div style={{ padding: 28, color: '#6b7280', fontSize: 14 }}>
                  正在加载历史使用数据...
                </div>
              ) : usageError ? (
                <div style={{ padding: 28, color: '#b91c1c', fontSize: 14 }}>
                  {usageError}
                </div>
              ) : !usageData ? (
                <div style={{ padding: 28, color: '#6b7280', fontSize: 14 }}>
                  当前时间范围暂无历史使用数据。
                </div>
              ) : (
                <div style={{ padding: 20 }}>
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                      gap: 16,
                      marginBottom: 20,
                    }}
                  >
                    <OverviewCard
                      icon={Activity}
                      title="平均节点使用率"
                      value={formatRatio(usageOverview.avg_node_usage_ratio)}
                      subtext={`峰值 ${formatRatio(usageOverview.peak_node_usage_ratio)}`}
                    />
                    <OverviewCard
                      icon={Boxes}
                      title="平均运行任务数"
                      value={usageOverview.avg_running_jobs ?? '--'}
                      subtext={`峰值 ${usageOverview.peak_running_jobs ?? '--'}`}
                    />
                    <OverviewCard
                      icon={Users}
                      title="活跃用户数"
                      value={usageOverview.active_user_count ?? '--'}
                      subtext="该时间范围内提交或运行过任务的用户"
                    />
                    <OverviewCard
                      icon={Layers3}
                      title="唯一任务总数"
                      value={usageOverview.total_unique_jobs ?? '--'}
                      subtext={`按 job_id 去重，采样点 ${usageData.sample_count ?? '--'} 个`}
                    />
                  </div>

                  <div style={{ overflowX: 'auto', marginTop: 24 }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: '#111827', marginBottom: 10 }}>
                      用户历史使用情况
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
                      <thead>
                        <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                          <th style={thStyle}>用户</th>
                          <th style={thStyle}>总任务数</th>
                          <th style={thStyle}>最常使用队列</th>
                          <th style={thStyle}>涉及节点数</th>
                          <th style={thStyle}>任务占比</th>
                        </tr>
                      </thead>
                      <tbody>
                        {usageUserStats.length === 0 ? (
                          <tr>
                            <td colSpan={5} style={emptyTdStyle}>暂无用户历史使用数据</td>
                          </tr>
                        ) : (
                          usageUserStats.map((item, idx) => (
                            <tr key={`${item.user}-${idx}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                              <td style={tdStyle}>{item.user || '--'}</td>
                              <td style={tdStyle}>{item.total_jobs ?? '--'}</td>
                              <td style={tdStyle}>{item.primary_queue || '--'}</td>
                              <td style={tdStyle}>{item.node_count ?? '--'}</td>
                              <td style={tdStyle}>{formatRatio(item.job_ratio)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>

                  <div style={{ overflowX: 'auto', marginTop: 24 }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: '#111827', marginBottom: 10 }}>
                      节点历史使用情况
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
                      <thead>
                        <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                          <th style={thStyle}>节点</th>
                          <th style={thStyle}>总任务数</th>
                          <th style={thStyle}>主要所属队列</th>
                          <th style={thStyle}>任务占比</th>
                        </tr>
                      </thead>
                      <tbody>
                        {usageNodeStats.length === 0 ? (
                          <tr>
                            <td colSpan={4} style={emptyTdStyle}>暂无节点历史使用数据</td>
                          </tr>
                        ) : (
                          usageNodeStats.map((item, idx) => (
                            <tr key={`${item.node}-${idx}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                              <td style={tdStyle}>{item.node || '--'}</td>
                              <td style={tdStyle}>{item.total_jobs ?? '--'}</td>
                              <td style={tdStyle}>{item.primary_queue || '--'}</td>
                              <td style={tdStyle}>{formatRatio(item.job_ratio)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>

                  <div style={{ overflowX: 'auto', marginTop: 24 }}>
                    <div style={{ fontSize: 16, fontWeight: 700, color: '#111827', marginBottom: 10 }}>
                      队列历史使用情况
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
                      <thead>
                        <tr style={{ background: '#f8fafc', textAlign: 'left' }}>
                          <th style={thStyle}>队列</th>
                          <th style={thStyle}>总任务数</th>
                          <th style={thStyle}>活跃用户数</th>
                          <th style={thStyle}>任务占比</th>
                        </tr>
                      </thead>
                      <tbody>
                        {usageQueueStats.length === 0 ? (
                          <tr>
                            <td colSpan={4} style={emptyTdStyle}>暂无队列历史使用数据</td>
                          </tr>
                        ) : (
                          usageQueueStats.map((item, idx) => (
                            <tr key={`${item.queue}-${idx}`} style={{ borderTop: '1px solid #f1f5f9' }}>
                              <td style={tdStyle}>{item.queue || '--'}</td>
                              <td style={tdStyle}>{item.total_jobs ?? '--'}</td>
                              <td style={tdStyle}>{item.active_users ?? '--'}</td>
                              <td style={tdStyle}>{formatRatio(item.job_ratio)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </SectionCard>
          </section>
        </>
      )}
    </ServerMonitorLayout>
  );
}

const heroBadgeStyle = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 6,
  padding: '6px 12px',
  borderRadius: 999,
  background: 'rgba(255,255,255,0.12)',
  fontSize: 13,
};

const thStyle = {
  padding: '14px 16px',
  fontSize: 13,
  fontWeight: 700,
  color: '#374151',
  borderBottom: '1px solid #e5e7eb',
  whiteSpace: 'nowrap',
};

const tdStyle = {
  padding: '14px 16px',
  fontSize: 14,
  color: '#111827',
  verticalAlign: 'top',
};

const emptyTdStyle = {
  padding: '28px 16px',
  textAlign: 'center',
  color: '#6b7280',
  fontSize: 14,
};
