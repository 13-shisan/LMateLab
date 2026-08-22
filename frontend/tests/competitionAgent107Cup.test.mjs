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
});


test('Agent page polls structured runs and keeps viewer submission disabled', () => {
  const source = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );

  assert.match(source, /useCompetitionPollingResource/);
  assert.match(source, /canWriteCompetitionData/);
  assert.match(source, /createAgentRun/);
  assert.match(source, /listAgentTemplates/);
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

test('successful template conversation can fill a missing structure once and exposes kz', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  const builder = readFileSync(
    new URL('../src/features/competition/agent/StructureBuilder.jsx', import.meta.url),
    'utf8',
  );

  assert.match(page, /run\.output\?\.workspace\?\.structure/);
  assert.match(builder, /useEffect/);
  assert.match(builder, /preparedStructure/);
  assert.match(builder, /autoBuildHandled/);
  assert.doesNotMatch(builder, /autoBuildRequest/);
  assert.match(builder, /\['kx', 'ky', 'kz'\]/);
});

test('Agent initial surface is a compact backend-tool console linked to existing features', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );

  assert.match(page, /后端受控工具/);
  assert.match(page, /tool_calls/);
  assert.match(page, /\/dashboard\/workflows/);
  assert.match(page, /\/dashboard\/database\/vasp/);
  assert.doesNotMatch(page, /competition-agent-catalog/);
});

test('Agent selects a curated structure instead of treating MoS2 as a built-in material', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );

  assert.match(page, /listCuratedStructures/);
  assert.match(page, /materialId/);
  assert.match(page, /material_id:\s*materialId/);
  assert.doesNotMatch(page, /material_id:\s*'MoS2_monolayer'/);
  assert.match(page, /受控样例结构/);
  assert.match(page, /请选择样例结构/);
});

test('Qoder Linux distribution link is repository-owned and authentication stays external', () => {
  const page = readFileSync(
    new URL('../src/features/competition/agent/CompetitionAgent.jsx', import.meta.url),
    'utf8',
  );
  const distribution = readFileSync(
    new URL('../src/config/qoderDistribution.js', import.meta.url),
    'utf8',
  );

  assert.match(distribution, /https:\/\/qoder\.com\/download/);
  assert.match(distribution, /authenticationOwner:\s*'user'/);
  assert.match(page, /QODER_LINUX_DISTRIBUTION/);
  assert.match(page, /Qoder Linux/);
  assert.match(page, /登录由用户/);
  assert.match(page, /target="_blank"/);
  assert.match(page, /noopener noreferrer/);
});
