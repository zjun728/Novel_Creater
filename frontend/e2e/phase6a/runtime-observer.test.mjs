import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'

import { assertRuntimeEvidenceHealthy, observeRuntime } from './runtime-observer.mjs'

class Page extends EventEmitter {}
class Context extends EventEmitter {
  constructor(pages = []) { super(); this._pages = pages }
  pages() { return this._pages }
  popup(page) { this._pages.push(page); this.emit('page', page) }
}
class StickyContext extends Context {
  off(event, listener) {
    if (event === 'response') return this
    return super.off(event, listener)
  }
}
class StickyPage extends Page {
  off(event, listener) {
    if (event === 'console') return this
    return super.off(event, listener)
  }
}

const request = (url, resourceType = 'other') => ({ url: () => url, resourceType: () => resourceType })
const response = (url, status) => ({ url: () => url, status: () => status, request: () => request(url) })
const failedRequest = (url, errorText) => ({ url: () => url, failure: () => ({ errorText }) })

test('context observer attaches initial pages and later popups then detaches every listener', async () => {
  const initial = new Page(); const popup = new Page(); const context = new Context([initial])
  const runtime = observeRuntime(context, { allowedOrigins: ['http://127.0.0.1:4000'] })
  for (const event of ['console', 'pageerror', 'request', 'requestfinished', 'requestfailed', 'response']) {
    assert.equal(initial.listenerCount(event), ['console', 'pageerror'].includes(event) ? 1 : 0, event)
  }
  for (const event of ['request', 'requestfinished', 'requestfailed', 'response']) assert.equal(context.listenerCount(event), 1, event)
  context.popup(popup)
  for (const event of ['console', 'pageerror', 'request', 'requestfinished', 'requestfailed', 'response']) {
    assert.equal(popup.listenerCount(event), ['console', 'pageerror'].includes(event) ? 1 : 0, event)
  }
  const evidence = await runtime.finish()
  assert.deepEqual(evidence, {
    consoleErrors: 0, pageErrors: 0, requestFailures: 0, non2xx: 0,
    originViolations: 0, pendingRequests: 0, listenerCount: 0,
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
  })
  assert.equal(context.listenerCount('page'), 0)
  for (const page of [initial, popup]) assert.equal(page.eventNames().length, 0)
})

test('listener evidence ignores framework listeners but detects observer-owned residue', async () => {
  const page = new Page(); const context = new Context([page])
  const frameworkContextListener = () => {}
  const frameworkPageListener = () => {}
  context.on('page', frameworkContextListener)
  page.on('console', frameworkPageListener)
  const runtime = observeRuntime(context, { allowedOrigins: ['http://127.0.0.1:4000'] })
  const evidence = await runtime.finish()
  assert.equal(evidence.listenerCount, 0)
  assert.deepEqual(context.listeners('page'), [frameworkContextListener])
  assert.deepEqual(page.listeners('console'), [frameworkPageListener])

  const sticky = new StickyPage(); const stickyContext = new Context([sticky])
  const leaky = observeRuntime(stickyContext, { allowedOrigins: ['http://127.0.0.1:4000'] })
  assert.equal((await leaky.finish()).listenerCount, 1)

  const networkContext = new StickyContext([])
  const networkLeaky = observeRuntime(networkContext, { allowedOrigins: ['http://127.0.0.1:4000'] })
  assert.equal((await networkLeaky.finish()).listenerCount, 1)
})

test('context network listeners capture popup initial navigation before the page event', async () => {
  const context = new Context([])
  const runtime = observeRuntime(context, { allowedOrigins: ['http://127.0.0.1:4000'] })
  const early = request('https://outside.invalid/SECRET', 'document')
  context.emit('request', early)
  context.emit('response', { status: () => 500, request: () => early })
  context.emit('requestfinished', early)
  context.popup(new Page())
  const evidence = await runtime.finish()
  assert.equal(evidence.originViolations, 1)
  assert.equal(evidence.non2xx, 1)
  assert.equal(evidence.pendingRequests, 0)
})

test('redirect responses are non2xx and remain unhealthy', async () => {
  const context = new Context([new Page()])
  const runtime = observeRuntime(context, { allowedOrigins: ['http://127.0.0.1:4000'] })
  const redirect = request('http://127.0.0.1:4000/redirect')
  context.emit('request', redirect)
  context.emit('response', { status: () => 302, request: () => redirect })
  context.emit('requestfinished', redirect)
  const evidence = await runtime.finish()
  assert.equal(evidence.non2xx, 1)
  assert.throws(() => assertRuntimeEvidenceHealthy(evidence), /phase6a-runtime-non2xx-count-1/u)
})

test('observer records only fixed counters and balances pending requests', async () => {
  const page = new Page(); const context = new Context([page])
  const runtime = observeRuntime(context, { allowedOrigins: ['http://127.0.0.1:4000'] })
  const good = request('http://127.0.0.1:4000/api/projects')
  context.emit('request', good)
  context.emit('requestfinished', good)
  context.emit('request', request('https://secret.example/private'))
  page.emit('console', { type: () => 'error', text: () => 'SECRET-CONSOLE' })
  page.emit('pageerror', new Error('SECRET-PAGE'))
  context.emit('requestfailed', request('https://secret.example/failed'))
  context.emit('response', response('http://127.0.0.1:4000/api/fail', 500))
  assert.deepEqual(await runtime.finish(), {
    consoleErrors: 1, pageErrors: 1, requestFailures: 1, non2xx: 1,
    originViolations: 1, pendingRequests: 1, listenerCount: 0,
    consoleNetworkErrors: 0, consoleBrowserFrameworkErrors: 0,
    consoleAppExplicitErrors: 0, consoleUnknownErrors: 1,
    consoleAdjacentOwnedRequests: 1, consoleAdjacentPopupCloses: 0,
    consoleAdjacentDownloads: 0,
    networkOwnedStatus2xx: 0, networkOwnedStatus3xx: 0,
    networkOwnedStatus4xx: 0, networkOwnedStatus5xx: 0,
    networkOwnedRequestFailed: 0, networkOwnedCancelled: 0,
    networkOwned4xxDocument: 0, networkOwned4xxScript: 0,
    networkOwned4xxStylesheet: 0, networkOwned4xxImage: 0,
    networkOwned4xxFont: 0, networkOwned4xxFetch: 0,
    networkOwned4xxXhr: 0, networkOwned4xxOther: 0,
  })
})

test('console diagnostics retain only fixed categories and bounded adjacency counters', async () => {
  let now = 100
  const page = new Page(); const popup = new Page(); const context = new Context([page])
  const runtime = observeRuntime(context, {
    allowedOrigins: ['http://127.0.0.1:4000'], clock: () => now, adjacencyWindowMs: 50,
  })
  const owned = request('http://127.0.0.1:4000/api/projects')
  context.emit('request', owned); context.emit('requestfinished', owned)
  now = 110; context.popup(popup); popup.emit('close')
  now = 120; page.emit('download', {})
  now = 125; page.emit('console', {
    type: () => 'error', text: () => 'Failed to load resource: SECRET',
    location: () => ({ url: 'http://127.0.0.1:4000/SECRET', lineNumber: 1 }),
  })
  now = 200; page.emit('console', {
    type: () => 'error', text: () => 'framework failure SECRET',
    location: () => ({ url: 'http://127.0.0.1:4000/node_modules/SECRET.js', lineNumber: 1 }),
  })
  page.emit('console', {
    type: () => 'error', text: () => 'application failure SECRET',
    location: () => ({ url: 'http://127.0.0.1:4000/src/SECRET.js', lineNumber: 1 }),
  })
  page.emit('console', {
    type: () => 'error', text: () => 'unclassified failure SECRET',
    location: () => ({ url: 'https://outside.invalid/SECRET', lineNumber: 1 }),
  })
  const evidence = await runtime.finish()
  assert.deepEqual({
    network: evidence.consoleNetworkErrors,
    framework: evidence.consoleBrowserFrameworkErrors,
    app: evidence.consoleAppExplicitErrors,
    unknown: evidence.consoleUnknownErrors,
    owned: evidence.consoleAdjacentOwnedRequests,
    popup: evidence.consoleAdjacentPopupCloses,
    download: evidence.consoleAdjacentDownloads,
  }, { network: 1, framework: 1, app: 1, unknown: 1, owned: 1, popup: 1, download: 1 })
  assert.throws(
    () => assertRuntimeEvidenceHealthy(evidence),
    error => error.message === 'phase6a-runtime-consoleNetworkErrors-count-1-adjacent-ownedRequest-1-popupClose-1-download-1'
      + '-owned-status2xx-0-status3xx-0-status4xx-0-status5xx-0-requestfailed-0-cancelled-0'
      + '-4xx-document-0-script-0-stylesheet-0-image-0-font-0-fetch-0-xhr-0-other-0'
      && !error.message.includes('SECRET'),
  )
})

test('network console diagnostics correlate only fixed owned-origin outcome counters', async () => {
  let now = 100
  const page = new Page(); const context = new Context([page])
  const runtime = observeRuntime(context, {
    allowedOrigins: ['http://127.0.0.1:4000'], clock: () => now, adjacencyWindowMs: 50,
  })
  for (const status of [200, 302, 404, 500]) {
    const item = request(`http://127.0.0.1:4000/SECRET-${status}`)
    context.emit('request', item)
    context.emit('response', { status: () => status, request: () => item })
    context.emit('requestfinished', item)
  }
  for (const item of [
    failedRequest('http://127.0.0.1:4000/SECRET-FAIL', 'SECRET-RESET'),
    failedRequest('http://127.0.0.1:4000/SECRET-CANCEL', 'net::ERR_ABORTED'),
  ]) {
    context.emit('request', item); context.emit('requestfailed', item)
  }
  now = 120
  page.emit('console', {
    type: () => 'error', text: () => 'Failed to load resource: SECRET',
    location: () => ({ url: 'http://127.0.0.1:4000/SECRET', lineNumber: 1 }),
  })
  const evidence = await runtime.finish()
  assert.deepEqual({
    status2xx: evidence.networkOwnedStatus2xx,
    status3xx: evidence.networkOwnedStatus3xx,
    status4xx: evidence.networkOwnedStatus4xx,
    status5xx: evidence.networkOwnedStatus5xx,
    requestfailed: evidence.networkOwnedRequestFailed,
    cancelled: evidence.networkOwnedCancelled,
  }, { status2xx: 1, status3xx: 1, status4xx: 1, status5xx: 1, requestfailed: 1, cancelled: 1 })
  assert.throws(
    () => assertRuntimeEvidenceHealthy(evidence),
    error => error.message.includes('-owned-status2xx-1-status3xx-1-status4xx-1-status5xx-1-requestfailed-1-cancelled-1')
      && error.message.endsWith('-4xx-document-0-script-0-stylesheet-0-image-0-font-0-fetch-0-xhr-0-other-1')
      && !error.message.includes('SECRET'),
  )
})

test('4xx correlation retains only fixed resource-type counters', async () => {
  const page = new Page(); const context = new Context([page])
  const runtime = observeRuntime(context, { allowedOrigins: ['http://127.0.0.1:4000'] })
  for (const type of ['document', 'script', 'stylesheet', 'image', 'font', 'fetch', 'xhr', 'SECRET-UNKNOWN']) {
    const item = request(`http://127.0.0.1:4000/SECRET-${type}`, type)
    context.emit('request', item)
    context.emit('response', { status: () => 404, request: () => item })
    context.emit('requestfinished', item)
  }
  page.emit('console', {
    type: () => 'error', text: () => 'Failed to load resource: SECRET',
    location: () => ({ url: 'http://127.0.0.1:4000/SECRET', lineNumber: 1 }),
  })
  const evidence = await runtime.finish()
  assert.deepEqual({
    document: evidence.networkOwned4xxDocument, script: evidence.networkOwned4xxScript,
    stylesheet: evidence.networkOwned4xxStylesheet, image: evidence.networkOwned4xxImage,
    font: evidence.networkOwned4xxFont, fetch: evidence.networkOwned4xxFetch,
    xhr: evidence.networkOwned4xxXhr, other: evidence.networkOwned4xxOther,
  }, { document: 1, script: 1, stylesheet: 1, image: 1, font: 1, fetch: 1, xhr: 1, other: 1 })
  assert.throws(
    () => assertRuntimeEvidenceHealthy(evidence),
    error => error.message.endsWith('-4xx-document-1-script-1-stylesheet-1-image-1-font-1-fetch-1-xhr-1-other-1')
      && !error.message.includes('SECRET'),
  )
})

test('health assertion rejects each unsafe counter without exposing raw evidence', () => {
  const zero = {
    consoleErrors: 0, pageErrors: 0, requestFailures: 0, non2xx: 0,
    originViolations: 0, pendingRequests: 0, listenerCount: 0,
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
  assert.doesNotThrow(() => assertRuntimeEvidenceHealthy(zero))
  const categories = new Set([
    'consoleNetworkErrors', 'consoleBrowserFrameworkErrors',
    'consoleAppExplicitErrors', 'consoleUnknownErrors',
  ])
  for (const key of Object.keys(zero)) {
    const unsafe = { ...zero, [key]: 2, raw: 'SECRET-URL-OR-ERROR' }
    const expected = `phase6a-runtime-${key}-count-2`
      + (categories.has(key) ? '-adjacent-ownedRequest-0-popupClose-0-download-0' : '')
      + (key === 'consoleNetworkErrors'
        ? '-owned-status2xx-0-status3xx-0-status4xx-0-status5xx-0-requestfailed-0-cancelled-0'
          + '-4xx-document-0-script-0-stylesheet-0-image-0-font-0-fetch-0-xhr-0-other-0' : '')
    assert.throws(
      () => assertRuntimeEvidenceHealthy(unsafe),
      error => error.message === expected && !error.message.includes(unsafe.raw),
    )
  }
  assert.throws(
    () => assertRuntimeEvidenceHealthy({ ...zero, consoleErrors: 'SECRET-NON-INTEGER' }),
    error => error.message === 'phase6a-runtime-consoleErrors-count-1',
  )
})
