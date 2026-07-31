const RESPONSE_BODY_READ_TIMEOUT_MS = 10_000
const runtimeFailureDiagnostics = new WeakMap()


async function readWithTimeout(read, timeoutMs, timeoutMessage) {
  let timer = null
  try {
    return await Promise.race([
      read(),
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(timeoutMessage)),
          timeoutMs,
        )
      }),
    ])
  } finally {
    if (timer !== null) clearTimeout(timer)
  }
}


async function readBeforeDeadline(read, deadline, timeoutMessage) {
  const remainingMs = deadline - Date.now()
  if (remainingMs <= 0) throw new Error(timeoutMessage)
  return readWithTimeout(read, remainingMs, timeoutMessage)
}


export async function captureApiResponse(
  response,
  { url, method, status },
  readTimeoutMs = RESPONSE_BODY_READ_TIMEOUT_MS,
) {
  const readDeadline = Date.now() + readTimeoutMs
  let headers = {}
  let headersReadError = ''
  try {
    headers = await readBeforeDeadline(
      () => response.allHeaders(),
      readDeadline,
      'response headers read timed out',
    )
  } catch (error) {
    headersReadError = error instanceof Error ? error.message : String(error)
  }

  let body = ''
  let bodyReadError = ''
  try {
    body = await readBeforeDeadline(
      () => response.text(),
      readDeadline,
      'response body read timed out',
    )
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

export async function captureRequest(
  request,
  { url, method },
  readTimeoutMs = RESPONSE_BODY_READ_TIMEOUT_MS,
) {
  const readDeadline = Date.now() + readTimeoutMs
  let headers = {}
  let headersReadError = ''
  try {
    headers = await readBeforeDeadline(
      () => request.allHeaders(),
      readDeadline,
      'request headers read timed out',
    )
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

function allowedHttpOrigins(values) {
  if (values == null) return null
  if (!Array.isArray(values) || values.length === 0) {
    throw new TypeError('Runtime HTTP origin allowlist is invalid')
  }
  const origins = new Set()
  for (const value of values) {
    if (typeof value !== 'string') {
      throw new TypeError('Runtime HTTP origin allowlist is invalid')
    }
    let parsed
    try {
      parsed = new URL(value)
    } catch {
      throw new TypeError('Runtime HTTP origin allowlist is invalid')
    }
    if (
      !['http:', 'https:'].includes(parsed.protocol)
      || parsed.hostname !== '127.0.0.1'
      || !parsed.port
      || parsed.pathname !== '/'
      || parsed.search
      || parsed.hash
      || parsed.username
      || parsed.password
      || parsed.origin !== value
      || origins.has(value)
    ) {
      throw new TypeError('Runtime HTTP origin allowlist is invalid')
    }
    origins.add(value)
  }
  return origins
}

function httpOrigin(value) {
  try {
    const parsed = new URL(String(value))
    return ['http:', 'https:'].includes(parsed.protocol)
      ? parsed.origin
      : null
  } catch {
    return null
  }
}

function isLoopbackHttpUrl(value) {
  try {
    const parsed = new URL(String(value))
    return ['http:', 'https:'].includes(parsed.protocol)
      && parsed.hostname === '127.0.0.1'
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

function exactResponseFailureRules(allowlist) {
  if (!Array.isArray(allowlist)) {
    throw new TypeError('Runtime response failure allowlist is invalid')
  }
  const seen = new Set()
  return allowlist.map(rule => {
    if (
      !Number.isInteger(rule?.status)
      || rule.status < 100
      || rule.status > 599
      || typeof rule.method !== 'string'
      || !/^[A-Z]+$/u.test(rule.method)
      || typeof rule.pathname !== 'string'
      || !rule.pathname.startsWith('/')
      || !Number.isInteger(rule.count)
      || rule.count < 1
    ) throw new TypeError('Runtime response failure allowlist is invalid')
    const key = `${String(rule.status)}\u0000${rule.method}\u0000${rule.pathname}`
    if (seen.has(key)) {
      throw new TypeError('Runtime response failure allowlist is invalid')
    }
    seen.add(key)
    return { ...rule }
  })
}

function parsedResponseFailure(value) {
  const match = String(value || '').match(/^(\d{3}) ([A-Z]+) (\S+)$/u)
  if (!match) return null
  try {
    return {
      status: Number(match[1]),
      method: match[2],
      pathname: new URL(match[3]).pathname,
    }
  } catch {
    return null
  }
}

function consumeResponseFailures(failures, allowlist) {
  const rules = exactResponseFailureRules(allowlist)
  const matches = new Array(rules.length).fill(0)
  for (const failure of failures) {
    const parsed = parsedResponseFailure(failure)
    if (!parsed) return null
    const indexes = rules.flatMap((rule, index) => (
      rule.status === parsed.status
      && rule.method === parsed.method
      && rule.pathname === parsed.pathname
        ? [index]
        : []
    ))
    if (indexes.length !== 1) return null
    matches[indexes[0]] += 1
  }
  if (!rules.every((rule, index) => matches[index] === rule.count)) return null
  return { rules, matches }
}

function consoleErrorsAreAllowed(errors, allowlist, consumedResponses) {
  if (!Array.isArray(allowlist)) {
    throw new TypeError('Runtime console error allowlist is invalid')
  }
  const seenMessages = new Set()
  const rules = allowlist.map(rule => {
    const link = rule?.linkedResponseFailure
    if (
      typeof rule?.message !== 'string'
      || rule.message.length === 0
      || !Number.isInteger(rule.count)
      || rule.count < 1
      || !Number.isInteger(link?.status)
      || typeof link.method !== 'string'
      || typeof link.pathname !== 'string'
      || seenMessages.has(rule.message)
    ) throw new TypeError('Runtime console error allowlist is invalid')
    const linkedIndexes = consumedResponses.rules.flatMap((responseRule, index) => (
      responseRule.status === link.status
      && responseRule.method === link.method
      && responseRule.pathname === link.pathname
        ? [index]
        : []
    ))
    if (linkedIndexes.length !== 1) {
      throw new TypeError('Runtime console error allowlist is invalid')
    }
    const linkedIndex = linkedIndexes[0]
    if (consumedResponses.matches[linkedIndex] !== consumedResponses.rules[linkedIndex].count) {
      return null
    }
    seenMessages.add(rule.message)
    return { message: rule.message, count: rule.count }
  })
  if (rules.includes(null)) return false
  const counts = new Array(rules.length).fill(0)
  for (const error of errors) {
    const indexes = rules.flatMap((rule, index) => (
      rule.message === error ? [index] : []
    ))
    if (indexes.length !== 1) return false
    counts[indexes[0]] += 1
  }
  return rules.every((rule, index) => counts[index] === rule.count)
}

export function assertRuntimeEvidenceHealthy(evidence, {
  responseFailureAllowlist = [],
  consoleErrorAllowlist = [],
} = {}) {
  const responseFailures = Array.isArray(evidence?.responseFailures)
    ? evidence.responseFailures
    : []
  const consumedResponses = consumeResponseFailures(
    responseFailures,
    responseFailureAllowlist,
  )
  if (!consumedResponses) {
    throw new Error('Runtime evidence contains response failures')
  }
  const consoleErrors = Array.isArray(evidence?.consoleErrors)
    ? evidence.consoleErrors
    : []
  if (!consoleErrorsAreAllowed(
    consoleErrors,
    consoleErrorAllowlist,
    consumedResponses,
  )) throw new Error('Runtime evidence contains console errors')
  if (Array.isArray(evidence?.pageErrors) && evidence.pageErrors.length > 0) {
    throw new Error('Runtime evidence contains page errors')
  }
  if (Array.isArray(evidence?.requestFailures) && evidence.requestFailures.length > 0) {
    throw new Error('Runtime evidence contains request failures')
  }
  if ((evidence?.apiResponses || []).some(item => item?.headersReadError)) {
    throw new Error('Runtime API response headers could not be read')
  }
  if ((evidence?.apiResponses || []).some(item => item?.bodyReadError)) {
    throw new Error('Runtime API response bodies could not be read')
  }
  if ((evidence?.requests || []).some(item => item?.headersReadError)) {
    throw new Error('Runtime request headers could not be read')
  }
  if ((evidence?.requests || []).some(item => item?.bodyReadError)) {
    throw new Error('Runtime request bodies could not be read')
  }
  const networkAccess = evidence?.networkAccess
  if (networkAccess !== undefined) {
    const counts = [
      networkAccess?.httpRequestCount,
      networkAccess?.allowedRequestCount,
      networkAccess?.forbiddenRequestCount,
      networkAccess?.forbiddenResponseCount,
    ]
    if (
      counts.some(value => !Number.isInteger(value) || value < 0)
      || networkAccess.httpRequestCount
        !== networkAccess.allowedRequestCount + networkAccess.forbiddenRequestCount
    ) {
      throw new Error('Runtime HTTP access evidence is invalid')
    }
    if (
      networkAccess.forbiddenRequestCount !== 0
      || networkAccess.forbiddenResponseCount !== 0
    ) {
      throw new Error('Runtime evidence contains forbidden HTTP access')
    }
    return { healthy: true, networkAccess: { ...networkAccess } }
  }
  return { healthy: true }
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
  const writes = (evidence.responses || []).filter(response => (
    isApiUrl(response?.url)
    && ['POST', 'PUT', 'PATCH', 'DELETE'].includes(String(response?.method).toUpperCase())
  ))
  const matched = new Map(allowlist.map((entry, index) => [index, []]))

  for (const write of writes) {
    const method = String(write.method).toUpperCase()
    const path = renderedTarget(write.url)
    const diagnosticPath = publicDiagnosticPath(write.url)
    const matchIndexes = allowlist.flatMap((entry, index) => (
      entry.method === method && matchesPath(entry.path, path) ? [index] : []
    ))
    if (matchIndexes.length === 0) {
      throw new Error(`Unmatched runtime write: ${method} ${diagnosticPath}`)
    }
    if (matchIndexes.length !== 1) {
      throw new Error(
        `Runtime write matched multiple overlapping rules: ${method} ${diagnosticPath}`,
      )
    }
    const [matchIndex] = matchIndexes
    const entry = allowlist[matchIndex]
    if (!entry.statuses.includes(write.status)) {
      throw new Error(
        `Unexpected runtime write status for ${method} ${diagnosticPath}`,
      )
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

export function assertNoPrivateEvidenceMarkers(surfaces) {
  const rendered = (Array.isArray(surfaces) ? surfaces : [])
    .map(value => String(value).toLowerCase())
    .join('\n')
  const containsPrivateEvidence = (
    /(?:^|[\s{,])["']?(?:prompt|manifest|input[_ -]?manifest|rawprovider|raw[_ -]?(?:provider[_ -]?)?output|provider[_ -]?output|corpus[_ -]?text|api[_ -]?key|authorization|password|dsn)["']?\s*[:=]/u
      .test(rendered)
    || /\b(?:raw provider|input manifest|corpus text)\b/u.test(rendered)
  )
  if (containsPrivateEvidence) {
    throw new Error('Runtime evidence contains private fields')
  }
  return { matchCount: 0 }
}


function publicDiagnosticPath(value) {
  try {
    return new URL(String(value)).pathname
  } catch {
    return '[invalid-path]'
  }
}


const PUBLIC_REQUEST_FAILURE_METHODS = new Set([
  'GET',
  'POST',
  'PUT',
  'PATCH',
  'DELETE',
  'HEAD',
  'OPTIONS',
])


function publicRequestFailure(value) {
  const invalid = {
    method: '[invalid-method]',
    path: '[invalid-path]',
  }
  if (typeof value !== 'string') return invalid
  const match = /^(\S+)\s+(\S+)(?:\s|$)/u.exec(value)
  if (!match) return invalid
  const [, method, rawUrl] = match
  if (!PUBLIC_REQUEST_FAILURE_METHODS.has(method)) return invalid
  if (!isLoopbackHttpUrl(rawUrl)) return null
  try {
    const url = new URL(rawUrl)
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return invalid
    return {
      method,
      path: url.pathname,
    }
  } catch {
    return invalid
  }
}


function publicPendingRequest(value) {
  const invalid = {
    method: '[invalid-method]',
    path: '[invalid-path]',
    status: 'pending',
  }
  if (!value || typeof value !== 'object') return invalid
  if (!PUBLIC_REQUEST_FAILURE_METHODS.has(value.method)) return invalid
  try {
    const url = new URL(value.url)
    if (!isLoopbackHttpUrl(url)) return null
    return { method: value.method, path: url.pathname, status: 'pending' }
  } catch {
    return invalid
  }
}


export function publicRuntimeDiagnostic(evidence) {
  const apiResponses = Array.isArray(evidence?.apiResponses)
    ? evidence.apiResponses
    : []
  const requests = Array.isArray(evidence?.requests) ? evidence.requests : []
  const responses = Array.isArray(evidence?.responses) ? evidence.responses : []
  const requestFailures = Array.isArray(evidence?.requestFailures)
    ? evidence.requestFailures
    : []
  const pendingRequests = Array.isArray(evidence?.pendingRequests)
    ? evidence.pendingRequests
    : []
  const publicPendingRequests = pendingRequests
    .map(publicPendingRequest)
    .filter(Boolean)
  const responseFailures = responses
    .filter(item => (
      isLoopbackHttpUrl(item?.url)
      &&
      (Number(item?.status) < 200 || Number(item?.status) >= 300)
      && Number(item?.status) !== 304
    ))
    .map(item => ({
      method: item.method,
      status: item.status,
      path: publicDiagnosticPath(item.url),
    }))
  const networkAccess = evidence?.networkAccess
  return {
    consoleErrorCount: Array.isArray(evidence?.consoleErrors)
      ? evidence.consoleErrors.length
      : 0,
    requestFailureCount: requestFailures.length,
    requestFailures: requestFailures.map(publicRequestFailure).filter(Boolean),
    responseFailures,
    apiResponseCount: apiResponses.length,
    apiHeaderReadFailures: apiResponses
      .filter(item => (
        isLoopbackHttpUrl(item?.url) && Boolean(item?.headersReadError)
      ))
      .map(item => ({
        method: item.method,
        status: item.status,
        path: publicDiagnosticPath(item.url),
      })),
    apiBodyReadFailures: apiResponses
      .filter(item => (
        isLoopbackHttpUrl(item?.url) && Boolean(item?.bodyReadError)
      ))
      .map(item => ({
        method: item.method,
        status: item.status,
        path: publicDiagnosticPath(item.url),
      })),
    requestHeaderReadFailures: requests
      .filter(item => (
        isLoopbackHttpUrl(item?.url) && Boolean(item?.headersReadError)
      ))
      .map(item => ({
        method: item.method,
        path: publicDiagnosticPath(item.url),
      })),
    pendingRequestCount: publicPendingRequests.length,
    pendingRequests: publicPendingRequests,
    ...(networkAccess === undefined
      ? {}
      : {
        networkAccess: {
          httpRequestCount: Number(networkAccess?.httpRequestCount) || 0,
          allowedRequestCount: Number(networkAccess?.allowedRequestCount) || 0,
          forbiddenRequestCount: Number(networkAccess?.forbiddenRequestCount) || 0,
          forbiddenResponseCount: Number(networkAccess?.forbiddenResponseCount) || 0,
        },
      }),
  }
}


function freezeRuntimeFailureDiagnostic(value) {
  if (Array.isArray(value)) {
    for (const item of value) freezeRuntimeFailureDiagnostic(item)
  } else if (value && typeof value === 'object') {
    for (const item of Object.values(value)) freezeRuntimeFailureDiagnostic(item)
  }
  return Object.freeze(value)
}


function copyRuntimeFailureDiagnostic(value) {
  return JSON.parse(JSON.stringify(value))
}


export function runtimeFailureDiagnostic(error) {
  if (!error || (typeof error !== 'object' && typeof error !== 'function')) {
    return null
  }
  const diagnostic = runtimeFailureDiagnostics.get(error)
  return diagnostic === undefined ? null : copyRuntimeFailureDiagnostic(diagnostic)
}


export async function settleNavigationBoundary(page, runtime) {
  await page.waitForLoadState('networkidle')
  await runtime.settle()
}


export function observeRuntime(page, {
  allowedOrigins = null,
  quietWindowMs = 50,
  readTimeoutMs = RESPONSE_BODY_READ_TIMEOUT_MS,
  settleTimeoutMs = 15_000,
} = {}) {
  const context = page.context()
  const originAllowlist = allowedHttpOrigins(allowedOrigins)
  const evidenceReadTimeoutMs = Math.min(readTimeoutMs, settleTimeoutMs)
  const pendingApiBodies = new Set()
  const pendingRequests = new Set()
  const activeApiRequests = new Set()
  const activeHttpRequests = new Map()
  const requestStages = new WeakMap()
  const responseStages = new WeakMap()
  const requestMetadata = new WeakMap()
  const responseMetadata = new WeakMap()
  const responses = []
  const consoleMessages = []
  const consoleErrors = []
  const pageErrors = []
  const requestFailures = []
  const responseFailures = []
  const apiResponses = []
  const requests = []
  const networkAccess = originAllowlist === null
    ? null
    : {
      httpRequestCount: 0,
      allowedRequestCount: 0,
      forbiddenRequestCount: 0,
      forbiddenResponseCount: 0,
    }
  let activityVersion = 0

  const onResponse = response => {
    responseStages.set(response, 'entry')
    const method = response.request().method()
    const status = response.status()
    const url = response.url()
    responseMetadata.set(response, { method, url, status })
    responseStages.set(response, 'metadata')
    const origin = httpOrigin(url)
    if (
      networkAccess !== null
      && origin !== null
      && !originAllowlist.has(origin)
    ) {
      networkAccess.forbiddenResponseCount += 1
    }
    responses.push({ url, method, status })
    responseStages.set(response, 'recorded')
    if ((status < 200 || status >= 300) && status !== 304) {
      responseFailures.push(`${status} ${method} ${url}`)
    }
    if (!isApiUrl(url)) return
    activityVersion += 1
    pendingApiBodies.add(captureApiResponse(
      response,
      { url, method, status },
      evidenceReadTimeoutMs,
    ))
    responseStages.set(response, 'scheduled')
  }
  const onRequest = request => {
    requestStages.set(request, 'entry')
    const method = request.method()
    const url = request.url()
    requestMetadata.set(request, { method, url })
    requestStages.set(request, 'metadata')
    const origin = httpOrigin(url)
    if (networkAccess !== null && origin !== null) {
      networkAccess.httpRequestCount += 1
      if (originAllowlist.has(origin)) networkAccess.allowedRequestCount += 1
      else networkAccess.forbiddenRequestCount += 1
    }
    activityVersion += 1
    if (isLoopbackHttpUrl(url)) {
      activeHttpRequests.set(request, { method, url })
    }
    if (isApiUrl(url)) activeApiRequests.add(request)
    pendingRequests.add(captureRequest(
      request,
      { url, method },
      evidenceReadTimeoutMs,
    ))
    requestStages.set(request, 'scheduled')
  }
  const onRequestFinished = request => {
    activityVersion += 1
    activeApiRequests.delete(request)
    activeHttpRequests.delete(request)
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
    activityVersion += 1
    activeApiRequests.delete(request)
    activeHttpRequests.delete(request)
    requestFailures.push(
      `${request.method()} ${request.url()} ${request.failure()?.errorText || 'unknown failure'}`,
    )
  }
  const listenersAttached = () => (
    context.listeners('request').includes(onRequest)
    && context.listeners('requestfinished').includes(onRequestFinished)
    && context.listeners('response').includes(onResponse)
    && context.listeners('requestfailed').includes(onRequestFailed)
  )
  const matchesObservation = (snapshot, method, pathname) => {
    if (!snapshot || typeof snapshot.method !== 'string' || typeof snapshot.url !== 'string') return false
    if (typeof method !== 'string' || typeof pathname !== 'string') return false
    try {
      return snapshot.method === method && new URL(snapshot.url).pathname === pathname
    } catch {
      return false
    }
  }
  context.on('request', onRequest)
  context.on('requestfinished', onRequestFinished)
  context.on('response', onResponse)
  page.on('console', onConsole)
  page.on('pageerror', onPageError)
  context.on('requestfailed', onRequestFailed)

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
    const deadline = Date.now() + settleTimeoutMs
    while (true) {
      const settleTimeoutMessage = 'runtime evidence did not settle before its deadline'
      await readBeforeDeadline(
        () => drainPendingRequests(),
        deadline,
        settleTimeoutMessage,
      )
      await readBeforeDeadline(
        () => drainPendingApiBodies(),
        deadline,
        settleTimeoutMessage,
      )
      const observedVersion = activityVersion
      if (deadline - Date.now() <= quietWindowMs) {
        throw new Error(settleTimeoutMessage)
      }
      await new Promise(resolve => setTimeout(resolve, quietWindowMs))
      await readBeforeDeadline(
        () => drainPendingRequests(),
        deadline,
        settleTimeoutMessage,
      )
      await readBeforeDeadline(
        () => drainPendingApiBodies(),
        deadline,
        settleTimeoutMessage,
      )
      if (Date.now() >= deadline) throw new Error(settleTimeoutMessage)
      if (
        activeApiRequests.size === 0
        && pendingRequests.size === 0
        && pendingApiBodies.size === 0
        && activityVersion === observedVersion
      ) return
    }
  }

  async function finish() {
    let pageContent = ''
    try {
      await page.waitForLoadState('networkidle')
      await settle()
      pageContent = await page.content()
      await settle()
    } catch {
      const diagnostic = publicRuntimeDiagnostic({
        requests,
        responses,
        apiResponses,
        consoleMessages,
        consoleErrors,
        pageErrors,
        requestFailures,
        responseFailures,
        pendingRequests: [...activeHttpRequests.values()],
        ...(networkAccess === null ? {} : { networkAccess: { ...networkAccess } }),
      })
      const failure = new Error(
        `Runtime evidence settlement failed: ${JSON.stringify(diagnostic)}`,
      )
      runtimeFailureDiagnostics.set(
        failure,
        freezeRuntimeFailureDiagnostic(copyRuntimeFailureDiagnostic(diagnostic)),
      )
      throw failure
    } finally {
      context.off('request', onRequest)
      context.off('requestfinished', onRequestFinished)
      context.off('response', onResponse)
      page.off('console', onConsole)
      page.off('pageerror', onPageError)
      context.off('requestfailed', onRequestFailed)
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
      ...(networkAccess === null ? {} : { networkAccess: { ...networkAccess } }),
    }
  }

  return {
    finish,
    settle,
    listenersAttached,
    observationStage: object => requestStages.get(object) || responseStages.get(object) || 'unseen',
    requestObservationMatches: (request, method, pathname) => matchesObservation(requestMetadata.get(request), method, pathname),
    responseObservationMatches: (response, method, pathname, status) => (
      Number.isInteger(status)
      && responseMetadata.get(response)?.status === status
      && matchesObservation(responseMetadata.get(response), method, pathname)
    ),
  }
}
