import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createSSRApp } from 'vue'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

test('manuscript index keeps directory, preparation, and download-option failures independent', async () => {
  const source = await readFile(new URL('../../src/views/ManuscriptIndexView.vue', import.meta.url), 'utf8')
  assert.match(source, /createManuscriptController/)
  assert.match(source, /createNovelDownloadController/)
  assert.match(source, /还没有已定稿章节/)
  assert.match(source, /作品稿件/)
  assert.match(source, /<h1[^>]*>作品稿件<\/h1>/)
  assert.doesNotMatch(source, /Canon|Projection|revision|hash/i)
})

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveUiStubId = '\0manuscript-index-naive-ui-stub'
const apiStubId = '\0manuscript-index-api-stub'
const manuscriptIndexTestPlugin = {
  name: 'manuscript-index-test-stubs',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveUiStubId
    if (id.endsWith('/api/db/client.js')) return apiStubId
    return undefined
  },
  load(id) {
    if (id === naiveUiStubId) return `
      import { defineComponent, h } from 'vue'
      const stub = name => defineComponent({ name, setup(_, { attrs, slots }) { return () => h('div', attrs, slots.default?.()) } })
      export const NButton = stub('NButton')
      export const NResult = stub('NResult')
      export const NSkeleton = stub('NSkeleton')
    `
    if (id === apiStubId) return `
      const forever = () => new Promise(() => {})
      export const api = {
        manuscripts: { index: forever },
        projects: { preparation: forever },
        novelDownloads: { options: forever, create: forever },
      }
    `
    return undefined
  },
}

test('manuscript index is a real route section with one stable heading while loading', async () => {
  const vite = await createServer({
    configFile: false,
    root: frontendRoot,
    plugins: [vuePlugin(), manuscriptIndexTestPlugin],
    server: { middlewareMode: true, hmr: false, ws: false },
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  try {
    const Component = (await vite.ssrLoadModule('/src/views/ManuscriptIndexView.vue')).default
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/projects/:projectId/manuscript', component: Component }],
    })
    await router.push('/projects/active/manuscript')
    await router.isReady()
    const app = createSSRApp({ template: '<router-view />' })
    app.use(createPinia())
    app.use(router)
    const html = await renderToString(app)
    assert.match(html, /^<section class="manuscript-index"/)
    assert.equal((html.match(/<h1/g) || []).length, 1)
    assert.match(html, /作品稿件/)
    assert.doesNotMatch(html, /<main/)
  } finally {
    await vite.close()
  }
})

test('pending reader renders a safe chapter heading and never echoes an unsafe route value', async () => {
  const vite = await createServer({
    configFile: false,
    root: frontendRoot,
    plugins: [vuePlugin()],
    server: { middlewareMode: true, hmr: false, ws: false },
    optimizeDeps: { noDiscovery: true },
  })
  try {
    const Component = (await vite.ssrLoadModule('/src/views/FinalChapterReaderPendingView.vue')).default
    const render = async chapterNumber => {
      const router = createRouter({
        history: createMemoryHistory(),
        routes: [{ path: '/projects/:projectId/manuscript', component: { template: '<div />' } }],
      })
      const app = createSSRApp(Component, { projectId: 'p', chapterNumber })
      app.use(router)
      return renderToString(app)
    }
    const valid = await render('3')
    assert.match(valid, /<h1[^>]*>第 3 章定稿<\/h1>/)
    const unsafe = await render('9007199254740993')
    assert.match(unsafe, /<h1[^>]*>章节地址无效<\/h1>/)
    assert.doesNotMatch(unsafe, /9007199254740993/)
  } finally {
    await vite.close()
  }
})
