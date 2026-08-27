import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

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
