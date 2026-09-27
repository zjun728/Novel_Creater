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
  assertRuntimeEvidenceHealthy(evidence)
  assertExactWrites(evidence, [
    { method: 'PUT', path: /\/working-draft$/u, count: 1, statuses: [200] },
    { method: 'POST', path: /\/candidates$/u, count: 1, statuses: [201] },
    { method: 'POST', path: /\/finalization\/prepare$/u, count: 2, statuses: [201] },
    { method: 'POST', path: /\/finalization\/revisions$/u, count: 2, statuses: [201] },
    { method: 'POST', path: /\/finalization\/confirm$/u, count: 2, statuses: [200] },
    { method: 'POST', path: /\/finalization\/attempts\/[^/]+\/revoke$/u, count: 1, statuses: [200] },
    { method: 'POST', path: /\/finalization\/commit$/u, count: 1, statuses: [200] },
    { method: 'POST', path: /\/continuity\/issues$/u, count: 1, statuses: [200] },
    { method: 'PATCH', path: /\/continuity\/issues\/[^/]+$/u, count: 1, statuses: [200] },
  ])
  assert.equal(scanRuntimeEvidence(evidence, runtimeSensitiveValues()).matchCount, 0)
  assertNoPrivateEvidenceMarkers([
    ...evidence.consoleMessages, ...evidence.consoleErrors, ...evidence.pageErrors,
    ...evidence.requestFailures, ...evidence.responseFailures,
  ])
}

test('@atomic-finalization reviews, corrects, confirms, and atomically finalizes one Candidate', async ({ page }) => {
  const runtime = observeRuntime(page, { allowedOrigins })
  const emptyReviewResponse = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname.endsWith('/finalization')
  ))
  await page.goto(writerPath)
  const emptyReview = await emptyReviewResponse
  assert.equal(emptyReview.status(), 200)
  assert.deepEqual(await emptyReview.json(), { state: 'empty' })
  await expect(page.getByRole('heading', { name: '章节工作台' })).toBeVisible()
  const editor = page.getByRole('textbox', { name: '章节正文工作稿' })
  await editor.fill(candidate)
  await expect(page.getByText(/已暂存 \d{2}:\d{2}:\d{2}/u)).toBeVisible()
  await page.getByRole('button', { name: '保存为候选' }).click()
  await expect(page.getByText('候选 1', { exact: true })).toBeVisible()

  for (let reviewPass = 0; reviewPass < 2; reviewPass += 1) {
  const prepareResponse = page.waitForResponse(response => (
    response.request().method() === 'POST'
    && new URL(response.url()).pathname.endsWith('/finalization/prepare')
  ))
  const reviewResponse = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname.endsWith('/finalization')
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
  assert.deepEqual(currentReview.changeSet.payload.planningPatches.map(item => item.id), [
    '30000000-0000-4000-8000-000000000005',
    '30000000-0000-4000-8000-000000000006',
  ])
  assert.deepEqual(currentReview.changeSet.payload.planningSuggestions.map(item => item.id), [
    '30000000-0000-4000-8000-000000000007',
  ])
  await expect(page.locator('section[aria-label="质量建议"]')).toContainText('开场节奏可更紧凑。')
  await expect(page.getByText('Canon 事实', { exact: true })).toBeVisible()
  await expect(page.getByText('故事进度', { exact: true })).toBeVisible()
  await expect(page.getByText('未来规划调整', { exact: true })).toBeVisible()

  const futureAdjustments = page.locator('.change-group').filter({
    has: page.getByRole('heading', { name: '未来规划调整', exact: true }),
  })
  const suggestions = page.locator('.change-group').filter({
    has: page.getByRole('heading', { name: '非权威建议', exact: true }),
  })
  await expect(suggestions).toContainText('入城后转向追查暗记。')
  await expect(suggestions).toContainText('不会写入规划')
  await expect(suggestions).toContainText('不会修改当前章或历史规划')
  await expect(futureAdjustments.locator('article')).toHaveCount(2)
  await expect(futureAdjustments).not.toContainText('expectedChange')
  const removablePatch = futureAdjustments.locator('article').nth(1)
  await expect(removablePatch.getByRole('textbox')).toHaveValue('保留入城后的悬念。')
  await removablePatch.getByRole('button', { name: '移除此项调整' }).click()
  await expect(futureAdjustments.locator('article')).toHaveCount(1)
  await expect(futureAdjustments.getByRole('textbox')).toHaveValue('追查城内接头人。')
  await expect(page.getByRole('button', { name: '确认以上变更' })).toBeDisabled()
  await expect(page.getByText('修订 1', { exact: true })).toBeVisible()

  const summary = page.getByRole('textbox', { name: '章节摘要' })
  await summary.fill('作者确认：主角成功入城。')
  if (reviewPass === 0) {
    await page.getByRole('button', { name: '排除此项事实', exact: true }).first().click()
    await page.getByRole('button', { name: '排除此项进度', exact: true }).first().click()
    const writerUrl = page.url()
    page.once('dialog', dialog => dialog.dismiss())
    await page.getByRole('link', { name: '调整本章小纲', exact: true }).click()
    await expect(page).toHaveURL(writerUrl)
    await expect(summary).toHaveValue('作者确认：主角成功入城。')
  }
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
  const savedReviewResponse = await correctedReviewResponse
  assert.equal(savedReviewResponse.status(), 200)
  const savedReview = await savedReviewResponse.json()
  if (reviewPass === 0) {
    assert.equal(savedReview.changeSet.payload.canonEvents.length, 0)
    assert.equal(savedReview.changeSet.payload.storyProgressEvents.length, 1)
    assert.equal(savedReview.changeSet.payload.storyProgressEvents[0].targetType, 'scene_task')
  }
  assert.deepEqual(savedReview.changeSet.payload.planningPatches.map(item => item.id), [
    '30000000-0000-4000-8000-000000000005',
  ])
  assert.deepEqual(savedReview.changeSet.payload.planningSuggestions, currentReview.changeSet.payload.planningSuggestions)
  await expect(page.getByText('修订 2', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '确认以上变更' })).toBeEnabled()
  await page.getByRole('button', { name: '确认以上变更' }).click()
  if (reviewPass === 0) {
    await page.getByRole('button', { name: '撤销已确认审查', exact: true }).click()
    await expect(page.getByText('本章尚未定稿。撤销本次审查会保留正文、候选和已有审查记录；重新审查将再次调用模型。')).toBeVisible()
    const revokedResponse = page.waitForResponse(response => response.request().method() === 'POST'
      && new URL(response.url()).pathname.endsWith(`/attempts/${currentReview.attemptId}/revoke`))
    await page.getByRole('button', { name: '确认撤销本次审查' }).click()
    const revoked = await revokedResponse
    assert.equal(revoked.status(), 200)
    const receipt = await revoked.json()
    assert.equal(receipt.attemptId, currentReview.attemptId)
    assert.equal(receipt.status, 'cancelled')
    assert.equal(receipt.confirmedRevision, 2)
    assert.equal(receipt.confirmedRevisionHash, savedReview.changeSet.contentHash)
    await expect(page.getByRole('button', { name: '审查并定稿' })).toBeEnabled()
    await expect(editor).toHaveValue(candidate)
    await expect(page.getByText('候选 1', { exact: true })).toBeVisible()
  }
  }
  await page.getByRole('button', { name: '定稿本章' }).click()
  await expect(page.getByRole('alert')).toContainText('本章已定稿')
  await expect(editor).toHaveAttribute('readonly', '')

  await page.getByRole('link', { name: '查看本章定稿', exact: true }).click()
  await page.locator('#final-reader-review').click()
  const historyReview = page.getByRole('dialog')
  await expect(historyReview).toContainText('作者确认：主角成功入城。')
  await expect(historyReview).toContainText('开场节奏可更紧凑。')
  await expect(historyReview).toContainText('城门')
  await page.keyboard.press('Escape')
  await expect(historyReview).toBeHidden()

  const issuesPath = `/api/projects/${String(projectId)}/continuity/issues`
  const issueDescription = '第一章入城时间需与后续行程核对。'
  const issueSuggestion = '后续出城前交代经过时长。'
  const issueFutureTarget = '在第二章补充时间说明。'
  const issueResolution = '已核对第一章入城顺序，后续仅补充时间说明。'
  const issuesListResponse = () => page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === issuesPath
  ))
  const initialIssuesResponse = issuesListResponse()
  await page.getByRole('link', { name: '连续性问题', exact: true }).click()
  const initialIssues = await initialIssuesResponse
  assert.equal(initialIssues.status(), 200)
  assert.deepEqual((await initialIssues.json()).items, [])
  await expect(page.getByRole('heading', { name: '连续性问题', exact: true })).toBeVisible()
  await expect(page.getByText('尚无连续性问题记录', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '记录问题', exact: true }).click()
  const issueDetail = page.locator('.issue-detail')
  await issueDetail.getByLabel('问题类别', { exact: true }).selectOption('time')
  await issueDetail.getByLabel('严重程度', { exact: true }).selectOption('medium')
  await issueDetail.getByRole('textbox', { name: /^问题说明/u }).fill(issueDescription)
  await issueDetail.getByRole('textbox', { name: '处理建议', exact: true }).fill(issueSuggestion)
  await issueDetail.getByRole('textbox', { name: '未来处理目标', exact: true }).fill(issueFutureTarget)
  await issueDetail.getByRole('textbox', { name: /^来源章节/u }).fill('1')
  const createdListResponse = issuesListResponse()
  await issueDetail.getByRole('button', { name: '保存问题记录', exact: true }).click()
  const createdList = await createdListResponse
  assert.equal(createdList.status(), 200)
  const createdIssues = await createdList.json()
  assert.equal(createdIssues.items.length, 1)
  const createdIssue = createdIssues.items[0]
  assert.match(createdIssue.id, /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u)
  assert.equal(createdIssue.projectId, projectId)
  assert.equal(createdIssue.status, 'pending')
  assert.equal(createdIssue.description, issueDescription)
  assert.equal(createdIssue.suggestion, issueSuggestion)
  assert.equal(createdIssue.futureTarget, issueFutureTarget)
  assert.equal(createdIssue.sourceChapterNumber, 1)
  assert.equal(createdIssue.sourceCanonRevision, 1)
  assert.match(createdIssue.sourceFinalizationId, /^[0-9a-f-]{36}$/u)
  await expect(issueDetail.getByRole('link', { name: '查看第 1 章定稿', exact: true })).toBeVisible()
  await expect(page.getByText(/不代表历史正文或已发生事实被改写/u)).toBeVisible()

  const restoredListResponse = issuesListResponse()
  await page.reload()
  const restoredList = await restoredListResponse
  assert.equal(restoredList.status(), 200)
  assert.deepEqual((await restoredList.json()).items, [createdIssue])
  const issueRegister = page.getByRole('region', { name: '问题记录', exact: true })
  const issueChoice = issueRegister.getByRole('button').filter({ hasText: issueDescription })
  await expect(issueChoice).toContainText('待处理')
  await expect(issueChoice).toContainText('来源：第 1 章定稿')
  const restoredDetailResponse = page.waitForResponse(response => (
    response.request().method() === 'GET'
    && new URL(response.url()).pathname === `${issuesPath}/${createdIssue.id}`
  ))
  await issueChoice.click()
  const restoredDetail = await restoredDetailResponse
  assert.equal(restoredDetail.status(), 200)
  assert.deepEqual(await restoredDetail.json(), createdIssue)
  await expect(issueDetail).toContainText(issueSuggestion)
  await expect(issueDetail).toContainText(issueFutureTarget)
  await issueDetail.getByLabel('处理状态', { exact: true }).selectOption('resolved')
  await issueDetail.getByRole('textbox', { name: /^处理说明/u }).fill(issueResolution)
  const resolvedListResponse = issuesListResponse()
  await issueDetail.getByRole('button', { name: '保存处理结论', exact: true }).click()
  const resolvedList = await resolvedListResponse
  assert.equal(resolvedList.status(), 200)
  const resolvedIssues = await resolvedList.json()
  assert.equal(resolvedIssues.items.length, 1)
  const resolvedIssue = resolvedIssues.items[0]
  assert.equal(resolvedIssue.id, createdIssue.id)
  assert.equal(resolvedIssue.status, 'resolved')
  assert.equal(resolvedIssue.resolutionNote, issueResolution)
  assert.ok(resolvedIssue.updatedAt > createdIssue.updatedAt)
  assert.equal(resolvedIssue.sourceFinalizationId, createdIssue.sourceFinalizationId)
  assert.equal(resolvedIssue.sourceCanonRevision, createdIssue.sourceCanonRevision)
  await expect(issueDetail).toContainText(`已解决 · ${issueResolution}`)

  const persistedListResponse = issuesListResponse()
  await page.reload()
  const persistedList = await persistedListResponse
  assert.equal(persistedList.status(), 200)
  assert.deepEqual((await persistedList.json()).items, [resolvedIssue])
  const pendingListResponse = issuesListResponse()
  await issueRegister.getByLabel('处理状态', { exact: true }).selectOption('pending')
  const pendingList = await pendingListResponse
  assert.equal(pendingList.status(), 200)
  assert.deepEqual((await pendingList.json()).items, [])
  await expect(issueRegister.getByRole('heading', { name: '该状态下暂无问题', exact: true })).toBeVisible()
  const filteredListResponse = issuesListResponse()
  await issueRegister.getByLabel('处理状态', { exact: true }).selectOption('resolved')
  const filteredList = await filteredListResponse
  assert.equal(filteredList.status(), 200)
  assert.deepEqual((await filteredList.json()).items, [resolvedIssue])
  await expect(issueChoice).toContainText('已解决')
  await issueChoice.click()
  await expect(issueDetail).toContainText(`已解决 · ${issueResolution}`)
  await issueDetail.getByRole('link', { name: '查看第 1 章定稿', exact: true }).click()
  await expect(page).toHaveURL(new RegExp(`/projects/${String(projectId)}/workbench/chapters/1\\?view=text$`, 'u'))
  await expect(page.getByRole('article', { name: '定稿正文', exact: true })).toHaveText(candidate)
  await expect(page.getByRole('heading', { name: '第 1 章 · 第一章：入城', exact: true })).toBeVisible()

  const evidence = await runtime.finish()
  assertHealthy(evidence)
})
