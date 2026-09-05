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
    ['startWorkflow', ['wf-demo-mos2-running'], '工作流启动'],
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

test('live dashboard, service health, and workflow list request the exact competition routes', async () => {
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
  await provider.getServiceHealth();
  await provider.listWorkflows({ query: 'MoS2', status: 'running' });

  assert.deepEqual(requests.map(([path]) => path), [
    '/api/competition/dashboard',
    '/api/health/live',
    '/api/competition/workflows?query=MoS2&status=running',
  ]);
});

test('demo service health is deterministic and never requests the network', async () => {
  let requestCount = 0;
  const provider = createDemoCompetitionDataProvider({
    fetchImpl: async () => {
      requestCount += 1;
      throw new Error('demo health must not request the network');
    },
  });

  assert.deepEqual(await provider.getServiceHealth(), {
    status: 'ok',
    job_id: 'DEMO-SERVICE',
    node: 'anode18',
    commit: '0000000000000000000000000000000000000000',
    release_kind: 'preview',
    data_mode: 'demo',
  });
  assert.equal(requestCount, 0);
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
      assert.equal(error.message, '当前身份无权执行此操作');
      assert.equal('details' in error, false);
      assert.equal('data_kind' in error, false);
      assert.doesNotMatch(error.message, /demo|演示/i);
      return true;
    },
  );
});

test('live request failures expose only stable status-based public errors', async () => {
  const cases = [
    {
      status: 401,
      body: { detail: '/home/private/initial', code: 'attacker-code' },
      message: '登录状态已失效，请重新登录',
      code: 'unauthorized',
    },
    {
      status: 403,
      body: { message: 'cat /etc/passwd', code: 'run-command' },
      message: '当前身份无权执行此操作',
      code: 'forbidden',
    },
    {
      status: 404,
      body: { detail: '../private/workflow' },
      message: '请求的数据不存在',
      code: 'not-found',
    },
    {
      status: 409,
      body: { detail: `$(scancel 41002)\n${'x'.repeat(5000)}` },
      message: '当前状态不允许执行此操作',
      code: 'conflict',
    },
    {
      status: 422,
      body: { detail: [{ message: 'line one\nline two\n/home/private/input' }] },
      message: '请求内容未通过校验',
      code: 'validation-error',
    },
    {
      status: 503,
      body: { detail: '/home/private/service', code: 'internal-trace-code' },
      message: '服务暂时不可用，请稍后重试',
      code: 'server-error',
    },
    {
      status: 418,
      body: { detail: 'unexpected\nserver\nbody' },
      message: '请求失败，请稍后重试',
      code: 'request-failed',
    },
  ];

  for (const expected of cases) {
    const rawBody = JSON.stringify(expected.body);
    const provider = createApiCompetitionDataProvider({
      authHeaders: () => ({}),
      fetchImpl: async () => new Response(rawBody, {
        status: expected.status,
        headers: { 'content-type': 'application/json' },
      }),
    });
    await assert.rejects(
      () => provider.getWorkflow('wf-1'),
      (error) => {
        assert.equal(error.name, 'CompetitionRequestError');
        assert.equal(error.status, expected.status);
        assert.equal(error.code, expected.code);
        assert.equal(error.message, expected.message);
        assert.equal('details' in error, false);
        const publicError = `${error.message}\n${JSON.stringify(error)}`;
        for (const secret of [
          '/home/private', 'cat /etc/passwd', 'scancel', 'line one',
          'internal-trace-code', 'attacker-code', 'unexpected',
        ]) {
          assert.equal(publicError.includes(secret), false, `${expected.status}: ${secret}`);
        }
        assert.ok(publicError.length < 300);
        return true;
      },
    );
  }
});

test('live structure validation uses only allowlisted error headers', async () => {
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    fetchImpl: async () => new Response(
      JSON.stringify({ detail: '/home/private/ase-parser-trace' }),
      {
        status: 422,
        headers: {
          'content-type': 'application/json',
          'x-error-code': 'structure_format_invalid',
        },
      },
    ),
  });

  await assert.rejects(
    () => provider.uploadStructure(new Blob(['invalid'])),
    (error) => {
      assert.equal(error.code, 'structure_format_invalid');
      assert.equal(error.message, '无法按 POSCAR 或 CIF 解析结构');
      assert.doesNotMatch(error.message, /home|ase|trace/i);
      return true;
    },
  );
});

test('live malformed JSON responses never retain the response text', async () => {
  const privateResponse = '{"detail":"/home/private/sensitive-response-marker\n$(scancel 1)"';
  for (const status of [200, 503]) {
    const provider = createApiCompetitionDataProvider({
      authHeaders: () => ({}),
      fetchImpl: async () => new Response(privateResponse, {
        status,
        headers: { 'content-type': 'application/json' },
      }),
    });
    await assert.rejects(
      () => provider.getWorkflow('wf-1'),
      (error) => {
        assert.equal(error.status, status);
        assert.equal(
          error.message,
          status === 200
            ? '响应格式无效，请稍后重试'
            : '服务暂时不可用，请稍后重试',
        );
        assert.equal(error.code, status === 200 ? 'parse-error' : 'server-error');
        assert.equal('details' in error, false);
        const publicError = `${error.message}\n${JSON.stringify(error)}`;
        assert.doesNotMatch(publicError, /home\/private|scancel|sensitive-response-marker/i);
        return true;
      },
    );
  }
});

test('live transport failures expose only stable public errors', async () => {
  const cases = [
    {
      label: 'fetch rejection',
      fetchImpl: async () => {
        throw new Error('/home/private/fetch-failure $(scancel 1)');
      },
      status: 0,
      message: '网络连接失败，请稍后重试',
      code: 'network-error',
    },
    {
      label: 'fetch abort',
      fetchImpl: async () => {
        throw new DOMException('/home/private/abort-failure', 'AbortError');
      },
      status: 0,
      message: '请求已中断，请重试',
      code: 'request-aborted',
    },
    {
      label: 'response text rejection',
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        headers: new Headers({ 'content-type': 'application/json' }),
        text: async () => {
          throw new Error('/home/private/body-read-failure');
        },
      }),
      status: 200,
      message: '响应读取失败，请稍后重试',
      code: 'response-read-error',
    },
    {
      label: 'response blob rejection',
      method: 'downloadArtifact',
      args: ['wf-1', 'band'],
      fetchImpl: async () => ({
        ok: true,
        status: 200,
        headers: new Headers(),
        blob: async () => {
          throw new Error('/home/private/blob-read-failure');
        },
      }),
      status: 200,
      message: '响应读取失败，请稍后重试',
      code: 'response-read-error',
    },
  ];

  for (const expected of cases) {
    const provider = createApiCompetitionDataProvider({
      authHeaders: () => ({}),
      fetchImpl: expected.fetchImpl,
    });
    const method = expected.method || 'getWorkflow';
    const args = expected.args || ['wf-1'];
    await assert.rejects(
      () => provider[method](...args),
      (error) => {
        assert.equal(error.name, 'CompetitionRequestError', expected.label);
        assert.equal(error.status, expected.status, expected.label);
        assert.equal(error.code, expected.code, expected.label);
        assert.equal(error.message, expected.message, expected.label);
        assert.equal('details' in error, false, expected.label);
        assert.equal('cause' in error, false, expected.label);
        const publicError = `${error.message}\n${JSON.stringify(error)}`;
        assert.doesNotMatch(publicError, /home\/private|scancel|failure/i, expected.label);
        return true;
      },
    );
  }
});

test('live requests time out even when fetch ignores abort signals', { timeout: 1000 }, async () => {
  let suppliedSignal = null;
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    requestTimeoutMs: 20,
    fetchImpl: async (_path, init) => {
      suppliedSignal = init.signal;
      return new Promise(() => {});
    },
  });

  const startedAt = Date.now();
  await assert.rejects(
    () => provider.getWorkflow('wf-1'),
    (error) => {
      assert.equal(error.name, 'CompetitionRequestError');
      assert.equal(error.status, 0);
      assert.equal(error.code, 'request-timeout');
      assert.equal(error.message, '请求超时，请稍后重试');
      assert.equal('details' in error, false);
      assert.equal('cause' in error, false);
      return true;
    },
  );
  assert.ok(Date.now() - startedAt < 500);
  assert.equal(suppliedSignal instanceof AbortSignal, true);
  assert.equal(suppliedSignal.aborted, true);
});

test('live request timeout covers stalled body reads', { timeout: 1000 }, async () => {
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    requestTimeoutMs: 20,
    fetchImpl: async () => ({
      ok: true,
      status: 200,
      headers: new Headers({ 'content-type': 'application/json' }),
      text: async () => new Promise(() => {}),
    }),
  });

  await assert.rejects(
    () => provider.getWorkflow('wf-1'),
    (error) => error.name === 'CompetitionRequestError'
      && error.status === 0
      && error.code === 'request-timeout'
      && error.message === '请求超时，请稍后重试',
  );
});

test('live requests clear timers and safely observe late fetch rejection', { timeout: 1000 }, async () => {
  let successfulSignal = null;
  const successfulProvider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    requestTimeoutMs: 20,
    fetchImpl: async (_path, init) => {
      successfulSignal = init.signal;
      return new Response('{}', { headers: { 'content-type': 'application/json' } });
    },
  });
  await successfulProvider.getWorkflow('wf-1');
  await new Promise((resolve) => setTimeout(resolve, 40));
  assert.equal(successfulSignal.aborted, false);

  let rejectLateFetch;
  const lateProvider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    requestTimeoutMs: 20,
    fetchImpl: async () => new Promise((_resolve, reject) => {
      rejectLateFetch = reject;
    }),
  });
  const unhandled = [];
  const captureUnhandled = (reason) => unhandled.push(reason);
  process.on('unhandledRejection', captureUnhandled);
  try {
    await assert.rejects(
      () => lateProvider.getWorkflow('wf-1'),
      (error) => error.code === 'request-timeout',
    );
    rejectLateFetch(new Error('/home/private/late-fetch-rejection'));
    await new Promise((resolve) => setImmediate(resolve));
    assert.deepEqual(unhandled, []);
  } finally {
    process.off('unhandledRejection', captureUnhandled);
  }
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

test('live curated structure builder uses fixed JSON routes and returns a bundle filename', async () => {
  const requests = [];
  const responses = [
    new Response(JSON.stringify({ items: [{ id: 'MoS2_monolayer' }] }), {
      headers: { 'content-type': 'application/json' },
    }),
    new Response(JSON.stringify({ material_id: 'MoS2_monolayer', files: { POSCAR: 'demo' } }), {
      headers: { 'content-type': 'application/json' },
    }),
    new Response(new Blob(['zip']), {
      headers: {
        'content-type': 'application/zip',
        'content-disposition': 'attachment; filename="MoS2_monolayer-vasp-inputs.zip"',
      },
    }),
  ];
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({ 'Content-Type': 'application/json' }),
    fetchImpl: async (path, init) => {
      requests.push({ path, init });
      return responses[requests.length - 1];
    },
  });
  const payload = {
    material_id: 'MoS2_monolayer',
    repeat_a: 2,
    repeat_b: 2,
    layers: 1,
    vacuum_angstrom: 18,
    interlayer_spacing_angstrom: 6.2,
    strain_percent: 0,
  };

  const catalog = await provider.listCuratedStructures();
  const built = await provider.buildCuratedStructure(payload);
  const bundle = await provider.downloadCuratedStructureBundle(payload);

  assert.equal(catalog.items[0].id, 'MoS2_monolayer');
  assert.equal(built.files.POSCAR, 'demo');
  assert.equal(bundle.filename, 'MoS2_monolayer-vasp-inputs.zip');
  assert.deepEqual(requests.map(({ path }) => path), [
    '/api/competition/agent/structures',
    '/api/competition/agent/structures/build',
    '/api/competition/agent/structures/bundle',
  ]);
  assert.equal(requests[0].init.method, undefined);
  assert.deepEqual(JSON.parse(requests[1].init.body), payload);
  assert.deepEqual(JSON.parse(requests[2].init.body), payload);
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

test('live provider validates then starts through separate fixed routes', async () => {
  const requests = [];
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    fetchImpl: async (path, init) => {
      requests.push([path, init]);
      return new Response('{}', {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    },
  });

  await provider.submitWorkflow('wf-1');
  await provider.startWorkflow('wf-1');

  assert.deepEqual(requests.map(([path]) => path), [
    '/api/competition/workflows/wf-1/submit',
    '/api/competition/workflows/wf-1/start',
  ]);
  assert.deepEqual(requests.map(([, init]) => [init.method, init.body]), [
    ['POST', '{}'],
    ['POST', '{}'],
  ]);
});

test('attempt log providers use only safe fixed stdout and stderr routes', async () => {
  const requests = [];
  const live = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    fetchImpl: async (path, init) => {
      requests.push([path, init]);
      const stream = path.endsWith('/stderr') ? 'stderr' : 'stdout';
      return new Response(JSON.stringify({ stream, content: `${stream} tail\n` }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    },
  });

  assert.deepEqual(
    await live.getAttemptLog('wf-1', 'attempt-1', 'stdout'),
    { stream: 'stdout', content: 'stdout tail\n' },
  );
  assert.deepEqual(
    await live.getAttemptLog('wf-1', 'attempt-1', 'stderr'),
    { stream: 'stderr', content: 'stderr tail\n' },
  );
  assert.deepEqual(requests.map(([path]) => path), [
    '/api/competition/workflows/wf-1/attempts/attempt-1/logs/stdout',
    '/api/competition/workflows/wf-1/attempts/attempt-1/logs/stderr',
  ]);
  assert.equal(requests.every(([, init]) => init.method === undefined), true);

  const requestCount = requests.length;
  for (const args of [
    ['/home/private/workflow', 'attempt-1', 'stdout'],
    ['wf-1', '/home/private/attempt', 'stdout'],
    ['wf-1', 'C:\\private\\attempt', 'stderr'],
    ['.', 'attempt-1', 'stdout'],
    ['..', 'attempt-1', 'stdout'],
    ['wf/child', 'attempt-1', 'stdout'],
    ['wf\\child', 'attempt-1', 'stdout'],
    ['wf-1', '../attempt', 'stdout'],
    ['wf-1', 'attempt/child', 'stdout'],
    ['wf-1', 'attempt\\child', 'stdout'],
    ['wf-1', 'attempt id', 'stdout'],
    ['wf-1', 'attempt\tid', 'stdout'],
    ['wf-1', 'attempt\nid', 'stdout'],
    ['wf-1', 'attempt%2Fchild', 'stdout'],
    ['wf-1', 'attempt-1', 'combined'],
    ['wf-1', 'attempt-1', '../../stdout'],
  ]) {
    await assert.rejects(
      () => live.getAttemptLog(...args),
      (error) => error?.status === 400 && error?.code === 'invalid-log-request',
    );
  }
  assert.equal(requests.length, requestCount);

  const demo = createDemoCompetitionDataProvider({
    fetchImpl: async () => { throw new Error('demo logs must not request the network'); },
  });
  const demoWorkflow = await demo.getWorkflow('wf-demo-mos2-running');
  const demoAttemptId = demoWorkflow.steps.find((step) => step.attempt_id)?.attempt_id;
  assert.match(demoAttemptId, /^[0-9a-f-]{36}$/);
  const demoLog = await demo.getAttemptLog(demoWorkflow.id, demoAttemptId, 'stdout');
  assert.deepEqual(Object.keys(demoLog).sort(), ['content', 'stream']);
  assert.equal(demoLog.stream, 'stdout');
  assert.match(demoLog.content, /DEMO/);
  assert.ok(new TextEncoder().encode(demoLog.content).byteLength <= 64 * 1024);
  for (const args of [
    ['..', demoAttemptId, 'stdout'],
    ['wf-demo/child', demoAttemptId, 'stdout'],
    ['wf-demo\\child', demoAttemptId, 'stdout'],
    [demoWorkflow.id, '../attempt', 'stdout'],
    [demoWorkflow.id, 'attempt id', 'stdout'],
    [demoWorkflow.id, demoAttemptId, 'stdin'],
  ]) {
    await assert.rejects(
      () => demo.getAttemptLog(...args),
      (error) => error?.status === 400 && error?.code === 'invalid-log-request',
    );
  }
});
