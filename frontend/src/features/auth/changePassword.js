function normalizedPolicy(policy = {}) {
  return {
    minLength: Number(policy.minLength) || 6,
    requireUpper: Boolean(policy.requireUpper),
    requireLower: Boolean(policy.requireLower),
    allowedPattern: String(policy.allowedPattern || ''),
    allowedHintShort: String(policy.allowedHintShort || ''),
  };
}


export function describePasswordPolicy(policy) {
  const normalized = normalizedPolicy(policy);
  if (normalized.allowedHintShort) return normalized.allowedHintShort;

  const requirements = [`至少 ${normalized.minLength} 位`];
  if (normalized.requireUpper) requirements.push('包含大写字母');
  if (normalized.requireLower) requirements.push('包含小写字母');
  return requirements.join('，');
}


export function validateChangePasswordForm(form, policy) {
  const currentPassword = String(form.currentPassword || '');
  const newPassword = String(form.newPassword || '');
  const confirmPassword = String(form.confirmPassword || '');
  const normalized = normalizedPolicy(policy);

  if (!currentPassword) return '请输入当前密码';
  if (!newPassword) return '请输入新密码';
  if (!confirmPassword) return '请再次输入新密码';
  if (newPassword !== confirmPassword) return '两次输入的新密码不一致';
  if (currentPassword === newPassword) return '新密码不能与当前密码相同';
  if (newPassword.length < normalized.minLength) {
    return `新密码至少 ${normalized.minLength} 位`;
  }
  if (normalized.requireUpper && !/[A-Z]/.test(newPassword)) {
    return '新密码必须包含大写字母';
  }
  if (normalized.requireLower && !/[a-z]/.test(newPassword)) {
    return '新密码必须包含小写字母';
  }
  if (normalized.allowedPattern) {
    try {
      if (!new RegExp(`^(?:${normalized.allowedPattern})$`).test(newPassword)) {
        return '新密码包含不允许的字符';
      }
    } catch {
      return '密码规则暂时不可用，请稍后重试';
    }
  }
  return '';
}
