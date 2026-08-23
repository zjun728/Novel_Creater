import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'


const source = path => readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')


test('Writer embeds one compact author-controlled finalization panel', async () => {
  const [view, panel] = await Promise.all([
    source('views/ChapterWriterView.vue'),
    source('components/writer/FinalizationPanel.vue'),
  ])

  assert.match(view, /components\/writer\/FinalizationPanel\.vue/)
  assert.match(view, /createFinalizationController/)
  assert.match(view, /<finalization-panel/)
  assert.match(view, /:planning-content="planningContent"/)
  assert.match(view, /finalization\.reset\(\)/)
  assert.match(view, /finalization\.load\(\)/)
  assert.match(view, /finalization\.dispose\(\)/)
  assert.match(view, /editorReadonly[\s\S]*finalization\.finalized\.value/)

  for (const label of [
    '审查并定稿', '确定性阻断', '质量建议', 'Canon 事实',
    '故事进度', '未来规划调整', '保存修正', '确认以上变更', '定稿本章',
    '放弃审查并返回修改',
  ]) assert.match(panel, new RegExp(label))
  assert.match(panel, /controller\.prepareCandidate/)
  assert.match(panel, /controller\.correctChangeSet/)
  assert.match(panel, /controller\.confirmChangeSet/)
  assert.match(panel, /controller\.commitChapter/)
  assert.match(panel, /controller\.cancelReview/)
  assert.match(panel, /planningContent/)
  assert.match(panel, /targetLabel\(item\)/)
  assert.doesNotMatch(panel, /item\.targetType\s*}}\s*·\s*{{\s*item\.targetId/)
  assert.match(panel, /previousCandidateIds/)
  assert.match(panel, /review\?\.status === 'failed'/)
  assert.match(panel, /审查未完成，正文和候选稿未受影响/)
  assert.equal(
    panel.match(/v-if="controller\.primaryAction\.value === 'confirm'"/g)?.length,
    2,
  )
  assert.doesNotMatch(
    panel,
    /v-else-if="controller\.primaryAction\.value === 'confirm'"/,
  )
  assert.doesNotMatch(panel, /通过分数|及格分|自动修复|自动定稿|partial approval/i)
  assert.doesNotMatch(panel, /<textarea[^>]*json|page\.request|page\.route|fetch\(|axios|page\.evaluate/i)
})


test('the panel renders evidence without exposing full candidate prose', async () => {
  const panel = await source('components/writer/FinalizationPanel.vue')

  assert.match(panel, /startScalar/)
  assert.match(panel, /endScalar/)
  assert.doesNotMatch(panel, /candidate\.content|workingDraft\.content|rawProvider|prompt|apiKey|dsn/i)
})
