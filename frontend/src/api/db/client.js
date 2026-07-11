/** Writer Core M1 product API client. */

const BASE = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api').replace(/\/+$/, '')
const DEFAULT_TIMEOUT = 30000

async function request(method, path, body, timeoutMs = DEFAULT_TIMEOUT) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)

  try {
    const options = {
      method,
      headers: { 'Content-Type': 'application/json' },
      signal: controller.signal,
    }
    if (body !== undefined) options.body = JSON.stringify(body)

    const response = await fetch(`${BASE}${path}`, options)
    if (!response.ok) {
      const detail = await response.text().catch(() => response.statusText)
      throw new Error(`API error ${response.status}: ${detail}`)
    }
    const text = await response.text()
    if (!text) return null
    try {
      return JSON.parse(text)
    } catch {
      throw new Error(`Invalid JSON response: ${text.slice(0, 200)}`)
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`请求超时 (${timeoutMs / 1000}s): ${method} ${path}`)
    }
    throw error
  } finally {
    clearTimeout(timer)
  }
}
const get = path => request('GET', path)
const post = (path, body) => request('POST', path, body)
const put = (path, body) => request('PUT', path, body)
const del = path => request('DELETE', path)

function queryString(params = {}) {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') query.set(key, value)
  }
  const result = query.toString()
  return result ? `?${result}` : ''
}

export const api = {
  health: () => get('/health'),

  projects: {
    list: () => get('/projects'),
    create: data => post('/projects', data),
    get: projectId => get(`/projects/${projectId}`),
    contentState: projectId => get(`/projects/${projectId}/content-state`),
    update: (projectId, data) => put(`/projects/${projectId}`, data),
    delete: projectId => del(`/projects/${projectId}`),
  },

  seeds: {
    list: projectId => get(`/projects/${projectId}/seeds`),
  },

  providers: {
    list: () => get('/providers'),
    create: data => post('/providers', data),
    update: (providerId, data) => put(`/providers/${providerId}`, data),
    delete: providerId => del(`/providers/${providerId}`),
  },

  bindings: {
    get: projectId => get(`/projects/${projectId}/bindings`),
    status: projectId => get(`/projects/${projectId}/bindings/status`),
  },

  writerCore: {
    state: projectId => get(`/projects/${projectId}/writer-core/state`),
  },

  canon: {
    head: projectId => get(`/projects/${projectId}/canon/head`),
    entities: (projectId, params = {}) => get(`/projects/${projectId}/canon/entities${queryString(params)}`),
    entity: (projectId, entityId) => get(`/projects/${projectId}/canon/entities/${entityId}`),
    resolveAlias: (projectId, name) => get(`/projects/${projectId}/canon/aliases/resolve?name=${encodeURIComponent(name)}`),
  },

  projections: {
    head: projectId => get(`/projects/${projectId}/projections/head`),
  },
}
