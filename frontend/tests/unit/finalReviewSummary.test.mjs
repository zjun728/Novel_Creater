import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createSSRApp } from 'vue'
import { renderToString } from '@vue/server-renderer'
import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

let vite; let Summary
test.before(async () => {
  vite = await createServer({ configFile: false, root: fileURLToPath(new URL('../..', import.meta.url)), plugins: [vuePlugin()], server: { middlewareMode: true, hmr: false, ws: false }, optimizeDeps: { noDiscovery: true } })
  Summary = (await vite.ssrLoadModule('/src/components/manuscript/FinalReviewSummary.vue')).default
})
test.after(async () => { await vite?.close() })
const evidence = { startScalar: 0, endScalar: 4, excerptHash: 'a'.repeat(64), confidence: 1, rationale: '本章原文依据。', excerpt: '船已靠岸', verified: true }
const review = () => ({ projectId: 'p', chapterNumber: 2, finalizationId: 'final-2', canonRevision: 2, summary: '码头会合。', qualityReport: { status: 'completed', contentHash: 'a'.repeat(64), deterministicBlocks: [], findings: [] }, canonEvents: [], storyProgressEvents: [], planningPatches: [] })
const render = data => renderToString(createSSRApp(Summary, { state: { status: 'ready', data, message: '' } }))

test('historical review renders distinct explicit empty sections and source chapter', async () => {
  const html = await render(review())
  for (const text of ['来源：第 2 章定稿', '历史状态反映本章当时的变化', '本章没有记录质量改进建议', '本章没有新增已确认事实', '本章没有实体状态变化', '本章没有线索或伏笔变化', '本章没有人物弧光变化', '本章没有确认故事进度变化', '本章没有调整未来规划']) assert.ok(html.includes(text), `missing ${text}`)
  assert.doesNotMatch(html, /<textarea|contenteditable|提交定稿|重新生成/)
})

test('review renders factual, state, progress and future planning evidence without equating them', async () => {
  const data = review()
  data.qualityReport.findings.push({ id: 'f', dimension: 'dialogue_credibility', reason: '对白缺少回应。', suggestedAction: '补足人物回应。', evidence })
  data.canonEvents.push({ id: 'event', entityId: 'person', entityName: '阿宁', factKind: 'dynamic_event', fieldPath: 'status', assertionOperator: 'not_equals', value: '困在船上', evidence })
  data.canonEvents.push({ id: 'claim', entityId: 'person', entityName: '阿宁', factKind: 'claim', fieldPath: 'claim', assertionOperator: 'equals', value: '船上有人跟踪', evidence })
  data.storyProgressEvents.push({ id: 'progress', targetType: 'stage', targetId: 'stage-uuid', targetTitle: '码头会合', status: 'completed', evidence })
  data.planningPatches.push({ id: 'patch', targetType: 'stage', targetId: 'future-uuid', targetTitle: '渡口追踪', fieldPath: 'purpose', replacement: '追查来信来源', evidence })
  const html = await render(data)
  for (const text of ['对白可信度', '补足人物回应', '已确认不成立', '困在船上', '已记录说法', '不作为已证实的客观事实', '阶段 · 码头会合', '已完成', '阶段目标', '追查来信来源', '不表示对应情节已经发生', '船已靠岸', '查看第 2 章正文依据']) assert.ok(html.includes(text), `missing ${text}`)
  assert.doesNotMatch(html, /stage-uuid|future-uuid|&lt;|"startScalar"|dialogue_credibility/)
})

test('incomplete quality review is never described as an empty successful conclusion', async () => {
  const data = review(); data.qualityReport.status = 'quality_not_completed'
  const html = await render(data)
  assert.match(html, /质量审查未完成，暂无质量结论/)
  assert.doesNotMatch(html, /没有记录质量改进建议/)
})

test('author content and verified excerpt are escaped rather than rendered as HTML', async () => {
  const data = review()
  data.summary = '<script>alert(1)</script>'
  data.qualityReport.findings.push({ id: 'f', dimension: 'pacing', reason: '<img onerror=alert(1)>', suggestedAction: '调整节奏', evidence: { ...evidence, excerpt: '<b>原文</b>' } })
  const html = await render(data)
  assert.match(html, /&lt;script&gt;/)
  assert.match(html, /&lt;b&gt;原文&lt;\/b&gt;/)
  assert.doesNotMatch(html, /<script>|<img onerror|<b>原文/)
})
