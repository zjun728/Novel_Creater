const TRUSTED_FACT_STATUSES = new Set(['trusted', 'accepted', 'committed', 'final', 'finalized'])
const UNTRUSTED_FACT_STATUSES = new Set([
  'failed',
  'failure',
  'unfinalized',
  'draft',
  'drafting',
  'candidate',
  'ai_candidate',
  'empty',
  'empty_chapter',
  'plan_only',
  'pending',
  'pending_review',
  'tainted',
  'quarantined',
  'rejected',
  'unknown',
  'degraded',
  'blocked'
])

function hasText(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function asArray(value) {
  if (Array.isArray(value)) return value
  return hasText(value) ? [value] : []
}

function compactText(value, limit = 260) {
  if (!hasText(value)) return ''
  const normalized = String(value).replace(/\s+/g, ' ').trim()
  return normalized.length > limit ? `${normalized.slice(0, limit)}...` : normalized
}

function lowerStatus(value) {
  return String(value || '').trim().toLowerCase()
}

function factText(item) {
  if (typeof item === 'string') return item
  return item?.text || item?.content || item?.summary || item?.fact || item?.description || ''
}

function factStatus(item) {
  if (typeof item === 'string') return ''
  const provenance = item?.provenance || item?.sourceProvenance || {}
  return lowerStatus(
    item?.commitStatus ||
    item?.commit_status ||
    item?.status ||
    provenance.commitStatus ||
    provenance.commit_status ||
    ''
  )
}

function factTrustLevel(item) {
  if (typeof item === 'string') return ''
  const provenance = item?.provenance || item?.sourceProvenance || {}
  return lowerStatus(
    item?.trustLevel ||
    item?.trust_level ||
    provenance.trustLevel ||
    provenance.trust_level ||
    ''
  )
}

function factRunStatus(item) {
  if (typeof item === 'string') return ''
  const provenance = item?.provenance || item?.sourceProvenance || {}
  return lowerStatus(
    item?.runStatus ||
    item?.run_status ||
    item?.versionType ||
    item?.version_type ||
    item?.sourceType ||
    item?.source_type ||
    provenance.runStatus ||
    provenance.run_status ||
    provenance.versionType ||
    provenance.version_type ||
    provenance.sourceType ||
    provenance.source_type ||
    ''
  )
}

function normalizeFacts(items = [], options = {}) {
  const seen = new Set()
  return asArray(items)
    .map(item => {
      const isPlainString = typeof item === 'string'
      const status = isPlainString && options.allowPlainString
        ? 'committed'
        : factStatus(item)
      const trustLevel = factTrustLevel(item)
      const runStatus = factRunStatus(item)
      return {
        text: compactText(factText(item), 220),
        sourceChapterNum: item?.sourceChapterNum ?? item?.source_chapter_num ?? item?.provenance?.sourceChapterNum ?? null,
        sourceVersionId: item?.sourceVersionId ?? item?.source_version_id ?? item?.provenance?.sourceVersionId ?? '',
        commitStatus: status,
        trustLevel,
        runStatus,
        isPlainString
      }
    })
    .filter(item => {
      if (!item.text) return false
      if (item.isPlainString) return Boolean(options.allowPlainString)
      if (UNTRUSTED_FACT_STATUSES.has(lowerStatus(item.commitStatus))) return false
      if (UNTRUSTED_FACT_STATUSES.has(lowerStatus(item.trustLevel))) return false
      if (UNTRUSTED_FACT_STATUSES.has(lowerStatus(item.runStatus))) return false
      return TRUSTED_FACT_STATUSES.has(lowerStatus(item.commitStatus)) ||
        lowerStatus(item.trustLevel) === 'trusted'
    })
    .filter(item => {
      const key = item.text
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .map(({ isPlainString, trustLevel, runStatus, ...item }) => item)
    .slice(0, 8)
}

function pickFirst(...values) {
  return values.flatMap(asArray).find(hasText) || ''
}

function formatConflictPair(context = {}) {
  const goal = context.chapterGoal || {}
  if (hasText(goal.conflict)) return compactText(goal.conflict)
  const characterNames = asArray(context.characters)
    .map(character => character?.name || character?.entityName || character?.entity_name || '')
    .filter(hasText)
    .slice(0, 2)
  if (characterNames.length >= 2) return `${characterNames[0]} vs ${characterNames[1]}`
  if (characterNames.length === 1) return `${characterNames[0]} vs 当前压力`
  return '主角 vs 当前阻力'
}

function safeRestrictionText(restrictions = []) {
  return asArray(restrictions)
    .map(item => compactText(item, 120))
    .filter(hasText)
    .filter(item => !/(未来第|后续第|roadmap|futureRoadmap|最终揭露|幕后人是|真凶是|不能公开[：:]|不能揭露[：:]|不得公开[：:])/iu.test(item))
    .slice(0, 4)
}

export function buildSceneExecutionCard(context = {}) {
  const goal = context.chapterGoal || {}
  const stage = context.creativeStageContract || {}
  const currentStage = context.currentStageCreativeContext || {}
  const allowedFacts = [
    ...normalizeFacts(currentStage.writableFacts),
    ...normalizeFacts(stage.allowedFacts, { allowPlainString: true }),
    ...normalizeFacts(context.stateAuthority?.facts),
    ...normalizeFacts(context.stateAuthority?.canonFacts),
    ...normalizeFacts(context.recentFacts)
  ].filter((item, index, all) => all.findIndex(other => other.text === item.text) === index).slice(0, 8)
  const sceneObjective = pickFirst(
    goal.goal,
    stage.allowedScope?.goal,
    context.creativeBoundary,
    '完成当前阶段允许的核心场景推进。'
  )
  const conflictPair = formatConflictPair(context)
  const emotionalTurn = pickFirst(
    goal.emotionalTurn,
    goal.emotionalBeat,
    goal.turn,
    stage.allowedScope?.turn,
    '角色从原有判断进入新的压力、误判或关系变化。'
  )
  const stopPoint = [
    goal.stopPoint,
    goal.handoff,
    currentStage.stageBoundary?.stopPoint,
    stage.stopPoint,
    stage.stopAt,
    context.stopPoint
  ].filter(hasText).map(item => compactText(item, 140))
  const stopPointText = [...new Set(stopPoint)].join('；') || '停在当前阶段边界内，不提前解决后续路线。'
  const restrictions = safeRestrictionText([
    ...asArray(stage.safeCreativeRestrictions),
    ...asArray(stage.forbiddenDirections),
    ...asArray(context.forbiddenDirections),
    currentStage.stageBoundary?.forbidden
  ])

  const card = {
    schemaVersion: 'scene-execution-card-v1',
    scope: 'current_stage_only',
    sceneObjective: compactText(sceneObjective),
    conflictPair,
    emotionalTurn: compactText(emotionalTurn),
    dialogueTask: `让 ${conflictPair} 在至少两轮直接引号对白里互相试探、逼问、否认或截断；每轮对白都要带冲突或潜台词。`,
    physicalPressure: compactText(
      pickFirst(
        goal.physicalPressure,
        context.volumeStage?.mainConflict,
        context.volumeStage?.currentSummary,
        '用可见物件、空间限制、时间压力或身体状态逼迫角色做选择。'
      )
    ),
    facialVoiceCues: '至少写出一处表情/眼神/喉咙/呼吸/语气变化，让读者看见情绪而不是只读到标签。',
    environmentalPressure: compactText(
      pickFirst(
        goal.environmentalPressure,
        context.volumeStage?.worldPressure,
        '环境只写最贴近压力的一两处，让空间、声音、温度或物件状态改变人物选择。'
      )
    ),
    allowedFacts,
    stopPoint: compactText(stopPointText),
    forbiddenSummary: restrictions.length
      ? restrictions.join('；')
      : '不得越过本章停靠点；后续未开放信息不在当前场戏展开。',
    externalCheckSummary: '后续未开放信息由外部校验；本卡只描述当前场戏可写内容。'
  }

  return card
}

export function formatSceneExecutionCardForPrompt(card = {}) {
  if (!card || card.schemaVersion !== 'scene-execution-card-v1') return ''
  const factLines = asArray(card.allowedFacts)
    .map(fact => `  - ${compactText(fact.text || fact, 180)}`)
    .filter(hasText)
    .join('\n')
  return [
    '## Scene Execution Card',
    '- 范围：只执行当前阶段可写内容；事实以上方可信状态为准。',
    `- 场景目标：${card.sceneObjective}`,
    `- 冲突双方：${card.conflictPair}`,
    `- 情绪转折：${card.emotionalTurn}`,
    `- 对白任务：${card.dialogueTask}`,
    '- 对白交锋：至少两轮直接引号对白；必须包含质问、否认、反击、截断或遮掩。',
    '- 情绪落地：本场必须出现一次情绪转折，写出角色判断从哪里变到哪里。',
    '- 短内心：写一处短内心或误判变化，控制在一句内，并让外界动作立刻打断或验证它。',
    `- 身体/空间压力：${card.physicalPressure}`,
    `- 表情/语气线索：${card.facialVoiceCues}`,
    `- 环境压力：${card.environmentalPressure}`,
    factLines ? `- 可写事实：\n${factLines}` : '',
    `- 停靠点：${card.stopPoint}`,
    `- 禁止越界摘要：${card.forbiddenSummary}`,
    '- 后续未开放信息不进入正文创作。'
  ].filter(hasText).join('\n')
}
