import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  PROJECT_HEALTH_API_ENDPOINTS,
  collectProjectHealthSnapshotFromApi
} from './live-qa/audits/project-health-api-snapshot.mjs'
import { summarizeProjectHealthSnapshot } from './live-qa/audits/project-health-audit.mjs'

const calls = []
const fakeData = new Map([
  ['/projects/p1/chapters', [{ id: 'c88', chapterNum: 88, status: 'final', finalVersionId: 'v88' }]],
  ['/projects/p1/settings/change-events?status=pending_review', []],
  ['/projects/p1/settings/entities', [
    { id: 'e1', entityType: 'character', name: '甲', status: 'active' },
    { id: 'e2', entityType: 'organization', name: '乙商会', status: 'active' }
  ]],
  ['/projects/p1/settings/relations', [
    { id: 'r1', sourceEntityId: 'e1', targetEntityId: 'e2', status: 'active' }
  ]]
])

const snapshot = await collectProjectHealthSnapshotFromApi({
  projectId: 'p1',
  api: async endpoint => {
    calls.push(endpoint)
    return fakeData.get(endpoint)
  }
})

assert.deepEqual(calls, [
  '/projects/p1/chapters',
  '/projects/p1/settings/change-events?status=pending_review',
  '/projects/p1/settings/entities',
  '/projects/p1/settings/relations'
])
assert.deepEqual(Object.values(PROJECT_HEALTH_API_ENDPOINTS).map(fn => fn('p1')), calls)
assert.equal(snapshot.projectId, 'p1')
assert.equal(snapshot.chapters.length, 1)
assert.equal(snapshot.settingChangeEvents.length, 0)
assert.equal(snapshot.settingEntities.length, 2)
assert.equal(snapshot.settingRelations.length, 1)

const health = summarizeProjectHealthSnapshot(snapshot, {
  projectId: 'p1',
  forbiddenChapters: [89]
})
assert.equal(health.ok, true)
assert.equal(health.relationshipAudit.activeRelationCount, 1)
assert.equal(health.relationshipAudit.activeSyntheticRelationCount, 0)
assert.equal(health.relationshipAudit.activeSelfRelationCount, 0)
assert.equal(health.relationshipAudit.activeWrongLayerRelationCount, 0)
assert.equal(health.relationshipAudit.activeMissingEndpointRelationCount, 0)

await assert.rejects(
  () => collectProjectHealthSnapshotFromApi({
    projectId: 'p1',
    api: async endpoint => {
      if (endpoint.includes('/settings/entities')) throw new Error('boom')
      return fakeData.get(endpoint) || []
    }
  }),
  error => {
    assert.equal(error.code, 'projectHealthSnapshotApiFailed')
    assert.equal(error.endpoint, '/projects/p1/settings/entities')
    assert.match(error.message, /projectHealthSnapshotApiFailed/)
    return true
  }
)

const source = readFileSync('tmp/live-qa/audits/project-health-api-snapshot.mjs', 'utf8')
assert.doesNotMatch(source, /\bPOST\b|\bPUT\b|\bDELETE\b/i, 'adapter must only encode GET endpoints')
assert.doesNotMatch(
  source,
  /chromium|page\.|fetch\s*\(|aiomysql|mysql|SELECT\s+|writeFileSync|readFileSync|node:fs/i,
  'adapter must not directly depend on browser/API implementation/DB/file I/O'
)
assert.doesNotMatch(source, /星债会|东城染坊|铁箱账本|庚七密室|三号仓钥|星债会地窖/, 'adapter must not hardcode current project terms')

console.log('live project health api snapshot contract passed')
