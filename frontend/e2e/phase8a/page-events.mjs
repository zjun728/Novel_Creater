const STAGES = new Set(['setup', 'complete', 'awaiting', 'corrupt'])
const METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])

function routeTemplate(rawUrl) {
  try {
    const url = new URL(rawUrl)
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1') return 'not-owned'
    const pathname = url.pathname
    if (/^\/api\/projects\/[^/]+\/manuscript\/chapters\/[^/]+$/u.test(pathname)) return 'manuscript-chapter'
    if (/^\/api\/projects\/[^/]+\/manuscript$/u.test(pathname)) return 'manuscript-index'
    if (/^\/api\/projects\/[^/]+\/novel-download(?:\/options)?$/u.test(pathname)) return 'novel-download'
    if (pathname.startsWith('/api/')) return 'other-api'
    if (pathname.startsWith('/src/') || pathname.startsWith('/assets/')) return 'frontend-asset'
    return 'frontend-route'
  } catch {
    return 'not-owned'
  }
}

function safeMethod(value) {
  const method = typeof value === 'string' ? value.toUpperCase() : ''
  return METHODS.has(method) ? method : 'OTHER'
}

function responseRouteTemplate(rawUrl) {
  try {
    const url = new URL(rawUrl)
    if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1') return 'not-owned'
    if (/^\/api\/projects\/[^/]+\/manuscript\/chapters\/[^/]+$/u.test(url.pathname)) return 'manuscript-chapter'
    if (/^\/api\/projects\/[^/]+\/manuscript$/u.test(url.pathname)) return 'manuscript-index'
    if (/^\/api\/projects\/[^/]+\/novel-download\/options$/u.test(url.pathname)) return 'novel-download-options'
    if (/^\/api\/projects\/[^/]+\/novel-download$/u.test(url.pathname)) {
      const scope = url.searchParams.get('scope')
      return `novel-download-${['chapter', 'volume', 'book'].includes(scope) ? scope : 'unknown'}`
    }
    if (url.pathname.startsWith('/api/')) return 'other-api'
    return 'other-owned'
  } catch {
    return 'not-owned'
  }
}

function failureType(value) {
  const text = typeof value === 'string' ? value.toUpperCase() : ''
  if (text.includes('ERR_ABORTED')) return 'aborted'
  if (text.includes('TIMED_OUT') || text.includes('TIMEOUT')) return 'timeout'
  if (text.includes('CONNECTION') || text.includes('CONNECTION_RESET')) return 'connection'
  if (text.includes('BLOCKED')) return 'blocked'
  return 'other'
}

export function summarizeRequestFailure(request, currentStage) {
  let method = 'OTHER'
  let url = ''
  let failure = null
  try { method = String(request.method()).toUpperCase() } catch {}
  try { url = request.url() } catch {}
  try { failure = request.failure() } catch {}
  return {
    kind: 'request-failed',
    stage: STAGES.has(currentStage) ? currentStage : 'unknown',
    method: safeMethod(method),
    route: routeTemplate(url),
    failureType: failureType(failure?.errorText),
  }
}

export function summarizeResponse(response, currentStage) {
  let method = 'OTHER'
  let url = ''
  let status = 0
  try { method = response.request().method() } catch {}
  try { url = response.url() } catch {}
  try {
    const observed = response.status()
    if (Number.isInteger(observed) && observed >= 100 && observed <= 599) status = observed
  } catch {}
  return {
    method: safeMethod(method),
    route: responseRouteTemplate(url),
    stage: STAGES.has(currentStage) ? currentStage : 'unknown',
    status,
  }
}
