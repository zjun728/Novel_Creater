import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createPinia, setActivePinia } from 'pinia'
import * as VueRuntime from '@vue/runtime-core'
import { createRenderer, nextTick, ssrContextKey } from '@vue/runtime-core'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('../..', import.meta.url))
const naiveId = '\0market-discovery-naive'
const readerId = '\0market-discovery-reader'

const stubs = {
  name: 'market-discovery-stubs',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveId
    if (id.endsWith('/MarketSnapshotWorks.vue') || id.endsWith('\\MarketSnapshotWorks.vue')) return readerId
    return undefined
  },
  load(id) {
    if (id === naiveId) return `
      import { defineComponent, h } from 'vue'
      const children = slots => Object.values(slots).flatMap(slot => slot?.() || [])
      const stub = (name, tag = 'div') => defineComponent({
        name, inheritAttrs: false,
        setup(_, { attrs, slots }) { return () => h(tag, attrs, children(slots)) },
      })
      export const NAlert = stub('NAlert', 'aside')
      export const NButton = stub('NButton', 'button')
      export const NEmpty = stub('NEmpty')
      export const NSpin = stub('NSpin')
      export const NTag = stub('NTag', 'span')
    `
    if (id === readerId) return `
      import { defineComponent, h } from 'vue'
      export default defineComponent({
        name: 'MarketSnapshotWorks', inheritAttrs: false,
        props: { snapshot: Object, source: Object, loading: Boolean, error: [Object, String], attached: Boolean },
        emits: ['toggle-attachment'],
        setup(props) { return () => h('section', {
          'data-reader-id': props.snapshot?.id || '',
          'data-reader-title': props.snapshot?.entries?.[0]?.title || '',
          'aria-busy': String(props.loading),
        }) },
      })
    `
    return undefined
  },
}

const node = type => ({
  type, text: '', props: {}, children: [], parent: null, clicked: 0,
  click() { this.clicked += 1 },
})
const detach = child => {
  if (!child?.parent) return
  const index = child.parent.children.indexOf(child)
  if (index >= 0) child.parent.children.splice(index, 1)
  child.parent = null
}
const renderer = createRenderer({
  patchProp(item, key, _old, value) { if (value == null) delete item.props[key]; else item.props[key] = value },
  insert(child, parent, anchor = null) { detach(child); child.parent = parent; const index = anchor ? parent.children.indexOf(anchor) : -1; if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child) },
  remove: detach,
  createElement: node,
  createText: value => ({ ...node('#text'), text: String(value) }),
  createComment: value => ({ ...node('#comment'), text: String(value || '') }),
  setText(item, value) { item.text = String(value) },
  setElementText(item, value) { item.text = String(value); item.children = [] },
  parentNode: item => item?.parent || null,
  nextSibling: item => item?.parent?.children[item.parent.children.indexOf(item) + 1] || null,
  querySelector: () => null,
  setScopeId(item, id) { item.props[id] = '' },
  cloneNode: item => ({ ...item, props: { ...item.props }, children: [...item.children], parent: null }),
  insertStaticContent(content, parent, anchor) { const item = { ...node('#static'), text: content }; renderer.insert(item, parent, anchor); return [item, item] },
})

function walk(item, result = []) {
  if (!item) return result
  result.push(item)
  for (const child of item.children || []) walk(child, result)
  return result
}
const textOf = item => [item?.text || '', ...(item?.children || []).map(textOf)].join('')
const find = (target, predicate) => walk(target).find(predicate)
const button = (target, label) => find(target, item => item.type === 'button' && item.props['aria-label'] === label)
const deferred = () => { let resolve; let reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
async function flush() { for (let index = 0; index < 8; index += 1) await Promise.resolve(); await nextTick() }
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })

function source(id, name, overrides = {}) {
  return Object.freeze({
    id, stableKey: `${id}.rank`, displayName: name, adapterKey: `${id}_rank`,
    platform: id, rankingName: 'rank', category: 'all', policyStatus: 'verified_public',
    policyVersion: 'v1', checkedAt: 1, evidenceURL: `https://www.qidian.com/${id}/`,
    automaticRefreshAllowed: true, canManualImport: true, canRefresh: true,
    canSchedule: false, refreshStatus: 'idle', lastAttemptedAt: null,
    lastSucceededAt: 1_752_800_000, lastSnapshotId: `${id}-old`, publicErrorCode: null,
    ...overrides,
  })
}
function summary(sourceId, id = `${sourceId}-old`) {
  return Object.freeze({ id, sourceId, capturedAt: 1_752_800_000, platform: sourceId, rankingName: 'rank', category: 'all', sourceURL: `https://www.qidian.com/${sourceId}/`, contentHash: 'a'.repeat(64), entryCount: 1, captureMode: 'network', adapterVersion: 'qidian-public-rank-v1' })
}
function detail(sourceId, id = `${sourceId}-old`, title = `${sourceId}作品`) {
  return { ...summary(sourceId, id), entries: [{ rank: 1, title, author: '作者', category: '题材', workURL: `https://www.qidian.com/${sourceId}/book/1/`, publicMetrics: {} }] }
}

let vite
let Component
test.before(async () => {
  vite = await createServer({ configFile: false, root, appType: 'custom', logLevel: 'error', resolve: { alias: { '@': `${root}/src` } }, server: { middlewareMode: true, hmr: false, ws: false }, plugins: [stubs, vuePlugin()], ssr: { noExternal: ['naive-ui'] }, optimizeDeps: { noDiscovery: true } })
  Component = (await vite.ssrLoadModule('/src/components/topics/MarketDiscoveryPanel.vue')).default
  const sourceText = await readFile(new URL('../../src/components/topics/MarketDiscoveryPanel.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(sourceText)
  Component.render = new Function('Vue', compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(descriptor, { id: 'market-discovery' }).bindings }).code)(VueRuntime)
})
test.after(async () => { await vite?.close() })

async function mountedWithState(fetchImpl, sources = [source('a', '甲榜'), source('b', '乙榜')]) {
  const originalFetch = globalThis.fetch
  globalThis.fetch = fetchImpl
  const pinia = createPinia(); setActivePinia(pinia)
  const { useMarketSourceStore } = await vite.ssrLoadModule('/src/stores/marketSourceStore.js')
  const store = useMarketSourceStore()
  store.$patch({ sources, snapshotHistory: Object.fromEntries(sources.map(item => [item.id, Object.freeze([summary(item.id)])])) })
  const target = node('root')
  const app = renderer.createApp(Component, { selectedEvidence: [] })
  app.use(pinia); app.provide(ssrContextKey, { modules: new Set() }); app.mount(target); await flush()
  return { target, store, dispose() { app.unmount(); globalThis.fetch = originalFetch } }
}

test('mounted source actions expose visible phrases inside their accessible names', async () => {
  const disabled = source('off', '停用榜', { automaticRefreshAllowed: false, canRefresh: false, canManualImport: false, policyStatus: 'disabled' })
  const item = await mountedWithState(async () => { throw new Error('unexpected fetch') }, [source('a', '甲榜'), disabled])
  try {
    for (const [label, visible] of [['刷新甲榜', '刷新甲榜'], ['导入甲榜', '导入甲榜'], ['查看榜单作品：甲榜', '查看榜单作品']]) {
      const action = button(item.target, label)
      assert.ok(action, label)
      assert.match(textOf(action), new RegExp(visible))
    }
    assert.match(textOf(item.target), /网络刷新/)
    assert.match(textOf(item.target), /已停用/)
  } finally { item.dispose() }
})

test('failed refresh cannot replace the old snapshot evidence attributes', async () => {
  const refreshGate = deferred()
  const item = await mountedWithState(async () => {
    await refreshGate.promise
    return response({ error: { code: 'MARKET_TRANSPORT_FAILED', message: '刷新失败' } }, 503)
  }, [source('a', '甲榜')])
  try {
    const card = find(item.target, candidate => candidate.props['data-market-source-key'] === 'a.rank')
    assert.equal(card.props['data-market-latest-snapshot-id'], 'a-old')
    assert.equal(card.props['data-market-latest-captured-at'], 1_752_800_000)
    assert.equal(card.props['data-market-latest-entry-count'], 1)

    const intent = button(item.target, '刷新甲榜').props.onClick()
    await flush()
    assert.equal(card.props['data-market-source-busy'], 'true')
    refreshGate.resolve()
    await intent
    await flush()

    assert.equal(card.props['data-market-source-busy'], 'false')
    assert.equal(card.props['data-market-latest-snapshot-id'], 'a-old')
    assert.equal(card.props['data-market-latest-captured-at'], 1_752_800_000)
    assert.equal(card.props['data-market-latest-entry-count'], 1)
  } finally { item.dispose() }
})

test('a later explicit view wins over an earlier refresh completion', async () => {
  const refreshGate = deferred()
  const item = await mountedWithState(async (url, options = {}) => {
    const path = String(url)
    if (options.method === 'POST' && path.includes('/a/refresh')) { await refreshGate.promise; return response(detail('a', 'a-new', '甲新作')) }
    if (path.endsWith('/b-old')) return response(detail('b', 'b-old', '乙旧作'))
    return response({ error: { code: 'MARKET_FETCH_FAILED', message: 'reread' } }, 503)
  })
  try {
    const oldIntent = button(item.target, '刷新甲榜').props.onClick()
    await flush()
    await button(item.target, '查看榜单作品：乙榜').props.onClick(); await flush()
    refreshGate.resolve(); await oldIntent; await flush()
    const reader = find(item.target, node => node.props['data-reader-id'] !== undefined)
    assert.equal(reader.props['data-reader-id'], 'b-old')
    assert.equal(reader.props['data-reader-title'], '乙旧作')
  } finally { item.dispose() }
})

test('manual import captures its source before awaits and a later view keeps selection', async () => {
  const textGate = deferred()
  const calls = []
  const item = await mountedWithState(async (url, options = {}) => {
    calls.push([String(url), options.method])
    if (options.method === 'POST' && String(url).includes('/a/manual-import')) return response(detail('a', 'a-import', '甲导入作'))
    if (String(url).endsWith('/b-old')) return response(detail('b', 'b-old', '乙旧作'))
    return response({ error: { code: 'MARKET_FETCH_FAILED', message: 'reread' } }, 503)
  })
  try {
    button(item.target, '导入甲榜').props.onClick(); await flush()
    const input = find(item.target, node => node.type === 'input' && node.props.type === 'file')
    const importPromise = input.props.onChange({ target: { value: 'a.json', files: [{ text: () => textGate.promise }] } })
    button(item.target, '导入乙榜').props.onClick(); await flush()
    await button(item.target, '查看榜单作品：乙榜').props.onClick(); await flush()
    textGate.resolve(JSON.stringify({ entries: [] })); await importPromise; await flush()
    assert.equal(calls.some(([url, method]) => method === 'POST' && url.includes('/a/manual-import')), true)
    assert.equal(calls.some(([url, method]) => method === 'POST' && url.includes('/b/manual-import')), false)
    const reader = find(item.target, node => node.props['data-reader-id'] !== undefined)
    assert.equal(reader.props['data-reader-id'], 'b-old')
  } finally { item.dispose() }
})

test('repeated detail loads for one key keep aria busy until the newest request settles', async () => {
  const first = deferred(); const second = deferred(); let count = 0
  const item = await mountedWithState(async url => {
    if (String(url).endsWith('/a-old')) { count += 1; await (count === 1 ? first.promise : second.promise); return response(detail('a')) }
    throw new Error(`unexpected ${url}`)
  }, [source('a', '甲榜')])
  try {
    const action = button(item.target, '查看榜单作品：甲榜')
    const older = action.props.onClick(); await flush()
    const newer = action.props.onClick(); await flush()
    first.resolve(); await older; await flush()
    let reader = find(item.target, node => node.props['data-reader-id'] !== undefined)
    assert.equal(reader.props['aria-busy'], 'true')
    second.resolve(); await newer; await flush()
    reader = find(item.target, node => node.props['data-reader-id'] !== undefined)
    assert.equal(reader.props['aria-busy'], 'false')
  } finally { item.dispose() }
})
