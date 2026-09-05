import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Box, CheckCircle2, Download, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { canWriteCompetitionData } from '../../../config/competitionAccess';
import VaspStructureViewer from '../../../pages/db/vasp-detail/VaspStructureViewer';
import '../../../pages/db/vasp-detail/VaspTaskDetail.css';
import { useCompetitionData, useCompetitionResource } from '../CompetitionDataContext';
import { CompetitionState } from '../components/CompetitionState';


const DEFAULT_PARAMETERS = Object.freeze({
  material_id: 'MoS2_monolayer', repeat_a: 1, repeat_b: 1, layers: 1,
  vacuum_angstrom: 15, interlayer_spacing_angstrom: 6.2, strain_percent: 0,
  kpoints_source: 'mock_qoder', kpoints_mesh: null,
});
const DEFAULT_INCAR = Object.freeze({
  relax: { ENCUT: 520, EDIFF: 0.000001, EDIFFG: -0.01, NSW: 120, SIGMA: 0.05 },
  scf: { ENCUT: 520, EDIFF: 0.0000001, NELM: 120, SIGMA: 0.05 },
  band: { ENCUT: 520, EDIFF: 0.0000001, NELM: 120, SIGMA: 0.05 },
  dos: { ENCUT: 520, EDIFF: 0.0000001, NELM: 120, SIGMA: 0.05, NEDOS: 3000 },
});
const KPOINT_STEPS = [['relax', '结构优化'], ['scf', 'SCF'], ['dos', 'DOS']];


function readStoredUser() {
  try { return JSON.parse(globalThis.localStorage?.getItem('user') || 'null'); } catch { return null; }
}

function saveDownload({ blob, filename }) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function initialMeshes(base) {
  const [a, b, z] = base;
  return {
    relax: [a, b, z],
    scf: [Math.min(60, Math.max(a, Math.round(a * 1.5))), Math.min(60, Math.max(b, Math.round(b * 1.5))), z],
    dos: [Math.min(60, a * 2), Math.min(60, b * 2), z],
  };
}

function initialIncar(plan) {
  const values = structuredClone(DEFAULT_INCAR);
  for (const change of plan?.parameter_changes || []) {
    const template = (plan.templates || []).find((item) => item.id === change.template_id);
    const numeric = Number(change.value);
    if (template?.step && Object.hasOwn(values[template.step] || {}, change.parameter) && Number.isFinite(numeric)) {
      values[template.step][change.parameter] = numeric;
    }
  }
  return values;
}


export default function StructureBuilder({ preparedStructure = null, calculationPlan = null }) {
  const { provider, mode } = useCompetitionData();
  const navigate = useNavigate();
  const operator = mode === 'live' && canWriteCompetitionData(readStoredUser());
  const catalog = useCompetitionResource(useCallback(() => provider.listCuratedStructures(), [provider]));
  const [parameters, setParameters] = useState(DEFAULT_PARAMETERS);
  const [manualMesh, setManualMesh] = useState([15, 15, 1]);
  const [result, setResult] = useState(null);
  const [review, setReview] = useState(null);
  const [building, setBuilding] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [queueing, setQueueing] = useState(false);
  const [error, setError] = useState('');
  const queueLock = useRef(false);
  const autoBuildHandled = useRef(null);
  const selected = useMemo(
    () => (catalog.data?.items || []).find((item) => item.id === parameters.material_id),
    [catalog.data, parameters.material_id],
  );
  const externalPrepared = preparedStructure?.source === 'user-upload';
  const workflowCompatible = result?.workflow_compatible ?? selected?.workflow_compatible;

  useEffect(() => {
    const materialId = preparedStructure?.material_id;
    if (!materialId || result || autoBuildHandled.current === preparedStructure) return;
    autoBuildHandled.current = preparedStructure;
    setParameters((current) => ({
      ...current,
      ...preparedStructure.parameters,
      material_id: materialId,
    }));
    setResult(preparedStructure);
  }, [preparedStructure, result]);

  function update(name, rawValue) {
    const value = ['material_id', 'kpoints_source'].includes(name) ? rawValue : Number(rawValue);
    setParameters((current) => ({ ...current, [name]: value }));
    setResult(null);
    setReview(null);
    setError('');
  }

  function requestParameters() {
    return {
      ...parameters,
      kpoints_mesh: parameters.kpoints_source === 'manual' ? manualMesh : null,
    };
  }

  async function build(event) {
    event.preventDefault();
    if (!operator || building) return;
    setBuilding(true);
    setError('');
    try { setResult(await provider.buildCuratedStructure(requestParameters())); }
    catch { setResult(null); setError('结构构建未通过服务端校验。'); }
    finally { setBuilding(false); }
  }

  async function download() {
    if (!operator || downloading) return;
    setDownloading(true);
    setError('');
    try { saveDownload(await provider.downloadCuratedStructureBundle(requestParameters())); }
    catch { setError('VASP 输入包生成失败。'); }
    finally { setDownloading(false); }
  }

  function openReview() {
    if (!result || !workflowCompatible) return;
    setReview({
      template: 'mos2_v1', task: 'full_pipeline', poscar: result.files.POSCAR,
      kpoints: initialMeshes(result.kpoints.mesh), incar: initialIncar(calculationPlan),
    });
  }

  function updateReviewMesh(step, axis, rawValue) {
    const value = Number(rawValue);
    setReview((current) => ({
      ...current,
      kpoints: { ...current.kpoints, [step]: current.kpoints[step].map((entry, index) => index === axis ? value : entry) },
    }));
  }

  function updateIncar(step, key, rawValue) {
    setReview((current) => ({
      ...current,
      incar: { ...current.incar, [step]: { ...current.incar[step], [key]: Number(rawValue) } },
    }));
  }

  async function verifyAndQueue() {
    if (!operator || !review || queueLock.current || queueing) return;
    queueLock.current = true;
    setQueueing(true);
    setError('');
    try {
      const file = new File([review.poscar], 'POSCAR', { type: 'text/plain' });
      const upload = await provider.uploadStructure(file);
      const draft = await provider.saveDraft({
        template_version: review.template,
        source_kind: 'upload',
        structure_upload_id: upload.id,
        steps: ['relax', 'scf', 'band', 'dos'],
        parameters: review.incar,
        kpoints: { source: result.kpoints.source, meshes: review.kpoints },
      });
      const validated = await provider.submitWorkflow(draft.id);
      await provider.startWorkflow(validated.id);
      navigate(`/dashboard/workflows/${encodeURIComponent(validated.id)}`);
    } catch (failure) {
      setError(failure?.message || '核验或排队失败；未确认的请求不会继续提交。');
      setReview(null);
    } finally {
      queueLock.current = false;
      setQueueing(false);
    }
  }

  return (
    <section className="competition-structure-builder" aria-labelledby="curated-structure-title">
      <div className="competition-structure-builder-heading"><div><span><Box size={15} /> Agent 计算交接</span><h2 id="curated-structure-title">核验并提交新建计算</h2></div><p>沿用现有上传、草稿、校验和工作流启动流程</p></div>
      <div className="competition-structure-builder-grid">
        <form onSubmit={build}>
          {catalog.status === 'loading' ? <CompetitionState status="loading" /> : null}
          <label>材料<select value={parameters.material_id} onChange={(event) => update('material_id', event.target.value)} disabled={!operator || building || externalPrepared}>{externalPrepared ? <option value={parameters.material_id}>{result?.summary?.formula} · 上传结构</option> : null}{(catalog.data?.items || []).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.formula}</option>)}</select></label>
          <fieldset disabled={externalPrepared}><legend>面内超胞</legend><label>a 方向<input type="number" min="1" max="6" value={parameters.repeat_a} onChange={(event) => update('repeat_a', event.target.value)} /></label><label>b 方向<input type="number" min="1" max="6" value={parameters.repeat_b} onChange={(event) => update('repeat_b', event.target.value)} /></label></fieldset>
          <fieldset disabled={externalPrepared}><legend>层数与真空层</legend><label>层数<input type="number" min="1" max="8" value={parameters.layers} onChange={(event) => update('layers', event.target.value)} /></label><label>真空层 (Å)<input type="number" min="8" max="40" value={parameters.vacuum_angstrom} onChange={(event) => update('vacuum_angstrom', event.target.value)} /></label></fieldset>
          <fieldset disabled={externalPrepared}><legend>晶胞调整</legend><label>层间距 (Å)<input type="number" min="3" max="10" step="0.1" value={parameters.interlayer_spacing_angstrom} onChange={(event) => update('interlayer_spacing_angstrom', event.target.value)} /></label><label>面内应变 (%)<input type="number" min="-5" max="5" step="0.1" value={parameters.strain_percent} onChange={(event) => update('strain_percent', event.target.value)} /></label></fieldset>
          <label>KPOINTS 来源<select value={parameters.kpoints_source} onChange={(event) => update('kpoints_source', event.target.value)} disabled={externalPrepared}><option value="mock_qoder">Agent 建议</option><option value="manual">用户指定</option></select></label>
          {parameters.kpoints_source === 'manual' ? <fieldset><legend>Gamma 网格</legend>{['kx', 'ky', 'kz'].map((label, axis) => <label key={label}>{label}<input type="number" min="1" max="60" value={manualMesh[axis]} onChange={(event) => setManualMesh((mesh) => mesh.map((value, index) => index === axis ? Number(event.target.value) : value))} /></label>)}</fieldset> : null}
          <label>INCAR 模板<select value="mos2_v1" disabled><option value="mos2_v1">mos2_v1 · 竞赛受控模板</option></select></label>
          <label>计算任务<select value="full_pipeline" disabled><option value="full_pipeline">relax → SCF → BAND → DOS</option></select></label>
          <div className="competition-structure-builder-actions"><button type="submit" disabled={!operator || building || externalPrepared}>{building ? '构建中' : '生成 POSCAR / KPOINTS'}</button><button type="button" onClick={download} disabled={!operator || downloading || externalPrepared}><Download size={16} />下载 ZIP</button><button type="button" onClick={openReview} disabled={!operator || !result || !workflowCompatible}><CheckCircle2 size={16} />核验并提交</button></div>
          {!operator ? <p>Viewer 只能浏览目录。</p> : null}{error ? <p className="competition-agent-error" role="alert">{error}</p> : null}
        </form>
        <div className="competition-structure-preview" aria-live="polite">{result?.structure ? <VaspStructureViewer structure={result.structure} /> : <div className="competition-structure-empty">选择参数后构建结构预览</div>}<div className="competition-structure-summary-line"><strong>{result?.summary?.formula || selected?.formula || '—'}</strong><span>{result?.summary?.atom_count ?? '—'} 原子</span><span>{result?.summary?.layers ?? parameters.layers ?? '—'} 层</span><span>{workflowCompatible ? '可进入受控工作流' : '仅分析与导出'}</span></div>{result ? <div className="competition-structure-files">{Object.keys(result.files || {}).map((name) => <code key={name}>{name}</code>)}</div> : null}<p>POTCAR 不包含在输入包中；Agent 参数必须人工核验。</p></div>
      </div>

      {review ? <div className="competition-agent-modal-backdrop"><section className="competition-agent-review" role="dialog" aria-modal="true" aria-labelledby="agent-review-title"><header><div><h2 id="agent-review-title">核验计算输入</h2><p>确认后由应用工作流协调器进入 Slurm 队列</p></div><button type="button" onClick={() => setReview(null)} title="关闭核验"><X size={18} /></button></header><div className="competition-agent-review-body"><label>POSCAR<textarea value={review.poscar} onChange={(event) => setReview((current) => ({ ...current, poscar: event.target.value }))} /></label><div className="competition-agent-review-grid">{KPOINT_STEPS.map(([step, label]) => <fieldset key={step}><legend>{label} KPOINTS</legend>{['kx', 'ky', 'kz'].map((axisLabel, axis) => <label key={axisLabel}>{axisLabel}<input type="number" min="1" max="60" value={review.kpoints[step][axis]} onChange={(event) => updateReviewMesh(step, axis, event.target.value)} /></label>)}</fieldset>)}</div><p className="competition-agent-band-lock">BAND 固定为 Γ-M-K-Γ 线模路径，不允许 Agent 或用户覆盖。</p><div className="competition-agent-review-grid">{Object.entries(review.incar).map(([step, values]) => <fieldset key={step}><legend>{step.toUpperCase()} INCAR</legend>{Object.entries(values).map(([key, value]) => <label key={key}>{key}<input type="number" value={value} onChange={(event) => updateIncar(step, key, event.target.value)} /></label>)}</fieldset>)}</div></div><footer><button type="button" onClick={() => setReview(null)}>返回修改</button><button type="button" onClick={verifyAndQueue} disabled={queueing}>{queueing ? '正在核验并排队' : '核验并进入队列'}</button></footer></section></div> : null}
    </section>
  );
}
