import { useState } from 'react';
import { Save, Send } from 'lucide-react';

import { canWriteCompetitionData } from '../../config/competitionAccess';
import {
  useCompetitionData,
} from '../../features/competition/CompetitionDataContext';
import { PreviewReadOnlyNotice } from '../../features/competition/components/CompetitionState';
import { DEMO_STRUCTURE } from '../../features/competition/data/demoFixtures';
import VaspStructureViewer from '../db/vasp-detail/VaspStructureViewer';
import '../db/vasp-detail/VaspTaskDetail.css';
import './CompetitionPages.css';

const WORKFLOW_STEPS = [
  { key: 'relax', label: 'relax', dependsOn: [], purpose: '优化离子位置与晶格' },
  { key: 'scf', label: 'SCF', dependsOn: ['relax'], purpose: '生成已验收自洽电荷密度' },
  { key: 'band', label: 'BAND', dependsOn: ['scf'], purpose: '沿固定高对称路径计算能带' },
  { key: 'dos', label: 'DOS', dependsOn: ['scf'], purpose: '基于自洽结果计算态密度' },
];

const STEP_PARAMETERS = {
  relax: {
    ENCUT: '520 eV',
    'k-point': '12 x 12 x 1',
    convergence: 'EDIFF 1e-6 / EDIFFG -0.01',
  },
  scf: {
    ENCUT: '520 eV',
    'k-point': '18 x 18 x 1',
    convergence: 'EDIFF 1e-7',
  },
  band: {
    ENCUT: '520 eV',
    'k-point': '固定高对称路径',
    convergence: '复用已验收 SCF 电荷密度',
  },
  dos: {
    ENCUT: '520 eV',
    'k-point': '24 x 24 x 1',
    convergence: '复用已验收 SCF 电荷密度',
  },
};

function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null');
  } catch {
    return null;
  }
}

export default function CompetitionNewCalculation() {
  const { provider, mode } = useCompetitionData();
  const [sourceKind, setSourceKind] = useState('builtin');
  const [selectedStep, setSelectedStep] = useState('relax');
  const [commandError, setCommandError] = useState('');
  const user = readStoredUser();
  const readOnly = mode === 'demo' || !canWriteCompetitionData(user);
  const activeStep = WORKFLOW_STEPS.find(({ key }) => key === selectedStep) || WORKFLOW_STEPS[0];
  const draft = {
    id: 'preview-draft',
    source_kind: sourceKind,
    template_version: 'mos2-v1',
    steps: WORKFLOW_STEPS.map((step) => step.key),
  };

  async function handleSaveDraft() {
    if (readOnly) return;
    if (sourceKind !== 'builtin') {
      setCommandError('上传来源仅供只读占位，未选择结构，不能保存。');
      return;
    }
    setCommandError('');
    try {
      await provider.saveDraft(draft);
    } catch (error) {
      setCommandError(error?.message || '草稿保存失败');
    }
  }

  async function handleSubmitWorkflow() {
    if (readOnly) return;
    if (sourceKind !== 'builtin') {
      setCommandError('上传来源仅供只读占位，未选择结构，不能提交。');
      return;
    }
    setCommandError('');
    try {
      await provider.submitWorkflow(draft.id);
    } catch (error) {
      setCommandError(error?.message || '工作流提交失败');
    }
  }

  return (
    <main className="competition-calculation-page">
      <header className="competition-calculation-header">
        <div>
          <h1>新建 VASP 计算</h1>
          <p>单层 MoS2 固定四步工作流审阅</p>
        </div>
        {readOnly ? <PreviewReadOnlyNotice /> : null}
      </header>

      <section className="competition-work-section" aria-labelledby="competition-source-title">
        <div className="competition-section-heading">
          <div>
            <span>01</span>
            <h2 id="competition-source-title">来源与结构</h2>
          </div>
          <p>演示参数 · 模板 mos2-v1 · 输入 SHA-256：提交前生成</p>
        </div>

        <div className="competition-source-segment" role="group" aria-label="结构来源">
          <button
            className={sourceKind === 'builtin' ? 'is-active' : ''}
            type="button"
            aria-pressed={sourceKind === 'builtin'}
            onClick={() => setSourceKind('builtin')}
          >
            内置 MoS2
          </button>
          <button
            className={sourceKind === 'upload' ? 'is-active' : ''}
            type="button"
            aria-pressed={sourceKind === 'upload'}
            onClick={() => setSourceKind('upload')}
          >
            上传结构
          </button>
        </div>

        <div className="competition-calculation-grid">
          <div className="competition-structure-viewer">
            {sourceKind === 'builtin' ? (
              <VaspStructureViewer structure={DEMO_STRUCTURE} />
            ) : (
              <div className="competition-upload-placeholder">
                <label htmlFor="competition-structure-file">结构文件</label>
                <input
                  id="competition-structure-file"
                  type="file"
                  accept=".vasp,.poscar,.cif"
                  disabled
                />
                <strong>未选择文件</strong>
                <span>POSCAR/CIF 文本，最大 1 MiB，最多 200 个原子</span>
                <small>本预览仅展示受限上传占位，不解析或上传文件</small>
              </div>
            )}
          </div>

          <aside className="competition-structure-summary" aria-label="晶格摘要">
            <h3>晶格摘要</h3>
            <dl>
              <div><dt>化学式</dt><dd>MoS2</dd></div>
              <div><dt>原子数</dt><dd>{DEMO_STRUCTURE.symbols.length}</dd></div>
              <div><dt>a</dt><dd>3.158 Å</dd></div>
              <div><dt>b</dt><dd>3.158 Å</dd></div>
              <div><dt>c</dt><dd>20.000 Å</dd></div>
              <div><dt>周期性</dt><dd>x / y</dd></div>
            </dl>
            <p>内置结构 · 演示数据</p>
          </aside>
        </div>
      </section>

      <section className="competition-work-section" aria-labelledby="competition-workflow-title">
        <div className="competition-section-heading">
          <div>
            <span>02</span>
            <h2 id="competition-workflow-title">不可变依赖</h2>
          </div>
          <p>relax → SCF → BAND / DOS</p>
        </div>

        <div className="competition-workflow-scroll">
          <ol className="competition-workflow-graph" aria-label="固定四步工作流">
            {WORKFLOW_STEPS.map((step) => (
              <li
                className={`competition-workflow-step is-${step.key}`}
                key={step.key}
              >
                <button
                  className={selectedStep === step.key ? 'is-active' : ''}
                  type="button"
                  aria-pressed={selectedStep === step.key}
                  onClick={() => setSelectedStep(step.key)}
                >
                  <span>{step.label}</span>
                  <small>
                    {step.dependsOn.length === 0
                      ? '起点'
                      : `依赖 ${step.dependsOn.map((key) => key.toUpperCase()).join(' + ')}`}
                  </small>
                </button>
                <p>{step.purpose}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="competition-work-section" aria-labelledby="competition-review-title">
        <div className="competition-section-heading">
          <div>
            <span>03</span>
            <h2 id="competition-review-title">参数与资源审阅</h2>
          </div>
          <p>只读审阅，不代表生产校验</p>
        </div>

        <div className="competition-review-grid">
          <div className="competition-parameter-review">
            <h3>{activeStep.label} · 演示参数</h3>
            <dl>
              {Object.entries(STEP_PARAMETERS[activeStep.key]).map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{value}<small>演示参数</small></dd>
                </div>
              ))}
            </dl>
          </div>

          <div className="competition-resource-review">
            <h3>Slurm 资源 · 演示参数</h3>
            <dl>
              <div><dt>Partition</dt><dd>P107-RTX5090<small>演示参数</small></dd></div>
              <div><dt>资源上限</dt><dd>最大 4 GPU / 16 CPU<small>演示参数</small></dd></div>
              <div><dt>证据单位</dt><dd>每步独立一个 Job / attempt 证据记录<small>演示参数</small></dd></div>
            </dl>
          </div>
        </div>
      </section>

      <footer className="competition-command-bar">
        <div>
          <strong>预览草稿</strong>
          <span>preview-draft · mos2-v1 · 4 步</span>
          {commandError ? <p role="alert">{commandError}</p> : null}
        </div>
        <div className="competition-command-actions">
          <button
            className="competition-command-button is-secondary"
            type="button"
            disabled={readOnly}
            onClick={handleSaveDraft}
          >
            <Save size={16} aria-hidden="true" />
            保存草稿
          </button>
          <button
            className="competition-command-button is-primary"
            type="button"
            disabled={readOnly}
            onClick={handleSubmitWorkflow}
          >
            <Send size={16} aria-hidden="true" />
            提交四步工作流
          </button>
        </div>
      </footer>
    </main>
  );
}
