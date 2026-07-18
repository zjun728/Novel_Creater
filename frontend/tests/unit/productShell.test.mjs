import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createPinia } from 'pinia'
import { createSSRApp, defineComponent, h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveUiStubId = '\0product-shell-naive-ui-stub'

const naiveUiStubPlugin = {
  name: 'product-shell-naive-ui-stub',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveUiStubId
  },
  load(id) {
    if (id !== naiveUiStubId) return undefined
    return `
      import { defineComponent, h } from 'vue'
      const stub = (name, tag = 'div') => defineComponent({
        name,
        inheritAttrs: false,
        setup(_, { attrs, slots }) {
          return () => h(tag, attrs, slots.default?.())
        },
      })
      export const NAlert = stub('NAlert', 'aside')
      export const NButton = stub('NButton', 'button')
      export const NConfigProvider = stub('NConfigProvider')
      export const NDialogProvider = stub('NDialogProvider')
      export const NMessageProvider = stub('NMessageProvider')
      export const NResult = stub('NResult')
      export const NSkeleton = stub('NSkeleton')
      export const dateZhCN = {}
      export const zhCN = {}
    `
  },
}

async function loadShellModule() {
  try {
    return await import('../../src/components/layout/productShell.js')
  } catch (error) {
    assert.fail(`route-driven product shell model is missing: ${error.message}`)
  }
}

function route(name, path, params = {}) {
  return { name, path, params }
}

test('shell model exposes only the two frozen global destinations', async () => {
  const {
    createProductShellModel,
    GLOBAL_SHELL_DESTINATIONS,
  } = await loadShellModule()
  const shell = createProductShellModel({
    route: route('ProjectLibrary', '/projects'),
    project: null,
    viewportWidth: 1440,
  })

  assert.deepEqual(
    GLOBAL_SHELL_DESTINATIONS.map(item => [item.label, item.path]),
    [['项目库', '/projects'], ['设置', '/settings/providers']],
  )
  assert.deepEqual(
    shell.globalNavigation.map(item => [item.label, item.path, item.selected]),
    [['项目库', '/projects', true], ['设置', '/settings/providers', false]],
  )
  assert.equal(shell.projectContext, null)
  assert.equal(shell.routeTitle, '项目库')
})

test('active and archived project contexts have different module surfaces', async () => {
  const { createProductShellModel } = await loadShellModule()
  const active = createProductShellModel({
    route: route(
      'ProjectOverview',
      '/projects/project%201/overview',
      { projectId: 'project 1' },
    ),
    project: {
      id: 'project 1',
      title: '典镇山河',
      archivedAt: null,
    },
    viewportWidth: 1440,
  })
  const archived = createProductShellModel({
    route: route(
      'ProjectOverview',
      '/projects/archived-1/overview',
      { projectId: 'archived-1' },
    ),
    project: {
      id: 'archived-1',
      title: '旧稿',
      archivedAt: 1_752_800_000,
    },
    viewportWidth: 1440,
  })

  assert.equal(active.projectContext.title, '典镇山河')
  assert.equal(active.projectContext.archived, false)
  assert.deepEqual(
    active.projectContext.modules.map(item => [item.label, item.path, item.selected]),
    [['项目概览', '/projects/project%201/overview', true]],
  )
  assert.deepEqual(
    active.breadcrumbs.map(item => [item.label, item.path]),
    [['项目库', '/projects'], ['典镇山河', '/projects/project%201/overview']],
  )

  assert.equal(archived.projectContext.title, '旧稿')
  assert.equal(archived.projectContext.archived, true)
  assert.equal(archived.projectContext.statusLabel, '已归档')
  assert.deepEqual(archived.projectContext.modules, [])
  assert.equal(archived.routeTitle, '已归档项目')
})

test('desktop breakpoint collapses navigation without removing the route title', async () => {
  const {
    DESKTOP_SIDEBAR_BREAKPOINT,
    createProductShellModel,
  } = await loadShellModule()
  const project = { id: 'project-1', title: '典镇山河', archivedAt: null }
  const currentRoute = route(
    'ProjectOverview',
    '/projects/project-1/overview',
    { projectId: 'project-1' },
  )
  const compact = createProductShellModel({
    route: currentRoute,
    project,
    viewportWidth: DESKTOP_SIDEBAR_BREAKPOINT - 1,
  })
  const desktop = createProductShellModel({
    route: currentRoute,
    project,
    viewportWidth: DESKTOP_SIDEBAR_BREAKPOINT,
  })

  assert.equal(compact.sidebarCollapsed, true)
  assert.equal(compact.routeTitle, '项目概览')
  assert.equal(compact.projectContext.title, '典镇山河')
  assert.equal(desktop.sidebarCollapsed, false)
})

let vite
let App
let Sidebar
let TopBar
let ActualProjectOverview

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('../../src', import.meta.url)),
      },
    },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin(), naiveUiStubPlugin],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  App = (await vite.ssrLoadModule('/src/App.vue')).default
  Sidebar = (await vite.ssrLoadModule('/src/components/layout/Sidebar.vue')).default
  TopBar = (await vite.ssrLoadModule('/src/components/layout/TopBar.vue')).default
  ActualProjectOverview = (
    await vite.ssrLoadModule('/src/views/ProjectOverviewView.vue')
  ).default
})

test.after(async () => {
  await vite?.close()
})

const Page = defineComponent({
  name: 'TestRoutePage',
  render: () => h('main', { 'data-route-page': '' }),
})

const shellRoutes = [
  { path: '/projects', name: 'ProjectLibrary', component: Page },
  { path: '/projects/archived', name: 'ArchivedProjects', component: Page },
  {
    path: '/projects/:projectId/overview',
    name: 'ProjectOverview',
    component: Page,
  },
  {
    path: '/settings/providers',
    name: 'ProviderSettings',
    component: Page,
  },
]

async function renderApp(path, projectResponse = null) {
  const originalFetch = global.fetch
  const requests = []
  global.fetch = async url => {
    requests.push(String(url))
    if (!projectResponse) {
      return new Response('Not found', {
        status: 404,
        headers: { 'content-type': 'application/json' },
      })
    }
    return new Response(JSON.stringify(projectResponse), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }

  try {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: shellRoutes,
    })
    await router.push(path)
    await router.isReady()
    const app = createSSRApp(App)
    app.use(createPinia())
    app.use(router)
    return {
      html: await renderToString(app),
      requests,
    }
  } finally {
    global.fetch = originalFetch
  }
}

test('real memory router renders global project and settings shell states', async () => {
  const projects = await renderApp('/projects')
  const settings = await renderApp('/settings/providers')

  assert.match(
    projects.html,
    /<a(?=[^>]*href="\/projects")(?=[^>]*aria-current="page")[^>]*>/,
  )
  assert.match(projects.html, /href="\/settings\/providers"/)
  assert.match(projects.html, /class="product-topbar__title"[^>]*>项目库</)
  assert.doesNotMatch(projects.html, /返回项目库|切换项目|v0\.1 本地地基版/)

  assert.match(
    settings.html,
    /<a(?=[^>]*href="\/settings\/providers")(?=[^>]*aria-current="page")[^>]*>/,
  )
  assert.match(settings.html, /class="product-topbar__title"[^>]*>Provider 与模型</)
  assert.deepEqual(projects.requests, [])
  assert.deepEqual(settings.requests, [])
})

test('refresh hydration renders the active project title and canonical overview', async () => {
  const { html, requests } = await renderApp(
    '/projects/project-1/overview',
    {
      id: 'project-1',
      title: '典镇山河',
      archivedAt: null,
      lifecycleRevision: 3,
    },
  )

  assert.deepEqual(requests, ['http://127.0.0.1:8000/api/projects/project-1'])
  assert.match(html, /class="product-sidebar__project-title"[^>]*>典镇山河</)
  assert.match(
    html,
    /<a(?=[^>]*class="[^"]*product-sidebar__module-link)(?=[^>]*href="\/projects\/project-1\/overview")[^>]*>/,
  )
  assert.match(html, /href="\/projects"[^>]*>项目库</)
  assert.match(html, /href="\/projects\/project-1\/overview"[^>]*>典镇山河</)
  assert.match(html, /class="product-topbar__title"[^>]*>项目概览</)
})

test('the real project overview consumes shell hydration without a duplicate read', async () => {
  const originalFetch = global.fetch
  const requests = []
  global.fetch = async url => {
    requests.push(String(url))
    return new Response(JSON.stringify({
      id: 'project-1',
      title: '典镇山河',
      archivedAt: null,
      lifecycleRevision: 3,
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }

  try {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/projects', name: 'ProjectLibrary', component: Page },
        { path: '/settings/providers', name: 'ProviderSettings', component: Page },
        {
          path: '/projects/:projectId/overview',
          name: 'ProjectOverview',
          component: ActualProjectOverview,
        },
      ],
    })
    await router.push('/projects/project-1/overview')
    await router.isReady()
    const app = createSSRApp(App)
    app.use(createPinia())
    app.use(router)
    const html = await renderToString(app)

    assert.deepEqual(requests, ['http://127.0.0.1:8000/api/projects/project-1'])
    assert.match(html, /class="product-sidebar__project-title"[^>]*>典镇山河</)
  } finally {
    global.fetch = originalFetch
  }
})

test('shared shell hydration preserves the explicit missing-project route state', async () => {
  const originalFetch = global.fetch
  const requests = []
  global.fetch = async url => {
    requests.push(String(url))
    return new Response(JSON.stringify({
      error: {
        code: 'ProjectNotFound',
        message: 'Project not found',
      },
    }), {
      status: 404,
      headers: { 'content-type': 'application/json' },
    })
  }

  try {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/projects', name: 'ProjectLibrary', component: Page },
        { path: '/settings/providers', name: 'ProviderSettings', component: Page },
        {
          path: '/projects/:projectId/overview',
          name: 'ProjectOverview',
          component: ActualProjectOverview,
        },
      ],
    })
    await router.push('/projects/missing-1/overview')
    await router.isReady()
    const app = createSSRApp(App)
    app.use(createPinia())
    app.use(router)
    const html = await renderToString(app)

    assert.deepEqual(requests, ['http://127.0.0.1:8000/api/projects/missing-1'])
    assert.match(html, /项目不存在或已被删除/)
    assert.doesNotMatch(html, /项目暂时无法加载/)
  } finally {
    global.fetch = originalFetch
  }
})

test('archived project shell is visibly read-only and has no module links', async () => {
  const { html } = await renderApp(
    '/projects/archived-1/overview',
    {
      id: 'archived-1',
      title: '旧稿',
      archivedAt: 1_752_800_000,
      lifecycleRevision: 4,
    },
  )

  assert.match(html, /class="product-sidebar__archive-mark"[^>]*>\s*已归档\s*</)
  assert.match(html, /class="product-topbar__title"[^>]*>已归档项目</)
  assert.doesNotMatch(html, /product-sidebar__module-link/)
})

test('collapsed shell SFC keeps route title in the top bar', async () => {
  const { createProductShellModel } = await loadShellModule()
  const shell = createProductShellModel({
    route: route(
      'ProjectOverview',
      '/projects/project-1/overview',
      { projectId: 'project-1' },
    ),
    project: { id: 'project-1', title: '典镇山河', archivedAt: null },
    viewportWidth: 800,
  })
  const router = createRouter({
    history: createMemoryHistory(),
    routes: shellRoutes,
  })
  await router.push('/projects/project-1/overview')
  await router.isReady()
  const Harness = defineComponent({
    render: () => h('div', [
      h(Sidebar, { shell }),
      h(TopBar, { shell }),
    ]),
  })
  const app = createSSRApp(Harness)
  app.use(router)
  const html = await renderToString(app)

  assert.match(html, /data-collapsed="true"/)
  assert.match(html, /class="product-topbar__title"[^>]*>项目概览</)
  assert.match(html, /aria-label="项目库"/)
  assert.match(html, /aria-label="设置"/)
})

test('provider settings route wraps only the safe Provider and model surface', async () => {
  const [providerView, retiredSettings] = await Promise.all([
    readFile(new URL('../../src/views/ProviderSettingsView.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/views/SettingsView.vue', import.meta.url), 'utf8')
      .catch(() => ''),
  ])

  assert.match(providerView, /ProviderSettings/)
  assert.doesNotMatch(providerView, /CreationAssetSettings|CorpusSettings|n-tabs/)
  assert.equal(retiredSettings, '')
})

test('unreachable writer views cannot reintroduce retired project navigation', async () => {
  const sources = await Promise.all([
    readFile(new URL('../../src/views/WriterView.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/views/WriterUnavailableView.vue', import.meta.url), 'utf8'),
  ])
  const combined = sources.join('\n')

  assert.doesNotMatch(combined, /\/project\//)
  assert.doesNotMatch(combined, /router\.push\(['"]\/['"]\)/)
  assert.match(combined, /projectOverviewPath/)
  assert.match(combined, /projectLibraryPath/)
})
