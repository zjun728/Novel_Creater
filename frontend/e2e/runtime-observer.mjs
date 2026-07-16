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

async function captureRequest(request, { url, method }) {
  let headers = {}
  let headersReadError = ''
  try {
    headers = await request.allHeaders()
  } catch (error) {
    headersReadError = error instanceof Error ? error.message : String(error)
  }

  let body = ''
  let bodyReadError = ''
  try {
    body = request.postData() || ''
  } catch (error) {
    bodyReadError = error instanceof Error ? error.message : String(error)
  }

  return { url, method, headers, headersReadError, body, bodyReadError }
}

function renderedPath(url) {
  try {
    return new URL(url).pathname
  } catch {
    return url
  }
}

function isApiUrl(url) {
  try {
    const pathname = new URL(url).pathname
    return pathname === '/api' || pathname.startsWith('/api/')
  } catch {
    return false
  }
}

function matchesPath(expected, actual) {
  if (typeof expected === 'string') return expected === actual
  if (!(expected instanceof RegExp)) return false
  expected.lastIndex = 0
  return expected.test(actual)
}

export function assertExactWrites(evidence, allowlist) {
  if (!Array.isArray(allowlist)) throw new TypeError('write allowlist must be an array')
  const writes = (evidence.apiResponses || []).filter(response => (
    !['GET', 'HEAD', 'OPTIONS'].includes(String(response.method).toUpperCase())
  ))
  const matched = new Map(allowlist.map((entry, index) => [index, []]))

  for (const write of writes) {
    const method = String(write.method).toUpperCase()
    const path = renderedPath(write.url)
    const matchIndex = allowlist.findIndex(entry => (
      String(entry.method).toUpperCase() === method && matchesPath(entry.path, path)
    ))
    if (matchIndex === -1) {
      throw new Error(`Unmatched runtime write: ${method} ${path}`)
    }
    const entry = allowlist[matchIndex]
    if (!Array.isArray(entry.statuses) || !entry.statuses.includes(write.status)) {
      throw new Error(`Unexpected runtime write status for ${method} ${path}`)
    }
    matched.get(matchIndex).push(write)
  }

  for (const [index, entry] of allowlist.entries()) {
    if (!Number.isInteger(entry.count) || entry.count < 0) {
      throw new TypeError('write allowlist count must be a non-negative integer')
    }
    if (matched.get(index).length !== entry.count) {
      throw new Error(`Runtime write count did not match allowlist entry ${index}`)
    }
  }
  return { writeCount: writes.length }
}

function countMatches(value, sensitiveValues) {
  const rendered = typeof value === 'string' ? value : JSON.stringify(value)
  if (!rendered) return 0
  return sensitiveValues.reduce((count, sensitive) => (
    count + rendered.split(sensitive).length - 1
  ), 0)
}

export function runtimeSensitiveValues(environment = process.env) {
  return [
    'BROWSER_SECRET_SENTINEL',
    'BROWSER_PRIVATE_PROVIDER_URL',
    'BROWSER_CORPUS_ROOT_SENTINEL',
    'BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL',
  ].map(name => environment[name]).filter(value => (
    typeof value === 'string' && value.length > 0
  ))
}

export function scanRuntimeEvidence(
  evidence,
  sensitiveValues = runtimeSensitiveValues(),
) {
  const values = [...new Set((sensitiveValues || []).filter(value => (
    typeof value === 'string' && value.length > 0
  )))]
  const surfaces = [
    ...(evidence.requests || []),
    ...(evidence.apiResponses || []),
    evidence.pageContent || '',
    ...(evidence.consoleMessages || []),
    ...(evidence.consoleErrors || []),
    ...(evidence.pageErrors || []),
    ...(evidence.requestFailures || []),
    ...(evidence.responseFailures || []),
  ]
  return {
    matchCount: surfaces.reduce(
      (count, surface) => count + countMatches(surface, values),
      0,
    ),
  }
}

export function observeRuntime(page) {
  const pendingApiBodies = new Set()
  const pendingRequests = new Set()
  const consoleMessages = []
  const consoleErrors = []
  const pageErrors = []
  const requestFailures = []
  const responseFailures = []

  const onResponse = response => {
    const method = response.request().method()
    const status = response.status()
    const url = response.url()
    if ((status < 200 || status >= 300) && status !== 304) {
      responseFailures.push(`${status} ${method} ${url}`)
    }
    if (!isApiUrl(url)) return
    pendingApiBodies.add(captureApiResponse(response, { url, method, status }))
  }
  const onRequest = request => {
    const method = request.method()
    const url = request.url()
    pendingRequests.add(captureRequest(request, { url, method }))
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

  page.on('request', onRequest)
  page.on('response', onResponse)
  page.on('console', onConsole)
  page.on('pageerror', onPageError)
  page.on('requestfailed', onRequestFailed)

  async function finish() {
    const apiResponses = []
    const requests = []
    const drainPendingRequests = async () => {
      while (pendingRequests.size) {
        const batch = [...pendingRequests]
        const resolved = await Promise.all(batch)
        for (const promise of batch) pendingRequests.delete(promise)
        requests.push(...resolved)
      }
    }
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
      await drainPendingRequests()
      await drainPendingApiBodies()
      pageContent = await page.content()
      await drainPendingRequests()
      await drainPendingApiBodies()
    } finally {
      page.off('request', onRequest)
      page.off('response', onResponse)
      page.off('console', onConsole)
      page.off('pageerror', onPageError)
      page.off('requestfailed', onRequestFailed)
    }

    return {
      requests,
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
