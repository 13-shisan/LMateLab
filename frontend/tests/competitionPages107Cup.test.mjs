import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse } from '@babel/parser';

import { canWriteCompetitionData } from '../src/config/competitionAccess.js';
import { createDemoCompetitionDataProvider } from '../src/features/competition/data/demoCompetitionDataProvider.js';
import {
  formatVaspValue,
  getVaspColumnPresentation,
} from '../src/pages/db/vaspTablePresentation.js';

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

function loadFunctions(source, names, bindings = {}) {
  const ast = parse(source, { sourceType: 'module', plugins: ['jsx'] });
  const declarations = ast.program.body
    .map((node) => (node.type === 'ExportNamedDeclaration' ? node.declaration : node))
    .filter((node) => node?.type === 'FunctionDeclaration' && names.includes(node.id?.name));
  assert.deepEqual(
    declarations.map((node) => node.id.name).sort(),
    [...names].sort(),
    'all executable regression helpers must exist',
  );
  const bindingNames = Object.keys(bindings);
  return new Function(
    ...bindingNames,
    `${declarations.map((node) => source.slice(node.start, node.end)).join('\n')}\n`
      + `return { ${names.join(', ')} };`,
  )(...bindingNames.map((key) => bindings[key]));
}

const TEST_DATABASE_COLUMNS = Object.freeze([
  'formula',
  'source',
  'workflow_id',
  'status',
  'bandgap_eV',
  'energy',
  'completed_at',
]);
const TEST_DATABASE_STATUSES = new Set([
  'succeeded',
  'running',
  'waiting',
  'queued',
  'blocked',
  'failed',
  'stale',
  'parse-error',
  'render-error',
]);
const TEST_METADATA_KINDS = new Set(['text', 'number', 'integer', 'path', 'json']);
const TEST_ELEMENT_SYMBOLS = new Set(['H', 'Mo', 'S']);

function validDatabaseListItem(overrides = {}) {
  return {
    id: 'db-1',
    formula: 'MoS2',
    source: 'builtin',
    workflow_id: 'wf-1',
    status: 'succeeded',
    bandgap_eV: 1.78,
    energy: -22.418731,
    completed_at: '2026-08-10T09:40:00+08:00',
    data_kind: 'demo',
    ...overrides,
  };
}

function validDatabaseListEnvelope(overrides = {}) {
  return {
    items: [validDatabaseListItem()],
    total: 1,
    page: 1,
    page_size: 20,
    available_elements: ['Mo', 'S'],
    metadata: {
      formula: { label: 'Formula', kind: 'text', priority: 1 },
      energy: {
        label: 'Energy', unit: 'eV', decimals: 2, kind: 'number', priority: 1,
      },
    },
    data_kind: 'demo',
    ...overrides,
  };
}

function loadDatabaseResultNormalizer(source) {
  return loadFunctions(source, [
    'isPlainObject',
    'normalizeDatabaseListItem',
    'normalizeDatabaseMetadataEntry',
    'normalizeDatabaseMetadata',
    'normalizeAvailableElements',
    'normalizeDatabaseResult',
  ], {
    DATABASE_COLUMNS: TEST_DATABASE_COLUMNS,
    DATABASE_STATUSES: TEST_DATABASE_STATUSES,
    DATABASE_METADATA_KINDS: TEST_METADATA_KINDS,
    VALID_ELEMENT_SYMBOLS: TEST_ELEMENT_SYMBOLS,
  }).normalizeDatabaseResult;
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

test('competition VASP database composes the extracted read-only units', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  assert.doesNotThrow(() => parse(source, { sourceType: 'module', plugins: ['jsx'] }));

  for (const token of [
    'PeriodicTableFilter',
    'VaspRecordTable',
    'getDatabaseRecord',
    'available_elements',
    'elementMode',
    'selectedElements',
    'VaspStructureViewer',
  ]) {
    assert.match(source, new RegExp(token));
  }
  assert.match(source, /const\s+DATABASE_COLUMNS\s*=\s*Object\.freeze\(\[\s*['"]formula['"],\s*['"]source['"],\s*['"]workflow_id['"],\s*['"]status['"],\s*['"]bandgap_eV['"],\s*['"]energy['"],\s*['"]completed_at['"]\s*\]\)/);
  assert.match(
    source,
    /provider\.listDatabase\(\{\s*query,\s*elements:\s*selectedElements,\s*elementMode,\s*page,\s*pageSize:\s*20,?\s*\}\)/,
  );
  assert.match(source, /_rowId:\s*item\.id/);
  assert.match(source, /detailPathForItem=\{databaseRecordUrl\}/);
  assert.match(source, /onSelect=\{selectRecord\}/);
  assert.match(source, /renderCell=\{renderDatabaseCell\}/);
  assert.match(source, /mobileMode="scroll"/);
  assert.match(source, /column\s*===\s*['"]status['"]\s*\?\s*<StatusBadge\s+status=\{item\.status\}\s*\/>/);
  assert.match(source, /import\s+['"]\.\.\/db\/vasp-detail\/VaspTaskDetail\.css['"];?/);
  assert.doesNotMatch(source, /renderActions|onCollect|onRemove|customDbs|uploadFiles/);
  assert.doesNotMatch(source, /fetch\s*\(|axios|mutateDatabase|uploadStructure/);
});

test('competition database URL state normalizes invalid page mode and elements', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  const validElements = new Set(['H', 'Mo', 'S']);
  const readDatabaseUrlState = loadFunction(source, 'readDatabaseUrlState', {
    VALID_ELEMENT_SYMBOLS: validElements,
  });

  assert.deepEqual(readDatabaseUrlState(new URLSearchParams(
    'q=MoS2&elements=Mo,Nope,S,Mo&element_mode=unexpected&page=-4&record=db%2F1',
  )), {
    query: 'MoS2',
    selectedElements: ['Mo', 'S'],
    elementMode: 'at_least',
    page: 1,
    selectedRecordId: 'db/1',
  });
  assert.deepEqual(readDatabaseUrlState(new URLSearchParams(
    'elements=H&element_mode=only&page=3&record=%20',
  )), {
    query: '',
    selectedElements: ['H'],
    elementMode: 'only',
    page: 3,
    selectedRecordId: '',
  });
});

test('competition database URL writer uses canonical query keys', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  const writeDatabaseUrlState = loadFunction(source, 'writeDatabaseUrlState');
  const params = writeDatabaseUrlState({
    query: 'Mo S',
    selectedElements: ['Mo', 'S'],
    elementMode: 'only',
    page: 4,
    selectedRecordId: 'db/demo 1',
  });

  assert.equal(params.get('q'), 'Mo S');
  assert.equal(params.get('elements'), 'Mo,S');
  assert.equal(params.get('element_mode'), 'only');
  assert.equal(params.get('page'), '4');
  assert.equal(params.get('record'), 'db/demo 1');
  assert.deepEqual([...params.keys()], ['q', 'elements', 'element_mode', 'page', 'record']);
});

test('competition database page normalization clamps once and preserves filters', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  const databasePageNormalization = loadFunction(source, 'databasePageNormalization');
  const shouldApplyPageNormalization = loadFunction(source, 'shouldApplyPageNormalization');
  const writeDatabaseUrlState = loadFunction(source, 'writeDatabaseUrlState');
  const state = {
    query: 'Mo S',
    selectedElements: ['Mo', 'S'],
    elementMode: 'only',
    page: 999,
    selectedRecordId: 'db-old',
  };

  assert.deepEqual(databasePageNormalization(999, 21, 20), {
    required: true,
    targetPage: 2,
    totalPages: 2,
  });
  assert.deepEqual(databasePageNormalization(999, 0, 20), {
    required: true,
    targetPage: 1,
    totalPages: 1,
  });
  assert.deepEqual(databasePageNormalization(2, 21, 20), {
    required: false,
    targetPage: 2,
    totalPages: 2,
  });
  assert.equal(shouldApplyPageNormalization(true, 'page:999->2', ''), true);
  assert.equal(shouldApplyPageNormalization(true, 'page:999->2', 'page:999->2'), false);
  assert.equal(shouldApplyPageNormalization(false, 'page:2->2', ''), false);

  const normalization = databasePageNormalization(state.page, 21, 20);
  const params = writeDatabaseUrlState({
    ...state,
    page: normalization.targetPage,
    selectedRecordId: '',
  });
  assert.equal(params.get('q'), 'Mo S');
  assert.equal(params.get('elements'), 'Mo,S');
  assert.equal(params.get('element_mode'), 'only');
  assert.equal(params.get('page'), '2');
  assert.equal(params.has('record'), false);
  assert.match(
    source,
    /const\s+pageNormalization\s*=\s*useMemo\(\s*\(\)\s*=>\s*databasePageNormalization\(page,\s*result\.total,\s*result\.page_size\)/,
  );
  assert.match(
    source,
    /useEffect\(\(\)\s*=>\s*\{[\s\S]*?if\s*\(!pageNormalization\.required\)\s*return;[\s\S]*?updateUrlState\([\s\S]*?page:\s*pageNormalization\.targetPage[\s\S]*?clearRecord:\s*true/s,
  );
  assert.match(source, /const\s+pageNormalizationRef\s*=\s*useRef\(['"]['"]\)/);
  assert.match(
    source,
    /shouldApplyPageNormalization\(\s*pageNormalization\.required,\s*normalizationKey,\s*pageNormalizationRef\.current,?\s*\)/,
  );
});

test('competition database list normalization returns only schema-safe fields', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  const normalizeDatabaseResult = loadDatabaseResultNormalizer(source);
  const unsafeItem = validDatabaseListItem({
    ignored_object: { must_not_reach_jsx: true },
  });
  const envelope = validDatabaseListEnvelope({
    items: [unsafeItem],
    metadata: {
      ...validDatabaseListEnvelope().metadata,
      ignored_column: { label: { must_not_reach_jsx: true } },
    },
  });
  const normalized = normalizeDatabaseResult(envelope, 1, 20);

  assert.deepEqual(normalized, {
    items: [{
      id: 'db-1',
      _rowId: 'db-1',
      formula: 'MoS2',
      source: 'builtin',
      workflow_id: 'wf-1',
      status: 'succeeded',
      bandgap_eV: 1.78,
      energy: -22.418731,
      completed_at: '2026-08-10T09:40:00+08:00',
      data_kind: 'demo',
    }],
    total: 1,
    page: 1,
    page_size: 20,
    available_elements: ['Mo', 'S'],
    metadata: {
      formula: { label: 'Formula', kind: 'text', priority: 1 },
      energy: {
        label: 'Energy', unit: 'eV', decimals: 2, kind: 'number', priority: 1,
      },
    },
    data_kind: 'demo',
  });
  assert.notEqual(normalized.items[0], unsafeItem);
  assert.equal(getVaspColumnPresentation('formula', normalized.metadata).label, 'Formula');
  assert.equal(formatVaspValue('energy', normalized.items[0].energy, normalized.metadata).display, '-22.42');
  assert.equal('ignored_column' in normalized.metadata, false);
  assert.equal('ignored_object' in normalized.items[0], false);

  for (const malformed of [
    {},
    validDatabaseListEnvelope({ items: {} }),
    validDatabaseListEnvelope({ items: [null] }),
    validDatabaseListEnvelope({ items: [validDatabaseListItem({ status: {} })] }),
    validDatabaseListEnvelope({ items: [validDatabaseListItem({ status: 'complete' })] }),
    validDatabaseListEnvelope({ items: [validDatabaseListItem({ formula: {} })] }),
    validDatabaseListEnvelope({ items: [validDatabaseListItem({ bandgap_eV: '1.78' })] }),
    validDatabaseListEnvelope({ items: [validDatabaseListItem({ energy: Number.POSITIVE_INFINITY })] }),
    validDatabaseListEnvelope({ data_kind: 'unknown' }),
    validDatabaseListEnvelope({ items: [validDatabaseListItem({ data_kind: 'live' })] }),
    validDatabaseListEnvelope({ metadata: { formula: { label: {}, kind: 'text', priority: 1 } } }),
    validDatabaseListEnvelope({ metadata: { formula: { label: [], kind: 'text', priority: 1 } } }),
    validDatabaseListEnvelope({ metadata: { formula: { label: 'Formula', unit: {}, kind: 'text', priority: 1 } } }),
    validDatabaseListEnvelope({ metadata: { formula: { label: 'Formula', kind: 'html', priority: 1 } } }),
    validDatabaseListEnvelope({ metadata: { formula: { label: 'Formula', kind: 'text', decimals: '2', priority: 1 } } }),
    validDatabaseListEnvelope({ metadata: { formula: { label: 'Formula', kind: 'text', priority: '1' } } }),
  ]) {
    assert.equal(normalizeDatabaseResult(malformed, 1, 20), null);
  }
});

test('competition database list normalization binds response identity to the request', async () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  const normalizeDatabaseResult = loadDatabaseResultNormalizer(source);

  assert.equal(normalizeDatabaseResult(validDatabaseListEnvelope({ page: 1 }), 2, 20), null);
  assert.equal(normalizeDatabaseResult(validDatabaseListEnvelope({ page_size: 50 }), 1, 20), null);
  const provider = createDemoCompetitionDataProvider();
  const response = await provider.listDatabase({ page: 999, pageSize: 20 });
  const outOfRange = normalizeDatabaseResult(response, 999, 20);
  assert.equal(outOfRange.page, 999);
  assert.equal(outOfRange.page_size, 20);
  assert.equal(outOfRange.total, 3);
  assert.deepEqual(outOfRange.items, []);
  assert.match(source, /normalizeDatabaseResult\(listState\.data,\s*page,\s*DATABASE_PAGE_SIZE\)/);
});

test('competition database render state masks out-of-range ready frames', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  const databasePageNormalization = loadFunction(source, 'databasePageNormalization');
  const databasePageViewState = loadFunction(source, 'databasePageViewState');
  const pageNormalization = databasePageNormalization(999, 21, 20);
  const result = {
    items: [{ id: 'out-of-range', formula: 'MoS2' }],
    total: 21,
  };

  assert.deepEqual(databasePageViewState('ready', 999, pageNormalization, result), {
    pageNormalizing: true,
    listStatus: 'loading',
    showTable: false,
    records: [],
    headingPage: null,
    totalPages: 2,
    paginationDisabled: true,
  });
  assert.deepEqual(databasePageViewState(
    'ready',
    2,
    databasePageNormalization(2, 21, 20),
    result,
  ), {
    pageNormalizing: false,
    listStatus: 'ready',
    showTable: true,
    records: [{ id: 'out-of-range', formula: 'MoS2', _rowId: 'out-of-range' }],
    headingPage: 2,
    totalPages: 2,
    paginationDisabled: false,
  });
  assert.match(source, /const\s+pageView\s*=\s*databasePageViewState\(listStatus,\s*page,\s*pageNormalization,\s*result\)/);
  assert.match(source, /pageView\.pageNormalizing\s*\?\s*<span>[^<]*校正页码[^<]*<\/span>/);
  assert.match(source, /\{pageView\.showTable\s*\?\s*\([\s\S]*?records=\{pageView\.records\}/s);
  assert.match(source, /disabled=\{pageView\.paginationDisabled\s*\|\|/);
});

test('competition database request envelopes reject stale list and detail frames', async () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  const loadRequestEnvelope = loadFunction(source, 'loadRequestEnvelope');
  const selectRequestResource = loadFunction(source, 'selectRequestResource');
  const loading = { status: 'loading', data: null, error: null };
  const oldDetail = {
    status: 'ready',
    data: { requestKey: 'detail:A', value: { id: 'A' } },
    error: null,
  };
  const oldList = {
    status: 'ready',
    data: { requestKey: 'list:page=1', value: { items: [{ id: 'A' }] } },
    error: null,
  };

  assert.deepEqual(selectRequestResource(oldDetail, 'detail:B'), loading);
  assert.deepEqual(selectRequestResource(oldList, 'list:page=2'), loading);
  assert.deepEqual(selectRequestResource(oldDetail, 'detail:A'), {
    status: 'ready',
    data: { id: 'A' },
    error: null,
  });
  assert.deepEqual(selectRequestResource({
    status: 'error',
    data: null,
    error: { message: 'old', requestKey: 'detail:A' },
  }, 'detail:B'), loading);
  assert.deepEqual(selectRequestResource({
    status: 'ready',
    data: { requestKey: 'detail:B', value: null },
    error: null,
  }, 'detail:B'), {
    status: 'empty',
    data: null,
    error: null,
  });
  assert.deepEqual(await loadRequestEnvelope('detail:B', async () => ({ id: 'B' })), {
    requestKey: 'detail:B',
    value: { id: 'B' },
  });
  await assert.rejects(
    loadRequestEnvelope('detail:B', async () => {
      const error = new Error('forbidden');
      error.code = 'forbidden';
      throw error;
    }),
    (error) => error.message === 'forbidden'
      && error.code === 'forbidden'
      && error.requestKey === 'detail:B',
  );
});

test('competition database detail fails closed for malformed records and resource states', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  const normalizeDatabaseRecord = loadFunction(source, 'normalizeDatabaseRecord');
  const databaseDetailState = loadFunction(source, 'databaseDetailState');

  for (const malformed of [null, undefined, [], 'record', 42, new Date()]) {
    assert.equal(normalizeDatabaseRecord(malformed, 'db-1'), null);
  }
  const validCapabilities = {
    structure_export: true,
    band_plot: true,
    dos_plot: true,
    band_data: true,
    dos_data: true,
  };
  const validRecord = {
    id: 'db-1',
    formula: 'MoS2',
    status: 'succeeded',
    data_kind: 'demo',
    vasp_detail: { capabilities: validCapabilities },
  };
  assert.equal(normalizeDatabaseRecord(validRecord, 'db-2'), null, 'mismatched selected id');
  for (const dataKind of ['unknown', '', null, undefined]) {
    assert.equal(normalizeDatabaseRecord({ ...validRecord, data_kind: dataKind }, 'db-1'), null);
  }
  for (const status of ['unknown', 'complete', '', null, undefined]) {
    assert.equal(normalizeDatabaseRecord({ ...validRecord, status }, 'db-1'), null);
  }
  for (const capabilities of [
    null,
    [],
    {},
    { ...validCapabilities, band_plot: 'yes' },
    { ...validCapabilities, dos_data: undefined },
  ]) {
    assert.equal(normalizeDatabaseRecord({
      ...validRecord,
      vasp_detail: { capabilities },
    }, 'db-1'), null);
  }
  const normalized = normalizeDatabaseRecord(validRecord, 'db-1');
  assert.equal(normalized.id, 'db-1');
  assert.equal(normalized.status, 'succeeded');
  assert.equal(normalized.data_kind, 'demo');
  assert.deepEqual(normalized.vasp_detail.capabilities, validCapabilities);
  assert.equal(databaseDetailState({ status: 'loading' }, null), 'loading');
  assert.equal(databaseDetailState({ status: 'empty' }, null), 'empty');
  assert.equal(databaseDetailState({ status: 'forbidden' }, null), 'forbidden');
  assert.equal(databaseDetailState({ status: 'error', error: { code: 'parse-error' } }, null), 'parse-error');
  assert.equal(databaseDetailState({ status: 'error', error: { code: 'stale' } }, null), 'stale');
  assert.equal(databaseDetailState({ status: 'error', error: new Error('network') }, null), 'error');
  assert.equal(databaseDetailState({ status: 'ready' }, null), 'parse-error');
  assert.equal(databaseDetailState({ status: 'ready' }, { status: 'parse-error' }), 'parse-error');
  assert.equal(databaseDetailState({ status: 'ready' }, { status: 'stale' }), 'stale');
  assert.equal(databaseDetailState({ status: 'ready' }, { status: 'succeeded' }), 'ready');
  assert.match(source, /normalizeDatabaseRecord\(detailResource\.data,\s*selectedRecordId\)/);
});

test('competition database viewer receives only a strict copied structure', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  const { normalizeViewerStructure } = loadFunctions(source, [
    'isPlainObject',
    'normalizeViewerStructure',
  ], {
    VALID_ELEMENT_SYMBOLS: TEST_ELEMENT_SYMBOLS,
  });
  const original = {
    symbols: [' Mo ', 'S'],
    positions: [[0, 0, 10], [1.579, 0.912, 11.568]],
    cell: [[3.158, 0, 0], [-1.579, 2.735, 0], [0, 0, 20]],
    pbc: [true, true, false],
    ignored: { must_not_reach_viewer: true },
  };
  const snapshot = structuredClone(original);
  const normalized = normalizeViewerStructure(original);

  assert.deepEqual(normalized, {
    symbols: ['Mo', 'S'],
    positions: [[0, 0, 10], [1.579, 0.912, 11.568]],
    cell: [[3.158, 0, 0], [-1.579, 2.735, 0], [0, 0, 20]],
    pbc: [true, true, false],
  });
  assert.notEqual(normalized, original);
  assert.notEqual(normalized.positions, original.positions);
  assert.notEqual(normalized.positions[0], original.positions[0]);
  assert.notEqual(normalized.symbols, original.symbols);
  assert.notEqual(normalized.cell, original.cell);
  assert.notEqual(normalized.pbc, original.pbc);
  normalized.positions[0][0] = 99;
  assert.deepEqual(original, snapshot, 'normalization must not mutate or alias the provider object');
  const withoutCell = structuredClone(original);
  delete withoutCell.cell;
  assert.deepEqual(normalizeViewerStructure(withoutCell), {
    symbols: ['Mo', 'S'],
    positions: [[0, 0, 10], [1.579, 0.912, 11.568]],
    pbc: [true, true, false],
  });

  for (const malformed of [
    { symbols: ['Mo'], positions: [[null, false, '']], pbc: [true, true, false] },
    { symbols: ['Xx'], positions: [[0, 0, 0]], pbc: [true, true, false] },
    {
      symbols: ['Mo'],
      positions: [[0, 0, 0]],
      cell: [[1, 0, 0], [0, 1, 0], [0, 0]],
      pbc: [true, true, false],
    },
    { symbols: ['Mo'], positions: [[0, 0, 0]], pbc: [true, 1, false] },
    { symbols: ['Mo'], positions: [[0, 0, 0, 1]], pbc: [true, true, false] },
  ]) {
    assert.equal(normalizeViewerStructure(malformed), null);
  }
  assert.match(source, /const\s+viewerStructure\s*=\s*normalizeViewerStructure\(record\.vasp_detail\?\.structure\)/);
  assert.match(source, /<VaspStructureViewer\s+structure=\{viewerStructure\}\s*\/>/);
  assert.doesNotMatch(source, /<VaspStructureViewer\s+structure=\{structure\}\s*\/>/);
});

test('competition database inspector exposes required evidence without success inference', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  for (const label of [
    '成分',
    '源工作流',
    '状态',
    '带隙',
    '总能',
    '完成时间',
    '最新演示 Job ID',
    'BAND 可用性',
    'DOS 可用性',
    '证据包状态',
    '来源未验证',
  ]) {
    assert.match(source, new RegExp(label));
  }
  assert.match(source, /record\.artifacts\.includes\(['"]evidence-bundle['"]\)/);
  assert.doesNotMatch(source, /record\.status\s*===\s*['"]succeeded['"]\s*\?\s*['"]真实数据['"]/);

  const styles = read('../src/pages/competition/CompetitionPages.css');
  assert.match(styles, /\.competition-database-workspace\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*[^)]+\)\s+minmax\(320px,/s);
  assert.match(styles, /@media\s*\(max-width:\s*1024px\)\s*{[\s\S]*?\.competition-database-workspace\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/);
  assert.doesNotMatch(styles, /letter-spacing:\s*-/);
});

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
    'mos2_v1',
    'ENCUT',
    'k-point',
    'convergence',
    'P107-RTX5090',
    '最大 4 GPU / 16 CPU',
    '每步独立一个 Job / attempt 证据记录',
    '参数',
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
  assert.match(source, /source_kind:\s*sourceKind/);
  assert.match(source, /template_version:\s*['"]mos2_v1['"]/);
  assert.match(source, /steps:\s*\[['"]relax['"],\s*['"]scf['"],\s*['"]band['"],\s*['"]dos['"]\]/);
  assert.match(source, /模板 mos2_v1 · 输入 SHA-256：保存草稿后由服务端生成/);
  assert.match(source, /<VaspStructureViewer\s+structure=\{DEMO_STRUCTURE\}\s*\/>/);
  assert.match(source, /<label\s+htmlFor=['"]competition-structure-file['"]/);
  assert.match(source, /<input[^>]*id=['"]competition-structure-file['"][^>]*type=['"]file['"][^>]*onChange=/s);
  assert.doesNotMatch(source, /FileReader|file\.type|FormData/);
  assert.equal(source.match(/provider\.uploadStructure\(/g)?.length, 1);
  assert.equal(source.match(/provider\.saveDraft\(/g)?.length, 1);
  assert.equal(source.match(/provider\.submitWorkflow\(/g)?.length, 1);
  assert.match(source, /aria-live=['"]polite['"]/);
  assert.match(source, /结构已由服务端解析 · 上传 ID/);
  assert.match(source, /已校验，等待 Slurm 适配器/);
  assert.doesNotMatch(source, /已排队|运行中|Job ID/);
  assert.doesNotMatch(source, /alert\s*\([^)]*成功|toast\s*\([^)]*成功/i);
  assert.doesNotMatch(source, /\b(?:add|delete|drag|reorder)(?:Step)?\b|添加|删除|拖拽|重排/i);
  assert.doesNotMatch(source, /Agent|Machine Learning|\bML\b|Quantum ESPRESSO|\bQE\b/);
  assert.doesNotMatch(source, /card/i);
});

test('new calculation upload source shows only server-derived structure summary', () => {
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
  for (const token of ['structureUpload', 'summary', 'originalFileName']) {
    assert.match(uploadSummary, new RegExp(token));
  }
  assert.doesNotMatch(uploadSummary, /MoS2|DEMO_STRUCTURE|3\.158|20\.000|内置结构/);
});

test('new calculation live upload and writes are single-flight and fail closed', async () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const { isBusinessWriteAllowed, runLockedWrite } = loadFunctions(source, [
    'isBusinessWriteAllowed',
    'runLockedWrite',
  ], {
    canWriteCompetitionData,
  });

  assert.equal(isBusinessWriteAllowed('live', { role: 'operator' }), true);
  assert.equal(isBusinessWriteAllowed('demo', { role: 'operator' }), false);
  assert.equal(isBusinessWriteAllowed('live', { role: 'viewer' }), false);

  let release;
  let writeCount = 0;
  const pending = new Promise((resolve) => { release = resolve; });
  const lock = { current: false };
  const first = runLockedWrite(lock, true, async () => {
    writeCount += 1;
    await pending;
    return { id: 'server-id' };
  });
  const duplicate = await runLockedWrite(lock, true, async () => {
    writeCount += 1;
  });
  assert.equal(duplicate, null);
  assert.equal(writeCount, 1);
  release();
  assert.deepEqual(await first, { id: 'server-id' });
  assert.equal(lock.current, false);
  assert.equal(await runLockedWrite(lock, false, async () => { writeCount += 1; }), null);
  assert.equal(writeCount, 1);
});

test('new calculation draft payload uses the fixed template and server upload id', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const buildDraftPayload = loadFunction(source, 'buildDraftPayload');
  const parameters = { relax: { ENCUT: 520 }, dos: { NEDOS: 3000 } };

  assert.deepEqual(buildDraftPayload({ sourceKind: 'builtin', parameters }), {
    template_version: 'mos2_v1',
    source_kind: 'builtin',
    steps: ['relax', 'scf', 'band', 'dos'],
    parameters,
  });
  assert.deepEqual(buildDraftPayload({
    sourceKind: 'upload',
    structureUpload: { id: 'upload-from-server', summary: { formula: 'MoS2' } },
    parameters,
  }), {
    template_version: 'mos2_v1',
    source_kind: 'upload',
    steps: ['relax', 'scf', 'band', 'dos'],
    parameters,
    structure_upload_id: 'upload-from-server',
  });
  assert.throws(
    () => buildDraftPayload({ sourceKind: 'upload', structureUpload: null, parameters }),
    /先上传并通过服务端解析/,
  );
});

test('new calculation source file and parameter changes invalidate stale server state', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const { invalidateServerState, shouldClearConsumedUpload } = loadFunctions(source, [
    'invalidateServerState',
    'shouldClearConsumedUpload',
  ]);
  const stagedUpload = {
    structureUpload: { id: 'upload-staged' },
    workflow: null,
    confirmation: null,
    error: '',
  };
  const prior = {
    structureUpload: { id: 'upload-old' },
    workflow: { id: 'workflow-old', input_sha256: 'old-sha' },
    confirmation: { id: 'workflow-old', status: 'validated' },
    error: 'old error',
  };

  assert.deepEqual(invalidateServerState(prior, { clearUpload: true }), {
    structureUpload: null,
    workflow: null,
    confirmation: null,
    error: '',
  });
  assert.deepEqual(invalidateServerState(prior, { clearUpload: false }), {
    structureUpload: prior.structureUpload,
    workflow: null,
    confirmation: null,
    error: '',
  });
  assert.equal(shouldClearConsumedUpload('upload', stagedUpload), false);
  assert.equal(shouldClearConsumedUpload('upload', prior), true);
  assert.equal(shouldClearConsumedUpload('builtin', prior), false);
  assert.deepEqual(invalidateServerState(stagedUpload, {
    clearUpload: shouldClearConsumedUpload('upload', stagedUpload),
  }), stagedUpload);
  assert.deepEqual(invalidateServerState(prior, {
    clearUpload: shouldClearConsumedUpload('upload', prior),
  }), {
    structureUpload: null,
    workflow: null,
    confirmation: null,
    error: '',
  });
  assert.match(source, /handleSourceKindChange[\s\S]*?clearUpload:\s*true/);
  assert.match(source, /handleStructureFileChange[\s\S]*?clearUpload:\s*true/);
  assert.match(source, /handleParameterChange[\s\S]*?shouldClearConsumedUpload\(sourceKind,\s*serverState\)/);
  assert.match(source, /handleParameterChange[\s\S]*?setOriginalFileName\(['"]['"]\)/);
  assert.match(source, /handleParameterChange[\s\S]*?setFileInputKey/);
});

test('new calculation live status announces pending writes before saved objects', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const describeCommandStatus = loadFunction(source, 'describeCommandStatus');
  const serverState = {
    structureUpload: { id: 'upload-server' },
    workflow: { id: 'workflow-server', status: 'draft', input_sha256: 'abc123' },
    confirmation: { id: 'workflow-server', status: 'validated' },
    error: '',
  };
  const common = { sourceKind: 'upload', serverState };

  assert.equal(describeCommandStatus({ ...common, uploadPending: true }), '正在上传并等待服务端解析结构');
  assert.equal(describeCommandStatus({ ...common, savePending: true }), '正在保存草稿');
  assert.equal(describeCommandStatus({ ...common, confirmPending: true }), '正在执行提交前校验');
  assert.equal(
    describeCommandStatus(common),
    '已校验，等待 Slurm 适配器 · workflow-server',
  );
  assert.match(source, /<span\s+aria-live=['"]polite['"]>\s*\{describeCommandStatus\(/s);
});

test('new calculation locks every input mutation for pending and same-tick writes', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const isInputMutationLocked = loadFunction(source, 'isInputMutationLocked');

  assert.equal(isInputMutationLocked({}), false);
  for (const key of [
    'uploadPending',
    'savePending',
    'confirmPending',
    'uploadLocked',
    'saveLocked',
    'confirmLocked',
  ]) {
    assert.equal(
      isInputMutationLocked({ [key]: true }),
      true,
      `${key} must lock source, file, and parameter changes`,
    );
  }

  assert.match(source, /const\s+inputMutationLocked\s*=\s*isInputMutationLocked\(/);
  assert.match(source, /function\s+inputMutationLockedNow\(\)[\s\S]*?uploadLocked:\s*uploadLock\.current[\s\S]*?saveLocked:\s*saveLock\.current[\s\S]*?confirmLocked:\s*confirmLock\.current/s);
  for (const handler of [
    'handleSourceKindChange',
    'handleStructureFileChange',
    'handleClearStructureFile',
    'handleParameterChange',
  ]) {
    assert.match(
      source,
      new RegExp(`function\\s+${handler}[\\s\\S]*?inputMutationLockedNow\\(\\)[\\s\\S]*?return;`),
    );
  }
  assert.ok(
    (source.match(/disabled=\{readOnly\s*\|\|\s*inputMutationLocked\}/g) || []).length >= 4,
    'source buttons, clear control, and parameter inputs must share the lock',
  );
  assert.match(source, /disabled=\{readOnly\s*\|\|\s*inputMutationLocked\s*\|\|\s*uploadPending\}/);
});

test('new calculation fails closed after uncertain save and confirmation results', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const { failClosedAfterUncertainWrite } = loadFunctions(source, [
    'invalidateServerState',
    'failClosedAfterUncertainWrite',
  ]);
  const uploaded = {
    structureUpload: { id: 'upload-consumed-or-unknown' },
    workflow: { id: 'workflow-old', status: 'draft' },
    confirmation: { id: 'workflow-old', status: 'validated' },
    error: '',
  };

  assert.deepEqual(
    failClosedAfterUncertainWrite('upload', uploaded, '服务端结果未知'),
    {
      serverState: {
        structureUpload: null,
        workflow: null,
        confirmation: null,
        error: '服务端结果未知',
      },
      clearFile: true,
    },
  );
  assert.deepEqual(
    failClosedAfterUncertainWrite('builtin', uploaded, '保存失败'),
    {
      serverState: {
        structureUpload: uploaded.structureUpload,
        workflow: null,
        confirmation: null,
        error: '保存失败',
      },
      clearFile: false,
    },
  );

  for (const handler of ['handleSaveDraft', 'handleSubmitWorkflow']) {
    const declaration = parse(source, { sourceType: 'module', plugins: ['jsx'] }).program.body
      .find((node) => node.type === 'ExportDefaultDeclaration')
      .declaration.body.body
      .find((node) => node.type === 'FunctionDeclaration' && node.id.name === handler);
    const handlerSource = source.slice(declaration.start, declaration.end);
    assert.match(handlerSource, /catch\s*\(error\)[\s\S]*?failClosedAfterUncertainWrite\(/);
    assert.match(handlerSource, /failure\.clearFile[\s\S]*?setOriginalFileName\(['"]['"]\)[\s\S]*?setFileInputKey/);
    assert.match(handlerSource, /setServerState\(failure\.serverState\)/);
    assert.doesNotMatch(handlerSource, /confirmation:\s*null[\s\S]*?\.\.\.current/);
  }
});

test('new calculation confirms only the latest saved workflow id', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');

  assert.match(source, /const\s+canSave\s*=/);
  assert.match(source, /const\s+canConfirm\s*=\s*canWrite[\s\S]*?Boolean\(serverState\.workflow\?\.id\)[\s\S]*?!serverState\.confirmation;/);
  assert.match(source, /provider\.submitWorkflow\(serverState\.workflow\.id\)/);
  assert.match(source, /setServerState\(\(current\)\s*=>\s*\(\{[\s\S]*?workflow:\s*result/s);
  assert.match(source, /disabled=\{!canSave\s*\|\|\s*savePending\}/);
  assert.match(source, /disabled=\{!canConfirm\s*\|\|\s*confirmPending\}/);
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
    /function\s+handleSourceKindChange\(nextSourceKind\)[\s\S]*?setSourceKind\(nextSourceKind\);[\s\S]*?invalidateServerState/s,
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
  assert.match(source, /@media\s*\(max-width:\s*520px\)[\s\S]*?\.competition-parameter-fields\s*{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s);
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
  assert.match(source, /const\s+workflowSteps\s*=\s*Array\.isArray\(workflow\?\.steps\)\s*\?\s*workflow\.steps\s*:\s*\[\];/);
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
  assert.match(
    source,
    /const\s+workflow\s*=\s*detailState\.status\s*===\s*['"]ready['"]\s*\?\s*detailState\.workflow\s*:\s*null;/,
  );
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

test('new calculation start is separate, single-flight, and fails closed', async () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  const {
    executeStartWorkflow,
    isValidStartOutcome,
  } = loadFunctions(source, ['executeStartWorkflow', 'isValidStartOutcome'], {
    canWriteCompetitionData,
  });
  const calls = [];
  const base = {
    mode: 'live',
    user: { role: 'operator' },
    workflowId: 'wf-1',
    pending: false,
    write: async () => calls.push('start'),
  };

  for (const invalid of [
    { ...base, mode: 'demo' },
    { ...base, user: { role: 'viewer' } },
    { ...base, workflowId: '' },
    { ...base, workflowId: ' wf-1 ' },
    { ...base, pending: true },
    { ...base, write: null },
  ]) {
    assert.equal(await executeStartWorkflow(invalid), false);
  }
  assert.deepEqual(calls, []);
  assert.equal(await executeStartWorkflow(base), true);
  assert.deepEqual(calls, ['start']);

  const attemptId = 'b1f1d2a8-7689-4dd4-802c-ff17c3eecb65';
  assert.equal(isValidStartOutcome({
    workflow_id: 'wf-1', attempt_id: attemptId, step_key: 'relax', status: 'queued',
  }, 'wf-1'), true);
  for (const malformed of [
    null,
    {},
    { workflow_id: 'wf-other', attempt_id: attemptId, step_key: 'relax', status: 'queued' },
    { workflow_id: 'wf-1', attempt_id: '/home/private', step_key: 'relax', status: 'queued' },
    { workflow_id: 'wf-1', attempt_id: attemptId, step_key: 'scf', status: 'queued' },
    { workflow_id: 'wf-1', attempt_id: attemptId, step_key: 'relax', status: 'unknown' },
  ]) {
    assert.equal(isValidStartOutcome(malformed, 'wf-1'), false);
  }

  assert.match(source, /useNavigate\(\)/);
  assert.match(source, /const\s+\[startPending,\s*setStartPending\]\s*=\s*useState\(false\);/);
  assert.match(source, /const\s+startLock\s*=\s*useRef\(false\);/);
  assert.match(source, /provider\.startWorkflow\(serverState\.confirmation\.id\)/);
  assert.match(source, /navigate\(`\/dashboard\/workflows\/\$\{encodeURIComponent\([^}]+\)\}`\)/);
  assert.match(source, /serverState\.confirmation\?\.status\s*===\s*['"]validated['"]\s*\?/);
  assert.match(source, /['"]开始计算['"]/);
  assert.match(source, /startPending\s*\?\s*['"]启动中['"]\s*:\s*['"]开始计算['"]/);
  assert.match(source, /catch\s*\(error\)[\s\S]*?setStartUncertain\(true\)/s);
});

test('new draft invalidation clears prior start uncertainty', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');

  assert.match(
    source,
    /function\s+clearPersistedState\([^)]*\)\s*\{[\s\S]*?setStartUncertain\(false\)[\s\S]*?invalidateServerState/s,
  );
  assert.match(
    source,
    /async\s+function\s+handleStructureFileChange\([^)]*\)\s*\{[\s\S]*?setStartUncertain\(false\)[\s\S]*?invalidateServerState[\s\S]*?if\s*\(!file\)\s*return/s,
  );
});

test('workflow polling runs only for live active scientific states', () => {
  const contextSource = read('../src/features/competition/CompetitionDataContext.jsx');
  const detailSource = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const shouldPollWorkflow = loadFunction(detailSource, 'shouldPollWorkflow');

  for (const status of [
    'preparing', 'submitting', 'queued', 'running', 'awaiting_acceptance', 'cancelling',
  ]) {
    assert.equal(shouldPollWorkflow('live', status), true, status);
    assert.equal(shouldPollWorkflow('demo', status), false, status);
  }
  for (const status of [
    'validated', 'succeeded', 'failed', 'scientific_failed', 'blocked', 'cancelled', null,
  ]) {
    assert.equal(shouldPollWorkflow('live', status), false, String(status));
  }

  assert.match(contextSource, /export\s+function\s+useCompetitionPollingResource\(/);
  assert.match(contextSource, /useCompetitionResource\(\s*useCallback\(/);
  assert.match(contextSource, /globalThis\.setInterval\(/);
  assert.match(contextSource, /return\s*\(\)\s*=>\s*globalThis\.clearInterval\(timer\)/);
  assert.match(contextSource, /let\s+active\s*=\s*true/);
  assert.match(contextSource, /if\s*\(!active\)\s*return/g);
  assert.match(detailSource, /useCompetitionPollingResource\(loadWorkflow,/);
  assert.match(detailSource, /shouldPollWorkflow\(mode,/);
});

test('workflow scientific failed, blocked, and awaiting acceptance remain distinct', () => {
  const source = read('../src/features/competition/components/WorkflowTimeline.jsx');
  const detailSource = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const describeScientificState = loadFunction(source, 'describeScientificState');
  const findRetryableFailedStep = loadFunction(detailSource, 'findRetryableFailedStep');

  assert.equal(
    describeScientificState({ status: 'awaiting_acceptance', accepted: null }),
    '等待科学验收',
  );
  assert.equal(
    describeScientificState({
      status: 'scientific_failed', accepted: false, reason: 'electronic_not_converged',
    }),
    '科学验收失败 · electronic_not_converged',
  );
  assert.equal(
    describeScientificState({ status: 'blocked', accepted: false }),
    '依赖失败，未启动',
  );
  assert.equal(
    describeScientificState({ status: 'running', accepted: false }),
    '尚未验收',
  );
  assert.equal(
    describeScientificState({ status: 'succeeded', accepted: false }),
    '科学验收失败',
  );
  assert.equal(
    describeScientificState({ status: 'succeeded', accepted: true }),
    '科学验收通过',
  );
  const scientificFailure = { key: 'scf', status: 'scientific_failed' };
  assert.equal(findRetryableFailedStep([scientificFailure]), scientificFailure);
  assert.match(source, /elapsed_wall_seconds/);
  assert.match(source, /process_tree_peak_rss_kbytes/);
  assert.match(source, /sha256/);
});

test('workflow evidence hides unexpected absolute attempt directories', () => {
  const source = read('../src/features/competition/components/WorkflowTimeline.jsx');
  const displayAttemptDirectory = loadFunction(source, 'displayAttemptDirectory');

  assert.equal(displayAttemptDirectory('attempt-1/scf'), 'attempt-1/scf');
  for (const unsafe of [
    null,
    '',
    ' attempt-1/scf ',
    '/home/private/attempt',
    '\\server\private\attempt',
    'C:\\private\\attempt',
    '../private/attempt',
    'attempts/../../private',
  ]) {
    assert.equal(displayAttemptDirectory(unsafe), '-');
  }

  assert.match(source, /const\s+attemptDirectory\s*=\s*displayAttemptDirectory\(step\.attempt_dir\);/);
  assert.match(source, /title=\{attemptDirectory\s*===\s*['"]-['"]\s*\?\s*undefined\s*:\s*attemptDirectory\}/);
});

test('workflow log selection uses only safe latest attempt identifiers', () => {
  const source = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  const {
    isSafeAttemptIdentifier,
    selectLatestAttemptStep,
    normalizeAttemptLogState,
  } = loadFunctions(source, [
    'isSafeAttemptIdentifier',
    'selectLatestAttemptStep',
    'normalizeAttemptLogState',
  ]);
  const relaxAttempt = 'b1f1d2a8-7689-4dd4-802c-ff17c3eecb65';
  const scfAttempt = '09dfc066-82df-4727-ac95-54aa2be24231';
  const steps = [
    { key: 'relax', attempt: 1, attempt_id: relaxAttempt, job_id: '41001' },
    { key: 'scf', attempt: 2, attempt_id: scfAttempt, job_id: '41002' },
    { key: 'band', attempt: 0, attempt_id: null },
  ];

  assert.equal(isSafeAttemptIdentifier(relaxAttempt), true);
  for (const unsafe of [
    null, '', 'attempt-1', '/home/private', 'C:\\private\\attempt', scfAttempt.toUpperCase(),
  ]) {
    assert.equal(isSafeAttemptIdentifier(unsafe), false);
  }
  assert.equal(selectLatestAttemptStep(steps, 'relax'), steps[0]);
  assert.equal(selectLatestAttemptStep(steps, 'band'), steps[1]);
  assert.equal(selectLatestAttemptStep(steps, ''), steps[1]);
  assert.equal(selectLatestAttemptStep([
    ...steps,
    { key: 'dos', attempt: 99, attempt_id: '/home/private', job_id: '99999' },
  ], 'dos'), steps[1]);

  assert.deepEqual(normalizeAttemptLogState(
    { status: 'loading', data: null, error: null }, 'stdout', scfAttempt,
  ), { status: 'loading', message: '日志加载中', content: '' });
  assert.deepEqual(normalizeAttemptLogState(
    { status: 'ready', data: { stream: 'stdout', content: '' }, error: null },
    'stdout', scfAttempt,
  ), { status: 'empty', message: '当前日志为空', content: '' });
  assert.deepEqual(normalizeAttemptLogState(
    { status: 'ready', data: { stream: 'stdout', content: 'bounded tail\n' }, error: null },
    'stdout', scfAttempt,
  ), { status: 'ready', message: '', content: 'bounded tail\n' });
  for (const resource of [
    { status: 'error', data: null, error: new Error('/home/private/log') },
    { status: 'ready', data: { stream: 'stderr', content: 'wrong stream' }, error: null },
    { status: 'ready', data: { stream: 'stdout', content: {} }, error: null },
  ]) {
    assert.deepEqual(
      normalizeAttemptLogState(resource, 'stdout', scfAttempt),
      { status: 'error', message: '日志暂时不可用', content: '' },
    );
  }
  assert.deepEqual(normalizeAttemptLogState(
    { status: 'ready', data: null, error: null }, 'stdout', null,
  ), { status: 'empty', message: '当前步骤暂无日志', content: '' });

  assert.match(source, /provider\.getAttemptLog\(workflow\.id,\s*selectedAttemptId,\s*logStream\)/);
  assert.match(source, /['"]stdout['"][\s\S]*?['"]stderr['"]/);
  assert.match(source, /<pre\s+className=['"]competition-result-log['"]>/);
  assert.doesNotMatch(source, /attempt_dir\.(?:split|match)/);

  const boundedSources = [
    source,
    read('../src/features/competition/data/apiCompetitionDataProvider.js'),
    read('../src/features/competition/data/demoCompetitionDataProvider.js'),
    read('../src/features/competition/components/WorkflowTimeline.jsx'),
  ].join('\n');
  assert.doesNotMatch(boundedSources, /sbatch|squeue|sacct|scancel|vasp_std|\/home\//i);
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
