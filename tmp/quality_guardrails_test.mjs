import assert from 'node:assert/strict'

import {
  buildChapterSystemPrompt,
  buildChapterBeatPrompt
} from '../frontend/src/prompts/chapter.js'

const systemPrompt = buildChapterSystemPrompt()
assert.match(systemPrompt, /长中短句/, '正文生成系统提示词应明确要求长中短句混合')
assert.match(systemPrompt, /短句独段/, '正文生成系统提示词应限制短句独段的连续使用')

const beatPrompt = buildChapterBeatPrompt({
  chapterNum: 6,
  wordTarget: { target: 5000, min: 4500, max: 6500, hardMin: 4000, hardMax: 7000 }
})
assert.match(beatPrompt, /句式节奏/, '小纲提示词应要求规划正常叙事节奏')
assert.match(beatPrompt, /短句密集/, '小纲提示词应避免把整章规划成短句密集段')

const { filterIssuesForCorrectionTasks } = await import('../frontend/src/utils/correctionTaskDenoise.js')

const noisyIssues = [
  { severity: 'suggestion', type: 'pacing', description: '节奏可以更紧' },
  { severity: 'minor', type: 'ai_tone', description: '短句略多' },
  { severity: 'minor', type: 'cliche_imagery', description: '月光意象普通' },
  { severity: 'major', type: 'logic', description: '关键因果断裂' },
  { severity: 'critical', type: 'world_rule_violation', description: '世界规则冲突' },
  { severity: 'major', type: 'ai_tone', description: '整章短句堆叠明显' },
  { severity: 'major', type: 'logic', description: '关键因果断裂' }
]

const filtered = filterIssuesForCorrectionTasks(noisyIssues, { maxTasks: 3 })
assert.deepEqual(
  filtered.map(issue => `${issue.severity}:${issue.type}:${issue.description}`),
  [
    'critical:world_rule_violation:世界规则冲突',
    'major:logic:关键因果断裂',
    'major:ai_tone:整章短句堆叠明显'
  ],
  '纠偏任务应只保留高优先级问题、去重并限制数量'
)

console.log('quality guardrails tests passed')
