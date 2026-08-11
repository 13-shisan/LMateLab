import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse } from '@babel/parser';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

function loadFunction(source, name) {
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] });
  const declaration = ast.program.body
    .map((node) => (node.type === 'ExportNamedDeclaration' ? node.declaration : node))
    .find((node) => node?.type === 'FunctionDeclaration' && node.id?.name === name);
  assert.ok(declaration, `${name} must exist for executable regression coverage`);
  return new Function(
    `${source.slice(declaration.start, declaration.end)}\nreturn ${name};`,
  )();
}

test('competition state surfaces keep demo, loading, and failures explicit', () => {
  const source = read('../src/features/competition/components/CompetitionState.jsx');
  for (const pattern of [
    /演示数据：不会写入数据库或提交 Slurm 作业/,
    /loading|正在加载/,
    /empty|暂无/,
    /forbidden|权限不足/,
    /stale|最后可信状态/,
    /parse-error|解析失败/,
    /render-error|渲染失败/,
    /error|加载失败/,
  ]) {
    assert.match(source, pattern);
  }
  for (const exportedComponent of [
    'DemoDataBanner',
    'CompetitionState',
    'StatusBadge',
    'PreviewReadOnlyNotice',
  ]) {
    assert.match(source, new RegExp(`export function ${exportedComponent}`));
  }
});

test('workflow timeline is fixed to relax scf band dos and keeps job evidence', () => {
  const source = read('../src/features/competition/components/WorkflowTimeline.jsx');
  for (const token of [
    'relax',
    'scf',
    'band',
    'dos',
    'job_id',
    'attempt',
    'attempt_dir',
    'slurm_state',
    'exit_code',
    'reason',
  ]) {
    assert.match(source, new RegExp(token));
  }
  assert.match(source, /status:\s*['"]waiting['"]/);
});

test('workflow evidence preserves numeric zero exit codes', () => {
  const source = read('../src/features/competition/components/WorkflowTimeline.jsx');
  const displayEvidenceValue = loadFunction(source, 'displayEvidenceValue');

  assert.equal(displayEvidenceValue(0), 0);
  assert.equal(displayEvidenceValue('0:0'), '0:0');
  assert.equal(displayEvidenceValue(null), '-');
  assert.equal(displayEvidenceValue(undefined), '-');
  assert.match(source, /displayEvidenceValue\(step\.exit_code\)/);
});

test('workflow step indexing tolerates invalid collections and entries', () => {
  const source = read('../src/features/competition/components/WorkflowTimeline.jsx');
  const indexWorkflowSteps = loadFunction(source, 'indexWorkflowSteps');

  for (const invalidSteps of [null, undefined, {}, 'relax']) {
    assert.deepEqual([...indexWorkflowSteps(invalidSteps)], []);
  }
  const relax = { key: 'relax', status: 'succeeded' };
  const band = { key: 'band', status: 'running' };
  const indexed = indexWorkflowSteps([null, {}, { key: '' }, relax, undefined, band]);
  assert.deepEqual([...indexed], [['relax', relax], ['band', band]]);
  assert.match(source, /const byKey = indexWorkflowSteps\(steps\)/);
});

test('competition table stays compact and exposes one read-only open action', () => {
  const source = read('../src/features/competition/components/CompetitionTable.jsx');
  for (const token of [
    'items',
    'kind',
    'onOpen',
    'material',
    'source',
    'status',
    'current_step',
    'latest_job_id',
    'updated_at',
  ]) {
    assert.match(source, new RegExp(token));
  }
  assert.equal(source.match(/<ArrowRight\b/g)?.length, 1);
  assert.match(source, /title=/);
  assert.match(source, /aria-label=/);
  assert.match(source, /type=['"]button['"]/);
  assert.match(source, /onClick=/);
  assert.doesNotMatch(source, /fetch\(|axios|method:\s*['"](?:POST|PUT|PATCH|DELETE)/);
});

test('competition shared styles preserve stable responsive geometry', () => {
  const source = read('../src/features/competition/components/competitionComponents.css');
  assert.match(source, /\.competition-state\s*\{[^}]*min-height:\s*96px/s);
  assert.match(source, /\.competition-status\s*\{[^}]*line-height:\s*[^;]+;[^}]*letter-spacing:\s*0/s);
  assert.match(source, /\.competition-table-scroll\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(source, /\.competition-timeline\s*>\s*li:nth-child\(3\)/);
  assert.match(source, /\.competition-timeline\s*>\s*li:nth-child\(4\)/);
  assert.doesNotMatch(source, /letter-spacing:\s*-/);
  for (const radius of source.matchAll(/border-radius:\s*(\d+)px/g)) {
    assert.ok(Number(radius[1]) <= 8, `border radius exceeds 8px: ${radius[0]}`);
  }
});

test('disabled competition table actions do not receive hover styling', () => {
  const source = read('../src/features/competition/components/competitionComponents.css');
  assert.match(source, /\.competition-table-action button:not\(:disabled\):hover/);
  assert.match(source, /\.vasp-viewer-reset:hover/);
  assert.doesNotMatch(source, /\.competition-table-action button:hover/);
});
