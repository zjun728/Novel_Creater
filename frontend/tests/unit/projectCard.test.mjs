import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
let vite
let cardModule

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
  cardModule = await vite.ssrLoadModule('/src/components/projects/ProjectCard.vue')
})

test.after(async () => {
  await vite?.close()
})

function project(overrides = {}) {
  return {
    id: 'project-1',
    title: '典镇山河',
    status: 'drafting',
    currentChapter: 3,
    lifecycleRevision: 4,
    ...overrides,
  }
}

async function renderCard(props = {}) {
  return renderToString(createSSRApp(cardModule.default, {
    project: project(),
    ...props,
  }))
}

test('card whitespace has no link, click, role, or keyboard affordance', async () => {
  const html = await renderCard()
  const [articleTag] = html.match(/<article\b[^>]*class="[^"]*project-card[^"]*"[^>]*>/) ?? []

  assert.ok(articleTag, html)
  assert.doesNotMatch(articleTag, /\brole=/)
  assert.doesNotMatch(articleTag, /\btabindex=/)
  assert.doesNotMatch(articleTag, /\bonclick=/i)
  assert.doesNotMatch(articleTag, /\bonkeydown=/i)
  assert.doesNotMatch(articleTag, /<a\b/)
})

test('explicit actions emit their own event and card whitespace emits nothing', () => {
  const emitted = []
  const actions = cardModule.createProjectCardActions((event, payload) => {
    emitted.push([event, payload])
  }, project())

  assert.deepEqual(emitted, [])
  actions.open()
  assert.deepEqual(emitted, [['open', project()]])
})

test('explicit actions use the latest project prop after a list row refresh', () => {
  const original = project({ title: '原名' })
  const refreshed = project({ title: '新名', lifecycleRevision: 5 })
  let current = original
  const emitted = []
  const actions = cardModule.createProjectCardActions(
    (event, payload) => emitted.push([event, payload]),
    () => current,
  )

  current = refreshed
  actions.rename()
  assert.deepEqual(emitted, [['rename', refreshed]])
})

test('resumable project renders one primary continue action and secondary open', async () => {
  const html = await renderCard({ resumableChapterNumber: 4 })

  assert.match(html, /class="[^"]*project-action--primary[^"]*"[^>]*>继续写作<\/button>/)
  assert.match(html, /class="[^"]*project-action--secondary[^"]*"[^>]*>打开项目<\/button>/)
})

test('ordinary project renders open as its only primary project action', async () => {
  const html = await renderCard()

  assert.doesNotMatch(html, />继续写作<\/button>/)
  assert.match(html, /class="[^"]*project-action--primary[^"]*"[^>]*>打开项目<\/button>/)
})

test('active More menu contains only rename and archive', async () => {
  const html = await renderCard()
  const menu = html.match(/<details\b[^>]*class="[^"]*project-more[^"]*"[^>]*>([\s\S]*?)<\/details>/)?.[1] ?? ''
  const labels = [...menu.matchAll(/<button\b[^>]*>([^<]+)<\/button>/g)].map(match => match[1])

  assert.match(menu, /<summary\b[^>]*>更多<\/summary>/)
  assert.deepEqual(labels, ['重命名', '归档'])
})

test('archived card renders restore and permanent delete without active actions', async () => {
  const html = await renderCard({ archived: true })

  assert.match(html, />恢复<\/button>/)
  assert.match(html, />永久删除<\/button>/)
  assert.doesNotMatch(html, />打开项目<\/button>/)
  assert.doesNotMatch(html, />继续写作<\/button>/)
  assert.doesNotMatch(html, />更多<\/summary>/)
})
