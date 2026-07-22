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
      export const NEmpty = stub('NEmpty')
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
        props: { show: Boolean },
        emits: ['update:show'],
        setup(props, { attrs, slots }) {
          return () => props.show
            ? h('aside', { ...attrs, 'data-component': 'NDrawer' }, children(slots))
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

let behaviorVite
let StoryEngineStep
let ContractHistoryDrawer
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
  ContractHistoryDrawer = (
    await behaviorVite.ssrLoadModule('/src/components/project/contract/ContractHistoryDrawer.vue')
  ).default
  ContractHistoryDrawer.render = await compileClientRender(
    'src/components/project/contract/ContractHistoryDrawer.vue',
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
  const Root = defineComponent({ setup: () => () => h(component, props) })
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
