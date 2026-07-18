import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createPinia, setActivePinia } from 'pinia'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
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
  let release
  const actionGate = new Promise(resolve => { release = resolve })
  let actionCalls = 0
  const confirmation = createDangerousConfirmation({
    warning(options) {
      dialogOptions = options
      return {}
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
  overlayComponent = (await vite.ssrLoadModule(
    '/src/components/common/AppOperationOverlay.vue',
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
})
