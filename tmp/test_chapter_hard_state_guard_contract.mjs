import assert from 'node:assert/strict'
import {
  buildChapterPrompt,
  buildChapterBeatPrompt
} from '../frontend/src/prompts/chapter.js'

const context = {
  chapterNum: 5,
  premise: '工业修仙长篇测试',
  worldRules: '灵机冷却需要一夜，青云宗尚未灭亡。',
  settingLibrary: '沈墨左臂在第4章断至肘部；青云宗仍存在但戒严。',
  stateLedger: '沈墨：左臂肘部以下残缺；灵毒扩散中；灵机冷却：一夜。',
  previousChapterEnding: '沈墨捂住左臂残肢，灵机仍在冷却。',
  wordTarget: { target: 5000, min: 4500, max: 6500 }
}

const chapterPrompt = buildChapterPrompt(context)
const beatPrompt = buildChapterBeatPrompt(context)

for (const [label, prompt] of [['chapter', chapterPrompt], ['beat', beatPrompt]]) {
  assert.match(
    prompt,
    /身体状态|伤势|断臂/,
    `${label} prompt should explicitly protect physical hard-state continuity`
  )
  assert.match(
    prompt,
    /冷却|次数|数值|规则/,
    `${label} prompt should explicitly protect numeric and rule continuity`
  )
  assert.match(
    prompt,
    /宗门|势力|灭亡|存灭/,
    `${label} prompt should explicitly protect faction survival/status continuity`
  )
  assert.match(
    prompt,
    /不得突然|不要突然|不能突然|不能无铺垫/,
    `${label} prompt should forbid sudden hard-state jumps without setup`
  )
}

console.log('chapter hard state guard contract tests passed')
