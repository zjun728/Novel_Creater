import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createPinia, setActivePinia } from 'pinia'
import * as VueRuntime from '@vue/runtime-core'
import {
  createRenderer, defineComponent, h, nextTick, ssrContextKey,
} from '@vue/runtime-core'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

import { api } from '../../src/api/db/client.js'
import { useCreationAssetStore } from '../../src/stores/creationAssetStore.js'
import { useCreationContractStore } from '../../src/stores/creationContractStore.js'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const behaviorNaiveStubId = '\0contract-workspace-naive-ui-stub'
const HASH_A = 'a'.repeat(64)
const HASH_B = 'b'.repeat(64)

const behaviorNaiveStubPlugin = {
  name: 'contract-workspace-behavior-stubs',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return behaviorNaiveStubId
    return undefined
  },
  load(id) {
    if (id !== behaviorNaiveStubId) return undefined
    return `
      import { defineComponent, h } from 'vue'
      export const focusEvents = []
      const children = slots => Object.values(slots)
        .flatMap(slot => typeof slot === 'function' ? slot() : [])
      const stub = (name, tag = 'div') => defineComponent({
        name,
        inheritAttrs: false,
        setup(_, { attrs, expose, slots }) {
          expose({ focus() { focusEvents.push(name) } })
          return () => h(tag, { ...attrs, 'data-component': name }, children(slots))
        },
      })
      export const NAlert = stub('NAlert', 'aside')
      export const NButton = stub('NButton', 'button')
      export const NCheckbox = stub('NCheckbox', 'input')
      export const NCollapse = stub('NCollapse')
      export const NCollapseItem = stub('NCollapseItem')
      export const NDrawerContent = stub('NDrawerContent', 'section')
      export const NDescriptions = stub('NDescriptions')
      export const NDescriptionsItem = stub('NDescriptionsItem')
      export const NEmpty = stub('NEmpty')
      export const NModal = stub('NModal')
      export const NResult = stub('NResult')
      export const NSelect = stub('NSelect')
      export const NSkeleton = stub('NSkeleton')
      export const NSpin = stub('NSpin')
      export const NTag = stub('NTag', 'span')
      export const NInput = defineComponent({
        name: 'NInput',
        inheritAttrs: false,
        props: { value: { default: '' } },
        emits: ['update:value'],
        setup(props, { attrs, emit }) {
          return () => h('input', {
            ...attrs,
            value: props.value,
            'data-component': 'NInput',
            onInput: event => emit('update:value', event?.target?.value ?? event),
          })
        },
      })
      export const NDrawer = defineComponent({
        name: 'NDrawer',
        inheritAttrs: false,
        props: {
          show: Boolean,
          maskClosable: { type: Boolean, default: true },
          closeOnEsc: { type: Boolean, default: true },
        },
        emits: ['update:show'],
        setup(props, { attrs, emit, slots }) {
          return () => props.show
            ? h('aside', {
                ...attrs,
                'data-component': 'NDrawer',
                maskClosable: props.maskClosable,
                closeOnEsc: props.closeOnEsc,
                onRequestClose: () => emit('update:show', false),
              }, children(slots))
            : null
        },
      })
    `
  },
}

function hostNode(type, text = '') {
  return {
    type,
    text,
    props: {},
    children: [],
    parent: null,
    focus() { this.focused = true },
  }
}

function detach(node) {
  if (!node?.parent) return
  const index = node.parent.children.indexOf(node)
  if (index >= 0) node.parent.children.splice(index, 1)
  node.parent = null
}

const renderer = createRenderer({
  patchProp(element, key, _previous, next) {
    if (next == null) delete element.props[key]
    else element.props[key] = next
  },
  insert(child, parent, anchor = null) {
    detach(child)
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index >= 0) parent.children.splice(index, 0, child)
    else parent.children.push(child)
  },
  remove: detach,
  createElement: type => hostNode(type),
  createText: text => hostNode('#text', String(text)),
  createComment: text => hostNode('#comment', String(text || '')),
  setText(node, text) { node.text = String(text) },
  setElementText(node, text) {
    node.text = String(text)
    node.children = []
  },
  parentNode: node => node?.parent || null,
  nextSibling(node) {
    if (!node?.parent) return null
    const index = node.parent.children.indexOf(node)
    return node.parent.children[index + 1] || null
  },
  querySelector: () => null,
  setScopeId(element, id) { element.props[id] = '' },
  cloneNode(node) {
    return { ...node, props: { ...node.props }, children: [...node.children], parent: null }
  },
  insertStaticContent(content, parent, anchor) {
    const node = hostNode('#static', String(content))
    renderer.insert(node, parent, anchor)
    return [node, node]
  },
})

function walk(node, values = []) {
  if (!node) return values
  values.push(node)
  for (const child of node.children || []) walk(child, values)
  return values
}

function textContent(node) {
  return [node?.text || '', ...(node?.children || []).map(textContent)].join('')
}

async function flush() {
  for (let index = 0; index < 5; index += 1) await Promise.resolve()
  await nextTick()
}

async function trigger(node, name, value) {
  const handlers = Array.isArray(node?.props?.[name]) ? node.props[name] : [node?.props?.[name]]
  assert.equal(typeof handlers[0], 'function', `missing ${name}`)
  for (const handler of handlers) await handler(value)
  await flush()
}

function invoke(node, name, value) {
  const handlers = Array.isArray(node?.props?.[name]) ? node.props[name] : [node?.props?.[name]]
  assert.equal(typeof handlers[0], 'function', `missing ${name}`)
  return Promise.all(handlers.map(handler => handler(value)))
}

async function compileClientRender(path) {
  const contents = await source(path)
  const filename = path.split('/').at(-1)
  const { descriptor } = parse(contents, { filename })
  const script = compileScript(descriptor, { id: `contract-${filename}` })
  const compiled = compile(descriptor.template.content, {
    mode: 'function',
    prefixIdentifiers: true,
    bindingMetadata: script.bindings,
  })
  return new Function('Vue', compiled.code)({
    ...VueRuntime,
    withKeys: handler => handler,
    withModifiers: handler => handler,
  })
}

function findByText(root, type, value) {
  return walk(root).find(node => node.type === type && textContent(node).trim() === value)
}

function inputForLabel(root, value) {
  const label = walk(root).find(node => node.type === 'label' && textContent(node).includes(value))
  assert.ok(label, `missing visible field: ${value}`)
  const input = walk(label).find(node => node.type === 'input')
  assert.ok(input, `missing input for: ${value}`)
  return input
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

let behaviorVite
let StoryEngineStep
let ContractHistoryDrawer
let ContractPreviewStep
let StyleSelectionStep
let StyleTrialPanel
let naiveBehaviorModule

test.before(async () => {
  behaviorVite = await createServer({
    configFile: false,
    root: frontendRoot,
    resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [behaviorNaiveStubPlugin, vuePlugin()],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  StoryEngineStep = (
    await behaviorVite.ssrLoadModule('/src/components/project/contract/StoryEngineStep.vue')
  ).default
  StoryEngineStep.render = await compileClientRender(
    'src/components/project/contract/StoryEngineStep.vue',
  )
  const decisionSummary = (
    await behaviorVite.ssrLoadModule('/src/components/project/contract/ContractDecisionSummary.vue')
  ).default
  decisionSummary.render = await compileClientRender(
    'src/components/project/contract/ContractDecisionSummary.vue',
  )
  ContractHistoryDrawer = (
    await behaviorVite.ssrLoadModule('/src/components/project/contract/ContractHistoryDrawer.vue')
  ).default
  ContractHistoryDrawer.render = await compileClientRender(
    'src/components/project/contract/ContractHistoryDrawer.vue',
  )
  ContractPreviewStep = (
    await behaviorVite.ssrLoadModule('/src/components/project/contract/ContractPreviewStep.vue')
  ).default
  ContractPreviewStep.render = await compileClientRender(
    'src/components/project/contract/ContractPreviewStep.vue',
  )
  StyleTrialPanel = (
    await behaviorVite.ssrLoadModule('/src/components/project/contract/StyleTrialPanel.vue')
  ).default
  StyleTrialPanel.render = await compileClientRender(
    'src/components/project/contract/StyleTrialPanel.vue',
  )
  StyleSelectionStep = (
    await behaviorVite.ssrLoadModule('/src/components/project/contract/StyleSelectionStep.vue')
  ).default
  StyleSelectionStep.render = await compileClientRender(
    'src/components/project/contract/StyleSelectionStep.vue',
  )
  naiveBehaviorModule = await behaviorVite.ssrLoadModule('naive-ui')
})

test.after(async () => {
  await behaviorVite?.close()
})

const file = relative => new URL(`../../${relative}`, import.meta.url)
const source = relative => readFile(file(relative), 'utf8')

function jsonResponse(value = {}) {
  return new Response(JSON.stringify(value), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

async function captureRequests(run) {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options = {}) => {
    calls.push({ url: String(url), options })
    return jsonResponse()
  }
  try {
    await run()
    return calls
  } finally {
    global.fetch = originalFetch
  }
}

function requestBody(call) {
  return call.options.body == null ? undefined : JSON.parse(call.options.body)
}

test('formal client posts style trials and revision-specific clone commands to backend-only routes', async () => {
  assert.equal(typeof api.styleTrials?.generate, 'function')
  const command = {
    selectionRevision: 3,
    engineOptionId: 'engine-1',
    engineHash: 'a'.repeat(64),
    primaryStyleRevisionId: 'style-primary',
    primaryStyleHash: 'b'.repeat(64),
    secondaryStyleRevisionId: null,
    secondaryStyleHash: null,
    authorScenario: '主角必须在救人和守住秘密之间做选择。',
    idempotencyKey: 'i'.repeat(64),
    apiKey: 'must-not-send',
    prompt: 'must-not-send',
  }
  const calls = await captureRequests(async () => {
    await api.styleTrials.generate('project-1', command)
    await api.contracts.clone('project-1', 4)
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['POST', '/api/projects/project-1/style-trials'],
    ['POST', '/api/projects/project-1/contracts/4/clone'],
  ])
  assert.deepEqual(requestBody(calls[0]), {
    selectionRevision: 3,
    engineOptionId: 'engine-1',
    engineHash: 'a'.repeat(64),
    primaryStyleRevisionId: 'style-primary',
    primaryStyleHash: 'b'.repeat(64),
    secondaryStyleRevisionId: null,
    secondaryStyleHash: null,
    authorScenario: '主角必须在救人和守住秘密之间做选择。',
    idempotencyKey: 'i'.repeat(64),
  })
  assert.equal(requestBody(calls[1]), undefined)
  assert.equal(JSON.stringify(calls).includes('must-not-send'), false)
})

test('contract page owns project states and keeps the selected seed read-only', async () => {
  const [view, wizard] = await Promise.all([
    source('src/views/ProjectContractView.vue'),
    source('src/components/project/CreationContractWizard.vue'),
  ])

  assert.match(view, /useRouteProject/)
  assert.match(view, /CreationContractWizard/)
  assert.match(view, /routeProject\.state\.value === 'active'/)
  assert.match(view, /routeProject\.state\.value === 'archived'/)
  assert.match(view, /:read-only="true"/)
  assert.match(wizard, /seedStore\.selectedSeed/)
  assert.match(wizard, /已选创作种子/)
  assert.match(wizard, /只读/)
  assert.match(wizard, /projectSeedsPath/)
  assert.match(wizard, /前往种子/)
  assert.doesNotMatch(wizard, /selectSeed|SeedSelectionStep/)
})

test('wizard is exactly five formal steps and the retired seed step is deleted', async () => {
  const wizard = await source('src/components/project/CreationContractWizard.vue')
  const expected = ['故事发动机', '风格契约', '素材范围', '容量约定', '预览并确认']

  for (const label of expected) assert.match(wizard, new RegExp(label))
  assert.match(wizard, /StoryEngineStep/)
  assert.match(wizard, /StyleSelectionStep/)
  assert.match(wizard, /AssetScopeStep/)
  assert.match(wizard, /CapacityStep/)
  assert.match(wizard, /ContractPreviewStep/)
  assert.match(wizard, /repeat\(5/)
  await assert.rejects(
    access(file('src/components/project/contract/SeedSelectionStep.vue')),
    error => error?.code === 'ENOENT',
  )
})

test('manual story engines use named fields without JSON or channel and genre assumptions', async () => {
  const engine = await source('src/components/project/contract/StoryEngineStep.vue')
  for (const label of ['方案名称', '故事承诺', '主角欲望', '持续压力', '成长方向', '冲突循环', '优势与代价', '结局锚点']) {
    assert.match(engine, new RegExp(label))
  }
  assert.doesNotMatch(engine, /manualJson|JSON\.parse|高级手动 JSON|qidian-qq|['"]玄幻['"]/)
  assert.match(engine, /createManualEngineBatch/)
  assert.match(engine, /保存草稿并继续/)
})

test('style trial panel is temporary, shows safe provider identity, and never selects a style', async () => {
  const [style, trial] = await Promise.all([
    source('src/components/project/contract/StyleSelectionStep.vue'),
    source('src/components/project/contract/StyleTrialPanel.vue'),
  ])
  assert.match(style, /StyleTrialPanel/)
  assert.match(style, /完整应用示例|完整风格样例/)
  assert.match(trial, /runStyleTrial/)
  assert.match(trial, /loading|试写中/)
  assert.match(trial, /failed|失败/)
  assert.match(trial, /succeeded|已完成/)
  assert.match(trial, /providerType/)
  assert.match(trial, /modelName/)
  assert.match(trial, /临时试写/)
  assert.match(trial, /不会自动选择/)
  assert.doesNotMatch(trial, /localStorage|chatCompletion|candidate|Canon|setPrimary/)
})

test('asset scope starts empty and saves explicit fragment ranges within a visible budget', async () => {
  const assets = await source('src/components/project/contract/AssetScopeStep.vue')
  assert.doesNotMatch(assets, /selectedExperienceIds\.value\s*=\s*uniqueIds\(recommendedCards/)
  assert.match(assets, /selectedExperienceIds\.value\s*=\s*\[\]/)
  assert.match(assets, /selectedCorpusFragments/)
  assert.match(assets, /fragmentHash/)
  assert.match(assets, /chapterCharStart/)
  assert.match(assets, /chapterCharEnd/)
  assert.match(assets, /contentHash/)
  assert.match(assets, /4000/)
  assert.match(assets, /完整经验库/)
  assert.match(assets, /完整语料库/)
  assert.match(assets, /当前没有.*推荐/)
  assert.match(assets, /fragmentPage\.value\?\.nextCursor/)
  assert.match(assets, /loadMoreFragments/)
})

test('capacity step captures all formal length and author-direction fields', async () => {
  const [capacity, preview] = await Promise.all([
    source('src/components/project/contract/CapacityStep.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
  ])
  for (const field of [
    'targetTotalWords',
    'expectedVolumeCount',
    'expectedChapterCount',
    'chapterWordRangePreference',
    'prohibitedDirections',
    'authorNotes',
  ]) assert.match(capacity, new RegExp(field))
  assert.match(capacity, /保存草稿并继续/)
  assert.match(capacity, /aria-live="assertive"/)
  assert.match(preview, /返回容量约定/)
})

test('workspace guards unsaved edits, scopes its overlay, and focuses live errors', async () => {
  const files = await Promise.all([
    source('src/components/project/CreationContractWizard.vue'),
    source('src/components/project/contract/StoryEngineStep.vue'),
    source('src/components/project/contract/StyleSelectionStep.vue'),
    source('src/components/project/contract/AssetScopeStep.vue'),
    source('src/components/project/contract/CapacityStep.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
  ])
  const combined = files.join('\n')
  assert.match(combined, /onBeforeRouteLeave/)
  assert.match(combined, /beforeunload/)
  assert.match(combined, /hasUnsavedChanges/)
  assert.match(combined, /contract-operation-overlay/)
  assert.match(combined, /position:\s*absolute/)
  assert.doesNotMatch(combined, /contract-operation-overlay[^}]*position:\s*fixed/s)
  assert.match(combined, /aria-live="polite"/)
  assert.match(combined, /aria-live="assertive"/)
  assert.match(combined, /tabindex="-1"/)
  assert.match(combined, /\.focus\(/)
  assert.match(combined, /requiresReload/)
  assert.match(combined, /重新加载并核对/)
  assert.doesNotMatch(combined, /删除契约|重置契约|resetContract|deleteContract/)
})

test('history shows immutable pinned revisions and enables clone only for compatible generations', async () => {
  const [history, preview] = await Promise.all([
    source('src/components/project/contract/ContractHistoryDrawer.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
  ])
  assert.match(history, /loadHistory/)
  assert.match(history, /pinnedHistoricalRevision/)
  assert.match(history, /supersededReasons/)
  assert.match(history, /selectionRevision/)
  assert.match(history, /cloneRevision\([^)]*revision/)
  assert.match(history, /调整未来设计/)
  assert.match(history, /:disabled="[^"\n]*(superseded|canClone)/)
  assert.match(preview, /一次确认完整契约/)
  assert.match(preview, /不可覆盖|只读/)
  assert.doesNotMatch(`${history}\n${preview}`, /删除|重置/)
})

function engineOption() {
  return {
    id: 'engine-1',
    contentHash: HASH_A,
    payload: {
      name: '作者自定义发动机',
      storyPromise: '承诺',
      sustainedPressure: '压力',
      conflictLoop: '循环',
      advantageAndCost: '优势与代价',
      risks: [],
      differentiation: '差异',
    },
  }
}

function mountWithPinia(component, props, configureStore) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = useCreationContractStore()
  store.draft = {
    id: 'draft-1',
    projectId: 'project-1',
    draftVersion: 3,
    draftStage: 'engine',
    draft: {
      schemaVersion: 'contract-draft-v2',
      draftStage: 'engine',
      engineOptionId: 'engine-1',
      engineHash: HASH_A,
      qualityCharterVersion: 'quality-v1',
    },
  }
  store.engineBatch = { id: 'batch-1', status: 'succeeded', options: [engineOption()] }
  configureStore?.(store)
  const Root = defineComponent({
    setup: () => () => h(component, typeof props === 'function' ? props() : props),
  })
  const root = hostNode('root')
  const app = renderer.createApp(Root)
  app.use(pinia)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)
  return { app, root, store }
}

test('story engine refuses missing author-visible profile identifiers without saving and focuses its error', async () => {
  let saveCalls = 0
  naiveBehaviorModule.focusEvents.length = 0
  const mounted = mountWithPinia(StoryEngineStep, {
    projectId: 'project-1',
    project: {},
    selectedSeed: { title: '无题材种子' },
  }, store => {
    store.saveDraft = async () => {
      saveCalls += 1
      throw new Error('missing profiles must never reach saveDraft')
    }
  })

  try {
    assert.equal(inputForLabel(mounted.root, '渠道定位标识').props.value, '')
    assert.equal(inputForLabel(mounted.root, '题材定位标识').props.value, '')
    await trigger(findByText(mounted.root, 'button', '保存草稿并继续'), 'onClick')

    assert.equal(saveCalls, 0)
    assert.match(textContent(mounted.root), /渠道定位标识和题材定位标识均不能为空。/)
    assert.ok(naiveBehaviorModule.focusEvents.includes('NAlert'))
  } finally {
    mounted.app.unmount()
  }
})

test('story engine trims and saves custom profile identifiers without mapping or fabrication', async () => {
  const calls = []
  const mounted = mountWithPinia(StoryEngineStep, {
    projectId: 'project-1',
    project: { channelProfileKey: 'initial-channel' },
    selectedSeed: { title: '种子', genre: 'initial-genre' },
  }, store => {
    store.saveDraft = async (projectId, payload) => {
      calls.push({ projectId, payload: structuredClone(payload) })
      const saved = {
        ...store.draft,
        draftVersion: store.draft.draftVersion + 1,
        draft: structuredClone(payload),
      }
      store.draft = saved
      return saved
    }
  })

  try {
    const channel = inputForLabel(mounted.root, '渠道定位标识')
    const genre = inputForLabel(mounted.root, '题材定位标识')
    assert.equal(channel.props.value, 'initial-channel')
    assert.equal(genre.props.value, 'initial-genre')
    await trigger(channel, 'onInput', { target: { value: '  custom-channel  ' } })
    await trigger(genre, 'onInput', { target: { value: '  自定义题材标识  ' } })
    await trigger(findByText(mounted.root, 'button', '保存草稿并继续'), 'onClick')

    assert.equal(calls.length, 1)
    assert.equal(calls[0].projectId, 'project-1')
    assert.equal(calls[0].payload.channelProfileKey, 'custom-channel')
    assert.equal(calls[0].payload.genreProfileKey, '自定义题材标识')
    assert.equal(JSON.stringify(calls[0]).includes('unspecified'), false)
  } finally {
    mounted.app.unmount()
  }
})

test('history drawer renders every pinned identity and fragment while generation gates clone', async () => {
  const hashes = {
    seed: '1'.repeat(64),
    engine: '2'.repeat(64),
    style: '3'.repeat(64),
    card: '4'.repeat(64),
    corpus: '5'.repeat(64),
    fragment: '6'.repeat(64),
  }
  const mounted = mountWithPinia(ContractHistoryDrawer, {
    show: true,
    projectId: 'project-1',
    currentSelectionRevision: 8,
    readOnly: false,
  }, store => {
    store.history = [{
      revision: 4,
      selectionRevision: 8,
      seedRef: { id: 'seed-1', revisionId: 'seed-revision-7', contentHash: hashes.seed },
      engineRef: { id: 'engine-1', batchId: 'engine-batch-9', contentHash: hashes.engine },
      styleRefs: [{ id: 'style-1', revision: 2, contentHash: hashes.style }],
      experienceCardRefs: [{ id: 'card-1', revision: 3, contentHash: hashes.card }],
      corpusSourceRefs: [{
        id: 'corpus-1', revisionId: 'corpus-revision-5', revision: 5,
        contentHash: hashes.corpus, pinnedHistoricalRevision: true,
        fragments: [{
          chapterId: 'chapter-2', fragmentId: 'fragment-8', fragmentHash: hashes.fragment,
          chapterCharStart: 12, chapterCharEnd: 34, referenceUse: 'style',
        }],
      }],
      supersededReasons: ['contract_revision_replaced'],
    }, {
      revision: 3,
      selectionRevision: 7,
      seedRef: { id: 'old-seed', revisionId: 'old-revision', contentHash: HASH_A },
      engineRef: { id: 'old-engine', batchId: 'old-batch', contentHash: HASH_B },
      styleRefs: [], experienceCardRefs: [], corpusSourceRefs: [], supersededReasons: [],
    }]
    store.loadHistory = async () => ({ items: store.history })
  })

  try {
    await flush()
    const rendered = textContent(mounted.root)
    for (const value of [
      'seed-1', 'seed-revision-7', hashes.seed,
      'engine-1', 'engine-batch-9', hashes.engine,
      'style-1', hashes.style, 'card-1', hashes.card,
      'corpus-1', 'corpus-revision-5', hashes.corpus,
      'chapter-2', 'fragment-8', hashes.fragment, '12–34', 'style',
    ]) assert.ok(rendered.includes(value), `missing pinned history identity: ${value}`)
    assert.match(rendered, /历史版本已钉住/)
    assert.match(rendered, /已被更新修订取代/)
    const cloneButtons = walk(mounted.root).filter(node => (
      node.type === 'button' && textContent(node).trim() === '调整未来设计'
    ))
    assert.equal(cloneButtons.length, 2)
    assert.notEqual(cloneButtons[0].props.disabled, true)
    assert.equal(cloneButtons[1].props.disabled, true)
  } finally {
    mounted.app.unmount()
  }
})

function completeDecisionPayload() {
  return {
    creationContract: {
      channelProfileKey: '女性成长频道',
      genreProfileKey: '架空悬疑',
      qualityCharterVersion: '质量章程-2026',
      selectedSeed: {
        title: '雾港拾灯人',
        genre: '潮汐奇谭',
        logline: '她必须在黎明前找回失踪档案。',
        protagonist: '拾灯人林缈',
        desire: '让被抹去的人重获姓名',
        coreConflict: '公布真相会让港城提前沉没',
        worldPressure: '每次涨潮都会抹去一段公共记忆',
        openingHook: '一盏本该熄灭的灯叫出了她的名字',
        differentiation: '用潮汐线与档案缺页双重记录遗忘',
      },
      selectedEngine: {
        name: '钟摆发动机',
        storyPromise: '每次破案都会失去一段记忆。',
        protagonistDesire: '保住妹妹的真实姓名',
        sustainedPressure: '城市在七日后沉没',
        growthDirection: '从独行转向学会托付',
        conflictLoop: '追查—交换—反噬—重新结盟',
        ensembleRoles: [{ role: '钟表匠', purpose: '提供错误时间线' }],
        advantageAndCost: '能听见谎言，代价是忘记一个真相',
        satisfactionSources: ['线索闭环', '关系反转'],
        longFormVariation: '每卷更换一个时间规则',
        endingAnchor: '她亲手写回所有人的名字',
        risks: ['设定过密'],
        differentiation: '以记忆作为侦探成本',
      },
      targetTotalWords: 1_260_000,
      expectedVolumeCount: 7,
      expectedChapterCount: 420,
      chapterWordRangePreference: [2_800, 3_400],
      prohibitedDirections: ['禁止无代价升级', '禁止工具人反派'],
      authorNotes: '人物选择必须优先于设定解释。',
    },
    styleContract: {
      readingExperience: '克制、清醒，但余韵绵长',
      narrativeDistance: '限知近距离',
      sentenceParagraphRhythm: '短句推进，长段收束',
      dictionDensity: '中等意象密度',
      dialogueAndSubtext: '对话留白，潜台词承担关系变化',
      characterVoices: '主要人物各有句式指纹',
      emotionAndInteriority: '情绪通过选择和动作外化',
      actionExplanationEnvironment: '动作六成，解释二成，环境二成',
      primaryRules: ['每场戏必须有不可逆变化'],
      secondaryFlavor: ['雨夜霍光', '旧纸质感'],
      risks: ['留白过多导致信息不足'],
    },
    likes: ['对话中的关系位移'],
    dislikes: ['用脸色发白代替情绪'],
  }
}

test('reusable decision summary renders every formal author decision without dropping API data', async () => {
  let componentModule
  try {
    componentModule = await behaviorVite.ssrLoadModule(
      '/src/components/project/contract/ContractDecisionSummary.vue',
    )
  } catch (error) {
    assert.fail(`reusable decision summary is missing: ${error.message}`)
  }
  const component = componentModule.default
  component.render = await compileClientRender(
    'src/components/project/contract/ContractDecisionSummary.vue',
  )
  const mounted = mountWithPinia(component, completeDecisionPayload())

  try {
    const rendered = textContent(mounted.root)
    for (const label of [
      '渠道', '题材', '质量章程', '故事承诺', '主角欲望', '持续压力', '成长方向', '冲突循环',
      '目标总字数', '预计卷数', '预计章数', '单章字数', '禁止方向', '作者备注',
      '阅读体验', '叙事距离', '句段节奏', '用词密度', '对话与潜台词', '人物声音',
      '情绪与内心', '动作·解释·环境', '主规则', '次要风味', '风险', '喜欢', '避开',
      '种子标题', '一句话梗概', '主角', '核心冲突', '世界压力', '开局钩子', '差异化',
    ]) assert.ok(rendered.includes(label), `missing decision label: ${label}`)
    for (const value of [
      '女性成长频道', '架空悬疑', '质量章程-2026', '钟摆发动机',
      '保住妹妹的真实姓名', '追查—交换—反噬—重新结盟', '1,260,000', '2,800', '3,400',
      '人物选择必须优先于设定解释。', '限知近距离', '动作六成，解释二成，环境二成',
      '每场戏必须有不可逆变化', '留白过多导致信息不足', '对话中的关系位移', '用脸色发白代替情绪',
      '雾港拾灯人', '潮汐奇谭', '她必须在黎明前找回失踪档案。', '拾灯人林缈',
      '让被抹去的人重获姓名', '公布真相会让港城提前沉没',
      '每次涨潮都会抹去一段公共记忆', '一盏本该熄灭的灯叫出了她的名字',
      '用潮汐线与档案缺页双重记录遗忘',
    ]) assert.ok(rendered.includes(value), `missing decision value: ${value}`)
  } finally {
    mounted.app.unmount()
  }
})

test('confirmed head and every history revision consume the same decision-summary component', async () => {
  const [wizard, history, preview] = await Promise.all([
    source('src/components/project/CreationContractWizard.vue'),
    source('src/components/project/contract/ContractHistoryDrawer.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
  ])
  for (const component of [wizard, history, preview]) {
    assert.match(component, /ContractDecisionSummary/)
  }
})

test('contract preview ignores an old project failure after the new project preview succeeds', async () => {
  const pendingA = deferred()
  const projectId = VueRuntime.ref('project-a')
  const calls = []
  const mounted = mountWithPinia(ContractPreviewStep, () => ({ projectId: projectId.value }), store => {
    store.preview = async targetProjectId => {
      calls.push(targetProjectId)
      if (targetProjectId === 'project-a') return pendingA.promise
      const result = {
        projectId: targetProjectId,
        contractReady: true,
        reasons: [],
        seedRef: { revisionId: 'project-b-success', contentHash: HASH_A },
        engineRef: { batchId: 'batch-b', contentHash: HASH_B },
        bindingRef: { revision: 2, contentHash: HASH_A, items: [] },
        styleRefs: [], experienceCardRefs: [], corpusSourceRefs: [],
      }
      store.previewResult = result
      return result
    }
  })

  try {
    await flush()
    projectId.value = 'project-b'
    await flush()
    pendingA.reject(new Error('project-a-late-failure'))
    await flush()

    assert.deepEqual(calls, ['project-a', 'project-b'])
    assert.match(textContent(mounted.root), /project-b-success/)
    assert.doesNotMatch(textContent(mounted.root), /project-a-late-failure/)
  } finally {
    mounted.app.unmount()
  }
})

test('style selection keeps rapid A to B navigation on B when A fails late', async () => {
  const pendingA = deferred()
  const projectId = VueRuntime.ref('project-a')
  let listCalls = 0
  const styleB = {
    id: 'style-b', name: '项目 B 风格', revision: 2, contentHash: HASH_B,
    readingExperience: 'B 的阅读体验', reasonCodes: [], applicability: [], nonApplicability: [],
  }
  const mounted = mountWithPinia(StyleSelectionStep, () => ({
    projectId: projectId.value,
    selectionRevision: 2,
  }), contractStore => {
    contractStore.load = async targetProjectId => {
      contractStore.projectId = targetProjectId
      contractStore.draft = {
        ...contractStore.draft,
        projectId: targetProjectId,
        draft: {
          ...contractStore.draft.draft,
          engineOptionId: `engine-${targetProjectId}`,
          engineHash: HASH_A,
          channelProfileKey: 'channel',
          genreProfileKey: 'genre',
        },
      }
    }
    const assetStore = useCreationAssetStore()
    assetStore.loadStyleTemplates = async () => {
      listCalls += 1
      if (listCalls === 1) return pendingA.promise
      assetStore.styleTemplates = [styleB]
      return [styleB]
    }
    assetStore.loadRecommendations = async targetProjectId => {
      const result = { styles: targetProjectId === 'project-b' ? [styleB] : [] }
      if (targetProjectId === 'project-b') assetStore.recommendations = result
      return result
    }
  })

  try {
    await flush()
    projectId.value = 'project-b'
    await flush()
    pendingA.reject(new Error('project-a-style-late-failure'))
    await flush()

    assert.equal(listCalls, 2)
    assert.match(textContent(mounted.root), /项目 B 风格/)
    assert.doesNotMatch(textContent(mounted.root), /project-a-style-late-failure/)
    const sourceText = await source('src/components/project/contract/StyleSelectionStep.vue')
    assert.match(sourceText, /createLatestRequestGuard/)
  } finally {
    mounted.app.unmount()
  }
})

function styleSummary(id, name, contentHash) {
  return {
    id,
    name,
    revision: id === 'style-a' ? 1 : 2,
    contentHash,
    readingExperience: `${name}的阅读体验`,
    reasonCodes: [],
    applicability: [],
    nonApplicability: [],
  }
}

function styleDetail(id, name, contentHash) {
  return {
    id,
    stableKey: `${id}-stable`,
    name,
    revision: id === 'style-a' ? 1 : 2,
    contentHash,
    payload: {
      readingExperience: `${name}阅读体验`,
      narrativeDistance: '限知',
      rhythm: '快慢相间',
      dictionDensity: '中等',
      dialogue: '克制',
      subtext: '清晰',
      characterVoices: '可区分',
      emotion: '外化',
      interiority: '选择驱动',
      standardSceneExample: `${name}标准场景`,
      completeApplicationExample: `${name}完整示例`,
      risks: [`${name}风险`],
    },
  }
}

for (const lateOutcome of ['success', 'failure']) {
  test(`style detail keeps B after A resolves late with ${lateOutcome}`, async () => {
    const pendingA = deferred()
    const pendingB = deferred()
    const styleA = styleSummary('style-a', '风格 A', HASH_A)
    const styleB = styleSummary('style-b', '风格 B', HASH_B)
    naiveBehaviorModule.focusEvents.length = 0
    const mounted = mountWithPinia(StyleSelectionStep, {
      projectId: 'project-1',
      selectionRevision: 2,
    }, contractStore => {
      contractStore.projectId = 'project-1'
      const assetStore = useCreationAssetStore()
      assetStore.loadStyleTemplates = async () => {
        assetStore.styleTemplates = [styleA, styleB]
        return [styleA, styleB]
      }
      assetStore.loadRecommendations = async () => {
        const result = { styles: [styleA, styleB] }
        assetStore.recommendations = result
        return result
      }
      assetStore.getStyleTemplate = async id => (
        id === 'style-a' ? pendingA.promise : pendingB.promise
      )
    })

    try {
      await flush()
      const detailButtons = walk(mounted.root).filter(node => (
        node.type === 'button' && textContent(node).trim() === '阅读全文示例'
      ))
      assert.equal(detailButtons.length, 2)
      const openA = invoke(detailButtons[0], 'onClick')
      await flush()
      const openB = invoke(detailButtons[1], 'onClick')
      pendingB.resolve(styleDetail('style-b', 'B 详情名称', HASH_B))
      await openB
      await flush()

      assert.match(textContent(mounted.root), /B 详情名称/)
      const modal = walk(mounted.root).find(node => node.props['data-component'] === 'NModal')
      const detailSpin = walk(modal).find(node => node.props['data-component'] === 'NSpin')
      assert.equal(detailSpin.props.show, false)

      if (lateOutcome === 'success') {
        pendingA.resolve(styleDetail('style-a', 'A 迟到详情', HASH_A))
      } else {
        pendingA.reject(new Error('A 迟到详情错误'))
      }
      await openA
      await flush()

      const rendered = textContent(mounted.root)
      assert.match(rendered, /B 详情名称/)
      assert.doesNotMatch(rendered, /A 迟到详情|A 迟到详情错误/)
      assert.equal(detailSpin.props.show, false)
      assert.deepEqual(naiveBehaviorModule.focusEvents, [])
    } finally {
      mounted.app.unmount()
    }
  })
}

for (const lateOutcome of ['rejection', 'failed-result']) {
  test(`style trial keeps B after obsolete A ${lateOutcome}`, async () => {
    const pendingA = deferred()
    const pendingB = deferred()
    const originalGenerate = api.styleTrials.generate
    const primaryStyleRef = VueRuntime.ref({ id: 'style-a', revision: 1, contentHash: HASH_A })
    const commands = []
    naiveBehaviorModule.focusEvents.length = 0
    api.styleTrials.generate = async (_projectId, command) => {
      commands.push(structuredClone(command))
      return command.authorScenario === '场景 A' ? pendingA.promise : pendingB.promise
    }
    const mounted = mountWithPinia(StyleTrialPanel, () => ({
      projectId: 'project-1',
      selectionRevision: 2,
      engineOptionId: 'engine-1',
      engineHash: HASH_A,
      primaryStyleRef: primaryStyleRef.value,
      secondaryStyleRef: null,
    }))

    try {
      const scenario = inputForLabel(mounted.root, '作者场景')
      await trigger(scenario, 'onInput', { target: { value: '场景 A' } })
      const runA = invoke(findByText(mounted.root, 'button', '运行临时试写'), 'onClick')
      await flush()

      primaryStyleRef.value = { id: 'style-b', revision: 2, contentHash: HASH_B }
      await trigger(scenario, 'onInput', { target: { value: '场景 B' } })
      const runB = invoke(findByText(mounted.root, 'button', '运行临时试写'), 'onClick')
      pendingB.resolve({
        attemptId: 'trial-b',
        status: 'succeeded',
        sample: 'B 当前试写正文',
        provider: { providerType: 'safe-provider', modelName: 'model-b', profileRevision: 2 },
      })
      await runB
      await flush()
      assert.match(textContent(mounted.root), /B 当前试写正文/)

      if (lateOutcome === 'rejection') {
        pendingA.reject(new Error('A 迟到试写错误'))
      } else {
        pendingA.resolve({
          attemptId: 'trial-a',
          status: 'failed',
          publicErrorCode: 'A_OBSOLETE_FAILED',
        })
      }
      await runA
      await flush()

      assert.deepEqual(commands.map(command => ({
        scenario: command.authorScenario,
        styleId: command.primaryStyleRevisionId,
        styleHash: command.primaryStyleHash,
      })), [
        { scenario: '场景 A', styleId: 'style-a', styleHash: HASH_A },
        { scenario: '场景 B', styleId: 'style-b', styleHash: HASH_B },
      ])
      assert.equal(mounted.store.styleTrial?.attemptId, 'trial-b')
      const rendered = textContent(mounted.root)
      assert.match(rendered, /B 当前试写正文/)
      assert.doesNotMatch(rendered, /A 迟到试写错误|A_OBSOLETE_FAILED/)
      assert.deepEqual(naiveBehaviorModule.focusEvents, [])
    } finally {
      api.styleTrials.generate = originalGenerate
      mounted.app.unmount()
    }
  })
}

function simpleHistoryRow(revision) {
  return {
    revision,
    selectionRevision: 8,
    styleRefs: [], experienceCardRefs: [], corpusSourceRefs: [], supersededReasons: [],
  }
}

test('history clone ignores close requests while pending then closes through the cloned step handoff', async () => {
  const pendingClone = deferred()
  const originalClone = api.contracts.clone
  const show = VueRuntime.ref(true)
  const events = []
  const clonedDraft = {
    id: 'draft-from-r4',
    projectId: 'project-1',
    baseHeadRevision: 4,
    draftVersion: 1,
    draftStage: 'assets',
    draft: { draftStage: 'assets' },
  }
  api.contracts.clone = async () => pendingClone.promise
  const mounted = mountWithPinia(ContractHistoryDrawer, () => ({
    show: show.value,
    projectId: 'project-1',
    currentSelectionRevision: 8,
    readOnly: false,
    'onUpdate:show': value => {
      events.push(['show', value])
      show.value = value
    },
    onCloned: value => events.push(['cloned', value]),
  }), store => {
    store.projectId = 'project-1'
    store.history = [simpleHistoryRow(4)]
    store.loadHistory = async () => ({ items: store.history, nextBeforeRevision: null })
  })

  try {
    await flush()
    const clone = invoke(findByText(mounted.root, 'button', '调整未来设计'), 'onClick')
    await flush()
    assert.equal(mounted.store.cloning, true)
    const drawer = walk(mounted.root).find(node => node.props['data-component'] === 'NDrawer')
    const content = walk(drawer).find(node => node.props['data-component'] === 'NDrawerContent')
    const pendingFlags = {
      maskClosable: drawer.props.maskClosable,
      closeOnEsc: drawer.props.closeOnEsc,
      contentClosable: content.props.closable,
    }
    await trigger(drawer, 'onRequestClose')
    const stayedOpen = show.value

    pendingClone.resolve(clonedDraft)
    await clone
    await flush()

    assert.equal(stayedOpen, true)
    assert.deepEqual(pendingFlags, {
      maskClosable: false,
      closeOnEsc: false,
      contentClosable: false,
    })
    assert.deepEqual(events, [
      ['show', false],
      ['cloned', clonedDraft],
    ])
    assert.equal(show.value, false)
    const wizard = await source('src/components/project/CreationContractWizard.vue')
    assert.match(wizard, /@cloned="advance\(4\)"/)
  } finally {
    api.contracts.clone = originalClone
    mounted.app.unmount()
  }
})

test('history clone failure keeps the drawer open and focuses its current error', async () => {
  const pendingClone = deferred()
  const originalClone = api.contracts.clone
  const show = VueRuntime.ref(true)
  const events = []
  naiveBehaviorModule.focusEvents.length = 0
  api.contracts.clone = async () => pendingClone.promise
  const mounted = mountWithPinia(ContractHistoryDrawer, () => ({
    show: show.value,
    projectId: 'project-1',
    currentSelectionRevision: 8,
    readOnly: false,
    'onUpdate:show': value => {
      events.push(['show', value])
      show.value = value
    },
    onCloned: value => events.push(['cloned', value]),
  }), store => {
    store.projectId = 'project-1'
    store.history = [simpleHistoryRow(4)]
    store.loadHistory = async () => ({ items: store.history, nextBeforeRevision: null })
  })

  try {
    await flush()
    const clone = invoke(findByText(mounted.root, 'button', '调整未来设计'), 'onClick')
    await flush()
    const drawer = walk(mounted.root).find(node => node.props['data-component'] === 'NDrawer')
    await trigger(drawer, 'onRequestClose')
    pendingClone.reject(new Error('当前克隆失败'))
    await clone
    await flush()

    assert.equal(show.value, true)
    assert.deepEqual(events, [])
    assert.equal(mounted.store.cloning, false)
    assert.match(textContent(mounted.root), /当前克隆失败/)
    assert.ok(naiveBehaviorModule.focusEvents.includes('NAlert'))
  } finally {
    api.contracts.clone = originalClone
    mounted.app.unmount()
  }
})

test('history drawer reloads on project change and ignores the old project late failure', async () => {
  const pendingA = deferred()
  const projectId = VueRuntime.ref('project-a')
  const show = VueRuntime.ref(false)
  const calls = []
  naiveBehaviorModule.focusEvents.length = 0
  const mounted = mountWithPinia(ContractHistoryDrawer, () => ({
    show: show.value,
    projectId: projectId.value,
    currentSelectionRevision: 8,
    readOnly: false,
  }), store => {
    store.loadHistory = async targetProjectId => {
      calls.push(targetProjectId)
      if (targetProjectId === 'project-a') return pendingA.promise
      store.history = [simpleHistoryRow(22)]
      return { items: store.history, nextBeforeRevision: null }
    }
    store.clearHistory = () => { store.history = [] }
  })

  try {
    show.value = true
    await flush()
    projectId.value = 'project-b'
    await flush()
    pendingA.reject(new Error('project-a-history-late-failure'))
    await flush()

    assert.deepEqual(calls, ['project-a', 'project-b'])
    assert.match(textContent(mounted.root), /R22/)
    assert.doesNotMatch(textContent(mounted.root), /project-a-history-late-failure/)
    assert.deepEqual(naiveBehaviorModule.focusEvents, [])
  } finally {
    mounted.app.unmount()
  }
})

test('closing history invalidates its pending request and leaves no stale error or focus on reopen', async () => {
  const pending = deferred()
  const show = VueRuntime.ref(false)
  let loads = 0
  naiveBehaviorModule.focusEvents.length = 0
  const mounted = mountWithPinia(ContractHistoryDrawer, () => ({
    show: show.value,
    projectId: 'project-1',
    currentSelectionRevision: 8,
    readOnly: false,
  }), store => {
    store.loadHistory = async () => {
      loads += 1
      if (loads === 1) return pending.promise
      store.history = [simpleHistoryRow(30)]
      return { items: store.history, nextBeforeRevision: null }
    }
    store.clearHistory = () => { store.history = [] }
  })

  try {
    show.value = true
    await flush()
    show.value = false
    await flush()
    pending.reject(new Error('closed-history-late-failure'))
    await flush()
    assert.deepEqual(naiveBehaviorModule.focusEvents, [])

    show.value = true
    await flush()
    assert.equal(loads, 2)
    assert.match(textContent(mounted.root), /R30/)
    assert.doesNotMatch(textContent(mounted.root), /closed-history-late-failure/)
  } finally {
    mounted.app.unmount()
  }
})

test('history drawer pages forward, clamps width, and resets state when closed', async () => {
  const show = VueRuntime.ref(false)
  const loads = []
  let clears = 0
  const mounted = mountWithPinia(ContractHistoryDrawer, () => ({
    show: show.value,
    projectId: 'project-1',
    currentSelectionRevision: 8,
    readOnly: false,
  }), store => {
    store.loadHistory = async (_projectId, params) => {
      loads.push({ ...params })
      if (params.append) {
        store.history = [...store.history, simpleHistoryRow(4)]
        store.historyNextBeforeRevision = null
      } else {
        store.history = [simpleHistoryRow(5)]
        store.historyNextBeforeRevision = 5
      }
      return { items: store.history, nextBeforeRevision: store.historyNextBeforeRevision }
    }
    store.clearHistory = () => {
      clears += 1
      store.history = []
      store.historyNextBeforeRevision = null
    }
  })

  try {
    show.value = true
    await flush()
    const drawer = walk(mounted.root).find(node => node.props['data-component'] === 'NDrawer')
    assert.equal(drawer.props.width, 'min(620px, 100vw)')
    await trigger(findByText(mounted.root, 'button', '加载更多'), 'onClick')
    assert.deepEqual(loads, [
      { limit: 20 },
      { limit: 20, beforeRevision: 5, append: true },
    ])
    assert.deepEqual(mounted.store.history.map(item => item.revision), [5, 4])

    show.value = false
    await flush()
    assert.equal(clears, 1)
    assert.deepEqual(mounted.store.history, [])
  } finally {
    mounted.app.unmount()
  }
})

test('contract workspace components inherit the paper ink and seal design tokens', async () => {
  const files = await Promise.all([
    source('src/components/project/contract/StoryEngineStep.vue'),
    source('src/components/project/contract/StyleSelectionStep.vue'),
    source('src/components/project/contract/AssetScopeStep.vue'),
    source('src/components/project/contract/CapacityStep.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
    source('src/components/project/contract/ContractHistoryDrawer.vue'),
    source('src/components/project/contract/StyleTrialPanel.vue'),
  ])
  const combined = files.join('\n')
  for (const token of ['--paper', '--ink', '--muted', '--rule', '--cinnabar', '--jade']) {
    assert.match(combined, new RegExp(`var\\(${token},`))
  }
  assert.doesNotMatch(files[5], /font-size:\s*(?:8|9|10)px/)
})
