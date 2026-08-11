import test from 'node:test';
import assert from 'node:assert/strict';

import * as navigation from '../src/config/appNavigation.js';

test('107 cup edition exposes only the focused competition route', () => {
  const groups = navigation.navigationGroupsForEdition('107cup');
  assert.deepEqual(groups.flatMap((group) => group.items.map((item) => [item.key, item.path])), [
    ['dashboard', '/dashboard'],
    ['competition-new', '/dashboard/calculations/new'],
    ['competition-workflows', '/dashboard/workflows'],
    ['competition-results', '/dashboard/results'],
    ['competition-vasp-db', '/dashboard/database/vasp'],
  ]);
});
