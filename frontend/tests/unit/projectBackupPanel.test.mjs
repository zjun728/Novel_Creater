import assert from 'node:assert/strict'
import test from 'node:test'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from '@vue/runtime-core'
import { createRenderer, nextTick, ssrContextKey } from '@vue/runtime-core'
import { createPinia, setActivePinia } from 'pinia'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
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
  createText: text => ({ ...makeNode('#text'), text: String(text) }),
  createComment: text => ({ ...makeNode('#comment'), text: String(text || '') }),
  setText: (node, text) => { node.text = String(text) },
  setElementText: (node, text) => { node.text = String(text); node.children = [] },
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
  for (let index = 0; index < 4; index += 1) await Promise.resolve()
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

let vite
let Panel
test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    appType: 'custom',
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false, ws: false },
    plugins: [vuePlugin()],
    optimizeDeps: { noDiscovery: true },
  })
  Panel = (await vite.ssrLoadModule('/src/components/projects/ProjectBackupPanel.vue')).default
  const source = await readFile(
    new URL('../../src/components/projects/ProjectBackupPanel.vue', import.meta.url),
    'utf8',
  )
  const { descriptor } = parse(source, { filename: 'ProjectBackupPanel.vue' })
  const script = compileScript(descriptor, { id: 'project-backup-panel' })
  Panel.render = new Function('Vue', compile(descriptor.template.content, {
    mode: 'function',
    prefixIdentifiers: true,
    bindingMetadata: script.bindings,
  }).code)(VueRuntime)
})

test.after(async () => { await vite?.close() })

async function mountPanel({ archived = false, flushCurrentDraft = async () => true, request } = {}) {
  const originalFetch = global.fetch
  const originalDocument = global.document
  const originalCreateObjectURL = URL.createObjectURL
  const originalRevokeObjectURL = URL.revokeObjectURL
  const requests = []
  const links = []
  const appended = []
  const revoked = []

  global.fetch = async (url, init = {}) => {
    requests.push([String(url), init])
    if (request) return request.promise
    return new Response(new Blob(['PK\u0003\u0004backup']), {
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': 'attachment; filename="novel-backup.zip"',
        'X-Package-SHA256': 'a'.repeat(64),
      },
    })
  }
  global.document = {
    createElement(tag) {
      assert.equal(tag, 'a')
      const link = {
        href: '', download: '', hidden: false, clicked: false, removed: false,
        click() { this.clicked = true },
        remove() { this.removed = true },
      }
      links.push(link)
      return link
    },
    body: { append(link) { appended.push(link) } },
  }
  URL.createObjectURL = () => 'blob:project-backup'
  URL.revokeObjectURL = value => { revoked.push(value) }

  const pinia = createPinia()
  setActivePinia(pinia)
  const target = makeNode('root')
  const app = renderer.createApp(Panel, {
    projectId: 'project / 一',
    title: '典镇山河',
    lifecycleRevision: 7,
    archived,
    flushCurrentDraft,
  })
  app.use(pinia)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(target)
  await flush()

  return {
    target, requests, links, appended, revoked,
    dispose() {
      app.unmount()
      global.fetch = originalFetch
      global.document = originalDocument
      URL.createObjectURL = originalCreateObjectURL
      URL.revokeObjectURL = originalRevokeObjectURL
    },
  }
}

test('active panel flushes, becomes busy, and saves the real binary response through a DOM anchor', async () => {
  const pending = deferred()
  let flushes = 0
  const item = await mountPanel({
    request: pending,
    flushCurrentDraft: async () => { flushes += 1; return true },
  })
  try {
    const button = find(item.target, node => node.type === 'button' && /创建项目备份/.test(text(node)))
    assert.ok(button)
    assert.equal(find(item.target, node => node.type === 'button' && /取消/.test(text(node))), null)

    const action = button.props.onClick()
    await flush()
    assert.equal(flushes, 1)
    assert.equal(button.props.disabled, true)
    assert.match(text(button), /正在创建备份/)

    pending.resolve(new Response(new Blob(['PK\u0003\u0004backup']), {
      headers: {
        'Content-Type': 'application/zip',
        'Content-Disposition': 'attachment; filename="novel-backup.zip"',
        'X-Package-SHA256': 'a'.repeat(64),
      },
    }))
    await action
    await flush()

    assert.equal(item.requests.length, 1)
    assert.match(item.requests[0][0], /\/api\/projects\/project%20%2F%20%E4%B8%80\/backup$/)
    assert.deepEqual(JSON.parse(item.requests[0][1].body), { expectedLifecycleRevision: 7 })
    assert.equal(item.links.length, 1)
    assert.equal(item.links[0].href, 'blob:project-backup')
    assert.equal(item.links[0].download, 'novel-backup.zip')
    assert.equal(item.links[0].hidden, true)
    assert.equal(item.links[0].clicked, true)
    assert.equal(item.links[0].removed, true)
    assert.deepEqual(item.appended, item.links)
    assert.deepEqual(item.revoked, ['blob:project-backup'])
  } finally { item.dispose() }
})

test('archived panel skips draft flush while retaining the exact lifecycle revision', async () => {
  let flushes = 0
  const item = await mountPanel({
    archived: true,
    flushCurrentDraft: async () => { flushes += 1; throw new Error('must not flush') },
  })
  try {
    const button = find(item.target, node => node.type === 'button' && /创建项目备份/.test(text(node)))
    await button.props.onClick()
    await flush()

    assert.equal(flushes, 0)
    assert.equal(item.requests.length, 1)
    assert.deepEqual(JSON.parse(item.requests[0][1].body), { expectedLifecycleRevision: 7 })
  } finally { item.dispose() }
})

test('backup failure exposes fixed retryable copy and restores the action without a cancel control', async () => {
  const pending = deferred()
  const item = await mountPanel({ request: pending })
  try {
    const button = find(item.target, node => node.type === 'button' && /创建项目备份/.test(text(node)))
    const action = button.props.onClick()
    await flush()
    pending.reject(new Error('private transport token'))
    await action
    await flush()

    assert.equal(button.props.disabled, false)
    assert.match(text(item.target), /创建项目备份失败，请重试。/)
    assert.doesNotMatch(text(item.target), /private transport token/)
    assert.equal(find(item.target, node => node.type === 'button' && /取消/.test(text(node))), null)
  } finally { item.dispose() }
})
