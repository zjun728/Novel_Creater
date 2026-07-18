import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { nextTick, ref } from 'vue'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
let vite
let dialogModule

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin()],
    optimizeDeps: { noDiscovery: true },
  })
  dialogModule = await vite.ssrLoadModule('/src/components/projects/ProjectNameDialog.vue')
})

test.after(async () => {
  await vite?.close()
})

function controller({ initialTitle = '', pending = ref(false) } = {}) {
  const emitted = []
  const focused = []
  return {
    pending,
    emitted,
    focused,
    controller: dialogModule.createProjectNameDialogController({
      initialTitle,
      pending,
      emit: (event, payload) => emitted.push([event, payload]),
      focusInput: () => focused.push('input'),
    }),
  }
}

test('dialog renders exactly one project-name input with inline error region', async () => {
  const context = {}
  const rootHtml = await renderToString(createSSRApp(dialogModule.default, {
    title: '新建项目',
    initialTitle: '',
    pending: false,
  }), context)
  const html = `${rootHtml}${context.teleports?.body ?? ''}`

  assert.equal((html.match(/<input\b/g) ?? []).length, 1)
  assert.match(html, /项目名称/)
  assert.match(html, /aria-describedby="project-name-error"/)
  assert.match(html, /id="project-name-error"[^>]*aria-live="polite"/)
  assert.match(rootHtml, /teleport start/)
})

test('submission trims surrounding whitespace and emits only submit payload', () => {
  const harness = controller({ initialTitle: '  典镇山河  ' })

  assert.equal(harness.controller.submit(), true)
  assert.deepEqual(harness.emitted, [['submit', { title: '典镇山河' }]])
})

test('empty submission stays inline and focuses the single input', async () => {
  const harness = controller({ initialTitle: '   ' })

  assert.equal(harness.controller.submit(), false)
  await nextTick()
  assert.equal(harness.controller.error.value, '请输入项目名称')
  assert.deepEqual(harness.emitted, [])
  assert.deepEqual(harness.focused, ['input'])
})

test('Enter submits through the same normalization path', () => {
  const harness = controller({ initialTitle: '  新名字 ' })
  let prevented = 0

  harness.controller.handleKeydown({
    key: 'Enter',
    preventDefault: () => { prevented += 1 },
  })

  assert.equal(prevented, 1)
  assert.deepEqual(harness.emitted, [['submit', { title: '新名字' }]])
})

test('IME composition Enter never prevents or submits, including keyCode 229', () => {
  for (const event of [
    { key: 'Enter', isComposing: true },
    { key: 'Enter', keyCode: 229 },
  ]) {
    const harness = controller({ initialTitle: '输入中的名字' })
    let prevented = 0

    assert.equal(harness.controller.handleKeydown({
      ...event,
      preventDefault: () => { prevented += 1 },
    }), false)
    assert.equal(prevented, 0)
    assert.deepEqual(harness.emitted, [])
  }
})

test('pending and immediate repeated submissions emit once and recover after failure', async () => {
  const harness = controller({ initialTitle: '新名字' })

  assert.equal(harness.controller.submit(), true)
  assert.equal(harness.controller.submit(), false)
  harness.pending.value = true
  await nextTick()
  assert.equal(harness.controller.disabled.value, true)
  harness.pending.value = false
  await nextTick()
  assert.equal(harness.controller.disabled.value, false)

  assert.equal(harness.controller.submit(), true)
  assert.equal(harness.emitted.length, 2)
})

function fakeElement(name, documentRef) {
  const attributes = new Map()
  return {
    name,
    inert: false,
    isConnected: true,
    focusCalls: 0,
    focus() {
      this.focusCalls += 1
      documentRef.activeElement = this
    },
    hasAttribute(attribute) {
      return attributes.has(attribute)
    },
    getAttribute(attribute) {
      return attributes.get(attribute) ?? null
    },
    setAttribute(attribute, value) {
      attributes.set(attribute, String(value))
    },
    removeAttribute(attribute) {
      attributes.delete(attribute)
    },
  }
}

test('modal focus manager isolates #app, loops Tab, and restores prior focus and inert state', () => {
  const documentRef = { activeElement: null }
  const trigger = fakeElement('trigger', documentRef)
  const app = fakeElement('app', documentRef)
  const input = fakeElement('input', documentRef)
  const cancel = fakeElement('cancel', documentRef)
  const submit = fakeElement('submit', documentRef)
  const dialog = {
    querySelectorAll() {
      return [input, cancel, submit]
    },
  }
  documentRef.activeElement = trigger
  documentRef.querySelector = selector => selector === '#app' ? app : null
  const manager = dialogModule.createProjectNameDialogFocusManager({
    getDocument: () => documentRef,
    getDialog: () => dialog,
    getInput: () => input,
  })

  manager.mount()
  assert.equal(app.inert, true)
  assert.equal(app.hasAttribute('inert'), true)
  assert.equal(documentRef.activeElement, input)

  documentRef.activeElement = submit
  let prevented = 0
  assert.equal(manager.trapTab({
    key: 'Tab',
    shiftKey: false,
    preventDefault: () => { prevented += 1 },
  }), true)
  assert.equal(documentRef.activeElement, input)

  documentRef.activeElement = input
  assert.equal(manager.trapTab({
    key: 'Tab',
    shiftKey: true,
    preventDefault: () => { prevented += 1 },
  }), true)
  assert.equal(documentRef.activeElement, submit)
  assert.equal(prevented, 2)

  manager.unmount()
  assert.equal(app.inert, false)
  assert.equal(app.hasAttribute('inert'), false)
  assert.equal(documentRef.activeElement, trigger)
})

test('modal focus manager preserves a pre-existing inert attribute and value', () => {
  const documentRef = { activeElement: null }
  const trigger = fakeElement('trigger', documentRef)
  const app = fakeElement('app', documentRef)
  const input = fakeElement('input', documentRef)
  app.inert = true
  app.setAttribute('inert', 'existing')
  documentRef.activeElement = trigger
  documentRef.querySelector = () => app
  const manager = dialogModule.createProjectNameDialogFocusManager({
    getDocument: () => documentRef,
    getDialog: () => ({ querySelectorAll: () => [input] }),
    getInput: () => input,
  })

  manager.mount()
  manager.unmount()

  assert.equal(app.inert, true)
  assert.equal(app.getAttribute('inert'), 'existing')
})
