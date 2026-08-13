import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'

import { expect, test } from '@playwright/test'

import { assertRuntimeEvidenceHealthy, observeRuntime } from './runtime-observer.mjs'

const projectId = process.env.BROWSER_PROJECT_ID
const downloadRoot = process.env.BROWSER_DOWNLOAD_ROOT
const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '[]')
const finals = ['PHASE6A_FINAL_CHAPTER_ONE', 'PHASE6A_FINAL_CHAPTER_TWO']
const UNSAVED_SENTINEL = 'PHASE6A_UNSAVED_SENTINEL'
const excluded = ['PHASE6A_WORKING_SENTINEL', 'PHASE6A_CANDIDATE_SENTINEL', UNSAVED_SENTINEL]

async function savedUtf8(download, filename) {
  const target = path.join(downloadRoot, filename)
  await download.saveAs(target)
  return readFile(target, 'utf8')
}

function assertFinalizedBytes(bytes, extension) {
  assert.match(bytes, extension)
  assert.ok(bytes.indexOf(finals[0]) >= 0, 'first finalized chapter is present')
  assert.ok(bytes.indexOf(finals[1]) > bytes.indexOf(finals[0]), 'finalized chapters keep authority order')
  for (const sentinel of excluded) assert.equal(bytes.includes(sentinel), false, `${sentinel} is excluded`)
}

test('@phase6a downloads finalized TXT from Overview and Markdown after archive', async ({ page, context }) => {
  const runtime = observeRuntime(context, { allowedOrigins })
  await page.goto(`/projects/${projectId}/overview`)
  await page.getByRole('link', { name: '继续章节写作' }).click()
  await expect(page.getByRole('heading', { name: '章节工作台' })).toBeVisible()
  const editor = page.getByRole('textbox', { name: '章节正文工作稿' })
  await expect(editor).toBeEditable()

  // The writer stays open. Overview is opened through its visible product link
  // before editing, so moving to the download controls never navigates away or
  // flushes the editor's 800ms autosave timer.
  const overviewPage = page.context().waitForEvent('page')
  await page.getByRole('link', { name: '项目概览' }).click({ modifiers: ['Control'] })
  const overview = await overviewPage
  await overview.waitForLoadState('domcontentloaded')
  await expect(overview.getByRole('button', { name: '下载整本定稿' })).toBeEnabled()

  await page.bringToFront()
  await editor.fill(UNSAVED_SENTINEL)
  await expect(editor).toHaveValue(UNSAVED_SENTINEL)
  await expect(page.getByText('未暂存', { exact: true })).toBeVisible()

  await overview.bringToFront()
  const overviewDownload = overview.waitForEvent('download')
  await overview.getByRole('button', { name: '下载整本定稿' }).click()
  // This executes before the controlled 800ms autosave threshold: the still-open
  // writer is the proof that an actual unsaved browser value coexists with download.
  await expect(editor).toHaveValue(UNSAVED_SENTINEL, { timeout: 300 })
  await expect(overview.getByRole('dialog', { name: '正在准备下载' })).toBeVisible()
  const beforeNavigation = new URL(overview.url()).pathname
  await overview.getByRole('link', { name: 'Novel Creator 项目库' }).click({ force: true })
  await expect.poll(() => new URL(overview.url()).pathname).toBe(beforeNavigation)

  const txt = await savedUtf8(await overviewDownload, 'overview-finalized.txt')
  assertFinalizedBytes(txt, /PHASE6A_FINAL_CHAPTER_ONE/u)
  await overview.getByRole('combobox', { name: '下载范围' }).selectOption('volume')
  await expect(overview.getByRole('button', { name: '下载分卷定稿' })).toBeEnabled()
  await overview.getByRole('combobox', { name: '下载范围' }).selectOption('book')

  await overview.getByRole('link', { name: 'Novel Creator 项目库' }).click()
  await expect(overview.getByRole('heading', { name: '项目库' })).toBeVisible()
  const card = overview.locator('.project-card').filter({ hasText: /PHASE6A_FINAL_CHAPTER_ONE|项目/u }).first()
  await card.getByText('更多', { exact: true }).click()
  await card.getByRole('button', { name: '归档' }).click()
  await expect(overview.getByText('项目已归档')).toBeVisible()

  await overview.goto(`/projects/${projectId}/overview`)
  await expect(overview.getByText('ARCHIVED PROJECT', { exact: true })).toBeVisible()
  await overview.getByRole('combobox', { name: '下载格式' }).selectOption('markdown')
  const archivedDownload = overview.waitForEvent('download')
  await overview.getByRole('button', { name: '下载整本定稿' }).click()
  const markdown = await savedUtf8(await archivedDownload, 'archived-finalized.md')
  assertFinalizedBytes(markdown, /# /u)

  assertRuntimeEvidenceHealthy(await runtime.finish())
})
