import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  classifyPlotThread,
  defaultVisiblePlotThreads,
  plotThreadNodeSummary,
  shouldResolvePlotThread
} from '../frontend/src/utils/plotThreadClassifier.js'

const systemTitles = ['主线推进', '世界观', '身体状态', '时间线', '时间紧迫线', '关键道具清单', '线索判断', '章节锚点', '硬状态账本', '关键地点线', '势力斗争线', '追捕线', '感情关系线']
for (const title of systemTitles) {
  assert.equal(classifyPlotThread({ title }).threadClass, 'system_tag', `${title} should be classified as system_tag`)
}

for (const title of ['星账代价线', '父亲线索线', '第三密栈行动', '庚字号门后的真相', '天池裂隙', '徐正清身份疑点', '小九身世线', '反派阴谋线', '主角身世线', '关键道具线']) {
  assert.equal(classifyPlotThread({ title }).threadClass, 'real_thread', `${title} should be classified as real_thread`)
}

assert.equal(
  classifyPlotThread({
    title: '父亲密信提及星债会',
    status: 'candidate',
    notes: '候选来源：第 1 卷分卷规划；尚未由 Canon facts 证明已埋设。'
  }).threadClass,
  'future_candidate',
  'volume foreshadowingPlan entries should be future_candidate'
)

assert.equal(
  shouldResolvePlotThread({
    title: '主角身世线',
    content: '宋怀安确认陆长庚曾在第三密栈留下账册。',
    notes: '最近推进：第 20 章，拿到新线索。'
  }),
  false,
  'broad long lines should not auto-resolve'
)

assert.equal(
  shouldResolvePlotThread({
    title: '庚字号门后的真相',
    content: '庚字号门后的真相揭开：铁箱中账簿证明徐正清长期超额抽取灵脉。',
    notes: '完成回收：第 20 章。'
  }),
  true,
  'specific mystery with explicit reveal wording should resolve'
)

assert.equal(
  shouldResolvePlotThread({
    title: '庚字号门后的真相',
    content: '陆沉舟进入庚字号门后，获得账簿和玉佩。',
    notes: '最近推进：第 20 章，进入下一地点。'
  }),
  false,
  'obtaining items or entering a location is progress, not resolution'
)

const defaultVisible = defaultVisiblePlotThreads([
  { title: '主线推进', status: 'developing' },
  { title: '世界观', status: 'planted' },
  { title: '父亲密信提及星债会', status: 'candidate', notes: '候选来源：第 1 卷分卷规划' },
  { title: '星账代价线', status: 'developing', plantedChapter: 9, notes: '首次出现：第 9 章；最近推进：第 19 章，左臂疼痛加剧。' },
  { title: '第三密栈行动', status: 'planted', plantedChapter: 18, notes: '首次出现：第 18 章；最近推进：第 18 章，小九提出接应。' }
])

assert.deepEqual(
  defaultVisible.map(thread => thread.title),
  ['星账代价线', '第三密栈行动'],
  'default view should hide system tags and future candidates'
)

assert.equal(
  plotThreadNodeSummary({
    plantedChapter: 3,
    latestChapter: 9,
    resolvedChapter: 12
  }),
  '第 3 章埋设 -> 第 9 章推进 -> 第 12 章回收',
  'thread card should use compact node summary, not all chapter dots'
)

const board = readFileSync('frontend/src/components/bible/PlotThreadBoard.vue', 'utf8')
assert.match(board, /const selectedFilter = ref\('all'\)/, 'board should default to the normal all-real view')
assert.match(board, /thread\.threadClass !== 'real_thread'/, 'default board filters should hide system tags and future candidates')
assert.match(board, /未来候选/, 'board should expose future candidates through an explicit filter')
assert.match(board, /系统标签/, 'board should expose system tags through an explicit filter')

console.log('plot thread noise filter contract passed')
