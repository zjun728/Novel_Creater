import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createRenderer, h, nextTick, ref, ssrContextKey } from '@vue/runtime-core'
import * as VueRuntime from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

const root = fileURLToPath(new URL('../..', import.meta.url))

async function loadDrawerModule() {
  const vite = await createServer({
    configFile: false,
    root,
    appType: 'custom',
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false, ws: false },
    plugins: [vuePlugin()],
    optimizeDeps: { noDiscovery: true },
  })
  try {
    return await vite.ssrLoadModule('/src/components/layout/MobileNavigationDrawer.vue')
  } finally {
    await vite.close()
  }
}

function focusable(name, documentRef) {
  return {
    name,
    isConnected: true,
    focus() { documentRef.activeElement = this },
  }
}

test('shell navigation mode covers both sides of every frozen breakpoint', async () => {
  const { navigationModeForWidth } = await loadDrawerModule()
  assert.deepEqual(
    [390, 760, 761, 1119, 1120, 1440].map(navigationModeForWidth),
    ['mobile', 'mobile', 'compact', 'compact', 'desktop', 'desktop'],
  )
})

test('drawer controller makes the background inert, traps focus, and restores its opener', async () => {
  const { createMobileNavigationController } = await loadDrawerModule()
  const listeners = new Map()
  const documentRef = {
    activeElement: null,
    body: { style: { overflow: 'auto' } },
    addEventListener(type, listener) { listeners.set(type, listener) },
    removeEventListener(type, listener) {
      if (listeners.get(type) === listener) listeners.delete(type)
    },
  }
  const opener = focusable('menu', documentRef)
  const close = focusable('close', documentRef)
  const firstLink = focusable('first-link', documentRef)
  const lastLink = focusable('last-link', documentRef)
  const region = { inert: false }
  const drawer = { querySelectorAll: () => [close, firstLink, lastLink] }
  let requested = 0
  documentRef.activeElement = opener

  const controller = createMobileNavigationController({
    documentRef,
    schedule: callback => Promise.resolve().then(callback),
    onRequestClose: () => { requested += 1 },
  })
  await controller.activate({ drawer, applicationRegion: region, trigger: opener })

  assert.equal(region.inert, true)
  assert.equal(documentRef.body.style.overflow, 'hidden')
  assert.equal(documentRef.activeElement, close)
  assert.equal(listeners.has('keydown'), true)

  let prevented = 0
  documentRef.activeElement = lastLink
  listeners.get('keydown')({ key: 'Tab', shiftKey: false, preventDefault: () => { prevented += 1 } })
  assert.equal(documentRef.activeElement, close)
  documentRef.activeElement = close
  listeners.get('keydown')({ key: 'Tab', shiftKey: true, preventDefault: () => { prevented += 1 } })
  assert.equal(documentRef.activeElement, lastLink)
  assert.equal(prevented, 2)

  listeners.get('keydown')({ key: 'Escape', preventDefault: () => { prevented += 1 } })
  assert.equal(requested, 1)
  controller.deactivate()
  assert.equal(region.inert, false)
  assert.equal(documentRef.body.style.overflow, 'auto')
  assert.equal(documentRef.activeElement, opener)
  assert.equal(listeners.has('keydown'), false)
})

test('drawer markup exposes a named modal, visible close and selected navigation links', async () => {
  const source = await readFile(
    new URL('../../src/components/layout/MobileNavigationDrawer.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /role="dialog"/)
  assert.match(source, /id="mobile-navigation-drawer"/)
  assert.match(source, /aria-modal="true"/)
  assert.match(source, /作品导航/)
  assert.match(source, />关闭</)
  assert.match(source, /aria-current/)
  assert.match(source, /@click="navigate"/)
  assert.match(source, /onBeforeUnmount/)
  assert.match(source, /min-(?:width|height):\s*44px/)
})

function runtimeNode(type, documentRef) {
  const value = {
    type,
    text: '',
    props: {},
    children: [],
    parent: null,
    isConnected: true,
    focus() { documentRef.activeElement = this },
    querySelectorAll() {
      const found = []
      const visit = item => {
        if (item !== value && (item.type === 'button' || (item.type === 'a' && item.props.href))) found.push(item)
        for (const child of item.children || []) visit(child)
      }
      visit(value)
      return found
    },
  }
  return value
}

const textOf = node => [node?.text, ...(node?.children || []).map(textOf)].filter(Boolean).join(' ')
const find = (node, predicate) => node && (predicate(node) ? node : (node.children || []).map(child => find(child, predicate)).find(Boolean))
async function flush() { for (let index = 0; index < 8; index += 1) await Promise.resolve(); await nextTick() }
async function invoke(handler, event) {
  for (const item of Array.isArray(handler) ? handler : [handler]) await item?.(event)
}

test('mounted drawer closes by every path and fences stale open continuations', async () => {
  const originalDocument = global.document
  const listeners = new Map()
  const documentRef = {
    activeElement: null,
    body: { style: { overflow: 'auto' } },
    addEventListener(type, listener) { listeners.set(type, listener) },
    removeEventListener(type, listener) { if (listeners.get(type) === listener) listeners.delete(type) },
  }
  global.document = documentRef
  let app
  try {
    const module = await loadDrawerModule()
    const source = await readFile(new URL('../../src/components/layout/MobileNavigationDrawer.vue', import.meta.url), 'utf8')
    const { descriptor } = parse(source)
    const Drawer = module.default
    Drawer.render = new Function('Vue', compile(descriptor.template.content, {
      mode: 'function',
      prefixIdentifiers: true,
      bindingMetadata: compileScript(descriptor, { id: 'mobile-drawer' }).bindings,
    }).code)(VueRuntime)
    const detach = child => { if (child?.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1) }
    const renderer = createRenderer({
      patchProp(node, key, _old, value) { if (value == null) delete node.props[key]; else node.props[key] = value },
      insert(child, parent, anchor = null) { detach(child); child.parent = parent; const index = anchor ? parent.children.indexOf(anchor) : -1; if (index < 0) parent.children.push(child); else parent.children.splice(index, 0, child) },
      remove: detach,
      createElement: type => runtimeNode(type, documentRef),
      createText: text => ({ ...runtimeNode('#text', documentRef), text: String(text) }),
      createComment: text => ({ ...runtimeNode('#comment', documentRef), text: String(text || '') }),
      setText(node, text) { node.text = String(text) },
      setElementText(node, text) { node.text = String(text); node.children = [] },
      parentNode: node => node?.parent || null,
      nextSibling: node => node?.parent?.children[node.parent.children.indexOf(node) + 1] || null,
      querySelector: () => null,
      setScopeId(node, id) { node.props[id] = '' },
      cloneNode: node => ({ ...node, props: { ...node.props }, children: [...node.children], parent: null }),
      insertStaticContent(content, parent, anchor) { const node = { ...runtimeNode('#static', documentRef), text: content }; renderer.insert(node, parent, anchor); return [node, node] },
    })
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/projects', component: { render: () => null } },
      { path: '/settings/providers', component: { render: () => null } },
    ] })
    await router.push('/projects'); await router.isReady()
    const open = ref(false)
    const region = { inert: false }
    const trigger = runtimeNode('button', documentRef)
    const shell = {
      globalNavigation: [
        { key: 'projects', path: '/projects', label: '项目库', mark: '库', selected: true },
        { key: 'settings', path: '/settings/providers', label: '设置', mark: '设', selected: false },
      ],
      assetNavigation: [], projectContext: null,
    }
    const Root = { setup: () => () => h(Drawer, {
      open: open.value, shell, applicationRegion: region, trigger,
      onClose: () => { open.value = false },
      onNavigate: () => { open.value = false },
    }) }
    const root = runtimeNode('root', documentRef)
    app = renderer.createApp(Root)
    app.use(router)
    app.provide(ssrContextKey, { modules: new Set() })
    app.mount(root)

    open.value = true; await flush()
    assert.equal(region.inert, true)
    const close = find(root, node => node.type === 'button' && /关闭/.test(textOf(node)))
    assert.ok(close, 'visible close button was not rendered')
    await invoke(close.props.onClick)
    await flush()
    assert.equal(region.inert, false)
    assert.equal(documentRef.activeElement, trigger)

    open.value = true; await flush()
    const backdrop = find(root, node => String(node.props.class || '').includes('mobile-navigation-drawer__backdrop'))
    await invoke(backdrop.props.onMousedown, { target: backdrop, currentTarget: backdrop })
    await flush()
    assert.equal(region.inert, false)

    open.value = true; await flush()
    const settings = find(root, node => node.type === 'a' && node.props.href === '/settings/providers')
    assert.ok(settings)
    await invoke(settings.props.onClick, { preventDefault() {}, button: 0 })
    await flush()
    assert.equal(region.inert, false)

    open.value = true
    await Promise.resolve()
    open.value = false
    await flush()
    assert.equal(region.inert, false, 'a stale open continuation made the application inert')
    assert.equal(documentRef.body.style.overflow, 'auto')

    open.value = true
    await Promise.resolve()
    app.unmount()
    app = null
    await flush()
    assert.equal(region.inert, false, 'unmount did not cancel pending activation')
    assert.equal(documentRef.body.style.overflow, 'auto')
  } finally {
    app?.unmount()
    global.document = originalDocument
  }
})
