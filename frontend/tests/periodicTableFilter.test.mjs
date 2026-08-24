import test, { after, before } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createServer } from 'vite';
import { PERIODIC_TABLE_ELEMENTS } from '../src/pages/db/periodicTableElements.js';
import { matchesElementSelection, toggleElementSelection } from '../src/utils/elementSelection.js';

let PeriodicTableFilter;
let vite;

before(async () => {
  vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'silent' });
  ({ default: PeriodicTableFilter } = await vite.ssrLoadModule('/src/pages/db/PeriodicTableFilter.jsx'));
});

after(async () => {
  await vite?.close();
});

function collectElements(node, predicate, matches = []) {
  if (Array.isArray(node)) {
    node.forEach((child) => collectElements(child, predicate, matches));
    return matches;
  }
  if (!node || typeof node !== 'object' || !node.props) return matches;
  if (predicate(node)) matches.push(node);
  collectElements(node.props.children, predicate, matches);
  return matches;
}

function elementText(node) {
  if (Array.isArray(node)) return node.map(elementText).join('');
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  return node?.props ? elementText(node.props.children) : '';
}

function renderFilter(overrides = {}) {
  return PeriodicTableFilter({
    availableElements: ['Mo', 'S'],
    selectedElements: ['Mo'],
    mode: 'only',
    onSelectionChange: () => {},
    onModeChange: () => {},
    ...overrides,
  });
}

test('periodic table contains each atomic number exactly once', () => {
  assert.equal(PERIODIC_TABLE_ELEMENTS.length, 118);
  assert.deepEqual(PERIODIC_TABLE_ELEMENTS.map((item) => item.Z), Array.from({ length: 118 }, (_, index) => index + 1));
  assert.deepEqual(PERIODIC_TABLE_ELEMENTS.find((item) => item.symbol === 'Mo'), { Z: 42, symbol: 'Mo', name: 'Molybdenum', row: 5, col: 6 });
});

test('periodic table freezes every element entry', () => {
  assert.equal(PERIODIC_TABLE_ELEMENTS.every(Object.isFrozen), true);
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

test('rendered filter exposes accessible mode and selection state', () => {
  const tree = renderFilter();
  const groups = collectElements(tree, (node) => node.props.role === 'group');
  const buttons = collectElements(tree, (node) => node.type === 'button');
  const buttonByText = (text) => buttons.find((button) => elementText(button) === text);
  const elementBySymbol = (symbol) => buttons.find((button) => button.props.title?.includes(`(${symbol}, Z=`));

  assert.equal(groups.find((group) => group.props['aria-label'] === '元素匹配模式')?.props.role, 'group');
  assert.equal(buttonByText('至少含有所选元素').props['aria-pressed'], false);
  assert.equal(buttonByText('只含所选元素').props['aria-pressed'], true);
  assert.equal(buttons.find((button) => button.props.title === '移除 Mo').props['aria-label'], '移除 Mo');

  assert.match(elementBySymbol('Mo').props.className, /is-present/);
  assert.match(elementBySymbol('Mo').props.className, /is-selected/);
  assert.equal(elementBySymbol('Mo').props['aria-pressed'], true);
  assert.match(elementBySymbol('S').props.className, /is-present/);
  assert.doesNotMatch(elementBySymbol('H').props.className, /is-present/);
});

test('rendered filter delegates every controlled action', () => {
  const selections = [];
  const modes = [];
  const tree = renderFilter({
    onSelectionChange: (next) => selections.push(next),
    onModeChange: (next) => modes.push(next),
  });
  const buttons = collectElements(tree, (node) => node.type === 'button');
  const buttonByText = (text) => buttons.find((button) => elementText(button) === text);

  buttonByText('至少含有所选元素').props.onClick();
  buttonByText('只含所选元素').props.onClick();
  buttonByText('清空选择').props.onClick();
  buttons.find((button) => button.props.title === '移除 Mo').props.onClick();
  buttons.find((button) => button.props.title?.includes('(S, Z=')).props.onClick();

  assert.deepEqual(modes, ['at_least', 'only']);
  assert.deepEqual(selections, [[], [], ['Mo', 'S']]);
});

test('rendered filter composes optional toolbar content and delegates a full reset', () => {
  const resets = [];
  const tree = renderFilter({
    toolbarContent: 'SEARCH_CONTROL',
    onReset: () => resets.push('reset'),
    resetDisabled: false,
    resetLabel: '重置筛选',
  });
  const toolbar = collectElements(
    tree,
    (node) => typeof node.props.className === 'string'
      && node.props.className.includes('vasp-periodic-toolbar'),
  )[0];
  const resetButton = collectElements(
    toolbar,
    (node) => node.type === 'button' && elementText(node) === '重置筛选',
  )[0];
  const toolbarText = elementText(toolbar);

  assert.match(toolbar.props.className, /has-content/);
  assert.ok(toolbarText.indexOf('至少含有所选元素') < toolbarText.indexOf('SEARCH_CONTROL'));
  assert.ok(toolbarText.indexOf('SEARCH_CONTROL') < toolbarText.indexOf('重置筛选'));
  assert.equal(resetButton.props.disabled, false);
  resetButton.props.onClick();
  assert.deepEqual(resets, ['reset']);
});

test('filter owns safe horizontal overflow alignment', () => {
  const css = readFileSync(new URL('../src/pages/db/PeriodicTableFilter.css', import.meta.url), 'utf8');
  const block = css.match(/\.vasp-periodic-filter \.vasp-periodic-scroll\s*\{([^}]*)\}/s)?.[1] || '';

  assert.match(block, /display:\s*flex/);
  assert.match(block, /overflow-x:\s*auto/);
  assert.match(block, /justify-content:\s*safe center/);
  assert.match(
    css,
    /@media\s*\(max-width:\s*700px\)\s*\{[\s\S]*?\.vasp-periodic-filter \.vasp-periodic-scroll\s*\{[^}]*justify-content:\s*flex-start/s,
  );
  assert.match(css, /\.vasp-periodic-toolbar-content\s*\{[^}]*flex:\s*0\s+1\s+480px/s);
  assert.match(
    css,
    /@media\s*\(max-width:\s*700px\)\s*\{[\s\S]*?\.vasp-periodic-toolbar\.has-content\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+auto/s,
  );
});
