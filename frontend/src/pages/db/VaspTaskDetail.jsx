import { useCallback, useEffect, useMemo, useState } from 'react';
import { ArrowLeft } from 'lucide-react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { API_BASE } from '../../api/config';
import DbLayout from './DbLayout';
import VaspCrystalDetails from './vasp-detail/VaspCrystalDetails';
import VaspElectronicProperties from './vasp-detail/VaspElectronicProperties';
import VaspStructureViewer from './vasp-detail/VaspStructureViewer';
import VaspTaskSummary from './vasp-detail/VaspTaskSummary';
import './vasp-detail/VaspTaskDetail.css';

function getAuthHeaders() {
  const token = localStorage.getItem('token')
    || localStorage.getItem('access_token')
    || sessionStorage.getItem('token')
    || '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

class RequestError extends Error {
  constructor(message, status) {
    super(message);
    this.name = 'RequestError';
    this.status = status;
  }
}

async function fetchJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    method: 'GET',
    headers: { ...getAuthHeaders(), ...(options.headers || {}) },
  });
  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : null;
  if (!response.ok) {
    const message = typeof data?.detail === 'string'
      ? data.detail
      : data?.detail
        ? JSON.stringify(data.detail)
        : `请求失败（${response.status}）`;
    throw new RequestError(message, response.status);
  }
  return data;
}

async function downloadFile(path, fallbackName) {
  const response = await fetch(`${API_BASE}${path}`, { headers: getAuthHeaders() });
  if (!response.ok) {
    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('application/json') ? await response.json() : null;
    throw new RequestError(data?.detail || `下载失败（${response.status}）`, response.status);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  const filename = match?.[1] || fallbackName;
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(href);
}

const SECTIONS = [
  { id: 'structure-summary', label: '结构与摘要' },
  { id: 'crystal-details', label: '晶体参数' },
  { id: 'electronic-properties', label: '电子性质' },
];

export default function VaspTaskDetail() {
  const { dbKey = '', rowId = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const decodedDbKey = useMemo(() => {
    try {
      return decodeURIComponent(dbKey);
    } catch {
      return dbKey;
    }
  }, [dbKey]);
  const requestKey = `${decodedDbKey}:${rowId}`;
  const [state, setState] = useState({ requestKey: '', status: 'loading', detail: null, message: '' });

  useEffect(() => {
    const controller = new AbortController();
    const path = `/api/db/vasp/task/${encodeURIComponent(rowId)}/detail?db=${encodeURIComponent(decodedDbKey)}`;
    fetchJson(path, { signal: controller.signal })
      .then((detail) => setState({ requestKey, status: 'ready', detail, message: '' }))
      .catch((error) => {
        if (error?.name === 'AbortError') return;
        const status = error?.status === 403 ? 'forbidden' : error?.status === 404 ? 'not-found' : 'error';
        setState({ requestKey, status, detail: null, message: String(error?.message || error) });
      });
    return () => controller.abort();
  }, [decodedDbKey, requestKey, rowId]);

  const handleBack = useCallback(() => {
    const backTo = location.state?.backTo;
    if (typeof backTo === 'string' && backTo.startsWith('/')) {
      navigate(backTo, { replace: true });
      return;
    }
    navigate(`/dashboard/db/personal/vasp?db=${encodeURIComponent(decodedDbKey)}`, { replace: true });
  }, [decodedDbKey, location.state, navigate]);

  function scrollToSection(id) {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  const viewState = state.requestKey === requestKey
    ? state
    : { status: 'loading', detail: null, message: '' };
  const detail = viewState.detail;
  const title = detail?.row?.formula ? `${detail.row.formula} 计算详情` : 'VASP 计算详情';

  return (
    <DbLayout currentSubPath="/dashboard/db/personal" currentDbType="vasp" showDbTypeSelector>
      <div className="vasp-task-detail-page">
        <header className="vasp-task-detail-header">
          <div className="vasp-task-detail-title">
            <h2>{title}</h2>
            <p>记录 {rowId} · {detail?.db?.dbname || decodedDbKey}</p>
          </div>
          <button className="vasp-detail-button" type="button" onClick={handleBack}>
            <ArrowLeft size={16} aria-hidden="true" />
            返回任务列表
          </button>
        </header>

        {viewState.status === 'ready' ? (
          <nav className="vasp-task-detail-section-nav" aria-label="详情章节">
            {SECTIONS.map((section) => (
              <button key={section.id} type="button" onClick={() => scrollToSection(section.id)}>{section.label}</button>
            ))}
          </nav>
        ) : null}

        {viewState.status === 'loading' ? <div className="vasp-detail-state">正在加载计算详情…</div> : null}
        {viewState.status === 'forbidden' ? (
          <div className="vasp-detail-state is-error"><strong>无权访问该记录</strong><span>{viewState.message}</span></div>
        ) : null}
        {viewState.status === 'not-found' ? (
          <div className="vasp-detail-state is-error"><strong>没有找到该记录</strong><span>{viewState.message}</span></div>
        ) : null}
        {viewState.status === 'error' ? (
          <div className="vasp-detail-state is-error"><strong>详情加载失败</strong><span>{viewState.message}</span></div>
        ) : null}

        {viewState.status === 'ready' ? (
          <>
            <section className="vasp-detail-surface" id="structure-summary">
              <h3>结构与任务摘要</h3>
              <VaspTaskSummary
                detail={detail}
                dbKey={decodedDbKey}
                rowId={rowId}
                viewer={<VaspStructureViewer structure={detail?.structure} />}
                downloadFile={downloadFile}
              />
            </section>
            <section className="vasp-detail-surface" id="crystal-details">
              <h3>晶体参数</h3>
              <VaspCrystalDetails detail={detail} />
            </section>
            <section className="vasp-detail-surface" id="electronic-properties">
              <h3>电子性质</h3>
              <VaspElectronicProperties
                rowId={rowId}
                dbKey={decodedDbKey}
                capabilities={detail?.capabilities}
                fetchJson={fetchJson}
                downloadFile={downloadFile}
              />
            </section>
          </>
        ) : null}
      </div>
    </DbLayout>
  );
}
