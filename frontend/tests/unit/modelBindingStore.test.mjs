import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import {
  TASK_KEYS,
  useProviderStore,
} from '../../src/stores/providerStore.js'

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

async function withBrowserGuards(fetchImpl, action) {
  const originalFetch = globalThis.fetch
  const localStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() {
      throw new Error('formal provider state must never read localStorage')
    },
  })
  globalThis.fetch = fetchImpl
  try {
    return await action()
  } finally {
    globalThis.fetch = originalFetch
    if (localStorageDescriptor) {
      Object.defineProperty(globalThis, 'localStorage', localStorageDescriptor)
    } else {
      delete globalThis.localStorage
    }
  }
}

test('provider API responses never retain plaintext apiKey or baseURL in frontend state', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const secret = 'sk-plain-response-secret'
  const privateURL = 'https://private-provider.example/v1'

  await withBrowserGuards(async (_url, options) => jsonResponse({
    id: options.method === 'POST' ? 'provider-new' : 'provider-1',
    name: '联通云', providerType: 'openai-compatible', model: 'deepseek-v4-flash',
    enabled: true, hasKey: true, hasBaseURL: true,
    apiKey: secret, baseURL: privateURL,
  }), async () => {
    await store.addProvider({
      name: '联通云', providerType: 'openai-compatible', model: 'deepseek-v4-flash',
      apiKey: 'request-only', baseURL: 'https://request-only.example/v1',
    })
    await store.updateProvider({
      id: 'provider-new', name: '联通云', apiKey: 'replacement-request-only',
      baseURL: 'https://request-only.example/v2',
    })
  })

  const rendered = JSON.stringify(store.providers)
  assert.equal(rendered.includes(secret), false)
  assert.equal(rendered.includes(privateURL), false)
  assert.equal(rendered.includes('apiKey'), false)
  assert.equal(rendered.includes('baseURL'), false)
})

test('provider creation requires key and base URL before issuing a request', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  let requests = 0

  await withBrowserGuards(async () => {
    requests += 1
    return jsonResponse({})
  }, async () => {
    await assert.rejects(
      store.addProvider({
        name: '联通云', providerType: 'openai-compatible', model: 'deepseek-v4-flash',
        apiKey: '   ', baseURL: '',
      }),
      /API Key.*Base URL|Base URL.*API Key/i,
    )
  })

  assert.equal(requests, 0)
})

test('binding options expose only enabled public provider summaries that are fully configured', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()

  await withBrowserGuards(async () => jsonResponse([
    {
      id: 'ready', name: '联通云', providerType: 'openai-compatible', model: 'deepseek-v4-flash',
      enabled: true, hasKey: true, hasBaseURL: true, apiKey: 'must-not-survive',
    },
    {
      id: 'disabled', name: '已停用', providerType: 'openai-compatible', model: 'old',
      enabled: false, hasKey: true, hasBaseURL: true,
    },
    {
      id: 'missing-key', name: '缺密钥', providerType: 'openai-compatible', model: 'old',
      enabled: true, hasKey: false, hasBaseURL: true,
    },
  ]), async () => {
    await store.loadProviders()
  })

  assert.deepEqual(store.availableProviders.map(provider => provider.id), ['ready'])
  assert.equal(JSON.stringify(store.availableProviders).includes('must-not-survive'), false)
})

test('an older provider list cannot overwrite later provider updates or additions', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const oldUpdateList = deferred()
  const oldAddList = deferred()
  let listReads = 0

  await withBrowserGuards((url, options) => {
    const path = new URL(String(url)).pathname
    if (options.method === 'GET') {
      listReads += 1
      if (listReads === 1) return Promise.resolve(jsonResponse([{
        id: 'provider-1', name: '旧名称', providerType: 'openai-compatible', model: 'old-model',
        enabled: true, hasKey: true, hasBaseURL: true,
      }]))
      if (listReads === 2) return oldUpdateList.promise
      return oldAddList.promise
    }
    if (options.method === 'PUT' && path.endsWith('/provider-1')) {
      return Promise.resolve(jsonResponse({
        id: 'provider-1', name: '新名称', providerType: 'openai-compatible', model: 'new-model',
        enabled: true, hasKey: true, hasBaseURL: true,
      }))
    }
    if (options.method === 'POST') {
      return Promise.resolve(jsonResponse({
        id: 'provider-2', name: '新增模型', providerType: 'openai-compatible', model: 'second-model',
        enabled: true, hasKey: true, hasBaseURL: true,
      }))
    }
    throw new Error(`unexpected request ${options.method} ${path}`)
  }, async () => {
    await store.loadProviders()

    const staleUpdateRead = store.loadProviders(true)
    await store.updateProvider({ id: 'provider-1', name: '新名称', model: 'new-model' })
    oldUpdateList.resolve(jsonResponse([{
      id: 'provider-1', name: '旧名称', providerType: 'openai-compatible', model: 'old-model',
      enabled: true, hasKey: true, hasBaseURL: true,
    }]))
    await staleUpdateRead
    assert.equal(store.providers[0].model, 'new-model')

    const staleAddRead = store.loadProviders(true)
    await store.addProvider({
      name: '新增模型', providerType: 'openai-compatible', model: 'second-model',
      apiKey: 'request-only', baseURL: 'https://request-only.example/v1',
    })
    oldAddList.resolve(jsonResponse([{
      id: 'provider-1', name: '新名称', providerType: 'openai-compatible', model: 'new-model',
      enabled: true, hasKey: true, hasBaseURL: true,
    }]))
    await staleAddRead
  })

  assert.deepEqual(store.providers.map(provider => provider.id), ['provider-1', 'provider-2'])
})

test('all eight model bindings are replaced by one atomic CAS write', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const requests = []
  const entries = [...TASK_KEYS].reverse().map(taskKey => ({ taskKey, providerId: 'provider-1' }))

  await withBrowserGuards(async (url, options) => {
    requests.push({ path: new URL(String(url)).pathname, method: options.method, body: JSON.parse(options.body) })
    return jsonResponse({
      projectId: 'p1', revision: 4, contentHash: 'b'.repeat(64),
      items: TASK_KEYS.map(taskKey => ({ taskKey, resolutionStatus: 'bound', providerId: 'provider-1' })),
    })
  }, async () => {
    const result = await store.replaceBindings('p1', { expectedRevision: 3, entries })
    assert.equal(result.revision, 4)
  })

  assert.equal(TASK_KEYS.length, 8)
  assert.deepEqual(TASK_KEYS, [
    'seed', 'planning', 'writing', 'audit', 'summary', 'extraction', 'polish', 'market',
  ])
  assert.equal(requests.length, 1)
  assert.equal(requests[0].method, 'PUT')
  assert.deepEqual(requests[0].body, {
    expectedRevision: 3,
    entries: TASK_KEYS.map(taskKey => ({ taskKey, providerId: 'provider-1' })),
  })
  assert.equal(store.bindingStatus, null, 'replace response cannot invent backend readiness')
})

test('repeating the same binding save while it is pending issues only one CAS write', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const writes = []
  const entries = TASK_KEYS.map(taskKey => ({ taskKey, providerId: 'provider-1' }))

  await withBrowserGuards((_url, options) => {
    const response = deferred()
    writes.push(response)
    return response.promise
  }, async () => {
    const first = store.replaceBindings('p1', { expectedRevision: 3, entries })
    const duplicate = store.replaceBindings('p1', { expectedRevision: 3, entries })
    assert.equal(store.bindingSaving, true)

    for (const response of writes) {
      response.resolve(jsonResponse({
        projectId: 'p1', revision: 4, contentHash: 'b'.repeat(64),
        items: TASK_KEYS.map(taskKey => ({ taskKey, resolutionStatus: 'bound', providerId: 'provider-1' })),
      }))
    }
    await Promise.all([first, duplicate])
  })

  assert.equal(writes.length, 1)
  assert.equal(store.binding.revision, 4)
  assert.equal(store.bindingSaving, false)
})

test('settings source exposes an editable eight-row binding ledger without secret-clear transport', async () => {
  const [settings, form, bindings] = await Promise.all([
    readFile(new URL('../../src/components/settings/ProviderSettings.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/settings/ProviderForm.vue', import.meta.url), 'utf8'),
    readFile(new URL('../../src/components/settings/TaskModelBinding.vue', import.meta.url), 'utf8'),
  ])

  assert.match(settings, /停用并清除私密配置/)
  assert.doesNotMatch(`${settings}\n${form}`, /clearApiKey|clearBaseURL|清除当前 API Key|清除当前 Base URL/)
  assert.match(bindings, /一次保存八项绑定/)
  assert.match(bindings, /replaceBindings/)
  assert.match(bindings, /bindingComplete/)
  assert.match(bindings, /bindingReady/)
  assert.match(bindings, /bindingReasons/)
  assert.match(bindings, /window\.confirm/)
  assert.match(bindings, /beforeunload/)
  assert.match(settings, /:mask-closable="!saving"/)
  assert.match(settings, /:close-on-esc="!saving"/)
  assert.match(settings, /onBeforeRouteLeave/)
  assert.match(settings, /beforeunload/)
  assert.match(settings, /showForm\.value\s*\|\|\s*bindingDirty\.value/)
  assert.match(form, /:disabled="saving\s*\|\|\s*editing"/)
  assert.match(form, /Provider 类型创建后不可更改/)
  assert.doesNotMatch(bindings, /M1 只读|只读映射/)
  assert.doesNotMatch(`${settings}\n${form}\n${bindings}`, /\bfetch\s*\(|localStorage/)
})

test('binding complete and ready stay distinct and use only the latest backend status', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const pending = new Map()

  await withBrowserGuards((url) => {
    const projectId = new URL(String(url)).pathname.split('/')[3]
    const response = deferred()
    pending.set(projectId, response)
    return response.promise
  }, async () => {
    const oldLoad = store.getBindingStatus('old', { force: true })
    const newLoad = store.getBindingStatus('new', { force: true })
    pending.get('new').resolve(jsonResponse({
      projectId: 'new', revision: 7, contentHash: 'n'.repeat(64), items: [],
      bindingComplete: true, bindingReady: false, reasons: ['provider_unavailable:writing'],
    }))
    await newLoad
    pending.get('old').resolve(jsonResponse({
      projectId: 'old', revision: 1, contentHash: 'o'.repeat(64), items: [],
      bindingComplete: true, bindingReady: true, reasons: [],
    }))
    await oldLoad

    assert.equal(store.bindingStatus.projectId, 'new')
    assert.equal(store.bindingComplete, true)
    assert.equal(store.bindingReady, false)
    assert.deepEqual(store.bindingReasons, ['provider_unavailable:writing'])
  })
})

test('selecting a cached binding status invalidates an older in-flight refresh', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const oldPending = deferred()
  let cachedReads = 0

  await withBrowserGuards((url) => {
    const projectId = new URL(String(url)).pathname.split('/')[3]
    if (projectId === 'cached') {
      cachedReads += 1
      return Promise.resolve(jsonResponse({
        projectId: 'cached', revision: 5, contentHash: 'c'.repeat(64), items: [],
        bindingComplete: true, bindingReady: true, reasons: [],
      }))
    }
    if (projectId === 'old') return oldPending.promise
    throw new Error(`unexpected project ${projectId}`)
  }, async () => {
    await store.getBindingStatus('cached', { force: true })
    const oldRefresh = store.getBindingStatus('old', { force: true })
    await store.getBindingStatus('cached')
    oldPending.resolve(jsonResponse({
      projectId: 'old', revision: 1, contentHash: 'o'.repeat(64), items: [],
      bindingComplete: true, bindingReady: false, reasons: ['seed_drift'],
    }))
    await oldRefresh

    assert.equal(store.bindingStatus.projectId, 'cached')
    assert.equal(store.bindingReady, true)
  })

  assert.equal(cachedReads, 1, 'cached selection must not perform another backend request')
})

test('a successful binding replacement invalidates an older in-flight status read', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const pendingStatus = deferred()

  await withBrowserGuards((url, options) => {
    if (options.method === 'GET') return pendingStatus.promise
    return Promise.resolve(jsonResponse({
      projectId: 'p1', revision: 2, contentHash: 'n'.repeat(64),
      items: TASK_KEYS.map(taskKey => ({ taskKey, resolutionStatus: 'bound', providerId: 'provider-1' })),
    }))
  }, async () => {
    const oldStatus = store.getBindingStatus('p1', { force: true })
    await store.replaceBindings('p1', {
      expectedRevision: 1,
      entries: TASK_KEYS.map(taskKey => ({ taskKey, providerId: 'provider-1' })),
    })
    pendingStatus.resolve(jsonResponse({
      projectId: 'p1', revision: 1, contentHash: 'o'.repeat(64), items: [],
      bindingComplete: true, bindingReady: true, reasons: [],
    }))
    await oldStatus

    assert.equal(store.binding.revision, 2)
    assert.equal(store.bindingStatus, null)
    assert.equal(store.bindingReady, false)
  })
})

test('a successful binding replacement invalidates an older in-flight binding read', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const pendingBinding = deferred()

  await withBrowserGuards((url, options) => {
    if (options.method === 'GET') return pendingBinding.promise
    return Promise.resolve(jsonResponse({
      projectId: 'p1', revision: 2, contentHash: 'n'.repeat(64),
      items: TASK_KEYS.map(taskKey => ({ taskKey, resolutionStatus: 'bound', providerId: 'provider-1' })),
    }))
  }, async () => {
    const oldBinding = store.getBindings('p1', { force: true })
    await store.replaceBindings('p1', {
      expectedRevision: 1,
      entries: TASK_KEYS.map(taskKey => ({ taskKey, providerId: 'provider-1' })),
    })
    pendingBinding.resolve(jsonResponse({
      projectId: 'p1', revision: 1, contentHash: 'o'.repeat(64), items: [],
    }))
    await oldBinding

    assert.equal(store.binding.revision, 2)
    assert.equal(store.bindingCache.p1.revision, 2)
  })
})

test('binding loading remains true until concurrent binding and status reads both settle', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const bindingPending = deferred()
  const statusPending = deferred()

  await withBrowserGuards((url) => (
    new URL(String(url)).pathname.endsWith('/status')
      ? statusPending.promise
      : bindingPending.promise
  ), async () => {
    const bindingRead = store.getBindings('p1', { force: true })
    const statusRead = store.getBindingStatus('p1', { force: true })
    assert.equal(store.bindingLoading, true)

    bindingPending.resolve(jsonResponse({
      projectId: 'p1', revision: 1, contentHash: 'a'.repeat(64), items: [],
    }))
    await bindingRead
    const loadingWhileStatusPending = store.bindingLoading

    statusPending.resolve(jsonResponse({
      projectId: 'p1', revision: 1, contentHash: 'a'.repeat(64), items: [],
      bindingComplete: true, bindingReady: true, reasons: [],
    }))
    await statusRead
    assert.equal(loadingWhileStatusPending, true, 'status request is still pending')
    assert.equal(store.bindingLoading, false)
  })
})

test('cross-project binding and status reads can never form a mixed active snapshot', async () => {
  setActivePinia(createPinia())
  let store = useProviderStore()
  let bindingPending = deferred()
  let statusPending = deferred()

  await withBrowserGuards((url) => (
    new URL(String(url)).pathname.endsWith('/status')
      ? statusPending.promise
      : bindingPending.promise
  ), async () => {
    const staleBinding = store.getBindings('project-a', { force: true })
    const currentStatus = store.getBindingStatus('project-b', { force: true })
    statusPending.resolve(jsonResponse({
      projectId: 'project-b', revision: 4, contentHash: 'b'.repeat(64), items: [],
      bindingComplete: true, bindingReady: true, reasons: [],
    }))
    await currentStatus
    bindingPending.resolve(jsonResponse({
      projectId: 'project-a', revision: 1, contentHash: 'a'.repeat(64), items: [],
    }))
    await staleBinding

    assert.equal(store.bindingProjectId, 'project-b')
    assert.equal(store.binding, null)
    assert.equal(store.bindingStatus.projectId, 'project-b')
  })

  setActivePinia(createPinia())
  store = useProviderStore()
  bindingPending = deferred()
  statusPending = deferred()

  await withBrowserGuards((url) => (
    new URL(String(url)).pathname.endsWith('/status')
      ? statusPending.promise
      : bindingPending.promise
  ), async () => {
    const staleStatus = store.getBindingStatus('project-a', { force: true })
    const currentBinding = store.getBindings('project-b', { force: true })
    bindingPending.resolve(jsonResponse({
      projectId: 'project-b', revision: 5, contentHash: 'c'.repeat(64), items: [],
    }))
    await currentBinding
    statusPending.resolve(jsonResponse({
      projectId: 'project-a', revision: 2, contentHash: 'd'.repeat(64), items: [],
      bindingComplete: true, bindingReady: false, reasons: ['provider_unavailable:writing'],
    }))
    await staleStatus

    assert.equal(store.bindingProjectId, 'project-b')
    assert.equal(store.binding.projectId, 'project-b')
    assert.equal(store.bindingStatus, null)
  })
})

test('a late binding write response cannot switch the active project back', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const pendingWrite = deferred()

  await withBrowserGuards((url, options) => {
    const projectId = new URL(String(url)).pathname.split('/')[3]
    if (options.method === 'PUT' && projectId === 'project-a') return pendingWrite.promise
    if (options.method === 'GET' && projectId === 'project-b') {
      return Promise.resolve(jsonResponse({
        projectId: 'project-b', revision: 7, contentHash: 'b'.repeat(64), items: [],
      }))
    }
    throw new Error(`unexpected request ${options.method} ${url}`)
  }, async () => {
    const writeA = store.replaceBindings('project-a', {
      expectedRevision: 1,
      entries: TASK_KEYS.map(taskKey => ({ taskKey, providerId: 'provider-1' })),
    })
    await store.getBindings('project-b', { force: true })
    pendingWrite.resolve(jsonResponse({
      projectId: 'project-a', revision: 2, contentHash: 'a'.repeat(64),
      items: TASK_KEYS.map(taskKey => ({ taskKey, resolutionStatus: 'bound', providerId: 'provider-1' })),
    }))
    const savedA = await writeA

    assert.equal(savedA.projectId, 'project-a')
    assert.equal(savedA.revision, 2)
    assert.equal(store.bindingProjectId, 'project-b')
    assert.equal(store.binding.projectId, 'project-b')
    assert.equal(store.binding.revision, 7)
    assert.equal(store.bindingCache['project-a'].revision, 2)
  })
})

test('binding replacement rejects missing or duplicate task keys before fetch', async () => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  let requests = 0

  await withBrowserGuards(async () => {
    requests += 1
    return jsonResponse({})
  }, async () => {
    await assert.rejects(
      store.replaceBindings('p1', {
        expectedRevision: 1,
        entries: TASK_KEYS.slice(0, 7).map(taskKey => ({ taskKey, providerId: null })),
      }),
      /each task key exactly once/i,
    )
    await assert.rejects(
      store.replaceBindings('p1', {
        expectedRevision: 1,
        entries: TASK_KEYS.map(() => ({ taskKey: 'seed', providerId: null })),
      }),
      /each task key exactly once/i,
    )
  })

  assert.equal(requests, 0)
})

test('binding project fallback ignores an archived current project', async () => {
  let selectionModule
  try {
    selectionModule = await import('../../src/components/settings/projectBindingSelection.js')
  } catch (error) {
    assert.fail(`active project selection helper is missing: ${error.message}`)
  }
  const { chooseActiveProjectId } = selectionModule
  const activeProjects = [
    { id: 'active-1', title: '活动项目一' },
    { id: 'active-2', title: '活动项目二' },
  ]
  const archivedCurrent = { id: 'archived-1', title: '已归档项目', archivedAt: 123 }

  assert.equal(
    chooseActiveProjectId(activeProjects, '', archivedCurrent),
    'active-1',
  )
  assert.equal(
    chooseActiveProjectId([], '', archivedCurrent),
    '',
  )
  assert.equal(
    chooseActiveProjectId(activeProjects, '', activeProjects[1]),
    'active-2',
  )
  assert.equal(
    chooseActiveProjectId(activeProjects, 'active-1', activeProjects[1]),
    'active-1',
  )
})
