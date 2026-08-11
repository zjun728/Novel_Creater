function originOf(value) {
  try { return new URL(value).origin } catch { return '' }
}

function statusCategory(status) {
  if (status >= 200 && status < 300) return 'success'
  if (status >= 300 && status < 400) return 'redirect'
  if (status >= 400 && status < 500) return 'client-error'
  if (status >= 500 && status < 600) return 'server-error'
  return 'other'
}

function exactExpectedURL(value, allowed, expectedPath) {
  if (!expectedPath) return false
  try {
    const parsed = new URL(value)
    return allowed.has(parsed.origin)
      && parsed.pathname === expectedPath
      && parsed.search === ''
      && parsed.hash === ''
  } catch { return false }
}

function chromiumNetworkError(message) {
  return /^(?:Failed to load resource: net::ERR_[A-Z_]+|(?:GET|POST|PUT|PATCH|DELETE) .+ net::ERR_[A-Z_]+(?: \d+ \([^)]*\))?)$/u.test(message)
}

function chromiumCorsNetworkError(message) {
  const match = message.match(
    /^Access to fetch at '([^']+)' from origin '([^']+)' has been blocked by CORS policy: .+$/u,
  )
  return match ? { target: match[1], source: match[2] } : null
}

export function observeRuntime(page, { allowedOrigins = [], expectedFailedRequest = '' } = {}) {
  const responses = []
  const pending = new Set()
  const unmatchedConsole = []
  const corsConsoleCandidates = []
  const expectedFailureSequences = []
  let sequence = 0
  let consoleErrors = 0
  let expectedNetworkConsole = 0
  let requestFailures = 0
  let expectedRequestFailures = 0
  let non2xx = 0
  let originViolations = 0
  let pageErrors = 0
  const allowed = new Set(allowedOrigins)
  const onRequest = wire => pending.add(wire)
  const onResponse = wire => {
    responses.push({ method: wire.request().method(), status: wire.status(), url: wire.url() })
    if (!allowed.has(originOf(wire.url()))) originViolations += 1
    if (wire.status() < 200 || wire.status() >= 400) non2xx += 1
  }
  const onConsole = message => {
    sequence += 1
    if (message.type() !== 'error') return
    const location = typeof message.location === 'function' ? message.location() : null
    const networkError = chromiumNetworkError(message.text())
    const corsNetwork = chromiumCorsNetworkError(message.text())
    if (
      networkError
      && exactExpectedURL(location?.url, allowed, expectedFailedRequest)
    ) expectedNetworkConsole += 1
    else if (
      corsNetwork
      && allowed.has(originOf(corsNetwork.source))
      && exactExpectedURL(corsNetwork.target, allowed, expectedFailedRequest)
    ) corsConsoleCandidates.push({ sequence })
    else {
      consoleErrors += 1
      let category = 'other'
      if (networkError && !location?.url) category = 'locationlessNetwork'
      else if (networkError || corsNetwork) category = 'otherResourceNetwork'
      else if (allowed.has(originOf(location?.url))) category = 'frameworkOrPageError'
      unmatchedConsole.push({ category, sequence })
    }
  }
  const onPageError = () => { sequence += 1; pageErrors += 1 }
  const onFinished = wire => pending.delete(wire)
  const onFailed = wire => {
    sequence += 1
    pending.delete(wire)
    if (
      wire.method() === 'POST'
      && exactExpectedURL(wire.url(), allowed, expectedFailedRequest)
    ) {
      expectedRequestFailures += 1
      expectedFailureSequences.push(sequence)
    }
    else requestFailures += 1
  }
  page.on('request', onRequest)
  page.on('response', onResponse)
  page.on('console', onConsole)
  page.on('pageerror', onPageError)
  page.on('requestfinished', onFinished)
  page.on('requestfailed', onFailed)
  return {
    async waitForResponse(method, pathname, timeoutMs = 45_000) {
      const deadline = Date.now() + timeoutMs
      while (Date.now() < deadline) {
        const match = responses.find(response => {
          try {
            return response.method === method && new URL(response.url).pathname === pathname
          } catch { return false }
        })
        if (match) return match.status
        await new Promise(resolve => setTimeout(resolve, 25))
      }
      return null
    },
    importStatusSummary() {
      const selected = { post: [], get: [] }
      for (const response of responses) {
        let pathname = ''
        try { pathname = new URL(response.url).pathname } catch { continue }
        if (response.method === 'POST' && pathname === '/api/project-imports') {
          selected.post.push(statusCategory(response.status))
        } else if (response.method === 'GET' && /^\/api\/project-imports\/[^/]+$/u.test(pathname)) {
          selected.get.push(statusCategory(response.status))
        }
      }
      return {
        postCount: selected.post.length,
        getCount: selected.get.length,
        statusCategories: {
          post: [...new Set(selected.post)].sort(),
          get: [...new Set(selected.get)].sort(),
        },
      }
    },
    async finish() {
      page.off('request', onRequest)
      page.off('response', onResponse)
      page.off('console', onConsole)
      page.off('pageerror', onPageError)
      page.off('requestfinished', onFinished)
      page.off('requestfailed', onFailed)
      const listeners = [
        ['request', onRequest], ['response', onResponse], ['console', onConsole],
        ['pageerror', onPageError],
        ['requestfinished', onFinished], ['requestfailed', onFailed],
      ]
      const listenerCount = typeof page.listeners === 'function'
        ? listeners.filter(([event, handler]) => page.listeners(event).includes(handler)).length
        : 0
      const consoleDiagnostics = Object.fromEntries([
        'locationlessNetwork', 'otherResourceNetwork', 'frameworkOrPageError', 'other',
      ].map(category => [category, { adjacent: 0, notAdjacent: 0 }]))
      let expectedCorsNetworkConsole = 0
      for (const item of corsConsoleCandidates) {
        const adjacent = expectedFailureSequences.some(value => Math.abs(value - item.sequence) <= 2)
        if (adjacent) expectedCorsNetworkConsole += 1
        else {
          consoleErrors += 1
          unmatchedConsole.push({ category: 'otherResourceNetwork', sequence: item.sequence })
        }
      }
      for (const item of unmatchedConsole) {
        const adjacent = expectedFailureSequences.some(value => Math.abs(value - item.sequence) <= 2)
        consoleDiagnostics[item.category][adjacent ? 'adjacent' : 'notAdjacent'] += 1
      }
      return {
        consoleErrors, expectedNetworkConsole, expectedCorsNetworkConsole,
        requestFailures, expectedRequestFailures,
        non2xx, originViolations,
        pendingRequests: pending.size, listenerCount, pageErrors, consoleDiagnostics,
      }
    },
  }
}

export function assertRuntimeEvidenceHealthy(evidence) {
  for (const category of [
    'locationlessNetwork', 'otherResourceNetwork', 'frameworkOrPageError', 'other',
  ]) {
    for (const adjacency of ['adjacent', 'notAdjacent']) {
      const count = evidence?.consoleDiagnostics?.[category]?.[adjacency]
      if (!Number.isInteger(count) || count < 0) {
        throw new Error(`runtime-console-${category}-${adjacency}-count-invalid`)
      }
      if (count) throw new Error(`runtime-console-${category}-${adjacency}-count-${count}`)
    }
  }
  const categories = [
    ['request-failures', evidence?.requestFailures],
    ['non2xx', evidence?.non2xx],
    ['origin-violations', evidence?.originViolations],
    ['pending-requests', evidence?.pendingRequests],
    ['listeners', evidence?.listenerCount],
    ['page-errors', evidence?.pageErrors],
  ]
  for (const [category, count] of categories) {
    if (!Number.isInteger(count) || count < 0) throw new Error(`runtime-${category}-count-invalid`)
    if (count) throw new Error(`runtime-${category}-count-${count}`)
  }
  if (!Number.isInteger(evidence?.expectedRequestFailures)) {
    throw new Error('runtime-expected-request-failures-count-invalid')
  }
  if (evidence.expectedRequestFailures !== 1) {
    throw new Error(`runtime-expected-request-failures-count-${evidence.expectedRequestFailures}`)
  }
  if (!Number.isInteger(evidence?.expectedNetworkConsole) || evidence.expectedNetworkConsole < 0) {
    throw new Error('runtime-expected-network-console-count-invalid')
  }
  if (evidence.expectedNetworkConsole > 2) {
    throw new Error(`runtime-expected-network-console-count-${evidence.expectedNetworkConsole}`)
  }
  if (!Number.isInteger(evidence?.expectedCorsNetworkConsole) || evidence.expectedCorsNetworkConsole < 0) {
    throw new Error('runtime-expected-cors-network-console-count-invalid')
  }
  if (evidence.expectedCorsNetworkConsole > 1) {
    throw new Error(`runtime-expected-cors-network-console-count-${evidence.expectedCorsNetworkConsole}`)
  }
}
