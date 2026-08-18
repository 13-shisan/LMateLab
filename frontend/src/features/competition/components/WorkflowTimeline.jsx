import { StatusBadge } from './CompetitionState.jsx';

const REQUIRED_STEPS = ['relax', 'scf', 'band', 'dos'];

const SAFE_ARTIFACT_NAMES = new Set([
  'OUTCAR',
  'vasprun.xml',
  'OSZICAR',
  'CONTCAR',
  'CHGCAR',
  'WAVECAR',
  'EIGENVAL',
  'DOSCAR',
]);

const STEP_LABELS = {
  relax: '结构优化',
  scf: '自洽计算',
  band: '能带',
  dos: '态密度',
};

function displayEvidenceValue(value) {
  return value === null || value === undefined || value === '' ? '-' : value;
}

function displayAttemptDirectory(value) {
  if (
    typeof value !== 'string'
    || value === ''
    || value !== value.trim()
    || !/^[A-Za-z0-9._/-]+$/.test(value)
    || value.startsWith('/')
    || value.split('/').some((segment) => segment === '.' || segment === '..')
  ) return '-';
  return value;
}

function displayAcceptance(value) {
  if (value === true) return '已验收';
  if (value === false) return '未验收';
  return '-';
}

function describeScientificState(step) {
  if (step?.status === 'blocked') return '依赖失败，未启动';
  if (step?.status === 'awaiting_acceptance') return '等待科学验收';
  if (step?.status === 'scientific_failed'
    || (step?.status === 'succeeded' && step?.accepted === false)) {
    return step?.reason ? `科学验收失败 · ${step.reason}` : '科学验收失败';
  }
  if (step?.accepted === true) return '科学验收通过';
  return '尚未验收';
}

function displayMeasurement(resources, key, unit) {
  const value = resources && typeof resources === 'object' ? resources[key] : null;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) return '-';
  return `${value} ${unit}`;
}

function safeArtifactHashes(acceptance) {
  if (!acceptance || !Array.isArray(acceptance.artifacts)) return [];
  return acceptance.artifacts.flatMap((artifact) => (
    artifact
    && typeof artifact === 'object'
    && SAFE_ARTIFACT_NAMES.has(artifact.name)
    && typeof artifact.sha256 === 'string'
    && /^[0-9a-f]{64}$/.test(artifact.sha256)
      ? [`${artifact.name} · ${artifact.sha256}`]
      : []
  ));
}

function indexWorkflowSteps(steps) {
  const byKey = new Map();
  if (!Array.isArray(steps)) return byKey;
  for (const step of steps) {
    if (!step || typeof step !== 'object' || typeof step.key !== 'string' || !step.key) continue;
    byKey.set(step.key, step);
  }
  return byKey;
}

export default function WorkflowTimeline({ steps = [], compact = false }) {
  const byKey = indexWorkflowSteps(steps);

  return (
    <ol
      className={`competition-timeline${compact ? ' is-compact' : ''}`}
      aria-label="固定四步 VASP 工作流"
    >
      {REQUIRED_STEPS.map((key) => {
        const suppliedStep = byKey.get(key);
        const step = suppliedStep
          ? { ...suppliedStep, status: suppliedStep.status || 'waiting' }
          : { key, status: 'waiting' };
        const artifactHashes = safeArtifactHashes(step.acceptance);
        const attemptDirectory = displayAttemptDirectory(step.attempt_dir);
        return (
          <li key={key} className={`is-${step.status}`}>
            <div className="competition-timeline-heading">
              <strong>{step.label || STEP_LABELS[key]}</strong>
              <StatusBadge status={step.status} />
            </div>
            {!compact ? (
              <dl className="competition-timeline-evidence">
                <div><dt>Job ID</dt><dd>{displayEvidenceValue(step.job_id)}</dd></div>
                <div><dt>Attempt</dt><dd>{displayEvidenceValue(step.attempt)}</dd></div>
                <div>
                  <dt>attempt_dir</dt>
                  <dd
                    className="is-path"
                    title={attemptDirectory === '-' ? undefined : attemptDirectory}
                  >
                    {attemptDirectory}
                  </dd>
                </div>
                <div><dt>Slurm state / exit_code</dt><dd>{displayEvidenceValue(step.slurm_state)} / {displayEvidenceValue(step.exit_code)}</dd></div>
                <div><dt>reason</dt><dd>{displayEvidenceValue(step.reason)}</dd></div>
                <div><dt>acceptance</dt><dd>{displayAcceptance(step.accepted)}</dd></div>
                <div><dt>科学状态</dt><dd>{describeScientificState(step)}</dd></div>
                <div>
                  <dt>elapsed / peak RSS</dt>
                  <dd>
                    {displayMeasurement(step.resources, 'elapsed_wall_seconds', 's')}
                    {' / '}
                    {displayMeasurement(step.resources, 'process_tree_peak_rss_kbytes', 'KiB')}
                  </dd>
                </div>
                <div>
                  <dt>output SHA-256</dt>
                  <dd>{artifactHashes.length > 0 ? artifactHashes.join('\n') : '-'}</dd>
                </div>
              </dl>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
