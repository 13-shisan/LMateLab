import { useEffect, useId, useState } from 'react';
import { Eye, EyeOff, KeyRound, X } from 'lucide-react';

import api from '../../api/client';
import { clearAuthState } from '../../api/auth';
import { describePasswordPolicy, validateChangePasswordForm } from './changePassword';
import './ChangePasswordDialog.css';


const EMPTY_FORM = {
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
};


function apiErrorMessage(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => item?.msg).filter(Boolean);
    if (messages.length) return messages.join('；');
  }
  return error?.message || '密码修改失败，请稍后重试';
}


function PasswordField({ autoFocus, autoComplete, label, name, onChange, value }) {
  const [revealed, setRevealed] = useState(false);

  return (
    <label className="change-password-field">
      <span>{label}</span>
      <div className="change-password-input-wrap">
        <input
          autoFocus={autoFocus}
          autoComplete={autoComplete}
          name={name}
          onChange={onChange}
          required
          type={revealed ? 'text' : 'password'}
          value={value}
        />
        <button
          type="button"
          onClick={() => setRevealed((current) => !current)}
          aria-label={revealed ? `隐藏${label}` : `显示${label}`}
          title={revealed ? `隐藏${label}` : `显示${label}`}
        >
          {revealed ? <EyeOff size={17} /> : <Eye size={17} />}
        </button>
      </div>
    </label>
  );
}


export default function ChangePasswordDialog({ onClose }) {
  const titleId = useId();
  const [form, setForm] = useState(EMPTY_FORM);
  const [policy, setPolicy] = useState(null);
  const [policyError, setPolicyError] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    const previousBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    api.get('/auth/password-policy')
      .then((response) => {
        if (active) setPolicy(response.data);
      })
      .catch(() => {
        if (active) setPolicyError('无法读取密码规则，请关闭后重试');
      });

    const onKeyDown = (event) => {
      if (event.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => {
      active = false;
      document.body.style.overflow = previousBodyOverflow;
      document.removeEventListener('keydown', onKeyDown);
    };
  }, [onClose]);

  const updateField = (event) => {
    const { name, value } = event.target;
    setForm((current) => ({ ...current, [name]: value }));
    setError('');
  };

  const close = () => {
    if (!submitting) onClose();
  };

  const submit = async (event) => {
    event.preventDefault();
    if (submitting) return;
    if (!policy) {
      setError(policyError || '密码规则正在加载，请稍候');
      return;
    }

    const validationError = validateChangePasswordForm(form, policy);
    if (validationError) {
      setError(validationError);
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      await api.post('/auth/change-password', {
        current_password: form.currentPassword,
        new_password: form.newPassword,
        new_password2: form.confirmPassword,
      });
      setForm(EMPTY_FORM);
      clearAuthState();
      window.location.assign('/login?passwordChanged=1');
    } catch (requestError) {
      setError(apiErrorMessage(requestError));
      setSubmitting(false);
    }
  };

  return (
    <div className="change-password-backdrop" onMouseDown={close}>
      <section
        className="change-password-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header>
          <div className="change-password-heading">
            <span className="change-password-heading-icon"><KeyRound size={19} /></span>
            <div>
              <h2 id={titleId}>修改密码</h2>
              <p>修改成功后，所有已登录设备都需要重新登录。</p>
            </div>
          </div>
          <button
            className="change-password-close"
            type="button"
            onClick={close}
            disabled={submitting}
            aria-label="关闭修改密码窗口"
            title="关闭"
          >
            <X size={19} />
          </button>
        </header>

        <form onSubmit={submit}>
          <PasswordField
            autoFocus
            autoComplete="current-password"
            label="当前密码"
            name="currentPassword"
            onChange={updateField}
            value={form.currentPassword}
          />
          <PasswordField
            autoComplete="new-password"
            label="新密码"
            name="newPassword"
            onChange={updateField}
            value={form.newPassword}
          />
          <PasswordField
            autoComplete="new-password"
            label="确认新密码"
            name="confirmPassword"
            onChange={updateField}
            value={form.confirmPassword}
          />

          <p className={`change-password-policy${policyError ? ' is-error' : ''}`}>
            {policyError || (policy ? describePasswordPolicy(policy) : '正在读取密码规则...')}
          </p>
          {error ? <div className="change-password-error" role="alert">{error}</div> : null}

          <footer>
            <button className="change-password-cancel" type="button" onClick={close} disabled={submitting}>
              取消
            </button>
            <button className="change-password-submit" type="submit" disabled={submitting || !policy}>
              <KeyRound size={16} />
              <span>{submitting ? '正在修改...' : '确认修改'}</span>
            </button>
          </footer>
        </form>
      </section>
    </div>
  );
}
