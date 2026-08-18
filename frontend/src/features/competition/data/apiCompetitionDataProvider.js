import { getAuthHeaders } from '../../../api/auth.js';
import { CompetitionRequestError } from './competitionErrors.js';

const LOG_STREAMS = new Set(['stdout', 'stderr']);
const SAFE_ROUTE_IDENTIFIER = /^[A-Za-z0-9_-]{1,128}$/;
const REQUEST_FAILURES = new Map([
  [400, { message: '请求参数无效', code: 'bad-request' }],
  [401, { message: '登录状态已失效，请重新登录', code: 'unauthorized' }],
  [403, { message: '当前身份无权执行此操作', code: 'forbidden' }],
  [404, { message: '请求的数据不存在', code: 'not-found' }],
  [409, { message: '当前状态不允许执行此操作', code: 'conflict' }],
  [422, { message: '请求内容未通过校验', code: 'validation-error' }],
  [429, { message: '请求过于频繁，请稍后重试', code: 'rate-limited' }],
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

function publicRequestFailure(status) {
  if (REQUEST_FAILURES.has(status)) return REQUEST_FAILURES.get(status);
  if (status >= 500 && status <= 599) {
    return { message: '服务暂时不可用，请稍后重试', code: 'server-error' };
  }
  return { message: '请求失败，请稍后重试', code: 'request-failed' };
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
} = {}) {
  async function request(path, options = {}) {
    const { responseType = 'auto', headers: suppliedHeaders, ...init } = options;
    const isFormData = typeof FormData !== 'undefined' && init.body instanceof FormData;
    const headers = {
      ...authHeaders(isFormData ? null : 'application/json'),
      ...(suppliedHeaders || {}),
    };
    const response = await fetchImpl(path, { ...init, headers });

    if (responseType === 'blob' && response.ok) {
      return { blob: await response.blob(), response };
    }

    if (!response.ok) {
      const failure = publicRequestFailure(response.status);
      throw new CompetitionRequestError(failure.message, response.status, failure.code);
    }

    const contentType = response.headers.get('content-type') || '';
    const text = await response.text();
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
    } = {}) {
      return request(`/api/competition/vasp/records${queryString([
        ['query', query],
        ['elements', elements],
        ['element_mode', elementMode],
        ['page', page],
        ['page_size', pageSize],
      ])}`);
    },

    getDatabaseRecord(id) {
      return request(`/api/competition/vasp/records/${encodeURIComponent(id)}`);
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
