import test from 'node:test'
import assert from 'node:assert/strict'
import { continuityRecordDetails } from '../../src/application/continuity/recordDetails.js'

test('real scalar arc projection retains its value and explicit dimension', () => {
  const result = continuityRecordDetails({ field: 'arc.trust', value: '稳固', sourceChapter: 3 }, 'arcs')
  assert.deepEqual(result.rows, [{ label: '信任变化', lines: ['稳固'] }])
  assert.equal(result.provenance, '本项最近更新于第 3 章')
  assert.equal(result.lines.length, 0)
})
test('structured arcs show only supplied dimensions and preserve other content', () => {
  const record = { field: 'arc.hero', value: { stage: '动摇', goal: '救人', belief: '守诺', relationship: '疏远', ability: '识字', detail: '雨夜的决定' } }
  const before = structuredClone(record)
  const result = continuityRecordDetails(record, 'arcs')
  assert.deepEqual(result.rows.map(row => row.label), ['当前阶段', '目标', '信念', '关系', '能力'])
  assert.ok(result.lines.includes('详情：雨夜的决定'))
  assert.deepEqual(record, before)
  assert.equal(continuityRecordDetails({ value: '尚在逃亡' }, 'arcs').rows.length, 0)
})
test('unknown real plot fields do not become foreshadowing or a completed thread', () => {
  const result = continuityRecordDetails({ field: 'plot.gunpowder', value: { status: '推进' } }, 'clues')
  assert.equal(result.title, '情节线索 · 类别未注明')
  assert.deepEqual(result.rows, [{ label: '当前进展', lines: ['推进'] }])
})

test('real scalar plot status is translated without duplicating internal wording', () => {
  const result = continuityRecordDetails({ field: 'plot.mystery.bell', value: 'resolved' }, 'clues')
  assert.deepEqual(result.rows, [{ label: '当前进展', lines: ['已回收'] }])
  assert.deepEqual(result.lines, [])
})
test('explicit plot classes remain distinct and status is translated', () => {
  for (const [field, title] of [['main', '主线'], ['sub', '支线'], ['character', '人物线'], ['mystery', '悬念'], ['foreshadow', '伏笔']]) {
    const result = continuityRecordDetails({ field: `plot.${field}.one`, value: { status: 'planted' } }, 'clues')
    assert.equal(result.title, title)
    assert.deepEqual(result.rows[0].lines, ['已埋设'])
  }
})
test('planned and actual resolution chapters are distinct without inference', () => {
  const result = continuityRecordDetails({ field: 'plot.mystery', value: { plannedResolutionChapter: 8 } }, 'clues')
  assert.equal(result.rows.length, 1)
  assert.match(result.rows[0].label, /计划.*不代表已发生/)
  assert.deepEqual(result.rows[0].lines, ['第 8 章'])
})
test('source chapters are not presented as first formation for current state', () => {
  assert.equal(continuityRecordDetails({ value: '北平', formedChapter: 1, sourceChapter: 3 }, 'state').provenance, '首次形成于第 1 章；本项最近更新于第 3 章')
  assert.equal(continuityRecordDetails({ value: '北平', sourceChapter: 3 }, 'state').provenance, '本项最近更新于第 3 章')
  assert.equal(continuityRecordDetails({ value: '北平' }, 'state').provenance, '')
  assert.equal(continuityRecordDetails({ value: '传闻', sourceChapter: 3, isClaim: true }, 'memory').note, '人物说法保留为记忆，不作为客观状态。')
})
test('false and zero remain meaningful values while unknown fields never invent meaning', () => {
  const result = continuityRecordDetails({ value: { ability: false, goal: 0, extra: '保留内容' } }, 'arcs')
  assert.deepEqual(result.rows.map(row => row.lines), [['0'], ['否']])
  assert.deepEqual(result.lines, ['补充内容：保留内容'])
})
