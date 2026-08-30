import { expect, test, type Locator, type Page, type Response } from '@playwright/test'

import {
  assertExactWrites,
  observeRuntime,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
} from './runtime-observer.mjs'


const PROJECT_TITLE = '典镇山河'
const RENAMED_TITLE = '典镇山河·修订稿'
const OVERVIEW_LOGLINE = '以山河典册镇压乱世妖祟。'


function apiPath(response: Response) {
  return new URL(response.url()).pathname
}


function projectOverviewPath(projectId: string) {
  return `/projects/${encodeURIComponent(projectId)}/overview`
}


function projectOverviewSurface(page: Page) {
  return page.locator('.overview-ledger').filter({ hasText: 'MANUSCRIPT LEDGER' })
}


function normalizedResponseFailure(failure: string) {
  const match = /^(?<status>\d{3}) (?<method>[A-Z]+) (?<url>.+)$/u.exec(failure)
  if (!match?.groups) throw new Error('Runtime response failure had an invalid shape')
  return `${match.groups.status} ${match.groups.method} ${new URL(match.groups.url).pathname}`
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


async function waitForRouteReady(page: Page, routeSurface: Locator) {
  await expect(routeSurface).toBeVisible()
  await page.waitForLoadState('networkidle')
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
  let bodyError: unknown
  let auditError: unknown
  let projectId = ''
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
    projectId = String(createdProject.id)
    const overviewPath = projectOverviewPath(projectId)
    await expect.poll(() => createRequests).toBe(1)
    await expect(page).toHaveURL(new RegExp(`${overviewPath.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')}$`, 'u'))
    await waitForRouteReady(
      page,
      projectOverviewSurface(page),
    )

    await page.goto('/projects')
    const activeCard = page.locator('.project-card').filter({ hasText: PROJECT_TITLE })
    await expect(activeCard).toBeVisible()
    const beforeWhitespaceClick = page.url()
    await activeCard.locator('.project-card__body').click()
    expect(page.url()).toBe(beforeWhitespaceClick)
    await activeCard.getByRole('button', { name: '打开项目', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`${overviewPath.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')}$`, 'u'))
    await waitForRouteReady(
      page,
      projectOverviewSurface(page),
    )
    await expect(page.getByRole('heading', { name: PROJECT_TITLE, exact: true })).toBeVisible()

    await page.reload()
    await waitForRouteReady(
      page,
      projectOverviewSurface(page),
    )
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
    await waitForRouteReady(
      page,
      projectOverviewSurface(page),
    )
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
    await waitForRouteReady(page, projectOverviewSurface(page))
    await expect(page.locator('.project-page-header__archive')).toHaveText('已归档 · 只读')
    await expect(page.getByRole('heading', { name: RENAMED_TITLE, exact: true })).toBeVisible()
    await expect(page.locator('.product-sidebar').getByRole('link', {
      name: '导出与备份',
      exact: true,
    })).toBeVisible()
    await expect(page.locator('.product-sidebar').getByRole('link', {
      name: '创作种子',
      exact: true,
    })).toHaveCount(0)
    await expect(page.locator('.product-sidebar').getByRole('link', {
      name: '模型绑定',
      exact: true,
    })).toHaveCount(0)
    const archivedForRestoreResponsePromise = page.waitForResponse(response => (
      response.request().method() === 'GET'
      && apiPath(response) === '/api/projects/archived'
    ))
    await page.goto('/projects/archived')
    await archivedForRestoreResponsePromise
    const archivedForRestore = page.locator('.project-card--archived').filter({
      hasText: RENAMED_TITLE,
    })
    const directRestoreResponsePromise = waitForProjectMutation(page, 'POST', '/restore')
    await archivedForRestore.getByRole('button', { name: '恢复', exact: true }).click()
    const directRestoreResponse = await directRestoreResponsePromise
    expect(directRestoreResponse.ok()).toBe(true)
    await page.goto(overviewPath)
    await waitForRouteReady(
      page,
      projectOverviewSurface(page),
    )
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
    let deleteReleased = false
    let deleteInFlight = 0
    let deleteRequestPayload: { expectedLifecycleRevision?: number } | undefined
    const deleteRoute = `**/api/projects/${encodeURIComponent(projectId)}`
    const releasePendingDelete = () => {
      if (deleteReleased || !releaseDelete) return
      deleteReleased = true
      releaseDelete()
    }
    await page.route(deleteRoute, async route => {
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

    try {
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
      releasePendingDelete()
      const deleteResponse = await deleteResponsePromise
      expect(deleteResponse.status()).toBe(204)
      await expect(dangerousDialog).toBeHidden()
      await expect(card).toHaveCount(0)
    } finally {
      releasePendingDelete()
      await page.unroute(deleteRoute)
    }

    await page.goto(overviewPath)
    await waitForRouteReady(
      page,
      page.locator('.route-state-page').filter({ hasText: '项目不存在或已被删除' }),
    )
    await expect(page.getByText('项目概览暂时无法加载', { exact: true })).toHaveCount(0)

    await page.goto('/projects')
    await waitForRouteReady(page, page.locator('.project-library-page'))
    await page.evaluate(async () => {
      const router = (await import('/src/router/index.js')).default
      await router.push('/settings/providers')
    })
    await waitForRouteReady(page, page.locator('.provider-route'))
    await page.evaluate(async () => {
      const router = (await import('/src/router/index.js')).default
      await router.push('/projects')
    })
    await expect(page).toHaveURL(/\/projects$/u)
    await waitForRouteReady(page, page.locator('.project-library-page'))
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
    await waitForRouteReady(page, page.locator('.provider-route'))
    await page.evaluate(async () => {
      const router = (await import('/src/router/index.js')).default
      await router.push('/projects')
    })
    await expect(page).toHaveURL(/\/projects$/u)
    await waitForRouteReady(page, page.locator('.project-library-page'))
    await page.goBack()
    await expect(page).toHaveURL(/\/settings\/providers$/u)
    await waitForRouteReady(page, page.locator('.provider-route'))

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
  } catch (error) {
    bodyError = error
  } finally {
    page.off('request', countWrites)
    try {
      const evidence = await runtimeObserver.finish()
      assertExactWrites(evidence, [
        {
          method: 'POST',
          path: '/api/projects',
          statuses: [200],
          count: 1,
        },
        {
          method: 'PUT',
          path: `/api/projects/${projectId}`,
          statuses: [200],
          count: 1,
        },
        {
          method: 'POST',
          path: `/api/projects/${projectId}/archive`,
          statuses: [200],
          count: 3,
        },
        {
          method: 'POST',
          path: `/api/projects/${projectId}/restore`,
          statuses: [200],
          count: 2,
        },
        {
          method: 'DELETE',
          path: `/api/projects/${projectId}`,
          statuses: [204],
          count: 1,
        },
      ])
      expect(
        evidence.consoleErrors.sort(),
        'the deliberate 404/500 suite audit permits only this lifecycle deleted project 404',
      ).toEqual([
        'error: Failed to load resource: the server responded with a status of 404 (Not Found)',
      ])
      expect(evidence.pageErrors, 'page errors must stay empty').toEqual([])
      expect(evidence.requestFailures, 'request failures must stay empty').toEqual([])
      expect(
        evidence.responseFailures.map(normalizedResponseFailure).sort(),
        'only the deleted project detail 404 is allowed',
      ).toEqual([
        `404 GET /api/projects/${projectId}`,
      ])
      const scan = scanRuntimeEvidence(evidence, runtimeSensitiveValues(process.env))
      if (scan.matchCount !== 0) {
        throw new Error('Product-shell browser evidence contained a runtime-sensitive value')
      }
    } catch (error) {
      auditError = error
    }
    if (bodyError && auditError) {
      throw new AggregateError(
        [bodyError, auditError],
        'Product-shell browser behavior and runtime audit both failed',
      )
    }
    if (bodyError) throw bodyError
    if (auditError) throw auditError
  }
})


test('project overview supports the complete manual product flow across desktop and mobile', async ({ page }) => {
  const runtimeObserver = observeRuntime(page)
  let bodyError: unknown
  let auditError: unknown
  let projectId = ''
  let routedProjectId = ''
  let overviewGetCount = 0

  try {
    await page.setViewportSize({ width: 1440, height: 720 })
    await page.route('**/api/projects/*/overview', async route => {
      const request = route.request()
      const match = /^\/api\/projects\/(?<projectId>[^/]+)\/overview$/u.exec(
        new URL(request.url()).pathname,
      )
      if (request.method() !== 'GET' || !match?.groups) {
        await route.continue()
        return
      }

      routedProjectId = decodeURIComponent(match.groups.projectId)
      overviewGetCount += 1
      if (overviewGetCount === 1) {
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

      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          project: {
            id: routedProjectId,
            title: PROJECT_TITLE,
            genre: '东方玄幻',
            logline: OVERVIEW_LOGLINE,
            targetWords: 2_400_000,
            targetChapters: 800,
            updatedAtMs: 1_777_777_777_000,
            lifecycle: 'active',
          },
          progress: {
            authoritativeChapterNumber: overviewGetCount >= 3 ? 5 : 4,
            currentVolume: { id: 'volume-1', order: 1, title: '山河初醒' },
            latestFinalChapter: {
              number: overviewGetCount >= 3 ? 4 : 3,
              title: overviewGetCount >= 3 ? '典册新章' : '城隍夜巡',
              finalizedAtMs: 1_777_777_770_000,
            },
            finalizedChapterCount: overviewGetCount >= 3 ? 4 : 3,
            finalizedScalarCount: overviewGetCount >= 3 ? 24_300 : 18_600,
          },
          modules: {
            seed: 'current',
            contract: 'current',
            bible: overviewGetCount >= 3 ? 'current' : 'needs_review',
            planning: 'current',
            outline: 'pending_confirmation',
            writing: 'working_draft',
          },
          writerCore: {
            canonRevision: 3,
            projectionRevision: 3,
            synchronized: true,
          },
          continuity: { availability: 'pending_module', pendingCount: null },
          recentAchievements: [
            {
              kind: 'final_chapter',
              label: overviewGetCount >= 3 ? '第 4 章已定稿' : '第 3 章已定稿',
              occurredAtMs: 1_777_777_770_000,
            },
            { kind: 'planning', label: '故事规划已确认', occurredAtMs: 1_777_777_760_000 },
          ],
        }),
      })
    })
    await page.goto('/projects')
    await page.locator('.project-library-heading__actions')
      .getByRole('button', { name: '新建项目', exact: true })
      .click()
    const dialog = page.getByRole('dialog', { name: '新建项目' })
    const createResponsePromise = page.waitForResponse(response => (
      response.request().method() === 'POST'
      && apiPath(response) === '/api/projects'
    ))
    await dialog.getByRole('textbox', { name: '项目名称' }).fill(PROJECT_TITLE)
    await dialog.getByRole('button', { name: '创建并打开' }).click()
    const createResponse = await createResponsePromise
    expect(createResponse.ok()).toBe(true)
    projectId = String((await createResponse.json()).id)
    const overviewPath = projectOverviewPath(projectId)
    await expect.poll(() => routedProjectId).toBe(projectId)
    await expect(page).toHaveURL(new RegExp(`${overviewPath.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')}$`, 'u'))
    await expect(page.getByText('项目概览暂时无法加载', { exact: true })).toBeVisible()
    const retry = page.getByRole('button', { name: '重试', exact: true })
    await expect(retry).toBeVisible()
    await retry.click()
    await expect.poll(() => overviewGetCount).toBe(2)
    const overview = page.locator('.overview-ledger')
    await expect(overview).toBeVisible()
    await expect(overview.getByRole('heading', { name: PROJECT_TITLE, exact: true })).toBeVisible()
    await expect(overview.getByText(OVERVIEW_LOGLINE, { exact: true })).toBeVisible()
    await expect(overview.getByText('2,400,000 字', { exact: true })).toBeVisible()
    await expect(overview.getByText('18,600 字', { exact: true })).toBeVisible()
    await expect(overview.getByText('第 1 卷 · 山河初醒', { exact: true })).toBeVisible()
    await expect(overview.getByText('当前权威：第 4 章', { exact: true })).toBeVisible()
    await expect(overview.getByText('第 3 章 · 城隍夜巡', { exact: true })).toBeVisible()
    await expect(overview.getByRole('link', { name: /下一步/u })).toHaveCount(0)
    await expect(overview.getByRole('button', { name: /下一步/u })).toHaveCount(0)

    await overview.locator('.overview-module').filter({ hasText: '创作种子' }).click()
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/seeds$`, 'u'))
    await page.waitForLoadState('networkidle')

    await page.locator('.product-sidebar')
      .getByRole('link', { name: '项目概览', exact: true })
      .click()
    await waitForRouteReady(page, overview)
    await expect.poll(() => overviewGetCount).toBe(3)
    await expect(overview.getByText('24,300 字', { exact: true })).toBeVisible()
    await expect(overview.getByText('当前权威：第 5 章', { exact: true })).toBeVisible()
    await expect(overview.getByText('当前正式版', { exact: true })).toHaveCount(4)
    await expect(overview.getByText('第 4 章已定稿', { exact: true })).toBeVisible()
    const desktopNavigation = page.locator('.product-sidebar')
    await expect(desktopNavigation).toBeVisible()
    await desktopNavigation.getByRole('link', { name: '导出与备份', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/settings/export$`, 'u'))
    await expect(page.getByRole('heading', { name: '导出与备份', exact: true })).toBeVisible()
    await page.waitForLoadState('networkidle')

    await desktopNavigation.getByRole('link', { name: '项目概览', exact: true }).click()
    await waitForRouteReady(page, overview)
    await expect.poll(() => overviewGetCount).toBe(4)
    const mainContent = page.locator('.product-app-shell__content')
    await mainContent.evaluate(element => { element.scrollTop = 0 })
    const overviewBox = await overview.boundingBox()
    expect(overviewBox).not.toBeNull()
    await page.mouse.move(
      overviewBox!.x + Math.min(overviewBox!.width / 2, 300),
      overviewBox!.y + Math.min(overviewBox!.height / 2, 300),
    )
    await page.mouse.wheel(0, 700)
    await expect.poll(() => mainContent.evaluate(element => element.scrollTop)).toBeGreaterThan(0)

    await page.setViewportSize({ width: 760, height: 900 })
    await expect(page.locator('.product-app-shell')).toHaveAttribute('data-navigation-mode', 'mobile')
    const menuButton = page.getByRole('button', { name: '菜单', exact: true })
    await expect(menuButton).toBeVisible()
    await menuButton.click()
    const mobileNavigation = page.getByRole('dialog', { name: '作品导航' })
    await expect(mobileNavigation).toBeVisible()
    await mobileNavigation.getByRole('link', { name: '导出与备份', exact: true }).click()
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/settings/export$`, 'u'))
    await expect(mobileNavigation).toHaveCount(0)
    await expect(page.getByRole('heading', { name: '导出与备份', exact: true })).toBeVisible()
    await page.waitForLoadState('networkidle')
    await menuButton.click()
    const returnNavigation = page.getByRole('dialog', { name: '作品导航' })
    await returnNavigation.getByRole('link', { name: '项目概览', exact: true }).click()
    await waitForRouteReady(page, overview)
    await expect.poll(() => overviewGetCount).toBe(5)
  } catch (error) {
    bodyError = error
  } finally {
    try {
      const evidence = await runtimeObserver.finish()
      assertExactWrites(evidence, [{
        method: 'POST',
        path: '/api/projects',
        statuses: [200],
        count: 1,
      }])
      expect(
        evidence.consoleErrors,
        'only the console error caused by the deliberate overview 500 is allowed',
      ).toEqual([
        'error: Failed to load resource: the server responded with a status of 500 (Internal Server Error)',
      ])
      expect(evidence.pageErrors, 'page errors must stay empty').toEqual([])
      expect(evidence.requestFailures, 'request failures must stay empty').toEqual([])
      expect(
        evidence.responseFailures.map(normalizedResponseFailure),
        'only the deliberately injected overview 500 is allowed',
      ).toEqual([
        `500 GET /api/projects/${projectId}/overview`,
      ])
      const scan = scanRuntimeEvidence(evidence, runtimeSensitiveValues(process.env))
      if (scan.matchCount !== 0) {
        throw new Error('Project-overview browser evidence contained a runtime-sensitive value')
      }
    } catch (error) {
      auditError = error
    }
    if (bodyError && auditError) {
      throw new AggregateError(
        [bodyError, auditError],
        'Project-overview browser behavior and runtime audit both failed',
      )
    }
    if (bodyError) throw bodyError
    if (auditError) throw auditError
  }
})
