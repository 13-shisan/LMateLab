import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse } from '@babel/parser';

import { canWriteCompetitionData } from '../src/config/competitionAccess.js';
import { createDemoCompetitionDataProvider } from '../src/features/competition/data/demoCompetitionDataProvider.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

function loadFunction(source, name, bindings = {}) {
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] });
  const declaration = ast.program.body
    .map((node) => (node.type === 'ExportNamedDeclaration' ? node.declaration : node))
    .find((node) => node?.type === 'FunctionDeclaration' && node.id?.name === name);
  assert.ok(declaration, `${name} must exist for executable regression coverage`);
  const names = Object.keys(bindings);
  return new Function(
    ...names,
    `${source.slice(declaration.start, declaration.end)}\nreturn ${name};`,
  )(...names.map((key) => bindings[key]));
}

function findNodes(value, predicate, matches = []) {
  if (value === null || typeof value !== 'object') return matches;
  if (predicate(value)) matches.push(value);
  for (const child of Object.values(value)) {
    if (Array.isArray(child)) {
      for (const entry of child) findNodes(entry, predicate, matches);
    } else {
      findNodes(child, predicate, matches);
    }
  }
  return matches;
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

test('non-compact workflow evidence exposes explicit acceptance without expanding compact mode', () => {
  const source = read('../src/features/competition/components/WorkflowTimeline.jsx');
  const displayAcceptance = loadFunction(source, 'displayAcceptance');

  assert.equal(displayAcceptance(true), '已验收');
  assert.equal(displayAcceptance(false), '未验收');
  assert.equal(displayAcceptance(null), '-');
  assert.equal(displayAcceptance(undefined), '-');
  assert.match(source, /<dt>acceptance<\/dt><dd>\{displayAcceptance\(step\.accepted\)\}<\/dd>/);
  assert.match(
    source,
    /\{!compact\s*\?\s*\([\s\S]*?<dl\s+className=['"]competition-timeline-evidence['"][\s\S]*?acceptance[\s\S]*?<\/dl>[\s\S]*?\)\s*:\s*null\}/,
  );
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

test('competition dashboard loads operational preview data without placeholder claims', () => {
  const source = read('../src/pages/CompetitionDashboard.jsx');

  for (const token of [
    'getDashboard',
    '新建计算',
    '最近工作流',
    'WorkflowTimeline',
    'Slurm 资源',
    'DemoDataBanner',
    '107 杯 VASP 计算工作台',
    '结构到 BAND/DOS 的固定可追溯闭环',
    'summary.total',
    'summary.running',
    'summary.recent_succeeded',
    'summary.needs_attention',
    'recent_workflows',
    'active_workflow',
    'slurm.partition',
    'slurm.queued',
    'slurm.running',
    'slurm.updated_at',
    '演示快照',
  ]) {
    assert.match(source, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  assert.match(source, /import\s+['"]\.\/Dashboard\.css['"];?/);
  assert.match(source, /const\s*{\s*provider,\s*mode\s*}\s*=\s*useCompetitionData\(\);/);
  assert.match(source, /const\s+loadDashboard\s*=\s*useCallback\(\(\)\s*=>\s*provider\.getDashboard\(\),\s*\[provider\]\);/);
  assert.match(source, /const\s+state\s*=\s*useCompetitionResource\(loadDashboard\);/);
  assert.match(source, /normalizeCompetitionDashboardData\(state\.data\)/);
  assert.match(source, /state\.status\s*!==\s*['"]ready['"]/);
  assert.match(source, /<main\s+className=['"]competition-page['"]>/);
  assert.match(source, /message=\{state\.error\?\.message\}/);
  assert.match(source, /mode\s*===\s*['"]demo['"]\s*\?\s*<DemoDataBanner\s*\/>\s*:\s*null/);
  assert.match(source, /<Link[\s\S]*?to=['"]\/dashboard\/calculations\/new['"][\s\S]*?aria-label=['"]新建计算['"][\s\S]*?title=['"]新建计算['"][\s\S]*?<SquarePlus\b/);
  assert.match(source, /<CompetitionTable\s+items=\{recent_workflows\}\s+kind=['"]workflow['"]\s+onOpen=\{openWorkflow\}/);
  assert.match(source, /navigate\(`\/dashboard\/workflows\/\$\{/);
  assert.match(source, /<WorkflowTimeline\s+steps=\{active_workflow\.steps\}\s+compact\s*\/>/);
  assert.match(source, /<CompetitionState\s+status=['"]empty['"]\s+message=['"]暂无当前工作流['"]\s*\/>/);
  assert.doesNotMatch(source, />0</);
  assert.doesNotMatch(source, /暂无工作流记录/);
  assert.doesNotMatch(source, /正常运行/);
  assert.doesNotMatch(source, /username|job[ _-]?name|work[ _-]?directory/i);
});

test('competition dashboard normalizes malformed ready payloads', () => {
  const source = read('../src/pages/CompetitionDashboard.jsx');
  const normalizeDashboard = loadFunction(source, 'normalizeCompetitionDashboardData');
  const emptyDashboard = {
    summary: {},
    recent_workflows: [],
    active_workflow: null,
    slurm: {},
  };

  for (const payload of [null, undefined, false, 42, 'dashboard', [], new Date()]) {
    assert.deepEqual(normalizeDashboard(payload), emptyDashboard);
  }

  for (const payload of [
    { summary: null, slurm: null, recent_workflows: null, active_workflow: [] },
    { summary: [], slurm: new Date(), recent_workflows: {}, active_workflow: 'workflow' },
  ]) {
    const normalized = normalizeDashboard(payload);
    assert.deepEqual(normalized, emptyDashboard);
    assert.equal(Object.getPrototypeOf(normalized.summary), Object.prototype);
    assert.equal(Object.getPrototypeOf(normalized.slurm), Object.prototype);
  }

  const summary = { total: 1 };
  const recentWorkflows = [{ id: 'wf-1' }];
  const activeWorkflow = { id: 'wf-1', steps: [] };
  const slurm = { partition: 'P107' };
  assert.deepEqual(normalizeDashboard({
    summary,
    recent_workflows: recentWorkflows,
    active_workflow: activeWorkflow,
    slurm,
  }), {
    summary,
    recent_workflows: recentWorkflows,
    active_workflow: activeWorkflow,
    slurm,
  });
});

test('competition dashboard styles keep the approved responsive work layout', () => {
  const source = read('../src/pages/Dashboard.css');

  assert.match(
    source,
    /\.lm-dashboard-grid\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1\.65fr\)\s+minmax\(310px,\s*0\.95fr\)/s,
  );
  assert.match(
    source,
    /\.lm-dashboard-grid\.competition-dashboard-grid\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1\.65fr\)\s+minmax\(280px,\s*\.85fr\)/s,
  );
  const tablet = source.match(/@media\s*\(max-width:\s*1120px\)\s*{([\s\S]*?)}\s*@media/)?.[1] || '';
  assert.match(tablet, /\.lm-dashboard-grid\s*{[^}]*grid-template-columns:\s*1fr[^}]*align-items:\s*start/s);
  assert.match(tablet, /\.lm-dashboard-grid\.competition-dashboard-grid\s*{[^}]*grid-template-columns:\s*1fr[^}]*align-items:\s*start/s);
  const mobile = source.match(/@media\s*\(max-width:\s*700px\)\s*{([\s\S]*)}\s*$/)?.[1] || '';
  assert.match(mobile, /\.lm-overview-grid\s*{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/s);
  assert.match(mobile, /\.lm-primary-action\s*{[^}]*width:\s*36px[^}]*height:\s*36px/s);
  assert.doesNotMatch(source, /letter-spacing:\s*-/);
  for (const radius of source.matchAll(/border-radius:\s*(\d+)px/g)) {
    assert.ok(Number(radius[1]) <= 8, `border radius exceeds 8px: ${radius[0]}`);
  }
});

test('competition dashboard compact timeline keeps the scf band dos fork visible', () => {
  const source = read('../src/pages/Dashboard.css');

  assert.match(
    source,
    /\.competition-active-workflow\s+\.competition-timeline\.is-compact\s*{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)[^}]*grid-template-rows:\s*repeat\(3,\s*auto\)[^}]*overflow-x:\s*hidden/s,
  );
  assert.match(
    source,
    /\.competition-active-workflow\s+\.competition-timeline\.is-compact\s*>\s*li:nth-child\(1\)\s*{[^}]*grid-column:\s*1\s*\/\s*-1[^}]*grid-row:\s*1/s,
  );
  assert.match(
    source,
    /\.competition-active-workflow\s+\.competition-timeline\.is-compact\s*>\s*li:nth-child\(2\)\s*{[^}]*grid-column:\s*1\s*\/\s*-1[^}]*grid-row:\s*2/s,
  );
  assert.match(
    source,
    /\.competition-active-workflow\s+\.competition-timeline\.is-compact\s*>\s*li:nth-child\(3\)\s*{[^}]*grid-column:\s*1[^}]*grid-row:\s*3/s,
  );
  assert.match(
    source,
    /\.competition-active-workflow\s+\.competition-timeline\.is-compact\s*>\s*li:nth-child\(4\)\s*{[^}]*grid-column:\s*2[^}]*grid-row:\s*3/s,
  );
  assert.match(
    source,
    /\.competition-active-workflow[\s\S]*?li:nth-child\(3\)::before,[\s\S]*?li:nth-child\(4\)::before\s*{[^}]*border-left:\s*2px\s+solid\s+#98a2b3/s,
  );
  assert.match(
    source,
    /\.competition-active-workflow[\s\S]*?li:nth-child\(3\)::after\s*{[^}]*border-top:\s*2px\s+solid\s+#98a2b3/s,
  );
  assert.doesNotMatch(
    source,
    /\.competition-active-workflow[^{]*li::before,[\s\S]*?li::after\s*{[^}]*display:\s*none/s,
  );
});

test('new calculation workspace is syntax-valid, fixed-scope, and fail-closed', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  assert.doesNotThrow(() => parse(source, { sourceType: 'module', plugins: ['jsx'] }));

  for (const token of [
    'DEMO_STRUCTURE',
    'VaspStructureViewer',
    'PreviewReadOnlyNotice',
    'relax',
    'scf',
    'band',
    'dos',
    'POSCAR/CIF 文本，最大 1 MiB，最多 200 个原子',
    'mos2-v1',
    '提交前生成',
    'ENCUT',
    'k-point',
    'convergence',
    'P107-RTX5090',
    '最大 4 GPU / 16 CPU',
    '每步独立一个 Job / attempt 证据记录',
    '演示参数',
  ]) {
    assert.match(source, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  }

  assert.match(source, /import\s+['"]\.\.\/db\/vasp-detail\/VaspTaskDetail\.css['"];?/);
  assert.match(source, /import\s+['"]\.\/CompetitionPages\.css['"];?/);
  assert.match(source, /useState\(['"]builtin['"]\)/);
  assert.match(source, /handleSourceKindChange\(['"]builtin['"]\)/);
  assert.match(source, /handleSourceKindChange\(['"]upload['"]\)/);
  assert.match(source, /const\s*\{\s*provider,\s*mode\s*\}\s*=\s*useCompetitionData\(\);/);
  assert.match(source, /const\s+user\s*=\s*readStoredUser\(\);/);
  assert.match(
    source,
    /const\s+readOnly\s*=\s*mode\s*===\s*['"]demo['"]\s*\|\|\s*!canWriteCompetitionData\(user\);/,
  );
  assert.match(source, /function\s+readStoredUser\(storage\)/);
  assert.match(source, /globalThis\.localStorage/);
  assert.match(source, /id:\s*['"]preview-draft['"]/);
  assert.match(source, /source_kind:\s*sourceKind/);
  assert.match(source, /template_version:\s*['"]mos2-v1['"]/);
  assert.match(source, /steps:\s*WORKFLOW_STEPS\.map\(\(step\)\s*=>\s*step\.key\)/);
  assert.match(source, /演示参数 · 模板 mos2-v1 · 输入 SHA-256：提交前生成/);
  assert.match(source, /<VaspStructureViewer\s+structure=\{DEMO_STRUCTURE\}\s*\/>/);
  assert.match(source, /<input[^>]*type=['"]file['"][^>]*disabled[^>]*>/s);
  assert.doesNotMatch(source, /<input[^>]*onChange=/s);
  assert.doesNotMatch(source, /uploadStructure|FileReader|FormData/);
  assert.equal(source.match(/provider\.saveDraft\(draft\)/g)?.length, 1);
  assert.equal(source.match(/provider\.submitWorkflow\(draft\.id\)/g)?.length, 1);
  assert.ok((source.match(/disabled=\{readOnly\}/g) || []).length >= 2);
  assert.match(source, /async\s+function\s+handleSaveDraft[\s\S]*?try\s*{[\s\S]*?await\s+executeCompetitionWrite\([\s\S]*?catch/s);
  assert.match(source, /async\s+function\s+handleSubmitWorkflow[\s\S]*?try\s*{[\s\S]*?await\s+executeCompetitionWrite\([\s\S]*?catch/s);
  assert.doesNotMatch(source, /alert\s*\([^)]*成功|toast\s*\([^)]*成功/i);
  assert.doesNotMatch(source, /\b(?:add|delete|drag|reorder)(?:Step)?\b|添加|删除|拖拽|重排/i);
  assert.doesNotMatch(source, /Agent|Machine Learning|\bML\b|Quantum ESPRESSO|\bQE\b/);
  assert.doesNotMatch(source, /card/i);
});

test('new calculation upload source hides builtin structure and draft claims', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] });
  const sourceConditionals = findNodes(ast, (node) => (
    node.type === 'ConditionalExpression'
    && source.slice(node.test.start, node.test.end).replaceAll(' ', '') === "sourceKind==='builtin'"
  ));
  const branchSource = (node, branch) => source.slice(node[branch].start, node[branch].end);
  const structureConditional = sourceConditionals.find((node) => (
    branchSource(node, 'consequent').includes('competition-structure-summary')
    && branchSource(node, 'alternate').includes('competition-structure-summary')
  ));

  assert.ok(structureConditional, 'structure summary must branch on builtin versus upload');
  const builtinSummary = branchSource(structureConditional, 'consequent');
  const uploadSummary = branchSource(structureConditional, 'alternate');
  for (const token of ['MoS2', 'DEMO_STRUCTURE.symbols.length', '3.158', '20.000']) {
    assert.match(builtinSummary, new RegExp(token.replaceAll('.', '\\.')));
  }
  for (const token of ['待选择', '未解析', '不可提交']) assert.match(uploadSummary, new RegExp(token));
  assert.doesNotMatch(uploadSummary, /MoS2|DEMO_STRUCTURE|3\.158|20\.000|内置结构/);

  const draftConditional = sourceConditionals.find((node) => (
    branchSource(node, 'consequent').includes('preview-draft')
    && branchSource(node, 'alternate').includes('preview-draft')
  ));
  assert.ok(draftConditional, 'draft summary must branch on builtin versus upload');
  assert.match(branchSource(draftConditional, 'consequent'), /mos2-v1.*4 步/s);
  assert.match(branchSource(draftConditional, 'alternate'), /上传结构待选择.*未解析.*不可提交/s);
  assert.doesNotMatch(branchSource(draftConditional, 'alternate'), /mos2-v1/);
});

test('new calculation executes writes only for live builtin operators', async () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const executeCompetitionWrite = loadFunction(source, 'executeCompetitionWrite', {
    canWriteCompetitionData,
  });
  let writeCount = 0;
  const write = async () => {
    writeCount += 1;
  };

  assert.equal(await executeCompetitionWrite({
    mode: 'demo', user: { role: 'operator' }, sourceKind: 'builtin', write,
  }), false);
  assert.equal(await executeCompetitionWrite({
    mode: 'standard', user: { role: 'operator' }, sourceKind: 'builtin', write,
  }), false);
  assert.equal(await executeCompetitionWrite({
    mode: 'live', user: { role: 'viewer' }, sourceKind: 'builtin', write,
  }), false);
  assert.equal(await executeCompetitionWrite({
    mode: 'live', user: { role: 'operator' }, sourceKind: 'upload', write,
  }), false);
  assert.equal(writeCount, 0);
  assert.equal(await executeCompetitionWrite({
    mode: 'live', user: { role: 'operator' }, sourceKind: 'builtin', write,
  }), true);
  assert.equal(writeCount, 1);

  assert.equal(source.match(/await\s+executeCompetitionWrite\(\{/g)?.length, 2);
  assert.match(source, /write:\s*\(\)\s*=>\s*provider\.saveDraft\(draft\)/);
  assert.match(source, /write:\s*\(\)\s*=>\s*provider\.submitWorkflow\(draft\.id\)/);
});

test('new calculation stored user parsing fails closed and accepts valid JSON', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const readStoredUser = loadFunction(source, 'readStoredUser', { globalThis: {} });

  assert.equal(readStoredUser(), null);
  assert.equal(readStoredUser({ getItem() { throw new Error('storage unavailable'); } }), null);
  assert.equal(readStoredUser({ getItem() { return '{not-json'; } }), null);
  assert.deepEqual(
    readStoredUser({ getItem() { return '{"role":"operator","name":"Ada"}'; } }),
    { role: 'operator', name: 'Ada' },
  );
});

test('new calculation source selection clears stale command failures', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');

  assert.match(
    source,
    /function\s+handleSourceKindChange\(nextSourceKind\)\s*{[^}]*setSourceKind\(nextSourceKind\);[^}]*setCommandError\(['"]['"]\);[^}]*}/s,
  );
  assert.match(source, /onClick=\{\(\)\s*=>\s*handleSourceKindChange\(['"]builtin['"]\)\}/);
  assert.match(source, /onClick=\{\(\)\s*=>\s*handleSourceKindChange\(['"]upload['"]\)\}/);
});

test('new calculation workflow preserves the approved dependency fork', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] });
  const declaration = ast.program.body.find((node) => (
    node.type === 'VariableDeclaration'
    && node.declarations.some(({ id }) => id.type === 'Identifier' && id.name === 'WORKFLOW_STEPS')
  ));
  assert.ok(declaration, 'WORKFLOW_STEPS must be a module constant');
  const workflowSteps = new Function(
    `${source.slice(declaration.start, declaration.end)}\nreturn WORKFLOW_STEPS;`,
  )();

  assert.deepEqual(workflowSteps, [
    { key: 'relax', label: 'relax', dependsOn: [], purpose: '优化离子位置与晶格' },
    { key: 'scf', label: 'SCF', dependsOn: ['relax'], purpose: '生成已验收自洽电荷密度' },
    { key: 'band', label: 'BAND', dependsOn: ['scf'], purpose: '沿固定高对称路径计算能带' },
    { key: 'dos', label: 'DOS', dependsOn: ['scf'], purpose: '基于自洽结果计算态密度' },
  ]);
  assert.match(source, /WORKFLOW_STEPS\.map\(\(step\)\s*=>/);
  assert.match(source, /step\.dependsOn\.map/);
});

test('new calculation styles keep stable responsive geometry without nested cards', () => {
  const source = read('../src/pages/competition/CompetitionPages.css');

  assert.match(
    source,
    /\.competition-calculation-grid\s*{[^}]*display:\s*grid[^}]*grid-template-columns:\s*minmax\(0,\s*1\.2fr\)\s+minmax\(280px,\s*\.8fr\)/s,
  );
  assert.match(source, /\.competition-structure-viewer\s*{[^}]*min-width:\s*0[^}]*overflow:\s*hidden/s);
  assert.match(source, /\.competition-workflow-graph\s*{[^}]*display:\s*grid[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)[^}]*gap:\s*12px/s);
  assert.match(source, /\.competition-workflow-step\.is-relax\s*{[^}]*grid-column:\s*1\s*\/\s*-1/s);
  assert.match(source, /\.competition-workflow-step\.is-scf\s*{[^}]*grid-column:\s*1\s*\/\s*-1/s);
  assert.match(
    source,
    /\.competition-workflow-step\.is-scf::after\s*{[^}]*width:\s*2px[^}]*height:\s*6px[^}]*right:\s*50%[^}]*bottom:\s*-6px[^}]*content:\s*''[^}]*background:\s*#98a2b3/s,
  );
  assert.match(
    source,
    /\.competition-workflow-step\.is-band::before,\s*\.competition-workflow-step\.is-dos::before\s*{[^}]*height:\s*2px[^}]*position:\s*absolute[^}]*top:\s*-6px[^}]*content:\s*''[^}]*background:\s*#98a2b3/s,
  );
  assert.match(
    source,
    /\.competition-workflow-step\.is-band::before\s*{[^}]*right:\s*-6px[^}]*left:\s*50%/s,
  );
  assert.match(
    source,
    /\.competition-workflow-step\.is-dos::before\s*{[^}]*right:\s*50%[^}]*left:\s*-6px/s,
  );
  assert.match(
    source,
    /\.competition-workflow-step\.is-band::after,\s*\.competition-workflow-step\.is-dos::after\s*{[^}]*width:\s*2px[^}]*height:\s*6px[^}]*position:\s*absolute[^}]*top:\s*-6px[^}]*left:\s*50%[^}]*content:\s*''[^}]*background:\s*#98a2b3/s,
  );
  assert.match(source, /\.competition-command-bar\s*{[^}]*display:\s*flex[^}]*flex-wrap:\s*wrap/s);
  assert.match(source, /:focus-visible/);
  assert.match(source, /:disabled/);
  assert.match(source, /:not\(:disabled\):hover/);
  assert.match(source, /@media\s*\(max-width:\s*900px\)[\s\S]*?\.competition-calculation-grid\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
  assert.match(source, /@media\s*\(max-width:\s*520px\)[\s\S]*?\.competition-command-button\s*{[^}]*width:\s*100%/s);
  assert.match(
    source,
    /@media\s*\(max-width:\s*520px\)[\s\S]*?\.competition-workflow-graph\s*{[^}]*grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)[\s\S]*?\.competition-workflow-step\.is-band\s*{[^}]*grid-column:\s*1[\s\S]*?\.competition-workflow-step\.is-dos\s*{[^}]*grid-column:\s*2/s,
  );
  assert.doesNotMatch(source, /\.competition-workflow-step\.is-band\s*\+\s*\.competition-workflow-step\.is-dos/);
  assert.match(source, /overflow-wrap:\s*anywhere/);
  assert.doesNotMatch(source, /\.vasp-(?:structure-viewer|viewer-canvas)\s*{/);
  assert.doesNotMatch(source, /card/i);
  assert.doesNotMatch(source, /font-size:\s*[^;]*vw/);
  assert.doesNotMatch(source, /letter-spacing:\s*-/);
  for (const radius of source.matchAll(/border-radius:\s*(\d+)px/g)) {
    assert.ok(Number(radius[1]) <= 8, `border radius exceeds 8px: ${radius[0]}`);
  }
});

test('workflow list page keeps query and status in stable URL state', () => {
  const source = read('../src/pages/competition/CompetitionWorkflows.jsx');
  assert.doesNotThrow(() => parse(source, { sourceType: 'module', plugins: ['jsx'] }));
  const readWorkflowFilters = loadFunction(source, 'readWorkflowFilters');
  const writeWorkflowFilters = loadFunction(source, 'writeWorkflowFilters', { URLSearchParams });

  assert.deepEqual(readWorkflowFilters(new URLSearchParams()), { query: '', status: 'all' });
  assert.deepEqual(readWorkflowFilters(new URLSearchParams('query=MoS2&status=running')), {
    query: 'MoS2',
    status: 'running',
  });
  assert.deepEqual(readWorkflowFilters(new URLSearchParams('status=unknown')), {
    query: '',
    status: 'all',
  });
  assert.equal(
    writeWorkflowFilters(new URLSearchParams('query=MoS2&status=failed'), {
      query: '', status: 'all',
    }).toString(),
    '',
  );
  assert.equal(
    writeWorkflowFilters(new URLSearchParams(), { query: 'S vacancy', status: 'succeeded' }).toString(),
    'query=S+vacancy&status=succeeded',
  );

  for (const token of [
    'listWorkflows',
    'query',
    'status',
    'CompetitionTable',
    'DemoDataBanner',
    'all',
    'running',
    'succeeded',
    'failed',
  ]) {
    assert.match(source, new RegExp(token));
  }
  assert.match(source, /useSearchParams\(\)/);
  assert.match(
    source,
    /const\s+loadWorkflows\s*=\s*useCallback\(\(\)\s*=>\s*provider\.listWorkflows\(\{\s*query,\s*status\s*\}\),\s*\[provider,\s*query,\s*status\]\);/,
  );
  assert.match(source, /useCompetitionResource\(loadWorkflows\)/);
  assert.match(source, /setSearchParams\([^;]+\{\s*replace:\s*true\s*\}\)/s);
  assert.match(source, /navigate\(`\/dashboard\/workflows\/\$\{encodeURIComponent\(workflow\.id\)\}`\)/);
  assert.match(source, /state\.status\s*!==\s*['"]ready['"]/);
  assert.match(source, /<CompetitionState\s+status=\{state\.status\}\s+message=\{state\.error\?\.message\}\s*\/>/);
  assert.match(source, /<CompetitionState\s+status=['"]empty['"]/);
  assert.match(source, /mode\s*===\s*['"]demo['"]\s*\?\s*<DemoDataBanner\s*\/>\s*:\s*null/g);
  assert.doesNotMatch(source, /sbatch|squeue|sacct|scancel|vasp_db|legacy/i);
});

test('workflow list all status preserves the complete demo fixture result', async () => {
  const provider = createDemoCompetitionDataProvider();
  const response = await provider.listWorkflows({ query: '', status: 'all' });

  assert.equal(response.total, 3);
  assert.deepEqual(response.items.map(({ status }) => status), ['succeeded', 'running', 'failed']);
});

test('workflow detail page loads immutable evidence and handles missing ids explicitly', () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  assert.doesNotThrow(() => parse(source, { sourceType: 'module', plugins: ['jsx'] }));

  for (const token of [
    'getWorkflow',
    'input_sha256',
    'release_commit',
    'template_version',
    'WorkflowTimeline',
    'data_kind',
    'creator',
    'PreviewReadOnlyNotice',
    'DemoDataBanner',
  ]) {
    assert.match(source, new RegExp(token));
  }
  assert.match(source, /const\s*\{\s*workflowId\s*\}\s*=\s*useParams\(\);/);
  assert.match(source, /provider\.getWorkflow\(workflowId\)/);
  assert.match(source, /workflowId\s*\?[^:]+:\s*Promise\.resolve\(null\)/s);
  assert.match(source, /缺少工作流 ID|未找到工作流/);
  assert.match(source, /mode\s*===\s*['"]demo['"]\s*\?\s*['"]演示数据['"]\s*:\s*['"]真实数据['"]/);
  assert.match(source, /<WorkflowTimeline\s+steps=\{workflowSteps\}\s*\/>/);
  assert.doesNotMatch(source, /<WorkflowTimeline[^>]*compact/);
  assert.ok(
    source.indexOf('competition-workflow-identity') < source.indexOf('<WorkflowTimeline'),
    'immutable identity must render before the workflow timeline',
  );
  assert.match(source, /const\s+workflowSteps\s*=\s*Array\.isArray\(workflow\.steps\)\s*\?\s*workflow\.steps\s*:\s*\[\];/);
  assert.match(source, /const\s+failedStep\s*=\s*workflowSteps\.find\(\(step\)\s*=>\s*step\?\.status\s*===\s*['"]failed['"]\)\s*\|\|\s*null;/);
  assert.match(
    source,
    /const\s+readOnly\s*=\s*mode\s*===\s*['"]demo['"]\s*\|\|\s*!canWriteCompetitionData\(user\);/,
  );
  assert.match(source, /disabled=\{readOnly\}/);
  assert.match(source, /disabled=\{readOnly\s*\|\|\s*failedStep\s*===\s*null\}/);
  assert.match(source, /provider\.cancelWorkflow\(workflow\.id\)/);
  assert.match(
    source,
    /provider\.retryWorkflow\(\{\s*id:\s*workflow\.id,\s*step:\s*failedStep\.key\s*\}\)/,
  );
  assert.match(source, /role=['"]alert['"]/);
  assert.doesNotMatch(source, /alert\s*\(|toast\s*\(|sbatch|squeue|sacct|scancel|vasp_db|legacy/i);
});

test('workflow detail commands execute only for live operators', async () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const executeWorkflowCommand = loadFunction(source, 'executeWorkflowCommand', {
    canWriteCompetitionData,
  });
  let writeCount = 0;
  const write = async () => {
    writeCount += 1;
  };

  assert.equal(await executeWorkflowCommand({
    mode: 'demo', user: { role: 'operator' }, write,
  }), false);
  assert.equal(await executeWorkflowCommand({
    mode: 'live', user: { role: 'viewer' }, write,
  }), false);
  assert.equal(await executeWorkflowCommand({
    mode: 'unknown', user: { role: 'operator' }, write,
  }), false);
  assert.equal(writeCount, 0);
  assert.equal(await executeWorkflowCommand({
    mode: 'live', user: { role: 'operator' }, write,
  }), true);
  assert.equal(writeCount, 1);

  const rejection = new Error('provider rejected command');
  await assert.rejects(
    () => executeWorkflowCommand({
      mode: 'live', user: { role: 'operator' }, write: async () => { throw rejection; },
    }),
    rejection,
  );
  assert.equal(source.match(/await\s+executeWorkflowCommand\(\{/g)?.length, 2);
  assert.match(source, /async\s+function\s+handleCancel[\s\S]*?try\s*{[\s\S]*?catch/s);
  assert.match(source, /async\s+function\s+handleRetry[\s\S]*?try\s*{[\s\S]*?catch/s);
});

test('workflow detail stored user parsing fails closed', () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const readStoredUser = loadFunction(source, 'readStoredUser', { globalThis: {} });

  assert.equal(readStoredUser(), null);
  assert.equal(readStoredUser({ getItem() { throw new Error('storage unavailable'); } }), null);
  assert.equal(readStoredUser({ getItem() { return '{broken'; } }), null);
  assert.deepEqual(
    readStoredUser({ getItem() { return '{"role":"operator"}'; } }),
    { role: 'operator' },
  );
});

test('workflow pages add only scoped responsive work-surface styles', () => {
  const source = read('../src/pages/competition/CompetitionPages.css');

  assert.match(source, /\.competition-workflows-page\s*{/);
  assert.match(source, /\.competition-workflow-detail-page\s*{/);
  assert.match(source, /\.competition-workflow-filters\s*{[^}]*display:\s*grid/s);
  assert.match(source, /\.competition-workflow-identity\s*{[^}]*display:\s*grid/s);
  assert.match(source, /\.competition-workflow-identity[^}]*[\s\S]*?overflow-wrap:\s*anywhere/);
  assert.match(source, /\.competition-workflow-command-button:not\(:disabled\):hover/);
  assert.match(source, /\.competition-workflow-command-button:disabled/);
  assert.match(source, /@media\s*\(max-width:\s*700px\)[\s\S]*?\.competition-workflow-identity\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
  assert.doesNotMatch(source, /font-size:\s*[^;]*vw/);
  assert.doesNotMatch(source, /letter-spacing:\s*-/);
  for (const radius of source.matchAll(/border-radius:\s*(\d+)px/g)) {
    assert.ok(Number(radius[1]) <= 8, `border radius exceeds 8px: ${radius[0]}`);
  }
});
