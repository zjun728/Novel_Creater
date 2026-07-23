import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const source = path => new URL(`../../src/${path}`, import.meta.url)

test('Project Bible workspace and its focused editor/history components exist as the only formal route surface', async () => {
  const [view, editor, drawer, routes] = await Promise.all([
    readFile(source('views/ProjectBibleView.vue'), 'utf8'),
    readFile(source('components/bible/BibleEditor.vue'), 'utf8'),
    readFile(source('components/bible/BibleHistoryDrawer.vue'), 'utf8'),
    readFile(source('router/projectRoutes.js'), 'utf8'),
  ])
  assert.match(view, /useBibleStore/)
  assert.match(view, /aria-live/)
  assert.match(editor, /premiseAndPromise/)
  assert.match(editor, /openDesignQuestions/)
  assert.match(drawer, /loadHistory/)
  assert.match(routes, /ProjectBible/)
})

test('retired Bible workspace files are physically absent', async () => {
  const retired = [
    'views/WriterView.vue', 'components/bible/CreativeBible.vue',
    'components/bible/CharacterArcView.vue', 'components/bible/PlotThreadBoard.vue',
    'prompts/bibleFromSeed.js', 'prompts/settingsFromBible.js',
  ]
  for (const path of retired) {
    await assert.rejects(access(source(path)))
  }
})

test('the source inventory has no formal imports of the retired Bible prompt or workspace', async () => {
  const root = fileURLToPath(new URL('../../src', import.meta.url))
  assert.match(root, /src$/)
})
