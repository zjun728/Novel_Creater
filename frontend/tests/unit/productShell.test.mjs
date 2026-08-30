import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createPinia } from 'pinia'
import { createSSRApp, defineComponent, h, reactive } from 'vue'
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

function declaredTargetSize(source, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const block = source.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`))?.[1] || ''
  const declarations = Object.fromEntries(
    [...block.matchAll(/([\w-]+)\s*:\s*([^;]+);?/g)].map(([, property, value]) => [property, value.trim()]),
  )
  const pixels = property => Number.parseFloat(declarations[property] || '0')
  return { inline: pixels('min-width'), block: pixels('min-height') }
}

test('shell model exposes topic center as the first global destination', async () => {
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
      ['选题中心', '/topics/market'],
      ['项目库', '/projects'],
      ['创作资产', '/assets/styles'],
      ['设置', '/settings/providers'],
    ],
  )
  assert.deepEqual(
    shell.globalNavigation.map(item => [item.label, item.path, item.selected]),
    [
      ['选题中心', '/topics/market', false],
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
      ['创作圣经', '/projects/project%201/bible', false],
      ['分卷规划', '/projects/project%201/planning/volumes', false],
      ['情节线', '/projects/project%201/planning/plots', false],
      ['故事块', '/projects/project%201/planning/story-blocks', false],
      ['作品稿件', '/projects/project%201/manuscript', false],
      ['模型绑定', '/projects/project%201/settings/models', false],
      ['导出与备份', '/projects/project%201/settings/export', false],
    ],
  )
  assert.deepEqual(
    active.projectContext.sections.map(section => [
      section.label,
      section.items.map(item => item.label),
    ]),
    [
      ['', ['项目概览']],
      ['创作基础', ['创作种子', '创作契约', '创作圣经']],
      ['故事规划', ['分卷规划', '情节线', '故事块']],
      ['写作与稿件', ['作品稿件']],
      ['项目配置', ['模型绑定', '导出与备份']],
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
      ['创作圣经', '/projects/archived-1/bible', false],
      ['分卷规划', '/projects/archived-1/planning/volumes', false],
      ['情节线', '/projects/archived-1/planning/plots', false],
      ['故事块', '/projects/archived-1/planning/story-blocks', false],
      ['作品稿件', '/projects/archived-1/manuscript', false],
      ['导出与备份', '/projects/archived-1/settings/export', false],
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

test('each planning tab selects its own truthful grouped navigation item', async () => {
  const { createProductShellModel } = await loadShellModule()
  const titles = {
    ProjectPlanningVolumes: '分卷规划',
    ProjectPlanningPlots: '情节线规划',
    ProjectPlanningStoryBlocks: '故事块规划',
  }
  for (const name of Object.keys(titles)) {
    const shell = createProductShellModel({
      route: route(name, '/projects/project-1/planning/volumes', {
        projectId: 'project-1',
      }),
      project: { id: 'project-1', title: '典镇山河', archivedAt: null },
    })
    const planning = shell.projectContext.modules.find(item => item.selected)
    assert.equal(planning.selected, true)
    assert.equal(planning.path, {
      ProjectPlanningVolumes: '/projects/project-1/planning/volumes',
      ProjectPlanningPlots: '/projects/project-1/planning/plots',
      ProjectPlanningStoryBlocks: '/projects/project-1/planning/story-blocks',
    }[name])
    assert.equal(shell.routeTitle, titles[name])
  }

  const archived = createProductShellModel({
    route: route('ProjectPlanningPlots', '/projects/old/planning/plots', {
      projectId: 'old',
    }),
    project: { id: 'old', title: '旧稿', archivedAt: 1 },
  })
  assert.equal(archived.projectContext.modules.find(item => item.key === 'plots').selected, true)
  assert.equal(archived.routeTitle, '已归档情节线规划')

  const archivedStoryBlocks = createProductShellModel({
    route: route('ProjectPlanningStoryBlocks', '/projects/old/planning/story-blocks', {
      projectId: 'old',
    }),
    project: { id: 'old', title: '旧稿', archivedAt: 1 },
  })
  assert.equal(
    archivedStoryBlocks.projectContext.modules.find(item => item.key === 'story-blocks').selected,
    true,
  )
  assert.equal(archivedStoryBlocks.routeTitle, '已归档故事块规划')
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

test('application shell owns the only main landmark and begins with a skip link', async () => {
  const app = await readFile(new URL('../../src/App.vue', import.meta.url), 'utf8')
  assert.match(app, /class="skip-link"[^>]*href="#main-content"[^>]*>跳到主内容</)
  assert.equal((app.match(/<main\b/g) || []).length, 1)
  assert.match(app, /<main[^>]*id="main-content"[^>]*tabindex="-1"/)
  assert.match(app, /MobileNavigationDrawer/)
  assert.match(app, /ref="shellRegion"[\s\S]*class="skip-link"[\s\S]*class="product-app-shell"/)
})

test('shell CSS preserves touch size, wrapping, mobile layout, and reduced motion', async () => {
  const [style, sidebar, index, reader] = await Promise.all([
    readFile(new URL('../../src/style.css', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/layout/Sidebar.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/views/ManuscriptIndexView.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/views/FinalChapterReaderView.vue', import.meta.url), 'utf8'),
  ])
  assert.match(style, /@media \(max-width: 760px\)/)
  assert.match(style, /grid-template-columns:\s*minmax\(0, 1fr\)/)
  assert.match(style, /\.product-mobile-topbar button[\s\S]*?min-height:\s*44px/)
  assert.match(sidebar, /\.product-sidebar__nav-link,[\s\S]*?min-height:\s*44px/)
  assert.match(sidebar, /\.product-sidebar__asset-subnav a[\s\S]*?min-height:\s*44px/)
  assert.match(
    sidebar,
    /\.product-sidebar__section-heading\s*\{[^}]*color:\s*var\(--nc-muted\)[^}]*font-size:\s*11px/s,
  )
  const topbar = await readFile(new URL('../../src/components/layout/TopBar.vue', import.meta.url), 'utf8')
  assert.match(topbar, /\.product-topbar__breadcrumbs a[\s\S]*?min-height:\s*44px/)
  assert.deepEqual(declaredTargetSize(topbar, '.product-topbar__breadcrumbs a'), { inline: 44, block: 44 })
  for (const source of [style, sidebar, index, reader]) {
    assert.match(source, /@media \(prefers-reduced-motion: reduce\)/)
  }
  assert.match(index, /\.manuscript-index :is\(a,button,summary\)[^}]*min-height:\s*44px/)
  assert.match(reader, /\.final-reader :is\(a, button, summary\)[^}]*min-height:\s*44px/)
  assert.deepEqual(declaredTargetSize(reader, '.final-reader nav a'), { inline: 44, block: 44 })
})

test('route views never introduce a second main landmark inside the application shell', async () => {
  const routes = await readFile(new URL('../../src/router/projectRoutes.js', import.meta.url), 'utf8')
  const names = [...routes.matchAll(/const\s+(\w+View)\s*=\s*\(\)\s*=>\s*import\('\.\.\/views\/([^']+\.vue)'\)/g)]
  assert.ok(names.length >= 15)
  for (const [, component, filename] of names) {
    const source = await readFile(new URL(`../../src/views/${filename}`, import.meta.url), 'utf8')
    assert.doesNotMatch(source, /<\/?main\b/, `${component} must render inside App's one main landmark`)
  }
})

test('forced shell hydration bypasses a matching cached project for lifecycle authority', async () => {
  const { useShellProjectHydration } = await loadShellModule()
  const cached = {
    id: 'project-1',
    title: '典镇山河',
    archivedAt: null,
  }
  const routeState = reactive({
    params: { projectId: 'project-1' },
  })
  const calls = []
  const store = {
    currentProject: cached,
    async loadProject(projectId) {
      calls.push(projectId)
      return {
        ...cached,
        archivedAt: 1,
        lifecycleRevision: 2,
      }
    },
  }
  let context
  const Harness = defineComponent({
    setup() {
      context = useShellProjectHydration({ route: routeState, store })
      return () => h('div')
    },
  })
  await renderToString(createSSRApp(Harness))

  assert.deepEqual(calls, [])
  assert.equal(context.state.value, 'active')
  await context.reload({ force: true })

  assert.deepEqual(calls, ['project-1'])
  assert.equal(context.state.value, 'archived')
  assert.equal(context.project.value.archivedAt, 1)
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
  render: () => h('section', { 'data-route-page': '' }),
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
    path: '/projects/:projectId/bible',
    name: 'ProjectBible',
    component: Page,
  },
  {
    path: '/projects/:projectId/planning/volumes',
    name: 'ProjectPlanningVolumes',
    component: Page,
  },
  {
    path: '/projects/:projectId/planning/plots',
    name: 'ProjectPlanningPlots',
    component: Page,
  },
  {
    path: '/projects/:projectId/planning/story-blocks',
    name: 'ProjectPlanningStoryBlocks',
    component: Page,
  },
  {
    path: '/projects/:projectId/manuscript',
    name: 'ProjectManuscript',
    component: Page,
  },
  {
    path: '/projects/:projectId/settings/models',
    name: 'ProjectModelSettings',
    component: Page,
  },
  {
    path: '/projects/:projectId/settings/export',
    name: 'ProjectExport',
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
    if (String(url).endsWith('/overview')) {
      return new Response(JSON.stringify({
        project: {
          id: 'project-1', title: '典镇山河', genre: '东方玄幻',
          logline: '山河待定。', targetWords: 2_400_000, targetChapters: 800,
          updatedAtMs: 1, lifecycle: 'active',
        },
        progress: {
          authoritativeChapterNumber: 1, currentVolume: null,
          latestFinalChapter: null, finalizedChapterCount: 0, finalizedScalarCount: 0,
        },
        modules: {
          seed: 'missing', contract: 'missing', bible: 'missing',
          planning: 'missing', outline: 'missing', writing: 'missing',
        },
        writerCore: { canonRevision: 0, projectionRevision: 0, synchronized: true },
        continuity: { availability: 'pending_module', pendingCount: null },
        recentAchievements: [],
      }), { status: 200, headers: { 'content-type': 'application/json' } })
    }
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
          path: '/projects/:projectId/bible',
          name: 'ProjectBible',
          component: Page,
        },
        {
          path: '/projects/:projectId/planning/volumes',
          name: 'ProjectPlanningVolumes',
          component: Page,
        },
        {
          path: '/projects/:projectId/planning/plots',
          name: 'ProjectPlanningPlots',
          component: Page,
        },
        {
          path: '/projects/:projectId/planning/story-blocks',
          name: 'ProjectPlanningStoryBlocks',
          component: Page,
        },
        {
          path: '/projects/:projectId/manuscript',
          name: 'ProjectManuscript',
          component: Page,
        },
        {
          path: '/projects/:projectId/settings/models',
          name: 'ProjectModelSettings',
          component: Page,
        },
        {
          path: '/projects/:projectId/settings/export',
          name: 'ProjectExport',
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

    assert.deepEqual(requests, [
      'http://127.0.0.1:8000/api/projects/project-1',
      'http://127.0.0.1:8000/api/projects/project-1/overview',
    ])
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
          path: '/projects/:projectId/bible',
          name: 'ProjectBible',
          component: Page,
        },
        {
          path: '/projects/:projectId/planning/volumes',
          name: 'ProjectPlanningVolumes',
          component: Page,
        },
        {
          path: '/projects/:projectId/planning/plots',
          name: 'ProjectPlanningPlots',
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

test('archived project shell exposes overview and read-only contract Bible and planning navigation', async () => {
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
  assert.match(html, /href="\/projects\/archived-1\/bible"/)
  assert.match(html, /href="\/projects\/archived-1\/planning\/volumes"/)
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

test('project overview renders manual module links without server-selected navigation authority', async () => {
  const overview = await readFile(
    new URL('../../src/views/ProjectOverviewView.vue', import.meta.url),
    'utf8',
  )

  assert.match(overview, /useProjectStore/)
  assert.match(overview, /projectContractPath|projectBiblePath/)
  assert.match(overview, /class="overview-module"/)
  assert.doesNotMatch(overview, /mapProjectNextAction|actionCopy|overview-next-action/)
  assert.doesNotMatch(overview, /WriterView|\/writer\//)
})

test('retired WriterView is physically absent and no shell test imports it', async () => {
  await assert.rejects(readFile(new URL('../../src/views/WriterView.vue', import.meta.url), 'utf8'))
})
