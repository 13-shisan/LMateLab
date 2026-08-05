import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  Atom,
  Bell,
  Bot,
  ChevronDown,
  ClipboardList,
  Database,
  Languages,
  LayoutDashboard,
  Library,
  ListChecks,
  LogOut,
  Map,
  Menu,
  MessageSquareText,
  Newspaper,
  Orbit,
  PanelLeftClose,
  PanelLeftOpen,
  Presentation,
  Rss,
  Server,
  UserRound,
  UsersRound,
  X,
} from 'lucide-react';

import { clearAuthState } from '../api/auth';
import logo from '../assets/logo/Logo.png';
import {
  getPageMeta,
  isNavigationItemActive,
  navigationGroups,
} from '../config/appNavigation';
import './AppShell.css';

const iconMap = {
  Atom,
  Bot,
  ClipboardList,
  Database,
  LayoutDashboard,
  Library,
  ListChecks,
  Map,
  MessageSquareText,
  Newspaper,
  Orbit,
  Presentation,
  Rss,
  Server,
  UserRound,
  UsersRound,
};

function readStoredUser() {
  try {
    return JSON.parse(localStorage.getItem('user') || 'null');
  } catch {
    return null;
  }
}

function getUserInitial(user) {
  const source = user?.name || user?.username || user?.email || '研';
  return source.trim().slice(0, 1).toUpperCase();
}

export default function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const menuRef = useRef(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(() => {
    return localStorage.getItem('lmatelab-sidebar-collapsed') === 'true';
  });

  const user = readStoredUser();
  const pageMeta = useMemo(() => getPageMeta(location.pathname), [location.pathname]);

  useEffect(() => {
    const onPointerDown = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setUserMenuOpen(false);
      }
    };
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        setDrawerOpen(false);
        setUserMenuOpen(false);
      }
    };

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  const toggleCollapsed = () => {
    setCollapsed((current) => {
      const next = !current;
      localStorage.setItem('lmatelab-sidebar-collapsed', String(next));
      return next;
    });
  };

  const logout = () => {
    clearAuthState();
    window.location.href = '/login';
  };

  const navigateFromMenu = (path) => {
    setUserMenuOpen(false);
    navigate(path);
  };

  return (
    <div className={`lm-app-shell${collapsed ? ' is-collapsed' : ''}`}>
      <aside className={`lm-sidebar${drawerOpen ? ' is-open' : ''}`} aria-label="主导航">
        <div className="lm-sidebar-brand">
          <Link
            className="lm-brand-link"
            to="/dashboard"
            title="返回工作台"
            onClick={() => setDrawerOpen(false)}
          >
            <img src={logo} alt="LMateLab" />
            <span className="lm-brand-copy">
              <strong>低维材料科学实验室</strong>
              <small>Low-Dimensional Materials Science Lab</small>
            </span>
          </Link>
          <button
            className="lm-drawer-close"
            type="button"
            onClick={() => setDrawerOpen(false)}
            aria-label="关闭导航"
            title="关闭导航"
          >
            <X size={18} />
          </button>
        </div>

        <nav className="lm-sidebar-nav">
          {navigationGroups.map((group) => (
            <div className="lm-nav-group" key={group.key}>
              {group.label ? <div className="lm-nav-group-label">{group.label}</div> : null}
              {group.items.map((item) => {
                const Icon = iconMap[item.icon] || LayoutDashboard;
                const active = isNavigationItemActive(location.pathname, item);
                return (
                  <Link
                    key={item.key}
                    className={`lm-nav-item${active ? ' is-active' : ''}`}
                    to={item.path}
                    aria-current={active ? 'page' : undefined}
                    title={collapsed ? item.label : undefined}
                    onClick={() => setDrawerOpen(false)}
                  >
                    <Icon size={17} strokeWidth={1.9} />
                    <span>{item.label}</span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="lm-sidebar-footer">
          <div className="lm-platform-state" title="平台运行正常">
            <span className="lm-platform-dot" />
            <span>平台运行正常</span>
          </div>
          <button
            className="lm-collapse-button"
            type="button"
            onClick={toggleCollapsed}
            aria-label={collapsed ? '展开侧栏' : '收起侧栏'}
            title={collapsed ? '展开侧栏' : '收起侧栏'}
          >
            {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
            <span>{collapsed ? '展开侧栏' : '收起侧栏'}</span>
          </button>
        </div>
      </aside>

      {drawerOpen ? (
        <button
          className="lm-drawer-backdrop"
          type="button"
          aria-label="关闭导航"
          onClick={() => setDrawerOpen(false)}
        />
      ) : null}

      <header className="lm-app-topbar">
        <button
          className="lm-mobile-menu"
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="打开导航"
          title="打开导航"
        >
          <Menu size={20} />
        </button>

        <div className="lm-page-heading">
          <h1>{pageMeta.title}</h1>
          <p>{pageMeta.description}</p>
        </div>

        <div className="lm-topbar-actions">
          <button
            className="lm-icon-button"
            type="button"
            onClick={() => navigateFromMenu('/dashboard/changelog')}
            aria-label="平台更新日志"
            title="平台更新日志"
          >
            <Bell size={17} />
          </button>

          <div className="lm-user-menu-wrap" ref={menuRef}>
            <button
              className="lm-user-trigger"
              type="button"
              aria-haspopup="menu"
              aria-expanded={userMenuOpen}
              onClick={() => setUserMenuOpen((current) => !current)}
            >
              <span className="lm-user-avatar">{getUserInitial(user)}</span>
              <span className="lm-user-summary">
                <strong>{user?.name || user?.username || '科研用户'}</strong>
                <small>账户与设置</small>
              </span>
              <ChevronDown size={15} />
            </button>

            {userMenuOpen ? (
              <div className="lm-user-menu" role="menu">
                <div className="lm-user-menu-identity">
                  <strong>{user?.name || user?.username || '科研用户'}</strong>
                  <span>{user?.email || '未读取到邮箱'}</span>
                </div>
                <div className="lm-user-menu-separator" />
                <button type="button" role="menuitem" onClick={() => navigateFromMenu('/dashboard/issues')}>
                  <MessageSquareText size={16} />
                  <span>反馈与建议</span>
                </button>
                <button type="button" role="menuitem" onClick={() => navigateFromMenu('/dashboard/changelog')}>
                  <Bell size={16} />
                  <span>平台更新日志</span>
                </button>
                <div className="lm-user-language" role="menuitem" aria-label="当前语言：中文">
                  <Languages size={16} />
                  <span>语言</span>
                  <small>中文</small>
                </div>
                <div className="lm-user-menu-separator" />
                <button className="is-danger" type="button" role="menuitem" onClick={logout}>
                  <LogOut size={16} />
                  <span>退出登录</span>
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <div className="lm-app-content">
        <Outlet />
      </div>
    </div>
  );
}
