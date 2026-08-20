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
  assert.ok(declaration, `${name} must exist`);
  return new Function(`${source.slice(declaration.start, declaration.end)}\nreturn ${name};`)();
}

test('workflow timeline keeps the trusted status and renders stale scheduler evidence separately', () => {
  const source = read('../src/features/competition/components/WorkflowTimeline.jsx');
  const displayStaleSince = loadFunction(source, 'displayStaleSince');
  const timestamp = '2026-08-20T09:15:00+00:00';

  assert.equal(displayStaleSince(timestamp), timestamp);
  for (const invalid of [null, '', 'yesterday', '2026-08-20T09:15:00', 'x'.repeat(65)]) {
    assert.equal(displayStaleSince(invalid), '-');
  }
  assert.match(source, /step\.scheduler_stale\s*===\s*true/);
  assert.match(source, /状态陈旧/);
  assert.match(source, /displayStaleSince\(step\.stale_since\)/);
  assert.match(source, /<StatusBadge\s+status=\{step\.status\}/);
});

test('workflow detail retains the last good frame when polling refresh fails', () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');

  assert.match(source, /state\.refreshError\s*===\s*['"]refresh-failed['"]/);
  assert.match(source, /已保留上一次有效数据并将自动重试/);
  assert.match(source, /shouldPollWorkflow\(mode,\s*current\?\.status\)/);
});

test('viewer workflow commands remain disabled while operator commands use fixed provider methods', () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const provider = read('../src/features/competition/data/apiCompetitionDataProvider.js');

  assert.match(source, /mode\s*!==\s*['"]live['"]/);
  assert.match(source, /!canWriteCompetitionData\(user\)/);
  assert.match(source, /provider\.cancelWorkflow\(workflow\.id\)/);
  assert.match(source, /provider\.retryWorkflow\(\{\s*id:\s*workflow\.id,\s*step:\s*failedStep\.key\s*\}\)/);
  assert.match(provider, /cancelWorkflow\(id\)[\s\S]*jsonPost/);
  assert.match(provider, /retryWorkflow\(\{\s*id,\s*step\s*\}\)[\s\S]*jsonPost/);
  assert.doesNotMatch(provider, /sbatch|squeue|sacct|scancel|vasp_std|\/home\//i);
});
