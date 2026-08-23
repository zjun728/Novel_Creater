function ownedHttpOrigins(values) {
  if (!Array.isArray(values) || values.length === 0) {
    throw new TypeError('Phase7B HTTP origin boundary is invalid')
  }
  const origins = new Set()
  for (const value of values) {
    let parsed
    try {
      parsed = new URL(value)
    } catch {
      throw new TypeError('Phase7B HTTP origin boundary is invalid')
    }
    if (
      typeof value !== 'string'
      || parsed.protocol !== 'http:'
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
      throw new TypeError('Phase7B HTTP origin boundary is invalid')
    }
    origins.add(value)
  }
  return origins
}


export async function installHttpOriginBoundary(context, allowedOrigins) {
  const originAllowlist = ownedHttpOrigins(allowedOrigins)
  if (typeof context?.route !== 'function') {
    throw new TypeError('Phase7B HTTP origin boundary is invalid')
  }
  await context.route('**/*', async route => {
    let origin = null
    try {
      const parsed = new URL(route.request().url())
      if (['http:', 'https:'].includes(parsed.protocol)) origin = parsed.origin
    } catch {
      origin = null
    }
    if (origin !== null && originAllowlist.has(origin)) {
      await route.continue()
      return
    }
    await route.abort('blockedbyclient')
  })
}
