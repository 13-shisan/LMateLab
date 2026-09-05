import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Bot, CheckCircle2, ChevronDown, Cpu, Database, Download, ExternalLink, FileCode2, FileText,
  FlaskConical, Folder, FolderOpen, History, KeyRound, Library, ListChecks, LogIn, Play, Plus,
  Search, Send, Settings2, Square, Trash2, Upload, X,
} from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';

import { canWriteCompetitionData } from '../../../config/competitionAccess';
import {
  useCompetitionData,
  useCompetitionPollingResource,
  useCompetitionResource,
} from '../CompetitionDataContext';
import { CompetitionState } from '../components/CompetitionState';
import StructureBuilder from './StructureBuilder';
import VaspElectronicProperties from '../../../pages/db/vasp-detail/VaspElectronicProperties';
import '../../../pages/db/vasp-detail/VaspTaskDetail.css';
import './CompetitionAgent.css';


function readStoredUser() {
  try { return JSON.parse(globalThis.localStorage?.getItem('user') || 'null'); } catch { return null; }
}

function newConversationId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else for (let index = 0; index < bytes.length; index += 1) bytes[index] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function saveDownload({ blob, filename }) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

const STATUS_LABELS = { queued: '排队中', running: '处理中', succeeded: '已完成', failed: '失败' };
const ERROR_LABELS = {
  'provider-timeout': '模型响应超时，请稍后重试或更换模型。',
  'provider-http-error': '模型服务拒绝了请求，请检查模型权限和余额。',
  'provider-invalid-response': '模型返回内容无法解析，请重试。',
  'provider-failed': '模型调用失败，请检查 Agent 设置。',
};
const MODE_LABELS = {
  calculation_planning: '计算规划',
  general_qa: '问答与分析',
  result_analysis: '结果分析',
};
const CATEGORY_LABELS = {
  result: '计算结果', structure: '结构文件', 'incar-template': 'INCAR 模板', literature: '文献 PDF',
};
const CALCULATION_FILE_NAMES = new Set([
  'INCAR', 'OUTCAR', 'POSCAR', 'CONTCAR', 'KPOINTS', 'OSZICAR', 'PROCAR', 'DOSCAR',
  'EIGENVAL', 'IBZKPT', 'XDATCAR', 'REPORT', 'VASPRUN.XML',
]);
const STEP_LABELS = { relax: '结构优化', scf: '自洽计算', band: '能带计算', dos: '态密度计算' };


function CalculationPlanResult({ plan, canSubmit, onMissingUpload, onSubmit }) {
  if (!plan) return null;
  if (plan.needs_upload) {
    return (
      <section className="competition-agent-plan is-missing" aria-label="计算规划结果">
        <strong>{plan.material_formula || '目标材料'} · 未找到结构</strong>
        <span>上传 POSCAR、CONTCAR 或 CIF 后将自动重新生成规划。</span>
        <label className="competition-agent-action-button">
          <Upload size={16} />上传结构并重新规划
          <input type="file" accept=".cif,.vasp,.poscar,POSCAR,CONTCAR" onChange={onMissingUpload} />
        </label>
      </section>
    );
  }
  return (
    <section className="competition-agent-plan" aria-label="计算规划结果">
      <div className="competition-agent-plan-heading">
        <strong>{plan.material_formula}</strong>
        <span>{(plan.structures || []).length} 个结构候选</span>
      </div>
      <div className="competition-agent-plan-structures">
        {(plan.structures || []).map((item) => (
          <span key={`${item.source}-${item.id}`}>{item.source} · {item.name || item.id}</span>
        ))}
      </div>
      <ol className="competition-agent-plan-steps">
        {(plan.templates || []).map((template) => (
          <li key={template.id}>
            <div><strong>{STEP_LABELS[template.step] || template.step}</strong><code>{template.filename}</code></div>
            {(plan.parameter_changes || []).filter((item) => item.template_id === template.id).map((item) => (
              <p key={`${item.parameter}-${item.value}`}><code>{item.parameter} = {item.value}</code><span>{item.reason}</span></p>
            ))}
            <details><summary>查看 INCAR</summary><pre>{template.rendered_content || template.content}</pre></details>
          </li>
        ))}
      </ol>
      <button type="button" className="competition-agent-primary" disabled={!canSubmit} onClick={onSubmit}>
        <FlaskConical size={16} />提交新建计算
      </button>
      {!canSubmit ? <p className="competition-agent-blocked">当前结构未通过现有计算工作流的输入约束，可继续分析但不能排队。</p> : null}
    </section>
  );
}


function safeHttpsUrl(value) {
  return typeof value === 'string' && value.startsWith('https://') ? value : '';
}


function CitationList({ citations }) {
  if (!Array.isArray(citations) || !citations.length) return null;
  return (
    <div className="competition-agent-citations">
      {citations.map((citation) => {
        const url = safeHttpsUrl(citation.url);
        const label = citation.title || `${citation.kind} · ${citation.id}`;
        const metadata = [citation.authors?.slice(0, 2).join(', '), citation.year, citation.source]
          .filter(Boolean).join(' · ');
        return (
          <article key={`${citation.kind}-${citation.id}`}>
            {url ? <a href={url} target="_blank" rel="noreferrer">{label}<ExternalLink size={12} /></a> : <strong>{label}</strong>}
            {metadata ? <small>{metadata}</small> : null}
          </article>
        );
      })}
    </div>
  );
}


function AnalysisFacts({ results }) {
  if (!Array.isArray(results) || !results.length) return null;
  return (
    <section className="competition-agent-analysis" aria-label="预置分析器结果">
      <strong>程序分析结果</strong>
      {results.map((result, index) => (
        <details key={`${result.file_id || result.structure_id}-${result.analyzer}-${index}`}>
          <summary>{result.file_name || result.formula || '结构'} · {result.analyzer}</summary>
          <pre>{JSON.stringify(result.facts || result, null, 2)}</pre>
        </details>
      ))}
    </section>
  );
}


function CalculationDirectoryTree({ calculations, selectedIds, onToggle }) {
  return (
    <div className="competition-agent-calculation-tree">
      {calculations.map((calculation) => (
        <section key={calculation.id} className={selectedIds.includes(calculation.id) ? 'is-selected' : ''}>
          <label title={calculation.name}>
            <input type="checkbox" checked={selectedIds.includes(calculation.id)} onChange={() => onToggle(calculation.id)} />
            <FolderOpen size={15} />
            <span><strong>{calculation.name}</strong><small>{calculation.files.length} 个文件{calculation.builtin_example ? ' · 内置示例' : ''}</small></span>
          </label>
          <details>
            <summary><ChevronDown size={13} />查看目录内容</summary>
            <div>{calculation.files.map((item) => <span key={item.id}><FileText size={13} />{item.name}</span>)}</div>
          </details>
        </section>
      ))}
      {!calculations.length ? <small>暂无 VASP 计算目录</small> : null}
    </div>
  );
}


function AuxiliaryFileTree({ files, selectedIds, onToggle }) {
  const items = files.filter((item) => ['structure', 'incar-template'].includes(item.category));
  if (!items.length) return null;
  return (
    <details className="competition-agent-auxiliary-files">
      <summary><ChevronDown size={13} />单独上传的输入文件<span>{items.length}</span></summary>
      <div>{items.map((item) => (
        <label key={item.id} title={item.name}>
          <input type="checkbox" checked={selectedIds.includes(item.id)} onChange={() => onToggle(item.id)} />
          {item.category === 'incar-template' ? <FileCode2 size={14} /> : <FileText size={14} />}
          <span>{item.name}</span>
        </label>
      ))}</div>
    </details>
  );
}


export default function CompetitionAgent() {
  const { provider, mode } = useCompetitionData();
  const navigate = useNavigate();
  const operator = mode === 'live' && canWriteCompetitionData(readStoredUser());
  const [prompt, setPrompt] = useState('计算一下 MoS2 体系的能带。');
  const [workflowId, setWorkflowId] = useState('');
  const [conversationId, setConversationId] = useState(newConversationId);
  const [runId, setRunId] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [showSettings, setShowSettings] = useState(false);
  const [showManualBuilder, setShowManualBuilder] = useState(false);
  const [settingsForm, setSettingsForm] = useState({ api_url: '', model: '', api_key: '' });
  const [settingsMessage, setSettingsMessage] = useState('');
  const [runtimeRefresh, setRuntimeRefresh] = useState(0);
  const [fileRefresh, setFileRefresh] = useState(0);
  const [historyRefresh, setHistoryRefresh] = useState(0);
  const [literatureRefresh, setLiteratureRefresh] = useState(0);
  const [selectedFileIds, setSelectedFileIds] = useState([]);
  const [selectedCalculationIds, setSelectedCalculationIds] = useState([]);
  const [selectedStructureIds, setSelectedStructureIds] = useState([]);
  const [selectedLiteratureIds, setSelectedLiteratureIds] = useState([]);
  const [resourceTab, setResourceTab] = useState('files');
  const [structureQuery, setStructureQuery] = useState('');
  const [structureSearch, setStructureSearch] = useState('');
  const [literatureQuery, setLiteratureQuery] = useState('');
  const [literatureResults, setLiteratureResults] = useState([]);
  const [literatureSearching, setLiteratureSearching] = useState(false);
  const [literatureSearchError, setLiteratureSearchError] = useState('');
  const [libraryName, setLibraryName] = useState('我的文献库');
  const [searchLiterature, setSearchLiterature] = useState(false);
  const [downloadingExample, setDownloadingExample] = useState('');
  const [deletingConversation, setDeletingConversation] = useState('');
  const [qoderAction, setQoderAction] = useState('');

  const histories = useCompetitionResource(useCallback(() => provider.listAgentRuns(historyRefresh), [provider, historyRefresh]));
  const runtime = useCompetitionResource(useCallback(() => provider.getAgentRuntime(runtimeRefresh), [provider, runtimeRefresh]));
  const settings = useCompetitionResource(useCallback(() => operator ? provider.getAgentSettings() : Promise.resolve(null), [operator, provider]));
  const files = useCompetitionResource(useCallback(() => operator ? provider.listAgentFiles(fileRefresh) : Promise.resolve({ items: [] }), [fileRefresh, operator, provider]));
  const examples = useCompetitionResource(useCallback(() => provider.listAgentExamples(), [provider]));
  const structureLibrary = useCompetitionResource(useCallback(() => provider.searchAgentStructures(structureSearch), [provider, structureSearch]));
  const literatureLibrary = useCompetitionResource(useCallback(
    () => operator ? provider.listAgentLiterature('', literatureRefresh) : Promise.resolve({ items: [], uploads: [] }),
    [literatureRefresh, operator, provider],
  ));
  const workflows = useCompetitionResource(useCallback(
    () => provider.listWorkflows({ status: 'all' }),
    [provider],
  ));
  const runLoader = useCallback(() => runId ? provider.getAgentRun(runId) : Promise.resolve(null), [provider, runId]);
  const currentRun = useCompetitionPollingResource(runLoader, {
    enabled: (item) => Boolean(item && ['queued', 'running'].includes(item.status)), intervalMs: 1200, requestKey: runId,
  });
  const run = currentRun.data;
  const calculationPlan = run?.output?.workspace?.plan || null;
  const preparedStructure = run?.output?.workspace?.structure || null;
  const analysisResults = run?.input?.analysis_results || [];
  const completedRunId = run && ['succeeded', 'failed'].includes(run.status) ? run.id : null;
  const mountedFiles = (files.data?.items || []).filter((item) => selectedFileIds.includes(item.id));
  const mountedCalculations = (files.data?.calculations || []).filter((item) => selectedCalculationIds.includes(item.id));
  const mountedStructures = selectedStructureIds.map((id) => (
    (structureLibrary.data?.items || []).find((item) => item.id === id) || { id }
  ));
  const mountedLiterature = selectedLiteratureIds.map((id) => (
    (literatureLibrary.data?.items || []).find((item) => item.id === id) || { id }
  ));
  const selectedWorkflow = (workflows.data?.items || []).find((item) => item.id === workflowId) || null;
  const apiKeyWriteAllowed = settings.data?.api_key_write_allowed === true;
  const selectedWorkflowResult = useCompetitionResource(useCallback(
    () => selectedWorkflow?.status === 'succeeded'
      ? provider.getResult(selectedWorkflow.id)
      : Promise.resolve(null),
    [provider, selectedWorkflow?.id, selectedWorkflow?.status],
  ));
  const conversationGroups = useMemo(() => {
    const groups = new Map();
    for (const item of histories.data?.items || []) {
      const id = item.conversation_id || item.id;
      const existing = groups.get(id);
      if (existing) existing.turnCount += 1;
      else groups.set(id, { id, latest: item, turnCount: 1 });
    }
    return [...groups.values()];
  }, [histories.data]);
  const conversationRuns = useMemo(() => {
    const rows = (histories.data?.items || []).filter((item) => item.conversation_id === conversationId).reverse().map((item) => item.id === run?.id ? run : item);
    if (run && !rows.some((item) => item.id === run.id)) rows.push(run);
    return rows;
  }, [conversationId, histories.data, run]);

  useEffect(() => {
    if (settings.data) setSettingsForm({ api_url: settings.data.api_url || '', model: settings.data.model || '', api_key: '' });
  }, [settings.data]);

  useEffect(() => {
    if (completedRunId) setHistoryRefresh((value) => value + 1);
  }, [completedRunId]);

  function toggle(setter, id) {
    setter((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  }

  function startConversation() {
    setConversationId(newConversationId());
    setRunId(null);
    setPrompt('');
    setError('');
  }

  async function createRun(extraFileIds = null) {
    if (!operator || submitting || !prompt.trim()) return;
    setSubmitting(true);
    setError('');
    try {
      const fileIds = extraFileIds || selectedFileIds;
      const payload = {
        request_kind: 'auto',
        prompt: prompt.trim(),
        file_ids: fileIds,
        calculation_ids: selectedCalculationIds,
        structure_ids: selectedStructureIds,
        literature_ids: selectedLiteratureIds,
        conversation_id: conversationId,
        search_literature: searchLiterature,
      };
      if (workflowId.trim()) payload.workflow_id = workflowId.trim();
      const created = await provider.createAgentRun(payload);
      setRunId(created.id);
      setHistoryRefresh((value) => value + 1);
    } catch (reason) {
      setError(reason?.message || '请求未创建，请核对输入、角色和功能开关。');
    } finally {
      setSubmitting(false);
    }
  }

  async function submit(event) {
    event.preventDefault();
    await createRun();
  }

  async function uploadFiles(event, category, autoPlan = false) {
    const chosen = [...(event.target.files || [])];
    event.target.value = '';
    if (!chosen.length) return;
    setError('');
    try {
      const uploaded = await Promise.all(chosen.map((file) => provider.uploadAgentFile(file, category, libraryName)));
      const ids = uploaded.map((item) => item.id);
      const nextIds = [...new Set([...selectedFileIds, ...ids])];
      setSelectedFileIds(nextIds);
      setFileRefresh((value) => value + 1);
      if (category === 'literature') {
        setLiteratureRefresh((value) => value + 1);
        setResourceTab('literature');
      }
      if (autoPlan) await createRun(nextIds);
    } catch (reason) {
      setError(reason?.message || '文件上传失败，请核对格式与 20 MiB 大小限制。');
    }
  }

  async function uploadCalculationDirectory(event) {
    const chosen = [...(event.target.files || [])];
    event.target.value = '';
    const supported = chosen.filter((file) => CALCULATION_FILE_NAMES.has(file.name.toUpperCase()));
    if (!supported.length) {
      setError('所选目录中没有可分析的 VASP 文件。');
      return;
    }
    const relativePath = supported[0].webkitRelativePath || supported[0].name;
    const groupName = relativePath.split('/')[0] || 'VASP 计算目录';
    const calculationId = newConversationId();
    setError('');
    try {
      await Promise.all(supported.map((file) => provider.uploadAgentFile(
        file, 'result', libraryName, { calculationId, groupName },
      )));
      setSelectedCalculationIds((current) => [...new Set([...current, calculationId])]);
      setFileRefresh((value) => value + 1);
    } catch (reason) {
      setError(reason?.message || '计算目录上传失败，请检查文件格式与 20 MiB 单文件限制。');
    }
  }

  async function saveSettings(event) {
    event.preventDefault();
    setSettingsMessage('');
    if (settingsForm.api_key && !apiKeyWriteAllowed) {
      setSettingsMessage('API Key 只能通过 HTTPS 或 127.0.0.1 SSH 隧道保存');
      return;
    }
    try {
      const payload = { api_url: settingsForm.api_url, model: settingsForm.model };
      if (settingsForm.api_key) payload.api_key = settingsForm.api_key;
      const saved = await provider.updateAgentSettings(payload);
      setSettingsForm((current) => ({ ...current, api_key: '' }));
      setSettingsMessage(saved.api_key_configured ? '配置已保存，API 已连接' : 'URL 与模型已保存，尚未配置密钥');
      setRuntimeRefresh((value) => value + 1);
    } catch (reason) { setSettingsMessage(reason?.message || '配置保存失败'); }
  }

  async function manageQoder(action, request) {
    if (qoderAction) return;
    setQoderAction(action);
    setSettingsMessage('');
    try {
      const status = await request();
      setSettingsMessage(
        action === 'install' ? 'Qoder 已安装。'
          : action === 'login' && status.authenticated ? 'Qoder 已登录。'
            : action === 'login' ? '请在授权页完成 Qoder 登录。'
              : status.service_running ? 'Qoder 服务已启动。' : 'Qoder 服务已停止。',
      );
      setRuntimeRefresh((value) => value + 1);
    } catch (reason) {
      setSettingsMessage(reason?.message || 'Qoder 操作失败。');
    } finally {
      setQoderAction('');
    }
  }

  async function findLiterature() {
    if (literatureQuery.trim().length < 2) return;
    setLiteratureSearching(true);
    setError('');
    setLiteratureSearchError('');
    try {
      const items = (await provider.searchAgentLiterature(literatureQuery.trim())).items || [];
      setLiteratureResults(items);
      if (!items.length) setLiteratureSearchError('未检索到匹配文献，请尝试英文题名、材料名或 DOI。');
    } catch (reason) { setLiteratureSearchError(reason?.message || 'OpenAlex 检索暂时不可用。'); }
    finally { setLiteratureSearching(false); }
  }

  async function addLiterature(item) {
    try {
      const indexed = await provider.indexAgentLiterature({
        source_id: item.id, title: item.title, abstract: item.abstract || '', authors: item.authors || [],
        year: item.year, doi: item.doi, url: item.url, library_name: libraryName,
      });
      setSelectedLiteratureIds((current) => [...new Set([...current, indexed.id])]);
      setLiteratureRefresh((value) => value + 1);
    } catch (reason) { setError(reason?.message || '文献索引失败。'); }
  }

  async function downloadExample(id) {
    if (downloadingExample) return;
    setDownloadingExample(id);
    setError('');
    try { saveDownload(await provider.downloadAgentExample(id)); }
    catch (reason) { setError(reason?.message || '示例结果包下载失败。'); }
    finally { setDownloadingExample(''); }
  }

  async function deleteConversation(id) {
    if (deletingConversation || !globalThis.confirm?.('删除这段对话及其中全部任务？')) return;
    setDeletingConversation(id);
    setError('');
    try {
      await provider.deleteAgentConversation(id);
      if (conversationId === id) startConversation();
      setHistoryRefresh((value) => value + 1);
    } catch (reason) {
      setError(reason?.message || '对话删除失败。');
    } finally {
      setDeletingConversation('');
    }
  }

  function selectWorkflow(id) {
    setWorkflowId(id);
    setRunId(null);
  }

  function submitPlanToCalculation() {
    if (!preparedStructure?.workflow_compatible || !preparedStructure?.files?.POSCAR) return;
    navigate('/dashboard/calculations/new', {
      state: {
        agentHandoff: {
          version: 1,
          structure: {
            filename: `${calculationPlan?.material_formula || 'structure'}.vasp`,
            content: preparedStructure.files.POSCAR,
          },
          parameter_changes: calculationPlan?.parameter_changes || [],
          source_run_id: run?.id,
        },
      },
    });
  }

  const fetchWorkflowPlot = useCallback((path) => (
    provider.loadPlot(workflowId, path.includes('/band-plot') ? 'band' : 'dos')
  ), [provider, workflowId]);
  const downloadWorkflowData = useCallback((path) => provider.downloadArtifact(
    workflowId,
    path.includes('/band-dat') ? 'band-data' : 'dos-data',
  ).then(saveDownload), [provider, workflowId]);

  return (
    <main className="competition-agent-page">
      <header className="competition-agent-header">
        <div><span className="competition-agent-kicker"><Bot size={15} /> Agent</span><h1>计算与数据 Agent</h1></div>
        <div className="competition-agent-header-actions">
          <span className={`competition-agent-status is-${runtime.data?.connected ? 'succeeded' : 'failed'}`}>LLM {runtime.data?.connected ? '可调用' : '未配置'}</span>
          <span className={`competition-agent-status is-${runtime.data?.qoder?.connected ? 'succeeded' : 'failed'}`}>Qoder {runtime.data?.qoder?.connected ? '已连接' : '未连接'}</span>
          {operator ? <button type="button" title="Agent 设置" onClick={() => setShowSettings((value) => !value)}><Settings2 size={17} /></button> : null}
        </div>
      </header>

      <nav className="competition-agent-links" aria-label="相关功能">
        <Link to="/dashboard/workflows"><FlaskConical size={16} />工作流</Link>
        <Link to="/dashboard/database/vasp"><Database size={16} />VASP 数据库</Link>
        <Link to="/dashboard/calculations/new"><ExternalLink size={16} />新建计算</Link>
        <button type="button" onClick={() => setShowManualBuilder((value) => !value)}><Folder size={16} />手动结构</button>
      </nav>

      {showSettings && operator ? (
        <form className="competition-agent-settings" onSubmit={saveSettings}>
          <section className="competition-agent-llm-settings">
            <strong>普通问答接口</strong>
            <label>API URL<input value={settingsForm.api_url} onChange={(event) => setSettingsForm((value) => ({ ...value, api_url: event.target.value }))} /></label>
            <label>模型<input value={settingsForm.model} onChange={(event) => setSettingsForm((value) => ({ ...value, model: event.target.value }))} /></label>
            <label>API Key<input type="password" autoComplete="new-password" value={settingsForm.api_key} disabled={!apiKeyWriteAllowed} placeholder={!apiKeyWriteAllowed ? '请通过安全入口配置' : settings.data?.api_key_configured ? '已配置，留空不修改' : '输入 API Key'} onChange={(event) => setSettingsForm((value) => ({ ...value, api_key: event.target.value }))} />{!apiKeyWriteAllowed ? <span className="competition-agent-secret-note">公网 HTTP 页面不传输密钥，请使用 HTTPS 或 127.0.0.1 SSH 隧道。</span> : null}</label>
            <button type="submit"><KeyRound size={16} />保存</button>
          </section>
          <aside className="competition-agent-qoder-settings" aria-label="Qoder 接口">
            <div><Cpu size={16} /><strong>Qoder CN 接口</strong><span className={`competition-agent-status is-${runtime.data?.qoder?.connected ? 'succeeded' : 'failed'}`}>{runtime.data?.qoder?.connected ? '已连接' : '未连接'}</span></div>
            <dl>
              <div><dt>接口</dt><dd>{runtime.data?.qoder?.interface || 'qodercn-agent-sdk'}</dd></div>
              <div><dt>用途</dt><dd>计算处理（可选）</dd></div>
              <div><dt>认证</dt><dd>{runtime.data?.qoder?.auth_mode || '未配置'}</dd></div>
              <div><dt>模型</dt><dd>{runtime.data?.qoder?.model || '默认'}</dd></div>
              <div><dt>CLI</dt><dd>{runtime.data?.qoder?.installed ? `已安装 ${runtime.data.qoder.version || ''}` : '未安装'}</dd></div>
              <div><dt>服务</dt><dd>{runtime.data?.qoder?.service_running ? '运行中' : '未启动'}</dd></div>
            </dl>
            <div className="competition-agent-qoder-actions">
              <button type="button" disabled={Boolean(qoderAction) || !runtime.data?.qoder?.manageable || runtime.data?.qoder?.installed} onClick={() => manageQoder('install', provider.installQoder)}><Download size={14} />一键安装</button>
              <button type="button" disabled={Boolean(qoderAction) || !runtime.data?.qoder?.manageable || !runtime.data?.qoder?.installed || runtime.data?.qoder?.authenticated} onClick={() => manageQoder('login', provider.loginQoder)}><LogIn size={14} />一键登录</button>
              <button type="button" disabled={Boolean(qoderAction) || !runtime.data?.qoder?.authenticated || runtime.data?.qoder?.service_running} onClick={() => manageQoder('start', provider.startQoderService)}><Play size={14} />启动服务</button>
              <button type="button" title="停止 Qoder 服务" disabled={Boolean(qoderAction) || !runtime.data?.qoder?.service_running} onClick={() => manageQoder('stop', provider.stopQoderService)}><Square size={13} /></button>
            </div>
            {runtime.data?.qoder?.login_url ? <a className="competition-agent-qoder-login" href={runtime.data.qoder.login_url} target="_blank" rel="noreferrer">打开 Qoder CN 授权页<ExternalLink size={12} /></a> : null}
          </aside>
          {settingsMessage ? <p>{settingsMessage}</p> : null}
        </form>
      ) : null}

      <section className="competition-agent-workspace">
        <aside className="competition-agent-history" aria-label="对话与任务历史">
          <div className="competition-agent-pane-title"><span><History size={16} />历史</span><button type="button" title="新建对话" onClick={startConversation}><Plus size={16} /></button></div>
          <div className="competition-agent-history-list">
            {conversationGroups.map(({ id, latest, turnCount }) => (
              <div className="competition-agent-history-row" key={id}>
                <button type="button" className={conversationId === id ? 'is-active' : ''} onClick={() => { setConversationId(id); setRunId(latest.id); }}>
                  <span>{latest.prompt || MODE_LABELS[latest.request_kind] || 'Agent 任务'}</span>
                  <small>{turnCount} 轮 · {MODE_LABELS[latest.request_kind] || '任务'} · {STATUS_LABELS[latest.status] || latest.status}</small>
                </button>
                {operator ? <button className="competition-agent-delete" type="button" title="删除对话" disabled={deletingConversation === id} onClick={() => deleteConversation(id)}><Trash2 size={14} /></button> : null}
              </div>
            ))}
            {!conversationGroups.length ? <p>暂无历史</p> : null}
          </div>
        </aside>

        <section className="competition-agent-chat" aria-label="Agent 对话">
          <div className="competition-agent-thread" aria-live="polite">
            {!conversationRuns.length ? <div className="competition-agent-empty"><Bot size={24} /><strong>新对话</strong></div> : null}
            {conversationRuns.map((item) => (
              <article key={item.id} className="competition-agent-turn">
                <div className="competition-agent-user-message"><strong>你</strong><p>{item.prompt}</p></div>
                <div className="competition-agent-response">
                  <div className="competition-agent-response-meta"><strong>Agent</strong><span className={`competition-agent-status is-${item.status}`}>{STATUS_LABELS[item.status] || item.status}</span></div>
                  {item.output?.summary ? <p>{item.output.summary}</p> : item.status === 'failed' ? <p>{ERROR_LABELS[item.error_code] || 'Agent 调用失败。'}</p> : <CompetitionState status={item.status} />}
                  {item.id === run?.id ? <>
                    <CalculationPlanResult plan={calculationPlan} canSubmit={Boolean(preparedStructure?.workflow_compatible)} onMissingUpload={(event) => uploadFiles(event, 'structure', true)} onSubmit={submitPlanToCalculation} />
                    <AnalysisFacts results={analysisResults} />
                  </> : null}
                  <CitationList citations={item.output?.citations} />
                  {item.output?.tool_calls?.length ? <div className="competition-agent-tools">{item.output.tool_calls.map((tool, index) => <span key={`${tool.name}-${index}`}><CheckCircle2 size={13} />{tool.name} · {tool.status}</span>)}</div> : null}
                </div>
              </article>
            ))}
          </div>
          <form className="competition-agent-composer" onSubmit={submit}>
            {mountedCalculations.length || mountedFiles.length || selectedStructureIds.length || selectedLiteratureIds.length || selectedWorkflow ? (
              <div className="competition-agent-mounted">
                <strong>已挂载</strong>
                {selectedWorkflow ? <span>任务 · {selectedWorkflow.material || selectedWorkflow.id}<button type="button" title="取消挂载任务" onClick={() => setWorkflowId('')}><X size={12} /></button></span> : null}
                {mountedCalculations.map((item) => <span key={item.id}>计算目录 · {item.name}<button type="button" title="取消挂载计算目录" onClick={() => toggle(setSelectedCalculationIds, item.id)}><X size={12} /></button></span>)}
                {mountedFiles.map((item) => <span key={item.id}>{item.name}<button type="button" title={item.category === 'literature' ? '取消挂载文献' : '取消挂载文件'} onClick={() => toggle(setSelectedFileIds, item.id)}><X size={12} /></button></span>)}
                {mountedStructures.map((item) => <span key={item.id}>{item.formula || item.id}<button type="button" title="取消挂载结构" onClick={() => toggle(setSelectedStructureIds, item.id)}><X size={12} /></button></span>)}
                {mountedLiterature.map((item) => <span key={item.id}>{item.title || item.id}<button type="button" title="取消挂载文献" onClick={() => toggle(setSelectedLiteratureIds, item.id)}><X size={12} /></button></span>)}
              </div>
            ) : null}
            <div className="competition-agent-prompt-row">
              <textarea value={prompt} maxLength={2000} placeholder="输入问题或计算要求" onChange={(event) => setPrompt(event.target.value)} />
              <button type="submit" title="发送" disabled={!operator || submitting || !prompt.trim() || !runtime.data?.connected}><Send size={18} /></button>
            </div>
            <label className="competition-agent-literature-toggle"><input type="checkbox" checked={searchLiterature} onChange={(event) => setSearchLiterature(event.target.checked)} />联网检索文献</label>
            {!operator ? <p className="competition-agent-error">Viewer 只能查看已发布的分析。</p> : null}
            {error ? <p className="competition-agent-error" role="alert">{error}</p> : null}
          </form>
        </section>

        <aside className="competition-agent-resources" aria-label="Agent 资源">
          <div className="competition-agent-resource-tabs">
            <button type="button" className={resourceTab === 'files' ? 'is-active' : ''} onClick={() => setResourceTab('files')} title="文件"><FolderOpen size={16} /></button>
            <button type="button" className={resourceTab === 'tasks' ? 'is-active' : ''} onClick={() => setResourceTab('tasks')} title="任务"><ListChecks size={16} /></button>
            <button type="button" className={resourceTab === 'structures' ? 'is-active' : ''} onClick={() => setResourceTab('structures')} title="结构库"><Database size={16} /></button>
            <button type="button" className={resourceTab === 'literature' ? 'is-active' : ''} onClick={() => setResourceTab('literature')} title="文献库"><Library size={16} /></button>
          </div>
          {resourceTab === 'files' ? <>
            <div className="competition-agent-pane-title"><span><FolderOpen size={16} />VASP 计算目录</span><small>{files.data?.calculations?.length || 0}</small></div>
            <div className="competition-agent-example-bundles">
              {(examples.data?.items || []).map((item) => <div key={item.id}><span><strong>{item.formula}</strong><small>{item.source} · {item.task} · {item.files.length} 文件</small></span><button type="button" title="下载示例结果包" disabled={Boolean(downloadingExample)} onClick={() => downloadExample(item.id)}><Download size={14} /></button></div>)}
            </div>
            <CalculationDirectoryTree calculations={files.data?.calculations || []} selectedIds={selectedCalculationIds} onToggle={(id) => toggle(setSelectedCalculationIds, id)} />
            <AuxiliaryFileTree files={files.data?.items || []} selectedIds={selectedFileIds} onToggle={(id) => toggle(setSelectedFileIds, id)} />
            <section className="competition-agent-upload-zone">
              <strong>上传</strong>
              <label><Upload size={14} />VASP 计算目录<input type="file" multiple webkitdirectory="" directory="" onChange={uploadCalculationDirectory} /></label>
              {Object.entries(CATEGORY_LABELS).filter(([category]) => ['structure', 'incar-template'].includes(category)).map(([category, label]) => (
                <label key={category}><Upload size={14} />{label}<input type="file" multiple={category !== 'structure'} onChange={(event) => uploadFiles(event, category)} /></label>
              ))}
            </section>
          </> : null}
          {resourceTab === 'tasks' ? <>
            <div className="competition-agent-pane-title"><span><ListChecks size={16} />任务</span><small>{workflows.data?.items?.length || 0}</small></div>
            <div className="competition-agent-resource-list is-tasks">
              {(workflows.data?.items || []).map((item) => <label key={item.id}><input type="radio" name="agent-workflow" checked={workflowId === item.id} onChange={() => selectWorkflow(item.id)} /><span><strong>{item.material || 'VASP 任务'}</strong><small>{STATUS_LABELS[item.status] || item.status} · {item.id}</small></span></label>)}
              {!workflows.loading && !workflows.data?.items?.length ? <p className="competition-agent-resource-empty">暂无任务</p> : null}
            </div>
            {selectedWorkflow ? <section className="competition-agent-task-preview">
              <strong>{selectedWorkflow.material} · {STATUS_LABELS[selectedWorkflow.status] || selectedWorkflow.status}</strong>
              {selectedWorkflow.status === 'succeeded' && selectedWorkflowResult.data?.vasp_detail ? <>
                <VaspElectronicProperties
                  rowId={selectedWorkflow.id}
                  dbKey="competition-results"
                  capabilities={selectedWorkflowResult.data.vasp_detail.capabilities}
                  fetchJson={fetchWorkflowPlot}
                  downloadFile={downloadWorkflowData}
                />
                <Link to={`/dashboard/results/${selectedWorkflow.id}`}>查看完整结果<ExternalLink size={12} /></Link>
              </> : <small>任务完成并通过验收后可绘制能带与 DOS。</small>}
            </section> : null}
          </> : null}
          {resourceTab === 'structures' ? <>
            <div className="competition-agent-pane-title"><span><Database size={16} />公开结构库</span><small>{structureLibrary.data?.total || 0}</small></div>
            <div className="competition-agent-search"><input value={structureQuery} placeholder="化学式、ID、拓扑" onChange={(event) => setStructureQuery(event.target.value)} /><button type="button" title="检索" onClick={() => setStructureSearch(structureQuery.trim())}><Search size={15} /></button></div>
            <div className="competition-agent-resource-list">{(structureLibrary.data?.items || []).map((item) => <label key={item.id}><input type="checkbox" checked={selectedStructureIds.includes(item.id)} onChange={() => toggle(setSelectedStructureIds, item.id)} /><span><strong>{item.formula}</strong><small>{item.id} · {item.source}</small></span></label>)}</div>
          </> : null}
          {resourceTab === 'literature' ? <>
            <div className="competition-agent-pane-title"><span><Library size={16} />文献库</span></div>
            <input className="competition-agent-library-name" value={libraryName} maxLength={80} onChange={(event) => setLibraryName(event.target.value)} aria-label="文献库名称" />
            <form className="competition-agent-search" onSubmit={(event) => { event.preventDefault(); findLiterature(); }}><input value={literatureQuery} placeholder="题名、材料名或 DOI" onChange={(event) => setLiteratureQuery(event.target.value)} /><button type="submit" title="联网检索" disabled={literatureSearching}><Search size={15} /></button></form>
            <div className="competition-agent-resource-list is-literature">
              {(literatureLibrary.data?.items || []).map((item) => <label key={item.id}><input type="checkbox" checked={selectedLiteratureIds.includes(item.id)} onChange={() => toggle(setSelectedLiteratureIds, item.id)} /><span><strong>{item.title}</strong><small>{item.year || '年份未知'} · {item.library_name}</small></span></label>)}
              {(literatureLibrary.data?.uploads || []).map((item) => <label key={item.id}><input type="checkbox" checked={selectedFileIds.includes(item.id)} onChange={() => toggle(setSelectedFileIds, item.id)} /><span><strong>{item.name}</strong><small>上传 PDF/文档 · {item.library_name}</small></span></label>)}
              {literatureSearching ? <p className="competition-agent-resource-empty">正在联网检索…</p> : null}
              {literatureSearchError ? <p className="competition-agent-error" role="alert">{literatureSearchError}</p> : null}
              {literatureResults.map((item) => <article key={item.id}><strong>{item.title}</strong><small>{item.year || '年份未知'} · {item.authors?.slice(0, 2).join(', ')}</small>{safeHttpsUrl(item.url) ? <a href={item.url} target="_blank" rel="noreferrer">查看文献<ExternalLink size={12} /></a> : null}<button type="button" onClick={() => addLiterature(item)}><Plus size={13} />加入索引</button></article>)}
            </div>
            <label className="competition-agent-action-button"><Upload size={15} />上传 PDF<input type="file" multiple accept=".pdf,.md,.txt" onChange={(event) => uploadFiles(event, 'literature')} /></label>
          </> : null}
        </aside>
      </section>

      {showManualBuilder ? <StructureBuilder /> : null}
    </main>
  );
}
