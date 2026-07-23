import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createPinia, setActivePinia } from 'pinia'
import { createSSRApp, ref, shallowRef } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
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
