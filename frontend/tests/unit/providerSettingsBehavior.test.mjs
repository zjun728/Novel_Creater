import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createPinia } from 'pinia'
import * as VueRuntime from '@vue/runtime-core'
import {
  createRenderer, defineComponent, h, nextTick, ssrContextKey,
} from '@vue/runtime-core'
import {
  createMemoryHistory, createRouter, RouterView,
} from 'vue-router'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'


const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveUiStubId = '\0provider-settings-naive-ui-stub'
const bindingStubId = '\0provider-settings-binding-stub'
const SECRET = 'component-local-provider-secret'
const PRIVATE_URL = 'https://component-private.example/v1'

const harnessStubPlugin = {
  name: 'provider-settings-behavior-stubs',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveUiStubId
    if (id.endsWith('/TaskModelBinding.vue') || id === './TaskModelBinding.vue') {
      return bindingStubId
    }
    return undefined
  },
  load(id) {
    if (id === bindingStubId) {
      return `
        import { defineComponent, h } from 'vue'
        export default defineComponent({
          name: 'TaskModelBindingStub',
          setup() {
            return () => h('section', { 'data-component': 'TaskModelBinding' })
          },
        })
      `
    }
    if (id !== naiveUiStubId) return undefined
    return `
      import { defineComponent, h } from 'vue'

      const slotChildren = slots => Object.values(slots)
        .flatMap(slot => typeof slot === 'function' ? slot() : [])

      const stub = (name, tag = 'div') => defineComponent({
        name,
        inheritAttrs: false,
        setup(_, { attrs, slots }) {
          return () => h(tag, {
            ...attrs,
            'data-component': name,
          }, slotChildren(slots))
        },
      })

      const inputStub = name => defineComponent({
        name,
        inheritAttrs: false,
        props: { value: { default: '' } },
        emits: ['update:value'],
        setup(props, { attrs, emit }) {
          return () => h('input', {
            ...attrs,
            value: props.value,
            'data-component': name,
            onInput: event => emit(
              'update:value',
              event && event.target ? event.target.value : event,
            ),
          })
        },
      })

      export const NAlert = stub('NAlert', 'aside')
      export const NButton = stub('NButton', 'button')
      export const NCard = stub('NCard', 'article')
      export const NEmpty = stub('NEmpty', 'div')
      export const NForm = stub('NForm', 'form')
      export const NFormItem = stub('NFormItem', 'label')
      export const NInput = inputStub('NInput')
      export const NInputNumber = inputStub('NInputNumber')
      export const NSelect = inputStub('NSelect')
      export const NSpace = stub('NSpace', 'div')
      export const NSwitch = inputStub('NSwitch')
      export const NTag = stub('NTag', 'span')

      export const NModal = defineComponent({
        name: 'NModal',
        inheritAttrs: false,
        props: { show: Boolean },
        emits: ['update:show'],
        setup(props, { attrs, emit, slots }) {
          return () => props.show
            ? h('section', {
              ...attrs,
              'data-component': 'NModal',
              onRequestClose: () => emit('update:show', false),
            }, slotChildren(slots))
            : null
        },
      })

      export function useMessage() {
        return globalThis.__providerSettingsHarness.message
      }

      export function useDialog() {
        return globalThis.__providerSettingsHarness.dialog
      }
    `
  },
}

function hostNode(type, text = '') {
  return {
    type,
    text,
    props: {},
    children: [],
    parent: null,
  }
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
  setText(node, text) {
    node.text = String(text)
  },
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
  setScopeId(element, id) {
    element.props[id] = ''
  },
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

function findNode(root, predicate, label) {
  const node = walk(root).find(predicate)
  assert.ok(node, `missing rendered node: ${label}`)
  return node
}

function findButton(root, label) {
  return findNode(
    root,
    node => node.type === 'button' && textContent(node).trim() === label,
    `button ${label}`,
  )
}

function findInput(root, placeholder) {
  return findNode(
    root,
    node => node.type === 'input' && node.props.placeholder === placeholder,
    `input ${placeholder}`,
  )
}

function findComponentInstance(instance, name, visited = new Set()) {
  if (!instance || visited.has(instance)) return null
  visited.add(instance)
  if (
    instance.type?.name === name
    || instance.type?.__name === name
    || instance.type?.__file?.endsWith(`/${name}.vue`)
  ) return instance

  function fromVNode(vnode) {
    if (!vnode || typeof vnode !== 'object') return null
    const direct = findComponentInstance(vnode.component, name, visited)
    if (direct) return direct
    if (Array.isArray(vnode.children)) {
      for (const child of vnode.children) {
        const found = fromVNode(child)
        if (found) return found
      }
    }
    return fromVNode(vnode.component?.subTree)
  }

  return fromVNode(instance.subTree)
}

async function flush() {
  for (let index = 0; index < 4; index += 1) await Promise.resolve()
  await nextTick()
}

async function trigger(node, eventName, value) {
  const handlers = Array.isArray(node.props[eventName])
    ? node.props[eventName]
    : [node.props[eventName]]
  assert.equal(typeof handlers[0], 'function', `missing ${eventName}`)
  for (const handler of handlers) await handler(value)
  await flush()
}

function publicProvider(overrides = {}) {
  return {
    id: 'provider-1',
    name: '联通云',
    providerType: 'openai-compatible',
    model: 'deepseek-v4-flash',
    enabled: true,
    hasKey: true,
    hasBaseURL: true,
    lifecycleStatus: 'active',
    revision: 4,
    ready: true,
    ...overrides,
  }
}

function publicBinding() {
  return {
    projectId: 'project-1',
    revision: 1,
    contentHash: 'binding-hash',
    sourceProjectId: null,
    items: [],
  }
}

let vite
let ProviderForm
let ProviderSettings
let providerStoreModule
let api

async function compileClientRender(path) {
  const source = await readFile(new URL(`../../${path}`, import.meta.url), 'utf8')
  const filename = path.split('/').at(-1)
  const { descriptor } = parse(source, { filename })
  const script = compileScript(descriptor, { id: `provider-${filename}` })
  const compiled = compile(descriptor.template.content, {
    mode: 'function',
    prefixIdentifiers: true,
    bindingMetadata: script.bindings,
  })
  return new Function('Vue', compiled.code)(VueRuntime)
}

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
    plugins: [harnessStubPlugin, vuePlugin()],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  ProviderForm = (
    await vite.ssrLoadModule('/src/components/settings/ProviderForm.vue')
  ).default
  ProviderSettings = (
    await vite.ssrLoadModule('/src/components/settings/ProviderSettings.vue')
  ).default
  ProviderForm.render = await compileClientRender(
    'src/components/settings/ProviderForm.vue',
  )
  ProviderSettings.render = await compileClientRender(
    'src/components/settings/ProviderSettings.vue',
  )
  providerStoreModule = await vite.ssrLoadModule('/src/stores/providerStore.js')
  api = (await vite.ssrLoadModule('/src/api/db/client.js')).api
})

test.after(async () => {
  delete globalThis.__providerSettingsHarness
  await vite?.close()
})

function mountForm(props) {
  const root = hostNode('root')
  const app = renderer.createApp(ProviderForm, props)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)
  return { app, root }
}

async function mountSettings({ providerApi = {} } = {}) {
  const originals = { ...api.providers }
  Object.assign(api.providers, {
    list: async () => [publicProvider({
      apiKey: SECRET,
      baseURL: PRIVATE_URL,
      thinking: { token: SECRET, safe: 'visible' },
    })],
    create: async () => publicProvider({ id: 'created', revision: 1 }),
    update: async () => publicProvider({ revision: 5 }),
    delete: async () => publicProvider({
      enabled: false,
      hasKey: false,
      hasBaseURL: false,
      lifecycleStatus: 'deleted',
      revision: 5,
      ready: false,
    }),
    clearApiKey: async () => publicProvider({
      enabled: false,
      hasKey: false,
      hasBaseURL: true,
      lifecycleStatus: 'unconfigured',
      revision: 5,
      ready: false,
    }),
    testConnection: async () => ({
      ok: true,
      code: 'connected',
      latencyMs: 12,
      publicMessage: '连接成功',
    }),
    ...providerApi,
  })

  const messages = []
  const dialogs = []
  globalThis.__providerSettingsHarness = {
    message: Object.fromEntries(
      ['success', 'error', 'warning', 'info'].map(type => [
        type,
        content => messages.push({ type, content: String(content) }),
      ]),
    ),
    dialog: {
      warning(options) {
        dialogs.push(options)
        return {}
      },
    },
  }

  const pinia = createPinia()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: ProviderSettings }],
  })
  await router.push('/')
  await router.isReady()

  const root = hostNode('root')
  const Root = defineComponent({
    name: 'ProviderSettingsHarnessRoot',
    render: () => h(RouterView),
  })
  const app = renderer.createApp(Root)
  app.use(pinia)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)
  await flush()

  return {
    app,
    root,
    pinia,
    store: providerStoreModule.useProviderStore(pinia),
    messages,
    dialogs,
    restoreApi() {
      Object.assign(api.providers, originals)
    },
  }
}

test('real ProviderForm keeps edit secrets blank and clears submit, cancel, and unmount state', async () => {
  const emitted = []
  const mounted = mountForm({
    initial: {
      ...publicProvider(),
      apiKey: SECRET,
      baseURL: PRIVATE_URL,
    },
    saving: false,
    onSave: payload => emitted.push(['save', payload]),
    onCancel: () => emitted.push(['cancel']),
  })

  assert.equal(findInput(mounted.root, '留空保留现有密钥').props.value, '')
  assert.equal(findInput(mounted.root, '留空保留现有地址').props.value, '')
  assert.doesNotMatch(textContent(mounted.root), new RegExp(`${SECRET}|${PRIVATE_URL}`))

  await trigger(
    findInput(mounted.root, '留空保留现有密钥'),
    'onInput',
    { target: { value: SECRET } },
  )
  await trigger(
    findInput(mounted.root, '留空保留现有地址'),
    'onInput',
    { target: { value: PRIVATE_URL } },
  )
  await trigger(findButton(mounted.root, '保存'), 'onClick')

  assert.equal(emitted[0][0], 'save')
  assert.equal(emitted[0][1].apiKey, SECRET)
  assert.equal(emitted[0][1].baseURL, PRIVATE_URL)
  assert.equal(findInput(mounted.root, '留空保留现有密钥').props.value, '')
  assert.equal(findInput(mounted.root, '留空保留现有地址').props.value, '')

  await trigger(
    findInput(mounted.root, '留空保留现有密钥'),
    'onInput',
    { target: { value: SECRET } },
  )
  await trigger(
    findInput(mounted.root, '留空保留现有地址'),
    'onInput',
    { target: { value: PRIVATE_URL } },
  )
  await trigger(findButton(mounted.root, '取消'), 'onClick')
  assert.deepEqual(emitted.at(-1), ['cancel'])
  assert.equal(findInput(mounted.root, '留空保留现有密钥').props.value, '')
  assert.equal(findInput(mounted.root, '留空保留现有地址').props.value, '')

  await trigger(
    findInput(mounted.root, '留空保留现有密钥'),
    'onInput',
    { target: { value: SECRET } },
  )
  await trigger(
    findInput(mounted.root, '留空保留现有地址'),
    'onInput',
    { target: { value: PRIVATE_URL } },
  )
  const formInstance = findComponentInstance(mounted.app._instance, 'ProviderForm')
  assert.equal(formInstance.setupState.form.apiKey, SECRET)
  assert.equal(formInstance.setupState.form.baseURL, PRIVATE_URL)
  mounted.app.unmount()
  assert.equal(formInstance.setupState.form.apiKey, '')
  assert.equal(formInstance.setupState.form.baseURL, '')
})

test('real ProviderSettings keeps failed edit secrets out of Pinia and clears close state', async () => {
  let rejectUpdate
  let capturedPayload
  const mounted = await mountSettings({
    providerApi: {
      update: async (_id, payload) => {
        capturedPayload = payload
        return new Promise((_resolve, reject) => {
          rejectUpdate = reject
        })
      },
    },
  })

  try {
    await trigger(findButton(mounted.root, '编辑'), 'onClick')
    assert.equal(findInput(mounted.root, '留空保留现有密钥').props.value, '')
    assert.equal(findInput(mounted.root, '留空保留现有地址').props.value, '')

    await trigger(
      findInput(mounted.root, '留空保留现有密钥'),
      'onInput',
      { target: { value: SECRET } },
    )
    await trigger(
      findInput(mounted.root, '留空保留现有地址'),
      'onInput',
      { target: { value: PRIVATE_URL } },
    )
    const savePromise = trigger(findButton(mounted.root, '保存'), 'onClick')
    await flush()

    assert.equal(capturedPayload.apiKey, SECRET)
    assert.equal(capturedPayload.baseURL, PRIVATE_URL)
    assert.doesNotMatch(JSON.stringify(mounted.store.$state), new RegExp(`${SECRET}|${PRIVATE_URL}`))
    assert.equal(findInput(mounted.root, '留空保留现有密钥').props.value, '')
    assert.equal(findInput(mounted.root, '留空保留现有地址').props.value, '')

    rejectUpdate(new Error('safe update failure'))
    await savePromise
    await flush()
    assert.equal(capturedPayload.apiKey, '')
    assert.equal(capturedPayload.baseURL, '')
    assert.doesNotMatch(textContent(mounted.root), new RegExp(`${SECRET}|${PRIVATE_URL}`))

    await trigger(
      findInput(mounted.root, '留空保留现有密钥'),
      'onInput',
      { target: { value: SECRET } },
    )
    await trigger(
      findInput(mounted.root, '留空保留现有地址'),
      'onInput',
      { target: { value: PRIVATE_URL } },
    )
    const modal = findNode(
      mounted.root,
      node => node.props['data-component'] === 'NModal',
      'Provider modal',
    )
    await trigger(modal, 'onRequestClose')
    await trigger(findButton(mounted.root, '编辑'), 'onClick')
    assert.equal(findInput(mounted.root, '留空保留现有密钥').props.value, '')
    assert.equal(findInput(mounted.root, '留空保留现有地址').props.value, '')

    await trigger(
      findInput(mounted.root, '留空保留现有密钥'),
      'onInput',
      { target: { value: SECRET } },
    )
    await trigger(
      findInput(mounted.root, '留空保留现有地址'),
      'onInput',
      { target: { value: PRIVATE_URL } },
    )
    const formInstance = findComponentInstance(mounted.app._instance, 'ProviderForm')
    mounted.app.unmount()
    assert.equal(formInstance.setupState.form.apiKey, '')
    assert.equal(formInstance.setupState.form.baseURL, '')
  } finally {
    mounted.restoreApi()
  }
})

test('real ProviderSettings renders fixed feedback and reserves red danger confirmation for clear key', async () => {
  const calls = []
  const mounted = await mountSettings({
    providerApi: {
      testConnection: async id => {
        calls.push(['test', id])
        return {
          ok: true,
          code: 'connected',
          latencyMs: 12,
          publicMessage: '连接成功',
        }
      },
      delete: async (id, body) => {
        calls.push(['delete', id, body])
        return publicProvider({
          enabled: false,
          hasKey: false,
          hasBaseURL: false,
          lifecycleStatus: 'deleted',
          revision: 5,
          ready: false,
        })
      },
      clearApiKey: async (id, body) => {
        calls.push(['clear', id, body])
        return publicProvider({
          enabled: false,
          hasKey: false,
          hasBaseURL: true,
          lifecycleStatus: 'unconfigured',
          revision: 5,
          ready: false,
        })
      },
    },
  })

  try {
    await trigger(findButton(mounted.root, '测试连接'), 'onClick')
    assert.match(textContent(mounted.root), /连接成功[\s\S]*12 ms/)
    assert.doesNotMatch(textContent(mounted.root), new RegExp(`${SECRET}|${PRIVATE_URL}`))
    assert.deepEqual(calls, [['test', 'provider-1']])
    assert.equal(mounted.dialogs.length, 0)

    const clearPromise = trigger(findButton(mounted.root, '清除 API Key'), 'onClick')
    await flush()
    assert.equal(mounted.dialogs.length, 1)
    const clearDialog = mounted.dialogs[0]
    assert.equal(clearDialog.title, '清除 API Key')
    assert.equal(clearDialog.positiveText, '清除密钥')
    assert.equal(clearDialog.positiveButtonProps.type, 'error')
    clearDialog.onNegativeClick()
    await clearPromise

    await trigger(findButton(mounted.root, '停用并清除私密配置'), 'onClick')
    assert.equal(mounted.dialogs.length, 2)
    const deleteDialog = mounted.dialogs[1]
    assert.equal(deleteDialog.title, '停用并清除私密配置')
    assert.notEqual(deleteDialog.positiveButtonProps?.type, 'error')
    assert.equal(
      mounted.dialogs.filter(
        options => options.positiveButtonProps?.type === 'error',
      ).length,
      1,
    )
    assert.deepEqual(calls, [['test', 'provider-1']])
  } finally {
    mounted.app.unmount()
    mounted.restoreApi()
  }
})
