import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

import { expect, test } from '@playwright/test'

import { assertRuntimeEvidenceHealthy, observeRuntime } from './runtime-observer.mjs'

const sourceProjectId = process.env.BROWSER_PROJECT_ID
const downloadRoot = process.env.BROWSER_DOWNLOAD_ROOT
const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '[]')
const importedTitle = 'Phase6C imported authority'
const consumerFailure = '/api/project-imports'
const finals = ['PHASE6A_FINAL_CHAPTER_ONE', 'PHASE6A_FINAL_CHAPTER_TWO']
const excluded = ['PHASE6A_WORKING_SENTINEL', 'PHASE6A_CANDIDATE_SENTINEL']
const uiTimeout = 45_000

async function saveDownload(download, filename) {
  const target = path.join(downloadRoot, filename)
  await download.saveAs(target)
  return target
}

function assertFinalizedText(bytes) {
  assert.ok(bytes.indexOf(finals[0]) >= 0, 'first finalized chapter is present')
  assert.ok(bytes.indexOf(finals[1]) > bytes.indexOf(finals[0]), 'finalized order is preserved')
  for (const sentinel of excluded) assert.equal(bytes.includes(sentinel), false, `${sentinel} is excluded`)
}

async function visibleImportState(page) {
  if (await page.getByRole('alert').filter({ hasText: '项目导入失败，请重试。' }).isVisible()) {
    return 'fixed-error'
  }
  for (const [label, token] of [
    ['正在上传项目备份', 'upload'],
    ['正在检查项目备份', 'checking'],
    ['正在暂存项目资料', 'staging'],
    ['正在发布新项目', 'publishing'],
    ['正在恢复导入状态', 'recovery'],
  ]) {
    if (await page.getByRole('dialog', { name: label }).isVisible()) return token
  }
  return 'none'
}

function importDiagnostic(summary, visible) {
  const categories = values => values.length ? values.join('+') : 'none'
  return [
    `postCount=${summary.postCount}`,
    `postCategories=${categories(summary.statusCategories.post)}`,
    `getCount=${summary.getCount}`,
    `getCategories=${categories(summary.statusCategories.get)}`,
    `visible=${visible}`,
  ].join(' ')
}

test('@phase6c imports a real backup atomically and recovers its unknown result', async ({ page }) => {
  const runtime = observeRuntime(page, {
    allowedOrigins,
    expectedFailedRequest: consumerFailure,
  })
  await page.goto(`/projects/${sourceProjectId}/overview`, { timeout: uiTimeout })
  await expect(page.getByText('PROJECT OVERVIEW', { exact: true })).toBeVisible({ timeout: uiTimeout })

  const backupDownload = page.waitForEvent('download', { timeout: uiTimeout })
  await page.getByRole('button', { name: '创建项目备份' }).click()
  await expect(page.getByRole('dialog', { name: '正在建立一致快照' })).toBeVisible({ timeout: uiTimeout })
  const backupPath = await saveDownload(await backupDownload, 'phase6c-import-source.zip')

  await page.getByRole('link', { name: 'Novel Creator 项目库' }).click()
  await expect(page.getByRole('heading', { name: '项目库' })).toBeVisible({ timeout: uiTimeout })
  await expect(page.getByText('导入项目备份', { exact: true })).toBeVisible()
  await page.getByLabel('选择项目备份').setInputFiles(backupPath)
  assert.equal(
    await runtime.waitForResponse('POST', '/api/project-imports/preflight', uiTimeout),
    200,
    'preflight response must succeed',
  )
  const title = page.getByLabel('新项目名称')
  await expect(title).toBeVisible({ timeout: uiTimeout })
  await expect(page.getByText('Provider Not Ready', { exact: true })).toBeVisible()
  await title.fill(importedTitle)

  await page.getByRole('button', { name: '导入为新项目' }).click()
  await expect(page.getByRole('dialog', { name: /正在上传项目备份|正在恢复导入状态/u }))
    .toBeVisible({ timeout: uiTimeout })
  try {
    await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/u, { timeout: uiTimeout })
  } catch (cause) {
    throw new Error(
      `phase6c-import-diagnostic ${importDiagnostic(
        runtime.importStatusSummary(), await visibleImportState(page),
      )}`,
      { cause },
    )
  }
  const importedProjectId = new URL(page.url()).pathname.split('/')[2]
  assert.notEqual(importedProjectId, sourceProjectId)
  await expect(page.getByRole('heading', { name: importedTitle })).toBeVisible({ timeout: uiTimeout })

  await page.getByRole('link', { name: '模型绑定' }).click()
  await expect(page.getByRole('heading', { name: importedTitle })).toBeVisible({ timeout: uiTimeout })
  await expect(page.getByText('Not Ready', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: '项目概览' }).click()

  const finalDownload = page.waitForEvent('download', { timeout: uiTimeout })
  await page.getByRole('button', { name: '下载整本定稿' }).click()
  const finalPath = await saveDownload(await finalDownload, 'phase6c-imported-finalized.txt')
  assertFinalizedText(await readFile(finalPath, 'utf8'))

  assertRuntimeEvidenceHealthy(await runtime.finish())
})
