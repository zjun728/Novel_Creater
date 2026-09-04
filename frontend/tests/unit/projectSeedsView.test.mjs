import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { createPinia } from 'pinia'
import { createSSRApp, h, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createRenderer, nextTick, ssrContextKey } from '@vue/runtime-core'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveStub = '\0project-seeds-naive-stub'
let vite
let ProjectSeedsView

const payload = {
  title: '典镇山河', genre: '东方玄幻', logline: '少年执掌残典，重建一县秩序。',
  targetAudience: '偏爱秩序建设与成长升级的长篇读者', protagonist: '守典人沈砚',
  desire: '保住故乡并查清典籍真相', coreConflict: '每次借典改制都会惊动更高层势力',
  worldPressure: '王朝崩解与诡异复苏同时逼近', openingHook: '县城一夜从舆图上消失',
  differentiation: '以基层制度建设推动玄幻升级', storyPromise: '每卷解决一层秩序危机并揭开大典真相',
  longFormPotential: '县、州、国、天下四级扩张，可支撑二百万字', marketBasis: '公开榜单显示建设流与规则怪谈均有稳定读者',
}
function canonicalDocument(value) {
  if (Array.isArray(value)) return value.map(canonicalDocument)
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonicalDocument(value[key])]))
  return value
}
function publicProvenance(facts) {
  return { ...facts, topicCandidate: facts.topicCandidate ?? null, provenanceHash: createHash('sha256').update(JSON.stringify(canonicalDocument(facts)), 'utf8').digest('hex') }
}

test.before(async () => {
  vite = await createServer({
    configFile: false, root: frontendRoot,
    resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } },
    server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error',
    plugins: [{
      name: 'project-seeds-naive-stub', enforce: 'pre',
      resolveId(id) { if (id === 'naive-ui') return naiveStub },
      load(id) {
        if (id !== naiveStub) return undefined
        return `
          import { defineComponent, h } from 'vue'
          const stub = (name, tag = 'div') => defineComponent({ name, inheritAttrs:false,
            setup(_, { attrs, slots }) { return () => h(tag, attrs, [slots.default?.(), slots.footer?.(), slots.action?.(), slots.extra?.()]) } })
          export const NAlert=stub('NAlert','aside'); export const NButton=stub('NButton','button')
          export const NEmpty=stub('NEmpty'); export const NInput=defineComponent({ props:{ value:{default:''} }, emits:['update:value'], inheritAttrs:false, setup(props,{attrs,emit}) { return () => h('textarea', { ...attrs, value: props.value, onInput:event => emit('update:value', event.target.value) }) } })
          export const NModal=stub('NModal'); export const NResult=stub('NResult')
          export const NSkeleton=stub('NSkeleton'); export const NSpin=stub('NSpin')
          export const NTag=stub('NTag','span'); export const useMessage=()=>({info(){},success(){},warning(){},error(){}})
        `
      },
    }, vuePlugin()],
    ssr: { noExternal: ['naive-ui'] }, optimizeDeps: { noDiscovery: true },
  })
  ProjectSeedsView = (await vite.ssrLoadModule('/src/views/ProjectSeedsView.vue')).default
})

test.after(async () => { await vite?.close() })

async function render({ selected = false, archived = false, seedStatus = archived ? 'archived' : 'candidate', canSelect = !selected && !archived, reasons = selected ? ['creation_contract_missing'] : ['seed_not_selected'] } = {}) {
  const originalFetch = globalThis.fetch
  const seed = {
    id: 's1', projectId: 'p1', status: seedStatus, revision: 1,
    revisionId: 'sr1', contentHash: 'a'.repeat(64), payload,
    recordedFields: ['title', 'genre', 'logline', 'protagonist', 'desire', 'coreConflict', 'worldPressure', 'openingHook', 'differentiation', 'targetAudience', 'storyPromise', 'longFormPotential', 'marketBasis'],
    isSelected: selected, selectionRevision: selected ? 1 : 0,
    capabilities: { referenced: false, hasFinalChapters: false, canEdit: !selected && !archived, canSelect, canArchive: !selected && !archived, canRestore: false, canPermanentlyDelete: false },
    provenance: publicProvenance({ kind: 'topic_candidate', snapshots: [], analysis: null, inspirationAttempt: null,
      topicCandidate: { id: 'c1', version: 2, hash: 'b'.repeat(64) }, publicNotes: [] }),
  }
  globalThis.fetch = async url => {
    if (String(url).endsWith('/projects/p1/seeds')) return new Response(JSON.stringify([seed]))
    if (String(url).endsWith('/projects/p1/selected-seed')) return new Response(JSON.stringify({
      activeSelection: selected ? { projectId:'p1', selectionRevision:1, seedId:'s1', seedRevisionId:'sr1', seedHash:'a'.repeat(64), selectedAt:1, updatedAt:1, seed } : null,
      seedReady: selected, contractReady: false, reasons,
    }))
    throw new Error(`unexpected request ${url}`)
  }
  try {
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] })
    const app = createSSRApp({ setup: () => () => h(RouterView) })
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    app.provide(shell.SHELL_PROJECT_CONTEXT, { state: ref(archived ? 'archived' : 'active'), project: ref({ id:'p1', title:'典镇山河', archivedAt:archived ? 1 : null }), error:ref(null), reload:async()=>null })
    app.use(createPinia())
    app.use(router)
    await router.push('/projects/p1/seeds')
    await router.isReady()
    return await renderToString(app)
  } finally { globalThis.fetch = originalFetch }
}

function testNode(type, text = '') {
  return { type, text, props: {}, children: [], parent: null, isConnected: true,
    focus() { this.focused = true; globalThis.document.activeElement = this },
    scrollIntoView(options) { this.scrollOptions = options },
    hasAttribute(name) { return Object.hasOwn(this.props, name) }, getAttribute(name) { return this.props[name] ?? null },
    setAttribute(name, value) { this.props[name] = value }, removeAttribute(name) { delete this.props[name] },
  }
}
function detach(node) { if (!node?.parent) return; node.parent.children.splice(node.parent.children.indexOf(node), 1); node.parent = null }
const clientRenderer = createRenderer({
  patchProp(node, key, _old, value) { if (value == null) delete node.props[key]; else node.props[key] = value },
  insert(child, parent, anchor = null) { detach(child); child.parent = parent; const index = anchor ? parent.children.indexOf(anchor) : -1; if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child) },
  remove: detach, createElement: type => testNode(type), createText: text => testNode('#text', String(text)), createComment: text => testNode('#comment', String(text || '')),
  setText(node, value) { node.text = String(value) }, setElementText(node, value) { node.text = String(value); node.children = [] },
  parentNode: node => node?.parent || null, nextSibling: node => node?.parent?.children[node.parent.children.indexOf(node) + 1] || null,
  querySelector: selector => globalThis.document?.querySelector?.(selector) ?? null, setScopeId(node, id) { node.props[id] = '' }, cloneNode: node => ({ ...node, props: { ...node.props }, children: [...node.children], parent: null }),
  insertStaticContent(content, parent, anchor) { const node = testNode('#static', content); clientRenderer.insert(node, parent, anchor); return [node, node] },
})
function walk(root, output = []) { if (!root) return output; output.push(root); for (const child of root.children || []) walk(child, output); return output }
function nodeText(node) { return [node.text || '', ...(node.children || []).map(nodeText)].join('') }
function button(root, label) { return walk(root).find(node => node.type === 'button' && nodeText(node).trim() === label) }
function buttonContaining(root, label) { return walk(root).find(node => node.type === 'button' && nodeText(node).includes(label)) }
function textarea(root, value) { return walk(root).find(node => node.type === 'textarea' && node.props.value === value) }
async function flush() { for (let index = 0; index < 4; index += 1) await Promise.resolve(); await nextTick() }
async function waitFor(check) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (check()) return true
    await new Promise(resolve => setTimeout(resolve, 1)); await flush()
  }
  return false
}
function deferred() { let resolve; let reject; const promise = new Promise((onResolve, onReject) => { resolve = onResolve; reject = onReject }); return { promise, resolve, reject } }
async function clientTemplate(path) {
  const source = await readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')
  const { descriptor } = parse(source, { filename: path }); const script = compileScript(descriptor, { id: `seeds-${path}` })
  const result = compile(descriptor.template.content, { mode: 'function', prefixIdentifiers: true, bindingMetadata: script.bindings })
  return new Function('Vue', result.code)({ ...await import('@vue/runtime-core'), withModifiers: handler => handler, withKeys: handler => handler })
}
async function installClientTemplates() {
  const paths = [
    'views/ProjectSeedsView.vue', 'components/seeds/SeedCard.vue', 'components/seeds/SeedDocument.vue', 'components/seeds/SeedEditor.vue', 'components/seeds/SeedOtherCandidatesDrawer.vue',
    'components/foundation/FoundationConfirmationDialog.vue', 'components/foundation/FoundationDocumentSection.vue', 'components/foundation/FoundationSectionIndex.vue', 'components/foundation/FoundationStatusRail.vue', 'components/foundation/FoundationWorkspace.vue',
  ]
  await Promise.all(paths.map(async path => {
    const component = (await vite.ssrLoadModule(`/src/${path}`)).default
    component.render = await clientTemplate(path)
  }))
}
function seed(id, values = payload, capabilities = {}) {
  const seedPayload = { ...values }
  const canonicalPayload = Object.fromEntries(Object.entries(seedPayload).sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)))
  const contentHash = createHash('sha256').update(JSON.stringify(canonicalPayload), 'utf8').digest('hex')
  return { id, projectId: 'p1', status: 'candidate', revision: 1, revisionId: `${id}-r1`, contentHash, payload: seedPayload, isSelected: false, selectionRevision: 0,
    recordedFields: ['title', 'genre', 'logline', 'protagonist', 'desire', 'coreConflict', 'worldPressure', 'openingHook', 'differentiation', 'targetAudience', 'storyPromise', 'longFormPotential', 'marketBasis'],
    capabilities: { referenced: false, hasFinalChapters: false, canEdit: true, canSelect: true, canArchive: true, canRestore: false, canPermanentlyDelete: true, ...capabilities },
    provenance: publicProvenance({ kind: 'manual', snapshots: [], analysis: null, inspirationAttempt: null, publicNotes: [] }), }
}

test('unconfirmed workspace keeps candidate list primary until an author explicitly opens a candidate', async () => {
  const html = await render()
  assert.match(html, /候选种子/)
  assert.match(html, /查看完整内容/)
  assert.doesNotMatch(html, /seed-document/)
  assert.doesNotMatch(html, new RegExp(payload.coreConflict))
})

test('candidate detail offers the author document confirmation CTA only after explicit open', async () => {
  const source = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  assert.match(source, /openedSeedId/)
  assert.match(source, /@open="startCandidate"/)
  assert.doesNotMatch(source, /startCandidate\(selectedCandidate\.value\)/)
  assert.match(source, /请先保存本地修改/)
  assert.match(source, /种子修订：\{\{ confirmationAdapter\.candidateRevision \}\}/)
})

test('authoritative reload keeps the local work copy when refresh fails', async () => {
  const source = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  assert.match(source, /await seedStore\.refresh\(projectId\)/)
  assert.match(source, /catch \(failure\) \{\r?\n    if \(isCurrentWorkspace\(projectId, generation\)\) loadError\.value/)
  assert.match(source, /beginWorkCopy\(openedCandidate\.value\)/)
})

test('archived unselected candidates remain inspectable but no longer editable', async () => {
  const html = await render({ archived: true, seedStatus: 'archived' })
  assert.match(html, /查看完整内容/)
  assert.match(html, /已归档 · 只读/)
  assert.doesNotMatch(html, /新建候选种子|编辑本区|保存种子|确认项目种子/)
})

test('opened candidate detail uses the author document confirmation CTA', async () => {
  const source = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  for (const value of Object.values(payload)) assert.match(source, /confirmationFields/)
  assert.match(source, /候选校订中/)
  assert.match(source, /确认项目种子/)
  assert.doesNotMatch(source, /进入创作契约/)
})

test('selected seed is read-only under the existing one-time confirmation authority', async () => {
  const html = await render({ selected: true })
  assert.match(html, /当前选定/)
  for (const value of Object.values(payload)) assert.match(html, new RegExp(value))
  const source = await readFile(new URL('../../src/components/seeds/SeedOtherCandidatesDrawer.vue', import.meta.url), 'utf8')
  assert.match(source, /其他候选（只读）/)
  assert.doesNotMatch(html, /新建候选种子|编辑本区|保存种子|确认项目种子|归档|恢复|永久删除|<(?:input|textarea|select)\b/)
})

test('one lifecycle label keeps archived confirmed and project-archived Seed views consistent', async () => {
  for (const html of [
    await render({ selected: true, seedStatus: 'archived' }),
    await render({ selected: true, archived: true, seedStatus: 'candidate' }),
  ]) {
    assert.ok((html.match(/只读归档/g) || []).length >= 2)
    assert.doesNotMatch(html, /待确认|已确认 \/ 已冻结|已确认并永久冻结/)
  }
  const page = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  assert.match(page, /const lifecycleStatus = computed/)
  assert.match(page, /:status-label="lifecycleStatus\.label"/)
  assert.match(page, /<p>\{\{ lifecycleStatus\.description \}\}<\/p>/)
})

test('Seed confirmation adapter owns revision, complete payload, provenance, and server selection capability', async () => {
  const source = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  assert.match(source, /const confirmationAdapter = computed/)
  for (const member of ['candidateRevision', 'payload', 'provenance', 'canConfirm']) {
    assert.match(source, new RegExp(member))
  }
  assert.match(source, /confirmationAdapter\.value\.candidate/)
})

test('main readiness rail translates every stable Seed reason without exposing raw codes', async () => {
  const html = await render({ selected: true, canSelect: false, reasons: ['seed_not_selected', 'creation_contract_missing', 'selected_seed_drift', 'binding_not_verified'] })
  for (const label of ['尚未确认项目种子', '尚未创建创作契约', '选定种子已发生漂移', '项目绑定尚未验证']) assert.match(html, new RegExp(label))
  for (const code of ['seed_not_selected', 'creation_contract_missing', 'selected_seed_drift', 'binding_not_verified']) assert.doesNotMatch(html, new RegExp(code))
})

test('project seed workspace contains no duplicate market manager, analysis, or chat', async () => {
  const files = await Promise.all([
    '../../src/views/ProjectSeedsView.vue', '../../src/components/seeds/SeedCard.vue',
    '../../src/components/seeds/SeedEditor.vue', '../../src/stores/seedStore.js',
  ].map(file => readFile(new URL(file, import.meta.url), 'utf8')))
  const source = files.join('\n')
  assert.doesNotMatch(source, /MarketEvidencePanel|useMarketSourceStore|requestInspiration|seed-inspiration|灵感讨论|自动刷新|定时调度|api\.topics/)
  assert.match(files[0], /expectedSeedRevision: editTarget\.revision/)
  assert.match(files[0], /expectedSelectionRevision: seedStore\.selectionRevision/)
  assert.match(files[0], /重新加载权威状态/)
  assert.match(files[0], /seedStore\.selectSeed/)
  for (const key of ['targetAudience', 'storyPromise', 'longFormPotential', 'marketBasis']) assert.match(files[2], new RegExp(key))
})

test('seed workspace declares the local manual-candidate and route-leave contracts', async () => {
  const source = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  assert.match(source, /新建候选种子/)
  assert.match(source, /seedStore\.createSeed\(projectId, payload, \{/)
  assert.match(source, /onBeforeRouteLeave/)
  assert.match(source, /onBeforeRouteUpdate/)
  assert.match(source, /永久删除候选/)
})

test('Seed authoring fences candidate context and reports incomplete required fields before transport', async () => {
  const [view, card, editor] = await Promise.all([
    readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/seeds/SeedCard.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/seeds/SeedEditor.vue', import.meta.url), 'utf8'),
  ])
  assert.match(view, /candidateEpoch/)
  assert.match(view, /当前操作尚未完成，请稍候/)
  assert.match(view, /请填写必填项：/)
  assert.match(view, /:focus-on-navigate="false"/)
  assert.match(card, /:disabled="busy"/)
  assert.match(editor, /limitUnicodeScalarText/)
  assert.match(editor, /unicodeScalarLength/)
  assert.match(editor, /show-count/)
})

test('Seed editor truncates astral input by Unicode scalars while retaining an accessible count', async () => {
  const source = await readFile(new URL('../../src/components/seeds/SeedEditor.vue', import.meta.url), 'utf8')
  assert.match(source, /limitUnicodeScalarText\(String\(value \?\? ''\), 2000\)/)
  assert.match(source, /unicodeScalarLength\(String\(modelValue\[key\] \|\| ''\)\)/)
  assert.match(source, /aria-live="polite"/)
})

test('mounted Seed editor accepts 1001 emoji and bounds input at 2000 Unicode scalars', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document
  globalThis.fetch = async url => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/seeds')) return new Response(JSON.stringify([]))
    if (path.endsWith('/selected-seed')) return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
    throw new Error(`unexpected ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js'); const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] }); const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null }); await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()
    button(root, '新建候选种子').props.onClick(); await flush(); buttonContaining(root, '作品定位').props.onClick(); await flush()
    const input = walk(root).find(node => node.type === 'textarea'); input.props.onInput({ target: { value: '\u{1F4DA}'.repeat(1001) } }); await flush(); assert.equal(walk(root).find(node => node.type === 'textarea').props.value, '\u{1F4DA}'.repeat(1001))
    walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: '\u{1F4DA}'.repeat(2001) } }); await flush(); assert.equal([...walk(root).find(node => node.type === 'textarea').props.value].length, 2000)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument }
})

test('Seed workspace keeps server payload authoritative when an opened candidate becomes read-only', async () => {
  const source = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  assert.match(source, /mainReadOnly\.value \? mainSeed\.value\?\.payload : candidateWorkCopy\.value/)
  assert.match(source, /本地未保存副本已保留，不作为当前权威内容/)
  assert.match(source, /放弃本地副本/)
})

test('Seed workspace closes an uncertain delete dialog and scrolls only after accepted section navigation', async () => {
  const source = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  assert.match(source, /kind === 'delete' && !seedStore\.selectionHydrated/)
  assert.match(source, /lifecycleTarget\.value = null/)
  assert.match(source, /scrollIntoView\?\.\(\{ block: 'start'/)
})

test('Seed update failures enter reconciliation exactly when the store invalidates authority', async () => {
  const source = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  const saveSource = source.slice(source.indexOf('async function saveSeed'), source.indexOf('async function lifecycle'))
  assert.match(saveSource, /if \(!seedStore\.selectionHydrated\) \{ reconciliationRequired\.value = true; return \}/)
})

test('Seed section display labels derive filled and suggested states from its current payload', async () => {
  const source = await readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8')
  assert.match(source, /function sectionDisplayState\(section\)/)
  assert.match(source, /sectionFieldKeys\[section\]/)
  assert.match(source, /sectionDisplayState\('promise'\)\.label/)
})

test('Seed presentation uses the exact approved section group labels everywhere', async () => {
  const [view, document] = await Promise.all([
    readFile(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/seeds/SeedDocument.vue', import.meta.url), 'utf8'),
  ])
  for (const label of ['作品定位', '故事核心', '开篇与压力', '差异与承诺']) {
    assert.match(view, new RegExp(label))
    assert.match(document, new RegExp(label))
  }
  for (const label of ['故事定位', '人物与冲突', '压力与开篇', '承诺与延展']) {
    assert.doesNotMatch(view, new RegExp(label))
    assert.doesNotMatch(document, new RegExp(label))
  }
})

test('read-only section navigation scrolls and focuses without entering edit mode', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document
  const confirmed = { ...seed('s1', payload, { canEdit: false, canSelect: false, canArchive: false }), isSelected: true, selectionRevision: 1 }
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/seeds') && (!options.method || options.method === 'GET')) return new Response(JSON.stringify([confirmed]))
    if (path.endsWith('/selected-seed')) return new Response(JSON.stringify({ activeSelection: { projectId: 'p1', selectionRevision: 1, seedId: 's1', seedRevisionId: confirmed.revisionId, seedHash: confirmed.contentHash, selectedAt: 1, updatedAt: 1, seed: confirmed }, seedReady: true, contractReady: false, reasons: ['creation_contract_missing'] }))
    throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] })
    const app = clientRenderer.createApp({ render: () => h(RouterView) }); app.use(createPinia()); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state: ref('active'), project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null })
    await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()
    buttonContaining(root, '故事核心').props.onClick(); await flush()
    const heading = globalThis.document.getElementById('seed-core')
    assert.equal(globalThis.document.activeElement, heading)
    assert.deepEqual(heading.scrollOptions, { block: 'start', behavior: 'smooth' })
    assert.doesNotMatch(nodeText(root), /正在校订/)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument }
})

test('mounted manual creation reports the exact missing required fields without dispatching a write', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document
  let writes = 0
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/seeds') && (!options.method || options.method === 'GET')) return new Response(JSON.stringify([]))
    if (path.endsWith('/selected-seed')) return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
    if (path.endsWith('/seeds') && options.method === 'POST') { writes += 1; return new Response(JSON.stringify(seed('unexpected')))
    }
    throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] })
    const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null })
    await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()
    button(root, '新建候选种子').props.onClick(); await flush()
    buttonContaining(root, '作品定位').props.onClick(); await flush()
    walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: '仅填标题' } }); await flush()
    walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush()
    const create = button(root, '创建候选种子'); assert.equal(create.props.disabled, false)
    create.props.onClick(); await flush()
    assert.equal(writes, 0)
    assert.match(nodeText(root), /请填写必填项：题材、一句话故事、主角、核心欲望、核心冲突、世界压力、开篇钩子、差异化/)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument }
})

test('an unsaved new candidate becomes an explicit local recovery panel when the project is archived', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document
  globalThis.fetch = async url => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/seeds')) return new Response(JSON.stringify([]))
    if (path.endsWith('/selected-seed')) return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
    throw new Error(`unexpected ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js'); const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] }); const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null }); await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()
    button(root, '新建候选种子').props.onClick(); await flush(); buttonContaining(root, '作品定位').props.onClick(); await flush(); walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: '仅本地草稿' } }); await flush(); assert.ok(textarea(root, '仅本地草稿'))
    state.value = 'archived'; assert.equal(await waitFor(() => nodeText(root).includes('本地未保存副本已保留，不作为当前权威内容')), true)
    assert.match(nodeText(root), /从一份候选开始校订/); assert.equal(textarea(root, '仅本地草稿'), undefined); assert.doesNotMatch(nodeText(root), /候选校订中/)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument }
})

test('authoritative reconciliation preserves removed and newly selected candidate edits only as recovery work', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document
  for (const outcome of ['removed', 'selected']) {
    let rows = [seed('s1')]; let activeSelection = null
    globalThis.fetch = async (url, options = {}) => {
      const path = new URL(String(url), 'http://example.test').pathname
      if (path.endsWith('/seeds') && (!options.method || options.method === 'GET')) return new Response(JSON.stringify(rows))
      if (path.endsWith('/selected-seed') && (!options.method || options.method === 'GET')) return new Response(JSON.stringify({ activeSelection, seedReady: Boolean(activeSelection), contractReady: false, reasons: activeSelection ? ['creation_contract_missing'] : ['seed_not_selected'] }))
      if (options.method === 'PUT' && path.endsWith('/seeds/s1')) return new Response(JSON.stringify({ code: 'SelectionConflict', message: 'stale' }), { status: 409 })
      throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
    }
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js'); const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] }); const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null }); await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()
    buttonContaining(root, '查看完整内容').props.onClick(); await flush(); button(root, '编辑本区').props.onClick(); await flush(); walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: `${outcome}-本地稿` } }); await flush(); walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush(); button(root, '保存种子').props.onClick(); await new Promise(resolve => setTimeout(resolve, 0)); await flush()
    if (outcome === 'removed') rows = []
    else { const selected = seed('s2', { ...payload, title: '权威候选' }); selected.isSelected = true; selected.selectionRevision = 1; rows = [selected]; activeSelection = { projectId: 'p1', selectionRevision: 1, seedId: 's2', seedRevisionId: selected.revisionId, seedHash: selected.contentHash, selectedAt: 1, updatedAt: 1, seed: selected } }
    button(root, '重新加载权威状态').props.onClick(); await new Promise(resolve => setTimeout(resolve, 0)); await flush()
    assert.match(nodeText(root), /本地未保存副本已保留，不作为当前权威内容/)
    assert.ok(button(root, '放弃本地副本'))
    assert.doesNotMatch(nodeText(root), new RegExp(`${outcome}-本地稿`))
    if (outcome === 'selected') assert.match(nodeText(root), /权威候选/)
    app.unmount()
  }
  globalThis.fetch = originalFetch; globalThis.document = originalDocument
})

test('a deferred save keeps the opened candidate context when a list switch is attempted', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document; const pendingUpdate = deferred()
  const first = seed('s1'); const second = seed('s2', { ...payload, title: '候选 B' })
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/seeds') && (!options.method || options.method === 'GET')) return new Response(JSON.stringify([first, second]))
    if (path.endsWith('/selected-seed')) return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
    if (options.method === 'PUT' && /\/seeds\/s1$/.test(path)) return pendingUpdate.promise
    throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] })
    const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null })
    await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()
    buttonContaining(root, '查看完整内容').props.onClick(); await flush(); button(root, '编辑本区').props.onClick(); await flush(); walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: '候选 A 的保存稿' } }); await flush(); walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush(); button(root, '保存种子').props.onClick(); await flush()
    const back = button(root, '返回候选列表'); assert.equal(back.props.disabled, true); back.props.onClick(); await flush()
    const coreHeading = globalThis.document.getElementById('seed-core'); buttonContaining(root, '故事核心').props.onClick(); await flush(); assert.equal(coreHeading.scrollOptions, undefined)
    assert.match(nodeText(root), /候选 A 的保存稿/); assert.doesNotMatch(nodeText(root), /候选 B/)
    pendingUpdate.resolve(new Response(JSON.stringify(seed('s1', { ...payload, title: '候选 A 的保存稿' }))))
    await flush(); await flush(); assert.match(nodeText(root), /候选 A 的保存稿/); assert.doesNotMatch(nodeText(root), /候选 B/)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument }
})

test('mounted seed workspace keeps page-owned edits, creates exactly one complete candidate, confirms deletion, and guards dirty route changes', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document; const originalConfirm = globalThis.confirm
  let projectOne = [seed('s1'), seed('s2', { ...payload, title: '第二候选' }, { canPermanentlyDelete: false })]
  const projectTwo = []
  const calls = { create: [], update: [], archive: [], restore: [], delete: [], list: { p1: 0, p2: 0 } }; const pendingDelete = deferred()
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url), 'http://example.test').pathname; const projectId = path.includes('/projects/p2/') ? 'p2' : 'p1'; const rows = projectId === 'p1' ? projectOne : projectTwo
    if (path.endsWith('/seeds') && (!options.method || options.method === 'GET')) { calls.list[projectId] += 1; return new Response(JSON.stringify(rows)) }
    if (path.endsWith('/selected-seed')) return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
    if (path.endsWith('/seeds') && options.method === 'POST') {
      const body = JSON.parse(options.body); calls.create.push(body); const created = seed('created', body.payload); projectOne = [...projectOne, created]; return new Response(JSON.stringify(created))
    }
    if (options.method === 'PUT' && /\/seeds\/s1$/.test(path)) { const body = JSON.parse(options.body); calls.update.push(body); const updated = seed('s1', body.payload); updated.revision = 2; updated.revisionId = 's1-r2'; projectOne = projectOne.map(item => item.id === 's1' ? updated : item); return new Response(JSON.stringify(updated)) }
    if (options.method === 'POST' && /\/seeds\/s1\/archive$/.test(path)) { calls.archive.push(JSON.parse(options.body)); const archived = seed('s1', projectOne[0].payload, { canArchive: false, canRestore: true, canPermanentlyDelete: true }); archived.status = 'archived'; archived.revision = 2; archived.revisionId = 's1-r2'; projectOne = projectOne.map(item => item.id === 's1' ? archived : item); return new Response(JSON.stringify(archived)) }
    if (options.method === 'POST' && /\/seeds\/s1\/restore$/.test(path)) { calls.restore.push(JSON.parse(options.body)); const restored = seed('s1', projectOne[0].payload, { canArchive: true, canRestore: false, canPermanentlyDelete: true }); restored.revision = 2; restored.revisionId = 's1-r2'; projectOne = projectOne.map(item => item.id === 's1' ? restored : item); return new Response(JSON.stringify(restored)) }
    if (options.method === 'DELETE') { calls.delete.push(JSON.parse(options.body)); return pendingDelete.promise }
    throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] })
    const state = ref('active'); const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia()
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null })
    await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()

    assert.ok(button(root, '新建候选种子'))
    const liveStatus = walk(root).find(node => node.props.role === 'status')
    assert.ok(liveStatus); assert.equal(liveStatus.props['aria-live'], 'polite')
    const lockedCard = walk(root).find(node => node.type === 'article' && nodeText(node).includes('第二候选'))
    assert.equal(walk(lockedCard).some(node => node.type === 'button' && nodeText(node).trim() === '永久删除'), false)
    const openFirst = buttonContaining(root, '查看完整内容'); openFirst.props.onClick(); await flush()
    assert.equal(globalThis.document.activeElement?.props.id, 'seed-document-heading')
    button(root, '编辑本区').props.onClick(); await flush()
    let firstEditor = walk(root).filter(node => node.type === 'textarea'); firstEditor[0].props.onInput({ target: { value: '取消标题' } }); await flush()
    button(root, '取消').props.onClick(); await flush(); assert.match(nodeText(root), new RegExp(payload.title))
    button(root, '编辑本区').props.onClick(); await flush()
    firstEditor = walk(root).filter(node => node.type === 'textarea'); firstEditor[0].props.onInput({ target: { value: '受控标题' } }); await flush()
    walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush()
    assert.equal(globalThis.document.activeElement?.props.id, 'seed-positioning')
    buttonContaining(root, '故事核心').props.onClick(); await flush()
    assert.match(nodeText(root), /受控标题/)
    walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: '人物临时修改' } }); await flush()
    const pressureHeading = globalThis.document.getElementById('seed-pressure')
    globalThis.confirm = () => false; buttonContaining(root, '开篇与压力').props.onClick(); await flush(); assert.match(nodeText(root), /正在校订「故事核心」/); assert.equal(pressureHeading.scrollOptions, undefined)
    globalThis.confirm = () => true; buttonContaining(root, '开篇与压力').props.onClick(); await flush(); assert.match(nodeText(root), /正在校订「开篇与压力」/)
    buttonContaining(root, '故事核心').props.onClick(); await flush(); assert.ok(textarea(root, payload.logline)); walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush()
    globalThis.confirm = () => false; button(root, '返回候选列表').props.onClick(); await flush()
    assert.match(nodeText(root), /受控标题/)
    globalThis.confirm = () => true; button(root, '返回候选列表').props.onClick(); await flush()
    assert.ok(button(root, '新建候选种子'))

    buttonContaining(root, '查看完整内容').props.onClick(); await flush(); button(root, '编辑本区').props.onClick(); await flush()
    walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: '保存后的标题' } }); await flush(); walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush()
    button(root, '保存种子').props.onClick(); await flush(); await flush(); assert.equal(await waitFor(() => nodeText(root).includes('当前修订已保存。')), true)
    assert.equal(calls.update.length, 1); assert.deepEqual(Object.keys(calls.update[0].payload).sort(), Object.keys(payload).sort()); assert.equal(button(root, '保存种子').props.disabled, true)
    button(root, '返回候选列表').props.onClick(); await flush()

    button(root, '归档').props.onClick(); await flush(); await flush(); assert.equal(await waitFor(() => Boolean(button(root, '恢复'))), true); assert.deepEqual(calls.archive, [{ expectedSeedRevision: 2, expectedSelectionRevision: 0 }]); assert.ok(button(root, '恢复')); assert.equal(nodeText(liveStatus), '候选种子已归档')
    const archivedCard = walk(root).find(node => node.type === 'article' && nodeText(node).includes('保存后的标题')); buttonContaining(archivedCard, '查看完整内容').props.onClick(); await flush(); assert.match(nodeText(root), /只读修订/); assert.equal((nodeText(root).match(/该历史版本未记录/g) || []).length, 0); for (const label of ['编辑本区', '保存种子', '确认项目种子', '归档', '恢复', '永久删除']) assert.equal(button(root, label), undefined); button(root, '返回候选列表').props.onClick(); await flush()
    button(root, '恢复').props.onClick(); await flush(); await flush(); assert.equal(await waitFor(() => Boolean(button(root, '新建候选种子'))), true); assert.deepEqual(calls.restore, [{ expectedSeedRevision: 2, expectedSelectionRevision: 0 }]); assert.ok(button(root, '归档'))

    button(root, '新建候选种子').props.onClick(); await flush()
    for (const section of ['作品定位', '故事核心', '开篇与压力', '差异与承诺']) {
      buttonContaining(root, section).props.onClick(); await flush()
      const fields = walk(root).filter(node => node.type === 'textarea')
      for (const field of fields) { if (!((section === '作品定位' && fields.indexOf(field) === 2) || (section === '差异与承诺' && fields.indexOf(field) > 0))) { field.props.onInput({ target: { value: `新建-${calls.create.length}-${section}-${fields.indexOf(field)}` } }); await flush() } }
      walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush()
    }
    const create = button(root, '创建候选种子'); assert.equal(create.props.disabled, false); create.props.onClick(); await flush(); await flush(); assert.equal(await waitFor(() => Boolean(button(root, '保存种子'))), true)
    assert.equal(calls.create.length, 1); assert.deepEqual(calls.create[0].payload, { title: '新建-0-作品定位-0', genre: '新建-0-作品定位-1', logline: '新建-0-故事核心-0', protagonist: '新建-0-故事核心-1', desire: '新建-0-故事核心-2', coreConflict: '新建-0-故事核心-3', worldPressure: '新建-0-开篇与压力-0', openingHook: '新建-0-开篇与压力-1', differentiation: '新建-0-差异与承诺-0', targetAudience: '', storyPromise: '', longFormPotential: '', marketBasis: '' }); assert.deepEqual(calls.create[0].provenance, { kind: 'manual', snapshotIds: [], analysisId: null, inspirationAttemptId: null, publicNotes: [] }); assert.match(calls.create[0].idempotencyKey, /^[A-Za-z0-9_-]{64}$/u); assert.equal(button(root, '保存种子').props.disabled, true)

    button(root, '返回候选列表').props.onClick(); await flush()
    const permanent = walk(root).find(node => node.type === 'button' && nodeText(node).trim() === '永久删除')
    permanent.props.onClick(); await flush(); assert.equal(calls.delete.length, 0); assert.match(nodeText(body), /永久删除候选种子/)
    walk(body).filter(node => node.type === 'button' && nodeText(node).trim() === '永久删除').at(-1).props.onClick(); await flush(); const deleteDialog = walk(body).find(node => node.props.role === 'dialog'); deleteDialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush(); assert.ok(walk(body).find(node => node.props.role === 'dialog')); deleteDialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); pendingDelete.resolve(new Response(JSON.stringify({ ok: true }))); await flush(); await flush(); assert.equal(calls.delete.length, 1); assert.deepEqual(calls.delete[0], { expectedSeedRevision: 2, expectedSelectionRevision: 0 }); assert.equal(globalThis.document.activeElement?.props.id, 'seed-candidate-list-heading')

    buttonContaining(root, '查看完整内容').props.onClick(); await flush(); button(root, '编辑本区').props.onClick(); await flush(); walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: '路由脏修改' } }); await flush()
    let prompts = 0; globalThis.confirm = () => { prompts += 1; return false }; await router.push('/projects/p2/seeds'); await flush(); assert.equal(prompts, 1); assert.equal(router.currentRoute.value.params.projectId, 'p1'); assert.match(nodeText(root), /路由脏修改/)
    prompts = 0; globalThis.confirm = () => { prompts += 1; return true }; await router.push('/projects/p2/seeds'); await flush(); await flush(); assert.equal(prompts, 1); assert.equal(calls.list.p2, 1); assert.equal(router.currentRoute.value.params.projectId, 'p2'); assert.ok(button(root, '新建候选种子'))
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument; globalThis.confirm = originalConfirm }
})

test('mounted selection outcome reconciliation closes the modal, fails closed, and only adopts refreshed authority', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document; const originalConfirm = globalThis.confirm
  const pendingSelection = deferred(); let refreshMode = 'initial'; const original = seed('s1')
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/selected-seed') && options.method === 'PUT') return pendingSelection.promise
    if (path.endsWith('/seeds') && (!options.method || options.method === 'GET')) {
      if (refreshMode === 'failed') return new Response(JSON.stringify({ code: 'refresh_failed', message: 'reload failed' }), { status: 503 })
      return new Response(JSON.stringify([original]))
    }
    if (path.endsWith('/selected-seed')) {
      if (refreshMode !== 'confirmed') return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
      const selected = { ...original, isSelected: true, selectionRevision: 1 }
      return new Response(JSON.stringify({ activeSelection: { projectId: 'p1', selectionRevision: 1, seedId: 's1', seedRevisionId: selected.revisionId, seedHash: selected.contentHash, seed: selected }, seedReady: true, contractReady: false, reasons: [] }))
    }
    throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] })
    const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null })
    await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()

    buttonContaining(root, '查看完整内容').props.onClick(); await flush(); const openConfirmation = button(root, '确认项目种子'); openConfirmation.props.onClick(); await flush()
    const nodes = () => [...walk(root), ...walk(body)]
    const dialog = nodes().find(node => node.props.role === 'dialog'); assert.ok(dialog)
    const confirm = nodes().find(node => node !== openConfirmation && node.type === 'button' && nodeText(node).trim() === '确认项目种子'); assert.ok(confirm); confirm.props.onClick(); await flush()
    await router.push('/projects/p2/seeds'); await flush(); assert.equal(router.currentRoute.value.params.projectId, 'p1')
    dialog.props.onKeydown({ key: 'Escape', preventDefault() {} }); await flush()
    assert.ok(nodes().find(node => node.props.role === 'dialog'))

    pendingSelection.resolve(new Response(JSON.stringify({ code: 'outcome_unknown', message: 'uncertain' }), { status: 503 })); await flush(); await flush(); await new Promise(resolve => setTimeout(resolve, 0)); await flush()
    assert.equal(nodes().some(node => node.props.role === 'dialog'), false)
    assert.equal(globalThis.document.activeElement?.props.id, 'seed-document-heading')
    assert.match(nodeText(root), /重新加载权威状态/)
    assert.doesNotMatch(nodeText(root), /服务端允许确认/)
    for (const label of ['新建候选种子', '保存种子', '确认项目种子', '编辑本区']) assert.equal(button(root, label), undefined)

    refreshMode = 'failed'; button(root, '重新加载权威状态').props.onClick(); await flush(); await new Promise(resolve => setTimeout(resolve, 0)); await flush()
    assert.match(nodeText(root), /reload failed/)
    assert.match(nodeText(root), /重新加载权威状态/)
    assert.match(nodeText(root), new RegExp(payload.title))

    refreshMode = 'confirmed'; button(root, '重新加载权威状态').props.onClick(); await flush(); await new Promise(resolve => setTimeout(resolve, 0)); await flush()
    assert.equal(button(root, '重新加载权威状态'), undefined)
    assert.match(nodeText(root), /当前选定/)
    assert.match(nodeText(root), new RegExp(payload.title))
    assert.equal(globalThis.document.activeElement?.props.id, 'seed-document-heading')
    for (const label of ['新建候选种子', '保存种子', '确认项目种子', '编辑本区', '归档', '恢复', '永久删除']) assert.equal(button(root, label), undefined)
    assert.equal(walk(root).some(node => ['input', 'textarea', 'select'].includes(node.type)), false)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument; globalThis.confirm = originalConfirm }
})

test('successful Seed confirmation immediately removes every candidate write control and input', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document
  const original = seed('s1')
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/seeds') && (!options.method || options.method === 'GET')) return new Response(JSON.stringify([original]))
    if (path.endsWith('/selected-seed') && options.method === 'PUT') {
      return new Response(JSON.stringify({ ...original, isSelected: true, selectionRevision: 1 }))
    }
    if (path.endsWith('/selected-seed')) {
      return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
    }
    throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] })
    const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null })
    await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()

    buttonContaining(root, '查看完整内容').props.onClick(); await flush(); button(root, '确认项目种子').props.onClick(); await flush()
    const confirm = [...walk(root), ...walk(body)].find(node => node.type === 'button' && nodeText(node).trim() === '确认项目种子' && node !== button(root, '确认项目种子'))
    assert.ok(confirm); confirm.props.onClick()
    assert.equal(await waitFor(() => /项目种子已确认|已确认并永久冻结/.test(nodeText(root))), true)

    assert.match(nodeText(root), /项目种子已确认|已确认并永久冻结/)
    assert.equal([...walk(root), ...walk(body)].some(node => node.props.role === 'dialog'), false)
    for (const label of [
      '新建候选种子', '编辑本区', '保存种子', '确认项目种子',
      '归档', '恢复', '永久删除', '生成候选', 'AI 生成',
    ]) assert.equal(button(root, label), undefined, `write control remained: ${label}`)
    assert.equal(walk(root).some(node => ['input', 'textarea', 'select'].includes(node.type)), false)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument }
})

test('mounted selection conflict also enters the same fail-closed reconciliation state', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document; const original = seed('s1')
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/seeds')) return new Response(JSON.stringify([original]))
    if (path.endsWith('/selected-seed') && options.method === 'PUT') return new Response(JSON.stringify({ code: 'SelectionConflict', message: 'stale selection' }), { status: 409 })
    if (path.endsWith('/selected-seed')) return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
    throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] })
    const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null })
    await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()

    buttonContaining(root, '查看完整内容').props.onClick(); await flush(); button(root, '确认项目种子').props.onClick(); await flush()
    const confirm = [...walk(root), ...walk(body)].find(node => node.type === 'button' && nodeText(node).trim() === '确认项目种子' && node !== button(root, '确认项目种子')); assert.ok(confirm); confirm.props.onClick(); await new Promise(resolve => setTimeout(resolve, 0)); await flush()
    assert.equal([...walk(root), ...walk(body)].some(node => node.props.role === 'dialog'), false)
    assert.match(nodeText(root), /重新加载权威状态/)
    assert.doesNotMatch(nodeText(root), /服务端允许确认/)
    for (const label of ['新建候选种子', '保存种子', '确认项目种子', '编辑本区']) assert.equal(button(root, label), undefined)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument }
})

test('mounted update conflict retains local text through authoritative refresh and retries with the new CAS revision', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document; const originalConfirm = globalThis.confirm
  let authority = seed('s1'); const second = seed('s2', { ...payload, title: '第二候选' }); const writes = []
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/seeds') && (!options.method || options.method === 'GET')) return new Response(JSON.stringify([authority, second]))
    if (path.endsWith('/selected-seed') && (!options.method || options.method === 'GET')) return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
    if (options.method === 'PUT') {
      writes.push(JSON.parse(options.body))
      if (writes.length === 1) { authority = seed('s1', { ...payload, title: '服务端新标题' }); authority.revision = 2; authority.revisionId = 's1-r2'; return new Response(JSON.stringify({ code: 'SelectionConflict', message: 'stale' }), { status: 409 }) }
      authority = seed('s1', writes[1].payload); authority.revision = 3; authority.revisionId = 's1-r3'; return new Response(JSON.stringify(authority))
    }
    throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js'); const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] }); const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null }); await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()
    buttonContaining(root, '查看完整内容').props.onClick(); await flush(); button(root, '编辑本区').props.onClick(); await flush(); walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: '本地保留标题' } }); await flush(); walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush()
    button(root, '保存种子').props.onClick(); await new Promise(resolve => setTimeout(resolve, 0)); await flush(); assert.equal(writes.length, 1); assert.match(nodeText(root), /本地保留标题/); assert.match(nodeText(root), /重新加载权威状态/); assert.equal(button(root, '放弃本地修改并采用权威版本'), undefined)
    button(root, '重新加载权威状态').props.onClick(); await new Promise(resolve => setTimeout(resolve, 0)); await flush(); assert.match(nodeText(root), /权威版本已更新，本地修改仍保留，请核对后保存/); assert.match(nodeText(root), /本地保留标题/)
    assert.ok(button(root, '放弃本地修改并采用权威版本')); globalThis.confirm = () => true; button(root, '返回候选列表').props.onClick(); await flush(); assert.doesNotMatch(nodeText(root), /权威版本已更新，本地修改仍保留，请核对后保存|放弃本地修改并采用权威版本/); const secondCard = walk(root).find(node => node.type === 'article' && nodeText(node).includes('第二候选')); buttonContaining(secondCard, '查看完整内容').props.onClick(); await flush(); assert.doesNotMatch(nodeText(root), /权威版本已更新，本地修改仍保留，请核对后保存|放弃本地修改并采用权威版本/)
    button(root, '返回候选列表').props.onClick(); await flush(); const reconciledCard = walk(root).find(node => node.type === 'article' && nodeText(node).includes('服务端新标题')); buttonContaining(reconciledCard, '查看完整内容').props.onClick(); await flush()
    button(root, '编辑本区').props.onClick(); await flush(); walk(root).find(node => node.type === 'textarea').props.onInput({ target: { value: '本地保留标题' } }); await flush(); walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush()
    button(root, '保存种子').props.onClick(); await new Promise(resolve => setTimeout(resolve, 0)); await flush(); assert.equal(writes.length, 2); assert.equal(writes[1].expectedSeedRevision, 2); assert.equal(writes[1].expectedSelectionRevision, 0)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument; globalThis.confirm = originalConfirm }
})

test('manual create keeps one idempotency key for an explicit outcome-unknown replay', async () => {
  await installClientTemplates()
  const originalFetch = globalThis.fetch; const originalDocument = globalThis.document; const requests = []
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(String(url), 'http://example.test').pathname
    if (path.endsWith('/seeds') && (!options.method || options.method === 'GET')) return new Response(JSON.stringify([]))
    if (path.endsWith('/selected-seed')) return new Response(JSON.stringify({ activeSelection: null, seedReady: false, contractReady: false, reasons: ['seed_not_selected'] }))
    if (path.endsWith('/seeds') && options.method === 'POST') { requests.push(JSON.parse(options.body)); return requests.length === 1 ? new Response(JSON.stringify({ code: 'outcome_unknown', message: 'uncertain' }), { status: 503 }) : new Response(JSON.stringify(seed('created', requests[0].payload))) }
    throw new Error(`unexpected ${options.method || 'GET'} ${path}`)
  }
  try {
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js'); const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/seeds', component: ProjectSeedsView, props: route => ({ projectId: String(route.params.projectId) }) }] }); const app = clientRenderer.createApp({ render: () => h(RouterView) }); const pinia = createPinia(); const state = ref('active')
    app.use(pinia); app.use(router); app.provide(ssrContextKey, { modules: new Set() }); app.provide(shell.SHELL_PROJECT_CONTEXT, { state, project: ref({ id: 'p1', archivedAt: null }), error: ref(null), reload: async () => null }); await router.push('/projects/p1/seeds'); await router.isReady(); const root = testNode('root'); const body = testNode('body'); globalThis.document = { activeElement: null, querySelector: selector => selector === 'body' ? body : null, getElementById: id => [...walk(root), ...walk(body)].find(node => node.props.id === id) || null }; app.mount(root); await flush(); await flush()
    button(root, '新建候选种子').props.onClick(); await flush()
    for (const [section, count] of [['作品定位', 2], ['故事核心', 4], ['开篇与压力', 2], ['差异与承诺', 1]]) { buttonContaining(root, section).props.onClick(); await flush(); const fields = walk(root).filter(node => node.type === 'textarea'); for (const field of fields.slice(0, count)) { field.props.onInput({ target: { value: `${section}-${fields.indexOf(field)}` } }); await flush() } walk(root).find(node => node.type === 'form').props.onSubmit({ preventDefault() {} }); await flush() }
    button(root, '创建候选种子').props.onClick(); await new Promise(resolve => setTimeout(resolve, 0)); await flush(); assert.equal(requests.length, 1)
    assert.match(nodeText(root), /重新加载权威状态/); button(root, '重新加载权威状态').props.onClick(); await new Promise(resolve => setTimeout(resolve, 0)); await flush()
    button(root, '创建候选种子').props.onClick(); await new Promise(resolve => setTimeout(resolve, 0)); await flush(); assert.equal(requests.length, 2); assert.equal(requests[0].idempotencyKey, requests[1].idempotencyKey); assert.deepEqual(requests[0].provenance, { kind: 'manual', snapshotIds: [], analysisId: null, inspirationAttemptId: null, publicNotes: [] }); assert.deepEqual(requests[0].payload, requests[1].payload)
    app.unmount()
  } finally { globalThis.fetch = originalFetch; globalThis.document = originalDocument }
})
