/** Writer Core product API client. */

import { ApiError, parseApiError } from './api-error.js'

const BASE = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api').replace(/\/+$/, '')
const DEFAULT_TIMEOUT = 30000
const CHAPTER_DRAFT_GENERATION_TIMEOUT = 1_200_000
const BIBLE_GENERATION_TIMEOUT = 210_000

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
const post = (path, body, timeoutMs) => request('POST', path, body, timeoutMs)
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

const PROVIDER_CREATE_FIELDS = [
  'name', 'providerType', 'model', 'baseURL', 'apiKey', 'enabled', 'sortOrder',
  'stream', 'maxContextTokens', 'maxOutputTokens', 'temperature', 'topP',
  'supportsJSON', 'supportsStreaming', 'notes', 'thinking', 'idempotencyKey',
]
const PROVIDER_UPDATE_FIELDS = [
  ...PROVIDER_CREATE_FIELDS.filter(field => !['providerType', 'idempotencyKey'].includes(field)),
  'expectedRevision', 'idempotencyKey',
]
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
  'genreProfileKey', 'qualityCharterVersion', 'targetTotalWords',
  'expectedVolumeCount', 'expectedChapterCount', 'chapterWordRangePreference',
  'prohibitedDirections', 'authorNotes', 'primaryStyleRef', 'secondaryStyleRef',
  'experienceCardRefs', 'corpusSourceRefs', 'likes', 'dislikes',
]
const STYLE_TRIAL_FIELDS = [
  'selectionRevision', 'engineOptionId', 'engineHash',
  'primaryStyleRevisionId', 'primaryStyleHash',
  'secondaryStyleRevisionId', 'secondaryStyleHash',
  'authorScenario', 'idempotencyKey',
]
const ASSET_RECOMMENDATION_FIELDS = [
  'idempotencyKey', 'engineOptionId', 'taxonomyVersion', 'taxonomyHash',
  'genre', 'creationStage', 'status', 'prohibitedDirections',
]
const BIBLE_SCALAR_FIELDS = [
  'premiseAndPromise', 'powerOrProgressionSystem', 'protagonist',
  'toneAndNarrativeBoundaries',
]
const BIBLE_ARRAY_FIELDS = [
  'worldRules', 'coreCast', 'factions', 'longTermConflicts',
  'relationshipDynamics', 'continuityGuardrails', 'openDesignQuestions',
]

const seedPayload = value => pickDefined(value, SEED_FIELDS)
const seedProvenance = value => pickDefined(value, [
  'kind', 'snapshotIds', 'analysisId', 'inspirationAttemptId', 'publicNotes',
])
const bindingEntry = value => pickDefined(value, ['taskKey', 'providerId'])
const assetRef = value => pickDefined(value, ['id', 'revision', 'contentHash'])
const corpusFragmentRef = value => pickDefined(value, [
  'chapterId', 'fragmentId', 'fragmentHash', 'chapterCharStart',
  'chapterCharEnd', 'referenceUse',
])
const corpusRef = value => {
  const ref = pickDefined(value, [
    'id', 'revisionId', 'revision', 'contentHash', 'selectionMode',
    'fragments', 'pinnedHistoricalRevision',
  ])
  if (Array.isArray(ref.fragments)) {
    ref.fragments = ref.fragments.map(corpusFragmentRef)
  }
  return ref
}

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
  for (const field of [
    'chapterWordRangePreference', 'prohibitedDirections', 'likes', 'dislikes',
  ]) {
    if (Array.isArray(draft[field])) draft[field] = [...draft[field]]
  }
  return draft
}

function biblePayload(value = {}) {
  const payload = pickDefined(value, BIBLE_SCALAR_FIELDS)
  for (const field of BIBLE_ARRAY_FIELDS) {
    if (Array.isArray(value?.[field])) {
      payload[field] = value[field].map(item => pickDefined(item, ['id', 'text']))
    }
  }
  return payload
}

const PLANNING_IDENTITY_FIELDS = [
  'id', 'clientNodeKey', 'revision', 'contentHash', 'lifecycle',
]
const PLANNING_VOLUME_FIELDS = [
  ...PLANNING_IDENTITY_FIELDS,
  'order', 'title', 'coreChange', 'mainPressure', 'ensembleFocus',
  'forbiddenEvents',
]
const PLANNING_PLOT_FIELDS = [
  ...PLANNING_IDENTITY_FIELDS,
  'order', 'title', 'plotType', 'storyQuestion', 'futureDirection',
  'expectedPayoff', 'relatedCharacters',
]
const PLANNING_BLOCK_FIELDS = [
  ...PLANNING_IDENTITY_FIELDS,
  'order', 'title', 'volumeRef', 'plotRefs', 'entrySituation', 'blockGoal',
  'mainPressure', 'expectedChange', 'openQuestions', 'involvedCharacters',
]
const PLANNING_STAGE_FIELDS = [
  ...PLANNING_IDENTITY_FIELDS,
  'order', 'title', 'purpose', 'dramaticQuestion',
]
const PLANNING_TASK_FIELDS = [
  ...PLANNING_IDENTITY_FIELDS,
  'order', 'task', 'completionEvidence',
]

function planningArray(value, label, mapper) {
  if (!Array.isArray(value)) {
    throw new TypeError(`Expected Planning ${label} array`)
  }
  return value.map(mapper)
}

function planningDraftContent(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('Expected Planning draft content')
  }
  return {
    ...pickDefined(value, ['activeStoryBlockRef']),
    volumes: planningArray(
      value.volumes,
      'volumes',
      item => pickDefined(item, PLANNING_VOLUME_FIELDS),
    ),
    plots: planningArray(
      value.plots,
      'plots',
      item => pickDefined(item, PLANNING_PLOT_FIELDS),
    ),
    storyBlocks: planningArray(value.storyBlocks, 'storyBlocks', block => ({
      ...pickDefined(block, PLANNING_BLOCK_FIELDS),
      stages: planningArray(block?.stages, 'stages', stage => ({
        ...pickDefined(stage, PLANNING_STAGE_FIELDS),
        sceneTasks: planningArray(
          stage?.sceneTasks,
          'sceneTasks',
          task => pickDefined(task, PLANNING_TASK_FIELDS),
        ),
      })),
    })),
  }
}

function bibleCloneSource(value = {}) {
  const hasDraftId = value?.sourceDraftId !== undefined && value.sourceDraftId !== null
  const hasRevision = value?.sourceRevision !== undefined && value.sourceRevision !== null
  if (hasDraftId === hasRevision) {
    throw new TypeError('Expected exactly one Bible clone source')
  }
  return hasDraftId
    ? { sourceDraftId: value.sourceDraftId }
    : { sourceRevision: positiveRevision(value.sourceRevision) }
}

function positiveRevision(value) {
  const revision = Number(value)
  if (!Number.isInteger(revision) || revision < 1) {
    throw new TypeError('Expected a positive contract revision')
  }
  return revision
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
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== undefined && item !== null && item !== '') {
          query.append(key, item)
        }
      }
    } else if (value !== undefined && value !== null && value !== '') {
      query.set(key, value)
    }
  }
  const result = query.toString()
  return result ? `?${result}` : ''
}

export const api = {
  health: () => get('/health'),

  projects: {
    listActive: () => get('/projects'),
    listArchived: () => get('/projects/archived'),
    create: ({ title }) => post('/projects', { title }),
    get: projectId => get(`/projects/${segment(projectId)}`),
    preparation: projectId => get(`/projects/${segment(projectId)}/preparation`),
    rename: (projectId, { title }) => put(
      `/projects/${segment(projectId)}`,
      { title },
    ),
    archive: (projectId, expectedLifecycleRevision) => post(
      `/projects/${segment(projectId)}/archive`,
      { expectedLifecycleRevision },
    ),
    restore: (projectId, expectedLifecycleRevision) => post(
      `/projects/${segment(projectId)}/restore`,
      { expectedLifecycleRevision },
    ),
    permanentlyDelete: (projectId, expectedLifecycleRevision) => del(
      `/projects/${segment(projectId)}`,
      { expectedLifecycleRevision },
    ),
  },

  seeds: {
    list: projectId => get(`/projects/${segment(projectId)}/seeds`),
    create: (projectId, payload, options = {}) => post(
      `/projects/${segment(projectId)}/seeds`,
      pickDefined({
        payload: seedPayload(payload),
        provenance: options.provenance
          ? seedProvenance(options.provenance)
          : undefined,
        idempotencyKey: options.idempotencyKey,
      }, ['payload', 'provenance', 'idempotencyKey']),
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
    archive: (projectId, seedId, data) => post(
      `/projects/${segment(projectId)}/seeds/${segment(seedId)}/archive`,
      pickDefined(data, ['expectedSeedRevision', 'expectedSelectionRevision']),
    ),
    restore: (projectId, seedId, data) => post(
      `/projects/${segment(projectId)}/seeds/${segment(seedId)}/restore`,
      pickDefined(data, ['expectedSeedRevision', 'expectedSelectionRevision']),
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
    inspiration: (projectId, data) => post(
      `/projects/${segment(projectId)}/seed-inspiration`,
      {
        transcript: Array.isArray(data.transcript)
          ? data.transcript.map(turn => pickDefined(turn, ['role', 'content']))
          : data.transcript,
        snapshotIds: Array.isArray(data.snapshotIds)
          ? [...data.snapshotIds]
          : data.snapshotIds,
        analysisId: data.analysisId,
        idempotencyKey: data.idempotencyKey,
      },
    ),
  },

  marketSources: {
    list: () => get('/market-sources'),
    get: sourceId => get(`/market-sources/${segment(sourceId)}`),
    snapshots: (sourceId) => get(
      `/market-sources/${segment(sourceId)}/snapshots`,
    ),
    snapshot: (sourceId, snapshotId) => get(
      `/market-sources/${segment(sourceId)}/snapshots/${segment(snapshotId)}`,
    ),
    manualImport: (sourceId, data) => post(
      `/market-sources/${segment(sourceId)}/manual-import`,
      {
        idempotencyKey: data.idempotencyKey,
        snapshot: data.snapshot,
      },
    ),
    refresh: (sourceId, idempotencyKey) => post(
      `/market-sources/${segment(sourceId)}/refresh`,
      { idempotencyKey },
    ),
    schedule: (sourceId, data) => put(
      `/market-sources/${segment(sourceId)}/schedule`,
      pickDefined(data, [
        'expectedRevision', 'enabled', 'intervalMinutes', 'idempotencyKey',
      ]),
    ),
  },

  marketAnalyses: {
    create: (projectId, data) => post(
      `/projects/${segment(projectId)}/market-analyses`,
      {
        snapshotIds: Array.isArray(data.snapshotIds)
          ? [...data.snapshotIds]
          : data.snapshotIds,
        idempotencyKey: data.idempotencyKey,
      },
    ),
    get: (projectId, analysisId) => get(
      `/projects/${segment(projectId)}/market-analyses/${segment(analysisId)}`,
    ),
  },

  providers: {
    list: () => get('/providers'),
    create: data => post('/providers', pickDefined(data, PROVIDER_CREATE_FIELDS)),
    update: (providerId, data) => put(
      `/providers/${segment(providerId)}`,
      pickDefined(data, PROVIDER_UPDATE_FIELDS),
    ),
    delete: (providerId, data) => del(
      `/providers/${segment(providerId)}`,
      pickDefined(data, ['expectedRevision', 'idempotencyKey']),
    ),
    clearApiKey: (providerId, data) => post(
      `/providers/${segment(providerId)}/clear-api-key`,
      pickDefined(data, ['expectedRevision', 'idempotencyKey']),
    ),
    testConnection: providerId => post(
      `/providers/${segment(providerId)}/test-connection`,
    ),
  },

  applicationSettings: {
    get: () => get('/settings/application'),
    updateDefaultModel: data => put('/settings/application/default-model', {
      expectedRevision: data.expectedRevision,
      fallbackProviderId: data.fallbackProviderId ?? null,
    }),
    diagnostics: () => get('/settings/application/diagnostics'),
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
    recoverable: projectId => get(
      `/projects/${segment(projectId)}/story-engine-batches/recoverable`,
    ),
    get: (projectId, batchId) => get(
      `/projects/${segment(projectId)}/story-engine-batches/${segment(batchId)}`,
    ),
    reconcile: (projectId, batchId) => post(
      `/projects/${segment(projectId)}/story-engine-batches/${segment(batchId)}/reconcile`,
    ),
  },

  styleTrials: {
    generate: (projectId, data) => post(
      `/projects/${segment(projectId)}/style-trials`,
      pickDefined(data, STYLE_TRIAL_FIELDS),
    ),
  },

  assets: {
    inventory: () => get('/assets/inventory'),
    styleTemplates: {
      list: (params = {}) => get(`/assets/style-templates${queryString({
        search: params.search,
        genre: params.genre,
        stage: params.stage,
        status: params.status,
      })}`),
      get: revisionId => get(`/assets/style-templates/${segment(revisionId)}`),
    },
    experienceCards: {
      list: (params = {}) => get(`/assets/experience-cards${queryString({
        search: params.search,
        category: params.category,
        genre: params.genre,
        stage: params.stage,
        status: params.status,
      })}`),
      get: revisionId => get(`/assets/experience-cards/${segment(revisionId)}`),
    },
    recommendations: (projectId, data) => post(
      `/projects/${segment(projectId)}/asset-recommendations`,
      pickDefined(data, ASSET_RECOMMENDATION_FIELDS),
    ),
  },

  corpus: {
    discovery: (params = {}) => get(`/corpus/discovery${queryString({
      cursor: boundedCursor(params.cursor),
      limit: boundedInteger(params.limit, { min: 1, max: 200 }),
    })}`),
      imports: {
        create: data => post('/corpus/imports', pickDefined({
          idempotencyKey: data.idempotencyKey,
          relativePath: relativeCorpusPath(data.relativePath),
          sourceId: data.sourceId,
          createDistinctSource: data.createDistinctSource,
          displayName: data.displayName,
          referenceTags: data.referenceTags,
          notes: data.notes,
        }, [
          'idempotencyKey', 'relativePath', 'sourceId', 'createDistinctSource',
          'displayName', 'referenceTags', 'notes',
        ])),
        get: importId => get(`/corpus/imports/${segment(importId)}`),
      },
      sources: {
        list: (params = {}) => get(`/corpus/sources${queryString({
          search: params.search,
          state: params.state,
        })}`),
        get: (sourceId, params = {}) => get(
          `/corpus/sources/${segment(sourceId)}${queryString({
            previewChars: boundedInteger(params.previewChars, { min: 1, max: 1200 }),
          })}`,
        ),
        versions: (sourceId, params = {}) => get(
          `/corpus/sources/${segment(sourceId)}/versions${queryString({
            cursor: boundedInteger(params.cursor, { min: 1, max: Number.MAX_SAFE_INTEGER }),
            limit: boundedInteger(params.limit, { min: 1, max: 100 }),
          })}`,
        ),
        archive: (sourceId, expectedRevision) => post(
          `/corpus/sources/${segment(sourceId)}/archive`,
          { expectedRevision },
        ),
        restore: (sourceId, expectedRevision) => post(
          `/corpus/sources/${segment(sourceId)}/restore`,
          { expectedRevision },
        ),
        permanentlyDelete: (sourceId, expectedRevision, confirmPermanentDelete) => del(
          `/corpus/sources/${segment(sourceId)}`,
          { expectedRevision, confirmPermanentDelete },
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
        beforeRevision: boundedInteger(params.beforeRevision, {
          min: 1,
          max: Number.MAX_SAFE_INTEGER,
        }),
      })}`,
    ),
    clone: (projectId, sourceRevision) => post(
      `/projects/${segment(projectId)}/contracts/${positiveRevision(sourceRevision)}/clone`,
    ),
  },

  bible: {
    head: projectId => get(`/projects/${segment(projectId)}/bible/head`),
    draft: {
      get: projectId => get(`/projects/${segment(projectId)}/bible/draft`),
      save: (projectId, data) => put(`/projects/${segment(projectId)}/bible/draft`, {
        expectedDraftVersion: data.expectedDraftVersion,
        draft: biblePayload(data.draft),
      }),
      clone: (projectId, source) => post(
        `/projects/${segment(projectId)}/bible/draft/clone`,
        bibleCloneSource(source),
      ),
    },
    confirm: (projectId, data) => post(`/projects/${segment(projectId)}/bible/confirm`, {
      idempotencyKey: data.idempotencyKey,
      expectedDraftVersion: data.expectedDraftVersion,
      expectedHeadRevision: data.expectedHeadRevision,
    }),
    generate: (projectId, data) => post(
      `/projects/${segment(projectId)}/bible/generate`,
      pickDefined(data, [
        'authorInstructions', 'expectedDraftVersion', 'expectedHeadRevision',
        'idempotencyKey',
      ]),
      BIBLE_GENERATION_TIMEOUT,
    ),
    generationAttempt: (projectId, attemptId) => get(
      `/projects/${segment(projectId)}/bible/generation-attempts/${segment(attemptId)}`,
    ),
    history: (projectId, params = {}) => get(
      `/projects/${segment(projectId)}/bible/history${queryString({
        limit: boundedInteger(params.limit, { min: 1, max: 100 }),
        beforeRevision: boundedInteger(params.beforeRevision, {
          min: 1,
          max: Number.MAX_SAFE_INTEGER,
        }),
      })}`,
    ),
    historyDetail: (projectId, revision) => get(
      `/projects/${segment(projectId)}/bible/history/${positiveRevision(revision)}`,
    ),
  },

  writerCore: {
    state: projectId => get(`/projects/${segment(projectId)}/writer-core/state`),
  },

  planning: {
    get: projectId => get(`/projects/${segment(projectId)}/planning`),
    history: projectId => get(`/projects/${segment(projectId)}/planning/history`),
    createDraft: (projectId, data) => post(
      `/projects/${segment(projectId)}/planning/drafts`,
      {
        idempotencyKey: data.idempotencyKey,
      },
    ),
    saveDraft: (projectId, draftId, data) => put(
      `/projects/${segment(projectId)}/planning/drafts/${segment(draftId)}`,
      {
        expectedDraftRevision: data.expectedDraftRevision,
        expectedDraftHash: data.expectedDraftHash,
        content: planningDraftContent(data.content),
        idempotencyKey: data.idempotencyKey,
      },
    ),
    confirmDraft: (projectId, draftId, data) => post(
      `/projects/${segment(projectId)}/planning/drafts/${segment(draftId)}/confirm`,
      {
        expectedDraftRevision: data.expectedDraftRevision,
        expectedDraftHash: data.expectedDraftHash,
        idempotencyKey: data.idempotencyKey,
      },
    ),
  },

  chapterSessions: {
    current: projectId => get(`/projects/${segment(projectId)}/chapter-sessions/current`),
    create: (projectId, data) => post(`/projects/${segment(projectId)}/chapter-sessions`, {
      expectedStoryBlockRevision: data.expectedStoryBlockRevision,
      expectedCanonRevision: data.expectedCanonRevision,
    }),
    saveWorkingDraft: (projectId, sessionId, data) => put(
      `/projects/${segment(projectId)}/chapter-sessions/${segment(sessionId)}/working-draft`,
      {
        expectedRevision: data.expectedRevision,
        content: data.content,
      },
    ),
    generateWorkingDraft: (projectId, sessionId, data) => post(
      `/projects/${segment(projectId)}/chapter-sessions/${segment(sessionId)}/generate-working-draft`,
      {
        expectedWorkingDraftRevision: data.expectedWorkingDraftRevision,
        authorInstruction: data.authorInstruction,
      },
      CHAPTER_DRAFT_GENERATION_TIMEOUT,
    ),
    saveCandidate: (projectId, sessionId, data) => post(
      `/projects/${segment(projectId)}/chapter-sessions/${segment(sessionId)}/candidates`,
      { expectedWorkingDraftRevision: data.expectedWorkingDraftRevision },
    ),
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
