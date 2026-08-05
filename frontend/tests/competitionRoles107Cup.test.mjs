import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const accessUrl = new URL('../src/config/competitionAccess.js', import.meta.url);

test('competition role helpers fail closed for legacy roles', async () => {
  assert.equal(existsSync(accessUrl), true, 'competitionAccess.js must exist');
  if (!existsSync(accessUrl)) return;

  const access = await import(accessUrl);
  assert.equal(access.isCompetitionRole('operator'), true);
  assert.equal(access.isCompetitionRole('viewer'), true);
  for (const role of ['root', 'user', '', null, undefined]) {
    assert.equal(access.isCompetitionRole(role), false, String(role));
  }
  assert.equal(access.canWriteCompetitionData({ role: 'operator' }), true);
  assert.equal(access.canWriteCompetitionData({ role: 'viewer' }), false);
  assert.equal(access.registrationEnabledForEdition('107cup'), false);
  assert.equal(access.passwordResetEnabledForEdition('107cup'), false);
});

test('107 cup UI removes registration and unrelated dashboard surfaces', () => {
  const competitionApp = readFileSync(new URL('../src/App107Cup.jsx', import.meta.url), 'utf8');
  const login = readFileSync(new URL('../src/pages/Login.jsx', import.meta.url), 'utf8');
  const dashboard = readFileSync(new URL('../src/pages/Dashboard.jsx', import.meta.url), 'utf8');
  const requireAuth = readFileSync(new URL('../src/routes/RequireAuth.jsx', import.meta.url), 'utf8');
  const appShell = readFileSync(new URL('../src/components/AppShell.jsx', import.meta.url), 'utf8');

  assert.doesNotMatch(competitionApp, /Register|ForgotPassword/);
  assert.match(competitionApp, /path="\/dashboard"/);
  assert.match(login, /registrationEnabledForEdition/);
  assert.match(login, /passwordResetEnabledForEdition/);
  assert.match(dashboard, /CompetitionDashboard/);
  assert.match(requireAuth, /isCompetitionRole/);
  assert.match(appShell, /roleLabel/);
  assert.match(appShell, /activeEdition/);
});

test('107 cup build uses a dedicated route entry without unrelated pages', () => {
  const competitionAppUrl = new URL('../src/App107Cup.jsx', import.meta.url);
  assert.equal(existsSync(competitionAppUrl), true, 'App107Cup.jsx must exist');
  if (!existsSync(competitionAppUrl)) return;

  const competitionApp = readFileSync(competitionAppUrl, 'utf8');
  const main = readFileSync(new URL('../src/main.jsx', import.meta.url), 'utf8');
  const vite = readFileSync(new URL('../vite.config.js', import.meta.url), 'utf8');

  assert.match(main, /@lmatelab-app/);
  assert.match(vite, /VITE_LMATELAB_EDITION/);
  assert.match(vite, /App107Cup\.jsx/);
  for (const unrelated of [
    'Register',
    'ForgotPassword',
    'AcademicReports',
    'AgentEntry',
    'PersonalVaspDatabase',
    'NotesJournal',
  ]) {
    assert.equal(competitionApp.includes(unrelated), false, unrelated);
  }
});
