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
          return () => h(tag, attrs, slots.default?.())
        },
      })
      export const NButton = stub('NButton', 'button')
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
  planningReady = true,
}) {
  return {
    lifecycle: 'active',
    activeSelection: selection,
    contract,
    bible,
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

let vite
let Overview
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

test('planning boundary is truthful and non-clickable while model loss keeps manual facts', async () => {
  const html = await renderOverview(preparation({
    nextAction: 'phase_boundary_planning',
    targetPath: null,
    planningReady: false,
  }))

  assert.equal((html.match(/class="overview-next-action"/g) || []).length, 0)
  assert.match(html, /创作准备已完成/)
  assert.match(html, /故事规划将在下一阶段接入/)
  assert.match(html, /规划模型不可用/)
  assert.match(html, /创作契约[\s\S]*已确认/)
  assert.match(html, /创作圣经[\s\S]*已确认/)
})

test('overview depends only on projectStore authority and has no browser joins', async () => {
  const source = await readFile(
    new URL('../../src/views/ProjectOverviewView.vue', import.meta.url),
    'utf8',
  )

  assert.match(source, /useProjectStore/)
  assert.match(source, /currentPreparation/)
  assert.doesNotMatch(
    source,
    /seedStore|creationContractStore|bibleStore|loadSelected|loadContract|loadBible/,
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
