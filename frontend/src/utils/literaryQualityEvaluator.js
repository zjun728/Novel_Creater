const DOCUMENTARY_TONE_PATTERN = /(本章主要|本文|资料显示|据此|因此可见|首先[\s\S]{0,80}其次|其次[\s\S]{0,80}最后|这表明|这说明|这意味着|下一阶段|完成.*任务|进行.*处理|按照规则|规则如下|总结|综上)/u
const SUMMARY_TONE_PATTERN = /(意识到|明白|意味着|表明|进入下一阶段|关系出现变化|后续剧情)/u
const CONFLICT_DIALOGUE_PATTERN = /(不是|可是|但是|凭什么|为什么|谁动的手|谁.*动|是我撕|少了一页|别|不能|不许|你敢|你以为|告诉我|承认|撒谎|闭嘴|够了|那就|除非|否则|拖时间|保护谁|不记得|没提|别装|签的字|说清楚|到底|查过|你刚才|交出来|站住|想活|继续跑|别再说|判断错了)/u
const EMOTIONAL_TURN_PATTERN = /(忽然|终于|却|但|可是|反而|原来|才明白|意识到|没挂住|停住|偏开|不是.*是|从.*转为|转为)/u
const FACE_VOICE_PATTERN = /(脸|眼|喉|嗓|声音|语气|呼吸|笑|唇|眉|发白|低声|哑|颤|盯|偏开)/u
const ENVIRONMENT_PATTERN = /(雨|风|灯|窗|门|墙|地面|桌|椅|审讯室|走廊|空气|温度|声音|排风口|警灯|码头|仓)/u
const INNER_THOUGHT_PATTERN = /(她想|他想|心里|忽然明白|才明白|不敢|怕|以为|原来|后悔|迟疑)/u
const ACTION_PATTERN = /(推|按|敲|站|退|偏|盯|开口|放下|抬|攥|握|拉|走|停|伸|躲|笑|沉默)/u
const ACTION_TEMPLATE_WORDS = ['握拳', '攥紧', '指节发白', '咬牙', '沉默', '抬头', '闭眼']
const UNBALANCED_STYLE_PATTERN = /(少描述多动作|少描写多动作|少描述|少描写|多动作|对话简洁|对白简洁)/u
const COUNTERWEIGHT_PATTERN = /(情绪转折|表情|语气|环境压力|潜台词|感官|身体反应|关系变化|动作.*意图|对白.*冲突)/u

function hasText(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function countMatches(text, pattern) {
  const flags = pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`
  const globalPattern = new RegExp(pattern.source, flags)
  return (String(text || '').match(globalPattern) || []).length
}

function countDialogueLines(text) {
  const quoted = countMatches(text, /[“"][^”"]{2,80}[”"]/g)
  const colonLines = String(text || '').split(/\r?\n/).filter(line => /[:：]/.test(line) && line.length < 120).length
  return quoted + colonLines
}

function countConflictDialogue(text) {
  const quoted = String(text || '').match(/[“"][^”"]{2,120}[”"]/g) || []
  return quoted.filter(line => CONFLICT_DIALOGUE_PATTERN.test(line)).length
}

function repeatedActionTemplates(text) {
  return ACTION_TEMPLATE_WORDS
    .map(word => ({ word, count: countMatches(text, new RegExp(word, 'gu')) }))
    .filter(item => item.count >= 2)
}

export function evaluatePromptQuality(prompt = '') {
  const text = String(prompt || '')
  const issues = []
  if (UNBALANCED_STYLE_PATTERN.test(text) && !COUNTERWEIGHT_PATTERN.test(text)) {
    issues.push({
      code: 'unbalanced_less_description',
      severity: 'blocking',
      message: 'Prompt 使用“少描述/多动作/对话简洁”等短语时缺少情绪转折、表情语气、环境压力或潜台词配重。'
    })
  }
  if (/(历史文献|履约报告|规则说明|说明书式|逐条打卡)/u.test(text)) {
    issues.push({
      code: 'documentary_prompt_tone',
      severity: 'warn',
      message: 'Prompt 可能把正文写成文献/报告/规则说明腔。'
    })
  }
  return {
    schemaVersion: 'prompt-quality-evaluator-v1',
    passed: !issues.some(issue => issue.severity === 'blocking'),
    issues
  }
}

export function evaluateLiteraryQuality(text = '', options = {}) {
  const content = String(text || '').trim()
  const issues = []
  const dialogueLines = countDialogueLines(content)
  const conflictDialogueLines = countConflictDialogue(content)
  const repeatedTemplates = repeatedActionTemplates(content)
  const paragraphCount = content.split(/\n+/).filter(hasText).length
  const documentaryHits = countMatches(content, DOCUMENTARY_TONE_PATTERN)
  const summaryHits = countMatches(content, SUMMARY_TONE_PATTERN)
  const hasEmotionalTurn = EMOTIONAL_TURN_PATTERN.test(content)
  const hasFaceVoice = FACE_VOICE_PATTERN.test(content)
  const hasEnvironment = ENVIRONMENT_PATTERN.test(content)
  const hasInnerThought = INNER_THOUGHT_PATTERN.test(content)
  const hasAction = ACTION_PATTERN.test(content)

  if (documentaryHits >= 2) {
    issues.push({
      code: 'documentary_tone',
      severity: 'blocking',
      message: '文本出现文献腔、规则说明腔或履约总结结构。'
    })
  }

  if (summaryHits >= 4 || /这表明|这意味着|关系出现变化|后续剧情/u.test(content)) {
    issues.push({
      code: 'summary_tone',
      severity: 'blocking',
      message: '文本用总结判断替代可见场景。'
    })
  }

  if (dialogueLines < 2 || conflictDialogueLines < 1) {
    issues.push({
      code: 'low_dialogue_conflict',
      severity: 'blocking',
      message: '缺少直接对白冲突、逼问、遮掩或潜台词。'
    })
  }

  if (!hasEmotionalTurn) {
    issues.push({
      code: 'missing_emotional_turn',
      severity: 'blocking',
      message: '没有检测到场景内情绪认知转折。'
    })
  }

  if (!hasFaceVoice) {
    issues.push({
      code: 'missing_face_voice_cues',
      severity: 'warn',
      message: '缺少表情、语气、呼吸、眼神或声音线索。'
    })
  }

  if (!hasEnvironment) {
    issues.push({
      code: 'missing_environmental_pressure',
      severity: 'warn',
      message: '缺少会改变人物压力的环境或空间细节。'
    })
  }

  if (!hasInnerThought) {
    issues.push({
      code: 'missing_short_interiority',
      severity: 'warn',
      message: '缺少贴近当下的短内心或误判变化。'
    })
  }

  if (!hasAction) {
    issues.push({
      code: 'missing_action_expression',
      severity: 'warn',
      message: '缺少承载意图或关系变化的动作。'
    })
  }

  if (repeatedTemplates.length) {
    issues.push({
      code: 'repetitive_action_template',
      severity: 'blocking',
      message: `动作模板重复：${repeatedTemplates.map(item => `${item.word}x${item.count}`).join('，')}`
    })
  }

  const promptQuality = evaluatePromptQuality(options.prompt || '')
  for (const issue of promptQuality.issues) {
    issues.push({
      code: `prompt_${issue.code}`,
      severity: issue.severity,
      message: issue.message
    })
  }

  let score = 100
  score -= issues.filter(issue => issue.severity === 'blocking').length * 18
  score -= issues.filter(issue => issue.severity === 'warn').length * 7
  if (dialogueLines >= 2 && conflictDialogueLines >= 1) score += 4
  if (hasEmotionalTurn) score += 4
  if (hasFaceVoice && hasEnvironment && hasInnerThought && hasAction) score += 6
  if (paragraphCount < 3 && content.length > 200) score -= 8
  score = Math.max(0, Math.min(100, score))

  return {
    schemaVersion: 'literary-quality-evaluator-v1',
    passed: score >= 70 && !issues.some(issue => issue.severity === 'blocking'),
    score,
    issues,
    metrics: {
      paragraphCount,
      dialogueLines,
      conflictDialogueLines,
      documentaryHits,
      summaryHits,
      hasEmotionalTurn,
      hasFaceVoice,
      hasEnvironment,
      hasInnerThought,
      hasAction,
      repeatedTemplates
    }
  }
}
