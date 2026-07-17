import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import { createServer } from 'vite'

const naiveUiStubId = '\0project-route-naive-ui-stub'
const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))

const naiveUiStubPlugin = {
  name: 'project-route-naive-ui-stub',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveUiStubId
  },
  load(id) {
    if (id !== naiveUiStubId) return undefined
    return `
      import { defineComponent, h } from 'vue'
      const stub = name => defineComponent({
        name,
        inheritAttrs: false,
        setup(_, { attrs, slots }) {
          return () => h('div', attrs, slots.default?.())
        },
      })
      export const NAlert = stub('NAlert')
      export const NButton = stub('NButton')
      export const NResult = stub('NResult')
      export const NSkeleton = stub('NSkeleton')
    `
  },
}

test('real memory router lazy-loads and renders the project overview SFC', async () => {
  const originalFetch = global.fetch
  const requests = []
  global.fetch = async url => {
    requests.push(String(url))
    return new Response(JSON.stringify({
      id: 'project-1',
      title: '典镇山河',
      archivedAt: null,
      lifecycleRevision: 1,
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }

  const vite = await createServer({
    root: frontendRoot,
    server: { middlewareMode: true },
    appType: 'custom',
    logLevel: 'error',
    plugins: [naiveUiStubPlugin],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })

  try {
    const { projectRoutes } = await vite.ssrLoadModule('/src/router/projectRoutes.js')
    const router = createRouter({
      history: createMemoryHistory(),
      routes: projectRoutes,
    })
    await router.push('/projects/project-1/overview')
    await router.isReady()

    const app = createSSRApp({ render: () => h(RouterView) })
    app.use(createPinia())
    app.use(router)
    const html = await renderToString(app)

    assert.match(html, /class="overview-page"/)
    assert.match(html, /aria-busy="true"/)
    assert.equal(router.currentRoute.value.name, 'ProjectOverview')
    assert.deepEqual(requests, ['http://127.0.0.1:8000/api/projects/project-1'])
  } finally {
    await vite.close()
    global.fetch = originalFetch
  }
})
