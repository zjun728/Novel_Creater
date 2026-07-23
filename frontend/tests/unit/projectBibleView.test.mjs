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

function node(type, text = '') { return { type, text, props: {}, children: [], parent: null, focus() { this.focused = true } } }
function detach(child) { if (!child?.parent) return; child.parent.children.splice(child.parent.children.indexOf(child), 1); child.parent = null }
const renderer = createRenderer({
  patchProp(el, key, _old, value) { if (value == null) delete el.props[key]; else el.props[key] = value },
  insert(child, parent, anchor = null) { detach(child); child.parent = parent; const at = anchor ? parent.children.indexOf(anchor) : -1; if (at < 0) parent.children.push(child); else parent.children.splice(at, 0, child) },
  remove: detach, createElement: type => node(type), createText: text => node('#text', String(text)), createComment: text => node('#comment', String(text || '')),
  setText(target, text) { target.text = String(text) }, setElementText(target, text) { target.text = String(text); target.children = [] },
  parentNode: target => target?.parent || null, nextSibling: target => target?.parent?.children[target.parent.children.indexOf(target) + 1] || null,
  querySelector: () => null, setScopeId(el, id) { el.props[id] = '' }, cloneNode: target => ({ ...target, props: { ...target.props }, children: [...target.children], parent: null }),
  insertStaticContent(content, parent, anchor) { const target = node('#static', content); renderer.insert(target, parent, anchor); return [target, target] },
})
function walk(root, all = []) { if (!root) return all; all.push(root); for (const child of root.children || []) walk(child, all); return all }
function text(root) { return [root.text || '', ...(root.children || []).map(text)].join('') }
function byText(root, value) { return walk(root).find(item => item.type === 'button' && text(item).trim() === value) }
async function flush() { for (let index = 0; index < 4; index += 1) await Promise.resolve(); await new Promise(resolve => setTimeout(resolve, 0)); await nextTick() }
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
  assert.match(page, /aria-busy/); assert.match(page, /inert/); assert.match(page, /role: "status"/); assert.match(page, /AI 辅助：Not Ready/)
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
      if (options.method === 'PUT') { puts.push(JSON.parse(options.body)); return new Response(JSON.stringify(makeDraft(id, { draftVersion: 1 })), { headers: { 'content-type': 'application/json' } }) }
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
