import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { computed, createSSRApp, h, ref, shallowRef } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'
import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import * as VueRuntime from 'vue'
import { createFinalizationController } from '../../src/application/writer/finalizationController.js'


const source = path => readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')

const root = fileURLToPath(new URL('../..', import.meta.url))
const naiveStubId = '\0finalization-panel-naive-stub'
const naiveStub = {
  name: 'finalization-panel-naive-stub',
  enforce: 'pre',
  resolveId: id => id === 'naive-ui' ? naiveStubId : undefined,
  load: id => id === naiveStubId ? `
    import { defineComponent, h } from 'vue'
    const children = slots => Object.values(slots).flatMap(slot => slot?.() || [])
    const stub = name => defineComponent({ name, setup(_, { attrs, slots }) { return () => h('div', attrs, children(slots)) } })
    export const NAlert = stub('NAlert')
    export const NCard = stub('NCard')
    export const NInput = stub('NInput')
    export const NTag = stub('NTag')
    export const NButton = defineComponent({ name: 'NButton', setup(_, { attrs, slots }) { return () => h('button', attrs, children(slots)) } })
  ` : undefined,
}

let vite
let FinalizationPanel
let InteractivePanel
test.before(async () => {
  vite = await createServer({
    configFile: false,
    root,
    appType: 'custom',
    logLevel: 'error',
    server: { middlewareMode: true, hmr: false, ws: false },
    plugins: [vuePlugin(), naiveStub],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  FinalizationPanel = (await vite.ssrLoadModule(
    '/src/components/writer/FinalizationPanel.vue',
  )).default
  const { descriptor } = parse(await source('components/writer/FinalizationPanel.vue'))
  InteractivePanel = { ...FinalizationPanel, render: new Function('Vue', compile(
    descriptor.template.content,
    {
      mode: 'function', prefixIdentifiers: true,
      bindingMetadata: compileScript(descriptor, { id: 'finalization-panel' }).bindings,
    },
  ).code)(VueRuntime) }
})
test.after(async () => { await vite?.close() })

const makeNode = type => ({ type, text: '', props: {}, children: [], parent: null })
const detach = child => {
  if (child?.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
}
const renderer = VueRuntime.createRenderer({
  patchProp(node, key, _old, value) {
    if (value == null) delete node.props[key]
    else node.props[key] = value
  },
  insert(child, parent, anchor = null) {
    detach(child)
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(child)
    else parent.children.splice(index, 0, child)
  },
  remove: detach,
  createElement: makeNode,
  createText: value => ({ ...makeNode('#text'), text: String(value) }),
  createComment: () => makeNode('#comment'),
  setText: (node, value) => { node.text = String(value) },
  setElementText: (node, value) => { node.text = String(value); node.children = [] },
  parentNode: node => node?.parent || null,
  nextSibling: node => node?.parent?.children[node.parent.children.indexOf(node) + 1] || null,
  setScopeId: (node, id) => { node.props[id] = '' },
})
const nodeText = node => [node?.text, ...(node?.children || []).map(nodeText)].filter(Boolean).join(' ')
const walk = node => [node, ...(node.children || []).flatMap(walk)]
const buttons = (root, label) => walk(root).filter(node => node.type === 'button' && nodeText(node) === label)

async function mountReview({ correctFailure = false } = {}) {
  const hashA = 'a'.repeat(64)
  const hashB = 'b'.repeat(64)
  const payload = {
    schemaVersion: 'finalization-changeset-v1', title: '第一章', summary: '摘要',
    existingEntityIds: [], entities: [], aliases: [], canonEvents: [], storyProgressEvents: [],
    planningPatches: ['patch-1', 'patch-2'].map(id => ({
      id, targetType: 'stage', targetId: id, fieldPath: 'title', replacement: id,
      evidence: { startScalar: 0, endScalar: 2 },
    })),
    planningSuggestions: [{ id: 'suggestion-1', message: '调整后续节奏' }],
  }
  let current = {
    status: 'awaiting_author', qualityReport: { status: 'completed', findings: [], deterministicBlocks: [] },
    changeSet: { revision: 1, contentHash: hashA, payload },
    confirmation: null,
  }
  const calls = []
  let pendingRead = null
  const controller = createFinalizationController({
    getReview: async () => {
      if (pendingRead) await pendingRead
      return structuredClone(current)
    },
    correct: async command => {
      calls.push(['correct', command])
      if (correctFailure) throw new Error('save failed')
      current = { ...current, changeSet: { revision: 2, contentHash: hashB, payload: command.changeSet } }
    },
    confirm: async command => {
      calls.push(['confirm', command])
      current = { ...current, confirmation: { revision: 2, contentHash: hashB } }
    },
  })
  await controller.load()
  const app = renderer.createApp(InteractivePanel, { controller })
  app.provide(VueRuntime.ssrContextKey, {})
  app.component('router-link', { render: () => h('a') })
  const root = makeNode('root')
  app.mount(root)
  const pauseLoad = () => {
    let release
    pendingRead = new Promise(resolve => { release = resolve })
    const request = controller.load()
    return async () => { release(); await request }
  }
  return { app, root, controller, calls, payload, pauseLoad }
}

test('removing one future planning patch stays local until a new revision is saved and confirmed', async () => {
  const { app, root, controller, calls, payload } = await mountReview()
  try {
    assert.equal(buttons(root, '移除此项调整').length, 2)
    await buttons(root, '移除此项调整')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(controller.review.value.changeSet.payload, payload)
    assert.equal(buttons(root, '移除此项调整').length, 1)
    assert.deepEqual(calls, [])
    const confirm = buttons(root, '确认以上变更')[0]
    assert.equal(confirm.props.disabled, true)
    await confirm.props.onClick()
    assert.deepEqual(calls, [])
    await buttons(root, '保存修正')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(calls[0][1].changeSet.planningPatches.map(item => item.id), ['patch-2'])
    assert.equal(controller.review.value.changeSet.revision, 2)
    assert.equal(buttons(root, '保存修正').length, 0)
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, false)
    await buttons(root, '确认以上变更')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.deepEqual(calls[1], ['confirm', { expectedRevision: 2, expectedRevisionHash: 'b'.repeat(64) }])
    assert.equal(buttons(root, '放弃审查并返回修改').length, 0)
    assert.equal(buttons(root, '移除此项调整')[0].props.disabled, true)
  } finally { app.unmount() }
})

test('failed correction preserves the patch deletion draft and keeps confirmation disabled', async () => {
  const { app, root, controller, calls } = await mountReview({ correctFailure: true })
  try {
    assert.equal(buttons(root, '移除此项调整').length, 2)
    await buttons(root, '移除此项调整')[0].props.onClick()
    await VueRuntime.nextTick()
    await buttons(root, '保存修正')[0].props.onClick()
    await VueRuntime.nextTick()
    assert.equal(controller.review.value.changeSet.revision, 1)
    assert.equal(controller.review.value.changeSet.payload.planningPatches.length, 2)
    assert.equal(buttons(root, '移除此项调整').length, 1)
    assert.equal(buttons(root, '确认以上变更')[0].props.disabled, true)
    await buttons(root, '确认以上变更')[0].props.onClick()
    assert.equal(calls.length, 1)
  } finally { app.unmount() }
})

test('patch removal cannot change confirmed, busy or finalized review drafts', async () => {
  for (const state of ['confirmed', 'busy', 'finalized']) {
    const { app, root, controller, payload, calls, pauseLoad } = await mountReview()
    let releaseLoad
    try {
      const remove = buttons(root, '移除此项调整')[0]
      assert.ok(remove, state)
      if (state === 'busy') releaseLoad = pauseLoad()
      else if (state === 'confirmed') controller.review.value = {
        ...controller.review.value, confirmation: { revision: 1, contentHash: 'a'.repeat(64) },
      }
      else controller.review.value = { ...controller.review.value, status: 'committed' }
      await VueRuntime.nextTick()
      if (state !== 'finalized') assert.equal(buttons(root, '移除此项调整')[0].props.disabled, true, state)
      else assert.equal(buttons(root, '移除此项调整').length, 0)
      await remove.props.onClick()
      await VueRuntime.nextTick()
      assert.deepEqual(controller.review.value.changeSet.payload, payload, state)
      assert.deepEqual(calls, [], state)
      if (state !== 'finalized') assert.equal(buttons(root, '移除此项调整').length, 2, state)
    } finally { await releaseLoad?.(); app.unmount() }
  }
})

test('non-authoritative suggestions visibly explain that they do not update planning', async () => {
  const { app, root } = await mountReview()
  try {
    assert.match(nodeText(root), /非权威建议/)
    assert.match(nodeText(root), /不会写入规划/)
  } finally { app.unmount() }
})


test('Writer embeds one compact author-controlled finalization panel', async () => {
  const [view, panel] = await Promise.all([
    source('views/ChapterWriterView.vue'),
    source('components/writer/FinalizationPanel.vue'),
  ])

  assert.match(view, /components\/writer\/FinalizationPanel\.vue/)
  assert.match(view, /createFinalizationController/)
  assert.match(view, /<finalization-panel/)
  assert.match(view, /:planning-content="planningContent"/)
  assert.match(view, /finalization\.reset\(\)/)
  assert.match(view, /finalization\.load\(\)/)
  assert.match(view, /finalization\.dispose\(\)/)
  assert.match(view, /editorReadonly[\s\S]*finalization\.finalized\.value/)

  for (const label of [
    '审查并定稿', '确定性阻断', '质量建议', 'Canon 事实',
    '故事进度', '未来规划调整', '保存修正', '确认以上变更', '定稿本章',
    '放弃审查并返回修改',
  ]) assert.match(panel, new RegExp(label))
  assert.match(panel, /controller\.prepareCandidate/)
  assert.match(panel, /controller\.correctChangeSet/)
  assert.match(panel, /controller\.confirmChangeSet/)
  assert.match(panel, /controller\.commitChapter/)
  assert.match(panel, /controller\.cancelReview/)
  assert.match(panel, /planningContent/)
  assert.match(panel, /targetLabel\(item\)/)
  assert.doesNotMatch(panel, /item\.targetType\s*}}\s*·\s*{{\s*item\.targetId/)
  assert.match(panel, /previousCandidateIds/)
  assert.match(panel, /review\?\.status === 'failed'/)
  assert.match(panel, /审查未完成，正文和候选稿未受影响/)
  assert.equal(
    panel.match(/v-if="controller\.primaryAction\.value === 'confirm'"/g)?.length,
    2,
  )
  assert.doesNotMatch(
    panel,
    /v-else-if="controller\.primaryAction\.value === 'confirm'"/,
  )
  assert.doesNotMatch(panel, /通过分数|及格分|自动修复|自动定稿|partial approval/i)
  assert.doesNotMatch(panel, /<textarea[^>]*json|page\.request|page\.route|fetch\(|axios|page\.evaluate/i)
})


test('the panel renders evidence without exposing full candidate prose', async () => {
  const panel = await source('components/writer/FinalizationPanel.vue')

  assert.match(panel, /startScalar/)
  assert.match(panel, /endScalar/)
  assert.doesNotMatch(panel, /candidate\.content|workingDraft\.content|rawProvider|prompt|apiKey|dsn/i)
})


test('finalized panel stays in place and offers only verified explicit navigation', async () => {
  const panel = await source('components/writer/FinalizationPanel.vue')

  assert.match(panel, /controller\.postFinalization\.value/)
  assert.match(panel, /postFinalization\.currentAction\.state === 'available'/)
  assert.match(panel, /:to="postFinalization\.currentAction\.targetPath"/)
  assert.match(panel, /\{\{ postFinalization\.currentAction\.label \}\}/)
  assert.match(panel, /postFinalization\?\.finalizedChapterReadable/)
  assert.match(panel, /:to="postFinalization\.finalizedChapterPath"/)
  assert.match(panel, /查看本章定稿/)
  assert.match(panel, /controller\.refreshPostFinalization/)
  assert.match(panel, /:disabled="controller\.postBusy\.value"/)
  assert.match(panel, /v-if="!postFinalization"[\s\S]*正在读取定稿后的创作状态/)
  assert.match(panel, /currentAction\.state === 'archived'[\s\S]*项目当前为只读状态/)
  assert.match(panel, /\.panel-intro[^}]*color:\s*#675d51/)
  assert.match(panel, /\.finalized-action--primary span[^}]*color:\s*#675d51/)
  assert.match(panel, /\.muted[^}]*color:\s*#6f6559/)
  assert.doesNotMatch(panel, /未实现内容|router\.push|router\.replace|window\.location/)
})


test('finalized panel renders a loading state while post-commit refresh is pending', async () => {
  const controller = {
    review: shallowRef({ status: 'committed' }),
    result: shallowRef({ chapterNumber: 4 }),
    postFinalization: shallowRef(null),
    postBusy: computed(() => false),
    busy: computed(() => true),
    error: ref(''),
    hardBlocks: computed(() => []),
    finalized: computed(() => true),
    primaryAction: computed(() => 'done'),
    refreshPostFinalization: async () => {},
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { render: () => h('div') } }],
  })
  await router.push('/')
  await router.isReady()
  const app = createSSRApp(FinalizationPanel, { controller })
  app.use(router)

  const html = await renderToString(app)

  assert.match(html, /本章已定稿/)
  assert.match(html, /正在读取定稿后的创作状态/)
  assert.doesNotMatch(html, /项目当前为只读状态|重新读取创作状态/)
})


test('initialized post-finalization refresh shows progress until retry is settled', async () => {
  const controller = {
    review: shallowRef({ status: 'committed' }),
    result: shallowRef({ chapterNumber: 4 }),
    postFinalization: shallowRef({
      currentAction: {
        state: 'unavailable',
        label: '重新读取创作状态',
      },
      finalizedChapterReadable: false,
    }),
    postBusy: computed(() => true),
    busy: computed(() => true),
    error: ref(''),
    hardBlocks: computed(() => []),
    finalized: computed(() => true),
    primaryAction: computed(() => 'done'),
    refreshPostFinalization: async () => {},
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: { render: () => h('div') } }],
  })
  await router.push('/')
  await router.isReady()
  const app = createSSRApp(FinalizationPanel, { controller })
  app.use(router)

  const html = await renderToString(app)

  assert.match(html, /正在读取创作状态…/)
  assert.doesNotMatch(html, /重新读取创作状态|项目当前为只读状态/)

  const settledApp = createSSRApp(FinalizationPanel, {
    controller: {
      ...controller,
      postBusy: computed(() => false),
      busy: computed(() => false),
    },
  })
  settledApp.use(router)
  const settledHtml = await renderToString(settledApp)

  assert.match(settledHtml, /重新读取创作状态/)
  assert.doesNotMatch(settledHtml, /正在读取创作状态…/)
})
