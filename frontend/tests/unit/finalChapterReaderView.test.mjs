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
const node = type => ({ type, text: '', props: {}, children: [], parent: null })
const detach = child => { if (child?.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1) }
const renderer = createRenderer({ patchProp(n, k, _o, v) { if (v == null) delete n.props[k]; else n.props[k] = v }, insert(c, p, a = null) { detach(c); c.parent = p; const i = a ? p.children.indexOf(a) : -1; if (i < 0) p.children.push(c); else p.children.splice(i, 0, c) }, remove: detach, createElement: node, createText: value => ({ ...node('#text'), text: String(value) }), createComment: value => ({ ...node('#comment'), text: String(value || '') }), setText: (n, v) => { n.text = String(v) }, setElementText: (n, v) => { n.text = String(v); n.children = [] }, parentNode: n => n?.parent || null, nextSibling: n => n?.parent?.children[n.parent.children.indexOf(n) + 1] || null, querySelector: () => null, setScopeId: (n, id) => { n.props[id] = '' }, cloneNode: n => ({ ...n, props: { ...n.props }, children: [...n.children], parent: null }), insertStaticContent(c, p, a) { const n = { ...node('#static'), text: c }; renderer.insert(n, p, a); return [n, n] } })
const textOf = n => [n?.text, ...(n?.children || []).map(textOf)].filter(Boolean).join(' ')
const find = (n, pred) => n && (pred(n) ? n : (n.children || []).map(child => find(child, pred)).find(Boolean))
async function flush() { for (let i = 0; i < 8; i += 1) await Promise.resolve(); await nextTick() }

let vite; let Reader
test.before(async () => {
  const stubId = '\0reader-naive'
  vite = await createServer({ configFile: false, root, appType: 'custom', logLevel: 'error', server: { middlewareMode: true, hmr: false, ws: false }, plugins: [vuePlugin(), { name: 'reader-naive', enforce: 'pre', resolveId: id => id === 'naive-ui' ? stubId : undefined, load: id => id === stubId ? `import {defineComponent,h} from 'vue';const c=n=>defineComponent({name:n,setup(_,x){return()=>h('div',x.attrs,x.slots.default?.())}});export const NButton=c('NButton');export const NResult=c('NResult');export const NSkeleton=c('NSkeleton')` : undefined }], ssr: { noExternal: ['naive-ui'] }, optimizeDeps: { noDiscovery: true } })
  Reader = (await vite.ssrLoadModule('/src/views/FinalChapterReaderView.vue')).default
  const source = await readFile(new URL('../../src/views/FinalChapterReaderView.vue', import.meta.url), 'utf8'); const { descriptor } = parse(source); Reader.render = new Function('Vue', compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(descriptor, { id: 'reader' }).bindings }).code)(VueRuntime)
  for (const path of ['components/manuscript/FinalChapterArticle.vue', 'components/manuscript/FinalOutlinePanel.vue']) { const component = (await vite.ssrLoadModule(`/src/${path}`)).default; const value = await readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8'); const parsed = parse(value).descriptor; component.render = new Function('Vue', compile(parsed.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(parsed, { id: path }).bindings }).code)(VueRuntime) }
})
test.after(async () => { await vite?.close() })
const chapter = (id = 'p', number = 2, lifecycle = 'active') => ({ projectId: id, projectTitle: '书名', lifecycle, volume: { id: 'v', order: 1, title: '卷一' }, chapter: { number, title: '章名', content: '<b>第一段</b>\n\n第二段', scalarCount: 15, finalizedAt: '2026-01-01T00:00:00Z' }, outline: { chapterGoal: '目标', expectedCharacters: [], continuation: [], plannedTasks: [], scenes: [], forbiddenEarlyEvents: [] }, navigation: { previousChapterNumber: 1, nextChapterNumber: 5 } })
const response = body => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
async function mount(path = '/projects/p/manuscript/chapters/2') {
  const originalFetch = global.fetch; const originalDocument = global.document; const calls = []
  global.document = { createElement: () => ({ click() {}, remove() {} }), body: { append() {} } }
  global.fetch = async (url, init = {}) => { const value = String(url); calls.push(value); if (value.endsWith('/preparation')) return response({ lifecycle: 'active', activeSelection: 'current', contract: 'draft', bible: 'missing', planning: 'missing', outline: 'missing', authoritativeChapterNumber: 3, modelTasks: [], capabilities: {}, nextAction: 'continue_contract', targetPath: '/projects/p/contract', reasons: [] }); if (value.endsWith('/novel-download/options')) return response({ available: true, reason: null, formats: ['txt', 'markdown'], volumes: [], chapters: [{ number: 2, title: '章名', volumeId: 'v' }] }); if (value.includes('/manuscript/chapters/')) return response(chapter()); return new Response(new Blob(['x']), { headers: { 'content-disposition': 'attachment; filename="x.txt"' } }) }
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/manuscript/chapters/:chapterNumber', component: Reader }, { path: '/projects/:projectId/manuscript', component: { render: () => null } }, { path: '/projects/:projectId/contract', component: { render: () => null } }] }); await router.push(path); await router.isReady(); const target = node('root'); const app = renderer.createApp({ render: () => VueRuntime.h(RouterView) }); const pinia = createPinia(); setActivePinia(pinia); app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.mount(target); await flush(); await flush(); return { target, router, calls, dispose() { app.unmount(); global.fetch = originalFetch; global.document = originalDocument } }
}

test('mounted reader switches text and outline by query without reloading chapter flow', async () => {
  const item = await mount()
  try { assert.match(textOf(item.target), /<b>第一段<\/b>.*第二段/); const before = item.calls.length; await item.router.push({ query: { view: 'outline' } }); await flush(); assert.match(textOf(item.target), /本章小纲.*目标.*无/); assert.equal(item.calls.length, before); await item.router.push({ query: { view: 'text' } }); await flush(); assert.match(textOf(item.target), /第一段/) } finally { item.dispose() }
})

test('mounted reader uses response navigation and has no author write controls', async () => {
  const item = await mount()
  try { assert.ok(find(item.target, n => n.props.href === '/projects/p/manuscript/chapters/1')); assert.ok(find(item.target, n => n.props.href === '/projects/p/manuscript/chapters/5')); assert.equal(find(item.target, n => n.type === 'textarea' || n.props.contenteditable), undefined); assert.doesNotMatch(textOf(item.target), /编辑本章|提交|生成/) } finally { item.dispose() }
})

test('reader keeps query view local, renders only readonly prose and response navigation', async () => {
  const source = await readFile(new URL('../../src/views/FinalChapterReaderView.vue', import.meta.url), 'utf8')
  assert.match(source, /route\.query\.view === 'outline'/)
  assert.match(source, /router\.replace/)
  assert.match(source, /watch\(\(\) => route\.query\.view/)
  assert.match(source, /watch\(\[projectId, chapterNumber\]/)
  assert.match(source, /navigation\.previousChapterNumber/)
  assert.match(source, /navigation\.nextChapterNumber/)
  assert.match(source, /不属于作品稿件/)
  assert.doesNotMatch(source, /v-html|contenteditable|编辑本章|重新打开会话/)
})

test('reader keeps download and creation state local to verified chapter content', async () => {
  const source = await readFile(new URL('../../src/views/FinalChapterReaderView.vue', import.meta.url), 'utf8')
  assert.match(source, /createNovelDownloadController/)
  assert.match(source, /scope: 'chapter'/)
  assert.match(source, /download\.error\.value/)
  assert.match(source, /manuscript\.loadPreparation/)
  assert.match(source, /data\.lifecycle === 'active'/)
  assert.match(source, /link\.hidden = true[\s\S]*document\.body\.append\(link\)[\s\S]*link\.remove\(\)/)
  assert.match(source, /manuscript\.loadContent\(id, 0\)/)
})

test('article and outline components keep author content plain and bounded', async () => {
  const [article, outline] = await Promise.all([
    readFile(new URL('../../src/components/manuscript/FinalChapterArticle.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/manuscript/FinalOutlinePanel.vue', import.meta.url), 'utf8'),
  ])
  assert.match(article, /split\(\/\\n/)
  assert.doesNotMatch(article, /v-html|JSON\.stringify|markdown/i)
  assert.match(outline, /chapterGoal.*expectedCharacters.*continuation.*plannedTasks.*scenes.*forbiddenEarlyEvents/s)
})
