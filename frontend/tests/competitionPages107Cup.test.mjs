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
  assert.match(source, /<WorkflowTimeline\s+steps=\{workflowSteps\}\s*\/>/);
  assert.doesNotMatch(source, /<WorkflowTimeline[^>]*compact/);
  assert.ok(
    source.indexOf('competition-workflow-identity') < source.indexOf('<WorkflowTimeline'),
    'immutable identity must render before the workflow timeline',
  );
  assert.match(source, /const\s+workflowSteps\s*=\s*Array\.isArray\(workflow\.steps\)\s*\?\s*workflow\.steps\s*:\s*\[\];/);
  assert.match(source, /const\s+failedStep\s*=\s*findRetryableFailedStep\(workflowSteps\);/);
  assert.match(
    source,
    /const\s+readOnly\s*=\s*mode\s*===\s*['"]demo['"]\s*\|\|\s*!canWriteCompetitionData\(user\);/,
  );
  assert.match(source, /disabled=\{readOnly\s*\|\|\s*commandPending\}/);
  assert.match(source, /disabled=\{readOnly\s*\|\|\s*commandPending\s*\|\|\s*failedStep\s*===\s*null\}/);
  assert.match(source, /provider\.cancelWorkflow\(workflow\.id\)/);
  assert.match(
    source,
    /provider\.retryWorkflow\(\{\s*id:\s*workflow\.id,\s*step:\s*failedStep\.key\s*\}\)/,
  );
  assert.match(source, /role=['"]alert['"]/);
  assert.doesNotMatch(source, /alert\s*\(|toast\s*\(|sbatch|squeue|sacct|scancel|vasp_db|legacy/i);
});

test('workflow detail data kind labels follow record provenance instead of provider mode', () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const workflowDataKindLabel = loadFunction(source, 'workflowDataKindLabel');

  assert.equal(workflowDataKindLabel('demo'), '演示数据');
  assert.equal(workflowDataKindLabel('live'), '真实数据');
  for (const dataKind of ['unknown', '', null, undefined]) {
    assert.equal(workflowDataKindLabel(dataKind), '来源未验证');
  }
  assert.match(
    source,
    /const\s+dataKindLabel\s*=\s*workflowDataKindLabel\(workflow\.data_kind\);/,
  );
  assert.equal(source.match(/\{dataKindLabel\}/g)?.length, 2);
  assert.doesNotMatch(source, /mode\s*===\s*['"]demo['"]\s*\?\s*['"]演示数据['"]\s*:\s*['"]真实数据['"]/);
  assert.match(source, /mode\s*===\s*['"]demo['"]\s*\?\s*<DemoDataBanner\s*\/>\s*:\s*null/g);
});

test('workflow detail immutable identity uses explicit Chinese labels', () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');

  for (const label of [
    '工作流 ID',
    '创建人',
    '模板版本',
    '输入 SHA-256',
    '发布提交',
    '数据类型',
  ]) {
    assert.match(source, new RegExp(`<dt>${label}</dt>`));
  }
  for (const internalName of [
    'workflow.id',
    'creator',
    'template_version',
    'input_sha256',
    'release_commit',
    'data_kind',
  ]) {
    assert.doesNotMatch(source, new RegExp(`<dt>${internalName.replace('.', '\\.')}</dt>`));
  }
});

test('workflow detail state normalization preserves provider failures and rejects malformed records', () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const normalizeWorkflowDetailState = loadFunction(source, 'normalizeWorkflowDetailState');
  const demoWorkflow = { id: 'wf-1', data_kind: 'demo' };
  const liveWorkflow = { id: 'wf-live', data_kind: 'live' };

  assert.deepEqual(
    normalizeWorkflowDetailState({ status: 'loading', data: null, error: null }, 'wf-1'),
    { status: 'loading', message: undefined, workflow: null },
  );
  assert.deepEqual(
    normalizeWorkflowDetailState({
      status: 'forbidden', data: null, error: { message: 'viewer denied' },
    }, 'wf-1'),
    { status: 'forbidden', message: 'viewer denied', workflow: null },
  );
  assert.deepEqual(
    normalizeWorkflowDetailState({
      status: 'error', data: null, error: { message: 'service unavailable' },
    }, 'wf-1'),
    { status: 'error', message: 'service unavailable', workflow: null },
  );
  assert.deepEqual(
    normalizeWorkflowDetailState({ status: 'empty', data: null, error: null }, 'wf-1'),
    { status: 'empty', message: '未找到工作流', workflow: null },
  );
  assert.deepEqual(
    normalizeWorkflowDetailState({ status: 'ready', data: null, error: null }, undefined),
    { status: 'empty', message: '缺少工作流 ID', workflow: null },
  );
  assert.deepEqual(
    normalizeWorkflowDetailState({ status: 'ready', data: demoWorkflow, error: null }, 'wf-1'),
    { status: 'ready', message: undefined, workflow: demoWorkflow },
  );
  assert.deepEqual(
    normalizeWorkflowDetailState({ status: 'ready', data: liveWorkflow, error: null }, 'wf-live'),
    { status: 'ready', message: undefined, workflow: liveWorkflow },
  );
  for (const malformed of [[], 'wf-1', 0, true, new Date()]) {
    assert.deepEqual(
      normalizeWorkflowDetailState({ status: 'ready', data: malformed, error: null }, 'wf-1'),
      { status: 'empty', message: '未找到工作流', workflow: null },
    );
  }
  for (const invalidIdentity of [
    {},
    { id: '', data_kind: 'demo' },
    { id: '   ', data_kind: 'demo' },
    { id: ' wf-1 ', data_kind: 'demo' },
  ]) {
    assert.deepEqual(
      normalizeWorkflowDetailState({ status: 'ready', data: invalidIdentity, error: null }, 'wf-1'),
      { status: 'parse-error', message: '工作流身份无效', workflow: null },
    );
  }
  assert.deepEqual(
    normalizeWorkflowDetailState({
      status: 'ready', data: { id: 'wf-other', data_kind: 'demo' }, error: null,
    }, 'wf-1'),
    { status: 'parse-error', message: '工作流身份不一致', workflow: null },
  );
  for (const dataKind of [undefined, null, '', 'unknown']) {
    assert.deepEqual(
      normalizeWorkflowDetailState({
        status: 'ready', data: { id: 'wf-1', data_kind: dataKind }, error: null,
      }, 'wf-1'),
      { status: 'parse-error', message: '工作流数据来源未验证', workflow: null },
    );
  }

  assert.match(
    source,
    /const\s+detailState\s*=\s*normalizeWorkflowDetailState\(state,\s*workflowId\);/,
  );
  assert.match(source, /detailState\.status\s*!==\s*['"]ready['"]/);
  assert.match(source, /status=\{detailState\.status\}/);
  assert.match(source, /message=\{detailState\.message\}/);
  assert.match(source, /const\s+workflow\s*=\s*detailState\.workflow;/);
});

test('workflow detail retries only the first failed fixed-step key', () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const findRetryableFailedStep = loadFunction(source, 'findRetryableFailedStep');

  for (const invalidSteps of [null, undefined, {}, 'scf']) {
    assert.equal(findRetryableFailedStep(invalidSteps), null);
  }
  for (const invalidStep of [
    null,
    {},
    { status: 'failed' },
    { key: '', status: 'failed' },
    { key: ' scf ', status: 'failed' },
    { key: 'postprocess', status: 'failed' },
    { key: 'scf', status: 'FAILED' },
  ]) {
    assert.equal(findRetryableFailedStep([invalidStep]), null);
  }

  const relax = { key: 'relax', status: 'failed' };
  const scf = { key: 'scf', status: 'failed' };
  assert.equal(findRetryableFailedStep([
    { key: 'unknown', status: 'failed' }, relax, scf,
  ]), relax);
  for (const key of ['relax', 'scf', 'band', 'dos']) {
    const step = { key, status: 'failed' };
    assert.equal(findRetryableFailedStep([step]), step);
  }
});

test('workflow detail commands fail closed and execute valid cancel and retry once', async () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const executeWorkflowCommand = loadFunction(source, 'executeWorkflowCommand', {
    canWriteCompetitionData,
  });
  const calls = [];
  const base = {
    mode: 'live',
    user: { role: 'operator' },
    workflowId: 'wf-1',
    pending: false,
  };
  const write = async () => calls.push('invalid');
  const invalidCommands = [
    { ...base, mode: 'demo', command: 'cancel', step: null, write },
    { ...base, user: { role: 'viewer' }, command: 'cancel', step: null, write },
    { ...base, workflowId: '', command: 'cancel', step: null, write },
    { ...base, workflowId: '   ', command: 'cancel', step: null, write },
    { ...base, workflowId: ' wf-1 ', command: 'cancel', step: null, write },
    { ...base, command: 'delete', step: null, write },
    { ...base, command: 'cancel', step: null, pending: true, write },
    { ...base, command: 'cancel', step: null, write: null },
    { ...base, command: 'retry', step: undefined, write },
    { ...base, command: 'retry', step: '', write },
    { ...base, command: 'retry', step: 'postprocess', write },
  ];

  for (const command of invalidCommands) {
    assert.equal(await executeWorkflowCommand(command), false);
  }
  assert.deepEqual(calls, []);
  assert.equal(await executeWorkflowCommand({
    ...base,
    command: 'cancel',
    step: null,
    write: async () => calls.push('cancel'),
  }), true);
  assert.equal(await executeWorkflowCommand({
    ...base,
    command: 'retry',
    step: 'scf',
    write: async () => calls.push('retry'),
  }), true);
  assert.deepEqual(calls, ['cancel', 'retry']);

  const rejection = new Error('provider rejected command');
  await assert.rejects(
    () => executeWorkflowCommand({
      ...base,
      command: 'cancel',
      step: null,
      write: async () => { throw rejection; },
    }),
    rejection,
  );
  assert.equal(source.match(/await\s+executeWorkflowCommand\(\{/g)?.length, 2);
  assert.equal(source.match(/workflowId:\s*workflow\.id/g)?.length, 2);
  assert.equal(source.match(/pending:\s*commandPending/g)?.length, 2);
  assert.match(source, /command:\s*['"]cancel['"]/);
  assert.match(source, /command:\s*['"]retry['"]/);
  assert.match(source, /step:\s*null/);
  assert.match(source, /step:\s*failedStep\.key/);
  assert.match(source, /const\s*\[commandPending,\s*setCommandPending\]\s*=\s*useState\(false\);/);
  assert.equal(source.match(/setCommandPending\(true\)/g)?.length, 2);
  assert.equal(source.match(/finally\s*{\s*setCommandPending\(false\);\s*}/g)?.length, 2);
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

test('result list keeps URL filters executable and opens only completed result identities', () => {
  const source = read('../src/pages/competition/CompetitionResults.jsx');
  assert.doesNotThrow(() => parse(source, { sourceType: 'module', plugins: ['jsx'] }));
  const readResultFilters = loadFunction(source, 'readResultFilters');
  const writeResultFilters = loadFunction(source, 'writeResultFilters', { URLSearchParams });
  const resultDetailUrl = loadFunction(source, 'resultDetailUrl');
  const selectCompletedResults = loadFunction(source, 'selectCompletedResults');

  assert.deepEqual(readResultFilters(new URLSearchParams()), { query: '', status: 'all' });
  assert.deepEqual(readResultFilters(new URLSearchParams('query=MoS2&status=parse-error')), {
    query: 'MoS2',
    status: 'parse-error',
  });
  assert.deepEqual(readResultFilters(new URLSearchParams('status=running')), {
    query: '',
    status: 'all',
  });
  assert.equal(
    writeResultFilters(new URLSearchParams('query=MoS2&status=failed'), {
      query: '', status: 'all',
    }).toString(),
    '',
  );
  assert.equal(
    writeResultFilters(new URLSearchParams(), { query: 'S vacancy', status: 'succeeded' }).toString(),
    'query=S+vacancy&status=succeeded',
  );

  assert.equal(
    resultDetailUrl({ id: 'result-row-17', workflow_id: 'wf/live' }),
    '/dashboard/results/wf%2Flive',
  );
  assert.equal(resultDetailUrl({ id: 'wf/result 1' }), '/dashboard/results/wf%2Fresult%201');
  assert.equal(resultDetailUrl({ id: '', workflow_id: 'wf#fallback' }), '/dashboard/results/wf%23fallback');
  for (const invalid of [
    null,
    undefined,
    {},
    [],
    { id: 7 },
    { id: '   ' },
    { id: 'wf-fallback', workflow_id: '' },
    { id: 'wf-fallback', workflow_id: {} },
    { workflow_id: ' wf-1 ' },
  ]) {
    assert.equal(resultDetailUrl(invalid), null);
  }

  const succeeded = { id: 'ok', status: 'succeeded' };
  const failed = { workflow_id: 'bad', status: 'failed' };
  const parseError = { id: 'parse', status: 'parse-error' };
  assert.deepEqual(selectCompletedResults({
    items: [succeeded, { id: 'active', status: 'running' }, failed, parseError, null, 'bad'],
  }), [succeeded, failed, parseError]);
  for (const malformed of [null, undefined, [], {}, { items: null }]) {
    assert.deepEqual(selectCompletedResults(malformed), []);
  }

  assert.match(
    source,
    /const\s+loadResults\s*=\s*useCallback\(\(\)\s*=>\s*provider\.listResults\(\{\s*query,\s*status\s*\}\),\s*\[provider,\s*query,\s*status\]\);/,
  );
  assert.match(source, /useCompetitionResource\(loadResults\)/);
  assert.match(source, /navigate\(destination\)/);
  assert.match(source, /<CompetitionTable\s+items=\{items\}\s+kind=['"]result['"]\s+onOpen=\{openResult\}\s*\/>/);
  assert.match(source, /<CompetitionState\s+status=\{state\.status\}\s+message=\{state\.error\?\.message\}\s*\/>/);
  assert.match(source, /<CompetitionState\s+status=['"]empty['"]/);
  assert.match(source, /mode\s*===\s*['"]demo['"]\s*\?\s*<DemoDataBanner\s*\/>\s*:\s*null/);
  assert.doesNotMatch(source, /<option\s+value=['"]running['"]/);
  assert.doesNotMatch(source, /sbatch|squeue|sacct|scancel|PersonalVaspDatabase|backend\/routers\/vasp_db/i);
});

test('demo result provider filters all succeeded failed and parse-error without running records', async () => {
  const provider = createDemoCompetitionDataProvider();
  const expectations = new Map([
    ['all', ['succeeded', 'failed']],
    ['succeeded', ['succeeded']],
    ['failed', ['failed']],
    ['parse-error', []],
  ]);

  for (const [status, expectedStatuses] of expectations) {
    const response = await provider.listResults({ query: '', status });
    assert.equal(response.total, expectedStatuses.length);
    assert.deepEqual(response.items.map((item) => item.status), expectedStatuses);
    assert.equal(response.items.some((item) => item.status === 'running'), false);
  }

  const artifactExpectations = new Map([
    ['band-data', ['DEMO-band.dat', '# DEMO MoS2 band data']],
    ['dos-data', ['DEMO-dos.dat', '# DEMO MoS2 DOS data']],
    ['structure-cif', ['DEMO-MoS2.cif', 'data_DEMO_MoS2']],
    ['structure-poscar', ['DEMO-POSCAR', 'DEMO MoS2']],
    ['evidence-bundle', ['DEMO-evidence.json', '"id": "wf-demo-mos2-success"']],
  ]);
  for (const [kind, [expectedFilename, fixtureMarker]] of artifactExpectations) {
    const artifact = await provider.downloadArtifact('wf-demo-mos2-success', kind);
    assert.equal(artifact.filename, expectedFilename);
    assert.match(artifact.filename, /^DEMO-/);
    assert.ok(artifact.blob instanceof Blob);
    assert.match(await artifact.blob.text(), new RegExp(fixtureMarker));
  }
});

test('result detail state classifier fails closed before mounting science', () => {
  const source = read('../src/pages/competition/CompetitionResultDetail.jsx');
  assert.doesNotThrow(() => parse(source, { sourceType: 'module', plugins: ['jsx'] }));
  const normalizeResultDetailState = loadFunction(source, 'normalizeResultDetailState');
  const scientificDetail = {
    db: { dbname: 'demo' },
    row: {
      id: 1,
      formula: 'MoS2',
      energy: -22.4,
      fmax: 0.006,
      natoms: 1,
      pbc: [true, true, false],
    },
    properties: {
      spacegroup: 'P1',
      bandgap_eV: 1.78,
      vbm_eV: 0,
      cbm_eV: 1.78,
    },
    structure: {
      symbols: ['Mo'],
      positions: [[0, 0, 0]],
      cell: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
      pbc: [true, true, true],
    },
    crystal: {
      lattice: {
        a: 1,
        b: 1,
        c: 10,
        alpha: 90,
        beta: 90,
        gamma: 90,
        volume: 10,
      },
      density_g_cm3: 1.2,
      dimensionality: 2,
      atomic_positions_frac: [{ element: 'Mo', x: 0, y: 0, z: 0 }],
    },
    capabilities: {
      structure_export: true,
      band_plot: true,
      dos_plot: true,
      band_data: true,
      dos_data: true,
    },
  };
  const acceptedSteps = ['relax', 'scf', 'band', 'dos'].map((key, index) => ({
    key,
    status: 'succeeded',
    accepted: true,
    job_id: `JOB-${index + 1}`,
    exit_code: index === 1 ? 0 : '0:0',
  }));
  const success = {
    id: 'wf-1',
    status: 'succeeded',
    data_kind: 'demo',
    steps: acceptedSteps,
    vasp_detail: scientificDetail,
  };
  const failed = { id: 'wf-1', status: 'failed', data_kind: 'live' };
  const parseError = { id: 'wf-1', status: 'parse-error', data_kind: 'demo' };

  assert.deepEqual(
    normalizeResultDetailState({ status: 'loading', data: null, error: null }, 'wf-1'),
    { status: 'loading', message: undefined, variant: null, result: null },
  );
  assert.deepEqual(
    normalizeResultDetailState({ status: 'forbidden', data: null, error: { message: 'denied' } }, 'wf-1'),
    { status: 'forbidden', message: 'denied', variant: null, result: null },
  );
  assert.deepEqual(
    normalizeResultDetailState({ status: 'ready', data: null, error: null }, undefined),
    { status: 'empty', message: '缺少工作流 ID', variant: null, result: null },
  );
  assert.deepEqual(
    normalizeResultDetailState({ status: 'ready', data: null, error: null }, 'wf-1'),
    { status: 'empty', message: '未找到结果', variant: null, result: null },
  );
  for (const malformed of [[], 'wf-1', 0, true, new Date()]) {
    assert.deepEqual(
      normalizeResultDetailState({ status: 'ready', data: malformed, error: null }, 'wf-1'),
      { status: 'empty', message: '未找到结果', variant: null, result: null },
    );
  }
  assert.deepEqual(
    normalizeResultDetailState({ status: 'ready', data: success, error: null }, 'wf-1'),
    { status: 'ready', message: undefined, variant: 'success', result: success },
  );
  assert.deepEqual(
    normalizeResultDetailState({ status: 'ready', data: failed, error: null }, 'wf-1'),
    { status: 'ready', message: undefined, variant: 'failure', result: failed },
  );
  assert.deepEqual(
    normalizeResultDetailState({ status: 'ready', data: parseError, error: null }, 'wf-1'),
    { status: 'ready', message: undefined, variant: 'failure', result: parseError },
  );
  const authoritativeResult = {
    id: 'result-row-17', workflow_id: 'wf-live', status: 'failed', data_kind: 'live',
  };
  assert.deepEqual(
    normalizeResultDetailState({ status: 'ready', data: authoritativeResult }, 'wf-live'),
    { status: 'ready', message: undefined, variant: 'failure', result: authoritativeResult },
  );
  assert.deepEqual(
    normalizeResultDetailState({ status: 'ready', data: authoritativeResult }, 'wf-other'),
    { status: 'parse-error', message: '结果身份不一致', variant: null, result: null },
  );
  assert.deepEqual(
    normalizeResultDetailState({
      status: 'ready',
      data: { id: 'wf-live', workflow_id: {}, status: 'failed', data_kind: 'live' },
    }, 'wf-live'),
    { status: 'parse-error', message: '结果身份无效', variant: null, result: null },
  );

  for (const malformedIdentity of [
    {},
    { id: '', status: 'failed', data_kind: 'demo' },
    { id: ' wf-1 ', status: 'failed', data_kind: 'demo' },
    { id: 'wf-other', status: 'failed', data_kind: 'demo' },
  ]) {
    assert.equal(
      normalizeResultDetailState({ status: 'ready', data: malformedIdentity }, 'wf-1').status,
      'parse-error',
    );
  }
  for (const dataKind of [undefined, null, '', 'unknown']) {
    assert.deepEqual(
      normalizeResultDetailState({
        status: 'ready', data: { id: 'wf-1', status: 'failed', data_kind: dataKind },
      }, 'wf-1'),
      { status: 'parse-error', message: '结果数据来源未验证', variant: null, result: null },
    );
  }
  for (const status of ['running', 'queued', 'unknown', '', undefined]) {
    assert.deepEqual(
      normalizeResultDetailState({
        status: 'ready', data: { id: 'wf-1', status, data_kind: 'demo' },
      }, 'wf-1'),
      { status: 'parse-error', message: '结果状态不受支持', variant: null, result: null },
    );
  }
  const rowWithoutEnergy = { ...scientificDetail.row };
  delete rowWithoutEnergy.energy;
  const propertiesWithoutSpacegroup = { ...scientificDetail.properties };
  delete propertiesWithoutSpacegroup.spacegroup;
  const nullableScientificDetail = {
    ...scientificDetail,
    row: { ...scientificDetail.row, energy: null, fmax: null },
    properties: {
      ...scientificDetail.properties,
      spacegroup: null,
      bandgap_eV: null,
      vbm_eV: null,
      cbm_eV: null,
    },
  };
  const nullableSuccess = { ...success, data_kind: 'live', vasp_detail: nullableScientificDetail };
  assert.deepEqual(
    normalizeResultDetailState({ status: 'ready', data: nullableSuccess }, 'wf-1'),
    { status: 'ready', message: undefined, variant: 'success', result: nullableSuccess },
  );

  const incompleteDetails = [
    null,
    {},
    { ...scientificDetail, db: {} },
    { ...scientificDetail, row: {} },
    { ...scientificDetail, row: { ...scientificDetail.row, formula: '' } },
    { ...scientificDetail, row: rowWithoutEnergy },
    { ...scientificDetail, properties: {} },
    { ...scientificDetail, properties: propertiesWithoutSpacegroup },
    { ...scientificDetail, structure: null },
    { ...scientificDetail, structure: { symbols: [], positions: [], cell: [] } },
    { ...scientificDetail, structure: { ...scientificDetail.structure, pbc: [] } },
    { ...scientificDetail, crystal: { ...scientificDetail.crystal, lattice: {} } },
    {
      ...scientificDetail,
      crystal: { ...scientificDetail.crystal, atomic_positions_frac: [{}] },
    },
    { ...scientificDetail, crystal: { ...scientificDetail.crystal, density_g_cm3: null } },
    { ...scientificDetail, crystal: { ...scientificDetail.crystal, dimensionality: null } },
    { ...scientificDetail, capabilities: { ...scientificDetail.capabilities, band_plot: false } },
  ];
  for (const incompleteDetail of incompleteDetails) {
    assert.deepEqual(
      normalizeResultDetailState({
        status: 'ready', data: { ...success, vasp_detail: incompleteDetail },
      }, 'wf-1'),
      { status: 'parse-error', message: '科学结果合同不完整', variant: null, result: null },
    );
  }

  const invalidAcceptedSteps = [
    undefined,
    [],
    acceptedSteps.slice(0, 3),
    [acceptedSteps[0], acceptedSteps[0], acceptedSteps[2], acceptedSteps[3]],
    acceptedSteps.map((step, index) => (index === 0 ? { ...step, job_id: '' } : step)),
    acceptedSteps.map((step, index) => (index === 0 ? { ...step, job_id: '   ' } : step)),
    acceptedSteps.map((step, index) => (index === 1 ? { ...step, exit_code: null } : step)),
    acceptedSteps.map((step, index) => (index === 2 ? { ...step, accepted: false } : step)),
    acceptedSteps.map((step, index) => (index === 3 ? { ...step, status: 'waiting' } : step)),
  ];
  for (const invalidJobId of [false, true, 0, -3.5, -1, 1.5, {}, []]) {
    invalidAcceptedSteps.push(
      acceptedSteps.map((step, index) => (
        index === 0 ? { ...step, job_id: invalidJobId } : step
      )),
    );
  }
  for (const invalidSteps of invalidAcceptedSteps) {
    assert.deepEqual(
      normalizeResultDetailState({
        status: 'ready', data: { ...success, steps: invalidSteps },
      }, 'wf-1'),
      { status: 'parse-error', message: '结果验收合同不完整', variant: null, result: null },
    );
  }
  const numericJobSuccess = {
    ...success,
    steps: acceptedSteps.map((step, index) => (
      index === 0 ? { ...step, job_id: 17 } : step
    )),
  };
  assert.deepEqual(
    normalizeResultDetailState({ status: 'ready', data: numericJobSuccess }, 'wf-1'),
    { status: 'ready', message: undefined, variant: 'success', result: numericJobSuccess },
  );
});

test('result detail sanitizes identity and workflow step evidence before JSX', () => {
  const source = read('../src/pages/competition/CompetitionResultDetail.jsx');
  const displayIdentity = loadFunction(source, 'displayIdentity');
  const normalizeResultSteps = loadFunction(source, 'normalizeResultSteps');

  assert.equal(displayIdentity('creator'), 'creator');
  assert.equal(displayIdentity(0), 0);
  assert.equal(displayIdentity(false), 'false');
  for (const unsafe of [null, undefined, '', {}, [], new Date()]) {
    assert.equal(displayIdentity(unsafe), '-');
  }

  const normalized = normalizeResultSteps([
    {
      key: 'relax',
      status: {},
      job_id: {},
      attempt: 1,
      attempt_dir: ['attempt-1'],
      slurm_state: false,
      exit_code: {},
      reason: {},
      accepted: {},
    },
    {
      key: 'scf',
      status: 'failed',
      job_id: 'JOB-2',
      attempt: 0,
      attempt_dir: 'attempt-1/scf',
      slurm_state: 'FAILED',
      exit_code: '1:0',
      reason: 'not converged',
      accepted: false,
    },
    { key: 'unknown', status: 'failed', job_id: {} },
    { key: 'scf', status: 'succeeded', job_id: 'duplicate' },
  ]);
  assert.deepEqual(normalized.map((step) => step.key), ['relax', 'scf']);
  assert.equal(normalized[0].status, 'waiting');
  assert.equal(normalized[0].job_id, null);
  assert.equal(normalized[0].attempt, 1);
  assert.equal(normalized[0].attempt_dir, null);
  assert.equal(normalized[0].slurm_state, 'false');
  assert.equal(normalized[0].exit_code, null);
  assert.equal(normalized[0].reason, null);
  assert.equal(normalized[0].accepted, null);
  assert.equal(normalized[1].accepted, false);
  assert.match(source, /const\s+resultSteps\s*=\s*normalizeResultSteps\(result\.steps\);/);
  assert.match(source, /const\s+materialLabel\s*=\s*displayIdentity\(result\.material\);/);
});

test('failure evidence completeness rejects unsafe array entries', () => {
  const source = read('../src/pages/competition/CompetitionResultDetail.jsx');
  const displayFailureValue = loadFunction(source, 'displayFailureValue');
  const normalizeEvidenceLines = loadFunction(source, 'normalizeEvidenceLines');
  const hasCompleteFailureEvidence = loadFunction(source, 'hasCompleteFailureEvidence', {
    displayFailureValue,
  });
  const complete = {
    step: 'scf',
    job_id: 'JOB-1',
    exit_code: '1:0',
    reason: 'failed',
    expected_files: ['OUTCAR', 'vasprun.xml'],
    missing_files: [],
    log_tail: ['line'],
  };

  assert.equal(hasCompleteFailureEvidence(complete), true);
  assert.equal(hasCompleteFailureEvidence({ ...complete, job_id: 42, exit_code: 0 }), true);
  for (const step of ['', 'opt', false, 0, {}]) {
    assert.equal(hasCompleteFailureEvidence({ ...complete, step }), false);
  }
  for (const jobId of ['', '   ', false, true, 0, -3.5, -1, 1.5, {}]) {
    assert.equal(hasCompleteFailureEvidence({ ...complete, job_id: jobId }), false);
  }
  for (const exitCode of ['', '   ', false, true, -1, 1.5, {}]) {
    assert.equal(hasCompleteFailureEvidence({ ...complete, exit_code: exitCode }), false);
  }
  for (const reason of ['', '   ', false, 0, {}]) {
    assert.equal(hasCompleteFailureEvidence({ ...complete, reason }), false);
  }
  for (const field of ['expected_files', 'missing_files', 'log_tail']) {
    for (const invalidEntry of [false, true, 0, 2, {}, [], new Date()]) {
      assert.equal(hasCompleteFailureEvidence({ ...complete, [field]: [invalidEntry] }), false);
    }
    assert.equal(hasCompleteFailureEvidence({ ...complete, [field]: ['   '] }), false);
  }
  assert.equal(hasCompleteFailureEvidence({ ...complete, expected_files: [] }), false);
  assert.equal(hasCompleteFailureEvidence({ ...complete, log_tail: [] }), false);
  assert.equal(hasCompleteFailureEvidence({ ...complete, missing_files: [] }), true);
  assert.deepEqual(normalizeEvidenceLines([{}, 'line', 0, false]), ['line', '0', 'false']);
});

test('scientific db keys distinguish demo from neutral live records', () => {
  const source = read('../src/pages/competition/CompetitionResultDetail.jsx');
  const resultDbKey = loadFunction(source, 'resultDbKey');

  assert.equal(resultDbKey('demo'), '107cup-demo');
  assert.equal(resultDbKey('live'), '107cup-live');
  assert.match(source, /const\s+scientificDbKey\s*=\s*resultDbKey\(result\.data_kind\);/);
  assert.equal(source.match(/dbKey=\{scientificDbKey\}/g)?.length, 2);
  assert.doesNotMatch(source, /dbKey=['"]107cup-demo['"]/);
});

test('result detail binds reused scientific components only to the success AST branch', () => {
  const source = read('../src/pages/competition/CompetitionResultDetail.jsx');
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] });
  const scienceNames = [
    'VaspStructureViewer',
    'VaspCrystalDetails',
    'VaspElectronicProperties',
    'VaspTaskSummary',
  ];
  const imports = ast.program.body.filter((node) => node.type === 'ImportDeclaration');
  for (const name of scienceNames) {
    const declaration = imports.find((node) => node.specifiers.some((specifier) => specifier.local?.name === name));
    assert.ok(declaration, `${name} must be imported directly`);
    assert.match(declaration.source.value, /^\.\.\/db\/vasp-detail\//);
  }
  assert.ok(imports.some((node) => node.source.value === '../db/vasp-detail/VaspTaskDetail.css'));

  const successConditional = findNodes(ast, (node) => (
    node.type === 'ConditionalExpression'
    && source.slice(node.test.start, node.test.end).includes("detailState.variant === 'success'")
  ));
  assert.equal(successConditional.length, 1);
  const successSource = source.slice(successConditional[0].consequent.start, successConditional[0].consequent.end);
  const failureSource = source.slice(successConditional[0].alternate.start, successConditional[0].alternate.end);
  for (const name of scienceNames) {
    assert.match(successSource, new RegExp(`<${name}\\b`));
    assert.doesNotMatch(failureSource, new RegExp(`<${name}\\b`));
  }
  assert.match(failureSource, /ResultFailureEvidence/);
  assert.doesNotMatch(source, /PersonalVaspDatabase|backend\/routers\/vasp_db|fetch\s*\(|axios/i);
});

test('result scientific adapters infer artifacts and keep callback cleanup stable', () => {
  const source = read('../src/pages/competition/CompetitionResultDetail.jsx');
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] });
  const inferArtifactKind = loadFunction(source, 'inferArtifactKind');

  assert.equal(
    inferArtifactKind('/api/task/wf-band-study/export?format=cif', 'wf-band-study.cif'),
    'structure-cif',
  );
  assert.equal(
    inferArtifactKind('/api/task/wf-dos-study/band-dat', 'wf-dos-study_band.dat'),
    'band-data',
  );
  assert.equal(
    inferArtifactKind('/api/task/wf-band-study/dos-dat', 'wf-band-study_dos_data.zip'),
    'dos-data',
  );
  assert.equal(
    inferArtifactKind('/api/task/wf-dos-study/export?format=poscar', 'wf-dos-study.vasp'),
    'structure-poscar',
  );
  assert.equal(
    inferArtifactKind('/api/task/wf-band-study/artifacts/evidence-bundle', 'DEMO-evidence.json'),
    'evidence-bundle',
  );
  assert.equal(inferArtifactKind('/api/task/wf-dos-study/band-dat'), 'band-data');
  assert.equal(
    inferArtifactKind('/api/task/wf-band-study/export?format=poscar'),
    'structure-poscar',
  );
  assert.throws(
    () => inferArtifactKind('/api/task/wf-band-study/metadata', 'report.json'),
    /未知科学工件类型/,
  );
  assert.throws(
    () => inferArtifactKind('/api/task/wf-band-study/band-dat', 'report.json'),
    /未知科学工件类型/,
  );

  const requestScientificArtifact = loadFunction(source, 'requestScientificArtifact', {
    inferArtifactKind,
  });
  const artifactCalls = [];
  const artifactProvider = {
    downloadArtifact(...args) {
      artifactCalls.push(args);
      return { blob: new Blob(['fixture']), filename: 'DEMO-fixture' };
    },
  };
  assert.throws(
    () => requestScientificArtifact(
      artifactProvider, 'wf-band-study', '/api/task/wf-band-study/band-dat', 'report.json',
    ),
    /未知科学工件类型/,
  );
  assert.deepEqual(artifactCalls, []);
  requestScientificArtifact(
    artifactProvider, 'wf-band-study', '/api/task/wf-band-study/export?format=cif', 'wf-band-study.cif',
  );
  assert.deepEqual(artifactCalls, [['wf-band-study', 'structure-cif']]);

  const callbackNames = ['fetchScientificJson', 'downloadScientificFile'];
  for (const callbackName of callbackNames) {
    const declarations = findNodes(ast, (node) => (
      node.type === 'VariableDeclarator'
      && node.id?.name === callbackName
      && node.init?.type === 'CallExpression'
      && node.init.callee?.name === 'useCallback'
    ));
    assert.equal(declarations.length, 1, `${callbackName} must be useCallback-bound`);
    const callbackSource = source.slice(declarations[0].start, declarations[0].end);
    assert.match(callbackSource, /\[provider,\s*workflowId\]/);
  }
  assert.match(source, /requestScientificPlot\(provider,\s*workflowId,\s*path\)/);
  assert.match(source, /requestScientificArtifact\(provider,\s*workflowId,\s*path,\s*filename\)/);
  assert.match(source, /anchor\.download\s*=\s*artifact\.filename/);
  assert.doesNotMatch(source, /anchor\.download\s*=\s*filename/);

  const downloadDeclaration = findNodes(ast, (node) => (
    node.type === 'VariableDeclarator' && node.id?.name === 'downloadScientificFile'
  ))[0];
  const downloadTries = findNodes(downloadDeclaration, (node) => node.type === 'TryStatement');
  assert.equal(downloadTries.length, 1);
  assert.ok(downloadTries[0].finalizer, 'download cleanup must use finally');
  const cleanupSource = source.slice(downloadTries[0].finalizer.start, downloadTries[0].finalizer.end);
  assert.match(cleanupSource, /URL\.revokeObjectURL\(href\)/);
});

test('result plot adapter maps only controlled terminal paths before provider calls', () => {
  const source = read('../src/pages/competition/CompetitionResultDetail.jsx');
  const inferPlotKind = loadFunction(source, 'inferPlotKind');
  const requestScientificPlot = loadFunction(source, 'requestScientificPlot', { inferPlotKind });

  assert.equal(inferPlotKind('/api/task/wf-band-study/dos-plot?emin=-3&emax=3'), 'dos');
  assert.equal(inferPlotKind('/api/task/wf-dos-study/band-plot?align=fermi'), 'band');
  assert.throws(
    () => inferPlotKind('/api/task/wf-band-study/metadata'),
    /未知科学图类型/,
  );

  const plotCalls = [];
  const plotProvider = {
    loadPlot(...args) {
      plotCalls.push(args);
      return { image_url: '/fixture.svg' };
    },
  };
  assert.throws(
    () => requestScientificPlot(plotProvider, 'wf-band-study', '/api/task/wf-band-study/metadata'),
    /未知科学图类型/,
  );
  assert.deepEqual(plotCalls, []);
  requestScientificPlot(plotProvider, 'wf-band-study', '/api/task/wf-band-study/dos-plot');
  assert.deepEqual(plotCalls, [['wf-band-study', 'dos']]);
});

test('result detail preserves identity timeline ordering and explicit failure evidence', () => {
  const source = read('../src/pages/competition/CompetitionResultDetail.jsx');

  for (const label of [
    '工作流 ID',
    '创建人',
    '模板版本',
    '输入 SHA-256',
    '发布提交',
    '数据类型',
    '失败步骤',
    'Job ID',
    'ExitCode',
    '原因',
    '预期文件',
    '缺失文件',
    '最后日志',
  ]) {
    assert.match(source, new RegExp(label));
  }
  assert.match(source, /const\s*\{\s*workflowId\s*\}\s*=\s*useParams\(\);/);
  assert.match(source, /provider\.getResult\(workflowId\)/);
  assert.match(source, /workflowId\s*\?[^:]+:\s*Promise\.resolve\(null\)/s);
  assert.match(source, /<WorkflowTimeline\s+steps=\{resultSteps\}\s*\/>/);
  assert.doesNotMatch(source, /<WorkflowTimeline[^>]*compact/);
  assert.ok(source.indexOf('competition-result-identity') < source.indexOf('<WorkflowTimeline'));
  assert.ok(source.indexOf('<WorkflowTimeline') < source.indexOf("detailState.variant === 'success'"));
  assert.match(source, /failure_evidence/);
  assert.match(source, /失败证据不完整/);
  assert.match(source, /Array\.isArray/);
  assert.match(source, /演示内容/);
  assert.match(source, /dbKey=\{scientificDbKey\}/g);
  assert.match(source, /rowId=\{workflowId\}/g);
  assert.match(source, /downloadFile=\{downloadScientificFile\}/g);
  assert.match(source, /fetchJson=\{fetchScientificJson\}/);
  assert.match(source, /capabilities=\{result\.vasp_detail\.capabilities\}/);
  assert.match(source, /viewer=\{<VaspStructureViewer\s+structure=\{result\.vasp_detail\.structure\}\s*\/>\}/);
  assert.match(source, /mode\s*===\s*['"]demo['"]\s*\?\s*<DemoDataBanner\s*\/>\s*:\s*null/g);
});

test('result page styles stay scoped, compact, overflow-safe, and responsive', () => {
  const source = read('../src/pages/competition/CompetitionPages.css');

  for (const selector of [
    '.competition-results-page',
    '.competition-result-detail-page',
    '.competition-result-identity',
    '.competition-result-science',
    '.competition-result-failure',
    '.competition-result-log',
  ]) {
    assert.match(source, new RegExp(selector.replace('.', '\\.')));
  }
  assert.match(source, /\.competition-result-identity\s*{[^}]*display:\s*grid/s);
  assert.match(source, /\.competition-result-(?:identity|failure|log)[\s\S]*?overflow-wrap:\s*anywhere/);
  assert.match(source, /\.competition-result-log\s*{[^}]*white-space:\s*pre-wrap/s);
  assert.match(source, /@media\s*\(max-width:\s*700px\)[\s\S]*?\.competition-result-identity\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
  assert.doesNotMatch(source, /font-size:\s*[^;]*vw/);
  assert.doesNotMatch(source, /letter-spacing:\s*-/);
  for (const radius of source.matchAll(/border-radius:\s*(\d+)px/g)) {
    assert.ok(Number(radius[1]) <= 8, `border radius exceeds 8px: ${radius[0]}`);
  }
});
