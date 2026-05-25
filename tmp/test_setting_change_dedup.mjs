import assert from 'node:assert/strict'
import {
  findDuplicateSettingChangeEvent,
  settingChangeDedupKey
} from '../frontend/src/utils/settingChangeDedup.js'

const candidate = {
  entityType: 'character',
  entityName: '林逐',
  changeType: 'correction_task',
  fieldPath: 'character',
  chapterNum: 12,
  evidence: '来自全局审稿纠偏任务：林逐动机偏离',
  newValue: '林逐需要补充家族压力下的真实动机。',
  status: 'pending_review'
}

const duplicate = {
  ...candidate,
  id: 'existing',
  chapterNum: '12',
  newValue: '  林逐需要补充家族压力下的真实动机。  '
}

assert.equal(settingChangeDedupKey(candidate), settingChangeDedupKey(duplicate))
assert.equal(findDuplicateSettingChangeEvent([duplicate], candidate)?.id, 'existing')
assert.equal(findDuplicateSettingChangeEvent([{ ...duplicate, status: 'accepted' }], candidate), null)
assert.equal(findDuplicateSettingChangeEvent([{ ...duplicate, newValue: '不同内容' }], candidate), null)

console.log('SETTING_CHANGE_DEDUP_TEST_OK')
