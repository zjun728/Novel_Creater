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
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import {
  computed,
  createSSRApp,
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

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
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

function authoritativePlanningContent(content = planningContent()) {
  return {
    schemaVersion: 'planning-v1',
    activeStoryBlockId: content.activeStoryBlockRef,
    volumes: structuredClone(content.volumes),
    plots: structuredClone(content.plots),
    storyBlocks: content.storyBlocks.map(sourceBlock => {
      const {
        volumeRef,
        plotRefs,
        ...block
      } = structuredClone(sourceBlock)
      return {
        ...block,
        volumeId: volumeRef,
        plotIds: plotRefs,
      }
    }),
    contentHash: '9'.repeat(64),
  }
}

function planningState(projectId = 'A') {
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
      content: authoritativePlanningContent(),
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

async function renderActualProgressPanel(vite) {
  const Panel = await vite.ssrLoadModule('/src/components/planning/ActualProgressPanel.vue')
  Panel.default.render = await clientRender('components/planning/ActualProgressPanel.vue')
}

test('mounted actual progress panel separates read-only Canon facts from future planning', async () => {
  const vite = await createPlanningVite()
  try {
    const Panel = await vite.ssrLoadModule('/src/components/planning/ActualProgressPanel.vue')
    Panel.default.render = await clientRender('components/planning/ActualProgressPanel.vue')
    const panelState = reactive({
      items: [],
      status: {
        canonRevision: 0,
        projectionRevision: 0,
        contentHash: 'a'.repeat(64),
        synchronized: true,
      },
    })
    const Harness = defineComponent({
      setup: () => () => h(Panel.default, panelState),
    })
    const root = node('root')
    const app = renderer.createApp(Harness)
    const warnings = []
    app.config.warnHandler = message => { warnings.push(String(message)) }
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(root)
    await flush()

    assert.match(text(root), /正文已发生/)
    assert.match(text(root), /尚无已定稿事实/)
    assert.doesNotMatch(text(root), /标记完成|同步记忆|手工进度/)

    panelState.status = {
      canonRevision: 4,
      projectionRevision: 3,
      contentHash: 'b'.repeat(64),
      synchronized: false,
    }
    await flush()
    assert.match(text(root), /正文事实正在重建，暂不展示实际进度/)

    panelState.status = {
      canonRevision: 4,
      projectionRevision: 4,
      contentHash: 'b'.repeat(64),
      synchronized: true,
    }
    panelState.items = [{
      revisionNumber: 4,
      subjectKey: '__global__',
      entityId: null,
      fieldPath: 'plot.gunpowder',
      value: { status: 'old', evidence: ['第一章', { chapter: 1 }] },
      contentHash: 'b'.repeat(64),
    }]
    await flush()
    assert.match(text(root), /Canon R4/)
    assert.match(text(root), /Projection R4/)
    assert.match(text(root), /plot\.gunpowder/)
    assert.match(text(root), /"status":"old"/)
    assert.match(text(root), /"chapter":1/)
    panelState.items = [{
      revisionNumber: 4,
      subjectKey: 'a:b',
      entityId: 'c',
      fieldPath: 'plot.gunpowder',
      value: { status: 'first' },
      contentHash: 'b'.repeat(64),
    }, {
      revisionNumber: 4,
      subjectKey: 'a',
      entityId: 'b:c',
      fieldPath: 'plot.gunpowder',
      value: { status: 'second' },
      contentHash: 'b'.repeat(64),
    }]
    await flush()
    panelState.items = [...panelState.items].reverse()
    await flush()
    assert.equal(warnings.some(message => /duplicate keys/i.test(message)), false)
    assert.match(text(root), /"status":"first"/)
    assert.match(text(root), /"status":"second"/)
    assert.equal(walk(root).some(item => (
      ['button', 'input', 'checkbox', 'textarea', 'select'].includes(item.type)
      || item.props.contenteditable != null
    )), false)
    const contents = await readFile(source('components/planning/ActualProgressPanel.vue'), 'utf8')
    assert.doesNotMatch(contents, /defineEmits|@(click|input|change|submit|drag)/)
    app.unmount()
  } finally {
    await vite.close()
  }
})

test('mounted PlanningWorkspace renders future planning and Canon facts in one tree', async () => {
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
    await renderActualProgressPanel(vite)
    Volume.default.render = await clientRender('components/planning/VolumeEditor.vue')
    Plot.default.render = await clientRender('components/planning/PlotEditor.vue')
    Drawer.default.render = await clientRender('components/planning/PlanningHistoryDrawer.vue')
    const store = workspaceStore()
    const controller = createPlanningWorkspaceController({ store, projectId: () => 'A' })
    const root = node('root')
    const app = renderer.createApp(Workspace.default, { store, controller, activeTab: 'volumes' })
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(root)
    await flush()

    assert.match(text(root), /未来规划/)
    assert.match(text(root), /正文已发生/)
    assert.match(text(root), /尚无已定稿事实/)
    assert.equal(walk(root).filter(item => item.props.class === 'actual-progress-panel').length, 1)
    app.unmount()
  } finally {
    global.document = originalDocument
    await vite.close()
  }
})

test('mounted PlanningWorkspace re-entry force-refreshes a same-project cached outline', async () => {
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
    await renderActualProgressPanel(vite)
    Volume.default.render = await clientRender('components/planning/VolumeEditor.vue')
    Plot.default.render = await clientRender('components/planning/PlotEditor.vue')
    Drawer.default.render = await clientRender('components/planning/PlanningHistoryDrawer.vue')

    const store = workspaceStore()
    store.projectId = 'A'
    store.outlineState = {
      projectId: 'A',
      activeSession: null,
      capabilities: { createDraft: false },
    }
    const outlineLoads = []
    store.ensureOutlineLoaded = async (projectId, options) => {
      outlineLoads.push({ projectId, options })
      return store.outlineState
    }
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => 'A',
    })

    for (let entry = 0; entry < 2; entry += 1) {
      const root = node('root')
      const app = renderer.createApp(Workspace.default, {
        store,
        controller,
        activeTab: 'volumes',
      })
      app.provide(ssrContextKey, { modules: new Set() })
      app.mount(root)
      await flush()
      app.unmount()
    }

    assert.deepEqual(outlineLoads, [
      { projectId: 'A', options: { force: true } },
      { projectId: 'A', options: { force: true } },
    ])
  } finally {
    global.document = originalDocument
    await vite.close()
  }
})

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
    await renderActualProgressPanel(vite)
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

test('mounted story-block workspace edits through one controller, supports physical undo, and becomes truly read-only', async () => {
  const vite = await createPlanningVite()
  const originalDocument = global.document
  try {
    const body = node('body')
    global.document = {
      activeElement: null,
      querySelector: selector => selector === 'body' ? body : null,
    }
    const [Workspace, StoryBlock, Volume, Plot, Drawer] = await Promise.all([
      vite.ssrLoadModule('/src/components/planning/PlanningWorkspace.vue'),
      vite.ssrLoadModule('/src/components/planning/StoryBlockEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/VolumeEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlotEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlanningHistoryDrawer.vue'),
    ])
    Workspace.default.render = await clientRender('components/planning/PlanningWorkspace.vue')
    await renderActualProgressPanel(vite)
    StoryBlock.default.render = await clientRender('components/planning/StoryBlockEditor.vue')
    Volume.default.render = await clientRender('components/planning/VolumeEditor.vue')
    Plot.default.render = await clientRender('components/planning/PlotEditor.vue')
    Drawer.default.render = await clientRender('components/planning/PlanningHistoryDrawer.vue')

    let key = 0
    const store = workspaceStore()
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => 'A',
      keyFactory: () => `new-${++key}`,
    })
    const root = node('root')
    const app = renderer.createApp(Workspace.default, {
      store,
      controller,
      activeTab: 'story-blocks',
    })
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(root)
    await flush()

    assert.match(text(root), /故事块编排/)
    assert.match(text(root), /当前活动故事块/)
    const title = () => walk(root).find(item => (
      item.type === 'input' && item.props.value === '夜入县衙'
    ))

    store.saving = true
    await flush()
    assert.equal(title().props.disabled, true)
    title().props.onInput?.({ target: { value: '不应写入' } })
    assert.equal(store.calls.length, 0)
    store.saving = false
    await flush()

    const preview = byButtonText(root, '预览并确认')
    preview.props.onClick()
    await flush()
    const confirm = walk(body).find(item => item.props['aria-label'] === '确认故事规划')
    assert.ok(confirm)
    assert.match(text(confirm), /分卷/)
    assert.match(text(confirm), /情节线/)
    assert.match(text(confirm), /故事块/)
    assert.match(text(confirm), /阶段/)
    assert.match(text(confirm), /场景任务/)
    assert.match(text(confirm), /活动故事块/)
    assert.match(text(confirm), /夜入县衙/)
    byButtonText(body, '返回核对').props.onClick()
    await flush()

    title().props.onInput({ target: { value: '雨夜入县衙' } })
    await flush()
    assert.equal(store.localContent.storyBlocks[0].title, '雨夜入县衙')
    assert.equal(store.calls.length, 1)

    byButtonText(root, '新增故事块').props.onClick()
    await flush()
    assert.equal(store.localContent.storyBlocks.length, 2)
    assert.equal(store.localContent.storyBlocks[1].clientNodeKey, 'new-1')

    byButtonText(root, '设为当前活动块').props.onClick()
    await flush()
    assert.equal(store.localContent.activeStoryBlockRef, 'new-1')

    const addStageButtons = walk(root).filter(item => (
      item.type === 'button' && text(item).trim() === '新增阶段'
    ))
    addStageButtons.at(-1).props.onClick()
    await flush()
    assert.equal(store.localContent.storyBlocks[1].stages.length, 1)

    const addTaskButtons = walk(root).filter(item => (
      item.type === 'button' && text(item).trim() === '新增场景任务'
    ))
    addTaskButtons.at(-1).props.onClick()
    await flush()
    assert.equal(store.localContent.storyBlocks[1].stages[0].sceneTasks.length, 1)

    const enabledBlockMoveUp = walk(root).find(item => (
      item.type === 'button'
      && text(item).trim() === '上移故事块'
      && item.props.disabled === false
    ))
    enabledBlockMoveUp.props.onClick()
    await flush()
    assert.equal(store.localContent.storyBlocks[0].clientNodeKey, 'new-1')

    byButtonText(root, '撤销新增故事块').props.onClick()
    await flush()
    assert.equal(store.localContent.storyBlocks.length, 1)
    assert.match(text(root), /已移除新增节点，可撤销一次/)
    byButtonText(root, '撤销上次物理删除').props.onClick()
    await flush()
    assert.equal(store.localContent.storyBlocks.length, 2)
    assert.equal(store.localContent.activeStoryBlockRef, 'new-1')

    store.state.capabilities.edit = false
    await flush()
    const readOnlyTitle = walk(root).find(item => (
      item.type === 'input' && item.props.value === '雨夜入县衙'
    ))
    assert.equal(readOnlyTitle.props.readonly, true)
    assert.equal(readOnlyTitle.props.disabled, false)
    for (const action of [
      '新增故事块',
      '新增阶段',
      '新增场景任务',
      '撤销新增故事块',
      '撤销上次物理删除',
      '上移故事块',
    ]) {
      assert.equal(byButtonText(root, action), undefined, action)
    }
    assert.match(text(root), /只读/)
    app.unmount()
  } finally {
    global.document = originalDocument
    await vite.close()
  }
})

test('real story-block SSR and mounted controls expose only referenced retired planning options', async () => {
  const vite = await createPlanningVite()
  const originalDocument = global.document
  try {
    const body = node('body')
    global.document = {
      activeElement: null,
      querySelector: selector => selector === 'body' ? body : null,
    }
    const [Workspace, StoryBlock, Volume, Plot, Drawer] = await Promise.all([
      vite.ssrLoadModule('/src/components/planning/PlanningWorkspace.vue'),
      vite.ssrLoadModule('/src/components/planning/StoryBlockEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/VolumeEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlotEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlanningHistoryDrawer.vue'),
    ])
    Workspace.default.render = await clientRender('components/planning/PlanningWorkspace.vue')
    await renderActualProgressPanel(vite)
    StoryBlock.default.render = await clientRender('components/planning/StoryBlockEditor.vue')
    Volume.default.render = await clientRender('components/planning/VolumeEditor.vue')
    Plot.default.render = await clientRender('components/planning/PlotEditor.vue')
    Drawer.default.render = await clientRender('components/planning/PlanningHistoryDrawer.vue')

    const content = planningContent()
    content.volumes.push({
      id: 'volume-retired',
      order: 2,
      title: '旧卷真名',
      lifecycle: 'retired',
    })
    content.plots.push({
      id: 'plot-retired',
      order: 2,
      title: '旧线真名',
      lifecycle: 'retired',
    }, {
      id: 'plot-retired-unreferenced',
      order: 3,
      title: '不可新选的旧线',
      lifecycle: 'retired',
    })
    content.storyBlocks[0].volumeRef = 'volume-retired'
    content.storyBlocks[0].plotRefs = ['plot-1', 'plot-retired']
    content.storyBlocks.push({
      id: 'block-retired',
      order: 2,
      title: '退役故事块',
      volumeRef: 'volume-retired',
      plotRefs: ['plot-retired'],
      lifecycle: 'retired',
      stages: [],
    })

    const store = workspaceStore()
    store.localContent = content
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => 'A',
    })
    const props = {
      store,
      controller,
      activeTab: 'story-blocks',
    }
    const html = await renderToString(createSSRApp(Workspace.default, props))
    assert.match(html, /旧卷真名/)
    assert.match(html, /旧线真名/)
    assert.match(html, /旧卷真名[\s\S]{0,80}已退役/)
    assert.match(html, /旧线真名[\s\S]{0,80}已退役/)
    assert.match(html, /<select value="volume-retired"/)
    assert.match(html, /value="plot-retired"[^>]*checked/)
    assert.doesNotMatch(html, /不可新选的旧线/)

    const root = node('root')
    const app = renderer.createApp(Workspace.default, props)
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(root)
    await flush()

    const selects = walk(root).filter(item => item.type === 'select')
    const activeVolume = selects.find(item => item.props.value === 'volume-retired')
    assert.ok(activeVolume)
    assert.equal(activeVolume.props.disabled, false)
    assert.match(text(activeVolume), /旧卷真名\s*·\s*已退役/)
    const retiredVolume = selects.find(item => (
      item !== activeVolume && item.props.value === 'volume-retired'
    ))
    assert.equal(retiredVolume.props.disabled, true)

    const retiredPlots = walk(root).filter(item => (
      item.type === 'input'
      && item.props.type === 'checkbox'
      && item.props.value === 'plot-retired'
    ))
    assert.equal(retiredPlots.length, 2)
    assert.equal(retiredPlots[0].props.checked, true)
    assert.equal(retiredPlots[0].props.disabled, false)
    assert.equal(retiredPlots[1].props.checked, true)
    assert.equal(retiredPlots[1].props.disabled, true)
    assert.doesNotMatch(text(root), /不可新选的旧线/)

    activeVolume.props.onChange({ target: { value: 'volume-1' } })
    retiredPlots[0].props.onChange({ target: { checked: false } })
    await flush()
    assert.equal(store.localContent.storyBlocks[0].volumeRef, 'volume-1')
    assert.deepEqual(store.localContent.storyBlocks[0].plotRefs, ['plot-1'])
    const activeCard = walk(root).find(item => (
      item.type === 'article'
      && String(item.props.class || '').includes('active')
    ))
    assert.doesNotMatch(text(activeCard), /旧卷真名|旧线真名/)
    app.unmount()
  } finally {
    global.document = originalDocument
    await vite.close()
  }
})

test('archived future plan uses one canonical DTO normalizer in real SSR and mounted workspace', async () => {
  const vite = await createPlanningVite()
  const originalDocument = global.document
  try {
    const body = node('body')
    global.document = {
      activeElement: null,
      querySelector: selector => selector === 'body' ? body : null,
    }
    const [Workspace, StoryBlock, Volume, Plot, Drawer] = await Promise.all([
      vite.ssrLoadModule('/src/components/planning/PlanningWorkspace.vue'),
      vite.ssrLoadModule('/src/components/planning/StoryBlockEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/VolumeEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlotEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlanningHistoryDrawer.vue'),
    ])
    Workspace.default.render = await clientRender('components/planning/PlanningWorkspace.vue')
    await renderActualProgressPanel(vite)
    StoryBlock.default.render = await clientRender('components/planning/StoryBlockEditor.vue')
    Volume.default.render = await clientRender('components/planning/VolumeEditor.vue')
    Plot.default.render = await clientRender('components/planning/PlotEditor.vue')
    Drawer.default.render = await clientRender('components/planning/PlanningHistoryDrawer.vue')

    const content = planningContent()
    content.volumes.push({
      id: 'volume-retired',
      order: 2,
      title: '权威旧卷',
      lifecycle: 'retired',
    })
    content.plots.push({
      id: 'plot-retired',
      order: 2,
      title: '权威旧线',
      lifecycle: 'retired',
    })
    content.storyBlocks[0].volumeRef = 'volume-retired'
    content.storyBlocks[0].plotRefs = ['plot-1', 'plot-retired']
    const futurePlan = authoritativePlanningContent(content)
    assert.equal('volumeRef' in futurePlan.storyBlocks[0], false)
    assert.equal('plotRefs' in futurePlan.storyBlocks[0], false)

    const store = workspaceStore()
    store.localContent = null
    store.state = {
      ...planningState(),
      basisStatus: 'archived',
      draft: null,
      futurePlan,
      capabilities: { view: true, edit: false, confirm: false, generate: false },
    }
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => 'A',
      isArchived: () => true,
    })
    const props = {
      store,
      controller,
      activeTab: 'story-blocks',
    }
    const html = await renderToString(createSSRApp(Workspace.default, props))
    assert.match(html, /当前活动故事块/)
    assert.match(html, /<select value="volume-retired"[^>]*disabled/)
    assert.match(html, /value="plot-retired"[^>]*checked[^>]*disabled/)
    assert.match(html, /权威旧卷[\s\S]{0,80}已退役/)
    assert.match(html, /权威旧线[\s\S]{0,80}已退役/)

    const root = node('root')
    const app = renderer.createApp(Workspace.default, props)
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(root)
    await flush()
    const selectedVolume = walk(root).find(item => (
      item.type === 'select' && item.props.value === 'volume-retired'
    ))
    const checkedPlots = walk(root).filter(item => (
      item.type === 'input'
      && item.props.type === 'checkbox'
      && item.props.checked === true
    ))
    assert.ok(selectedVolume)
    assert.equal(selectedVolume.props.disabled, true)
    assert.deepEqual(checkedPlots.map(item => item.props.value), ['plot-1', 'plot-retired'])
    assert.match(text(root), /当前活动故事块/)
    assert.match(text(root), /权威旧卷\s*·\s*已退役/)
    assert.match(text(root), /权威旧线\s*·\s*已退役/)
    app.unmount()
  } finally {
    global.document = originalDocument
    await vite.close()
  }
})

test('real story-block SSR exposes a labelled h3 h4 h5 hierarchy with live titles', async () => {
  const vite = await createPlanningVite()
  try {
    const StoryBlock = await vite.ssrLoadModule(
      '/src/components/planning/StoryBlockEditor.vue',
    )
    const content = planningContent()
    const html = await renderToString(createSSRApp(StoryBlock.default, {
      modelValue: content.storyBlocks,
      volumes: content.volumes,
      plots: content.plots,
      activeStoryBlockRef: content.activeStoryBlockRef,
      readOnly: true,
    }))

    assert.match(
      html,
      /<article[^>]*aria-labelledby="story-block-heading-0"[^>]*>[\s\S]*?<h3 id="story-block-heading-0"[^>]*>故事块 01 · 夜入县衙<\/h3>/u,
    )
    assert.match(
      html,
      /<section[^>]*aria-labelledby="story-stage-heading-0-0"[^>]*>[\s\S]*?<h4 id="story-stage-heading-0-0"[^>]*>阶段 01 · 潜入<\/h4>/u,
    )
    assert.match(
      html,
      /<article[^>]*aria-labelledby="story-task-heading-0-0-0"[^>]*>[\s\S]*?<h5 id="story-task-heading-0-0-0"[^>]*>场景任务 01 · 偷换腰牌<\/h5>/u,
    )
  } finally {
    await vite.close()
  }
})

test('pending recovery stays visible, keyboard-actionable and disabled only while checking', async () => {
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
    await renderActualProgressPanel(vite)
    Volume.default.render = await clientRender('components/planning/VolumeEditor.vue')
    Plot.default.render = await clientRender('components/planning/PlotEditor.vue')
    Drawer.default.render = await clientRender('components/planning/PlanningHistoryDrawer.vue')

    const pendingCheck = deferred()
    const store = workspaceStore()
    store.generationOutcomeUnknown = true
    store.generating = true
    store.generationOperation = {
      operationId: 'operation-1',
      status: 'pending',
    }
    let checks = 0
    store.reconcileGeneration = async () => {
      checks += 1
      store.reconciling = true
      try {
        if (checks === 1) return await pendingCheck.promise
        store.generationOperation = {
          operationId: 'operation-1',
          status: 'succeeded',
        }
        store.generationOutcomeUnknown = false
        store.generating = false
        return store.generationOperation
      } finally {
        store.reconciling = false
      }
    }
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

    const recoveryButton = () => byButtonText(root, '核对原操作')
    assert.match(text(root), /原操作仍在进行，稍后核对/)
    assert.equal(store.error, null)
    assert.equal(recoveryButton().props.type, 'button')
    assert.equal(recoveryButton().props.disabled, false)
    assert.equal(typeof recoveryButton().props.onClick, 'function')

    recoveryButton().props.onClick()
    await flush()
    assert.equal(checks, 1)
    assert.equal(recoveryButton().props.disabled, true)

    pendingCheck.resolve({
      operationId: 'operation-1',
      status: 'pending',
    })
    await flush()
    assert.equal(recoveryButton().props.disabled, false)
    assert.match(text(root), /原操作仍在进行，稍后核对/)

    recoveryButton().props.onClick()
    await flush()
    assert.equal(checks, 2)
    assert.equal(recoveryButton(), undefined)
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
    const [
      Page,
      Workspace,
      OutlineWorkspace,
      OutlineDrawer,
      Volume,
      Plot,
      StoryBlock,
      Drawer,
      Shell,
    ] = await Promise.all([
      vite.ssrLoadModule('/src/views/ProjectPlanningView.vue'),
      vite.ssrLoadModule('/src/components/planning/PlanningWorkspace.vue'),
      vite.ssrLoadModule('/src/components/planning/ChapterOutlineWorkspace.vue'),
      vite.ssrLoadModule('/src/components/planning/ChapterOutlineHistoryDrawer.vue'),
      vite.ssrLoadModule('/src/components/planning/VolumeEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlotEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/StoryBlockEditor.vue'),
      vite.ssrLoadModule('/src/components/planning/PlanningHistoryDrawer.vue'),
      vite.ssrLoadModule('/src/components/layout/productShell.js'),
    ])
    Page.default.render = await clientRender('views/ProjectPlanningView.vue')
    Workspace.default.render = await clientRender('components/planning/PlanningWorkspace.vue')
    await renderActualProgressPanel(vite)
    OutlineWorkspace.default.render = await clientRender(
      'components/planning/ChapterOutlineWorkspace.vue',
    )
    OutlineDrawer.default.render = await clientRender(
      'components/planning/ChapterOutlineHistoryDrawer.vue',
    )
    Volume.default.render = await clientRender('components/planning/VolumeEditor.vue')
    Plot.default.render = await clientRender('components/planning/PlotEditor.vue')
    StoryBlock.default.render = await clientRender('components/planning/StoryBlockEditor.vue')
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
        {
          path: '/projects/:projectId/planning/story-blocks',
          name: 'ProjectPlanningStoryBlocks',
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
    const volumeTitle = walk(root).find(item => (
      item.type === 'input' && item.props.value === '入世卷'
    ))
    volumeTitle.props.onInput({ target: { value: 'A 的未保存卷名' } })
    await flush()

    await router.push('/projects/A/planning/story-blocks')
    await flush()
    assert.equal(router.currentRoute.value.name, 'ProjectPlanningStoryBlocks')
    assert.equal(confirms, 0)
    assert.ok(walk(root).find(item => (
      item.type === 'input' && item.props.value === '夜入县衙'
    )))
    byButtonText(root, '新增故事块').props.onClick()
    await flush()
    byButtonText(root, '撤销新增故事块').props.onClick()
    await flush()
    assert.ok(byButtonText(root, '撤销上次物理删除'))

    await router.push('/projects/A/planning/plots')
    await flush()
    assert.equal(router.currentRoute.value.name, 'ProjectPlanningPlots')
    assert.equal(confirms, 0)

    await router.push('/projects/A/planning/volumes')
    await flush()
    assert.ok(walk(root).find(item => (
      item.type === 'input' && item.props.value === 'A 的未保存卷名'
    )))
    assert.equal(confirms, 0)

    await router.push('/projects/A/planning/story-blocks')
    await flush()
    assert.ok(byButtonText(root, '撤销上次物理删除'))
    byButtonText(root, '撤销上次物理删除').props.onClick()
    await flush()
    assert.ok(byButtonText(root, '撤销新增故事块'))
    byButtonText(root, '撤销新增故事块').props.onClick()
    await flush()
    assert.ok(byButtonText(root, '撤销上次物理删除'))

    await router.push('/projects/A/planning/volumes')
    await flush()
    await router.push('/projects/B/planning/volumes')
    assert.equal(router.currentRoute.value.params.projectId, 'A')
    assert.equal(confirms, 1)

    allowLeave = true
    await router.push('/projects/B/planning/volumes')
    await waitFor(() => router.currentRoute.value.params.projectId === 'B')
    assert.equal(confirms, 2)
    await router.push('/projects/B/planning/story-blocks')
    await flush()
    assert.equal(byButtonText(root, '撤销上次物理删除'), undefined)
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

test('planning workspace embeds outline authoring under story blocks with separate local locks', async () => {
  const contents = await readFile(
    source('components/planning/PlanningWorkspace.vue'),
    'utf8',
  )

  assert.match(contents, /ChapterOutlineWorkspace/)
  assert.match(contents, /createChapterOutlineController/)
  assert.match(contents, /activeTab === 'story-blocks'/)
  assert.match(contents, /chapter-outline-workspace/)
  assert.match(contents, /outlineController/)
  assert.match(contents, /hasCombinedLeaveRisk/)
  assert.doesNotMatch(
    contents,
    /controller\.localOverlay[\s\S]{0,120}chapter-outline-workspace/,
  )
})

test('mounted outline selectors are locked to the active story hierarchy and cascade invalid descendants', async () => {
  const vite = await createPlanningVite()
  const originalDocument = global.document
  try {
    const body = node('body')
    global.document = {
      activeElement: null,
      querySelector: selector => selector === 'body' ? body : null,
    }
    const [Workspace, Drawer] = await Promise.all([
      vite.ssrLoadModule('/src/components/planning/ChapterOutlineWorkspace.vue'),
      vite.ssrLoadModule('/src/components/planning/ChapterOutlineHistoryDrawer.vue'),
    ])
    Workspace.default.render = await clientRender(
      'components/planning/ChapterOutlineWorkspace.vue',
    )
    Drawer.default.render = await clientRender(
      'components/planning/ChapterOutlineHistoryDrawer.vue',
    )
    const hash = 'a'.repeat(64)
    const refOf = (id, revision) => ({ id, revision, contentHash: hash })
    const localContent = {
      schemaVersion: 'chapter-outline-draft-v1',
      volumeRef: refOf('volume-other', 2),
      storyBlockRef: refOf('block-other', 2),
      stageRefs: [refOf('stage-active', 3), refOf('stage-other', 6)],
      sceneTaskRefs: [refOf('task-active', 4), refOf('task-other', 7)],
      chapterGoal: '本章目标',
      expectedCharacters: [],
      continuation: [],
      plannedTasks: [],
      scenes: [],
      forbiddenEarlyEvents: [],
    }
    const store = reactive({
      outlineState: {
        projectId: 'project-1',
        lifecycle: 'active',
        authoritativeChapterNumber: 3,
        planningAuthority: {
          planningRevisionId: 'planning-1',
          revision: 1,
          contentHash: hash,
          content: {
            activeStoryBlockId: 'block-active',
            volumes: [
              {
                ...refOf('volume-active', 1),
                lifecycle: 'active',
                title: '活动分卷',
              },
              {
                ...refOf('volume-other', 2),
                lifecycle: 'active',
                title: '其他分卷',
              },
            ],
            storyBlocks: [
              {
                ...refOf('block-active', 2),
                lifecycle: 'active',
                title: '活动故事块',
                volumeId: 'volume-active',
                stages: [
                  {
                    ...refOf('stage-active', 3),
                    lifecycle: 'active',
                    title: '活动阶段',
                    sceneTasks: [{
                      ...refOf('task-active', 4),
                      lifecycle: 'active',
                      task: '活动任务',
                    }],
                  },
                ],
              },
              {
                ...refOf('block-other', 5),
                lifecycle: 'active',
                title: '其他故事块',
                volumeId: 'volume-other',
                stages: [{
                  ...refOf('stage-other', 6),
                  lifecycle: 'active',
                  title: '其他阶段',
                  sceneTasks: [{
                    ...refOf('task-other', 7),
                    lifecycle: 'active',
                    task: '其他任务',
                  }],
                }],
              },
            ],
          },
        },
        canonProjectionAuthority: {
          canonRevision: 1,
          projectionRevision: 1,
          contentHash: hash,
          synchronized: true,
        },
        draft: {
          draftId: 'draft-1',
          content: localContent,
          status: 'current',
        },
        confirmedOutline: null,
        capabilities: { editDraft: true, confirm: true },
        reasons: [],
      },
      outlineHistory: [],
      outlineLocalContent: localContent,
      outlineDirty: false,
      outlineLoading: false,
      outlineConfirming: false,
      outlineReconciling: false,
      outlineError: null,
    })
    const controller = {
      historyOpen: ref(false),
      authorInstructions: ref(''),
      notice: ref(''),
      editorLocked: ref(false),
      localOverlay: ref(false),
      hasCriticalRecovery: ref(false),
      readOnly: ref(false),
      editable: ref(true),
      canAdjustOutline: ref(false),
      canCreateDraft: ref(false),
      canSave: ref(true),
      canGenerate: ref(false),
      canConfirm: ref(true),
      generationDisabledReason: ref(''),
      recovery: ref(null),
      recoveryActions: ref([]),
      editLocal(next) {
        store.outlineLocalContent = structuredClone(next)
        store.outlineDirty = true
      },
      createManualDraft() {},
      save() {},
      generate() {},
      reconcile() {},
      confirm() {},
      openHistory() { this.historyOpen.value = true },
      closeHistory() { this.historyOpen.value = false },
    }
    const root = node('root')
    const app = renderer.createApp(Workspace.default, { store, controller })
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(root)
    await flush()

    let selects = walk(root).filter(item => item.type === 'select')
    assert.equal(selects.length, 2)
    assert.match(text(selects[0]), /活动分卷/)
    assert.doesNotMatch(text(selects[0]), /其他分卷/)
    assert.match(text(selects[1]), /活动故事块/)
    assert.doesNotMatch(text(selects[1]), /其他故事块/)
    assert.match(text(root), /活动阶段|活动任务/)
    assert.doesNotMatch(text(root), /其他阶段|其他任务/)
    assert.equal(
      byButtonText(root, '保存小纲工作稿').props.disabled,
      true,
    )
    assert.equal(
      byButtonText(root, '采用小纲').props.disabled,
      true,
    )

    selects[1].props.onChange({ target: { value: 'block-active' } })
    await flush()
    assert.equal(store.outlineLocalContent.storyBlockRef.id, 'block-active')
    assert.equal(store.outlineLocalContent.volumeRef.id, 'volume-active')
    assert.deepEqual(
      store.outlineLocalContent.stageRefs.map(item => item.id),
      ['stage-active'],
    )
    assert.deepEqual(
      store.outlineLocalContent.sceneTaskRefs.map(item => item.id),
      ['task-active'],
    )
    assert.equal(
      byButtonText(root, '保存小纲工作稿').props.disabled,
      false,
    )

    const stageCheckbox = walk(root).find(item => (
      item.type === 'input'
      && item.props.type === 'checkbox'
      && item.props.checked === true
    ))
    stageCheckbox.props.onChange({ target: { checked: false } })
    await flush()
    assert.deepEqual(store.outlineLocalContent.stageRefs, [])
    assert.deepEqual(store.outlineLocalContent.sceneTaskRefs, [])

    selects = walk(root).filter(item => item.type === 'select')
    selects[0].props.onChange({ target: { value: '' } })
    await flush()
    assert.equal(store.outlineLocalContent.volumeRef, null)
    assert.equal(store.outlineLocalContent.storyBlockRef, null)
    assert.deepEqual(store.outlineLocalContent.stageRefs, [])
    assert.deepEqual(store.outlineLocalContent.sceneTaskRefs, [])
    app.unmount()
  } finally {
    global.document = originalDocument
    await vite.close()
  }
})
