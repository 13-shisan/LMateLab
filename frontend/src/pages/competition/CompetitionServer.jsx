import { useCallback } from 'react';
import {
  Activity,
  Boxes,
  Clock3,
  Cpu,
  Gauge,
  RefreshCw,
  Server,
  Workflow,
  Zap,
} from 'lucide-react';

import {
  useCompetitionData,
  useCompetitionPollingResource,
} from '../../features/competition/CompetitionDataContext';
import {
  CompetitionState,
  DemoDataBanner,
} from '../../features/competition/components/CompetitionState';
import './CompetitionServer.css';


const PARTITIONS = Object.freeze([
  Object.freeze({
    name: 'P107-RTX5090',
    gpu: 'RTX 5090',
    nodes: 'anode01–anode15',
    nodeCount: 15,
    gpuCount: 120,
    qos: 'qos_p107-rtx5090',
    accent: 'blue',
    preferred: true,
  }),
  Object.freeze({
    name: 'P107-A100',
    gpu: 'A100',
    nodes: 'anode16–anode26',
    nodeCount: 11,
    gpuCount: 88,
    qos: 'qos_p107-a100',
    accent: 'green',
    preferred: false,
  }),
]);

function isPlainObject(value) {
  if (value === null || typeof value !== 'object') return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}


function safeText(value, fallback = '-') {
  return typeof value === 'string' && value.trim() ? value.trim() : fallback;
}


function safeCount(value) {
  return Number.isInteger(value) && value >= 0 ? value : null;
}


function normalizeClusterResources(value) {
  const unavailable = {
    status: 'unavailable',
    stale: false,
    collectedAt: '',
    schedulerUpdatedAt: '',
    summary: {
      nodeTotal: 0,
      availableNodes: 0,
      gpuTotal: null,
      gpuAllocated: null,
      gpuFree: null,
      gpuAvailable: false,
    },
    partitions: [],
    nodes: [],
  };
  if (!isPlainObject(value) || !['fresh', 'stale'].includes(value.status)) {
    return unavailable;
  }
  if (!isPlainObject(value.summary) || !Array.isArray(value.partitions) || !Array.isArray(value.nodes)) {
    return unavailable;
  }

  const normalizeTriple = (resource) => {
    if (!isPlainObject(resource)) return null;
    const normalized = {
      total: safeCount(resource.total),
      allocated: safeCount(resource.allocated),
      free: safeCount(resource.free),
    };
    return Object.values(normalized).every((item) => item !== null) ? normalized : null;
  };
  const normalizeGpu = (resource) => {
    if (!isPlainObject(resource) || typeof resource.available !== 'boolean') return null;
    if (!resource.available) {
      return { total: null, allocated: null, free: null, available: false };
    }
    const counts = normalizeTriple(resource);
    return counts ? { ...counts, available: true } : null;
  };
  const allowedPartitions = new Set(['P107-RTX5090', 'P107-A100']);
  const partitionForNode = (name) => {
    const match = /^anode(0[1-9]|1[0-9]|2[0-6])$/.exec(name);
    if (!match) return '';
    return Number(match[1]) <= 15 ? 'P107-RTX5090' : 'P107-A100';
  };

  const partitions = value.partitions.flatMap((item) => {
    if (!isPlainObject(item) || !allowedPartitions.has(item.name)) return [];
    const cpu = normalizeTriple(item.cpu);
    const memory = normalizeTriple(item.memory_mib);
    const gpu = normalizeGpu(item.gpu);
    const nodeTotal = safeCount(item.node_total);
    const availableNodes = safeCount(item.available_nodes);
    if (!cpu || !memory || !gpu || nodeTotal === null || availableNodes === null) return [];
    return [{
      name: item.name,
      gpuModel: safeText(item.gpu_model),
      nodeTotal,
      availableNodes,
      cpu,
      memory,
      gpu,
    }];
  });
  const nodes = value.nodes.flatMap((item) => {
    if (!isPlainObject(item)) return [];
    const name = safeText(item.name, '');
    const partition = safeText(item.partition, '');
    const expectedPartition = partitionForNode(name);
    const availability = safeText(item.availability, '');
    const cpu = normalizeTriple(item.cpu);
    const memory = normalizeTriple(item.memory_mib);
    const gpu = normalizeGpu(item.gpu);
    if (
      !expectedPartition
      || partition !== expectedPartition
      || !['available', 'busy', 'unavailable', 'unknown'].includes(availability)
      || !cpu
      || !memory
      || !gpu
    ) return [];
    return [{
      name,
      partition,
      gpuModel: safeText(item.gpu_model),
      state: safeText(item.state, 'unknown'),
      availability,
      cpu,
      memory,
      gpu,
    }];
  });
  const summary = {
    nodeTotal: safeCount(value.summary.node_total),
    availableNodes: safeCount(value.summary.available_nodes),
    gpuTotal: safeCount(value.summary.gpu_total),
    gpuAllocated: safeCount(value.summary.gpu_allocated),
    gpuFree: safeCount(value.summary.gpu_free),
    gpuAvailable: value.summary.gpu_available === true,
  };
  if (summary.nodeTotal === null || summary.availableNodes === null) return unavailable;
  if (
    summary.gpuAvailable
    && [summary.gpuTotal, summary.gpuAllocated, summary.gpuFree].some((item) => item === null)
  ) return unavailable;
  if (!summary.gpuAvailable) {
    summary.gpuTotal = null;
    summary.gpuAllocated = null;
    summary.gpuFree = null;
  }

  return {
    status: value.status,
    stale: value.status === 'stale',
    collectedAt: safeText(value.collected_at, ''),
    schedulerUpdatedAt: safeText(value.scheduler_updated_at, ''),
    summary,
    partitions,
    nodes,
  };
}


function normalizeCompetitionServerData(value) {
  const payload = isPlainObject(value) ? value : {};
  const dashboard = isPlainObject(payload.dashboard) ? payload.dashboard : {};
  const slurm = isPlainObject(dashboard.slurm) ? dashboard.slurm : {};
  const service = isPlainObject(payload.service) ? payload.service : {};

  return {
    slurm: {
      partition: safeText(slurm.partition, ''),
      queued: safeCount(slurm.queued),
      running: safeCount(slurm.running),
      attempts: safeCount(slurm.attempts),
      state: safeText(slurm.state, 'unknown'),
      updatedAt: safeText(slurm.updated_at, ''),
    },
    service: {
      status: safeText(service.status, 'unknown'),
      jobId: safeText(service.job_id),
      node: safeText(service.node),
      commit: safeText(service.commit),
      releaseKind: safeText(service.release_kind),
      dataMode: safeText(service.data_mode),
    },
    cluster: normalizeClusterResources(payload.cluster),
  };
}


function stateLabel(state) {
  return ({
    idle: '空闲',
    queued: '有作业排队',
    running: '有作业运行',
    '演示快照': '演示快照',
    unknown: '状态待确认',
  })[state] || '状态待确认';
}


function displayCount(value) {
  return value === null ? '-' : value;
}


function displayTime(value, fallback = '暂无更新时间') {
  if (!value) return fallback;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', { hour12: false });
}


function displayRatio(free, total, suffix = '') {
  if (free === null || total === null) return '不可用';
  return `${free} / ${total}${suffix}`;
}


function displayMemoryRatio(free, total) {
  if (free === null || total === null) return '不可用';
  return `${Math.round(free / 1024)} / ${Math.round(total / 1024)} GiB`;
}


function clusterStatusLabel(status) {
  return ({
    fresh: '实时快照',
    stale: '上次有效快照',
    unavailable: '数据不可用',
  })[status] || '数据不可用';
}


function availabilityLabel(availability) {
  return ({
    available: '可用',
    busy: '已占用',
    unavailable: '不可调度',
    unknown: '待确认',
  })[availability] || '待确认';
}


function displayCommit(value) {
  return /^[0-9a-f]{40}$/.test(value) ? value.slice(0, 10) : value;
}


function OverviewItem({ icon, label, value, note, tone }) {
  const IconComponent = icon;
  return (
    <article className={`competition-server-stat is-${tone}`}>
      <div className="competition-server-stat-heading">
        <span>{label}</span>
        <span className="competition-server-stat-icon"><IconComponent size={17} aria-hidden="true" /></span>
      </div>
      <strong>{value}</strong>
      <small>{note}</small>
    </article>
  );
}


function PartitionCard({ partition, snapshot, clusterStatus, collectedAt }) {
  const hasSnapshot = snapshot !== undefined;
  const footerLabel = clusterStatus === 'unavailable'
    ? '资源快照暂不可用'
    : `${clusterStatusLabel(clusterStatus)} · ${displayTime(collectedAt)}`;
  return (
    <article className={`competition-partition-card is-${partition.accent}`}>
      <header>
        <span className="competition-partition-icon"><Zap size={19} aria-hidden="true" /></span>
        <div>
          <h3>{partition.name}</h3>
          <p>{partition.gpu} 竞赛分区</p>
        </div>
        {partition.preferred ? <span className="competition-partition-badge">默认</span> : null}
      </header>
      <dl>
        <div><dt>节点范围</dt><dd>{partition.nodes}</dd></div>
        <div><dt>当前可用节点</dt><dd>{hasSnapshot ? displayRatio(snapshot.availableNodes, snapshot.nodeTotal) : '不可用'}</dd></div>
        <div><dt>空闲 CPU</dt><dd>{hasSnapshot ? displayRatio(snapshot.cpu.free, snapshot.cpu.total) : '不可用'}</dd></div>
        <div><dt>空闲 GPU</dt><dd>{hasSnapshot ? displayRatio(snapshot.gpu.free, snapshot.gpu.total) : '不可用'}</dd></div>
      </dl>
      <footer className={`is-${clusterStatus}`} title={`QoS: ${partition.qos}`}>
        <span className="competition-server-status-dot" />
        {footerLabel}
      </footer>
    </article>
  );
}


export default function CompetitionServer() {
  const { provider, mode } = useCompetitionData();
  const loadServer = useCallback(async () => {
    const [dashboard, service, cluster] = await Promise.all([
      provider.getDashboard(),
      provider.getServiceHealth(),
      provider.getClusterResources(),
    ]);
    return { dashboard, service, cluster };
  }, [provider]);
  const state = useCompetitionPollingResource(loadServer, {
    enabled: true,
    intervalMs: 15000,
  });

  if (state.status !== 'ready') {
    return (
      <main className="competition-server-page">
        {mode === 'demo' ? <DemoDataBanner /> : null}
        <CompetitionState status={state.status} message={state.error?.message} />
      </main>
    );
  }

  const { slurm, service, cluster } = normalizeCompetitionServerData(state.data);
  const serviceReady = service.status === 'ok';
  const partitionSnapshots = new Map(cluster.partitions.map((partition) => [partition.name, partition]));
  const clusterNote = cluster.status === 'unavailable'
    ? '无法读取当前调度器快照'
    : clusterStatusLabel(cluster.status);

  return (
    <main className="competition-server-page">
      {mode === 'demo' ? <DemoDataBanner /> : null}

      <header className="competition-server-header">
        <div className="competition-server-title">
          <span className="competition-server-title-icon"><Server size={22} aria-hidden="true" /></span>
          <div>
            <h1>107 集群资源</h1>
            <p>竞赛分区、LMateLab 作业与网页服务运行状态</p>
          </div>
        </div>
        <div className="competition-server-header-actions">
          <span className={`competition-server-service-state${serviceReady ? ' is-ready' : ''}`}>
            <span className="competition-server-status-dot" />
            {serviceReady ? '服务正常' : '服务状态待确认'}
          </span>
          <button
            type="button"
            className="competition-server-refresh"
            onClick={state.refresh}
            disabled={state.refreshing}
            aria-label="刷新服务器状态"
            title="刷新服务器状态"
          >
            <RefreshCw size={17} className={state.refreshing ? 'is-spinning' : ''} />
          </button>
        </div>
      </header>

      <section className="competition-server-overview" aria-label="107 集群概览">
        <OverviewItem
          icon={Boxes}
          label="当前可用节点"
          value={cluster.status === 'unavailable' ? '不可用' : displayRatio(cluster.summary.availableNodes, cluster.summary.nodeTotal)}
          note={clusterNote}
          tone="blue"
        />
        <OverviewItem
          icon={Cpu}
          label="空闲 GPU"
          value={displayRatio(cluster.summary.gpuFree, cluster.summary.gpuTotal)}
          note={cluster.summary.gpuAvailable ? '调度器实际 GRES 占用' : '调度器未提供可用数据'}
          tone="teal"
        />
        <OverviewItem icon={Activity} label="LMateLab 运行" value={displayCount(slurm.running)} note="当前账号可见 attempt" tone="green" />
        <OverviewItem icon={Clock3} label="LMateLab 排队" value={displayCount(slurm.queued)} note="当前账号可见 attempt" tone="amber" />
      </section>

      <section className="competition-server-primary-grid">
        <section className="competition-server-section" aria-labelledby="competition-partitions-title">
          <div className="competition-server-section-heading">
            <div>
              <h2 id="competition-partitions-title">竞赛分区</h2>
              <p>当前节点、CPU 与 GPU 调度快照</p>
            </div>
            <span className="competition-server-section-icon"><Gauge size={18} aria-hidden="true" /></span>
          </div>
          <div className="competition-partition-grid">
            {PARTITIONS.map((partition) => (
              <PartitionCard
                key={partition.name}
                partition={partition}
                snapshot={partitionSnapshots.get(partition.name)}
                clusterStatus={cluster.status}
                collectedAt={cluster.collectedAt}
              />
            ))}
          </div>
        </section>

        <aside className="competition-server-section competition-service-panel" aria-labelledby="competition-service-title">
          <div className="competition-server-section-heading">
            <div>
              <h2 id="competition-service-title">网页服务</h2>
              <p>当前发布身份</p>
            </div>
            <span className="competition-server-section-icon"><Server size={18} aria-hidden="true" /></span>
          </div>
          <dl className="competition-service-details">
            <div><dt>Slurm Job ID</dt><dd>{service.jobId}</dd></div>
            <div><dt>计算节点</dt><dd>{service.node}</dd></div>
            <div><dt>发布类型</dt><dd>{service.releaseKind}</dd></div>
            <div><dt>数据模式</dt><dd>{service.dataMode}</dd></div>
            <div><dt>Git 提交</dt><dd title={service.commit}>{displayCommit(service.commit)}</dd></div>
          </dl>
        </aside>
      </section>

      <section className="competition-server-secondary-grid">
        <section className="competition-server-section competition-job-panel" aria-labelledby="competition-jobs-title">
          <div className="competition-server-section-heading">
            <div>
              <h2 id="competition-jobs-title">LMateLab 作业</h2>
              <p>仅统计当前登录账号可见的工作流 attempt</p>
            </div>
            <span className="competition-server-section-icon"><Workflow size={18} aria-hidden="true" /></span>
          </div>
          <div className="competition-job-summary">
            <div><span>运行</span><strong>{displayCount(slurm.running)}</strong></div>
            <div><span>排队</span><strong>{displayCount(slurm.queued)}</strong></div>
            <div><span>累计 attempt</span><strong>{displayCount(slurm.attempts)}</strong></div>
          </div>
          <div className="competition-job-state-row">
            <span className={`competition-job-state is-${slurm.state}`}>{stateLabel(slurm.state)}</span>
            <time dateTime={slurm.updatedAt || undefined}>{displayTime(slurm.updatedAt, '暂无作业更新时间')}</time>
          </div>
        </section>

        <section className="competition-server-section competition-node-panel" aria-labelledby="competition-nodes-title">
          <div className="competition-server-section-heading">
            <div>
              <h2 id="competition-nodes-title">节点与 GPU 明细</h2>
              <p>仅显示 P107 竞赛分区允许节点</p>
            </div>
            <span className="competition-server-section-icon"><Cpu size={18} aria-hidden="true" /></span>
          </div>
          <div className={`competition-cluster-freshness is-${cluster.status}`} role="status">
            <span className="competition-server-status-dot" />
            <strong>{clusterStatusLabel(cluster.status)}</strong>
            <span>
              {cluster.status === 'unavailable'
                ? '当前没有可显示的调度器数据'
                : `采集于 ${displayTime(cluster.collectedAt)}`}
            </span>
          </div>
          <p className="competition-cluster-note">
            空闲节点表示当前快照有可分配 CPU 与 GPU；实际启动仍受 QoS、资源请求与排队优先级影响。
          </p>
          <div className="competition-node-table-scroll">
            <table className="competition-node-table">
              <thead>
                <tr>
                  <th>分区</th>
                  <th>节点</th>
                  <th>GPU</th>
                  <th>状态</th>
                  <th>CPU / 内存</th>
                  <th>更新时间</th>
                </tr>
              </thead>
              <tbody>
                {cluster.nodes.length ? cluster.nodes.map((node) => (
                  <tr key={node.name}>
                    <td>{node.partition}</td>
                    <td><strong className="competition-node-name">{node.name}</strong></td>
                    <td>
                      <strong>{displayRatio(node.gpu.free, node.gpu.total)}</strong>
                      <small>{node.gpuModel} 空闲 / 总量</small>
                    </td>
                    <td>
                      <span className={`competition-node-state is-${node.availability}`}>
                        {availabilityLabel(node.availability)}
                      </span>
                      <small>{node.state.toUpperCase()}</small>
                    </td>
                    <td>
                      <strong>{displayRatio(node.cpu.free, node.cpu.total)}</strong>
                      <small>CPU 空闲 / 总量</small>
                      <strong>{displayMemoryRatio(node.memory.free, node.memory.total)}</strong>
                      <small>内存空闲 / 总量</small>
                    </td>
                    <td><time dateTime={cluster.collectedAt || undefined}>{displayTime(cluster.collectedAt)}</time></td>
                  </tr>
                )) : (
                  <tr>
                    <td colSpan="6">
                      <div className="competition-node-empty">
                        <Cpu size={20} aria-hidden="true" />
                        <strong>集群资源暂不可用</strong>
                        <span>请稍后刷新；页面不会用配置总量推断实时空闲资源</span>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>
  );
}
