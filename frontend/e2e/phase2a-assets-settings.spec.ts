import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'


const PROJECT_TITLE = 'Phase 2A 浏览器项目'
const PROVIDER_A = 'Phase 2A 合成 Provider A'
const PROVIDER_B = 'Phase 2A 合成 Provider B'
const PROVIDER_OPTION_A = `${PROVIDER_A} · phase2a-model-a`
const PROVIDER_OPTION_B = `${PROVIDER_B} · phase2a-model-b`
const REFERENCED_CORPUS = '合成引用保护样本'
const VERSIONED_CORPUS = '合成版本语料'
const STRICT_UUID = String.raw`[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}`


function requiredRunnerOrigin(name: string) {
  const value = process.env[name]
  if (!value || !/^http:\/\/127\.0\.0\.1:\d+$/u.test(value)) {
    throw new Error(`${name} must identify one exact runner-owned origin`)
  }
  return value
}


const VITE_ORIGIN = requiredRunnerOrigin('BROWSER_VITE_ORIGIN')
const BACKEND_ORIGIN = requiredRunnerOrigin('BROWSER_BACKEND_ORIGIN')
if (VITE_ORIGIN === BACKEND_ORIGIN) {
  throw new Error('runner-owned Vite and backend origins must be distinct')
}


async function selectOption(
  page,
  select,
  optionName: string | RegExp,
) {
  await select.click()
  const visibleOverlay = page.locator('.n-base-select-menu:visible')
  await expect(visibleOverlay).toHaveCount(1)
  const option = visibleOverlay.getByText(optionName, {
    exact: typeof optionName === 'string',
  })
  await expect(option).toHaveCount(1)
  await expect(option).toBeVisible()
  await option.click()
}


function observedWrites(evidence) {
  const isWrite = entry => !['GET', 'HEAD', 'OPTIONS'].includes(entry.method)
  return {
    requests: (evidence.requests || []).filter(isWrite).map(entry => ({
      method: entry.method,
      path: `${new URL(entry.url).pathname}${new URL(entry.url).search}`,
    })),
    responses: (evidence.apiResponses || []).filter(isWrite).map(entry => ({
      method: entry.method,
      path: `${new URL(entry.url).pathname}${new URL(entry.url).search}`,
      status: entry.status,
    })),
  }
}


async function importCorpus(
  page,
  {
    openButton,
    fileName,
    displayName,
    notes,
  }: {
    openButton: string
    fileName: string
    displayName: string
    notes: string
  },
) {
  await page.getByRole('button', { name: openButton, exact: true }).click()
  const dialog = page.getByRole('dialog').filter({ hasText: 'CORPUS INTAKE' })
  await expect(dialog).toBeVisible()
  const sourceField = dialog.locator('.n-form-item').filter({
    has: page.getByText('来源文件', { exact: true }),
  })
  await expect(sourceField).toHaveCount(1)
  await selectOption(
    page,
    sourceField.getByRole('textbox'),
    new RegExp(`^${fileName.replaceAll('.', '\\.')} · \\d+ B$`, 'u'),
  )
  const nameInput = dialog.getByPlaceholder('例如：北境卷叙事样本')
  await nameInput.fill(displayName)
  await dialog.getByPlaceholder('记录适用场景、版本差异或使用边界').fill(notes)
  await dialog.getByRole('button', { name: '确认导入', exact: true }).click()
  await expect(dialog).toBeHidden()
}


test('accepts Phase 2A assets, corpus, Provider, fallback, and model bindings', async ({
  page,
}) => {
  const runtime = observeRuntime(page)
  const sensitiveValues = runtimeSensitiveValues()
  const checkpointSurfaces: Array<{ dom: string; visibleText: string }> = []
  let bodyError: unknown = null
  let auditError: unknown = null
  const auditCheckpoint = async (label: string) => {
    await page.waitForLoadState('networkidle')
    const [dom, visibleText] = await Promise.all([
      page.content(),
      page.locator('body').innerText(),
    ])
    expect(
      scanRuntimeEvidence({
        checkpointSurfaces: [{ dom, visibleText }],
      }, sensitiveValues),
      `runtime-sensitive content found at ${label} checkpoint`,
    ).toEqual({ matchCount: 0 })
    checkpointSurfaces.push({ dom, visibleText })
  }

  try {
    await page.goto('/')
    await expect(page).toHaveURL(/\/projects$/u)
    await expect(page.getByRole('heading', { name: '项目库', exact: true })).toBeVisible()
    await auditCheckpoint('project-library')

    await page.getByRole('link', { name: '已归档', exact: true }).click()
    await expect(page).toHaveURL(/\/projects\/archived$/u)
    await expect(page.getByRole('heading', { name: '已归档项目', exact: true })).toBeVisible()
    await auditCheckpoint('archived-projects')
    await page.getByRole('link', { name: '返回项目库', exact: true }).click()

    await page.getByRole('button', { name: '新建项目', exact: true }).click()
    const projectDialog = page.getByRole('dialog', { name: '新建项目' })
    await projectDialog.getByLabel('项目名称').fill(PROJECT_TITLE)
    await projectDialog.getByRole('button', { name: '创建并打开', exact: true }).click()
    await expect.poll(() => new URL(page.url()).pathname).toMatch(
      new RegExp(String.raw`^/projects/${STRICT_UUID}/overview$`, 'u'),
    )
    const projectId = new URL(page.url()).pathname.split('/')[2]
    expect(projectId).toMatch(new RegExp(String.raw`^${STRICT_UUID}$`, 'u'))
    await expect(page.getByRole('heading', { name: PROJECT_TITLE, exact: true })).toBeVisible()
    await auditCheckpoint('project-overview')

    await page.goto('/assets/styles')
    await expect(page.getByRole('heading', { name: '风格模板库', exact: true })).toBeVisible()
    await expect(page.getByText('APPROVED STYLES', { exact: true }).locator('..')).toContainText('10')
    await expect(page.locator('.style-grid article')).toHaveCount(10)
    await page.getByRole('textbox', { name: '搜索风格' }).fill('稳健求生积累型')
    await expect(page.locator('.style-grid article')).toHaveCount(1)
    await page.getByRole('button', { name: '查看批准示例', exact: true }).click()
    const styleDrawer = page.getByRole('dialog').filter({ hasText: '风格模板详情' })
    await expect(styleDrawer.getByRole('heading', { name: '稳健求生积累型' })).toBeVisible()
    await expect(styleDrawer.getByText('APPROVED EXAMPLE · 批准示例', { exact: true })).toBeVisible()
    await styleDrawer.getByRole('button', { name: '关闭', exact: true }).click()
    await auditCheckpoint('style-library')

    await page.locator('.library-hero').getByRole('link', {
      name: '经验卡',
      exact: true,
    }).click()
    await expect(page).toHaveURL(/\/assets\/experience$/u)
    await expect(page.getByText('APPROVED CARDS', { exact: true }).locator('..')).toContainText('64')
    await expect(page.locator('.card-grid article')).toHaveCount(64)
    await page.getByPlaceholder('搜索标题、stable key 或类别').fill('目标旁边放私人成本')
    await expect(page.locator('.card-grid article')).toHaveCount(1)
    await page.getByRole('button', { name: /展开方法与示例/u }).click()
    const cardDrawer = page.getByRole('dialog').filter({ hasText: '经验卡详情' })
    await expect(cardDrawer.getByRole('heading', { name: '目标旁边放私人成本' })).toBeVisible()
    await expect(cardDrawer.getByText('METHOD · 方法', { exact: true })).toBeVisible()
    await cardDrawer.getByRole('button', { name: '关闭', exact: true }).click()
    await auditCheckpoint('experience-library')

    await page.goto('/assets/corpus')
    await expect(page.getByRole('heading', { name: '语料档案室', exact: true })).toBeVisible()
    const referencedCard = page.locator('.source-card').filter({
      has: page.getByRole('heading', { name: REFERENCED_CORPUS, exact: true }),
    })
    await expect(referencedCard).toContainText('当前引用 1')
    await referencedCard.getByRole('button', { name: '打开档案 →', exact: true }).click()
    let corpusDrawer = page.getByRole('dialog').filter({ hasText: REFERENCED_CORPUS })
    await corpusDrawer.getByRole('button', { name: '归档来源', exact: true }).click()
    await expect(corpusDrawer.getByRole('button', { name: '永久删除', exact: true })).toBeDisabled()
    await expect(corpusDrawer.getByText('当前或历史创作契约仍引用此来源。', { exact: true })).toBeVisible()
    await corpusDrawer.getByRole('button', { name: '恢复来源', exact: true }).click()
    await page.keyboard.press('Escape')
    await expect(corpusDrawer).toBeHidden()
    await auditCheckpoint('corpus-reference-protection')

    await importCorpus(page, {
      openButton: '导入语料',
      fileName: 'phase2a-version-1.txt',
      displayName: VERSIONED_CORPUS,
      notes: '浏览器导入的第一版合成文本',
    })
    const versionedCard = page.locator('.source-card').filter({
      has: page.getByRole('heading', { name: VERSIONED_CORPUS, exact: true }),
    })
    await expect(versionedCard).toContainText('r1')
    await versionedCard.getByRole('button', { name: '打开档案 →', exact: true }).click()
    corpusDrawer = page.getByRole('dialog').filter({ hasText: VERSIONED_CORPUS })
    await importCorpus(page, {
      openButton: '导入新版本',
      fileName: 'phase2a-version-2.txt',
      displayName: VERSIONED_CORPUS,
      notes: '浏览器导入的第二版合成文本',
    })
    await expect(versionedCard).toContainText('r2')
    await versionedCard.getByRole('button', { name: '打开档案 →', exact: true }).click()
    corpusDrawer = page.getByRole('dialog').filter({ hasText: VERSIONED_CORPUS })
    await expect(corpusDrawer.locator('.version-list li')).toHaveCount(2)
    await corpusDrawer.getByRole('button', { name: '归档来源', exact: true }).click()
    await corpusDrawer.getByRole('button', { name: '恢复来源', exact: true }).click()
    await corpusDrawer.getByRole('button', { name: '归档来源', exact: true }).click()
    await corpusDrawer.getByRole('button', { name: '永久删除', exact: true }).click()
    const deleteDialog = page.getByRole('alertdialog').filter({
      hasText: '永久删除这份语料？',
    })
    await expect(deleteDialog).toBeVisible()
    await deleteDialog.getByRole('button', { name: '确认永久删除', exact: true }).click()
    await expect(corpusDrawer).toBeHidden()
    await expect(page.locator('.drawer-alert')).toHaveCount(0)
    await expect(versionedCard).toHaveCount(0)
    await auditCheckpoint('corpus-lifecycle')

    await page.goto('/settings/application')
    await expect(page.getByRole('heading', { name: '应用默认与诊断', exact: true })).toBeVisible()
    const fallbackSheet = page.locator('.fallback-sheet')
    await selectOption(
      page,
      fallbackSheet.getByRole('textbox'),
      PROVIDER_OPTION_B,
    )
    await fallbackSheet.getByRole('button', { name: '保存 fallback', exact: true }).click()
    await expect(fallbackSheet).toContainText(PROVIDER_B)
    await expect(page.getByText('writer-core-v1.3.0', { exact: true })).toBeVisible()
    await auditCheckpoint('application-settings')

    await page.goto(`/projects/${projectId}/settings/models`)
    await expect(page.getByRole('heading', { name: '项目模型绑定', exact: true })).toBeVisible()
    const binding = page.locator('.binding-ledger')
    await selectOption(
      page,
      binding.locator('.simple-binding').getByRole('textbox'),
      PROVIDER_OPTION_B,
    )
    await binding.getByRole('button', { name: '保存完整八项', exact: true }).click()
    await expect(binding.getByText('完整八项快照已保存，后端确认 Ready。', { exact: true })).toBeVisible()
    await binding.getByRole('button', { name: /高级设置 · 分别绑定八项/u }).click()
    const advancedSelects = binding.locator('.binding-grid').getByRole('textbox')
    await expect(advancedSelects).toHaveCount(8)
    const seedBinding = binding.locator('.binding-row').filter({
      hasText: '种子与故事发动机',
    })
    await expect(seedBinding).toHaveCount(1)
    await selectOption(page, seedBinding.getByRole('textbox'), PROVIDER_OPTION_A)
    await binding.getByRole('button', { name: '保存完整八项', exact: true }).click()
    await expect(binding.getByText('完整八项快照已保存，后端确认 Ready。', { exact: true })).toBeVisible()
    await auditCheckpoint('model-bindings')

    await page.goto('/settings/providers')
    await expect(page.getByRole('heading', { name: 'Provider 与模型', exact: true })).toBeVisible()
    const providerCard = page.locator('.provider-card').filter({
      hasText: PROVIDER_A,
    })
    await providerCard.getByRole('button', { name: '编辑', exact: true }).click()
    const providerDialog = page.getByRole('dialog').filter({ hasText: '编辑 Provider' })
    await expect(providerDialog.getByPlaceholder('留空保留现有密钥')).toHaveValue('')
    await expect(providerDialog.getByPlaceholder('留空保留现有地址')).toHaveValue('')
    await providerDialog.getByPlaceholder('仅保存公开说明，不填写密钥').fill('浏览器只修改公开备注')
    await providerDialog.getByRole('button', { name: '保存', exact: true }).click()
    await expect(providerDialog).toBeHidden()
    await providerCard.getByRole('button', { name: '编辑', exact: true }).click()
    await expect(providerDialog.getByPlaceholder('留空保留现有密钥')).toHaveValue('')
    await expect(providerDialog.getByPlaceholder('留空保留现有地址')).toHaveValue('')
    await expect(
      providerDialog.getByPlaceholder('仅保存公开说明，不填写密钥'),
    ).toHaveValue('浏览器只修改公开备注')
    await providerDialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(providerDialog).toBeHidden()
    await auditCheckpoint('provider-public-note')
    await providerCard.getByRole('button', { name: '测试连接', exact: true }).click()
    await expect(providerCard.getByText('连接成功', { exact: false })).toBeVisible()
    await providerCard.getByRole('button', { name: '清除 API Key', exact: true }).click()
    const clearDialog = page.getByRole('dialog').filter({ hasText: '清除 API Key' })
    await expect(clearDialog).toBeVisible()
    await clearDialog.getByRole('button', { name: '清除密钥', exact: true }).click()
    await expect(providerCard).toContainText('未配置')
    await auditCheckpoint('provider-credential-clear')

    await page.goto('/assets/styles')
    await expect(page.getByRole('heading', { name: '风格模板库', exact: true })).toBeVisible()
    await expect(page.locator('.style-grid article')).toHaveCount(10)
    await page.waitForLoadState('networkidle')
    await page.goBack()
    await expect(page).toHaveURL(/\/settings\/providers$/u)
    await page.waitForLoadState('networkidle')
    await page.goForward()
    await expect(page).toHaveURL(/\/assets\/styles$/u)
    await expect(page.locator('.style-grid article')).toHaveCount(10)
    await page.waitForLoadState('networkidle')
    await auditCheckpoint('history-navigation')
  } catch (error) {
    bodyError = error
  } finally {
    try {
      const evidence = await runtime.finish()
      const auditedEvidence = { ...evidence, checkpointSurfaces }
      const deleteRequests = evidence.requests.filter(entry => {
        if (entry.method !== 'DELETE') return false
        const url = new URL(entry.url)
        return (
          url.search === ''
          && url.hash === ''
          && /^\/api\/corpus\/sources\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u
            .test(url.pathname)
        )
      })
      expect(deleteRequests).toHaveLength(1)
      expect(deleteRequests[0].bodyReadError).toBe('')
      const deleteBody = JSON.parse(deleteRequests[0].body)
      expect(Object.keys(deleteBody).sort()).toEqual([
        'confirmPermanentDelete',
        'expectedRevision',
      ])
      expect(deleteBody.confirmPermanentDelete).toBe(true)
      expect(Number.isInteger(deleteBody.expectedRevision)).toBe(true)
      expect(deleteBody.expectedRevision).toBeGreaterThan(0)
      try {
        assertExactWrites(auditedEvidence, [
        { method: 'POST', path: '/api/projects', statuses: [200], count: 1 },
        {
          method: 'POST',
          path: /^\/api\/corpus\/sources\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/archive$/u,
          statuses: [200],
          count: 3,
        },
        {
          method: 'POST',
          path: /^\/api\/corpus\/sources\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/restore$/u,
          statuses: [200],
          count: 2,
        },
        { method: 'POST', path: '/api/corpus/imports', statuses: [200], count: 2 },
        {
          method: 'DELETE',
          path: /^\/api\/corpus\/sources\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u,
          statuses: [204],
          count: 1,
        },
        {
          method: 'PUT',
          path: '/api/settings/application/default-model',
          statuses: [200],
          count: 1,
        },
        {
          method: 'PUT',
          path: /^\/api\/projects\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/bindings$/u,
          statuses: [200],
          count: 2,
        },
        {
          method: 'PUT',
          path: /^\/api\/providers\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u,
          statuses: [200],
          count: 1,
        },
        {
          method: 'POST',
          path: /^\/api\/providers\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/test-connection$/u,
          statuses: [200],
          count: 1,
        },
        {
          method: 'POST',
          path: /^\/api\/providers\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\/clear-api-key$/u,
          statuses: [200],
          count: 1,
        },
        ])
      } catch (error) {
        throw new Error(
          `${error instanceof Error ? error.message : String(error)}; `
          + `observed=${JSON.stringify(observedWrites(auditedEvidence))}`,
          { cause: error },
        )
      }
      expect(evidence.consoleErrors).toEqual([])
      expect(evidence.pageErrors).toEqual([])
      expect(evidence.requestFailures).toEqual([])
      expect(evidence.responseFailures).toEqual([])
      expect(evidence.apiResponses.filter(entry => entry.bodyReadError)).toEqual([])
      expect(evidence.requests.filter(entry => entry.bodyReadError)).toEqual([])
      const runnerOrigins = new Set([VITE_ORIGIN, BACKEND_ORIGIN])
      expect(
        evidence.requests.every(entry => runnerOrigins.has(new URL(entry.url).origin)),
        'every browser request must use an exact runner-owned origin',
      ).toBe(true)
      expect(
        evidence.responses.every(entry => runnerOrigins.has(new URL(entry.url).origin)),
        'every browser response must use an exact runner-owned origin',
      ).toBe(true)
      expect(
        evidence.apiResponses.every(entry => new URL(entry.url).origin === BACKEND_ORIGIN),
        'every API response must use the exact runner-owned backend origin',
      ).toBe(true)
      expect(new URL(page.url()).origin).toBe(VITE_ORIGIN)
      expect(scanRuntimeEvidence(auditedEvidence, sensitiveValues)).toEqual({
        matchCount: 0,
      })
    } catch (error) {
      auditError = error
    }
    if (bodyError && auditError) {
      throw new AggregateError(
        [bodyError, auditError],
        'Phase 2A behavior and runtime audit both failed',
      )
    }
    if (bodyError) throw bodyError
    if (auditError) throw auditError
  }
})
