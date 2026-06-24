import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  buildSettingInitializationDedupKey,
  dedupeSettingInitializationEvents
} from '../frontend/src/prompts/settingsFromBible.js'

const first = {
  entityType: 'character',
  entityName: '沈照夜',
  changeType: 'new_entity',
  fieldPath: 'summary',
  newValue: '{"summary":"主角"}'
}

const duplicate = {
  ...first,
  newValue: '  {"summary":"主角"}  '
}

assert.equal(buildSettingInitializationDedupKey(first), buildSettingInitializationDedupKey(duplicate))
assert.equal(dedupeSettingInitializationEvents([first, duplicate], []).length, 1)

const store = readFileSync('frontend/src/stores/settingStore.js', 'utf8')
assert.match(store, /buildSettingInitializationDedupKey/)
assert.match(store, /existingPendingKeys/)
assert.match(store, /savedInitializationKeys/)
assert.match(store, /skipDuplicateInitializationEvent/)

console.log('setting initialization retry dedupe contract tests passed')
