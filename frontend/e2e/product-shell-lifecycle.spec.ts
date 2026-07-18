import { expect, test, type Page, type Response } from '@playwright/test'

import {
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'


const PROJECT_TITLE = '典镇山河'
const RENAMED_TITLE = '典镇山河·修订稿'


function apiPath(response: Response) {
  return new URL(response.url()).pathname
}


function projectOverviewPath(projectId: string) {
  return `/projects/${encodeURIComponent(projectId)}/overview`
}


async function waitForProjectMutation(
  page: Page,
  method: string,
  suffix: string,
) {
  return page.waitForResponse(response => (
    response.request().method() === method
    && apiPath(response).endsWith(suffix)
  ))
}


async function openProjectMenu(page: Page, title: string) {
  const card = page.locator('.project-card').filter({ hasText: title })
  await card.locator('summary', { hasText: '更多' }).click()
  return card
}


async function archiveFromLibrary(page: Page, title: string) {
  const card = await openProjectMenu(page, title)
  const responsePromise = waitForProjectMutation(page, 'POST', '/archive')
  await card.getByRole('button', { name: '归档', exact: true }).click()
  const response = await responsePromise
  expect(response.ok()).toBe(true)
  return response.json()
}


test('product shell lifecycle is accessible, durable, owned, and secret-safe', async ({ page }) => {
  const runtimeObserver = observeRuntime(page)
  let createRequests = 0
  let deleteRequests = 0
  const countWrites = (request: { method(): string, url(): string }) => {
    const pathname = new URL(request.url()).pathname
    if (request.method() === 'POST' && pathname === '/api/projects') createRequests += 1
    if (request.method() === 'DELETE' && /^\/api\/projects\/[^/]+$/u.test(pathname)) {
      deleteRequests += 1
    }
  }
  page.on('request', countWrites)

  try {
    await page.goto('/projects')
    await expect(page.getByRole('heading', { name: '项目库', exact: true })).toBeVisible()

    const createTrigger = page.locator('.project-library-heading__actions')
      .getByRole('button', { name: '新建项目', exact: true })
    await createTrigger.focus()
    await expect(createTrigger).toBeFocused()
    await createTrigger.click()

    let nameDialog = page.getByRole('dialog', { name: '新建项目' })
    const createInput = nameDialog.getByRole('textbox', { name: '项目名称' })
    await expect(nameDialog).toBeVisible()
    await expect(createInput).toBeFocused()
    await expect(page.locator('#app')).toHaveAttribute('inert', '')
    await expect(page.locator('#app').locator('[role="dialog"]')).toHaveCount(0)

    const imeEvidence = await createInput.evaluate(input => {
      const element = input as HTMLInputElement
      element.value = '典'
      element.dispatchEvent(new CompositionEvent('compositionstart', {
        bubbles: true,
        data: '典',
      }))
      const compositionEnter = new KeyboardEvent('keydown', {
        bubbles: true,
        cancelable: true,
        key: 'Enter',
      })
      Object.defineProperty(compositionEnter, 'isComposing', { value: true })
      const compositionDispatched = element.dispatchEvent(compositionEnter)
      const legacyImeEnter = new KeyboardEvent('keydown', {
        bubbles: true,
        cancelable: true,
        key: 'Enter',
      })
      Object.defineProperty(legacyImeEnter, 'keyCode', { value: 229 })
      const legacyDispatched = element.dispatchEvent(legacyImeEnter)
      element.dispatchEvent(new CompositionEvent('compositionend', {
        bubbles: true,
        data: '典',
      }))
      return {
        compositionDispatched,
        compositionPrevented: compositionEnter.defaultPrevented,
        legacyDispatched,
        legacyPrevented: legacyImeEnter.defaultPrevented,
      }
    })
    expect(imeEvidence).toEqual({
      compositionDispatched: true,
      compositionPrevented: false,
      legacyDispatched: true,
      legacyPrevented: false,
    })
    expect(createRequests).toBe(0)
    await expect(nameDialog).toBeVisible()

    await createInput.press('Tab')
    const cancelNameButton = nameDialog.getByRole('button', { name: '取消', exact: true })
    const submitNameButton = nameDialog.getByRole('button', { name: '创建并打开' })
    await expect(cancelNameButton).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(submitNameButton).toBeFocused()
    await page.keyboard.press('Tab')
    await expect(createInput).toBeFocused()
    await page.keyboard.press('Shift+Tab')
    await expect(submitNameButton).toBeFocused()
    await expect(page.locator('.product-app-shell').locator(':focus')).toHaveCount(0)

    await page.keyboard.press('Escape')
    await expect(nameDialog).toBeHidden()
    await expect(createTrigger).toBeFocused()
    await expect(page.locator('#app')).not.toHaveAttribute('inert', '')

    await createTrigger.click()
    nameDialog = page.getByRole('dialog', { name: '新建项目' })
    await expect(nameDialog.getByRole('textbox')).toHaveCount(1)
    await expect(nameDialog.getByRole('textbox', { name: '项目名称' })).toHaveCount(1)
    await expect(nameDialog.locator('input, textarea, select')).toHaveCount(1)

    const createResponsePromise = page.waitForResponse(response => (
      response.request().method() === 'POST'
      && apiPath(response) === '/api/projects'
    ))
    const finalCreateInput = nameDialog.getByRole('textbox', { name: '项目名称' })
    await finalCreateInput.fill(PROJECT_TITLE)
    await finalCreateInput.press('Enter')
    const createResponse = await createResponsePromise
    expect(createResponse.ok()).toBe(true)
    const createdProject = await createResponse.json()
    const projectId = String(createdProject.id)
    const overviewPath = projectOverviewPath(projectId)
    await expect.poll(() => createRequests).toBe(1)
    await expect(page).toHaveURL(new RegExp(`${overviewPath.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')}$`, 'u'))

    await page.goto('/projects')
    const activeCard = page.locator('.project-card').filter({ hasText: PROJECT_TITLE })
    await expect(activeCard).toBeVisible()
    const beforeWhitespaceClick = page.url()
    await activeCard.locator('.project-card__body').click()
    expect(page.url()).toBe(beforeWhitespaceClick)
    await activeCard.getByRole('button', { name: '打开项目', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`${overviewPath.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')}$`, 'u'))
    await expect(page.getByRole('heading', { name: PROJECT_TITLE, exact: true })).toBeVisible()

    await page.reload()
    await expect(page.getByRole('heading', { name: PROJECT_TITLE, exact: true })).toBeVisible()
    await expect(page.locator('.product-sidebar__project-title')).toHaveText(PROJECT_TITLE)
    await expect(page.locator('.product-topbar__breadcrumbs').getByRole('link', {
      name: '项目库',
      exact: true,
    })).toHaveAttribute('href', '/projects')
    await expect(page.locator('.product-topbar__breadcrumbs').getByRole('link', {
      name: PROJECT_TITLE,
      exact: true,
    })).toHaveAttribute('href', overviewPath)

    await page.goto('/projects')
    let card = await openProjectMenu(page, PROJECT_TITLE)
    await card.getByRole('button', { name: '重命名', exact: true }).click()
    const renameDialog = page.getByRole('dialog', { name: '编辑项目名称' })
    const renameInput = renameDialog.getByRole('textbox', { name: '项目名称' })
    await expect(renameInput).toHaveValue(PROJECT_TITLE)
    const renameResponsePromise = waitForProjectMutation(page, 'PUT', `/projects/${projectId}`)
    await renameInput.fill(RENAMED_TITLE)
    await renameInput.press('Enter')
    const renameResponse = await renameResponsePromise
    expect(renameResponse.ok()).toBe(true)
    const renamedProject = await renameResponse.json()
    expect(renamedProject.title).toBe(RENAMED_TITLE)
    await expect(page.locator('.project-card').filter({ hasText: RENAMED_TITLE })).toBeVisible()
    await page.locator('.project-card').filter({ hasText: RENAMED_TITLE })
      .getByRole('button', { name: '打开项目', exact: true }).click()
    await expect(page.getByRole('heading', { name: renamedProject.title, exact: true })).toBeVisible()

    await page.goto('/projects')
    await expect(page.getByRole('dialog')).toHaveCount(0)
    const firstArchived = await archiveFromLibrary(page, RENAMED_TITLE)
    await expect(page.getByRole('dialog')).toHaveCount(0)
    const undo = page.getByRole('button', { name: '撤销', exact: true })
    await expect(undo).toBeVisible()
    const undoResponsePromise = waitForProjectMutation(page, 'POST', '/restore')
    await undo.click()
    const undoResponse = await undoResponsePromise
    expect(undoResponse.ok()).toBe(true)
    await expect(page.locator('.project-card').filter({ hasText: RENAMED_TITLE })).toBeVisible()

    const secondArchived = await archiveFromLibrary(page, RENAMED_TITLE)
    expect(secondArchived.lifecycleRevision).toBeGreaterThan(firstArchived.lifecycleRevision)
    await page.goto(overviewPath)
    await expect(page.locator('.archived-sheet .status-mark')).toHaveText('已归档')
    await expect(page.getByRole('heading', { name: RENAMED_TITLE, exact: true })).toBeVisible()
    await expect(page.getByText('项目内容仍完整保留，但当前为只读状态。恢复后可继续原来的工作稿。')).toBeVisible()
    await expect(page.locator('.product-sidebar__module-link')).toHaveCount(0)
    const directRestoreResponsePromise = waitForProjectMutation(page, 'POST', '/restore')
    await page.getByRole('button', { name: '恢复项目', exact: true }).click()
    const directRestoreResponse = await directRestoreResponsePromise
    expect(directRestoreResponse.ok()).toBe(true)
    await expect(page.getByText('PROJECT OVERVIEW', { exact: true })).toBeVisible()
    await expect(page.getByRole('heading', { name: RENAMED_TITLE, exact: true })).toBeVisible()

    await page.goto('/projects')
    const thirdArchived = await archiveFromLibrary(page, RENAMED_TITLE)
    const archivedListResponsePromise = page.waitForResponse(response => (
      response.request().method() === 'GET'
      && apiPath(response) === '/api/projects/archived'
    ))
    await page.goto('/projects/archived')
    const archivedListResponse = await archivedListResponsePromise
    const archivedRows = await archivedListResponse.json()
    const archivedRow = archivedRows.find((row: { id: string }) => String(row.id) === projectId)
    expect(archivedRow.lifecycleRevision).toBe(thirdArchived.lifecycleRevision)
    const archivedStoreRevision = await page.evaluate(async targetProjectId => {
      const { useProjectStore } = await import('/src/stores/projectStore.js')
      const project = useProjectStore().archivedProjects.find(
        ({ id }: { id: string }) => String(id) === targetProjectId,
      )
      return project?.lifecycleRevision
    }, projectId)
    expect(archivedStoreRevision).toBe(thirdArchived.lifecycleRevision)
    await expect(page.locator('.project-card--archived').filter({ hasText: RENAMED_TITLE })).toBeVisible()

    card = page.locator('.project-card--archived').filter({ hasText: RENAMED_TITLE })
    await card.getByRole('button', { name: '永久删除', exact: true }).click()
    let dangerousDialog = page.getByRole('dialog').filter({
      hasText: `永久删除《${RENAMED_TITLE}》？`,
    })
    await expect(dangerousDialog).toBeVisible()
    await dangerousDialog.getByRole('button', { name: '取消', exact: true }).click()
    await expect(dangerousDialog).toBeHidden()
    expect(deleteRequests).toBe(0)

    let releaseDelete: (() => void) | undefined
    let deleteInFlight = 0
    let deleteRequestPayload: { expectedLifecycleRevision?: number } | undefined
    await page.route(`**/api/projects/${encodeURIComponent(projectId)}`, async route => {
      if (route.request().method() !== 'DELETE') {
        await route.continue()
        return
      }
      deleteInFlight += 1
      deleteRequestPayload = route.request().postDataJSON()
      await new Promise<void>(resolve => { releaseDelete = resolve })
      try {
        await route.continue()
      } finally {
        deleteInFlight -= 1
      }
    })

    await card.getByRole('button', { name: '永久删除', exact: true }).click()
    dangerousDialog = page.getByRole('dialog').filter({
      hasText: `永久删除《${RENAMED_TITLE}》？`,
    })
    const confirmDelete = dangerousDialog.getByRole('button').filter({
      hasText: '永久删除',
    })
    const cancelDelete = dangerousDialog.getByRole('button', { name: '取消', exact: true })
    await confirmDelete.click()
    await expect.poll(() => deleteInFlight).toBe(1)
    expect(deleteRequests).toBe(1)
    expect(deleteRequestPayload).toEqual({
      expectedLifecycleRevision: thirdArchived.lifecycleRevision,
    })
    await expect(confirmDelete).toBeDisabled()
    await expect(confirmDelete).toHaveClass(/n-button--loading/u)
    await expect(cancelDelete).toBeDisabled()

    await page.keyboard.press('Escape')
    await cancelDelete.click({ force: true })
    await page.mouse.click(5, 5)
    await confirmDelete.click({ force: true })
    await expect(dangerousDialog).toBeVisible()
    expect(deleteInFlight).toBe(1)
    expect(deleteRequests).toBe(1)

    const deleteResponsePromise = page.waitForResponse(response => (
      response.request().method() === 'DELETE'
      && apiPath(response) === `/api/projects/${projectId}`
    ))
    expect(releaseDelete).toBeDefined()
    releaseDelete?.()
    const deleteResponse = await deleteResponsePromise
    expect(deleteResponse.status()).toBe(204)
    await expect(dangerousDialog).toBeHidden()
    await expect(card).toHaveCount(0)
    await page.unroute(`**/api/projects/${encodeURIComponent(projectId)}`)

    await page.goto(overviewPath)
    await expect(page.getByText('项目不存在或已被删除', { exact: true })).toBeVisible()
    await expect(page.getByText('项目暂时无法加载', { exact: true })).toHaveCount(0)

    const recoverableId = 'recoverable-error-project'
    let detailFailureInjected = false
    await page.route(`**/api/projects/${recoverableId}`, async route => {
      if (!detailFailureInjected && route.request().method() === 'GET') {
        detailFailureInjected = true
        await route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({
            error: {
              code: 'synthetic_browser_error',
              message: '浏览器验收注入的可恢复错误',
            },
          }),
        })
        return
      }
      await route.continue()
    })
    await page.goto(projectOverviewPath(recoverableId))
    await expect(page.getByText('项目暂时无法加载', { exact: true })).toBeVisible()
    const retry = page.getByRole('button', { name: '重试', exact: true })
    await expect(retry).toBeVisible()
    await retry.click()
    await expect(page.getByText('项目不存在或已被删除', { exact: true })).toBeVisible()
    await page.unroute(`**/api/projects/${recoverableId}`)

    await page.goto('/projects')
    await page.evaluate(async () => {
      const router = (await import('/src/router/index.js')).default
      await router.push('/settings/providers')
      await router.push('/projects')
    })
    await expect(page).toHaveURL(/\/projects$/u)
    const globalNavigation = page.getByRole('navigation', { name: '全局导航' })
    const priorFocus = globalNavigation.getByRole('link', {
      name: '项目库',
      exact: true,
    })
    await priorFocus.focus()
    await expect(priorFocus).toBeFocused()
    const blockerToken = await page.evaluate(async () => {
      const { useOperationStore } = await import('/src/stores/operationStore.js')
      const store = useOperationStore()
      const token = store.start({
        label: '浏览器验收阻断',
        detail: '验证全局交互边界',
        blocking: true,
      })
      return token
    })
    expect(blockerToken).toMatch(/^operation-\d+$/u)
    const blockingOverlay = page.locator('.app-operation-overlay--blocking')
    await expect(page.locator('.app-interaction-boundary')).toHaveAttribute('inert', '')
    await expect(blockingOverlay).toBeVisible()
    await expect(blockingOverlay).toBeFocused()
    await expect(blockingOverlay).not.toHaveAttribute('inert', '')

    const blockedUrl = page.url()
    await page.keyboard.press('Tab')
    await page.keyboard.press('Enter')
    expect(page.url()).toBe(blockedUrl)
    const blockedFocus = await page.evaluate(() => {
      const activeElement = document.activeElement
      const boundary = document.querySelector('.app-interaction-boundary')
      const globalNavigation = document.querySelector('[aria-label="全局导航"]')
      const overlay = document.querySelector('.app-operation-overlay--blocking')
      return {
        inInteractionBoundary: Boolean(activeElement && boundary?.contains(activeElement)),
        inGlobalNavigation: Boolean(activeElement && globalNavigation?.contains(activeElement)),
        overlayOutsideBoundary: Boolean(overlay && boundary && !boundary.contains(overlay)),
      }
    })
    expect(blockedFocus).toEqual({
      inInteractionBoundary: false,
      inGlobalNavigation: false,
      overlayOutsideBoundary: true,
    })
    await page.evaluate(async () => {
      const router = (await import('/src/router/index.js')).default
      await router.push('/settings/providers')
    })
    expect(page.url()).toBe(blockedUrl)
    await page.evaluate(() => {
      ;(window as typeof window & { __productShellBackEvents?: number })
        .__productShellBackEvents = 0
      window.addEventListener('popstate', () => {
        const state = window as typeof window & { __productShellBackEvents?: number }
        state.__productShellBackEvents = (state.__productShellBackEvents || 0) + 1
      })
    })
    await page.goBack({ timeout: 2_000 }).catch(() => null)
    await expect.poll(async () => page.evaluate(() => (
      (window as typeof window & { __productShellBackEvents?: number })
        .__productShellBackEvents || 0
    ))).toBeGreaterThan(0)
    await expect.poll(async () => page.evaluate(async () => {
      const { useOperationStore } = await import('/src/stores/operationStore.js')
      return {
        blocking: useOperationStore().blocking,
        path: window.location.pathname,
      }
    })).toEqual({
      blocking: true,
      path: '/projects',
    })

    const finishedExactBlocker = await page.evaluate(async token => {
      const { useOperationStore } = await import('/src/stores/operationStore.js')
      return useOperationStore().finish(token)
    }, blockerToken)
    expect(finishedExactBlocker).toBe(true)
    await expect(blockingOverlay).toHaveCount(0)
    await expect(page.locator('.app-interaction-boundary')).not.toHaveAttribute('inert', '')
    await expect(priorFocus).toBeFocused()

    const settingsLink = globalNavigation.getByRole('link', {
      name: '设置',
      exact: true,
    })
    await settingsLink.focus()
    await page.keyboard.press('Enter')
    await expect(page).toHaveURL(/\/settings\/providers$/u)
    await page.evaluate(async () => {
      const router = (await import('/src/router/index.js')).default
      await router.push('/projects')
    })
    await expect(page).toHaveURL(/\/projects$/u)
    await page.goBack()
    await expect(page).toHaveURL(/\/settings\/providers$/u)

    const overlap = await page.evaluate(async () => {
      const { useOperationStore } = await import('/src/stores/operationStore.js')
      const store = useOperationStore()
      const oldBlocker = store.start({ label: '较早阻断', blocking: true })
      const latestNotice = store.start({ label: '最新提示', blocking: false })
      const latestBlocker = store.start({ label: '最新阻断', blocking: true })
      return { oldBlocker, latestNotice, latestBlocker }
    })
    await expect(page.locator('.app-operation-overlay').getByText('最新阻断', { exact: true })).toBeVisible()
    await page.evaluate(async ({ oldBlocker }) => {
      const { useOperationStore } = await import('/src/stores/operationStore.js')
      useOperationStore().finish(oldBlocker)
    }, overlap)
    await expect(page.locator('.app-operation-overlay').getByText('最新阻断', { exact: true })).toBeVisible()
    await page.evaluate(async ({ latestBlocker }) => {
      const { useOperationStore } = await import('/src/stores/operationStore.js')
      useOperationStore().finish(latestBlocker)
    }, overlap)
    await expect(page.locator('.app-operation-overlay--notice').getByText(
      '最新提示',
      { exact: true },
    )).toBeVisible()
    await page.evaluate(async ({ latestNotice }) => {
      const { useOperationStore } = await import('/src/stores/operationStore.js')
      useOperationStore().finish(latestNotice)
    }, overlap)
    await expect(page.locator('.app-operation-overlay')).toHaveCount(0)
  } finally {
    page.off('request', countWrites)
    const evidence = await runtimeObserver.finish()
    const scan = scanRuntimeEvidence(evidence, runtimeSensitiveValues(process.env))
    if (scan.matchCount !== 0) {
      throw new Error('Product-shell browser evidence contained a runtime-sensitive value')
    }
  }
})
