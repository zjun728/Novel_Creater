async function captureApiResponse(response, { url, method, status }) {
  let headers = {}
  let headersReadError = ''
  try {
    headers = await response.allHeaders()
  } catch (error) {
    headersReadError = error instanceof Error ? error.message : String(error)
  }

  let body = ''
  let bodyReadError = ''
  try {
    body = await response.text()
  } catch (error) {
    bodyReadError = error instanceof Error ? error.message : String(error)
  }

  return {
    url,
    method,
    status,
    headers,
    headersReadError,
    body,
    bodyReadError,
  }
}

export function observeRuntime(page) {
  const pendingApiBodies = new Set()
  const consoleMessages = []
  const consoleErrors = []
  const pageErrors = []
  const requestFailures = []
  const responseFailures = []

  const onResponse = response => {
    const method = response.request().method()
    const status = response.status()
    const url = response.url()
    if (status < 200 || status >= 300) {
      responseFailures.push(`${status} ${method} ${url}`)
    }
    if (!url.includes('/api/')) return
    pendingApiBodies.add(captureApiResponse(response, { url, method, status }))
  }
  const onConsole = message => {
    const rendered = `${message.type()}: ${message.text()}`
    consoleMessages.push(rendered)
    if (message.type() === 'error') consoleErrors.push(rendered)
  }
  const onPageError = error => {
    pageErrors.push(error.message)
  }
  const onRequestFailed = request => {
    requestFailures.push(
      `${request.method()} ${request.url()} ${request.failure()?.errorText || 'unknown failure'}`,
    )
  }

  page.on('response', onResponse)
  page.on('console', onConsole)
  page.on('pageerror', onPageError)
  page.on('requestfailed', onRequestFailed)

  async function finish() {
    const apiResponses = []
    const drainPendingApiBodies = async () => {
      while (pendingApiBodies.size) {
        const batch = [...pendingApiBodies]
        const resolved = await Promise.all(batch)
        for (const promise of batch) pendingApiBodies.delete(promise)
        apiResponses.push(...resolved)
      }
    }
    let pageContent = ''
    try {
      await page.waitForLoadState('networkidle')
      await drainPendingApiBodies()
      pageContent = await page.content()
      await drainPendingApiBodies()
    } finally {
      page.off('response', onResponse)
      page.off('console', onConsole)
      page.off('pageerror', onPageError)
      page.off('requestfailed', onRequestFailed)
    }

    return {
      apiResponses,
      consoleMessages,
      consoleErrors,
      pageErrors,
      requestFailures,
      responseFailures,
      pageContent,
    }
  }

  return { finish }
}
