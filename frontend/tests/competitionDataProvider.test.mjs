import test from 'node:test';
import assert from 'node:assert/strict';

import { PreviewReadOnlyError } from '../src/features/competition/data/competitionErrors.js';
import { createDemoCompetitionDataProvider } from '../src/features/competition/data/demoCompetitionDataProvider.js';
import { createApiCompetitionDataProvider } from '../src/features/competition/data/apiCompetitionDataProvider.js';
import { createCompetitionDataProvider } from '../src/features/competition/data/competitionDataProvider.js';
import {
  DEMO_DATABASE_METADATA,
  DEMO_DATABASE_ROWS,
  DEMO_RESULTS_BY_ID,
  DEMO_WORKFLOWS,
} from '../src/features/competition/data/demoFixtures.js';

test('demo workflows preserve the preview status and step order', async () => {
  const provider = createDemoCompetitionDataProvider();
  const response = await provider.listWorkflows();

  assert.deepEqual(response.items.map(({ status }) => status), ['succeeded', 'running', 'failed']);
  assert.deepEqual(response.items[0].steps.map(({ key }) => key), ['relax', 'scf', 'band', 'dos']);
  assert.equal(response.items.every(({ data_kind }) => data_kind === 'demo'), true);
  assert.equal(response.total, 3);
  assert.equal(response.data_kind, 'demo');
});

test('demo results use the same items envelope as workflow lists', async () => {
  const provider = createDemoCompetitionDataProvider();
  const response = await provider.listResults();

  assert.deepEqual(response.items.map(({ id }) => id), [
    'wf-demo-mos2-success',
    'wf-demo-mos2-failed',
  ]);
  assert.equal(response.total, 2);
  assert.equal(response.data_kind, 'demo');
});

test('demo database applies at-least and only element matching', async () => {
  const provider = createDemoCompetitionDataProvider();

  const molybdenum = await provider.listDatabase({ elements: ['Mo'], elementMode: 'at_least' });
  const molybdenumOnly = await provider.listDatabase({ elements: ['Mo'], elementMode: 'only' });
  const mos2Only = await provider.listDatabase({ elements: ['Mo', 'S'], elementMode: 'only' });

  assert.equal(molybdenum.total, 3);
  assert.equal(molybdenumOnly.total, 0);
  assert.equal(mos2Only.total, 3);
});

test('demo mutations reject before any supplied fetch implementation runs', async () => {
  let requestCount = 0;
  const provider = createDemoCompetitionDataProvider({
    fetchImpl: async () => {
      requestCount += 1;
      throw new Error('demo mutations must not request the network');
    },
  });
  const mutations = [
    ['uploadStructure', [new Blob(['POSCAR'])], '结构上传'],
    ['saveDraft', [{ material: 'MoS2' }], '草稿保存'],
    ['submitWorkflow', ['wf-demo-mos2-running'], '工作流提交'],
    ['cancelWorkflow', ['wf-demo-mos2-running'], '工作流取消'],
    ['retryWorkflow', ['wf-demo-mos2-failed', 'scf'], '工作流重试'],
    ['mutateDatabase', [{ formula: 'MoS2' }], '数据库写入'],
  ];

  for (const [method, args, action] of mutations) {
    await assert.rejects(
      () => provider[method](...args),
      (error) => {
        assert.equal(error instanceof PreviewReadOnlyError, true);
        assert.equal(error.name, 'PreviewReadOnlyError');
        assert.equal(error.code, 'preview-read-only');
        assert.equal(error.message, `预览环境不会执行${action}`);
        return true;
      },
    );
  }
  assert.equal(requestCount, 0);
});

test('live dashboard and workflow list request the exact competition routes', async () => {
  const requests = [];
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    fetchImpl: async (path, init) => {
      requests.push([path, init]);
      return new Response(JSON.stringify({ data_kind: 'live' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    },
  });

  await provider.getDashboard();
  await provider.listWorkflows({ query: 'MoS2', status: 'running' });

  assert.deepEqual(requests.map(([path]) => path), [
    '/api/competition/dashboard',
    '/api/competition/workflows?query=MoS2&status=running',
  ]);
});

test('live forbidden responses retain status and never fall back to demo data', async () => {
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    fetchImpl: async () => new Response(JSON.stringify({ detail: 'viewer cannot write' }), {
      status: 403,
      headers: { 'content-type': 'application/json' },
    }),
  });

  await assert.rejects(
    () => provider.saveDraft({ material: 'MoS2' }),
    (error) => {
      assert.equal(error.name, 'CompetitionRequestError');
      assert.equal(error.status, 403);
      assert.equal(error.code, 'forbidden');
      assert.equal(error.message, 'viewer cannot write');
      assert.equal('data_kind' in error, false);
      assert.doesNotMatch(error.message, /demo|演示/i);
      return true;
    },
  );
});

test('demo database pagination is stable and reports the full total', async () => {
  const provider = createDemoCompetitionDataProvider();
  const firstPage = await provider.listDatabase({ page: 1, pageSize: 2 });
  const secondPage = await provider.listDatabase({ page: 2, pageSize: 2 });

  assert.equal(firstPage.items.length, 2);
  assert.equal(secondPage.items.length, 1);
  assert.equal(firstPage.total, 3);
  assert.equal(secondPage.total, 3);
  assert.equal(new Set([...firstPage.items, ...secondPage.items].map(({ id }) => id)).size, 3);
  assert.equal(firstPage.data_kind, 'demo');
  assert.deepEqual(firstPage.available_elements, ['Mo', 'S']);
  assert.equal(firstPage.metadata.source.label, '来源');
});

test('demo database energy fields are populated only for succeeded workflows', () => {
  const [succeeded, running, failed] = DEMO_DATABASE_ROWS;

  assert.deepEqual(
    [succeeded.bandgap_eV, succeeded.energy, succeeded.completed_at],
    [1.78, -22.418731, '2026-08-10T09:40:00+08:00'],
  );
  assert.deepEqual(
    [
      succeeded.vasp_detail.row.energy,
      succeeded.vasp_detail.row.fmax,
      succeeded.vasp_detail.properties.bandgap_eV,
      succeeded.vasp_detail.properties.vbm_eV,
      succeeded.vasp_detail.properties.cbm_eV,
    ],
    [-22.418731, 0.0062, 1.78, 0, 1.78],
  );
  for (const row of [running, failed]) {
    assert.equal(row.bandgap_eV, null);
    assert.equal(row.energy, null);
    assert.equal(row.completed_at, null);
    assert.deepEqual(
      [
        row.vasp_detail.row.energy,
        row.vasp_detail.row.fmax,
        row.vasp_detail.properties.bandgap_eV,
        row.vasp_detail.properties.vbm_eV,
        row.vasp_detail.properties.cbm_eV,
      ],
      [null, null, null, null, null],
    );
    assert.equal(Object.values(row.vasp_detail.capabilities).every((value) => value === false), true);
  }
});

test('demo singular reads return null for missing ids', async () => {
  const provider = createDemoCompetitionDataProvider();

  assert.deepEqual(await Promise.all([
    provider.getWorkflow('missing-workflow'),
    provider.getResult('missing-result'),
    provider.getDatabaseRecord('missing-record'),
  ]), [null, null, null]);
});

test('demo database query does not match internal row ids', async () => {
  const provider = createDemoCompetitionDataProvider();
  const response = await provider.listDatabase({ query: 'db-demo-1' });

  assert.equal(response.total, 0);
  assert.deepEqual(response.items, []);
});

test('competition data provider mode is selected only at construction time', () => {
  assert.equal(createCompetitionDataProvider('demo').mode, 'demo');
  assert.equal(createCompetitionDataProvider('live', {
    authHeaders: () => ({}),
    fetchImpl: async () => new Response('{}'),
  }).mode, 'live');
  assert.throws(
    () => createCompetitionDataProvider('switchable'),
    /Unsupported competition data mode/,
  );
});

test('demo fixture collections expose provenance without adding a result id', () => {
  for (const collection of [DEMO_WORKFLOWS, DEMO_DATABASE_ROWS, DEMO_DATABASE_METADATA, DEMO_RESULTS_BY_ID]) {
    assert.equal(collection.data_kind, 'demo');
  }
  assert.deepEqual(Object.keys(DEMO_RESULTS_BY_ID), [
    'wf-demo-mos2-success',
    'wf-demo-mos2-failed',
  ]);
  assert.deepEqual(DEMO_DATABASE_METADATA.source, {
    label: '来源',
    kind: 'text',
    priority: 1,
  });
});

test('direct fixture imports cannot mutate later demo provider reads', async () => {
  const workflowStep = DEMO_WORKFLOWS[0].steps[0];
  const databaseProperties = DEMO_DATABASE_ROWS[0].vasp_detail.properties;
  const originalStepStatus = workflowStep.status;
  const originalBandgap = databaseProperties.bandgap_eV;
  const workflowWasMutated = Reflect.set(workflowStep, 'status', 'failed');
  const databaseWasMutated = Reflect.set(databaseProperties, 'bandgap_eV', 0);

  try {
    const provider = createDemoCompetitionDataProvider();
    const workflows = await provider.listWorkflows();
    const database = await provider.listDatabase();

    assert.equal(workflows.items[0].steps[0].status, 'succeeded');
    assert.equal(database.items[0].vasp_detail.properties.bandgap_eV, 1.78);
    assert.equal(workflowWasMutated, false);
    assert.equal(databaseWasMutated, false);
    assert.equal(Object.isFrozen(workflowStep), true);
    assert.equal(Object.isFrozen(databaseProperties), true);
  } finally {
    if (workflowWasMutated) Reflect.set(workflowStep, 'status', originalStepStatus);
    if (databaseWasMutated) Reflect.set(databaseProperties, 'bandgap_eV', originalBandgap);
  }
});

test('live database queries omit empty filters and map non-empty query names', async () => {
  const requests = [];
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    fetchImpl: async (path) => {
      requests.push(path);
      return new Response('{}', { headers: { 'content-type': 'application/json' } });
    },
  });

  await provider.listDatabase();
  await provider.listDatabase({
    query: 'MoS2',
    elements: ['Mo', 'S'],
    elementMode: 'only',
    page: 2,
    pageSize: 20,
  });

  assert.deepEqual(requests, [
    '/api/competition/vasp/records',
    '/api/competition/vasp/records?query=MoS2&elements=Mo%2CS&element_mode=only&page=2&page_size=20',
  ]);
});

test('live structure upload leaves multipart content type to FormData', async () => {
  let headers;
  const provider = createApiCompetitionDataProvider({
    authHeaders: (contentType) => contentType ? { 'Content-Type': contentType } : {},
    fetchImpl: async (_path, init) => {
      headers = init.headers;
      return new Response('{}', { headers: { 'content-type': 'application/json' } });
    },
  });

  await provider.uploadStructure(new Blob(['DEMO POSCAR']));

  assert.equal(Object.keys(headers).some((name) => name.toLowerCase() === 'content-type'), false);
});

test('live structure draft and confirmation preserve server contracts exactly', async () => {
  const requests = [];
  const responses = [
    {
      id: 'upload-server-id',
      size_bytes: 321,
      sha256: 'a'.repeat(64),
      source_format: 'vasp',
      summary: { formula: 'MoS2', atom_count: 3 },
    },
    {
      id: 'workflow-server-id',
      status: 'draft',
      input_sha256: 'b'.repeat(64),
      template_version: 'mos2_v1',
      source_kind: 'upload',
      structure_summary: { formula: 'MoS2', atom_count: 3 },
    },
    {
      id: 'workflow-server-id',
      status: 'validated',
      input_sha256: 'b'.repeat(64),
      template_version: 'mos2_v1',
      source_kind: 'upload',
      structure_summary: { formula: 'MoS2', atom_count: 3 },
    },
  ];
  const provider = createApiCompetitionDataProvider({
    authHeaders: (contentType) => contentType ? { 'Content-Type': contentType } : {},
    fetchImpl: async (path, init) => {
      requests.push({ path, init });
      return new Response(JSON.stringify(responses[requests.length - 1]), {
        status: requests.length < 3 ? 201 : 200,
        headers: { 'content-type': 'application/json' },
      });
    },
  });
  const file = new Blob(['MoS2 POSCAR']);
  const draftPayload = {
    template_version: 'mos2_v1',
    source_kind: 'upload',
    steps: ['relax', 'scf', 'band', 'dos'],
    parameters: { relax: { ENCUT: 520 } },
    structure_upload_id: 'upload-server-id',
  };

  const upload = await provider.uploadStructure(file);
  const draft = await provider.saveDraft(draftPayload);
  const confirmation = await provider.submitWorkflow(draft.id);

  assert.equal(upload.id, 'upload-server-id');
  assert.equal(draft.id, 'workflow-server-id');
  assert.equal(confirmation.status, 'validated');
  assert.deepEqual(requests.map(({ path }) => path), [
    '/api/competition/structures',
    '/api/competition/drafts',
    '/api/competition/workflows/workflow-server-id/submit',
  ]);
  assert.equal(requests[0].init.body instanceof FormData, true);
  const uploadedPart = requests[0].init.body.get('file');
  assert.equal(uploadedPart.size, file.size);
  assert.equal(await uploadedPart.text(), await file.text());
  assert.deepEqual(JSON.parse(requests[1].init.body), draftPayload);
  assert.equal(Object.hasOwn(JSON.parse(requests[1].init.body), 'owner'), false);
  assert.equal(requests[2].init.body, '{}');
});

test('live workflow retry accepts an object and encodes id and step', async () => {
  let request;
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    fetchImpl: async (path, init) => {
      request = { path, init };
      return new Response('{}', { headers: { 'content-type': 'application/json' } });
    },
  });

  await provider.retryWorkflow({ id: 'wf/demo id', step: 'scf+restart' });

  assert.equal(request.path, '/api/competition/workflows/wf%2Fdemo%20id/steps/scf%2Brestart/retry');
  assert.equal(request.init.method, 'POST');
  assert.equal(request.init.body, '{}');
});
