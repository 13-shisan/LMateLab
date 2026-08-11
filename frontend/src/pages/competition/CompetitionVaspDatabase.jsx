import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Search } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';

import {
  useCompetitionData,
  useCompetitionResource,
} from '../../features/competition/CompetitionDataContext';
import {
  CompetitionState,
  DemoDataBanner,
  StatusBadge,
} from '../../features/competition/components/CompetitionState';
import PeriodicTableFilter from '../db/PeriodicTableFilter';
import { PERIODIC_TABLE_ELEMENTS } from '../db/periodicTableElements';
import VaspRecordTable from '../db/VaspRecordTable';
import VaspStructureViewer from '../db/vasp-detail/VaspStructureViewer';
import '../db/vasp-detail/VaspTaskDetail.css';
import './CompetitionPages.css';

const DATABASE_COLUMNS = Object.freeze(['formula', 'source', 'workflow_id', 'status', 'bandgap_eV', 'energy', 'completed_at']);
const DATABASE_PAGE_SIZE = 20;
const VALID_ELEMENT_SYMBOLS = new Set(PERIODIC_TABLE_ELEMENTS.map((element) => element.symbol));
const EMPTY_DATABASE_RESULT = Object.freeze({
  items: Object.freeze([]),
  total: 0,
  page: 1,
  page_size: DATABASE_PAGE_SIZE,
  available_elements: Object.freeze([]),
  metadata: Object.freeze({}),
});

function readDatabaseUrlState(searchParams) {
  const rawPage = Number(searchParams.get('page'));
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 && rawPage <= 100000
    ? rawPage
    : 1;
  const requestedMode = searchParams.get('element_mode');
  const elementMode = requestedMode === 'only' ? 'only' : 'at_least';
  const selectedElements = [...new Set(
    (searchParams.get('elements') || '')
      .split(',')
      .map((symbol) => symbol.trim())
      .filter((symbol) => VALID_ELEMENT_SYMBOLS.has(symbol)),
  )];

  return {
    query: searchParams.get('q') || '',
    selectedElements,
    elementMode,
    page,
    selectedRecordId: (searchParams.get('record') || '').trim(),
  };
}

function writeDatabaseUrlState({
  query,
  selectedElements,
  elementMode,
  page,
  selectedRecordId,
}) {
  const params = new URLSearchParams();
  if (query) params.set('q', query);
  if (selectedElements.length > 0) params.set('elements', selectedElements.join(','));
  params.set('element_mode', elementMode === 'only' ? 'only' : 'at_least');
  params.set('page', String(Number.isSafeInteger(page) && page > 0 ? page : 1));
  if (selectedRecordId) params.set('record', selectedRecordId);
  return params;
}

function databasePageNormalization(page, total, pageSize) {
  const currentPage = Number.isSafeInteger(page) && page > 0 ? page : 1;
  const safeTotal = Number.isSafeInteger(total) && total > 0 ? total : 0;
  const safePageSize = Number.isSafeInteger(pageSize) && pageSize > 0 ? pageSize : 1;
  const totalPages = Math.max(1, Math.ceil(safeTotal / safePageSize));
  const targetPage = Math.min(currentPage, totalPages);
  return {
    required: targetPage !== page,
    targetPage,
    totalPages,
  };
}

function databasePageViewState(listStatus, page, pageNormalization, result) {
  const pageNormalizing = listStatus === 'ready' && pageNormalization.required;
  return {
    pageNormalizing,
    listStatus: pageNormalizing ? 'loading' : listStatus,
    showTable: !pageNormalizing && (listStatus === 'ready' || listStatus === 'loading'),
    records: pageNormalizing
      ? []
      : result.items.map((item) => ({ ...item, _rowId: item.id })),
    headingPage: pageNormalizing ? null : page,
    totalPages: pageNormalization.totalPages,
    paginationDisabled: pageNormalizing || listStatus !== 'ready',
  };
}

function shouldApplyPageNormalization(required, normalizationKey, lastNormalizationKey) {
  return required && normalizationKey !== lastNormalizationKey;
}

function isPlainObject(value) {
  if (value === null || typeof value !== 'object') return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function safeText(value) {
  if (typeof value === 'string') return value;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return '';
}

async function loadRequestEnvelope(requestKey, loader) {
  try {
    return {
      requestKey,
      value: await loader(),
    };
  } catch (error) {
    const requestError = new Error(String(error?.message || error));
    requestError.name = error?.name || 'Error';
    requestError.code = error?.code;
    requestError.status = error?.status;
    requestError.details = error?.details;
    requestError.requestKey = requestKey;
    requestError.cause = error;
    throw requestError;
  }
}

function selectRequestResource(resource, requestKey) {
  const loading = { status: 'loading', data: null, error: null };
  if (resource?.status === 'ready') {
    const envelope = resource.data;
    if (envelope === null || typeof envelope !== 'object' || Array.isArray(envelope)) {
      return loading;
    }
    if (envelope.requestKey !== requestKey || !Object.hasOwn(envelope, 'value')) {
      return loading;
    }
    return {
      status: envelope.value === null || envelope.value === undefined ? 'empty' : 'ready',
      data: envelope.value ?? null,
      error: null,
    };
  }
  if (resource?.status === 'error' || resource?.status === 'forbidden') {
    if (resource.error?.requestKey !== requestKey) return loading;
    return { status: resource.status, data: null, error: resource.error };
  }
  return loading;
}

function normalizeDatabaseRecord(value, selectedRecordId) {
  const isRecordObject = (candidate) => {
    if (candidate === null || typeof candidate !== 'object' || Array.isArray(candidate)) return false;
    const prototype = Object.getPrototypeOf(candidate);
    return prototype === Object.prototype || prototype === null;
  };
  if (!isRecordObject(value)) return null;

  const id = typeof value.id === 'string'
    ? value.id
    : (typeof value.id === 'number' && Number.isFinite(value.id) ? String(value.id) : '');
  if (!id || id !== String(selectedRecordId || '')) return null;
  const knownStatuses = [
    'succeeded',
    'running',
    'waiting',
    'queued',
    'blocked',
    'failed',
    'stale',
    'parse-error',
    'render-error',
  ];
  if (!knownStatuses.includes(value.status)) return null;
  if (value.data_kind !== 'demo' && value.data_kind !== 'live') return null;
  if (!isRecordObject(value.vasp_detail)) return null;
  const capabilities = value.vasp_detail.capabilities;
  if (!isRecordObject(capabilities)) return null;
  const capabilityKeys = [
    'structure_export',
    'band_plot',
    'dos_plot',
    'band_data',
    'dos_data',
  ];
  if (!capabilityKeys.every((key) => typeof capabilities[key] === 'boolean')) return null;

  return {
    id,
    formula: typeof value.formula === 'string' ? value.formula : '',
    elements: Array.isArray(value.elements)
      ? [...new Set(value.elements.filter((element) => typeof element === 'string' && element))]
      : [],
    source: typeof value.source === 'string' ? value.source : '',
    workflow_id: typeof value.workflow_id === 'string' ? value.workflow_id : '',
    status: value.status,
    bandgap_eV: value.bandgap_eV !== null
      && value.bandgap_eV !== undefined
      && value.bandgap_eV !== ''
      && Number.isFinite(Number(value.bandgap_eV))
      ? Number(value.bandgap_eV)
      : null,
    energy: value.energy !== null
      && value.energy !== undefined
      && value.energy !== ''
      && Number.isFinite(Number(value.energy))
      ? Number(value.energy)
      : null,
    completed_at: typeof value.completed_at === 'string' ? value.completed_at : '',
    latest_job_id: typeof value.latest_job_id === 'string' ? value.latest_job_id : '',
    data_kind: value.data_kind,
    vasp_detail: value.vasp_detail,
    artifacts: Array.isArray(value.artifacts)
      ? value.artifacts.filter((artifact) => typeof artifact === 'string')
      : [],
  };
}

function normalizeDatabaseResult(value) {
  if (!isPlainObject(value)) return null;
  const items = Array.isArray(value.items)
    ? value.items.filter(isPlainObject).map((item) => ({
      ...item,
      _rowId: item.id,
    }))
    : [];
  const availableElements = Array.isArray(value.available_elements)
    ? [...new Set(value.available_elements.filter((symbol) => VALID_ELEMENT_SYMBOLS.has(symbol)))]
    : [];
  const total = Number.isSafeInteger(Number(value.total)) && Number(value.total) >= 0
    ? Number(value.total)
    : items.length;

  return {
    items,
    total,
    page: Number.isSafeInteger(Number(value.page)) && Number(value.page) > 0
      ? Number(value.page)
      : 1,
    page_size: Number.isSafeInteger(Number(value.page_size)) && Number(value.page_size) > 0
      ? Number(value.page_size)
      : DATABASE_PAGE_SIZE,
    available_elements: availableElements,
    metadata: isPlainObject(value.metadata) ? value.metadata : {},
  };
}

function databaseDetailState(resource, record) {
  if (resource?.status === 'error') {
    if (resource.error?.code === 'parse-error') return 'parse-error';
    if (resource.error?.code === 'stale') return 'stale';
    if (resource.error?.code === 'forbidden') return 'forbidden';
    return 'error';
  }
  if (resource?.status !== 'ready') return resource?.status || 'error';
  if (!record) return 'parse-error';
  if (record.status === 'parse-error') return 'parse-error';
  if (record.status === 'stale') return 'stale';
  return 'ready';
}

function databaseRecordUrl(item) {
  const recordId = safeText(item?.id).trim();
  return recordId
    ? `/dashboard/database/vasp?record=${encodeURIComponent(recordId)}`
    : null;
}

function renderDatabaseCell(column, item) {
  return column === 'status' ? <StatusBadge status={item.status} /> : undefined;
}

function isRenderableStructure(structure) {
  if (!isPlainObject(structure)) return false;
  if (!Array.isArray(structure.positions) || structure.positions.length === 0) return false;
  if (!Array.isArray(structure.symbols) || structure.symbols.length !== structure.positions.length) {
    return false;
  }
  return structure.positions.every((position) => (
    Array.isArray(position)
    && position.length >= 3
    && position.slice(0, 3).every((coordinate) => Number.isFinite(Number(coordinate)))
  )) && structure.symbols.every((symbol) => typeof symbol === 'string' && symbol.length > 0);
}

function capabilityState(record, capabilityNames) {
  const capabilities = record.vasp_detail?.capabilities;
  if (!isPlainObject(capabilities)) return '未声明';
  if (capabilityNames.some((name) => capabilities[name] === true)) return '可用';
  if (capabilityNames.every((name) => capabilities[name] === false)) return '不可用';
  return '未声明';
}

function provenanceLabel(dataKind) {
  if (dataKind === 'demo') return '演示数据';
  if (dataKind === 'live') return '真实数据';
  return '来源未验证';
}

function displayNumber(value, unit) {
  return value === null ? '-' : `${value}${unit ? ` ${unit}` : ''}`;
}

function DatabaseInspector({ status, error, record }) {
  const showRecord = record !== null && ['ready', 'stale', 'parse-error'].includes(status);
  if (!showRecord) {
    return (
      <aside className="competition-database-inspector" aria-labelledby="competition-database-inspector-title">
        <div className="competition-database-inspector-heading">
          <h2 id="competition-database-inspector-title">记录详情</h2>
        </div>
        <CompetitionState status={status} message={error?.message} />
      </aside>
    );
  }

  const structure = record.vasp_detail?.structure;
  const composition = record.elements.length > 0 ? record.elements.join(' / ') : record.formula;
  const latestJobLabel = record.data_kind === 'demo' ? '最新演示 Job ID' : '最新 Job ID';

  return (
    <aside className="competition-database-inspector" aria-labelledby="competition-database-inspector-title">
      <div className="competition-database-inspector-heading">
        <div>
          <h2 id="competition-database-inspector-title">记录详情</h2>
          <p>{provenanceLabel(record.data_kind)}</p>
        </div>
        <StatusBadge status={record.status} />
      </div>

      {status !== 'ready' ? <CompetitionState status={status} message={error?.message} /> : null}

      <dl className="competition-database-detail-fields">
        <div><dt>成分</dt><dd>{composition || '-'}</dd></div>
        <div><dt>源工作流</dt><dd>{record.source || '-'} / {record.workflow_id || '-'}</dd></div>
        <div><dt>状态</dt><dd><StatusBadge status={record.status} /></dd></div>
        <div><dt>带隙</dt><dd>{displayNumber(record.bandgap_eV, 'eV')}</dd></div>
        <div><dt>总能</dt><dd>{displayNumber(record.energy, 'eV')}</dd></div>
        <div><dt>完成时间</dt><dd>{record.completed_at || '-'}</dd></div>
        <div><dt>{latestJobLabel}</dt><dd>{record.latest_job_id || '-'}</dd></div>
        <div><dt>BAND 可用性</dt><dd>{capabilityState(record, ['band_plot', 'band_data'])}</dd></div>
        <div><dt>DOS 可用性</dt><dd>{capabilityState(record, ['dos_plot', 'dos_data'])}</dd></div>
        <div><dt>证据包状态</dt><dd>{record.artifacts.includes('evidence-bundle') ? '可用' : '未声明'}</dd></div>
      </dl>

      <section className="competition-database-structure" aria-label="结构查看器">
        <h3>结构</h3>
        {isRenderableStructure(structure) ? (
          <VaspStructureViewer structure={structure} />
        ) : (
          <CompetitionState status="empty" message="该记录没有可核验的结构坐标" />
        )}
      </section>
    </aside>
  );
}

export default function CompetitionVaspDatabase() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { provider, mode } = useCompetitionData();
  const pageNormalizationRef = useRef('');
  const serializedSearch = searchParams.toString();
  const urlState = useMemo(
    () => readDatabaseUrlState(new URLSearchParams(serializedSearch)),
    [serializedSearch],
  );
  const {
    query,
    selectedElements,
    elementMode,
    page,
    selectedRecordId,
  } = urlState;

  const listRequestKey = useMemo(() => JSON.stringify([
    'database-list',
    query,
    selectedElements,
    elementMode,
    page,
  ]), [elementMode, page, query, selectedElements]);
  const loadDatabase = useCallback(() => loadRequestEnvelope(
    listRequestKey,
    () => provider.listDatabase({
      query,
      elements: selectedElements,
      elementMode,
      page,
      pageSize: 20,
    }),
  ), [elementMode, listRequestKey, page, provider, query, selectedElements]);
  const listResource = useCompetitionResource(loadDatabase);
  const listState = useMemo(
    () => selectRequestResource(listResource, listRequestKey),
    [listRequestKey, listResource],
  );

  const detailRequestKey = useMemo(
    () => JSON.stringify(['database-detail', selectedRecordId]),
    [selectedRecordId],
  );
  const loadRecord = useCallback(() => loadRequestEnvelope(
    detailRequestKey,
    () => (selectedRecordId
      ? provider.getDatabaseRecord(selectedRecordId)
      : Promise.resolve(null)),
  ), [detailRequestKey, provider, selectedRecordId]);
  const detailRequestResource = useCompetitionResource(loadRecord);
  const detailResource = useMemo(
    () => selectRequestResource(detailRequestResource, detailRequestKey),
    [detailRequestKey, detailRequestResource],
  );

  const normalizedResult = useMemo(
    () => (listState.status === 'ready' ? normalizeDatabaseResult(listState.data) : null),
    [listState.data, listState.status],
  );
  const result = normalizedResult || EMPTY_DATABASE_RESULT;
  const listStatus = listState.status === 'ready' && normalizedResult === null
    ? 'parse-error'
    : databaseDetailState(listState, { status: 'ready' });
  const pageNormalization = useMemo(
    () => databasePageNormalization(page, result.total, DATABASE_PAGE_SIZE),
    [page, result.total],
  );
  const pageView = databasePageViewState(listStatus, page, pageNormalization, result);
  const selectedRecord = useMemo(
    () => (detailResource.status === 'ready'
      ? normalizeDatabaseRecord(detailResource.data, selectedRecordId)
      : null),
    [detailResource.data, detailResource.status, selectedRecordId],
  );
  const detailStatus = selectedRecordId
    ? databaseDetailState(detailResource, selectedRecord)
    : 'empty';

  const updateUrlState = useCallback((changes, options = {}) => {
    const next = {
      query,
      selectedElements,
      elementMode,
      page,
      selectedRecordId,
      ...changes,
    };
    if (options.resetPage) next.page = 1;
    if (options.clearRecord) next.selectedRecordId = '';
    setSearchParams(writeDatabaseUrlState(next), { replace: true });
  }, [elementMode, page, query, selectedElements, selectedRecordId, setSearchParams]);

  const changeQuery = useCallback((event) => {
    updateUrlState(
      { query: event.target.value },
      { resetPage: true, clearRecord: true },
    );
  }, [updateUrlState]);
  const changeElements = useCallback((elements) => {
    updateUrlState(
      { selectedElements: elements },
      { resetPage: true, clearRecord: true },
    );
  }, [updateUrlState]);
  const changeElementMode = useCallback((nextMode) => {
    updateUrlState(
      { elementMode: nextMode },
      { resetPage: true, clearRecord: true },
    );
  }, [updateUrlState]);
  const changePage = useCallback((nextPage) => {
    updateUrlState(
      { page: Math.min(pageNormalization.totalPages, Math.max(1, nextPage)) },
      { clearRecord: true },
    );
  }, [pageNormalization.totalPages, updateUrlState]);
  const selectRecord = useCallback((item) => {
    const recordId = safeText(item?.id).trim();
    if (!recordId) return;
    updateUrlState({ selectedRecordId: recordId });
  }, [updateUrlState]);

  useEffect(() => {
    if (listStatus !== 'ready') {
      pageNormalizationRef.current = '';
      return;
    }
    if (!pageNormalization.required) return;
    const normalizationKey = JSON.stringify([
      listRequestKey,
      result.total,
      pageNormalization.targetPage,
    ]);
    if (!shouldApplyPageNormalization(
      pageNormalization.required,
      normalizationKey,
      pageNormalizationRef.current,
    )) return;
    pageNormalizationRef.current = normalizationKey;
    updateUrlState(
      { page: pageNormalization.targetPage },
      { clearRecord: true },
    );
  }, [listRequestKey, listStatus, pageNormalization, result.total, updateUrlState]);

  return (
    <main className="competition-database-page">
      {mode === 'demo' ? <DemoDataBanner /> : null}

      <header className="competition-database-header">
        <h1>VASP 数据库</h1>
        <p>按元素、来源与工作流检索已记录的只读计算结果</p>
      </header>

      <section className="competition-database-filters" aria-labelledby="competition-database-filter-title">
        <div className="competition-database-section-heading">
          <h2 id="competition-database-filter-title">元素筛选</h2>
          {pageView.listStatus === 'ready' ? <span>{result.total} 条结果</span> : null}
        </div>
        <PeriodicTableFilter
          availableElements={result.available_elements}
          selectedElements={selectedElements}
          mode={elementMode}
          onSelectionChange={changeElements}
          onModeChange={changeElementMode}
        />
        <label className="competition-database-search" htmlFor="competition-database-query">
          <span>查询</span>
          <div>
            <Search size={16} aria-hidden="true" />
            <input
              id="competition-database-query"
              type="search"
              value={query}
              placeholder="化学式、来源或工作流 ID"
              onChange={changeQuery}
            />
          </div>
        </label>
      </section>

      <div className="competition-database-workspace">
        <section className="competition-database-records" aria-labelledby="competition-database-records-title">
          <div className="competition-database-section-heading">
            <h2 id="competition-database-records-title">记录</h2>
            {pageView.pageNormalizing
              ? <span>正在校正页码...</span>
              : <span>第 {pageView.headingPage} / {pageView.totalPages} 页</span>}
          </div>

          {pageView.showTable ? (
            <VaspRecordTable
              records={pageView.records}
              columns={DATABASE_COLUMNS}
              metadata={result.metadata}
              loading={pageView.listStatus === 'loading'}
              loadedOnce={pageView.listStatus !== 'loading'}
              detailPathForItem={databaseRecordUrl}
              onSelect={selectRecord}
              renderCell={renderDatabaseCell}
              mobileMode="scroll"
            />
          ) : (
            <CompetitionState
              status={pageView.listStatus}
              message={pageView.pageNormalizing ? '正在校正页码' : listState.error?.message}
            />
          )}

          <nav className="competition-database-pagination" aria-label="数据库分页">
            <button
              type="button"
              disabled={pageView.paginationDisabled || pageView.headingPage <= 1}
              onClick={() => changePage(pageView.headingPage - 1)}
            >
              上一页
            </button>
            <span>{result.total} 条记录</span>
            <button
              type="button"
              disabled={pageView.paginationDisabled || pageView.headingPage >= pageView.totalPages}
              onClick={() => changePage(pageView.headingPage + 1)}
            >
              下一页
            </button>
          </nav>
        </section>

        <DatabaseInspector
          status={detailStatus}
          error={detailResource.error}
          record={selectedRecord}
        />
      </div>
    </main>
  );
}
