import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  classifySettingChangeRisk,
  isBatchAcceptableSettingChange,
  isPlaceholderSettingEntity
} from '../frontend/src/utils/settingChangeRisk.js'

const placeholderEntity = {
  id: 'placeholder-1',
  entityType: 'character',
  name: '陆沉舟',
  category: '',
  summary: '第 ? 章自动识别的设定',
  tags: ['AI识别'],
  profile: {},
  firstChapter: null,
  lastChapter: null
}

assert.equal(isPlaceholderSettingEntity(placeholderEntity), true)

const placeholderCompletion = {
  entityName: '陆沉舟',
  entityType: 'character',
  changeType: 'new_entity',
  fieldPath: 'summary',
  newValue: JSON.stringify({
    summary: '主角，被逐出巡天司的少年，用星账追查父亲旧案。',
    category: '主角',
    profile: {
      identity: '前巡天司见习星吏',
      faction: '无',
      realm: '见习'
    },
    tags: ['创作圣经初始化']
  }),
  evidence: '创作圣经初始化',
  confidence: 1
}

const completionRisk = classifySettingChangeRisk(placeholderCompletion, {
  existingEntity: placeholderEntity
})
assert.equal(completionRisk.classification, 'low_risk_update')
assert.equal(isBatchAcceptableSettingChange({ ...placeholderCompletion, classification: completionRisk.classification }), true)
assert.ok(completionRisk.conflictWarnings.some(item => item.includes('占位实体补全')))

const formalConflict = classifySettingChangeRisk({
  entityName: '陆沉舟',
  entityType: 'character',
  changeType: 'new_entity',
  fieldPath: 'summary',
  newValue: JSON.stringify({
    summary: '赤焰宗内门弟子',
    profile: { faction: '赤焰宗' }
  }),
  evidence: '无明确剧情证据',
  confidence: 0.8
}, {
  existingEntity: {
    entityType: 'character',
    name: '陆沉舟',
    category: '主角',
    summary: '前巡天司见习星吏',
    tags: [],
    profile: { faction: '巡天司' },
    firstChapter: 1,
    lastChapter: 1
  }
})
assert.equal(formalConflict.classification, 'hard_conflict')

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
assert.match(liveScript, /function sortSettingEventsForConfirmation\(/)
assert.match(
  liveScript,
  /sortSettingEventsForConfirmation\(pending\)[\s\S]*splitSettingEventsByRisk/,
  'initial setting confirmation must classify events after entity-before-relationship ordering'
)
assert.match(
  liveScript,
  /new_entity[\s\S]*update_entity[\s\S]*relationship/,
  'confirmation order must keep new_entity, then update_entity, then relationship'
)
assert.match(liveScript, /existingEntity/)
assert.match(liveScript, /placeholderEntity/)
assert.match(liveScript, /cannotAutoConfirmReason/)
assert.match(
  liveScript,
  /liveDiagnostics:\s*error\?\.liveDiagnostics\s*\|\|\s*error\?\.settingReview/,
  'top-level hard conflict failures must preserve settingReview diagnostics'
)

const backend = readFileSync('backend/routers/settings_library.py', 'utf8')
assert.match(backend, /def _is_placeholder_entity\(/)
assert.match(
  backend,
  /def _collect_duplicate_entity_hard_conflicts[\s\S]*_is_placeholder_entity/,
  'backend duplicate new_entity conflict collection must allow placeholder completion'
)
assert.match(
  backend,
  /async def _apply_relationship_event[\s\S]*_find_pending_new_entity_event/,
  'relationship acceptance must check pending new_entity before creating placeholder entities'
)
assert.match(
  backend,
  /async def _find_or_create_entity[\s\S]*placeholder_reason/,
  'backend placeholder creation must be diagnostic and avoid hiding why a placeholder was created'
)

console.log('setting placeholder merge contract tests passed')
