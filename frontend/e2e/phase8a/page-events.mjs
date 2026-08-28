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

function failureType(value) {
  const text = typeof value === 'string' ? value.toUpperCase() : ''
  if (text.includes('ERR_ABORTED')) return 'aborted'
  if (text.includes('CONNECTION') || text.includes('CONNECTION_RESET')) return 'connection'
  if (text.includes('TIMED_OUT') || text.includes('TIMEOUT')) return 'timeout'
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
    method: METHODS.has(method) ? method : 'OTHER',
    route: routeTemplate(url),
    failureType: failureType(failure?.errorText),
  }
}
