import assert from 'node:assert/strict'
import {
  formatActiveWritingStandardLowDoseForPrompt,
  getSelectableWritingStyleStandards
} from '../frontend/src/data/writingStyleStandards.js'

function createMemoryStorage() {
  const data = new Map()
  return {
    getItem(key) {
      return data.has(key) ? data.get(key) : null
    },
    setItem(key, value) {
      data.set(key, String(value))
    },
    removeItem(key) {
      data.delete(key)
    }
  }
}

const forbiddenTokens = [
  'sourceWork',
  'sourceInfluence',
  'sourceCardId',
  'sourceCardIds',
  'rawExcerpt',
  'sourceText',
  'characterEmotionVariants',
  'emotionDialogueOptions',
  '凡人修仙传',
  '四世同堂',
  '老舍',
  '一句顶一万句',
  '大奉打更人',
  '修真聊天群',
  '斗破苍穹',
  '全球高武',
  '韩立',
  '黄枫谷',
  '祁家'
]

const storage = createMemoryStorage()
const systemStandards = getSelectableWritingStyleStandards({ storage })
  .filter(item => item.sourceKind === 'system')

assert.equal(systemStandards.length, 6, 'content patch must update exactly the existing 6 system formal standards')

const byId = Object.fromEntries(systemStandards.map(item => [item.id, item]))
for (const id of [
  'system-dialogue-realism',
  'system-character-humanity',
  'system-scene-dwell-life-texture',
  'system-anti-ai-basic',
  'system-popular-story-progression',
  'system-natural-setting-exposition'
]) {
  assert.ok(byId[id], `system standard should exist: ${id}`)
}

for (const standard of systemStandards) {
  assert.ok((standard.principles || []).length <= 2, `${standard.id} should keep at most 2 principles`)
  assert.equal(typeof standard.originalMicroDemo, 'string', `${standard.id} should keep one micro demo string`)
  assert.ok(standard.originalMicroDemo.length > 0, `${standard.id} should keep a compact original micro demo`)
  assert.equal(typeof standard.antiAiReminder, 'string', `${standard.id} should keep one anti-AI reminder string`)
  assert.ok(standard.antiAiReminder.length > 0, `${standard.id} should keep one anti-AI reminder`)
  assert.equal(typeof standard.notApplicableScenes, 'string', `${standard.id} should keep one not-applicable/guardrail string`)
  assert.ok(standard.notApplicableScenes.length > 0, `${standard.id} should keep a compact guardrail`)
  const serialized = JSON.stringify(standard)
  for (const token of forbiddenTokens) {
    assert.ok(!serialized.includes(token), `${standard.id} should not contain leaked source/backend token: ${token}`)
  }
}

assert.match(
  byId['system-dialogue-realism'].principles.join('\n'),
  /半截话|打岔|转骂物件|熟人旧账|关系余温/,
  'dialogue standard should absorb half-speech, interruption, object-cursing and old-account warmth'
)
assert.match(
  byId['system-dialogue-realism'].originalMicroDemo,
  /破门|骂门|闭嘴|照光/,
  'dialogue standard should use a compact original micro demo about curse-avoidance and interruption'
)

assert.match(
  byId['system-character-humanity'].principles.join('\n'),
  /配角|私心|生活成本|同一情绪|分叉/,
  'character standard should absorb side-character self-interest and emotion variants'
)
assert.match(
  byId['system-character-humanity'].originalMicroDemo,
  /顺路不顺命|船|养家/,
  'character standard should use a compact original micro demo about self-interest while helping'
)

assert.match(
  byId['system-scene-dwell-life-texture'].principles.join('\n'),
  /等待|排队|吃饭|翻找|秩序|摩擦|微变/,
  'scene standard should absorb waiting, queuing, meals and searching as scene dwell'
)
assert.match(
  byId['system-scene-dwell-life-texture'].originalMicroDemo,
  /殿门|侧门|茶碗|铜钱/,
  'scene standard should use a compact original micro demo about waiting order'
)

assert.match(
  byId['system-anti-ai-basic'].principles.join('\n'),
  /只允许一张微示范|动作、物件和后果|剧情摘要感|身体反应|关系性废话/,
  'anti-AI standard should absorb low-dose reference and anti-summary repair'
)

assert.match(
  byId['system-popular-story-progression'].principles.join('\n'),
  /追逃|清点损失|小答案|新代价|喘息段|关系回血|身体代价/,
  'popular progression standard should absorb loss-counting, small answer and breathing-scene burden'
)
assert.match(
  byId['system-popular-story-progression'].originalMicroDemo,
  /箭袋|木牌|红蜡|水声/,
  'popular progression standard should use a compact original micro demo about answer opening consequence'
)

assert.match(
  byId['system-natural-setting-exposition'].principles.join('\n'),
  /操作失败|小代价|旁人后退|社会反应|价格|让路|物件位置/,
  'setting standard should absorb rule-through-failure and social reaction'
)
assert.match(
  byId['system-natural-setting-exposition'].originalMicroDemo,
  /银盘|擦血|第一次气息/,
  'setting standard should use a compact original micro demo about failed operation showing rule'
)

const prompt = formatActiveWritingStandardLowDoseForPrompt(systemStandards, {
  chapterGoal: '追逃后短暂停下来清点损失，给一个小答案，再让身体代价和关系摩擦接上。',
  beatPlan: '角色在废亭里清点箭袋和线索，喘息段承担关系回血。'
})
assert.equal((prompt.match(/正式写作标准低量调用/g) || []).length, 1, 'prompt should contain exactly one low-dose formal-standard section')
assert.ok((prompt.match(/写法原则：/g) || []).length <= 1, 'prompt should include at most one principle')
assert.ok((prompt.match(/原创微示范：/g) || []).length <= 1, 'prompt should include at most one micro demo')
assert.ok((prompt.match(/反 AI 提醒：/g) || []).length <= 1, 'prompt should include at most one anti-AI reminder')
for (const token of forbiddenTokens) {
  assert.ok(!prompt.includes(token), `low-dose prompt should not leak source/backend token: ${token}`)
}

console.log('formal standard content patch contract passed')
