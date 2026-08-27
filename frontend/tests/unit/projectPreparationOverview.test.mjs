import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from '@vue/runtime-core'
import { createRenderer, nextTick, ssrContextKey } from '@vue/runtime-core'
import { createPinia, setActivePinia } from 'pinia'
import { createSSRApp, h, ref, shallowRef } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

import { useProjectStore } from '../../src/stores/projectStore.js'


const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveUiStubId = '\0project-preparation-naive-ui-stub'
const naiveUiStubPlugin = {
  name: 'project-preparation-naive-ui-stub',
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
          return () => h(tag, attrs, [slots.default?.(), slots.footer?.()])
        },
      })
      export const NButton = stub('NButton', 'button')
      export const NAlert = stub('NAlert')
      export const NResult = stub('NResult')
      export const NSkeleton = stub('NSkeleton')
    `
  },
}

const tasks = [
  'seed', 'planning', 'writing', 'audit',
  'summary', 'extraction', 'polish', 'market',
]

function preparation({
  nextAction,
  targetPath,
  selection = 'current',
  contract = 'current',
  bible = 'current',
  planning = 'current',
  outline = 'missing',
  authoritativeChapterNumber = 1,
  planningReady = true,
}) {
  return {
    lifecycle: 'active',
    activeSelection: selection,
    contract,
    bible,
    planning,
    planningOperation: null,
    outline,
    outlineOperation: null,
    authoritativeChapterNumber,
    modelTasks: tasks.map(taskKey => ({
      taskKey,
      readiness: taskKey === 'planning' && !planningReady ? 'not_ready' : 'ready',
      reasons: taskKey === 'planning' && !planningReady ? ['provider_unavailable'] : [],
    })),
    capabilities: {
      viewPreparation: true,
      editContract: selection === 'current',
      editBible: contract === 'current',
      generateBible: planningReady && contract === 'current',
    },
    nextAction,
    targetPath,
    reasons: planningReady ? [] : ['planning_model_not_ready'],
  }
}

function archivedPreparation() {
  return {
    ...preparation({
      nextAction: 'phase_boundary_planning',
      targetPath: null,
    }),
    lifecycle: 'archived',
    capabilities: {
      viewPreparation: true,
      editContract: false,
      editBible: false,
      generateBible: false,
    },
    nextAction: 'archived_read_only',
    reasons: ['project_archived'],
  }
}

function node(type, text = '') {
  return { type, text, props: {}, children: [], parent: null }
}

function detach(child) {
  if (!child?.parent) return
  child.parent.children.splice(child.parent.children.indexOf(child), 1)
  child.parent = null
}

const renderer = createRenderer({
  patchProp(element, key, _oldValue, value) {
    if (value == null) delete element.props[key]
    else element.props[key] = value
  },
  insert(child, parent, anchor = null) {
    detach(child)
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(child)
    else parent.children.splice(index, 0, child)
  },
  remove: detach,
  createElement: type => node(type),
  createText: text => node('#text', String(text)),
  createComment: text => node('#comment', String(text || '')),
  setText(target, text) { target.text = String(text) },
  setElementText(target, text) {
    target.text = String(text)
    target.children = []
  },
  parentNode: target => target?.parent || null,
  nextSibling: target => (
    target?.parent?.children[target.parent.children.indexOf(target) + 1] || null
  ),
  querySelector: () => null,
  setScopeId(element, id) { element.props[id] = '' },
  cloneNode: target => ({
    ...target,
    props: { ...target.props },
    children: [...target.children],
    parent: null,
  }),
  insertStaticContent(content, parent, anchor) {
    const target = node('#static', content)
    renderer.insert(target, parent, anchor)
    return [target, target]
  },
})

async function clientRender(path) {
  const contents = await readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')
  const filename = path.split('/').at(-1)
  const { descriptor } = parse(contents, { filename })
  const script = compileScript(descriptor, {
    id: `preparation-${filename}`,
  })
  const result = compile(descriptor.template.content, {
    mode: 'function',
    prefixIdentifiers: true,
    bindingMetadata: script.bindings,
  })
  return new Function('Vue', result.code)(VueRuntime)
}

async function flush() {
  for (let index = 0; index < 4; index += 1) await Promise.resolve()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

async function waitFor(predicate) {
  for (let index = 0; index < 20; index += 1) {
    if (predicate()) return
    await flush()
  }
  assert.fail('condition did not become true')
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

function renderedText(target) {
  if (!target) return ''
  return [
    target.text,
    target.props?.title,
    target.props?.description,
    ...(target.children || []).map(renderedText),
  ].filter(Boolean).join(' ')
}

function findRenderedNode(target, predicate) {
  if (!target) return null
  if (predicate(target)) return target
  for (const child of target.children || []) {
    const found = findRenderedNode(child, predicate)
    if (found) return found
  }
  return null
}

let vite
let Overview
let ArchivedOverview
let NotFoundOverview
let ShellProjectContext

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin(), naiveUiStubPlugin],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  const DeliveryPanel = (
    await vite.ssrLoadModule('/src/components/projects/NovelDownloadPanel.vue')
  ).default
  DeliveryPanel.render = await clientRender('components/projects/NovelDownloadPanel.vue')
  const BackupPanel = (
    await vite.ssrLoadModule('/src/components/projects/ProjectBackupPanel.vue')
  ).default
  BackupPanel.render = await clientRender('components/projects/ProjectBackupPanel.vue')
  ArchivedOverview = (
    await vite.ssrLoadModule('/src/views/ArchivedProjectStatusView.vue')
  ).default
  ArchivedOverview.render = await clientRender('views/ArchivedProjectStatusView.vue')
  NotFoundOverview = (
    await vite.ssrLoadModule('/src/views/NotFoundView.vue')
  ).default
  NotFoundOverview.render = await clientRender('views/NotFoundView.vue')
  Overview = (await vite.ssrLoadModule('/src/views/ProjectOverviewView.vue')).default
  Overview.render = await clientRender('views/ProjectOverviewView.vue')
  ShellProjectContext = (
    await vite.ssrLoadModule('/src/components/layout/productShell.js')
  ).SHELL_PROJECT_CONTEXT
})

test.after(async () => {
  await vite?.close()
})

async function renderOverview(authority, { fail = false } = {}) {
  const originalFetch = global.fetch
  global.fetch = async url => {
    assert.match(String(url), /\/api\/projects\/project%20%2F%20%E4%B8%80\/preparation$/)
    if (fail) {
      return new Response(JSON.stringify({ detail: 'internal provider identity' }), {
        status: 503,
        headers: { 'content-type': 'application/json' },
      })
    }
    return new Response(JSON.stringify(authority), {
      headers: { 'content-type': 'application/json' },
    })
  }
  try {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useProjectStore()
    try {
      await store.loadPreparation('project / 一')
    } catch {
      // Rendering must expose only the safe retryable UI state.
    }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/projects/:projectId/overview',
          component: Overview,
        },
        {
          path: '/projects/:projectId/seeds',
          component: { template: '<div />' },
        },
        {
          path: '/projects/:projectId/contract',
          component: { template: '<div />' },
        },
        {
          path: '/projects/:projectId/bible',
          component: { template: '<div />' },
        },
        {
          path: '/projects/:projectId/planning/volumes',
          component: { template: '<div />' },
        },
        {
          path: '/projects/:projectId/planning/story-blocks',
          component: { template: '<div />' },
        },
        {
          path: '/projects/:projectId/write/chapters/:chapterNumber',
          component: { template: '<div />' },
        },
      ],
    })
    await router.push('/projects/project%20%2F%20%E4%B8%80/overview')
    await router.isReady()
    const app = createSSRApp(Overview)
    app.use(pinia)
    app.use(router)
    app.provide(ShellProjectContext, {
      state: ref('active'),
      project: shallowRef({
        id: 'project / 一',
        title: '典镇山河',
        archivedAt: null,
      }),
      error: shallowRef(null),
      reload: async () => null,
    })
    return renderToString(app)
  } finally {
    global.fetch = originalFetch
  }
}

test('overview renders one primary server-selected action and compact persisted summaries', async () => {
  const html = await renderOverview(preparation({
    nextAction: 'continue_contract',
    targetPath: '/projects/project%20%2F%20%E4%B8%80/contract',
    contract: 'draft',
    bible: 'missing',
  }))

  assert.equal((html.match(/class="overview-next-action"/g) || []).length, 1)
  assert.match(html, /href="\/projects\/project%20%2F%20%E4%B8%80\/contract"/)
  assert.match(html, /继续创作契约/)
  assert.match(html, /种子[\s\S]*已选择/)
  assert.match(html, /创作契约[\s\S]*草稿/)
  assert.match(html, /创作圣经[\s\S]*未建立/)
})

test('planning next action uses the server target while model loss keeps manual facts', async () => {
  const html = await renderOverview(preparation({
    nextAction: 'continue_planning',
    targetPath: '/projects/project%20%2F%20%E4%B8%80/planning/volumes',
    planningReady: false,
  }))

  assert.equal((html.match(/class="overview-next-action"/g) || []).length, 1)
  assert.match(html, /href="\/projects\/project%20%2F%20%E4%B8%80\/planning\/volumes"/)
  assert.match(html, /继续故事规划/)
  assert.match(html, /规划模型不可用/)
  assert.match(html, /创作契约[\s\S]*已确认/)
  assert.match(html, /创作圣经[\s\S]*已确认/)
})

test('new and recoverable planning states keep the exact server-selected destination', async () => {
  for (const [nextAction, label] of [
    ['establish_planning', '开始故事规划'],
    ['recover_planning_operation', '核对规划生成结果'],
  ]) {
    const html = await renderOverview(preparation({
      nextAction,
      targetPath: '/projects/project%20%2F%20%E4%B8%80/planning/volumes',
    }))
    assert.equal((html.match(/class="overview-next-action"/g) || []).length, 1)
    assert.match(html, /href="\/projects\/project%20%2F%20%E4%B8%80\/planning\/volumes"/)
    assert.match(html, new RegExp(label))
  }
})

test('outline and writer actions navigate only to the exact server targetPath', async () => {
  const cases = [
    ['prepare_chapter_outline', '准备第 8 章小纲', '/server-selected/outline/new'],
    ['continue_chapter_outline', '继续第 8 章小纲', '/server-selected/outline/draft'],
    ['recover_chapter_outline_operation', '核对第 8 章小纲生成结果', '/server-selected/outline/recovery'],
    ['start_chapter_session', '进入第 8 章写作', '/server-selected/writer/start'],
    ['continue_writing', '继续创作第 8 章', '/server-selected/writer/continue'],
  ]
  for (const [nextAction, label, targetPath] of cases) {
    const html = await renderOverview(preparation({
      nextAction,
      targetPath,
      outline: nextAction === 'start_chapter_session' ? 'current' : 'draft',
      authoritativeChapterNumber: 8,
    }))
    assert.equal((html.match(/class="overview-next-action"/g) || []).length, 1)
    assert.match(html, new RegExp(`href="${targetPath}"`))
    assert.match(html, new RegExp(label))
  }
})

test('overview keeps its one primary next action before the manuscript entry and backup', async () => {
  const html = await renderOverview(preparation({
    nextAction: 'continue_contract',
    targetPath: '/projects/project%20%2F%20%E4%B8%80/contract',
    contract: 'draft',
    bible: 'missing',
  }))
  assert.equal((html.match(/class="overview-next-action"/g) || []).length, 1)
  assert.match(html, /manuscript-summary-link/)
  assert.match(html, /project-backup-panel/)
  assert.ok(html.indexOf('manuscript-summary-link') < html.indexOf('overview-next-action'))
  assert.ok(html.indexOf('manuscript-summary-link') < html.indexOf('project-backup-panel'))
})

test('active and archived views pass exact backup authority after the delivery desk', async () => {
  const overviewSource = await readFile(
    new URL('../../src/views/ProjectOverviewView.vue', import.meta.url),
    'utf8',
  )
  const writerSource = await readFile(
    new URL('../../src/views/ChapterWriterView.vue', import.meta.url),
    'utf8',
  )
  const source = await readFile(
    new URL('../../src/views/ArchivedProjectStatusView.vue', import.meta.url),
    'utf8',
  )
  assert.match(overviewSource, /import ProjectBackupPanel/)
  assert.match(overviewSource, /<manuscript-summary-link[\s\S]*<project-backup-panel/)
  assert.match(overviewSource, /import ManuscriptSummaryLink/)
  assert.doesNotMatch(overviewSource, /NovelDownloadPanel|novel-download-panel/)
  assert.match(overviewSource, /<project-backup-panel[\s\S]*:project-id="routeProject\.project\.value\.id"/)
  assert.match(overviewSource, /:title="routeProject\.project\.value\.title"/)
  assert.match(overviewSource, /:lifecycle-revision="routeProject\.project\.value\.lifecycleRevision"/)
  assert.match(overviewSource, /:archived="false"/)
  assert.match(overviewSource, /:flush-current-draft="flushCurrentDraft"/)
  assert.match(source, /import ManuscriptSummaryLink/)
  assert.match(source, /import ProjectBackupPanel/)
  assert.match(source, /<manuscript-summary-link[\s\S]*<project-backup-panel/)
  assert.doesNotMatch(source, /NovelDownloadPanel|novel-download-panel/)
  assert.match(source, /<project-backup-panel[\s\S]*:project-id="project\.id"/)
  assert.match(source, /:title="project\.title"/)
  assert.match(source, /:lifecycle-revision="project\.lifecycleRevision"/)
  assert.match(source, /:archived="true"/)
  assert.doesNotMatch(writerSource, /ProjectBackupPanel|project-backup-panel/)
})

test('overview uses the project store for preparation and the manuscript read model for its summary', async () => {
  const source = await readFile(
    new URL('../../src/views/ProjectOverviewView.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /useProjectStore/)
  assert.match(source, /currentPreparation/)
  assert.match(source, /import ManuscriptSummaryLink/)
  assert.doesNotMatch(
    source,
    /seedStore|creationContractStore|bibleStore|loadSelected|loadContract|loadBible|current_chapter|currentChapter|\+\s*1/,
  )
})

test('overview renders the safe retry action when preparation loading fails', async () => {
  const html = await renderOverview(null, { fail: true })

  assert.match(html, /创作准备状态暂时无法加载/)
  assert.match(html, /重新读取/)
  assert.doesNotMatch(html, /internal provider identity/)
  assert.doesNotMatch(html, /preparation-loading/)
})

test('returning to the same project overview refreshes its server preparation authority', async () => {
  const originalFetch = global.fetch
  const responses = [
    preparation({
      nextAction: 'continue_contract',
      targetPath: '/projects/project%20%2F%20%E4%B8%80/contract',
      contract: 'draft',
      bible: 'missing',
    }),
    preparation({
      nextAction: 'continue_bible',
      targetPath: '/projects/project%20%2F%20%E4%B8%80/bible',
      contract: 'current',
      bible: 'draft',
    }),
  ]
  let preparationReads = 0
  global.fetch = async url => {
    assert.match(String(url), /\/api\/projects\/project%20%2F%20%E4%B8%80\/preparation$/)
    const response = responses[Math.min(preparationReads, responses.length - 1)]
    preparationReads += 1
    return new Response(JSON.stringify(response), {
      headers: { 'content-type': 'application/json' },
    })
  }

  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/projects/:projectId/overview',
        component: Overview,
      },
      {
        path: '/projects/:projectId/contract',
        component: { render: () => h('div', 'contract') },
      },
      {
        path: '/projects/:projectId/bible',
        component: { render: () => h('div', 'bible') },
      },
      {
        path: '/projects/:projectId/planning/volumes',
        component: { render: () => h('div', 'planning') },
      },
    ],
  })
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(pinia)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.provide(ShellProjectContext, {
    state: ref('active'),
    project: shallowRef({
      id: 'project / 一',
      title: '典镇山河',
      archivedAt: null,
    }),
    error: shallowRef(null),
    reload: async () => null,
  })

  try {
    await router.push('/projects/project%20%2F%20%E4%B8%80/overview')
    await router.isReady()
    app.mount(node('root'))
    await waitFor(() => (
      preparationReads === 1
      && useProjectStore(pinia).currentPreparation?.nextAction === 'continue_contract'
    ))
    assert.equal(useProjectStore(pinia).currentPreparation.nextAction, 'continue_contract')

    await router.push('/projects/project%20%2F%20%E4%B8%80/contract')
    await flush()
    await router.push('/projects/project%20%2F%20%E4%B8%80/overview')
    await flush()

    assert.equal(preparationReads, 2)
    assert.equal(useProjectStore(pinia).currentPreparation.nextAction, 'continue_bible')
  } finally {
    app.unmount()
    global.fetch = originalFetch
  }
})

test('an archive observed between tabs reconciles the active shell without showing phase complete', async () => {
  const archived = archivedPreparation()
  const html = await renderOverview(archived)
  assert.match(html, /已归档/)
  assert.doesNotMatch(html, /PHASE 2 COMPLETE|创作准备已完成/)

  const originalFetch = global.fetch
  let preparationReads = 0
  global.fetch = async url => {
    assert.match(String(url), /\/api\/projects\/project%20%2F%20%E4%B8%80\/preparation$/)
    preparationReads += 1
    return new Response(JSON.stringify(archived), {
      headers: { 'content-type': 'application/json' },
    })
  }
  const state = ref('active')
  const project = shallowRef({
    id: 'project / 一',
    title: '典镇山河',
    archivedAt: null,
    lifecycleRevision: 0,
  })
  let shellReloads = 0
  const reload = async () => {
    shellReloads += 1
    state.value = 'archived'
    project.value = {
      ...project.value,
      archivedAt: 1,
      lifecycleRevision: 1,
    }
    return project.value
  }
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/projects/:projectId/overview',
        component: Overview,
      },
      {
        path: '/projects/:projectId/contract',
        component: { render: () => h('div', 'contract') },
      },
      {
        path: '/projects/:projectId/bible',
        component: { render: () => h('div', 'bible') },
      },
      {
        path: '/projects',
        component: { render: () => h('div', 'projects') },
      },
    ],
  })
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(pinia)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.provide(ShellProjectContext, {
    state,
    project,
    error: shallowRef(null),
    reload,
  })

  try {
    await router.push('/projects/project%20%2F%20%E4%B8%80/overview')
    await router.isReady()
    app.mount(node('root'))
    await waitFor(() => shellReloads === 1 && state.value === 'archived')

    assert.equal(preparationReads, 1)
    assert.equal(shellReloads, 1)
    assert.equal(state.value, 'archived')
  } finally {
    app.unmount()
    global.fetch = originalFetch
  }
})

test('a late archived response for the previous project cannot reload the new shell', async () => {
  const originalFetch = global.fetch
  const pendingA = deferred()
  const activeB = preparation({
    nextAction: 'continue_contract',
    targetPath: '/projects/B/contract',
    contract: 'draft',
    bible: 'missing',
  })
  const reads = []
  global.fetch = async url => {
    const value = String(url)
    reads.push(value)
    if (value.endsWith('/projects/A/preparation')) return pendingA.promise
    if (value.endsWith('/projects/B/preparation')) {
      return new Response(JSON.stringify(activeB), {
        headers: { 'content-type': 'application/json' },
      })
    }
    throw new Error(`unexpected URL: ${value}`)
  }
  const state = ref('active')
  const project = shallowRef({
    id: 'A',
    title: 'A',
    archivedAt: null,
  })
  let shellReloads = 0
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/projects/:projectId/overview',
        component: Overview,
      },
      {
        path: '/projects/:projectId/contract',
        component: { render: () => h('div', 'contract') },
      },
    ],
  })
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(pinia)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.provide(ShellProjectContext, {
    state,
    project,
    error: shallowRef(null),
    reload: async () => {
      shellReloads += 1
      return project.value
    },
  })

  try {
    await router.push('/projects/A/overview')
    await router.isReady()
    app.mount(node('root'))
    await waitFor(() => reads.some(value => value.endsWith('/projects/A/preparation')))

    project.value = {
      id: 'B',
      title: 'B',
      archivedAt: null,
    }
    await router.push('/projects/B/overview')
    await waitFor(() => (
      useProjectStore(pinia).preparationProjectId === 'B'
      && useProjectStore(pinia).currentPreparation?.nextAction
        === 'continue_contract'
    ))

    pendingA.resolve(new Response(JSON.stringify(archivedPreparation()), {
      headers: { 'content-type': 'application/json' },
    }))
    await flush()

    assert.equal(shellReloads, 0)
    assert.equal(useProjectStore(pinia).preparationProjectId, 'B')
    assert.equal(
      useProjectStore(pinia).currentPreparation.nextAction,
      'continue_contract',
    )
  } finally {
    app.unmount()
    global.fetch = originalFetch
  }
})

test('an active force result never spins and only explicit resync starts another attempt', async () => {
  const originalFetch = global.fetch
  global.fetch = async url => {
    assert.match(String(url), /\/api\/projects\/project%20%2F%20%E4%B8%80\/preparation$/)
    return new Response(JSON.stringify(archivedPreparation()), {
      headers: { 'content-type': 'application/json' },
    })
  }
  const state = ref('active')
  const project = shallowRef({
    id: 'project / 一',
    title: '典镇山河',
    archivedAt: null,
  })
  let shellReloads = 0
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/projects/:projectId/overview',
        component: Overview,
      },
    ],
  })
  const root = node('root')
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(pinia)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.provide(ShellProjectContext, {
    state,
    project,
    error: shallowRef(null),
    reload: async options => {
      shellReloads += 1
      assert.equal(options?.force, true)
      if (shellReloads <= 4) {
        state.value = 'loading'
        await Promise.resolve()
        state.value = 'active'
      }
      return project.value
    },
  })

  try {
    await router.push('/projects/project%20%2F%20%E4%B8%80/overview')
    await router.isReady()
    app.mount(root)
    await waitFor(() => shellReloads >= 1)
    for (let index = 0; index < 8; index += 1) await flush()

    assert.equal(shellReloads, 1)
    assert.match(renderedText(root), /正在同步项目权威状态/)
    const resync = findRenderedNode(
      root,
      target => (
        target.type === 'button'
        && /重新同步/.test(renderedText(target))
      ),
    )
    assert.ok(resync)
    await resync.props.onClick()
    for (let index = 0; index < 8; index += 1) await flush()

    assert.equal(shellReloads, 2)
    assert.equal(state.value, 'active')
    assert.match(renderedText(root), /正在同步项目权威状态/)
  } finally {
    app.unmount()
    global.fetch = originalFetch
  }
})

test('archived reconciliation exposes a failed shell reload and explicit retry reaches the archived view', async () => {
  const originalFetch = global.fetch
  const archived = archivedPreparation()
  global.fetch = async url => {
    assert.match(String(url), /\/api\/projects\/project%20%2F%20%E4%B8%80\/preparation$/)
    return new Response(JSON.stringify(archived), {
      headers: { 'content-type': 'application/json' },
    })
  }
  const state = ref('active')
  const project = shallowRef({
    id: 'project / 一',
    title: '典镇山河',
    archivedAt: null,
    lifecycleRevision: 0,
  })
  const error = shallowRef(null)
  const forceValues = []
  let shellReloads = 0
  const reload = async options => {
    shellReloads += 1
    forceValues.push(options?.force)
    if (shellReloads === 1) {
      error.value = new Error('shell unavailable')
      state.value = 'error'
      return null
    }
    error.value = null
    state.value = 'archived'
    project.value = {
      ...project.value,
      archivedAt: 1,
      lifecycleRevision: 1,
    }
    return project.value
  }
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/projects/:projectId/overview',
        component: Overview,
      },
      {
        path: '/projects/:projectId/contract',
        component: { render: () => h('div', 'contract') },
      },
      {
        path: '/projects/:projectId/bible',
        component: { render: () => h('div', 'bible') },
      },
      {
        path: '/projects',
        component: { render: () => h('div', 'projects') },
      },
    ],
  })
  const root = node('root')
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(pinia)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.provide(ShellProjectContext, {
    state,
    project,
    error,
    reload,
  })

  try {
    await router.push('/projects/project%20%2F%20%E4%B8%80/overview')
    await router.isReady()
    app.mount(root)
    await waitFor(() => shellReloads === 1 && state.value === 'error')

    assert.match(renderedText(root), /项目暂时无法加载/)
    assert.doesNotMatch(renderedText(root), /正在同步项目权威状态/)
    const retry = findRenderedNode(
      root,
      target => target.type === 'button' && /重试/.test(renderedText(target)),
    )
    assert.ok(retry)
    await retry.props.onClick()
    await waitFor(() => shellReloads === 2 && state.value === 'archived')

    assert.deepEqual(forceValues, [true, true])
    assert.match(renderedText(root), /恢复项目/)
    assert.doesNotMatch(renderedText(root), /正在同步项目权威状态/)
  } finally {
    app.unmount()
    global.fetch = originalFetch
  }
})

test('a missing shell authority is never hidden by stale archived preparation', async () => {
  const originalFetch = global.fetch
  global.fetch = async url => {
    assert.match(String(url), /\/api\/projects\/project%20%2F%20%E4%B8%80\/preparation$/)
    return new Response(JSON.stringify(archivedPreparation()), {
      headers: { 'content-type': 'application/json' },
    })
  }
  const state = ref('active')
  const project = shallowRef({
    id: 'project / 一',
    title: '典镇山河',
    archivedAt: null,
  })
  let shellReloads = 0
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/projects/:projectId/overview',
        component: Overview,
      },
      {
        path: '/projects',
        component: { render: () => h('div', 'projects') },
      },
    ],
  })
  const root = node('root')
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(pinia)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.provide(ShellProjectContext, {
    state,
    project,
    error: shallowRef(null),
    reload: async options => {
      shellReloads += 1
      assert.equal(options?.force, true)
      state.value = 'missing'
      return null
    },
  })

  try {
    await router.push('/projects/project%20%2F%20%E4%B8%80/overview')
    await router.isReady()
    app.mount(root)
    await waitFor(() => shellReloads === 1 && state.value === 'missing')

    assert.match(renderedText(root), /项目不存在或已被删除/)
    assert.doesNotMatch(renderedText(root), /正在同步项目权威状态/)
  } finally {
    app.unmount()
    global.fetch = originalFetch
  }
})
