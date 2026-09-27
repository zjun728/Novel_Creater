import { shallowRef } from 'vue'

const text = value => typeof value === 'string' && value.length > 0
const hash = value => typeof value === 'string' && /^[a-f0-9]{64}$/u.test(value)
const optionalText = value => value === undefined || value === null || text(value)
const evidenceValid = value => Boolean(value
  && value.verified === true && text(value.excerpt) && hash(value.excerptHash)
  && Number.isSafeInteger(value.startScalar) && value.startScalar >= 0
  && Number.isSafeInteger(value.endScalar) && value.endScalar > value.startScalar
  && [...value.excerpt].length === value.endScalar - value.startScalar
  && Number.isFinite(value.confidence) && value.confidence >= 0 && value.confidence <= 1
  && text(value.rationale))
const list = (value, validate) => Array.isArray(value) && value.every(item => item && validate(item))
const target = item => text(item.id) && text(item.targetType) && text(item.targetId) && optionalText(item.targetTitle) && evidenceValid(item.evidence)

function matchesRequest(value, projectId, chapterNumber) {
  const report = value?.qualityReport
  return value?.projectId === projectId && value.chapterNumber === chapterNumber
    && text(value.finalizationId) && Number.isSafeInteger(value.canonRevision) && value.canonRevision >= 1
    && typeof value.summary === 'string' && report && hash(report.contentHash)
    && ['completed', 'quality_not_completed'].includes(report.status)
    && list(report.deterministicBlocks, item => text(item.code) && text(item.message) && (item.evidence === null || evidenceValid(item.evidence)))
    && list(report.findings, item => text(item.id) && text(item.dimension) && text(item.reason) && text(item.suggestedAction) && evidenceValid(item.evidence))
    && (report.status !== 'quality_not_completed' || report.findings.length === 0)
    && list(value.canonEvents, item => text(item.id) && text(item.fieldPath)
      && (item.entityId === null || text(item.entityId)) && optionalText(item.entityName)
      && ['stable_definition', 'dynamic_event', 'claim'].includes(item.factKind)
      && ['equals', 'not_equals'].includes(item.assertionOperator)
      && Object.hasOwn(item, 'value') && evidenceValid(item.evidence))
    && list(value.storyProgressEvents, item => target(item) && ['started', 'advanced', 'completed'].includes(item.status))
    && list(value.planningPatches, item => target(item) && text(item.fieldPath) && Object.hasOwn(item, 'replacement'))
}

export function createFinalReviewController({ api }) {
  const state = shallowRef({ status: 'idle', data: null, message: '' })
  let generation = 0
  let abort = null
  let disposed = false

  function reset() {
    generation += 1
    abort?.abort()
    abort = null
    state.value = { status: 'idle', data: null, message: '' }
  }

  async function load(projectId, chapterNumber) {
    if (disposed) return false
    reset()
    const token = generation
    if (!text(projectId) || !Number.isSafeInteger(chapterNumber) || chapterNumber < 1) {
      state.value = { status: 'error', data: null, message: '章节地址无效，请从作品目录重新选择。' }
      return false
    }
    abort = new AbortController()
    state.value = { status: 'loading', data: null, message: '' }
    try {
      const result = await api.workbench.review(projectId, chapterNumber, { signal: abort.signal })
      if (disposed || token !== generation) return false
      if (!matchesRequest(result, projectId, chapterNumber)) throw new Error('Invalid final review response')
      state.value = { status: 'ready', data: result, message: '' }
      return true
    } catch {
      if (disposed || token !== generation) return false
      state.value = { status: 'error', data: null, message: '定稿审查记录暂时无法读取，请重试。已定稿正文不受影响。' }
      return false
    }
  }

  function dispose() { disposed = true; reset() }
  return { state, load, reset, dispose }
}
