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

const payload = {
  title: '典镇山河', genre: '东方玄幻', logline: '少年执掌残典，重建一县秩序。',
  targetAudience: '偏爱秩序建设与成长升级的长篇读者', protagonist: '守典人沈砚',
  desire: '保住故乡并查清典籍真相', coreConflict: '每次借典改制都会惊动更高层势力',
  worldPressure: '王朝崩解与诡异复苏同时逼近', openingHook: '县城一夜从舆图上消失',
  differentiation: '以基层制度建设推动玄幻升级', storyPromise: '每卷解决一层秩序危机并揭开大典真相',
  longFormPotential: '县、州、国、天下四级扩张，可支撑二百万字', marketBasis: '公开榜单显示建设流与规则怪谈均有稳定读者',
}

test.before(async () => {
  vite = await createServer({
    configFile: false, root: frontendRoot,
    resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } },
    server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error',
    plugins: [{
      name: 'project-seeds-naive-stub', enforce: 'pre',
      resolveId(id) { if (id === 'naive-ui') return naiveStub },
      load(id) {
        if (id !== naiveStub) return undefined
        return `
          import { defineComponent, h } from 'vue'
          const stub = (name, tag = 'div') => defineComponent({ name, inheritAttrs:false,
            setup(_, { attrs, slots }) { return () => h(tag, attrs, [slots.default?.(), slots.footer?.(), slots.action?.(), slots.extra?.()]) } })
          export const NAlert=stub('NAlert','aside'); export const NButton=stub('NButton','button')
          export const NEmpty=stub('NEmpty'); export const NInput=stub('NInput','input')
          export const NModal=stub('NModal'); export const NResult=stub('NResult')
          export const NSkeleton=stub('NSkeleton'); export const NSpin=stub('NSpin')
          export const NTag=stub('NTag','span'); export const useMessage=()=>({info(){},success(){},warning(){},error(){}})
        `
      },
    }, vuePlugin()],
    ssr: { noExternal: ['naive-ui'] }, optimizeDeps: { noDiscovery: true },
  })
  ProjectSeedsView = (await vite.ssrLoadModule('/src/views/ProjectSeedsView.vue')).default
})

test.after(async () => { await vite?.close() })

async function render({ selected = false } = {}) {
  const originalFetch = globalThis.fetch
  const seed = {
    id: 's1', projectId: 'p1', status: 'candidate', revision: 1,
    revisionId: 'sr1', contentHash: 'a'.repeat(64), payload,
    isSelected: selected, selectionRevision: selected ? 1 : 0,
    capabilities: { canEdit: !selected, canSelect: !selected, canArchive: !selected, canRestore: false, canPermanentlyDelete: false },
    provenance: { kind: 'topic_candidate', snapshots: [], analysis: null, inspirationAttempt: null,
      topicCandidate: { id: 'c1', version: 2, hash: 'b'.repeat(64) }, publicNotes: [], provenanceHash: 'c'.repeat(64) },
  }
  globalThis.fetch = async url => {
    if (String(url).endsWith('/projects/p1/seeds')) return new Response(JSON.stringify([seed]))
    if (String(url).endsWith('/projects/p1/selected-seed')) return new Response(JSON.stringify({
      activeSelection: selected ? { projectId:'p1', selectionRevision:1, seedId:'s1', seedRevisionId:'sr1', seedHash:'a'.repeat(64), selectedAt:1, updatedAt:1, seed } : null,
      seedReady: selected, contractReady: false, reasons: selected ? ['creation_contract_missing'] : ['seed_not_selected'],
    }))
    throw new Error(`unexpected request ${url}`)
  }
  try {
    const app = createSSRApp({ setup: () => () => h(ProjectSeedsView, { projectId: 'p1' }) })
    const shell = await vite.ssrLoadModule('/src/components/layout/productShell.js')
    app.provide(shell.SHELL_PROJECT_CONTEXT, { state: ref('active'), project: ref({ id:'p1', title:'典镇山河', archivedAt:null }), error:ref(null), reload:async()=>null })
    app.use(createPinia())
    return await renderToString(app)
  } finally { globalThis.fetch = originalFetch }
}

test('handed-off seed shows all author fields, exact provenance and pending confirmation', async () => {
  const html = await render()
  for (const value of Object.values(payload)) assert.match(html, new RegExp(value))
  assert.match(html, /来源：选题中心候选《典镇山河》版本 2/)
  assert.match(html, /待确认/)
  assert.match(html, /确认这个种子并进入创作契约/)
  assert.match(html, /<button[^>]*>[\s\S]*?编辑[\s\S]*?<\/button>/)
})

test('selected seed is read-only under the existing one-time confirmation authority', async () => {
  const html = await render({ selected: true })
  assert.match(html, /当前选定/)
  for (const value of Object.values(payload)) assert.match(html, new RegExp(value))
  assert.doesNotMatch(html, /<(?:button|input|textarea|select)\b/)
})

test('project seed workspace contains no duplicate market manager, analysis, or chat', async () => {
  const files = await Promise.all([
    '../../src/views/ProjectSeedsView.vue', '../../src/components/seeds/SeedCard.vue',
    '../../src/components/seeds/SeedEditor.vue', '../../src/stores/seedStore.js',
  ].map(file => readFile(new URL(file, import.meta.url), 'utf8')))
  const source = files.join('\n')
  assert.doesNotMatch(source, /MarketEvidencePanel|useMarketSourceStore|requestInspiration|seed-inspiration|灵感讨论|市场分析|自动刷新|定时调度|api\.topics/)
  assert.match(files[0], /seedStore\.updateSeed/)
  assert.match(files[0], /seedStore\.selectSeed/)
  for (const key of ['targetAudience', 'storyPromise', 'longFormPotential', 'marketBasis']) assert.match(files[2], new RegExp(key))
})
