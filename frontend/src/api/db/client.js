/** Writer Core product API client. */

import { ApiError, parseApiError } from './api-error.js'

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
      throw await parseApiError(response)
    }
    const text = await response.text()
    if (!text) return null
    try {
      return JSON.parse(text)
    } catch {
      throw new ApiError({
        status: response.status,
        code: 'invalid_response',
        message: '服务返回了无效响应',
      })
    }
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new ApiError({
        code: 'request_timeout',
        message: `请求超时 (${timeoutMs / 1000}s)`,
      })
    }
    if (error instanceof ApiError) throw error
    throw new ApiError()
  } finally {
    clearTimeout(timer)
  }
}
const get = path => request('GET', path)
const post = (path, body) => request('POST', path, body)
const put = (path, body) => request('PUT', path, body)
const del = (path, body) => request('DELETE', path, body)

const segment = value => encodeURIComponent(String(value))

function pickDefined(value = {}, fields = []) {
  const result = {}
  for (const field of fields) {
    if (value?.[field] !== undefined) result[field] = value[field]
  }
  return result
}

const PROJECT_FIELDS = [
  'title', 'genre', 'description', 'targetWords', 'targetChapters',
]
const PROVIDER_CREATE_FIELDS = [
  'name', 'providerType', 'model', 'baseURL', 'apiKey', 'enabled', 'sortOrder',
  'stream', 'maxContextTokens', 'maxOutputTokens', 'temperature', 'topP',
  'supportsJSON', 'supportsStreaming', 'notes', 'thinking',
]
const PROVIDER_UPDATE_FIELDS = PROVIDER_CREATE_FIELDS.filter(field => field !== 'providerType')
const SEED_FIELDS = [
  'title', 'genre', 'logline', 'protagonist', 'desire', 'coreConflict',
  'worldPressure', 'openingHook', 'differentiation',
]
const STORY_ENGINE_FIELDS = [
  'name', 'storyPromise', 'protagonistDesire', 'sustainedPressure',
  'growthDirection', 'conflictLoop', 'ensembleRoles', 'advantageAndCost',
  'satisfactionSources', 'longFormVariation', 'endingAnchor', 'risks',
  'differentiation',
]
const CONTRACT_DRAFT_FIELDS = [
  'schemaVersion', 'draftStage', 'engineOptionId', 'engineHash', 'channelProfileKey',
  'genreProfileKey', 'qualityCharterVersion', 'totalWordRange',
  'chapterCapacityPolicy', 'primaryStyleRef', 'secondaryStyleRef',
  'experienceCardRefs', 'corpusSourceRefs', 'likes', 'dislikes',
]

const seedPayload = value => pickDefined(value, SEED_FIELDS)
const bindingEntry = value => pickDefined(value, ['taskKey', 'providerId'])
const assetRef = value => pickDefined(value, ['id', 'revision', 'contentHash'])
const corpusRef = value => pickDefined(value, [
  'id', 'revision', 'contentHash', 'selectionMode',
])

function storyEngineOption(value = {}) {
  const option = pickDefined(value, STORY_ENGINE_FIELDS)
  if (Array.isArray(option.ensembleRoles)) {
    option.ensembleRoles = option.ensembleRoles.map(role => (
      pickDefined(role, ['role', 'purpose'])
    ))
  }
  for (const field of ['satisfactionSources', 'longFormVariation', 'risks']) {
    if (Array.isArray(option[field])) option[field] = [...option[field]]
  }
  return option
}

function contractDraft(value = {}) {
  const draft = pickDefined(value, CONTRACT_DRAFT_FIELDS)
  if (draft.primaryStyleRef != null) draft.primaryStyleRef = assetRef(draft.primaryStyleRef)
  if (draft.secondaryStyleRef) draft.secondaryStyleRef = assetRef(draft.secondaryStyleRef)
  if (Array.isArray(draft.experienceCardRefs)) {
    draft.experienceCardRefs = draft.experienceCardRefs.map(assetRef)
  }
  if (Array.isArray(draft.corpusSourceRefs)) {
    draft.corpusSourceRefs = draft.corpusSourceRefs.map(corpusRef)
  }
  for (const field of ['totalWordRange', 'likes', 'dislikes']) {
    if (Array.isArray(draft[field])) draft[field] = [...draft[field]]
  }
  return draft
}

function boundedInteger(value, { min = 0, max }) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return undefined
  return Math.min(max, Math.max(min, Math.trunc(parsed)))
}

function relativeCorpusPath(value) {
  const path = String(value || '').trim()
  const segments = path.split(/[\\/]+/)
  if (
    !path
    || /^[\\/]/.test(path)
    || /^[A-Za-z][A-Za-z0-9+.-]*:/.test(path)
    || segments.some(part => part === '.' || part === '..')
  ) {
    throw new TypeError('Expected a relative corpus path')
  }
  return path
}

function boundedCursor(value) {
  if (value === undefined || value === null || value === '') return undefined
  const cursor = String(value)
  if (cursor.length > 4096) throw new RangeError('Corpus cursor exceeds 4096 characters')
  return cursor
}

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
    create: data => post('/projects', pickDefined(data, PROJECT_FIELDS)),
    get: projectId => get(`/projects/${segment(projectId)}`),
    contentState: projectId => get(`/projects/${segment(projectId)}/content-state`),
    update: (projectId, data) => put(
      `/projects/${segment(projectId)}`,
      pickDefined(data, PROJECT_FIELDS),
    ),
    delete: projectId => del(`/projects/${segment(projectId)}`),
  },

  seeds: {
    list: projectId => get(`/projects/${segment(projectId)}/seeds`),
    create: (projectId, payload) => post(
      `/projects/${segment(projectId)}/seeds`,
      { payload: seedPayload(payload) },
    ),
    update: (projectId, seedId, data) => put(
      `/projects/${segment(projectId)}/seeds/${segment(seedId)}`,
      {
        payload: seedPayload(data.payload),
        expectedSeedRevision: data.expectedSeedRevision,
        expectedSelectionRevision: data.expectedSelectionRevision,
      },
    ),
    delete: (projectId, seedId, data) => del(
      `/projects/${segment(projectId)}/seeds/${segment(seedId)}`,
      {
        expectedSeedRevision: data.expectedSeedRevision,
        expectedSelectionRevision: data.expectedSelectionRevision,
      },
    ),
    selected: projectId => get(`/projects/${segment(projectId)}/selected-seed`),
    select: (projectId, data) => put(
      `/projects/${segment(projectId)}/selected-seed`,
      {
        seedId: data.seedId,
        expectedSeedRevision: data.expectedSeedRevision,
        expectedSelectionRevision: data.expectedSelectionRevision,
      },
    ),
  },

  providers: {
    list: () => get('/providers'),
    create: data => post('/providers', pickDefined(data, PROVIDER_CREATE_FIELDS)),
    update: (providerId, data) => put(
      `/providers/${segment(providerId)}`,
      pickDefined(data, PROVIDER_UPDATE_FIELDS),
    ),
    delete: providerId => del(`/providers/${segment(providerId)}`),
  },

  bindings: {
    get: projectId => get(`/projects/${segment(projectId)}/bindings`),
    status: projectId => get(`/projects/${segment(projectId)}/bindings/status`),
    replace: (projectId, data) => put(`/projects/${segment(projectId)}/bindings`, {
      expectedRevision: data.expectedRevision,
      entries: Array.isArray(data.entries) ? data.entries.map(bindingEntry) : data.entries,
    }),
  },

  storyEngines: {
    generate: (projectId, data) => post(
      `/projects/${segment(projectId)}/story-engine-batches`,
      { idempotencyKey: data.idempotencyKey },
    ),
    manual: (projectId, data) => post(
      `/projects/${segment(projectId)}/story-engine-batches/manual`,
      {
        idempotencyKey: data.idempotencyKey,
        options: Array.isArray(data.options) ? data.options.map(storyEngineOption) : data.options,
      },
    ),
    get: (projectId, batchId) => get(
      `/projects/${segment(projectId)}/story-engine-batches/${segment(batchId)}`,
    ),
    reconcile: (projectId, batchId) => post(
      `/projects/${segment(projectId)}/story-engine-batches/${segment(batchId)}/reconcile`,
    ),
  },

  assets: {
    styleTemplates: {
      list: () => get('/assets/style-templates'),
      get: revisionId => get(`/assets/style-templates/${segment(revisionId)}`),
    },
    experienceCards: {
      list: (params = {}) => get(`/assets/experience-cards${queryString({ category: params.category })}`),
      get: revisionId => get(`/assets/experience-cards/${segment(revisionId)}`),
    },
    recommendations: (projectId, engineOptionId) => get(
      `/projects/${segment(projectId)}/asset-recommendations${queryString({ engineOptionId })}`,
    ),
  },

  corpus: {
    discovery: (params = {}) => get(`/corpus/discovery${queryString({
      cursor: boundedCursor(params.cursor),
      limit: boundedInteger(params.limit, { min: 1, max: 200 }),
    })}`),
    imports: {
      create: data => post('/corpus/imports', {
        idempotencyKey: data.idempotencyKey,
        relativePath: relativeCorpusPath(data.relativePath),
      }),
      get: importId => get(`/corpus/imports/${segment(importId)}`),
    },
    sources: {
      list: () => get('/corpus/sources'),
      get: (sourceId, params = {}) => get(
        `/corpus/sources/${segment(sourceId)}${queryString({
          previewChars: boundedInteger(params.previewChars, { min: 1, max: 1200 }),
        })}`,
      ),
      chapters: sourceId => get(`/corpus/sources/${segment(sourceId)}/chapters`),
    },
    chapters: {
      fragments: (chapterId, params = {}) => get(
        `/corpus/chapters/${segment(chapterId)}/fragments${queryString({
          cursor: boundedInteger(params.cursor, { min: 0, max: Number.MAX_SAFE_INTEGER }),
          limit: boundedInteger(params.limit, { min: 1, max: 20 }),
        })}`,
      ),
    },
  },

  contracts: {
    draft: {
      get: projectId => get(`/projects/${segment(projectId)}/contract-draft`),
      save: (projectId, data) => put(`/projects/${segment(projectId)}/contract-draft`, {
        expectedDraftVersion: data.expectedDraftVersion,
        draft: contractDraft(data.draft),
      }),
    },
    preview: projectId => post(`/projects/${segment(projectId)}/contracts/preview`),
    confirm: (projectId, data) => post(`/projects/${segment(projectId)}/contracts/confirm`, {
      idempotencyKey: data.idempotencyKey,
      expectedDraftVersion: data.expectedDraftVersion,
      expectedDraftHash: data.expectedDraftHash,
    }),
    head: projectId => get(`/projects/${segment(projectId)}/contracts/head`),
    history: (projectId, params = {}) => get(
      `/projects/${segment(projectId)}/contracts/history${queryString({
        limit: boundedInteger(params.limit, { min: 1, max: 100 }),
      })}`,
    ),
    clone: projectId => post(`/projects/${segment(projectId)}/contracts/clone`),
  },

  writerCore: {
    state: projectId => get(`/projects/${segment(projectId)}/writer-core/state`),
  },

  canon: {
    head: projectId => get(`/projects/${segment(projectId)}/canon/head`),
    entities: projectId => get(`/projects/${segment(projectId)}/canon/entities`),
    entity: (projectId, entityId) => get(
      `/projects/${segment(projectId)}/canon/entities/${segment(entityId)}`,
    ),
    resolveAlias: (projectId, name) => get(
      `/projects/${segment(projectId)}/canon/aliases/resolve${queryString({ name })}`,
    ),
  },

  projections: {
    head: projectId => get(`/projects/${segment(projectId)}/projections/head`),
  },
}
