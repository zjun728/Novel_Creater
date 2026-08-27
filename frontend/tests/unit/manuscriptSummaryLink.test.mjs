import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createSSRApp } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))

test('manuscript summary link renders a real accessible loading link', async () => {
  const vite = await createServer({
    configFile: false,
    root: frontendRoot,
    plugins: [vuePlugin()],
    server: { middlewareMode: true, hmr: false, ws: false },
    optimizeDeps: { noDiscovery: true },
  })
  const originalFetch = global.fetch
  global.fetch = async () => new Response(JSON.stringify({
    projectId: 'project one',
    summary: { finalChapterCount: 2 },
    volumes: [],
  }), { headers: { 'content-type': 'application/json' } })
  try {
    const Component = (await vite.ssrLoadModule('/src/components/manuscript/ManuscriptSummaryLink.vue')).default
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/projects/:projectId/manuscript', component: { template: '<div />' } }],
    })
    const app = createSSRApp(Component, { projectId: 'project one' })
    app.use(router)
    const html = await renderToString(app)
    assert.match(html, /class="manuscript-summary-link"/)
    assert.match(html, /href="\/projects\/project%20one\/manuscript"/)
    assert.match(html, /作品稿件 · 正在读取定稿数量/)
    assert.doesNotMatch(html, /<main/)
  } finally {
    global.fetch = originalFetch
    await vite.close()
  }
})
