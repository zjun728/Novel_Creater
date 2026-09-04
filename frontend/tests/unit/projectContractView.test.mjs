import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
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
import { useCorpusStore } from '../../src/stores/corpusStore.js'
import { useSeedStore } from '../../src/stores/seedStore.js'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const behaviorNaiveStubId = '\0contract-workspace-naive-ui-stub'
const HASH_A = 'a'.repeat(64)
const HASH_B = 'b'.repeat(64)
const teleportTarget = hostNode('body')

test('real Naive UI alert renders default recovery markup but has no action slot', async () => {
  const require = createRequire(import.meta.url)
  const NAlert = require('naive-ui/lib/alert/src/Alert.js').default
  const NButton = require('naive-ui/lib/button/src/Button.js').default
  const [{ createSSRApp }, { renderToString }] = await Promise.all([
    import('vue'), import('@vue/server-renderer'),
  ])
  const html = await renderToString(createSSRApp({
    setup: () => () => h(NAlert, null, {
      default: () => [h('p', '权威状态已变化'), h(NButton, null, () => '默认内容恢复')],
      action: () => h(NButton, null, () => '无效 action 恢复'),
    }),
  }))

  assert.match(html, /默认内容恢复/)
  assert.doesNotMatch(html, /无效 action 恢复/)
})

test('confirmed contract components present a permanent baseline without clone controls', async () => {
  const files = await Promise.all([
    'src/components/project/ContractHeadSummary.vue',
    'src/components/project/CreationContractWizard.vue',
    'src/components/project/contract/ContractHistoryDrawer.vue',
  ].map(path => source(path)))
  const contents = files.join('\n')
  assert.match(contents, /已确认，作为项目永久基线/)
  assert.match(contents, /Number\(contractStore\.head\?\.revision \|\| 0\) > 0/)
  assert.doesNotMatch(contents, /contractStore\.contractReady\s*&&\s*!contractStore\.draft/)
  assert.doesNotMatch(contents, /创建新修订|调整未来设计|cloneRevision/)
  assert.doesNotMatch(contents, /contracts\/[^`'"\n]*\/clone/)
})

function formalAssetRecommendations(styles = [], cards = [], corpus = []) {
  return {
    attemptId: 'attempt-formal',
    publicReason: null,
    rankingUnavailable: false,
    fullBrowseAvailable: true,
    assetRecommendations: [
      ...styles.map(style => ({
        assetRevisionId: style.id,
        assetType: 'style',
        stableKey: style.stableKey,
        revision: style.revision,
        contentHash: style.contentHash,
        reason: 'semantic-profile',
        confidence: 0.93,
      })),
      ...cards.map(card => ({
        assetRevisionId: card.id,
        assetType: 'experience_card',
        stableKey: card.stableKey,
        revision: card.revision,
        contentHash: card.contentHash,
        reason: 'asset-text-overlap',
        confidence: 0.89,
      })),
    ],
    corpusRecommendations: corpus,
    inputManifest: {},
    inputManifestHash: HASH_A,
    resultHash: HASH_B,
  }
}

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
      export const NAlert = defineComponent({
        name: 'NAlert',
        inheritAttrs: false,
        setup(_, { attrs, expose, slots }) {
          expose({ $el: { focus() { focusEvents.push('NAlert.$el') } } })
          return () => h('aside', { ...attrs, 'data-component': 'NAlert' }, slots.default?.())
        },
      })
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
      export const NInputNumber = defineComponent({
        name: 'NInputNumber',
        inheritAttrs: false,
        props: { value: { default: null } },
        emits: ['update:value'],
        setup(props, { attrs, emit }) {
          return () => h('input', {
            ...attrs,
            value: props.value,
            'data-component': 'NInputNumber',
            onInput: event => emit('update:value', Number(event?.target?.value ?? event)),
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
  querySelector: selector => selector === 'body' ? teleportTarget : null,
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

function textExcluding(node, excluded) {
  if (!node || node === excluded) return ''
  return [node.text || '', ...(node.children || []).map(child => textExcluding(child, excluded))].join('')
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
let AssetScopeStep
let CapacityStep
let CreationContractWizard
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
  AssetScopeStep = (
    await behaviorVite.ssrLoadModule('/src/components/project/contract/AssetScopeStep.vue')
  ).default
  AssetScopeStep.render = await compileClientRender(
    'src/components/project/contract/AssetScopeStep.vue',
  )
  CapacityStep = (
    await behaviorVite.ssrLoadModule('/src/components/project/contract/CapacityStep.vue')
  ).default
  CapacityStep.render = await compileClientRender(
    'src/components/project/contract/CapacityStep.vue',
  )
  for (const path of [
    'src/components/foundation/FoundationWorkspace.vue',
    'src/components/foundation/FoundationSectionIndex.vue',
    'src/components/foundation/FoundationStatusRail.vue',
    'src/components/foundation/FoundationDocumentSection.vue',
    'src/components/foundation/FoundationConfirmationDialog.vue',
  ]) {
    const foundationComponent = (await behaviorVite.ssrLoadModule(`/${path}`)).default
    foundationComponent.render = await compileClientRender(path)
  }
  CreationContractWizard = (
    await behaviorVite.ssrLoadModule('/src/components/project/CreationContractWizard.vue')
  ).default
  CreationContractWizard.render = await compileClientRender(
    'src/components/project/CreationContractWizard.vue',
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
  assert.match(view, /contract-page--foundation/)
  assert.match(wizard, /seedStore\.selectedSeed/)
  assert.match(wizard, /已选创作种子/)
  assert.match(wizard, /只读/)
  assert.match(wizard, /projectSeedsPath/)
  assert.match(wizard, /前往种子/)
  assert.doesNotMatch(wizard, /selectSeed|SeedSelectionStep/)
})

test('contract is one six-section author document rather than a paged wizard', async () => {
  const [wizard, mapper] = await Promise.all([
    source('src/components/project/CreationContractWizard.vue'),
    source('src/application/contracts/contractDocumentSections.js'),
  ])
  const expected = ['故事发动机', '长篇容量', '正式资产范围', '风格方案', '禁止方向', '完整预览']

  for (const label of expected) assert.match(`${wizard}\n${mapper}`, new RegExp(label))
  for (const foundationComponent of [
    'FoundationWorkspace', 'FoundationSectionIndex',
    'FoundationStatusRail', 'FoundationDocumentSection',
  ]) assert.match(wizard, new RegExp(foundationComponent))
  assert.match(wizard, /contractDocumentSections/)
  assert.match(wizard, /activeSectionKey/)
  assert.match(wizard, /targetId:\s*`contract-section-\$\{section\.key\}`/)
  assert.match(wizard, /StoryEngineStep/)
  assert.match(wizard, /StyleSelectionStep/)
  assert.match(wizard, /AssetScopeStep/)
  assert.match(wizard, /CapacityStep/)
  assert.match(wizard, /ContractPreviewStep/)
  assert.doesNotMatch(wizard, /const step\s*=|step-ribbon|openStep|advance\(|repeat\(5/)
  assert.doesNotMatch(wizard, /下一步|上一步|保存草稿并继续|返回(?:故事发动机|风格契约|素材范围|容量约定)/)
  assert.doesNotMatch(wizard, /router\.push|route\.push/)
  await assert.rejects(
    access(file('src/components/project/contract/SeedSelectionStep.vue')),
    error => error?.code === 'ENOENT',
  )
})

test('contract section components contain no residual page-step navigation language', async () => {
  const files = await Promise.all([
    'src/components/project/contract/StoryEngineStep.vue',
    'src/components/project/contract/StyleSelectionStep.vue',
    'src/components/project/contract/AssetScopeStep.vue',
    'src/components/project/contract/CapacityStep.vue',
    'src/components/project/contract/ContractPreviewStep.vue',
  ].map(path => source(path)))
  assert.doesNotMatch(files.join('\n'), /下一步|上一步|保存草稿并继续|返回(?:故事发动机|风格契约|素材范围|容量约定)/)
})

test('document navigation focuses sections and locked sections explain server-owned prerequisites without controls', async () => {
  const wizard = await source('src/components/project/CreationContractWizard.vue')

  assert.match(wizard, /focusOnNavigate|:focus-on-navigate="false"/i)
  assert.match(wizard, /scrollIntoView/)
  assert.match(wizard, /\.focus\?\.\(\{ preventScroll: true \}\)/)
  assert.match(wizard, /section\.open/)
  assert.match(wizard, /section\.blockedReasons/)
  assert.match(wizard, /服务器|服务端/)
  assert.match(wizard, /前置条件|先保存/)
  assert.match(wizard, /writeFields/)
  assert.match(wizard, /:read-only="documentReadOnly \|\| !section\.open[^\"]*section\.blockedReasons\.length/)
})

test('preview confirmation is server-snapshot driven and uses the shared confirmation shell', async () => {
  const [wizard, preview] = await Promise.all([
    source('src/components/project/CreationContractWizard.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
  ])

  assert.match(wizard, /:confirmation="confirmationAdapter"/)
  assert.match(wizard, /contractStore\.serverCanConfirm/)
  assert.match(wizard, /contractStore\.serverReasons/)
  assert.match(wizard, /draftVersion:\s*contractStore\.activeDraftVersion/)
  assert.match(preview, /FoundationConfirmationDialog/)
  assert.match(preview, /preview\.seedRef/)
  assert.match(preview, /preview\.styleRefs/)
  assert.match(preview, /preview\.experienceCardRefs/)
  assert.match(preview, /preview\.corpusSourceRefs/)
  assert.match(preview, /preview\.creationHash/)
  assert.match(preview, /preview\.styleHash/)
  assert.match(preview, /confirmation\.value\.preview/)
  assert.match(preview, /v-if="confirmation\.canConfirm"/)
  assert.match(preview, /ref="confirmErrorRegion"/)
  assert.match(preview, /focusControl\(confirmErrorRegion\.value\)/)
  assert.doesNotMatch(preview, /store\.contractReady\s*\?/)
})

test('manual story engines use named fields without JSON or channel and genre assumptions', async () => {
  const engine = await source('src/components/project/contract/StoryEngineStep.vue')
  for (const label of ['方案名称', '故事承诺', '主角欲望', '持续压力', '成长方向', '冲突循环', '优势与代价', '结局锚点']) {
    assert.match(engine, new RegExp(label))
  }
  assert.doesNotMatch(engine, /manualJson|JSON\.parse|高级手动 JSON|qidian-qq|['"]玄幻['"]/)
  assert.match(engine, /createManualEngineBatch/)
  assert.match(engine, /保存本节/)
})

test('story engine error focus safely targets the Naive UI component root', async () => {
  const engine = await source('src/components/project/contract/StoryEngineStep.vue')
  assert.match(engine, /errorRegion\.value\?\.\$el/)
  assert.match(engine, /target\?\.focus\?\./)
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

test('style and asset recommendations receive the server selection revision context', async () => {
  const files = await Promise.all([
    source('src/components/project/contract/StyleSelectionStep.vue'),
    source('src/components/project/contract/AssetScopeStep.vue'),
  ])
  for (const component of files) {
    assert.match(
      component,
      /loadRecommendations\([\s\S]*?selectionRevision:\s*contractStore\.draft\?\.selectionRevision[\s\S]*?\)/u,
    )
  }
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
  assert.match(capacity, /mode/)
  assert.match(capacity, /保存本节/)
  assert.match(capacity, /aria-live="assertive"/)
  assert.match(preview, /FoundationConfirmationDialog/)
})

test('story engine missing-project capacity fallback uses the long-form default', async () => {
  const component = await source('src/components/project/contract/StoryEngineStep.vue')
  assert.match(component, /projectWords[\s\S]*?2_400_000/u)
  assert.doesNotMatch(component, /projectWords[\s\S]*?:\s*100_000/u)
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
  assert.match(combined, /focusControl/)
  assert.match(combined, /requiresReload/)
  assert.match(combined, /重新加载并核对/)
  assert.doesNotMatch(combined, /删除契约|重置契约|resetContract|deleteContract/)
})

test('history shows immutable pinned revisions as read-only records', async () => {
  const [history, preview] = await Promise.all([
    source('src/components/project/contract/ContractHistoryDrawer.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
  ])
  assert.match(history, /loadHistory/)
  assert.match(history, /pinnedHistoricalRevision/)
  assert.match(history, /supersededReasons/)
  assert.match(history, /selectionRevision/)
  assert.match(history, /历史修订仅供查看与核对/)
  assert.doesNotMatch(history, /cloneRevision|调整未来设计|canClone/)
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

test('wizard treats a revisioned contract head as a permanent baseline despite stale readiness', async () => {
  const invalidHead = {
    hasContract: true,
    contractReady: false,
    reasons: ['selection_revision_changed'],
    revision: 1,
    selectionRevision: 3,
    seedRef: { revisionId: 'seed-revision-a', contentHash: HASH_A },
    creationContract: {
      selectedSeed: {
        title: '雾港错钟',
        logline: '回到雾港的守钟人必须阻止一场被时间掩埋的灾难。',
        genre: '历史悬疑',
      },
    },
    styleRefs: [],
    experienceCardRefs: [],
    corpusSourceRefs: [],
  }
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-1',
    project: {},
    readOnly: false,
  }, store => {
    store.draft = null
    store.head = invalidHead
    store.load = async () => {
      store.draft = null
      store.head = invalidHead
      return { draft: null, head: invalidHead }
    }
    const seedStore = useSeedStore()
    seedStore.activeSelection = {
      projectId: 'project-1',
      selectionRevision: 3,
      seedId: 'seed-a',
      seedRevisionId: 'seed-revision-a',
      seedHash: HASH_A,
      seed: {
        id: 'seed-a',
        revisionId: 'seed-revision-a',
        contentHash: HASH_A,
        revision: 1,
        payload: {
          title: '雾港错钟',
          logline: '回到雾港的守钟人必须阻止一场被时间掩埋的灾难。',
          genre: '历史悬疑',
        },
      },
    }
    seedStore.refresh = async () => ({
      seeds: [seedStore.selectedSeed],
      activeSelection: seedStore.activeSelection,
      readiness: { seedReady: true, contractReady: false, reasons: ['selection_revision_changed'] },
    })
  })

  try {
    await flush()
    const rendered = textContent(mounted.root)
    assert.match(rendered, /已确认，作为项目永久基线/)
    assert.equal(walk(mounted.root).find(node => (
      node.type === 'nav' && node.props['aria-label'] === '创作契约五个步骤'
    )), undefined)
    assert.match(rendered, /雾港错钟/)
    assert.match(rendered, /种子状态已冻结/)
    assert.doesNotMatch(rendered, /seed-revision-a/)
    const buttons = walk(mounted.root).filter(node => node.type === 'button')
    assert.deepEqual(buttons.map(textContent), [
      '故事发动机已签印', '长篇容量已签印', '正式资产范围已签印',
      '风格方案已签印', '禁止方向已签印', '完整预览已签印', '历史修订',
    ])
    assert.doesNotMatch(rendered, /本节等待服务端前置状态|前置条件：/)
    assert.doesNotMatch(rendered, /编辑本节|生成三套方案|运行临时试写|保存本节|核对并签印/)
    assert.equal(walk(mounted.root).some(node => ['input', 'textarea', 'select'].includes(node.type)), false)
  } finally {
    mounted.app.unmount()
  }
})

test('archived superseded head remains visible as the last signed historical contract', async () => {
  const archivedHead = {
    hasContract: true,
    contractReady: false,
    reasons: ['superseded'],
    supersededReasons: ['selection_revision_changed', 'binding_drift'],
    revision: 8,
    seedRef: { revisionId: 'seed-revision-archived', contentHash: HASH_A },
    styleRefs: [{ id: 'style-archived', revision: 3, contentHash: HASH_B }],
    experienceCardRefs: [],
    corpusSourceRefs: [],
    creationContract: { targetWords: 320000 },
    styleContract: { primaryStyleName: '归档风格' },
    likes: [],
    dislikes: [],
  }
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-archived',
    project: { status: 'archived' },
    readOnly: true,
  }, store => {
    store.draft = null
    store.head = archivedHead
    store.load = async () => {
      store.draft = null
      store.head = archivedHead
      return { draft: null, head: archivedHead }
    }
    const seedStore = useSeedStore()
    seedStore.activeSelection = {
      projectId: 'project-archived',
      selectionRevision: 9,
      seedId: 'seed-archived',
      seedRevisionId: 'seed-revision-archived',
      seedHash: HASH_A,
      seed: {
        id: 'seed-archived', revisionId: 'seed-revision-archived', contentHash: HASH_A,
        title: '归档种子', logline: '已归档项目的最后签印仍应可核对。', revision: 2, genre: '悬疑',
      },
    }
    seedStore.refresh = async () => ({
      seeds: [seedStore.selectedSeed],
      activeSelection: seedStore.activeSelection,
      readiness: {
        seedReady: true,
        contractReady: false,
        reasons: archivedHead.reasons,
      },
    })
  })

  try {
    await flush()
    const rendered = textContent(mounted.root)
    assert.match(rendered, /最后签印的历史契约/)
    assert.match(rendered, /永久基线 · 第 8 版/)
    assert.match(rendered, /种子选择代次已改变/)
    assert.match(rendered, /模型绑定已改变/)
    assert.doesNotMatch(rendered, /当前生效的创作契约|归档时尚未签印创作契约/)
    assert.equal(walk(mounted.root).some(node => (
      node.type === 'nav' && node.props['aria-label'] === '创作契约五个步骤'
    )), false)
    assert.ok(findByText(mounted.root, 'button', '历史修订'))
    assert.equal(walk(mounted.root).some(node => ['input', 'textarea', 'select'].includes(node.type)), false)
  } finally {
    mounted.app.unmount()
  }
})

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
    await trigger(findByText(mounted.root, 'button', '保存本节'), 'onClick')

    assert.equal(saveCalls, 0)
    assert.match(textContent(mounted.root), /渠道定位标识和题材定位标识均不能为空。/)
    assert.ok(naiveBehaviorModule.focusEvents.includes('NAlert.$el'))
  } finally {
    mounted.app.unmount()
  }
})

test('story engine trims and saves custom profile identifiers without mapping or fabrication', async () => {
  const calls = []
  const mounted = mountWithPinia(StoryEngineStep, {
    projectId: 'project-1',
    project: { channelProfileKey: 'initial-channel' },
    selectedSeed: { payload: { title: '种子', genre: 'initial-genre' } },
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
    await trigger(findByText(mounted.root, 'button', '保存本节'), 'onClick')

    assert.equal(calls.length, 1)
    assert.equal(calls[0].projectId, 'project-1')
    assert.equal(calls[0].payload.channelProfileKey, 'custom-channel')
    assert.equal(calls[0].payload.genreProfileKey, '自定义题材标识')
    assert.equal(JSON.stringify(calls[0]).includes('unspecified'), false)
  } finally {
    mounted.app.unmount()
  }
})

test('history drawer renders every pinned identity and fragment as read-only', async () => {
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
      styleRefs: [], experienceCardRefs: [], corpusSourceRefs: [],
      supersededReasons: ['selection_revision_changed'],
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
    assert.match(rendered, /种子选择代次已改变/)
    assert.doesNotMatch(rendered, /selection_revision_changed/)
    assert.match(rendered, /历史修订仅供查看与核对/)
    assert.equal(walk(mounted.root).some(node => textContent(node).trim() === '调整未来设计'), false)
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

test('reusable decision summary renders every formal author decision while translating internal profile metadata', async () => {
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
      '女性成长频道', '架空悬疑', '已冻结', '钟摆发动机',
      '保住妹妹的真实姓名', '追查—交换—反噬—重新结盟', '1,260,000', '2,800', '3,400',
      '人物选择必须优先于设定解释。', '限知近距离', '动作六成，解释二成，环境二成',
      '每场戏必须有不可逆变化', '留白过多导致信息不足', '对话中的关系位移', '用脸色发白代替情绪',
      '雾港拾灯人', '潮汐奇谭', '她必须在黎明前找回失踪档案。', '拾灯人林缈',
      '让被抹去的人重获姓名', '公布真相会让港城提前沉没',
      '每次涨潮都会抹去一段公共记忆', '一盏本该熄灭的灯叫出了她的名字',
      '用潮汐线与档案缺页双重记录遗忘',
    ]) assert.ok(rendered.includes(value), `missing decision value: ${value}`)
    assert.doesNotMatch(rendered, /质量章程-2026/)
  } finally {
    mounted.app.unmount()
  }
})

test('Contract confirmation adapter supplies the exact server snapshot, CAS tuple, and capability to the shared confirmation flow', async () => {
  const adapterPreview = {
    projectId: 'project-1', draftVersion: 41, baseHeadRevision: 7, expectedRevision: 8,
    selectionRevision: 12, contractReady: true, reasons: ['opaque_contract_reason'],
    seedRef: { name: '适配器种子', revisionId: 'adapter-seed-revision', contentHash: '1'.repeat(64) },
    engineRef: { name: '适配器发动机', batchId: 'adapter-engine-batch', contentHash: '2'.repeat(64) },
    bindingRef: { revision: 6, contentHash: '3'.repeat(64), items: [] },
    styleRefs: [{ id: 'adapter-style-id', name: '适配器风格', revision: 3, contentHash: '4'.repeat(64) }],
    experienceCardRefs: [], corpusSourceRefs: [], creationHash: '5'.repeat(64), styleHash: '6'.repeat(64),
  }
  const confirmation = {
    preview: adapterPreview, draftVersion: 41, contentHash: '7'.repeat(64), canConfirm: true,
  }
  const mounted = mountWithPinia(ContractPreviewStep, {
    projectId: 'project-1', confirmation, interactionLocked: false,
  }, store => {
    store.draft = { ...store.draft, draftVersion: 3, contentHash: HASH_A }
    store.previewResult = {
      ...adapterPreview, draftVersion: 3,
      seedRef: { name: '错误的 Store 种子', revisionId: 'store-seed-revision', contentHash: HASH_A },
      styleRefs: [{ id: 'store-style-id', name: '错误的 Store 风格', revision: 1, contentHash: HASH_A }],
    }
    store.preview = async () => { throw new Error('匹配的 adapter 不应重新请求预览') }
  })

  try {
    await flush()
    const mainDiagnostics = walk(mounted.root).find(node => node.type === 'details' && textContent(node).includes('来源与诊断'))
    const mainText = textExcluding(mounted.root, mainDiagnostics)
    assert.match(mainText, /适配器风格/)
    assert.match(mainText, /状态需要重新核对/)
    assert.doesNotMatch(mainText, /错误的 Store 风格|opaque_contract_reason/)
    assert.match(textContent(mainDiagnostics), /诊断代码opaque_contract_reason/)
    await trigger(findByText(mounted.root, 'button', '核对并签印完整契约'), 'onClick')
    const dialog = walk(teleportTarget).find(node => node.props.role === 'dialog')
    assert.ok(dialog)
    assert.match(textContent(dialog), /草稿版本41/)
    assert.match(textContent(dialog), /服务器确认能力允许签印/)
  } finally {
    mounted.app.unmount()
    teleportTarget.children.splice(0)
  }
})

test('Contract preview translates only real binding and corpus enums and fails closed for unknown values', async () => {
  const preview = {
    projectId: 'project-1', draftVersion: 5, contractReady: false, reasons: [],
    seedRef: { name: '枚举核对种子' }, engineRef: { name: '枚举核对发动机' },
    bindingRef: { revision: 2, contentHash: HASH_A, items: [
      { taskKey: 'planning', providerNameSnapshot: '规划模型', modelNameSnapshot: 'model-a', resolutionStatus: 'bound' },
      { taskKey: 'writing', providerNameSnapshot: '', modelNameSnapshot: '', resolutionStatus: 'unbound' },
      { taskKey: 'audit', providerNameSnapshot: '审核模型', modelNameSnapshot: 'model-b', resolutionStatus: 'future_binding_state' },
    ] },
    styleRefs: [], experienceCardRefs: [], corpusSourceRefs: [
      { id: 'author-source', name: '作者自选语料', revision: 2, contentHash: HASH_A, selectionMode: 'author', fragments: [] },
      { id: 'system-source', name: '系统推荐语料', revision: 3, contentHash: HASH_A, selectionMode: 'system', fragments: [] },
      { id: 'unknown-source', name: '未知来源语料', revision: 4, contentHash: HASH_A, selectionMode: 'future_selection_mode', fragments: [] },
    ],
  }
  const mounted = mountWithPinia(ContractPreviewStep, {
    projectId: 'project-1', confirmation: { preview, draftVersion: 5, contentHash: HASH_A, canConfirm: false },
  })

  try {
    await flush()
    const diagnostics = walk(mounted.root).find(node => node.type === 'details' && textContent(node).includes('来源与诊断'))
    const publicText = textExcluding(mounted.root, diagnostics)
    for (const label of ['已绑定', '未绑定', '作者选择', '系统推荐', '状态待核对', '引用方式待核对']) {
      assert.match(publicText, new RegExp(label), `missing enum presentation: ${label}`)
    }
    for (const raw of ['bound', 'unbound', 'author', 'system', 'future_binding_state', 'future_selection_mode']) {
      assert.doesNotMatch(publicText, new RegExp(raw), `raw enum escaped diagnostics: ${raw}`)
    }
    assert.ok(walk(mounted.root).find(node => node.props.type === 'success' && textContent(node).includes('已绑定')))
    assert.ok(walk(mounted.root).find(node => node.props.type === 'warning' && textContent(node).includes('未绑定')))
    assert.ok(walk(mounted.root).find(node => node.props.type === 'warning' && textContent(node).includes('状态待核对')))
    assert.match(textContent(diagnostics), /future_binding_state|future_selection_mode/)
  } finally {
    mounted.app.unmount()
  }
})

test('successful Contract confirmation immediately replaces the editable workspace with the authoritative read-only head', async () => {
  const decisions = completeDecisionPayload()
  const draft = {
    id: 'draft-confirm-success', projectId: 'project-1', draftVersion: 9, draftStage: 'assets',
    contentHash: HASH_A, baseHeadRevision: 0,
    draft: {
      ...decisions.creationContract, draftStage: 'assets', engineOptionId: 'engine-1', engineHash: HASH_A,
      primaryStyleRef: null, secondaryStyleRef: null, experienceCardRefs: [], corpusSourceRefs: [],
      likes: decisions.likes, dislikes: decisions.dislikes,
    },
  }
  const preview = {
    projectId: 'project-1', draftVersion: 9, baseHeadRevision: 0, expectedRevision: 1,
    selectionRevision: 4, contractReady: true, reasons: [],
    seedRef: { name: '雾港拾灯人', revisionId: 'seed-confirm-success', contentHash: HASH_A },
    engineRef: { name: '钟摆发动机', batchId: 'engine-confirm-success', contentHash: HASH_A },
    bindingRef: { revision: 4, contentHash: HASH_B, items: [] },
    styleRefs: [], experienceCardRefs: [], corpusSourceRefs: [], ...decisions,
    creationHash: HASH_A, styleHash: HASH_B,
  }
  const head = { ...preview, revision: 1, hasContract: true }
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-1', project: {}, readOnly: false,
  }, store => {
    store.draft = draft
    store.head = { projectId: 'project-1', revision: 0, hasContract: false, contractReady: false, reasons: ['contract_missing'] }
    store.load = async () => ({ draft: store.draft, head: store.head })
    store.preview = async () => { store.previewResult = preview; return preview }
    store.confirm = async () => {
      store.head = head; store.confirmed = head; store.draft = null; store.previewResult = null
      return head
    }
    const seedStore = useSeedStore()
    seedStore.activeSelection = {
      projectId: 'project-1', selectionRevision: 4, seedId: 'seed-a',
      seedRevisionId: 'seed-confirm-success', seedHash: HASH_A,
      seed: { id: 'seed-a', revisionId: 'seed-confirm-success', contentHash: HASH_A, revision: 2,
        payload: decisions.creationContract.selectedSeed },
    }
    seedStore.refresh = async () => ({ activeSelection: seedStore.activeSelection })
  })

  try {
    await flush()
    const previewDirectoryItem = walk(mounted.root).find(node => node.type === 'button' && textContent(node).includes('完整预览'))
    await trigger(previewDirectoryItem, 'onClick')
    await flush()
    await trigger(findByText(mounted.root, 'button', '核对并签印完整契约'), 'onClick')
    const dialog = walk(teleportTarget).find(node => node.props.role === 'dialog')
    await trigger(findByText(dialog, 'button', '一次确认完整契约'), 'onClick')
    await flush()

    assert.match(textContent(mounted.root), /已确认，作为项目永久基线/)
    assert.equal(walk(teleportTarget).some(node => node.props.role === 'dialog'), false)
    for (const label of [
      '编辑本节', '保存本节', '生成三套方案', '运行临时试写',
      '核对并签印完整契约', '一次确认完整契约', '重新加载并核对',
    ]) assert.equal(findByText(mounted.root, 'button', label), undefined, `write control remained: ${label}`)
    assert.equal(walk(mounted.root).some(node => ['input', 'textarea', 'select'].includes(node.type)), false)
  } finally {
    mounted.app.unmount()
    teleportTarget.children.splice(0)
  }
})

test('loaded document reads substantive author decisions and top capacity without opening editors', async () => {
  const decisions = completeDecisionPayload()
  let previewCalls = 0
  const draft = {
    id: 'draft-readable', projectId: 'project-1', draftVersion: 6, draftStage: 'assets',
    contentHash: HASH_A, baseHeadRevision: 0,
    draft: {
      ...decisions.creationContract,
      draftStage: 'assets', engineOptionId: 'engine-readable', engineHash: HASH_A,
      primaryStyleRef: { id: 'style-primary', name: '克制潮汐体', revision: 4, contentHash: HASH_B },
      secondaryStyleRef: { id: 'style-secondary', name: '档案残页体', revision: 2, contentHash: HASH_A },
      experienceCardRefs: [{ id: 'card-memory-cost', name: '记忆代价卡', revision: 3, contentHash: HASH_A }],
      corpusSourceRefs: [{
        id: 'corpus-tide', name: '潮汐档案语料', revision: 5, contentHash: HASH_B,
        selectionMode: 'author',
        fragments: [{ chapterId: 'chapter-2', fragmentId: 'tide-frag', chapterCharStart: 12, chapterCharEnd: 38, referenceUse: 'fact_check' }],
      }],
      likes: decisions.likes, dislikes: decisions.dislikes,
    },
  }
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-1', project: {}, readOnly: false,
  }, store => {
    store.draft = draft
    store.head = { projectId: 'project-1', revision: 0, hasContract: false, contractReady: false, reasons: ['contract_missing'] }
    store.engineBatch = null
    store.load = async () => ({ draft: store.draft, head: store.head, recovery: { items: [] } })
    store.preview = async () => {
      previewCalls += 1
      const result = {
        projectId: 'project-1', selectionRevision: 4, draftVersion: 6,
        baseHeadRevision: 0, expectedRevision: 1, contractReady: true, reasons: [],
        seedRef: { id: 'seed-a', revisionId: 'seed-revision-a', contentHash: HASH_A },
        engineRef: { id: 'engine-readable', batchId: 'batch-readable', contentHash: HASH_A },
        bindingRef: { id: 'binding-1', revision: 2, contentHash: HASH_B, items: [] },
        styleRefs: store.draft.draft.primaryStyleRef ? [store.draft.draft.primaryStyleRef] : [],
        experienceCardRefs: store.draft.draft.experienceCardRefs,
        corpusSourceRefs: store.draft.draft.corpusSourceRefs,
        ...decisions,
        creationHash: HASH_A, styleHash: HASH_B,
      }
      store.previewResult = result
      return result
    }
    const seedStore = useSeedStore()
    seedStore.activeSelection = {
      projectId: 'project-1', selectionRevision: 4, seedId: 'seed-a',
      seedRevisionId: 'seed-revision-a', seedHash: HASH_A,
      seed: { id: 'seed-a', revisionId: 'seed-revision-a', contentHash: HASH_A, revision: 2,
        payload: decisions.creationContract.selectedSeed },
    }
    seedStore.refresh = async () => ({ activeSelection: seedStore.activeSelection })
  })

  try {
    await flush()
    assert.equal(previewCalls, 1)
    const rendered = textContent(mounted.root)
    for (const value of [
      '钟摆发动机', '每次破案都会失去一段记忆。', '克制潮汐体', '档案残页体',
      '对话中的关系位移', '记忆代价卡', '潮汐档案语料', '位置 12–38 · 已配置（详情见来源与诊断）',
      '1,260,000', '7 卷', '420 章', '2,800 ～ 3,400',
      '禁止无代价升级', '人物选择必须优先于设定解释。',
    ]) assert.ok(rendered.includes(value), `missing immediate document substance: ${value}`)
  } finally {
    mounted.app.unmount()
  }
})

test('cold Engine and Style drafts render only the server document projection', async () => {
  const cases = [
    {
      stage: 'engine',
      draftFields: {
        primaryStyleRef: null, secondaryStyleRef: null,
        likes: null, dislikes: null, experienceCardRefs: null, corpusSourceRefs: null,
      },
      projection: {
        selectedEngine: {
          name: '冷启动钟摆发动机',
          storyPromise: '每次核对档案都要放弃一种确定性。',
          sustainedPressure: '真相与城市一起下沉',
          conflictLoop: '核对—取舍—失真—再核对',
          advantageAndCost: '看见删改，代价是失去亲历记忆',
        },
        primaryStyle: null,
        secondaryStyle: null,
        unavailableReasons: [],
      },
      visible: ['冷启动钟摆发动机', '每次核对档案都要放弃一种确定性。'],
    },
    {
      stage: 'style',
      draftFields: {
        primaryStyleRef: { id: 'style-exact', revision: 2, contentHash: HASH_B },
        secondaryStyleRef: null, likes: ['克制'], dislikes: ['喊口号'],
        experienceCardRefs: null, corpusSourceRefs: null,
      },
      projection: {
        selectedEngine: engineOption().payload,
        primaryStyle: {
          id: 'style-exact', revision: 2, contentHash: HASH_B, name: '克制现实',
          readingExperience: '冷静但不冷漠', narrativeDistance: '近距离第三人称',
          sentenceParagraphRhythm: '行动短促，余波舒展',
        },
        secondaryStyle: null,
        unavailableReasons: [],
      },
      visible: ['克制现实', 'R2', '冷静但不冷漠', '近距离第三人称'],
    },
  ]

  for (const scenario of cases) {
    const mounted = mountWithPinia(CreationContractWizard, {
      projectId: 'project-1', project: {}, readOnly: false,
    }, store => {
      store.engineBatch = null
      store.draft = {
        id: 'draft-cold', projectId: 'project-1', draftVersion: 3,
        draftStage: scenario.stage, contentHash: HASH_A, baseHeadRevision: 0,
        documentProjection: scenario.projection,
        draft: {
          schemaVersion: 'contract-draft-v2', draftStage: scenario.stage,
          engineOptionId: 'engine-1', engineHash: HASH_A,
          channelProfileKey: 'serial', genreProfileKey: 'mystery',
          qualityCharterVersion: 'quality-v1', targetTotalWords: 900000,
          expectedVolumeCount: 6, expectedChapterCount: 300,
          chapterWordRangePreference: [2800, 3200], prohibitedDirections: [],
          authorNotes: '冷启动读取', ...scenario.draftFields,
        },
      }
      store.head = { projectId: 'project-1', revision: 0, hasContract: false, reasons: ['contract_missing'] }
      store.load = async () => ({ draft: store.draft, head: store.head, recovery: { items: [] } })
      const seedStore = useSeedStore()
      seedStore.activeSelection = {
        projectId: 'project-1', selectionRevision: 3, seedId: 'seed-a',
        seedRevisionId: 'seed-r3', seedHash: HASH_A,
        seed: { payload: { title: '冷启动种子', genre: '悬疑', logline: '读取服务器冻结决定。' } },
      }
      seedStore.refresh = async () => ({ activeSelection: seedStore.activeSelection })
    })
    try {
      await flush()
      const rendered = textContent(mounted.root)
      for (const value of scenario.visible) {
        assert.ok(rendered.includes(value), `${scenario.stage} missing server projection: ${value}`)
      }
    } finally {
      mounted.app.unmount()
    }
  }
})

test('cold draft identity mismatch never falls back to stale author content', async () => {
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-1', project: {}, readOnly: false,
  }, store => {
    store.engineBatch = {
      id: 'stale-local-batch', status: 'succeeded', options: [{
        id: 'engine-1', contentHash: HASH_A,
        payload: { name: '过期发动机内容', storyPromise: '不得显示的本地缓存' },
      }],
    }
    store.draft = {
      id: 'draft-drift', projectId: 'project-1', draftVersion: 3,
      draftStage: 'style', contentHash: HASH_A, baseHeadRevision: 0,
      documentProjection: {
        selectedEngine: null, primaryStyle: null, secondaryStyle: null,
        unavailableReasons: ['engine_identity_unavailable', 'primary_style_identity_unavailable'],
      },
      draft: {
        schemaVersion: 'contract-draft-v2', draftStage: 'style',
        engineOptionId: 'engine-1', engineHash: HASH_A,
        channelProfileKey: 'serial', genreProfileKey: 'mystery', qualityCharterVersion: 'quality-v1',
        targetTotalWords: 900000, expectedVolumeCount: 6, expectedChapterCount: 300,
        chapterWordRangePreference: [2800, 3200], prohibitedDirections: [], authorNotes: '',
        primaryStyleRef: { id: 'style-exact', revision: 2, contentHash: HASH_B },
        secondaryStyleRef: null, likes: [], dislikes: [],
        experienceCardRefs: null, corpusSourceRefs: null,
      },
    }
    store.head = { projectId: 'project-1', revision: 0, hasContract: false, reasons: ['contract_missing'] }
    store.load = async () => ({ draft: store.draft, head: store.head, recovery: { items: [] } })
    const seedStore = useSeedStore()
    seedStore.activeSelection = { selectionRevision: 3, seed: { payload: { title: '种子', genre: '悬疑' } } }
    seedStore.refresh = async () => ({ activeSelection: seedStore.activeSelection })
  })
  try {
    await flush()
    const rendered = textContent(mounted.root)
    assert.doesNotMatch(rendered, /过期发动机内容|过期风格名称/)
    assert.doesNotMatch(rendered, /engine-1|style-exact/)
    assert.match(rendered, /已选择故事发动机/)
    assert.match(rendered, /已冻结引用/)
  } finally {
    mounted.app.unmount()
  }
})

test('workspace locks active controls without dropping local values while reload awaits keep or discard', async () => {
  const interactionLocked = VueRuntime.ref(false)
  const mounted = mountWithPinia(StoryEngineStep, () => ({
    projectId: 'project-1', project: {}, selectedSeed: { payload: { title: '种子', genre: '幻想' } },
    interactionLocked: interactionLocked.value,
  }))
  try {
    await flush()
    const channel = inputForLabel(mounted.root, '渠道定位标识')
    await trigger(channel, 'onInput', { target: { value: '作者尚未保存的渠道' } })
    interactionLocked.value = true
    await flush()
    assert.equal(channel.props.value, '作者尚未保存的渠道')
    const editor = walk(mounted.root).find(node => node.type === 'section' && node.props['aria-labelledby'] === 'engine-step-heading')
    assert.equal(editor.props.inert, '')
    assert.equal(editor.props['aria-disabled'], 'true')
    const sourceText = await source('src/components/project/CreationContractWizard.vue')
    assert.match(sourceText, /FoundationConfirmationDialog/)
    assert.match(sourceText, /requestAuthoritativeReload/)
    assert.match(sourceText, /contractStore\.hasUnsavedChanges/)
    assert.match(sourceText, /保留本地修改/)
    assert.match(sourceText, /放弃并重新加载/)
  } finally {
    mounted.app.unmount()
  }
})

test('save conflict locks the whole document and requires keep or discard before authoritative reload', async () => {
  teleportTarget.children.splice(0)
  let loadCalls = 0
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-1', project: {}, readOnly: false,
  }, store => {
    store.draft = {
      ...store.draft,
      selectionRevision: 3,
      draftStage: 'engine',
      draft: {
        ...store.draft.draft,
        draftStage: 'engine', channelProfileKey: '原渠道', genreProfileKey: '原题材',
      },
    }
    store.head = { projectId: 'project-1', revision: 0, hasContract: false, reasons: ['contract_missing'] }
    store.load = async () => {
      loadCalls += 1
      if (loadCalls > 1) store.requiresReload = false
      return { draft: store.draft, head: store.head, recovery: { items: [] } }
    }
    store.saveDraft = async () => {
      store.requiresReload = true
      store.conflict = { code: 'ContractConflict' }
      throw new Error('服务器版本已经变化')
    }
    const seedStore = useSeedStore()
    seedStore.activeSelection = {
      projectId: 'project-1', selectionRevision: 3, seedId: 'seed-a',
      seedRevisionId: 'seed-r3', seedHash: HASH_A,
      seed: { id: 'seed-a', revisionId: 'seed-r3', contentHash: HASH_A, revision: 3,
        payload: { title: '冲突测试种子', logline: '保留作者本地输入。', genre: '悬疑' } },
    }
    seedStore.refresh = async () => ({ activeSelection: seedStore.activeSelection })
  })

  try {
    await flush()
    await trigger(findByText(mounted.root, 'button', '编辑本节'), 'onClick')
    const channel = inputForLabel(mounted.root, '渠道定位标识')
    await trigger(channel, 'onInput', { target: { value: '尚未保存的作者渠道' } })
    await trigger(findByText(mounted.root, 'button', '保存本节'), 'onClick')

    assert.equal(channel.props.value, '尚未保存的作者渠道')
    const engine = walk(mounted.root).find(node => node.props['aria-labelledby'] === 'engine-step-heading')
    assert.equal(engine.props.inert, '')
    for (const button of walk(mounted.root).filter(node => node.type === 'button' && textContent(node).trim() === '编辑本节')) {
      assert.equal(button.props.disabled, true)
    }

    await trigger(findByText(mounted.root, 'button', '重新加载并核对'), 'onClick')
    let dialog = walk(teleportTarget).find(node => node.props.role === 'dialog')
    assert.ok(dialog)
    await trigger(findByText(dialog, 'button', '保留本地修改'), 'onClick')
    assert.equal(channel.props.value, '尚未保存的作者渠道')
    assert.equal(loadCalls, 1)
    assert.equal(mounted.store.requiresReload, true)

    await trigger(findByText(mounted.root, 'button', '重新加载并核对'), 'onClick')
    dialog = walk(teleportTarget).find(node => node.props.role === 'dialog')
    await trigger(findByText(dialog, 'button', '放弃并重新加载'), 'onClick')
    assert.equal(loadCalls, 2)
    assert.equal(mounted.store.requiresReload, false)
    assert.equal(mounted.store.hasUnsavedChanges, false)
  } finally {
    mounted.app.unmount()
    teleportTarget.children.splice(0)
  }
})

test('real alert exposes Capacity conflict recovery without replacing dirty input', async () => {
  teleportTarget.children.splice(0)
  let loadCalls = 0
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-1', project: {}, readOnly: false,
  }, store => {
    const draft = {
      ...store.draft,
      selectionRevision: 3,
      draftStage: 'assets',
      draft: {
        ...store.draft.draft,
        draftStage: 'assets',
        channelProfileKey: 'serial', genreProfileKey: 'mystery',
        targetTotalWords: 900000, expectedVolumeCount: 6, expectedChapterCount: 300,
        chapterWordRangePreference: [2800, 3200], prohibitedDirections: [], authorNotes: '',
        primaryStyleRef: { id: 'style-1', revision: 2, contentHash: HASH_B },
        secondaryStyleRef: null, likes: [], dislikes: [],
        experienceCardRefs: [], corpusSourceRefs: [],
      },
    }
    store.draft = draft
    store.head = { projectId: 'project-1', revision: 0, hasContract: false, reasons: ['contract_missing'] }
    store.load = async () => {
      loadCalls += 1
      if (loadCalls > 1) {
        store.draft = {
          ...draft,
          draft: { ...draft.draft, targetTotalWords: 800000 },
        }
        store.requiresReload = false
      }
      return { draft: store.draft, head: store.head, recovery: { items: [] } }
    }
    store.preview = async () => ({ contractReady: false, reasons: ['not_ready'] })
    store.saveDraft = async () => {
      store.requiresReload = true
      store.conflict = { code: 'ContractConflict' }
      throw new Error('服务器版本已经变化')
    }
    const seedStore = useSeedStore()
    seedStore.activeSelection = {
      projectId: 'project-1', selectionRevision: 3, seedId: 'seed-a',
      seedRevisionId: 'seed-r3', seedHash: HASH_A,
      seed: { payload: { title: '冲突测试种子', genre: '悬疑', logline: '保留容量输入。' } },
    }
    seedStore.refresh = async () => ({ activeSelection: seedStore.activeSelection })
  })

  try {
    await flush()
    await trigger(findByText(mounted.root, 'button', '长篇容量已记录'), 'onClick')
    const targetWords = inputForLabel(mounted.root, '目标总字数')
    await trigger(targetWords, 'onInput', { target: { value: '910000' } })
    await trigger(findByText(mounted.root, 'button', '保存本节'), 'onClick')

    assert.equal(targetWords.props.value, 910000)
    assert.equal(mounted.store.requiresReload, true)
    const recovery = findByText(mounted.root, 'button', '重新加载并核对')
    assert.ok(recovery, 'recovery action must be in NAlert default content')
    assert.notEqual(recovery.props.disabled, true)
    const directory = walk(mounted.root).find(node => (
      node.type === 'nav' && node.props['aria-label'] === '文档章节'
    ))
    const directoryButtons = walk(directory).filter(node => node.type === 'button')
    assert.equal(directoryButtons.length, 6)
    for (const button of directoryButtons) assert.equal(button.props.disabled, true)
    for (const button of walk(mounted.root).filter(node => (
      node.type === 'button' && textContent(node).trim() === '编辑本节'
    ))) assert.equal(button.props.disabled, true)

    await trigger(recovery, 'onClick')
    let dialog = walk(teleportTarget).find(node => node.props.role === 'dialog')
    await trigger(findByText(dialog, 'button', '保留本地修改'), 'onClick')
    assert.equal(targetWords.props.value, 910000)
    assert.equal(loadCalls, 1)

    await trigger(findByText(mounted.root, 'button', '重新加载并核对'), 'onClick')
    dialog = walk(teleportTarget).find(node => node.props.role === 'dialog')
    await trigger(findByText(dialog, 'button', '放弃并重新加载'), 'onClick')
    assert.equal(loadCalls, 2)
    assert.equal(mounted.store.requiresReload, false)
  } finally {
    mounted.app.unmount()
    teleportTarget.children.splice(0)
  }
})

test('confirmation conflict closes its stale dialog and locks every later confirmation attempt', async () => {
  teleportTarget.children.splice(0)
  let confirmCalls = 0
  let contractStore
  const mounted = mountWithPinia(ContractPreviewStep, () => ({
    projectId: 'project-1', confirmation: {
      preview: contractStore.previewResult,
      draftVersion: contractStore.draft?.draftVersion,
      contentHash: contractStore.draft?.contentHash,
      canConfirm: true,
    },
    interactionLocked: contractStore.requiresReload,
  }), store => {
    contractStore = store
    store.draft = { ...store.draft, draftVersion: 3, contentHash: HASH_A, baseHeadRevision: 0 }
    const result = {
      projectId: 'project-1', selectionRevision: 3, draftVersion: 3,
      baseHeadRevision: 0, expectedRevision: 1, contractReady: true, reasons: [],
      seedRef: { id: 'seed-a', revisionId: 'seed-r3', contentHash: HASH_A },
      engineRef: { id: 'engine-1', batchId: 'batch-1', contentHash: HASH_A },
      bindingRef: { revision: 2, contentHash: HASH_B, items: [] },
      styleRefs: [], experienceCardRefs: [], corpusSourceRefs: [],
      creationHash: HASH_A, styleHash: HASH_B,
    }
    store.preview = async () => { store.previewResult = result; return result }
    store.confirm = async () => {
      confirmCalls += 1
      store.requiresReload = true
      throw new Error('服务器版本已经变化')
    }
  })

  try {
    await flush()
    const mainDiagnostics = walk(mounted.root).find(node => node.type === 'details' && textContent(node).includes('来源与诊断'))
    const mainText = textExcluding(mounted.root, mainDiagnostics)
    for (const internal of [
      'seed-exact', 'seed-revision-8', 'batch-exact', 'binding-1', 'provider-1', 'planning', 'ready',
      'corpus-r5', 'fragment-9', 'fact_check', '9'.repeat(64), HASH_A,
    ]) assert.doesNotMatch(mainText, new RegExp(internal), `internal value escaped main preview diagnostics: ${internal}`)
    await trigger(findByText(mounted.root, 'button', '核对并签印完整契约'), 'onClick')
    const dialog = walk(teleportTarget).find(node => node.props.role === 'dialog')
    await trigger(findByText(dialog, 'button', '一次确认完整契约'), 'onClick')
    assert.equal(confirmCalls, 1)
    assert.equal(walk(teleportTarget).some(node => node.props.role === 'dialog'), false)
    const previewRoot = walk(mounted.root).find(node => node.type === 'article' && node.props.class === 'preview-step')
    assert.equal(previewRoot.props.inert, '')
    assert.equal(findByText(mounted.root, 'button', '核对并签印完整契约').props.disabled, true)
    assert.equal(confirmCalls, 1)
  } finally {
    mounted.app.unmount()
    teleportTarget.children.splice(0)
  }
})

test('confirmation dialog consumes its adapter and keeps command shape outside the shared dialog', async () => {
  const wizard = await source('src/components/project/CreationContractWizard.vue')
  const preview = await source('src/components/project/contract/ContractPreviewStep.vue')
  const dialog = preview.slice(
    preview.indexOf('<FoundationConfirmationDialog'),
    preview.indexOf('</FoundationConfirmationDialog>'),
  )
  assert.match(wizard, /:confirmation="confirmationAdapter"/)
  for (const evidence of ['confirmation.value.preview', 'confirmation.draftVersion', 'confirmation.contentHash', 'confirmation.canConfirm']) {
    assert.ok(preview.includes(evidence), `missing adapter evidence: ${evidence}`)
  }
  assert.doesNotMatch(dialog, /store\.draft|store\.previewResult/)
})

test('opened confirmation presents author semantics and confines internal provenance to expandable diagnostics', async () => {
  const decisions = completeDecisionPayload()
  decisions.creationContract.channelProfileKey = 'serial'
  decisions.creationContract.genreProfileKey = 'mystery'
  decisions.creationContract.qualityCharterVersion = 'quality-v1'
  teleportTarget.children.splice(0)
  const exactPreview = {
    projectId: 'project-1', selectionRevision: 8, draftVersion: 11,
    baseHeadRevision: 4, expectedRevision: 5, contractReady: true, reasons: [],
    seedRef: { id: 'seed-exact', revisionId: 'seed-revision-8', contentHash: '1'.repeat(64) },
    engineRef: { id: 'engine-exact', batchId: 'batch-exact', contentHash: '2'.repeat(64) },
    bindingRef: {
      id: 'binding-1', revision: 6, contentHash: '3'.repeat(64),
      items: [
        { taskKey: 'planning', providerId: 'provider-1', providerNameSnapshot: '作者模型', modelNameSnapshot: 'novel-model', resolutionStatus: 'bound' },
        { taskKey: 'writing', providerId: null, providerNameSnapshot: '', modelNameSnapshot: '', resolutionStatus: 'unbound' },
      ],
    },
    styleRefs: [{ id: 'style-exact', name: '潮汐留白体', revision: 2, contentHash: '4'.repeat(64) }],
    experienceCardRefs: [{ id: 'card-exact', name: '记忆代价卡', revision: 3, contentHash: '5'.repeat(64) }],
    corpusSourceRefs: [{
      id: 'corpus-exact', name: '雾港档案', revisionId: 'corpus-r5', revision: 5,
      selectionMode: 'author', pinnedHistoricalRevision: false, contentHash: '6'.repeat(64),
      fragments: [{ chapterId: 'chapter-4', fragmentId: 'fragment-9', fragmentHash: '9'.repeat(64), chapterCharStart: 12, chapterCharEnd: 38, referenceUse: 'fact_check' }],
    }],
    ...decisions,
    creationHash: '7'.repeat(64), styleHash: '8'.repeat(64),
  }
  const mounted = mountWithPinia(ContractPreviewStep, {
    projectId: 'project-1', confirmation: {
      preview: exactPreview, draftVersion: 11, contentHash: HASH_A, canConfirm: true,
    }, interactionLocked: false,
  }, store => {
    store.draft = {
      ...store.draft, draftVersion: 11, baseHeadRevision: 4,
      selectionRevision: 8, contentHash: HASH_A,
    }
    store.preview = async () => { store.previewResult = exactPreview; return exactPreview }
  })

  try {
    await flush()
    await trigger(findByText(mounted.root, 'button', '核对并签印完整契约'), 'onClick')
    const dialog = walk(teleportTarget).find(node => node.props.role === 'dialog')
    assert.ok(dialog, 'shared confirmation dialog should be mounted')
    const diagnostics = walk(dialog).find(node => node.type === 'details' && textContent(node).includes('来源与诊断'))
    assert.ok(diagnostics, 'internal provenance should be contained in expandable diagnostics')
    const publicText = textExcluding(dialog, diagnostics)
    const rendered = textContent(diagnostics)
    for (const value of [
      '种子修订标识seed-revision-8', '发动机批次标识batch-exact',
      '模型提供方标识provider-1', '任务代码planning', '状态代码bound',
      `草稿内容校验值${HASH_A}`,
    ]) assert.ok(rendered.includes(value), `missing diagnostic evidence: ${value}`)
    for (const internal of [
      'seed-exact', 'seed-revision-8', 'batch-exact', 'binding-1', 'provider-1', 'planning', 'bound', 'unbound',
      'corpus-r5', 'fragment-9', 'fact_check', 'serial', 'mystery', 'quality-v1', '9'.repeat(64), HASH_A,
    ]) assert.doesNotMatch(publicText, new RegExp(internal), `internal value escaped diagnostics: ${internal}`)
    for (const authorValue of [
      '草稿版本11', '服务器确认能力允许签印', '潮汐留白体', '记忆代价卡', '雾港档案',
      '创作规划', '作者模型', '已绑定', '正文写作', '未绑定', '作者选择', '钟摆发动机', '每次破案都会失去一段记忆。',
      '克制、清醒，但余韵绵长', '长篇连载', '悬疑', '已冻结',
    ]) assert.match(publicText, new RegExp(authorValue), `missing author-facing value: ${authorValue}`)
  } finally {
    mounted.app.unmount()
    teleportTarget.children.splice(0)
  }
})

test('real component refs focus through either component focus or its root element', async () => {
  const components = await Promise.all([
    source('src/components/project/CreationContractWizard.vue'),
    source('src/components/project/contract/ContractPreviewStep.vue'),
    source('src/components/project/contract/CapacityStep.vue'),
    source('src/components/project/contract/AssetScopeStep.vue'),
    source('src/components/project/contract/StyleSelectionStep.vue'),
    source('src/components/project/contract/StyleTrialPanel.vue'),
    source('src/components/project/contract/ContractHistoryDrawer.vue'),
  ])
  for (const contents of components) {
    assert.match(contents, /\?\.\$el/)
    assert.match(contents, /typeof .*?\.focus === 'function'/s)
    assert.doesNotMatch(contents, /(?:errorRegion|detailErrorRegion|loadErrorRegion|confirmErrorRegion)\.value\?\.focus/)
  }
})

test('Foundation shell maps every legacy child token to the shared editorial tokens', async () => {
  const paths = [
    'src/components/project/contract/StoryEngineStep.vue',
    'src/components/project/contract/StyleSelectionStep.vue',
    'src/components/project/contract/StyleTrialPanel.vue',
    'src/components/project/contract/AssetScopeStep.vue',
    'src/components/project/contract/CapacityStep.vue',
    'src/components/project/contract/ContractPreviewStep.vue',
    'src/components/project/contract/ContractDecisionSummary.vue',
  ]
  const children = (await Promise.all(paths.map(path => source(path)))).join('\n')
  const shell = await source('src/components/foundation/FoundationWorkspace.vue')
  const globalStyles = await source('src/style.css')
  const legacyTokens = [...new Set([...children.matchAll(/var\(--(paper|ink|muted|rule|cinnabar|jade)\b/g)].map(match => match[1]))]
  const aliases = Object.fromEntries([...shell.matchAll(/--(paper|ink|muted|rule|cinnabar|jade):\s*var\(--(nc-[a-z-]+)\)/g)].map(match => [match[1], match[2]]))
  assert.deepEqual(legacyTokens.sort(), Object.keys(aliases).sort())
  assert.deepEqual(aliases, {
    paper: 'nc-paper', ink: 'nc-ink', muted: 'nc-muted', rule: 'nc-border',
    cinnabar: 'nc-vermilion', jade: 'nc-jade',
  })
  const rootBlock = globalStyles.match(/:root\s*\{([\s\S]*?)\}/)?.[1] || ''
  const globalTokens = Object.fromEntries(
    [...rootBlock.matchAll(/--([\w-]+):\s*([^;]+);/g)].map(match => [match[1], match[2].trim()]),
  )
  const resolved = Object.fromEntries(Object.entries(aliases).map(([legacy, shared]) => (
    [legacy, globalTokens[shared]]
  )))
  assert.match(resolved.jade || '', /^#[0-9a-f]{6}$/i)
  assert.ok(Object.values(resolved).every(value => value && !value.includes('var(')))
})

test('preview directory uses preview-specific read labels instead of generic editing labels', async () => {
  const wizard = await source('src/components/project/CreationContractWizard.vue')
  for (const label of ['待核对', '核对中', '已加载']) assert.match(wizard, new RegExp(label))
})

test('fresh head-zero contract_missing keeps the first Engine generate and save path writable', async () => {
  const headZero = {
    projectId: 'project-fresh', revision: 0, hasContract: false,
    contractReady: false, reasons: ['contract_missing'],
  }
  let generateCalls = 0
  let saveCalls = 0
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-fresh', project: { channelProfileKey: 'serial-fiction' }, readOnly: false,
  }, store => {
    store.draft = null
    store.head = headZero
    store.engineBatch = null
    store.load = async () => {
      store.draft = null
      store.head = headZero
      store.headHydrated = true
      return { draft: null, head: headZero, recovery: { items: [] } }
    }
    store.generateEngineBatch = async () => {
      generateCalls += 1
      const options = [1, 2, 3].map(index => ({
        ...engineOption(), id: `engine-${index}`, contentHash: index === 1 ? HASH_A : HASH_B,
        payload: { ...engineOption().payload, name: `新书发动机${index}`, storyPromise: `承诺${index}` },
      }))
      store.engineBatch = { id: 'batch-fresh', status: 'succeeded', options }
      return store.engineBatch
    }
    store.saveDraft = async (_projectId, values) => {
      saveCalls += 1
      const saved = {
        id: 'draft-fresh', projectId: 'project-fresh', draftVersion: 1,
        contentHash: HASH_A, draftStage: 'engine', draft: values,
      }
      store.draft = saved
      return saved
    }
    const seedStore = useSeedStore()
    seedStore.activeSelection = {
      projectId: 'project-fresh', selectionRevision: 1, seedId: 'seed-fresh',
      seedRevisionId: 'seed-revision-fresh', seedHash: HASH_A,
      seed: {
        id: 'seed-fresh', revisionId: 'seed-revision-fresh', contentHash: HASH_A, revision: 1,
        payload: { title: '新书种子', genre: '幻想', logline: '从空白契约开始。' },
      },
    }
    seedStore.refresh = async () => ({ activeSelection: seedStore.activeSelection })
  })

  try {
    await flush()
    await trigger(findByText(mounted.root, 'button', '编辑本节'), 'onClick')
    const generate = findByText(mounted.root, 'button', '生成三套方案')
    assert.ok(generate)
    assert.notEqual(generate.props.disabled, true)
    await trigger(generate, 'onClick')
    assert.equal(generateCalls, 1)
    await trigger(walk(mounted.root).find(node => node.props.role === 'radio'), 'onClick')
    await trigger(findByText(mounted.root, 'button', '保存本节'), 'onClick')
    assert.equal(saveCalls, 1)
    assert.match(textContent(mounted.root), /风格方案待填写/)
  } finally {
    mounted.app.unmount()
  }
})

test('signed Contract header uses the frozen Seed even when the live selection differs', async () => {
  const decisions = completeDecisionPayload()
  const frozenSeed = { ...decisions.creationContract.selectedSeed, title: '签印时的雾港种子' }
  const head = {
    projectId: 'project-1', revision: 5, hasContract: true, contractReady: true, reasons: [],
    selectionRevision: 7,
    seedRef: { id: 'seed-frozen', revisionId: 'seed-frozen-r3', contentHash: HASH_A },
    creationContract: { ...decisions.creationContract, selectedSeed: frozenSeed },
    styleContract: decisions.styleContract, likes: decisions.likes, dislikes: decisions.dislikes,
    styleRefs: [], experienceCardRefs: [], corpusSourceRefs: [],
  }
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-1', project: {}, readOnly: false,
  }, store => {
    store.draft = null
    store.head = head
    store.load = async () => { store.head = head; store.draft = null; return { head, draft: null } }
    const seedStore = useSeedStore()
    seedStore.activeSelection = {
      projectId: 'project-1', selectionRevision: 9, seedId: 'seed-live',
      seedRevisionId: 'seed-live-r9', seedHash: HASH_B,
      seed: { id: 'seed-live', revisionId: 'seed-live-r9', contentHash: HASH_B, revision: 9,
        payload: { title: '当前但未签印的新种子', genre: '都市', logline: '不应冒充签印依据。' } },
    }
    seedStore.refresh = async () => ({ activeSelection: seedStore.activeSelection })
  })

  try {
    await flush()
    const header = walk(mounted.root).find(node => node.type === 'aside' && node.props['aria-label']?.includes('种子'))
    assert.match(textContent(header), /签印时的雾港种子/)
    assert.match(textContent(header), /种子状态已冻结/)
    assert.doesNotMatch(textContent(header), /seed-frozen-r3/)
    assert.match(textContent(header), /R7/)
    assert.doesNotMatch(textContent(header), /当前但未签印的新种子/)
  } finally {
    mounted.app.unmount()
  }
})

test('document directory opens the server preview in place without changing page step', async () => {
  let previewCalls = 0
  const draft = {
    id: 'draft-document',
    projectId: 'project-1',
    draftVersion: 9,
    draftStage: 'assets',
    draft: {
      draftStage: 'assets',
      seedRevisionId: 'seed-revision-a',
      seedHash: HASH_A,
      engineOptionId: 'engine-1',
      engineHash: HASH_A,
      primaryStyleRef: { id: 'style-1', revision: 1, contentHash: HASH_B },
      secondaryStyleRef: null,
      likes: [], dislikes: [], experienceCardRefs: [], corpusSourceRefs: [],
      targetTotalWords: 900000, expectedVolumeCount: 6, expectedChapterCount: 300,
      chapterWordRangePreference: [2800, 3400], prohibitedDirections: [], authorNotes: null,
    },
  }
  const mounted = mountWithPinia(CreationContractWizard, {
    projectId: 'project-1', project: {}, readOnly: false,
  }, store => {
    store.draft = draft
    store.head = { projectId: 'project-1', revision: 0, hasContract: false }
    store.headHydrated = true
    store.load = async () => ({ draft, head: store.head })
    store.preview = async () => {
      previewCalls += 1
      const result = {
        projectId: 'project-1', draftVersion: 9, contractReady: true, reasons: [],
        seedRef: { revisionId: 'seed-revision-preview', contentHash: HASH_A },
        engineRef: { batchId: 'engine-batch-preview', contentHash: HASH_B },
        bindingRef: { revision: 4, contentHash: HASH_A, items: [] },
        styleRefs: [], experienceCardRefs: [], corpusSourceRefs: [],
        creationHash: HASH_A, styleHash: HASH_B,
      }
      store.previewResult = result
      return result
    }
    const seedStore = useSeedStore()
    seedStore.activeSelection = {
      projectId: 'project-1', selectionRevision: 4, seedId: 'seed-a',
      seedRevisionId: 'seed-revision-a', seedHash: HASH_A,
      seed: {
        id: 'seed-a', revisionId: 'seed-revision-a', contentHash: HASH_A, revision: 2,
        payload: { title: '目录预览种子', logline: '目录定位后在原文档内核对。', genre: '悬疑' },
      },
    }
    seedStore.refresh = async () => ({ activeSelection: seedStore.activeSelection })
  })

  try {
    await flush()
    for (const heading of ['故事发动机', '长篇容量', '正式资产范围', '风格方案', '禁止方向', '完整预览']) {
      assert.ok(textContent(mounted.root).includes(heading), `missing document heading: ${heading}`)
    }
    const previewDirectoryItem = walk(mounted.root).find(node => (
      node.type === 'button' && textContent(node).includes('完整预览')
    ))
    await trigger(previewDirectoryItem, 'onClick')
    assert.equal(previewCalls, 1)
    const diagnostics = walk(mounted.root).find(node => node.type === 'details' && textContent(node).includes('来源与诊断'))
    const publicText = textExcluding(mounted.root, diagnostics)
    assert.match(publicText, /创作种子已冻结/)
    assert.doesNotMatch(publicText, /seed-revision-preview/)
    assert.doesNotMatch(textContent(mounted.root), /下一步|上一步/)
  } finally {
    mounted.app.unmount()
  }
})

test('the shared decision summary declares its immutable display semantics', async () => {
  const summary = await source('src/components/project/contract/ContractDecisionSummary.vue')
  assert.match(summary, /readOnly/)
  assert.match(summary, /aria-readonly/)
  assert.doesNotMatch(summary, /@input|@update:value|contenteditable/)
  assert.match(summary, /authorProfileLabel/)
  assert.doesNotMatch(summary, /readable\(props\.creationContract\?\.(?:channelProfileKey|genreProfileKey|qualityCharterVersion)\)/)
})

test('contract workspace calls its own document divisions sections instead of novel chapters', async () => {
  const wizard = await source('src/components/project/CreationContractWizard.vue')
  for (const wording of ['切换分区', '当前分区', '按分区编辑并保存']) assert.match(wizard, new RegExp(wording))
  assert.doesNotMatch(wizard, /切换章节|当前章节|按章节编辑并保存/)
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
  let contractStore
  const mounted = mountWithPinia(ContractPreviewStep, () => ({
    projectId: projectId.value,
    confirmation: {
      preview: contractStore.previewResult,
      draftVersion: contractStore.draft?.draftVersion,
      contentHash: contractStore.draft?.contentHash,
      canConfirm: contractStore.previewResult?.contractReady === true,
    },
  }), store => {
    contractStore = store
    store.preview = async targetProjectId => {
      calls.push(targetProjectId)
      if (targetProjectId === 'project-a') return pendingA.promise
      const result = {
        projectId: targetProjectId, draftVersion: 3,
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
    const diagnostics = walk(mounted.root).find(node => node.type === 'details' && textContent(node).includes('来源与诊断'))
    const publicText = textExcluding(mounted.root, diagnostics)
    assert.match(publicText, /创作种子已冻结/)
    assert.doesNotMatch(publicText, /project-b-success/)
    assert.doesNotMatch(textContent(mounted.root), /project-a-late-failure/)
  } finally {
    mounted.app.unmount()
  }
})

test('confirmation conflict closes the stale dialog and disables every submit before reload', async () => {
  const preview = await source('src/components/project/contract/ContractPreviewStep.vue')

  assert.match(preview, /if \(!confirmation\.value\.canConfirm \|\| store\.confirming \|\| store\.requiresReload\) return/)
  assert.match(preview, /if \(store\.requiresReload\)\s*\{\s*confirmOpen\.value = false/)
  assert.match(preview, /:disabled="(?:props\.interactionLocked \|\| )?store\.confirming \|\| store\.requiresReload \|\| !confirmation\.canConfirm"/)
})

test('style selection keeps rapid A to B navigation on B when A fails late', async () => {
  const pendingA = deferred()
  const projectId = VueRuntime.ref('project-a')
  let listCalls = 0
  const styleB = {
    id: 'style-b', stableKey: 'style-b-stable', name: '项目 B 风格', revision: 2, contentHash: HASH_B,
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
      const result = formalAssetRecommendations(targetProjectId === 'project-b' ? [styleB] : [])
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

test('formal high-confidence style card and corpus recommendations remain explicitly selectable', async () => {
  const style = {
    id: 'style-formal', stableKey: 'style-formal-key', revision: 4,
    contentHash: HASH_A, name: '正式高置信风格', readingExperience: '线索与关系同步推进',
    applicability: [], nonApplicability: [],
  }
  const card = {
    id: 'card-formal', stableKey: 'card-formal-key', revision: 5,
    contentHash: HASH_B, title: '正式高置信经验卡', category: 'dialogue',
    method: '让每轮对话改变双方筹码', applicability: [], nonApplicability: [],
  }
  const source = {
    id: 'source-formal', revisionId: 'source-formal-revision', revision: 6,
    contentHash: 'c'.repeat(64), name: '正式推荐语料来源', state: 'active',
    fragmentCount: 3, shortHash: 'cccccccccccc',
  }
  const corpusRecommendation = {
    sourceId: source.id, sourceRevision: source.revision, sourceHash: source.contentHash,
    chapterId: 'chapter-formal', fragmentId: 'fragment-formal',
    fragmentHash: 'd'.repeat(64), rangeStart: 20, rangeEnd: 80,
    use: '作为制度压力的结构参照', reason: '与当前冲突直接相关', confidence: 0.92,
  }
  const response = formalAssetRecommendations([style], [card], [corpusRecommendation])
  const saves = []
  const configureAssets = contractStore => {
    contractStore.projectId = 'project-1'
    contractStore.draft = {
      ...contractStore.draft,
      selectionRevision: 3,
      draft: {
        ...contractStore.draft.draft,
        engineOptionId: 'engine-1', engineHash: HASH_A,
        channelProfileKey: 'manual-channel', genreProfileKey: 'historical',
        primaryStyleRef: { id: style.id, revision: style.revision, contentHash: style.contentHash },
      },
    }
    contractStore.saveDraft = async (projectId, payload) => {
      const frozenPayload = JSON.parse(JSON.stringify(payload))
      saves.push({ projectId, payload: frozenPayload })
      const saved = {
        ...contractStore.draft,
        draftVersion: contractStore.draft.draftVersion + 1,
        draft: frozenPayload,
      }
      contractStore.draft = saved
      return saved
    }
    const assetStore = useCreationAssetStore()
    assetStore.loadStyleTemplates = async () => {
      assetStore.styleTemplates = [style]
      return assetStore.styleTemplates
    }
    assetStore.loadExperienceCards = async () => {
      assetStore.experienceCards = [card]
      return assetStore.experienceCards
    }
    assetStore.loadRecommendations = async () => {
      assetStore.recommendations = response
      return response
    }
    const corpusStore = useCorpusStore()
    corpusStore.loadSources = async () => {
      corpusStore.sources = [source]
      return corpusStore.sources
    }
  }

  const styleMounted = mountWithPinia(StyleSelectionStep, {
    projectId: 'project-1', selectionRevision: 3,
  }, configureAssets)
  try {
    await flush()
    assert.match(textContent(styleMounted.root), /正式高置信风格/)
    assert.match(textContent(styleMounted.root), /整体气质匹配/)
    await trigger(findByText(styleMounted.root, 'button', '设为主风格'), 'onClick')
    assert.match(textContent(styleMounted.root), /主风格：正式高置信风格/)
  } finally {
    styleMounted.app.unmount()
  }

  const cardMounted = mountWithPinia(AssetScopeStep, { projectId: 'project-1' }, configureAssets)
  try {
    await flush()
    assert.match(textContent(cardMounted.root), /正式高置信经验卡/)
    assert.match(textContent(cardMounted.root), /推荐语料片段/)
    assert.match(textContent(cardMounted.root), /正式推荐语料来源/)
    assert.match(textContent(cardMounted.root), /作为制度压力的结构参照/)
    assert.match(textContent(cardMounted.root), /与当前冲突直接相关/)
    assert.match(textContent(cardMounted.root), /0 个片段/)
    assert.equal(textContent(cardMounted.root).includes('已授权 1 个来源'), false)
    const referenceUse = walk(cardMounted.root).find(node => (
      node.props['data-component'] === 'NSelect'
      && node.props['aria-label'] === '推荐片段 fragment-formal 的引用方式'
    ))
    assert.ok(referenceUse)
    assert.equal(findByText(cardMounted.root, 'button', '明确纳入推荐范围').props.disabled, true)
    await trigger(referenceUse, 'onUpdate:value', 'structure')
    assert.equal(findByText(cardMounted.root, 'button', '明确纳入推荐范围').props.disabled, false)
    await trigger(findByText(cardMounted.root, 'button', '明确纳入推荐范围'), 'onClick')
    assert.match(textContent(cardMounted.root), /1 个片段/)
    assert.match(textContent(cardMounted.root), /已授权 1 个来源/)
    await trigger(findByText(cardMounted.root, 'button', '明确纳入'), 'onClick')
    assert.match(textContent(cardMounted.root), /1 张已选/)
    await trigger(findByText(cardMounted.root, 'button', '保存本节'), 'onClick')
    assert.equal(saves.length, 1, textContent(cardMounted.root))
    assert.deepEqual(saves[0], {
      projectId: 'project-1',
      payload: {
        ...saves[0].payload,
        experienceCardRefs: [{ id: card.id, revision: card.revision, contentHash: card.contentHash }],
        corpusSourceRefs: [{
          id: source.id,
          revisionId: source.revisionId,
          revision: source.revision,
          contentHash: source.contentHash,
          selectionMode: 'author',
          pinnedHistoricalRevision: false,
          fragments: [{
            chapterId: corpusRecommendation.chapterId,
            fragmentId: corpusRecommendation.fragmentId,
            fragmentHash: corpusRecommendation.fragmentHash,
            chapterCharStart: corpusRecommendation.rangeStart,
            chapterCharEnd: corpusRecommendation.rangeEnd,
            referenceUse: 'structure',
          }],
        }],
      },
    })
  } finally {
    cardMounted.app.unmount()
  }
})

test('style selection updates both summaries and saves both frozen refs from selects', async () => {
  const primary = styleSummary('style-a', '克制悬疑型', HASH_A)
  const secondary = styleSummary('style-b', '沉浸群像型', HASH_B)
  const saves = []
  const mounted = mountWithPinia(StyleSelectionStep, {
    projectId: 'project-1',
    selectionRevision: 3,
  }, contractStore => {
    contractStore.projectId = 'project-1'
    contractStore.draft = {
      ...contractStore.draft,
      selectionRevision: 3,
      draft: {
        ...contractStore.draft.draft,
        channelProfileKey: 'manual-channel',
        genreProfileKey: 'historical',
        qualityCharterVersion: 'quality-v1',
        prohibitedDirections: [],
      },
    }
    contractStore.saveDraft = async (projectId, payload) => {
      saves.push({ projectId, payload: structuredClone(payload) })
      const saved = {
        ...contractStore.draft,
        draftVersion: contractStore.draft.draftVersion + 1,
        draft: structuredClone(payload),
      }
      contractStore.draft = saved
      return saved
    }
    const assetStore = useCreationAssetStore()
    assetStore.loadStyleTemplates = async () => {
      assetStore.styleTemplates = [primary, secondary]
      return assetStore.styleTemplates
    }
    assetStore.loadRecommendations = async () => {
      const result = formalAssetRecommendations([primary, secondary])
      assetStore.recommendations = result
      return result
    }
  })

  try {
    await flush()
    const selects = walk(mounted.root).filter(node => (
      node.props['data-component'] === 'NSelect'
    ))
    assert.equal(selects.length, 2)

    await trigger(selects[0], 'onUpdate:value', primary.id)
    assert.match(textContent(mounted.root), /主风格：克制悬疑型/)
    await trigger(selects[1], 'onUpdate:value', secondary.id)
    assert.match(textContent(mounted.root), /次风格：沉浸群像型/)

    await trigger(findByText(mounted.root, 'button', '保存本节'), 'onClick')
    assert.equal(saves.length, 1)
    assert.equal(saves[0].projectId, 'project-1')
    assert.deepEqual(saves[0].payload.primaryStyleRef, {
      id: primary.id,
      revision: primary.revision,
      contentHash: primary.contentHash,
    })
    assert.deepEqual(saves[0].payload.secondaryStyleRef, {
      id: secondary.id,
      revision: secondary.revision,
      contentHash: secondary.contentHash,
    })
  } finally {
    mounted.app.unmount()
  }
})

function styleSummary(id, name, contentHash) {
  return {
    id,
    stableKey: `${id}-stable`,
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
        const result = formalAssetRecommendations([styleA, styleB])
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
    }), store => {
      store.projectId = 'project-1'
      store.head = { projectId: 'project-1', revision: 0, hasContract: false }
      store.headHydrated = true
    })

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

test('history error focuses the real component root and exposes retry in alert content', async () => {
  const show = VueRuntime.ref(false)
  let calls = 0
  naiveBehaviorModule.focusEvents.length = 0
  const mounted = mountWithPinia(ContractHistoryDrawer, () => ({
    show: show.value, projectId: 'project-1',
  }), store => {
    store.loadHistory = async () => {
      calls += 1
      if (calls === 1) throw new Error('历史暂时不可用')
      store.history = [simpleHistoryRow(9)]
      return { items: store.history, nextBeforeRevision: null }
    }
    store.clearHistory = () => { store.history = [] }
  })
  try {
    show.value = true
    await flush()
    assert.match(textContent(mounted.root), /历史暂时不可用/)
    assert.ok(naiveBehaviorModule.focusEvents.includes('NAlert.$el'))
    const retry = findByText(mounted.root, 'button', '重新加载')
    assert.ok(retry)
    await trigger(retry, 'onClick')
    assert.equal(calls, 2)
    assert.match(textContent(mounted.root), /R9/)
  } finally {
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
