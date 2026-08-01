/** Writer Core product API client. */

import { ApiError, parseApiError } from './api-error.js'

const BASE = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api').replace(/\/+$/, '')
const DEFAULT_TIMEOUT = 30000
const DRAFT_OPERATION_TIMEOUT = 1_200_000
const BIBLE_GENERATION_TIMEOUT = 210_000
const PLANNING_GENERATION_TIMEOUT = 210_000
const CHAPTER_OUTLINE_GENERATION_TIMEOUT = 210_000

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

function planningActualProgressItem(value) {
  const invalid = () => {
    throw new TypeError('Invalid Planning actual progress response')
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()

  const revisionNumber = value.revisionNumber
  const subjectKey = value.subjectKey
  const entityId = value.entityId
  const fieldPath = value.fieldPath
  const publicValue = planningProgressValue(value.value)
  const contentHash = value.contentHash
  if (
    !Number.isInteger(revisionNumber)
    || revisionNumber <= 0
    || !planningProgressText(subjectKey)
    || !(entityId === null || planningProgressText(entityId))
    || !planningProgressText(fieldPath)
    || !fieldPath.startsWith('plot.')
    || fieldPath.slice('plot.'.length).length === 0
    || publicValue === INVALID_PLANNING_PROGRESS_VALUE
    || typeof contentHash !== 'string'
    || !/^[a-f0-9]{64}$/u.test(contentHash)
  ) invalid()

  return {
    revisionNumber,
    subjectKey,
    entityId,
    fieldPath,
    value: publicValue,
    contentHash,
  }
}

function planningProgressText(value) {
  return (
    typeof value === 'string'
    && value.length > 0
    && value === value.trim()
    && hasValidUnicode(value)
  )
}

const INVALID_PLANNING_PROGRESS_VALUE = Symbol('invalid-planning-progress-value')

function planningProgressValue(value, ancestors = new WeakSet()) {
  if (typeof value === 'string') return value
  if (value === null || typeof value === 'boolean') return value
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (!value || typeof value !== 'object' || ancestors.has(value)) {
    return INVALID_PLANNING_PROGRESS_VALUE
  }
  ancestors.add(value)
  try {
    if (Array.isArray(value)) {
      const copied = value.map(item => planningProgressValue(item, ancestors))
      return copied.includes(INVALID_PLANNING_PROGRESS_VALUE)
        ? INVALID_PLANNING_PROGRESS_VALUE
        : copied
    }
    if (Object.getPrototypeOf(value) !== Object.prototype) {
      return INVALID_PLANNING_PROGRESS_VALUE
    }
    const copied = {}
    for (const key of Object.keys(value)) {
      const item = planningProgressValue(value[key], ancestors)
      if (item === INVALID_PLANNING_PROGRESS_VALUE) {
        return INVALID_PLANNING_PROGRESS_VALUE
      }
      Object.defineProperty(copied, key, {
        value: item,
        enumerable: true,
        configurable: true,
        writable: true,
      })
    }
    return copied
  } catch {
    return INVALID_PLANNING_PROGRESS_VALUE
  } finally {
    ancestors.delete(value)
  }
}

function planningStateResponse(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError('Invalid Planning actual progress response')
  }
  const actualProgress = value.actualProgress === undefined
    ? []
    : value.actualProgress
  if (!Array.isArray(actualProgress)) {
    throw new TypeError('Invalid Planning actual progress response')
  }
  return {
    ...value,
    actualProgress: actualProgress.map(planningActualProgressItem),
  }
}

const CHAPTER_OUTLINE_PLANNING_IDENTITY_FIELDS = [
  'id', 'revision', 'contentHash', 'lifecycle',
]
const CHAPTER_OUTLINE_PLANNING_VOLUME_FIELDS = [
  ...CHAPTER_OUTLINE_PLANNING_IDENTITY_FIELDS,
  'order', 'title', 'coreChange', 'mainPressure', 'ensembleFocus',
  'forbiddenEvents',
]
const CHAPTER_OUTLINE_PLANNING_PLOT_FIELDS = [
  ...CHAPTER_OUTLINE_PLANNING_IDENTITY_FIELDS,
  'order', 'title', 'plotType', 'storyQuestion', 'futureDirection',
  'expectedPayoff', 'relatedCharacters',
]
const CHAPTER_OUTLINE_PLANNING_BLOCK_FIELDS = [
  ...CHAPTER_OUTLINE_PLANNING_IDENTITY_FIELDS,
  'volumeId', 'plotIds', 'order', 'title', 'entrySituation', 'blockGoal',
  'mainPressure', 'expectedChange', 'openQuestions', 'involvedCharacters',
]
const CHAPTER_OUTLINE_PLANNING_STAGE_FIELDS = [
  ...CHAPTER_OUTLINE_PLANNING_IDENTITY_FIELDS,
  'storyBlockId', 'order', 'title', 'purpose', 'dramaticQuestion',
]
const CHAPTER_OUTLINE_PLANNING_TASK_FIELDS = [
  ...CHAPTER_OUTLINE_PLANNING_IDENTITY_FIELDS,
  'stageId', 'order', 'task', 'completionEvidence',
]
const CHAPTER_OUTLINE_PLANNING_NUMBER_FIELDS = new Set([
  'revision', 'order',
])

function chapterOutlinePlanningObject(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`Expected ChapterOutline Planning ${label}`)
  }
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError(`Expected ChapterOutline Planning ${label}`)
  }
  return value
}

function chapterOutlinePlanningNode(
  value,
  fields,
  arrayFields = [],
  label = 'node',
) {
  const source = chapterOutlinePlanningObject(value, label)
  const stringArrayFields = new Set(arrayFields)
  const node = {}
  for (const field of fields) {
    if (!Object.hasOwn(source, field)) {
      throw new TypeError(`Invalid ChapterOutline Planning ${label}`)
    }
    const fieldValue = source[field]
    if (stringArrayFields.has(field)) {
      if (
        !Array.isArray(fieldValue)
        || fieldValue.some(item => typeof item !== 'string')
      ) {
        throw new TypeError(`Invalid ChapterOutline Planning ${label}`)
      }
      node[field] = [...fieldValue]
      continue
    }
    const scalarIsValid = CHAPTER_OUTLINE_PLANNING_NUMBER_FIELDS.has(field)
      ? Number.isInteger(fieldValue)
      : typeof fieldValue === 'string'
    if (!scalarIsValid) {
      throw new TypeError(`Invalid ChapterOutline Planning ${label}`)
    }
    node[field] = fieldValue
  }
  return node
}

function chapterOutlinePlanningCollection(source, field, mapper) {
  if (!Object.hasOwn(source, field)) {
    throw new TypeError('Invalid ChapterOutline Planning collection')
  }
  return planningArray(source[field], field, mapper)
}

function chapterOutlinePlanningContent(value) {
  const source = chapterOutlinePlanningObject(value, 'content')
  const rootFields = [
    'schemaVersion',
    'activeStoryBlockId',
    'contentHash',
    'volumes',
    'plots',
    'storyBlocks',
  ]
  if (
    rootFields.some(field => !Object.hasOwn(source, field))
    || typeof source.schemaVersion !== 'string'
    || (
      source.activeStoryBlockId !== null
      && typeof source.activeStoryBlockId !== 'string'
    )
    || typeof source.contentHash !== 'string'
  ) {
    throw new TypeError('Invalid ChapterOutline Planning content')
  }
  return {
    schemaVersion: source.schemaVersion,
    activeStoryBlockId: source.activeStoryBlockId,
    volumes: planningArray(source.volumes, 'volumes', item => (
      chapterOutlinePlanningNode(
        item,
        CHAPTER_OUTLINE_PLANNING_VOLUME_FIELDS,
        ['ensembleFocus', 'forbiddenEvents'],
        'Volume',
      )
    )),
    plots: planningArray(source.plots, 'plots', item => (
      chapterOutlinePlanningNode(
        item,
        CHAPTER_OUTLINE_PLANNING_PLOT_FIELDS,
        ['relatedCharacters'],
        'Plot',
      )
    )),
    storyBlocks: planningArray(source.storyBlocks, 'storyBlocks', block => ({
      ...chapterOutlinePlanningNode(
        block,
        CHAPTER_OUTLINE_PLANNING_BLOCK_FIELDS,
        ['plotIds', 'openQuestions', 'involvedCharacters'],
        'StoryBlock',
      ),
      stages: chapterOutlinePlanningCollection(block, 'stages', stage => ({
        ...chapterOutlinePlanningNode(
          stage,
          CHAPTER_OUTLINE_PLANNING_STAGE_FIELDS,
          [],
          'Stage',
        ),
        sceneTasks: chapterOutlinePlanningCollection(
          stage,
          'sceneTasks',
          task => chapterOutlinePlanningNode(
            task,
            CHAPTER_OUTLINE_PLANNING_TASK_FIELDS,
            [],
            'SceneTask',
          ),
        ),
      })),
    })),
    contentHash: source.contentHash,
  }
}

const PLANNING_OPERATION_STATUSES = new Set([
  'pending',
  'succeeded',
  'failed',
  'superseded',
])
const PLANNING_FAILURE_CODES = new Set([
  'PlanningGenerationCancelled',
  'PlanningGenerationFailed',
  'PlanningProviderFailed',
  'PlanningProviderResultInvalid',
])
const PRIVATE_OPERATION_TEXT = /(?:api[\s_-]*key|base[\s_-]*url|access[\s_-]*token|bearer[\s_-]*token|token|password|dsn)\s*[:=]\s*\S+|(?:source[\s_.-]*document[\s_.-]*text|raw[\s_.-]*source(?:[\s_.-]*(?:text|content|payload))?|corpus(?:[\s_.-]*(?:text|content|payload|fragment))?)\s*[:=]\s*\S+|\bauthorization\s*:\s*[A-Za-z][A-Za-z0-9_-]*\s+\S+|\bauthorization\s*:?\s*bearer\s+\S+|\bbearer\s+[A-Za-z0-9][A-Za-z0-9._~+/=-]{7,}|(?:mysql|postgres(?:ql)?|mariadb):\/\/\S+/i
const API_KEY_SHAPED_TEXT = /(?:^|[^A-Za-z0-9])(?:(?:sk|rk|pk)[-_][A-Za-z0-9._~+/=-]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})(?:$|[^A-Za-z0-9])/i
const INVALID_PERCENT_ESCAPE = /%(?![0-9A-Fa-f]{2})/
const VALID_PERCENT_ESCAPE = /%[0-9A-Fa-f]{2}/
const PRIVATE_OPERATION_ID_TEXT = /(?:authorization|api[-_]?key|credential|password|secret|token|dsn)/i
const SENSITIVE_PLANNING_KEY_SHAPE = /(?:^|[._:-])(?:(?:sk|rk|pk)[_-][A-Za-z0-9]|gh[pousr]_[A-Za-z0-9]|github_pat_[A-Za-z0-9])/i
const AWS_ACCESS_KEY_SHAPE = /(?:^|[._:-])(?:AKIA|ASIA)[A-Z0-9]{16}(?:$|[._:-])/i
const GOOGLE_API_KEY_SHAPE = /(?:^|[._:-])AIza[A-Za-z0-9_-]{20,}(?:$|[._:-])/
const SENSITIVE_PLANNING_KEY_MARKERS = [
  'authorization',
  'bearer',
  'apikey',
  'accesstoken',
  'token',
  'secret',
  'password',
  'passwd',
  'credential',
  'dsn',
]

function hasValidUnicode(value) {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1)
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false
      index += 1
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return false
    }
  }
  return true
}

function planningTextVariants(value) {
  if (
    typeof value !== 'string'
    || !value
    || value !== value.trim()
    || value.length > 512
    || !hasValidUnicode(value)
  ) {
    return null
  }
  const variants = new Set([value])
  let frontier = new Set([value])
  let stopped = false
  try {
    for (let round = 0; round < 2; round += 1) {
      if ([...frontier].some(item => INVALID_PERCENT_ESCAPE.test(item))) {
        return null
      }
      const decoded = new Set()
      for (const item of frontier) {
        decoded.add(decodeURIComponent(item))
        decoded.add(decodeURIComponent(item.replace(/\+/g, ' ')))
      }
      if ([...decoded].some(item => item.length > 512 || !hasValidUnicode(item))) {
        return null
      }
      const next = new Set([...decoded].filter(item => !variants.has(item)))
      for (const item of decoded) variants.add(item)
      if (next.size === 0) {
        stopped = true
        break
      }
      frontier = next
    }
  } catch {
    return null
  }
  if (!stopped && [...frontier].some(item => VALID_PERCENT_ESCAPE.test(item))) {
    return null
  }
  if ([...variants].some(item => INVALID_PERCENT_ESCAPE.test(item))) {
    return null
  }
  return variants
}

function planningVariantHasCredentialUrl(value) {
  const hasAuthority = (
    /^[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(value)
    || value.startsWith('//')
  )
  if (!hasAuthority) return false
  try {
    const parsed = new URL(value.startsWith('//') ? `http:${value}` : value)
    return Boolean(parsed.username || parsed.password)
  } catch {
    return true
  }
}

function publicPlanningLabel(value) {
  const variants = planningTextVariants(value)
  if (!variants) return null
  for (const variant of variants) {
    if (
      /[\u0000-\u001f\u007f]/.test(variant)
      || PRIVATE_OPERATION_TEXT.test(variant)
      || API_KEY_SHAPED_TEXT.test(variant)
      || planningVariantHasCredentialUrl(variant)
    ) {
      return null
    }
  }
  return value
}

function planningOperationId(value) {
  if (
    typeof value !== 'string'
    || !value
    || value !== value.trim()
    || value.length > 128
    || !hasValidUnicode(value)
    || !/^[A-Za-z0-9][A-Za-z0-9._~-]*$/.test(value)
    || PRIVATE_OPERATION_ID_TEXT.test(value)
    || API_KEY_SHAPED_TEXT.test(value)
  ) {
    return null
  }
  return value
}

export function isSafePlanningIdempotencyKey(value) {
  if (
    typeof value !== 'string'
    || value.length < 1
    || value.length > 64
    || !/^[A-Za-z0-9][A-Za-z0-9._:-]*$/.test(value)
  ) {
    return false
  }
  const normalized = value.replace(/[._:-]+/g, '').toLowerCase()
  return (
    !SENSITIVE_PLANNING_KEY_MARKERS.some(marker => normalized.includes(marker))
    && !SENSITIVE_PLANNING_KEY_SHAPE.test(value)
    && !AWS_ACCESS_KEY_SHAPE.test(value)
    && !GOOGLE_API_KEY_SHAPE.test(value)
  )
}

function planningIdempotencyKey(value) {
  return isSafePlanningIdempotencyKey(value) ? value : null
}

function planningOperationResponse(value, expectedOperationId) {
  const invalid = () => {
    throw new TypeError('Invalid Planning operation response')
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()

  const operationId = planningOperationId(value.operationId)
  if (!operationId || (expectedOperationId && operationId !== expectedOperationId)) {
    invalid()
  }
  const status = value.status
  const failureCode = value.failureCode
  const loaded = value.loaded
  const loadedDraftRevision = value.loadedDraftRevision
  const revisionIsPositive = (
    Number.isInteger(loadedDraftRevision) && loadedDraftRevision > 0
  )
  const commonValid = (
    PLANNING_OPERATION_STATUSES.has(status)
    && typeof loaded === 'boolean'
    && (
      failureCode === null
      || (
        typeof failureCode === 'string'
        && PLANNING_FAILURE_CODES.has(failureCode)
      )
    )
    && (loadedDraftRevision === null || revisionIsPositive)
  )
  const stateValid = commonValid && (
    (
      status === 'pending'
      && failureCode === null
      && loaded === false
      && loadedDraftRevision === null
    )
    || (
      status === 'succeeded'
      && failureCode === null
      && (
        (loaded === false && loadedDraftRevision === null)
        || (loaded === true && revisionIsPositive)
      )
    )
    || (
      status === 'failed'
      && PLANNING_FAILURE_CODES.has(failureCode)
      && loaded === false
      && loadedDraftRevision === null
    )
    || (
      status === 'superseded'
      && failureCode === null
      && loaded === false
      && loadedDraftRevision === null
    )
  )
  if (!stateValid) invalid()

  const providerId = publicPlanningLabel(value.model?.providerId)
  const modelName = publicPlanningLabel(value.model?.modelName)
  const model = providerId && modelName
    ? { providerId, modelName }
    : { providerId: 'unavailable', modelName: 'unavailable' }
  return {
    operationId,
    status,
    failureCode,
    model,
    loaded,
    loadedDraftRevision,
  }
}

const CHAPTER_OUTLINE_FAILURE_CODES = new Set([
  'ChapterOutlineGenerationCancelled',
  'ChapterOutlineProviderFailed',
  'ChapterOutlineProviderResultInvalid',
])

function positiveChapterNumber(value) {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
    throw new TypeError('Expected a positive chapter number')
  }
  return value
}

function chapterOutlineOpaqueId(value, label) {
  const result = planningOperationId(value)
  if (!result) throw new TypeError(`Invalid Chapter Outline ${label}`)
  return result
}

function chapterOutlineIdempotencyKey(value) {
  if (!isSafePlanningIdempotencyKey(value)) {
    throw new TypeError('Invalid Chapter Outline idempotency key')
  }
  return value
}

const CHAPTER_OUTLINE_CONTENT_STRING_ARRAY_FIELDS = [
  'expectedCharacters',
  'continuation',
  'plannedTasks',
  'scenes',
  'forbiddenEarlyEvents',
]
const CHAPTER_OUTLINE_CONTENT_FIELDS = [
  'schemaVersion',
  'volumeRef',
  'storyBlockRef',
  'stageRefs',
  'sceneTaskRefs',
  'chapterGoal',
  ...CHAPTER_OUTLINE_CONTENT_STRING_ARRAY_FIELDS,
]

function chapterOutlineResponseObject(value, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`Invalid ChapterOutline ${label}`)
  }
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) {
    throw new TypeError(`Invalid ChapterOutline ${label}`)
  }
  return value
}

function chapterOutlineNodeRef(value) {
  const source = chapterOutlineResponseObject(value, 'node reference')
  if (
    !Object.hasOwn(source, 'id')
    || !Object.hasOwn(source, 'revision')
    || !Object.hasOwn(source, 'contentHash')
    || typeof source.id !== 'string'
    || !Number.isInteger(source.revision)
    || typeof source.contentHash !== 'string'
  ) {
    throw new TypeError('Invalid ChapterOutline node reference')
  }
  return {
    id: source.id,
    revision: source.revision,
    contentHash: source.contentHash,
  }
}

function chapterOutlineContentProjection(value, { requireAll }) {
  const source = chapterOutlineResponseObject(value, 'content')
  if (requireAll) {
    chapterOutlineRequireOwnFields(
      source,
      CHAPTER_OUTLINE_CONTENT_FIELDS,
      'content',
    )
  }
  const content = {}
  for (const field of ['schemaVersion', 'chapterGoal']) {
    if (!Object.hasOwn(source, field)) continue
    if (typeof source[field] !== 'string') {
      throw new TypeError('Invalid ChapterOutline content')
    }
    content[field] = source[field]
  }
  for (const field of ['volumeRef', 'storyBlockRef']) {
    if (!Object.hasOwn(source, field)) continue
    content[field] = source[field] === null
      ? null
      : chapterOutlineNodeRef(source[field])
  }
  for (const field of ['stageRefs', 'sceneTaskRefs']) {
    if (!Object.hasOwn(source, field)) continue
    if (!Array.isArray(source[field])) {
      throw new TypeError('Invalid ChapterOutline content')
    }
    content[field] = source[field].map(chapterOutlineNodeRef)
  }
  for (const field of CHAPTER_OUTLINE_CONTENT_STRING_ARRAY_FIELDS) {
    if (!Object.hasOwn(source, field)) continue
    if (
      !Array.isArray(source[field])
      || source[field].some(item => typeof item !== 'string')
    ) {
      throw new TypeError('Invalid ChapterOutline content')
    }
    content[field] = [...source[field]]
  }
  return content
}

function chapterOutlineWriteContent(value) {
  if (value == null) return {}
  return chapterOutlineContentProjection(value, { requireAll: false })
}

function chapterOutlineResponseContent(value) {
  return chapterOutlineContentProjection(value, { requireAll: true })
}

function chapterOutlinePlanningAuthority(value) {
  if (value == null) return null
  const source = chapterOutlinePlanningObject(value, 'authority')
  if (
    !Object.hasOwn(source, 'planningRevisionId')
    || !Object.hasOwn(source, 'revision')
    || !Object.hasOwn(source, 'contentHash')
    || !Object.hasOwn(source, 'content')
    || typeof source.planningRevisionId !== 'string'
    || !Number.isInteger(source.revision)
    || typeof source.contentHash !== 'string'
  ) {
    throw new TypeError('Invalid ChapterOutline Planning authority')
  }
  return {
    planningRevisionId: source.planningRevisionId,
    revision: source.revision,
    contentHash: source.contentHash,
    content: source.content === null
      ? null
      : chapterOutlinePlanningContent(source.content),
  }
}

function chapterOutlineProjectionAuthority(value) {
  if (value == null) return null
  const source = chapterOutlineResponseObject(value, 'projection authority')
  if (
    !Object.hasOwn(source, 'canonRevision')
    || !Object.hasOwn(source, 'projectionRevision')
    || !Object.hasOwn(source, 'contentHash')
    || !Object.hasOwn(source, 'synchronized')
    || !Number.isInteger(source.canonRevision)
    || !Number.isInteger(source.projectionRevision)
    || typeof source.contentHash !== 'string'
    || typeof source.synchronized !== 'boolean'
  ) {
    throw new TypeError('Invalid ChapterOutline projection authority')
  }
  return {
    canonRevision: source.canonRevision,
    projectionRevision: source.projectionRevision,
    contentHash: source.contentHash,
    synchronized: source.synchronized,
  }
}

function chapterOutlineRequireOwnFields(source, fields, label) {
  if (fields.some(field => !Object.hasOwn(source, field))) {
    throw new TypeError(`Invalid ChapterOutline ${label}`)
  }
}

function chapterOutlineResponseScalars(
  source,
  {
    strings = [],
    integers = [],
    booleans = [],
  },
  label,
) {
  chapterOutlineRequireOwnFields(
    source,
    [...strings, ...integers, ...booleans],
    label,
  )
  if (
    strings.some(field => typeof source[field] !== 'string')
    || integers.some(field => !Number.isInteger(source[field]))
    || booleans.some(field => typeof source[field] !== 'boolean')
  ) {
    throw new TypeError(`Invalid ChapterOutline ${label}`)
  }
}

function chapterOutlineBasis(value) {
  const source = chapterOutlineResponseObject(value, 'basis')
  chapterOutlineRequireOwnFields(
    source,
    ['planningAuthority', 'canonProjectionAuthority'],
    'basis',
  )
  const planningAuthority = chapterOutlinePlanningAuthority(
    source.planningAuthority,
  )
  const canonProjectionAuthority = chapterOutlineProjectionAuthority(
    source.canonProjectionAuthority,
  )
  if (planningAuthority === null || canonProjectionAuthority === null) {
    throw new TypeError('Invalid ChapterOutline basis')
  }
  return {
    planningAuthority,
    canonProjectionAuthority,
  }
}

function chapterOutlineDraftResponse(value) {
  if (value == null) return null
  const source = chapterOutlineResponseObject(value, 'draft')
  chapterOutlineResponseScalars(
    source,
    {
      strings: ['projectId', 'draftId', 'contentHash', 'status'],
      integers: [
        'chapterNumber',
        'baseHeadRevision',
        'draftRevision',
      ],
    },
    'draft',
  )
  chapterOutlineRequireOwnFields(source, ['content', 'basis'], 'draft')
  return {
    projectId: source.projectId,
    chapterNumber: source.chapterNumber,
    draftId: source.draftId,
    baseHeadRevision: source.baseHeadRevision,
    draftRevision: source.draftRevision,
    contentHash: source.contentHash,
    content: chapterOutlineResponseContent(source.content),
    basis: chapterOutlineBasis(source.basis),
    status: source.status,
  }
}

function chapterOutlineRevisionResponse(
  value,
  { includeDisplay = true } = {},
) {
  if (value == null) return null
  const source = chapterOutlineResponseObject(value, 'revision')
  const stringFields = [
    'projectId',
    'outlineRevisionId',
    'contentHash',
  ]
  if (includeDisplay) stringFields.push('status', 'reason')
  chapterOutlineResponseScalars(
    source,
    {
      strings: stringFields,
      integers: ['chapterNumber', 'revision', 'parentRevision'],
    },
    'revision',
  )
  chapterOutlineRequireOwnFields(source, ['content', 'basis'], 'revision')
  const result = {
    projectId: source.projectId,
    chapterNumber: source.chapterNumber,
    outlineRevisionId: source.outlineRevisionId,
    revision: source.revision,
    parentRevision: source.parentRevision,
    contentHash: source.contentHash,
    content: chapterOutlineResponseContent(source.content),
    basis: chapterOutlineBasis(source.basis),
  }
  if (includeDisplay) {
    result.status = source.status
    result.reason = source.reason
  }
  return result
}

function chapterOutlineRequiredDraftResponse(value) {
  const result = chapterOutlineDraftResponse(value)
  if (result === null) throw new TypeError('Invalid ChapterOutline draft')
  return result
}

function chapterOutlineRequiredRevisionResponse(value, options) {
  const result = chapterOutlineRevisionResponse(value, options)
  if (result === null) throw new TypeError('Invalid ChapterOutline revision')
  return result
}

function chapterOutlineHistoryResponse(value) {
  const source = chapterOutlineResponseObject(value, 'history')
  chapterOutlineRequireOwnFields(source, ['items'], 'history')
  if (!Array.isArray(source.items)) {
    throw new TypeError('Invalid ChapterOutline history')
  }
  return {
    items: source.items.map(item => (
      chapterOutlineRequiredRevisionResponse(item, { includeDisplay: true })
    )),
  }
}

function chapterOutlineActiveSession(value) {
  if (value == null) return null
  const source = chapterOutlineResponseObject(value, 'active session')
  chapterOutlineResponseScalars(
    source,
    {
      strings: [
        'chapterSessionId',
        'status',
        'planningRevisionId',
        'planningHash',
        'outlineRevisionId',
        'outlineHash',
      ],
      integers: [
        'chapterNumber',
        'planningRevision',
        'outlineRevision',
      ],
    },
    'active session',
  )
  return {
    chapterSessionId: source.chapterSessionId,
    chapterNumber: source.chapterNumber,
    status: source.status,
    planningRevisionId: source.planningRevisionId,
    planningRevision: source.planningRevision,
    planningHash: source.planningHash,
    outlineRevisionId: source.outlineRevisionId,
    outlineRevision: source.outlineRevision,
    outlineHash: source.outlineHash,
  }
}

function chapterOutlinePendingOperation(value) {
  if (value == null) return null
  const source = chapterOutlineResponseObject(value, 'pending operation')
  chapterOutlineResponseScalars(
    source,
    { strings: ['operationId', 'status'] },
    'pending operation',
  )
  return {
    operationId: source.operationId,
    status: source.status,
  }
}

function chapterOutlineCapabilities(value) {
  const source = chapterOutlineResponseObject(value, 'capabilities')
  const fields = [
    'view',
    'createDraft',
    'editDraft',
    'generate',
    'confirm',
    'startSession',
  ]
  chapterOutlineResponseScalars(
    source,
    { booleans: fields },
    'capabilities',
  )
  return Object.fromEntries(fields.map(field => [field, source[field]]))
}

function chapterOutlineStateResponse(value) {
  const source = chapterOutlineResponseObject(value, 'state')
  chapterOutlineResponseScalars(
    source,
    {
      strings: ['projectId', 'lifecycle', 'targetPath'],
      integers: ['authoritativeChapterNumber'],
    },
    'state',
  )
  chapterOutlineRequireOwnFields(
    source,
    [
      'planningAuthority',
      'canonProjectionAuthority',
      'confirmedOutline',
      'draft',
      'activeSession',
      'pendingOperation',
      'capabilities',
      'reasons',
    ],
    'state',
  )
  if (
    !Array.isArray(source.reasons)
    || source.reasons.some(reason => typeof reason !== 'string')
  ) {
    throw new TypeError('Invalid ChapterOutline state')
  }
  return {
    projectId: source.projectId,
    lifecycle: source.lifecycle,
    authoritativeChapterNumber: source.authoritativeChapterNumber,
    targetPath: source.targetPath,
    planningAuthority: chapterOutlinePlanningAuthority(
      source.planningAuthority,
    ),
    canonProjectionAuthority: chapterOutlineProjectionAuthority(
      source.canonProjectionAuthority,
    ),
    confirmedOutline: chapterOutlineRevisionResponse(
      source.confirmedOutline,
    ),
    draft: chapterOutlineDraftResponse(source.draft),
    activeSession: chapterOutlineActiveSession(source.activeSession),
    pendingOperation: chapterOutlinePendingOperation(
      source.pendingOperation,
    ),
    capabilities: chapterOutlineCapabilities(source.capabilities),
    reasons: [...source.reasons],
  }
}

function chapterOutlineOperationResponse(value, expectedOperationId) {
  const invalid = () => {
    throw new TypeError('Invalid ChapterOutline operation response')
  }
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()
  const operationId = planningOperationId(value.operationId)
  if (!operationId || (expectedOperationId && operationId !== expectedOperationId)) {
    invalid()
  }
  const revision = value.loadedDraftRevision
  const revisionIsPositive = Number.isInteger(revision) && revision > 0
  const valid = (
    (
      value.status === 'pending'
      && value.failureCode === null
      && value.loaded === false
      && revision === null
    )
    || (
      value.status === 'succeeded'
      && value.failureCode === null
      && value.loaded === true
      && revisionIsPositive
    )
    || (
      value.status === 'failed'
      && CHAPTER_OUTLINE_FAILURE_CODES.has(value.failureCode)
      && value.loaded === false
      && revision === null
    )
    || (
      value.status === 'superseded'
      && value.failureCode === null
      && value.loaded === false
      && revision === null
    )
  )
  if (!valid) invalid()
  const providerId = publicPlanningLabel(value.model?.providerId)
  const modelName = publicPlanningLabel(value.model?.modelName)
  return {
    operationId,
    status: value.status,
    failureCode: value.failureCode,
    model: providerId && modelName
      ? { providerId, modelName }
      : { providerId: 'unavailable', modelName: 'unavailable' },
    loaded: value.loaded,
    loadedDraftRevision: revision,
  }
}

const DRAFT_OPERATION_STATUSES = new Set([
  'starting', 'running', 'completed', 'failed', 'expired',
])
const DRAFT_OPERATION_FAILURE_CODES = new Set([
  'DraftProviderFailed', 'DraftProviderResultInvalid',
])
const DRAFT_OPERATION_SENSITIVE_KEYS = new Set([
  'prompt', 'messages', 'provider', 'model', 'apikey', 'baseurl', 'debug',
  'responsebody',
])
const DRAFT_OPERATION_COMMAND_FIELDS = [
  'operationType', 'expectedWorkingDraftRevision', 'expectedContentHash',
  'idempotencyKey', 'authorInstruction',
]

function draftOperationObject(value, label) {
  if (
    !value
    || typeof value !== 'object'
    || Array.isArray(value)
    || (Object.getPrototypeOf(value) !== Object.prototype
      && Object.getPrototypeOf(value) !== null)
  ) {
    throw new TypeError(`Invalid draft operation ${label}`)
  }
  return value
}

function draftOperationUuid(value, label) {
  if (
    typeof value !== 'string'
    || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value)
  ) {
    throw new TypeError(`Invalid draft operation ${label}`)
  }
  return value
}

function draftOperationHash(value, label) {
  if (typeof value !== 'string' || !/^[0-9a-f]{64}$/.test(value)) {
    throw new TypeError(`Invalid draft operation ${label}`)
  }
  return value
}

function hasSensitiveDraftOperationKey(value, ancestors = new WeakSet()) {
  if (!value || typeof value !== 'object') return false
  if (ancestors.has(value)) return true
  ancestors.add(value)
  try {
    for (const key of Object.keys(value)) {
      const normalized = key.replace(/[^a-z0-9]/gi, '').toLowerCase()
      if (DRAFT_OPERATION_SENSITIVE_KEYS.has(normalized)) return true
      if (hasSensitiveDraftOperationKey(value[key], ancestors)) return true
    }
    return false
  } finally {
    ancestors.delete(value)
  }
}

function draftOperationCommand(value) {
  const source = draftOperationObject(value, 'command')
  if (
    hasSensitiveDraftOperationKey(source)
    || Object.keys(source).length !== DRAFT_OPERATION_COMMAND_FIELDS.length
    || DRAFT_OPERATION_COMMAND_FIELDS.some(field => !Object.hasOwn(source, field))
    || source.operationType !== 'generate_new'
    || !Number.isInteger(source.expectedWorkingDraftRevision)
    || source.expectedWorkingDraftRevision < 1
    || typeof source.authorInstruction !== 'string'
    || source.authorInstruction.length > 2000
  ) {
    throw new TypeError('Invalid draft operation command')
  }
  return Object.freeze({
    operationType: 'generate_new',
    expectedWorkingDraftRevision: source.expectedWorkingDraftRevision,
    expectedContentHash: draftOperationHash(
      source.expectedContentHash,
      'expected content hash',
    ),
    idempotencyKey: draftOperationUuid(source.idempotencyKey, 'idempotency key'),
    authorInstruction: source.authorInstruction,
  })
}

function draftOperationResponse(value, expected = {}) {
  const source = draftOperationObject(value, 'response')
  const operationId = draftOperationUuid(source.operationId, 'id')
  const projectId = draftOperationUuid(source.projectId, 'project id')
  const chapterSessionId = draftOperationUuid(source.chapterSessionId, 'session id')
  const status = source.status
  const sequence = source.lastEventSequence
  const revision = source.resultWorkingDraftRevision
  const resultHash = source.resultContentHash
  const failureCode = source.failureCode
  const providerId = publicPlanningLabel(source.providerId)
  const modelName = publicPlanningLabel(source.modelName)
  if (
    (expected.operationId && operationId !== expected.operationId)
    || (expected.projectId && projectId !== expected.projectId)
    || (expected.sessionId && chapterSessionId !== expected.sessionId)
    || source.operationType !== 'generate_new'
    || !DRAFT_OPERATION_STATUSES.has(status)
    || !Number.isInteger(sequence)
    || sequence < 1
    || !providerId
    || !modelName
  ) {
    throw new TypeError('Invalid draft operation response')
  }
  const terminal = status === 'completed' || status === 'failed'
  if (sequence !== (terminal ? 2 : 1)) {
    throw new TypeError('Invalid draft operation response')
  }
  if (status === 'completed') {
    if (
      !Number.isInteger(revision)
      || revision < 1
      || (
        expected.expectedBaseRevision !== undefined
        && revision !== expected.expectedBaseRevision + 1
      )
      || failureCode !== null
    ) throw new TypeError('Invalid draft operation response')
    draftOperationHash(resultHash, 'result content hash')
  } else if (status === 'failed') {
    if (
      revision !== null
      || resultHash !== null
      || !DRAFT_OPERATION_FAILURE_CODES.has(failureCode)
    ) throw new TypeError('Invalid draft operation response')
  } else if (revision !== null || resultHash !== null || failureCode !== null) {
    throw new TypeError('Invalid draft operation response')
  }
  return Object.freeze({
    operationId,
    projectId,
    chapterSessionId,
    operationType: 'generate_new',
    status,
    lastEventSequence: sequence,
    resultWorkingDraftRevision: revision,
    resultContentHash: resultHash,
    failureCode,
    providerId,
    modelName,
  })
}

function draftOperationEventsResponse(value, expectedOperationId, afterSequence) {
  const source = draftOperationObject(value, 'events response')
  if (
    draftOperationUuid(source.operationId, 'id') !== expectedOperationId
    || !Array.isArray(source.events)
    || source.events.length > 100
  ) throw new TypeError('Invalid draft operation events response')
  const events = source.events.map((event, index) => {
    const item = draftOperationObject(event, 'event')
    const sequence = item.sequence
    if (
      !Number.isInteger(sequence)
      || sequence < 1
      || sequence !== afterSequence + index + 1
      || typeof item.type !== 'string'
      || !Number.isInteger(item.createdAt)
      || item.createdAt < 0
    ) throw new TypeError('Invalid draft operation event')
    const result = { sequence, type: item.type, createdAt: item.createdAt }
    if (sequence === 1) {
      if (item.type !== 'started') throw new TypeError('Invalid draft operation event')
    } else if (sequence === 2 && item.type === 'completed') {
      if (
        !Number.isInteger(item.resultWorkingDraftRevision)
        || item.resultWorkingDraftRevision < 1
      ) throw new TypeError('Invalid draft operation event')
      result.resultWorkingDraftRevision = item.resultWorkingDraftRevision
      result.resultContentHash = draftOperationHash(
        item.resultContentHash,
        'event result content hash',
      )
    } else if (sequence === 2 && item.type === 'failed') {
      if (!DRAFT_OPERATION_FAILURE_CODES.has(item.failureCode)) {
        throw new TypeError('Invalid draft operation event')
      }
      result.failureCode = item.failureCode
    } else {
      throw new TypeError('Invalid draft operation event')
    }
    return Object.freeze(result)
  })
  return Object.freeze({ operationId: expectedOperationId, events: Object.freeze(events) })
}

function draftOperationAfterSequence(value) {
  if (!Number.isInteger(value) || value < 0 || value > 2_147_483_647) {
    throw new TypeError('Invalid draft operation event cursor')
  }
  return value
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
    get: async projectId => planningStateResponse(await get(
      `/projects/${segment(projectId)}/planning`,
    )),
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
    generateDraft: async (projectId, draftId, data) => {
      const opaqueKey = planningIdempotencyKey(data?.idempotencyKey)
      if (!opaqueKey) {
        throw new TypeError('Invalid Planning idempotency key')
      }
      return planningOperationResponse(await post(
        `/projects/${segment(projectId)}/planning/drafts/${segment(draftId)}/generate`,
        {
          ...pickDefined(data, [
            'draftRevision',
            'draftHash',
            'authorInstructions',
          ]),
          idempotencyKey: opaqueKey,
        },
        PLANNING_GENERATION_TIMEOUT,
      ))
    },
    getOperation: async (projectId, operationId) => {
      const opaqueId = planningOperationId(operationId)
      if (!opaqueId) throw new TypeError('Invalid Planning operation id')
      return planningOperationResponse(
        await get(
          `/projects/${segment(projectId)}/planning/operations/${segment(opaqueId)}`,
        ),
        opaqueId,
      )
    },
    getOperationByIdempotencyKey: async (projectId, idempotencyKey) => {
      const opaqueKey = planningIdempotencyKey(idempotencyKey)
      if (!opaqueKey) {
        throw new TypeError('Invalid Planning idempotency key')
      }
      return planningOperationResponse(
        await get(
          `/projects/${segment(projectId)}/planning/operations/by-idempotency-key/${segment(opaqueKey)}`,
        ),
      )
    },
  },

  chapterOutlines: {
    current: async projectId => chapterOutlineStateResponse(await get(
      `/projects/${segment(projectId)}/chapter-outlines/current`,
    )),
    get: async (projectId, chapterNumber) => chapterOutlineStateResponse(await get(
      `/projects/${segment(projectId)}/chapter-outlines/${positiveChapterNumber(chapterNumber)}`,
    )),
    history: async (projectId, chapterNumber) => chapterOutlineHistoryResponse(
      await get(
        `/projects/${segment(projectId)}/chapter-outlines/${positiveChapterNumber(chapterNumber)}/history`,
      ),
    ),
    createDraft: async (projectId, chapterNumber) => (
      chapterOutlineRequiredDraftResponse(await post(
        `/projects/${segment(projectId)}/chapter-outlines/${positiveChapterNumber(chapterNumber)}/drafts`,
        {},
      ))
    ),
    saveDraft: async (projectId, chapterNumber, draftId, data) => (
      chapterOutlineRequiredDraftResponse(await put(
        `/projects/${segment(projectId)}/chapter-outlines/${positiveChapterNumber(chapterNumber)}/drafts/${segment(chapterOutlineOpaqueId(draftId, 'draft id'))}`,
        {
          expectedDraftRevision: data.expectedDraftRevision,
          expectedDraftHash: data.expectedDraftHash,
          content: chapterOutlineWriteContent(data.content),
        },
      ))
    ),
    confirmDraft: async (projectId, chapterNumber, draftId, data) => (
      chapterOutlineRequiredRevisionResponse(await post(
        `/projects/${segment(projectId)}/chapter-outlines/${positiveChapterNumber(chapterNumber)}/drafts/${segment(chapterOutlineOpaqueId(draftId, 'draft id'))}/confirm`,
        {
          expectedDraftRevision: data.expectedDraftRevision,
          expectedDraftHash: data.expectedDraftHash,
          expectedHeadRevision: data.expectedHeadRevision,
          idempotencyKey: chapterOutlineIdempotencyKey(data.idempotencyKey),
        },
      ), { includeDisplay: false })
    ),
    generateDraft: async (projectId, chapterNumber, draftId, data) => (
      chapterOutlineOperationResponse(await post(
        `/projects/${segment(projectId)}/chapter-outlines/${positiveChapterNumber(chapterNumber)}/drafts/${segment(chapterOutlineOpaqueId(draftId, 'draft id'))}/generate`,
        {
          draftRevision: data.draftRevision,
          draftHash: data.draftHash,
          idempotencyKey: chapterOutlineIdempotencyKey(data.idempotencyKey),
          authorInstructions: String(data.authorInstructions || ''),
        },
        CHAPTER_OUTLINE_GENERATION_TIMEOUT,
      ))
    ),
    getOperation: async (projectId, operationId) => {
      const opaqueId = chapterOutlineOpaqueId(operationId, 'operation id')
      return chapterOutlineOperationResponse(
        await get(
          `/projects/${segment(projectId)}/chapter-outlines/operations/${segment(opaqueId)}`,
        ),
        opaqueId,
      )
    },
    getOperationByKey: async (projectId, idempotencyKey) => (
      chapterOutlineOperationResponse(await get(
        `/projects/${segment(projectId)}/chapter-outlines/operations/by-key/${segment(chapterOutlineIdempotencyKey(idempotencyKey))}`,
      ))
    ),
  },

  chapterSessions: {
    get: (projectId, chapterNumber) => get(
      `/projects/${segment(projectId)}/chapter-sessions/${segment(chapterNumber)}`,
    ),
    create: (projectId, chapterNumber, data) => post(
      `/projects/${segment(projectId)}/chapter-sessions/${segment(chapterNumber)}`,
      {
        chapterNumber: data.chapterNumber,
        expectedPlanningRevision: data.expectedPlanningRevision,
        expectedPlanningHash: data.expectedPlanningHash,
        expectedOutlineRevision: data.expectedOutlineRevision,
        expectedOutlineHash: data.expectedOutlineHash,
        expectedCanonRevision: data.expectedCanonRevision,
      },
    ),
    saveWorkingDraft: (projectId, sessionId, data) => put(
      `/projects/${segment(projectId)}/chapter-sessions/${segment(sessionId)}/working-draft`,
      {
        expectedRevision: data.expectedRevision,
        expectedContentHash: data.expectedContentHash,
        content: data.content,
      },
    ),
    createDraftOperation: async (projectId, sessionId, command) => {
      const normalizedProjectId = draftOperationUuid(projectId, 'project id')
      const normalizedSessionId = draftOperationUuid(sessionId, 'session id')
      const body = draftOperationCommand(command)
      return draftOperationResponse(await post(
        `/projects/${segment(normalizedProjectId)}/chapter-sessions/${segment(normalizedSessionId)}/draft-operations`,
        body,
        DRAFT_OPERATION_TIMEOUT,
      ), {
        projectId: normalizedProjectId,
        sessionId: normalizedSessionId,
        expectedBaseRevision: body.expectedWorkingDraftRevision,
      })
    },
    readDraftOperation: async (projectId, sessionId, operationId) => {
      const normalizedProjectId = draftOperationUuid(projectId, 'project id')
      const normalizedSessionId = draftOperationUuid(sessionId, 'session id')
      const normalizedOperationId = draftOperationUuid(operationId, 'id')
      return draftOperationResponse(await get(
        `/projects/${segment(normalizedProjectId)}/chapter-sessions/${segment(normalizedSessionId)}/draft-operations/${segment(normalizedOperationId)}`,
      ), {
        projectId: normalizedProjectId,
        sessionId: normalizedSessionId,
        operationId: normalizedOperationId,
      })
    },
    listDraftOperationEvents: async (projectId, sessionId, operationId, afterSequence) => {
      const normalizedProjectId = draftOperationUuid(projectId, 'project id')
      const normalizedSessionId = draftOperationUuid(sessionId, 'session id')
      const normalizedOperationId = draftOperationUuid(operationId, 'id')
      const after = draftOperationAfterSequence(afterSequence)
      return draftOperationEventsResponse(await get(
        `/projects/${segment(normalizedProjectId)}/chapter-sessions/${segment(normalizedSessionId)}/draft-operations/${segment(normalizedOperationId)}/events?after=${after}`,
      ), normalizedOperationId, after)
    },
    saveCandidate: (projectId, sessionId, data) => post(
      `/projects/${segment(projectId)}/chapter-sessions/${segment(sessionId)}/candidates`,
      {
        expectedWorkingDraftRevision: data.expectedWorkingDraftRevision,
        expectedContentHash: data.expectedContentHash,
        idempotencyKey: data.idempotencyKey,
      },
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
