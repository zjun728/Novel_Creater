import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createPinia } from 'pinia'
import { createSSRApp, h } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
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

async function renderProjectOverview(createViteServer = createServer) {
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

  let vite
  try {
    vite = await createViteServer({
      configFile: false,
      root: frontendRoot,
      server: { middlewareMode: true, hmr: false, ws: false },
      appType: 'custom',
      logLevel: 'error',
      plugins: [vuePlugin(), naiveUiStubPlugin],
      ssr: { noExternal: ['naive-ui'] },
      optimizeDeps: { noDiscovery: true },
    })
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

    return {
      html,
      requests,
      routeName: router.currentRoute.value.name,
    }
  } finally {
    try {
      await vite?.close()
    } finally {
      global.fetch = originalFetch
    }
  }
}

test('real memory router lazy-loads and renders the project overview SFC loading state', async () => {
  const { html, requests, routeName } = await renderProjectOverview()

  assert.match(html, /class="overview-page"/)
  assert.match(html, /aria-busy="true"/)
  assert.equal(routeName, 'ProjectOverview')
  assert.deepEqual(requests, ['http://127.0.0.1:8000/api/projects/project-1'])
})

test('SSR harness restores global fetch when Vite server creation fails', async () => {
  const originalFetch = global.fetch
  const creationFailure = new Error('injected Vite creation failure')
  await assert.rejects(
    renderProjectOverview(async config => {
      assert.deepEqual(config.server, { middlewareMode: true, hmr: false, ws: false })
      throw creationFailure
    }),
    creationFailure,
  )
  assert.equal(global.fetch, originalFetch)
})
