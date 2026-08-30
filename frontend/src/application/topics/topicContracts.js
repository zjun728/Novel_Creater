const HASH = /^[0-9a-f]{64}$/u
const text = value => typeof value === 'string' && value.length > 0
const integer = value => Number.isSafeInteger(value) && value > 0

function exact(value, keys, label) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new TypeError(`Invalid ${label}`)
  const actual = Object.keys(value)
  if (actual.length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) {
    throw new TypeError(`Invalid ${label}`)
  }
  return value
}

export const DIRECTION_FIELDS = Object.freeze([
  'title', 'genreOpportunity', 'targetAudience', 'readerPromise',
  'differentiation', 'longFormPotential', 'risks', 'evidenceSummary',
])
export const CANDIDATE_FIELDS = Object.freeze([
  'title', 'genre', 'logline', 'targetAudience', 'protagonist', 'desire',
  'coreConflict', 'worldPressure', 'openingHook', 'differentiation',
  'storyPromise', 'longFormPotential', 'marketBasis',
])

function payload(value, fields, label) {
  exact(value, fields, label)
  if (!fields.every(field => text(value[field]) && value[field] === value[field].trim())) {
    throw new TypeError(`Invalid ${label}`)
  }
  return Object.freeze({ ...value })
}

export const parseDirectionPayload = value => payload(value, DIRECTION_FIELDS, 'topic direction')
export const parseCandidatePayload = value => payload(value, CANDIDATE_FIELDS, 'topic candidate')

export function parseAssistantResult(value) {
  exact(value, ['reply', 'directionSuggestions', 'candidateSuggestions'], 'topic assistant result')
  if (!text(value.reply) || !Array.isArray(value.directionSuggestions)
    || !Array.isArray(value.candidateSuggestions)
    || value.directionSuggestions.length > 4 || value.candidateSuggestions.length > 4) {
    throw new TypeError('Invalid topic assistant result')
  }
  return Object.freeze({
    reply: value.reply,
    directionSuggestions: Object.freeze(value.directionSuggestions.map(parseDirectionPayload)),
    candidateSuggestions: Object.freeze(value.candidateSuggestions.map(parseCandidatePayload)),
  })
}

export function parseHandoff(value) {
  exact(value, ['project', 'seed', 'handoff'], 'topic handoff')
  exact(value.project, ['id', 'title'], 'topic handoff project')
  exact(value.seed, ['id', 'revision', 'isSelected', 'selectionRevision'], 'topic handoff seed')
  exact(value.handoff, ['candidateId', 'version'], 'topic handoff receipt')
  if (!text(value.project.id) || !text(value.project.title) || !text(value.seed.id)
    || !integer(value.seed.revision) || value.seed.isSelected !== false
    || value.seed.selectionRevision !== 0 || !text(value.handoff.candidateId)
    || !integer(value.handoff.version)) throw new TypeError('Invalid topic handoff')
  return Object.freeze({
    project: Object.freeze({ ...value.project }),
    seed: Object.freeze({ ...value.seed }),
    handoff: Object.freeze({ ...value.handoff }),
  })
}

export function parseSavedCandidate(value) {
  exact(value, ['candidateId', 'versionId', 'version', 'contentHash', 'payload', 'basis'], 'saved topic candidate')
  if (!text(value.candidateId) || !text(value.versionId) || !integer(value.version)
    || !HASH.test(value.contentHash)) throw new TypeError('Invalid saved topic candidate')
  return Object.freeze({ ...value, payload: parseCandidatePayload(value.payload) })
}

export function candidatePresentation(value) {
  const parsed = parseSavedCandidate(value)
  return Object.freeze({
    id: parsed.candidateId,
    version: parsed.version,
    title: parsed.payload.title,
    genre: parsed.payload.genre,
    logline: parsed.payload.logline,
  })
}
