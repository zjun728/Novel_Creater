import assert from 'node:assert/strict'
import test from 'node:test'
import { planningEntries, comparePlanning } from '../../src/application/planning/planningPresentation.js'

const content = () => ({ activeStoryBlockRef: 'b', volumes: [{ id: 'v', lifecycle: 'active', title: '第一卷', coreChange: '发现线索' }], plots: [], storyBlocks: [{ id: 'b', lifecycle: 'active', title: '调查', volumeRef: 'v', stages: [{ id: 's', title: '取证', purpose: '找到证据', sceneTasks: [{ id: 't', task: '检查桥墩', completionEvidence: '找到铜钉' }] }] }] })

test('continuation does not label the unchanged former active block as modified', () => {
  const before = content(), after = content()
  after.storyBlocks.push({ id: 'next', lifecycle: 'active', title: '追踪', volumeRef: 'v', stages: [] })
  after.activeStoryBlockRef = 'next'
  const changes = comparePlanning(before, after)
  assert.deepEqual(changes.map(row => row.key), ['story-blocks:next', 'active-story-block'])
})
test('reading resolves relationships and retains task evidence without mutating the plan', () => {
  const plan = content(), original = structuredClone(plan)
  const rows = planningEntries(plan, 'story-blocks')
  assert.equal(rows[0].current, true)
  assert.match(JSON.stringify(rows[0].fields), /第一卷/)
  assert.match(JSON.stringify(rows[0].fields), /找到铜钉/)
  assert.deepEqual(plan, original)
})
test('comparison ignores revision metadata but reports nested task changes and removed nodes', () => {
  const before = content(), after = content()
  after.volumes[0].revision = 2
  assert.equal(comparePlanning(before, after).length, 0)
  after.storyBlocks[0].stages[0].sceneTasks[0].completionEvidence = '记录钉孔尺寸'
  after.volumes = []
  const changes = comparePlanning(before, after)
  assert.ok(changes.some(row => row.kind === '移除' && row.title === '第一卷'))
  assert.ok(changes.some(row => row.title === '调查' && row.after.fields.some(field => field.value.includes('记录钉孔尺寸'))))
})
test('retired nodes are excluded from reading but retirement and active block changes are compared', () => {
  const before = content(), after = content()
  after.storyBlocks[0].lifecycle = 'retired'
  after.activeStoryBlockRef = null
  assert.deepEqual(planningEntries(after, 'story-blocks'), [])
  assert.ok(comparePlanning(before, after).some(row => row.title === '当前故事块'))
  assert.ok(comparePlanning(before, after).some(row => row.title === '调查'))
})
