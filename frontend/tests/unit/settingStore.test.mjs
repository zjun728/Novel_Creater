import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('../..', import.meta.url))

test('setting store groups entities and exposes only pending change events', async () => {
  const vite = await createServer({ configFile: false, root, resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } }, server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error' })
  const { useSettingStore } = await vite.ssrLoadModule('/src/stores/settingStore.js')
  setActivePinia(createPinia())
  const store = useSettingStore()
  store.entities = [{ id: 'c', entityType: 'character' }, { id: 'f', entityType: 'faction' }]
  store.changeEvents = [{ id: 'p', status: 'pending_review' }, { id: 'a', status: 'accepted' }]
  assert.deepEqual(store.entitiesByType.character.map(item => item.id), ['c'])
  assert.deepEqual(store.entitiesByType.faction.map(item => item.id), ['f'])
  assert.deepEqual(store.pendingChangeEvents.map(item => item.id), ['p'])
  await vite.close()
})
