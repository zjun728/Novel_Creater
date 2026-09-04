import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from '@vue/runtime-core'
import { createRenderer, defineComponent, h, nextTick, ref, ssrContextKey } from '@vue/runtime-core'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const source = path => new URL(`../../src/${path}`, import.meta.url)
let vite

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin()],
    optimizeDeps: { noDiscovery: true },
  })
})

test.after(async () => { await vite?.close() })

function node(type, value = '') {
  return {
    type, text: value, props: {}, children: [], parent: null, isConnected: true,
    scrollTop: type === 'section' ? 480 : 0,
    focus() { globalThis.document.activeElement = this },
    hasAttribute(name) { return Object.hasOwn(this.props, name) },
    getAttribute(name) { return this.props[name] ?? null },
    setAttribute(name, value) { this.props[name] = value },
    removeAttribute(name) { delete this.props[name] },
    querySelectorAll() {
      return walk(this).filter(item => ['button', 'input', 'textarea', 'a'].includes(item.type)
        && item.props.disabled !== true && item.props.tabindex !== '-1')
    },
  }
}

function detach(child) {
  if (!child?.parent) return
  child.parent.children.splice(child.parent.children.indexOf(child), 1)
  child.parent = null
}

const renderer = createRenderer({
  patchProp(element, key, _oldValue, value) { if (value == null) delete element.props[key]; else element.props[key] = value },
  insert(child, parent, anchor = null) {
    detach(child); child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child)
  },
  remove: detach,
  createElement: type => node(type),
  createText: value => node('#text', String(value)),
  createComment: value => node('#comment', String(value || '')),
  setText(target, value) { target.text = String(value) },
  setElementText(target, value) { target.text = String(value); target.children = [] },
  parentNode: target => target?.parent ?? null,
  nextSibling: target => target?.parent?.children[target.parent.children.indexOf(target) + 1] ?? null,
  querySelector: selector => globalThis.document?.querySelector?.(selector) ?? null,
  setScopeId(element, id) { element.props[id] = '' },
  cloneNode: target => ({ ...target, props: { ...target.props }, children: [...target.children], parent: null }),
  insertStaticContent(content, parent, anchor) { const target = node('#static', content); renderer.insert(target, parent, anchor); return [target, target] },
})

function walk(root, result = []) {
  if (!root) return result
  result.push(root)
  for (const child of root.children ?? []) walk(child, result)
  return result
}

function text(root) { return [root?.text ?? '', ...(root?.children ?? []).map(text)].join('') }

async function clientRender(path) {
  const contents = await readFile(source(path), 'utf8')
  const filename = path.split('/').at(-1)
  const { descriptor } = parse(contents, { filename })
  const script = compileScript(descriptor, { id: `foundation-${filename}` })
  const result = compile(descriptor.template.content, {
    mode: 'function', prefixIdentifiers: true, bindingMetadata: script.bindings,
  })
  return new Function('Vue', result.code)({
    ...VueRuntime,
    withModifiers: handler => handler,
    withKeys: handler => handler,
  })
}

async function component(path) {
  const loaded = (await vite.ssrLoadModule(`/src/${path}`)).default
  loaded.render = await clientRender(path)
  return loaded
}

test('foundation workspace gives Chinese purpose a dominant document region and named side slots', async () => {
  const Workspace = (await vite.ssrLoadModule('/src/components/foundation/FoundationWorkspace.vue')).default
  const app = createSSRApp({
    setup: () => () => h(Workspace, { title: '创作契约', purpose: '把长期承诺写成可复核的正文。', statusLabel: '工作稿' }, {
      index: () => h('p', '目录内容'),
      document: () => h('article', '正文内容'),
      status: () => h('p', '状态内容'),
      actions: () => h('button', '保存工作稿'),
    }),
  })
  const html = await renderToString(app)

  assert.match(html, /创作契约/)
  assert.match(html, /把长期承诺写成可复核的正文。/)
  assert.match(html, /foundation-workspace__index/)
  assert.match(html, /foundation-workspace__document/)
  assert.match(html, /foundation-workspace__status/)
  assert.match(html, /保存工作稿/)
  assert.doesNotMatch(html, /<main\b/)
})

test('foundation status rail stays beside the document on desktop and precedes it on mobile', async () => {
  const { chromium } = await import('@playwright/test')
  const Workspace = (await vite.ssrLoadModule('/src/components/foundation/FoundationWorkspace.vue')).default
  const componentSource = await readFile(source('components/foundation/FoundationWorkspace.vue'), 'utf8')
  const css = componentSource.match(/<style scoped>([\s\S]*?)<\/style>/)?.[1] ?? ''
  const body = await renderToString(createSSRApp({
    setup: () => () => h(Workspace, {
      title: '创作契约', purpose: '把长期承诺写成可复核的正文。', statusLabel: '工作稿',
    }, {
      index: () => h('nav', '目录内容'),
      status: () => h('div', { style: 'height:240px' }, '容量与准备度摘要'),
      document: () => h('article', { style: 'height:4200px' }, '长篇正文'),
    }),
  }))
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  try {
    await page.setContent(`<style>:root{--nc-paper:#fff;--nc-ink:#111;--nc-muted:#555;--nc-border:#ccc;--nc-vermilion:#a33;--nc-jade:#496750;--nc-canvas:#f5f2eb}${css}</style>${body}`)
    const geometry = async () => page.locator('.foundation-workspace__grid').evaluate(grid => {
      const index = grid.querySelector('.foundation-workspace__index').getBoundingClientRect()
      const status = grid.querySelector('aside.foundation-workspace__status').getBoundingClientRect()
      const document = grid.querySelector('.foundation-workspace__document').getBoundingClientRect()
      return {
        indexTop: index.top, statusTop: status.top, documentTop: document.top,
        statusPosition: getComputedStyle(grid.querySelector('aside.foundation-workspace__status')).position,
      }
    })

    const desktop = await geometry()
    assert.ok(Math.abs(desktop.statusTop - desktop.documentTop) <= 2, JSON.stringify(desktop))
    assert.equal(desktop.statusPosition, 'sticky')

    await page.setViewportSize({ width: 360, height: 800 })
    const mobile = await geometry()
    assert.ok(mobile.indexTop < mobile.statusTop, JSON.stringify(mobile))
    assert.ok(mobile.statusTop < mobile.documentTop, JSON.stringify(mobile))
  } finally {
    await browser.close()
  }
})

test('section index renders all author-facing states, emits stable keys, and honors reduced motion', async () => {
  const SectionIndex = await component('components/foundation/FoundationSectionIndex.vue')
  const headings = new Map()
  for (const key of ['premise', 'world', 'characters', 'blocker']) {
    const heading = node('h2'); heading.props.id = `foundation-${key}`; heading.props.tabindex = '-1'
    heading.scrollIntoView = options => { heading.scrollOptions = options }
    headings.set(key, heading)
  }
  const appRoot = node('div'); appRoot.props.id = 'app'
  const originalDocument = globalThis.document
  const originalMatchMedia = globalThis.matchMedia
  globalThis.document = {
    activeElement: null,
    getElementById: id => headings.get(id.replace('foundation-', '')) ?? null,
    querySelector: selector => selector === '#app' ? appRoot : null,
  }
  const emitted = []
  const root = node('root')
  try {
    const app = renderer.createApp(defineComponent({
      setup: () => () => h(SectionIndex, {
        currentKey: 'premise',
        items: [
          { key: 'premise', label: '核心命题', status: 'current', statusLabel: '当前', targetId: 'foundation-premise' },
          { key: 'world', label: '世界规则', status: 'filled', statusLabel: '已填写', targetId: 'foundation-world' },
          { key: 'characters', label: '人物关系', status: 'suggested', statusLabel: '建议补充', targetId: 'foundation-characters' },
          { key: 'blocker', label: '前置条件', status: 'blocked', statusLabel: '阻塞', targetId: 'foundation-blocker' },
        ],
        onNavigate: key => emitted.push(key),
      }),
    }))
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(root)
    for (const label of ['当前', '已填写', '建议补充', '阻塞']) assert.match(text(root), new RegExp(label))
    const button = walk(root).find(item => item.type === 'button' && text(item).includes('核心命题'))
    assert.ok(button)
    globalThis.matchMedia = () => ({ matches: false })
    button.props.onClick({ preventDefault() {} })
    assert.deepEqual(emitted, ['premise'])
    assert.deepEqual(headings.get('premise').scrollOptions, { block: 'start', behavior: 'smooth' })
    assert.equal(globalThis.document.activeElement, headings.get('premise'))
    globalThis.matchMedia = () => ({ matches: true })
    walk(root).find(item => item.type === 'button' && text(item).includes('世界规则')).props.onClick({ preventDefault() {} })
    assert.deepEqual(headings.get('world').scrollOptions, { block: 'start', behavior: 'auto' })
  } finally { globalThis.document = originalDocument; globalThis.matchMedia = originalMatchMedia }
})

test('section index can defer focus until a parent accepts navigation', async () => {
  const SectionIndex = await component('components/foundation/FoundationSectionIndex.vue')
  const heading = node('h2'); heading.props.id = 'foundation-world'; heading.scrollIntoView = () => { heading.scrolled = true }
  const originalDocument = globalThis.document
  globalThis.document = { activeElement: null, getElementById: id => id === 'foundation-world' ? heading : null }
  const root = node('root'); const emitted = []
  try {
    const app = renderer.createApp(defineComponent({
      setup: () => () => h(SectionIndex, { focusOnNavigate: false, items: [{ key: 'world', label: '世界规则', status: 'filled', statusLabel: '已填写', targetId: 'foundation-world' }], onNavigate: key => emitted.push(key) }),
    }))
    app.provide(ssrContextKey, { modules: new Set() }); app.mount(root)
    walk(root).find(item => item.type === 'button').props.onClick({ preventDefault() {} })
    assert.deepEqual(emitted, ['world'])
    assert.equal(heading.scrolled, undefined)
    assert.equal(globalThis.document.activeElement, null)
  } finally { globalThis.document = originalDocument }
})

test('status rail exposes exact summary, status, source, and action slots while omitting action in read-only mode', async () => {
  const StatusRail = (await vite.ssrLoadModule('/src/components/foundation/FoundationStatusRail.vue')).default
  const render = readOnly => renderToString(createSSRApp({
    setup: () => () => h(StatusRail, { readOnly }, {
      summary: () => h('p', '摘要内容'),
      status: () => h('p', '状态内容'),
      source: () => h('p', '来源内容'),
      action: () => h('button', '写入操作'),
    }),
  }))
  const editable = await render(false)
  for (const value of ['摘要内容', '状态内容', '来源内容', '写入操作']) assert.match(editable, new RegExp(value))
  const readOnly = await render(true)
  for (const value of ['摘要内容', '状态内容', '来源内容']) assert.match(readOnly, new RegExp(value))
  assert.doesNotMatch(readOnly, /写入操作/)
  assert.doesNotMatch(readOnly, /foundation-status-rail__action/)
})

test('document section keeps a stable heading anchor and omits edit slot only in read-only mode', async () => {
  const DocumentSection = (await vite.ssrLoadModule('/src/components/foundation/FoundationDocumentSection.vue')).default
  const render = readOnly => renderToString(createSSRApp({
    setup: () => () => h(DocumentSection, { targetId: 'foundation-premise', title: '核心命题', readOnly }, {
      read: () => h('p', '可阅读正文'),
      edit: () => h('textarea', '可编辑正文'),
    }),
  }))
  const editable = await render(false)
  assert.match(editable, /id="foundation-premise"/)
  assert.match(editable, /可阅读正文/)
  assert.match(editable, /可编辑正文/)
  const readOnly = await render(true)
  assert.match(readOnly, /可阅读正文/)
  assert.doesNotMatch(readOnly, /可编辑正文/)
})

test('confirmation dialog opens at its heading, traps focus, and restores its trigger', async () => {
  const Dialog = await component('components/foundation/FoundationConfirmationDialog.vue')
  const body = node('body')
  const appRoot = node('div'); appRoot.props.id = 'app'; appRoot.parent = body; body.children.push(appRoot)
  const trigger = node('button')
  const originalDocument = globalThis.document
  globalThis.document = {
    activeElement: trigger,
    body,
    querySelector: selector => ({ '#app': appRoot, body })[selector] ?? null,
  }
  const open = ref(true)
  try {
    const app = renderer.createApp(defineComponent({
      setup: () => () => h(Dialog, { open: open.value, title: '确认创作契约', onClose: () => { open.value = false } }, {
        snapshot: () => h('p', '确认前快照'),
        source: () => h('p', '来源快照'),
        action: () => [h('button', '返回核对'), h('button', '确认签印')],
      }),
    }))
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(appRoot)
    await nextTick(); await nextTick()
    const dialog = walk(body).find(item => item.props.role === 'dialog')
    assert.ok(dialog)
    assert.equal(walk(appRoot).includes(dialog), false)
    assert.equal(appRoot.inert, true)
    const buttons = dialog.querySelectorAll()
    assert.equal(dialog.scrollTop, 0)
    assert.equal(globalThis.document.activeElement?.props.role, 'dialog')
    const heading = walk(dialog).find(item => item.type === 'h2')
    assert.ok(heading)
    assert.equal(dialog.props['aria-labelledby'], heading.props.id)
    assert.equal(text(heading), '确认创作契约')
    dialog.props.onKeydown({ key: 'Tab', shiftKey: false, preventDefault() {} })
    assert.equal(text(globalThis.document.activeElement), '返回核对')
    globalThis.document.activeElement = buttons[0]
    dialog.props.onKeydown({ key: 'Tab', shiftKey: true, preventDefault() {} })
    assert.equal(text(globalThis.document.activeElement), '确认签印')
    globalThis.document.activeElement = buttons.at(-1)
    dialog.props.onKeydown({ key: 'Tab', shiftKey: false, preventDefault() {} })
    assert.equal(text(globalThis.document.activeElement), '返回核对')
    dialog.props.onKeydown({ key: 'Escape', preventDefault() {} })
    await nextTick()
    assert.notEqual(appRoot.inert, true)
    assert.equal(globalThis.document.activeElement, trigger)
  } finally { globalThis.document = originalDocument }
})

test('confirmation dialog cancels a pending focus mount when unmounted before next tick', async () => {
  const Dialog = await component('components/foundation/FoundationConfirmationDialog.vue')
  const body = node('body')
  const appRoot = node('div'); appRoot.props.id = 'app'; appRoot.parent = body; body.children.push(appRoot)
  const trigger = node('button')
  const originalDocument = globalThis.document
  globalThis.document = { activeElement: trigger, body, querySelector: selector => ({ '#app': appRoot, body })[selector] ?? null }
  try {
    const app = renderer.createApp(defineComponent({
      setup: () => () => h(Dialog, { open: true, title: '确认创作契约' }, {
        action: () => h('button', '确认签印'),
      }),
    }))
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(appRoot)
    app.unmount()
    await nextTick(); await nextTick()
    assert.notEqual(appRoot.inert, true)
    assert.equal(globalThis.document.activeElement, trigger)
  } finally { globalThis.document = originalDocument }
})

test('actionless confirmation dialog focuses its panel rather than leaving focus on the trigger', async () => {
  const Dialog = await component('components/foundation/FoundationConfirmationDialog.vue')
  const body = node('body')
  const appRoot = node('div'); appRoot.props.id = 'app'; appRoot.parent = body; body.children.push(appRoot)
  const trigger = node('button')
  const originalDocument = globalThis.document
  globalThis.document = { activeElement: trigger, body, querySelector: selector => ({ '#app': appRoot, body })[selector] ?? null }
  try {
    const app = renderer.createApp(defineComponent({
      setup: () => () => h(Dialog, { open: true, title: '确认创作契约' }, {
        snapshot: () => h('p', '没有可执行操作的快照'),
      }),
    }))
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(appRoot)
    await nextTick(); await nextTick()
    const dialog = walk(body).find(item => item.props.role === 'dialog')
    assert.equal(dialog.props.tabindex, '-1')
    assert.equal(globalThis.document.activeElement?.props.role, 'dialog')
    app.unmount()
  } finally { globalThis.document = originalDocument }
})

test('dialog close only notifies a parent that keeps it open, preserving focus containment', async () => {
  const Dialog = await component('components/foundation/FoundationConfirmationDialog.vue')
  const body = node('body')
  const appRoot = node('div'); appRoot.props.id = 'app'; appRoot.parent = body; body.children.push(appRoot)
  const trigger = node('button'); const closeCalls = []
  const originalDocument = globalThis.document
  globalThis.document = { activeElement: trigger, body, querySelector: selector => ({ '#app': appRoot, body })[selector] ?? null }
  try {
    const app = renderer.createApp(defineComponent({
      setup: () => () => h(Dialog, { open: true, title: '确认创作契约', onClose: () => closeCalls.push('close') }, {
        action: () => [h('button', '返回核对'), h('button', '确认签印')],
      }),
    }))
    app.provide(ssrContextKey, { modules: new Set() }); app.mount(appRoot)
    await nextTick(); await nextTick()
    const dialog = walk(body).find(item => item.props.role === 'dialog')
    dialog.props.onKeydown({ key: 'Escape', preventDefault() {} })
    await nextTick()
    assert.deepEqual(closeCalls, ['close'])
    assert.ok(walk(body).includes(dialog))
    assert.equal(appRoot.inert, true)
    assert.notEqual(globalThis.document.activeElement, trigger)
  } finally { globalThis.document = originalDocument }
})

test('actionless dialog traps both Tab directions on its focusable panel', async () => {
  const Dialog = await component('components/foundation/FoundationConfirmationDialog.vue')
  const body = node('body')
  const appRoot = node('div'); appRoot.props.id = 'app'; appRoot.parent = body; body.children.push(appRoot)
  const trigger = node('button')
  const originalDocument = globalThis.document
  globalThis.document = { activeElement: trigger, body, querySelector: selector => ({ '#app': appRoot, body })[selector] ?? null }
  try {
    const app = renderer.createApp(defineComponent({
      setup: () => () => h(Dialog, { open: true, title: '确认创作契约' }, {
        snapshot: () => h('p', '静态确认摘要'),
      }),
    }))
    app.provide(ssrContextKey, { modules: new Set() }); app.mount(appRoot)
    await nextTick(); await nextTick()
    const dialog = walk(body).find(item => item.props.role === 'dialog')
    for (const shiftKey of [false, true]) {
      let prevented = false
      dialog.props.onKeydown({ key: 'Tab', shiftKey, preventDefault() { prevented = true } })
      assert.equal(prevented, true)
      assert.equal(globalThis.document.activeElement?.props.role, 'dialog')
    }
    app.unmount()
  } finally { globalThis.document = originalDocument }
})

test('each foundation component owns its responsive safety CSS', async () => {
  const [workspace, index, status, section, dialog] = await Promise.all([
    'components/foundation/FoundationWorkspace.vue',
    'components/foundation/FoundationSectionIndex.vue',
    'components/foundation/FoundationStatusRail.vue',
    'components/foundation/FoundationDocumentSection.vue',
    'components/foundation/FoundationConfirmationDialog.vue',
  ].map(path => readFile(source(path), 'utf8')))
  assert.match(workspace, /grid-template-columns/)
  assert.match(workspace, /min-width:\s*0/)
  assert.match(workspace, /overflow-wrap:\s*anywhere/)
  assert.match(workspace, /@media\s*\(max-width:\s*760px\)/)
  assert.match(workspace, /prefers-reduced-motion:\s*reduce/)
  assert.match(workspace, /grid-template-columns:\s*minmax\(168px,\.72fr\)\s+minmax\(0,2\.5fr\)\s+minmax\(196px,\.86fr\)/)
  assert.match(workspace, /@media\s*\(max-width:760px\)/)
  assert.match(workspace, /grid-template-areas:'index'\s+'status'\s+'document';\s*grid-template-columns:minmax\(0,1fr\)/)
  assert.match(workspace, /\.foundation-workspace__status\s*\{[^}]*position:sticky;[^}]*align-self:start/)
  assert.match(workspace, /\.foundation-workspace__header-status\s*\{[^}]*align-self:end/)
  const workspaceTemplate = workspace.match(/<template>([\s\S]*)<\/template>/)?.[1] ?? ''
  assert.ok(workspaceTemplate.indexOf('foundation-workspace__index') < workspaceTemplate.indexOf('foundation-workspace__document'))
  assert.ok(workspaceTemplate.indexOf('<aside class="foundation-workspace__status"') < workspaceTemplate.indexOf('foundation-workspace__document'))
  assert.match(index, /overflow-wrap:\s*anywhere/)
  assert.match(index, /@media\s*\(max-width:\s*760px\)/)
  assert.match(index, /--foundation-status-suggested:\s*#60420f/)
  assert.match(index, /color:var\(--foundation-status-suggested\)/)
  assert.match(index, /--foundation-status-filled:\s*#496750/)
  assert.match(index, /color:var\(--foundation-status-filled\)/)
  assert.match(status, /min-width:\s*0/)
  assert.match(status, /@media\s*\(max-width:\s*760px\)/)
  assert.match(section, /min-width:\s*0/)
  assert.match(section, /overflow-wrap:\s*anywhere/)
  assert.match(section, /@media\s*\(max-width:\s*760px\)/)
  assert.match(dialog, /max-height/)
  assert.match(dialog, /overflow:\s*auto/)
  assert.match(dialog, /@media\s*\(max-width:\s*760px\)/)
  assert.match(dialog, /prefers-reduced-motion:\s*reduce/)
})

test('Seed, Contract, and Bible expose the same complete Chinese author-state contract', async () => {
  const pages = await Promise.all([
    'views/ProjectSeedsView.vue',
    'components/project/CreationContractWizard.vue',
    'views/ProjectBibleView.vue',
  ].map(path => readFile(source(path), 'utf8')))

  for (const page of pages) {
    for (const label of ['用途', '生命周期', '上游摘要', '可编辑性', '完整内容', '来源与诊断']) {
      assert.match(page, new RegExp(label), `missing shared author-state label: ${label}`)
    }
    assert.match(page, /confirmationAdapter/)
    assert.doesNotMatch(page, /重新签署|确认并进入|下一步/)
  }

  assert.match(pages[0], /title="创作种子"/)
  assert.match(pages[1], /title="本书创作契约"/)
  assert.match(pages[2], /创作圣经/)
  assert.doesNotMatch(pages.join('\n'), />\s*(?:CONTRACT DOCUMENT|IMMUTABLE REVISION|SIGNED SEED|CONFIRMED SEED|Contract basis)\b/)
})
