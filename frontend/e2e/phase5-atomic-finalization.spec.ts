import assert from 'node:assert/strict'
import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  assertNoPrivateEvidenceMarkers,
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'

const projectId = process.env.BROWSER_PROJECT_ID
const writerPath = `/projects/${String(projectId)}/write/chapters/1`
const allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '[]')
const candidate = '夜雨压着城门。主角递上路引，守门老卒核对暗记后放他入城。'.repeat(4)

function assertHealthy(evidence) {
  const missingReview = evidence.responses.filter(response => {
    if (response.method !== 'GET' || response.status !== 404) return false
    try {
      return new URL(response.url).pathname.endsWith('/finalization')
    } catch {
      return false
    }
  })
  assert.equal(missingReview.length, 1)
  const missingReviewPath = new URL(missingReview[0].url).pathname
  assertRuntimeEvidenceHealthy(evidence, {
    responseFailureAllowlist: [{
      status: 404, method: 'GET', pathname: missingReviewPath, count: 1,
    }],
    consoleErrorAllowlist: [{
      message: 'error: Failed to load resource: the server responded with a status of 404 (Not Found)',
      count: 1,
      linkedResponseFailure: { status: 404, method: 'GET', pathname: missingReviewPath },
    }],
  })
  assertExactWrites(evidence, [
    { method: 'PUT', path: /\/working-draft$/u, count: 1, statuses: [200] },
    { method: 'POST', path: /\/candidates$/u, count: 1, statuses: [201] },
    { method: 'POST', path: /\/finalization\/prepare$/u, count: 1, statuses: [201] },
    { method: 'POST', path: /\/finalization\/revisions$/u, count: 1, statuses: [201] },
    { method: 'POST', path: /\/finalization\/confirm$/u, count: 1, statuses: [200] },
    { method: 'POST', path: /\/finalization\/commit$/u, count: 1, statuses: [200] },
  ])
  assert.equal(scanRuntimeEvidence(evidence, runtimeSensitiveValues()).matchCount, 0)
  assertNoPrivateEvidenceMarkers([
    ...evidence.consoleMessages, ...evidence.consoleErrors, ...evidence.pageErrors,
    ...evidence.requestFailures, ...evidence.responseFailures,
  ])
}

test('@atomic-finalization reviews, corrects, confirms, and atomically finalizes one Candidate', async ({ page }) => {
  const runtime = observeRuntime(page, { allowedOrigins })
  await page.goto(writerPath)
  await expect(page.getByRole('heading', { name: '章节工作台' })).toBeVisible()
  const editor = page.getByRole('textbox', { name: '章节正文工作稿' })
  await editor.fill(candidate)
  await expect(page.getByText(/已暂存 \d{2}:\d{2}:\d{2}/u)).toBeVisible()
  await page.getByRole('button', { name: '保存为候选' }).click()
  await expect(page.getByText('候选 1', { exact: true })).toBeVisible()

  const prepareResponse = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname.endsWith('/finalization/prepare')
  ))
  const reviewResponse = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname.endsWith('/finalization')
    && response.status() !== 404
  ))
  await page.getByRole('button', { name: '审查并定稿' }).click()
  assert.equal((await prepareResponse).status(), 201)
  const currentReviewResponse = await reviewResponse
  assert.equal(currentReviewResponse.status(), 200)
  const currentReview = await currentReviewResponse.json()
  if (currentReview.status !== 'awaiting_author') {
    const codes = (currentReview.qualityReport?.deterministicBlocks || [])
      .map(item => item.code).sort().join(',') || 'none'
    throw new Error(`review-status-${String(currentReview.status)}-blocks-${codes}`)
  }
  assert.equal(currentReview.changeSet?.revision, 1)
  assert.equal(currentReview.qualityReport?.findings?.length, 1)
  await expect(page.locator('section[aria-label="质量建议"]')).toContainText('开场节奏可更紧凑。')
  await expect(page.getByText('Canon 事实', { exact: true })).toBeVisible()
  await expect(page.getByText('故事进度', { exact: true })).toBeVisible()
  await expect(page.getByText('未来规划调整', { exact: true })).toBeVisible()

  const summary = page.getByRole('textbox', { name: '章节摘要' })
  await summary.fill('作者确认：主角成功入城。')
  const correctionResponse = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname.endsWith('/finalization/revisions')
  ))
  const correctedReviewResponse = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname.endsWith('/finalization')
  ))
  await page.getByRole('button', { name: '保存修正' }).click()
  assert.equal((await correctionResponse).status(), 201)
  assert.equal((await correctedReviewResponse).status(), 200)
  await expect(page.getByText('修订 2', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '确认以上变更' }).click()
  await page.getByRole('button', { name: '定稿本章' }).click()
  await expect(page.getByRole('alert')).toContainText('本章已定稿')
  await expect(editor).toHaveAttribute('readonly', '')

  const evidence = await runtime.finish()
  assertHealthy(evidence)
})
