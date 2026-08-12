import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import { parse } from '@babel/parser';

const accessUrl = new URL('../src/config/competitionAccess.js', import.meta.url);

function findAstNodes(value, predicate, matches = []) {
  if (value === null || typeof value !== 'object') return matches;
  if (predicate(value)) matches.push(value);
  for (const child of Object.values(value)) {
    if (Array.isArray(child)) {
      for (const entry of child) findAstNodes(entry, predicate, matches);
    } else {
      findAstNodes(child, predicate, matches);
    }
  }
  return matches;
}

function jsxElementName(node) {
  return node?.openingElement?.name?.type === 'JSXIdentifier'
    ? node.openingElement.name.name
    : '';
}

function jsxAttribute(node, name) {
  return node?.openingElement?.attributes?.find((attribute) => (
    attribute.type === 'JSXAttribute' && attribute.name?.name === name
  ));
}

function routeElementComponentName(node) {
  const expression = jsxAttribute(node, 'element')?.value?.expression;
  return expression?.type === 'JSXElement' ? jsxElementName(expression) : '';
}

function routePath(node) {
  const value = jsxAttribute(node, 'path')?.value;
  return value?.type === 'StringLiteral' ? value.value : null;
}

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
  assert.match(competitionApp, /CompetitionDataProvider/);
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

test('107 cup entry atomically exposes exactly seven protected preview routes', () => {
  const competitionApp = readFileSync(new URL('../src/App107Cup.jsx', import.meta.url), 'utf8');
  const ast = parse(competitionApp, { sourceType: 'module', plugins: ['jsx'] });
  const lazyPages = [...competitionApp.matchAll(
    /const\s+(\w+)\s*=\s*lazy\(\(\)\s*=>\s*import\(/g,
  )].map((match) => match[1]);
  const protectedContainers = findAstNodes(ast, (node) => (
    node.type === 'JSXElement'
    && jsxElementName(node) === 'Route'
    && routeElementComponentName(node) === 'ProtectedCompetitionShell'
  ));
  assert.equal(protectedContainers.length, 1);
  const protectedRoutes = protectedContainers[0].children.filter((node) => (
    node.type === 'JSXElement' && jsxElementName(node) === 'Route'
  ));
  const protectedPaths = protectedRoutes.map(routePath);

  assert.deepEqual(lazyPages, [
    'Login',
    'CompetitionDashboard',
    'CompetitionNewCalculation',
    'CompetitionWorkflows',
    'CompetitionWorkflowDetail',
    'CompetitionResults',
    'CompetitionResultDetail',
    'CompetitionVaspDatabase',
  ]);
  assert.deepEqual(protectedPaths, [
    '/dashboard',
    '/dashboard/calculations/new',
    '/dashboard/workflows',
    '/dashboard/workflows/:workflowId',
    '/dashboard/results',
    '/dashboard/results/:workflowId',
    '/dashboard/database/vasp',
  ]);
  assert.equal(protectedRoutes.length, 7);
  assert.equal(protectedPaths.every((path) => path?.startsWith('/dashboard')), true);
  assert.match(
    competitionApp,
    /function\s+ProtectedCompetitionShell\(\)[\s\S]*?<RequireAuth>[\s\S]*?<CompetitionDataProvider>[\s\S]*?<AppShell\s*\/>/,
  );
  assert.match(competitionApp, /<Route\s+path="\*"\s+element=\{<Navigate\s+to="\/dashboard"\s+replace\s*\/>\}/);
  assert.doesNotMatch(
    competitionApp,
    /import\(['"]\.\/pages\/(?:Dashboard(?:\.jsx)?|PersonalVaspDatabase|AcademicReports|Agent|Notes|ServerMonitor)/,
  );
});

test('107 cup shell renders the compact demo build marker and route icons', () => {
  const source = readFileSync(new URL('../src/components/AppShell.jsx', import.meta.url), 'utf8');
  const styles = readFileSync(new URL('../src/components/AppShell.css', import.meta.url), 'utf8');

  for (const icon of ['SquarePlus', 'Workflow', 'ChartNoAxesCombined']) {
    assert.match(source, new RegExp(`\\b${icon}\\b`));
  }
  assert.match(
    source,
    /const\s+competitionDemo\s*=\s*activeEdition\s*===\s*['"]107cup['"]\s*&&\s*import\.meta\.env\.VITE_COMPETITION_DATA_MODE\s*===\s*['"]demo['"]/,
  );
  assert.match(source, /className="lm-demo-build-badge"/);
  assert.match(source, /title="此发布只使用版本控制内的演示数据"/);
  assert.match(source, />演示数据<\/span>/);
  assert.match(styles, /\.lm-demo-build-badge\s*\{/);
  assert.match(styles, /@media\s*\(max-width:\s*420px\)[\s\S]*?\.lm-demo-build-badge/);
});
