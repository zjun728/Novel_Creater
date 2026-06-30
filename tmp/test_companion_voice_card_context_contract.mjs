import assert from 'node:assert/strict'
import { buildWritingContext } from '../frontend/src/utils/contextBuilder.js'
import { buildChapterPrompt } from '../frontend/src/prompts/chapter.js'

const novelStore = {
  bible: { premise: '测试长篇', worldRules: '星账使用必须付出代价。' },
  outline: {
    nearChapters: [
      { chapterNum: 21, goal: '处理第三密栈余波，小九同行。' }
    ]
  },
  characters: [
    { id: 'p', name: '陆沉舟', role: 'protagonist', hardState: { location: '第三密栈' }, softState: { emotion: '强撑' } },
    { id: 'xj', name: '小九', role: 'supporting', hardState: { location: '第三密栈外' }, softState: { emotion: '嘴硬担心' } },
    { id: 'chen', name: '老陈', role: 'supporting', hardState: {}, softState: {} },
    { id: 'random', name: '陌生路人甲', role: 'supporting', hardState: {}, softState: {} }
  ],
  plotThreads: [],
  canonFacts: [
    {
      id: 'fact-voice',
      status: 'accepted',
      chapterNum: 19,
      factType: 'relationship',
      content: '小九给陆沉舟冷饼和腊肠，嘴上催他快走。',
      relatedCharacters: ['陆沉舟', '小九']
    }
  ]
}

const settingStore = {
  entities: [
    { id: 'chen-setting', status: 'active', entityType: 'character', name: '老陈', summary: '杂货铺旧识。', profile: {} },
    { id: 'xu-setting', status: 'active', entityType: 'character', name: '徐主簿', summary: '巡天司主簿。', profile: { canonicalName: '徐正清' } }
  ],
  relations: [],
  changeEvents: []
}

const result = buildWritingContext(novelStore, 21, 12000, settingStore, null, null, null)
assert.ok(result.context.companionVoiceCards, 'writing context should include short companion voice cards')
assert.match(result.context.companionVoiceCards, /小九/)
assert.match(result.context.companionVoiceCards, /说话习惯/)
assert.match(result.context.companionVoiceCards, /不愿说出口/)
assert.match(result.context.companionVoiceCards, /对陆沉舟/)
assert.match(result.context.companionVoiceCards, /本阶段小目标/)
assert.doesNotMatch(result.context.companionVoiceCards, /陌生路人甲/, 'unknown companions should not get invented voice cards')
assert.ok(
  result.context.companionVoiceCards.length < 900,
  'voice cards should stay short and context-budget friendly'
)

const prompt = buildChapterPrompt({ chapterNum: 21, companionVoiceCards: result.context.companionVoiceCards })
assert.match(prompt, /配角声音卡/)
assert.match(prompt, /小九/)

console.log('companion voice card context contract passed')
