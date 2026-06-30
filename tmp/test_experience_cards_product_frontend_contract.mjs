import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function read(relPath) {
  return fs.readFileSync(path.join(ROOT, relPath), 'utf8')
}

function fileUrl(relPath) {
  return new URL(`file://${path.join(ROOT, relPath).replace(/\\/g, '/')}`).href
}

const view = read('frontend/src/views/ExperienceCardsView.vue')
const apiClient = read('frontend/src/api/db/client.js')
const draftPrompt = read('frontend/src/prompts/chapterDraftPrompt.js')
const writerView = read('frontend/src/views/WriterView.vue')

for (const forbidden of [
  'candidate',
  'reviewed',
  'rejected',
  'merged',
  'archived',
  'promoted',
  'draft',
  'reviewing',
  'approved',
  '导入微示范卡',
  '迁移本地样本报告',
  '审核通过',
  '拒绝',
  '归档',
  'promote'
]) {
  assert.ok(!view.includes(forbidden), `ExperienceCardsView should not expose internal maintenance state/action: ${forbidden}`)
}

for (const required of [
  '系统内置',
  '我的经验',
  '激活',
  '未激活',
  '复制为我的经验卡',
  '加入候选标准',
  '生成正式写作标准',
  '复制为我的写作标准'
]) {
  assert.ok(view.includes(required), `ExperienceCardsView should expose product label: ${required}`)
}

assert.ok(!draftPrompt.includes('formatSampleMicroDemoPromptSection'), 'chapterDraftPrompt must not format experience-card micro demos directly')
assert.ok(!draftPrompt.includes('sampleMicroDemoCard'), 'chapterDraftPrompt must ignore direct sampleMicroDemoCard context')
assert.ok(!writerView.includes('selectSampleMicroDemoCard'), 'WriterView must not select experience cards for draft prompt')

for (const route of [
  'delete',
  'toggleActive',
  'copy',
  'generateStandard',
  'removeCard'
]) {
  assert.ok(apiClient.includes(route), `experienceCards API should expose product operation: ${route}`)
}

const product = await import(`${fileUrl('frontend/src/data/experienceCardProduct.js')}?contract=${Date.now()}`)

const state = product.createExperienceCardProductState()
assert.ok(state.cards.some(card => card.sourceKind === 'system' && card.sourceLabel === '系统内置'), 'built-in experience cards should be visible without manual import')
assert.ok(state.cards.every(card => ['激活', '未激活'].includes(card.statusLabel)), 'experience cards should expose only product status labels')

const systemCard = state.cards.find(card => card.sourceKind === 'system')
assert.equal(product.canDeleteExperienceCard(state, systemCard.id).allowed, false, 'system built-in experience cards cannot be deleted')

const userCard = product.copyExperienceCardToMine(state, systemCard.id)
assert.equal(userCard.sourceKind, 'user')
assert.equal(product.canDeleteExperienceCard(state, userCard.id).allowed, true, 'unreferenced user experience card can be deleted')

const draft = product.createWritingStandardDraft(state, {
  name: '关系对白草稿',
  description: '用多张经验卡生成标准',
  applicableScenes: '关系摩擦和对白场'
}, [systemCard.id, userCard.id])
assert.equal(draft.statusLabel, '草稿')
assert.equal(product.canDeleteExperienceCard(state, userCard.id).allowed, false, 'card referenced by draft standard cannot be deleted')
assert.match(product.canDeleteExperienceCard(state, userCard.id).message, /候选标准/)

product.removeExperienceCardFromDraft(state, draft.id, systemCard.id)
assert.throws(
  () => product.removeExperienceCardFromDraft(state, draft.id, userCard.id),
  /不能产生空候选标准/,
  'removing cards from a draft must not create an empty draft'
)
product.addExperienceCardsToDraft(state, draft.id, [systemCard.id])

const standard = product.generateFormalWritingStandardFromDraft(state, draft.id)
assert.equal(standard.statusLabel, '激活')
assert.equal(standard.sourceKind, 'user')
assert.ok(Array.isArray(standard.experienceCardSnapshots) && standard.experienceCardSnapshots.length >= 2, 'formal standard must store experience card snapshots')
assert.equal(product.canDeleteExperienceCard(state, userCard.id).allowed, false, 'card referenced by formal standard cannot be deleted')
assert.match(product.canDeleteExperienceCard(state, userCard.id).message, /正式写作标准/)

const systemStandard = state.standards.find(item => item.sourceKind === 'system')
assert.ok(systemStandard, 'system built-in formal standards should exist')
assert.equal(systemStandard.active, true, 'system built-in formal standards are active by default')
assert.equal(product.canDeleteWritingStandard(state, systemStandard.id).allowed, false, 'system built-in formal standards cannot be deleted')

console.log('experience cards product frontend contract passed')
