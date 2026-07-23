import assert from 'node:assert/strict'
import { access, readdir, readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from '@vue/runtime-core'
import { createRenderer, nextTick, ssrContextKey } from '@vue/runtime-core'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { createServer } from 'vite'
import vuePlugin from '@vitejs/plugin-vue'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const source = path => new URL(`../../src/${path}`, import.meta.url)
const bible = () => ({
  premiseAndPromise: 'promise', powerOrProgressionSystem: 'power', protagonist: 'hero', toneAndNarrativeBoundaries: 'tone',
  worldRules: [{ id: 'world-1', text: 'rule' }], coreCast: [{ id: 'cast-1', text: 'cast' }], factions: [{ id: 'faction-1', text: 'faction' }],
  longTermConflicts: [{ id: 'conflict-1', text: 'conflict' }], relationshipDynamics: [{ id: 'relation-1', text: 'relation' }],
  continuityGuardrails: [{ id: 'guard-1', text: 'guard' }], openDesignQuestions: [{ id: 'question-1', text: 'question' }],
})

function node(type, text = '') {
  return {
    type,
    text,
    props: {},
    children: [],
    parent: null,
    isConnected: true,
    focus() { this.focused = true; if (globalThis.document) globalThis.document.activeElement = this },
    hasAttribute(name) { return Object.hasOwn(this.props, name) },
    getAttribute(name) { return this.props[name] ?? null },
    setAttribute(name, value) { this.props[name] = value },
    removeAttribute(name) { delete this.props[name] },
    querySelectorAll() {
      return walk(this).filter(value => (
        ['button', 'input', 'textarea', 'a'].includes(value.type)
        && value.props.disabled !== true
        && value.props.tabindex !== '-1'
      ))
    },
  }
}
function detach(child) { if (!child?.parent) return; child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null }
const renderer = createRenderer({
  patchProp(el, key, _old, value) { if (value == null) delete el.props[key]; else el.props[key] = value },
  insert(child, parent, anchor = null) { detach(child); child.parent = parent; const at = anchor ? parent.children.indexOf(anchor) : -1; if (at < 0) parent.children.push(child); else parent.children.splice(at, 0, child) },
  remove: detach, createElement: type => node(type), createText: text => node('#text', String(text)), createComment: text => node('#comment', String(text || '')),
  setText(target, text) { target.text = String(text) }, setElementText(target, text) { target.text = String(text); target.children = [] },
  parentNode: target => target?.parent || null, nextSibling: target => target?.parent?.children[target.parent.children.indexOf(target) + 1] || null,
  querySelector: selector => globalThis.document?.querySelector?.(selector) ?? null, setScopeId(el, id) { el.props[id] = '' }, cloneNode: target => ({ ...target, props: { ...target.props }, children: [...target.children], parent: null }),
  insertStaticContent(content, parent, anchor) { const target = node('#static', content); renderer.insert(target, parent, anchor); return [target, target] },
})
function walk(root, all = []) { if (!root) return all; all.push(root); for (const child of root.children || []) walk(child, all); return all }
function walkParents(target) { const parents = []; for (let value = target; value; value = value.parent) parents.push(value); return parents }
function text(root) { return [root.text || '', ...(root.children || []).map(text)].join('') }
function byText(root, value) { return walk(root).find(item => item.type === 'button' && text(item).trim() === value) }
async function flush() { for (let index = 0; index < 4; index += 1) await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
async function waitFor(predicate, message) {
  for (let index = 0; index < 20; index += 1) {
    const value = predicate()
    if (value) return value
    await flush()
  }
  assert.fail(typeof message === 'function' ? message() : message)
}
function deferred() {
  let resolve; let reject
  const promise = new Promise((onResolve, onReject) => { resolve = onResolve; reject = onReject })
  return { promise, resolve, reject }
}
async function clientRender(path) {
  const contents = await readFile(source(path), 'utf8'); const filename = path.split('/').at(-1)
  const { descriptor } = parse(contents, { filename }); const script = compileScript(descriptor, { id: `bible-${filename}` })
  const result = compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: script.bindings })
  return new Function('Vue', result.code)({ ...VueRuntime, withModifiers: handler => handler, withKeys: handler => handler })
}
async function compiledTemplate(path) {
  const contents = await readFile(source(path), 'utf8'); const filename = path.split('/').at(-1)
  const { descriptor } = parse(contents, { filename }); const script = compileScript(descriptor, { id: `bible-template-${filename}` })
  return compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: script.bindings }).code
}
async function allSourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true })
  const nested = await Promise.all(entries.map(entry => entry.isDirectory() ? allSourceFiles(`${directory}/${entry.name}`) : [`${directory}/${entry.name}`]))
  return nested.flat()
}

test('retired Bible workspace files are physically absent', async () => {
  for (const path of ['views/WriterView.vue', 'components/bible/CreativeBible.vue', 'components/bible/CharacterArcView.vue', 'components/bible/PlotThreadBoard.vue', 'prompts/bibleFromSeed.js', 'prompts/settingsFromBible.js']) await assert.rejects(access(source(path)))
})

test('the recursive source inventory has no retired Bible workspace imports', async () => {
  const root = fileURLToPath(new URL('../../src', import.meta.url)); const files = await allSourceFiles(root)
  const contents = await Promise.all(files.filter(path => /\.(?:js|vue)$/.test(path)).map(path => readFile(path, 'utf8')))
  for (const value of contents) {
    assert.doesNotMatch(value, /(?:CreativeBible|CharacterArcView|PlotThreadBoard|bibleFromSeed|settingsFromBible)/)
  }
})

test('Vite compiles the page through its controller and SSR renders the 11-field disabled preview and history detail', async () => {
  const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  try {
    const [Page, Editor, Drawer] = await Promise.all([
      vite.ssrLoadModule('/src/views/ProjectBibleView.vue'), vite.ssrLoadModule('/src/components/bible/BibleEditor.vue'), vite.ssrLoadModule('/src/components/bible/BibleHistoryDrawer.vue'),
    ])
    assert.equal(typeof Page.default.setup, 'function')
    const preview = await renderToString(createSSRApp({ render: () => h(Editor.default, { modelValue: bible(), disabled: true }) }))
    assert.match(preview, /作品承诺/); assert.match(preview, /开放设计问题/); assert.match(preview, /disabled/)
    const drawer = await renderToString(createSSRApp({ render: () => h(Drawer.default, { open: true, busy: true, history: [{ revision: 3, canClone: true }], historyDetail: { revision: 3, bible: bible(), reasons: ['selection_missing'], basis: { seedId: 'seed-1', policyVersion: 'v1' } } }) }))
    assert.match(drawer, /Revision 3/); assert.match(drawer, /查看详情/); assert.match(drawer, /开放设计问题/)
    assert.match(drawer, /<dl/); assert.doesNotMatch(drawer, /\[object Object\]/)
  } finally { await vite.close() }
})

test('the Vite-loaded BibleEditor emits scalar/list edits and renders disabled controls', async () => {
  const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  try {
    const Editor = (await vite.ssrLoadModule('/src/components/bible/BibleEditor.vue')).default
    Editor.render = await clientRender('components/bible/BibleEditor.vue')
    const emitted = []; const root = node('root'); const existing = bible(); existing.worldRules = [{ id: 'design-worldRules-1', text: 'existing' }]
    const app = renderer.createApp(Editor, { modelValue: existing, disabled: false, 'onUpdate:modelValue': value => emitted.push(value) })
    app.provide(ssrContextKey, { modules: new Set() }); app.mount(root)
    const scalar = walk(root).find(item => item.type === 'textarea' && item.props.value === 'promise')
    scalar.props.onInput({ target: { value: 'changed promise' } }); await nextTick()
    assert.equal(emitted.at(-1).premiseAndPromise, 'changed promise')
    byText(root, '新增世界规则').props.onClick(); await nextTick()
    assert.equal(emitted.at(-1).worldRules.length, 2)
    assert.equal(emitted.at(-1).worldRules[1].id, 'design-worldRules-2')
    byText(root, '删除').props.onClick(); await nextTick()
    assert.equal(emitted.at(-1).worldRules.length, 0)
    const disabledRoot = node('root'); const disabledApp = renderer.createApp(Editor, { modelValue: bible(), disabled: true })
    disabledApp.provide(ssrContextKey, { modules: new Set() }); disabledApp.mount(disabledRoot)
    assert.ok(walk(disabledRoot).filter(item => item.type === 'textarea' || item.type === 'button').every(item => item.props.disabled === true))
  } finally { await vite.close() }
})

test('read-only BibleEditor keeps textareas focusable/copyable but does not emit edits or show list controls', async () => {
  const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  try {
    const Editor = (await vite.ssrLoadModule('/src/components/bible/BibleEditor.vue')).default; Editor.render = await clientRender('components/bible/BibleEditor.vue')
    const emitted = []; const root = node('root'); const app = renderer.createApp(Editor, { modelValue: bible(), readOnly: true, 'onUpdate:modelValue': value => emitted.push(value) })
    app.provide(ssrContextKey, { modules: new Set() }); app.mount(root)
    const areas = walk(root).filter(item => item.type === 'textarea')
    assert.ok(areas.length > 0 && areas.every(item => item.props.readonly === true && item.props.disabled !== true))
    assert.equal(walk(root).some(item => item.type === 'button' && /新增|删除/.test(text(item))), false)
    assert.equal(areas[0].props.onInput, undefined); assert.equal(emitted.length, 0)
  } finally { await vite.close() }
})

test('compiled workspace template exposes an inert busy region and a sibling live status overlay', async () => {
  const page = await compiledTemplate('views/ProjectBibleView.vue')
  assert.match(page, /aria-busy/); assert.match(page, /inert/); assert.match(page, /role: "status"/)
  assert.match(page, /AI 辅助/)
  assert.match(page, /authorInstructions/)
  assert.match(page, /生成创作圣经/)
  assert.match(page, /请先保存/)
})

test('ProjectBibleView derives AI readiness from the planning binding item only', async () => {
  const page = await readFile(source('views/ProjectBibleView.vue'), 'utf8')
  assert.match(page, /useModelBindingStore/)
  assert.match(page, /taskKey === 'planning'/)
  assert.match(page, /resolutionStatus === 'bound'/)
  assert.doesNotMatch(page, /bindingStore\.bindingReady/)
  assert.doesNotMatch(page, /下一阶段接入/)
})

test('mounted ProjectBibleView follows first, head-only, superseded, and archived route states through real Pinia/router/fetch', async () => {
  const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  const originalFetch = global.fetch; const originalWindow = global.window; const puts = []; const clones = []; let allowLeave = false
  const item = id => [{ id, text: id }]
  const makeDraft = (id, extra = {}) => ({ projectId: id, lifecycle: 'active', status: 'editable', draftId: 'draft-1', draftVersion: 1, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [], ...extra })
  const makeHead = (id, extra = {}) => ({ projectId: id, lifecycle: 'active', status: 'current', revision: 7, bible: bible(), canClone: true, reasons: [], ...extra })
  try {
    const [Page, Editor, Drawer] = await Promise.all([vite.ssrLoadModule('/src/views/ProjectBibleView.vue'), vite.ssrLoadModule('/src/components/bible/BibleEditor.vue'), vite.ssrLoadModule('/src/components/bible/BibleHistoryDrawer.vue')])
    Page.default.render = await clientRender('views/ProjectBibleView.vue'); Editor.default.render = await clientRender('components/bible/BibleEditor.vue'); Drawer.default.render = await clientRender('components/bible/BibleHistoryDrawer.vue')
    global.window = { confirm: () => allowLeave, addEventListener() {}, removeEventListener() {} }
    global.fetch = async (url, options = {}) => {
      const path = String(url); const id = path.match(/projects\/([^/]+)/)?.[1]
      if (options.method === 'PUT') {
        puts.push(JSON.parse(options.body))
        return new Response(JSON.stringify(makeDraft(id, { draftVersion: 1 })), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/draft/clone')) { clones.push(JSON.parse(options.body)); return new Response(JSON.stringify(makeDraft(id, { draftVersion: 2 })), { headers: { 'content-type': 'application/json' } }) }
      if (path.endsWith('/bible/head')) {
        const value = id === 'first' ? makeHead(id, { revision: 0, bible: null, canClone: false }) : id === 'head' ? makeHead(id, { reasons: ['bible_head_changed'] }) : id === 'archived' ? makeHead(id, { lifecycle: 'archived', canClone: false, bible: { ...bible(), premiseAndPromise: 'ARCHIVED HEAD' }, reasons: ['project_archived'] }) : makeHead(id)
        return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/draft')) {
        const value = id === 'first' ? makeDraft(id, { draftId: null, draftVersion: null, status: 'missing', draft: null, canConfirm: false }) : id === 'head' ? makeDraft(id, { draftId: null, draftVersion: null, status: 'missing', draft: null, canConfirm: false, reasons: [] }) : id === 'super' ? makeDraft(id, { draftId: 'draft-super', status: 'superseded', canEdit: false, canConfirm: false, reasons: ['bible_head_changed'] }) : makeDraft(id, { lifecycle: 'archived', status: 'superseded', draft: { ...bible(), premiseAndPromise: 'ARCHIVED DRAFT' }, canEdit: false, canConfirm: false, canClone: false, reasons: ['bible_head_changed'] })
        return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
      }
      return new Response(JSON.stringify({ id, title: id, archivedAt: id === 'archived' ? '2026-01-01' : null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }, { path: '/next', component: { render: () => h('p', 'next') } }] })
    const app = renderer.createApp({ render: () => h(RouterView) }); app.use(createPinia()); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/first/bible'); await router.isReady(); const root = node('root'); app.mount(root); await flush()
    let area = walk(root).find(value => value.type === 'textarea'); assert.equal(area.props.readonly, undefined); assert.equal(area.props.disabled, false)
    area.props.onInput({ target: { value: 'first local' } }); await flush(); await byText(root, '手动保存').props.onClick(); await flush(); assert.equal(puts[0].expectedDraftVersion, 0)
    area.props.onInput({ target: { value: 'dirty again' } }); await flush(); await router.push('/next'); assert.equal(router.currentRoute.value.fullPath, '/projects/first/bible')
    allowLeave = true; await router.push('/next'); assert.equal(router.currentRoute.value.fullPath, '/next')
    await router.push('/projects/head/bible'); await flush(); assert.match(text(root), /CREATION BIBLE · current/); assert.match(text(root), /内容已过期，请调整未来设计/); area = walk(root).find(value => value.type === 'textarea'); assert.equal(area.props.readonly, true); assert.equal(area.props.disabled, false); assert.ok(byText(root, '调整未来设计'))
    await router.push('/projects/super/bible'); await flush(); assert.match(text(root), /superseded/); await byText(root, '调整未来设计').props.onClick(); await flush(); assert.deepEqual(clones.at(-1), { sourceDraftId: 'draft-super' })
    await router.push('/projects/archived/bible'); await flush(); assert.match(text(root), /CREATION BIBLE · superseded/); assert.match(text(root), /内容已过期，请调整未来设计/); assert.equal(byText(root, '调整未来设计'), undefined); area = walk(root).find(value => value.type === 'textarea' && value.props.value === 'ARCHIVED DRAFT'); assert.ok(area); assert.equal(area.props.readonly, true)
  } finally { global.fetch = originalFetch; global.window = originalWindow; await vite.close() }
})

test('mounted load retry and conflict recovery keep local edits until authoritative reload is confirmed', async () => {
  const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  const originalFetch = global.fetch; const originalWindow = global.window; const originalDocument = global.document; let allowReload = false; let headCalls = 0; let draftCalls = 0; let root
  const body = node('body')
  const makeDraft = () => ({ projectId: 'conflict', lifecycle: 'active', status: 'editable', draftId: 'draft-conflict', draftVersion: 1, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [] })
  const makeHead = () => ({ projectId: 'conflict', lifecycle: 'active', status: 'current', revision: 7, bible: bible(), canClone: true, reasons: [] })
  try {
    const [Page, Editor, Drawer] = await Promise.all([vite.ssrLoadModule('/src/views/ProjectBibleView.vue'), vite.ssrLoadModule('/src/components/bible/BibleEditor.vue'), vite.ssrLoadModule('/src/components/bible/BibleHistoryDrawer.vue')])
    Page.default.render = await clientRender('views/ProjectBibleView.vue'); Editor.default.render = await clientRender('components/bible/BibleEditor.vue'); Drawer.default.render = await clientRender('components/bible/BibleHistoryDrawer.vue')
    global.window = { confirm: () => allowReload, addEventListener() {}, removeEventListener() {} }
    global.document = { activeElement: null, querySelector: selector => selector === '#app' ? root : selector === 'body' ? body : null }
    global.fetch = async (url, options = {}) => {
      const path = String(url)
      if (options.method === 'PUT') return new Response(JSON.stringify({ code: 'BibleConflict', message: 'raw provider key secret' }), { status: 409, headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/head')) {
        headCalls += 1
        if (headCalls === 1) return new Response(JSON.stringify({ code: 'ProviderFailure', message: 'raw provider key secret' }), { status: 503, headers: { 'content-type': 'application/json' } })
        return new Response(JSON.stringify(makeHead()), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/draft')) { draftCalls += 1; return new Response(JSON.stringify(makeDraft()), { headers: { 'content-type': 'application/json' } }) }
      return new Response(JSON.stringify({ id: 'conflict', title: 'conflict', archivedAt: null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }] })
    const pinia = createPinia()
    const app = renderer.createApp({ render: () => h(RouterView) }); app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/conflict/bible'); await router.isReady(); root = node('root'); root.parent = body; body.children.push(root); app.mount(root)
    const loadError = await waitFor(() => walk(root).find(value => value.props?.class === 'error-summary'), 'initial load failure did not render')
    assert.equal(loadError.props.tabindex, '-1'); assert.equal(global.document.activeElement.props.class, 'error-summary'); assert.doesNotMatch(text(loadError), /provider|key|secret/i)
    await byText(root, '重试加载').props.onClick()
    const area = await waitFor(() => walk(root).find(value => value.type === 'textarea' && value.props.value === 'promise'), `conflict workspace did not hydrate after retry: ${text(root)}`)
    assert.equal(headCalls, 2); assert.equal(draftCalls, 2)
    area.props.onInput({ target: { value: 'LOCAL CONFLICT' } }); await flush(); await byText(root, '手动保存').props.onClick()
    const visibleError = await waitFor(() => walk(root).find(value => value.props?.class === 'error-summary'), 'conflict summary did not render')
    assert.equal(global.document.activeElement.props.class, 'error-summary'); assert.match(text(visibleError), /本地编辑仍保留/); assert.doesNotMatch(text(visibleError), /provider|key|secret/)
    allowReload = false; await byText(root, '重新加载权威版本').props.onClick(); await flush(); assert.ok(walk(root).some(value => value.type === 'textarea' && value.props.value === 'LOCAL CONFLICT'))
    allowReload = true; await byText(root, '重新加载权威版本').props.onClick()
    await waitFor(() => walk(root).some(value => value.type === 'textarea' && value.props.value === 'promise'), 'authoritative Bible did not replace the local conflict after confirmation')
    const trigger = byText(root, '预览并确认'); global.document.activeElement = trigger; trigger.props.onClick({ currentTarget: trigger })
    const confirmDialog = await waitFor(() => walk(body).find(value => value.props?.class === 'confirm-panel'), 'confirm dialog did not mount')
    assert.equal(walk(root).some(value => value.props?.class === 'confirm-panel'), false)
    assert.equal(confirmDialog.parent.props.class, 'confirm-overlay')
    const confirmButton = byText(confirmDialog, '确认签印'); const cancelButton = byText(confirmDialog, '返回编辑')
    assert.equal(root.inert, true); assert.equal(text(global.document.activeElement), '确认签印')
    const focusable = confirmDialog.querySelectorAll()
    global.document.activeElement = focusable.at(-1)
    let prevented = false; confirmDialog.props.onKeydown({ key: 'Tab', shiftKey: false, preventDefault() { prevented = true } })
    assert.equal(prevented, true); assert.equal(global.document.activeElement.type, 'textarea')
    global.document.activeElement = focusable[0]
    confirmDialog.props.onKeydown({ key: 'Tab', shiftKey: true, preventDefault() {} })
    assert.equal(text(global.document.activeElement), '返回编辑')
    confirmDialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush()
    assert.equal(walk(body).some(value => value.props?.class === 'confirm-panel'), false); assert.notEqual(root.inert, true); assert.equal(root.hasAttribute('inert'), false); assert.equal(text(global.document.activeElement), '预览并确认')
    trigger.props.onClick({ currentTarget: trigger })
    let busyDialog = await waitFor(() => walk(body).find(value => value.props?.class === 'confirm-panel'), 'confirm dialog did not reopen')
    pinia.state.value.bible.confirming = true; await flush(); busyDialog = walk(body).find(value => value.props?.class === 'confirm-panel')
    busyDialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush()
    assert.ok(walk(body).some(value => value.props?.class === 'confirm-panel')); assert.equal(byText(body, '返回编辑').props.disabled, true)
    pinia.state.value.bible.confirming = false; await flush(); busyDialog = walk(body).find(value => value.props?.class === 'confirm-panel')
    busyDialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush(); assert.equal(walk(body).some(value => value.props?.class === 'confirm-panel'), false)
  } finally { global.fetch = originalFetch; global.window = originalWindow; global.document = originalDocument; await vite.close() }
})

test('real store recovery retries save, confirm, and history without leaving the active modal focus domain', async () => {
  const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  const originalFetch = global.fetch; const originalWindow = global.window; const originalDocument = global.document
  const body = node('body'); let root; let saveCalls = 0; let historyCalls = 0; let cloneCalls = 0; const saves = []; const confirms = []; let headReads = 0; let draftReads = 0
  const makeDraft = (premise = 'SERVER', version = 1) => ({ projectId: 'recovery', lifecycle: 'active', status: 'editable', draftId: 'draft-recovery', draftVersion: version, draft: { ...bible(), premiseAndPromise: premise }, canEdit: true, canConfirm: true, canClone: true, reasons: [] })
  const makeHead = (revision = 7) => ({ projectId: 'recovery', lifecycle: 'active', status: 'current', revision, bible: { ...bible(), premiseAndPromise: `HEAD ${revision}` }, canClone: true, reasons: [] })
  try {
    const [Page, Editor, Drawer] = await Promise.all([vite.ssrLoadModule('/src/views/ProjectBibleView.vue'), vite.ssrLoadModule('/src/components/bible/BibleEditor.vue'), vite.ssrLoadModule('/src/components/bible/BibleHistoryDrawer.vue')])
    Page.default.render = await clientRender('views/ProjectBibleView.vue'); Editor.default.render = await clientRender('components/bible/BibleEditor.vue'); Drawer.default.render = await clientRender('components/bible/BibleHistoryDrawer.vue')
    global.window = { confirm: () => true, addEventListener() {}, removeEventListener() {} }
    global.document = { activeElement: null, querySelector: selector => selector === '#app' ? root : selector === 'body' ? body : null }
    global.fetch = async (url, options = {}) => {
      const path = String(url)
      if (options.method === 'PUT') {
        const command = JSON.parse(options.body); saves.push(command); saveCalls += 1
        if (saveCalls === 1) return new Response(JSON.stringify({ code: 'ProviderFailure', message: 'raw provider key secret' }), { status: 503, headers: { 'content-type': 'application/json' } })
        return new Response(JSON.stringify(makeDraft(command.draft.premiseAndPromise, 2)), { headers: { 'content-type': 'application/json' } })
      }
      if (options.method === 'POST' && path.endsWith('/bible/confirm')) {
        const command = JSON.parse(options.body); confirms.push(command)
        if (confirms.length === 1) return new Response(JSON.stringify({ code: 'outcome_unknown', message: 'raw provider key secret' }), { status: 503, headers: { 'content-type': 'application/json' } })
        return new Response(JSON.stringify(makeHead(8)), { headers: { 'content-type': 'application/json' } })
      }
      if (options.method === 'POST' && path.endsWith('/bible/draft/clone')) {
        cloneCalls += 1
        return new Response(JSON.stringify({ code: 'outcome_unknown', message: 'raw provider key secret' }), { status: 503, headers: { 'content-type': 'application/json' } })
      }
      if (path.includes('/bible/history')) {
        historyCalls += 1
        if (historyCalls === 1) return new Response(JSON.stringify({ code: 'HistoryFailure', message: 'raw provider key secret' }), { status: 503, headers: { 'content-type': 'application/json' } })
        return new Response(JSON.stringify({ items: [makeHead(8)], nextBeforeRevision: null }), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/head')) { headReads += 1; return new Response(JSON.stringify(makeHead()), { headers: { 'content-type': 'application/json' } }) }
      if (path.endsWith('/bible/draft')) { draftReads += 1; return new Response(JSON.stringify(makeDraft()), { headers: { 'content-type': 'application/json' } }) }
      return new Response(JSON.stringify({ id: 'recovery', title: 'recovery', archivedAt: null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }] })
    const pinia = createPinia(); const app = renderer.createApp({ render: () => h(RouterView) }); app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/recovery/bible'); await router.isReady(); root = node('root'); root.parent = body; body.children.push(root); app.mount(root)
    const area = await waitFor(() => walk(root).find(value => value.type === 'textarea' && value.props.value === 'SERVER'), 'recovery project did not hydrate')
    area.props.onInput({ target: { value: 'LOCAL AFTER 503' } }); await flush(); await byText(root, '手动保存').props.onClick()
    const saveRetry = await waitFor(() => byText(root, '重试保存'), 'save retry command did not render')
    assert.equal(pinia.state.value.bible.dirty, true); assert.equal(headReads, 1); assert.equal(draftReads, 1)
    await saveRetry.props.onClick(); await waitFor(() => saveCalls === 2, 'save retry did not issue PUT')
    assert.equal(saves[1].draft.premiseAndPromise, 'LOCAL AFTER 503'); assert.equal(headReads, 1); assert.equal(draftReads, 1); assert.equal(pinia.state.value.bible.dirty, false)
    const confirmTrigger = byText(root, '预览并确认'); global.document.activeElement = confirmTrigger; confirmTrigger.props.onClick({ currentTarget: confirmTrigger })
    let confirmDialog = await waitFor(() => walk(body).find(value => value.props?.class === 'confirm-panel'), 'confirm dialog did not open')
    await byText(confirmDialog, '确认签印').props.onClick()
    const confirmError = await waitFor(() => walk(confirmDialog).find(value => value.props?.class === 'modal-error-summary'), 'confirm error did not stay in its dialog')
    assert.equal(walk(root).some(value => value.props?.class === 'error-summary'), false); assert.equal(global.document.activeElement.props.class, 'modal-error-summary')
    assert.equal(walkParents(confirmError).some(value => value.inert === true || value.hasAttribute?.('inert')), false); assert.doesNotMatch(text(confirmError), /provider|key|secret/i)
    await byText(confirmDialog, '重试确认').props.onClick(); await waitFor(() => confirms.length === 2, 'confirm retry did not issue POST')
    assert.equal(confirms[0].idempotencyKey, confirms[1].idempotencyKey)
    await waitFor(() => !walk(body).some(value => value.props?.class === 'confirm-panel'), 'confirm dialog did not close after retry success')
    const historyTrigger = byText(root, '修订历史'); global.document.activeElement = historyTrigger; historyTrigger.props.onClick()
    let historyDialog = await waitFor(() => walk(body).find(value => value.type === 'aside' && value.props.role === 'dialog'), 'history dialog did not open')
    const historyError = await waitFor(() => walk(historyDialog).find(value => value.props?.class === 'modal-error-summary'), 'history error did not render in drawer')
    assert.equal(walk(root).some(value => value.props?.class === 'error-summary'), false); assert.equal(global.document.activeElement.props.class, 'modal-error-summary')
    assert.equal(walkParents(historyError).some(value => value.inert === true || value.hasAttribute?.('inert')), false)
    await byText(historyDialog, '重试历史').props.onClick(); await waitFor(() => historyCalls === 2, 'history retry did not issue GET')
    assert.equal(headReads, 1); assert.equal(draftReads, 1)
    const cloneButton = await waitFor(() => byText(walk(body).find(value => value.type === 'aside' && value.props.role === 'dialog'), 'Adjust Future Design'), () => `history retry result did not render: ${text(body)}`)
    historyDialog = walk(body).find(value => value.type === 'aside' && value.props.role === 'dialog')
    await cloneButton.props.onClick()
    const cloneError = await waitFor(() => walk(historyDialog).find(value => value.props?.class === 'modal-error-summary'), 'clone outcome error did not stay in drawer')
    assert.equal(byText(cloneError, '重新核对当前状态')?.type, 'button'); assert.equal(cloneCalls, 1)
    await byText(cloneError, '重新核对当前状态').props.onClick()
    await waitFor(() => headReads === 2 && draftReads === 2, 'clone reconciliation did not hydrate current state')
    assert.equal(cloneCalls, 1)
  } finally { global.fetch = originalFetch; global.window = originalWindow; global.document = originalDocument; await vite.close() }
})

test('mounted history dialog traps focus, restores its trigger, and ignores Escape while busy', async () => {
  const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  const originalDocument = global.document; let root; const body = node('body')
  try {
    const [Drawer, Editor] = await Promise.all([vite.ssrLoadModule('/src/components/bible/BibleHistoryDrawer.vue'), vite.ssrLoadModule('/src/components/bible/BibleEditor.vue')])
    Drawer.default.render = await clientRender('components/bible/BibleHistoryDrawer.vue'); Editor.default.render = await clientRender('components/bible/BibleEditor.vue')
    const open = VueRuntime.ref(false); const busy = VueRuntime.ref(false); let closes = 0
    const Parent = {
      render: () => h('div', [
        h('button', { onClick: () => { open.value = true } }, '打开历史'),
        h(Drawer.default, {
          open: open.value,
          busy: busy.value,
          history: [{ bibleRevisionId: 'revision-3', revision: 3, status: 'current', canClone: true }],
          onClose: () => { closes += 1; open.value = false },
        }),
      ]),
    }
    global.document = { activeElement: null, querySelector: selector => selector === '#app' ? root : selector === 'body' ? body : null }
    root = node('root'); root.parent = body; body.children.push(root); const app = renderer.createApp(Parent); app.provide(ssrContextKey, { modules: new Set() }); app.mount(root)
    const trigger = byText(root, '打开历史'); global.document.activeElement = trigger; trigger.props.onClick()
    let dialog = await waitFor(() => walk(body).find(value => value.type === 'aside' && value.props.role === 'dialog'), 'history dialog did not mount')
    assert.equal(walk(root).some(value => value.type === 'aside'), false)
    assert.equal(root.inert, true); assert.equal(global.document.activeElement.props.role, 'dialog')
    let focusable = dialog.querySelectorAll(); global.document.activeElement = focusable.at(-1)
    dialog.props.onKeydown({ key: 'Tab', shiftKey: false, preventDefault() {} }); assert.equal(global.document.activeElement.props['aria-label'], '关闭历史')
    global.document.activeElement = focusable[0]
    dialog.props.onKeydown({ key: 'Tab', shiftKey: true, preventDefault() {} }); assert.equal(text(global.document.activeElement), 'Adjust Future Design')
    dialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush()
    assert.equal(closes, 1); assert.equal(walk(body).some(value => value.type === 'aside'), false); assert.notEqual(root.inert, true); assert.equal(text(global.document.activeElement), '打开历史')
    global.document.activeElement = trigger; trigger.props.onClick(); dialog = await waitFor(() => walk(body).find(value => value.type === 'aside'), 'history dialog did not reopen')
    busy.value = true; await flush(); dialog = walk(body).find(value => value.type === 'aside')
    dialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush()
    assert.equal(closes, 1); assert.ok(walk(body).some(value => value.type === 'aside')); assert.equal(byText(body, '×').props.disabled, true)
    busy.value = false; await flush(); dialog = walk(body).find(value => value.type === 'aside'); dialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush()
    assert.equal(closes, 2); assert.equal(walk(body).some(value => value.type === 'aside'), false)
  } finally { global.document = originalDocument; await vite.close() }
})

test('real Pinia, router, and fetch keep a forced B context clean when A save resolves late', async () => {
  const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  const originalFetch = global.fetch; const originalWindow = global.window; const pendingA = deferred(); const puts = []
  const makeDraft = (id, premise = `${id} BODY`) => ({ projectId: id, lifecycle: 'active', status: 'editable', draftId: `draft-${id}`, draftVersion: 1, draft: { ...bible(), premiseAndPromise: premise }, canEdit: true, canConfirm: true, canClone: true, reasons: [] })
  const makeHead = id => ({ projectId: id, lifecycle: 'active', status: 'current', revision: 1, bible: { ...bible(), premiseAndPromise: `${id} HEAD` }, canClone: true, reasons: [] })
  try {
    const [Page, Editor, Drawer] = await Promise.all([vite.ssrLoadModule('/src/views/ProjectBibleView.vue'), vite.ssrLoadModule('/src/components/bible/BibleEditor.vue'), vite.ssrLoadModule('/src/components/bible/BibleHistoryDrawer.vue')])
    Page.default.render = await clientRender('views/ProjectBibleView.vue'); Editor.default.render = await clientRender('components/bible/BibleEditor.vue'); Drawer.default.render = await clientRender('components/bible/BibleHistoryDrawer.vue')
    global.window = { confirm: () => true, addEventListener() {}, removeEventListener() {} }
    global.fetch = async (url, options = {}) => {
      const path = String(url); const id = path.match(/projects\/([^/]+)/)?.[1]
      if (options.method === 'PUT') {
        const command = JSON.parse(options.body); puts.push({ id, command })
        if (id === 'A') return pendingA.promise
        return new Response(JSON.stringify(makeDraft(id, command.draft.premiseAndPromise)), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/head')) return new Response(JSON.stringify(makeHead(id)), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/draft')) return new Response(JSON.stringify(makeDraft(id)), { headers: { 'content-type': 'application/json' } })
      return new Response(JSON.stringify({ id, title: id, archivedAt: null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }] })
    const pinia = createPinia(); const app = renderer.createApp({ render: () => h(RouterView) }); app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/A/bible'); await router.isReady(); const root = node('root'); app.mount(root)
    let area = await waitFor(() => walk(root).find(value => value.type === 'textarea' && value.props.value === 'A BODY'), 'A did not hydrate')
    area.props.onInput({ target: { value: 'A LOCAL' } }); await flush()
    const oldSave = byText(root, '手动保存').props.onClick()
    await waitFor(() => puts.length === 1, 'A save was not issued')
    await router.push('/projects/B/bible'); assert.equal(router.currentRoute.value.params.projectId, 'A')
    pinia.state.value.bible.saving = false; pinia.state.value.bible.dirty = false
    await router.push('/projects/B/bible')
    area = await waitFor(() => walk(root).find(value => value.type === 'textarea' && value.props.value === 'B BODY'), 'B did not hydrate after the forced host context switch')
    pendingA.resolve(new Response(JSON.stringify(makeDraft('A', 'A LATE SAVED')), { headers: { 'content-type': 'application/json' } }))
    await oldSave; await flush()
    assert.equal(router.currentRoute.value.params.projectId, 'B'); assert.doesNotMatch(text(root), /A LATE SAVED|创作圣经操作失败/)
    area.props.onInput({ target: { value: 'B LOCAL' } }); await flush(); await byText(root, '手动保存').props.onClick(); await flush()
    assert.equal(puts.at(-1).id, 'B'); assert.equal(puts.at(-1).command.draft.premiseAndPromise, 'B LOCAL')
  } finally { global.fetch = originalFetch; global.window = originalWindow; await vite.close() }
})

test('Bible workspace styles consume the shared canvas, paper, ink, muted, border, and vermilion tokens', async () => {
  const values = await Promise.all(['views/ProjectBibleView.vue', 'components/bible/BibleEditor.vue', 'components/bible/BibleHistoryDrawer.vue'].map(path => readFile(source(path), 'utf8')))
  const combined = values.join('\n')
  for (const token of ['--nc-canvas', '--nc-paper', '--nc-ink', '--nc-muted', '--nc-border', '--nc-vermilion']) assert.match(combined, new RegExp(`var\\(${token}`))
  assert.doesNotMatch(combined, /#(?:302a23|eee6d7|fffaf0|cdbda5|9b372b|8b3028|6c5a49)\b/i)
  assert.doesNotMatch(combined, /rgba\((?:48,42,35|55,39,25|39,28,20|38,25,15)/)
  assert.match(values[0], /@click="retryFailure"/)
  assert.doesNotMatch(values[0], /store\.(?:error|conflict)\?\.message|\berror\.message/)
})
