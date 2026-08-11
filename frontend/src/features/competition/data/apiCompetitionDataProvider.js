import { getAuthHeaders } from '../../../api/auth.js';
import { CompetitionRequestError } from './competitionErrors.js';

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

function errorMessage(data, status) {
  if (typeof data?.detail === 'string') return data.detail;
  if (data?.detail !== undefined) return JSON.stringify(data.detail);
  if (typeof data?.message === 'string') return data.message;
  if (typeof data === 'string' && data) return data;
  return `Competition request failed (${status})`;
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

    const contentType = response.headers.get('content-type') || '';
    const text = await response.text();
    let data = text;
    if (contentType.includes('application/json')) {
      try {
        data = text ? JSON.parse(text) : null;
      } catch {
        const parseError = new CompetitionRequestError('Competition response could not be parsed', response.status, 'parse-error');
        parseError.details = text;
        throw parseError;
      }
    }

    if (!response.ok) {
      const error = new CompetitionRequestError(
        errorMessage(data, response.status),
        response.status,
        data?.code || 'request-failed',
      );
      error.details = data;
      throw error;
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
