function projectPath(projectId, suffix) {
  return `/projects/${encodeURIComponent(String(projectId || '').trim())}${suffix}`
}

export const PROJECT_HEALTH_API_ENDPOINTS = Object.freeze({
  chapters: projectId => projectPath(projectId, '/chapters'),
  pendingSettingChangeEvents: projectId => projectPath(projectId, '/settings/change-events?status=pending_review'),
  settingEntities: projectId => projectPath(projectId, '/settings/entities'),
  settingRelations: projectId => projectPath(projectId, '/settings/relations')
})

function snapshotError(endpoint, error) {
  const wrapped = new Error(`projectHealthSnapshotApiFailed: ${endpoint}: ${error?.message || error}`)
  wrapped.code = 'projectHealthSnapshotApiFailed'
  wrapped.endpoint = endpoint
  wrapped.cause = error
  return wrapped
}

async function getEndpoint(api, endpoint) {
  try {
    const rows = await api(endpoint)
    return Array.isArray(rows) ? rows : []
  } catch (error) {
    throw snapshotError(endpoint, error)
  }
}

export async function collectProjectHealthSnapshotFromApi({
  api,
  projectId
} = {}) {
  if (typeof api !== 'function') {
    throw new TypeError('collectProjectHealthSnapshotFromApi requires an injected api function')
  }
  const normalizedProjectId = String(projectId || '').trim()
  if (!normalizedProjectId) {
    const error = new Error('projectHealthSnapshotApiFailed: projectId is required')
    error.code = 'projectHealthSnapshotApiFailed'
    error.endpoint = null
    throw error
  }

  const endpoints = {
    chapters: PROJECT_HEALTH_API_ENDPOINTS.chapters(normalizedProjectId),
    settingChangeEvents: PROJECT_HEALTH_API_ENDPOINTS.pendingSettingChangeEvents(normalizedProjectId),
    settingEntities: PROJECT_HEALTH_API_ENDPOINTS.settingEntities(normalizedProjectId),
    settingRelations: PROJECT_HEALTH_API_ENDPOINTS.settingRelations(normalizedProjectId)
  }

  const [
    chapters,
    settingChangeEvents,
    settingEntities,
    settingRelations
  ] = await Promise.all([
    getEndpoint(api, endpoints.chapters),
    getEndpoint(api, endpoints.settingChangeEvents),
    getEndpoint(api, endpoints.settingEntities),
    getEndpoint(api, endpoints.settingRelations)
  ])

  return {
    projectId: normalizedProjectId,
    chapters,
    settingChangeEvents,
    settingEntities,
    settingRelations,
    endpoints
  }
}
