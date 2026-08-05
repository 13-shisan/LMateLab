import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

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
