import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

test('manuscript index keeps directory, preparation, and download-option failures independent', async () => {
  const source = await readFile(new URL('../../src/views/ManuscriptIndexView.vue', import.meta.url), 'utf8')
  assert.match(source, /createManuscriptController/)
  assert.match(source, /createNovelDownloadController/)
  assert.match(source, /还没有已定稿章节/)
  assert.match(source, /作品稿件/)
  assert.match(source, /<h1[^>]*>作品稿件<\/h1>/)
  assert.doesNotMatch(source, /Canon|Projection|revision|hash/i)
})
