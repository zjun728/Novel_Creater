import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

import { expect, test } from '@playwright/test'

import { assertRuntimeEvidenceHealthy, observeRuntime } from './runtime-observer.mjs'

const projectId = process.env.BROWSER_PROJECT_ID
const downloadRoot = process.env.BROWSER_DOWNLOAD_ROOT
const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '[]')
const uiTimeout = 30_000

async function saveVerifiedDownload(download, response, filename) {
  const target = path.join(downloadRoot, filename)
  await download.saveAs(target)
  const bytes = await readFile(target)
  const expectedHash = response.headers()['x-package-sha256']
  assert.match(expectedHash || '', /^[0-9a-f]{64}$/u, 'backup response exposes a package hash')
  assert.equal(createHash('sha256').update(bytes).digest('hex'), expectedHash)
  assert.equal(download.suggestedFilename(), 'project-backup.zip')
  return target
}

async function createBackup(page, filename, { fenceNavigation = false } = {}) {
  const endpoint = `/projects/${projectId}/backup`
  const responsePromise = page.waitForResponse(response => (
    response.url().includes(endpoint) && response.request().method() === 'POST'
  ), { timeout: uiTimeout })
  const downloadPromise = page.waitForEvent('download', { timeout: uiTimeout })
  await page.getByRole('button', { name: '创建项目备份' }).click({ timeout: uiTimeout })
  await expect(page.getByRole('dialog', { name: '正在建立一致快照' })).toBeVisible({ timeout: uiTimeout })
  if (fenceNavigation) {
    const beforeNavigation = new URL(page.url()).pathname
    await page.getByRole('link', { name: 'Novel Creator 项目库' }).click({ force: true })
    await expect.poll(() => new URL(page.url()).pathname).toBe(beforeNavigation)
  }
  const response = await responsePromise
  if (response.status() !== 200) void downloadPromise.catch(() => {})
  assert.equal(response.status(), 200, `backup-status-${response.status()}`)
  const download = await downloadPromise
  const target = await saveVerifiedDownload(download, response, filename)
  await expect(page.getByRole('dialog', { name: '正在建立一致快照' })).toBeHidden({ timeout: uiTimeout })
  return target
}

test('@phase6b backs up active and archived project with consumer cleanup', async ({ page, context }) => {
  const runtime = observeRuntime(page, { allowedOrigins })
  const preparationResponse = page.waitForResponse(response => (
    response.url().includes(`/projects/${projectId}/preparation`)
    && response.request().method() === 'GET'
  ), { timeout: uiTimeout })
  await page.goto(`/projects/${projectId}/overview`, { timeout: uiTimeout })
  await expect(page.getByText('PROJECT OVERVIEW', { exact: true })).toBeVisible({ timeout: uiTimeout })
  assert.equal((await preparationResponse).status(), 200)
  await expect(page.getByRole('heading', { name: '创作准备状态暂时无法加载' })).toBeHidden()
  await expect(page.locator('[aria-label="创作准备状态"]')).toBeVisible({ timeout: uiTimeout })
  const activeBackupButton = page.getByRole('button', { name: '创建项目备份' })
  await expect(activeBackupButton).toBeVisible({ timeout: uiTimeout })
  await expect(activeBackupButton).toBeEnabled({ timeout: uiTimeout })
  await createBackup(page, 'active-project-backup.zip', { fenceNavigation: true })

  const activeListResponsePromise = page.waitForResponse(response => {
    const url = new URL(response.url())
    return url.pathname.endsWith('/api/projects')
      && response.request().method() === 'GET'
  }, { timeout: uiTimeout })
  await page.getByRole('link', { name: 'Novel Creator 项目库' }).click()
  const activeListResponse = await activeListResponsePromise
  assert.equal([200, 304].includes(activeListResponse.status()), true, `active-list-status-${activeListResponse.status()}`)
  await expect(page.getByRole('heading', { name: '项目库' })).toBeVisible()
  const card = page.locator('.project-card').filter({ hasText: 'contract integration' })
  await expect(card).toBeVisible({ timeout: uiTimeout })
  await card.getByText('更多', { exact: true }).click()
  await card.getByRole('button', { name: '归档' }).click()
  await expect(page.getByText('项目已归档')).toBeVisible()

  await page.goto(`/projects/${projectId}/overview`, { timeout: uiTimeout })
  await expect(page.getByText('ARCHIVED PROJECT', { exact: true })).toBeVisible({ timeout: uiTimeout })
  await createBackup(page, 'archived-project-backup.zip')
  assertRuntimeEvidenceHealthy(await runtime.finish())

  // A final visible UI request is abandoned by its response consumer after the
  // real repository and package service have produced the held streaming reply.
  const consumerPage = await context.newPage()
  await consumerPage.goto(`/projects/${projectId}/overview`, { timeout: uiTimeout })
  await expect(consumerPage.getByText('ARCHIVED PROJECT', { exact: true })).toBeVisible({ timeout: uiTimeout })
  const consumerResponse = consumerPage.waitForResponse(response => (
    response.url().includes(`/projects/${projectId}/backup`)
    && response.request().method() === 'POST'
  ), { timeout: uiTimeout })
  await consumerPage.getByRole('button', { name: '创建项目备份' }).click({ timeout: uiTimeout })
  await expect(consumerPage.getByRole('dialog', { name: '正在建立一致快照' })).toBeVisible({ timeout: uiTimeout })
  await consumerResponse
  await consumerPage.close()
})
