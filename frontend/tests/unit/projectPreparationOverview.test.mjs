import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { createPinia, setActivePinia } from 'pinia'
import { createSSRApp, ref, shallowRef } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

import { useProjectStore } from '../../src/stores/projectStore.js'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveUiStubId = '\0project-overview-naive-ui-stub'
const naiveUiStubPlugin = {
  name: 'project-overview-naive-ui-stub',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveUiStubId
  },
  load(id) {
    if (id !== naiveUiStubId) return undefined
    return `
      import { defineComponent, h } from 'vue'
      const stub = (name, tag = 'div') => defineComponent({
        name,
        inheritAttrs: false,
        setup(_, { attrs, slots }) {
          return () => h(tag, attrs, [slots.default?.(), slots.footer?.()])
        },
      })
      export const NButton = stub('NButton', 'button')
      export const NResult = stub('NResult')
      export const NSkeleton = stub('NSkeleton')
    `
  },
}

function overview(overrides = {}) {
  const value = {
    project: {
      id: 'project / 一',
      title: '典镇山河',
      genre: '东方玄幻',
      logline: '以山河典册镇压乱世妖祟。',
      targetWords: 2_400_000,
      targetChapters: 800,
      updatedAtMs: 1_777_777_777_000,
      lifecycle: 'active',
    },
    progress: {
      authoritativeChapterNumber: 4,
      currentVolume: { id: 'volume-1', order: 1, title: '山河初醒' },
      latestFinalChapter: { number: 3, title: '城隍夜巡', finalizedAtMs: 1_777_777_770_000 },
      finalizedChapterCount: 3,
      finalizedScalarCount: 18_600,
    },
    modules: {
      seed: 'current',
      contract: 'current',
      bible: 'needs_review',
      planning: 'current',
      outline: 'pending_confirmation',
      writing: 'working_draft',
    },
    writerCore: { canonRevision: 3, projectionRevision: 3, synchronized: true },
    continuity: { availability: 'pending_module', pendingCount: null },
    recentAchievements: [
      { kind: 'final_chapter', label: '第 3 章已定稿', occurredAtMs: 1_777_777_770_000 },
      { kind: 'planning', label: '故事规划已确认', occurredAtMs: 1_777_777_760_000 },
      { kind: 'bible', label: '创作圣经已确认', occurredAtMs: 1_777_777_750_000 },
      { kind: 'contract', label: '创作契约已确认', occurredAtMs: 1_777_777_740_000 },
      { kind: 'seed', label: '创作种子已确认', occurredAtMs: 1_777_777_730_000 },
    ],
  }
  return Object.assign(value, overrides)
}

let vite
let Overview
let ShellProjectContext

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin(), naiveUiStubPlugin],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  Overview = (await vite.ssrLoadModule('/src/views/ProjectOverviewView.vue')).default
  ShellProjectContext = (
    await vite.ssrLoadModule('/src/components/layout/productShell.js')
  ).SHELL_PROJECT_CONTEXT
})

test.after(async () => {
  await vite?.close()
})

function projectRecord(projectId, archived = false) {
  return {
    id: projectId,
    title: projectId === 'project / 一' ? '典镇山河' : '另一部作品',
    archivedAt: archived ? 1_777_777_777_000 : null,
    lifecycleRevision: archived ? 4 : 3,
  }
}

async function renderOverview({
  payload = overview(),
  routeProjectId = 'project / 一',
  shellState = 'active',
  overviewState = 'ready',
  overviewError = null,
} = {}) {
  const originalFetch = global.fetch
  global.fetch = async url => {
    throw new Error(`unexpected request during cached overview render: ${url}`)
  }
  try {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useProjectStore()
    if (overviewState !== 'idle') {
      store.overviewProjectId = payload?.project?.id || routeProjectId
      store.currentOverview = overviewState === 'ready' ? payload : null
      store.overviewStatus = overviewState
      store.overviewError = overviewError
    }
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/projects', component: { template: '<div />' } },
        { path: '/projects/:projectId/overview', component: Overview },
        { path: '/projects/:projectId/seeds', component: { template: '<div />' } },
        { path: '/projects/:projectId/contract', component: { template: '<div />' } },
        { path: '/projects/:projectId/bible', component: { template: '<div />' } },
        { path: '/projects/:projectId/planning/volumes', component: { template: '<div />' } },
        { path: '/projects/:projectId/planning/story-blocks', component: { template: '<div />' } },
        { path: '/projects/:projectId/manuscript', component: { template: '<div />' } },
      ],
    })
    await router.push(`/projects/${encodeURIComponent(routeProjectId)}/overview`)
    await router.isReady()
    const app = createSSRApp(Overview)
    app.use(pinia)
    app.use(router)
    app.provide(ShellProjectContext, {
      state: ref(shellState),
      project: shallowRef(shellState === 'missing' ? null : projectRecord(
        routeProjectId,
        payload?.project?.lifecycle === 'archived',
      )),
      error: shallowRef(shellState === 'error' ? new Error('shell unavailable') : null),
      reload: async () => null,
    })
    return renderToString(app)
  } finally {
    global.fetch = originalFetch
  }
}

test('overview presents project identity, long-form progress, authority and latest final above the fold', async () => {
  const html = await renderOverview()
  assert.match(html, /典镇山河/)
  assert.match(html, /东方玄幻/)
  assert.match(html, /以山河典册镇压乱世妖祟/)
  assert.match(html, /2,400,000 字/)
  assert.match(html, /18,600 字/)
  assert.match(html, /第 1 卷 · 山河初醒/)
  assert.match(html, /第 4 章/)
  assert.match(html, /第 3 章 · 城隍夜巡/)
})

test('overview renders six manual module links with Chinese authority labels and no next-step authority', async () => {
  const html = await renderOverview()
  for (const label of ['创作种子', '创作契约', '创作圣经', '故事规划', '本章小纲', '正文写作']) {
    assert.match(html, new RegExp(label))
  }
  for (const status of ['当前正式版', '需要检查', '等待确认', '工作草稿']) {
    assert.match(html, new RegExp(status))
  }
  assert.match(html, /href="\/projects\/project%20%2F%20%E4%B8%80\/seeds"/)
  assert.match(html, /href="\/projects\/project%20%2F%20%E4%B8%80\/manuscript"/)
  assert.doesNotMatch(html, /下一步|nextAction|overview-next-action/)
})

test('overview explains Writer Core and continuity in author language and limits achievements to five', async () => {
  const html = await renderOverview()
  assert.match(html, /创作核心已同步至第 3 版/)
  assert.match(html, /连续性问题将在连续性模块启用后显示/)
  assert.equal((html.match(/class="overview-achievement"/g) || []).length, 5)
  assert.doesNotMatch(html, /volume-1|project \/ 一|contentHash|rawJson/)
})

test('overview explicitly renders archived, missing, loading, retryable error and stale-route states', async () => {
  const archivedPayload = overview({
    project: { ...overview().project, lifecycle: 'archived' },
  })
  assert.match(await renderOverview({ payload: archivedPayload, shellState: 'archived' }), /已归档 · 只读/)
  assert.match(await renderOverview({ shellState: 'missing', overviewState: 'idle' }), /项目不存在或已被删除/)
  assert.match(await renderOverview({ overviewState: 'loading' }), /正在读取当前项目概览/)
  const failed = await renderOverview({
    overviewState: 'error',
    overviewError: new Error('internal provider identity'),
  })
  assert.match(failed, /项目概览暂时无法加载/)
  assert.equal((failed.match(/>重试</g) || []).length, 1)
  assert.doesNotMatch(failed, /internal provider identity/)
  const stale = await renderOverview({ routeProjectId: 'project-B' })
  assert.match(stale, /正在读取当前项目概览/)
  assert.doesNotMatch(stale, /典镇山河|以山河典册镇压乱世妖祟/)
})

test('overview source uses only the overview read model and omits delivery, backup and next-action coupling', async () => {
  const source = await readFile(
    new URL('../../src/views/ProjectOverviewView.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /loadOverview/)
  assert.match(source, /ProjectPageHeader/)
  assert.doesNotMatch(source, /loadPreparation|currentPreparation|mapProjectNextAction/)
  assert.doesNotMatch(source, /NovelDownloadPanel|ProjectBackupPanel|ManuscriptSummaryLink/)
  assert.doesNotMatch(source, /nextAction|targetPath|rawJson|contentHash/)
})
