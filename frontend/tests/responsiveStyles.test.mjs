import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const sharedStyles = readFileSync(new URL('../src/styles.css', import.meta.url), 'utf8');
const dashboardStyles = readFileSync(new URL('../src/pages/Dashboard.css', import.meta.url), 'utf8');
const competitionComponentStyles = readFileSync(
  new URL('../src/features/competition/components/competitionComponents.css', import.meta.url),
  'utf8',
);

test('mobile authentication layout resets the desktop card offset', () => {
  assert.match(
    sharedStyles,
    /@media\s*\(max-width:\s*720px\)[\s\S]*?\.login-card-wrapper-right\s*\{[\s\S]*?margin-right:\s*0;/,
  );
});

test('dashboard content typography keeps readable minimum sizes', () => {
  assert.match(dashboardStyles, /\.lm-overview-label\s*\{[\s\S]*?font-size:\s*13px;/);
  assert.match(dashboardStyles, /\.lm-shortcut-copy\s+strong\s*\{[\s\S]*?font-size:\s*14px;/);
  assert.match(dashboardStyles, /\.lm-reports-panel\s+\.acad-meta\s*\{[\s\S]*?font-size:\s*12px;/);
});

test('dashboard columns align on desktop and keep natural height when stacked', () => {
  assert.match(
    dashboardStyles,
    /\.lm-dashboard-grid\s*\{[^}]*align-items:\s*stretch;/,
  );
  assert.match(
    dashboardStyles,
    /@media\s*\(max-width:\s*1120px\)[\s\S]*?\.lm-dashboard-grid\s*\{[^}]*align-items:\s*start;/,
  );
});

test('competition table scroller contains its wide mobile table', () => {
  assert.match(
    competitionComponentStyles,
    /\.competition-table-scroll\s*\{[^}]*position:\s*relative;[^}]*width:\s*100%;[^}]*min-width:\s*0;[^}]*overflow-x:\s*auto;/,
  );
});
