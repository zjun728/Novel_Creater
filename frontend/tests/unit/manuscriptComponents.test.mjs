import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createSSRApp } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

test('chapter list is an ordered volume directory with sibling reader and download controls', async () => {
  const source = await readFile(new URL('../../src/components/manuscript/ManuscriptChapterList.vue', import.meta.url), 'utf8')
  assert.match(source, /<section[^>]*v-for="\(volume, volumeIndex\) in volumes"/)
  assert.match(source, /<ol[^>]*class="manuscript-chapter-list__chapters"/)
  assert.match(source, /<li[^>]*v-for="chapter in volume\.chapters"/)
  assert.match(source, /<router-link[\s\S]*class="manuscript-chapter-list__reader"/)
  assert.match(source, /<button[^>]*class="manuscript-chapter-list__download"/)
  assert.match(source, /<time[^>]*:datetime=/)
  assert.match(source, /<\/router-link>\s*<button/)
})

test('chapter list renders semantic reader links and sibling controls without volume ids', async () => {
  const root = fileURLToPath(new URL('../..', import.meta.url))
  const vite = await createServer({ configFile: false, root, plugins: [vuePlugin()], server: { middlewareMode: true, hmr: false, ws: false }, optimizeDeps: { noDiscovery: true } })
  try {
    const Component = (await vite.ssrLoadModule('/src/components/manuscript/ManuscriptChapterList.vue')).default
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/projects/:projectId/manuscript/chapters/:chapterNumber', component: { template: '<div />' } }] })
    const app = createSSRApp(Component, { projectId: 'p', volumes: [{ id: '123e4567-e89b-12d3-a456-426614174000', order: 1, title: '卷一', chapters: [{ number: 2, title: '章名', scalarCount: 8, finalizedAt: '2026-01-01T00:00:00Z' }] }], formats: ['txt'], downloadableChapters: [2], downloadChapter: () => {} })
    app.use(router)
    const html = await renderToString(app)
    assert.match(html, /href="\/projects\/p\/manuscript\/chapters\/2"/)
    assert.match(html, /id="manuscript-chapter-2"/)
    assert.match(html, /<\/a>\s*<button/)
    assert.match(html, /datetime="2026-01-01T00:00:00Z"/)
    assert.doesNotMatch(html, /123e4567-e89b-12d3-a456-426614174000/)
  } finally { await vite.close() }
})
