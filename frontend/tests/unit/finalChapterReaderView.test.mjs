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
const node = type => ({ type, text: '', props: {}, children: [], parent: null, focused: false, focus() { this.focused = true }, closest() { return null } })
const detach = child => { if (child?.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1) }
const renderer = createRenderer({ patchProp(n, k, _o, v) { if (v == null) delete n.props[k]; else n.props[k] = v }, insert(c, p, a = null) { detach(c); c.parent = p; const i = a ? p.children.indexOf(a) : -1; if (i < 0) p.children.push(c); else p.children.splice(i, 0, c) }, remove: detach, createElement: node, createText: value => ({ ...node('#text'), text: String(value) }), createComment: value => ({ ...node('#comment'), text: String(value || '') }), setText: (n, v) => { n.text = String(v) }, setElementText: (n, v) => { n.text = String(v); n.children = [] }, parentNode: n => n?.parent || null, nextSibling: n => n?.parent?.children[n.parent.children.indexOf(n) + 1] || null, querySelector: () => null, setScopeId: (n, id) => { n.props[id] = '' }, cloneNode: n => ({ ...n, props: { ...n.props }, children: [...n.children], parent: null }), insertStaticContent(c, p, a) { const n = { ...node('#static'), text: c }; renderer.insert(n, p, a); return [n, n] } })
const textOf = n => [n?.text, ...(n?.children || []).map(textOf)].filter(Boolean).join(' ')
const find = (n, pred) => n && (pred(n) ? n : (n.children || []).map(child => find(child, pred)).find(Boolean))
async function flush() { for (let i = 0; i < 8; i += 1) await Promise.resolve(); await nextTick() }
async function waitFor(predicate, message) { for (let index = 0; index < 20; index += 1) { const value = predicate(); if (value) return value; await new Promise(resolve => setImmediate(resolve)); await flush() } assert.fail(message) }
function deferred() { let resolve; let reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

let vite; let Reader
test.before(async () => {
  const stubId = '\0reader-naive'
  vite = await createServer({ configFile: false, root, appType: 'custom', logLevel: 'error', server: { middlewareMode: true, hmr: false, ws: false }, plugins: [vuePlugin(), { name: 'reader-naive', enforce: 'pre', resolveId: id => id === 'naive-ui' ? stubId : undefined, load: id => id === stubId ? `import {defineComponent,h} from 'vue';const children=s=>Object.values(s).flatMap(x=>x?.()||[]);const c=n=>defineComponent({name:n,setup(_,x){return()=>h('div',x.attrs,children(x.slots))}});export const NButton=defineComponent({name:'NButton',setup(_,x){return()=>h('button',x.attrs,children(x.slots))}});export const NResult=defineComponent({name:'NResult',setup(_,x){return()=>h('div',x.attrs,[x.attrs.title,x.attrs.description,...children(x.slots)])}});export const NSkeleton=c('NSkeleton')` : undefined }], ssr: { noExternal: ['naive-ui'] }, optimizeDeps: { noDiscovery: true } })
  Reader = (await vite.ssrLoadModule('/src/views/FinalChapterReaderView.vue')).default
  const source = await readFile(new URL('../../src/views/FinalChapterReaderView.vue', import.meta.url), 'utf8'); const { descriptor } = parse(source); Reader.render = new Function('Vue', compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(descriptor, { id: 'reader' }).bindings }).code)(VueRuntime)
  for (const path of ['components/manuscript/FinalChapterArticle.vue', 'components/manuscript/FinalOutlinePanel.vue']) { const component = (await vite.ssrLoadModule(`/src/${path}`)).default; const value = await readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8'); const parsed = parse(value).descriptor; component.render = new Function('Vue', compile(parsed.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: compileScript(parsed, { id: path }).bindings }).code)(VueRuntime) }
})
test.after(async () => { await vite?.close() })
const chapter = (id = 'p', number = 2, lifecycle = 'active') => ({ projectId: id, projectTitle: '书名', lifecycle, volume: { id: 'v', order: 1, title: '卷一' }, chapter: { number, title: `${number}章名`, content: '<b>第一段</b>\n\n第二段', scalarCount: 15, finalizedAt: '2026-01-01T00:00:00Z' }, outline: { chapterGoal: '目标', expectedCharacters: [], continuation: [], plannedTasks: [], scenes: [], forbiddenEarlyEvents: [] }, navigation: { previousChapterNumber: number === 2 ? 1 : number - 1, nextChapterNumber: number === 2 ? 5 : number + 3 } })
const response = body => new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } })
const errorResponse = (code, status = 500) => new Response(JSON.stringify({ code, message: 'private transport detail', correlationId: 'safe_1' }), { status, headers: { 'content-type': 'application/json' } })
const preparation = (lifecycle = 'active', id = 'p') => ({ lifecycle, activeSelection: 'current', contract: 'draft', bible: 'missing', planning: 'missing', outline: 'missing', authoritativeChapterNumber: 3, modelTasks: [], capabilities: {}, nextAction: lifecycle === 'archived' ? 'archived_read_only' : 'continue_contract', targetPath: lifecycle === 'archived' ? null : `/projects/${id}/contract`, reasons: [] })
const options = number => ({ available: true, reason: null, formats: ['txt', 'markdown'], volumes: [], chapters: [{ number, title: '章名', volumeId: 'v' }] })
async function mount(path = '/projects/p/manuscript/chapters/2', { fetchOverride, lifecycle = 'active' } = {}) {
  const originalFetch = global.fetch; const originalDocument = global.document; const calls = []
  const anchors = []
  let app
  global.document = { createElement: () => { const anchor = { click() {}, remove() {} }; anchors.push(anchor); return anchor }, body: { append() {} } }
  global.fetch = async (url, init = {}) => {
    const value = String(url); calls.push([value, init])
    if (fetchOverride) { const result = fetchOverride(value, init, calls); if (result !== undefined) return result }
    const match = value.match(/\/projects\/([^/]+)\/manuscript\/chapters\/(\d+)$/u)
    if (match) return response(chapter(decodeURIComponent(match[1]), Number(match[2]), lifecycle))
    if (value.endsWith('/preparation')) return response(preparation(lifecycle, decodeURIComponent(value.match(/\/projects\/([^/]+)\/preparation$/u)?.[1] || 'p')))
    if (value.endsWith('/novel-download/options')) return response(options(Number(new URL(path, 'http://x').pathname.split('/').at(-1))))
    return new Response(new Blob(['x']), { headers: { 'content-disposition': 'attachment; filename="x.txt"' } })
  }
  try {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects', component: { render: () => null } }, { path: '/projects/:projectId/manuscript/chapters/:chapterNumber', component: Reader }, { path: '/projects/:projectId/manuscript', component: { render: () => null } }, { path: '/projects/:projectId/contract', component: { render: () => null } }, { path: '/projects/:projectId/writer/:chapterNumber', component: { render: () => null } }] })
    await router.push(path); await router.isReady()
    const target = node('root'); app = renderer.createApp({ render: () => VueRuntime.h(RouterView) }); const pinia = createPinia(); setActivePinia(pinia); app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.mount(target); await flush(); await flush()
    return { target, router, calls, anchors, dispose() { app.unmount(); global.fetch = originalFetch; global.document = originalDocument } }
  } catch (error) {
    try { app?.unmount() } finally { global.fetch = originalFetch; global.document = originalDocument }
    throw error
  }
}

test('mounted reader switches text and outline by query without reloading chapter flow', async () => {
  const item = await mount('/projects/p/manuscript/chapters/2?view=text')
  try {
    assert.match(textOf(item.target), /<b>第一段<\/b>.*第二段/, JSON.stringify(item.calls))
    const title = find(item.target, n => n.type === 'h1')
    assert.equal(title.focused, true)
    title.focused = false
    const counts = () => ({ chapter: item.calls.filter(([url]) => /\/manuscript\/chapters\/2$/.test(url)).length, preparation: item.calls.filter(([url]) => url.endsWith('/preparation')).length, options: item.calls.filter(([url]) => url.endsWith('/novel-download/options')).length })
    assert.deepEqual(counts(), { chapter: 1, preparation: 1, options: 1 })
    await item.router.push({ query: { view: 'outline' } }); await flush()
    assert.match(textOf(item.target), /本章小纲.*目标.*无/)
    assert.equal(title.focused, false)
    assert.deepEqual(counts(), { chapter: 1, preparation: 1, options: 1 })
    item.router.back(); await waitFor(() => item.router.currentRoute.value.query.view === 'text', 'browser back did not restore text view')
    assert.match(textOf(item.target), /<b>第一段<\/b>/)
    item.router.forward(); await waitFor(() => item.router.currentRoute.value.query.view === 'outline', 'browser forward did not restore outline view')
    assert.match(textOf(item.target), /本章小纲/)
    assert.deepEqual(counts(), { chapter: 1, preparation: 1, options: 1 })
    await item.router.push({ query: { view: 'private-invalid' } }); await waitFor(() => item.router.currentRoute.value.query.view === 'text', 'invalid view was not normalized with replace')
    assert.match(textOf(item.target), /<b>第一段<\/b>/)
    item.router.back(); await waitFor(() => item.router.currentRoute.value.query.view === 'outline', 'invalid view normalization added a history entry instead of replacing it')
    assert.match(textOf(item.target), /本章小纲/)
    assert.deepEqual(counts(), { chapter: 1, preparation: 1, options: 1 })
  } finally { item.dispose() }
})

test('mounted reader uses response navigation and has no author write controls', async () => {
  const item = await mount()
  try {
    assert.ok(find(item.target, n => n.props.href === '/projects/p/manuscript/chapters/1')); assert.ok(find(item.target, n => n.props.href === '/projects/p/manuscript/chapters/5'))
    const rendered = textOf(item.target)
    assert.ok(rendered.indexOf('下一篇') < rendered.indexOf('继续创作契约'))
    assert.equal(find(item.target, n => n.type === 'textarea' || n.props.contenteditable), undefined); assert.doesNotMatch(rendered, /编辑本章|提交|生成/)
  } finally { item.dispose() }
})

test('mounted reader fences a late chapter when project and chapter change', async () => {
  const late = deferred()
  const item = await mount('/projects/p/manuscript/chapters/2', { fetchOverride(value) {
    if (value.endsWith('/projects/p/manuscript/chapters/3')) return late.promise
    if (value.endsWith('/projects/q/manuscript/chapters/7')) return response(chapter('q', 7))
    if (value.endsWith('/projects/q/preparation')) return response(preparation('active', 'q'))
    if (value.endsWith('/projects/q/novel-download/options')) return response(options(7))
    return undefined
  } })
  try {
    await item.router.push('/projects/p/manuscript/chapters/3'); await flush()
    await item.router.push('/projects/q/manuscript/chapters/7'); await flush(); await flush()
    assert.match(textOf(item.target), /第 7 章 · 7章名/, JSON.stringify(item.calls))
    assert.equal(find(item.target, n => n.type === 'h1').focused, true)
    late.resolve(response(chapter('p', 3))); await flush(); await flush()
    assert.match(textOf(item.target), /第 7 章 · 7章名/)
    assert.doesNotMatch(textOf(item.target), /3章名/)
  } finally { late.resolve(response(chapter('p', 3))); item.dispose() }
})

test('missing chapter keeps an independently loaded action while archived prose has no creation action', async () => {
  const missing = await mount('/projects/p/manuscript/chapters/9', { fetchOverride(value) {
    if (value.endsWith('/manuscript/chapters/9')) return errorResponse('FinalChapterNotFound', 404)
    return undefined
  } })
  try {
    assert.match(textOf(missing.target), /不属于作品稿件/)
    assert.match(textOf(missing.target), /继续创作契约/)
    assert.ok(find(missing.target, n => n.props.href === '/projects/p/contract'))
    assert.equal(missing.calls.filter(([url]) => url.endsWith('/novel-download/options')).length, 0)
  } finally { missing.dispose() }

  const archived = await mount('/projects/p/manuscript/chapters/2', { lifecycle: 'archived' })
  try {
    assert.match(textOf(archived.target), /<b>第一段<\/b>/)
    assert.doesNotMatch(textOf(archived.target), /继续创作/)
  } finally { archived.dispose() }
})

test('chapter download uses the exact selector and a safe local failure never hides prose', async () => {
  let downloadAttempts = 0
  const item = await mount('/projects/p/manuscript/chapters/2', { fetchOverride(value) {
    if (value.includes('/novel-download?')) { downloadAttempts += 1; return downloadAttempts === 1 ? errorResponse('NovelDownloadUnavailable', 503) : undefined }
    return undefined
  } })
  try {
    const button = find(item.target, n => n.type === 'button' && /下载 TXT/.test(textOf(n)))
    assert.ok(button)
    await button.props.onClick(); await flush(); await flush()
    const request = item.calls.find(([url]) => url.includes('/novel-download?'))?.[0]
    const query = new URL(request).searchParams
    assert.equal(query.get('scope'), 'chapter'); assert.equal(query.get('chapterNumber'), '2'); assert.equal(query.get('format'), 'txt')
    assert.match(textOf(item.target), /<b>第一段<\/b>/)
    assert.match(textOf(item.target), /下载失败，请重试/)
    assert.doesNotMatch(textOf(item.target), /private transport detail|NovelDownloadUnavailable/)
    await item.router.push('/projects/p/manuscript/chapters/5'); await flush(); await flush()
    assert.match(textOf(item.target), /第 5 章 · 5章名/)
    assert.doesNotMatch(textOf(item.target), /下载失败，请重试/)
  } finally { item.dispose() }
})

test('integrity and invalid addresses fail closed without prose or outline', async () => {
  const integrity = await mount('/projects/p/manuscript/chapters/2?view=outline', { fetchOverride(value) {
    if (value.endsWith('/manuscript/chapters/2')) return errorResponse('ManuscriptIntegrityFailure')
    return undefined
  } })
  try {
    assert.match(textOf(integrity.target), /章节定稿暂时不可用/)
    assert.doesNotMatch(textOf(integrity.target), /第一段|本章小纲|目标/)
  } finally { integrity.dispose() }

  const invalid = await mount('/projects/p/manuscript/chapters/02')
  try {
    assert.match(textOf(invalid.target), /章节地址无效/)
    assert.equal(invalid.calls.filter(([url]) => url.includes('/manuscript/chapters/')).length, 0)
  } finally { invalid.dispose() }
})

test('missing projects and independent preparation or option failures remain actionable', async () => {
  const missing = await mount('/projects/gone/manuscript/chapters/2', { fetchOverride(value) {
    if (value.endsWith('/projects/gone/manuscript/chapters/2')) return errorResponse('ManuscriptProjectNotFound', 404)
    if (value.endsWith('/projects/gone/preparation')) return response(preparation('active', 'gone'))
    return undefined
  } })
  try {
    assert.match(textOf(missing.target), /项目不存在或已被删除.*返回项目库/)
    assert.doesNotMatch(textOf(missing.target), /继续创作契约/)
  } finally { missing.dispose() }

  let preparationAttempts = 0; let optionAttempts = 0
  const failures = await mount('/projects/p/manuscript/chapters/2', { fetchOverride(value) {
    if (value.endsWith('/preparation')) { preparationAttempts += 1; return preparationAttempts === 1 ? Promise.reject(new Error('private preparation')) : response(preparation()) }
    if (value.endsWith('/novel-download/options')) { optionAttempts += 1; return optionAttempts === 1 ? Promise.reject(new Error('private options')) : response(options(2)) }
    return undefined
  } })
  try {
    assert.match(textOf(failures.target), /<b>第一段<\/b>/)
    assert.match(textOf(failures.target), /创作状态暂时无法读取/)
    assert.match(textOf(failures.target), /下载选项加载失败/)
    assert.doesNotMatch(textOf(failures.target), /private preparation|private options/)
    const prepRetry = find(failures.target, n => n.type === 'button' && /重新读取创作状态/.test(textOf(n)))
    const optionRetry = find(failures.target, n => n.type === 'button' && /重新读取下载选项/.test(textOf(n)))
    await prepRetry.props.onClick(); await optionRetry.props.onClick(); await flush(); await flush()
    assert.match(textOf(failures.target), /继续创作契约/)
    assert.match(textOf(failures.target), /下载本章定稿/)
  } finally { failures.dispose() }
})

test('final prose preserves non-separator whitespace and outline uses exactly the approved author labels', async () => {
  const spaced = chapter()
  spaced.chapter.content = '  第一段  \n\n第二段'
  spaced.chapter.scalarCount = 12
  const item = await mount('/projects/p/manuscript/chapters/2?view=text', { fetchOverride(value) {
    if (value.endsWith('/manuscript/chapters/2')) return response(spaced)
    return undefined
  } })
  try {
    const article = find(item.target, n => n.type === 'article')
    assert.deepEqual(article.children.filter(n => n.type === 'p').map(n => n.text), ['  第一段  ', '第二段'])
    await item.router.push({ query: { view: 'outline' } }); await flush()
    const rendered = textOf(item.target)
    for (const label of ['本章目标', '预计人物', '延续项', '计划任务', '场景', '禁止提前发生事项']) assert.match(rendered, new RegExp(label))
    assert.doesNotMatch(rendered, /章节目标|预期人物|承接关系|revision|hash|basis|projection|canon/i)
  } finally { item.dispose() }
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
  assert.match(source, /!isArchived && !\['idle', 'loading', 'invalid-address', 'missing-project'\]\.includes\(status\)/)
  assert.match(source, /preparation\.status === 'ready'/)
  assert.match(source, /link\.hidden = true[\s\S]*document\.body\.append\(link\)[\s\S]*link\.remove\(\)/)
  assert.match(source, /manuscript\.loadContent\(id, 0\)/)
  assert.match(source, /\.final-reader__action:hover/)
  assert.doesNotMatch(source, /:is\(a, nav a\)/)
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
