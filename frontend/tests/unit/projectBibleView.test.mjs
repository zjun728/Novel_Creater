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

import { createProjectBibleViteServer } from '../support/projectBibleViteServer.mjs'

const source = path => new URL(`../../src/${path}`, import.meta.url)

test('confirmed Bible page is a permanent read-only baseline without clone controls', async () => {
  const contents = await Promise.all([
    'views/ProjectBibleView.vue',
    'components/bible/BibleEditor.vue',
    'components/bible/BibleHistoryDrawer.vue',
  ].map(path => readFile(source(path), 'utf8')))
  const joined = contents.join('\n')
  assert.match(joined, /已确认，作为项目永久基线/)
  assert.match(joined, /已确认为项目永久基线/)
  assert.match(joined, /确认创作圣经/)
  assert.doesNotMatch(joined, /确认新的未来设计|已确认新的创作圣经修订/)
  assert.doesNotMatch(joined, /调整未来设计|workspace\.clone|cloneSource/)
  assert.doesNotMatch(joined, /恢复此修订|恢复草稿/)
})

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
async function loadClientBiblePage(vite, { actualProposal = false } = {}) {
  const paths = [
    'views/ProjectBibleView.vue',
    'components/bible/BibleEditor.vue',
    'components/bible/BibleHistoryDrawer.vue',
    'components/bible/BibleProposalReview.vue',
    'components/foundation/FoundationConfirmationDialog.vue',
    'components/foundation/FoundationSectionIndex.vue',
    'components/foundation/FoundationStatusRail.vue',
    'components/foundation/FoundationWorkspace.vue',
  ]
  const modules = await Promise.all(paths.map(path => vite.ssrLoadModule(`/src/${path}`)))
  const compiledCount = actualProposal ? 4 : 3
  const renders = await Promise.all(paths.slice(0, compiledCount).map(clientRender))
  modules.slice(0, compiledCount).forEach((module, index) => { module.default.render = renders[index] })
  for (const module of modules.slice(compiledCount)) module.default.setup = undefined
  if (!actualProposal) {
    modules[3].default.render = function renderProposal() {
      if (!this.open) return null
      return h('section', { class: 'bible-proposal-review', role: 'dialog' }, [h('button', { onClick: () => this.$emit('cancel') }, '取消'), h('button', { onClick: () => this.$emit('adopt') }, '采纳建议')])
    }
  }
  modules[4].default.render = function renderConfirmation() {
    if (!this.open) return null
    return h(VueRuntime.Teleport, { to: 'body' }, h('div', { class: 'foundation-confirmation-dialog__overlay' }, [
      h('section', { class: 'foundation-confirmation-dialog', role: 'dialog', onKeydown: event => { if (event.key === 'Escape' && !this.closeDisabled) this.$emit('close') } }, [this.$slots.snapshot?.(), this.$slots.source?.(), this.$slots.action?.()]),
    ]))
  }
  modules[5].default.render = function renderIndex() { return h('nav', this.items?.map(item => h('button', { onClick: () => this.$emit('navigate', item.key) }, item.label))) }
  modules[6].default.render = function renderStatus() { return h('aside', [this.$slots.summary?.(), this.$slots.status?.(), this.$slots.source?.(), !this.readOnly ? this.$slots.action?.() : null]) }
  modules[7].default.render = function renderWorkspace() {
    return h('section', [h('header', [h('p', { class: 'foundation-workspace__kicker' }, 'AUTHORING FOUNDATION'), h('h1', this.title), h('p', { class: 'foundation-workspace__header-status' }, this.statusLabel)]), this.$slots.index?.(), this.$slots.status?.(), this.$slots.document?.()])
  }
  return { Page: modules[0], Editor: modules[1], Drawer: modules[2], Proposal: modules[3] }
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

test('Vite compiles the page through its controller and SSR renders the ten-section 11-field document and read-only history detail', async () => {
  const vite = await createProjectBibleViteServer()
  try {
    const [Page, Editor, Drawer] = await Promise.all([
      vite.ssrLoadModule('/src/views/ProjectBibleView.vue'), vite.ssrLoadModule('/src/components/bible/BibleEditor.vue'), vite.ssrLoadModule('/src/components/bible/BibleHistoryDrawer.vue'),
    ])
    assert.equal(typeof Page.default.setup, 'function')
    const preview = await renderToString(createSSRApp({ render: () => h(Editor.default, { modelValue: bible(), disabled: true }) }))
    for (const label of ['作品承诺', '世界规则', '力量／成长体系', '主角与核心人物', '势力', '长期冲突', '关系动力', '基调与叙事边界', '连贯性护栏', '开放设计问题']) assert.match(preview, new RegExp(label))
    assert.match(preview, /disabled/)
    const drawer = await renderToString(createSSRApp({ render: () => h(Drawer.default, { open: true, busy: true, history: [{ revision: 3, status: 'current' }, { revision: 2, status: 'superseded' }, { revision: 1, status: 'unknown-status' }], historyDetail: { revision: 3, bible: bible(), reasons: ['bible_confirmed', 'contract_unavailable', 'contract_basis_invalid', 'unknown-reason-sentinel'], basis: { seedId: 'seed-1', policyVersion: 'v1' } } }) }))
    assert.match(drawer, /Revision 3/); assert.match(drawer, /查看详情/); assert.match(drawer, /开放设计问题/)
    assert.match(drawer, /<dl/); assert.doesNotMatch(drawer, /\[object Object\]/)
    assert.match(drawer, /当前修订/); assert.match(drawer, /历史修订/); assert.match(drawer, /状态待核对/)
    assert.equal((drawer.match(/当前项目契约状态异常，请查看来源与诊断。/g) || []).length, 1)
    assert.equal((drawer.match(/创作圣经状态需要重新读取。/g) || []).length, 1)
    assert.doesNotMatch(drawer, /bible_confirmed|contract_unavailable|contract_basis_invalid|unknown-reason-sentinel|unknown-status/)
  } finally { await vite.close() }
})

test('the Vite-loaded BibleEditor edits one section at a time and completes with one full work copy', async () => {
  const vite = await createProjectBibleViteServer()
  try {
    const Editor = (await vite.ssrLoadModule('/src/components/bible/BibleEditor.vue')).default
    Editor.render = await clientRender('components/bible/BibleEditor.vue')
    const emitted = []; const completed = []; const root = node('root'); const existing = bible()
    const app = renderer.createApp(Editor, { modelValue: existing, activeSection: 'premise', editingSection: 'premise', disabled: false, 'onUpdate:modelValue': value => emitted.push(value), onCompleteSectionEdit: value => completed.push(value) })
    app.provide(ssrContextKey, { modules: new Set() }); app.mount(root)
    const scalar = walk(root).find(item => item.type === 'textarea' && item.props.value === 'promise')
    scalar.props.onInput({ target: { value: 'changed promise' } }); await nextTick()
    assert.equal(emitted.at(-1).premiseAndPromise, 'changed promise')
    assert.equal(walk(root).filter(item => item.type === 'textarea').length, 1)
    byText(root, '完成本区编辑').props.onClick(); await nextTick()
    assert.equal(completed.length, 1); assert.equal(completed[0].premiseAndPromise, 'changed promise')
    assert.deepEqual(Object.keys(completed[0]).sort(), Object.keys(bible()).sort())
    const disabledRoot = node('root'); const disabledApp = renderer.createApp(Editor, { modelValue: bible(), disabled: true })
    disabledApp.provide(ssrContextKey, { modules: new Set() }); disabledApp.mount(disabledRoot)
    assert.ok(walk(disabledRoot).filter(item => item.type === 'textarea' || item.type === 'button').every(item => item.props.disabled === true))
  } finally { await vite.close() }
})

test('read-only BibleEditor renders the same complete semantic document without form or edit controls', async () => {
  const vite = await createProjectBibleViteServer()
  try {
    const Editor = (await vite.ssrLoadModule('/src/components/bible/BibleEditor.vue')).default; Editor.render = await clientRender('components/bible/BibleEditor.vue')
    const emitted = []; const root = node('root'); const app = renderer.createApp(Editor, { modelValue: bible(), readOnly: true, 'onUpdate:modelValue': value => emitted.push(value), onBeginSectionEdit: value => emitted.push(value), onCompleteSectionEdit: value => emitted.push(value) })
    app.provide(ssrContextKey, { modules: new Set() }); app.mount(root)
    assert.equal(walk(root).some(item => ['input', 'textarea', 'select'].includes(item.type)), false)
    assert.equal(walk(root).filter(item => item.type === 'section' && String(item.props.class || '').includes('bible-section')).length, 10)
    assert.equal(walk(root).filter(item => item.type === 'ol' && String(item.props.class || '').includes('bible-field__list')).length, 7)
    for (const value of Object.values(bible()).flatMap(item => Array.isArray(item) ? item.map(row => row.text) : [item])) assert.match(text(root), new RegExp(value))
    assert.equal(walk(root).some(item => item.type === 'button'), false)
    assert.equal(emitted.length, 0)

    const emptyRoot = node('root'); const emptyApp = renderer.createApp(Editor, { modelValue: {}, readOnly: true })
    emptyApp.provide(ssrContextKey, { modules: new Set() }); emptyApp.mount(emptyRoot)
    assert.equal((text(emptyRoot).match(/尚未填写/g) || []).length, 11)
  } finally { await vite.close() }
})

test('ProjectBibleView reuses BibleEditor as the only ten-section field mapping for editable and read-only documents', async () => {
  const [page, editor] = await Promise.all([
    readFile(source('views/ProjectBibleView.vue'), 'utf8'),
    readFile(source('components/bible/BibleEditor.vue'), 'utf8'),
  ])
  assert.doesNotMatch(page, /readonlySections|bible-readonly-document/)
  assert.match(page, /<BibleEditor\s+v-if="working"/)
  assert.equal((editor.match(/const sections = Object\.freeze/g) || []).length, 1)
  for (const field of Object.keys(bible())) assert.match(editor, new RegExp(`'${field}'`))
})

test('compiled workspace template exposes an inert busy region and a sibling live status overlay', async () => {
  const page = await compiledTemplate('views/ProjectBibleView.vue')
  const sourcePage = await readFile(source('views/ProjectBibleView.vue'), 'utf8')
  assert.match(page, /aria-busy/); assert.match(page, /inert/); assert.match(page, /role: "status"/)
  assert.match(page, /AI 辅助/)
  assert.match(page, /authorInstructions/)
  assert.match(sourcePage, /AI 生成初稿/)
  assert.match(sourcePage, /AI 补充\/重写本区/)
  assert.match(page, /请先保存/)
  assert.doesNotMatch(page, /workspace\.generate/)
})

test('formal Bible document uses the shared shell, section directory, status rail, and complete source summary', async () => {
  const page = await readFile(source('views/ProjectBibleView.vue'), 'utf8')
  for (const component of ['FoundationWorkspace', 'FoundationSectionIndex', 'FoundationStatusRail', 'FoundationConfirmationDialog', 'BibleProposalReview']) assert.match(page, new RegExp(component))
  for (const token of ['draftVersion', 'contractRevision', 'worldRules', 'coreCast', 'factions', 'openDesignQuestions']) assert.match(page, new RegExp(token))
  assert.match(page, /存在未保存修改/)
})

test('Bible confirmation adapter owns the saved document, draft version, Contract basis, and server capability', async () => {
  const page = await readFile(source('views/ProjectBibleView.vue'), 'utf8')
  assert.match(page, /const confirmationAdapter = computed/)
  for (const member of ['snapshot', 'draftVersion', 'contractBasis', 'canConfirm']) {
    assert.match(page, new RegExp(member))
  }
  assert.match(page, /confirmationAdapter\.snapshot/)
})

test('confirmed head basis remains the displayed source when the missing draft carries a newer drifting basis', async () => {
  const vite = await createProjectBibleViteServer()
  const originalFetch = global.fetch; const originalWindow = global.window
  const headBasis = { contractRevision: 7, creationContractId: 'creation-head', styleContractId: 'style-head' }
  const draftBasis = { contractRevision: 99, creationContractId: 'creation-drift', styleContractId: 'style-drift' }
  try {
    const { Page } = await loadClientBiblePage(vite)
    global.window = { confirm: () => true, addEventListener() {}, removeEventListener() {} }
    global.fetch = async url => {
      const path = String(url)
      if (path.endsWith('/bible/head')) return new Response(JSON.stringify({ projectId: 'basis', lifecycle: 'active', status: 'current', bibleRevisionId: 'head-7', revision: 7, contentHash: 'h'.repeat(64), bible: bible(), basis: headBasis, canEdit: false, canClone: false, reasons: [], confirmedAt: 7 }), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/draft')) return new Response(JSON.stringify({ projectId: 'basis', lifecycle: 'active', status: 'missing', draftId: null, draftVersion: null, baseHeadRevision: 7, contentHash: null, draft: null, basis: draftBasis, canEdit: false, canConfirm: false, canClone: false, reasons: [] }), { headers: { 'content-type': 'application/json' } })
      return new Response(JSON.stringify({ id: 'basis', title: 'basis', archivedAt: null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }] })
    const app = renderer.createApp({ render: () => h(RouterView) }); app.use(createPinia()); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/basis/bible'); await router.isReady(); const root = node('root'); app.mount(root)
    await waitFor(() => text(root).includes('creation-head'), () => text(root))
    assert.match(text(root), /契约依据：第 7 版/); assert.match(text(root), /creation-head/); assert.match(text(root), /style-head/)
    assert.doesNotMatch(text(root), /creation-drift|style-drift|契约依据：第 99 版/)
    const page = await readFile(source('views/ProjectBibleView.vue'), 'utf8')
    assert.match(page, /sourceBasis\s*=\s*computed\(\(\)\s*=>\s*workspace\.activeBasis\.value\s*\|\|\s*\{\}\)/)
    assert.ok((page.match(/sourceBasis\.contractRevision/g) || []).length >= 2, 'summary and confirmation adapter must share the displayed basis')
  } finally { global.fetch = originalFetch; global.window = originalWindow; await vite.close() }
})

test('ProjectBibleView derives AI readiness from the planning binding item only', async () => {
  const page = await readFile(source('views/ProjectBibleView.vue'), 'utf8')
  assert.match(page, /useModelBindingStore/)
  assert.match(page, /taskKey === 'planning'/)
  assert.match(page, /resolutionStatus === 'bound'/)
  assert.doesNotMatch(page, /bindingStore\.bindingReady/)
  assert.doesNotMatch(page, /下一阶段接入/)
})

test('failed same-project binding refresh disables proposals but preserves manual save and confirm', async () => {
  const vite = await createProjectBibleViteServer()
  const originalFetch = global.fetch; const originalWindow = global.window
  let failStatus = false; let proposals = 0; let draftVersion = 1
  const draft = () => ({ projectId: 'stale', lifecycle: 'active', status: 'editable', draftId: 'draft-stale', draftVersion, baseHeadRevision: 0, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [] })
  const head = () => ({ projectId: 'stale', lifecycle: 'active', status: 'current', revision: 0, bible: null, canClone: false, reasons: [] })
  try {
    const [{ Page, Editor, Drawer }, BindingModule] = await Promise.all([
      loadClientBiblePage(vite), vite.ssrLoadModule('/src/stores/modelBindingStore.js'),
    ])
    global.window = { confirm: () => true, addEventListener() {}, removeEventListener() {} }
    global.fetch = async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      if (path.endsWith('/bindings/status')) {
        if (failStatus) return new Response(JSON.stringify({ code: 'status_unavailable' }), { status: 503, headers: { 'content-type': 'application/json' } })
        return new Response(JSON.stringify({
          projectId: 'stale', revision: 7, contentHash: 's'.repeat(64),
          items: [{ taskKey: 'planning', resolutionStatus: 'bound', providerId: 'provider-1' }],
          bindingComplete: false, bindingReady: false, reasons: [],
        }), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/head')) return new Response(JSON.stringify(head()), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/draft') && options.method === 'PUT') {
        draftVersion += 1
        return new Response(JSON.stringify(draft()), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/draft')) return new Response(JSON.stringify(draft()), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/proposals')) { proposals += 1; throw new Error('proposal must stay disabled') }
      return new Response(JSON.stringify({ id: 'stale', title: 'stale', archivedAt: null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }] })
    const pinia = createPinia(); const app = renderer.createApp({ render: () => h(RouterView) }); app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/stale/bible'); await router.isReady(); const root = node('root'); app.mount(root)
    await waitFor(() => byText(root, 'AI 补充/重写本区')?.props.disabled === false, () => text(root))

    failStatus = true
    const bindingStore = BindingModule.useModelBindingStore(pinia)
    await assert.rejects(bindingStore.getBindingStatus('stale', { force: true }))
    await flush()
    assert.equal(byText(root, 'AI 补充/重写本区').props.disabled, true)
    assert.equal(byText(root, '预览并确认').props.disabled, false)

    const editor = walk(root).find(value => value.type === 'textarea' && value.props.value === 'promise')
    editor.props.onInput({ target: { value: 'manual remains available' } }); await flush()
    assert.equal(byText(root, '手动保存').props.disabled, false)
    await byText(root, '手动保存').props.onClick(); await flush()
    assert.equal(byText(root, '预览并确认').props.disabled, false)
    assert.equal(proposals, 0)
  } finally { global.fetch = originalFetch; global.window = originalWindow; await vite.close() }
})

test('outcome-unknown proposal renders one assertive reconciliation notice without a direct-generate request', async () => {
  const vite = await createProjectBibleViteServer()
  const originalFetch = global.fetch; const originalWindow = global.window; const proposalBodies = []; let directGenerates = 0
  const draft = { projectId: 'unknown', lifecycle: 'active', status: 'editable', draftId: 'draft-unknown', draftVersion: 1, baseHeadRevision: 0, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [] }
  const head = { projectId: 'unknown', lifecycle: 'active', status: 'current', revision: 0, bible: null, canClone: false, reasons: [] }
  try {
    const { Page, Editor, Drawer } = await loadClientBiblePage(vite)
    global.window = { confirm: () => true, addEventListener() {}, removeEventListener() {} }
    global.fetch = async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      if (path.endsWith('/bindings/status')) return new Response(JSON.stringify({ projectId: 'unknown', revision: 7, contentHash: 'u'.repeat(64), items: [{ taskKey: 'planning', resolutionStatus: 'bound', providerId: 'provider-1' }], bindingComplete: false, bindingReady: false, reasons: [] }), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/head')) return new Response(JSON.stringify(head), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/draft')) return new Response(JSON.stringify(draft), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/proposals')) {
        proposalBodies.push(JSON.parse(options.body))
        return new Response(JSON.stringify({ attempt: { id: 'attempt-unknown', projectId: 'unknown', status: 'outcome_unknown', attemptVersion: 2, providerId: 'provider-1', modelNameSnapshot: 'model', inputManifestHash: 'a'.repeat(64), resultHash: null, publicErrorCode: 'BibleGenerationRetryable', createdAt: 1, completedAt: 2 } }), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/generate')) { directGenerates += 1; throw new Error('formal page must not call direct generation') }
      return new Response(JSON.stringify({ id: 'unknown', title: 'unknown', archivedAt: null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }] })
    const app = renderer.createApp({ render: () => h(RouterView) }); app.use(createPinia()); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/unknown/bible'); await router.isReady(); const root = node('root'); app.mount(root)
    const propose = await waitFor(() => byText(root, 'AI 补充/重写本区')?.props.disabled === false && byText(root, 'AI 补充/重写本区'), () => text(root))
    await propose.props.onClick(); await flush()

    const live = walk(root).filter(value => value.props['aria-live'] && text(value).trim())
    assert.equal(live.length, 1)
    assert.equal(live[0].props.role, 'alert')
    assert.equal(live[0].props['aria-live'], 'assertive')
    assert.match(text(live[0]), /结果尚未确认，请先重新核对/)
    assert.doesNotMatch(text(root), /操作失败，请重试|生成结果尚未确认，请重新核对当前状态/)
    assert.equal(proposalBodies.length, 1); assert.equal(proposalBodies[0].scope, 'premise'); assert.equal(directGenerates, 0)
    await byText(root, '重新核对当前状态').props.onClick(); await flush()
    assert.equal(proposalBodies.length, 1); assert.equal(directGenerates, 0)
  } finally { global.fetch = originalFetch; global.window = originalWindow; await vite.close() }
})

test('mounted proposal cancel and adopt restore the real main scroller and focus before one full manual save', async () => {
  const vite = await createProjectBibleViteServer()
  const originalFetch = global.fetch; const originalWindow = global.window; const originalDocument = global.document
  const body = node('body'); const main = node('main'); main.props.id = 'main-content'; main.props.tabindex = '-1'; main.scrollTop = 480; main.scrollLeft = 0
  main.scrollTo = ({ top = main.scrollTop, left = main.scrollLeft }) => { main.scrollTop = top; main.scrollLeft = left }
  let root; let proposalCalls = 0; const puts = []
  const proposed = { ...bible(), premiseAndPromise: 'proposal accepted' }
  try {
    const { Page } = await loadClientBiblePage(vite, { actualProposal: true })
    global.window = { confirm: () => true, addEventListener() {}, removeEventListener() {}, scrollX: 0, scrollY: 11, scrollTo() { throw new Error('window fallback must not be used when #main-content exists') } }
    global.document = {
      activeElement: null,
      querySelector: selector => selector === '#app' ? root : selector === 'body' ? body : selector === '#main-content' ? main : null,
      getElementById: id => id === 'main-content' ? main : walk(root).find(value => value.props?.id === id) || null,
    }
    global.fetch = async (url, options = {}) => {
      const path = String(url)
      if (path.endsWith('/bindings/status')) return new Response(JSON.stringify({ projectId: 'proposal-flow', revision: 1, contentHash: 'b'.repeat(64), items: [{ taskKey: 'planning', resolutionStatus: 'bound', providerId: 'provider-1' }], reasons: [] }), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/head')) return new Response(JSON.stringify({ projectId: 'proposal-flow', lifecycle: 'active', status: 'current', revision: 0, bible: null, basis: { contractRevision: 4 }, canClone: false, reasons: [] }), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/draft') && options.method === 'PUT') {
        const command = JSON.parse(options.body); puts.push(command)
        return new Response(JSON.stringify({ projectId: 'proposal-flow', lifecycle: 'active', status: 'editable', draftId: 'draft-1', draftVersion: 2, baseHeadRevision: 0, contentHash: 'd'.repeat(64), draft: command.draft, basis: { contractRevision: 4 }, canEdit: true, canConfirm: true, reasons: [] }), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/draft')) return new Response(JSON.stringify({ projectId: 'proposal-flow', lifecycle: 'active', status: 'editable', draftId: 'draft-1', draftVersion: 1, baseHeadRevision: 0, contentHash: 'c'.repeat(64), draft: bible(), basis: { contractRevision: 4 }, canEdit: true, canConfirm: true, reasons: [] }), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/proposals')) {
        proposalCalls += 1
        return new Response(JSON.stringify({ attempt: { id: `proposal-${proposalCalls}`, projectId: 'proposal-flow', status: 'succeeded', attemptVersion: 1, providerId: 'provider-1', modelNameSnapshot: 'model', inputManifestHash: 'e'.repeat(64), resultHash: 'f'.repeat(64), publicErrorCode: null, createdAt: proposalCalls, completedAt: proposalCalls + 1, proposal: proposed } }), { headers: { 'content-type': 'application/json' } })
      }
      return new Response(JSON.stringify({ id: 'proposal-flow', title: 'proposal-flow', archivedAt: null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }] })
    const app = renderer.createApp({ render: () => h(RouterView) }); app.use(createPinia()); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/proposal-flow/bible'); await router.isReady()
    root = node('root'); root.parent = main; main.children.push(root); main.parent = body; body.children.push(main); app.mount(root)
    let trigger = await waitFor(() => byText(root, 'AI 补充/重写本区')?.props.disabled === false && byText(root, 'AI 补充/重写本区'), () => text(root))
    global.document.activeElement = trigger; await trigger.props.onClick(); let dialog = await waitFor(() => walk(body).find(value => value.props?.class === 'bible-proposal-review'), 'proposal review did not mount')
    assert.equal(text(global.document.activeElement).trim(), '取消')
    main.scrollTop = 0; await byText(dialog, '取消').props.onClick(); await flush()
    assert.equal(main.scrollTop, 480); assert.equal(global.document.activeElement === trigger, true); assert.equal(puts.length, 0)

    main.scrollTop = 620; trigger = byText(root, 'AI 补充/重写本区'); global.document.activeElement = trigger
    await trigger.props.onClick(); dialog = await waitFor(() => walk(body).find(value => value.props?.class === 'bible-proposal-review'), 'proposal review did not reopen')
    main.scrollTop = 0; await byText(dialog, '采纳建议').props.onClick(); await flush()
    assert.equal(main.scrollTop, 620)
    assert.equal(global.document.activeElement === main || global.document.activeElement?.props?.id === 'bible-section-premise', true)
    assert.equal(byText(root, 'AI 补充/重写本区').props.disabled, true)
    assert.match(text(root), /已采纳建议，存在未保存修改。/)
    await byText(root, '手动保存').props.onClick(); await flush()
    assert.equal(puts.length, 1); assert.deepEqual(puts[0].draft, proposed)
  } finally { global.fetch = originalFetch; global.window = originalWindow; global.document = originalDocument; await vite.close() }
})

test('mounted ProjectBibleView presents every mode label without exposing raw status values', async () => {
  const vite = await createProjectBibleViteServer()
  const originalFetch = global.fetch; const originalWindow = global.window; const puts = []; let allowLeave = false
  const item = id => [{ id, text: id }]
  const makeDraft = (id, extra = {}) => ({ projectId: id, lifecycle: 'active', status: 'editable', draftId: 'draft-1', draftVersion: 1, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [], ...extra })
  const makeHead = (id, extra = {}) => ({ projectId: id, lifecycle: 'active', status: 'current', revision: 7, bible: bible(), canClone: true, reasons: [], ...extra })
  try {
    const { Page, Editor, Drawer } = await loadClientBiblePage(vite)
    global.window = { confirm: () => allowLeave, addEventListener() {}, removeEventListener() {} }
    global.fetch = async (url, options = {}) => {
      const path = String(url); const id = path.match(/projects\/([^/]+)/)?.[1]
      if (path.endsWith('/bindings/status')) return new Response(JSON.stringify({ projectId: id, revision: 1, contentHash: 'm'.repeat(64), items: [{ taskKey: 'planning', resolutionStatus: 'bound', providerId: 'provider-1' }], reasons: [] }), { headers: { 'content-type': 'application/json' } })
      if (options.method === 'PUT') {
        puts.push(JSON.parse(options.body))
        return new Response(JSON.stringify(makeDraft(id, { draftVersion: 1 })), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/head')) {
        const value = id === 'first' || id === 'draft' || id === 'super' ? makeHead(id, { revision: 0, bible: null, canClone: false }) : id === 'head' ? makeHead(id, { reasons: ['bible_head_changed'] }) : id === 'archived' ? makeHead(id, { revision: 0, lifecycle: 'archived', canClone: false, bible: { ...bible(), premiseAndPromise: 'ARCHIVED HEAD' }, reasons: ['project_archived'] }) : makeHead(id)
        return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
      }
      if (path.endsWith('/bible/draft')) {
        const value = id === 'first' ? makeDraft(id, { draftId: null, draftVersion: null, status: 'missing', draft: null, canConfirm: false }) : id === 'head' ? makeDraft(id, { draftId: null, draftVersion: null, status: 'missing', draft: null, canConfirm: false, reasons: [] }) : id === 'draft' ? makeDraft(id, { reasons: ['bible_confirmed', 'contract_unavailable', 'contract_basis_invalid', 'unknown-current-reason-sentinel'] }) : id === 'super' ? makeDraft(id, { draftId: 'draft-super', status: 'superseded', canEdit: false, canConfirm: false, reasons: ['bible_head_changed'] }) : id === 'archived' ? makeDraft(id, { lifecycle: 'archived', draftId: null, draftVersion: null, status: 'missing', draft: null, canEdit: false, canConfirm: false, canClone: false, reasons: ['bible_head_changed'] }) : makeDraft(id)
        return new Response(JSON.stringify(value), { headers: { 'content-type': 'application/json' } })
      }
      return new Response(JSON.stringify({ id, title: id, archivedAt: id === 'archived' ? '2026-01-01' : null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }, { path: '/next', component: { render: () => h('p', 'next') } }] })
    const app = renderer.createApp({ render: () => h(RouterView) }); app.use(createPinia()); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/first/bible'); await router.isReady(); const root = node('root'); app.mount(root); await flush()
    const modeStatus = () => walk(root).find(value => String(value.props?.class || '').includes('foundation-workspace__header-status'))
    assert.equal(text(modeStatus()), '待建立')
    let area = walk(root).find(value => value.type === 'textarea' && value.props['aria-label'] === '作品承诺'); assert.equal(area.props.readonly, undefined); assert.equal(area.props.disabled, false)
    area.props.onInput({ target: { value: 'first local' } }); await flush(); assert.equal(byText(root, '手动保存').props.disabled, true); assert.match(text(root), /请先补全“世界规则”/); assert.equal(puts.length, 0)
    assert.equal(byText(root, 'AI 生成初稿').props.disabled, false)
    assert.doesNotMatch(text(root), /请先保存本地编辑，再请求 AI 建议/)
    area = walk(root).find(value => value.type === 'textarea' && value.props['aria-label'] === '作品承诺')
    area.props.onInput({ target: { value: 'dirty again' } }); await flush(); await router.push('/next'); assert.equal(router.currentRoute.value.fullPath, '/projects/first/bible')
    allowLeave = true; await router.push('/next'); assert.equal(router.currentRoute.value.fullPath, '/next')
    await router.push('/projects/draft/bible'); await waitFor(() => modeStatus() && text(modeStatus()) === '工作草稿', () => text(root)); await flush()
    assert.match(text(root), /当前项目契约状态异常，请查看来源与诊断。/)
    assert.match(text(root), /创作圣经状态需要重新读取。/)
    assert.doesNotMatch(text(root), /bible_confirmed|contract_unavailable|contract_basis_invalid|unknown-current-reason-sentinel/)
    await router.push('/projects/head/bible'); await waitFor(() => modeStatus() && text(modeStatus()) === '已确认', () => text(root)); assert.match(text(root), /已确认，作为项目永久基线/); assert.match(text(root), /promise/); assert.equal(walk(root).some(value => ['input', 'textarea', 'select'].includes(value.type)), false); assert.equal(byText(root, '调整未来设计'), undefined)
    const confirmedActions = walk(root).filter(value => value.type === 'button').map(value => text(value).trim())
    assert.ok(confirmedActions.includes('修订历史'))
    assert.equal(confirmedActions.some(label => /AI |手动保存|预览并确认|编辑本区|完成本区编辑/.test(label)), false)
    await router.push('/projects/super/bible'); await waitFor(() => modeStatus() && text(modeStatus()) === '历史修订', () => text(root)); assert.match(text(root), /此修订已被替代/); assert.equal(byText(root, '调整未来设计'), undefined)
    await router.push('/projects/archived/bible'); await waitFor(() => modeStatus() && text(modeStatus()) === '只读归档', () => text(root)); assert.match(text(root), /此项目或当前服务端状态为只读/); assert.match(text(root), /ARCHIVED HEAD/); assert.equal(walk(root).some(value => ['input', 'textarea', 'select'].includes(value.type)), false)
    assert.doesNotMatch(text(modeStatus()), /\b(?:current|head|superseded|archived)\b|bible_confirmed/)
  } finally { global.fetch = originalFetch; global.window = originalWindow; await vite.close() }
})

test('mounted load retry and conflict recovery keep local edits until authoritative reload is confirmed', async () => {
  const vite = await createProjectBibleViteServer()
  const originalFetch = global.fetch; const originalWindow = global.window; const originalDocument = global.document; let allowReload = false; let headCalls = 0; let draftCalls = 0; let root
  const body = node('body')
  const makeDraft = () => ({ projectId: 'conflict', lifecycle: 'active', status: 'editable', draftId: 'draft-conflict', draftVersion: 1, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [] })
  const makeHead = () => ({ projectId: 'conflict', lifecycle: 'active', status: 'current', revision: 0, bible: null, canClone: false, reasons: [] })
  try {
    const { Page, Editor, Drawer } = await loadClientBiblePage(vite)
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
    const confirmDialog = await waitFor(() => walk(body).find(value => value.props?.class === 'foundation-confirmation-dialog'), 'confirm dialog did not mount')
    assert.equal(walk(root).some(value => value.props?.class === 'foundation-confirmation-dialog'), false)
    assert.equal(confirmDialog.parent.props.class, 'foundation-confirmation-dialog__overlay')
    assert.ok(byText(confirmDialog, '确认签印')); assert.ok(byText(confirmDialog, '返回编辑'))
    confirmDialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush()
    assert.equal(walk(body).some(value => value.props?.class === 'foundation-confirmation-dialog'), false)
    trigger.props.onClick({ currentTarget: trigger })
    let busyDialog = await waitFor(() => walk(body).find(value => value.props?.class === 'foundation-confirmation-dialog'), 'confirm dialog did not reopen')
    pinia.state.value.bible.confirming = true; await flush(); busyDialog = walk(body).find(value => value.props?.class === 'foundation-confirmation-dialog')
    busyDialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush()
    assert.ok(walk(body).some(value => value.props?.class === 'foundation-confirmation-dialog')); assert.equal(byText(body, '返回编辑').props.disabled, true)
    pinia.state.value.bible.confirming = false; await flush(); busyDialog = walk(body).find(value => value.props?.class === 'foundation-confirmation-dialog')
    busyDialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush(); assert.equal(walk(body).some(value => value.props?.class === 'foundation-confirmation-dialog'), false)
  } finally { global.fetch = originalFetch; global.window = originalWindow; global.document = originalDocument; await vite.close() }
})

test('real store recovery retries save, confirm, and history without leaving the active modal focus domain', async () => {
  const vite = await createProjectBibleViteServer()
  const originalFetch = global.fetch; const originalWindow = global.window; const originalDocument = global.document
  const body = node('body'); let root; let saveCalls = 0; let historyCalls = 0; const saves = []; const confirms = []; let headReads = 0; let draftReads = 0
  const makeDraft = (premise = 'SERVER', version = 1) => ({ projectId: 'recovery', lifecycle: 'active', status: 'editable', draftId: 'draft-recovery', draftVersion: version, draft: { ...bible(), premiseAndPromise: premise }, canEdit: true, canConfirm: true, canClone: true, reasons: [] })
  const makeHead = (revision = 0) => ({ projectId: 'recovery', lifecycle: 'active', status: 'current', revision, bible: revision ? { ...bible(), premiseAndPromise: `HEAD ${revision}` } : null, canClone: false, reasons: [] })
  try {
    const { Page, Editor, Drawer } = await loadClientBiblePage(vite)
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
    let confirmDialog = await waitFor(() => walk(body).find(value => value.props?.class === 'foundation-confirmation-dialog'), 'confirm dialog did not open')
    await byText(confirmDialog, '确认签印').props.onClick()
    const confirmError = await waitFor(() => walk(confirmDialog).find(value => value.props?.class === 'modal-error-summary'), 'confirm error did not stay in its dialog')
    assert.equal(walk(root).some(value => value.props?.class === 'error-summary'), false); assert.equal(global.document.activeElement.props.class, 'modal-error-summary')
    assert.equal(walkParents(confirmError).some(value => value.inert === true || value.hasAttribute?.('inert')), false); assert.doesNotMatch(text(confirmError), /provider|key|secret/i)
    await byText(confirmDialog, '重试确认').props.onClick(); await waitFor(() => confirms.length === 2, 'confirm retry did not issue POST')
    assert.equal(confirms[0].idempotencyKey, confirms[1].idempotencyKey)
    await waitFor(() => !walk(body).some(value => value.props?.class === 'foundation-confirmation-dialog'), 'confirm dialog did not close after retry success')
    assert.match(text(root), /HEAD 8/)
    assert.equal(walk(root).some(value => ['input', 'textarea', 'select'].includes(value.type)), false)
    for (const label of ['AI 生成初稿', 'AI 补充/重写本区', '手动保存', '预览并确认', '编辑本区', '完成本区编辑']) assert.equal(byText(root, label), undefined)
    const historyTrigger = byText(root, '修订历史'); global.document.activeElement = historyTrigger; historyTrigger.props.onClick()
    let historyDialog = await waitFor(() => walk(body).find(value => value.type === 'aside' && value.props.role === 'dialog'), 'history dialog did not open')
    const historyError = await waitFor(() => walk(historyDialog).find(value => value.props?.class === 'modal-error-summary'), 'history error did not render in drawer')
    assert.equal(walk(root).some(value => value.props?.class === 'error-summary'), false); assert.equal(global.document.activeElement.props.class, 'modal-error-summary')
    assert.equal(walkParents(historyError).some(value => value.inert === true || value.hasAttribute?.('inert')), false)
    await byText(historyDialog, '重试历史').props.onClick(); await waitFor(() => historyCalls === 2, 'history retry did not issue GET')
    assert.equal(headReads, 1); assert.equal(draftReads, 1)
    historyDialog = walk(body).find(value => value.type === 'aside' && value.props.role === 'dialog')
    assert.equal(byText(historyDialog, 'Adjust Future Design'), undefined)
  } finally { global.fetch = originalFetch; global.window = originalWindow; global.document = originalDocument; await vite.close() }
})

test('mounted history dialog traps focus, restores its trigger, and ignores Escape while busy', async () => {
  const vite = await createProjectBibleViteServer()
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
    dialog.props.onKeydown({ key: 'Tab', shiftKey: true, preventDefault() {} }); assert.equal(text(global.document.activeElement), '查看详情')
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

test('mounted Bible history restores the captured trigger after loading disables and blurs it', async () => {
  const vite = await createProjectBibleViteServer()
  const originalFetch = global.fetch; const originalWindow = global.window; const originalDocument = global.document
  const body = node('body'); let root; let historyRequests = 0; const requests = []; const historyResponse = deferred()
  const draft = () => ({ projectId: 'focus', lifecycle: 'active', status: 'editable', draftId: 'draft-focus', draftVersion: 1, draft: bible(), canEdit: true, canConfirm: true, canClone: true, reasons: [] })
  const head = () => ({ projectId: 'focus', lifecycle: 'active', status: 'current', revision: 0, bible: null, canClone: false, reasons: [] })
  try {
    const { Page, Editor, Drawer } = await loadClientBiblePage(vite)
    global.window = { confirm: () => true, addEventListener() {}, removeEventListener() {} }
    global.document = { activeElement: null, querySelector: selector => selector === '#app' ? root : selector === 'body' ? body : null }
    global.fetch = async (url, options = {}) => {
      const path = String(url); const method = options.method || 'GET'; requests.push({ path, method })
      if (path.endsWith('/bindings/status')) return new Response(JSON.stringify({ projectId: 'focus', revision: 1, contentHash: 'f'.repeat(64), items: [{ taskKey: 'planning', resolutionStatus: 'bound' }], reasons: [] }), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/head')) return new Response(JSON.stringify(head()), { headers: { 'content-type': 'application/json' } })
      if (path.endsWith('/bible/draft')) return new Response(JSON.stringify(draft()), { headers: { 'content-type': 'application/json' } })
      if (path.includes('/bible/history')) { historyRequests += 1; return historyResponse.promise }
      return new Response(JSON.stringify({ id: 'focus', title: 'focus', archivedAt: null }), { headers: { 'content-type': 'application/json' } })
    }
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/bible', component: Page.default }] })
    const app = renderer.createApp({ render: () => h(RouterView) }); app.use(createPinia()); app.use(router); app.provide(ssrContextKey, { modules: new Set() })
    await router.push('/projects/focus/bible'); await router.isReady(); root = node('root'); root.parent = body; body.children.push(root); app.mount(root)
    const trigger = await waitFor(() => byText(root, '修订历史'), 'history trigger did not mount')
    global.document.activeElement = trigger; trigger.props.onClick({ currentTarget: trigger })
    await waitFor(() => historyRequests === 1 && trigger.props.disabled === true, 'history loading did not disable its trigger')
    global.document.activeElement = body
    historyResponse.resolve(new Response(JSON.stringify({ items: [head()], nextBeforeRevision: null }), { headers: { 'content-type': 'application/json' } }))
    const dialog = await waitFor(() => walk(body).find(value => value.type === 'aside' && value.props.role === 'dialog'), 'history dialog did not mount after loading')
    await flush(); assert.equal(trigger.props.disabled, false)
    await byText(dialog, '×').props.onClick(); await flush()
    assert.equal(global.document.activeElement, trigger)
    assert.equal(trigger.isConnected, true)
    assert.equal(historyRequests, 1)
    assert.ok(requests.every(request => request.method === 'GET'))
    assert.deepEqual(requests.filter(request => request.path.includes('/bible/history')).map(request => request.method), ['GET'])
  } finally { global.fetch = originalFetch; global.window = originalWindow; global.document = originalDocument; await vite.close() }
})

test('real Pinia, router, and fetch keep a forced B context clean when A save resolves late', async () => {
  const vite = await createProjectBibleViteServer()
  const originalFetch = global.fetch; const originalWindow = global.window; const pendingA = deferred(); const puts = []
  const makeDraft = (id, premise = `${id} BODY`) => ({ projectId: id, lifecycle: 'active', status: 'editable', draftId: `draft-${id}`, draftVersion: 1, draft: { ...bible(), premiseAndPromise: premise }, canEdit: true, canConfirm: true, canClone: true, reasons: [] })
  const makeHead = id => ({ projectId: id, lifecycle: 'active', status: 'current', revision: 0, bible: null, canClone: false, reasons: [] })
  try {
    const { Page, Editor, Drawer } = await loadClientBiblePage(vite)
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

test('Bible history basis fields stay visible and use an overflow-wrap unit contract while browser verifies geometry', async () => {
  const values = await Promise.all(['views/ProjectBibleView.vue', 'components/bible/BibleEditor.vue', 'components/bible/BibleHistoryDrawer.vue'].map(path => readFile(source(path), 'utf8')))
  const combined = values.join('\n')
  for (const token of ['--nc-canvas', '--nc-paper', '--nc-ink', '--nc-muted', '--nc-border', '--nc-vermilion']) assert.match(combined, new RegExp(`var\\(${token}`))
  assert.doesNotMatch(combined, /#(?:302a23|eee6d7|fffaf0|cdbda5|9b372b|8b3028|6c5a49)\b/i)
  assert.doesNotMatch(combined, /rgba\((?:48,42,35|55,39,25|39,28,20|38,25,15)/)
  assert.match(values[0], /@click="retryFailure"/)
  assert.doesNotMatch(values[0], /store\.(?:error|conflict)\?\.message|\berror\.message/)
  assert.match(values[2], /basisFields/)
  assert.match(values[2], /<dl>/)
  assert.match(values[2], /\.history-detail\s+dd\s*\{[^}]*overflow-wrap\s*:\s*anywhere/u)
})
