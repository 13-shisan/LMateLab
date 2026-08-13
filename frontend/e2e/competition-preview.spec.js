import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import process from 'node:process';

import { expect, test } from '@playwright/test';
import { PNG } from 'pngjs';

const evidenceRoot = process.env.LMATELAB_E2E_EVIDENCE_DIR;
const previewCommit = process.env.LMATELAB_PREVIEW_COMMIT;
const previewEmail = process.env.LMATELAB_E2E_EMAIL;
const previewPassword = process.env.LMATELAB_E2E_PASSWORD;

if (!evidenceRoot || !previewCommit) {
  throw new Error('external evidence directory and preview commit are required');
}
if (!/^[0-9a-f]{40}$/.test(previewCommit)) {
  throw new Error('LMATELAB_PREVIEW_COMMIT must be a full 40-character lowercase Git commit');
}
if (!previewEmail || !previewPassword) {
  throw new Error('private preview credentials are required');
}

const routeChecks = [
  { path: '/dashboard', heading: '107 杯 VASP 计算工作台', screenshot: 'dashboard' },
  { path: '/dashboard/calculations/new', heading: '新建 VASP 计算', screenshot: 'calculation' },
  { path: '/dashboard/workflows', heading: '工作流' },
  { path: '/dashboard/results', heading: '计算结果' },
  { path: '/dashboard/database/vasp', heading: 'VASP 数据库' },
];

async function login(page) {
  await page.goto('/login');
  await page.locator('input[name="email"]').fill(previewEmail);
  await page.locator('input[name="password"]').fill(previewPassword);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/dashboard');
}

function collectViolations(page) {
  const consoleProblems = [];
  const businessWrites = [];

  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) {
      consoleProblems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => {
    consoleProblems.push(`pageerror: ${error.message}`);
  });
  page.on('request', (request) => {
    const method = request.method();
    const pathname = new URL(request.url()).pathname;
    const isLogin = method === 'POST' && pathname.endsWith('/api/auth/login');
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method) && !isLogin) {
      businessWrites.push(`${method} ${request.url()}`);
    }
  });

  return { consoleProblems, businessWrites };
}

async function expectNoDocumentOverflow(page) {
  const dimensions = await page.evaluate(() => ({
    innerWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.innerWidth + 1);
}

async function expectRouteAfterRefresh(page, route) {
  await page.goto(route.path);
  await expect.poll(() => new URL(page.url()).pathname).toBe(route.path);
  await expect(page.getByText('演示数据', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('heading', { name: route.heading, exact: true }).first()).toBeVisible();
  await expectNoDocumentOverflow(page);

  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(() => new URL(page.url()).pathname).toBe(route.path);
  await expect(page.getByText('演示数据', { exact: true }).first()).toBeVisible();
  await expect(page.getByRole('heading', { name: route.heading, exact: true }).first()).toBeVisible();
  await expectNoDocumentOverflow(page);
}

async function captureEvidence(page, testInfo, routeName) {
  mkdirSync(evidenceRoot, { recursive: true });
  const timestamp = new Date().toISOString().replaceAll(':', '-');
  const filename = `${testInfo.project.name}-${routeName}-${previewCommit}-${timestamp}.png`;
  const path = join(evidenceRoot, filename);
  await page.screenshot({ path, fullPage: true });
  return path;
}

async function expectNonblankStructureCanvas(page) {
  const canvas = page.locator('.vasp-viewer-canvas canvas').first();
  await expect(canvas).toBeVisible();
  const png = PNG.sync.read(await canvas.screenshot());
  let colored = 0;
  for (let index = 0; index < png.data.length; index += 4) {
    const [r, g, b, a] = png.data.subarray(index, index + 4);
    if (a > 0 && (r < 245 || g < 245 || b < 245)) colored += 1;
  }
  expect(colored).toBeGreaterThan(png.width * png.height * 0.002);
  return { colored, total: png.width * png.height, width: png.width, height: png.height };
}

test('competition preview passes the complete read-only browser acceptance', async ({ page }, testInfo) => {
  const violations = collectViolations(page);
  const screenshots = [];

  await login(page);

  for (const route of routeChecks) {
    await expectRouteAfterRefresh(page, route);
    if (route.screenshot) {
      screenshots.push(await captureEvidence(page, testInfo, route.screenshot));
    }

    if (route.path === '/dashboard/calculations/new') {
      await page.getByRole('button', { name: '上传结构', exact: true }).click();
      await expect(page.locator('input[type="file"]')).toBeDisabled();
      await expect(page.getByRole('button', { name: '保存草稿' })).toBeDisabled();
      await expect(page.getByRole('button', { name: '提交四步工作流' })).toBeDisabled();
      await page.getByRole('button', { name: '内置 MoS2', exact: true }).click();
    }
  }

  await page.goto('/dashboard/workflows/wf-demo-mos2-success');
  await expect(page.getByText('固定 relax → SCF → BAND / DOS', { exact: false })).toBeVisible();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: '步骤与调度证据', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '取消工作流' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '重试失败步骤' })).toBeDisabled();
  await expectNoDocumentOverflow(page);

  await page.goto('/dashboard/results');
  await page.getByRole('button', { name: '打开结果详情：MoS2', exact: true }).first().click();
  await expect.poll(() => new URL(page.url()).pathname).toBe('/dashboard/results/wf-demo-mos2-success');
  await expect(page.getByRole('heading', { name: '科学结果', exact: true })).toBeVisible();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: '科学结果', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '能带', exact: true })).toHaveClass(/is-active/);
  await expect(page.getByRole('img', { name: '能带图' })).toBeVisible();
  await page.getByRole('button', { name: '态密度 (DOS)', exact: true }).click();
  await expect(page.getByRole('img', { name: '态密度图' })).toBeVisible();
  await page.getByRole('button', { name: '能带', exact: true }).click();
  await expect(page.getByRole('img', { name: '能带图' })).toBeVisible();
  await expect(page.getByRole('button', { name: '重置结构视角' })).toBeVisible();
  await page.getByRole('button', { name: '重置结构视角' }).click();
  const canvasPixels = await expectNonblankStructureCanvas(page);
  await expectNoDocumentOverflow(page);
  screenshots.push(await captureEvidence(page, testInfo, 'result-success'));

  await page.goto('/dashboard/results/wf-demo-mos2-failed');
  await expect(page.getByRole('heading', { name: '计算失败证据', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '科学结果', exact: true })).toHaveCount(0);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: '计算失败证据', exact: true })).toBeVisible();
  await expectNoDocumentOverflow(page);
  screenshots.push(await captureEvidence(page, testInfo, 'result-failed'));

  await page.goto('/dashboard/database/vasp');
  await expect(page.getByRole('heading', { name: 'VASP 数据库', exact: true }).first()).toBeVisible();
  await page.getByTitle(/\(Mo, Z=42\)$/).click();
  await expect(page.getByRole('button', { name: '移除 Mo' })).toBeVisible();
  await page.getByTitle(/\(S, Z=16\)$/).click();
  await expect(page.getByRole('button', { name: '移除 S' })).toBeVisible();
  await page.getByRole('button', { name: '只含所选元素', exact: true }).click();
  await expect(page.getByRole('button', { name: '只含所选元素', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: '至少含有所选元素', exact: true }).click();
  await expect(page.getByRole('button', { name: '至少含有所选元素', exact: true })).toHaveAttribute('aria-pressed', 'true');
  await page.getByRole('button', { name: '清空选择', exact: true }).click();
  await expect(page.getByRole('button', { name: '清空选择', exact: true })).toBeDisabled();
  await page.locator('[aria-label="选择 MoS2，记录 ID db-demo-1"]:visible').first().click();
  await expect.poll(() => new URL(page.url()).searchParams.get('record')).toBe('db-demo-1');
  await expect(page.getByRole('heading', { name: '记录详情', exact: true })).toBeVisible();
  await expect(page.getByText('最新演示 Job ID', { exact: true })).toBeVisible();
  await expect(page.locator('.competition-database-inspector .vasp-viewer-canvas canvas')).toBeVisible();
  await expectNoDocumentOverflow(page);
  screenshots.push(await captureEvidence(page, testInfo, 'database'));

  expect(violations.consoleProblems).toEqual([]);
  expect(violations.businessWrites).toEqual([]);

  mkdirSync(evidenceRoot, { recursive: true });
  const viewport = page.viewportSize();
  const summaryPath = join(
    evidenceRoot,
    `${testInfo.project.name}-acceptance-${previewCommit}.json`,
  );
  writeFileSync(summaryPath, `${JSON.stringify({
    project: testInfo.project.name,
    viewport,
    preview_url: process.env.LMATELAB_PREVIEW_URL,
    preview_commit: previewCommit,
    canvas_pixels: canvasPixels,
    console_problem_count: violations.consoleProblems.length,
    business_write_count: violations.businessWrites.length,
    screenshots,
  }, null, 2)}\n`, 'utf8');
});
