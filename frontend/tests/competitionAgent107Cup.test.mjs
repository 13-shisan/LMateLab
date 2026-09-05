import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';


test('competition Agent has a dedicated protected page and navigation item', () => {
  const app = readFileSync(new URL('../src/App107Cup.jsx', import.meta.url), 'utf8');
  const navigation = readFileSync(new URL('../src/config/appNavigation.js', import.meta.url), 'utf8');
  const pageUrl = new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url);

  assert.equal(existsSync(pageUrl), true);
  assert.match(app, /CompetitionAgent/);
  assert.match(app, /path="\/dashboard\/agent"/);
  assert.match(navigation, /competition-agent/);
  assert.match(navigation, /\/dashboard\/agent/);
  assert.match(navigation, /label: 'Agent'/);
  assert.doesNotMatch(navigation, /Qoder Agent/);
});


test('Agent page polls structured runs and keeps viewer submission disabled', () => {
  const source = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );

  assert.match(source, /useCompetitionPollingResource/);
  assert.match(source, /canWriteCompetitionData/);
  assert.match(source, /createAgentRun/);
  assert.match(source, /listAgentRuns/);
  assert.match(source, /Viewer/);
  assert.match(source, /succeeded:\s*'已完成'/);
  assert.doesNotMatch(source, /StatusBadge/);
  assert.doesNotMatch(source, /EventSource|WebSocket/);
});


test('demo provider blocks Agent mutation before network', async () => {
  const { createDemoCompetitionDataProvider } = await import(
    '../src/features/competition/data/demoCompetitionDataProvider.js'
  );
  const provider = createDemoCompetitionDataProvider();
  await assert.rejects(() => provider.createAgentRun({ prompt: 'test' }), /Agent/);
});

test('Agent page reveals the bounded structure workspace only after a backend result', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  const builder = readFileSync(
    new URL('../src/features/competition/agent/StructureBuilder.jsx', import.meta.url),
    'utf8',
  );

  assert.match(page, /preparedStructure/);
  assert.match(page, /showManualBuilder/);
  assert.match(page, /<StructureBuilder(?:\s+[^>]*)?\s*\/>/);
  for (const token of [
    'listCuratedStructures',
    'buildCuratedStructure',
    'downloadCuratedStructureBundle',
    '面内超胞',
    '层数',
    '真空层',
    'POTCAR',
    'VaspStructureViewer',
  ]) {
    assert.match(builder, new RegExp(token));
  }
  assert.doesNotMatch(builder, /fetch\(|WebSocket|EventSource|Materials Project|api_key/i);
});

test('structure builder verifies editable inputs before app-owned queue handoff', () => {
  const builder = readFileSync(
    new URL('../src/features/competition/agent/StructureBuilder.jsx', import.meta.url),
    'utf8',
  );

  for (const token of [
    'manual',
    'mock_qoder',
    'KPOINTS',
    '核验',
    'role="dialog"',
    'uploadStructure',
    'saveDraft',
    'submitWorkflow',
    'startWorkflow',
  ]) {
    assert.match(builder, new RegExp(token));
  }
  assert.match(builder, /BAND.*Γ-M-K-Γ/s);
  assert.doesNotMatch(builder, /sbatch|scancel|Bash|WebFetch/);
});

test('successful calculation conversation can fill a missing structure once and exposes kz', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  const builder = readFileSync(
    new URL('../src/features/competition/agent/StructureBuilder.jsx', import.meta.url),
    'utf8',
  );

  assert.match(page, /run\?\.output\?\.workspace\?\.structure/);
  assert.match(builder, /useEffect/);
  assert.match(builder, /preparedStructure/);
  assert.match(builder, /autoBuildHandled/);
  assert.doesNotMatch(builder, /autoBuildRequest/);
  assert.match(builder, /\['kx', 'ky', 'kz'\]/);
});

test('Agent initial surface is a compact three-pane workspace linked to existing features', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );

  assert.match(page, /competition-agent-history/);
  assert.match(page, /competition-agent-resources/);
  assert.match(page, /tool_calls/);
  assert.match(page, /\/dashboard\/workflows/);
  assert.match(page, /\/dashboard\/database\/vasp/);
  assert.doesNotMatch(page, /competition-agent-catalog/);
});

test('Agent mounts selected public structures without hard-coding a material', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );

  assert.match(page, /searchAgentStructures/);
  assert.match(page, /selectedStructureIds/);
  assert.match(page, /structure_ids:\s*selectedStructureIds/);
  assert.doesNotMatch(page, /material_id:\s*'MoS2_monolayer'/);
  assert.match(page, /公开结构库/);
});

test('Agent exposes server-backed LLM settings, file upload, and structure search', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  assert.match(page, /getAgentSettings/);
  assert.match(page, /updateAgentSettings/);
  assert.match(page, /uploadAgentFile/);
  assert.match(page, /searchAgentStructures/);
  assert.match(page, /Agent 设置/);
  assert.doesNotMatch(page, /QODER_LINUX_DISTRIBUTION/);
});

test('Agent renders calculation plans and predefined file analyzer facts', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  for (const token of [
    'CalculationPlanResult',
    'plan.needs_upload',
    'template.rendered_content',
    'parameter_changes',
    'AnalysisFacts',
    'analysis_results',
    '预置分析器结果',
  ]) {
    assert.match(page, new RegExp(token.replace('.', '\\.')));
  }
  assert.doesNotMatch(page, /eval\(|new Function|child_process/);
});

test('Agent workspace persists history, merges QA and file analysis, and removes template recommendation UI', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  for (const token of ['对话与任务历史', '已挂载', '提交新建计算', '上传结构并重新规划']) {
    assert.match(page, new RegExp(token));
  }
  assert.match(page, /request_kind:\s*'auto'/);
  assert.match(page, /取消挂载文献/);
  assert.doesNotMatch(page, /setRequestKind|role="tablist"|competition-agent-segment/);
  assert.doesNotMatch(page, />模板建议</);
  assert.doesNotMatch(page, /批准为只读分析/);
});

test('Agent exposes categorized uploads and a real literature indexing surface', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  for (const token of [
    'INCAR 模板', '结构文件', '计算结果', '文献 PDF', 'searchAgentLiterature',
    'indexAgentLiterature', 'OpenAlex', '联网检索文献',
  ]) assert.match(page, new RegExp(token));
});

test('Agent groups deletable conversations, mounts workflows, and hands plans to new calculation', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  const provider = readFileSync(
    new URL('../src/features/competition/data/apiCompetitionDataProvider.js', import.meta.url),
    'utf8',
  );

  for (const token of [
    'conversationGroups', 'turnCount', 'deleteAgentConversation', 'Trash2',
    'listWorkflows', 'type="radio"', 'VaspElectronicProperties',
    "navigate('/dashboard/calculations/new'", 'agentHandoff',
    'literatureLibrary.data?.uploads', 'CitationList',
  ]) assert.match(page, new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
  assert.match(provider, /method:\s*['"]DELETE['"]/);
  assert.match(page, /getRandomValues/);
  assert.doesNotMatch(page, /00000000-0000-4000-8000-000000000000/);
});

test('Agent mounts complete VASP calculation directories and exposes the optional Qoder interface', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  const provider = readFileSync(
    new URL('../src/features/competition/data/apiCompetitionDataProvider.js', import.meta.url),
    'utf8',
  );

  for (const token of [
    'CalculationDirectoryTree', 'selectedCalculationIds', 'calculation_ids',
    'VASP 计算目录', 'webkitdirectory', 'Qoder 接口', 'qoder-agent-sdk',
  ]) assert.match(page, new RegExp(token));
  assert.match(provider, /calculation_id/);
  assert.match(provider, /group_name/);
  assert.doesNotMatch(page, /category === 'result'.*type="checkbox"/s);
});

test('Qoder settings expose fixed install, login, and service controls', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  const provider = readFileSync(
    new URL('../src/features/competition/data/apiCompetitionDataProvider.js', import.meta.url),
    'utf8',
  );
  for (const token of ['一键安装', '一键登录', '启动服务', '停止 Qoder 服务', '打开 Qoder 授权页']) {
    assert.match(page, new RegExp(token));
  }
  for (const route of ['/qoder/install', '/qoder/login', '/qoder/service/start', '/qoder/service/stop']) {
    assert.match(provider, new RegExp(route));
  }
});
