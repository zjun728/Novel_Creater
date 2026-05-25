import assert from 'node:assert/strict'
import {
  buildChapterBeatPrompt,
  buildChapterPrompt,
  buildChapterSystemPrompt
} from '../frontend/src/prompts/chapter.js'
import { buildAuditPrompt, buildAuditSystemPrompt } from '../frontend/src/prompts/audit.js'
import { auditIssueTypeLabel } from '../frontend/src/utils/auditLabels.js'

const context = {
  chapterNum: 8,
  bible: {
    premise: '弃子归家，面对亲情、权力和自我证明。',
    styleBible: '克制、具体、有生活质感。',
    worldRules: '家族血脉不可随意觉醒。'
  },
  characters: [
    {
      name: '林逐',
      role: '主角',
      desire: '证明自己不是弃子',
      fear: '再次被亲人抛弃',
      softState: {
        emotion: '压抑愤怒',
        currentDesire: '查明林家真相'
      }
    }
  ],
  beatPlan: '1. 林逐回到林家旧宅。\n2. 老人试探他是否还怨恨父亲。',
  previousChapterEnding: '林逐看见族谱上被刮掉的名字。'
}

const systemPrompt = buildChapterSystemPrompt()
assert.match(systemPrompt, /欲望/)
assert.match(systemPrompt, /恐惧/)
assert.match(systemPrompt, /选择/)
assert.match(systemPrompt, /代价/)
assert.match(systemPrompt, /情绪残留/)
assert.match(systemPrompt, /整章最多 2 次/)
assert.match(systemPrompt, /非对白叙述/)

const chapterPrompt = buildChapterPrompt(context)
assert.match(chapterPrompt, /人物代入感/)
assert.match(chapterPrompt, /他想得到什么/)
assert.match(chapterPrompt, /害怕失去什么/)
assert.match(chapterPrompt, /为什么不能直接说出口/)
assert.match(chapterPrompt, /这个选择要付出什么代价/)
assert.match(chapterPrompt, /整章最多 2 次/)

const beatPrompt = buildChapterBeatPrompt(context)
assert.match(beatPrompt, /人物动机层/)
assert.match(beatPrompt, /欲望/)
assert.match(beatPrompt, /恐惧/)
assert.match(beatPrompt, /选择/)
assert.match(beatPrompt, /代价/)

const auditSystemPrompt = buildAuditSystemPrompt()
assert.match(auditSystemPrompt, /代入感/)
assert.match(auditSystemPrompt, /人物是否像工具人/)

const auditPrompt = buildAuditPrompt('林逐推门进去。', context)
assert.match(auditPrompt, /human_motivation/)
assert.match(auditPrompt, /emotional_logic/)
assert.match(auditPrompt, /ai_tone/)
assert.match(auditPrompt, /超过 2 次/)
assert.match(auditPrompt, /人物动机与代入感/)
assert.equal(auditIssueTypeLabel('human_motivation'), '人性动机')
assert.equal(auditIssueTypeLabel('emotional_logic'), '情绪因果')
assert.equal(auditIssueTypeLabel('ai_tone'), 'AI 腔')

console.log('HUMAN_MOTIVATION_PROMPTS_OK')
