import { shallowReactive } from 'vue'

const drafts = shallowReactive(new Map())

function discussionKey(value) {
  if (typeof value !== 'string' || !value.trim()) {
    throw new TypeError('Expected a discussion id')
  }
  return value
}

export function readTopicDraft(discussionId) {
  return drafts.get(discussionKey(discussionId)) || ''
}

export function writeTopicDraft(discussionId, value) {
  if (typeof value !== 'string') throw new TypeError('Expected a discussion draft')
  const key = discussionKey(discussionId)
  if (value) drafts.set(key, value)
  else drafts.delete(key)
}

export function clearTopicDraft(discussionId, expectedDraft) {
  const key = discussionKey(discussionId)
  if (typeof expectedDraft !== 'string') throw new TypeError('Expected a discussion draft')
  if (drafts.get(key) !== expectedDraft) return false
  drafts.delete(key)
  return true
}
