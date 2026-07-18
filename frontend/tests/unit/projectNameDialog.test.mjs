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
  const html = await renderToString(createSSRApp(dialogModule.default, {
    title: '新建项目',
    initialTitle: '',
    pending: false,
  }))

  assert.equal((html.match(/<input\b/g) ?? []).length, 1)
  assert.match(html, /项目名称/)
  assert.match(html, /aria-describedby="project-name-error"/)
  assert.match(html, /id="project-name-error"[^>]*aria-live="polite"/)
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
