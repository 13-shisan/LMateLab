import { StatusBadge } from './CompetitionState.jsx';

const REQUIRED_STEPS = ['relax', 'scf', 'band', 'dos'];

const STEP_LABELS = {
  relax: '结构优化',
  scf: '自洽计算',
  band: '能带',
  dos: '态密度',
};

export default function WorkflowTimeline({ steps = [], compact = false }) {
  const byKey = new Map(steps.map((step) => [step.key, step]));

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
                <div><dt>Job ID</dt><dd>{step.job_id || '-'}</dd></div>
                <div><dt>Attempt</dt><dd>{step.attempt ?? '-'}</dd></div>
                <div><dt>attempt_dir</dt><dd className="is-path" title={step.attempt_dir || undefined}>{step.attempt_dir || '-'}</dd></div>
                <div><dt>Slurm state / exit_code</dt><dd>{step.slurm_state || '-'} / {step.exit_code || '-'}</dd></div>
                <div><dt>reason</dt><dd>{step.reason || '-'}</dd></div>
              </dl>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
