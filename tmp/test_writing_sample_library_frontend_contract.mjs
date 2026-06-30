import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')

function read(relPath) {
  return fs.readFileSync(path.join(ROOT, relPath), 'utf8')
}

function assertIncludes(text, needle, label) {
  assert.ok(text.includes(needle), `missing ${label}: ${needle}`)
}

{
  const router = read('frontend/src/router/index.js')
  const sidebar = read('frontend/src/components/layout/Sidebar.vue')
  const apiClient = read('frontend/src/api/db/client.js')
  const settingsView = read('frontend/src/views/SettingsView.vue')
  const creativeBible = read('frontend/src/components/bible/CreativeBible.vue')
  const standards = read('frontend/src/data/writingStyleStandards.js')

  assertIncludes(router, '/experience-cards', 'top-level experience-card route')
  assertIncludes(router, 'ExperienceCards', 'route name')
  assertIncludes(sidebar, '创作经验卡', 'top-level sidebar label')
  assertIncludes(apiClient, 'experienceCards', 'experienceCards API namespace')
  assertIncludes(apiClient, '/experience-cards/standards', 'backend standards API')
  assert.ok(!settingsView.includes('WritingSampleReview'), 'settings page should no longer render the experimental sample review panel')
  assert.ok(!settingsView.includes('样本库'), 'settings page should not expose sample-library operations')
  assert.ok(!settingsView.includes('创作经验卡'), 'settings page should not expose experience-card operations')
  assertIncludes(creativeBible, 'experienceCards.standards.list', 'CreativeBible reads backend standards')
  assertIncludes(creativeBible, 'standardSnapshots', 'CreativeBible saves sanitized selected standard snapshots')
  assertIncludes(standards, 'normalizeBackendWritingStyleStandard', 'backend standard normalizer')
  assertIncludes(standards, 'sanitizeWritingStyleStandardForPrompt', 'prompt sanitizer')
  assertIncludes(standards, 'formatActiveWritingStandardLowDoseForPrompt', 'low-dose formal standard prompt resolver')
}

{
  assert.ok(!fs.existsSync(path.join(ROOT, 'frontend/src/components/settings/WritingSampleReview.vue')), 'legacy settings WritingSampleReview.vue should be removed or migrated away')
  const viewPath = path.join(ROOT, 'frontend/src/views/ExperienceCardsView.vue')
  assert.ok(fs.existsSync(viewPath), 'ExperienceCardsView.vue must exist')
  const view = fs.readFileSync(viewPath, 'utf8')
  for (const label of ['经验卡', '候选标准', '正式写作标准', '系统内置', '我的经验', '激活', '未激活', '生成正式写作标准']) {
    assertIncludes(view, label, `experience-card UI label ${label}`)
  }
  for (const forbidden of [
    '导入微示范卡',
    '迁移本地样本报告',
    '审核通过',
    '拒绝',
    '归档',
    'candidate',
    'reviewed',
    'rejected',
    'merged',
    'archived',
    'draft',
    'reviewing',
    'approved',
    'promoted',
    'promote'
  ]) {
    assert.ok(!view.includes(forbidden), `experience-card UI should hide internal state/action ${forbidden}`)
  }
  assertIncludes(view, '经验卡不会直接进入正文生成', 'formal prompt boundary copy')
}

{
  const modulePath = path.join(ROOT, 'frontend/src/data/writingStyleStandards.js')
  const standardsModule = await import(`${pathToFileUrl(modulePath)}?contract=${Date.now()}`)
  assert.equal(typeof standardsModule.normalizeBackendWritingStyleStandard, 'function')
  assert.equal(typeof standardsModule.sanitizeWritingStyleStandardForPrompt, 'function')
  assert.equal(typeof standardsModule.createWritingProfileStandardSnapshots, 'function')

  const backendStandard = standardsModule.normalizeBackendWritingStyleStandard({
    id: 'backend-safe-standard',
    name: '后端抽象标准',
    category: '样本库 / 人工审核',
    shortRule: '凡人修仙传式的资源推进要被抽象成方法，不允许出现韩立或黄枫谷。',
    noDirectImitation: true,
    guidanceJson: {
      chapterEngine: '不要复刻四世同堂，不要提祁家，只保留关系压力的抽象方法。',
      dialogueMethod: 'rawExcerpt 和 sourceText 只能用于后台审核，不进入生成提示。',
      characterMethod: '人物保留自身目的，不使用样本人物名。',
      sourceCardIds: ['seed-card-1'],
      rawExcerpt: '这是一段禁止进入上下文的原文',
      sourceText: '这也是禁止进入上下文的原文'
    },
    sourceCardIds: ['seed-card-1'],
    safetyFlags: ['no_source_names']
  })

  const snapshots = standardsModule.createWritingProfileStandardSnapshots(
    { primaryStandard: 'backend-safe-standard', secondaryFlavor: '' },
    [backendStandard]
  )
  const prompt = standardsModule.formatWritingStyleStandardsForPrompt({
    primaryStandard: 'backend-safe-standard',
    secondaryFlavor: '',
    customStyleNotes: '',
    standardSnapshots: snapshots
  })

  for (const forbidden of ['sourceCardIds', 'rawExcerpt', 'sourceText', '凡人修仙传', '四世同堂', '韩立', '黄枫谷', '祁家']) {
    assert.ok(!prompt.includes(forbidden), `prompt leaked forbidden token: ${forbidden}`)
  }
  assert.ok(prompt.includes('后端抽象标准'), 'prompt should keep the formal standard name')
  assert.ok(prompt.includes('人物保留自身目的'), 'prompt should keep one low-dose abstract guidance item')
  assert.ok(!prompt.includes('章节组织：'), 'prompt must not dump full formal standard sections')
}

function pathToFileUrl(filePath) {
  return new URL(`file://${filePath.replace(/\\/g, '/')}`).href
}
