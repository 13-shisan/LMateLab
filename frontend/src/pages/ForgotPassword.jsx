// src/pages/ForgotPassword.jsx
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

// sessionStorage keys（避免到处写字符串）
const SS_EMAIL = 'fp_email';
const SS_CODE_SENT = 'fp_codeSent';
const SS_COOLDOWN_UNTIL = 'fp_cooldownUntil';

export default function ForgotPassword() {
  const navigate = useNavigate();

  // 两步：request(同卡片：邮箱+验证码) -> reset(设置新密码)
  const [step, setStep] = useState('request');

  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [codeSent, setCodeSent] = useState(false); // 是否已发送验证码（决定是否允许验证）
  const [resetToken, setResetToken] = useState('');

  const [pw1, setPw1] = useState('');
  const [pw2, setPw2] = useState('');

  const [msg, setMsg] = useState('');
  const [busy, setBusy] = useState(false);

  // 60s 冷却倒计时（支持后端 Retry-After）
  const [cooldown, setCooldown] = useState(0);

  // 密码策略（用于提示；后端仍强校验）
  const [policy, setPolicy] = useState(null);

  const [showPwAllowedDetails, setShowPwAllowedDetails] = useState(false);

  const emailTrim = useMemo(() => email.trim().toLowerCase(), [email]);
  const codeTrim = useMemo(() => code.trim(), [code]);

  const validatePassword = useMemo(() => buildPasswordValidator(policy), [policy]);
  const pwCheck = useMemo(() => validatePassword(pw1), [validatePassword, pw1]);

  const pw2Touched = pw2.length > 0;
  const pwMatch = pw2 === pw1;

  const canReset =
    Boolean(resetToken) &&
    pwCheck.ok &&
    pw2Touched &&
    pwMatch;

  const setCooldownWithPersist = (sec) => {
    const s = Math.max(0, Number(sec) || 0);
    setCooldown(s);
    if (s > 0) {
      const until = Date.now() + s * 1000;
      sessionStorage.setItem(SS_COOLDOWN_UNTIL, String(until));
    } else {
      sessionStorage.removeItem(SS_COOLDOWN_UNTIL);
    }
  };

  // 读取密码策略
  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const res = await api.get('/auth/password-policy');
        if (mounted) setPolicy(res.data);
      } catch (e) {
        if (mounted) setPolicy({ minLength: 6, requireUpper: true, requireLower: true, allowedPattern: '' });
      }
    })();
    return () => { mounted = false; };
  }, []);

  // ✅ 首次加载：恢复 sessionStorage（邮箱、是否已发码、倒计时）
  useEffect(() => {
    const savedEmail = sessionStorage.getItem(SS_EMAIL) || '';
    const savedCodeSent = sessionStorage.getItem(SS_CODE_SENT) === '1';
    const savedUntil = Number(sessionStorage.getItem(SS_COOLDOWN_UNTIL) || '0');

    if (savedEmail) setEmail(savedEmail);
    if (savedCodeSent) setCodeSent(true);

    if (savedUntil && Date.now() < savedUntil) {
      setCooldown(Math.ceil((savedUntil - Date.now()) / 1000));
    } else {
      setCooldown(0);
      sessionStorage.removeItem(SS_COOLDOWN_UNTIL);
    }
  }, []);

  // 倒计时 ticking（并在归零时清理持久化）
  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setInterval(() => {
      setCooldown((s) => {
        const next = s > 0 ? s - 1 : 0;
        if (next <= 0) sessionStorage.removeItem(SS_COOLDOWN_UNTIL);
        return next;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [cooldown]);

  const requestCode = async (e) => {
    e?.preventDefault?.();
    setMsg('');

    if (!emailTrim) {
      setMsg('请输入邮箱');
      return;
    }
    if (cooldown > 0) return;

    setBusy(true);
    try {
      await api.post('/auth/forgot-password/request', { email: emailTrim });

      // 后端防枚举：统一 ok
      setMsg('若该邮箱存在，验证码已发送，请检查邮箱（含垃圾箱）。');

      // ✅ 不切换界面：只是启用验证码输入与验证按钮
      setCodeSent(true);
      sessionStorage.setItem(SS_CODE_SENT, '1');

      // ✅ 启动冷却并持久化
      setCooldownWithPersist(60);
    } catch (err) {
      const ra = Number(err.response?.headers?.['retry-after']);
      if (err.response?.status === 429 && ra > 0) {
        setCooldownWithPersist(ra);
      }
      setMsg(err.response?.data?.detail || '发送验证码失败');
    } finally {
      setBusy(false);
    }
  };

  const verifyCode = async (e) => {
    e?.preventDefault?.();
    setMsg('');

    if (!emailTrim) {
      setMsg('请输入邮箱');
      return;
    }
    if (!codeTrim) {
      setMsg('请输入验证码');
      return;
    }
    if (!codeSent) {
      setMsg('请先发送验证码');
      return;
    }

    setBusy(true);
    try {
      const resp = await api.post('/auth/forgot-password/verify', {
        email: emailTrim,
        code: codeTrim,
      });

      const token = resp.data?.reset_token || '';
      if (!token) {
        setMsg('验证失败：未返回 reset_token');
        return;
      }

      setResetToken(token);
      setMsg('');
      setStep('reset');
    } catch (err) {
      setResetToken('');
      setMsg(err.response?.data?.detail || '验证码验证失败');
    } finally {
      setBusy(false);
    }
  };

  const resetPassword = async (e) => {
    e.preventDefault();
    setMsg('');

    if (!resetToken) {
      setMsg('请先验证验证码');
      return;
    }

    const check = validatePassword(pw1);
    if (!check.ok) {
      setMsg(`密码要求：${check.errors.join('，')}`);
      return;
    }
    if (!pw2Touched) {
      setMsg('请再次确认密码');
      return;
    }
    if (!pwMatch) {
      setMsg('两次输入的新密码不一致');
      return;
    }

    setBusy(true);
    try {
      await api.post('/auth/forgot-password/reset', {
        reset_token: resetToken,
        new_password: pw1,
        new_password2: pw2,
      });

      // 成功后清理状态（包括 sessionStorage）
      sessionStorage.removeItem(SS_CODE_SENT);
      sessionStorage.removeItem(SS_COOLDOWN_UNTIL);

      setMsg('密码已重置成功，请用新密码登录。');
      setTimeout(() => navigate('/login'), 800);
    } catch (err) {
      setMsg(err.response?.data?.detail || '重置密码失败');
    } finally {
      setBusy(false);
    }
  };

  const changeEmail = () => {
    // 允许重新输入邮箱：清理验证码上下文（并解锁邮箱输入框）
    setCode('');
    setCodeSent(false);
    setResetToken('');
    setMsg('');
    setCooldownWithPersist(0);

    sessionStorage.removeItem(SS_CODE_SENT);
    sessionStorage.removeItem(SS_COOLDOWN_UNTIL);
    // SS_EMAIL 不清：方便用户更换时还保留已输入（你也可以清掉）
  };

  const resetAllToRequest = () => {
    setStep('request');
    setEmail('');
    setCode('');
    setCodeSent(false);
    setResetToken('');
    setPw1('');
    setPw2('');
    setMsg('');
    setCooldownWithPersist(0);

    sessionStorage.removeItem(SS_EMAIL);
    sessionStorage.removeItem(SS_CODE_SENT);
    sessionStorage.removeItem(SS_COOLDOWN_UNTIL);
  };

  return (
    <AuthShell>
      <div className="card login-card">
        <h2 className="login-title">忘记密码</h2>

        {/* Step: request（进入页面就显示：邮箱 + 验证码；不做“发送后跳转”） */}
        {step === 'request' && (
          <>
            <p className="login-subtitle">请输入邮箱获取验证码，然后完成验证</p>

            {/* Email */}
            <div className="form-field">
              <label className="form-label">Email</label>
              <input
                className="form-input"
                placeholder="请输入邮箱"
                value={email}
                onChange={(e) => {
                  const v = e.target.value;
                  setEmail(v);
                  sessionStorage.setItem(SS_EMAIL, v);

                  // 改邮箱就清理验证码上下文，避免错配
                  setMsg('');
                  setCode('');
                  setResetToken('');
                  setCodeSent(false);
                  sessionStorage.removeItem(SS_CODE_SENT);

                  setCooldownWithPersist(0);
                }}
                autoComplete="email"
                disabled={busy || codeSent} // ✅ 发码后锁定邮箱，避免 A->B 错配
              />
            </div>

            {/* Send code */}
            <button
              type="button"
              className="btn btn-primary"
              style={{ width: '100%', marginTop: 8 }}
              onClick={requestCode}
              disabled={busy || !emailTrim || cooldown > 0}
            >
              {cooldown > 0
                ? `重新发送（${cooldown}s）`
                : (busy ? '发送中…' : (codeSent ? '重新发送验证码' : '发送验证码'))}
            </button>

            {/* Code (always visible) */}
            <div className="form-field" style={{ marginTop: 12 }}>
              <label className="form-label">验证码（6 位）</label>
              <input
                className="form-input"
                placeholder={codeSent ? '请输入验证码' : '请先发送验证码'}
                value={code}
                onChange={(e) => {
                  setCode(e.target.value);
                  setMsg('');
                }}
                inputMode="numeric"
                disabled={busy || !codeSent}
              />
            </div>

            {/* Verify */}
            <button
              type="button"
              className="btn btn-primary"
              style={{ width: '100%', marginTop: 8 }}
              onClick={verifyCode}
              disabled={busy || !codeSent || !emailTrim || !codeTrim}
            >
              {busy ? '验证中…' : '验证验证码'}
            </button>

            <div className="form-footer" style={{ marginTop: 10 }}>
              <button
                type="button"
                className="inline-link"
                onClick={changeEmail}
                disabled={busy}
              >
                更换邮箱
              </button>
            </div>

            {msg && <div className="form-error" style={{ marginTop: 10 }}>{msg}</div>}
          </>
        )}

        {/* Step: reset */}
        {step === 'reset' && (
          <>
            <p className="login-subtitle">请输入新密码</p>

            <form onSubmit={resetPassword}>
              <div className="form-field">
                <label className="form-label">新密码</label>
                <input
                  className="form-input"
                  type="password"
                  placeholder="请输入新密码"
                  value={pw1}
                  onChange={(e) => {
                    setPw1(e.target.value);
                    setMsg('');
                  }}
                  autoComplete="new-password"
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

                {pw1.length > 0 && !pwCheck.ok && (
                  <div className="form-error">
                    密码要求：{pwCheck.errors.join('，')}
                  </div>
                )}
              </div>

              <div className="form-field">
                <label className="form-label">确认新密码</label>
                <input
                  className="form-input"
                  type="password"
                  placeholder="再次输入新密码"
                  value={pw2}
                  onChange={(e) => {
                    setPw2(e.target.value);
                    setMsg('');
                  }}
                  autoComplete="new-password"
                />
                {pw2Touched && !pwMatch && (
                  <div className="form-error">两次输入的密码不一致</div>
                )}
              </div>

              {msg && <div className="form-error">{msg}</div>}

              <button
                type="submit"
                className="btn btn-primary"
                style={{ width: '100%', marginTop: 8 }}
                disabled={busy || !canReset}
              >
                {busy ? '提交中…' : '重置密码'}
              </button>
            </form>

            <div className="form-footer" style={{ marginTop: 10 }}>
              <button type="button" className="inline-link" onClick={resetAllToRequest}>
                重新开始
              </button>
            </div>
          </>
        )}

        <div className="form-footer">
          <span>
            想起密码了？
            <button type="button" className="inline-link" onClick={() => navigate('/login')}>
              返回登录
            </button>
          </span>
        </div>
      </div>
    </AuthShell>
  );
}
