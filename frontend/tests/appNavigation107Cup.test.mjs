import test from 'node:test';
import assert from 'node:assert/strict';

import * as navigation from '../src/config/appNavigation.js';

test('107 cup edition exposes only the competition dashboard', () => {
  assert.equal(typeof navigation.navigationGroupsForEdition, 'function');

  const groups = navigation.navigationGroupsForEdition('107cup');
  const keys = groups.flatMap((group) => group.items.map((item) => item.key));

  assert.deepEqual(keys, ['dashboard']);

  for (const disabled of [
    'tasks',
    'journal',
    'db-group',
    'db-personal',
    'db-personal-vasp',
    'db-personal-qe-epw',
    'servers',
    'server-users',
    'papers-daily',
    'papers-subscription',
    'papers-library',
    'academic-reports',
    'agents-entry',
    'general-chat',
    'platform-guide',
  ]) {
    assert.equal(keys.includes(disabled), false, `${disabled} should be hidden`);
  }

  assert.equal(groups.every((group) => group.items.length > 0), true);

  const shortcuts = navigation.dashboardShortcutsForEdition('107cup');
  assert.deepEqual(shortcuts, []);
});
