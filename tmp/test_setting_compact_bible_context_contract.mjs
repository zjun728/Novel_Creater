import assert from 'node:assert/strict'

import {
  SETTING_INITIALIZATION_GROUPS,
  buildCompactBibleContext,
  buildSettingsFromBibleSegmentPrompt,
  extractSettingsFromBibleText,
  filterEventsForInitializationGroup
} from '../frontend/src/prompts/settingsFromBible.js'

const long = '很长的世界规则。'.repeat(1200)
const bible = {
  premise: '一个少年在巨城中追查失踪的日晷。',
  targetReader: '长篇网文读者',
  styleBible: long,
  themeBible: long,
  worldRules: long,
  forbiddenDirections: ['不要写成规则表']
}
const group = SETTING_INITIALIZATION_GROUPS.find(item => item.key === 'characters')
const context = buildCompactBibleContext({ bible, group, seed: { title: '日晷城', logline: '少年追查日晷' } })
const prompt = buildSettingsFromBibleSegmentPrompt({
  bibleContext: context,
  seed: { title: '日晷城', logline: '少年追查日晷' },
  existingSettings: [],
  existingEvents: [],
  group
})

assert.ok(context.length < JSON.stringify(bible).length / 3)
assert.match(context, /作品定位/)
assert.match(context, /人物/)
assert.match(prompt, /紧凑圣经上下文/)
assert.doesNotMatch(prompt, new RegExp(long.slice(0, 80)))
assert.match(prompt, /本轮最多\s+8\s+条/)

const worldRuleGroup = SETTING_INITIALIZATION_GROUPS.find(item => item.key === 'worldRules')
const parsedRules = extractSettingsFromBibleText(JSON.stringify({
  settings: [
    {
      entityType: 'world_rule',
      ruleName: '灵脉透支规则',
      summary: '修士透支灵脉会引发区域崩灭。'
    },
    {
      entityType: 'ability_system',
      systemName: '星账代价',
      summary: '星账查询必须支付寿元或记忆。'
    }
  ]
}))
assert.equal(filterEventsForInitializationGroup(parsedRules, worldRuleGroup).length, 2)
assert.ok(parsedRules.every(event => event.entityType === 'power_system'))

console.log('setting compact bible context contract tests passed')
