import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  buildProjectFreezeStatus,
  summarizeProjectHealthSnapshot,
  summarizeRelationshipRisks
} from './live-qa/audits/project-health-audit.mjs'
import { collectFreezeGuardSummary } from './live-qa/guards/live-run-freeze-guards.mjs'

const PROJECT_ID = 'fixture-project'
const FINAL_88 = 'bf7c1992-2b0e-410a-a2d0-cef177c13732'

function chaptersFixture(extra = []) {
  return [
    { id: 'chapter-83', project_id: PROJECT_ID, chapter_num: 83, status: 'final', final_version_id: 'final-83', title: '第83章' },
    { id: 'chapter-84', project_id: PROJECT_ID, chapter_num: 84, status: 'final', final_version_id: 'final-84', title: '第84章' },
    { id: 'chapter-85', project_id: PROJECT_ID, chapter_num: 85, status: 'final', final_version_id: 'final-85', title: '第85章' },
    { id: 'chapter-86', project_id: PROJECT_ID, chapter_num: 86, status: 'final', final_version_id: 'final-86', title: '第86章' },
    { id: 'chapter-87', project_id: PROJECT_ID, chapter_num: 87, status: 'final', final_version_id: 'final-87', title: '第87章' },
    { id: 'chapter-88', project_id: PROJECT_ID, chapter_num: 88, status: 'final', final_version_id: FINAL_88, title: '铁箱账本' },
    ...extra
  ]
}

function entitiesFixture(extra = []) {
  return [
    { id: 'person-a', project_id: PROJECT_ID, entity_type: 'character', name: '陆沉舟', status: 'active' },
    { id: 'person-b', project_id: PROJECT_ID, entity_type: 'character', name: '青鸾', status: 'active' },
    { id: 'org-a', project_id: PROJECT_ID, entity_type: 'organization', name: '青木商会', status: 'active' },
    { id: 'place-a', project_id: PROJECT_ID, entity_type: 'location', name: '北桥仓库', status: 'active' },
    ...extra
  ]
}

function activeRelation(id, sourceEntityId, targetEntityId, extra = {}) {
  return {
    id,
    project_id: PROJECT_ID,
    source_entity_id: sourceEntityId,
    target_entity_id: targetEntityId,
    relation_type: '关联',
    status: 'active',
    ...extra
  }
}

function healthyRelations(count = 42) {
  return Array.from({ length: count }, (_, index) => activeRelation(`rel-${index + 1}`, 'person-a', index % 2 ? 'org-a' : 'person-b'))
}

function healthySnapshot(overrides = {}) {
  return {
    projectId: PROJECT_ID,
    chapters: chaptersFixture(),
    settingChangeEvents: [],
    settingEntities: entitiesFixture(),
    settingRelations: healthyRelations(),
    ...overrides
  }
}

const health = summarizeProjectHealthSnapshot(healthySnapshot(), {
  requiredFinalChapter: 88,
  expectedFinalVersionId: FINAL_88,
  forbiddenChapters: [89],
  pendingStatuses: ['pending_review']
})
assert.equal(health.ok, true)
assert.equal(health.chapter88FinalVersionId, FINAL_88)
assert.equal(health.chapter89Exists, false)
assert.equal(health.pendingSettingsCount, 0)
assert.deepEqual(health.blockers, [])
assert.deepEqual(health.relationshipAudit, {
  activeRelationCount: 42,
  activeSyntheticRelationCount: 0,
  activeSelfRelationCount: 0,
  activeWrongLayerRelationCount: 0,
  activeMissingEndpointRelationCount: 0
})

const forbidden = buildProjectFreezeStatus({
  chapters: chaptersFixture([{ id: 'chapter-89', project_id: PROJECT_ID, chapter_num: 89, status: 'drafting', title: '第89章' }]),
  requiredFinalChapter: 88,
  expectedFinalVersionId: FINAL_88,
  forbiddenChapters: [89]
})
assert.equal(forbidden.ok, false)
assert.equal(forbidden.chapter89Exists, true)
assert.equal(forbidden.blockers[0].code, 'unexpectedChapterStarted')

const pending = summarizeProjectHealthSnapshot(healthySnapshot({
  settingChangeEvents: [
    { id: 'pending-1', project_id: PROJECT_ID, status: 'pending_review' }
  ]
}), {
  requiredFinalChapter: 88,
  expectedFinalVersionId: FINAL_88,
  forbiddenChapters: [89]
})
assert.equal(pending.ok, false)
assert.equal(pending.pendingSettingsCount, 1)
assert.ok(pending.blockers.some(item => item.code === 'pendingSettingsNonZero'))

const syntheticAudit = summarizeRelationshipRisks({
  entities: entitiesFixture([{ id: 'synthetic-endpoint', entity_type: 'character', name: '角色_临时', status: 'active' }]),
  relations: [activeRelation('synthetic-rel', 'synthetic-endpoint', 'person-b')]
})
assert.equal(syntheticAudit.activeRelationCount, 1)
assert.equal(syntheticAudit.activeSyntheticRelationCount, 1)

const selfAudit = summarizeRelationshipRisks({
  entities: entitiesFixture(),
  relations: [activeRelation('self-rel', 'person-a', 'person-a')]
})
assert.equal(selfAudit.activeRelationCount, 1)
assert.equal(selfAudit.activeSelfRelationCount, 1)

const wrongLayerAudit = summarizeRelationshipRisks({
  entities: entitiesFixture([{ id: 'wrong-layer', entity_type: 'character', name: '南市商会', status: 'active' }]),
  relations: [activeRelation('wrong-layer-rel', 'wrong-layer', 'person-b')]
})
assert.equal(wrongLayerAudit.activeRelationCount, 1)
assert.equal(wrongLayerAudit.activeWrongLayerRelationCount, 1)

const missingEndpointAudit = summarizeRelationshipRisks({
  entities: entitiesFixture(),
  relations: [activeRelation('missing-rel', 'person-a', 'missing-target')]
})
assert.equal(missingEndpointAudit.activeRelationCount, 1)
assert.equal(missingEndpointAudit.activeMissingEndpointRelationCount, 1)

const inactiveRelationAudit = summarizeRelationshipRisks({
  entities: entitiesFixture([{ id: 'inactive-risk', entity_type: 'character', name: '临时_角色', status: 'active' }]),
  relations: [activeRelation('inactive-rel', 'inactive-risk', 'person-b', { status: 'archived' })]
})
assert.equal(inactiveRelationAudit.activeRelationCount, 0)
assert.equal(inactiveRelationAudit.activeSyntheticRelationCount, 0)

const freezeGuardSummary = collectFreezeGuardSummary({
  report: {
    chapterReports: chaptersFixture().map(chapter => ({
      chapterNum: chapter.chapter_num,
      finalized: chapter.status === 'final'
    })),
    pendingSettingsCount: health.pendingSettingsCount,
    relationshipAudit: health.relationshipAudit
  },
  startChapter: 83,
  endChapter: 88,
  forbiddenChapters: [89],
  unexpectedChapterNum: 89,
  expectedPendingCount: 0,
  expectedRelationRisk: health.relationshipAudit
})
assert.equal(freezeGuardSummary.relationshipRiskChecked, true)
assert.ok(freezeGuardSummary.checkedFailureModes.includes('relationRiskNonZero'))

const source = readFileSync('tmp/live-qa/audits/project-health-audit.mjs', 'utf8')
assert.doesNotMatch(
  source,
  /chromium|page\.|fetch\s*\(|api\s*\(|aiomysql|mysql|SELECT\s+|writeFileSync|readFileSync|from 'node:fs'|from "node:fs"/i,
  'project health pure evaluator must not contain browser/API/DB/file I/O'
)
assert.doesNotMatch(source, /星债会|东城染坊|铁箱账本|庚七密室|三号仓钥|星债会地窖/, 'audit policy must not hardcode current project terms')

console.log('live project health audit contract passed')
