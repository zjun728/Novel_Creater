import assert from 'node:assert/strict'
import test from 'node:test'

import {
  clearTopicDraft,
  readTopicDraft,
  writeTopicDraft,
} from '../../src/components/topics/topicDiscussionDraftSession.js'

test('discussion draft remains available to a later component mount', () => {
  const discussionId = 'route-away-draft'
  writeTopicDraft(discussionId, '  返回后仍保留  ')

  assert.equal(readTopicDraft(discussionId), '  返回后仍保留  ')
  assert.equal(clearTopicDraft(discussionId, 'different submission'), false)
  assert.equal(readTopicDraft(discussionId), '  返回后仍保留  ')
})

test('accepted submission clears only its unchanged exact draft snapshot', () => {
  const discussionId = 'accepted-draft'
  writeTopicDraft(discussionId, '原始内容')
  writeTopicDraft(discussionId, '发送期间新增内容')

  assert.equal(clearTopicDraft(discussionId, '原始内容'), false)
  assert.equal(readTopicDraft(discussionId), '发送期间新增内容')
  assert.equal(clearTopicDraft(discussionId, '发送期间新增内容'), true)
  assert.equal(readTopicDraft(discussionId), '')
})
