import test from 'node:test';
import assert from 'node:assert/strict';
import { PERIODIC_TABLE_ELEMENTS } from '../src/pages/db/periodicTableElements.js';
import { matchesElementSelection, toggleElementSelection } from '../src/utils/elementSelection.js';

test('periodic table contains each atomic number exactly once', () => {
  assert.equal(PERIODIC_TABLE_ELEMENTS.length, 118);
  assert.deepEqual(PERIODIC_TABLE_ELEMENTS.map((item) => item.Z), Array.from({ length: 118 }, (_, index) => index + 1));
  assert.deepEqual(PERIODIC_TABLE_ELEMENTS.find((item) => item.symbol === 'Mo'), { Z: 42, symbol: 'Mo', name: 'Molybdenum', row: 5, col: 6 });
});

test('selection toggles without duplicates', () => {
  assert.deepEqual(toggleElementSelection(['Mo'], 'S'), ['Mo', 'S']);
  assert.deepEqual(toggleElementSelection(['Mo', 'S'], 'Mo'), ['S']);
});

test('element matching distinguishes at-least from only', () => {
  assert.equal(matchesElementSelection(['Mo', 'S'], ['Mo'], 'at_least'), true);
  assert.equal(matchesElementSelection(['Mo', 'S'], ['Mo'], 'only'), false);
  assert.equal(matchesElementSelection(['Mo', 'S'], ['S', 'Mo'], 'only'), true);
});
