import { expect, test } from '@playwright/test';


const protectedRoutes = [
  { path: '/dashboard', activeLabel: '工作台', root: '.competition-page' },
  { path: '/dashboard/calculations/new', activeLabel: '新建计算', root: '.competition-calculation-page' },
  { path: '/dashboard/workflows', activeLabel: '工作流', root: '.competition-workflows-page' },
  { path: '/dashboard/results', activeLabel: '结果', root: '.competition-results-page' },
  { path: '/dashboard/database/vasp', activeLabel: 'VASP 数据库', root: '.competition-database-page' },
];

const optionalAgentRoute = {
  path: '/dashboard/agent',
  activeLabel: 'Qoder Agent',
  root: '.competition-agent-page',
};


test.beforeEach(async ({ page }) => {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        name: '视觉验收',
        email: 'visual@example.invalid',
        role: 'Viewer',
      }),
    });
  });
  await page.addInitScript(() => {
    localStorage.setItem('token', 'local-visual-audit');
  });
});


test('protected routes share a quiet workbench canvas without overflow', async ({ page }, testInfo) => {
  const problems = [];
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) {
      problems.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));

  await page.goto('/dashboard');
  const agentEnabled = await page.getByRole('link', {
    name: optionalAgentRoute.activeLabel,
    exact: true,
  }).count() > 0;
  const routes = agentEnabled ? [...protectedRoutes, optionalAgentRoute] : protectedRoutes;

  for (const route of routes) {
    await page.goto(route.path);
    await expect(page.locator(route.root)).toBeVisible();

    const activeItem = page.getByRole('link', { name: route.activeLabel, exact: true });
    await expect(activeItem).toHaveAttribute('aria-current', 'page');
    await expect(activeItem).toHaveCSS('box-shadow', /rgb/);

    const geometry = await page.evaluate(() => ({
      innerWidth: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      canvasBackground: getComputedStyle(document.querySelector('.lm-app-content')).backgroundImage,
      pageBackground: getComputedStyle(document.querySelector('main')).backgroundImage,
    }));
    expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.innerWidth + 1);
    expect(geometry.canvasBackground).toContain('linear-gradient');
    expect(geometry.canvasBackground).not.toContain('url(');
    expect(geometry.pageBackground).not.toContain('url(');

    await page.screenshot({
      path: testInfo.outputPath(`${route.activeLabel}.png`),
      fullPage: true,
    });
  }

  expect(problems).toEqual([]);
});
