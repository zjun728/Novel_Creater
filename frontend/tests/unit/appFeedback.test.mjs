import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { createPinia, setActivePinia } from 'pinia'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import { createMemoryHistory, createRouter } from 'vue-router'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

import { createAppMessage } from '../../src/composables/useAppMessage.js'
import { createDangerousConfirmation } from '../../src/composables/useDangerousConfirmation.js'
import { createOperationStore } from '../../src/stores/operationStore.js'

function findVNode(node, predicate) {
  if (!node || typeof node !== 'object') return null
  if (predicate(node)) return node
  const children = Array.isArray(node.children) ? node.children : []
  for (const child of children) {
    const result = findVNode(child, predicate)
    if (result) return result
  }
  return null
}

test('ordinary feedback delegates every type to the message port', () => {
  const calls = []
  const port = {}
  for (const type of ['success', 'error', 'warning', 'info']) {
    port[type] = (content, options) => calls.push({ type, content, options })
  }
  const message = createAppMessage(port)

  message.success('完成', { title: 'ignored legacy title' })
  message.error('失败')
  message.warning('注意')
  message.info('提示')

  assert.deepEqual(calls.map(call => call.type), ['success', 'error', 'warning', 'info'])
  assert.deepEqual(calls.map(call => call.content), ['完成', '失败', '注意', '提示'])
})

test('archive toast renders Undo and invokes its action once', async () => {
  const calls = []
  let messageCall
  const message = createAppMessage({
    success(content, options) {
      messageCall = { content, options }
    },
  })

  message.success('项目已归档', {
    actionLabel: '撤销',
    onAction: async () => { calls.push('restore') },
    duration: 6000,
  })
  const content = typeof messageCall.content === 'function'
    ? messageCall.content()
    : messageCall.content
  const action = findVNode(content, node => node.type === 'button')

  assert.equal(action.children, '撤销')
  assert.equal(messageCall.options.duration, 6000)
  await Promise.all([action.props.onClick(), action.props.onClick()])
  assert.deepEqual(calls, ['restore'])
})

test('danger confirmation defaults to one red positive action and neutral cancel', async () => {
  let dialogOptions
  const dialogHandle = {}
  let release
  const actionGate = new Promise(resolve => { release = resolve })
  let actionCalls = 0
  const confirmation = createDangerousConfirmation({
    warning(options) {
      dialogOptions = options
      return dialogHandle
    },
  })
  const result = confirmation.confirm({
    content: '删除后无法恢复',
    onConfirm: async () => {
      actionCalls += 1
      await actionGate
    },
  })

  assert.equal(dialogOptions.positiveText, '永久删除')
  assert.equal(dialogOptions.negativeText, '取消')
  assert.equal(dialogOptions.positiveButtonProps.type, 'error')
  assert.notEqual(dialogOptions.negativeButtonProps.type, 'error')

  const first = dialogOptions.onPositiveClick()
  const second = dialogOptions.onPositiveClick()
  await Promise.resolve()
  assert.equal(actionCalls, 1)
  assert.equal(dialogHandle.loading, true)
  assert.equal(dialogHandle.closeOnEsc, false)
  assert.equal(dialogHandle.positiveButtonProps.loading, true)
  assert.equal(dialogHandle.positiveButtonProps.disabled, true)
  assert.equal(dialogHandle.negativeButtonProps.disabled, true)

  let resultSettled = false
  void result.then(() => { resultSettled = true })
  assert.equal(dialogOptions.onNegativeClick(), false)
  assert.equal(dialogOptions.onEsc(), false)
  assert.equal(dialogOptions.onClose(), false)
  await Promise.resolve()
  assert.equal(resultSettled, false)
  assert.equal(actionCalls, 1)

  release()
  await Promise.all([first, second])
  assert.equal(await result, true)
  assert.equal(actionCalls, 1)
})

test('cancel, Escape, and close settle false without invoking the destructive callback', async () => {
  for (const cancel of ['onNegativeClick', 'onEsc', 'onClose']) {
    let options
    let actionCalls = 0
    const confirmation = createDangerousConfirmation({
      warning(value) {
        options = value
        return {}
      },
    })
    const result = confirmation.confirm({
      onConfirm: async () => { actionCalls += 1 },
    })

    options[cancel]()
    assert.equal(await result, false)
    assert.equal(actionCalls, 0)
  }
})

test('a rejected dangerous action settles false and remains single-use', async () => {
  let dialogOptions
  let actionCalls = 0
  const confirmation = createDangerousConfirmation({
    warning(options) {
      dialogOptions = options
      return {}
    },
  })
  const result = confirmation.confirm({
    onConfirm: async () => {
      actionCalls += 1
      throw new Error('delete failed')
    },
  })

  const first = await dialogOptions.onPositiveClick().then(
    value => value,
    error => error,
  )
  const second = await dialogOptions.onPositiveClick().then(
    value => value,
    error => error,
  )
  const settled = await Promise.race([
    result,
    new Promise(resolve => setTimeout(() => resolve('timeout'), 100)),
  ])

  assert.equal(first, undefined)
  assert.equal(second, undefined)
  assert.equal(settled, false)
  assert.equal(actionCalls, 1)
})

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
let vite
let overlayComponent
let overlayModule
let boundaryComponent

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
  overlayModule = await vite.ssrLoadModule(
    '/src/components/common/AppOperationOverlay.vue',
  )
  overlayComponent = overlayModule.default
  boundaryComponent = (await vite.ssrLoadModule(
    '/src/components/common/AppInteractionBoundary.vue',
  )).default
})

test.after(async () => {
  await vite?.close()
})

async function renderOverlay(operation) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const store = createOperationStore('operation')()
  if (operation) store.start(operation)
  const app = createSSRApp(overlayComponent)
  app.use(pinia)
  return renderToString(app)
}

test('operation overlay blocks app navigation only for blocking operations', async () => {
  const inactive = await renderOverlay()
  const nonBlocking = await renderOverlay({ label: '正在准备下载', blocking: false })
  const blocking = await renderOverlay({ label: '正在导入项目', blocking: true })

  assert.doesNotMatch(inactive, /app-operation-overlay/)
  assert.match(nonBlocking, /data-blocks-navigation="false"/)
  assert.doesNotMatch(nonBlocking, /aria-modal="true"/)
  assert.match(blocking, /data-blocks-navigation="true"/)
  assert.match(blocking, /aria-modal="true"/)
  assert.match(blocking, /aria-labelledby="app-operation-overlay-title"/)
  assert.match(blocking, /tabindex="-1"/)
})

test('operation tokens prefer the latest blocker and finish only their own work', () => {
  setActivePinia(createPinia())
  const store = createOperationStore('operation-overlap')()
  const oldNotice = store.start({ label: '旧提示', blocking: false })
  const oldBlocker = store.start({ label: '旧阻断', blocking: true })
  const latestNotice = store.start({ label: '新提示', blocking: false })
  const latestBlocker = store.start({ label: '新阻断', blocking: true })

  assert.equal(store.blocking, true)
  assert.equal(store.current.label, '新阻断')
  assert.equal(store.finish(oldNotice), true)
  assert.equal(store.current.label, '新阻断')
  assert.equal(store.finish(oldBlocker), true)
  assert.equal(store.current.label, '新阻断')
  assert.equal(store.finish('unknown-token'), false)
  assert.equal(store.finish(latestBlocker), true)
  assert.equal(store.blocking, false)
  assert.equal(store.current.label, '新提示')
  assert.equal(store.finish(latestNotice), true)
  assert.equal(store.current, null)
})

test('memory-router guard blocks push and back navigation only while an operation blocks', async () => {
  const { installOperationNavigationGuard } = await import(
    '../../src/router/operationNavigationGuard.js'
  )
  setActivePinia(createPinia())
  const store = createOperationStore('operation-navigation')()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/first', component: { template: '<div />' } },
      { path: '/second', component: { template: '<div />' } },
      { path: '/third', component: { template: '<div />' } },
    ],
  })
  installOperationNavigationGuard(router, () => store)
  await router.push('/first')
  await router.push('/second')

  const blocker = store.start({ label: '正在导入', blocking: true })
  await router.push('/third')
  assert.equal(router.currentRoute.value.path, '/second')

  router.back()
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(router.currentRoute.value.path, '/second')

  store.finish(blocker)
  await router.push('/third')
  assert.equal(router.currentRoute.value.path, '/third')
})

test('interaction boundary makes only the shell inert while overlay remains a sibling', async () => {
  const app = createSSRApp({
    components: { boundaryComponent },
    template: `
      <boundary-component :blocking="true">
        <main data-shell-content>正文</main>
        <template #overlay><aside data-overlay>处理中</aside></template>
      </boundary-component>
    `,
  })
  const html = await renderToString(app)

  assert.match(html, /class="app-interaction-boundary"[^>]*inert/)
  assert.match(html, /<\/div>[\s\S]*<aside data-overlay/)
})

test('blocking overlay captures focus, focuses itself, and restores the prior element', () => {
  const documentRef = { activeElement: null }
  const trigger = {
    isConnected: true,
    focusCalls: 0,
    focus() {
      this.focusCalls += 1
      documentRef.activeElement = this
    },
  }
  const overlay = {
    focusCalls: 0,
    focus() {
      this.focusCalls += 1
      documentRef.activeElement = this
    },
  }
  documentRef.activeElement = trigger
  const manager = overlayModule.createOperationOverlayFocusManager({
    getDocument: () => documentRef,
    getOverlay: () => overlay,
    schedule: callback => callback(),
  })

  manager.setBlocking(true)
  assert.equal(documentRef.activeElement, overlay)
  manager.setBlocking(true)
  assert.equal(overlay.focusCalls, 1)
  manager.setBlocking(false)
  assert.equal(documentRef.activeElement, trigger)
  assert.equal(trigger.focusCalls, 1)
})

test('reduced-motion users do not receive infinite operation or skeleton animation', async () => {
  const [globalCss, libraryCss] = await Promise.all([
    readFile(new URL('../../src/style.css', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/projects/projectLibrary.css', import.meta.url), 'utf8'),
  ])

  assert.match(globalCss, /prefers-reduced-motion:\s*reduce[\s\S]*app-operation-overlay__progress[\s\S]*animation:\s*none/)
  assert.match(libraryCss, /prefers-reduced-motion:\s*reduce[\s\S]*(project-library-skeleton|archived-projects-skeleton)[\s\S]*animation:\s*none/)
})
