export const NON_CHARACTER_NAME_TAILS = Object.freeze([
  '会',
  '商会',
  '司',
  '盟',
  '宗',
  '门派',
  '宗门',
  '官署',
  '机构',
  '组织',
  '势力',
  '帮',
  '阁',
  '堂',
  '府',
  '衙',
  '院',
  '坊',
  '寺',
  '观',
  '客栈',
  '粮栈',
  '仓',
  '仓库',
  '地窖',
  '密室',
  '街',
  '巷',
  '镇',
  '村',
  '城',
  '山',
  '河',
  '湖',
  '港',
  '桥'
])

function field(row, camelName, snakeName = camelName) {
  if (!row || typeof row !== 'object') return undefined
  return row[camelName] ?? row[snakeName]
}

function normalizeStatus(value, fallback = 'active') {
  const status = String(value ?? fallback).trim()
  return status || fallback
}

function numberOf(value, fallback = 0) {
  const number = Number(value)
  return Number.isFinite(number) ? number : fallback
}

function chapterNumOf(row) {
  return numberOf(field(row, 'chapterNum', 'chapter_num'))
}

function finalVersionIdOf(row) {
  return String(field(row, 'finalVersionId', 'final_version_id') || '')
}

function entityIdOf(row) {
  return String(field(row, 'id') || '')
}

function entityTypeOf(row) {
  return String(field(row, 'entityType', 'entity_type') || '').trim()
}

function entityNameOf(row) {
  return String(field(row, 'name') || '').trim()
}

function relationIdOf(row) {
  return String(field(row, 'id') || '')
}

function relationSourceIdOf(row) {
  return String(field(row, 'sourceEntityId', 'source_entity_id') || '')
}

function relationTargetIdOf(row) {
  return String(field(row, 'targetEntityId', 'target_entity_id') || '')
}

function isActiveRow(row) {
  return normalizeStatus(field(row, 'status')) === 'active'
}

function uniqueCountByRelationId(items) {
  return new Set(items.map(item => relationIdOf(item)).filter(Boolean)).size
}

export function isSyntheticEndpointName(name = '') {
  return String(name || '').trim().includes('_')
}

export function isLikelyNonCharacterName(name = '') {
  const text = String(name || '').trim()
  if (!text) return false
  return NON_CHARACTER_NAME_TAILS.some(tail => text.endsWith(tail))
}

export function buildProjectFreezeStatus({
  chapters = [],
  requiredFinalChapter,
  expectedFinalVersionId = '',
  forbiddenChapters = []
} = {}) {
  const blockers = []
  const requiredChapterNum = numberOf(requiredFinalChapter)
  const shouldCheckRequiredChapter = requiredChapterNum > 0
  const forbiddenSet = new Set((Array.isArray(forbiddenChapters) ? forbiddenChapters : [])
    .map(Number)
    .filter(Number.isFinite))
  const chapterRows = Array.isArray(chapters) ? chapters : []
  const requiredChapter = shouldCheckRequiredChapter
    ? chapterRows.find(row => chapterNumOf(row) === requiredChapterNum) || null
    : null

  if (shouldCheckRequiredChapter && !requiredChapter) {
    blockers.push({
      code: 'requiredFinalChapterMissing',
      chapterNum: requiredChapterNum
    })
  } else if (shouldCheckRequiredChapter) {
    const status = normalizeStatus(field(requiredChapter, 'status'), '')
    if (status !== 'final') {
      blockers.push({
        code: 'requiredChapterNotFinal',
        chapterNum: requiredChapterNum,
        status
      })
    }
    if (expectedFinalVersionId && finalVersionIdOf(requiredChapter) !== expectedFinalVersionId) {
      blockers.push({
        code: 'finalVersionMismatch',
        chapterNum: requiredChapterNum,
        expectedFinalVersionId,
        actualFinalVersionId: finalVersionIdOf(requiredChapter)
      })
    }
  }

  const forbiddenHits = chapterRows
    .filter(row => forbiddenSet.has(chapterNumOf(row)))
    .map(row => ({
      chapterNum: chapterNumOf(row),
      status: normalizeStatus(field(row, 'status'), ''),
      title: String(field(row, 'title') || '')
    }))
  for (const hit of forbiddenHits) {
    blockers.push({
      code: 'unexpectedChapterStarted',
      chapterNum: hit.chapterNum,
      status: hit.status,
      title: hit.title
    })
  }

  return {
    ok: blockers.length === 0,
    chapter88FinalVersionId: requiredChapterNum === 88 ? finalVersionIdOf(requiredChapter) : '',
    requiredFinalChapter: shouldCheckRequiredChapter ? requiredChapterNum : null,
    requiredFinalVersionId: requiredChapter ? finalVersionIdOf(requiredChapter) : '',
    forbiddenChapterHits: forbiddenHits,
    chapter89Exists: forbiddenSet.has(89)
      ? forbiddenHits.some(hit => hit.chapterNum === 89)
      : chapterRows.some(row => chapterNumOf(row) === 89),
    blockers
  }
}

export function summarizeRelationshipRisks({
  entities = [],
  relations = []
} = {}) {
  const activeEntities = new Map((Array.isArray(entities) ? entities : [])
    .filter(isActiveRow)
    .map(entity => [entityIdOf(entity), entity]))
  const activeRelations = (Array.isArray(relations) ? relations : []).filter(isActiveRow)
  const syntheticRelations = []
  const selfRelations = []
  const wrongLayerRelations = []
  const missingEndpointRelations = []

  for (const relation of activeRelations) {
    const sourceId = relationSourceIdOf(relation)
    const targetId = relationTargetIdOf(relation)
    const source = activeEntities.get(sourceId)
    const target = activeEntities.get(targetId)

    if (!source || !target) {
      missingEndpointRelations.push(relation)
    }

    if (source && isSyntheticEndpointName(entityNameOf(source))) syntheticRelations.push(relation)
    else if (target && isSyntheticEndpointName(entityNameOf(target))) syntheticRelations.push(relation)

    if (sourceId && sourceId === targetId) {
      selfRelations.push(relation)
    }

    const sourceWrongLayer = entityTypeOf(source) === 'character' && isLikelyNonCharacterName(entityNameOf(source))
    const targetWrongLayer = entityTypeOf(target) === 'character' && isLikelyNonCharacterName(entityNameOf(target))
    if (sourceWrongLayer || targetWrongLayer) {
      wrongLayerRelations.push(relation)
    }
  }

  return {
    activeRelationCount: activeRelations.length,
    activeSyntheticRelationCount: uniqueCountByRelationId(syntheticRelations),
    activeSelfRelationCount: uniqueCountByRelationId(selfRelations),
    activeWrongLayerRelationCount: uniqueCountByRelationId(wrongLayerRelations),
    activeMissingEndpointRelationCount: uniqueCountByRelationId(missingEndpointRelations)
  }
}

export function countPendingSettings(snapshot = {}, options = {}) {
  if (Number.isFinite(Number(snapshot.pendingSettingsCount))) {
    return Number(snapshot.pendingSettingsCount)
  }
  const pendingStatuses = new Set((options.pendingStatuses || ['pending_review'])
    .map(value => String(value || '').trim())
    .filter(Boolean))
  return (Array.isArray(snapshot.settingChangeEvents) ? snapshot.settingChangeEvents : [])
    .filter(event => pendingStatuses.has(normalizeStatus(field(event, 'status'), 'pending_review')))
    .length
}

export function summarizeProjectHealthSnapshot(snapshot = {}, options = {}) {
  const freezeStatus = buildProjectFreezeStatus({
    chapters: snapshot.chapters || snapshot.chapterRows || [],
    requiredFinalChapter: options.requiredFinalChapter,
    expectedFinalVersionId: options.expectedFinalVersionId,
    forbiddenChapters: options.forbiddenChapters || []
  })
  const pendingSettingsCount = countPendingSettings(snapshot, options)
  const relationshipAudit = summarizeRelationshipRisks({
    entities: snapshot.settingEntities || snapshot.entities || [],
    relations: snapshot.settingRelations || snapshot.relations || []
  })
  const blockers = [...freezeStatus.blockers]
  if (pendingSettingsCount > 0) {
    blockers.push({
      code: 'pendingSettingsNonZero',
      pendingSettingsCount
    })
  }
  for (const [fieldName, count] of Object.entries(relationshipAudit)) {
    if (fieldName === 'activeRelationCount') continue
    if (count > 0) {
      blockers.push({
        code: 'relationRiskNonZero',
        relationRiskField: fieldName,
        count
      })
    }
  }

  return {
    ok: blockers.length === 0,
    projectId: snapshot.projectId || options.projectId || '',
    chapter89Exists: freezeStatus.chapter89Exists,
    chapter88FinalVersionId: freezeStatus.chapter88FinalVersionId,
    pendingSettingsCount,
    activeRelationCount: relationshipAudit.activeRelationCount,
    relationshipAudit,
    freezeStatus,
    blockers
  }
}
