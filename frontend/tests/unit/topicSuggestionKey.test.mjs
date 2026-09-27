import assert from 'node:assert/strict'
import test from 'node:test'
import { topicSuggestionKey } from '../../src/application/topics/topicSuggestionKey.js'

test('suggestion retries reuse identity while distinct sources remain independent', async () => {
  const key = await topicSuggestionKey('d1', 'r1', 'candidate', 0)
  assert.match(key, /^[a-f0-9]{64}$/)
  assert.equal(await topicSuggestionKey('d1', 'r1', 'candidate', 0), key)
  for (const args of [['d2', 'r1', 'candidate', 0], ['d1', 'r2', 'candidate', 0],
    ['d1', 'r1', 'direction', 0], ['d1', 'r1', 'candidate', 1]]) {
    assert.notEqual(await topicSuggestionKey(...args), key)
  }
})
