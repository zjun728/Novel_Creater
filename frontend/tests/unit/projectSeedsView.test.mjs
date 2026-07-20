import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import test from 'node:test'

import { createPinia } from 'pinia'
import { createSSRApp, h, ref } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveStub = '\0project-seeds-naive-stub'
let vite
let ProjectSeedsView

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } },
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [
      {
        name: 'project-seeds-naive-stub',
        enforce: 'pre',
        resolveId(id) {
          if (id === 'naive-ui') return naiveStub
        },
        load(id) {
          if (id !== naiveStub) return undefined
          return `
            import { defineComponent, h } from 'vue'
            const stub = (name, tag = 'div') => defineComponent({
              name, inheritAttrs: false,
              setup(_, { attrs, slots }) {
                return () => h(tag, attrs, [
                  slots.trigger?.(), slots.default?.(), slots.footer?.(),
                  slots.action?.(), slots.empty?.(),
                ])
              },
            })
            export const NAlert = stub('NAlert', 'aside')
            export const NButton = stub('NButton', 'button')
            export const NDialog = stub('NDialog')
            export const NEmpty = stub('NEmpty')
            export const NInput = stub('NInput', 'input')
            export const NInputNumber = stub('NInputNumber', 'input')
            export const NModal = stub('NModal')
            export const NResult = stub('NResult')
            export const NSkeleton = stub('NSkeleton')
            export const NSpin = stub('NSpin')
            export const NTag = stub('NTag', 'span')
            export const useDialog = () => ({ warning: () => ({}) })
            export const useMessage = () => ({ info(){},success(){},warning(){},error(){} })
          `
        },
      },
      vuePlugin(),
    ],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  ProjectSeedsView = (await vite.ssrLoadModule('/src/views/ProjectSeedsView.vue')).default
})

test.after(async () => {
  await vite?.close()
})

async function render({ archived = false, marketState = null } = {}) {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async url => {
    const path = String(url)
    if (path.endsWith('/market-sources')) {
      return new Response(JSON.stringify(marketState?.sources || []))
    }
    const snapshotMatch = path.match(/\/market-sources\/([^/]+)\/snapshots$/)
    if (snapshotMatch) {
      return new Response(JSON.stringify(
        marketState?.snapshotHistory?.[decodeURIComponent(snapshotMatch[1])] || [],
      ))
    }
    if (path.endsWith('/projects/p1/seeds')) return new Response('[]')
    if (path.endsWith('/projects/p1/selected-seed')) {
      return new Response(JSON.stringify({
        activeSelection: null,
        seedReady: false,
        contractReady: false,
        reasons: ['seed_not_selected'],
      }))
    }
    throw new Error(`unexpected request ${url}`)
  }
  try {
    const app = createSSRApp({
      setup() {
        return () => h(ProjectSeedsView, { projectId: 'p1' })
      },
    })
    app.provide(Symbol.for('unused'), null)
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    app.provide(shell.SHELL_PROJECT_CONTEXT, {
      state: ref(archived ? 'archived' : 'active'),
      project: ref({
        id: 'p1',
        title: '典镇山河',
        archivedAt: archived ? 123 : null,
      }),
      error: ref(null),
      reload: async () => null,
    })
    const pinia = createPinia()
    if (marketState) {
      const marketModule = await vite.ssrLoadModule('/src/stores/marketSourceStore.js')
      marketModule.useMarketSourceStore(pinia).$patch(marketState)
    }
    app.use(pinia)
    return await renderToString(app)
  } finally {
    globalThis.fetch = originalFetch
  }
}

test('one Project Seeds workspace renders Evidence, Inspiration and Saved Seeds without a market sub-product', async () => {
  const html = await render()
  assert.match(html, /市场证据/)
  assert.match(html, /灵感讨论/)
  assert.match(html, /已存种子/)
  assert.match(html, /手动导入快照/)
  assert.match(html, /保存为种子/)
  assert.match(html, /选定一个创作种子/)
  assert.doesNotMatch(html, /Provider|模型选择|raw JSON|市场项目/)
})

test('archived project keeps evidence and candidates visible but disables every authoring command', async () => {
  const html = await render({ archived: true })
  assert.match(html, /已归档 · 只读/)
  assert.match(html, /恢复项目后才能继续刷新证据、讨论灵感或修改种子/)
  assert.match(html, /<button[^>]*disabled[\s\S]*?新建种子/)
  assert.doesNotMatch(html, /永久删除种子/)
})

test('retired direct-model market and seed workbenches are physically absent', async () => {
  const retired = [
    'src/stores/marketStore.js',
    'src/components/market/MarketRadar.vue',
    'src/components/market/MarketCard.vue',
    'src/components/market/AIChatPanel.vue',
    'src/prompts/market.js',
    'src/prompts/marketDirections.js',
    'src/prompts/seed.js',
    'src/components/seed/SeedWorkbench.vue',
    'src/components/seed/StyleTrialPanel.vue',
  ]

  for (const relativePath of retired) {
    await assert.rejects(
      readFile(fileURLToPath(new URL(`../../${relativePath}`, import.meta.url))),
      error => error?.code === 'ENOENT',
      `${relativePath} must not remain as a callable legacy chain`,
    )
  }
})

test('project seed workspace reaches only backend product APIs and has one danger dialog', async () => {
  const files = await Promise.all([
    'src/views/ProjectSeedsView.vue',
    'src/components/seeds/MarketEvidencePanel.vue',
    'src/stores/marketSourceStore.js',
    'src/stores/seedStore.js',
  ].map(relativePath => readFile(
    fileURLToPath(new URL(`../../${relativePath}`, import.meta.url)),
    'utf8',
  )))
  const source = files.join('\n')

  assert.doesNotMatch(source, /useProviderStore|api\/ai|chat-completions|providerId|modelId/)
  assert.equal(
    (files[0].match(/class="permanent-delete-dialog"/g) || []).length,
    1,
  )
  assert.match(files[0], /seed-operation-veil/)
  assert.doesNotMatch(files[0], /AppOperationOverlay|useOperationStore/)
})

test('project changes clear transient workspace state and schedule conflicts install the reloaded interval', async () => {
  const view = await readFile(
    fileURLToPath(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url)),
    'utf8',
  )
  const evidence = await readFile(
    fileURLToPath(new URL('../../src/components/seeds/MarketEvidencePanel.vue', import.meta.url)),
    'utf8',
  )

  assert.match(view, /function resetProjectWorkspace\(/)
  assert.match(view, /transcript\.value = \[\]/)
  assert.match(view, /proposal\.value = null/)
  assert.match(view, /editorOpen\.value = false/)
  assert.match(view, /deleteTarget\.value = null/)
  assert.match(view, /marketStore\.activateProject\(projectId\)/)
  assert.match(evidence, /market\.scheduleConflictSourceId === source\.id/)
  assert.match(
    evidence,
    /intervalDrafts\[source\.id\]\s*=\s*Number\(source\.scheduleIntervalMinutes/,
  )
})

test('frozen analysis shows its exact snapshot manifest and per-statement citations', async () => {
  const evidence = await readFile(
    fileURLToPath(new URL('../../src/components/seeds/MarketEvidencePanel.vue', import.meta.url)),
    'utf8',
  )

  assert.match(evidence, /本次分析固定使用每个来源的最新快照/)
  assert.match(evidence, /class="snapshot-evidence-list"/)
  assert.match(evidence, /market\.loadSnapshotDetail\(/)
  assert.match(evidence, /statement\.snapshotIds/)
  assert.match(evidence, /class="analysis-citations"/)
  assert.match(evidence, /sourceCoverage/)
  assert.match(evidence, /hasUnresolvedAnalysisCitations/)
  assert.match(evidence, /部分结论的引用快照当前无法核验，已隐藏/)
  assert.match(evidence, /map\(snapshotRecord\)\.filter\(Boolean\)/)
  assert.match(evidence, /shortSnapshotId\(snapshot\.id\)/)
})

test('SSR renders only analysis statements whose frozen snapshot citations can be verified', async () => {
  const snapshotId = 'snapshot-abcdef-1234'
  const html = await render({
    marketState: {
      sources: [{
        id: 'qidian',
        platform: '起点',
        rankingName: '畅销榜',
        displayName: '起点畅销榜',
        policyStatus: 'verified_public',
        automaticRefreshAllowed: true,
        scheduleRevision: 1,
        scheduleEnabled: false,
        scheduleIntervalMinutes: 360,
        lastSucceededAt: 1_784_477_400_000,
        lastSnapshotId: snapshotId,
        publicErrorCode: null,
      }],
      snapshotHistory: {
        qidian: [{
          id: snapshotId,
          sourceId: 'qidian',
          capturedAt: 1_784_477_400_000,
          entryCount: 20,
        }],
      },
      analysisProjectId: 'p1',
      analysisState: {
        status: 'available',
        publicErrorCode: null,
        result: {
          id: 'analysis-1',
          status: 'succeeded',
          analysis: {
            sourceCoverage: {
              summary: '使用一份冻结榜单快照。',
              snapshotIds: [snapshotId],
            },
            currentHeat: [{
              text: '玄幻题材当前仍有稳定读者。',
              inference: false,
              snapshotIds: [snapshotId],
            }],
            growthDirections: [{
              text: '这条没有可核验引用，不能展示。',
              inference: true,
              snapshotIds: ['missing-snapshot'],
            }],
            crowding: [],
            opportunities: [],
            uncertainties: [],
          },
        },
      },
    },
  })

  assert.match(html, /本次分析证据清单/)
  assert.match(html, /起点畅销榜/)
  assert.match(html, /snapshot…1234/)
  assert.match(html, /玄幻题材当前仍有稳定读者/)
  assert.match(html, /部分结论的引用快照当前无法核验，已隐藏/)
  assert.doesNotMatch(html, /这条没有可核验引用，不能展示/)
})

test('every seed write callback is workspace-fenced and a new inspiration invalidates the old proposal', async () => {
  const view = await readFile(
    fileURLToPath(new URL('../../src/views/ProjectSeedsView.vue', import.meta.url)),
    'utf8',
  )

  for (const functionName of [
    'saveEditor',
    'selectSeed',
    'changeArchive',
    'confirmPermanentDelete',
  ]) {
    const start = view.indexOf(`async function ${functionName}(`)
    const next = view.indexOf('\nasync function ', start + 1)
    const body = view.slice(start, next < 0 ? view.length : next)
    assert.match(body, /const projectId = props\.projectId/)
    assert.match(body, /const generation = workspaceGeneration/)
    assert.match(body, /isCurrentWorkspace\(projectId, generation\)/)
  }
  assert.match(
    view,
    /async function sendInspiration\(\)[\s\S]*?proposal\.value = null[\s\S]*?requestInspiration/,
  )
  assert.match(view, /seedStore\.inspirationBusy \|\| !proposal/)
})

test('core Chinese evidence and seed metadata keep a readable minimum size', async () => {
  const [view, evidence, card, editor] = await Promise.all([
    'src/views/ProjectSeedsView.vue',
    'src/components/seeds/MarketEvidencePanel.vue',
    'src/components/seeds/SeedCard.vue',
    'src/components/seeds/SeedEditor.vue',
  ].map(relativePath => readFile(
    fileURLToPath(new URL(`../../${relativePath}`, import.meta.url)),
    'utf8',
  )))

  assert.match(view, /\.transcript article p[^}]*font-size:\s*14px/s)
  assert.match(view, /\.seed-operation-veil p[^}]*font-size:\s*12px/s)
  assert.match(evidence, /\.source-sheet dt[^}]*font-size:\s*12px/s)
  assert.match(evidence, /\.analysis-grid ul[^}]*font-size:\s*13px/s)
  assert.match(card, /dt[^}]*font-size:\s*12px/s)
  assert.match(card, /\.seed-record__provenance[^}]*font-size:\s*12px/s)
  assert.match(editor, /footer p[^}]*font-size:\s*12px/s)
})
