import { buildContextPackV2, buildCreativeContextFromPack } from './contextPackV2.js'
import { normalizeStateProvenance } from './stateProvenance.js'

const FINAL_STATUSES = new Set(['final', 'finalized', 'committed', 'accepted', 'trusted'])
const PLAN_ONLY_STATUSES = new Set(['plan_only', 'candidate', 'draft', 'ai_candidate', 'unfinalized'])
const PENDING_FINALIZATION_STATUSES = new Set(['pending', 'in_progress', 'started', 'validated', 'half_success', 'failed_after_chapter_commit'])

export function checkProjectStateHealth(snapshot = {}, options = {}) {
  const chapterNum = Number(options.chapterNum || snapshot.chapterNum || 0)
  const pack = buildContextPackV2({
    novelStore: snapshot.novelStore || {},
    settingStore: snapshot.settingStore || {},
    volumeStore: snapshot.volumeStore || {},
    correctionTaskStore: snapshot.correctionTaskStore || {},
    contextOptions: snapshot.contextOptions || {},
    chapterNum
  })
  const creativeContext = buildCreativeContextFromPack(pack, { chapterNum })
  const issues = dedupeIssues([
    ...(pack.healthCheck?.issues || []),
    ...findEmptyChapterAuthorityIssues(snapshot, chapterNum),
    ...findPromptFacingDegradedIssues(pack, creativeContext),
    ...findBeatPlanConflictIssues(snapshot, chapterNum),
    ...findGuardLeakIssues(pack, creativeContext)
  ])
  return {
    schemaVersion: 'project-health-check-v1',
    chapterNum,
    blocked: issues.some(issue => issue.severity === 'block'),
    issues,
    contextPack: pack,
    creativeContext
  }
}

export function rebuildStateProjectionFromFinals(snapshot = {}, options = {}) {
  const chapterNum = Number(options.chapterNum || snapshot.chapterNum || 0)
  const contextOptions = snapshot.contextOptions || {}
  const { chaptersByNum, versionsById } = buildChapterMaps(contextOptions.chapters || [], contextOptions.chapterVersions || [])
  const rejectedProjectionSources = []
  const finalChapters = Array.from(chaptersByNum.values())
    .filter(chapter => isFinalChapterBefore(chapter, versionsById, chapterNum))
    .sort((a, b) => numberOf(a.chapterNum ?? a.chapter_num) - numberOf(b.chapterNum ?? b.chapter_num))
    .map(chapter => {
      const finalVersionId = chapter.finalVersionId || chapter.final_version_id || ''
      const version = versionsById.get(finalVersionId) || {}
      return {
        chapterNum: numberOf(chapter.chapterNum ?? chapter.chapter_num),
        sourceVersionId: finalVersionId,
        contentEvidence: compactText(version.content || '', 420),
        provenance: {
          sourceChapterNum: numberOf(chapter.chapterNum ?? chapter.chapter_num),
          sourceVersionId: finalVersionId,
          finalizationId: chapter.finalizationId || chapter.finalization_id || '',
          commitStatus: 'final'
        }
      }
    })

  for (const version of contextOptions.chapterVersions || []) {
    const num = numberOf(version.chapterNum ?? version.chapter_num)
    const type = String(version.versionType || version.version_type || '').toLowerCase()
    if (num && num < chapterNum && !isFinalVersion(version, chaptersByNum)) {
      rejectedProjectionSources.push({
        sourceType: 'chapter_version',
        sourceId: version.id || version.versionId || '',
        sourceChapterNum: num,
        reason: type || 'non_final_version'
      })
    }
  }

  for (const plan of contextOptions.savedBeatPlans || []) {
    const provenance = normalizeStateProvenance(plan)
    rejectedProjectionSources.push({
      sourceType: 'chapter_beat_plan',
      sourceChapterNum: numberOf(plan.chapterNum ?? plan.chapter_num ?? provenance.sourceChapterNum),
      sourceVersionId: provenance.sourceVersionId,
      reason: provenance.commitStatus || 'plan_only'
    })
  }

  return {
    schemaVersion: 'state-projection-rebuild-dry-run-v1',
    chapterNum,
    stateAuthority: {
      finalChapters,
      canonFacts: collectFinalCanonFacts(snapshot.novelStore?.canonFacts || [], chaptersByNum, versionsById, chapterNum),
      settingEntities: collectFinalRecords(snapshot.settingStore?.entities || [], chaptersByNum, versionsById, chapterNum),
      settingChangeEvents: collectFinalRecords(snapshot.settingStore?.changeEvents || [], chaptersByNum, versionsById, chapterNum),
      settingRelations: collectFinalRecords(snapshot.settingStore?.relations || [], chaptersByNum, versionsById, chapterNum)
    },
    rejectedProjectionSources
  }
}

function findEmptyChapterAuthorityIssues(snapshot, currentChapterNum) {
  const contextOptions = snapshot.contextOptions || {}
  const { chaptersByNum, versionsById } = buildChapterMaps(contextOptions.chapters || [], contextOptions.chapterVersions || [])
  const issues = []
  for (const { targetType, records } of authorityRecordSets(snapshot)) {
    for (const record of records) {
      if (!isAuthorityFacing(record)) continue
      const provenance = normalizeStateProvenance(record)
      const sourceChapterNum = provenance.sourceChapterNum || numberOf(record.chapterNum ?? record.chapter_num)
      const sourceChapter = sourceChapterNum ? chaptersByNum.get(sourceChapterNum) : null
      const status = provenance.commitStatus
      const emptyLedger = sourceChapterNum &&
        chaptersByNum.size > 0 &&
        sourceChapterNum < currentChapterNum &&
        !isNonEmptyFinalChapter(sourceChapter, versionsById)
      if (status === 'empty_chapter' || emptyLedger) {
        issues.push({
          code: 'empty_chapter_authority',
          severity: 'block',
          targetType,
          target: record.id || record.name || record.entityName || record.content || targetType,
          reason: status === 'empty_chapter' ? 'commit_empty_chapter' : 'source_chapter_not_final_or_empty',
          provenance: { ...provenance, sourceChapterNum }
        })
      }
    }
  }
  return issues
}

function findPromptFacingDegradedIssues(pack, creativeContext) {
  const contextText = JSON.stringify(creativeContext || {})
  const issues = []
  for (const record of promptFacingAuthorityRecords(pack)) {
    if (!['unknown', 'degraded'].includes(record.trustLevel)) continue
    const visibleMarkers = [
      record.name,
      record.entityName,
      record.entity_name,
      record.content,
      record.summary,
      record.fact,
      record.id
    ].filter(value => String(value || '').trim())
    const marker = visibleMarkers[0] || record.targetType || 'state_authority'
    if (!visibleMarkers.length || visibleMarkers.some(value => contextText.includes(String(value)))) {
      issues.push({
        code: 'prompt_facing_degraded_context',
        severity: 'warn',
        targetType: record.targetType || 'state_authority',
        target: marker || record.targetType || 'state_authority',
        reason: record.trustLevel,
        provenance: record.provenance || {}
      })
    }
  }
  return issues
}

function findBeatPlanConflictIssues(snapshot, currentChapterNum) {
  const plans = snapshot.contextOptions?.savedBeatPlans || []
  const facts = snapshot.novelStore?.canonFacts || []
  const factText = facts
    .filter(fact => isRecordTrustedFinal(fact, new Map(), new Map(), currentChapterNum))
    .map(fact => `${fact.content || fact.summary || fact.fact || ''} ${fact.evidence || ''}`)
    .join('\n')
  return plans
    .filter(plan => {
      const provenance = normalizeStateProvenance(plan)
      if (PLAN_ONLY_STATUSES.has(provenance.commitStatus)) return true
      const content = String(plan.content || '').trim()
      return content && factText && !factText.includes(content)
    })
    .map(plan => {
      const provenance = normalizeStateProvenance(plan)
      return {
        code: 'saved_beat_plan_conflict',
        severity: 'warn',
        targetType: 'chapter_beat_plan',
        target: `chapter:${plan.chapterNum || plan.chapter_num || provenance.sourceChapterNum || '?'}`,
        reason: provenance.commitStatus || 'not_authority',
        provenance
      }
    })
}

function findGuardLeakIssues(pack, creativeContext) {
  const guardTextItems = []
  for (const item of pack.guardSnapshot?.futureRoadmap || []) {
    guardTextItems.push(item.goal, item.title, item.conflict, item.turn, item.handoff)
  }
  guardTextItems.push(...(pack.guardSnapshot?.forbiddenDirections || []))
  for (const plan of pack.guardSnapshot?.savedBeatPlans || []) {
    guardTextItems.push(plan.content)
  }
  const creativeText = JSON.stringify(creativeContext || {})
  return guardTextItems
    .filter(value => String(value || '').trim().length > 10)
    .filter(value => creativeText.includes(String(value)))
    .map(value => ({
      code: 'guard_snapshot_in_creative_context',
      severity: 'block',
      targetType: 'guard_snapshot',
      target: compactText(value, 80),
      reason: 'guard_only_text_visible_to_creative_context',
      provenance: {}
    }))
}

function collectFinalCanonFacts(records, chaptersByNum, versionsById, currentChapterNum) {
  return (records || [])
    .filter(record => String(record.status || 'accepted').toLowerCase() === 'accepted')
    .filter(record => isRecordTrustedFinal(record, chaptersByNum, versionsById, currentChapterNum))
    .map(record => ({ ...record, provenance: normalizeStateProvenance(record) }))
}

function collectFinalRecords(records, chaptersByNum, versionsById, currentChapterNum) {
  return (records || [])
    .filter(record => isRecordTrustedFinal(record, chaptersByNum, versionsById, currentChapterNum))
    .map(record => ({ ...record, provenance: normalizeStateProvenance(record) }))
}

function isRecordTrustedFinal(record, chaptersByNum, versionsById, currentChapterNum) {
  const provenance = normalizeStateProvenance(record)
  const sourceChapterNum = provenance.sourceChapterNum || numberOf(record.chapterNum ?? record.chapter_num)
  if (!sourceChapterNum || (currentChapterNum && sourceChapterNum >= currentChapterNum)) return false
  if (provenance.commitStatus && !FINAL_STATUSES.has(provenance.commitStatus)) return false
  if (chaptersByNum.size > 0) {
    return isNonEmptyFinalChapter(chaptersByNum.get(sourceChapterNum), versionsById)
  }
  return FINAL_STATUSES.has(provenance.commitStatus)
}

function promptFacingAuthorityRecords(pack = {}) {
  const authority = pack.stateAuthority || {}
  return [
    ...withTargetType(authority.canonFacts, 'canon_fact'),
    ...withTargetType(authority.settingEntities, 'setting_entity'),
    ...withTargetType(authority.settingChangeEvents, 'setting_change_event'),
    ...withTargetType(authority.settingRelations, 'setting_relation'),
    ...withTargetType(authority.characters, 'character'),
    ...withTargetType(authority.plotThreads, 'plot_thread'),
    ...(authority.activeStoryBlock ? [{ ...authority.activeStoryBlock, targetType: 'story_block' }] : [])
  ]
}

function withTargetType(records = [], targetType) {
  return (records || []).map(record => ({ ...record, targetType }))
}

function authorityRecordSets(snapshot = {}) {
  return [
    { targetType: 'canon_fact', records: snapshot.novelStore?.canonFacts || [] },
    { targetType: 'character', records: snapshot.novelStore?.characters || [] },
    { targetType: 'plot_thread', records: snapshot.novelStore?.plotThreads || [] },
    { targetType: 'setting_entity', records: snapshot.settingStore?.entities || [] },
    { targetType: 'setting_relation', records: snapshot.settingStore?.relations || [] },
    { targetType: 'setting_change_event', records: snapshot.settingStore?.changeEvents || [] },
    { targetType: 'story_block', records: snapshot.volumeStore?.volumes || [] }
  ]
}

function isAuthorityFacing(record = {}) {
  const status = String(record.status || 'accepted').trim().toLowerCase()
  return !['rejected', 'archived', 'deleted'].includes(status)
}

function buildChapterMaps(chapters = [], versions = []) {
  const chaptersByNum = new Map()
  const versionsById = new Map()
  for (const version of versions || []) {
    const id = version.id || version.versionId || version.version_id || ''
    if (id) versionsById.set(id, version)
  }
  for (const chapter of chapters || []) {
    const num = numberOf(chapter.chapterNum ?? chapter.chapter_num)
    if (num) chaptersByNum.set(num, chapter)
  }
  return { chaptersByNum, versionsById }
}

function isFinalChapterBefore(chapter, versionsById, currentChapterNum) {
  const num = numberOf(chapter?.chapterNum ?? chapter?.chapter_num)
  return num > 0 && num < currentChapterNum && isNonEmptyFinalChapter(chapter, versionsById)
}

function isNonEmptyFinalChapter(chapter, versionsById) {
  if (!chapter) return false
  const status = String(chapter.status || '').toLowerCase()
  const finalVersionId = chapter.finalVersionId || chapter.final_version_id || ''
  if (status !== 'final' && !finalVersionId) return false
  const version = finalVersionId ? versionsById.get(finalVersionId) : null
  const content = String(version?.content || '').trim()
  const wordCount = Number(chapter.wordCount ?? chapter.word_count ?? 0)
  return wordCount > 0 || content.length > 0
}

function isFinalVersion(version, chaptersByNum) {
  const type = String(version.versionType || version.version_type || '').toLowerCase()
  if (type === 'final') return true
  const chapter = chaptersByNum.get(numberOf(version.chapterNum ?? version.chapter_num))
  const finalVersionId = chapter?.finalVersionId || chapter?.final_version_id || ''
  return finalVersionId && finalVersionId === (version.id || version.versionId || version.version_id)
}

function dedupeIssues(issues) {
  const seen = new Set()
  const result = []
  for (const issue of issues || []) {
    const key = [
      issue.code,
      issue.severity,
      issue.targetType,
      issue.target,
      issue.reason
    ].join('|')
    if (seen.has(key)) continue
    seen.add(key)
    result.push(issue)
  }
  return result
}

function compactText(value, limit = 240) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length > limit ? `${text.slice(0, limit)}...` : text
}

function numberOf(value) {
  if (value === '' || value == null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}
