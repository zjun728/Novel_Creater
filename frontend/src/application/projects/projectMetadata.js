import { unicodeScalarLength } from '../../utils/unicodeScalarText.js'

export const PROJECT_METADATA_DEFAULTS = Object.freeze({
  genre: '',
  description: '',
  targetWords: 2_400_000,
  targetChapters: 720,
})

function invalid() {
  throw new TypeError('Invalid project metadata')
}

function text(value, { required = false, max }) {
  if (typeof value !== 'string') invalid()
  const normalized = value.trim()
  if ((required && !normalized) || unicodeScalarLength(normalized) > max) invalid()
  return normalized
}

function positiveInteger(value) {
  if (!Number.isSafeInteger(value) || value < 1) invalid()
  return value
}

export function projectMetadataPayload(value = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalid()
  return {
    title: text(value.title, { required: true, max: 200 }),
    genre: text(value.genre ?? PROJECT_METADATA_DEFAULTS.genre, { max: 120 }),
    description: text(
      value.description ?? PROJECT_METADATA_DEFAULTS.description,
      { max: 5000 },
    ),
    targetWords: positiveInteger(
      value.targetWords ?? PROJECT_METADATA_DEFAULTS.targetWords,
    ),
    targetChapters: positiveInteger(
      value.targetChapters ?? PROJECT_METADATA_DEFAULTS.targetChapters,
    ),
  }
}

export function projectMetadataUpdatePayload(value = {}) {
  const payload = projectMetadataPayload(value)
  const revision = value.expectedLifecycleRevision
  if (!Number.isSafeInteger(revision) || revision < 0) invalid()
  return { ...payload, expectedLifecycleRevision: revision }
}
