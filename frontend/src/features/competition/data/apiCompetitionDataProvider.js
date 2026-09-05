import { getAuthHeaders } from '../../../api/auth.js';
import { CompetitionRequestError } from './competitionErrors.js';

const LOG_STREAMS = new Set(['stdout', 'stderr']);
const SAFE_ROUTE_IDENTIFIER = /^[A-Za-z0-9_-]{1,128}$/;
const DEFAULT_REQUEST_TIMEOUT_MS = 15000;
const MIN_REQUEST_TIMEOUT_MS = 10;
const MAX_REQUEST_TIMEOUT_MS = 120000;
const REQUEST_FAILURES = new Map([
  [400, { message: '请求参数无效', code: 'bad-request' }],
  [401, { message: '登录状态已失效，请重新登录', code: 'unauthorized' }],
  [403, { message: '当前身份无权执行此操作', code: 'forbidden' }],
  [404, { message: '请求的数据不存在', code: 'not-found' }],
  [409, { message: '当前状态不允许执行此操作', code: 'conflict' }],
  [422, { message: '请求内容未通过校验', code: 'validation-error' }],
  [429, { message: '请求过于频繁，请稍后重试', code: 'rate-limited' }],
]);

const VALIDATION_FAILURES = new Map([
  ['structure_file_too_large', '结构文件超过 1 MiB 限制'],
  ['structure_atom_limit', '结构超过 200 个原子限制'],
  ['structure_filename_invalid', '结构文件名不符合安全要求'],
  ['structure_elements_invalid', '结构元素或元素顺序无效'],
  ['structure_geometry_invalid', '结构晶格或原子坐标无效'],
  ['structure_content_invalid', '结构文件必须是非空 UTF-8 文本'],
  ['structure_format_invalid', '无法按 POSCAR 或 CIF 解析结构'],
  ['workflow_template_invalid', '结构来源与计算模板不匹配'],
]);

function queryString(entries) {
  const params = new URLSearchParams();
  for (const [key, value] of entries) {
    const normalized = Array.isArray(value) ? value.join(',') : value;
    if (normalized === '' || normalized === undefined || normalized === null || normalized === 'all') continue;
    params.set(key, String(normalized));
  }
  const query = params.toString();
  return query ? `?${query}` : '';
}

function publicRequestFailure(status, errorCode = '') {
  if (status === 422 && VALIDATION_FAILURES.has(errorCode)) {
    return { message: VALIDATION_FAILURES.get(errorCode), code: errorCode };
  }
  if (REQUEST_FAILURES.has(status)) return REQUEST_FAILURES.get(status);
  if (status >= 500 && status <= 599) {
    return { message: '服务暂时不可用，请稍后重试', code: 'server-error' };
  }
  return { message: '请求失败，请稍后重试', code: 'request-failed' };
}

function publicTransportFailure(error) {
  if (error?.name === 'AbortError') {
    return new CompetitionRequestError('请求已中断，请重试', 0, 'request-aborted');
  }
  return new CompetitionRequestError('网络连接失败，请稍后重试', 0, 'network-error');
}

function publicResponseReadFailure(status) {
  return new CompetitionRequestError(
    '响应读取失败，请稍后重试',
    status,
    'response-read-error',
  );
}

function publicRequestTimeoutFailure() {
  return new CompetitionRequestError('请求超时，请稍后重试', 0, 'request-timeout');
}

function boundedRequestTimeoutMs(value) {
  if (!Number.isFinite(value)) return DEFAULT_REQUEST_TIMEOUT_MS;
  return Math.min(
    MAX_REQUEST_TIMEOUT_MS,
    Math.max(MIN_REQUEST_TIMEOUT_MS, Math.trunc(value)),
  );
}

function filenameFromDisposition(disposition, fallback) {
  const encoded = disposition?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded.replace(/^"|"$/g, ''));
    } catch {
      return encoded.replace(/^"|"$/g, '');
    }
  }
  return disposition?.match(/filename="?([^";]+)"?/i)?.[1] || fallback;
}

function isSafeRouteIdentifier(value) {
  return typeof value === 'string' && SAFE_ROUTE_IDENTIFIER.test(value);
}

function validateAttemptLogRoute(workflowId, attemptId, stream) {
  const invalidIdentifier = !isSafeRouteIdentifier(workflowId)
    || !isSafeRouteIdentifier(attemptId);
  if (invalidIdentifier || !LOG_STREAMS.has(stream)) {
    throw new CompetitionRequestError(
      'Attempt log request is invalid',
      400,
      'invalid-log-request',
    );
  }
}

export function createApiCompetitionDataProvider({
  fetchImpl = fetch,
  authHeaders = getAuthHeaders,
  requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
} = {}) {
  const timeoutMs = boundedRequestTimeoutMs(requestTimeoutMs);

  async function request(path, options = {}) {
    const { responseType = 'auto', headers: suppliedHeaders, ...init } = options;
    const isFormData = typeof FormData !== 'undefined' && init.body instanceof FormData;
    const headers = {
      ...authHeaders(isFormData ? null : 'application/json'),
      ...(suppliedHeaders || {}),
    };
    const controller = new AbortController();
    let timedOut = false;
    let timeoutId;

    const transport = (async () => {
      let response;
      try {
        response = await fetchImpl(path, { ...init, headers, signal: controller.signal });
      } catch (error) {
        if (timedOut) throw publicRequestTimeoutFailure();
        throw publicTransportFailure(error);
      }

      if (responseType === 'blob' && response.ok) {
        try {
          return { blob: await response.blob(), response };
        } catch {
          if (timedOut) throw publicRequestTimeoutFailure();
          throw publicResponseReadFailure(response.status);
        }
      }

      if (!response.ok) {
        const failure = publicRequestFailure(
          response.status,
          response.headers.get('x-error-code') || '',
        );
        throw new CompetitionRequestError(failure.message, response.status, failure.code);
      }

      let contentType;
      let text;
      try {
        contentType = response.headers.get('content-type') || '';
        text = await response.text();
      } catch {
        if (timedOut) throw publicRequestTimeoutFailure();
        throw publicResponseReadFailure(response.status);
      }
      let data = text;
      if (contentType.includes('application/json')) {
        try {
          data = text ? JSON.parse(text) : null;
        } catch {
          throw new CompetitionRequestError(
            '响应格式无效，请稍后重试',
            response.status,
            'parse-error',
          );
        }
      }
      return data;
    })();

    const timeout = new Promise((_resolve, reject) => {
      timeoutId = globalThis.setTimeout(() => {
        timedOut = true;
        reject(publicRequestTimeoutFailure());
        controller.abort();
      }, timeoutMs);
    });

    try {
      return await Promise.race([transport, timeout]);
    } finally {
      globalThis.clearTimeout(timeoutId);
    }
  }

  function jsonPost(path, body) {
    return request(path, { method: 'POST', body: JSON.stringify(body) });
  }

  return Object.freeze({
    mode: 'live',
    readOnly: false,

    getDashboard() {
      return request('/api/competition/dashboard');
    },

    listWorkflows({ query = '', status = '' } = {}) {
      return request(`/api/competition/workflows${queryString([
        ['query', query],
        ['status', status],
      ])}`);
    },

    getWorkflow(id) {
      return request(`/api/competition/workflows/${encodeURIComponent(id)}`);
    },

    listResults({ query = '', status = '' } = {}) {
      return request(`/api/competition/results${queryString([
        ['query', query],
        ['status', status],
      ])}`);
    },

    getResult(id) {
      return request(`/api/competition/results/${encodeURIComponent(id)}`);
    },

    listDatabase({
      query = '',
      elements = [],
      elementMode = '',
      page,
      pageSize,
      sourceScope = 'all',
    } = {}) {
      return request(`/api/competition/vasp/records${queryString([
        ['query', query],
        ['elements', elements],
        ['element_mode', elementMode],
        ['page', page],
        ['page_size', pageSize],
        ['source_scope', sourceScope],
      ])}`);
    },

    getDatabaseRecord(id) {
      return request(`/api/competition/vasp/records/${encodeURIComponent(id)}`);
    },

    listAgentTemplates() {
      return request('/api/competition/agent/templates');
    },

    getAgentRuntime() {
      return request('/api/competition/agent/runtime');
    },

    installQoder() {
      return request('/api/competition/agent/qoder/install', { method: 'POST' });
    },

    loginQoder() {
      return request('/api/competition/agent/qoder/login', { method: 'POST' });
    },

    startQoderService() {
      return request('/api/competition/agent/qoder/service/start', { method: 'POST' });
    },

    stopQoderService() {
      return request('/api/competition/agent/qoder/service/stop', { method: 'POST' });
    },

    getAgentSettings() {
      return request('/api/competition/agent/settings');
    },

    updateAgentSettings(payload) {
      return request('/api/competition/agent/settings', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
    },

    listAgentFiles() {
      return request('/api/competition/agent/files');
    },

    listAgentExamples() {
      return request('/api/competition/agent/examples');
    },

    async downloadAgentExample(id) {
      const { blob, response } = await request(
        `/api/competition/agent/examples/${encodeURIComponent(id)}/bundle`,
        { responseType: 'blob' },
      );
      return {
        blob,
        filename: filenameFromDisposition(response.headers.get('content-disposition'), `${id}.zip`),
      };
    },

    uploadAgentFile(file, category = 'result', libraryName = '我的文献库', options = {}) {
      const body = new FormData();
      body.append('file', file);
      body.append('category', category);
      body.append('library_name', libraryName);
      if (options.calculationId) body.append('calculation_id', options.calculationId);
      if (options.groupName) body.append('group_name', options.groupName);
      return request('/api/competition/agent/files', { method: 'POST', body });
    },

    listAgentLiterature(query = '') {
      return request(`/api/competition/agent/literature${queryString([['query', query]])}`);
    },

    searchAgentLiterature(query) {
      return request(`/api/competition/agent/literature/search${queryString([['query', query]])}`);
    },

    indexAgentLiterature(payload) {
      return jsonPost('/api/competition/agent/literature/index', payload);
    },

    searchAgentStructures(query = '') {
      return request(`/api/competition/agent/library/structures${queryString([['query', query]])}`);
    },

    listAgentRuns() {
      return request('/api/competition/agent/runs');
    },

    getAgentRun(id) {
      return request(`/api/competition/agent/runs/${encodeURIComponent(id)}`);
    },

    createAgentRun(payload) {
      return jsonPost('/api/competition/agent/runs', payload);
    },

    deleteAgentConversation(id) {
      return request(`/api/competition/agent/runs/conversations/${encodeURIComponent(id)}`, {
        method: 'DELETE',
      });
    },

    approveAgentRun(id) {
      return jsonPost(`/api/competition/agent/runs/${encodeURIComponent(id)}/approve`, {});
    },

    listCuratedStructures() {
      return request('/api/competition/agent/structures');
    },

    buildCuratedStructure(payload) {
      return jsonPost('/api/competition/agent/structures/build', payload);
    },

    async downloadCuratedStructureBundle(payload) {
      const { blob, response } = await request(
        '/api/competition/agent/structures/bundle',
        { method: 'POST', body: JSON.stringify(payload), responseType: 'blob' },
      );
      return {
        blob,
        filename: filenameFromDisposition(
          response.headers.get('content-disposition'),
          `${payload.material_id}-vasp-inputs.zip`,
        ),
        data_kind: 'live',
      };
    },

    loadPlot(id, kind) {
      return request(`/api/competition/results/${encodeURIComponent(id)}/${encodeURIComponent(kind)}-plot`);
    },

    async downloadArtifact(id, kind) {
      const encodedId = encodeURIComponent(id);
      const encodedKind = encodeURIComponent(kind);
      const { blob, response } = await request(
        `/api/competition/results/${encodedId}/artifacts/${encodedKind}`,
        { responseType: 'blob' },
      );
      return {
        blob,
        filename: filenameFromDisposition(
          response.headers.get('content-disposition'),
          `${id}-${kind}`,
        ),
        data_kind: 'live',
      };
    },

    uploadStructure(file) {
      const body = new FormData();
      body.append('file', file);
      return request('/api/competition/structures', { method: 'POST', body });
    },

    saveDraft(payload) {
      return jsonPost('/api/competition/drafts', payload);
    },

    submitWorkflow(id) {
      return jsonPost(`/api/competition/workflows/${encodeURIComponent(id)}/submit`, {});
    },

    startWorkflow(id) {
      return jsonPost(`/api/competition/workflows/${encodeURIComponent(id)}/start`, {});
    },

    async getAttemptLog(workflowId, attemptId, stream) {
      validateAttemptLogRoute(workflowId, attemptId, stream);
      return request(
        `/api/competition/workflows/${encodeURIComponent(workflowId)}`
        + `/attempts/${encodeURIComponent(attemptId)}/logs/${stream}`,
      );
    },

    cancelWorkflow(id) {
      return jsonPost(`/api/competition/workflows/${encodeURIComponent(id)}/cancel`, {});
    },

    retryWorkflow({ id, step }) {
      return jsonPost(
        `/api/competition/workflows/${encodeURIComponent(id)}/steps/${encodeURIComponent(step)}/retry`,
        {},
      );
    },

    mutateDatabase(payload) {
      return jsonPost('/api/competition/vasp/records', payload);
    },
  });
}
