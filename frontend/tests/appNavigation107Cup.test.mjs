import test from 'node:test';
import assert from 'node:assert/strict';

import * as navigation from '../src/config/appNavigation.js';

test('107 cup edition exposes only the five focused competition entrances', () => {
  const groups = navigation.navigationGroupsForEdition('107cup');
  assert.deepEqual(groups.flatMap((group) => group.items.map((item) => [
    item.key,
    item.path,
    item.icon,
  ])), [
    ['dashboard', '/dashboard', 'LayoutDashboard'],
    ['competition-new', '/dashboard/calculations/new', 'SquarePlus'],
    ['competition-workflows', '/dashboard/workflows', 'Workflow'],
    ['competition-results', '/dashboard/results', 'ChartNoAxesCombined'],
    ['competition-vasp-db', '/dashboard/database/vasp', 'Database'],
  ]);
});

test('107 cup navigation keeps detail routes owned by their list entries', () => {
  const items = navigation.navigationGroupsForEdition('107cup')
    .flatMap((group) => group.items);
  const workflows = items.find((item) => item.key === 'competition-workflows');
  const results = items.find((item) => item.key === 'competition-results');

  assert.deepEqual(workflows.activePrefixes, ['/dashboard/workflows/']);
  assert.deepEqual(results.activePrefixes, ['/dashboard/results/']);
  assert.equal(navigation.dashboardShortcutsForEdition('107cup').length, 0);
});
