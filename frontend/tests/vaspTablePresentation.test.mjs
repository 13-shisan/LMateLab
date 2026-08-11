import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { parse } from '@babel/parser';

import {
  compactSourcePath,
  formatVaspValue,
  getVaspColumnPresentation,
} from '../src/pages/db/vaspTablePresentation.js';

test('VASP columns use readable labels and scientific units', () => {
  assert.deepEqual(
    getVaspColumnPresentation('energy'),
    { key: 'energy', label: '总能量', unit: 'eV', decimals: 6, kind: 'number', priority: 1 },
  );
  assert.equal(getVaspColumnPresentation('data.source_dir').label, '计算目录');
});

test('VASP values use bounded precision without losing raw value', () => {
  assert.equal(formatVaspValue('fmax', 0.0028036869507132925).display, '0.0028');
  assert.equal(formatVaspValue('energy', -549.9697138700001).display, '-549.969714');
  assert.equal(formatVaspValue('data.phys_bandgap_eV', null).display, '-');
  assert.equal(formatVaspValue('energy', -549.9697138700001).raw, '-549.9697138700001');
});

test('source paths keep the informative tail', () => {
  assert.equal(
    compactSourcePath('/storage/Pwjb/Dawn4/project/material/relax/final'),
    '.../material/relax/final',
  );
});

test('VASP task surface does not restore fixed-height row clipping', () => {
  const pageSource = readFileSync(new URL('../src/pages/db/PersonalVaspDatabase.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(pageSource, /TABLE_ROW_H|TABLE_HEAD_H/);
  assert.doesNotMatch(pageSource, /height:\s*TABLE_HEAD_H\s*\+\s*tasksPageSize/);
});

test('read-only table core is separate from legacy mutations', () => {
  const core = readFileSync(new URL('../src/pages/db/VaspRecordTable.jsx', import.meta.url), 'utf8');
  const wrapper = readFileSync(new URL('../src/pages/db/VaspDataTable.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(core, /收藏|移除|onCollect|onRemove|customDbs/);
  assert.match(core, /detailPathForItem/);
  assert.match(core, /mobileMode/);
  assert.match(core, /is-mobile-scroll/);
  assert.match(wrapper, /VaspRecordTable/);
  assert.match(wrapper, /RowActions/);
});

test('selectable records isolate nested controls and support keyboard activation', () => {
  const core = readFileSync(new URL('../src/pages/db/VaspRecordTable.jsx', import.meta.url), 'utf8');
  const css = readFileSync(new URL('../src/pages/db/VaspDataTable.css', import.meta.url), 'utf8');
  const ast = parse(core, { sourceType: 'module', plugins: ['jsx'] });
  const selector = ast.program.body.find((node) => (
    node.type === 'VariableDeclaration'
      && node.declarations.some((declaration) => declaration.id?.name === 'INTERACTIVE_TARGET_SELECTOR')
  ));
  const helper = ast.program.body.find((node) => (
    node.type === 'FunctionDeclaration' && node.id?.name === 'handleRecordInteraction'
  ));

  assert.ok(selector, 'VaspRecordTable must define INTERACTIVE_TARGET_SELECTOR');
  assert.ok(helper, 'VaspRecordTable must define handleRecordInteraction');
  const loadHelper = new Function(
    `${core.slice(selector.start, selector.end)}\n${core.slice(helper.start, helper.end)}\n`
      + 'return { INTERACTIVE_TARGET_SELECTOR, handleRecordInteraction };',
  );
  const { INTERACTIVE_TARGET_SELECTOR, handleRecordInteraction } = loadHelper();
  const interactiveTargets = new Set(INTERACTIVE_TARGET_SELECTOR.split(',').map((target) => target.trim()));
  for (const interactiveTarget of ['a', 'button', 'input', 'select', 'textarea', 'summary', '[role="button"]', '[role="link"]']) {
    assert.equal(interactiveTargets.has(interactiveTarget), true, `missing selector for ${interactiveTarget}`);
  }

  const item = { formula: 'MoS2', id: 7 };
  const selected = [];
  const onSelect = (selectedItem) => selected.push(selectedItem);
  const container = {};
  const nestedControl = {
    closest: (selectorText) => {
      assert.equal(selectorText, INTERACTIVE_TARGET_SELECTOR);
      return {};
    },
  };
  handleRecordInteraction({ type: 'click', currentTarget: container, target: nestedControl }, onSelect, item);
  assert.deepEqual(selected, [], 'nested controls must not select their record');

  const nestedText = { closest: () => null };
  handleRecordInteraction({ type: 'click', currentTarget: container, target: nestedText }, onSelect, item);
  handleRecordInteraction({ type: 'click', currentTarget: container, target: container }, onSelect, item);
  assert.deepEqual(selected, [item, item], 'record background and nested non-controls must select');

  let prevented = 0;
  const keyboardEvent = (key, target = container) => ({
    type: 'keydown',
    key,
    currentTarget: container,
    target,
    preventDefault: () => { prevented += 1; },
  });
  handleRecordInteraction(keyboardEvent('Enter'), onSelect, item);
  handleRecordInteraction(keyboardEvent(' '), onSelect, item);
  handleRecordInteraction(keyboardEvent('Escape'), onSelect, item);
  handleRecordInteraction(keyboardEvent('Enter', nestedControl), onSelect, item);
  assert.deepEqual(selected, [item, item, item, item]);
  assert.equal(prevented, 2, 'Enter and Space must prevent their native container behavior');

  assert.match(core, /onClick:\s*\(event\) => handleRecordInteraction\(event, onSelect, item\)/);
  assert.match(core, /onKeyDown:\s*\(event\) => handleRecordInteraction\(event, onSelect, item\)/);
  assert.doesNotMatch(core, /role:\s*['"]button['"]/);
  assert.match(core, /if \(typeof onSelect !== 'function'\) return \{\};/);
  assert.match(core, /['"]aria-label['"]:\s*accessibleLabelForItem\(item\)/);
  assert.match(core, /tabIndex:\s*0/);
  assert.match(css, /\.vasp-data-table tbody tr\[tabindex="0"\]:focus-visible/);
  assert.match(css, /\.vasp-mobile-record\[tabindex="0"\]:focus-visible/);
});
