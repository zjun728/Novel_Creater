import { expect, test, type Page } from '@playwright/test'

function requiredTestEnvironment(name: string): string {
  const value = process.env[name]
  if (!value) throw new Error(`Missing required browser test environment: ${name}`)
  return value
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const secretSentinel = requiredTestEnvironment('BROWSER_SECRET_SENTINEL')
const privateProviderURL = requiredTestEnvironment('BROWSER_PRIVATE_PROVIDER_URL')
const browserDatabase = requiredTestEnvironment('BROWSER_TEST_DATABASE')
const SECRET_OR_TEST_STATE = new RegExp(
  [secretSentinel, privateProviderURL, browserDatabase]
    .map(escapeRegExp)
    .concat(String.raw`api[_-]?key`)
    .join('|'),
  'i',
)
const READ_METHODS = new Set(['GET', 'HEAD'])

type ApiResponseEvidence = {
  url: string
  method: string
  status: number
  body: string
  bodyReadError: string
}

function observeRuntime(page: Page) {
  const apiBodyPromises: Array<Promise<ApiResponseEvidence>> = []
  const consoleMessages: string[] = []
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  const requestFailures: string[] = []
  const responseFailures: string[] = []

  page.on('response', response => {
    const method = response.request().method()
    const status = response.status()
    const url = response.url()
    if (status < 200 || status >= 300) {
      responseFailures.push(`${status} ${method} ${url}`)
    }
    if (!url.includes('/api/')) return
    apiBodyPromises.push((async () => {
      try {
        return {
          url,
          method,
          status,
          body: await response.text(),
          bodyReadError: '',
        }
      } catch (error) {
        return {
          url,
          method,
          status,
          body: '',
          bodyReadError: error instanceof Error ? error.message : String(error),
        }
      }
    })())
  })
  page.on('console', message => {
    const rendered = `${message.type()}: ${message.text()}`
    consoleMessages.push(rendered)
    if (message.type() === 'error') consoleErrors.push(rendered)
  })
  page.on('pageerror', error => {
    pageErrors.push(error.message)
  })
  page.on('requestfailed', request => {
    requestFailures.push(
      `${request.method()} ${request.url()} ${request.failure()?.errorText || 'unknown failure'}`,
    )
  })

  return async function assertCleanRuntime() {
    await page.waitForLoadState('networkidle')
    const apiResponses = await Promise.all(apiBodyPromises)
    const apiFailures = apiResponses
      .filter(response => response.status < 200 || response.status >= 300)
      .map(response => `${response.status} ${response.method} ${response.url}`)
    const apiWriteMethods = apiResponses
      .filter(response => !READ_METHODS.has(response.method))
      .map(response => `${response.method} ${response.url}`)
    const apiBodyReadFailures = apiResponses
      .filter(response => response.bodyReadError)
      .map(response => `${response.method} ${response.url}: ${response.bodyReadError}`)

    expect(consoleErrors, 'console.error must stay empty').toEqual([])
    expect(pageErrors, 'uncaught page errors must stay empty').toEqual([])
    expect(requestFailures, 'network requests must not fail').toEqual([])
    expect(responseFailures, 'every page response must be 2xx').toEqual([])
    expect(apiFailures, 'every product API response must be 2xx').toEqual([])
    expect(apiWriteMethods, 'browser goals must use only GET/HEAD product API reads').toEqual([])
    expect(apiBodyReadFailures, 'every product API body must be readable').toEqual([])

    const diagnosticEvidence = JSON.stringify({
      apiResponses,
      consoleMessages,
      consoleErrors,
      pageErrors,
      requestFailures,
      responseFailures,
      apiFailures,
      apiWriteMethods,
      apiBodyReadFailures,
    })
    expect(diagnosticEvidence).not.toMatch(SECRET_OR_TEST_STATE)
  }
}

test('author opens the preserved project and sees a clean synced foundation', async ({ page }) => {
  const assertCleanRuntime = observeRuntime(page)

  await page.goto('/')
  await page.getByRole('heading', { name: '永乐大典', exact: true }).click()

  await expect(page.getByText('永乐长明', { exact: true })).toBeVisible()
  await expect(page.getByText('文渊山海', { exact: true })).toBeVisible()
  const selectedSeed = page.locator('article.seed-card').filter({ hasText: '典镇山河' })
  await expect(selectedSeed.getByText('典镇山河', { exact: true })).toBeVisible()
  await expect(selectedSeed.getByText('已选定', { exact: true })).toBeVisible()
  await expect(page.getByText('writer-core-v1.0.0', { exact: true })).toBeVisible()
  await expect(page.getByText('Canon 0', { exact: true })).toBeVisible()
  await expect(page.getByText('Projection 0', { exact: true })).toBeVisible()
  await expect(page.getByText('状态同步', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '进入写作台' })).toBeDisabled()

  await page.getByRole('menuitem', { name: '设置' }).click()
  await expect(page.getByRole('heading', { name: '设置' })).toBeVisible()
  await expect(page.getByText('浏览器验收 Provider', { exact: true })).toBeVisible()
  await page.getByRole('menuitem', { name: '项目库' }).click()
  await page.getByRole('heading', { name: '永乐大典', exact: true }).click()
  await expect(page.getByRole('heading', { name: '永乐大典', exact: true })).toBeVisible()

  await assertCleanRuntime()
})

test('old writer URL cannot mount the retired writer chain', async ({ page }) => {
  const assertCleanRuntime = observeRuntime(page)

  await page.goto('/writer/project-1/1')
  await expect(page.getByRole('heading', { name: '写作内核尚未开放' })).toBeVisible()
  await expect(page.getByText('旧章节、临时草稿和版本定稿链已停用。')).toBeVisible()
  await page.getByRole('link', { name: '返回项目' }).click()
  await expect(page).toHaveURL(/\/project\/project-1$/)
  await expect(page.getByRole('heading', { name: '永乐大典', exact: true })).toBeVisible()

  await assertCleanRuntime()
})
