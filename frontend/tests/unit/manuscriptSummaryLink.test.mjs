import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from '@vue/runtime-core'
import { createRenderer, h, nextTick, ref, ssrContextKey } from '@vue/runtime-core'
import { createMemoryHistory, createRouter } from 'vue-router'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const makeNode = type => ({ type, text: '', props: {}, children: [], parent: null })
const detach = child => {
  if (!child?.parent) return
  child.parent.children.splice(child.parent.children.indexOf(child), 1)
  child.parent = null
}
const renderer = createRenderer({
  patchProp(node, key, _oldValue, value) {
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
  createComment: value => ({ ...makeNode('#comment'), text: String(value || '') }),
  setText: (node, value) => { node.text = String(value) },
  setElementText: (node, value) => { node.text = String(value); node.children = [] },
  parentNode: node => node?.parent || null,
  nextSibling: node => node?.parent?.children[node.parent.children.indexOf(node) + 1] || null,
  querySelector: () => null,
  setScopeId: (node, id) => { node.props[id] = '' },
  cloneNode: node => ({ ...node, props: { ...node.props }, children: [...node.children], parent: null }),
  insertStaticContent(content, parent, anchor) {
    const node = { ...makeNode('#static'), text: content }
    renderer.insert(node, parent, anchor)
    return [node, node]
  },
})

function text(node) {
  return [node?.text, ...(node?.children || []).map(text)].filter(Boolean).join(' ')
}
function find(node, predicate) {
  if (node && predicate(node)) return node
  for (const child of node?.children || []) {
    const found = find(child, predicate)
    if (found) return found
  }
  return null
}
async function flush() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
  await nextTick()
}
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
const directory = (projectId, count) => ({
  projectId,
  title: `${projectId} 书名`,
  lifecycle: 'active',
  summary: { finalChapterCount: count, totalScalarCount: count * 10 },
  volumes: count === 0 ? [] : [{
    id: 'volume-1', order: 1, title: '第一卷',
    chapters: Array.from({ length: count }, (_, index) => ({
      number: index + 1,
      title: `第${index + 1}章`,
      scalarCount: 10,
      finalizedAt: '2026-01-01T00:00:00Z',
    })),
  }],
})
const response = body => new Response(JSON.stringify(body), {
  headers: { 'content-type': 'application/json' },
})

let vite
let SummaryLink
test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin()],
    server: { middlewareMode: true, hmr: false, ws: false },
    optimizeDeps: { noDiscovery: true },
  })
  SummaryLink = (await vite.ssrLoadModule('/src/components/manuscript/ManuscriptSummaryLink.vue')).default
  const source = await readFile(new URL('../../src/components/manuscript/ManuscriptSummaryLink.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source, { filename: 'ManuscriptSummaryLink.vue' })
  const bindings = compileScript(descriptor, { id: 'manuscript-summary-link' }).bindings
  SummaryLink.render = new Function('Vue', compile(descriptor.template.content, {
    mode: 'function', prefixIdentifiers: true, bindingMetadata: bindings,
  }).code)(VueRuntime)
})
test.after(async () => { await vite?.close() })

async function mountSummary(fetchImpl, initialProjectId = 'A') {
  const originalFetch = global.fetch
  global.fetch = fetchImpl
  const projectId = ref(initialProjectId)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/projects/:projectId/manuscript', component: { render: () => null } }],
  })
  const target = makeNode('root')
  const app = renderer.createApp({
    setup() { return () => h(SummaryLink, { projectId: projectId.value }) },
  })
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(target)
  await flush()
  return {
    target,
    projectId,
    async update(value) { projectId.value = value; await flush() },
    dispose() { app.unmount(); global.fetch = originalFetch },
  }
}

test('summary publishes a validated ready count and encoded manuscript link', async () => {
  const item = await mountSummary(async () => response(directory('A', 3)))
  try {
    await waitFor(() => /已定稿 3 章/.test(text(item.target)), () => text(item.target))
    const link = find(item.target, node => node.type === 'a')
    assert.equal(link.props.href, '/projects/A/manuscript')
  } finally { item.dispose() }
})

test('summary failure stays safe and its retry installs the authoritative count', async () => {
  let attempt = 0
  const item = await mountSummary(async () => {
    attempt += 1
    if (attempt === 1) throw new Error('private transport token')
    return response(directory('A', 4))
  })
  try {
    await waitFor(() => /暂时无法读取定稿数量/.test(text(item.target)), () => text(item.target))
    assert.doesNotMatch(text(item.target), /private transport token/)
    const retry = find(item.target, node => node.type === 'button')
    await retry.props.onClick(); await flush()
    await waitFor(() => /已定稿 4 章/.test(text(item.target)), () => text(item.target))
  } finally { item.dispose() }
})

test('summary project changes discard an older same-id response', async () => {
  const firstA = deferred()
  let aCalls = 0
  const item = await mountSummary(async url => {
    const id = decodeURIComponent(/\/projects\/([^/]+)\/manuscript$/u.exec(String(url))?.[1] || '')
    if (id === 'A' && aCalls++ === 0) return firstA.promise
    return response(directory(id, id === 'A' ? 5 : 2))
  })
  try {
    await item.update('B')
    await waitFor(() => /已定稿 2 章/.test(text(item.target)), () => text(item.target))
    await item.update('A')
    await waitFor(() => /已定稿 5 章/.test(text(item.target)), () => text(item.target))
    firstA.resolve(response(directory('A', 99)))
    await flush(); await flush()
    assert.match(text(item.target), /已定稿 5 章/)
    assert.doesNotMatch(text(item.target), /99/)
  } finally { item.dispose() }
})

test('summary unmount aborts its owned request', async () => {
  let receivedSignal
  const item = await mountSummary(async (_url, { signal }) => {
    receivedSignal = signal
    return new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })
  })
  item.dispose()
  assert.equal(receivedSignal.aborted, true)
})
