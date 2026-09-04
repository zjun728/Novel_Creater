import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createPinia, setActivePinia } from 'pinia'
import * as VueRuntime from 'vue'
import { createRenderer, nextTick, ssrContextKey } from '@vue/runtime-core'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('../..', import.meta.url))
const naiveId = '\0topic-discussion-naive'
const originalDocumentClass = globalThis.Document
class TestDocument { constructor() { this.activeElement = null } }
const documentRoot = new TestDocument()
const stubs = {
  name: 'topic-discussion-stubs',
  enforce: 'pre',
  resolveId(id) { return id === 'naive-ui' ? naiveId : undefined },
  load(id) {
    if (id !== naiveId) return undefined
    return `
      import { defineComponent, h } from 'vue'
      const children = slots => Object.values(slots).flatMap(slot => slot?.() || [])
      const stub = (name, tag = 'div') => defineComponent({
        name, inheritAttrs: false,
        setup(_, { attrs, slots }) { return () => h(tag, attrs, children(slots)) },
      })
      export const NAlert = stub('NAlert', 'aside')
      export const NButton = stub('NButton', 'button')
      export const NEmpty = stub('NEmpty')
      export const NSpin = stub('NSpin')
      export const NTag = stub('NTag', 'span')
    `
  },
}

const node = type => ({
  type, text: '', props: {}, children: [], parent: null, listeners: {}, value: '',
  addEventListener(name, handler) { this.listeners[name] = handler },
  removeEventListener(name) { delete this.listeners[name] },
  getRootNode() { return documentRoot },
})
const detach = child => {
  if (!child?.parent) return
  const index = child.parent.children.indexOf(child)
  if (index >= 0) child.parent.children.splice(index, 1)
  child.parent = null
}
const renderer = createRenderer({
  patchProp(item, key, _old, value) {
    if (value == null) delete item.props[key]
    else item.props[key] = value
  },
  insert(child, parent, anchor = null) {
    detach(child); child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(child)
    else parent.children.splice(index, 0, child)
  },
  remove: detach,
  createElement: node,
  createText: value => ({ ...node('#text'), text: String(value) }),
  createComment: value => ({ ...node('#comment'), text: String(value || '') }),
  setText(item, value) { item.text = String(value) },
  setElementText(item, value) { item.text = String(value); item.children = [] },
  parentNode: item => item?.parent || null,
  nextSibling: item => item?.parent?.children[item.parent.children.indexOf(item) + 1] || null,
  querySelector: () => null,
  setScopeId(item, id) { item.props[id] = '' },
  cloneNode: item => ({ ...item, props: { ...item.props }, children: [...item.children], parent: null }),
  insertStaticContent(content, parent, anchor) {
    const item = { ...node('#static'), text: content }
    renderer.insert(item, parent, anchor)
    return [item, item]
  },
})

function walk(item, result = []) {
  if (!item) return result
  result.push(item)
  for (const child of item.children || []) walk(child, result)
  return result
}
const textOf = item => [item?.text || '', ...(item?.children || []).map(textOf)].join('')
const find = (target, predicate) => walk(target).find(predicate)
const deferred = () => {
  let resolve; let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
async function flush() {
  for (let index = 0; index < 8; index += 1) await Promise.resolve()
  await nextTick()
}

let vite
let Component
let storeModule
test.before(async () => {
  globalThis.Document = TestDocument
  vite = await createServer({
    configFile: false, root, appType: 'custom', logLevel: 'error',
    resolve: { alias: { '@': `${root}/src` } },
    server: { middlewareMode: true, hmr: false, ws: false },
    plugins: [stubs, vuePlugin()],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  Component = (await vite.ssrLoadModule('/src/components/topics/TopicDiscussionPanel.vue')).default
  storeModule = await vite.ssrLoadModule('/src/stores/topicCenterStore.js')
  const source = await readFile(new URL('../../src/components/topics/TopicDiscussionPanel.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source)
  Component.render = new Function('Vue', compile(descriptor.template.content, {
    mode: 'function', prefixIdentifiers: true,
    bindingMetadata: compileScript(descriptor, { id: 'topic-discussion' }).bindings,
  }).code)(VueRuntime)
})
test.after(async () => {
  await vite?.close()
  if (originalDocumentClass === undefined) delete globalThis.Document
  else globalThis.Document = originalDocumentClass
})

function mountWith(pinia) {
  const target = node('root')
  const app = renderer.createApp(Component)
  app.component('RouterLink', {
    props: { to: String },
    setup(props, { slots }) { return () => VueRuntime.h('a', { href: props.to }, slots.default?.()) },
  })
  app.use(pinia)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(target)
  return { app, target }
}

test('route unmount and remount preserve the active discussion draft', async () => {
  const pinia = createPinia(); setActivePinia(pinia)
  const store = storeModule.createTopicCenterStore({}, 'topic-center')()
  store.activeDiscussion = { discussion: { id: 'route-d1', title: '路由草稿' }, messages: [], requests: [] }
  const first = mountWith(pinia); await flush()
  const textarea = find(first.target, item => item.type === 'textarea')
  textarea.value = '离开设置页前的想法'
  textarea.listeners.input({ target: textarea }); await flush()
  first.app.unmount()

  const second = mountWith(pinia); await flush()
  assert.equal(find(second.target, item => item.type === 'textarea').value, '离开设置页前的想法')
  second.app.unmount()
})

test('accepted send clears draft and reports reload warning without resend failure', async () => {
  const pinia = createPinia(); setActivePinia(pinia)
  const store = storeModule.createTopicCenterStore({
    sendMessage: async () => ({
      status: 'succeeded', requestId: 'r1', assistantMessageId: 'm2',
      result: { reply: '已接受。', directionSuggestions: [], candidateSuggestions: [] },
    }),
    getDiscussion: async () => { throw new Error('reload failed') },
  }, 'topic-center')()
  store.activeDiscussion = { discussion: { id: 'accepted-d1', title: '成功边界' }, messages: [], requests: [] }
  const mounted = mountWith(pinia); await flush()
  const textarea = find(mounted.target, item => item.type === 'textarea')
  textarea.value = '只应提交一次'
  textarea.listeners.input({ target: textarea }); await flush()
  const send = find(mounted.target, item => item.type === 'button' && textOf(item).includes('发送给 AI'))
  await send.props.onClick(); await flush()

  assert.equal(find(mounted.target, item => item.type === 'textarea').value, '')
  assert.equal(store.lastSendFailure, null)
  assert.match(textOf(mounted.target), /消息已经发送成功，但讨论记录刷新失败/)
  assert.doesNotMatch(textOf(mounted.target), /当前输入已保留|配置默认模型/)
  mounted.app.unmount()
})

test('origin failure stays hidden on another discussion and reappears with canonical settings link', async () => {
  const gate = deferred()
  const pinia = createPinia(); setActivePinia(pinia)
  const store = storeModule.createTopicCenterStore({
    sendMessage: async () => gate.promise,
  }, 'topic-center')()
  store.activeDiscussion = { discussion: { id: 'origin-d1', title: '原讨论' }, messages: [], requests: [] }
  const mounted = mountWith(pinia); await flush()
  const textarea = find(mounted.target, item => item.type === 'textarea')
  textarea.value = '保留在原讨论'
  textarea.listeners.input({ target: textarea }); await flush()
  const send = find(mounted.target, item => item.type === 'button' && textOf(item).includes('发送给 AI'))
  const pending = send.props.onClick(); await flush()

  store.activeDiscussion = { discussion: { id: 'other-d2', title: '另一讨论' }, messages: [], requests: [] }
  gate.reject(Object.assign(new Error('backend english message'), {
    code: 'TOPIC_PROVIDER_NOT_READY',
  }))
  await pending; await flush()
  assert.doesNotMatch(textOf(mounted.target), /配置默认模型|默认模型尚未配置/)

  store.activeDiscussion = { discussion: { id: 'origin-d1', title: '原讨论' }, messages: [], requests: [] }
  await flush()
  assert.match(textOf(mounted.target), /默认模型尚未配置/)
  assert.doesNotMatch(textOf(mounted.target), /backend english message/)
  const settings = find(mounted.target, item => item.type === 'a' && textOf(item).includes('配置默认模型'))
  assert.equal(settings.props.href, '/settings/providers')
  mounted.app.unmount()
})
