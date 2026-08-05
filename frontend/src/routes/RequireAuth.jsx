// src/routes/RequireAuth.jsx
import { useEffect, useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import api from '../api/client';

export default function RequireAuth({ children }) {
  const location = useLocation();
  const [checking, setChecking] = useState(true);
  const [ok, setOk] = useState(false);

  useEffect(() => {
    let alive = true;

    const run = async () => {
      const token = localStorage.getItem('token');
      if (!token) {
        if (!alive) return;
        setOk(false);
        setChecking(false);
        return;
      }

      try {
        // ✅ 用后端最终裁决 token 是否有效
        const res = await api.get('/auth/me');
        // 可选：同步刷新本地 user，避免 Dashboard 显示空
        localStorage.setItem('user', JSON.stringify(res.data));

        if (!alive) return;
        setOk(true);
        setChecking(false);
      } catch (e) {
        // 401/网络错误：统一视为不通过（401 会被 axios 拦截器清 token 并跳转）
        if (!alive) return;
        setOk(false);
        setChecking(false);
      }
    };

    run();

    return () => {
      alive = false;
    };
  }, []);

  // 校验中：你可以换成更漂亮的 loading 页面
  if (checking) {
    return (
      <div style={{ padding: 24 }}>
        正在校验登录状态...
      </div>
    );
  }

  if (!ok) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
}
