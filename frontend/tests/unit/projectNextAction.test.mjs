import assert from 'node:assert/strict'
import test from 'node:test'

import { mapProjectNextAction } from '../../src/application/projects/projectNextAction.js'

const chapterActions = [
  'recover_chapter_outline_operation', 'prepare_chapter_outline',
  'continue_chapter_outline', 'start_chapter_session', 'continue_writing',
]

test('maps every supported preparation next action using its safe server target', () => {
  for (const nextAction of [
    'select_seed', 'continue_contract', 'continue_bible', 'recover_planning_operation',
    'establish_planning', 'continue_planning', ...chapterActions,
  ]) {
    const result = mapProjectNextAction({
      lifecycle: 'active', nextAction, targetPath: '/server/path',
      authoritativeChapterNumber: 8,
    })
    assert.equal(result.state, 'available')
    assert.equal(result.targetPath, '/server/path')
    assert.equal(result.chapterNumber, chapterActions.includes(nextAction) ? 8 : null)
  }
})

test('uses authoritative chapter labels and never infers a next chapter', () => {
  const result = mapProjectNextAction({
    lifecycle: 'active', nextAction: 'continue_writing', targetPath: '/write/8',
    authoritativeChapterNumber: 8,
  })
  assert.equal(result.label, '继续创作第 8 章')
  assert.doesNotMatch(result.label + result.description, /下一章|9/)
})

test('rejects malformed and unsafe targets and archived authority wins', () => {
  for (const targetPath of ['https://bad.test', '//bad.test', '/\\bad', '/bad\npath', 'bad']) {
    assert.equal(mapProjectNextAction({ lifecycle: 'active', nextAction: 'continue_contract', targetPath }).state, 'unavailable')
  }
  assert.deepEqual(mapProjectNextAction({ lifecycle: 'archived', nextAction: 'continue_writing', targetPath: '/write/8', authoritativeChapterNumber: 8 }), { state: 'archived' })
  assert.equal(mapProjectNextAction({ lifecycle: 'active', nextAction: 'unknown', targetPath: '/x' }).label, '重新读取创作状态')
  assert.deepEqual(mapProjectNextAction({ lifecycle: 'active', nextAction: 'archived_read_only', targetPath: '/read' }), { state: 'unavailable', label: '重新读取创作状态' })
})

test('continue writing has the fixed author-facing description', () => {
  const action = mapProjectNextAction({ lifecycle: 'active', nextAction: 'continue_writing', targetPath: '/write/2', authoritativeChapterNumber: 2 })
  assert.equal(action.description, '回到当前权威章节，继续已有写作。')
  assert.deepEqual(Object.keys(action).sort(), ['chapterNumber', 'description', 'eyebrow', 'label', 'state', 'targetPath'])
})

test('every action returns a closed complete available object', () => {
  const labels = {
    select_seed: '选择创作种子', continue_contract: '继续创作契约', continue_bible: '继续创作圣经',
    recover_planning_operation: '核对规划生成结果', establish_planning: '开始故事规划', continue_planning: '继续故事规划',
    recover_chapter_outline_operation: '核对第 7 章小纲生成结果', prepare_chapter_outline: '准备第 7 章小纲',
    continue_chapter_outline: '继续第 7 章小纲', start_chapter_session: '进入第 7 章写作', continue_writing: '继续创作第 7 章',
  }
  for (const [nextAction, label] of Object.entries(labels)) {
    const value = mapProjectNextAction({ lifecycle: 'active', nextAction, targetPath: '/authority', authoritativeChapterNumber: 7 })
    assert.equal(value.state, 'available'); assert.equal(value.label, label); assert.equal(value.targetPath, '/authority'); assert.equal(value.chapterNumber, chapterActions.includes(nextAction) ? 7 : null); assert.ok(value.description)
  }
})
