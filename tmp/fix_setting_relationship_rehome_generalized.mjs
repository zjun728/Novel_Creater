import fs from 'node:fs'
import path from 'node:path'
import { buildRelationshipRehomeAudit } from './audit_setting_relationship_rehome_generalized.mjs'

const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8000/api'
const PROJECT_ID = process.env.PROJECT_ID || '2da6152a-c083-41ee-8bcb-f11b0fae387d'
const QA_DIR = path.join(process.cwd(), 'tmp', 'realistic-flow-qa')
const OUT_JSON = process.env.RELATION_FIX_JSON || path.join(QA_DIR, 'latest-setting-relationship-rehome-generalized-fix.json')
const OUT_MD = process.env.RELATION_FIX_MD || path.join(QA_DIR, 'latest-setting-relationship-rehome-generalized-fix.md')

function isSyntheticName(name = '') {
  return String(name || '').trim().includes('_')
}

function isOrgishName(name = '') {
  return /(星债会|巡天司|商盟|会|司|盟|宗|门派|宗门|商会|官署|机构|组织|势力|帮|阁|堂|府|衙|院)$/.test(String(name || '').trim())
}

function splitSyntheticName(name = '') {
  const parts = String(name || '').split('_').map(item => item.trim()).filter(Boolean)
  if (parts.length < 2) return []
  return [parts[0], parts[1], parts.slice(2).join('_')]
}

function normalizeNameCore(name = '') {
  return String(name || '')
    .replace(/[（(][^（）()]*[）)]/g, '')
    .replace(/\s+/g, '')
    .trim()
}

function parseJsonish(value, fallback = {}) {
  if (!value) return fallback
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch {
    return fallback
  }
}

async function api(pathname, options = {}) {
  const response = await fetch(`${API_BASE}${pathname}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options
  })
  const text = await response.text()
  if (!response.ok) throw new Error(`${options.method || 'GET'} ${pathname}: ${response.status} ${response.statusText}: ${text.slice(0, 800)}`)
  return text ? JSON.parse(text) : null
}

async function getState() {
  const [entities, relations] = await Promise.all([
    api(`/projects/${PROJECT_ID}/settings/entities`),
    api(`/projects/${PROJECT_ID}/settings/relations`)
  ])
  return { entities, relations }
}

function entityByIdMap(entities) {
  return new Map(entities.map(entity => [entity.id, entity]))
}

function entitiesByNameMap(entities) {
  const map = new Map()
  for (const entity of entities) {
    if (!entity.name) continue
    if (!map.has(entity.name)) map.set(entity.name, [])
    map.get(entity.name).push(entity)
  }
  return map
}

function preferRealEntity(candidates = [], fallbackType = '') {
  if (!candidates.length) return null
  const active = candidates.filter(entity => (entity.status || 'active') === 'active')
  const source = active.length ? active : candidates
  const preferredType = fallbackType || ''
  return source.find(entity => preferredType && entity.entityType === preferredType) ||
    source.find(entity => isOrgishName(entity.name) && entity.entityType === 'faction') ||
    source.find(entity => entity.entityType !== 'character') ||
    source.find(entity => !isSyntheticName(entity.name)) ||
    source[0]
}

function resolveEntityByName(entities, name, fallbackType = '', excludeIds = []) {
  const excluded = new Set(excludeIds.filter(Boolean))
  const cleanName = String(name || '').trim()
  const coreName = normalizeNameCore(cleanName)
  const candidates = entities.filter(entity => {
    if (excluded.has(entity.id)) return false
    if (isSyntheticName(entity.name)) return false
    if ((entity.status || 'active') !== 'active') return false
    const entityCore = normalizeNameCore(entity.name)
    return entity.name === cleanName ||
      entityCore === coreName ||
      String(entity.name || '').startsWith(`${cleanName}（`) ||
      String(entity.name || '').startsWith(`${cleanName}(`)
  })
  return preferRealEntity(candidates, fallbackType)
}

function mergeTags(entity, ...tags) {
  const existing = Array.isArray(entity.tags) ? entity.tags : []
  return [...new Set([...existing, ...tags].filter(Boolean))]
}

function appendDynamicProfileEntry(profile, fieldName, entry) {
  const next = { ...(profile || {}) }
  const existing = Array.isArray(next[fieldName]) ? next[fieldName] : []
  const duplicated = existing.some(item =>
    item?.value === entry.value &&
    item?.evidence === entry.evidence &&
    item?.chapterNum === entry.chapterNum
  )
  next[fieldName] = duplicated ? existing : [...existing, entry]
  next._dynamicStateMeta = {
    ...(next._dynamicStateMeta || {}),
    [fieldName]: {
      chapterNum: entry.chapterNum,
      lastUpdatedChapter: entry.chapterNum,
      evidence: entry.evidence || '',
      confidence: entry.confidence ?? null
    }
  }
  return next
}

function selfRelationProfileField(relation) {
  const text = `${relation.relationType || ''} ${relation.summary || ''} ${relation.evidence || ''}`
  if (/(机制|规则|规矩|债本|账本|问询权|通行证|凭证|铜扣|欠条)/.test(text)) return 'internalMechanisms'
  if (/(行动|正在|已|试图|追|问|查|带|拿|逃|躲|守|等|偿还|承担|使用)/.test(text)) return 'currentActions'
  return 'observedFacts'
}

function relationLabel(relation, entityMap) {
  const source = entityMap.get(relation.sourceEntityId)
  const target = entityMap.get(relation.targetEntityId)
  return `${source?.name || '未知'}(${source?.entityType || ''}) -> ${relation.relationType || '关系'} -> ${target?.name || '未知'}(${target?.entityType || ''})`
}

async function markEntityMerged(entity, reason) {
  const summary = String(entity.summary || '')
  await api(`/projects/${PROJECT_ID}/settings/entities/${entity.id}`, {
    method: 'PUT',
    body: JSON.stringify({
      status: 'merged',
      summary: summary.includes('错误占位')
        ? summary
        : `错误占位（已合并）：${summary || reason}`,
      tags: mergeTags(entity, '错误占位', '已合并'),
      profile: parseJsonish(entity.profile, {})
    })
  })
}

async function markWrongLayerFaction(entity) {
  await api(`/projects/${PROJECT_ID}/settings/entities/${entity.id}`, {
    method: 'PUT',
    body: JSON.stringify({
      entityType: 'faction',
      tags: mergeTags(entity, '组织归位'),
      profile: parseJsonish(entity.profile, {})
    })
  })
}

async function rehomeSelfRelation(relation, entity) {
  const profile = parseJsonish(entity.profile, {})
  const fieldName = selfRelationProfileField(relation)
  const nextProfile = appendDynamicProfileEntry(profile, fieldName, {
    value: relation.summary || relation.evidence || `${entity.name} 的自我关系事件已归位。`,
    evidence: relation.evidence || '',
    chapterNum: relation.chapterNum || null,
    confidence: null,
    sourceField: 'setting_relations.self_relation',
    relationType: relation.relationType || '关系',
    targetEntityName: entity.name || ''
  })
  await api(`/projects/${PROJECT_ID}/settings/entities/${entity.id}`, {
    method: 'PUT',
    body: JSON.stringify({
      profile: nextProfile,
      lastChapter: relation.chapterNum || entity.lastChapter || null
    })
  })
  await api(`/projects/${PROJECT_ID}/settings/relations/${relation.id}`, {
    method: 'PUT',
    body: JSON.stringify({
      status: 'merged',
      summary: relation.summary || '自我关系已归位到实体 profile。',
      evidence: relation.evidence || ''
    })
  })
}

async function main() {
  fs.mkdirSync(QA_DIR, { recursive: true })
  let { entities, relations } = await getState()
  const before = buildRelationshipRehomeAudit({ entities, relations })
  let entityMap = entityByIdMap(entities)
  let nameMap = entitiesByNameMap(entities)
  const operations = []
  const manualReview = []

  for (const relation of relations.filter(item => (item.status || 'active') === 'active')) {
    const source = entityMap.get(relation.sourceEntityId)
    const target = entityMap.get(relation.targetEntityId)
    if (!source || !target) continue

    if (relation.sourceEntityId && relation.sourceEntityId === relation.targetEntityId) {
      await rehomeSelfRelation(relation, source)
      operations.push({ type: 'self_relation_rehomed', relationId: relation.id, entityName: source.name })
      continue
    }

    let nextSourceId = relation.sourceEntityId
    let nextTargetId = relation.targetEntityId
    const reasons = []

    if (isSyntheticName(source.name)) {
      const [sourceName, targetName, eventQualifier] = splitSyntheticName(source.name)
      if (
        sourceName &&
        targetName &&
        normalizeNameCore(sourceName) === normalizeNameCore(targetName) &&
        target &&
        normalizeNameCore(target.name) === normalizeNameCore(targetName)
      ) {
        await rehomeSelfRelation(relation, target)
        operations.push({ type: 'synthetic_self_relation_rehomed', relationId: relation.id, entityName: target.name })
        continue
      }
      const realSource = resolveEntityByName(entities, sourceName, isOrgishName(sourceName) ? 'faction' : '', [source.id])
      const realTarget = target?.name === targetName
        ? target
        : resolveEntityByName(entities, targetName, isOrgishName(targetName) ? 'faction' : '', [source.id])
      if (realSource && realTarget && realSource.id !== realTarget.id) {
        nextSourceId = realSource.id
        nextTargetId = realTarget.id
        reasons.push(`source synthetic ${source.name} -> ${realSource.name}/${realTarget.name}`)
        if (eventQualifier) reasons.push(`eventQualifier=${eventQualifier}`)
      } else {
        manualReview.push({ relationId: relation.id, reason: 'source synthetic name cannot be resolved safely', label: relationLabel(relation, entityMap) })
      }
    }

    if (isSyntheticName(target.name)) {
      const [sourceName, targetName, eventQualifier] = splitSyntheticName(target.name)
      const realSource = source?.name === sourceName
        ? source
        : resolveEntityByName(entities, sourceName, isOrgishName(sourceName) ? 'faction' : '', [target.id])
      const realTarget = resolveEntityByName(entities, targetName, isOrgishName(targetName) ? 'faction' : '', [target.id])
      if (realSource && realTarget && realSource.id !== realTarget.id) {
        nextSourceId = realSource.id
        nextTargetId = realTarget.id
        reasons.push(`target synthetic ${target.name} -> ${realSource.name}/${realTarget.name}`)
        if (eventQualifier) reasons.push(`eventQualifier=${eventQualifier}`)
      } else {
        manualReview.push({ relationId: relation.id, reason: 'target synthetic name cannot be resolved safely', label: relationLabel(relation, entityMap) })
      }
    }

    for (const [side, entity] of [['source', source], ['target', target]]) {
      if (!(entity.entityType === 'character' && isOrgishName(entity.name) && !isSyntheticName(entity.name))) continue
      const realFaction = preferRealEntity((nameMap.get(entity.name) || []).filter(item => item.id !== entity.id), 'faction')
      if (realFaction) {
        if (side === 'source') nextSourceId = realFaction.id
        else nextTargetId = realFaction.id
        reasons.push(`${side} wrong-layer ${entity.name} -> faction`)
      } else {
        await markWrongLayerFaction(entity)
        reasons.push(`${side} wrong-layer ${entity.name} type changed to faction`)
      }
    }

    if (nextSourceId !== relation.sourceEntityId || nextTargetId !== relation.targetEntityId) {
      if (nextSourceId === nextTargetId) {
        manualReview.push({ relationId: relation.id, reason: 'resolved to self relation; kept for manual review', label: relationLabel(relation, entityMap) })
        continue
      }
      const qualifier = reasons
        .map(reason => String(reason || '').match(/^eventQualifier=(.+)$/)?.[1])
        .find(Boolean)
      const nextSummary = qualifier && !String(relation.summary || '').includes(qualifier)
        ? `${relation.summary || '关系事件已归位。'}（事件性质：${qualifier}）`
        : relation.summary
      await api(`/projects/${PROJECT_ID}/settings/relations/${relation.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          sourceEntityId: nextSourceId,
          targetEntityId: nextTargetId,
          summary: nextSummary,
          status: 'active'
        })
      })
      operations.push({ type: 'relation_repointed', relationId: relation.id, reasons })
    }
  }

  ;({ entities, relations } = await getState())
  entityMap = entityByIdMap(entities)
  const activeReferenceIds = new Set(
    relations
      .filter(relation => (relation.status || 'active') === 'active')
      .flatMap(relation => [relation.sourceEntityId, relation.targetEntityId])
  )
  for (const entity of entities) {
    if ((entity.status || 'active') !== 'active') continue
    if (!isSyntheticName(entity.name)) continue
    if (activeReferenceIds.has(entity.id)) {
      manualReview.push({ entityId: entity.id, entityName: entity.name, reason: 'synthetic placeholder still referenced by active relation' })
      continue
    }
    await markEntityMerged(entity, '合成关系占位实体已不再被 active relation 引用。')
    operations.push({ type: 'placeholder_entity_marked_merged', entityId: entity.id, entityName: entity.name })
  }

  const afterState = await getState()
  const after = buildRelationshipRehomeAudit(afterState)
  const report = {
    projectId: PROJECT_ID,
    fixedAt: new Date().toISOString(),
    before,
    after,
    activeSyntheticRelationCountBefore: before.activeSyntheticRelationCount,
    activeSelfRelationCountBefore: before.activeSelfRelationCount,
    activeWrongLayerRelationCountBefore: before.activeWrongLayerRelationCount,
    activeSyntheticRelationCountAfter: after.activeSyntheticRelationCount,
    activeSelfRelationCountAfter: after.activeSelfRelationCount,
    activeWrongLayerRelationCountAfter: after.activeWrongLayerRelationCount,
    fixedCount: operations.length,
    manualReviewCount: manualReview.length,
    operations,
    manualReview,
    remainingRiskySamples: [
      ...after.syntheticRelations,
      ...after.selfRelations,
      ...after.wrongLayerRelations
    ].slice(0, 20),
    forceHardConflictUsed: false
  }

  fs.writeFileSync(OUT_JSON, JSON.stringify(report, null, 2), 'utf8')
  fs.writeFileSync(OUT_MD, [
    '# 设定关系归位泛化修复',
    '',
    `- 项目：${report.projectId}`,
    `- 修复时间：${report.fixedAt}`,
    `- active synthetic relation count：${report.activeSyntheticRelationCountBefore} -> ${report.activeSyntheticRelationCountAfter}`,
    `- active self relation count：${report.activeSelfRelationCountBefore} -> ${report.activeSelfRelationCountAfter}`,
    `- active wrong-layer relation count：${report.activeWrongLayerRelationCountBefore} -> ${report.activeWrongLayerRelationCountAfter}`,
    `- fixed count：${report.fixedCount}`,
    `- manual review count：${report.manualReviewCount}`,
    `- forceHardConflictUsed：${report.forceHardConflictUsed}`,
    '',
    '## 剩余风险样本',
    '',
    ...(report.remainingRiskySamples.length
      ? report.remainingRiskySamples.map(item => `- ${item.id}: ${item.sourceName} -> ${item.relationType || '关系'} -> ${item.targetName}`)
      : ['- 无'])
  ].join('\n') + '\n', 'utf8')

  console.log(JSON.stringify({
    ok: true,
    outJson: OUT_JSON,
    activeSyntheticRelationCountBefore: report.activeSyntheticRelationCountBefore,
    activeSyntheticRelationCountAfter: report.activeSyntheticRelationCountAfter,
    activeSelfRelationCountBefore: report.activeSelfRelationCountBefore,
    activeSelfRelationCountAfter: report.activeSelfRelationCountAfter,
    fixedCount: report.fixedCount,
    manualReviewCount: report.manualReviewCount
  }, null, 2))
}

main().catch(error => {
  console.error(error)
  process.exit(1)
})
