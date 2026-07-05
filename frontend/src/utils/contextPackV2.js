import {
  buildNarrativeVoiceContractV2,
  lintNarrativeVoiceContractV2,
  sanitizeNarrativeVoiceContractV2
} from './narrativeVoiceContract.js'
import { buildSceneExecutionCard } from './sceneExecutionContract.js'

const TRUSTED_COMMIT_STATUSES = new Set(['final', 'finalized', 'committed', 'accepted', 'trusted'])
const UNTRUSTED_COMMIT_STATUSES = new Set([
  'failed',
  'failure',
  'unfinalized',
  'draft',
  'drafting',
  'candidate',
  'ai_candidate',
  'empty',
  'empty_chapter',
  'plan_only',
  'pending',
  'pending_review',
  'tainted',
  'quarantined',
  'rejected'
])

const NARRATIVE_VOICE_FORBIDDEN_KEYS = [
  'factOverride',
  'factOverrides',
  'factsOverride',
  'stateOverride',
  'stateAuthority',
  'stageBoundary',
  'stageOverride',
  'creativeStageContract',
  'mustReveal',
  'mustResolve',
  'mustStopAt',
  'worldRules'
]

function unwrapMaybeRef(value) {
  return value?.value ?? value
}

function asArray(value) {
  const unwrapped = unwrapMaybeRef(value)
  return Array.isArray(unwrapped) ? unwrapped : []
}

function hasText(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function compactText(value, limit = 360) {
  const text = typeof value === 'string' ? value : JSON.stringify(value || '')
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (!normalized) return ''
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized
}

function lowerStatus(value) {
  return String(value || '').trim().toLowerCase()
}

function getProvenance(item = {}) {
  const provenance = item.provenance || item.sourceProvenance || item.snapshotProvenance || {}
  return {
    sourceChapterNum: numberOrNull(
      provenance.sourceChapterNum ??
      provenance.source_chapter_num ??
      item.sourceChapterNum ??
      item.source_chapter_num ??
      item.chapterNum ??
      item.chapter_num
    ),
    sourceVersionId:
      provenance.sourceVersionId ??
      provenance.source_version_id ??
      item.sourceVersionId ??
      item.source_version_id ??
      item.versionId ??
      item.version_id ??
      '',
    runId: provenance.runId ?? provenance.run_id ?? item.runId ?? item.run_id ?? '',
    finalizationId:
      provenance.finalizationId ??
      provenance.finalization_id ??
      item.finalizationId ??
      item.finalization_id ??
      '',
    commitStatus:
      lowerStatus(
        provenance.commitStatus ??
        provenance.commit_status ??
        item.commitStatus ??
        item.commit_status ??
        item.runStatus ??
        item.run_status ??
        ''
      )
  }
}

function numberOrNull(value) {
  if (value === '' || value == null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function chapterNumOf(item) {
  return numberOrNull(item?.chapterNum ?? item?.chapter_num ?? item?.chapter)
}

function versionIdOf(item) {
  return item?.id || item?.versionId || item?.version_id || ''
}

function isFinalChapter(chapter) {
  if (!chapter) return false
  return Boolean(
    chapter.finalVersionId ||
    chapter.final_version_id ||
    lowerStatus(chapter.status) === 'final'
  )
}

function isNonEmptyFinalChapter(chapter, versionsById) {
  if (!isFinalChapter(chapter)) return false
  const wordCount = Number(chapter.wordCount ?? chapter.word_count ?? 0)
  const finalVersionId = chapter.finalVersionId || chapter.final_version_id || ''
  const finalVersion = finalVersionId ? versionsById.get(finalVersionId) : null
  const content = finalVersion?.content || ''
  if (wordCount > 0) return true
  return String(content || '').trim().length > 0
}

function isAcceptedFact(item) {
  return lowerStatus(item?.status || 'accepted') === 'accepted'
}

function isAcceptedEvent(item) {
  return lowerStatus(item?.status || 'accepted') === 'accepted'
}

function isActiveEntity(item) {
  return lowerStatus(item?.status || 'active') === 'active'
}

function isTrustedThread(item) {
  const status = lowerStatus(item?.status || 'developing')
  return ['planted', 'developing', 'active', 'accepted', 'in_progress'].includes(status)
}

function isActiveRelation(item) {
  const status = lowerStatus(item?.status || 'active')
  return !['archived', 'rejected', 'tainted', 'quarantined'].includes(status)
}

function isTaintedOrQuarantined(item = {}) {
  const status = lowerStatus(item.status)
  const quarantineStatus = lowerStatus(item.quarantineStatus || item.quarantine_status)
  return Boolean(
    item.tainted ||
    item.isTainted ||
    item.quarantined ||
    item.isQuarantined ||
    status === 'tainted' ||
    status === 'quarantined' ||
    quarantineStatus === 'quarantined' ||
    quarantineStatus === 'active'
  )
}

function buildChapterMaps(chapters = [], versions = []) {
  const chaptersByNum = new Map()
  const versionsById = new Map()
  for (const version of versions || []) {
    const id = versionIdOf(version)
    if (id) versionsById.set(id, version)
  }
  for (const chapter of chapters || []) {
    const num = chapterNumOf(chapter)
    if (num) chaptersByNum.set(num, chapter)
  }
  return { chaptersByNum, versionsById }
}

function sourceTrustStatus(item, options = {}) {
  const currentChapterNum = Number(options.chapterNum || 0)
  const provenance = getProvenance(item)
  const sourceChapterNum = provenance.sourceChapterNum
  const commitStatus = provenance.commitStatus
  const hasProvenanceObject = value =>
    value && typeof value === 'object' && Object.values(value).some(entry => entry !== undefined && entry !== null && entry !== '')
  const hasExplicitProvenance = Boolean(
    hasProvenanceObject(item?.provenance) ||
    hasProvenanceObject(item?.sourceProvenance) ||
    hasProvenanceObject(item?.snapshotProvenance) ||
    item?.sourceChapterNum ||
    item?.source_chapter_num ||
    item?.sourceVersionId ||
    item?.source_version_id ||
    item?.commitStatus ||
    item?.commit_status ||
    item?.runStatus ||
    item?.run_status
  )

  if (isTaintedOrQuarantined(item)) {
    return { trusted: false, reason: 'tainted_or_quarantined', provenance, trustLevel: 'blocked' }
  }

  if (commitStatus && UNTRUSTED_COMMIT_STATUSES.has(commitStatus)) {
    return { trusted: false, reason: `commit_${commitStatus}`, provenance, trustLevel: 'blocked' }
  }

  if (sourceChapterNum && currentChapterNum && sourceChapterNum >= currentChapterNum) {
    return { trusted: false, reason: 'source_not_before_current_chapter', provenance, trustLevel: 'blocked' }
  }

  const chaptersByNum = options.chaptersByNum || new Map()
  const versionsById = options.versionsById || new Map()
  const sourceChapter = sourceChapterNum ? chaptersByNum.get(sourceChapterNum) : null
  const hasChapterLedger = chaptersByNum.size > 0

  if (sourceChapterNum && hasChapterLedger && !isNonEmptyFinalChapter(sourceChapter, versionsById)) {
    return { trusted: false, reason: 'source_chapter_not_final_or_empty', provenance, trustLevel: 'blocked' }
  }

  if (commitStatus && !TRUSTED_COMMIT_STATUSES.has(commitStatus)) {
    return { trusted: false, reason: `commit_${commitStatus}`, provenance, trustLevel: 'blocked' }
  }

  if (!hasExplicitProvenance) {
    return {
      trusted: true,
      reason: 'unknown_provenance',
      provenance,
      trustLevel: hasChapterLedger && sourceChapterNum ? 'degraded' : 'unknown'
    }
  }

  const hasFinalProof = Boolean(
    (commitStatus && TRUSTED_COMMIT_STATUSES.has(commitStatus)) ||
    provenance.finalizationId ||
    (sourceChapterNum && hasChapterLedger)
  )
  if (!hasFinalProof) {
    return {
      trusted: true,
      reason: 'unknown_provenance',
      provenance,
      trustLevel: 'degraded'
    }
  }

  return { trusted: true, reason: '', provenance, trustLevel: 'trusted' }
}

function authoritySafeTargetLabel(item, fallback = 'item') {
  const stableId = item?.id ||
    item?.entityId ||
    item?.entity_id ||
    item?.relationId ||
    item?.relation_id ||
    item?.threadId ||
    item?.thread_id ||
    item?.factId ||
    item?.fact_id
  if (stableId) return `${fallback}:${stableId}`
  const provenance = getProvenance(item)
  if (provenance.sourceVersionId) return `${fallback}:sourceVersion:${provenance.sourceVersionId}`
  if (provenance.sourceChapterNum) return `${fallback}:sourceChapter:${provenance.sourceChapterNum}`
  return `${fallback}:unidentified`
}

function collectAuthorityItems(items, predicate, options, issueTargetType, healthIssues) {
  const trusted = []
  const rejected = []
  for (const item of items || []) {
    if (!predicate(item)) continue
    const trust = sourceTrustStatus(item, options)
    if (trust.trusted) {
      trusted.push({ ...item, provenance: trust.provenance, trustLevel: trust.trustLevel || 'trusted' })
      if (trust.reason === 'unknown_provenance') {
        healthIssues.push({
          code: 'unknown_provenance',
          severity: 'warn',
          targetType: issueTargetType,
          target: authoritySafeTargetLabel(item, issueTargetType),
          reason: trust.trustLevel || 'unknown',
          provenance: trust.provenance
        })
      }
    } else {
      rejected.push({ item, trust, targetType: issueTargetType })
      healthIssues.push({
        code: trust.reason === 'tainted_or_quarantined' ? 'tainted_or_quarantined' : 'untrusted_source',
        severity: 'block',
        targetType: issueTargetType,
        target: authoritySafeTargetLabel(item, issueTargetType),
        reason: trust.reason,
        provenance: trust.provenance
      })
    }
  }
  return { trusted, rejected }
}

function currentChapterGoal(outline, chapterNum) {
  return asArray(outline?.nearChapters)
    .find(item => Number(item.chapterNum || item.chapter_num || 0) === Number(chapterNum)) || null
}

function futureRoadmap(outline, chapterNum) {
  return asArray(outline?.nearChapters)
    .filter(item => Number(item.chapterNum || item.chapter_num || 0) > Number(chapterNum))
    .map(item => ({
      chapterNum: Number(item.chapterNum || item.chapter_num || 0),
      title: item.title || '',
      goal: item.goal || '',
      conflict: item.conflict || '',
      turn: item.turn || '',
      handoff: item.handoff || ''
    }))
}

function extractFocusKeywords(text) {
  const source = String(text || '')
  const stopWords = new Set([
    'chapter',
    'title',
    'goal',
    'conflict',
    'turn',
    '本章',
    '当前',
    '必须',
    '确认',
    '状态',
    '剩余',
    '知道',
    '进入',
    '找到',
    '目标',
    '冲突'
  ])
  return new Set((source.match(/[#A-Za-z0-9_\u4e00-\u9fa5·-]{2,24}/g) || [])
    .map(item => item.replace(/^[#，,。；;：:\s]+|[，,。；;：:\s]+$/g, '').trim())
    .filter(item => item.length >= 2 && !stopWords.has(item)))
}

function buildCreativeFocus(goal, activeStoryBlock) {
  const text = [
    goal?.title,
    goal?.goal,
    goal?.conflict,
    goal?.turn,
    goal?.emotionalBeat,
    goal?.handoff,
    ...(asArray(goal?.doNotResolveYet)),
    activeStoryBlock?.coreGoal,
    activeStoryBlock?.mainConflict,
    activeStoryBlock?.currentSummary,
    ...(asArray(activeStoryBlock?.completedBeats)),
    ...(asArray(activeStoryBlock?.openQuestions)),
    ...(asArray(activeStoryBlock?.handoffToNext)),
    ...(asArray(activeStoryBlock?.continuityNotes))
  ].filter(hasText).join('\n')
  return { text, keywords: extractFocusKeywords(text) }
}

function valueToText(value) {
  if (value == null) return ''
  if (Array.isArray(value)) return value.map(valueToText).filter(Boolean).join('\n')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function textMatchesCreativeFocus(value, focus) {
  const source = valueToText(value)
  if (!source.trim()) return false
  if (!focus?.text && !focus?.keywords?.size) return true
  for (const name of focus.entityNames || []) {
    if (String(name || '').length >= 2 && source.includes(name)) return true
  }
  for (const keyword of focus.keywords || []) {
    if (keyword.length >= 2 && source.includes(keyword)) return true
  }
  return false
}

function alwaysCarryEntity(entity) {
  const importance = Number(entity?.importance || 0)
  const text = [entity?.category, entity?.summary, entity?.name].filter(Boolean).join('\n')
  return importance >= 10 && /主角|protagonist|核心/.test(text)
}

function entityMatchesCreativeFocus(entity, focus) {
  if (!focus?.text && !focus?.keywords?.size) return true
  if (alwaysCarryEntity(entity)) return true
  const names = [
    entity?.name,
    ...(Array.isArray(entity?.aliases) ? entity.aliases : [])
  ].filter(Boolean)
  if (names.some(name => focus.text.includes(name) || textMatchesCreativeFocus(name, focus))) return true
  return textMatchesCreativeFocus([
    entity?.entityType,
    entity?.category,
    entity?.summary,
    entity?.tags,
    entity?.profile
  ], focus)
}

function eventMatchesCreativeFocus(event, focus, selectedEntityIds) {
  if (!focus?.text && !focus?.keywords?.size) return true
  if (selectedEntityIds?.has(event.entityId || event.entity_id)) return true
  return textMatchesCreativeFocus([
    event?.entityName,
    event?.entity_name,
    event?.targetEntityName,
    event?.target_entity_name,
    event?.fieldPath,
    event?.field_path,
    event?.changeType,
    event?.change_type,
    event?.newValue,
    event?.new_value,
    event?.summary,
    event?.content,
    event?.evidence
  ], focus)
}

function factMatchesCreativeFocus(fact, focus) {
  if (!focus?.text && !focus?.keywords?.size) return true
  return textMatchesCreativeFocus([
    fact?.factType,
    fact?.fact_type,
    fact?.content,
    fact?.summary,
    fact?.fact,
    fact?.evidence,
    fact?.tags,
    fact?.threadTags,
    fact?.relatedPlotThreads,
    fact?.related_plot_threads
  ], focus)
}

function threadMatchesCreativeFocus(thread, focus) {
  if (!focus?.text && !focus?.keywords?.size) return true
  return textMatchesCreativeFocus([
    thread?.title,
    thread?.name,
    thread?.content,
    thread?.summary,
    thread?.description,
    thread?.tags,
    thread?.threadTags,
    thread?.relatedPlotThreads
  ], focus)
}

function safeCreativeRestrictions(goal, bible = {}) {
  const fromGoal = [
    ...(Array.isArray(goal?.doNotResolveYet) ? goal.doNotResolveYet : []),
    ...(Array.isArray(goal?.forbiddenDirections) ? goal.forbiddenDirections : [])
  ]
  const fromBible = Array.isArray(bible?.forbiddenDirections) ? bible.forbiddenDirections : []
  return [...fromGoal, ...fromBible]
    .map(item => String(item || '').trim())
    .filter(Boolean)
    .filter(item => !/^guard-only\s*[:：]/i.test(item))
    .filter(item => !/第\s*\d+\s*章才揭示|未来章才|后续才揭示/.test(item))
}

function pickActiveStoryBlock(volumes, chapterNum, options, healthIssues) {
  const current = (volumes || []).find(volume =>
    Number(chapterNum) >= Number(volume.startChapter || 0) &&
    Number(chapterNum) <= Number(volume.endChapter || 0)
  )
  if (!current) return null

  const report = current.stageSummaryReport || {}
  const snapshotProvenance = current.snapshotProvenance ||
    current.provenance ||
    report.snapshotProvenance ||
    report.sourceProvenance ||
    {}
  const trust = sourceTrustStatus({
    ...current,
    provenance: snapshotProvenance
  }, options)

  if (!trust.trusted) {
    healthIssues.push({
      code: 'untrusted_stage_snapshot',
      severity: 'block',
      targetType: 'story_block',
      target: current.id || current.title || 'active_story_block',
      reason: trust.reason,
      provenance: trust.provenance
    })
    return null
  } else if (trust.trustLevel !== 'trusted') {
    healthIssues.push({
      code: 'stage_degraded_provenance',
      severity: 'warn',
      targetType: 'story_block',
      target: current.id || current.title || 'active_story_block',
      reason: trust.trustLevel || 'unknown',
      provenance: trust.provenance
    })
  }

  const sourceType = trust.trusted
    ? (trust.trustLevel === 'trusted' ? 'final_state' : 'degraded_fallback')
    : 'untrusted_snapshot'
  return {
    id: current.id || '',
    title: current.title || `第 ${current.volumeNum || '?'} 卷`,
    volumeNum: current.volumeNum,
    chapterRange: `第${current.startChapter || '?'}-${current.endChapter || '?'}章`,
    status: current.status || 'planned',
    coreGoal: current.coreGoal || '',
    mainConflict: current.mainConflict || '',
    currentSummary: report.compactSummary || current.summary || '',
    completedBeats: asArray(report.completedBeats),
    openQuestions: asArray(report.openQuestions),
    handoffToNext: asArray(report.handoffToNext),
    continuityNotes: asArray(report.continuityNotes),
    provenance: trust.provenance,
    trustLevel: trust.trustLevel || (trust.trusted ? 'trusted' : 'blocked'),
    sourceExplanation: {
      sourceType,
      reason: trust.reason || '',
      canRebuildFromFinalFacts: trust.trustLevel === 'trusted',
      guidance: sourceType === 'degraded_fallback'
        ? 'Active stage lacks final/provenance support; treat as fallback planning context until rebuilt from finalized chapter facts.'
        : 'Active stage is supported by explicit trusted final-state provenance.'
    },
    rebuildHint: trust.trusted
      ? 'trusted_stage_snapshot'
      : 'rebuild_from_final_chapter_facts_before_creative_use'
  }
}

function buildFinalChapterEvidence(chapters, versionsById, chapterNum) {
  return (chapters || [])
    .filter(chapter => {
      const num = chapterNumOf(chapter)
      return num && num < Number(chapterNum || 0) && isNonEmptyFinalChapter(chapter, versionsById)
    })
    .sort((a, b) => chapterNumOf(a) - chapterNumOf(b))
    .map(chapter => {
      const finalVersionId = chapter.finalVersionId || chapter.final_version_id || ''
      const version = versionsById.get(finalVersionId)
      return {
        chapterNum: chapterNumOf(chapter),
        sourceVersionId: finalVersionId,
        summary: chapter.summary || '',
        contentEvidence: compactText(version?.content || '', 420),
        provenance: {
          sourceChapterNum: chapterNumOf(chapter),
          sourceVersionId: finalVersionId,
          finalizationId: chapter.finalizationId || chapter.finalization_id || '',
          commitStatus: 'final'
        }
      }
    })
}

function pendingFinalizationIssues(markers, chapterNum) {
  return (markers || [])
    .filter(marker => {
      const markerChapter = Number(marker.chapterNum || marker.chapter_num || 0)
      const status = lowerStatus(marker.commitStatus || marker.status || 'pending')
      return markerChapter > 0 &&
        markerChapter <= Number(chapterNum || 0) &&
        ['staged', 'validated', 'pending', 'in_progress', 'started', 'half_success', 'failed_after_chapter_commit'].includes(status)
    })
    .map(marker => ({
      code: 'finalization_pending',
      severity: 'block',
      targetType: 'finalization',
      target: `chapter:${marker.chapterNum || marker.chapter_num}`,
      reason: lowerStatus(marker.commitStatus || marker.status || 'pending'),
      provenance: {
        sourceChapterNum: Number(marker.chapterNum || marker.chapter_num || 0),
        sourceVersionId: marker.sourceVersionId || marker.source_version_id || '',
        runId: marker.runId || marker.run_id || '',
        finalizationId: marker.finalizationId || marker.finalization_id || '',
        commitStatus: lowerStatus(marker.commitStatus || marker.status || 'pending')
      }
    }))
}

function formatEntityLine(entity) {
  const profile = entity.profile || {}
  const facts = [
    entity.summary,
    profile.owner ? `owner=${profile.owner}` : '',
    profile.usesLeft ? `usesLeft=${profile.usesLeft}` : '',
    profile.location || profile.currentLocation ? `location=${profile.location || profile.currentLocation}` : '',
    profile.physicalStatus ? `physicalStatus=${profile.physicalStatus}` : '',
    profile.currentGoal ? `currentGoal=${profile.currentGoal}` : ''
  ].filter(hasText)
  return `- [${entity.entityType || 'setting'}] ${entity.name || '未命名'}${formatTrustLabel(entity)}：${facts.join('；') || '可信实体'}`
}

function formatEventLine(event) {
  const chapter = event.chapterNum ?? event.chapter_num ?? '?'
  const name = event.entityName || event.entity_name || event.targetEntityName || event.target_entity_name || '未知实体'
  const field = event.fieldPath || event.field_path || event.changeType || event.change_type || '状态'
  const value = event.newValue ?? event.new_value ?? event.summary ?? event.content ?? ''
  return `- 第${chapter}章${formatTrustLabel(event)}：${name}.${field} -> ${value}`
}

function formatFactLine(fact) {
  const chapter = fact.chapterNum ?? fact.chapter_num ?? '?'
  const type = fact.factType || fact.fact_type || 'fact'
  return `- 第${chapter}章[${type}]${formatTrustLabel(fact)} ${fact.content || fact.summary || fact.fact || ''}`
}

function formatTrustLabel(item = {}) {
  const level = item.trustLevel || 'trusted'
  return level && level !== 'trusted' ? ` [trustLevel=${level}]` : ''
}

function buildSettingLibrary(entities) {
  if (!entities.length) return ''
  return ['### 可信设定实体', ...entities.map(formatEntityLine)].join('\n')
}

function buildRecentSettingChanges(events) {
  if (!events.length) return ''
  return events
    .slice()
    .sort((a, b) => Number(b.chapterNum || b.chapter_num || 0) - Number(a.chapterNum || a.chapter_num || 0))
    .slice(0, 10)
    .map(formatEventLine)
    .join('\n')
}

function buildRecentFacts(facts, finalEvidence) {
  const factLines = facts
    .slice()
    .sort((a, b) => Number(b.chapterNum || b.chapter_num || 0) - Number(a.chapterNum || a.chapter_num || 0))
    .slice(0, 12)
    .map(formatFactLine)
  const evidenceLines = finalEvidence
    .slice(-3)
    .map(item => item.contentEvidence ? `- 第${item.chapterNum}章定稿证据：${item.contentEvidence}` : '')
    .filter(Boolean)
  return [...factLines, ...evidenceLines].join('\n')
}

function relationEntityId(relation, key) {
  if (key === 'source') return relation.sourceEntityId || relation.source_entity_id || ''
  return relation.targetEntityId || relation.target_entity_id || ''
}

function relationEntityName(relation, key) {
  if (key === 'source') {
    return relation.sourceEntityName || relation.source_entity_name || relation.sourceName || relation.source_name || relationEntityId(relation, 'source')
  }
  return relation.targetEntityName || relation.target_entity_name || relation.targetName || relation.target_name || relationEntityId(relation, 'target')
}

function relationMatchesCreativeEntities(relation, creativeEntityIds) {
  if (!creativeEntityIds?.size) return false
  return creativeEntityIds.has(relationEntityId(relation, 'source')) ||
    creativeEntityIds.has(relationEntityId(relation, 'target'))
}

function buildRelationships(relations) {
  if (!relations.length) return ''
  return relations.map(relation => {
    const source = relationEntityName(relation, 'source') || '未知实体'
    const target = relationEntityName(relation, 'target') || '未知实体'
    const type = relation.relationType || relation.relation_type || '关系'
    const summary = relation.summary || relation.content || relation.description || ''
    const detail = summary ? `：${summary}` : ''
    return `- ${source} --${type}--> ${target}${formatTrustLabel(relation)}${detail}`
  }).join('\n')
}

function buildStateLedger(stateAuthority) {
  const lines = [
    ...stateAuthority.settingEntities.map(formatEntityLine),
    ...stateAuthority.settingChangeEvents.map(formatEventLine),
    ...stateAuthority.canonFacts.map(formatFactLine)
  ].filter(Boolean)

  if (!lines.length) return ''
  return [
    '## ContextPack v2 stateAuthority',
    ...lines,
    '以上内容只来自定稿前序章节或带 trustLevel 标记的 legacy 记录；失败、未定稿、空章、tainted、quarantined 来源已排除。'
  ].join('\n')
}

function formatChapterGoal(goal) {
  if (!goal) return null
  return {
    title: goal.title || '',
    goal: goal.goal || '',
    conflict: goal.conflict || '',
    turn: goal.turn || '',
    emotionalBeat: goal.emotionalBeat || '',
    doNotResolveYet: asArray(goal.doNotResolveYet),
    handoff: goal.handoff || ''
  }
}

function formatVolumeStageForCreative(stage) {
  if (!stage) return null
  return {
    title: stage.title,
    volumeNum: stage.volumeNum,
    chapterRange: stage.chapterRange,
    status: stage.status,
    coreGoal: stage.coreGoal,
    mainConflict: stage.mainConflict,
    currentSummary: stage.currentSummary,
    completedBeats: stage.completedBeats,
    openQuestions: stage.openQuestions,
    handoffToNext: stage.handoffToNext,
    continuityNotes: stage.continuityNotes,
    rebuildHint: stage.rebuildHint
  }
}

export function lintNarrativeVoiceContract(contract = {}) {
  const lint = lintNarrativeVoiceContractV2(contract)
  return {
    ok: lint.ok,
    issues: lint.issues.map(issue => issue.message || String(issue))
  }
}

export function buildContextPackV2({
  novelStore = {},
  chapterNum,
  settingStore = null,
  volumeStore = null,
  correctionTaskStore = null,
  contextOptions = {}
} = {}) {
  contextOptions = contextOptions && typeof contextOptions === 'object' ? contextOptions : {}
  const bible = unwrapMaybeRef(novelStore.bible) || {}
  const outline = unwrapMaybeRef(novelStore.outline) || {}
  const canonFacts = asArray(novelStore.canonFacts)
  const characters = asArray(novelStore.characters)
  const plotThreads = asArray(novelStore.plotThreads)
  const settingEntities = asArray(settingStore?.entities)
  const settingRelations = asArray(settingStore?.relations)
  const settingChangeEvents = asArray(settingStore?.changeEvents)
  const volumes = asArray(volumeStore?.volumes)
  const chapters = asArray(contextOptions.chapters)
  const chapterVersions = asArray(contextOptions.chapterVersions)
  const savedBeatPlans = asArray(contextOptions.savedBeatPlans)
  const finalizationMarkers = asArray(contextOptions.finalizationMarkers)
  const { chaptersByNum, versionsById } = buildChapterMaps(chapters, chapterVersions)
  const healthIssues = pendingFinalizationIssues(finalizationMarkers, chapterNum)
  const trustOptions = { chapterNum, chaptersByNum, versionsById }

  const trustedFacts = collectAuthorityItems(canonFacts, isAcceptedFact, trustOptions, 'canon_fact', healthIssues)
  const trustedEntities = collectAuthorityItems(settingEntities, isActiveEntity, trustOptions, 'setting_entity', healthIssues)
  const trustedEvents = collectAuthorityItems(settingChangeEvents, isAcceptedEvent, trustOptions, 'setting_change_event', healthIssues)
  const trustedCharacters = collectAuthorityItems(characters, item => lowerStatus(item?.status || 'active') === 'active', trustOptions, 'character', healthIssues)
  const trustedRelations = collectAuthorityItems(settingRelations, isActiveRelation, trustOptions, 'setting_relation', healthIssues)
  const trustedThreads = collectAuthorityItems(plotThreads, isTrustedThread, trustOptions, 'plot_thread', healthIssues)
  const activeStoryBlock = pickActiveStoryBlock(volumes, chapterNum, trustOptions, healthIssues)
  const finalChapterEvidence = buildFinalChapterEvidence(chapters, versionsById, chapterNum)
  const goal = currentChapterGoal(outline, chapterNum)
  const rawVoiceContract = {
    styleBible: [
      bible.styleBible,
      contextOptions.styleBible,
      contextOptions.styleMethodBrief,
      contextOptions.styleStandardBrief
    ].filter(hasText),
    tone: contextOptions.narrativeVoiceContract?.tone || bible.styleBible || '',
    rhythm: contextOptions.narrativeVoiceContract?.rhythm || '',
    diction: contextOptions.narrativeVoiceContract?.diction || '',
    writingProfile: contextOptions.narrativeVoiceContract?.writingProfile || bible.writingProfile || null,
    ...contextOptions.narrativeVoiceContract
  }
  const voiceLint = lintNarrativeVoiceContractV2(rawVoiceContract)
  const voiceContract = sanitizeNarrativeVoiceContract(
    buildNarrativeVoiceContractV2(rawVoiceContract)
  )
  if (!voiceLint.ok) {
    healthIssues.push({
      code: 'narrative_voice_contract_violation',
      severity: 'warn',
      targetType: 'narrative_voice_contract',
      target: 'narrativeVoiceContract',
      reason: voiceLint.issues.map(issue => issue.message || issue).join('；'),
      provenance: {}
    })
  }

  const stateAuthority = {
    schemaVersion: 'state-authority-v1',
    currentChapterNum: Number(chapterNum || 0),
    finalChapters: finalChapterEvidence.map(item => ({
      chapterNum: item.chapterNum,
      sourceVersionId: item.sourceVersionId,
      summary: item.summary,
      contentEvidence: item.contentEvidence,
      provenance: item.provenance
    })),
    canonFacts: trustedFacts.trusted,
    settingEntities: trustedEntities.trusted,
    settingRelations: trustedRelations.trusted.filter(relation => {
      const selectedIds = new Set(trustedEntities.trusted.map(entity => entity.id).filter(Boolean))
      if (!selectedIds.size) return false
      return selectedIds.has(relation.sourceEntityId || relation.source_entity_id) &&
        selectedIds.has(relation.targetEntityId || relation.target_entity_id) &&
        !isTaintedOrQuarantined(relation)
    }),
    settingChangeEvents: trustedEvents.trusted,
    characters: trustedCharacters.trusted,
    plotThreads: trustedThreads.trusted.filter(item => !isTaintedOrQuarantined(item)),
    activeStoryBlock,
    rejectedSources: [
      ...trustedFacts.rejected,
      ...trustedEntities.rejected,
      ...trustedEvents.rejected,
      ...trustedCharacters.rejected,
      ...trustedRelations.rejected,
      ...trustedThreads.rejected
    ].map(({ item, trust, targetType }) => ({
      target: authoritySafeTargetLabel(item, targetType || 'rejected_source'),
      reason: trust.reason,
      provenance: trust.provenance
    }))
  }
  const creativeFocus = buildCreativeFocus(goal, activeStoryBlock)
  const creativeEntityIds = stateAuthority.settingEntities
    .filter(entity => entityMatchesCreativeFocus(entity, creativeFocus))
    .map(entity => entity.id)
    .filter(Boolean)

  const creativeStageContract = {
    schemaVersion: 'creative-stage-contract-v1',
    chapterNum: Number(chapterNum || 0),
    chapterGoal: formatChapterGoal(goal),
    allowedScope: {
      goal: goal?.goal || '',
      conflict: goal?.conflict || '',
      turn: goal?.turn || '',
      emotionalBeat: goal?.emotionalBeat || ''
    },
    stopAt: goal?.handoff || asArray(goal?.doNotResolveYet).join('；') || '',
    safeCreativeRestrictions: safeCreativeRestrictions(goal, bible),
    focusKeywords: [...creativeFocus.keywords],
    trustedSettingEntityIds: creativeEntityIds,
    activeStoryBlock: formatVolumeStageForCreative(activeStoryBlock),
    beatPlanPolicy: 'current_chapter_beat_plan_is_plan_evidence_only; final_chapter_facts_override_saved_beat_plans'
  }

  const guardSnapshot = {
    schemaVersion: 'guard-snapshot-v1',
    deterministicOnly: true,
    futureRoadmap: futureRoadmap(outline, chapterNum),
    forbiddenDirections: Array.isArray(bible.forbiddenDirections) ? bible.forbiddenDirections : [],
    savedBeatPlans: savedBeatPlans.map(plan => ({
      chapterNum: Number(plan.chapterNum || plan.chapter_num || 0),
      content: plan.content || '',
      provenance: getProvenance(plan),
      authority: 'plan_evidence_only'
    })),
    rejectedSources: stateAuthority.rejectedSources,
    correctionTasks: asArray(correctionTaskStore?.tasks || correctionTaskStore?.activeTasks)
  }

  const healthCheck = {
    schemaVersion: 'context-health-v1',
    blocked: healthIssues.some(issue => issue.severity === 'block'),
    issues: healthIssues,
    checkedAt: new Date(0).toISOString()
  }

  return {
    schemaVersion: 'context-pack-v2',
    stateAuthority,
    creativeStageContract,
    narrativeVoiceContract: {
      ...voiceContract,
      lint: voiceLint
    },
    guardSnapshot,
    healthCheck
  }
}

function sanitizeNarrativeVoiceContract(contract = {}) {
  return sanitizeNarrativeVoiceContractV2(contract)
}

function stripNarrativeVoiceForbidden(value) {
  if (Array.isArray(value)) return value.map(stripNarrativeVoiceForbidden)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !NARRATIVE_VOICE_FORBIDDEN_KEYS.includes(key))
      .map(([key, child]) => [key, stripNarrativeVoiceForbidden(child)])
  )
}

export function buildCreativeContextFromPack(pack, overrides = {}) {
  const stateAuthority = pack?.stateAuthority || {}
  const creativeStage = pack?.creativeStageContract || {}
  const voice = pack?.narrativeVoiceContract || {}
  const chapterGoal = creativeStage.chapterGoal || null
  const activeStoryBlock = creativeStage.activeStoryBlock || null
  const focus = {
    text: [
      chapterGoal?.title,
      chapterGoal?.goal,
      chapterGoal?.conflict,
      chapterGoal?.turn,
      chapterGoal?.emotionalBeat,
      chapterGoal?.handoff,
      ...(asArray(chapterGoal?.doNotResolveYet)),
      activeStoryBlock?.coreGoal,
      activeStoryBlock?.mainConflict,
      activeStoryBlock?.currentSummary,
      ...(asArray(activeStoryBlock?.completedBeats)),
      ...(asArray(activeStoryBlock?.openQuestions)),
      ...(asArray(activeStoryBlock?.handoffToNext)),
      ...(asArray(activeStoryBlock?.continuityNotes))
    ].filter(hasText).join('\n'),
    keywords: new Set(creativeStage.focusKeywords || [])
  }
  const selectedEntityIds = new Set(creativeStage.trustedSettingEntityIds || [])
  const creativeEntities = (stateAuthority.settingEntities || [])
    .filter(entity => selectedEntityIds.has(entity.id) || entityMatchesCreativeFocus(entity, focus))
  focus.entityNames = new Set(creativeEntities.flatMap(entity => [
    entity?.name,
    ...(Array.isArray(entity?.aliases) ? entity.aliases : [])
  ]).filter(Boolean))
  const creativeEvents = (stateAuthority.settingChangeEvents || [])
    .filter(event => eventMatchesCreativeFocus(event, focus, selectedEntityIds))
  const creativeFacts = (stateAuthority.canonFacts || [])
    .filter(fact => factMatchesCreativeFocus(fact, focus))
  const creativeThreads = (stateAuthority.plotThreads || [])
    .filter(thread => threadMatchesCreativeFocus(thread, focus))
  const creativeRelationIds = new Set(creativeEntities.map(entity => entity.id).filter(Boolean))
  const creativeRelations = (stateAuthority.settingRelations || [])
    .filter(relation => relationMatchesCreativeEntities(relation, creativeRelationIds))
  const creativeAuthority = {
    ...stateAuthority,
    settingEntities: creativeEntities,
    settingRelations: creativeRelations,
    settingChangeEvents: creativeEvents,
    canonFacts: creativeFacts,
    plotThreads: creativeThreads
  }
  const stateLedger = buildStateLedger(creativeAuthority)
  const settingLibrary = buildSettingLibrary(creativeEntities)
  const relationships = buildRelationships(creativeRelations)
  const recentSettingChanges = buildRecentSettingChanges(creativeEvents)
  const recentFacts = buildRecentFacts(creativeFacts, stateAuthority.finalChapters || [])

  const creativeContext = {
    contextPackVersion: pack?.schemaVersion || 'context-pack-v2',
    chapterNum: overrides.chapterNum || creativeStage.chapterNum || stateAuthority.currentChapterNum,
    chapterGoal,
    nearOutline: chapterGoal ? [chapterGoal] : [],
    volumeStage: activeStoryBlock,
    creativeBoundary: [
      creativeStage.allowedScope?.goal ? `本章目标：${creativeStage.allowedScope.goal}` : '',
      creativeStage.allowedScope?.conflict ? `本章冲突：${creativeStage.allowedScope.conflict}` : '',
      creativeStage.stopAt ? `停靠点：${creativeStage.stopAt}` : ''
    ].filter(Boolean).join('\n'),
    settingLibrary,
    recentSettingChanges,
    stateLedger,
    recentFacts,
    threadFacts: recentFacts,
    characters: (stateAuthority.characters?.length
      ? stateAuthority.characters.filter(character => entityMatchesCreativeFocus(character, focus))
      : creativeEntities.filter(entity => entity.entityType === 'character'))
      .map(character => ({ ...character, trustLabel: formatTrustLabel(character) })),
    relationships,
    plotThreads: creativeThreads,
    forbiddenDirections: creativeStage.safeCreativeRestrictions || [],
    styleBible: '',
    styleMethodBrief: '',
    styleStandardBrief: '',
    narrativeVoiceContract: voice,
    stateAuthority: creativeAuthority,
    creativeStageContract: creativeStage,
    beatPlan: overrides.beatPlan || '',
    contextHealth: summarizeHealthForCreative(pack?.healthCheck)
  }
  creativeContext.sceneExecutionCard = buildSceneExecutionCard(creativeContext)
  return creativeContext
}

function summarizeHealthForCreative(health) {
  if (!health) return null
  const issues = Array.isArray(health.issues) ? health.issues : []
  const blockingIssues = issues.filter(issue => issue?.severity === 'block')
  const warningIssues = issues.filter(issue => issue?.severity !== 'block')
  return {
    schemaVersion: health.schemaVersion || 'context-health-v1',
    blocked: Boolean(health.blocked),
    issueCount: issues.length,
    blockingIssueCodes: uniqueIssueCodes(blockingIssues),
    warningIssueCodes: uniqueIssueCodes(warningIssues)
  }
}

function uniqueIssueCodes(issues) {
  return [...new Set((issues || []).map(issue => issue?.code).filter(Boolean))]
}

export function assertContextPackHealthy(pack) {
  const health = pack?.healthCheck
  if (!health?.blocked) return true
  const details = (health.issues || [])
    .filter(issue => issue.severity === 'block')
    .map(issue => `${issue.code}:${issue.target}:${issue.reason}`)
    .join('; ')
  throw new Error(`ContextPack health check blocked: ${details || 'unknown'}`)
}
