import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { computed, createSSRApp, h, ref, shallowRef } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from 'vue'
import { createFinalizationController } from '../../src/application/writer/finalizationController.js'


const source = path => readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')

const root = fileURLToPath(new URL('../..', import.meta.url))
const naiveStubId = '\0finalization-panel-naive-stub'
const naiveStub = {
  name: 'finalization-panel-naive-stub',
  enforce: 'pre',
  resolveId: id => id === 'naive-ui' ? naiveStubId : undefined,
  load: id => id === naiveStubId ? `
    import { defineComponent, h } from 'vue'
    const children = slots => Object.values(slots).flatMap(slot => slot?.() || [])
    const stub = name => defineComponent({ name, setup(_, { attrs, slots }) { return () => h('div', attrs, children(slots)) } })
    export const NAlert = stub('NAlert')
    export const NCard = stub('NCard')
    export const NInput = stub('NInput')
    export const NTag = stub('NTag')
    export const NModal = defineComponent({ name: 'NModal', props: ['show'], setup(props, { slots }) { return () => props.show ? h('div', children(slots)) : null } })
    export const NButton = defineComponent({ name: 'NButton', setup(_, { attrs, slots }) { return () => h('button', attrs, children(slots)) } })
  ` : undefined,
}

let vite
let FinalizationPanel
let InteractivePanel
test.before(async () => {
  vite = await createServer({
    configFile: false,
    root,
    appType: 'custom',
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false, ws: false },
    plugins: [vuePlugin(), naiveStub],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  FinalizationPanel = (await vite.ssrLoadModule(
    '/src/components/writer/FinalizationPanel.vue',
  )).default
  for (const name of ['FinalizationValueEditor', 'AddCanonFactEditor', 'ReviewResultsDialog']) {
    const component = (await vite.ssrLoadModule(`/src/components/writer/${name}.vue`)).default
    const { descriptor } = parse(await source(`components/writer/${name}.vue`))
    component.render = new Function('Vue', compile(descriptor.template.content, {
      mode: 'function', prefixIdentifiers: true,
      bindingMetadata: compileScript(descriptor, { id: name }).bindings,
    }).code)(VueRuntime)
  }
  const { descriptor } = parse(await source('components/writer/FinalizationPanel.vue'))
  InteractivePanel = { ...FinalizationPanel, render: new Function('Vue', compile(
    descriptor.template.content,
    {
      mode: 'function', prefixIdentifiers: true,
      bindingMetadata: compileScript(descriptor, { id: 'finalization-panel' }).bindings,
    },
  ).code)(VueRuntime) }
})
test.after(async () => { await vite?.close() })

const makeNode = type => ({
  type, text: '', props: {}, children: [], parent: null,
  listeners: {},
  addEventListener(event, handler) { this.listeners[event] = handler },
  removeEventListener(event) { delete this.listeners[event] },
  getRootNode() { return globalThis.document },
  get options() { return this.children.filter(child => child.type === 'option') },
  get value() { return this.props.value },
  set value(value) { this.props.value = value },
})
const detach = child => {
  if (child?.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
}
const renderer = VueRuntime.createRenderer({
  patchProp(node, key, _old, value) {
    if (value == null) delete node.props[key]
    else node.props[key] = value
  },
  insert(child, parent, anchor = null) {
    detach(child)
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(child)
    else parent.children.splice(index, 0, child)
  },
  remove: detach,
  createElement: makeNode,
  createText: value => ({ ...makeNode('#text'), text: String(value) }),
  createComment: () => makeNode('#comment'),
  setText: (node, value) => { node.text = String(value) },
  setElementText: (node, value) => { node.text = String(value); node.children = [] },
  parentNode: node => node?.parent || null,
  nextSibling: node => node?.parent?.children[node.parent.children.indexOf(node) + 1] || null,
  setScopeId: (node, id) => { node.props[id] = '' },
})
const nodeText = node => [node?.text, ...(node?.children || []).map(nodeText)].filter(Boolean).join(' ')
const walk = node => [node, ...(node.children || []).flatMap(walk)]
const buttons = (root, label) => walk(root).filter(node => node.type === 'button' && nodeText(node) === label)

async function mountReview({ correctFailure = false, includeFactChanges = false, factValue, disabled = false, draftStale = false, candidateContent = '' } = {}) {
  const hashA = 'a'.repeat(64)
  const hashB = 'b'.repeat(64)
  const payload = {
    schemaVersion: 'finalization-changeset-v1', title: '第一章', summary: '摘要',
    existingEntityIds: [], entities: [], aliases: [], canonEvents: [], storyProgressEvents: [],
    planningPatches: ['patch-1', 'patch-2'].map(id => ({
      id, targetType: 'stage', targetId: id, fieldPath: 'title', replacement: id,
      evidence: { startScalar: 0, endScalar: 2 },
    })),
    planningSuggestions: [{ id: 'suggestion-1', message: '调整后续节奏' }],
  }
  if (includeFactChanges) {
    payload.canonEvents = ['fact-1', 'fact-2'].map(id => ({
      id, entityId: 'entity-1', factKind: 'dynamic_event', fieldPath: 'status',
      value: factValue === undefined ? id : structuredClone(factValue), evidence: { startScalar: 0, endScalar: 2 },
    }))
    payload.storyProgressEvents = ['progress-1', 'progress-2'].map(id => ({
      id, targetType: 'scene_task', targetId: id, status: 'advanced',
      evidence: { startScalar: 0, endScalar: 2 },
    }))
  }
  if (factValue !== undefined) payload.aliases = [{ id: 'alias-1', entityId: 'entity-1', alias: '哥哥' }]
  let current = {
    status: 'awaiting_author', qualityReport: { status: 'completed', findings: [], deterministicBlocks: [] },
    changeSet: { revision: 1, contentHash: hashA, payload },
    confirmation: null,
    ...(candidateContent ? { candidateId: 'frozen', candidateHash: hashA } : {}),
  }
  const calls = []
  let pendingRead = null
  const controller = createFinalizationController({
    getReview: async () => {
      if (pendingRead) await pendingRead
      return structuredClone(current)
    },
    correct: async command => {
      calls.push(['correct', command])
      if (correctFailure) throw new Error('save failed')
      current = { ...current, changeSet: { revision: 2, contentHash: hashB, payload: command.changeSet } }
    },
    confirm: async command => {
      calls.push(['confirm', command])
      current = { ...current, confirmation: { revision: 2, contentHash: hashB } }
    },
  })
  await controller.load()
  const dirtyChanges = []
  const app = renderer.createApp(InteractivePanel, {
    controller, disabled, draftStale, chapterNumber: 3,
    candidates: candidateContent ? [{ id: 'frozen', contentHash: hashA, content: candidateContent }] : [],
    onDirtyChange: value => dirtyChanges.push(value),
  })
  app.provide(VueRuntime.ssrContextKey, {})
  app.component('router-link', { render: () => h('a') })
  const root = makeNode('root')
  app.mount(root)
  const pauseLoad = () => {
    let release
    pendingRead = new Promise(resolve => { release = resolve })
    const request = controller.load()
    return async () => { release(); await request }
  }
  return { app, root, controller, calls, payload, pauseLoad, dirtyChanges }
}

const valueEditor = root => walk(root).find(node => node.props['data-value-path'] === '事实内容')
test('review results open separately, group actual dimensions, and close without changing facts', async () => {
  const { app, root, controller, calls } = await mountReview({ candidateContent: '原文片段' })
  try {
    controller.review.value = { ...controller.review.value, qualityReport: { status: 'completed', deterministicBlocks: [], findings: [
      { id: 'f1', dimension: 'pacing', reason: '重复动作', suggestedAction: '合并动作', evidence: { startScalar: 0, endScalar: 2 } },
      { id: 'f2', dimension: 'dialogue_credibility', reason: '对白生硬', suggestedAction: '改成口语', evidence: { startScalar: 2, endScalar: 4 } },
    ] } }
    await VueRuntime.nextTick()
    assert.equal(walk(root).some(n => n.props.role === 'dialog'), false)
    buttons(root, '查看本章审查结果')[0].props.onClick()
    await VueRuntime.nextTick()
    const dialog = walk(root).find(n => n.props.role === 'dialog')
    assert.ok(dialog)
    assert.match(nodeText(dialog), /叙事节奏 · 1 项/)
    assert.match(nodeText(dialog), /对白可信度 · 1 项/)
    assert.match(nodeText(dialog), /原文：“原文”/)
    assert.equal(buttons(dialog, '忽略此建议').length, 0)
    buttons(dialog, '关闭')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.equal(walk(root).some(n => n.props.role === 'dialog'), false)
    assert.deepEqual(calls, [])
  } finally { app.unmount() }
})

test('stale review dialog keeps evidence readable and blocks editing actions', async () => {
  const { app, root, controller } = await mountReview({ candidateContent: '原文片段', draftStale: true })
  try {
    controller.review.value = { ...controller.review.value, qualityReport: { status: 'completed', deterministicBlocks: [], findings: [
      { id: 'f1', dimension: 'continuity', reason: '时间矛盾', suggestedAction: '核对时间', evidence: { startScalar: 0, endScalar: 2 } },
    ] } }
    await VueRuntime.nextTick()
    buttons(root, '查看本章审查结果')[0].props.onClick()
    await VueRuntime.nextTick()
    const dialog = walk(root).find(n => n.props.role === 'dialog')
    for (const label of ['定位原文并修改', '基于审稿意见调整', '核对定稿变更']) assert.equal(buttons(dialog, label)[0].props.disabled, true)
    assert.match(nodeText(dialog), /本次结果仅供回看/)
  } finally { app.unmount() }
})

test('only optional findings offer ignore and restore; required findings block confirmation', async () => {
  const { app, root, controller } = await mountReview({ candidateContent: '原文片段' })
  try {
    controller.review.value = { ...controller.review.value, findingDecisions: { revision: 0, ignoredFindingIds: [] }, qualityReport: { status: 'completed', findings: [
      { id: 'optional', severity: 'optional', dimension: 'pacing', reason: '措辞偏好', suggestedAction: '调整措辞', evidence: { startScalar: 0, endScalar: 2 } },
      { id: 'required', severity: 'required', dimension: 'continuity', reason: '事实冲突', suggestedAction: '核对事实', evidence: { startScalar: 0, endScalar: 2 } },
    ] } }
    const calls = []
    controller.setFindingIgnored = async (id, ignored) => {
      calls.push([id, ignored])
      controller.review.value = { ...controller.review.value, findingDecisions: { revision: 1, ignoredFindingIds: ignored ? [id] : [] } }
    }
    await VueRuntime.nextTick()
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, true)
    buttons(root, '查看本章审查结果')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.equal(buttons(root, '忽略此建议').length, 1)
    await buttons(root, '忽略此建议')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(calls, [['optional', true]])
    assert.equal(buttons(root, '恢复采用').length, 1)
    assert.match(nodeText(root), /已忽略 1 项/)
    assert.equal(buttons(root, '核对定稿变更')[0].props.disabled, true)
  } finally { app.unmount() }
})

const labelled = (root, label) => walk(root).find(node => node.props['aria-label'] === label)
async function inputValue(node, value) {
  if (node.props.onInput) node.props.onInput({ target: { value } })
  else node.props['onUpdate:modelValue'](value)
  await VueRuntime.nextTick()
}

test('fact value correction edits nested fields and removes aliases locally before the existing CAS save', async () => {
  const original = { injury: { condition: '耳鸣', severity: '轻度' }, paid: false }
  const { app, root, controller, calls, payload, dirtyChanges } = await mountReview({ includeFactChanges: true, factValue: original })
  try {
    const editor = valueEditor(root)
    labelled(editor, '事实内容.injury.severity：删除').props.onClick()
    await VueRuntime.nextTick()
    await inputValue(labelled(editor, '事实内容.injury.condition：文字'), '右耳持续耳鸣，听不清岸上喊声')
    await inputValue(labelled(editor, '事实内容：新字段名称'), 'result')
    buttons(editor, '添加字段').at(-1).props.onClick()
    await VueRuntime.nextTick()
    await inputValue(labelled(editor, '事实内容.result：文字'), '赵德顺归还铁牌，江越取回')
    buttons(root, '移除此别名')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(calls, [])
    assert.deepEqual(controller.review.value.changeSet.payload, payload)
    assert.equal(dirtyChanges.at(-1), true)
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, true)
    await buttons(root, '保存修正')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.equal(calls.length, 1)
    assert.equal(calls[0][1].expectedRevision, 1)
    assert.equal(calls[0][1].expectedRevisionHash, 'a'.repeat(64))
    const saved = calls[0][1].changeSet
    assert.deepEqual(saved.canonEvents[0], { ...payload.canonEvents[0], value: {
      injury: { condition: '右耳持续耳鸣，听不清岸上喊声' }, paid: false, result: '赵德顺归还铁牌，江越取回',
    } })
    assert.deepEqual(saved.canonEvents[1], payload.canonEvents[1])
    assert.deepEqual(saved.aliases, [])
    assert.equal(dirtyChanges.at(-1), false)
  } finally { app.unmount() }
})

test('array and scalar types retain valid JSON while incomplete numeric input blocks save and navigation loss', async () => {
  const { app, root, calls, dirtyChanges } = await mountReview({ includeFactChanges: true, factValue: { values: [null, true, 0] } })
  try {
    const editor = valueEditor(root)
    assert.equal(labelled(editor, '事实内容.values.2：数字').props.value, '0')
    labelled(editor, '事实内容.values.0：类型').props.onChange({ target: { value: 'string' } })
    await VueRuntime.nextTick()
    await inputValue(labelled(editor, '事实内容.values.0：文字'), '已支付')
    labelled(editor, '事实内容.values.1：是或否').props.onChange({ target: { value: 'false' } })
    await inputValue(labelled(editor, '事实内容.values.2：数字'), '-')
    assert.equal(dirtyChanges.at(-1), true)
    assert.equal(buttons(root, '保存修正')[0].props.disabled, true)
    await buttons(root, '保存修正')[0].props.onClick()
    assert.deepEqual(calls, [])
    await inputValue(labelled(editor, '事实内容.values.2：数字'), '-1.5')
    buttons(editor, '添加列表项')[0].props.onClick()
    await VueRuntime.nextTick()
    labelled(editor, '事实内容.values.3：类型').props.onChange({ target: { value: 'null' } })
    await VueRuntime.nextTick()
    labelled(editor, '事实内容.values.0：删除').props.onClick()
    await VueRuntime.nextTick()
    await buttons(root, '保存修正')[0].props.onClick()
    assert.deepEqual(calls[0][1].changeSet.canonEvents[0].value.values, [false, -1.5, null])
  } finally { app.unmount() }
})

test('a failed correction retains fact edits and no read-only review accepts editor events', async () => {
  const failed = await mountReview({ includeFactChanges: true, factValue: { condition: '原值' }, correctFailure: true })
  try {
    await inputValue(labelled(valueEditor(failed.root), '事实内容.condition：文字'), '修正值')
    await buttons(failed.root, '保存修正')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.equal(labelled(valueEditor(failed.root), '事实内容.condition：文字').props.value, '修正值')
    assert.equal(failed.dirtyChanges.at(-1), true)
  } finally { failed.app.unmount() }
  for (const state of ['confirmed', 'busy', 'finalized', 'archived']) {
    const mounted = await mountReview({ includeFactChanges: true, factValue: { condition: '原值' }, disabled: state === 'archived' })
    let release
    try {
      const editor = valueEditor(mounted.root)
      if (state === 'confirmed') mounted.controller.review.value = { ...mounted.controller.review.value, confirmation: { revision: 1, contentHash: 'a'.repeat(64) } }
      if (state === 'busy') release = mounted.pauseLoad()
      if (state === 'finalized') mounted.controller.result.value = { status: 'finalized' }
      await VueRuntime.nextTick()
      const field = labelled(editor, '事实内容.condition：文字')
      // Finalized controls are unmounted; captured handlers must still refuse changes.
      await inputValue(field, '不可接受')
      assert.deepEqual(mounted.controller.review.value.changeSet.payload, mounted.payload)
      assert.deepEqual(mounted.calls, [])
      assert.equal(mounted.dirtyChanges.at(-1), false)
    } finally { if (release) await release(); mounted.app.unmount() }
  }
})

test('author fact addition stays local, protects unfinished input, and uses the pinned candidate and route chapter', async () => {
  const documentBefore = globalThis.document
  const DocumentBefore = globalThis.Document
  const ShadowRootBefore = globalThis.ShadowRoot
  globalThis.Document = class Document {}
  globalThis.ShadowRoot = class ShadowRoot {}
  globalThis.document = { activeElement: null }
  const { app, root, controller, calls, dirtyChanges } = await mountReview({ candidateContent: '江越取回铁牌。' })
  try {
    const toggle = walk(root).find(node => node.type === 'details' && nodeText(node).includes('补录遗漏事实'))
    toggle.props.onToggle({ target: { open: true } })
    await VueRuntime.nextTick()
    const builder = labelled(root, '作者补录事实')
    await inputValue(labelled(builder, '补录事实内容'), '江越取回铁牌。')
    assert.equal(dirtyChanges.at(-1), true)
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, true)
    assert.deepEqual(controller.review.value.changeSet.payload.canonEvents, [])
    await buttons(builder, '添加事实')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(calls, [])
    assert.equal(buttons(root, '保存修正')[0].props.disabled, false)
    await buttons(root, '保存修正')[0].props.onClick()
    await VueRuntime.nextTick()
    const [fact] = calls[0][1].changeSet.canonEvents
    assert.equal(fact.value, '江越取回铁牌。')
    assert.equal(fact.effectiveStartChapter, 3)
    assert.equal(fact.evidence.startScalar, 0)
    assert.equal(fact.evidence.endScalar, 7)
    assert.match(fact.evidence.excerptHash, /^[a-f0-9]{64}$/u)
    assert.equal(dirtyChanges.at(-1), false)
  } finally {
    app.unmount()
    globalThis.document = documentBefore
    globalThis.Document = DocumentBefore
    globalThis.ShadowRoot = ShadowRootBefore
  }
})

test('excluding facts and progress stays local until the corrected revision is saved and confirmed', async () => {
  const { app, root, controller, calls, payload, dirtyChanges } = await mountReview({ includeFactChanges: true })
  try {
    assert.deepEqual(dirtyChanges, [false])
    assert.equal(buttons(root, '排除此项事实').length, 2)
    assert.equal(buttons(root, '排除此项进度').length, 2)
    await buttons(root, '排除此项事实')[0].props.onClick()
    await buttons(root, '排除此项进度')[1].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(calls, [])
    assert.deepEqual(controller.review.value.changeSet.payload, payload)
    assert.equal(dirtyChanges.at(-1), true)
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, true)
    await buttons(root, '保存修正')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(calls[0][1].changeSet.canonEvents.map(item => item.id), ['fact-2'])
    assert.deepEqual(calls[0][1].changeSet.storyProgressEvents.map(item => item.id), ['progress-1'])
    assert.deepEqual(calls[0][1].changeSet.planningPatches, payload.planningPatches)
    assert.deepEqual(calls[0][1].changeSet.entities, payload.entities)
    assert.equal(dirtyChanges.at(-1), false)
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, false)
    await buttons(root, '确认以上变更')[0].props.onClick()
    assert.deepEqual(calls[1], ['confirm', { expectedRevision: 2, expectedRevisionHash: 'b'.repeat(64) }])
  } finally { app.unmount() }
})

test('failed fact and progress correction preserves exclusions and reports dirty until unmount', async () => {
  const { app, root, controller, calls, dirtyChanges } = await mountReview({ includeFactChanges: true, correctFailure: true })
  try {
    await buttons(root, '排除此项事实')[0].props.onClick()
    await buttons(root, '排除此项进度')[0].props.onClick()
    await VueRuntime.nextTick()
    await buttons(root, '保存修正')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.equal(controller.review.value.changeSet.revision, 1)
    assert.equal(controller.review.value.changeSet.payload.canonEvents.length, 2)
    assert.equal(controller.review.value.changeSet.payload.storyProgressEvents.length, 2)
    assert.equal(buttons(root, '排除此项事实').length, 1)
    assert.equal(buttons(root, '排除此项进度').length, 1)
    assert.equal(dirtyChanges.at(-1), true)
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, true)
    await buttons(root, '确认以上变更')[0].props.onClick()
    assert.equal(calls.length, 1)
  } finally { app.unmount() }
  assert.equal(dirtyChanges.at(-1), false)
})

test('fact and progress exclusion cannot mutate confirmed, busy, finalized or blocked reviews', async () => {
  for (const state of ['confirmed', 'busy', 'finalized', 'failed', 'invalidated']) {
    const { app, root, controller, payload, calls, pauseLoad } = await mountReview({ includeFactChanges: true })
    let releaseLoad
    try {
      const excludeFact = buttons(root, '排除此项事实')[0]
      const excludeProgress = buttons(root, '排除此项进度')[0]
      assert.ok(excludeFact, state)
      assert.ok(excludeProgress, state)
      if (state === 'busy') releaseLoad = pauseLoad()
      else if (state === 'confirmed') controller.review.value = {
        ...controller.review.value, confirmation: { revision: 1, contentHash: 'a'.repeat(64) },
      }
      else controller.review.value = { ...controller.review.value, status: state === 'finalized' ? 'committed' : state }
      await VueRuntime.nextTick()
      if (state === 'confirmed' || state === 'busy') {
        assert.equal(buttons(root, '排除此项事实')[0].props.disabled, true, state)
        assert.equal(buttons(root, '排除此项进度')[0].props.disabled, true, state)
      } else {
        assert.equal(buttons(root, '排除此项事实').length, 0, state)
        assert.equal(buttons(root, '排除此项进度').length, 0, state)
      }
      await excludeFact.props.onClick()
      await excludeProgress.props.onClick()
      await VueRuntime.nextTick()
      assert.deepEqual(controller.review.value.changeSet.payload, payload, state)
      assert.deepEqual(calls, [], state)
      if (state === 'confirmed' || state === 'busy') {
        assert.equal(buttons(root, '排除此项事实').length, 2, state)
        assert.equal(buttons(root, '排除此项进度').length, 2, state)
      }
    } finally { await releaseLoad?.(); app.unmount() }
  }
})

test('removing one future planning patch stays local until a new revision is saved and confirmed', async () => {
  const { app, root, controller, calls, payload } = await mountReview()
  try {
    assert.equal(buttons(root, '移除此项调整').length, 2)
    await buttons(root, '移除此项调整')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(controller.review.value.changeSet.payload, payload)
    assert.equal(buttons(root, '移除此项调整').length, 1)
    assert.deepEqual(calls, [])
    const confirm = buttons(root, '确认以上变更')[0]
    assert.equal(confirm.props.disabled, true)
    await confirm.props.onClick()
    assert.deepEqual(calls, [])
    await buttons(root, '保存修正')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(calls[0][1].changeSet.planningPatches.map(item => item.id), ['patch-2'])
    assert.equal(controller.review.value.changeSet.revision, 2)
    assert.equal(buttons(root, '保存修正').length, 0)
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, false)
    await buttons(root, '确认以上变更')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(calls[1], ['confirm', { expectedRevision: 2, expectedRevisionHash: 'b'.repeat(64) }])
    assert.equal(buttons(root, '放弃审查并返回修改').length, 0)
    assert.equal(buttons(root, '移除此项调整')[0].props.disabled, true)
  } finally { app.unmount() }
})

test('failed correction preserves the patch deletion draft and keeps confirmation disabled', async () => {
  const { app, root, controller, calls } = await mountReview({ correctFailure: true })
  try {
    assert.equal(buttons(root, '移除此项调整').length, 2)
    await buttons(root, '移除此项调整')[0].props.onClick()
    await VueRuntime.nextTick()
    await buttons(root, '保存修正')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.equal(controller.review.value.changeSet.revision, 1)
    assert.equal(controller.review.value.changeSet.payload.planningPatches.length, 2)
    assert.equal(buttons(root, '移除此项调整').length, 1)
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, true)
    await buttons(root, '确认以上变更')[0].props.onClick()
    assert.equal(calls.length, 1)
  } finally { app.unmount() }
})

test('patch removal cannot change confirmed, busy or finalized review drafts', async () => {
  for (const state of ['confirmed', 'busy', 'finalized']) {
    const { app, root, controller, payload, calls, pauseLoad } = await mountReview()
    let releaseLoad
    try {
      const remove = buttons(root, '移除此项调整')[0]
      assert.ok(remove, state)
      if (state === 'busy') releaseLoad = pauseLoad()
      else if (state === 'confirmed') controller.review.value = {
        ...controller.review.value, confirmation: { revision: 1, contentHash: 'a'.repeat(64) },
      }
      else controller.review.value = { ...controller.review.value, status: 'committed' }
      await VueRuntime.nextTick()
      if (state !== 'finalized') assert.equal(buttons(root, '移除此项调整')[0].props.disabled, true, state)
      else assert.equal(buttons(root, '移除此项调整').length, 0)
      await remove.props.onClick()
      await VueRuntime.nextTick()
      assert.deepEqual(controller.review.value.changeSet.payload, payload, state)
      assert.deepEqual(calls, [], state)
      if (state !== 'finalized') assert.equal(buttons(root, '移除此项调整').length, 2, state)
    } finally { await releaseLoad?.(); app.unmount() }
  }
})

test('non-authoritative suggestions visibly explain that they do not update planning', async () => {
  const { app, root } = await mountReview()
  try {
    assert.match(nodeText(root), /非权威建议/)
    assert.match(nodeText(root), /不会写入规划/)
  } finally { app.unmount() }
})


test('Writer embeds one compact author-controlled finalization panel', async () => {
  const [view, panel] = await Promise.all([
    source('views/ChapterWriterView.vue'),
    source('components/writer/FinalizationPanel.vue'),
  ])

  assert.match(view, /components\/writer\/FinalizationPanel\.vue/)
  assert.match(view, /createFinalizationController/)
  assert.match(view, /<finalization-panel/)
  assert.match(view, /:planning-content="planningContent"/)
  assert.match(view, /finalization\.reset\(\)/)
  assert.match(view, /finalization\.load\(\)/)
  assert.match(view, /finalization\.dispose\(\)/)
  assert.match(view, /editorReadonly[\s\S]*finalization\.finalized\.value/)

  for (const label of [
    '审查并定稿', '确定性阻断', '质量建议', 'Canon 事实',
    '故事进度', '未来规划调整', '保存修正', '确认以上变更', '定稿本章',
    '放弃审查并返回修改',
  ]) assert.match(panel, new RegExp(label))
  assert.match(panel, /controller\.prepareCandidate/)
  assert.match(panel, /controller\.correctChangeSet/)
  assert.match(panel, /controller\.confirmChangeSet/)
  assert.match(panel, /controller\.commitChapter/)
  assert.match(panel, /controller\.cancelReview/)
  assert.match(panel, /planningContent/)
  assert.match(panel, /targetLabel\(item\)/)
  assert.doesNotMatch(panel, /item\.targetType\s*}}\s*·\s*{{\s*item\.targetId/)
  assert.match(panel, /previousCandidateIds/)
  assert.match(panel, /review\?\.status === 'failed'/)
  assert.match(panel, /审查未完成，正文和候选稿未受影响/)
  assert.equal(
    panel.match(/v-if="controller\.primaryAction\.value === 'confirm'"/g)?.length,
    2,
  )
  assert.doesNotMatch(
    panel,
    /v-else-if="controller\.primaryAction\.value === 'confirm'"/,
  )
  assert.doesNotMatch(panel, /通过分数|及格分|自动修复|自动定稿|partial approval/i)
  assert.doesNotMatch(panel, /<textarea[^>]*json|page\.request|page\.route|fetch\(|axios|page\.evaluate/i)
})


test('retrying a failed review shows progress without erasing the previous review', async () => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  const previous = { status: 'failed', qualityReport: { findings: [], deterministicBlocks: [] } }
  const controller = createFinalizationController({
    getReview: async () => previous,
    prepare: async () => pending,
  })
  await controller.load()
  const hash = 'a'.repeat(64)
  const app = renderer.createApp(InteractivePanel, { controller, candidates: [{
    id: 'candidate', basisStatus: 'current', contentHash: hash,
    canonRevision: 0, planningHash: hash, outlineHash: hash,
  }] })
  app.provide(VueRuntime.ssrContextKey, {})
  app.component('router-link', { render: () => h('a') })
  const root = makeNode('root')
  app.mount(root)
  let request
  try {
    assert.match(nodeText(root), /可稍后重新点击/)
    request = buttons(root, '审查并定稿')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.equal(controller.busy.value, true)
    assert.equal(controller.review.value.status, 'failed')
    assert.doesNotMatch(nodeText(root), /可稍后重新点击/)
    assert.equal(buttons(root, '正在审查…')[0].props.disabled, true)
    release()
    await request
    await VueRuntime.nextTick()
    assert.equal(controller.busy.value, false)
    assert.match(nodeText(root), /可稍后重新点击/)
    assert.equal(buttons(root, '审查并定稿')[0].props.disabled, false)
  } finally {
    release()
    await request
    app.unmount()
  }
})

test('the panel renders evidence without exposing full candidate prose', async () => {
  const panel = await source('components/writer/FinalizationPanel.vue')

  assert.match(panel, /startScalar/)
  assert.match(panel, /endScalar/)
  assert.doesNotMatch(panel, /candidate\.content|workingDraft\.content|rawProvider|prompt|apiKey|dsn/i)
})


test('review displays the exact escaped excerpt from the pinned candidate, not the working draft', async () => {
  const hash = 'a'.repeat(64)
  const controller = createFinalizationController({ getReview: async () => ({
    status: 'awaiting_author', candidateId: 'frozen', candidateHash: hash,
    qualityReport: { findings: [], deterministicBlocks: [] }, confirmation: null,
    changeSet: { revision: 1, contentHash: hash, payload: {
      title: '标题', summary: '摘要', entities: [], aliases: [], planningPatches: [], planningSuggestions: [], storyProgressEvents: [],
      canonEvents: [{ id: 'event', fieldPath: 'state', value: '耳鸣', evidence: { startScalar: 2, endScalar: 6 } }],
    } },
  }) })
  await controller.load()
  const app = createSSRApp(FinalizationPanel, { controller, candidates: [
    { id: 'other', contentHash: hash, content: '错误候选' },
    { id: 'frozen', contentHash: hash, content: '前😀<耳鸣>隐藏尾文' },
  ] })
  app.component('router-link', { render: () => h('a') })
  const html = await renderToString(app)
  assert.match(html, /&lt;耳鸣&gt;/)
  assert.doesNotMatch(html, /错误候选|隐藏尾文/)
})

test('finalized panel stays in place and offers only verified explicit navigation', async () => {
  const panel = await source('components/writer/FinalizationPanel.vue')

  assert.match(panel, /controller\.postFinalization\.value/)
  assert.match(panel, /postFinalization\.currentAction\.state === 'available'/)
  assert.match(panel, /:to="postFinalization\.currentAction\.targetPath"/)
  assert.match(panel, /\{\{ postFinalization\.currentAction\.label \}\}/)
  assert.match(panel, /postFinalization\?\.finalizedChapterReadable/)
  assert.match(panel, /:to="postFinalization\.finalizedChapterPath"/)
  assert.match(panel, /查看本章定稿/)
  assert.match(panel, /controller\.refreshPostFinalization/)
  assert.match(panel, /:disabled="controller\.postBusy\.value"/)
  assert.match(panel, /v-if="!postFinalization"[\s\S]*正在读取定稿后的创作状态/)
  assert.match(panel, /currentAction\.state === 'archived'[\s\S]*项目当前为只读状态/)
  assert.match(panel, /\.panel-intro[^}]*color:\s*#675d51/)
  assert.match(panel, /\.finalized-action--primary span[^}]*color:\s*#675d51/)
  assert.match(panel, /\.muted[^}]*color:\s*#6f6559/)
  assert.doesNotMatch(panel, /未实现内容|router\.push|router\.replace|window\.location/)
})


test('finalized panel renders a loading state while post-commit refresh is pending', async () => {
  const controller = {
    review: shallowRef({ status: 'committed' }),
    result: shallowRef({ chapterNumber: 4 }),
    postFinalization: shallowRef(null),
    postBusy: computed(() => false),
    busy: computed(() => true),
    error: ref(''),
    hardBlocks: computed(() => []),
    finalized: computed(() => true),
    primaryAction: computed(() => 'done'),
    refreshPostFinalization: async () => {},
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { render: () => h('div') } }],
  })
  await router.push('/')
  await router.isReady()
  const app = createSSRApp(FinalizationPanel, { controller })
  app.use(router)

  const html = await renderToString(app)

  assert.match(html, /本章已定稿/)
  assert.match(html, /正在读取定稿后的创作状态/)
  assert.doesNotMatch(html, /项目当前为只读状态|重新读取创作状态/)
})


test('initialized post-finalization refresh shows progress until retry is settled', async () => {
  const controller = {
    review: shallowRef({ status: 'committed' }),
    result: shallowRef({ chapterNumber: 4 }),
    postFinalization: shallowRef({
      currentAction: {
        state: 'unavailable',
        label: '重新读取创作状态',
      },
      finalizedChapterReadable: false,
    }),
    postBusy: computed(() => true),
    busy: computed(() => true),
    error: ref(''),
    hardBlocks: computed(() => []),
    finalized: computed(() => true),
    primaryAction: computed(() => 'done'),
    refreshPostFinalization: async () => {},
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { render: () => h('div') } }],
  })
  await router.push('/')
  await router.isReady()
  const app = createSSRApp(FinalizationPanel, { controller })
  app.use(router)

  const html = await renderToString(app)

  assert.match(html, /正在读取创作状态…/)
  assert.doesNotMatch(html, /重新读取创作状态|项目当前为只读状态/)

  const settledApp = createSSRApp(FinalizationPanel, {
    controller: {
      ...controller,
      postBusy: computed(() => false),
      busy: computed(() => false),
    },
  })
  settledApp.use(router)
  const settledHtml = await renderToString(settledApp)

  assert.match(settledHtml, /重新读取创作状态/)
  assert.doesNotMatch(settledHtml, /正在读取创作状态…/)
})


test('changed prose blocks author confirmation while leaving review cancellation available', async () => {
  const mounted = await mountReview({ draftStale: true })
  try {
    const confirm = buttons(mounted.root, '确认以上变更')[0]
    assert.ok(confirm.props.disabled)
    await confirm.props.onClick()
    assert.equal(mounted.calls.some(([action]) => action === 'confirm'), false)
    assert.match(nodeText(mounted.root), /旧审稿不能作为当前正文/)
    assert.equal(buttons(mounted.root, '放弃审查并返回修改')[0].props.disabled, false)
  } finally { mounted.app.unmount() }
})
