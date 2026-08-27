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
})
