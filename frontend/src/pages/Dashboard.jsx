import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Activity,
  ArrowRight,
  Atom,
  Bot,
  CalendarDays,
  ClipboardList,
  Database,
  ExternalLink,
  FileClock,
  Link as LinkIcon,
  Orbit,
  Plus,
  Server,
  UserRound,
} from 'lucide-react';

import api from '../api/client';
import AcademicReportList from '../components/AcademicReportList';
import AcademicReportModal from '../components/AcademicReportModal';
import {
  dashboardShortcuts,
  getNavigationItem,
  navigationGroups,
} from '../config/appNavigation';
import './Dashboard.css';

const shortcutIconMap = {
  Atom,
  Bot,
  ClipboardList,
  Database,
  Orbit,
  Server,
  UserRound,
};

const externalLinks = [
  {
    key: 'group-home',
    href: 'http://staff.ustc.edu.cn/~xjwu',
    title: '课题组首页',
    description: 'CCML 课题组主页',
  },
  {
    key: 'matelab',
    href: 'https://matelab.iphy.ac.cn',
    title: 'MatElab',
    description: '材料科学数据与计算平台',
  },
  {
    key: 'cmpdc',
    href: 'https://cmpdc.iphy.ac.cn',
    title: 'CMPDC',
    description: '凝聚态物质科学数据库中心',
  },
];

function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null');
  } catch {
    return null;
  }
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [latestReports, setLatestReports] = useState([]);
  const [reportsLoading, setReportsLoading] = useState(true);
  const [openId, setOpenId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const user = readStoredUser();
  const userName = user?.name || user?.username || '科研用户';
  const databaseCount = navigationGroups.find((group) => group.key === 'database')?.items.length || 0;
  const shortcuts = useMemo(
    () => dashboardShortcuts.map(getNavigationItem).filter(Boolean),
    [],
  );

  useEffect(() => {
    let alive = true;

    const loadReports = async () => {
      try {
        const response = await api.get('/academic-reports/latest', { params: { limit: 3 } });
        if (alive) setLatestReports(response?.data?.items || []);
      } catch {
        if (alive) setLatestReports([]);
      } finally {
        if (alive) setReportsLoading(false);
      }
    };

    loadReports();
    return () => {
      alive = false;
    };
  }, []);

  const openDetail = async (item) => {
    if (!item?.id) return;

    setOpenId(item.id);
    setDetail(item);
    setDetailLoading(true);
    try {
      const response = await api.get(`/academic-reports/${item.id}`);
      setDetail(response.data);
    } catch (error) {
      console.error('Failed to load academic report detail', error);
    } finally {
      setDetailLoading(false);
    }
  };

  const closeDetail = () => {
    setOpenId(null);
    setDetail(null);
    setDetailLoading(false);
  };

  return (
    <div className="lm-dashboard-page">
      <section className="lm-dashboard-welcome">
        <div>
          <h2>欢迎回来，{userName}</h2>
          <p>这里汇总平台状态、常用科研入口和近期学术报告。</p>
        </div>
        <button
          className="lm-primary-action"
          type="button"
          onClick={() => navigate('/dashboard/notes/journal')}
        >
          <Plus size={16} />
          <span>新建实验记录</span>
        </button>
      </section>

      <section className="lm-overview-grid" aria-label="平台概览">
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>平台状态</span>
            <span className="lm-overview-icon"><Activity size={16} /></span>
          </div>
          <strong className="is-healthy">正常运行</strong>
          <small>当前页面与认证服务可用</small>
        </article>
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>当前用户</span>
            <span className="lm-overview-icon"><UserRound size={16} /></span>
          </div>
          <strong>{userName}</strong>
          <small>{user?.email || '个人工作空间'}</small>
        </article>
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>数据库</span>
            <span className="lm-overview-icon"><Database size={16} /></span>
          </div>
          <strong>{databaseCount}</strong>
          <small>个已配置数据入口</small>
        </article>
        <article className="lm-overview-item">
          <div className="lm-overview-label">
            <span>近期学术报告</span>
            <span className="lm-overview-icon"><CalendarDays size={16} /></span>
          </div>
          <strong>{reportsLoading ? '...' : latestReports.length}</strong>
          <small>条接口返回记录</small>
        </article>
      </section>

      <section className="lm-dashboard-grid">
        <div className="lm-dashboard-main-column">
          <section className="lm-dashboard-panel">
            <div className="lm-dashboard-panel-header">
              <div>
                <h3>常用入口</h3>
                <p>直接进入常用科研工作区</p>
              </div>
            </div>
            <div className="lm-shortcut-grid">
              {shortcuts.map((item) => {
                const Icon = shortcutIconMap[item.icon] || Database;
                return (
                  <button
                    className="lm-shortcut-item"
                    key={item.key}
                    type="button"
                    onClick={() => navigate(item.path)}
                  >
                    <span className="lm-shortcut-icon"><Icon size={18} /></span>
                    <span className="lm-shortcut-copy">
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
                    </span>
                    <ArrowRight size={15} />
                  </button>
                );
              })}
            </div>
          </section>

          <section className="lm-dashboard-panel">
            <div className="lm-dashboard-panel-header">
              <div>
                <h3>科研资源</h3>
                <p>实验室与公共材料平台</p>
              </div>
              <button type="button" onClick={() => navigate('/dashboard/changelog')}>
                <FileClock size={14} />
                <span>更新日志</span>
              </button>
            </div>
            <div className="lm-resource-list">
              {externalLinks.map((link) => (
                <a key={link.key} href={link.href} target="_blank" rel="noreferrer">
                  <span className="lm-resource-icon"><LinkIcon size={16} /></span>
                  <span>
                    <strong>{link.title}</strong>
                    <small>{link.description}</small>
                  </span>
                  <ExternalLink size={14} />
                </a>
              ))}
            </div>
          </section>
        </div>

        <aside className="lm-dashboard-panel lm-reports-panel">
          <div className="lm-dashboard-panel-header">
            <div>
              <h3>学术报告</h3>
              <p>来自平台现有报告数据</p>
            </div>
            <button type="button" onClick={() => navigate('/dashboard/academic-reports')}>
              <span>查看全部</span>
              <ArrowRight size={14} />
            </button>
          </div>

          {reportsLoading ? (
            <div className="lm-dashboard-empty">正在加载报告...</div>
          ) : latestReports.length > 0 ? (
            <AcademicReportList items={latestReports} onOpen={openDetail} />
          ) : (
            <div className="lm-dashboard-empty">暂无近期学术报告</div>
          )}
        </aside>
      </section>

      <AcademicReportModal
        open={Boolean(openId)}
        item={detail}
        loading={detailLoading}
        onClose={closeDetail}
      />
    </div>
  );
}
