// src/pages/Register.jsx
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AuthShell from '../components/AuthShell';
import api from '../api/client';

function buildPasswordValidator(policy) {
  const minLength = policy?.minLength ?? 6;
  const requireUpper = policy?.requireUpper ?? true;
  const requireLower = policy?.requireLower ?? true;
  const allowedPattern = policy?.allowedPattern || '';
  const allowedRe = allowedPattern ? new RegExp(allowedPattern) : null;

  return function validate(pw) {
    const errors = [];
    if (!pw || pw.length < minLength) errors.push(`至少 ${minLength} 位`);
    if (requireUpper && !/[A-Z]/.test(pw)) errors.push('至少包含 1 个大写字母');
    if (requireLower && !/[a-z]/.test(pw)) errors.push('至少包含 1 个小写字母');
    if (allowedRe && pw && !allowedRe.test(pw)) errors.push('包含不允许的字符（不允许空格/非常规字符）');
    return { ok: errors.length === 0, errors };
  };
}

export default function Register() {
  const navigate = useNavigate();

  const [nameCN, setNameCN] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [password2, setPassword2] = useState('');
  const [msg, setMsg] = useState('');
  const [showPwAllowedDetails, setShowPwAllowedDetails] = useState(false);

  // 后端策略/白名单匹配信息
  const [policy, setPolicy] = useState(null);
  const [allowedInfo, setAllowedInfo] = useState({ status: 'idle', allowed: false, aliasEN: '', role: '' });

  // 1) 拉取密码策略（仅用于前端提示；后端仍会强校验）
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await api.get('/auth/password-policy');
        if (mounted) setPolicy(res.data);
      } catch (e) {
        // 拉取失败不阻塞注册，只是前端无法做精准提示
        if (mounted) setPolicy({ minLength: 6, requireUpper: true, requireLower: true, allowedPattern: '' });
      }
    })();
    return () => { mounted = false; };
  }, []);

  const validatePassword = useMemo(() => buildPasswordValidator(policy), [policy]);
  const pwCheck = useMemo(() => validatePassword(password), [validatePassword, password]);

  // 2) 姓名实时匹配（防抖：简单版 setTimeout）
  useEffect(() => {
    const n = nameCN.trim();
    if (!n) {
      setAllowedInfo({ status: 'idle', allowed: false, aliasEN: '', role: '' });
      return;
    }

    setAllowedInfo(prev => ({ ...prev, status: 'loading' }));

    const t = setTimeout(async () => {
      try {
        const res = await api.get('/auth/allowed-info', { params: { name: n } });
        setAllowedInfo({
          status: 'done',
          allowed: !!res.data.allowed,
          aliasEN: res.data.aliasEN || '',
          role: res.data.role || ''
        });
      } catch (e) {
        setAllowedInfo({ status: 'error', allowed: false, aliasEN: '', role: '' });
      }
    }, 250);

    return () => clearTimeout(t);
  }, [nameCN]);

  const pw2Touched = password2.length > 0;
  const pwMatch = password2 === password;

  const canSubmit =
    allowedInfo.allowed &&
    Boolean(email.trim()) &&
    pwCheck.ok &&
    pw2Touched &&
    pwMatch;

  const onSubmit = async (e) => {
    e.preventDefault();
    setMsg('');

    const n = nameCN.trim();

    // 1) 白名单校验（前端提示 + 拦截；后端仍会再校验）
    if (!allowedInfo.allowed) {
      setMsg('该姓名不在允许注册名单中，请联系实验室管理员');
      return;
    }

    // 2) 密码规则
    const check = validatePassword(password);
    if (!check.ok) {
      setMsg(`密码要求：${check.errors.join('，')}`);
      return;
    }

    // 3) 两次一致
    if (!password2) {
      setMsg('请再次确认密码');
      return;
    }
    if (!pwMatch) {
      setMsg('两次输入的密码不一致');
      return;
    }

    try {
      await api.post('/auth/register', {
        name: n,
        email: email.trim(),
        password,
        password2
      });

      setMsg('注册成功，请登录');
      setTimeout(() => navigate('/login'), 600);
    } catch (err) {
      setMsg(err.response?.data?.detail || '注册失败');
    }
  };

  return (
    <AuthShell>
      <div className="card login-card">
        <h2 className="login-title">注册账号</h2>
        <p className="login-subtitle">仅限实验室已授权成员注册</p>

        <form onSubmit={onSubmit}>
          <div className="form-field">
            <label className="form-label">姓名</label>
            <input
              className="form-input"
              placeholder="请输入真实姓名（需在授权名单内）"
              value={nameCN}
              onChange={(e) => {
                setNameCN(e.target.value);
                setMsg('');
              }}
            />

            {nameCN.trim() && (
              <div className="form-hint">
                {allowedInfo.status === 'loading' && '正在校验授权名单...'}
                {allowedInfo.status !== 'loading' && (
                  allowedInfo.allowed
                    ? `已识别：${allowedInfo.aliasEN} · 权限：${allowedInfo.role}`
                    : '未在授权名单中'
                )}
              </div>
            )}
          </div>

          <div className="form-field">
            <label className="form-label">Email</label>
            <input
              className="form-input"
              placeholder="请输入邮箱"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setMsg('');
              }}
            />
          </div>

          <div className="form-field">
            <label className="form-label">密码</label>
            <input
              type="password"
              className="form-input"
              placeholder="至少 6 位，必须包含大小写字母"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setMsg('');
              }}
            />

            {/* ✅ 短提示 + 可展开详情 */}
            {(policy?.allowedHintShort || policy?.allowedDescription) && (
            <div className="form-hint" style={{ marginTop: 6, lineHeight: 1.5 }}>
                <div>
                可用字符：{policy?.allowedHintShort || '（见详情）'}
                {policy?.allowedDescription && (
                    <>
                    {' '}
                    <button
                        type="button"
                        className="inline-link"
                        onClick={() => setShowPwAllowedDetails(v => !v)}
                        style={{ padding: 0 }}
                    >
                        {showPwAllowedDetails ? '收起' : '查看详情'}
                    </button>
                    </>
                )}
                </div>

                {showPwAllowedDetails && policy?.allowedDescription && (
                <div style={{ marginTop: 6 }}>
                    {policy.allowedDescription}
                    {policy?.allowedExample ? `（${policy.allowedExample}）` : ''}
                </div>
                )}
            </div>
            )}

            {/* 持续提示：输入后不满足就一直提示 */}
            {password.length > 0 && !pwCheck.ok && (
              <div className="form-error">
                密码要求：{pwCheck.errors.join('，')}
              </div>
            )}
          </div>

          <div className="form-field">
            <label className="form-label">再次确认密码</label>
            <input
              type="password"
              className="form-input"
              placeholder="请再次输入密码"
              value={password2}
              onChange={(e) => {
                setPassword2(e.target.value);
                setMsg('');
              }}
            />
            {/* 不一致持续提示：直到一致 */}
            {pw2Touched && !pwMatch && (
              <div className="form-error">两次输入的密码不一致</div>
            )}
          </div>

          {msg && <div className="form-error">{msg}</div>}

          <button
            type="submit"
            className="btn btn-primary"
            style={{ width: '100%', marginTop: 8 }}
            disabled={!canSubmit}
          >
            注册
          </button>
        </form>

        <div className="form-footer">
          <span>
            已有帐号？
            <button type="button" className="inline-link" onClick={() => navigate('/login')}>
              立即登录
            </button>
          </span>
        </div>

        <div className="form-hint" style={{ marginTop: 10 }}>
          如果无法注册请联系 <a href="mailto:jbwu@mail.ustc.edu.cn">jbwu@mail.ustc.edu.cn</a>
        </div>
      </div>
    </AuthShell>
  );
}
