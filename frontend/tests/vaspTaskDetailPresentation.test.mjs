import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

import {
  formatTaskValue,
  getTaskFieldPresentation,
} from '../src/pages/db/vasp-detail/vaspTaskDetailPresentation.js';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('VASP task detail uses readable labels and bounded precision', () => {
  assert.deepEqual(getTaskFieldPresentation('energy'), {
    key: 'energy', label: '总能量', unit: 'eV', decimals: 6,
  });
  assert.equal(formatTaskValue('energy', -192.67317127).display, '-192.673171');
  assert.equal(formatTaskValue('fmax', 0.00891234).display, '0.0089');
  assert.equal(formatTaskValue('bandgap_eV', null).display, '-');
});

test('VASP task detail bundles a fixed 3Dmol dependency', () => {
  const html = read('../index.html');
  const packageJson = JSON.parse(read('../package.json'));
  assert.doesNotMatch(html, /3Dmol\.org/i);
  assert.equal(packageJson.dependencies['3dmol'], '2.5.5');
});

test('structure viewer owns canvas bounds and lifecycle', () => {
  const source = read('../src/pages/db/vasp-detail/VaspStructureViewer.jsx');
  const css = read('../src/pages/db/vasp-detail/VaspTaskDetail.css');
  assert.match(source, /import\(['"]3dmol['"]\)/);
  assert.match(source, /ResizeObserver/);
  assert.match(source, /viewer\.clear|innerHTML\s*=\s*['"]{2}/);
  assert.match(css, /\.vasp-structure-viewer\s*\{[^}]*position:\s*relative/s);
  assert.match(css, /\.vasp-structure-viewer\s*\{[^}]*overflow:\s*hidden/s);
  assert.match(css, /@media\s*\(max-width:\s*700px\)/);
});

test('detail components use responsive class-owned grids', () => {
  const summary = read('../src/pages/db/vasp-detail/VaspTaskSummary.jsx');
  const crystal = read('../src/pages/db/vasp-detail/VaspCrystalDetails.jsx');
  const css = read('../src/pages/db/vasp-detail/VaspTaskDetail.css');
  assert.match(summary, /vasp-task-summary/);
  assert.match(crystal, /vasp-crystal-grid/);
  assert.match(css, /\.vasp-task-summary/);
  assert.match(css, /\.vasp-crystal-grid/);
  assert.doesNotMatch(summary + crystal, /gridTemplateColumns/);
});

test('electronic properties load only the active available tab', () => {
  const source = read('../src/pages/db/vasp-detail/VaspElectronicProperties.jsx');
  assert.match(source, /activeTab/);
  assert.match(source, /capabilities\?\.(band_plot|dos_plot)/);
  assert.match(source, /disabled=\{!.*Available/);
  assert.match(source, /该记录没有可用的能带或 DOS 源文件/);
  assert.doesNotMatch(source, /Phonon|待实现/);
});

test('route delegates detail responsibilities and table action is accurate', () => {
  const route = read('../src/pages/db/VaspTaskDetail.jsx');
  const table = read('../src/pages/db/VaspDataTable.jsx');
  assert.match(route, /VaspStructureViewer/);
  assert.match(route, /VaspTaskSummary/);
  assert.match(route, /VaspCrystalDetails/);
  assert.match(route, /VaspElectronicProperties/);
  assert.doesNotMatch(route, /240px 1fr|window\.\$3Dmol|height:\s*460/);
  assert.match(table, />输入参数</);
  assert.doesNotMatch(table, /onOpenParams\(item\)[^<]*>详情</);
});
