import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { createPinia, setActivePinia } from 'pinia'
import { createRenderer, nextTick, ssrContextKey } from '@vue/runtime-core'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from '@vue/runtime-core'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('../..', import.meta.url))
const naiveStubId = '\0manuscript-directory-naive-stub'
const naiveStub = {
  name: 'manuscript-directory-naive-stub', enforce: 'pre',
  resolveId(id) { return id === 'naive-ui' ? naiveStubId : undefined },
  load(id) { return id === naiveStubId ? `import { defineComponent, h } from 'vue'; const children = slots => Object.values(slots).flatMap(slot => slot?.() || []); const stub = name => defineComponent({ name, setup(_, { attrs, slots }) { return () => h('div', attrs, children(slots)) } }); export const NButton = defineComponent({ name: 'NButton', setup(_, { attrs, slots }) { return () => h('button', attrs, children(slots)) } }); export const NResult = stub('NResult'); export const NSkeleton = stub('NSkeleton')` : undefined },
}
const makeNode = type => ({ type, text: '', props: {}, children: [], parent: null })
const detach = child => { if (child?.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1) }
const renderer = createRenderer({
  patchProp(node, key, _old, value) { if (value == null) delete node.props[key]; else node.props[key] = value },
  insert(child, parent, anchor = null) { detach(child); child.parent = parent; const index = anchor ? parent.children.indexOf(anchor) : -1; if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child) },
  remove: detach, createElement: makeNode, createText: value => ({ ...makeNode('#text'), text: String(value) }), createComment: value => ({ ...makeNode('#comment'), text: String(value || '') }),
  setText: (node, value) => { node.text = String(value) }, setElementText: (node, value) => { node.text = String(value); node.children = [] }, parentNode: node => node?.parent || null, nextSibling: node => node?.parent?.children[node.parent.children.indexOf(node) + 1] || null, querySelector: () => null, setScopeId: (node, id) => { node.props[id] = '' }, cloneNode: node => ({ ...node, props: { ...node.props }, children: [...node.children], parent: null }), insertStaticContent(content, parent, anchor) { const node = { ...makeNode('#static'), text: content }; renderer.insert(node, parent, anchor); return [node, node] },
})
const text = node => [node?.text, ...(node?.children || []).map(text)].filter(Boolean).join(' ')
const find = (node, predicate) => node && (predicate(node) ? node : (node.children || []).map(child => find(child, predicate)).find(Boolean))
async function flush() { for (let i = 0; i < 8; i += 1) await Promise.resolve(); await nextTick() }
async function waitFor(predicate, message) {
  for (let index = 0; index < 20; index += 1) {
    const value = predicate()
    if (value) return value
    await flush()
  }
  assert.fail(message)
}
function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => { resolve = onResolve; reject = onReject })
  return { promise, resolve, reject }
}

let vite; let Index
async function clientRender(path, id) {
  const source = await readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')
  const { descriptor } = parse(source, { filename: path })
  return new Function('Vue', compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(descriptor, { id }).bindings }).code)(VueRuntime)
}
test.before(async () => {
  vite = await createServer({ configFile: false, root, appType: 'custom', logLevel: 'error', server: { middlewareMode: true, hmr: false, ws: false }, plugins: [vuePlugin(), naiveStub], ssr: { noExternal: ['naive-ui'] }, optimizeDeps: { noDiscovery: true } })
  Index = (await vite.ssrLoadModule('/src/views/ManuscriptIndexView.vue')).default
  const source = await readFile(new URL('../../src/views/ManuscriptIndexView.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source, { filename: 'ManuscriptIndexView.vue' })
  Index.render = new Function('Vue', compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(descriptor, { id: 'manuscript-index' }).bindings }).code)(VueRuntime)
  const ChapterList = (await vite.ssrLoadModule('/src/components/manuscript/ManuscriptChapterList.vue')).default
  ChapterList.render = await clientRender('components/manuscript/ManuscriptChapterList.vue', 'manuscript-chapter-list')
})
test.after(async () => { await vite?.close() })

const directory = (id, lifecycle = 'active', chapters = true) => ({ projectId: id, title: `${id} 书名`, lifecycle, summary: { finalChapterCount: chapters ? 1 : 0, totalScalarCount: chapters ? 123 : 0 }, volumes: chapters ? [{ id: 'v-1', order: 1, title: '上卷', chapters: [{ number: 2, title: '第二章', scalarCount: 123, finalizedAt: '2026-01-01T00:00:00Z' }] }] : [] })
const preparation = id => ({ projectId: id, lifecycle: 'active', nextAction: 'continue_contract', targetPath: `/projects/${id}/contract`, activeSelection: 'current', contract: 'draft', bible: 'missing', planning: 'missing', outline: 'missing', authoritativeChapterNumber: 1, modelTasks: [], capabilities: {}, reasons: [] })
const options = { available: true, reason: null, formats: ['txt', 'markdown'], volumes: [{ id: 'v-1', order: 1, title: '上卷' }], chapters: [{ number: 2, title: '第二章', volumeId: 'v-1' }] }
const response = body => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })

async function mount({
  lifecycle = 'active', chapters = true, unavailable = false,
  directorySequence = [], preparationSequence = [], optionSequence = [], fetchOverride,
} = {}) {
  const originalFetch = global.fetch; const originalDocument = global.document; const calls = []
  let directoryAttempt = 0; let preparationAttempt = 0; let optionAttempt = 0
  global.document = { createElement: () => ({ click() {}, remove() {} }), body: { append() {} } }
  global.fetch = async (url, init = {}) => {
    const value = String(url); calls.push([value, init])
    if (fetchOverride) {
      const overridden = fetchOverride(value, init, calls)
      if (overridden !== undefined) return overridden
    }
    if (value.endsWith('/manuscript')) {
      const next = directorySequence[directoryAttempt++]
      if (next instanceof Error) throw next
      if (next instanceof Response) return next
      return response(next || directory('p', lifecycle, chapters))
    }
    if (value.endsWith('/preparation')) {
      const next = preparationSequence[preparationAttempt++]
      if (next instanceof Error) throw next
      if (next instanceof Response) return next
      return response(next || preparation('p'))
    }
    if (value.endsWith('/novel-download/options')) {
      const next = optionSequence[optionAttempt++]
      if (next instanceof Error) throw next
      if (next instanceof Response) return next
      return response(next || { ...options, available: !unavailable })
    }
    return new Response(new Blob(['x']), { headers: { 'content-disposition': 'attachment; filename="book.txt"' } })
  }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/manuscript', component: Index }, { path: '/projects/:projectId/contract', component: { render: () => null } }, { path: '/projects/:projectId/manuscript/chapters/:chapterNumber', component: { render: () => null } }] })
  await router.push('/projects/p/manuscript'); await router.isReady()
  const target = makeNode('root'); const app = renderer.createApp({ render: () => VueRuntime.h(RouterView) }); const pinia = createPinia(); setActivePinia(pinia); app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.mount(target); await flush(); await flush()
  return { target, calls, router, dispose() { app.unmount(); global.fetch = originalFetch; global.document = originalDocument } }
}

test('mounted active directory loads preparation, options, and exact download selectors', async () => {
  const item = await mount()
  try {
    assert.match(text(item.target), /p 书名.*123.*当前创作位置/)
    assert.ok(find(item.target, node => node.type === 'details' && text(node).includes('下载定稿')))
    const book = find(item.target, node => node.type === 'button' && node.props['aria-label'] === '下载整本定稿 TXT')
    await book.props.onClick(); await flush()
    let query = new URL(item.calls.at(-1)[0]).searchParams
    assert.equal(query.get('scope'), 'book'); assert.equal(query.get('format'), 'txt')
    const volume = find(item.target, node => node.type === 'button' && node.props['aria-label'] === '下载第1卷 Markdown')
    await volume.props.onClick(); await flush()
    query = new URL(item.calls.at(-1)[0]).searchParams
    assert.equal(query.get('scope'), 'volume'); assert.equal(query.get('volumeId'), 'v-1'); assert.equal(query.get('format'), 'markdown')
    const chapter = find(item.target, node => node.type === 'button' && node.props['aria-label'] === '下载第 2 章定稿 Markdown')
    await chapter.props.onClick(); await flush()
    query = new URL(item.calls.at(-1)[0]).searchParams
    assert.equal(query.get('scope'), 'chapter'); assert.equal(query.get('chapterNumber'), '2'); assert.equal(query.get('format'), 'markdown')
  } finally { item.dispose() }
})

test('mounted archived and empty directories keep lifecycle calls independent', async () => {
  const archived = await mount({ lifecycle: 'archived' }); const empty = await mount({ chapters: false })
  try {
    assert.match(text(archived.target), /仅供阅读与下载/)
    assert.equal(archived.calls.filter(([url]) => url.endsWith('/preparation')).length, 0)
    assert.match(text(empty.target), /还没有已定稿章节/)
    assert.equal(empty.calls.filter(([url]) => url.endsWith('/novel-download/options')).length, 0)
  } finally { archived.dispose(); empty.dispose() }
})

test('unavailable download options leave the mounted directory readable without controls', async () => {
  const item = await mount({ unavailable: true })
  try { assert.match(text(item.target), /p 书名/); assert.ok(!find(item.target, node => node.type === 'details' && text(node).includes('下载定稿'))) } finally { item.dispose() }
})

test('a first temporary failure retries the complete directory preparation and options flow', async () => {
  const unavailableResponse = new Response(JSON.stringify({
    code: 'ManuscriptTemporarilyUnavailable', message: '作品稿件暂时不可用', correlationId: 'safe_1',
  }), { status: 503, headers: { 'content-type': 'application/json' } })
  const item = await mount({ directorySequence: [unavailableResponse, directory('p')] })
  try {
    assert.match(text(item.target), /目录暂时无法读取/)
    assert.doesNotMatch(text(item.target), /已保留可安全显示/)
    const retry = find(item.target, node => node.type === 'button' && /重新读取/.test(text(node)))
    await retry.props.onClick(); await flush(); await flush()
    assert.match(text(item.target), /p 书名.*当前创作位置/)
    assert.equal(item.calls.filter(([url]) => url.endsWith('/preparation')).length, 1)
    assert.equal(item.calls.filter(([url]) => url.endsWith('/novel-download/options')).length, 1)
  } finally { item.dispose() }
})

test('integrity retry and independent preparation or option failures never hide the directory', async () => {
  const integrityResponse = new Response(JSON.stringify({
    code: 'ManuscriptIntegrityFailure', message: '作品稿件完整性校验失败', correlationId: 'safe_2',
  }), { status: 500, headers: { 'content-type': 'application/json' } })
  const integrity = await mount({ directorySequence: [integrityResponse, directory('p')] })
  const preparationFailure = await mount({ preparationSequence: [new Error('private preparation failure')] })
  const optionFailure = await mount({ optionSequence: [new Error('private option failure')] })
  try {
    const retry = find(integrity.target, node => node.type === 'button' && /重新读取/.test(text(node)))
    assert.ok(retry)
    await retry.props.onClick(); await flush(); await flush()
    assert.match(text(integrity.target), /p 书名.*当前创作位置/)
    assert.match(text(preparationFailure.target), /p 书名.*创作状态暂时无法读取/)
    assert.doesNotMatch(text(preparationFailure.target), /private preparation failure/)
    assert.match(text(optionFailure.target), /p 书名.*下载选项加载失败，请重试/)
    assert.doesNotMatch(text(optionFailure.target), /private option failure/)
  } finally { integrity.dispose(); preparationFailure.dispose(); optionFailure.dispose() }
})

test('switching projects fences a late directory and keeps only the new project flow', async () => {
  const pendingA = deferred()
  const item = await mount({
    fetchOverride(value) {
      if (value.endsWith('/projects/A/manuscript')) return pendingA.promise
      if (value.endsWith('/projects/B/manuscript')) return response(directory('B'))
      if (value.endsWith('/projects/B/preparation')) return response(preparation('B'))
      if (value.endsWith('/projects/B/novel-download/options')) return response(options)
      return undefined
    },
  })
  try {
    await item.router.push('/projects/A/manuscript'); await flush()
    await item.router.push('/projects/B/manuscript'); await flush(); await flush()
    assert.match(text(item.target), /B 书名/)
    pendingA.resolve(response(directory('A')))
    await flush(); await flush()
    assert.match(text(item.target), /B 书名/)
    assert.doesNotMatch(text(item.target), /A 书名/)
  } finally { item.dispose() }
})
