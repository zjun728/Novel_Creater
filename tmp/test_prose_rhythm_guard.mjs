import assert from 'node:assert/strict'

import {
  analyzeProseRhythm,
  shouldRepairProseRhythm
} from '../frontend/src/utils/proseRhythmGuard.js'
import {
  buildProseRhythmRepairPrompt,
  buildProseRhythmRepairSystemPrompt
} from '../frontend/src/prompts/chapter.js'

const shortParagraphs = Array.from({ length: 90 }, (_, index) => {
  if (index % 9 === 0) return '他停下。'
  if (index % 9 === 1) return '灯灭了。'
  if (index % 9 === 2) return '风很冷。'
  return `林逐沿着石阶往下走，第 ${index} 次确认墙上的刻痕仍在。`
}).join('\n\n')

const shortAnalysis = analyzeProseRhythm(shortParagraphs)
assert.equal(shortAnalysis.paragraphCount, 90)
assert.ok(shortAnalysis.shortParagraphRate > 0.3)
assert.ok(shortAnalysis.maxShortStreak >= 3)
assert.equal(shouldRepairProseRhythm(shortAnalysis), true)

const balancedOpenings = [
  '林逐停在廊下',
  '石缝里的水线先亮了一下',
  '门后压低的脚步声断了半拍',
  '他把铜钱翻到背面',
  '旧痕没有扩大',
  '风从廊柱后面绕过来'
]
const balancedText = Array.from({ length: 36 }, (_, index) =>
  `${balancedOpenings[index % balancedOpenings.length]}，他听见门后压低的脚步声。第 ${index} 次呼吸之后，他才把手里的铜钱翻到背面，确认那道旧痕没有扩大。`
).join('\n\n')
const balancedAnalysis = analyzeProseRhythm(balancedText)
assert.equal(shouldRepairProseRhythm(balancedAnalysis), false)

const repeatedLeadSubjectText = [
  '陆鸣岐摇了摇头，不再去想祭坛上的那些嘲笑。他把卷轴压在掌心，先确认墓室里的风从哪里来。',
  '陆鸣岐抬起头，看向墓室顶部。夜明珠的光仍然很淡，石缝里的水汽沿着墙面往下爬。',
  '陆鸣岐盯着那行新字，沉默了很久。卷轴边缘微微发热，像在等他做出回应。',
  '陆鸣岐握紧卷轴，站起身，朝门后那片更深的黑暗走去。',
  '他低头看了一眼指尖的血痕，又把那一点疼痛压回掌心。',
  '陆鸣岐把卷轴收好，塞进怀里，然后转身走向来路。'
].join('\n\n')
const repeatedLeadSubjectAnalysis = analyzeProseRhythm(repeatedLeadSubjectText)
assert.equal(repeatedLeadSubjectAnalysis.maxSameLeadingSubjectCount, 5)
assert.ok(repeatedLeadSubjectAnalysis.reasons.includes('段首重复点名偏多'))
assert.equal(shouldRepairProseRhythm(repeatedLeadSubjectAnalysis), true)

const lightContrastText = Array.from({ length: 24 }, (_, index) => {
  if (index === 5) return '门后的响动不是脚步，是旧木头被雨泡胀后自己裂开的声音。'
  if (index === 17) return '他没有立刻回头，只把手里的账册往袖口里推了一寸。'
  return `雨从瓦缝里落下来，打在柜台边缘。第 ${index} 次水声之后，掌柜才把灯芯拨亮。`
}).join('\n\n')
const lightContrastAnalysis = analyzeProseRhythm(lightContrastText)
assert.equal(lightContrastAnalysis.aiContrastCount, 1)
assert.equal(shouldRepairProseRhythm(lightContrastAnalysis), false)

const denseContrastText = Array.from({ length: 30 }, (_, index) => {
  if (index % 4 === 0) return `那不是风，是第 ${index} 道符在墙后松开的声音。`
  return `雨水沿着门槛往里爬，鞋底的泥一点点散开，掌柜把账册翻到空白页。`
}).join('\n\n')
const denseContrastAnalysis = analyzeProseRhythm(denseContrastText)
assert.ok(denseContrastAnalysis.aiContrastCount > 6)
assert.ok(denseContrastAnalysis.reasons.includes('套路化反差句偏多'))
assert.equal(shouldRepairProseRhythm(denseContrastAnalysis), true)

const repairSystem = buildProseRhythmRepairSystemPrompt()
assert.match(repairSystem, /不要新增剧情/)
assert.match(repairSystem, /短句/)
assert.match(repairSystem, /完整正文/)
assert.match(repairSystem, /段首/)

const repairPrompt = buildProseRhythmRepairPrompt({
  chapterNum: 7,
  content: shortParagraphs,
  analysis: shortAnalysis
})
assert.match(repairPrompt, /第 7 章/)
assert.match(repairPrompt, /连续短句/)
assert.match(repairPrompt, /2-5 句/)
assert.match(repairPrompt, /不要输出解释/)
assert.match(repairPrompt, /段首/)

console.log('PROSE_RHYTHM_GUARD_TEST_OK')
