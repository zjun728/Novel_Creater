import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'

import { compile } from '@vue/compiler-dom'
import { compileScript, parse } from '@vue/compiler-sfc'
import { createPinia } from 'pinia'
import * as VueRuntime from '@vue/runtime-core'
import { createRenderer, nextTick, ssrContextKey } from '@vue/runtime-core'
import { createSSRApp, h } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const naiveUiStubId = '\0project-route-naive-ui-stub'
const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))

const naiveUiStubPlugin = {
  name: 'project-route-naive-ui-stub',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveUiStubId
  },
  load(id) {
    if (id !== naiveUiStubId) return undefined
    return `
      import { defineComponent, h } from 'vue'
      const stub = name => defineComponent({
        name,
        inheritAttrs: false,
        setup(_, { attrs, slots }) {
          return () => h('div', attrs, slots.default?.())
        },
      })
      export const NAlert = stub('NAlert')
      export const NButton = stub('NButton')
      export const NCard = stub('NCard')
      export const NInput = stub('NInput')
      export const NResult = stub('NResult')
      export const NSkeleton = stub('NSkeleton')
      export const NStatistic = stub('NStatistic')
      export const NTag = stub('NTag')
    `
  },
}

function hostNode(type, text = '') {
  return { type, text, props: {}, children: [], parent: null }
}

function detach(child) {
  if (!child?.parent) return
  child.parent.children.splice(child.parent.children.indexOf(child), 1)
  child.parent = null
}

const renderer = createRenderer({
  patchProp(element, key, _oldValue, value) {
    if (value == null) delete element.props[key]
    else element.props[key] = value
  },
  insert(child, parent, anchor = null) {
    detach(child)
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index < 0) parent.children.push(child)
    else parent.children.splice(index, 0, child)
  },
  remove: detach,
  createElement: type => hostNode(type),
  createText: text => hostNode('#text', String(text)),
  createComment: text => hostNode('#comment', String(text || '')),
  setText(target, text) { target.text = String(text) },
  setElementText(target, text) {
    target.text = String(text)
    target.children = []
  },
  parentNode: target => target?.parent || null,
  nextSibling: target => (
    target?.parent?.children[target.parent.children.indexOf(target) + 1] || null
  ),
  querySelector: () => null,
  setScopeId(element, id) { element.props[id] = '' },
  cloneNode: target => ({
    ...target,
    props: { ...target.props },
    children: [...target.children],
    parent: null,
  }),
  insertStaticContent(content, parent, anchor) {
    const target = hostNode('#static', content)
    renderer.insert(target, parent, anchor)
    return [target, target]
  },
})

function renderedText(target) {
  if (!target) return ''
  return [
    target.text,
    target.props?.title,
    target.props?.description,
    ...(target.children || []).map(renderedText),
  ].filter(Boolean).join(' ')
}

function renderedNodes(target, predicate, found = []) {
  if (!target) return found
  if (predicate(target)) found.push(target)
  for (const child of target.children || []) renderedNodes(child, predicate, found)
  return found
}

async function flush() {
  for (let index = 0; index < 5; index += 1) await Promise.resolve()
  await new Promise(resolve => setTimeout(resolve, 0))
  await nextTick()
}

async function waitFor(predicate) {
  for (let index = 0; index < 30; index += 1) {
    if (predicate()) return
    await flush()
  }
  assert.fail('condition did not become true')
}

function deferred() {
  let resolve
  const promise = new Promise(next => {
    resolve = next
  })
  return { promise, resolve }
}

async function clientRender(path) {
  const contents = await readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')
  const filename = path.split('/').at(-1)
  const { descriptor } = parse(contents, { filename })
  const script = compileScript(descriptor, { id: `route-${filename}` })
  const result = compile(descriptor.template.content, {
    mode: 'function',
    prefixIdentifiers: true,
    bindingMetadata: script.bindings,
  })
  return new Function('Vue', result.code)(VueRuntime)
}

async function renderProjectOverview(createViteServer = createServer) {
  const originalFetch = global.fetch
  const requests = []
  global.fetch = async url => {
    requests.push(String(url))
    return new Response(JSON.stringify({
      id: 'project-1',
      title: '典镇山河',
      archivedAt: null,
      lifecycleRevision: 1,
    }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }

  let vite
  try {
    vite = await createViteServer({
      configFile: false,
      root: frontendRoot,
      server: { middlewareMode: true, hmr: false, ws: false },
      appType: 'custom',
      logLevel: 'error',
      plugins: [vuePlugin(), naiveUiStubPlugin],
      ssr: { noExternal: ['naive-ui'] },
      optimizeDeps: { noDiscovery: true },
    })
    const { projectRoutes } = await vite.ssrLoadModule('/src/router/projectRoutes.js')
    const router = createRouter({
      history: createMemoryHistory(),
      routes: projectRoutes,
    })
    await router.push('/projects/project-1/overview')
    await router.isReady()

    const app = createSSRApp({ render: () => h(RouterView) })
    app.use(createPinia())
    app.use(router)
    const html = await renderToString(app)

    return {
      html,
      requests,
      routeName: router.currentRoute.value.name,
    }
  } finally {
    try {
      await vite?.close()
    } finally {
      global.fetch = originalFetch
    }
  }
}

function currentOutline({
  chapterNumber = 1,
  confirmed = true,
  activeSession = null,
  startSession = true,
} = {}) {
  const planningAuthority = {
    planningRevisionId: 'planning-1',
    revision: 7,
    contentHash: 'a'.repeat(64),
    content: null,
  }
  const canonProjectionAuthority = {
    canonRevision: 5,
    projectionRevision: 5,
    contentHash: 'd'.repeat(64),
    synchronized: true,
  }
  return {
    projectId: 'project-1',
    lifecycle: 'active',
    authoritativeChapterNumber: chapterNumber,
    targetPath: `/projects/project-1/write/chapters/${chapterNumber}`,
    planningAuthority,
    canonProjectionAuthority,
    confirmedOutline: confirmed ? {
      projectId: 'project-1',
      chapterNumber,
      outlineRevisionId: 'outline-1',
      revision: 9,
      parentRevision: 8,
      contentHash: 'c'.repeat(64),
      content: {
        schemaVersion: 'chapter-outline-draft-v1',
        volumeRef: null,
        storyBlockRef: null,
        stageRefs: [],
        sceneTaskRefs: [],
        chapterGoal: '守住雨夜码头',
        expectedCharacters: ['林砚', '阿箬'],
        continuation: ['追查旧账'],
        plannedTasks: ['稳住船工'],
        scenes: ['雨夜码头'],
        forbiddenEarlyEvents: ['不可提前揭示内应'],
      },
      basis: {
        planningAuthority,
        canonProjectionAuthority,
      },
      status: 'current',
      reason: 'currentOutlineHead',
    } : null,
    draft: null,
    activeSession,
    pendingOperation: null,
    capabilities: {
      view: true,
      createDraft: false,
      editDraft: false,
      generate: false,
      confirm: false,
      startSession,
    },
    reasons: confirmed ? [] : ['outlineMissing'],
  }
}

function sessionWorkspace(chapterNumber = 1) {
  return {
    projectId: 'project-1',
    activeDraftOperationId: null,
    session: {
      id: `session-${chapterNumber}`,
      chapterNum: chapterNumber,
      expectedCanonRevision: 5,
      planningRevisionId: 'planning-1',
      planningRevision: 7,
      planningHash: 'a'.repeat(64),
      storyBlockId: 'block-1',
      storyBlockRevision: 2,
      storyBlockHash: 'b'.repeat(64),
      chapterOutlineRevisionId: 'outline-1',
      chapterOutlineRevision: 9,
      chapterOutlineHash: 'c'.repeat(64),
      status: 'drafting',
    },
    workingDraft: {
      id: `draft-${chapterNumber}`,
      projectId: 'project-1',
      chapterSessionId: `session-${chapterNumber}`,
      revision: 1,
      content: '',
      contentHash: 'e'.repeat(64),
    },
    candidates: [],
  }
}

async function mountWriter(path, fetchImpl) {
  const originalFetch = global.fetch
  global.fetch = fetchImpl
  const vite = await createServer({
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
    plugins: [vuePlugin(), naiveUiStubPlugin],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  const Writer = (await vite.ssrLoadModule('/src/views/ChapterWriterView.vue')).default
  Writer.render = await clientRender('views/ChapterWriterView.vue')
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/projects/:projectId/write/chapters/:chapterNumber',
        component: Writer,
      },
      {
        path: '/projects/:projectId/planning/story-blocks',
        component: { render: () => h('div', 'story blocks') },
      },
      {
        path: '/projects/:projectId/overview',
        component: { render: () => h('div', 'overview') },
      },
    ],
  })
  await router.push(path)
  await router.isReady()
  const pinia = createPinia()
  const root = hostNode('root')
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(pinia)
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount(root)
  return {
    root,
    router,
    async close() {
      app.unmount()
      await vite.close()
      global.fetch = originalFetch
    },
  }
}

test('real memory router lazy-loads and renders the project overview SFC loading state', async () => {
  const { html, requests, routeName } = await renderProjectOverview()

  assert.match(html, /class="overview-page"/)
  assert.match(html, /aria-busy="true"/)
  assert.equal(routeName, 'ProjectOverview')
  assert.deepEqual(requests, ['http://127.0.0.1:8000/api/projects/project-1'])
})

test('SSR harness restores global fetch when Vite server creation fails', async () => {
  const originalFetch = global.fetch
  const creationFailure = new Error('injected Vite creation failure')
  await assert.rejects(
    renderProjectOverview(async config => {
      assert.deepEqual(config.server, { middlewareMode: true, hmr: false, ws: false })
      throw creationFailure
    }),
    creationFailure,
  )
  assert.equal(global.fetch, originalFetch)
})

test('mounted Writer stops a wrong chapter after current and exposes only the explicit authority link', async () => {
  const requests = []
  const mounted = await mountWriter(
    '/projects/project-1/write/chapters/7',
    async (url, options = {}) => {
      requests.push([options.method || 'GET', new URL(String(url)).pathname])
      return new Response(JSON.stringify(currentOutline({ chapterNumber: 8 })), {
        headers: { 'content-type': 'application/json' },
      })
    },
  )
  try {
    await waitFor(() => /章节地址与服务端权威不一致/.test(renderedText(mounted.root)))
    assert.deepEqual(requests, [[
      'GET',
      '/api/projects/project-1/chapter-outlines/current',
    ]])
    assert.equal(
      mounted.router.currentRoute.value.fullPath,
      '/projects/project-1/write/chapters/7',
    )
    const links = renderedNodes(
      mounted.root,
      node => node.type === 'a',
    )
    assert.equal(
      links.some(node => node.props.href === '/projects/project-1/write/chapters/8'),
      true,
    )
  } finally {
    await mounted.close()
  }
})

test('mounted Writer replays an active Session with GET, checks pins, and renders the read-only Outline', async () => {
  const requests = []
  const current = currentOutline({
    activeSession: {
      chapterSessionId: 'session-1',
      chapterNumber: 1,
      status: 'drafting',
      planningRevisionId: 'planning-1',
      planningRevision: 7,
      planningHash: 'a'.repeat(64),
      outlineRevisionId: 'outline-1',
      outlineRevision: 9,
      outlineHash: 'c'.repeat(64),
    },
    startSession: false,
  })
  const mounted = await mountWriter(
    '/projects/project-1/write/chapters/1',
    async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      requests.push([options.method || 'GET', path])
      if (path.endsWith('/finalization')) {
        return new Response('{}', { status: 404 })
      }
      const body = path.endsWith('/chapter-outlines/current')
        ? current
        : sessionWorkspace(1)
      return new Response(JSON.stringify(body), {
        headers: { 'content-type': 'application/json' },
      })
    },
  )
  try {
    await waitFor(() => /守住雨夜码头/.test(renderedText(mounted.root)))
    assert.deepEqual(requests, [
      ['GET', '/api/projects/project-1/chapter-outlines/current'],
      ['GET', '/api/projects/project-1/chapter-sessions/1'],
      ['GET', '/api/projects/project-1/chapter-sessions/session-1/finalization'],
    ])
    assert.match(renderedText(mounted.root), /林砚/)
    assert.match(renderedText(mounted.root), /不可提前揭示内应/)
    const selfLinks = renderedNodes(
      mounted.root,
      node => (
        node.type === 'a'
        && node.props.href === '/projects/project-1/write/chapters/1'
      ),
    )
    assert.equal(selfLinks.length, 0)
  } finally {
    await mounted.close()
  }
})

test('mounted Writer creates only after confirmed current authority and sends the exact pins', async () => {
  const requests = []
  let createBody
  const mounted = await mountWriter(
    '/projects/project-1/write/chapters/1',
    async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      requests.push([options.method || 'GET', path])
      if (path.endsWith('/chapter-outlines/current')) {
        return new Response(JSON.stringify(currentOutline()), {
          headers: { 'content-type': 'application/json' },
        })
      }
      if (path.endsWith('/finalization')) {
        return new Response('{}', { status: 404 })
      }
      createBody = JSON.parse(options.body)
      return new Response(JSON.stringify(sessionWorkspace(1)), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      })
    },
  )
  try {
    await waitFor(() => /drafting/.test(renderedText(mounted.root)))
    assert.deepEqual(requests, [
      ['GET', '/api/projects/project-1/chapter-outlines/current'],
      ['POST', '/api/projects/project-1/chapter-sessions/1'],
      ['GET', '/api/projects/project-1/chapter-sessions/session-1/finalization'],
    ])
    assert.deepEqual(createBody, {
      chapterNumber: 1,
      expectedPlanningRevision: 7,
      expectedPlanningHash: 'a'.repeat(64),
      expectedOutlineRevision: 9,
      expectedOutlineHash: 'c'.repeat(64),
      expectedCanonRevision: 5,
    })
  } finally {
    await mounted.close()
  }
})

test('mounted Writer gives missing Outline a separate planning recovery link and makes zero Session requests', async () => {
  const requests = []
  const mounted = await mountWriter(
    '/projects/project-1/write/chapters/1',
    async (url, options = {}) => {
      requests.push([options.method || 'GET', new URL(String(url)).pathname])
      return new Response(JSON.stringify(currentOutline({
        confirmed: false,
        startSession: false,
      })), {
        headers: { 'content-type': 'application/json' },
      })
    },
  )
  try {
    await waitFor(() => /请先完成并确认本章小纲/.test(renderedText(mounted.root)))
    assert.deepEqual(requests, [[
      'GET',
      '/api/projects/project-1/chapter-outlines/current',
    ]])
    const links = renderedNodes(mounted.root, node => node.type === 'a')
    assert.equal(
      links.some(node => node.props.href === '/projects/project-1/planning/story-blocks'),
      true,
    )
    assert.equal(
      links.some(node => node.props.href === '/projects/project-1/write/chapters/1'),
      false,
    )
  } finally {
    await mounted.close()
  }
})

test('mounted Writer fences a late old-route current before any old Session request', async () => {
  const oldCurrent = deferred()
  const requests = []
  let currentReads = 0
  const mounted = await mountWriter(
    '/projects/project-1/write/chapters/1',
    async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      requests.push([options.method || 'GET', path])
      if (path.endsWith('/chapter-outlines/current')) {
        currentReads += 1
        if (currentReads === 1) return oldCurrent.promise
        return new Response(JSON.stringify(currentOutline({ chapterNumber: 2 })), {
          headers: { 'content-type': 'application/json' },
        })
      }
      if (path.endsWith('/finalization')) {
        return new Response('{}', { status: 404 })
      }
      return new Response(JSON.stringify(sessionWorkspace(2)), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      })
    },
  )
  try {
    await waitFor(() => currentReads === 1)
    await mounted.router.push('/projects/project-1/write/chapters/2')
    await waitFor(() => requests.some(([method]) => method === 'POST'))
    oldCurrent.resolve(new Response(JSON.stringify(currentOutline({
      chapterNumber: 1,
    })), {
      headers: { 'content-type': 'application/json' },
    }))
    await flush()

    assert.deepEqual(requests, [
      ['GET', '/api/projects/project-1/chapter-outlines/current'],
      ['GET', '/api/projects/project-1/chapter-outlines/current'],
      ['POST', '/api/projects/project-1/chapter-sessions/2'],
      ['GET', '/api/projects/project-1/chapter-sessions/session-2/finalization'],
    ])
    assert.equal(
      mounted.router.currentRoute.value.fullPath,
      '/projects/project-1/write/chapters/2',
    )
    assert.match(renderedText(mounted.root), /第 2 章/)
  } finally {
    await mounted.close()
  }
})
