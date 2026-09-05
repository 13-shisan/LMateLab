import { matchesElementSelection } from '../../../utils/elementSelection.js';
import { CompetitionRequestError, PreviewReadOnlyError } from './competitionErrors.js';
import {
  DEMO_BAND_DATA,
  DEMO_CIF,
  DEMO_CLUSTER_RESOURCES,
  DEMO_DASHBOARD,
  DEMO_DATABASE_METADATA,
  DEMO_DATABASE_ROWS,
  DEMO_DOS_DATA,
  DEMO_PLOTS,
  DEMO_POSCAR,
  DEMO_RESULTS_BY_ID,
  DEMO_WORKFLOWS,
} from './demoFixtures.js';

const SUCCESS_WORKFLOW_ID = 'wf-demo-mos2-success';
const LOG_STREAMS = new Set(['stdout', 'stderr']);
const SAFE_ROUTE_IDENTIFIER = /^[A-Za-z0-9_-]{1,128}$/;

function clone(value) {
  return structuredClone(value);
}

function notFound(message, code = 'not-found') {
  throw new CompetitionRequestError(message, 404, code);
}

function rejectMutation(action) {
  throw new PreviewReadOnlyError(action);
}

function matchesQuery(record, query) {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return true;
  return [record.id, record.material, record.source]
    .some((value) => String(value || '').toLowerCase().includes(needle));
}

function matchesDatabaseQuery(record, query) {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return true;
  return [record.formula, record.source, record.workflow_id]
    .some((value) => String(value || '').toLowerCase().includes(needle));
}

function matchesStatus(record, status) {
  return !status || status === 'all' || record.status === status;
}

function demoAttemptId(workflowIndex, stepIndex) {
  const suffix = `${String(workflowIndex + 1).padStart(4, '0')}${String(stepIndex + 1).padStart(8, '0')}`;
  return `00000000-0000-4000-8000-${suffix}`;
}

function workflowWithAttemptIds(workflow) {
  if (!workflow) return null;
  const cloned = clone(workflow);
  const workflowIndex = DEMO_WORKFLOWS.findIndex((item) => item.id === workflow.id);
  cloned.steps = cloned.steps.map((step, stepIndex) => ({
    ...step,
    attempt_id: step.job_id ? demoAttemptId(workflowIndex, stepIndex) : null,
  }));
  return cloned;
}

function isSafeRouteIdentifier(value) {
  return typeof value === 'string' && SAFE_ROUTE_IDENTIFIER.test(value);
}

function validateAttemptLogRequest(workflowId, attemptId, stream) {
  const invalidIdentifier = !isSafeRouteIdentifier(workflowId)
    || !isSafeRouteIdentifier(attemptId);
  if (invalidIdentifier || !LOG_STREAMS.has(stream)) {
    throw new CompetitionRequestError('Attempt log request is invalid', 400, 'invalid-log-request');
  }
}

export function createDemoCompetitionDataProvider() {
  return Object.freeze({
    mode: 'demo',
    readOnly: true,

    async getDashboard() {
      return clone(DEMO_DASHBOARD);
    },

    async getServiceHealth() {
      return {
        status: 'ok',
        job_id: 'DEMO-SERVICE',
        node: 'anode18',
        commit: '0000000000000000000000000000000000000000',
        release_kind: 'preview',
        data_mode: 'demo',
      };
    },

    async getClusterResources() {
      return clone(DEMO_CLUSTER_RESOURCES);
    },

    async listWorkflows({ query = '', status = '' } = {}) {
      const items = DEMO_WORKFLOWS.filter((workflow) => (
        matchesQuery(workflow, query) && matchesStatus(workflow, status)
      )).map(workflowWithAttemptIds);
      return {
        items: clone(items),
        total: items.length,
        data_kind: 'demo',
      };
    },

    async getWorkflow(id) {
      const workflow = DEMO_WORKFLOWS.find((item) => item.id === id);
      return workflowWithAttemptIds(workflow);
    },

    async listResults({ query = '', status = '' } = {}) {
      const results = Object.values(DEMO_RESULTS_BY_ID).filter((result) => (
        result && typeof result === 'object'
        && matchesQuery(result, query)
        && matchesStatus(result, status)
      ));
      return {
        items: clone(results),
        total: results.length,
        data_kind: 'demo',
      };
    },

    async getResult(id) {
      const result = DEMO_RESULTS_BY_ID[id];
      return clone(result || null);
    },

    async listDatabase({
      query = '',
      elements = [],
      elementMode = 'at_least',
      page = 1,
      pageSize = 20,
    } = {}) {
      const currentPage = Math.max(1, Number(page) || 1);
      const currentPageSize = Math.max(1, Number(pageSize) || 20);
      const filtered = DEMO_DATABASE_ROWS.filter((row) => (
        matchesElementSelection(row.elements, elements, elementMode)
        && matchesDatabaseQuery(row, query)
      ));
      const start = (currentPage - 1) * currentPageSize;

      return clone({
        items: filtered.slice(start, start + currentPageSize),
        total: filtered.length,
        page: currentPage,
        page_size: currentPageSize,
        available_elements: ['Mo', 'S'],
        metadata: DEMO_DATABASE_METADATA,
        data_kind: 'demo',
      });
    },

    async getDatabaseRecord(id) {
      const row = DEMO_DATABASE_ROWS.find((item) => item.id === id || item._rowId === id);
      return clone(row || null);
    },

    async listAgentTemplates() {
      return { items: [] };
    },

    async getAgentRuntime() {
      return {
        provider: 'mock', connected: false, qoder_available: false,
        qoder: { interface: 'qodercn-agent-sdk', enabled: false, connected: false, auth_mode: 'pat', model: null },
      };
    },

    async installQoder() { return rejectMutation('Qoder 安装'); },
    async loginQoder() { return rejectMutation('Qoder 登录'); },
    async startQoderService() { return rejectMutation('Qoder 服务启动'); },
    async stopQoderService() { return rejectMutation('Qoder 服务停止'); },

    async getAgentSettings() {
      return { api_url: '', model: '', api_key_configured: false, api_key_write_allowed: false };
    },

    async updateAgentSettings() {
      return rejectMutation('Agent 设置');
    },

    async listAgentFiles() {
      return { items: [], calculations: [] };
    },

    async listAgentExamples() {
      return { items: [] };
    },

    async downloadAgentExample() {
      return rejectMutation('Agent 示例下载');
    },

    async uploadAgentFile() {
      return rejectMutation('Agent 文件上传');
    },

    async listAgentLiterature() {
      return { items: [], uploads: [] };
    },

    async searchAgentLiterature() {
      return { items: [], source: 'OpenAlex' };
    },

    async indexAgentLiterature() {
      return rejectMutation('文献索引');
    },

    async searchAgentStructures() {
      return { items: [], total: 0, sources: [] };
    },

    async listAgentRuns() {
      return { items: [] };
    },

    async getAgentRun() {
      return null;
    },

    async createAgentRun() {
      return rejectMutation('竞赛 Agent 请求');
    },

    async deleteAgentConversation() {
      return rejectMutation('竞赛 Agent 对话删除');
    },

    async approveAgentRun() {
      return rejectMutation('竞赛 Agent 审核');
    },

    async listCuratedStructures() {
      return { items: [] };
    },

    async buildCuratedStructure() {
      return rejectMutation('结构构建');
    },

    async downloadCuratedStructureBundle() {
      return rejectMutation('VASP 输入包下载');
    },

    async loadPlot(id, kind) {
      if (id !== SUCCESS_WORKFLOW_ID || !['band', 'dos'].includes(kind)) {
        return notFound(`Plot is unavailable: ${id}/${kind}`, 'parse-error');
      }
      return clone({
        image_url: DEMO_PLOTS[kind],
        workflow_id: id,
        kind,
        data_kind: 'demo',
      });
    },

    async downloadArtifact(id, kind) {
      if (id !== SUCCESS_WORKFLOW_ID) {
        return notFound(`Artifact is unavailable: ${id}/${kind}`);
      }

      const artifacts = {
        'band-data': ['DEMO-band.dat', DEMO_BAND_DATA, 'text/plain;charset=utf-8'],
        'dos-data': ['DEMO-dos.dat', DEMO_DOS_DATA, 'text/plain;charset=utf-8'],
        'structure-cif': ['DEMO-MoS2.cif', DEMO_CIF, 'chemical/x-cif;charset=utf-8'],
        'structure-poscar': ['DEMO-POSCAR', DEMO_POSCAR, 'text/plain;charset=utf-8'],
        'evidence-bundle': [
          'DEMO-evidence.json',
          JSON.stringify(DEMO_RESULTS_BY_ID[SUCCESS_WORKFLOW_ID], null, 2),
          'application/json;charset=utf-8',
        ],
      };
      const artifact = artifacts[kind];
      if (!artifact) return notFound(`Artifact is unavailable: ${id}/${kind}`);
      const [filename, content, type] = artifact;
      return {
        blob: new Blob([content], { type }),
        filename,
        data_kind: 'demo',
      };
    },

    async uploadStructure() {
      return rejectMutation('结构上传');
    },

    async saveDraft() {
      return rejectMutation('草稿保存');
    },

    async submitWorkflow() {
      return rejectMutation('工作流提交');
    },

    async startWorkflow() {
      return rejectMutation('工作流启动');
    },

    async getAttemptLog(workflowId, attemptId, stream) {
      validateAttemptLogRequest(workflowId, attemptId, stream);
      const workflow = workflowWithAttemptIds(
        DEMO_WORKFLOWS.find((item) => item.id === workflowId),
      );
      const step = workflow?.steps.find((item) => item.attempt_id === attemptId);
      if (!step) return notFound('Attempt log is unavailable');
      return {
        stream,
        content: `DEMO ${stream.toUpperCase()} tail\n${workflow.id} · ${step.key} · attempt ${step.attempt}\n`,
      };
    },

    async cancelWorkflow() {
      return rejectMutation('工作流取消');
    },

    async retryWorkflow() {
      return rejectMutation('工作流重试');
    },

    async mutateDatabase() {
      return rejectMutation('数据库写入');
    },
  });
}
