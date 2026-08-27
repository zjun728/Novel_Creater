import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

test('reader keeps query view local, renders only readonly prose and response navigation', async () => {
  const source = await readFile(new URL('../../src/views/FinalChapterReaderView.vue', import.meta.url), 'utf8')
  assert.match(source, /route\.query\.view === 'outline'/)
  assert.match(source, /router\.replace/)
  assert.match(source, /watch\(\(\) => route\.query\.view/)
  assert.match(source, /watch\(\[projectId, chapterNumber\]/)
  assert.match(source, /navigation\.previousChapterNumber/)
  assert.match(source, /navigation\.nextChapterNumber/)
  assert.match(source, /不属于作品稿件/)
  assert.doesNotMatch(source, /v-html|contenteditable|编辑本章|重新打开会话/)
})

test('reader keeps download and creation state local to verified chapter content', async () => {
  const source = await readFile(new URL('../../src/views/FinalChapterReaderView.vue', import.meta.url), 'utf8')
  assert.match(source, /createNovelDownloadController/)
  assert.match(source, /scope: 'chapter'/)
  assert.match(source, /download\.error\.value/)
  assert.match(source, /manuscript\.loadPreparation/)
  assert.match(source, /data\.lifecycle === 'active'/)
  assert.match(source, /link\.hidden = true[\s\S]*document\.body\.append\(link\)[\s\S]*link\.remove\(\)/)
  assert.match(source, /manuscript\.loadContent\(id, 0\)/)
})

test('article and outline components keep author content plain and bounded', async () => {
  const [article, outline] = await Promise.all([
    readFile(new URL('../../src/components/manuscript/FinalChapterArticle.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/manuscript/FinalOutlinePanel.vue', import.meta.url), 'utf8'),
  ])
  assert.match(article, /split\(\/\\n/)
  assert.doesNotMatch(article, /v-html|JSON\.stringify|markdown/i)
  assert.match(outline, /chapterGoal.*expectedCharacters.*continuation.*plannedTasks.*scenes.*forbiddenEarlyEvents/s)
})
