import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { readFile } from 'node:fs/promises'
import { createSSRApp, h } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveStub = '\0seed-document-naive-stub'
let vite
let SeedDocument

const payload = Object.freeze({
  title: '典镇山河', genre: '东方玄幻', logline: '少年执掌残典，重建一县秩序。',
  protagonist: '守典人沈砚', desire: '保住故乡并查清典籍真相', coreConflict: '每次借典改制都会惊动更高层势力',
  worldPressure: '王朝崩解与诡异复苏同时逼近', openingHook: '县城一夜从舆图上消失',
  differentiation: '以基层制度建设推动玄幻升级', targetAudience: '偏爱秩序建设与成长升级的长篇读者',
  storyPromise: '每卷解决一层秩序危机并揭开大典真相', longFormPotential: '县、州、国、天下四级扩张',
  marketBasis: '建设流与规则怪谈均有稳定读者',
})

test.before(async () => {
  vite = await createServer({
    configFile: false, root: frontendRoot,
    resolve: { alias: { '@': fileURLToPath(new URL('../../src', import.meta.url)) } },
    server: { middlewareMode: true, hmr: false, ws: false }, appType: 'custom', logLevel: 'error',
    plugins: [{
      name: 'seed-document-naive-stub', enforce: 'pre',
      resolveId(id) { return id === 'naive-ui' ? naiveStub : undefined },
      load(id) {
        if (id !== naiveStub) return undefined
        return "import { defineComponent, h } from 'vue'; export const NButton=defineComponent({inheritAttrs:false,setup(_, {attrs,slots}){return()=>h('button',attrs,slots.default?.())}})"
      },
    }, vuePlugin()],
    ssr: { noExternal: ['naive-ui'] }, optimizeDeps: { noDiscovery: true },
  })
  SeedDocument = (await vite.ssrLoadModule('/src/components/seeds/SeedDocument.vue')).default
})

test.after(async () => { await vite?.close() })

function seed(overrides = {}) {
  return {
    id: 's1', revision: 3, revisionId: 'sr3', status: 'candidate', payload,
    capabilities: { canEdit: true, canSelect: false, canArchive: true },
    provenance: { kind: 'topic_candidate', topicCandidate: { id: 'tc1', version: 2 }, publicNotes: ['选题中心移交'] },
    ...overrides,
  }
}

async function render(props = {}) {
  return renderToString(createSSRApp({ setup: () => () => h(SeedDocument, { seed: seed(), ...props }) }))
}

test('candidate document renders the complete 13-field authority', async () => {
  const html = await render()
  const keys = ['title', 'genre', 'logline', 'protagonist', 'desire', 'coreConflict', 'worldPressure', 'openingHook', 'differentiation', 'targetAudience', 'storyPromise', 'longFormPotential', 'marketBasis']
  for (const key of keys) assert.match(html, new RegExp(payload[key]))
  for (const label of ['标题', '题材', '一句话故事', '主角', '核心欲望', '核心冲突', '世界压力', '开篇钩子', '差异化', '目标读者', '故事承诺', '长篇潜力', '市场依据']) assert.match(html, new RegExp(label))
})

test('document groups fields as presentation only and exposes one inline section edit at a time', async () => {
  const html = await render({ activeSection: 'core' })
  for (const heading of ['作品定位', '故事核心', '开篇与压力', '差异与承诺']) assert.match(html, new RegExp(heading))
  assert.match(html, /编辑本区/)
  assert.equal((html.match(/seed-document__section--editing/g) || []).length, 1)
  assert.match(html, /seed-document__section--editing[\s\S]*?故事核心/)
})

test('document uses the shared FoundationDocumentSection for every reading group', async () => {
  const source = await readFile(new URL('../../src/components/seeds/SeedDocument.vue', import.meta.url), 'utf8')
  assert.match(source, /import FoundationDocumentSection/)
  assert.match(source, /<FoundationDocumentSection/)
})

test('stored 9-field revisions use real public empty optional keys only in read mode', async () => {
  const oldPayload = { title: '旧稿', genre: '历史', logline: '旧梗概', protagonist: '旧主角', desire: '旧欲望', coreConflict: '旧冲突', worldPressure: '旧压力', openingHook: '旧钩子', differentiation: '旧差异', targetAudience: '', storyPromise: '', longFormPotential: '', marketBasis: '' }
  const recordedFields = ['title', 'genre', 'logline', 'protagonist', 'desire', 'coreConflict', 'worldPressure', 'openingHook', 'differentiation']
  const html = await render({ seed: seed({ payload: oldPayload, recordedFields, status: 'archived' }), readOnly: true })
  assert.equal((html.match(/该历史版本未记录/g) || []).length, 4)
  assert.match(html, /来源与诊断/)
  assert.doesNotMatch(html, /topicCandidate[^<]*典镇山河/)
  assert.doesNotMatch(html, /编辑本区/)
  const editable = await render({ seed: seed({ payload: oldPayload }) })
  assert.equal((editable.match(/建议补充/g) || []).length, 4)
  assert.doesNotMatch(editable, /该历史版本未记录/)
  const presentEmpty = await render({ seed: seed({ payload: oldPayload, recordedFields: Object.keys(oldPayload), status: 'archived' }), readOnly: true })
  assert.equal((presentEmpty.match(/该历史版本未记录/g) || []).length, 0)
  assert.equal((presentEmpty.match(/建议补充/g) || []).length, 4)
})

test('source diagnosis maps every supported provenance kind without inserting it into payload', async () => {
  const cases = [
    ['manual', { kind: 'manual', snapshots: [], analysis: null, inspirationAttempt: null, publicNotes: ['作者备注'] }, '作者手动创建'],
    ['market_snapshot', { kind: 'market_snapshot', snapshots: [{ id: 'snap-1', sourceURL: 'https://example.test/a' }], analysis: null, inspirationAttempt: null, publicNotes: ['采样依据'] }, '市场快照'],
    ['market_analysis', { kind: 'market_analysis', snapshots: [{ id: 'snap-1', sourceURL: 'https://example.test/a' }], analysis: { id: 'analysis-1' }, inspirationAttempt: null, publicNotes: ['分析依据'] }, '市场分析'],
    ['ai_chat', { kind: 'ai_chat', snapshots: [{ id: 'snap-1', sourceURL: 'https://example.test/a' }], analysis: { id: 'analysis-1' }, inspirationAttempt: { id: 'chat-1' }, publicNotes: ['对话依据'] }, 'AI 灵感对话'],
    ['topic_candidate', { kind: 'topic_candidate', snapshots: [], analysis: null, inspirationAttempt: null, topicCandidate: { id: 'tc-1', version: 7 }, publicNotes: ['移交依据'] }, '选题中心候选 · 版本 7'],
    ['unknown', { kind: 'future_source', publicNotes: ['未知依据'] }, '未识别来源（类型：future_source）'],
  ]
  for (const [, provenance, expected] of cases) {
    const html = await render({ seed: seed({ provenance }), readOnly: true })
    assert.match(html, new RegExp(expected))
    assert.match(html, new RegExp(provenance.publicNotes[0]))
  }
})
