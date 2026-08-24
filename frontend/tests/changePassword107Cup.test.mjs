import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

import {
  describePasswordPolicy,
  validateChangePasswordForm,
} from '../src/features/auth/changePassword.js';


const validPolicy = {
  minLength: 10,
  requireUpper: true,
  requireLower: true,
  allowedPattern: '[A-Za-z0-9!@#$%^&*()_+\\-=.]+',
  allowedHintShort: '至少10位，包含大小写字母',
};


test('change-password validation mirrors the server policy and confirmation rules', () => {
  assert.equal(
    validateChangePasswordForm({
      currentPassword: '',
      newPassword: 'ChangedPassword2!',
      confirmPassword: 'ChangedPassword2!',
    }, validPolicy),
    '请输入当前密码',
  );
  assert.equal(
    validateChangePasswordForm({
      currentPassword: 'CurrentPassword1!',
      newPassword: 'short',
      confirmPassword: 'short',
    }, validPolicy),
    '新密码至少 10 位',
  );
  assert.equal(
    validateChangePasswordForm({
      currentPassword: 'CurrentPassword1!',
      newPassword: 'ChangedPassword2!',
      confirmPassword: 'DifferentPassword3!',
    }, validPolicy),
    '两次输入的新密码不一致',
  );
  assert.equal(
    validateChangePasswordForm({
      currentPassword: 'CurrentPassword1!',
      newPassword: 'CurrentPassword1!',
      confirmPassword: 'CurrentPassword1!',
    }, validPolicy),
    '新密码不能与当前密码相同',
  );
  assert.equal(
    validateChangePasswordForm({
      currentPassword: 'CurrentPassword1!',
      newPassword: 'ChangedPassword2!',
      confirmPassword: 'ChangedPassword2!',
    }, validPolicy),
    '',
  );
  assert.equal(describePasswordPolicy(validPolicy), '至少10位，包含大小写字母');
});


test('competition shell exposes authenticated password change and forces re-login on success', () => {
  const dialogUrl = new URL('../src/features/auth/ChangePasswordDialog.jsx', import.meta.url);
  assert.equal(existsSync(dialogUrl), true, 'ChangePasswordDialog.jsx must exist');
  if (!existsSync(dialogUrl)) return;

  const dialog = readFileSync(dialogUrl, 'utf8');
  const shell = readFileSync(new URL('../src/components/AppShell.jsx', import.meta.url), 'utf8');
  const login = readFileSync(new URL('../src/pages/Login.jsx', import.meta.url), 'utf8');
  const styles = readFileSync(new URL('../src/features/auth/ChangePasswordDialog.css', import.meta.url), 'utf8');

  assert.match(shell, /competitionEdition[\s\S]*?修改密码/);
  assert.match(shell, /<ChangePasswordDialog/);
  assert.match(dialog, /role="dialog"/);
  assert.match(dialog, /aria-modal="true"/);
  assert.match(dialog, /api\.get\(['"]\/auth\/password-policy['"]\)/);
  assert.match(dialog, /api\.post\(['"]\/auth\/change-password['"]/);
  assert.match(dialog, /clearAuthState\(\)/);
  assert.match(dialog, /\/login\?passwordChanged=1/);
  assert.match(login, /passwordChanged/);
  assert.match(login, /密码已修改，请使用新密码登录/);
  assert.match(styles, /@media\s*\(max-width:\s*640px\)/);
  assert.doesNotMatch(dialog, /localStorage\.setItem|sessionStorage\.setItem|console\./);
});
