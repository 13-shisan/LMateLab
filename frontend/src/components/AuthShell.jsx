// frontend/src/components/AuthShell.jsx
import { useNavigate } from 'react-router-dom';
import { Home } from 'lucide-react';
import loginBg from '../assets/bg/login-bg.png';
import { activeEdition } from '../config/appNavigation';
import BrandMark from './BrandMark';

const DEFAULT_HOME_LINKS = Object.freeze([
  { hash: '#features', label: '平台介绍' },
  { hash: '#modules', label: '核心能力' },
  { hash: '#cases', label: '应用案例' },
  { hash: '#docs', label: '帮助文档' },
]);

const COMPETITION_HOME_LINKS = Object.freeze([
  { hash: '#platform', label: '平台' },
  { hash: '#workflow', label: '工作流' },
  { hash: '#evidence', label: '证据' },
]);

export default function AuthShell({ children }) {
  const navigate = useNavigate();
  const homeLinks = activeEdition === '107cup' ? COMPETITION_HOME_LINKS : DEFAULT_HOME_LINKS;

  const goHomeHash = (hash) => {
    navigate(`/${hash}`, { replace: true });
  };

  return (
    <div className="login-page login-with-bg" style={{ '--page-bg': `url(${loginBg})` }}>
      <header className="auth-topbar">
        <button
          type="button"
          className="auth-brand-button"
          onClick={() => navigate('/')}
        >
          <BrandMark />
        </button>

        <nav className="auth-nav" aria-label="认证页导航">
          {homeLinks.map((item) => (
            <button
              className="auth-nav-link"
              key={item.hash}
              onClick={() => goHomeHash(item.hash)}
            >
              {item.label}
            </button>
          ))}

          <button
            className="auth-home-action"
            onClick={() => navigate('/')}
            aria-label="返回首页"
          >
            <Home size={16} aria-hidden="true" />
            <span>返回首页</span>
          </button>
        </nav>
      </header>

      <main className="login-center login-center-right">
        <div className="login-right-shell">
          <div className="login-card-wrapper login-card-wrapper-right">
            {children}
          </div>
        </div>
      </main>

      <footer className="login-footer">
        <div className="login-footer-text">
          copyright © 2024‑2025 低维材料科学实验室平台
          <br />
          中国科学技术大学物质楼‑Wugroup
        </div>
      </footer>
    </div>
  );
}
