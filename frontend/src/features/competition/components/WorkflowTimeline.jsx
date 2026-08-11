import { StatusBadge } from './CompetitionState.jsx';

const REQUIRED_STEPS = ['relax', 'scf', 'band', 'dos'];

const STEP_LABELS = {
  relax: '结构优化',
  scf: '自洽计算',
  band: '能带',
  dos: '态密度',
};

function displayEvidenceValue(value) {
  return value === null || value === undefined || value === '' ? '-' : value;
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
                <div><dt>attempt_dir</dt><dd className="is-path" title={step.attempt_dir || undefined}>{displayEvidenceValue(step.attempt_dir)}</dd></div>
                <div><dt>Slurm state / exit_code</dt><dd>{displayEvidenceValue(step.slurm_state)} / {displayEvidenceValue(step.exit_code)}</dd></div>
                <div><dt>reason</dt><dd>{displayEvidenceValue(step.reason)}</dd></div>
              </dl>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
