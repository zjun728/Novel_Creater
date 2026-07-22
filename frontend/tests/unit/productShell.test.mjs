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

test('shell model exposes the three frozen global destinations', async () => {
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
    [
      ['项目库', '/projects'],
      ['创作资产', '/assets/styles'],
      ['设置', '/settings/providers'],
    ],
  )
  assert.deepEqual(
    shell.globalNavigation.map(item => [item.label, item.path, item.selected]),
    [
      ['项目库', '/projects', true],
      ['创作资产', '/assets/styles', false],
      ['设置', '/settings/providers', false],
    ],
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
    [
      ['项目概览', '/projects/project%201/overview', true],
      ['创作种子', '/projects/project%201/seeds', false],
      ['创作契约', '/projects/project%201/contract', false],
      ['模型绑定', '/projects/project%201/settings/models', false],
    ],
  )
  const seeds = createProductShellModel({
    route: route(
      'ProjectSeeds',
      '/projects/project%201/seeds',
      { projectId: 'project 1' },
    ),
    project: {
      id: 'project 1',
      title: '典镇山河',
      archivedAt: null,
    },
  })
  assert.equal(seeds.routeTitle, '创作种子')
  assert.equal(
    seeds.projectContext.modules.find(item => item.key === 'seeds').selected,
    true,
  )
  const contract = createProductShellModel({
    route: route(
      'ProjectContract',
      '/projects/project%201/contract',
      { projectId: 'project 1' },
    ),
    project: {
      id: 'project 1',
      title: '典镇山河',
      archivedAt: null,
    },
  })
  assert.equal(contract.routeTitle, '创作契约')
  assert.equal(
    contract.projectContext.modules.find(item => item.key === 'contract').selected,
    true,
  )
  assert.deepEqual(
    active.breadcrumbs.map(item => [item.label, item.path]),
    [['项目库', '/projects'], ['典镇山河', '/projects/project%201/overview']],
  )

  assert.equal(archived.projectContext.title, '旧稿')
  assert.equal(archived.projectContext.archived, true)
  assert.equal(archived.projectContext.statusLabel, '已归档')
  assert.deepEqual(
    archived.projectContext.modules.map(item => [item.label, item.path, item.selected]),
    [
      ['项目概览', '/projects/archived-1/overview', true],
      ['创作契约', '/projects/archived-1/contract', false],
    ],
  )
  assert.equal(archived.routeTitle, '已归档项目')

  const archivedContract = createProductShellModel({
    route: route(
      'ProjectContract',
      '/projects/archived-1/contract',
      { projectId: 'archived-1' },
    ),
    project: {
      id: 'archived-1',
      title: '旧稿',
      archivedAt: 1_752_800_000,
    },
  })
  assert.equal(archivedContract.routeTitle, '已归档创作契约')
  assert.equal(
    archivedContract.projectContext.modules.find(item => item.key === 'contract').selected,
    true,
  )
  assert.equal(
    archivedContract.projectContext.modules.some(item => ['seeds', 'models'].includes(item.key)),
    false,
  )
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
  { path: '/assets/styles', name: 'StyleLibrary', component: Page },
  { path: '/assets/experience', name: 'ExperienceLibrary', component: Page },
  { path: '/assets/corpus', name: 'CorpusLibrary', component: Page },
  {
    path: '/projects/:projectId/overview',
    name: 'ProjectOverview',
    component: Page,
  },
  {
    path: '/projects/:projectId/seeds',
    name: 'ProjectSeeds',
    component: Page,
  },
  {
    path: '/projects/:projectId/contract',
    name: 'ProjectContract',
    component: Page,
  },
  {
    path: '/projects/:projectId/settings/models',
    name: 'ProjectModelSettings',
    component: Page,
  },
  {
    path: '/settings/providers',
    name: 'ProviderSettings',
    component: Page,
  },
  {
    path: '/settings/application',
    name: 'ApplicationSettings',
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
  const assets = await renderApp('/assets/styles')
  const settings = await renderApp('/settings/providers')

  assert.match(
    projects.html,
    /<a(?=[^>]*href="\/projects")(?=[^>]*aria-current="page")[^>]*>/,
  )
  assert.match(projects.html, /href="\/settings\/providers"/)
  assert.match(projects.html, /href="\/assets\/styles"/)
  assert.match(projects.html, /class="product-topbar__title"[^>]*>项目库</)
  assert.doesNotMatch(projects.html, /返回项目库|切换项目|v0\.1 本地地基版/)

  assert.match(
    assets.html,
    /<a(?=[^>]*href="\/assets\/styles")(?=[^>]*aria-current="page")[^>]*>/,
  )
  assert.match(assets.html, /class="product-topbar__title"[^>]*>风格模板库</)

  assert.match(
    settings.html,
    /<a(?=[^>]*href="\/settings\/providers")(?=[^>]*aria-current="page")[^>]*>/,
  )
  assert.match(settings.html, /class="product-topbar__title"[^>]*>Provider 与模型</)
  assert.deepEqual(projects.requests, [])
  assert.deepEqual(assets.requests, [])
  assert.deepEqual(settings.requests, [])
})

test('creative asset pages share global selection and route-aware breadcrumbs', async () => {
  const { createProductShellModel } = await loadShellModule()
  const styles = createProductShellModel({
    route: route('StyleLibrary', '/assets/styles'),
    viewportWidth: 1440,
  })
  const experience = createProductShellModel({
    route: route('ExperienceLibrary', '/assets/experience'),
    viewportWidth: 1440,
  })
  const corpus = createProductShellModel({
    route: route('CorpusLibrary', '/assets/corpus'),
    viewportWidth: 1440,
  })

  assert.equal(
    styles.globalNavigation.find(item => item.key === 'assets').selected,
    true,
  )
  assert.equal(
    experience.globalNavigation.find(item => item.key === 'assets').selected,
    true,
  )
  assert.equal(
    corpus.globalNavigation.find(item => item.key === 'assets').selected,
    true,
  )
  assert.equal(styles.routeTitle, '风格模板库')
  assert.equal(experience.routeTitle, '经验卡库')
  assert.equal(corpus.routeTitle, '语料档案室')
  assert.deepEqual(styles.breadcrumbs, [
    { label: '创作资产', path: '/assets/styles' },
    { label: '风格模板', path: '/assets/styles' },
  ])
  assert.deepEqual(experience.breadcrumbs, [
    { label: '创作资产', path: '/assets/styles' },
    { label: '经验卡', path: '/assets/experience' },
  ])
  assert.deepEqual(corpus.breadcrumbs, [
    { label: '创作资产', path: '/assets/styles' },
    { label: '语料档案室', path: '/assets/corpus' },
  ])
  assert.deepEqual(
    corpus.assetNavigation.map(item => [item.path, item.selected]),
    [
      ['/assets/styles', false],
      ['/assets/experience', false],
      ['/assets/corpus', true],
    ],
  )
})

test('application settings is selected under Settings and has a safe title', async () => {
  const { createProductShellModel } = await loadShellModule()
  const shell = createProductShellModel({
    route: route('ApplicationSettings', '/settings/application'),
    viewportWidth: 1440,
  })

  assert.equal(
    shell.globalNavigation.find(item => item.key === 'settings').selected,
    true,
  )
  assert.equal(shell.routeTitle, '应用默认与诊断')
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
        { path: '/assets/styles', name: 'StyleLibrary', component: Page },
        { path: '/assets/experience', name: 'ExperienceLibrary', component: Page },
        { path: '/settings/providers', name: 'ProviderSettings', component: Page },
        {
          path: '/projects/:projectId/overview',
          name: 'ProjectOverview',
          component: ActualProjectOverview,
        },
        {
          path: '/projects/:projectId/seeds',
          name: 'ProjectSeeds',
          component: Page,
        },
        {
          path: '/projects/:projectId/contract',
          name: 'ProjectContract',
          component: Page,
        },
        {
          path: '/projects/:projectId/settings/models',
          name: 'ProjectModelSettings',
          component: Page,
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
        { path: '/assets/styles', name: 'StyleLibrary', component: Page },
        { path: '/assets/experience', name: 'ExperienceLibrary', component: Page },
        { path: '/settings/providers', name: 'ProviderSettings', component: Page },
        {
          path: '/projects/:projectId/overview',
          name: 'ProjectOverview',
          component: ActualProjectOverview,
        },
        {
          path: '/projects/:projectId/seeds',
          name: 'ProjectSeeds',
          component: Page,
        },
        {
          path: '/projects/:projectId/contract',
          name: 'ProjectContract',
          component: Page,
        },
        {
          path: '/projects/:projectId/settings/models',
          name: 'ProjectModelSettings',
          component: Page,
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

test('archived project shell exposes only overview and read-only contract navigation', async () => {
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
  assert.match(html, /href="\/projects\/archived-1\/overview"/)
  assert.match(html, /href="\/projects\/archived-1\/contract"/)
  assert.doesNotMatch(html, /href="\/projects\/archived-1\/(?:seeds|settings\/models)"/)
})

test('archived status view links directly to the read-only creation contract', async () => {
  const source = await readFile(
    new URL('../../src/views/ArchivedProjectStatusView.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /projectContractPath/)
  assert.match(source, /查看只读创作契约/)
  assert.doesNotMatch(source, /projectModelSettingsPath|模型绑定/)
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
  assert.match(html, /aria-label="创作资产"/)
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

test('project overview has one clear entry into the formal contract workspace', async () => {
  const overview = await readFile(
    new URL('../../src/views/ProjectOverviewView.vue', import.meta.url),
    'utf8',
  )
  assert.match(overview, /projectContractPath/)
  assert.match(overview, /进入创作契约工作区/)
  assert.equal((overview.match(/projectContractPath\(/g) || []).length, 1)
  assert.doesNotMatch(overview, /WriterView|\/writer\//)
})

test('unreachable writer views cannot reintroduce retired project navigation', async () => {
  const sources = await Promise.all([
    readFile(new URL('../../src/views/WriterView.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/views/WriterUnavailableView.vue', import.meta.url), 'utf8'),
  ])
  const combined = sources.join('\n')

  assert.doesNotMatch(combined, /\/project\//)
  assert.doesNotMatch(combined, /[`'"]\/writer\//)
  assert.doesNotMatch(combined, /router\.push\(['"]\/['"]\)/)
  assert.match(combined, /chapterWriterPath/)
  assert.match(combined, /projectOverviewPath/)
  assert.match(combined, /projectLibraryPath/)
})
