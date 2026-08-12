const evidenceKeys = Object.freeze([
  'consoleNetworkErrors', 'consoleBrowserFrameworkErrors',
  'consoleAppExplicitErrors', 'consoleUnknownErrors',
  'consoleErrors', 'pageErrors', 'requestFailures', 'non2xx',
  'originViolations', 'pendingRequests', 'listenerCount',
  'consoleAdjacentOwnedRequests', 'consoleAdjacentPopupCloses',
  'consoleAdjacentDownloads',
  'networkOwnedStatus2xx', 'networkOwnedStatus3xx',
  'networkOwnedStatus4xx', 'networkOwnedStatus5xx',
  'networkOwnedRequestFailed', 'networkOwnedCancelled',
  'networkOwned4xxDocument', 'networkOwned4xxScript',
  'networkOwned4xxStylesheet', 'networkOwned4xxImage',
  'networkOwned4xxFont', 'networkOwned4xxFetch',
  'networkOwned4xxXhr', 'networkOwned4xxOther',
])
const consoleCategoryKeys = new Set(evidenceKeys.slice(0, 4))
const resource4xxCounters = Object.freeze({
  document: 'networkOwned4xxDocument', script: 'networkOwned4xxScript',
  stylesheet: 'networkOwned4xxStylesheet', image: 'networkOwned4xxImage',
  font: 'networkOwned4xxFont', fetch: 'networkOwned4xxFetch',
  xhr: 'networkOwned4xxXhr', other: 'networkOwned4xxOther',
})

function originOf(value) {
  try { return new URL(value).origin } catch { return '' }
}

export function observeRuntime(context, {
  allowedOrigins = [], clock = Date.now, adjacencyWindowMs = 1000,
} = {}) {
  const allowed = new Set(allowedOrigins)
  const pending = new Set()
  const pages = new Map()
  const counters = {
    consoleErrors: 0, pageErrors: 0, requestFailures: 0, non2xx: 0,
    originViolations: 0,
    consoleNetworkErrors: 0, consoleBrowserFrameworkErrors: 0,
    consoleAppExplicitErrors: 0, consoleUnknownErrors: 0,
    consoleAdjacentOwnedRequests: 0, consoleAdjacentPopupCloses: 0,
    consoleAdjacentDownloads: 0,
    networkOwnedStatus2xx: 0, networkOwnedStatus3xx: 0,
    networkOwnedStatus4xx: 0, networkOwnedStatus5xx: 0,
    networkOwnedRequestFailed: 0, networkOwnedCancelled: 0,
    networkOwned4xxDocument: 0, networkOwned4xxScript: 0,
    networkOwned4xxStylesheet: 0, networkOwned4xxImage: 0,
    networkOwned4xxFont: 0, networkOwned4xxFetch: 0,
    networkOwned4xxXhr: 0, networkOwned4xxOther: 0,
  }
  const recent = { ownedRequest: null, popupClose: null, download: null }
  const ownedOutcomes = []

  const isAdjacent = timestamp => timestamp !== null
    && clock() - timestamp >= 0 && clock() - timestamp <= adjacencyWindowMs
  const classifyConsole = message => {
    const text = typeof message.text === 'function' ? message.text() : ''
    const location = typeof message.location === 'function' ? message.location() : {}
    const source = typeof location?.url === 'string' ? location.url : ''
    if (/failed to load resource|networkerror|net::|\berr_/iu.test(text)) return 'consoleNetworkErrors'
    if (/(?:node_modules|@vite|react-dom|webpack|playwright)/iu.test(source)) return 'consoleBrowserFrameworkErrors'
    if (allowed.has(originOf(source))) return 'consoleAppExplicitErrors'
    return 'consoleUnknownErrors'
  }
  const recordOwnedOutcome = key => { ownedOutcomes.push({ key, at: clock() }) }
  const correlateOwnedOutcomes = () => {
    for (const outcome of ownedOutcomes) {
      if (isAdjacent(outcome.at)) counters[outcome.key] += 1
    }
  }
  const recordResponseOutcome = response => {
    const request = response.request()
    if (!allowed.has(originOf(request.url()))) return
    const status = response.status()
    if (status >= 200 && status < 300) recordOwnedOutcome('networkOwnedStatus2xx')
    else if (status >= 300 && status < 400) recordOwnedOutcome('networkOwnedStatus3xx')
    else if (status >= 400 && status < 500) {
      recordOwnedOutcome('networkOwnedStatus4xx')
      const rawType = typeof request.resourceType === 'function' ? request.resourceType() : 'other'
      const type = Object.hasOwn(resource4xxCounters, rawType) ? rawType : 'other'
      recordOwnedOutcome(resource4xxCounters[type])
    }
    else if (status >= 500 && status < 600) recordOwnedOutcome('networkOwnedStatus5xx')
  }
  const recordFailureOutcome = request => {
    if (!allowed.has(originOf(request.url()))) return
    const detail = typeof request.failure === 'function' ? request.failure()?.errorText || '' : ''
    recordOwnedOutcome(/cancel|aborted|err_aborted/iu.test(detail)
      ? 'networkOwnedCancelled' : 'networkOwnedRequestFailed')
  }

  const inspectOrigin = request => {
    if (!allowed.has(originOf(request.url()))) counters.originViolations += 1
  }
  const contextListeners = {
    request: request => {
      pending.add(request)
      if (allowed.has(originOf(request.url()))) recent.ownedRequest = clock()
      inspectOrigin(request)
    },
    requestfinished: request => { pending.delete(request) },
    requestfailed: request => {
      pending.delete(request); counters.requestFailures += 1; recordFailureOutcome(request)
    },
    response: response => {
      recordResponseOutcome(response)
      if (response.status() < 200 || response.status() >= 300) counters.non2xx += 1
    },
  }
  const onPage = (page, popup = true) => {
    if (pages.has(page)) return
    const listeners = {
      console: message => {
        if (message.type() !== 'error') return
        counters.consoleErrors += 1
        const category = classifyConsole(message)
        counters[category] += 1
        if (category === 'consoleNetworkErrors') correlateOwnedOutcomes()
        if (isAdjacent(recent.ownedRequest)) counters.consoleAdjacentOwnedRequests += 1
        if (isAdjacent(recent.popupClose)) counters.consoleAdjacentPopupCloses += 1
        if (isAdjacent(recent.download)) counters.consoleAdjacentDownloads += 1
      },
      pageerror: () => { counters.pageErrors += 1 },
      download: () => { recent.download = clock() },
      close: () => { if (popup) recent.popupClose = clock() },
    }
    pages.set(page, listeners)
    page.on('console', listeners.console)
    page.on('pageerror', listeners.pageerror)
    page.on('download', listeners.download)
    page.on('close', listeners.close)
  }

  for (const page of context.pages()) onPage(page, false)
  context.on('page', onPage)
  for (const [event, listener] of Object.entries(contextListeners)) context.on(event, listener)
  return {
    async finish() {
      context.off('page', onPage)
      for (const [event, listener] of Object.entries(contextListeners)) context.off(event, listener)
      for (const [page, listeners] of pages) {
        for (const [event, listener] of Object.entries(listeners)) page.off(event, listener)
      }
      const evidence = Object.freeze({
        ...counters,
        pendingRequests: pending.size,
        listenerCount: Number(context.listeners('page').includes(onPage))
          + Object.entries(contextListeners).reduce(
            (total, [event, listener]) => total + Number(context.listeners(event).includes(listener)), 0,
          )
          + [...pages.entries()].reduce(
          (total, [page, listeners]) => total + Object.keys(listeners).reduce(
            (count, event) => count + Number(page.listeners(event).includes(listeners[event])), total,
          ), 0,
        ),
      })
      pages.clear()
      pending.clear()
      return evidence
    },
  }
}

export function assertRuntimeEvidenceHealthy(evidence) {
  for (const key of evidenceKeys) {
    const value = evidence?.[key]
    const count = Number.isInteger(value) && value >= 0 ? value : 1
    if (count !== 0) {
      if (consoleCategoryKeys.has(key)) {
        let marker = `phase6a-runtime-${key}-count-${count}`
          + `-adjacent-ownedRequest-${evidence.consoleAdjacentOwnedRequests}`
          + `-popupClose-${evidence.consoleAdjacentPopupCloses}`
          + `-download-${evidence.consoleAdjacentDownloads}`
        if (key === 'consoleNetworkErrors') {
          marker += `-owned-status2xx-${evidence.networkOwnedStatus2xx}`
            + `-status3xx-${evidence.networkOwnedStatus3xx}`
            + `-status4xx-${evidence.networkOwnedStatus4xx}`
            + `-status5xx-${evidence.networkOwnedStatus5xx}`
            + `-requestfailed-${evidence.networkOwnedRequestFailed}`
            + `-cancelled-${evidence.networkOwnedCancelled}`
            + `-4xx-document-${evidence.networkOwned4xxDocument}`
            + `-script-${evidence.networkOwned4xxScript}`
            + `-stylesheet-${evidence.networkOwned4xxStylesheet}`
            + `-image-${evidence.networkOwned4xxImage}`
            + `-font-${evidence.networkOwned4xxFont}`
            + `-fetch-${evidence.networkOwned4xxFetch}`
            + `-xhr-${evidence.networkOwned4xxXhr}`
            + `-other-${evidence.networkOwned4xxOther}`
        }
        throw new Error(marker)
      }
      throw new Error(`phase6a-runtime-${key}-count-${count}`)
    }
  }
}
