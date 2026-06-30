import assert from 'node:assert/strict'
import {
  createExperienceCardProductState,
  createUserExperienceCard,
  createWritingStandardDraft,
  generateFormalWritingStandardFromDraft,
  toggleWritingStandardActive
} from '../frontend/src/data/experienceCardProduct.js'
import {
  createWritingProfileStandardSnapshots,
  formatWritingStyleStandardsForPrompt,
  getSelectableWritingStyleStandards,
  getSelectedWritingStyleStandards,
  normalizeWritingProfile
} from '../frontend/src/data/writingStyleStandards.js'
import { buildWritingContext } from '../frontend/src/utils/contextBuilder.js'
import { buildDraftPrompt } from '../frontend/src/prompts/chapterDraftPrompt.js'
import { normalizeBiblePayload } from '../frontend/src/prompts/bibleFromSeed.js'

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

const storage = createMemoryStorage()
const productState = createExperienceCardProductState({ storage })
const systemDialogue = productState.standards.find(item => item.id === 'system-dialogue-realism')
const systemScene = productState.standards.find(item => item.id === 'system-scene-dwell-life-texture')
assert.ok(systemDialogue, 'product state should initialize system formal writing standards')
assert.ok(systemScene, 'product state should initialize more than one system formal standard')

toggleWritingStandardActive(productState, systemDialogue.id)

const userCard = createUserExperienceCard(productState, {
  title: '我的对话停顿经验',
  applicableScenes: '熟人试探、关系摩擦、话说半截',
  writingMethod: '先让人物用半句、停顿和动作绕开真正担心的事。',
  originalMicroDemo: '他把伞柄往她那边挪了挪，说：“路滑，我是怕你摔了还得我赔。”',
  antiAiReminder: '不要让人物把关心解释成完整心理报告。'
})
const candidate = createWritingStandardDraft(productState, {
  name: '我的对话停顿标准',
  applicableScenes: '熟人试探、嘴硬关心、关系摩擦'
}, [userCard.id])
const userStandard = generateFormalWritingStandardFromDraft(productState, candidate.id, {
  name: '我的对话停顿标准',
  applicableScenes: '熟人试探、嘴硬关心、关系摩擦',
  principle: '先用半句、停顿和动作表达关系压力，再让信息自然露出。',
  originalMicroDemo: '他把伞柄往她那边挪了挪，说：“路滑，我是怕你摔了还得我赔。”',
  antiAiReminder: '不要让人物把关心解释成完整心理报告。'
})

const selectable = getSelectableWritingStyleStandards({ storage })
assert.ok(selectable.some(item => item.id === userStandard.id), 'writing style selection should read active user formal standards created on the experience-card page')
assert.ok(selectable.some(item => item.id === systemScene.id), 'writing style selection should include active system formal standards')
assert.ok(!selectable.some(item => item.id === systemDialogue.id), 'inactive formal standards should not appear in project selection')
assert.ok(selectable.every(item => item.status === 'active'), 'project selection should only expose active formal standards')

const profile = normalizeWritingProfile({
  selectedStandards: [userStandard.id, systemDialogue.id, systemScene.id],
  customStyleNotes: ''
}, { storage })
const selected = getSelectedWritingStyleStandards(profile, { storage })
assert.deepEqual(
  selected.map(item => item.standard.id),
  [userStandard.id, systemScene.id],
  'project selection should keep active formal standards and drop inactive ones'
)
assert.ok(selected.length <= 3, 'project writing profile should support at most three selected formal standards')

const lowDoseBrief = formatWritingStyleStandardsForPrompt(profile, {
  storage,
  context: { chapterGoal: '熟人试探时嘴硬关心' }
})
assert.match(lowDoseBrief, /正式写作标准低量调用/, 'writing style prompt should format selected formal standards as low-dose guidance')
assert.match(lowDoseBrief, /我的对话停顿标准/, 'low-dose brief should use selected formal standards from product state')
assert.doesNotMatch(lowDoseBrief, /对话真实感增强/, 'inactive formal standards should not enter writing style prompt')
assert.doesNotMatch(lowDoseBrief, /经验卡不会直接进入正文|候选标准|cardType|promptReadiness/, 'experience cards and candidate standards should not be dumped into prompt')

const standardSnapshots = createWritingProfileStandardSnapshots(profile, selectable)
const savedProfile = { ...profile, standardSnapshots }
const normalizedBible = normalizeBiblePayload({
  premise: '闭环测试故事',
  writingProfile: savedProfile
})
assert.deepEqual(
  normalizedBible.writingProfile.selectedStandards,
  savedProfile.selectedStandards,
  'creative bible save normalizer should preserve 1-3 selected formal standard ids'
)
assert.ok(
  normalizedBible.writingProfile.standardSnapshots?.[userStandard.id],
  'creative bible save normalizer should preserve formal standard snapshots'
)
const contextResult = buildWritingContext({
  bible: {
    premise: '闭环测试故事',
    styleBible: '',
    worldRules: '',
    writingProfile: savedProfile
  },
  outline: {
    nearChapters: [
      { chapterNum: 8, title: '旧识试探', goal: '熟人试探时嘴硬关心，关系摩擦里露出线索。' }
    ]
  },
  characters: [],
  plotThreads: [],
  canonFacts: []
}, 8, 12000, null, null, null, null)

assert.ok(Array.isArray(contextResult.context.activeWritingStandards), 'contextBuilder should pass real activeWritingStandards into draft context')
assert.deepEqual(
  contextResult.context.activeWritingStandards.map(item => item.id),
  [userStandard.id, systemScene.id],
  'contextBuilder should carry the project-enabled formal standards, not experience cards or candidates'
)
assert.doesNotMatch(JSON.stringify(contextResult.context.activeWritingStandards), /对话真实感增强/, 'contextBuilder should exclude inactive formal standards')

const draftPrompt = buildDraftPrompt({
  ...contextResult.context,
  chapterGoal: '熟人试探时嘴硬关心',
  beatPlan: '两人旧识重逢，话说半截，借一把伞绕开真正担心。',
  sampleMicroDemoCard: {
    cardTitle: '经验卡直连不应出现',
    sourceWork: '凡人修仙传',
    sourceInfluence: '韩立',
    originalMicroDemo: '这张经验卡不应直接进正文 prompt。'
  },
  candidateStandards: [
    { name: '候选标准不应出现', principle: '候选标准不能进入正文 prompt。' }
  ]
})

assert.match(draftPrompt, /正式写作标准低量调用/, 'draft prompt should include low-dose formal standard section when project standards are enabled')
assert.match(draftPrompt, /我的对话停顿标准/, 'draft prompt should use project-enabled formal standards')
assert.doesNotMatch(draftPrompt, /经验卡直连不应出现|候选标准不应出现|sourceWork|sourceInfluence|韩立|凡人修仙传/, 'draft prompt must not directly read experience cards, candidate standards, or source fields')
assert.ok((draftPrompt.match(/写法原则：/g) || []).length <= 1, 'draft prompt should include at most one writing principle')
assert.ok((draftPrompt.match(/原创微示范：/g) || []).length <= 1, 'draft prompt should include at most one original micro demo')
assert.ok((draftPrompt.match(/反 AI 提醒：/g) || []).length <= 1, 'draft prompt should include at most one anti-AI reminder')

console.log('FORMAL_WRITING_STANDARD_CLOSURE_CONTRACT_OK')
