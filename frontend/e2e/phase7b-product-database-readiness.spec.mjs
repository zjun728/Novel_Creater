import { test, expect } from '@playwright/test'

import {
  assertRuntimeEvidenceHealthy,
  observeRuntime,
} from './runtime-observer.mjs'
import { installHttpOriginBoundary } from './phase7b-network-boundary.mjs'

test('new product database exposes only approved empty/static state', async ({ page }) => {
  const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS)
  await installHttpOriginBoundary(page.context(), allowedOrigins)
  const runtime = observeRuntime(page, {
    allowedOrigins,
  })
  let response = await page.goto('/api/health')
  expect(response.status()).toBe(200)
  expect(JSON.parse(await page.locator('body').innerText())).toEqual({ ok: true })
  await page.goto('/projects')
  await expect(page.getByRole('heading', { name: '项目库' })).toBeVisible()
  await expect(page.getByRole('heading', { name: '从一个名字开始' })).toBeVisible()
  await page.goto('/assets/styles')
  await expect(page.getByRole('heading', { name: '风格模板库' })).toBeVisible()
  await expect(page.getByText('APPROVED STYLES').locator('..')).toContainText('10')
  await expect(page.locator('.style-grid article')).toHaveCount(10)
  await page.goto('/assets/experience')
  await expect(page.getByRole('heading', { name: '经验卡库' })).toBeVisible()
  await expect(page.getByText('APPROVED CARDS').locator('..')).toContainText('64')
  response = await page.goto('/api/market-sources')
  expect(response.status()).toBe(200)
  expect(JSON.parse(await page.locator('body').innerText())).toHaveLength(2)
  await page.goto('/settings/providers')
  await expect(page.getByRole('heading', { name: 'Provider 与模型' })).toBeVisible()
  await expect(page.getByText('还没有 Provider 配置')).toBeVisible()
  assertRuntimeEvidenceHealthy(await runtime.finish())
})
