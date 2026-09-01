import {
  contractDraftVersion,
  contractStepAccess,
} from '../../domain/creation-contract/wizard-state.js'

const SECTION_DEFINITIONS = Object.freeze([
  {
    key: 'engine',
    label: '故事发动机',
    step: 1,
    fields: [
      'engineOptionId', 'engineHash', 'channelProfileKey', 'genreProfileKey',
      'qualityCharterVersion',
    ],
  },
  {
    key: 'capacity',
    label: '长篇容量',
    step: 4,
    fields: [
      'targetTotalWords', 'expectedVolumeCount', 'expectedChapterCount',
      'chapterWordRangePreference', 'authorNotes',
    ],
  },
  {
    key: 'assets',
    label: '正式资产范围',
    step: 3,
    fields: ['experienceCardRefs', 'corpusSourceRefs'],
  },
  {
    key: 'style',
    label: '风格方案',
    step: 2,
    fields: ['primaryStyleRef', 'secondaryStyleRef', 'likes', 'dislikes'],
  },
  {
    key: 'prohibitions',
    label: '禁止方向',
    step: 4,
    fields: ['prohibitedDirections'],
  },
  {
    key: 'preview',
    label: '完整预览',
    step: 5,
    fields: [],
  },
])

function currentPayload(state) {
  if (state?.payload && typeof state.payload === 'object') return state.payload
  if (state?.draft?.draft && typeof state.draft.draft === 'object') return state.draft.draft
  if (state?.draft && typeof state.draft === 'object') return state.draft
  return {}
}

function savedStage(state, payload) {
  return state?.draftStage
    || state?.lastSavedStage
    || state?.draft?.draftStage
    || payload?.draftStage
    || null
}

function serverReasons(state) {
  const sources = [
    state?.serverReasons,
    state?.readiness?.reasons,
    state?.validation?.reasons,
  ]
  return [...new Set(sources.flatMap(value => (
    Array.isArray(value) ? value.map(reason => String(reason)) : []
  )))]
}

function serverBlocked(state, reasons) {
  return reasons.length > 0
    || state?.capabilities?.view === false
    || state?.capabilities?.edit === false
    || state?.serverCanEdit === false
}

function hasOwnProperty(value, property) {
  return value !== null && typeof value === 'object' && Object.hasOwn(value, property)
}

function serverCanConfirm(state) {
  if (hasOwnProperty(state, 'serverCanConfirm')) return state.serverCanConfirm === true
  if (hasOwnProperty(state?.capabilities, 'confirm')) return state.capabilities.confirm === true
  if (hasOwnProperty(state?.readiness, 'canConfirm')) return state.readiness.canConfirm === true
  return false
}

function hasValue(value) {
  if (Array.isArray(value)) return value.length > 0
  return value !== null && value !== undefined && value !== ''
}

function isFilled(key, payload, stage) {
  if (key === 'engine') return hasValue(payload.engineOptionId) && hasValue(payload.engineHash)
  if (key === 'capacity') return [
    'targetTotalWords', 'expectedVolumeCount', 'expectedChapterCount',
    'chapterWordRangePreference',
  ].every(field => hasValue(payload[field]))
  if (key === 'assets') return Array.isArray(payload.experienceCardRefs)
    && Array.isArray(payload.corpusSourceRefs)
  if (key === 'style') return hasValue(payload.primaryStyleRef)
    && Array.isArray(payload.likes) && Array.isArray(payload.dislikes)
  if (key === 'prohibitions') return Array.isArray(payload.prohibitedDirections)
  return stage === 'assets'
}

function valuesFor(fields, payload) {
  return Object.fromEntries(fields.map(field => [field, snapshotValue(payload[field])]))
}

function snapshotValue(value) {
  if (Array.isArray(value)) return value.map(snapshotValue)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, snapshotValue(item)]))
  }
  return value
}

/**
 * Maps the persisted Contract workflow into the document's six author sections.
 * The mapper is display-only: command authorization stays with the server and
 * the existing store commands.
 */
export function contractDocumentSections(state = {}) {
  const payload = currentPayload(state)
  const draftStage = savedStage(state, payload)
  const stepAccess = contractStepAccess({
    selectionDrift: state?.selectionDrift === true,
    lastSavedStage: draftStage,
  })
  const reasons = serverReasons(state)
  const blocked = serverBlocked(state, reasons)
  const canPreview = !blocked && stepAccess.maxOpenStep >= 5
  const canConfirm = canPreview && serverCanConfirm(state)
  const draftVersion = hasOwnProperty(state, 'draftVersion')
    ? contractDraftVersion(state.draftVersion)
    : contractDraftVersion(state?.draft?.draftVersion)

  return {
    draftVersion: { label: '并发版本', value: draftVersion },
    sections: SECTION_DEFINITIONS.map(definition => {
      const open = definition.step <= stepAccess.maxOpenStep
      const filled = isFilled(definition.key, payload, draftStage)
      const status = blocked ? 'blocked' : (filled ? 'filled' : 'suggested')
      return {
        key: definition.key,
        label: definition.label,
        targetId: `contract-${definition.key}`,
        visible: true,
        open,
        status,
        values: valuesFor(definition.fields, payload),
        writeFields: !blocked && open ? [...definition.fields] : [],
        canPreview: definition.key === 'preview' && canPreview,
        canConfirm: definition.key === 'preview' && canConfirm,
        blockedReasons: blocked ? reasons : [],
      }
    }),
  }
}
