import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'


function jsonResponse(body) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}


async function loadStore() {
  try {
    return await import('../../src/stores/applicationSettingsStore.js')
  } catch (error) {
    assert.fail(`application settings store is missing: ${error.message}`)
  }
}


test('application fallback uses one revision CAS and keeps only public model identity', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  const secret = 'settings-response-secret'
  const privateURL = 'https://settings-private.example/v1'
  globalThis.fetch = async (url, options) => {
    calls.push({
      path: new URL(String(url)).pathname,
      method: options.method,
      body: options.body ? JSON.parse(options.body) : undefined,
    })
    return jsonResponse({
      revision: options.method === 'PUT' ? 4 : 3,
      fallbackProvider: {
        id: 'provider-1',
        name: '联通云',
        providerType: 'openai-compatible',
        model: 'deepseek-v4-flash',
        ready: true,
        apiKey: secret,
        baseURL: privateURL,
      },
      apiKey: secret,
      baseURL: privateURL,
    })
  }

  try {
    setActivePinia(createPinia())
    const { useApplicationSettingsStore } = await loadStore()
    const store = useApplicationSettingsStore()
    await store.loadSettings()
    await store.updateFallback('provider-1')

    assert.deepEqual(calls, [
      {
        path: '/api/settings/application',
        method: 'GET',
        body: undefined,
      },
      {
        path: '/api/settings/application/default-model',
        method: 'PUT',
        body: {
          expectedRevision: 3,
          fallbackProviderId: 'provider-1',
        },
      },
    ])
    assert.equal(store.settings.revision, 4)
    assert.deepEqual(store.settings.fallbackProvider, {
      id: 'provider-1',
      name: '联通云',
      providerType: 'openai-compatible',
      model: 'deepseek-v4-flash',
      ready: true,
    })
    assert.equal(JSON.stringify(store.$state).includes(secret), false)
    assert.equal(JSON.stringify(store.$state).includes(privateURL), false)
  } finally {
    globalThis.fetch = originalFetch
  }
})


test('diagnostics retains only the exact safe application allowlist', async () => {
  const originalFetch = globalThis.fetch
  const secret = 'diagnostic-secret'
  globalThis.fetch = async () => jsonResponse({
    schemaVersion: 'writer-core-v1.4.0',
    schemaManifestMatch: true,
    databaseReachable: true,
    managedCorpusStoreReady: false,
    schedulerEnabled: false,
    schedulerState: 'disabled',
    applicationVersion: '1.0.0',
    databaseHost: secret,
    dsn: secret,
    corpusPath: secret,
    providerConfig: { token: secret },
    exception: secret,
  })

  try {
    setActivePinia(createPinia())
    const { useApplicationSettingsStore } = await loadStore()
    const store = useApplicationSettingsStore()
    await store.loadDiagnostics()

    assert.deepEqual(store.diagnostics, {
      schemaVersion: 'writer-core-v1.4.0',
      schemaManifestMatch: true,
      databaseReachable: true,
      managedCorpusStoreReady: false,
      schedulerEnabled: false,
      schedulerState: 'disabled',
      applicationVersion: '1.0.0',
    })
    assert.equal(JSON.stringify(store.$state).includes(secret), false)
  } finally {
    globalThis.fetch = originalFetch
  }
})
