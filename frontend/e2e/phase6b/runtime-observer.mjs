function originOf(value) {
  try { return new URL(value).origin } catch { return '' }
}

export function observeRuntime(page, { allowedOrigins = [] } = {}) {
  const responses = []
  const errors = []
  const failures = []
  const allowed = new Set(allowedOrigins)
  const onResponse = wire => responses.push({
    method: wire.request().method(), status: wire.status(), url: wire.url(),
  })
  const onConsole = message => { if (message.type() === 'error') errors.push(message.text()) }
  const onFailed = wire => failures.push(wire.url())
  page.on('response', onResponse)
  page.on('console', onConsole)
  page.on('requestfailed', onFailed)
  return {
    async finish() {
      page.off('response', onResponse)
      page.off('console', onConsole)
      page.off('requestfailed', onFailed)
      return { responses, errors, failures, allowed }
    },
  }
}

export function assertRuntimeEvidenceHealthy(evidence) {
  if (!evidence || evidence.errors.length || evidence.failures.length) {
    throw new Error('runtime failures were observed')
  }
  for (const response of evidence.responses) {
    if (!evidence.allowed.has(originOf(response.url))) throw new Error('runtime origin was not owned')
    if (response.status < 200 || response.status >= 400) throw new Error('runtime response was not healthy')
  }
}
