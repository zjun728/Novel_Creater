import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
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
const seed = '基'.repeat(8)
const outputs = ['改', '润', '扩', '缩'].map(value => value.repeat(256))
const digest = (value: string) => createHash('sha256').update(value, 'utf8').digest('hex')
const expectedDrafts = [
  seed,
  `${outputs[0]}${seed.slice(1)}`,
  `${outputs[1]}${seed.slice(1)}`,
  `${outputs[3]}${seed.slice(1)}`,
]


async function editorDigest(editor) {
  return digest(await editor.inputValue())
}


async function previewDigest(replacementPreview) {
  return digest(String(await replacementPreview.locator('pre').textContent()))
}


async function completeLocal(page, editor, replacementPreview, label, output, before, after) {
  await page.getByRole('button', { name: label }).click()
  await expect(replacementPreview).toBeVisible()
  await expect.poll(
    () => previewDigest(replacementPreview),
    { timeout: 15_000 },
  ).toBe(digest(output))
  await expect.poll(() => editorDigest(editor)).toBe(digest(before))
  await expect(page.getByText('生成完成')).toBeVisible({ timeout: 15_000 })
  await expect.poll(
    () => editorDigest(editor),
    { timeout: 15_000 },
  ).toBe(digest(after))
  await expect(editor).not.toHaveAttribute('readonly', '')
}


function assertHealthy(evidence) {
  assertRuntimeEvidenceHealthy(evidence, { allowedOrigins })
  assertExactWrites(evidence, [
    { method: 'PUT', path: /\/working-draft$/u, count: 1, statuses: [200] },
    { method: 'POST', path: /\/draft-operations$/u, count: 4, statuses: [200] },
    { method: 'POST', path: /\/draft-operations\/[^/]+\/cancel$/u, count: 1, statuses: [200] },
    { method: 'POST', path: /\/working-draft\/undo$/u, count: 1, statuses: [200] },
  ])
  assert.equal(evidence.responses.some(item => new URL(item.url).pathname.includes('/candidates')), false)
  assert.equal(scanRuntimeEvidence(evidence, runtimeSensitiveValues()).matchCount, 0)
  assertNoPrivateEvidenceMarkers([
    ...evidence.consoleMessages,
    ...evidence.consoleErrors,
    ...evidence.pageErrors,
    ...evidence.requestFailures,
    ...evidence.responseFailures,
  ])
}


test('@selection-tools completes four local tools, preserves cancelled prose, and undoes once', async ({ page }) => {
  const runtime = observeRuntime(page, { allowedOrigins })
  await page.goto(writerPath)
  await expect(page.getByRole('heading', { name: '章节工作台' })).toBeVisible()
  const editor = page.getByRole('textbox', { name: '章节正文工作稿' })
  const replacementPreview = page.getByLabel('替换内容预览')
  await editor.fill(seed)
  await expect(page.getByText(/已暂存 \d{2}:\d{2}:\d{2}/u)).toBeVisible()
  await expect.poll(() => editorDigest(editor)).toBe(digest(expectedDrafts[0]))
  await editor.press('Control+Home')
  await editor.press('Shift+ArrowRight')
  await expect(page.getByRole('button', { name: 'AI 改写' })).toBeVisible()

  await completeLocal(page, editor, replacementPreview, 'AI 改写', outputs[0], expectedDrafts[0], expectedDrafts[1])
  await completeLocal(page, editor, replacementPreview, 'AI 润色', outputs[1], expectedDrafts[1], expectedDrafts[2])

  await page.getByRole('button', { name: 'AI 扩写' }).click()
  await expect(replacementPreview).toBeVisible()
  await expect.poll(
    () => previewDigest(replacementPreview),
    { timeout: 15_000 },
  ).toBe(digest(outputs[2]))
  await expect.poll(() => editorDigest(editor)).toBe(digest(expectedDrafts[2]))
  await page.getByRole('button', { name: '停止生成' }).click()
  await expect(page.getByText('已停止，正文未改变')).toBeVisible()
  await expect.poll(() => editorDigest(editor)).toBe(digest(expectedDrafts[2]))

  await completeLocal(page, editor, replacementPreview, 'AI 缩写', outputs[3], expectedDrafts[2], expectedDrafts[3])
  const undo = page.getByRole('button', { name: '撤销本次 AI 修改' })
  await expect(undo).toBeVisible()
  await undo.click()
  await expect.poll(() => editorDigest(editor)).toBe(digest(expectedDrafts[2]))
  await expect(undo).toHaveCount(0)

  const evidence = await runtime.finish()
  assertHealthy(evidence)
})
