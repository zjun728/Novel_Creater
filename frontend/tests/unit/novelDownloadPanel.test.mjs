import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'
import { createRenderer, nextTick, ssrContextKey } from '@vue/runtime-core'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from '@vue/runtime-core'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('../..', import.meta.url))
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
    detach(child); child.parent = parent
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

let vite
let Panel
test.before(async () => {
  vite = await createServer({
    configFile: false, root, appType: 'custom', logLevel: 'error',
    server: { middlewareMode: true, hmr: false, ws: false },
    plugins: [vuePlugin()], optimizeDeps: { noDiscovery: true },
  })
  Panel = (await vite.ssrLoadModule('/src/components/projects/NovelDownloadPanel.vue')).default
  const source = await readFile(new URL('../../src/components/projects/NovelDownloadPanel.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source, { filename: 'NovelDownloadPanel.vue' })
  const script = compileScript(descriptor, { id: 'novel-download-panel' })
  Panel.render = new Function('Vue', compile(descriptor.template.content, {
    mode: 'function', prefixIdentifiers: true, bindingMetadata: script.bindings,
  }).code)(VueRuntime)
})
test.after(async () => { await vite?.close() })

async function mountPanel(options = {}) {
  const originalFetch = global.fetch
  const originalDocument = global.document
  const calls = []
  let optionAttempts = 0
  global.fetch = async (url, init = {}) => {
    calls.push([String(url), init])
    if (String(url).endsWith('/novel-download/options')) {
      optionAttempts += 1
      if (optionAttempts <= (options.failOptionAttempts || 0)) {
        throw new Error('transport-token-must-not-render')
      }
      return new Response(JSON.stringify(options.response || {
        available: true, reason: null, formats: ['txt', 'markdown'],
        volumes: [{ id: 'v-1', order: 1, title: '上卷' }],
        chapters: [{ number: 2, title: '第二章', volumeId: 'v-1' }],
      }), { headers: { 'content-type': 'application/json' } })
    }
    return new Response(new Blob(['正文']), {
      headers: { 'Content-Disposition': 'attachment; filename="book.txt"' },
    })
  }
  global.document = {
    createElement: () => ({ click() {}, remove() {} }),
    body: { append() {} },
  }
  const pinia = createPinia(); setActivePinia(pinia)
  const target = makeNode('root')
  const app = renderer.createApp(Panel, { projectId: 'p-1', title: '书名' })
  app.use(pinia); app.provide(ssrContextKey, { modules: new Set() }); app.mount(target); await flush()
  return { target, calls, dispose: () => {
    app.unmount(); global.fetch = originalFetch; global.document = originalDocument
  } }
}

test('panel loads book TXT by default and exposes scoped native selectors', async () => {
  const item = await mountPanel()
  try {
    assert.match(text(item.target), /下载定稿/)
    assert.match(text(item.target), /整本/)
    const scope = find(item.target, node => node.type === 'select' && node.props['aria-label'] === '下载范围')
    assert.equal(scope.props.value, 'book')
    assert.equal(find(item.target, node => node.props['aria-label'] === '选择分卷'), null)
    assert.equal(find(item.target, node => node.props['aria-label'] === '选择章节'), null)
    assert.match(text(item.target), /TXT/)
  } finally { item.dispose() }
})

test('scope selection sends only the relevant safe selector and never renders confirm, cancel, or body preview', async () => {
  const item = await mountPanel()
  try {
    const scope = find(item.target, node => node.props['aria-label'] === '下载范围')
    await scope.props.onChange({ target: { value: 'chapter' } }); await flush()
    const chapter = find(item.target, node => node.props['aria-label'] === '选择章节')
    assert.ok(chapter)
    await chapter.props.onChange({ target: { value: '2' } }); await flush()
    const button = find(item.target, node => node.type === 'button' && /下载章节/.test(text(node)))
    await button.props.onClick(); await flush()
    const request = new URL(item.calls.at(-1)[0])
    assert.equal(request.searchParams.get('scope'), 'chapter')
    assert.equal(request.searchParams.get('chapterNumber'), '2')
    assert.equal(request.searchParams.has('volumeId'), false)
    assert.equal(find(item.target, node => node.type === 'button' && /取消|确认/.test(text(node))), null)
    assert.equal(find(item.target, node => /正文预览/.test(text(node))), null)
  } finally { item.dispose() }
})

test('volume scope resets to its first safe option and excludes chapter selection', async () => {
  const item = await mountPanel()
  try {
    const scope = find(item.target, node => node.props['aria-label'] === '下载范围')
    await scope.props.onChange({ target: { value: 'volume' } }); await flush()
    const volume = find(item.target, node => node.props['aria-label'] === '选择分卷')
    assert.equal(volume.props.value, 'v-1')
    assert.equal(find(item.target, node => node.props['aria-label'] === '选择章节'), null)
    const button = find(item.target, node => node.type === 'button' && /下载分卷/.test(text(node)))
    await button.props.onClick(); await flush()
    const request = new URL(item.calls.at(-1)[0])
    assert.equal(request.searchParams.get('scope'), 'volume')
    assert.equal(request.searchParams.get('volumeId'), 'v-1')
    assert.equal(request.searchParams.has('chapterNumber'), false)
  } finally { item.dispose() }
})

test('fixed option-load failure offers a retry without exposing transport detail', async () => {
  const item = await mountPanel({ failOptionAttempts: 1 })
  try {
    assert.match(text(item.target), /下载选项加载失败，请重试。/)
    assert.doesNotMatch(text(item.target), /transport-token-must-not-render/)
    const retry = find(item.target, node => node.type === 'button' && /重新读取/.test(text(node)))
    await retry.props.onClick(); await flush()
    assert.doesNotMatch(text(item.target), /下载选项加载失败/)
    assert.equal(item.calls.filter(([url]) => url.endsWith('/novel-download/options')).length, 2)
  } finally { item.dispose() }
})

test('unavailable final chapters keep the delivery button disabled without requesting a download', async () => {
  const item = await mountPanel({ response: {
    available: false, reason: 'no_final', formats: ['txt'], volumes: [], chapters: [],
  } })
  try {
    assert.match(text(item.target), /尚无已定稿章节，无法下载/)
    const button = find(item.target, node => node.type === 'button')
    assert.equal(button.props.disabled, true)
    assert.equal(item.calls.filter(([url]) => url.includes('/novel-download?')).length, 0)
  } finally { item.dispose() }
})
