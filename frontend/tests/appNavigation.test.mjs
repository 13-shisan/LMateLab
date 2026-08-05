import test from 'node:test';
import assert from 'node:assert/strict';

import {
  getPageMeta,
  isNavigationItemActive,
  navigationGroups,
} from '../src/config/appNavigation.js';

test('dashboard is active only on the dashboard index route', () => {
  const dashboard = navigationGroups[0].items[0];
  assert.equal(isNavigationItemActive('/dashboard', dashboard), true);
  assert.equal(isNavigationItemActive('/dashboard/db/group', dashboard), false);
});

test('personal database entry does not shadow its specialized children', () => {
  const databaseItems = navigationGroups.find((group) => group.key === 'database').items;
  const personal = databaseItems.find((item) => item.key === 'db-personal');
  const vasp = databaseItems.find((item) => item.key === 'db-personal-vasp');

  assert.equal(isNavigationItemActive('/dashboard/db/personal', personal), true);
  assert.equal(isNavigationItemActive('/dashboard/db/personal/vasp', personal), false);
  assert.equal(isNavigationItemActive('/dashboard/db/personal/vasp', vasp), true);
});

test('database task detail routes activate their corresponding database item', () => {
  const databaseItems = navigationGroups.find((group) => group.key === 'database').items;
  const vasp = databaseItems.find((item) => item.key === 'db-personal-vasp');
  const qeEpw = databaseItems.find((item) => item.key === 'db-personal-qe-epw');

  assert.equal(isNavigationItemActive('/dashboard/db/vasp/task/private/42', vasp), true);
  assert.equal(isNavigationItemActive('/dashboard/db/qe-epw/task/private/17', qeEpw), true);
});

test('page metadata follows the most specific matching navigation item', () => {
  assert.deepEqual(getPageMeta('/dashboard/papers/library'), {
    title: '文献库',
    description: '检索与管理组内文献',
  });
  assert.equal(getPageMeta('/dashboard/unknown').title, '科研工作台');
});
