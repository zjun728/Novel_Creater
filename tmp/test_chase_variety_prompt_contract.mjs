import assert from 'node:assert/strict'
import { buildDraftPrompt } from '../frontend/src/prompts/chapterDraftPrompt.js'
import { buildScenePlanPrompt } from '../frontend/src/prompts/chapterPlanPrompt.js'

const scenePlanPrompt = buildScenePlanPrompt({
  chapterNum: 43,
  previousChapterEnding: '陆沉舟刚从地道撤出，身后搜查声还在。',
  chaseLoopDiagnostics: {
    consecutiveChaseDominant: 3,
    preferredSceneFunctions: [
      'active_setup',
      'relationship_confrontation',
      'consequence_scene',
      'information_verification'
    ],
    reason: '最近三章连续由搜查、撤离、潜入主导。'
  },
  storyBlock: {
    title: '水渠余波',
    goal: '确认缺指男人真正目标',
    storyFunction: '承接搜查压力后的主动转向',
    sceneVarietyHint: '避免连续潜入/追逃，改用关系对峙或主动布局。'
  }
})

assert.match(scenePlanPrompt, /场景功能多样性/)
assert.match(scenePlanPrompt, /active_setup|主动布局/)
assert.match(scenePlanPrompt, /relationship_confrontation|关系对峙/)
assert.match(scenePlanPrompt, /consequence_scene|代价后果/)
assert.match(scenePlanPrompt, /information_verification|信息验证/)
assert.match(scenePlanPrompt, /连续\s*3\s*章|最近三章/)
assert.match(scenePlanPrompt, /不能继续以.*追兵逼近|不要继续以.*追兵逼近|追兵逼近、撤离、潜入、搜查为主骨架/)
assert.match(scenePlanPrompt, /底层推进模式/)
assert.match(scenePlanPrompt, /主动布局、关系谈判、行动后果或组织规则观察改变局势/)

const draftPrompt = buildDraftPrompt({
  chapterNum: 43,
  previousChapterEnding: '上一章以搜查撤离结束。',
  beatPlan: '陆沉舟和小九在废院先处理星账代价，再主动设局引缺指男人露面。'
})

const hintMatches = draftPrompt.match(/若上文连续由追捕\/撤离推动/g) || []
assert.equal(hintMatches.length, 1, 'draft prompt should add exactly one short underlying-progression hint')
assert.match(draftPrompt, /主动布局、关系对峙、代价后果或规则观察推进剧情/)
assert.match(draftPrompt, /不要只靠追兵逼近和换地点制造推进/)

console.log('chase variety prompt contract passed')
