import { useCallback, useState } from 'react';
import { Bot, CheckCircle2, Database, ExternalLink, FlaskConical, Send, Settings2, ShieldCheck, Terminal } from 'lucide-react';
import { Link } from 'react-router-dom';

import { canWriteCompetitionData } from '../../../config/competitionAccess';
import { QODER_LINUX_DISTRIBUTION } from '../../../config/qoderDistribution';
import {
  useCompetitionData,
  useCompetitionPollingResource,
  useCompetitionResource,
} from '../CompetitionDataContext';
import { CompetitionState } from '../components/CompetitionState';
import StructureBuilder from './StructureBuilder';
import './CompetitionAgent.css';


function readStoredUser() {
  try {
    return JSON.parse(globalThis.localStorage?.getItem('user') || 'null');
  } catch {
    return null;
  }
}


const STEP_OPTIONS = [
  ['relax', '结构优化'],
  ['scf', '自洽计算'],
  ['band', '能带计算'],
  ['dos', '态密度计算'],
];

const AGENT_STATUS_LABELS = {
  queued: '排队中',
  running: '处理中',
  succeeded: '已完成',
  failed: '失败',
};


export default function CompetitionAgent() {
  const { provider, mode } = useCompetitionData();
  const user = readStoredUser();
  const operator = mode === 'live' && canWriteCompetitionData(user);
  const [requestKind, setRequestKind] = useState('template_recommendation');
  const [stepKey, setStepKey] = useState('relax');
  const [materialId, setMaterialId] = useState('');
  const [workflowId, setWorkflowId] = useState('');
  const [prompt, setPrompt] = useState('为所选材料构建结构，并推荐当前阶段可用的受控 INCAR 模板。');
  const [selectedTemplateId, setSelectedTemplateId] = useState('');
  const [runId, setRunId] = useState(null);
  const [runOverride, setRunOverride] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const templates = useCompetitionResource(
    useCallback(() => provider.listAgentTemplates(), [provider]),
  );
  const structures = useCompetitionResource(
    useCallback(() => provider.listCuratedStructures(), [provider]),
  );
  const approvedRuns = useCompetitionResource(
    useCallback(() => provider.listAgentRuns(), [provider]),
  );
  const runLoader = useCallback(
    () => (runId ? provider.getAgentRun(runId) : Promise.resolve(null)),
    [provider, runId],
  );
  const currentRun = useCompetitionPollingResource(runLoader, {
    enabled: (run) => Boolean(run && ['queued', 'running'].includes(run.status)),
    intervalMs: 1200,
    requestKey: runId,
  });
  const run = runOverride?.id === currentRun.data?.id ? runOverride : currentRun.data;

  const [showManualBuilder, setShowManualBuilder] = useState(false);
  const preparedStructure = (run && run.output?.workspace?.structure) || null;
  const selectedTemplate = (templates.data?.items || []).find((item) => item.id === selectedTemplateId);

  async function submit(event) {
    event.preventDefault();
    if (!operator || submitting) return;
    setSubmitting(true);
    setError('');
    try {
      const payload = requestKind === 'template_recommendation'
        ? {
            request_kind: requestKind,
            prompt,
            material_id: materialId,
            step_key: stepKey,
          }
        : { request_kind: requestKind, prompt, workflow_id: workflowId.trim() };
      const created = await provider.createAgentRun(payload);
      setRunOverride(null);
      setRunId(created.id);
    } catch {
      setError('请求未创建，请核对输入、角色和功能开关。');
    } finally {
      setSubmitting(false);
    }
  }

  async function approve() {
    if (!operator || !run?.id || run.status !== 'succeeded') return;
    setError('');
    try {
      const approved = await provider.approveAgentRun(run.id);
      setRunOverride(approved);
    } catch {
      setError('分析尚不能批准，请刷新状态后重试。');
    }
  }

  return (
    <main className="competition-agent-page">
      <header className="competition-agent-header">
        <div>
          <span className="competition-agent-kicker"><Bot size={15} /> Qoder Agent</span>
          <h1>竞赛计算助手</h1>
          <p>Qoder 在后端调用应用受控工具，前端只展示持久化结果</p>
        </div>
        <div className="competition-agent-policy">
          <ShieldCheck size={17} />
          <span>后端受控工具 · mock provider</span>
        </div>
      </header>

      <nav className="competition-agent-links" aria-label="现有功能">
        <Link to="/dashboard/workflows"><FlaskConical size={16} />工作流</Link>
        <Link to="/dashboard/database/vasp"><Database size={16} />VASP 数据库</Link>
        <Link to="/dashboard/calculations/new"><ExternalLink size={16} />新建计算</Link>
        <button type="button" onClick={() => setShowManualBuilder((value) => !value)}><Settings2 size={16} />手动配置结构</button>
      </nav>

      <section className="competition-agent-runtime" aria-label="Qoder Linux 运行环境">
        <div><Terminal size={17} /><span><strong>Qoder Linux</strong>未连接 · 登录由用户在 Qoder 官方页面完成</span></div>
        <a href={QODER_LINUX_DISTRIBUTION.officialDownloadUrl} target="_blank" rel="noopener noreferrer">
          官方下载 <ExternalLink size={15} />
        </a>
      </section>

      <section className="competition-agent-console" aria-label="Agent 请求">
          <div className="competition-agent-segment" role="tablist" aria-label="请求类型">
            <button type="button" className={requestKind === 'template_recommendation' ? 'is-active' : ''} onClick={() => setRequestKind('template_recommendation')}>模板建议</button>
            <button type="button" className={requestKind === 'result_analysis' ? 'is-active' : ''} onClick={() => setRequestKind('result_analysis')}>结果分析</button>
          </div>

          <form className="competition-agent-composer" onSubmit={submit}>
            {requestKind === 'template_recommendation' ? (
              <div className="competition-agent-context-fields">
                <label>
                  受控样例结构
                  <select value={materialId} onChange={(event) => setMaterialId(event.target.value)} disabled={!structures.data?.items?.length}>
                    <option value="" disabled>请选择样例结构</option>
                    {(structures.data?.items || []).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.formula}</option>)}
                  </select>
                </label>
                <label>
                  计算阶段
                  <select value={stepKey} onChange={(event) => setStepKey(event.target.value)}>
                    {STEP_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
              </div>
            ) : (
              <label>
                Workflow ID
                <input value={workflowId} onChange={(event) => setWorkflowId(event.target.value)} placeholder="00000000-0000-4000-8000-000000000000" />
              </label>
            )}
            <label>
              请求
              <textarea value={prompt} maxLength={2000} onChange={(event) => setPrompt(event.target.value)} />
            </label>
            <button className="competition-agent-submit" type="submit" disabled={!operator || submitting || !prompt.trim() || (requestKind === 'template_recommendation' && !materialId)}>
              <Send size={16} />{submitting ? '提交中' : '提交请求'}
            </button>
            {!operator ? <p className="competition-agent-viewer">Viewer 只能查看已批准的持久化分析。</p> : null}
            {error ? <p className="competition-agent-error" role="alert">{error}</p> : null}
          </form>

          <div className="competition-agent-response" aria-live="polite">
            {!runId ? <p>描述材料与任务。缺少结构时，后端 Agent 会调用本地目录构建可核验的 POSCAR 和 KPOINTS。</p> : null}
            {runId && !run ? <CompetitionState status={currentRun.status} /> : null}
            {run ? (
              <>
                <div className="competition-agent-response-meta">
                  <code>{run.id}</code>
                  <span className={`competition-agent-status is-${run.status}`}>
                    {AGENT_STATUS_LABELS[run.status] || '未知'}
                  </span>
                </div>
                {run.output?.summary ? <p>{run.output.summary}</p> : <p>Worker 正在处理请求。</p>}
                {run.output?.tool_calls?.length ? (
                  <div className="competition-agent-tools" aria-label="后端工具调用">
                    {run.output.tool_calls.map((tool) => <span key={tool.name}><CheckCircle2 size={14} />{tool.name} · {tool.status}</span>)}
                  </div>
                ) : null}
                {run.output?.citations?.map((citation) => (
                  <button key={`${citation.kind}-${citation.id}`} type="button" className="competition-agent-citation" onClick={() => citation.kind === 'template' && setSelectedTemplateId(citation.id)}>
                    {citation.kind} · {citation.id}
                  </button>
                ))}
                {operator && run.status === 'succeeded' && !run.approved ? (
                  <button type="button" className="competition-agent-approve" onClick={approve}><CheckCircle2 size={16} />批准为只读分析</button>
                ) : null}
              </>
            ) : null}
                {selectedTemplate ? <p className="competition-agent-template-result"><strong>{selectedTemplate.name}</strong><span>{selectedTemplate.summary}</span></p> : null}
          </div>
          {selectedTemplate?.applicable ? (
                <Link className="competition-agent-apply" to={`/dashboard/calculations/new?agent_template=${encodeURIComponent(selectedTemplateId)}`}>
                  用于新建计算 <ExternalLink size={15} />
                </Link>
              ) : null}
          {!operator && approvedRuns.data?.items?.length ? (
            <div className="competition-agent-approved">
              <h3>已批准分析</h3>
              {approvedRuns.data.items.map((item) => <p key={item.id}>{item.output?.summary}</p>)}
            </div>
          ) : null}
      </section>
      {preparedStructure || showManualBuilder ? <StructureBuilder preparedStructure={preparedStructure} /> : null}
    </main>
  );
}
