import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8000/api'
const PROJECT_ID = process.env.PROJECT_ID || '2da6152a-c083-41ee-8bcb-f11b0fae387d'
const QA_DIR = path.join(process.cwd(), 'tmp', 'realistic-flow-qa')
const OUT_JSON = process.env.RELATION_AUDIT_JSON || path.join(QA_DIR, 'latest-setting-relationship-rehome-generalized-audit-before.json')
const OUT_MD = process.env.RELATION_AUDIT_MD || path.join(QA_DIR, 'latest-setting-relationship-rehome-generalized-audit-before.md')

function isSyntheticName(name = '') {
  return String(name || '').trim().includes('_')
}

function isOrgishName(name = '') {
  return /(星债会|巡天司|商盟|会|司|盟|宗|门派|宗门|商会|官署|机构|组织|势力|帮|阁|堂|府|衙|院)$/.test(String(name || '').trim())
}

async function api(pathname) {
  const response = await fetch(`${API_BASE}${pathname}`)
  const text = await response.text()
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}: ${text.slice(0, 800)}`)
  return text ? JSON.parse(text) : null
}

function relationLabel(relation, entityMap) {
  const source = entityMap.get(relation.sourceEntityId)
  const target = entityMap.get(relation.targetEntityId)
  return {
    id: relation.id,
    relationType: relation.relationType || '',
    stance: relation.stance || '',
    sourceEntityId: relation.sourceEntityId,
    sourceName: source?.name || '未知',
    sourceEntityType: source?.entityType || '',
    targetEntityId: relation.targetEntityId,
    targetName: target?.name || '未知',
    targetEntityType: target?.entityType || '',
    summary: relation.summary || '',
    chapterNum: relation.chapterNum || null,
    status: relation.status || 'active'
  }
}

export function buildRelationshipRehomeAudit({ entities = [], relations = [] } = {}) {
  const entityMap = new Map(entities.map(entity => [entity.id, entity]))
  const activeRelations = relations.filter(relation => (relation.status || 'active') === 'active')
  const syntheticRelations = []
  const selfRelations = []
  const wrongLayerRelations = []

  for (const relation of activeRelations) {
    const source = entityMap.get(relation.sourceEntityId)
    const target = entityMap.get(relation.targetEntityId)
    if (source?.name && isSyntheticName(source.name)) syntheticRelations.push(relationLabel(relation, entityMap))
    else if (target?.name && isSyntheticName(target.name)) syntheticRelations.push(relationLabel(relation, entityMap))

    if (relation.sourceEntityId && relation.sourceEntityId === relation.targetEntityId) {
      selfRelations.push(relationLabel(relation, entityMap))
    }

    const sourceWrongLayer = source?.entityType === 'character' && isOrgishName(source.name)
    const targetWrongLayer = target?.entityType === 'character' && isOrgishName(target.name)
    if (sourceWrongLayer || targetWrongLayer) {
      wrongLayerRelations.push(relationLabel(relation, entityMap))
    }
  }

  const uniqueById = list => [...new Map(list.map(item => [item.id, item])).values()]
  return {
    projectId: PROJECT_ID,
    auditedAt: new Date().toISOString(),
    activeRelationCount: activeRelations.length,
    activeSyntheticRelationCount: uniqueById(syntheticRelations).length,
    activeSelfRelationCount: uniqueById(selfRelations).length,
    activeWrongLayerRelationCount: uniqueById(wrongLayerRelations).length,
    syntheticRelations: uniqueById(syntheticRelations).slice(0, 50),
    selfRelations: uniqueById(selfRelations).slice(0, 50),
    wrongLayerRelations: uniqueById(wrongLayerRelations).slice(0, 50)
  }
}

function markdown(report) {
  const lines = [
    '# 设定关系归位泛化只读审计',
    '',
    `- 项目：${report.projectId}`,
    `- 审计时间：${report.auditedAt}`,
    `- active relation 总数：${report.activeRelationCount}`,
    `- active synthetic relation count：${report.activeSyntheticRelationCount}`,
    `- active self relation count：${report.activeSelfRelationCount}`,
    `- active wrong-layer relation count：${report.activeWrongLayerRelationCount}`,
    '',
    '## 风险样本',
    '',
    ...[...report.syntheticRelations, ...report.selfRelations, ...report.wrongLayerRelations]
      .slice(0, 20)
      .map(item => `- ${item.id}: ${item.sourceName}(${item.sourceEntityType}) -> ${item.relationType || '关系'} -> ${item.targetName}(${item.targetEntityType})；status=${item.status}`)
  ]
  return `${lines.join('\n')}\n`
}

async function main() {
  fs.mkdirSync(QA_DIR, { recursive: true })
  const [entities, relations] = await Promise.all([
    api(`/projects/${PROJECT_ID}/settings/entities`),
    api(`/projects/${PROJECT_ID}/settings/relations`)
  ])
  const report = buildRelationshipRehomeAudit({ entities, relations })
  fs.writeFileSync(OUT_JSON, JSON.stringify(report, null, 2), 'utf8')
  fs.writeFileSync(OUT_MD, markdown(report), 'utf8')
  console.log(JSON.stringify({
    ok: true,
    outJson: OUT_JSON,
    activeSyntheticRelationCount: report.activeSyntheticRelationCount,
    activeSelfRelationCount: report.activeSelfRelationCount,
    activeWrongLayerRelationCount: report.activeWrongLayerRelationCount
  }, null, 2))
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
