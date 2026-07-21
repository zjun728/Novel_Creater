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

function renderedTarget(url) {
  try {
    const parsed = new URL(url)
    return `${parsed.pathname}${parsed.search}${parsed.hash}`
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
  const ruleKeys = new Set()
  for (const entry of allowlist) {
    if (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(entry?.method)) {
      throw new TypeError('write allowlist method must be POST, PUT, PATCH, or DELETE')
    }
    if (
      !((typeof entry.path === 'string' && entry.path.length > 0)
      || entry.path instanceof RegExp)
    ) {
      throw new TypeError('write allowlist path must be a non-empty string or RegExp')
    }
    if (!Number.isInteger(entry.count) || entry.count < 1) {
      throw new TypeError('write allowlist count must be a positive integer')
    }
    if (
      !Array.isArray(entry.statuses)
      || entry.statuses.length === 0
      || entry.statuses.some(status => (
        !Number.isInteger(status) || status < 100 || status > 599
      ))
    ) {
      throw new TypeError('write allowlist statuses must contain valid HTTP status integers')
    }
    const method = entry.method
    const pathKey = typeof entry.path === 'string'
      ? `string:${entry.path}`
      : `regexp:${entry.path.source}/${entry.path.flags}`
    const ruleKey = `${method}:${pathKey}`
    if (ruleKeys.has(ruleKey)) {
      throw new Error(`Duplicate or overlapping runtime write rule: ${method}`)
    }
    ruleKeys.add(ruleKey)
  }
  const writes = (evidence.apiResponses || []).filter(response => (
    !['GET', 'HEAD', 'OPTIONS'].includes(String(response.method).toUpperCase())
  ))
  const matched = new Map(allowlist.map((entry, index) => [index, []]))

  for (const write of writes) {
    const method = String(write.method).toUpperCase()
    const path = renderedTarget(write.url)
    const matchIndexes = allowlist.flatMap((entry, index) => (
      entry.method === method && matchesPath(entry.path, path) ? [index] : []
    ))
    if (matchIndexes.length === 0) {
      throw new Error(`Unmatched runtime write: ${method} ${path}`)
    }
    if (matchIndexes.length !== 1) {
      throw new Error(`Runtime write matched multiple overlapping rules: ${method} ${path}`)
    }
    const [matchIndex] = matchIndexes
    const entry = allowlist[matchIndex]
    if (!entry.statuses.includes(write.status)) {
      throw new Error(`Unexpected runtime write status for ${method} ${path}`)
    }
    matched.get(matchIndex).push(write)
  }

  for (const [index, entry] of allowlist.entries()) {
    if (matched.get(index).length !== entry.count) {
      throw new Error(`Runtime write count did not match allowlist entry ${index}`)
    }
  }
  return { writeCount: writes.length }
}

function expandSensitiveValues(values) {
  const expanded = new Set()
  for (const value of values || []) {
    if (typeof value !== 'string' || value.length === 0) continue
    const slashVariants = new Set([
      value,
      value.replaceAll('\\', '/'),
      value.replaceAll('/', '\\'),
    ])
    for (const variant of slashVariants) {
      if (!variant) continue
      expanded.add(variant)
      expanded.add(JSON.stringify(variant).slice(1, -1))
      expanded.add(encodeURIComponent(variant))
    }
  }
  return [...expanded].filter(value => value.length > 0)
}

function countMatches(value, sensitiveValues, seen = new WeakSet()) {
  if (typeof value === 'string') {
    return sensitiveValues.reduce((count, sensitive) => (
      count + value.split(sensitive).length - 1
    ), 0)
  }
  if (!value || typeof value !== 'object') return 0
  if (seen.has(value)) return 0
  seen.add(value)
  return Object.values(value).reduce(
    (count, nested) => count + countMatches(nested, sensitiveValues, seen),
    0,
  )
}

export function runtimeSensitiveValues(environment = process.env) {
  const values = [
    'BROWSER_SECRET_SENTINEL',
    'BROWSER_PRIVATE_PROVIDER_URL',
    'BROWSER_CORPUS_ROOT_SENTINEL',
    'BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL',
  ].map(name => environment[name]).filter(value => (
    typeof value === 'string' && value.length > 0
  ))
  const host = environment.MYSQL_HOST
  const port = environment.MYSQL_PORT
  const user = environment.MYSQL_USER
  const password = environment.MYSQL_PASSWORD
  const database = environment.MYSQL_DB || environment.BROWSER_TEST_DATABASE
  if ([host, port, user, password, database].every(value => (
    typeof value === 'string' && value.length > 0
  ))) {
    const rawAuthority = `${user}:${password}@${host}:${port}/${database}`
    const encodedPassword = encodeURIComponent(password)
    const encodedAuthority = `${encodeURIComponent(user)}:${encodedPassword}`
      + `@${host}:${port}/${encodeURIComponent(database)}`
    values.push(
      password,
      encodedPassword,
      database,
      `mysql://${rawAuthority}`,
      `mysql://${encodedAuthority}`,
      `mysql+aiomysql://${rawAuthority}`,
      `mysql+aiomysql://${encodedAuthority}`,
    )
  }
  return expandSensitiveValues(values)
}

export function scanRuntimeEvidence(
  evidence,
  sensitiveValues = runtimeSensitiveValues(),
) {
  const values = expandSensitiveValues(sensitiveValues)
  const surfaces = [
    ...(evidence.requests || []),
    ...(evidence.responses || []),
    ...(evidence.apiResponses || []),
    ...(evidence.checkpointSurfaces || []),
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
  const responses = []
  const consoleMessages = []
  const consoleErrors = []
  const pageErrors = []
  const requestFailures = []
  const responseFailures = []
  const apiResponses = []
  const requests = []

  const onResponse = response => {
    const method = response.request().method()
    const status = response.status()
    const url = response.url()
    responses.push({ url, method, status })
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
  async function settle() {
    await drainPendingRequests()
    await drainPendingApiBodies()
  }

  async function finish() {
    let pageContent = ''
    try {
      await page.waitForLoadState('networkidle')
      await settle()
      pageContent = await page.content()
      await settle()
    } finally {
      page.off('request', onRequest)
      page.off('response', onResponse)
      page.off('console', onConsole)
      page.off('pageerror', onPageError)
      page.off('requestfailed', onRequestFailed)
    }

    return {
      requests,
      responses,
      apiResponses,
      consoleMessages,
      consoleErrors,
      pageErrors,
      requestFailures,
      responseFailures,
      pageContent,
    }
  }

  return { finish, settle }
}
