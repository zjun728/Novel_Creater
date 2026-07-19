import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createPinia } from 'pinia'
import * as VueRuntime from '@vue/runtime-core'
import {
  createRenderer, defineComponent, h, nextTick, ref, ssrContextKey,
} from '@vue/runtime-core'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveStubId = '\0corpus-library-naive-ui-stub'

function slotChildren(slots) {
  return Object.values(slots).flatMap(
    slot => typeof slot === 'function' ? slot() : [],
  )
}

const naiveStubPlugin = {
  name: 'corpus-library-behavior-stubs',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveStubId
    return undefined
  },
  load(id) {
    if (id !== naiveStubId) return undefined
    return `
      import { defineComponent, h } from 'vue'
      const children = slots => Object.values(slots)
        .flatMap(slot => typeof slot === 'function' ? slot() : [])
      const stub = (name, tag = 'div') => defineComponent({
        name,
        inheritAttrs: false,
        setup(_, { attrs, slots }) {
          return () => h(tag, {
            ...attrs,
            'data-component': name,
          }, children(slots))
        },
      })
      export const NAlert = stub('NAlert', 'aside')
      export const NButton = stub('NButton', 'button')
      export const NCard = stub('NCard', 'article')
      export const NCheckbox = stub('NCheckbox', 'input')
      export const NDynamicTags = stub('NDynamicTags')
      export const NForm = stub('NForm', 'form')
      export const NFormItem = stub('NFormItem', 'label')
      export const NInput = stub('NInput', 'input')
      export const NSpace = stub('NSpace')
      export const NModal = defineComponent({
        name: 'NModal',
        inheritAttrs: false,
        props: { show: Boolean },
        emits: ['update:show'],
        setup(props, { attrs, slots }) {
          return () => props.show
            ? h('section', {
                ...attrs,
                'data-component': 'NModal',
              }, children(slots))
            : null
        },
      })
      export const NSelect = defineComponent({
        name: 'NSelect',
        inheritAttrs: false,
        props: {
          value: { default: null },
          options: { type: Array, default: () => [] },
        },
        emits: ['update:value'],
        setup(props, { attrs, emit }) {
          return () => h('select', {
            ...attrs,
            value: props.value,
            'data-component': 'NSelect',
            onInput: event => emit('update:value', event.target.value),
          }, props.options.map(option => h('option', {
            value: option.value,
            disabled: option.disabled,
          }, option.label)))
        },
      })
    `
  },
}

function hostNode(type, text = '') {
  return { type, text, props: {}, children: [], parent: null }
}

function detach(node) {
  if (!node?.parent) return
  const index = node.parent.children.indexOf(node)
  if (index >= 0) node.parent.children.splice(index, 1)
  node.parent = null
}

const renderer = createRenderer({
  patchProp(element, key, _previous, next) {
    if (next == null) delete element.props[key]
    else element.props[key] = next
  },
  insert(child, parent, anchor = null) {
    detach(child)
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index >= 0) parent.children.splice(index, 0, child)
    else parent.children.push(child)
  },
  remove: detach,
  createElement: type => hostNode(type),
  createText: text => hostNode('#text', String(text)),
  createComment: text => hostNode('#comment', String(text || '')),
  setText(node, text) { node.text = String(text) },
  setElementText(node, text) {
    node.text = String(text)
    node.children = []
  },
  parentNode: node => node?.parent || null,
  nextSibling(node) {
    if (!node?.parent) return null
    const index = node.parent.children.indexOf(node)
    return node.parent.children[index + 1] || null
  },
  querySelector: () => null,
  setScopeId(element, id) { element.props[id] = '' },
  cloneNode(node) {
    return {
      ...node,
      props: { ...node.props },
      children: [...node.children],
      parent: null,
    }
  },
  insertStaticContent(content, parent, anchor) {
    const node = hostNode('#static', String(content))
    renderer.insert(node, parent, anchor)
    return [node, node]
  },
})

function walk(node, values = []) {
  if (!node) return values
  values.push(node)
  for (const child of node.children || []) walk(child, values)
  return values
}

function textContent(node) {
  return [
    node?.text || '',
    ...(node?.children || []).map(textContent),
  ].join('')
}

async function flush() {
  for (let index = 0; index < 5; index += 1) await Promise.resolve()
  await nextTick()
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

async function trigger(node, name, value) {
  const handlers = Array.isArray(node.props[name])
    ? node.props[name]
    : [node.props[name]]
  assert.equal(typeof handlers[0], 'function', `missing ${name}`)
  for (const handler of handlers) await handler(value)
  await flush()
}

async function compileClientRender(path) {
  const source = await readFile(new URL(`../../${path}`, import.meta.url), 'utf8')
  const filename = path.split('/').at(-1)
  const { descriptor } = parse(source, { filename })
  const script = compileScript(descriptor, { id: `corpus-${filename}` })
  const compiled = compile(descriptor.template.content, {
    mode: 'function',
    prefixIdentifiers: true,
    bindingMetadata: script.bindings,
  })
  return new Function('Vue', compiled.code)({
    ...VueRuntime,
    withModifiers: handler => handler,
  })
}

let vite
let CorpusImportDialog
let CorpusLifecycleMenu

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('../../src', import.meta.url)),
      },
    },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [naiveStubPlugin, vuePlugin()],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  CorpusImportDialog = (
    await vite.ssrLoadModule('/src/components/assets/CorpusImportDialog.vue')
  ).default
  CorpusImportDialog.render = await compileClientRender(
    'src/components/assets/CorpusImportDialog.vue',
  )
  CorpusLifecycleMenu = (
    await vite.ssrLoadModule('/src/components/assets/CorpusLifecycleMenu.vue')
  ).default
  CorpusLifecycleMenu.render = await compileClientRender(
    'src/components/assets/CorpusLifecycleMenu.vue',
  )
})

test.after(async () => {
  await vite?.close()
})

test('permanent delete confirmation stays pending until its real action settles', async () => {
  let calls = 0
  const pending = deferred()
  const Root = defineComponent({
    setup() {
      return () => h(CorpusLifecycleMenu, {
        source: {
          id: 'source-1',
          state: 'archived',
          deleteEligible: true,
          deleteReason: null,
        },
        deleteAction: async () => {
          calls += 1
          return pending.promise
        },
      })
    },
  })
  const root = hostNode('root')
  const app = renderer.createApp(Root)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)

  try {
    const open = walk(root).find(node => (
      node.type === 'button' && textContent(node).trim() === '永久删除'
    ))
    await trigger(open, 'onClick')
    let confirm = walk(root).find(node => (
      node.type === 'button' && textContent(node).trim() === '确认永久删除'
    ))
    const confirming = trigger(confirm, 'onClick')
    await flush()

    assert.equal(calls, 1)
    const cancel = walk(root).find(node => (
      node.type === 'button' && textContent(node).trim() === '保留'
    ))
    confirm = walk(root).find(node => (
      node.type === 'button' && textContent(node).trim() === '确认永久删除'
    ))
    const restore = walk(root).find(node => (
      node.type === 'button' && textContent(node).trim() === '恢复来源'
    ))
    assert.equal(cancel.props.disabled, true)
    assert.equal(confirm.props.disabled, true)
    assert.equal(confirm.props.loading, true)
    assert.equal(restore.props.disabled, true)
    await trigger(confirm, 'onClick')
    assert.equal(calls, 1, 'pending confirmation must not emit a duplicate delete')

    pending.resolve(true)
    await confirming
    await flush()
    assert.equal(
      walk(root).some(node => textContent(node).trim() === '确认永久删除'),
      false,
      'successful action closes the confirmation only after it settles',
    )
  } finally {
    pending.resolve(false)
    app.unmount()
  }
})

test('failed permanent delete unlocks the same dialog for one explicit retry', async () => {
  const attempts = [deferred(), deferred()]
  let calls = 0
  const Root = defineComponent({
    setup() {
      return () => h(CorpusLifecycleMenu, {
        source: {
          id: 'source-1',
          state: 'archived',
          deleteEligible: true,
          deleteReason: null,
        },
        deleteAction: async () => {
          const attempt = attempts[calls]
          calls += 1
          return attempt.promise
        },
      })
    },
  })
  const root = hostNode('root')
  const app = renderer.createApp(Root)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)

  try {
    await trigger(
      walk(root).find(node => (
        node.type === 'button' && textContent(node).trim() === '永久删除'
      )),
      'onClick',
    )
    let confirm = walk(root).find(node => (
      node.type === 'button' && textContent(node).trim() === '确认永久删除'
    ))
    const first = trigger(confirm, 'onClick')
    await flush()
    attempts[0].resolve(false)
    await first
    await flush()

    confirm = walk(root).find(node => (
      node.type === 'button' && textContent(node).trim() === '确认永久删除'
    ))
    assert.ok(confirm, 'failed action keeps the dialog visible')
    assert.notEqual(confirm.props.disabled, true)
    assert.notEqual(confirm.props.loading, true)
    assert.equal(calls, 1)

    const second = trigger(confirm, 'onClick')
    await flush()
    assert.equal(calls, 2)
    attempts[1].resolve(true)
    await second
    await flush()
    assert.equal(
      walk(root).some(node => textContent(node).trim() === '确认永久删除'),
      false,
    )
  } finally {
    for (const attempt of attempts) attempt.resolve(false)
    app.unmount()
  }
})

test('eligible discovery item is selectable and submits through the real Pinia store', async () => {
  const originalFetch = globalThis.fetch
  const requests = []
  globalThis.fetch = async (url, options) => {
    const parsed = new URL(String(url))
    requests.push({
      method: options.method,
      path: parsed.pathname,
      body: options.body && JSON.parse(options.body),
    })
    if (parsed.pathname.endsWith('/corpus/discovery')) {
      return new Response(JSON.stringify({
        items: [{
          relativePath: 'safe/book.txt',
          byteSize: 321,
          preflightStatus: 'eligible',
        }],
        nextCursor: null,
        reasonCounts: {},
        scanStrategy: 'recursive',
      }), { status: 200 })
    }
    if (parsed.pathname.endsWith('/corpus/imports')) {
      return new Response(JSON.stringify({
        importId: 'import-1',
        status: 'succeeded',
        sourceId: 'source-1',
        sourceRevision: 1,
        sourceRevisionId: 'revision-1',
        sourceLabel: 'safe/book.txt',
        shortHash: 'abc123def456',
        errorCode: null,
      }), { status: 200 })
    }
    throw new Error(`unexpected request ${options.method} ${url}`)
  }

  const show = ref(false)
  const imported = []
  const Root = defineComponent({
    setup() {
      return () => h(CorpusImportDialog, {
        show: show.value,
        'onUpdate:show': value => { show.value = value },
        onImported: value => imported.push(value),
      })
    },
  })
  const root = hostNode('root')
  const app = renderer.createApp(Root)
  app.use(createPinia())
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)

  try {
    show.value = true
    await flush()
    const nodes = walk(root)
    const option = nodes.find(node => (
      node.type === 'option' && node.props.value === 'safe/book.txt'
    ))
    assert.ok(option, 'eligible discovery option must render')
    assert.notEqual(option.props.disabled, true)
    const select = nodes.find(node => node.type === 'select')
    await trigger(select, 'onInput', { target: { value: 'safe/book.txt' } })
    const submit = walk(root).find(node => (
      node.type === 'button' && textContent(node).trim() === '确认导入'
    ))
    await trigger(submit, 'onClick')

    assert.equal(imported.length, 1)
    assert.deepEqual(requests.map(item => item.method), ['GET', 'POST'])
    assert.equal(requests[1].body.relativePath, 'safe/book.txt')
    assert.equal('rawBytes' in requests[1].body, false)
  } finally {
    app.unmount()
    globalThis.fetch = originalFetch
  }
})
