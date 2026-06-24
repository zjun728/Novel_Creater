import assert from 'node:assert/strict'

import {
  collectStructuredBeatPlanIssues,
  formatStructuredBeatPlan,
  parseStructuredBeatPlan
} from '../frontend/src/prompts/chapter.js'
import { validateBeatPlanProgressionGate } from '../frontend/src/quality/writingQualityScoring.js'

const chapter3Attempt2Json = `{
  "chapterEvent": "陆沉舟从星账的震惊中回神，沈渡低声说出父亲最后任务地点是城西废弃矿场，并展示半块玉佩作为信物。陆沉舟确认玉佩为父亲遗物，正要追问细节时，巡天司疤脸队长带队闯入货栈搜查。沈渡示意陆沉舟躲藏，但疤脸队长察觉异样。陆沉舟面临选择：冒险留下继续追问，或立即从后窗跳下逃离。他选择留下，沈渡故意打翻货架制造混乱，陆沉舟被迫跳窗，脚踝扭伤，失去追问机会。逃离后，他在巷中检查玉佩，发现背面刻有“星”字，与星账印章相似。正欲离开，被一灰袍年轻人拦截，对方自称星债会成员，要求交出星账，否则活不过今晚。",
  "characterGoal": "陆沉舟想从沈渡处获取父亲旧案的关键细节，尤其是矿场任务的具体内容和父亲死因，同时避免被巡天司抓获，为三天后赴老槐树之约保留行动能力。",
  "coreConflict": "巡天司追捕队伍突然闯入货栈，打断陆沉舟与沈渡的对话，迫使他必须在获取更多信息与安全逃离之间做出选择，而沈渡的真实身份和动机仍存疑。",
  "externalPressure": "巡天司疤脸队长带四名黑衣星吏踹门进入货栈，以搜查逃犯为名盘问沈渡，并注意到货架后的动静，搜查范围逐步逼近陆沉舟的藏身处。",
  "costOrLoss": "陆沉舟选择冒险留下，但最终被迫跳窗逃离，脚踝扭伤，未能追问矿场任务的细节（如父亲与谁同行、遭遇什么），失去立即获取更多信息的机会，且受伤影响后续行动速度。",
  "irreversibleChange": "陆沉舟获得半块玉佩（父亲遗物，背面刻有“星”字），确认沈渡与父亲确有联系；脚踝扭伤成为身体状态的新负担；星债会外围成员首次主动现身拦截，敌我态势从被动追查转为被对方盯上。",
  "endingHandoff": "陆沉舟被星债会灰袍年轻人拦截，对方声称知道父亲旧案，要求交出星账，否则威胁其性命。陆沉舟握紧玉佩，面临是否交出星账、如何应对星债会的新选择，下一章需处理这一直接冲突。"
}`

const parsed = parseStructuredBeatPlan(chapter3Attempt2Json)
const structuredIssues = collectStructuredBeatPlanIssues(parsed)
assert.deepEqual(structuredIssues.missingRequiredFields, [])
assert.deepEqual(structuredIssues.placeholderFields, [])

const formatted = formatStructuredBeatPlan(parsed)
const quality = validateBeatPlanProgressionGate(formatted, { chapterNum: 3 })
assert.equal(
  quality.passed,
  true,
  `complete chapter 3 JSON candidate must pass quality gate, got ${quality.issues.map(item => item.type).join(',')}`
)

const vaguePlan = formatStructuredBeatPlan({
  chapterEvent: '主角继续处理上一章余波。',
  characterGoal: '主角想弄清局势。',
  coreConflict: '局势变化带来压力。',
  externalPressure: '外部局势变化。',
  costOrLoss: '付出一些代价。',
  irreversibleChange: '关系变化，局势变化，认知变化。',
  endingHandoff: '下一章继续推进。'
})
const vagueQuality = validateBeatPlanProgressionGate(vaguePlan, { chapterNum: 3 })
assert.equal(vagueQuality.passed, false)
assert.ok(
  vagueQuality.issues.some(item => item.type === 'abstract_irreversible_change'),
  'vague relationship/situation/cognition-only irreversibleChange must fail as abstract'
)

console.log('beat plan candidate quality contract tests passed')
