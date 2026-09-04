import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

const root = path.resolve(import.meta.dirname, '../..')
const files = [
  'src/views/TopicCenterView.vue',
  'src/components/topics/TopicCenterHeader.vue',
  'src/components/topics/MarketDiscoveryPanel.vue',
  'src/components/topics/MarketSnapshotWorks.vue',
  'src/components/topics/TopicDiscussionPanel.vue',
  'src/components/topics/TopicDirectionsPanel.vue',
  'src/components/topics/TopicCandidatesPanel.vue',
  'src/components/topics/CreateProjectFromCandidateDialog.vue',
]

async function sources() {
  await Promise.all(files.map(file => access(path.join(root, file))))
  return Promise.all(files.map(file => readFile(path.join(root, file), 'utf8')))
}

test('topic center has four truthful destinations and an information-first page identity', async () => {
  const [view, header] = await sources()
  assert.match(view, /MARKET DISCOVERY|IDEA CONVERSATION|DIRECTION LIBRARY|CANDIDATE LIBRARY/)
  assert.match(header, /市场热门/)
  assert.match(header, /AI 讨论/)
  assert.match(header, /选题方向/)
  assert.match(header, /候选种子库/)
  assert.match(header, /router-link/)
  assert.doesNotMatch(`${view}\n${header}`, /继续下一步/)
})

test('market and discussion surfaces preserve explicit evidence and explicit saves', async () => {
  const [, , market, works, discussion] = await sources()
  const presentation = await readFile(path.join(root, 'src/application/market/marketSourcePresentation.js'), 'utf8')
  assert.match(presentation, /网络刷新/)
  assert.match(presentation, /人工导入/)
  assert.match(market, /上次成功/)
  assert.match(market, /最新刷新失败/)
  assert.match(market, /查看榜单作品/)
  assert.match(market, /data-market-source-key/)
  assert.match(market, /data-market-source-status/)
  assert.match(market, /`刷新\$\{source\.displayName\}`/)
  assert.match(market, /刷新\{\{ source\.displayName \}\}/)
  assert.match(market, /source\.canRefresh/)
  assert.match(market, /source\.canManualImport/)
  assert.doesNotMatch(market, /source\.policyStatus/)
  assert.match(market, /`导入\$\{source\.displayName\}`/)
  assert.match(market, /导入\{\{ source\.displayName \}\}/)
  assert.match(market, /`查看榜单作品：\$\{source\.displayName\}`/)
  assert.match(market, /marketFailureCopy\(source, market\.snapshotHistory\[source\.id\] \|\| \[\]\)/)
  assert.match(market, /marketCapabilityPresentation\(source\)/)
  assert.doesNotMatch(market, /自动刷新|定时|每隔/)
  assert.match(works, /MarketSnapshotWorks|榜单作品/)
  assert.match(discussion, /从空白想法开始/)
  assert.match(discussion, /移除证据/)
  assert.match(discussion, /保存为方向/)
  assert.match(discussion, /保存为候选种子/)
  assert.match(discussion, /@keydown\.enter\.exact\.prevent/)
  assert.match(discussion, /Shift \+ Enter 换行/)
  assert.match(discussion, /request\.basis\?\.evidence/)
  assert.doesNotMatch(discussion, /evidence:\s*evidencePayload\(\),\s*\n\s*idempotencyKey:\s*commandKey\(\)/)
  assert.doesNotMatch(discussion, /已自动保存|Provider|模型选择|raw JSON/)
})

test('direction and candidate detail show author fields, version history, and guarded handoff', async () => {
  const [, , , , , directions, candidates, dialog] = await sources()
  for (const label of ['题材机会', '目标读者', '读者承诺', '差异化', '长篇发展空间', '风险', '证据摘要']) {
    assert.match(directions, new RegExp(label))
  }
  for (const label of ['暂定书名', '一句话创意', '主角', '核心欲望', '核心冲突', '世界压力', '开篇钩子', '故事承诺', '市场依据']) {
    assert.match(candidates, new RegExp(label))
  }
  assert.match(candidates, /版本历史/)
  assert.match(candidates, /继续讨论/)
  assert.match(candidates, /归档/)
  assert.match(candidates, /创建项目/)
  assert.match(dialog, /指定版本/)
  assert.match(dialog, /项目种子仍为“待确认”/)
  assert.match(dialog, /role="dialog"/)
  assert.match(dialog, /handoffAttempt/)
  assert.match(dialog, /fingerprint/)
  assert.match(dialog, /handoffKeyFor\(title\)/)
  assert.doesNotMatch(dialog, /idempotencyKey:\s*commandKey\(\)/)
})

test('topic panels own independent scrolling and responsive layout without page overflow', async () => {
  const text = (await sources()).join('\n')
  assert.match(text, /overflow-y:\s*auto/)
  assert.match(text, /min-width:\s*0/)
  assert.match(text, /@media\s*\(max-width:\s*720px\)/)
  assert.match(text, /aria-live="(?:polite|assertive)"/)
  assert.match(text, /aria-label=/)
  assert.doesNotMatch(text, /<main\b/)
})

test('narrow market page leaves vertical scrolling to the page alone', async () => {
  const [, , market, works, discussion, , candidates] = await sources()
  assert.match(market, /@media\(max-width:720px\)[\s\S]*\.source-list\{max-height:none;overflow-y:visible\}/)
  assert.match(works, /@media\(max-width:720px\)/)
  assert.match(discussion, /@media\(max-width:720px\)[\s\S]*\.discussion-list\{max-height:none;overflow-y:visible\}/)
  assert.match(discussion, /@media\(max-width:720px\)[\s\S]*\.message-scroll\{max-height:none;overflow-y:visible\}/)
  assert.match(candidates, /@media\(max-width:720px\)[\s\S]*\.record-list\{max-height:none;overflow-y:visible/)
  assert.match(market, /\.source-list:focus-visible/)
  assert.match(discussion, /\.discussion-list:focus-visible.*\.message-scroll:focus-visible/)
  assert.match(candidates, /\.record-list:focus-visible/)
})
