import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from '@vue/runtime-core'
import {
  createRenderer,
  nextTick,
  ssrContextKey,
} from '@vue/runtime-core'
import { createPinia } from 'pinia'
import {
  computed,
  defineComponent,
  h,
  reactive,
  ref,
} from 'vue'
import {
  createMemoryHistory,
  createRouter,
  RouterView,
  useRoute,
} from 'vue-router'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

import { createPlanningWorkspaceController } from '../../src/application/planning/planningWorkspaceController.js'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const sourceRoot = fileURLToPath(new URL('../../src', import.meta.url))
const source = path => new URL(`../../src/${path}`, import.meta.url)
const messageStubId = '\0planning-app-message-stub'

const messageStubPlugin = {
  name: 'planning-app-message-stub',
  enforce: 'pre',
  resolveId(id) {
    if (id.endsWith('/composables/useAppMessage.js')) return messageStubId
    return undefined
  },
  load(id) {
    if (id !== messageStubId) return undefined
    return `
      export function useAppMessage() {
        return { success() {}, error() {}, warning() {}, info() {} }
      }
    `
  },
}

function node(type, value = '') {
  return {
    type,
    text: value,
    props: {},
    children: [],
    parent: null,
    isConnected: true,
    focused: false,
    inert: false,
    focus() {
      this.focused = true
      if (globalThis.document) globalThis.document.activeElement = this
    },
    hasAttribute(name) { return Object.hasOwn(this.props, name) },
    getAttribute(name) { return this.props[name] ?? null },
    setAttribute(name, next) { this.props[name] = next },
    removeAttribute(name) { delete this.props[name] },
    querySelectorAll() {
      return walk(this).filter(item => (
        ['button', 'input', 'textarea', 'select', 'a'].includes(item.type)
        && item.props.disabled !== true
        && item.props.tabindex !== '-1'
      ))
    },
  }
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
  createText: value => node('#text', String(value)),
  createComment: value => node('#comment', String(value || '')),
  setText(target, value) { target.text = String(value) },
  setElementText(target, value) {
    target.text = String(value)
    target.children = []
  },
  parentNode: target => target?.parent || null,
  nextSibling: target => (
    target?.parent?.children[target.parent.children.indexOf(target) + 1] || null
  ),
  querySelector: selector => globalThis.document?.querySelector?.(selector) ?? null,
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

function walk(root, result = []) {
  if (!root) return result
  result.push(root)
  for (const child of root.children || []) walk(child, result)
  return result
}

function text(root) {
  return [root?.text || '', ...(root?.children || []).map(text)].join('')
}

function byButtonText(root, label) {
  return walk(root).find(item => (
    item.type === 'button' && text(item).trim() === label
  ))
}

async function flush() {
  for (let index = 0; index < 4; index += 1) await Promise.resolve()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

async function waitFor(predicate, message = 'condition did not become true') {
  for (let index = 0; index < 30; index += 1) {
    const result = predicate()
    if (result) return result
    await flush()
  }
  assert.fail(message)
}

async function clientRender(path) {
  const contents = await readFile(source(path), 'utf8')
  const filename = path.split('/').at(-1)
  const { descriptor } = parse(contents, { filename })
  const script = compileScript(descriptor, { id: `planning-${filename}` })
  const result = compile(descriptor.template.content, {
    mode: 'function',
    prefixIdentifiers: true,
    bindingMetadata: script.bindings,
  })
  return new Function('Vue', result.code)({
    ...VueRuntime,
    withModifiers: handler => handler,
    withKeys: handler => handler,
  })
}

function planningContent() {
  return {
    activeStoryBlockRef: 'block-1',
    volumes: [{
      id: 'volume-1',
      order: 1,
      title: '入世卷',
      coreChange: '从逃亡到入局',
      mainPressure: '两方追索',
      ensembleFocus: ['沈砚'],
      forbiddenEvents: ['不提前揭密'],
      revision: 1,
      contentHash: 'a'.repeat(64),
      lifecycle: 'active',
    }],
    plots: [{
      id: 'plot-1',
      order: 1,
      title: '残卷主线',
      plotType: 'main',
      storyQuestion: '残卷从何而来',
      futureDirection: '追到京师',
      expectedPayoff: '揭开首层目录',
      relatedCharacters: ['沈砚'],
      revision: 1,
      contentHash: 'b'.repeat(64),
      lifecycle: 'active',
    }],
    storyBlocks: [{
      id: 'block-1',
      order: 1,
      title: '夜入县衙',
      entrySituation: '追兵封城',
      blockGoal: '取得残卷',
      mainPressure: '守卫换班',
      expectedChange: '拿到线索',
      openQuestions: ['谁在接应'],
      involvedCharacters: ['沈砚'],
      volumeRef: 'volume-1',
      plotRefs: ['plot-1'],
      revision: 1,
      contentHash: 'c'.repeat(64),
      lifecycle: 'active',
      stages: [{
        id: 'stage-1',
        order: 1,
        title: '潜入',
        purpose: '进入库房',
        dramaticQuestion: '能否避开巡夜',
        revision: 1,
        contentHash: 'd'.repeat(64),
        lifecycle: 'active',
        sceneTasks: [{
          id: 'task-1',
          order: 1,
          task: '偷换腰牌',
          completionEvidence: '成功进入内院',
          revision: 1,
          contentHash: 'e'.repeat(64),
          lifecycle: 'active',
        }],
      }],
    }],
  }
}

function planningState(projectId = 'A') {
  const content = planningContent()
  return {
    projectId,
    basisStatus: 'current',
    head: { revision: 1, planningRevisionId: 'revision-1', contentHash: 'f'.repeat(64) },
    draft: {
      projectId,
      draftId: `draft-${projectId}`,
      baseHeadRevision: 1,
      draftRevision: 1,
      contentHash: '9'.repeat(64),
      content: {
        schemaVersion: 'planning-v1',
        activeStoryBlockId: 'block-1',
        volumes: content.volumes,
        plots: content.plots,
        storyBlocks: content.storyBlocks.map(block => ({
          ...block,
          volumeId: block.volumeRef,
          plotIds: block.plotRefs,
          stages: block.stages,
        })),
        contentHash: '9'.repeat(64),
      },
      status: 'active',
      capacityPolicy: { targetMin: 3000, targetMax: 5000, softCeiling: 5000 },
    },
    futurePlan: null,
    actualProgress: [],
    canonProjectionStatus: {
      canonRevision: 0,
      projectionRevision: 0,
      contentHash: '8'.repeat(64),
      synchronized: true,
    },
    capacityPolicy: { targetMin: 3000, targetMax: 5000, softCeiling: 5000 },
    capabilities: { view: true, edit: true, confirm: true, generate: true },
  }
}

function historyAggregate() {
  return {
    schemaVersion: 'planning-v1',
    activeStoryBlockId: 'block-1',
    contentHash: '7'.repeat(64),
    volumes: [{
      id: 'volume-1',
      order: 1,
      title: '入世卷',
      coreChange: '从逃亡到入局',
      mainPressure: '两方追索',
      ensembleFocus: ['沈砚'],
      forbiddenEvents: ['不提前揭密'],
      revision: 1,
      contentHash: 'a'.repeat(64),
      lifecycle: 'active',
    }, {
      id: 'volume-retired',
      order: 2,
      title: '旧卷',
      coreChange: '旧变化完整保留',
      mainPressure: '旧压力完整保留',
      ensembleFocus: ['旧人物'],
      forbiddenEvents: ['旧禁区'],
      revision: 2,
      contentHash: '1'.repeat(64),
      lifecycle: 'retired',
    }],
    plots: [{
      id: 'plot-1',
      order: 1,
      title: '残卷主线',
      plotType: 'main',
      storyQuestion: '残卷从何而来',
      futureDirection: '追到京师',
      expectedPayoff: '揭开首层目录',
      relatedCharacters: ['沈砚'],
      revision: 1,
      contentHash: 'b'.repeat(64),
      lifecycle: 'active',
    }, {
      id: 'plot-retired',
      order: 2,
      title: '旧情节线',
      plotType: 'other',
      storyQuestion: '旧问题完整保留',
      futureDirection: '旧走向完整保留',
      expectedPayoff: '旧回报完整保留',
      relatedCharacters: ['旧人物'],
      revision: 2,
      contentHash: '2'.repeat(64),
      lifecycle: 'retired',
    }],
    storyBlocks: [{
      id: 'block-1',
      order: 1,
      title: '夜入县衙',
      entrySituation: '追兵封城',
      blockGoal: '取得残卷',
      mainPressure: '守卫换班',
      expectedChange: '拿到线索',
      openQuestions: ['谁在接应'],
      involvedCharacters: ['沈砚'],
      volumeId: 'volume-1',
      plotIds: ['plot-1', 'plot-missing'],
      revision: 1,
      contentHash: 'c'.repeat(64),
      lifecycle: 'active',
      stages: [{
        id: 'stage-1',
        storyBlockId: 'block-1',
        order: 1,
        title: '潜入',
        purpose: '进入库房',
        dramaticQuestion: '能否避开巡夜',
        revision: 1,
        contentHash: 'd'.repeat(64),
        lifecycle: 'active',
        sceneTasks: [{
          id: 'task-1',
          stageId: 'stage-1',
          order: 1,
          task: '偷换腰牌',
          completionEvidence: '成功进入内院',
          revision: 1,
          contentHash: 'e'.repeat(64),
          lifecycle: 'active',
        }, {
          id: 'task-retired',
          stageId: 'stage-1',
          order: 2,
          task: '旧场景任务',
          completionEvidence: '旧证据完整保留',
          revision: 2,
          contentHash: '3'.repeat(64),
          lifecycle: 'retired',
        }],
      }, {
        id: 'stage-retired',
        storyBlockId: 'block-1',
        order: 2,
        title: '旧阶段',
        purpose: '旧阶段目的完整保留',
        dramaticQuestion: '旧戏剧问题完整保留',
        revision: 2,
        contentHash: '4'.repeat(64),
        lifecycle: 'retired',
        sceneTasks: [],
      }],
    }, {
      id: 'block-retired',
      order: 2,
      title: '旧故事块',
      entrySituation: '旧情境完整保留',
      blockGoal: '旧目标完整保留',
      mainPressure: '旧压力完整保留',
      expectedChange: '旧变化完整保留',
      openQuestions: ['旧开放问题'],
      involvedCharacters: ['旧人物'],
      volumeId: 'volume-retired',
      plotIds: ['plot-retired'],
      revision: 2,
      contentHash: '5'.repeat(64),
      lifecycle: 'retired',
      stages: [],
    }],
  }
}

function workspaceStore() {
  const calls = []
  return reactive({
    calls,
    state: planningState(),
    history: [],
    localContent: planningContent(),
    dirty: false,
    error: null,
    loading: false,
    saving: false,
    confirming: false,
    generating: false,
    reconciling: false,
    generationOutcomeUnknown: false,
    awaitingAuthoritativeReload: false,
    editLocal(value) {
      calls.push(JSON.parse(JSON.stringify(value)))
      this.localContent = value
      this.dirty = true
    },
  })
}

async function createPlanningVite() {
  return createServer({
    configFile: false,
    root: frontendRoot,
    resolve: { alias: { '@': sourceRoot } },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [messageStubPlugin, vuePlugin()],
    optimizeDeps: { noDiscovery: true },
  })
}

test('mounted workspace locks editor mutations for every busy or recovery state and restores them', async () => {
  const vite = await createPlanningVite()
  const originalDocument = global.document
  try {
    const body = node('body')
    global.document = {
      activeElement: null,
      querySelector: selector => selector === 'body' ? body : null,
    }
    const [Workspace, Volume, Plot, Drawer] = await Promise.all([
      vite.ssrLoadModule('/src/components/planning/PlanningWorkspace.vue'),
      vite.ssrLoadModule('/src/components/planning/VolumeEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlotEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlanningHistoryDrawer.vue'),
    ])
    Workspace.default.render = await clientRender('components/planning/PlanningWorkspace.vue')
    Volume.default.render = await clientRender('components/planning/VolumeEditor.vue')
    Plot.default.render = await clientRender('components/planning/PlotEditor.vue')
    Drawer.default.render = await clientRender('components/planning/PlanningHistoryDrawer.vue')

    const store = workspaceStore()
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => 'A',
    })
    const root = node('root')
    const app = renderer.createApp(Workspace.default, {
      store,
      controller,
      activeTab: 'volumes',
    })
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(root)
    await flush()

    const volumeTitle = () => walk(root).find(item => (
      item.type === 'input' && item.props.value === '入世卷'
    ))
    for (const flag of [
      'saving',
      'loading',
      'confirming',
      'generating',
      'reconciling',
      'awaitingAuthoritativeReload',
      'generationOutcomeUnknown',
    ]) {
      store[flag] = true
      await flush()
      assert.equal(volumeTitle().props.disabled, true, flag)
      volumeTitle().props.onInput?.({ target: { value: `blocked-${flag}` } })
      assert.equal(store.calls.length, 0, flag)
      assert.equal(store.localContent.volumes[0].title, '入世卷', flag)
      store[flag] = false
      await flush()
      assert.equal(volumeTitle().props.disabled, false, `${flag} recovered`)
    }

    volumeTitle().props.onInput({ target: { value: '可继续编辑' } })
    await flush()
    assert.equal(store.calls.length, 1)
    assert.equal(store.localContent.volumes[0].title, '可继续编辑')
    app.unmount()
  } finally {
    global.document = originalDocument
    await vite.close()
  }
})

test('mounted route preserves instructions across tabs, cancels project leave, then clears A state on B', async () => {
  const vite = await createPlanningVite()
  const originalFetch = global.fetch
  const originalWindow = global.window
  const originalDocument = global.document
  let allowLeave = false
  let confirms = 0
  try {
    const body = node('body')
    global.document = {
      activeElement: null,
      querySelector: selector => selector === 'body' ? body : null,
    }
    const [Page, Workspace, Volume, Plot, Drawer, Shell] = await Promise.all([
      vite.ssrLoadModule('/src/views/ProjectPlanningView.vue'),
      vite.ssrLoadModule('/src/components/planning/PlanningWorkspace.vue'),
      vite.ssrLoadModule('/src/components/planning/VolumeEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlotEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlanningHistoryDrawer.vue'),
      vite.ssrLoadModule('/src/components/layout/productShell.js'),
    ])
    Page.default.render = await clientRender('views/ProjectPlanningView.vue')
    Workspace.default.render = await clientRender('components/planning/PlanningWorkspace.vue')
    Volume.default.render = await clientRender('components/planning/VolumeEditor.vue')
    Plot.default.render = await clientRender('components/planning/PlotEditor.vue')
    Drawer.default.render = await clientRender('components/planning/PlanningHistoryDrawer.vue')

    global.window = {
      confirm() {
        confirms += 1
        return allowLeave
      },
      addEventListener() {},
      removeEventListener() {},
    }
    global.fetch = async url => {
      const path = new URL(String(url)).pathname
      const projectId = decodeURIComponent(path.match(/\/projects\/([^/]+)/u)?.[1] || 'A')
      if (path.endsWith('/planning/history')) {
        return new Response(JSON.stringify({ items: [] }), {
          headers: { 'content-type': 'application/json' },
        })
      }
      if (path.endsWith('/planning')) {
        return new Response(JSON.stringify(planningState(projectId)), {
          headers: { 'content-type': 'application/json' },
        })
      }
      throw new Error(`unexpected request ${path}`)
    }

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        {
          path: '/projects/:projectId/planning/volumes',
          name: 'ProjectPlanningVolumes',
          component: Page.default,
        },
        {
          path: '/projects/:projectId/planning/plots',
          name: 'ProjectPlanningPlots',
          component: Page.default,
        },
        { path: '/outside', name: 'Outside', component: { render: () => h('p', 'outside') } },
      ],
    })
    const ShellProvider = defineComponent({
      setup() {
        const route = useRoute()
        return {
          state: ref('active'),
          project: computed(() => ({
            id: String(route.params.projectId || ''),
            title: String(route.params.projectId || ''),
            archivedAt: null,
          })),
        }
      },
      render: () => h(RouterView),
    })
    await router.push('/projects/A/planning/volumes')
    await router.isReady()
    const app = renderer.createApp(ShellProvider)
    app.use(createPinia())
    app.use(router)
    const provider = {
      state: ref('active'),
      project: computed(() => ({
        id: String(router.currentRoute.value.params.projectId || ''),
        title: String(router.currentRoute.value.params.projectId || ''),
        archivedAt: null,
      })),
      error: ref(null),
      reload: async () => null,
    }
    app.provide(Shell.SHELL_PROJECT_CONTEXT, provider)
    app.provide(ssrContextKey, { modules: new Set() })
    const root = node('root')
    app.mount(root)

    const instructions = await waitFor(() => walk(root).find(item => (
      item.type === 'textarea'
      && item.props.id === 'planning-author-instructions'
      && item.props.disabled === false
    )))
    instructions.props['onUpdate:modelValue']('只属于 A 的要求')
    await flush()

    await router.push('/projects/A/planning/plots')
    await flush()
    assert.equal(router.currentRoute.value.name, 'ProjectPlanningPlots')
    assert.equal(confirms, 0)

    await router.push('/projects/B/planning/volumes')
    assert.equal(router.currentRoute.value.params.projectId, 'A')
    assert.equal(confirms, 1)

    allowLeave = true
    await router.push('/projects/B/planning/volumes')
    await waitFor(() => router.currentRoute.value.params.projectId === 'B')
    assert.equal(confirms, 2)
    await router.push('/outside')
    assert.equal(router.currentRoute.value.name, 'Outside')
    assert.equal(confirms, 2)
    app.unmount()
  } finally {
    global.fetch = originalFetch
    global.window = originalWindow
    global.document = originalDocument
    await vite.close()
  }
})

test('mounted history drawer renders the immutable hierarchy and owns modal keyboard cleanup', async () => {
  const vite = await createPlanningVite()
  const originalDocument = global.document
  try {
    const Drawer = await vite.ssrLoadModule(
      '/src/components/planning/PlanningHistoryDrawer.vue',
    )
    Drawer.default.render = await clientRender(
      'components/planning/PlanningHistoryDrawer.vue',
    )
    const body = node('body')
    const appRoot = node('div')
    appRoot.props.id = 'app'
    const trigger = node('button')
    const documentRef = {
      activeElement: trigger,
      querySelector(selector) {
        if (selector === '#app') return appRoot
        if (selector === 'body') return body
        return null
      },
    }
    global.document = documentRef
    const opened = ref(true)
    const malformedAggregate = historyAggregate()
    malformedAggregate.volumes[0].lifecycle = 'unexpected'
    const history = [
      {
        planningRevisionId: 'revision-7',
        revision: 7,
        createdAt: '2026-07-25',
        displayStatus: 'current',
        displayReason: 'currentPlanningHead',
        content: historyAggregate(),
      },
      {
        planningRevisionId: 'revision-6',
        revision: 6,
        createdAt: '2026-07-24',
        displayStatus: 'superseded',
        displayReason: 'newerPlanningOrBasis',
        content: historyAggregate(),
      },
      {
        planningRevisionId: 'revision-5',
        revision: 5,
        createdAt: '2026-07-23',
        displayStatus: 'archived',
        displayReason: 'projectArchived',
        content: historyAggregate(),
      },
      {
        planningRevisionId: 'revision-4',
        revision: 4,
        createdAt: '2026-07-22',
        displayStatus: 'unexpected',
        displayReason: 'unexpected',
        content: malformedAggregate,
      },
    ]
    const Harness = defineComponent({
      setup() {
        return () => h(Drawer.default, {
          open: opened.value,
          history,
          onClose: () => { opened.value = false },
        })
      },
    })
    const app = renderer.createApp(Harness)
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(appRoot)
    await flush()

    const dialog = walk(body).find(item => item.props.role === 'dialog')
    assert.ok(dialog)
    assert.equal(dialog.props['aria-modal'], 'true')
    assert.match(text(dialog), /入世卷/)
    assert.match(text(dialog), /从逃亡到入局/)
    assert.match(text(dialog), /残卷主线/)
    assert.match(text(dialog), /残卷从何而来/)
    assert.match(text(dialog), /夜入县衙/)
    assert.match(text(dialog), /当前活动故事块/)
    assert.match(text(dialog), /当前版本/)
    assert.match(text(dialog), /当前规划主版本/)
    assert.match(text(dialog), /已被后续规划取代/)
    assert.match(text(dialog), /已有更新规划或创作依据/)
    assert.match(text(dialog), /项目已归档/)
    assert.match(text(dialog), /状态不可用/)
    assert.match(text(dialog), /原因不可用/)
    assert.deepEqual(
      walk(dialog)
        .filter(item => item.props.class === 'revision-state')
        .map(item => text(item).replace(/\s+/gu, '')),
      [
        '当前版本当前规划主版本',
        '已被后续规划取代已有更新规划或创作依据',
        '项目已归档项目已归档',
        '状态不可用原因不可用',
      ],
    )
    assert.match(text(dialog), /分卷 · 已退役/)
    assert.match(text(dialog), /情节线 · 已退役/)
    assert.match(text(dialog), /故事块 · 已退役/)
    assert.match(text(dialog), /阶段 · 已退役/)
    assert.match(text(dialog), /场景任务 · 已退役/)
    assert.match(text(dialog), /分卷 · 生命周期不可用/)
    assert.match(text(dialog), /旧变化完整保留/)
    assert.match(text(dialog), /旧问题完整保留/)
    assert.match(text(dialog), /旧情境完整保留/)
    assert.match(text(dialog), /旧阶段目的完整保留/)
    assert.match(text(dialog), /旧证据完整保留/)
    assert.match(text(dialog), /所属分卷：入世卷（volume-1）/)
    assert.match(text(dialog), /关联情节线：残卷主线（plot-1）、未找到情节线（plot-missing）/)
    assert.match(text(dialog), /进入库房/)
    assert.match(text(dialog), /偷换腰牌/)
    assert.match(text(dialog), /成功进入内院/)
    assert.doesNotMatch(text(dialog), /克隆|编辑|保存/)
    assert.equal(appRoot.inert, true)
    assert.equal(appRoot.props['aria-hidden'], 'true')

    const close = byButtonText(body, '关闭')
    assert.equal(documentRef.activeElement?.type, 'button')
    assert.equal(text(documentRef.activeElement).trim(), '关闭')
    assert.equal(documentRef.activeElement?.focused, true)
    let prevented = 0
    dialog.props.onKeydown({
      key: 'Tab',
      shiftKey: false,
      preventDefault() { prevented += 1 },
    })
    assert.equal(prevented, 1)
    dialog.props.onKeydown({
      key: 'Escape',
      preventDefault() { prevented += 1 },
    })
    await flush()
    assert.equal(opened.value, false)
    assert.equal(appRoot.inert, false)
    assert.equal(appRoot.hasAttribute('aria-hidden'), false)
    assert.equal(documentRef.activeElement, trigger)

    opened.value = true
    await flush()
    assert.equal(appRoot.inert, true)
    app.unmount()
    assert.equal(appRoot.inert, false)
    assert.equal(appRoot.hasAttribute('aria-hidden'), false)
  } finally {
    global.document = originalDocument
    await vite.close()
  }
})
