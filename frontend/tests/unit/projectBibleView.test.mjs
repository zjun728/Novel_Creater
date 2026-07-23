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

function node(type, text = '') { return { type, text, props: {}, children: [], parent: null } }
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
async function clientRender(path) {
  const contents = await readFile(source(path), 'utf8'); const filename = path.split('/').at(-1)
  const { descriptor } = parse(contents, { filename }); const script = compileScript(descriptor, { id: `bible-${filename}` })
  const result = compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: script.bindings })
  return new Function('Vue', result.code)({ ...VueRuntime, withModifiers: handler => handler, withKeys: handler => handler })
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
    const drawer = await renderToString(createSSRApp({ render: () => h(Drawer.default, { open: true, history: [{ revision: 3, canClone: true }], historyDetail: { revision: 3, bible: bible(), reasons: [], basis: {} } }) }))
    assert.match(drawer, /Revision 3/); assert.match(drawer, /查看详情/); assert.match(drawer, /开放设计问题/)
  } finally { await vite.close() }
})

test('the Vite-loaded BibleEditor emits scalar/list edits and renders disabled controls', async () => {
  const vite = await createServer({ configFile: false, root: frontendRoot, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error', plugins: [vuePlugin()] })
  try {
    const Editor = (await vite.ssrLoadModule('/src/components/bible/BibleEditor.vue')).default
    Editor.render = await clientRender('components/bible/BibleEditor.vue')
    const emitted = []; const root = node('root')
    const app = renderer.createApp(Editor, { modelValue: bible(), disabled: false, 'onUpdate:modelValue': value => emitted.push(value) })
    app.provide(ssrContextKey, { modules: new Set() }); app.mount(root)
    const scalar = walk(root).find(item => item.type === 'textarea' && item.props.value === 'promise')
    scalar.props.onInput({ target: { value: 'changed promise' } }); await nextTick()
    assert.equal(emitted.at(-1).premiseAndPromise, 'changed promise')
    byText(root, '新增世界规则').props.onClick(); await nextTick()
    assert.equal(emitted.at(-1).worldRules.length, 2)
    byText(root, '删除').props.onClick(); await nextTick()
    assert.equal(emitted.at(-1).worldRules.length, 0)
    const disabledRoot = node('root'); const disabledApp = renderer.createApp(Editor, { modelValue: bible(), disabled: true })
    disabledApp.provide(ssrContextKey, { modules: new Set() }); disabledApp.mount(disabledRoot)
    assert.ok(walk(disabledRoot).filter(item => item.type === 'textarea' || item.type === 'button').every(item => item.props.disabled === true))
  } finally { await vite.close() }
})
