import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'
import vuePlugin from '@vitejs/plugin-vue'

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

test('real Bible editor SSR renders all fields and disabled list controls for read-only state', async () => {
  const vite = await createServer({ configFile: false, root: fileURLToPath(new URL('../..', import.meta.url)), server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  try {
    const Editor = (await vite.ssrLoadModule('/src/components/bible/BibleEditor.vue')).default
    const item = id => [{ id, text: id }]
    const bible = { premiseAndPromise: 'p', powerOrProgressionSystem: 'power', protagonist: 'hero', toneAndNarrativeBoundaries: 'tone', worldRules: item('world'), coreCast: item('cast'), factions: item('faction'), longTermConflicts: item('conflict'), relationshipDynamics: item('relation'), continuityGuardrails: item('guard'), openDesignQuestions: item('question') }
    const html = await renderToString(createSSRApp({ render: () => h(Editor, { modelValue: bible, disabled: true }) }))
    assert.match(html, /作品承诺/); assert.match(html, /开放设计问题/)
    assert.match(html, /新增世界规则/); assert.match(html, /disabled/)
  } finally { await vite.close() }
})
