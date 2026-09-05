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

const TOTAL_NODES = PARTITIONS.reduce((total, partition) => total + partition.nodeCount, 0);
const TOTAL_GPUS = PARTITIONS.reduce((total, partition) => total + partition.gpuCount, 0);


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


function displayTime(value) {
  if (!value) return '暂无作业更新时间';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString('zh-CN', { hour12: false });
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


function PartitionCard({ partition }) {
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
        <div><dt>配置节点</dt><dd>{partition.nodeCount}</dd></div>
        <div><dt>配置 GPU</dt><dd>{partition.gpuCount}</dd></div>
        <div><dt>QoS</dt><dd>{partition.qos}</dd></div>
      </dl>
      <footer>
        <span className="competition-server-status-dot is-muted" />
        动态占用数据待接入
      </footer>
    </article>
  );
}


export default function CompetitionServer() {
  const { provider, mode } = useCompetitionData();
  const loadServer = useCallback(async () => {
    const [dashboard, service] = await Promise.all([
      provider.getDashboard(),
      provider.getServiceHealth(),
    ]);
    return { dashboard, service };
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

  const { slurm, service } = normalizeCompetitionServerData(state.data);
  const serviceReady = service.status === 'ok';

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
        <OverviewItem icon={Boxes} label="配置节点" value={TOTAL_NODES} note="两个竞赛分区" tone="blue" />
        <OverviewItem icon={Cpu} label="配置 GPU" value={TOTAL_GPUS} note="RTX 5090 与 A100" tone="teal" />
        <OverviewItem icon={Activity} label="LMateLab 运行" value={displayCount(slurm.running)} note="当前账号可见 attempt" tone="green" />
        <OverviewItem icon={Clock3} label="LMateLab 排队" value={displayCount(slurm.queued)} note="当前账号可见 attempt" tone="amber" />
      </section>

      <section className="competition-server-primary-grid">
        <section className="competition-server-section" aria-labelledby="competition-partitions-title">
          <div className="competition-server-section-heading">
            <div>
              <h2 id="competition-partitions-title">竞赛分区</h2>
              <p>固定资源配置</p>
            </div>
            <span className="competition-server-section-icon"><Gauge size={18} aria-hidden="true" /></span>
          </div>
          <div className="competition-partition-grid">
            {PARTITIONS.map((partition) => (
              <PartitionCard key={partition.name} partition={partition} />
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
            <time dateTime={slurm.updatedAt || undefined}>{displayTime(slurm.updatedAt)}</time>
          </div>
        </section>

        <section className="competition-server-section competition-node-panel" aria-labelledby="competition-nodes-title">
          <div className="competition-server-section-heading">
            <div>
              <h2 id="competition-nodes-title">节点与 GPU 明细</h2>
              <p>集群级实时采集接口</p>
            </div>
            <span className="competition-server-section-icon"><Cpu size={18} aria-hidden="true" /></span>
          </div>
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
                <tr>
                  <td colSpan="6">
                    <div className="competition-node-empty">
                      <Cpu size={20} aria-hidden="true" />
                      <strong>实时节点数据待接入</strong>
                      <span>当前页面未将工作流统计冒充为集群资源占用</span>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </section>
    </main>
  );
}
