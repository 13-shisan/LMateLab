import test from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';

const sourceUrl = new URL('../src/pages/competition/CompetitionHome.jsx', import.meta.url);
const stylesUrl = new URL('../src/pages/competition/CompetitionHome.css', import.meta.url);
const springUrl = new URL('../src/assets/107cup/campus-spring.webp', import.meta.url);
const summerUrl = new URL('../src/assets/107cup/campus-summer.webp', import.meta.url);
const lakeUrl = new URL('../src/assets/107cup/campus-lake.webp', import.meta.url);
const winterUrl = new URL('../src/assets/107cup/campus-winter.webp', import.meta.url);

test('107 cup exposes a public competition-specific home before login', () => {
  const app = readFileSync(new URL('../src/App107Cup.jsx', import.meta.url), 'utf8');
  const authShell = readFileSync(new URL('../src/components/AuthShell.jsx', import.meta.url), 'utf8');

  assert.match(app, /const\s+CompetitionHome\s*=\s*lazy\(\(\)\s*=>\s*import\(['"]\.\/pages\/competition\/CompetitionHome['"]\)\)/);
  assert.match(app, /<Route\s+path="\/"\s+element=\{<CompetitionHome\s*\/>\}\s*\/>/);
  assert.doesNotMatch(app, /path="\/"\s+element=\{<Navigate\s+to="\/login"/);
  assert.match(authShell, /activeEdition\s*===\s*['"]107cup['"]\s*\?\s*COMPETITION_HOME_LINKS/);
  for (const hash of ['#platform', '#workflow', '#evidence']) {
    assert.match(authShell, new RegExp(hash));
  }
  assert.match(authShell, /aria-label="返回首页"/);
});

test('competition home uses the four supplied campus seasons without broadening scope', () => {
  for (const url of [sourceUrl, stylesUrl, springUrl, summerUrl, lakeUrl, winterUrl]) {
    assert.equal(existsSync(url), true, `${url.pathname} must exist`);
  }
  if (!existsSync(sourceUrl) || !existsSync(stylesUrl)) return;

  const source = readFileSync(sourceUrl, 'utf8');
  for (const expected of [
    'LMateLab',
    '二维材料',
    'VASP',
    'relax',
    'SCF',
    'BAND',
    'DOS',
    'Slurm',
    '进入平台',
  ]) {
    assert.match(source, new RegExp(expected));
  }
  assert.match(source, /campus-spring\.webp/);
  assert.match(source, /campus-summer\.webp/);
  assert.match(source, /campus-lake\.webp/);
  assert.match(source, /campus-winter\.webp/);
  assert.match(source, /--competition-home-flow-image/);
  assert.match(source, /--competition-home-evidence-image/);
  assert.match(source, /navigate\(['"]\/login['"]\)/);
  assert.match(source, /aria-label="进入平台"/);
  assert.doesNotMatch(source, /Agent|RAG|机器学习|QE|EPW|跨服务器|高通量|任意材料|任意命令/);
});

test('competition home keeps all four seasonal backgrounds responsive and overflow safe', () => {
  if (!existsSync(stylesUrl)) return;
  const styles = readFileSync(stylesUrl, 'utf8');

  assert.match(styles, /\.competition-home-hero\s*\{[^}]*background-image:\s*var\(--competition-home-hero-image\)/s);
  assert.match(styles, /\.competition-home-campus\s*\{[^}]*background-image:\s*var\(--competition-home-campus-image\)/s);
  assert.match(styles, /\.competition-home-flow\s*\{[^}]*background-image:\s*var\(--competition-home-flow-image\)/s);
  assert.match(styles, /\.competition-home-evidence\s*\{[^}]*background-image:\s*var\(--competition-home-evidence-image\)/s);
  assert.match(styles, /@media\s*\(max-width:\s*640px\)/);
  assert.match(styles, /overflow-x:\s*hidden/);
  assert.doesNotMatch(styles, /font-size:\s*[^;]*vw/);
  assert.doesNotMatch(styles, /letter-spacing:\s*-/);
  for (const radius of styles.matchAll(/border-radius:\s*(\d+)px/g)) {
    assert.ok(Number(radius[1]) <= 8, `border radius exceeds 8px: ${radius[0]}`);
  }
});
