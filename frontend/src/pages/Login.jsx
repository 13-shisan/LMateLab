// src/pages/Login.jsx
import { useState } from 'react';
import api from '../api/client';
import { useNavigate } from 'react-router-dom';
import AuthShell from '../components/AuthShell';
import logo from '../assets/logo/Logo.png';


export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [msg, setMsg] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const onSubmit = async (e) => {
    e.preventDefault();
    if (loading) return;

    setMsg('');
    setLoading(true);
    try {
      const res = await api.post('/auth/login', { email, password }, { timeout: 10000 });

      // 兼容后端字段：token / access_token
      const token = res?.data?.token || res?.data?.access_token;
      if (!token) throw new Error('登录响应缺少 token');

      localStorage.setItem('token', token);
      localStorage.setItem('user', JSON.stringify(res.data.user || {}));

      localStorage.removeItem('agent_session_general_chat_active');
      localStorage.removeItem('agent_session_platform_guide');

      navigate('/dashboard', { replace: true });

    } catch (err) {
      setMsg(err?.response?.data?.detail || err?.message || '登录失败');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell>
      <div className="card login-card">
        <h2 className="login-title login-title-with-logo">
          <img className="login-title-logo" src={logo} alt="Logo" />
          低维材料科学实验室平台
        </h2>
        <p className="login-subtitle">请输入账户信息进入平台</p>

        <form onSubmit={onSubmit}>
          <div className="form-field">
            <label className="form-label">Email</label>
            <input
              type="email"
              name="email"
              autoComplete="username"
              required
              className="form-input"
              placeholder="请输入邮箱"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="form-field">
            <div className="form-row">
              <label className="form-label">密码</label>
              <button
                type="button"
                className="form-link"
                onClick={() => navigate('/forgot-password')}
              >
                忘记密码
              </button>
            </div>

            <input
              type="password"
              name="password"
              autoComplete="current-password"
              required
              className="form-input"
              placeholder="请输入密码"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          {msg && <div className="form-error">{msg}</div>}

          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading}
            style={{ width: '100%', marginTop: 8 }}
          >
            {loading ? '登录中...' : '登录'}
          </button>
        </form>

        <div className="form-footer">
          <span>
            没有账号？
            <button
              type="button"
              className="inline-link"
              onClick={() => navigate('/register')}
            >
              立即注册
            </button>
          </span>
        </div>
      </div>
    </AuthShell>
  );
}
