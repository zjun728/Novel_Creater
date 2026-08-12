import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
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
const PARTIAL_SCALAR_COUNT = 256
const COMPLETE_SCALAR_COUNT = 257
const PARTIAL_OUTPUT_SHA256 = 'f0a0b60f973a06b3723525ece56b44231bf8b4d1715e7356d2d008063767741f'
const COMPLETED_OUTPUT_SHA256 = 'c88ade88d9dd15b14d6bd8b9c7662072148fdb8dc4fc714d56a9fb9a31f12fbe'
const BASE_WORKING_DRAFT_SHA256 = 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'


function createReloadResponsePaths(nextProjectId) {
  const opaqueIdPath = '[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}'
  return {
    workspaceReloadPath: new RegExp(`^/api/projects/${nextProjectId}/chapter-sessions/1$`, 'u'),
    activeDraftOperationReloadPath: new RegExp(`^/api/projects/${nextProjectId}/chapter-sessions/${opaqueIdPath}/draft-operations/${opaqueIdPath}$`, 'iu'),
  }
}


const { workspaceReloadPath, activeDraftOperationReloadPath } = createReloadResponsePaths(projectId)


function ownedProviderLedgerPath() {
  const root = process.env.BROWSER_OWNED_ROOT
  const candidate = process.env.BROWSER_PROVIDER_LEDGER_PATH
  if (typeof root !== 'string' || typeof candidate !== 'string' || !root || !candidate) {
    throw new Error('Phase4B2 provider ledger authority is invalid')
  }
  const ownedRoot = path.resolve(root)
  const ledgerPath = path.resolve(candidate)
  if (path.relative(ownedRoot, ledgerPath) !== 'provider-ledger.log' || !existsSync(ledgerPath)) {
    throw new Error('Phase4B2 provider ledger authority is invalid')
  }
  return ledgerPath
}


const providerLedgerPath = ownedProviderLedgerPath()


function acceptedProviderCallCount() {
  try {
    const entries = readFileSync(providerLedgerPath, 'utf8').split(/\r?\n/u).filter(Boolean)
    const allowed = /^(?:scenario=(?:complete|reconnect|cancel-output|cancel-empty)|method=POST path=\/v1\/chat\/completions status=200|connection=[1-9]\d*|call=[1-9]\d*|terminal=(?:completed|transport-closed|payload-too-large|rejected))$/u
    return entries.every(entry => allowed.test(entry))
      ? entries.filter(entry => entry === 'method=POST path=/v1/chat/completions status=200').length
      : 0
  } catch {
    return 0
  }
}


function assertHealthy(evidence, writeCount) {
  assertRuntimeEvidenceHealthy(evidence, { allowedOrigins })
  assertExactWrites(evidence, [{
    method: 'POST',
    path: /\/draft-operations(?:\/[^/]+\/cancel)?$/u,
    count: writeCount,
    statuses: [200],
  }])
  assert.equal(
    evidence.responses.some(item => new URL(item.url).pathname.includes('/candidates')),
    false,
  )
  assert.equal(scanRuntimeEvidence(evidence, runtimeSensitiveValues()).matchCount, 0)
  assertNoPrivateEvidenceMarkers([
    ...evidence.consoleMessages,
    ...evidence.consoleErrors,
    ...evidence.pageErrors,
    ...evidence.requestFailures,
    ...evidence.responseFailures,
  ])
}


async function openWriter(page) {
  const runtime = observeRuntime(page, { allowedOrigins })
  await page.goto(writerPath)
  await expect(page.getByRole('heading', { name: '章节工作台' })).toBeVisible()
  return runtime
}


async function startGeneration(page) {
  await page.getByRole('button', { name: 'AI 生成工作稿' }).click()
  await expect(page.getByText('正在生成')).toBeVisible()
}


async function waitForAcceptedProviderCall() {
  await expect.poll(() => acceptedProviderCallCount()).toBe(1)
}


function isLoopbackGet(response, pathname) {
  try {
    const request = response.request()
    const url = new URL(response.url())
    return url.protocol === 'http:'
      && url.hostname === '127.0.0.1'
      && request.method() === 'GET'
      && pathname.test(url.pathname)
  } catch {
    return false
  }
}


function reloadWithRecoveryObservers(page, workspaceReload, operationReload) {
  const reload = Promise.resolve().then(() => page.reload())
  return Promise.all([workspaceReload, operationReload, reload])
}


async function editorScalarCount(editor) {
  return Array.from(await editor.inputValue()).length
}


async function editorDigest(editor) {
  return createHash('sha256').update(await editor.inputValue(), 'utf8').digest('hex')
}


test('@complete streams a readonly preview and reloads an editable WorkingDraft', async ({ page }) => {
  const runtime = await openWriter(page)
  await startGeneration(page)
  const editor = page.getByRole('textbox', { name: '章节正文工作稿' })
  await expect(editor).toHaveAttribute('readonly', '')
  await expect.poll(() => editorScalarCount(editor)).toBe(PARTIAL_SCALAR_COUNT)
  await expect.poll(() => editorDigest(editor)).toBe(PARTIAL_OUTPUT_SHA256)
  await expect(page.getByText('生成完成')).toBeVisible()
  await expect.poll(() => editorScalarCount(editor)).toBe(COMPLETE_SCALAR_COUNT)
  await expect.poll(() => editorDigest(editor)).toBe(COMPLETED_OUTPUT_SHA256)
  await expect(editor).not.toHaveAttribute('readonly', '')
  await page.reload()
  await expect.poll(() => editorScalarCount(editor)).toBe(COMPLETE_SCALAR_COUNT)
  await expect.poll(() => editorDigest(editor)).toBe(COMPLETED_OUTPUT_SHA256)
  const evidence = await runtime.finish()
  assertHealthy(evidence, 1)
})


test('@reconnect reload restores one persisted partial without provider recall', async ({ page }) => {
  const runtime = await openWriter(page)
  await startGeneration(page)
  const editor = page.getByRole('textbox', { name: '章节正文工作稿' })
  await expect.poll(() => editorScalarCount(editor)).toBe(PARTIAL_SCALAR_COUNT)
  await expect.poll(() => editorDigest(editor)).toBe(PARTIAL_OUTPUT_SHA256)
  const workspaceReload = page.waitForResponse(response => isLoopbackGet(response, workspaceReloadPath))
  const operationReload = page.waitForResponse(response => isLoopbackGet(response, activeDraftOperationReloadPath))
  const [workspaceResponse, operationResponse] = await reloadWithRecoveryObservers(page, workspaceReload, operationReload)
  await expect(workspaceResponse.status()).toBe(200)
  await expect(operationResponse.status()).toBe(200)
  await expect(page.getByRole('status')).toHaveText('正在恢复连接')
  await expect(editor).toHaveAttribute('readonly', '')
  await expect.poll(() => editorScalarCount(editor)).toBe(PARTIAL_SCALAR_COUNT)
  await expect.poll(() => editorDigest(editor)).toBe(PARTIAL_OUTPUT_SHA256)
  const evidence = await runtime.finish()
  assertHealthy(evidence, 1)
})


test('@cancel-output preserves the latest partial after reload', async ({ page }) => {
  const runtime = await openWriter(page)
  await startGeneration(page)
  const editor = page.getByRole('textbox', { name: '章节正文工作稿' })
  await expect.poll(() => editorScalarCount(editor)).toBe(PARTIAL_SCALAR_COUNT)
  await expect.poll(() => editorDigest(editor)).toBe(PARTIAL_OUTPUT_SHA256)
  await page.getByRole('button', { name: '停止生成' }).click()
  await expect(page.getByText('已停止，已保留生成内容')).toBeVisible()
  await expect.poll(() => editorScalarCount(editor)).toBe(PARTIAL_SCALAR_COUNT)
  await expect.poll(() => editorDigest(editor)).toBe(PARTIAL_OUTPUT_SHA256)
  await expect(editor).not.toHaveAttribute('readonly', '')
  await page.reload()
  await expect.poll(() => editorScalarCount(editor)).toBe(PARTIAL_SCALAR_COUNT)
  await expect.poll(() => editorDigest(editor)).toBe(PARTIAL_OUTPUT_SHA256)
  const evidence = await runtime.finish()
  assertHealthy(evidence, 2)
})


test('@cancel-empty restores the original WorkingDraft after reload', async ({ page }) => {
  const runtime = await openWriter(page)
  const editor = page.getByRole('textbox', { name: '章节正文工作稿' })
  await expect.poll(() => editorDigest(editor)).toBe(BASE_WORKING_DRAFT_SHA256)
  await startGeneration(page)
  await waitForAcceptedProviderCall()
  await page.getByRole('button', { name: '停止生成' }).click()
  await expect(page.getByText('已停止，正文未改变')).toBeVisible()
  await expect.poll(() => editorDigest(editor)).toBe(BASE_WORKING_DRAFT_SHA256)
  await page.reload()
  await expect.poll(() => editorDigest(editor)).toBe(BASE_WORKING_DRAFT_SHA256)
  const evidence = await runtime.finish()
  assertHealthy(evidence, 2)
})
