const FORBIDDEN_FACT_STAGE_KEYS = new Set([
  'factOverride',
  'factOverrides',
  'factsOverride',
  'stateOverride',
  'stateAuthority',
  'stageBoundary',
  'stageOverride',
  'creativeStageContract',
  'mustReveal',
  'mustResolve',
  'mustStopAt',
  'worldRules',
  'guardSnapshot',
  'futureRoadmap'
])

const DOCUMENTARY_TONE_PATTERN = /(历史文献|文献|报告|规则说明|履约文本|说明书|条款|按规则|逐条执行|打卡)/u
const RISKY_STYLE_PATTERN = /(少描述多动作|少描写多动作|少描述|少描写|多动作|对话简洁|对白简洁|节奏快|快节奏|场景短促|场景短)/u

function hasText(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function asArray(value) {
  if (Array.isArray(value)) return value
  return hasText(value) ? [value] : []
}

function compactText(value, limit = 280) {
  if (!hasText(value)) return ''
  const normalized = String(value).replace(/\s+/g, ' ').trim()
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized
}

function collectText(value, bucket = []) {
  if (!value) return bucket
  if (typeof value === 'string' || typeof value === 'number') {
    if (hasText(value)) bucket.push(String(value))
    return bucket
  }
  if (Array.isArray(value)) {
    value.forEach(item => collectText(item, bucket))
    return bucket
  }
  if (typeof value === 'object') {
    Object.entries(value).forEach(([key, child]) => {
      if (FORBIDDEN_FACT_STAGE_KEYS.has(key)) return
      collectText(child, bucket)
    })
  }
  return bucket
}

function stripForbiddenKeys(value) {
  if (Array.isArray(value)) return value.map(stripForbiddenKeys)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => !FORBIDDEN_FACT_STAGE_KEYS.has(key))
      .map(([key, child]) => [key, stripForbiddenKeys(child)])
  )
}

function detectStyleIntents(text) {
  return {
    fastPacing: /(节奏快|快节奏|短促|场景短)/u.test(text),
    lessDescription: /(少描述|少描写|少解释)/u.test(text),
    actionForward: /(多动作|动作多|动作推进)/u.test(text),
    conciseDialogue: /(对话简洁|对白简洁|短对白|少对白)/u.test(text),
    documentaryRisk: DOCUMENTARY_TONE_PATTERN.test(text)
  }
}

function normalizeProfile(input = {}) {
  const rawText = [
    ...asArray(input.styleBible),
    ...asArray(input.styleMethodBrief),
    ...asArray(input.styleStandardBrief),
    ...asArray(input.customStyleNotes),
    ...asArray(input.rawStyle),
    ...collectText(input.writingProfile),
    input.tone,
    input.rhythm,
    input.diction
  ].filter(hasText).join('\n')
  const intents = detectStyleIntents(rawText)

  return {
    rawText,
    intents,
    sourceSummary: compactText(
      rawText
        .replace(RISKY_STYLE_PATTERN, '')
        .replace(DOCUMENTARY_TONE_PATTERN, '')
    )
  }
}

export function buildNarrativeVoiceContractV2(input = {}) {
  if (input?.schemaVersion === 'narrative-voice-contract-v2' && input.scope === 'expression_only') {
    return sanitizeNarrativeVoiceContractV2(input)
  }

  const profile = normalizeProfile(input)
  const fastPacingNote = profile.intents.fastPacing
    ? '短场景可以有推力，但每场必须有压力、选择和情绪转折。'
    : '场景节奏服务人物压力，不用机械加速。'
  const lessDescriptionNote = profile.intents.lessDescription
    ? '少解释不等于少感官；保留表情、语气、身体反应和环境压力。'
    : '描写贴近角色视角，优先服务压力、误判和关系变化。'
  const actionNote = profile.intents.actionForward
    ? '动作必须承载意图、关系变化或代价，不能只做流水账位移。'
    : '关键动作要带欲望、阻力和后果。'
  const dialogueNote = profile.intents.conciseDialogue
    ? '短对白必须有冲突、遮掩、潜台词或权力变化。'
    : '对白要让人物互相试探、回避、逼问或误判。'

  const contract = {
    schemaVersion: 'narrative-voice-contract-v2',
    scope: 'expression_only',
    tone: compactText(input.tone || input.writingProfile?.tone || '贴近角色处境，避免旁白替人物总结。'),
    rhythm: fastPacingNote,
    diction: compactText(input.diction || '句子长短按压力变化；表达贴近场景，不写成抽象说明。'),
    dialogue: {
      conflictAndSubtext: true,
      guidance: dialogueNote
    },
    emotion: {
      mustTurn: true,
      guidance: '每个主场景至少有一次情绪认知变化，变化来自证据、错话、代价或关系压力。'
    },
    embodiment: {
      facialVoiceEnvironment: true,
      guidance: lessDescriptionNote
    },
    action: {
      mustCarryIntentionAndRelationshipChange: true,
      guidance: actionNote
    },
    interiority: {
      shortAndInterrupted: true,
      guidance: '内心短、贴近当下，可以被外界动作、对白或危险打断。'
    },
    forbiddenModes: [
      '历史文献腔',
      '履约报告腔',
      '规则说明腔',
      '总结替代场景',
      '动作流水账'
    ],
    sourceRiskTransform: {
      fastPacingNormalized: profile.intents.fastPacing,
      lessDescriptionCounterweighted: profile.intents.lessDescription,
      actionListCounterweighted: profile.intents.actionForward,
      conciseDialogueCounterweighted: profile.intents.conciseDialogue,
      documentaryToneFiltered: profile.intents.documentaryRisk
    }
  }

  const sanitized = sanitizeNarrativeVoiceContractV2(contract)
  return {
    ...sanitized,
    lint: lintNarrativeVoiceContractV2(sanitized)
  }
}

export function lintNarrativeVoiceContractV2(contract = {}) {
  const issues = []
  const scan = (value, path = '') => {
    if (typeof value === 'string') {
      if (DOCUMENTARY_TONE_PATTERN.test(value)) {
        issues.push({
          code: 'documentary_or_rule_tone',
          severity: 'warn',
          path,
          message: `叙事声音合同不能把表达方式写成文献/报告/规则说明：${path || 'root'}`
        })
      }
      if (/少描述多动作|少描写多动作/u.test(value)) {
        issues.push({
          code: 'risky_style_shorthand',
          severity: 'warn',
          path,
          message: `叙事声音合同不能保留“少描述多动作”这类未配平短语：${path || 'root'}`
        })
      }
      return
    }
    if (!value || typeof value !== 'object') return
    for (const [key, child] of Object.entries(value)) {
      const childPath = path ? `${path}.${key}` : key
      if (FORBIDDEN_FACT_STAGE_KEYS.has(key)) {
        issues.push({
          code: 'forbidden_fact_or_stage_field',
          severity: 'block',
          path: childPath,
          message: `叙事声音合同不能声明事实、世界规则、guard 或 stage 边界覆盖字段：${childPath}`
        })
        continue
      }
      scan(child, childPath)
    }
  }
  scan(contract)
  return { ok: issues.length === 0, issues }
}

export function sanitizeNarrativeVoiceContractV2(contract = {}) {
  const stripped = stripForbiddenKeys(contract)
  const safe = {
    schemaVersion: 'narrative-voice-contract-v2',
    scope: 'expression_only',
    tone: compactText(stripped.tone || ''),
    rhythm: compactText(stripped.rhythm || ''),
    diction: compactText(stripped.diction || ''),
    dialogue: {
      conflictAndSubtext: Boolean(stripped.dialogue?.conflictAndSubtext ?? true),
      guidance: compactText(stripped.dialogue?.guidance || '对白带冲突、遮掩和潜台词。')
    },
    emotion: {
      mustTurn: Boolean(stripped.emotion?.mustTurn ?? true),
      guidance: compactText(stripped.emotion?.guidance || '主场景需要看得见的情绪转折。')
    },
    embodiment: {
      facialVoiceEnvironment: Boolean(stripped.embodiment?.facialVoiceEnvironment ?? true),
      guidance: compactText(stripped.embodiment?.guidance || '表情、语气、身体反应和环境压力共同承载情绪。')
    },
    action: {
      mustCarryIntentionAndRelationshipChange: Boolean(stripped.action?.mustCarryIntentionAndRelationshipChange ?? true),
      guidance: compactText(stripped.action?.guidance || '动作承载意图、关系变化或代价。')
    },
    interiority: {
      shortAndInterrupted: Boolean(stripped.interiority?.shortAndInterrupted ?? true),
      guidance: compactText(stripped.interiority?.guidance || '短内心贴近当下，并允许被外界打断。')
    },
    forbiddenModes: asArray(stripped.forbiddenModes)
      .filter(item => !DOCUMENTARY_TONE_PATTERN.test(String(item)))
      .slice(0, 8),
    sourceRiskTransform: stripped.sourceRiskTransform || {}
  }
  const lint = lintNarrativeVoiceContractV2(safe)
  return { ...safe, lint }
}

export function formatNarrativeVoiceContractForPrompt(contract = {}) {
  const voice = contract?.schemaVersion === 'narrative-voice-contract-v2'
    ? sanitizeNarrativeVoiceContractV2(contract)
    : buildNarrativeVoiceContractV2(contract)
  if (!voice?.lint?.ok) return ''
  return [
    '## Narrative Voice Contract',
    '- 范围：只约束表达方式，不覆盖事实、世界规则、阶段边界或 guard。',
    `- 情绪转折：${voice.emotion.guidance}`,
    `- 对白交锋：${voice.dialogue.guidance}`,
    `- 表情/语气/环境压力：${voice.embodiment.guidance}`,
    `- 动作执行：${voice.action.guidance}`,
    `- 短内心：${voice.interiority.guidance}`,
    '- 禁止写法：不要写成历史文献、履约报告、规则说明、总结梗概或动作流水账。'
  ].filter(hasText).join('\n')
}

export const NARRATIVE_VOICE_FORBIDDEN_KEYS = [...FORBIDDEN_FACT_STAGE_KEYS]
