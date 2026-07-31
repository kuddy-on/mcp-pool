import { expect, test } from '@playwright/test';

test('login and logout complete without browser errors', async ({ page }, testInfo) => {
  const browserErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' || message.type() === 'warning') {
      browserErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => browserErrors.push(error.message));

  let logoutCalled = false;
  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (!pathname.startsWith('/api/')) {
      await route.continue();
      return;
    }
    if (pathname === '/api/auth/login') {
      await route.fulfill({
        json: {
          token: 'e2e-token',
          user: { id: 'admin-1', username: 'admin', role: 'admin' },
        },
      });
      return;
    }
    if (pathname === '/api/auth/me') {
      await route.fulfill({
        json: { id: 'admin-1', username: 'admin', role: 'admin' },
      });
      return;
    }
    if (pathname === '/api/auth/logout') {
      logoutCalled = true;
      await route.fulfill({ json: { status: 'ok' } });
      return;
    }
    if (pathname === '/api/admin/settings') {
      await route.fulfill({
        json: { gateway_external_url: 'https://gateway.example' },
      });
      return;
    }
    if (pathname === '/api/admin/services') {
      await route.fulfill({
        json: [
          {
            id: 'service-context7',
            name: 'Context7',
            upstream_url: 'https://mcp.context7.com/mcp',
            provider_type: 'context7',
            auth_header: 'Authorization',
            auth_prefix: 'Bearer ',
            total_keys: 3,
            active_keys: 2,
            status: 'degraded',
            keys: [
              { id: 'key-1', name: 'ctx7-primary', key_masked: 'ctx7...3f8a', is_active: true, quota_exhausted: false, paused_until: null, weight: 1, fail_count: 0, requests_count: 128456, last_used: null, monthly_quota: 1000000, used_this_month: 128456 },
              { id: 'key-2', name: 'ctx7-secondary', key_masked: 'ctx7...7b1c', is_active: true, quota_exhausted: false, paused_until: null, weight: 1, fail_count: 0, requests_count: 67231, last_used: null, monthly_quota: 1000000, used_this_month: 67231 },
              { id: 'key-3', name: 'ctx7-backup', key_masked: 'ctx7...9d4e', is_active: false, quota_exhausted: false, paused_until: null, weight: 1, fail_count: 0, requests_count: 12934, last_used: null, monthly_quota: 500000, used_this_month: 12934 },
            ],
          },
          {
            id: 'service-docs',
            name: 'Internal Docs',
            upstream_url: 'https://docs.internal.example/mcp',
            provider_type: 'generic',
            auth_header: 'Authorization',
            auth_prefix: 'Bearer ',
            total_keys: 1,
            active_keys: 1,
            status: 'active',
            keys: [],
          },
        ],
      });
      return;
    }
    if (pathname.endsWith('/quota-status')) {
      await route.fulfill({
        json: {
          service_id: 'service-context7',
          provider_type: 'context7',
          supported: true,
          can_refresh: true,
          status: 'ok',
          keys: [
            { key_id: 'key-1', status: 'ok', used: 128456, limit: 1000000, remaining: 871544, reset_at: '2026-08-01T00:00:00Z', last_success_at: '2026-07-31T02:00:00Z', last_attempt_at: '2026-07-31T02:00:00Z', stale: false, estimated: false, error_code: null },
            { key_id: 'key-2', status: 'ok', used: 67231, limit: 1000000, remaining: 932769, reset_at: '2026-08-01T00:00:00Z', last_success_at: '2026-07-31T02:00:00Z', last_attempt_at: '2026-07-31T02:00:00Z', stale: false, estimated: false, error_code: null },
          ],
        },
      });
      return;
    }
    await route.fulfill({ json: [] });
  });

  await page.goto('/');
  await expect(page).toHaveTitle('MCPPool Admin Dashboard');
  await expect(page.getByText('登录 MCPPool 管理控制台')).toBeVisible();

  const inputs = page.locator('input');
  await inputs.nth(0).fill('admin');
  await inputs.nth(1).fill('a-secure-password');
  await page.getByRole('button', { name: '登录' }).click();

  await expect(page.getByRole('button', { name: /退出登录/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /服务与账号池/ })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Context7' })).toBeVisible();
  await page.getByRole('button', { name: /添加服务/ }).click();
  await expect(page.getByText('新增 MCP 服务')).toBeVisible();
  await page.getByRole('button', { name: '取消' }).click();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth))
    .toBe(await page.evaluate(() => document.documentElement.clientWidth));
  await page.screenshot({
    path: `/tmp/mcp-pool-dashboard-${testInfo.project.name}.png`,
    fullPage: false,
  });
  if (testInfo.project.name === 'mobile-chromium') {
    await page.locator('.key-table__row').first().scrollIntoViewIfNeeded();
    await page.screenshot({
      path: '/tmp/mcp-pool-dashboard-mobile-keys.png',
      fullPage: false,
    });
  }

  await page.getByRole('button', { name: /退出登录/ }).click();
  await expect(page.getByText('登录 MCPPool 管理控制台')).toBeVisible();
  expect(logoutCalled).toBe(true);
  expect(browserErrors).toEqual([]);
});
