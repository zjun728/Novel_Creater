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

test('chapter actions reject non-safe chapter numbers', () => {
  for (const chapterNumber of [Number.MAX_SAFE_INTEGER + 1, Infinity, 1.5, 0]) {
    assert.deepEqual(mapProjectNextAction({ lifecycle: 'active', nextAction: 'continue_writing', targetPath: '/write', authoritativeChapterNumber: chapterNumber }), { state: 'unavailable', label: '重新读取创作状态' })
  }
})

test('every action returns a closed complete available object', () => {
  const labels = {
    select_seed: ['CREATIVE SEED', '选择创作种子', '从候选种子中明确本项目唯一的当前创作方向。'], continue_contract: ['CREATION CONTRACT', '继续创作契约', '完成故事发动机、风格、经验与篇幅边界，并由作者确认。'], continue_bible: ['CREATION BIBLE', '继续创作圣经', '补全未来设计；手工建立与确认不依赖可用模型。'],
    recover_planning_operation: ['STORY PLANNING', '核对规划生成结果', '沿用原操作标识读取权威结果，不会重复发起一次 AI 生成。'], establish_planning: ['STORY PLANNING', '开始故事规划', '从空白工作稿建立分卷与情节线，再逐步形成可执行的完整规划。'], continue_planning: ['STORY PLANNING', '继续故事规划', '建立分卷、情节线与滚动故事块，让后续章节有方向也有调整余地。'],
    recover_chapter_outline_operation: ['CHAPTER OUTLINE', '核对第 7 章小纲生成结果', '读取本章小纲生成操作的权威结果，不会重复发起生成。'], prepare_chapter_outline: ['CHAPTER OUTLINE', '准备第 7 章小纲', '基于当前规划建立本章的写作边界。'], continue_chapter_outline: ['CHAPTER OUTLINE', '继续第 7 章小纲', '完善当前章节小纲并确认，随后即可进入正文工作台。'], start_chapter_session: ['WRITER', '进入第 7 章写作', '使用已确认的小纲与固定权威基线创建章节工作会话。'], continue_writing: ['WRITER', '继续创作第 7 章', '回到当前权威章节，继续已有写作。'],
  }
  for (const [nextAction, [eyebrow, label, description]] of Object.entries(labels)) {
    const value = mapProjectNextAction({ lifecycle: 'active', nextAction, targetPath: '/authority', authoritativeChapterNumber: 7 })
    assert.deepEqual(value, { state: 'available', eyebrow, label, description, targetPath: '/authority', chapterNumber: chapterActions.includes(nextAction) ? 7 : null })
  }
})
