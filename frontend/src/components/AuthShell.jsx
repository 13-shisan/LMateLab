// frontend/src/components/AuthShell.jsx
import { useNavigate } from 'react-router-dom';
import { Home } from 'lucide-react';
import loginBg from '../assets/bg/login-bg.png';
import BrandMark from './BrandMark';

export default function AuthShell({ children }) {
  const navigate = useNavigate();

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
          <button className="auth-nav-link" onClick={() => goHomeHash('#features')}>平台介绍</button>
          <button className="auth-nav-link" onClick={() => goHomeHash('#modules')}>核心能力</button>
          <button className="auth-nav-link" onClick={() => goHomeHash('#cases')}>应用案例</button>
          <button className="auth-nav-link" onClick={() => goHomeHash('#docs')}>帮助文档</button>

          <button className="auth-home-action" onClick={() => navigate('/')}>
            <Home size={16} />
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
