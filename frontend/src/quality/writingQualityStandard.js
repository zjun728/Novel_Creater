export const AI_TRACE_DIMENSIONS = [
  {
    id: 'emotionalPresentation',
    label: '情绪呈现',
    description: '情绪被直接命名、开关式切换，替代动作、生理反应、停顿、回避和余波。'
  },
  {
    id: 'informationReveal',
    label: '信息露出',
    description: '真相、设定、规则以说明书方式倾倒，而不是通过证据、误判、物件反应和关系变化露出。'
  },
  {
    id: 'innerActivity',
    label: '内心活动',
    description: '危机中的内心被写成清单、计划书或干净总结，缺少迟疑、碎片、反复和自我打断。'
  },
  {
    id: 'rhythmStructure',
    label: '节奏结构',
    description: '连续短句独段、段首反复点名、段落过碎或节奏没有呼吸。'
  },
  {
    id: 'languageTexture',
    label: '语言质感',
    description: '模板化章尾、机械反差句、套话意象、无效数字或过度工整的表达削弱小说质感。'
  }
]

export const HUMAN_TEXTURE_DIMENSIONS = [
  { id: 'realScene', label: '真实场景', description: '场景有具体物、气味、秩序和不完全服务剧情的生活痕迹。' },
  { id: 'characterReaction', label: '角色反应', description: '人物会迟疑、误判、遮掩、反复或用动作泄露状态。' },
  { id: 'costProcess', label: '代价过程', description: '选择和失去有发生过程、残留和后续影响。' },
  { id: 'naturalBlank', label: '自然留白', description: '信息不一次讲透，允许读者在证据和沉默中拼合。' },
  { id: 'imperfectHumanFlavor', label: '不工整的人味', description: '人物表达和行动允许不漂亮、不完整、不总是服务主线。' },
  { id: 'informationReveal', label: '信息露出', description: '信息由行动、证据、关系摩擦和失败验证带出。' },
  { id: 'relationshipFriction', label: '关系摩擦', description: '配角有自己的顾虑、利益、误判和不配合。' },
  { id: 'rhythmBreath', label: '节奏呼吸', description: '章节有推进、停顿、观察、闲笔和余波的交替。' }
]

export const NARRATIVE_READABILITY_GATES = [
  { id: 'plotIncrement', label: '有效剧情增量', description: '本章是否产生读者能复述的新事件、新信息、新代价或新局面。' },
  { id: 'externalEvent', label: '真实外部事件', description: '本章是否有发生在人物外部的可见事件，而不是只停留在感知和理解。' },
  { id: 'concreteAction', label: '具体人物行动', description: '人物是否通过离开、进入、交出、拒绝、烧毁、追击、对峙等动作推进故事。' },
  { id: 'stateChange', label: '关系/地点/态势变化', description: '关系、地点、敌我态势、目标或线索状态是否发生可追踪变化。' },
  { id: 'irreversibleChange', label: '不可逆变化', description: '本章是否有不能被下一段轻易撤销的具体结果、代价或失效。' },
  { id: 'paragraphRepetition', label: '段落级重复', description: '连续段落或成组段落是否只是替换少数名词，形成近似复制。' },
  { id: 'templateRepetition', label: '模板级重复', description: '高频句式、段首、概念链或固定表达是否支配了正文。' },
  { id: 'conceptSpinning', label: '概念空转', description: '规则、结构、记忆、答案、问题等抽象词互相替换，但没有剧情增量。' },
  { id: 'disguisedThemeRepetition', label: '主题伪装重复', description: '看似换主题，实则仍围绕同一物象、状态或冲突模式循环。' },
  { id: 'readabilityClarity', label: '读者复述清晰度', description: '普通读者读完能否说清本章真实发生了什么。' }
]

export const QUALITY_LEVELS = [
  { id: 'low', label: '极轻', rank: 1 },
  { id: 'medium', label: '中等', rank: 2 },
  { id: 'high', label: '较重', rank: 3 },
  { id: 'severe', label: '极重', rank: 4 }
]

export const QUALITY_ISSUE_DEFINITIONS = [
  {
    type: 'not_x_but_y',
    aliases: ['contrast_sentence', 'ai_contrast', 'routine_contrast'],
    label: '机械反差句',
    aiTraceDimensions: ['languageTexture'],
    humanTextureDimensions: ['imperfectHumanFlavor'],
    auditHints: ['单次出现不是问题；高频出现并替代真实感受、动作和场景变化时才标记。']
  },
  {
    type: 'repetitive_subject_opening',
    aliases: ['lead_subject_repeat', 'leading_subject_repeat'],
    label: '段首反复主角名',
    aiTraceDimensions: ['rhythmStructure', 'languageTexture'],
    humanTextureDimensions: ['rhythmBreath'],
    auditHints: ['多个连续段落都以同一角色姓名起句，读感像机械分镜时才标记。']
  },
  {
    type: 'prose_rhythm_flat',
    aliases: ['short_sentence_streak', 'short_paragraph_streak', 'pacing'],
    label: '连续短句独段',
    aiTraceDimensions: ['rhythmStructure'],
    humanTextureDimensions: ['rhythmBreath'],
    auditHints: ['战斗、惊惧、断裂可短句密集；整章替代正常叙事段落时才升级。']
  },
  {
    type: 'info_dump',
    aliases: ['information_dump', 'exposition_dump'],
    label: '信息倾倒',
    aiTraceDimensions: ['informationReveal'],
    humanTextureDimensions: ['informationReveal', 'naturalBlank'],
    auditHints: ['系统流/规则流允许提示，但不允许说明书式长篇交底替代证据链。']
  },
  {
    type: 'system_or_villain_monologue',
    aliases: ['villain_monologue', 'system_monologue'],
    label: '反派/系统交底',
    aiTraceDimensions: ['informationReveal'],
    humanTextureDimensions: ['informationReveal', 'relationshipFriction'],
    auditHints: ['只有当旁白、系统、导师或反派连续解释并削弱冲突时才标记。']
  },
  {
    type: 'emotion_label',
    aliases: ['surface_emotion', 'emotional_logic'],
    label: '情绪贴标签',
    aiTraceDimensions: ['emotionalPresentation'],
    humanTextureDimensions: ['characterReaction'],
    auditHints: ['高频直接命名情绪，并替代动作、生理反应、停顿和余波时才标记。']
  },
  {
    type: 'template_ending',
    aliases: ['ending_template', 'chapter_tail_template'],
    label: '模板化章尾',
    aiTraceDimensions: ['languageTexture', 'rhythmStructure'],
    humanTextureDimensions: ['naturalBlank', 'rhythmBreath'],
    auditHints: ['多章反复用抽象总结、转身、闭眼、黑暗意象收束时标记。']
  },
  {
    type: 'decorative_number',
    aliases: ['invalid_number', 'decorative_data'],
    label: '无效数字',
    aiTraceDimensions: ['languageTexture', 'informationReveal'],
    humanTextureDimensions: ['realScene'],
    auditHints: ['数字精确但不影响风险、选择、误判、代价或后果时标记。']
  },
  {
    type: 'skipped_loss',
    aliases: ['cost_skipped', 'loss_skipped'],
    label: '代价跳过',
    aiTraceDimensions: ['emotionalPresentation', 'innerActivity'],
    humanTextureDimensions: ['costProcess', 'characterReaction'],
    auditHints: ['重大失去只给结果，没有过程、残留或迟发反应时标记。']
  },
  {
    type: 'tool_character',
    aliases: ['functional_character', 'npc_tool'],
    label: '配角工具化',
    aiTraceDimensions: ['innerActivity', 'informationReveal'],
    humanTextureDimensions: ['relationshipFriction', 'characterReaction', 'imperfectHumanFlavor'],
    auditHints: ['配角只递送信息、道具或阻碍，没有自己的欲望、顾虑、误判和选择时标记。']
  },
  {
    type: 'overfunctional_density',
    aliases: ['functional_density'],
    label: '功能过满',
    aiTraceDimensions: ['rhythmStructure'],
    humanTextureDimensions: ['realScene', 'rhythmBreath', 'imperfectHumanFlavor'],
    auditHints: ['每段都推进、解释或制造钩子，没有沉默、闲笔和生活痕迹时标记。']
  },
  {
    type: 'cliche_imagery',
    aliases: ['cliche_image'],
    label: '套话意象',
    aiTraceDimensions: ['languageTexture'],
    humanTextureDimensions: ['realScene'],
    auditHints: ['通用意象反复出现且没有角色视角的独特观察时标记。']
  },
  {
    type: 'sensory_checklist',
    aliases: ['sensory_list'],
    label: '感官打勾',
    aiTraceDimensions: ['languageTexture'],
    humanTextureDimensions: ['realScene'],
    auditHints: ['五感平均罗列、每种只写一层，像完成清单时标记。']
  },
  {
    type: 'ai_tone',
    aliases: ['quality'],
    label: '综合 AI 痕迹',
    aiTraceDimensions: ['languageTexture', 'rhythmStructure'],
    humanTextureDimensions: ['rhythmBreath'],
    auditHints: ['只作综合类型；优先映射到更具体的统一维度。']
  }
]

export const NARRATIVE_READABILITY_ISSUE_DEFINITIONS = [
  {
    type: 'no_plot_increment',
    aliases: ['plot_increment_missing', 'no_story_increment'],
    label: '缺少有效剧情增量',
    gateDimensions: ['plotIncrement', 'readabilityClarity'],
    aiTraceDimensions: ['informationReveal', 'languageTexture'],
    humanTextureDimensions: ['realScene', 'costProcess'],
    severity: 'major'
  },
  {
    type: 'no_external_event',
    aliases: ['external_event_missing', 'no_real_event'],
    label: '缺少真实外部事件',
    gateDimensions: ['externalEvent', 'readabilityClarity'],
    aiTraceDimensions: ['innerActivity', 'rhythmStructure'],
    humanTextureDimensions: ['realScene', 'characterReaction'],
    severity: 'major'
  },
  {
    type: 'no_concrete_action',
    aliases: ['concrete_action_missing', 'action_missing'],
    label: '缺少具体人物行动',
    gateDimensions: ['concreteAction', 'readabilityClarity'],
    aiTraceDimensions: ['innerActivity'],
    humanTextureDimensions: ['characterReaction', 'costProcess'],
    severity: 'major'
  },
  {
    type: 'no_irreversible_change',
    aliases: ['irreversible_change_missing'],
    label: '不可逆变化缺失',
    gateDimensions: ['irreversibleChange', 'stateChange'],
    aiTraceDimensions: ['informationReveal', 'innerActivity'],
    humanTextureDimensions: ['costProcess', 'relationshipFriction'],
    severity: 'major'
  },
  {
    type: 'abstract_irreversible_change',
    aliases: ['abstract_change', 'abstract_progression'],
    label: '不可逆变化过于抽象',
    gateDimensions: ['irreversibleChange', 'plotIncrement'],
    aiTraceDimensions: ['informationReveal', 'innerActivity'],
    humanTextureDimensions: ['costProcess'],
    severity: 'major'
  },
  {
    type: 'loop_exit_missing',
    aliases: ['no_loop_exit', 'still_observing_loop'],
    label: '未离开上一循环',
    gateDimensions: ['disguisedThemeRepetition', 'plotIncrement', 'stateChange'],
    aiTraceDimensions: ['rhythmStructure', 'languageTexture'],
    humanTextureDimensions: ['realScene', 'rhythmBreath'],
    severity: 'major'
  },
  {
    type: 'paragraph_level_repetition',
    aliases: ['paragraph_repetition', 'paragraph_copy_loop'],
    label: '段落级重复',
    gateDimensions: ['paragraphRepetition', 'readabilityClarity'],
    aiTraceDimensions: ['rhythmStructure', 'languageTexture'],
    humanTextureDimensions: ['rhythmBreath', 'imperfectHumanFlavor'],
    severity: 'critical'
  },
  {
    type: 'template_level_repetition',
    aliases: ['template_repetition', 'sentence_template_loop'],
    label: '模板级重复',
    gateDimensions: ['templateRepetition', 'readabilityClarity'],
    aiTraceDimensions: ['rhythmStructure', 'languageTexture'],
    humanTextureDimensions: ['rhythmBreath', 'imperfectHumanFlavor'],
    severity: 'major'
  },
  {
    type: 'concept_spinning',
    aliases: ['concept_loop', 'abstract_loop'],
    label: '概念空转',
    gateDimensions: ['conceptSpinning', 'plotIncrement', 'readabilityClarity'],
    aiTraceDimensions: ['informationReveal', 'languageTexture'],
    humanTextureDimensions: ['realScene', 'costProcess', 'naturalBlank'],
    severity: 'critical'
  },
  {
    type: 'disguised_theme_repetition',
    aliases: ['theme_repetition', 'same_pattern_loop'],
    label: '主题伪装重复',
    gateDimensions: ['disguisedThemeRepetition', 'plotIncrement'],
    aiTraceDimensions: ['rhythmStructure', 'languageTexture'],
    humanTextureDimensions: ['rhythmBreath', 'realScene'],
    severity: 'major'
  },
  {
    type: 'unreadable_chapter',
    aliases: ['reader_cannot_retell', 'readability_fail'],
    label: '读者无法复述本章事件',
    gateDimensions: ['readabilityClarity', 'plotIncrement', 'externalEvent'],
    aiTraceDimensions: ['informationReveal', 'languageTexture', 'rhythmStructure'],
    humanTextureDimensions: ['realScene', 'characterReaction', 'costProcess'],
    severity: 'critical'
  },
  {
    type: 'narrative_progression_fail',
    aliases: ['progression_gate_fail', 'progression_fail'],
    label: '叙事推进门禁失败',
    gateDimensions: ['plotIncrement', 'irreversibleChange', 'readabilityClarity'],
    aiTraceDimensions: ['rhythmStructure', 'languageTexture'],
    humanTextureDimensions: ['costProcess', 'rhythmBreath'],
    severity: 'critical'
  },
  {
    type: 'same_object_loop',
    aliases: ['same_scene_loop', 'object_loop'],
    label: '同一物象/场景循环',
    gateDimensions: ['disguisedThemeRepetition', 'plotIncrement', 'stateChange'],
    aiTraceDimensions: ['rhythmStructure', 'languageTexture'],
    humanTextureDimensions: ['realScene', 'rhythmBreath'],
    severity: 'major'
  },
  {
    type: 'main_goal_drift',
    aliases: ['goal_drift', 'mainline_drift'],
    label: '主线目标漂移',
    gateDimensions: ['plotIncrement', 'stateChange', 'readabilityClarity'],
    aiTraceDimensions: ['informationReveal'],
    humanTextureDimensions: ['costProcess', 'relationshipFriction'],
    severity: 'major'
  },
  {
    type: 'not_x_but_y_chain',
    aliases: ['contrast_chain', 'concept_contrast_chain'],
    label: '不是X是Y概念链',
    gateDimensions: ['templateRepetition', 'conceptSpinning'],
    aiTraceDimensions: ['languageTexture', 'rhythmStructure'],
    humanTextureDimensions: ['imperfectHumanFlavor', 'rhythmBreath'],
    severity: 'major'
  }
]

const ISSUE_DEFINITION_BY_TYPE = new Map()
const NARRATIVE_ISSUE_DEFINITION_BY_TYPE = new Map()

for (const definition of NARRATIVE_READABILITY_ISSUE_DEFINITIONS) {
  NARRATIVE_ISSUE_DEFINITION_BY_TYPE.set(definition.type, definition)
  for (const alias of definition.aliases || []) NARRATIVE_ISSUE_DEFINITION_BY_TYPE.set(alias, definition)
}

for (const definition of [...QUALITY_ISSUE_DEFINITIONS, ...NARRATIVE_READABILITY_ISSUE_DEFINITIONS]) {
  ISSUE_DEFINITION_BY_TYPE.set(definition.type, definition)
  for (const alias of definition.aliases || []) ISSUE_DEFINITION_BY_TYPE.set(alias, definition)
}

export const AI_TRACE_ISSUE_TYPES = QUALITY_ISSUE_DEFINITIONS.map(item => item.type)

function unique(values = []) {
  return [...new Set(values.filter(Boolean))]
}

export function getQualityIssueDefinition(type) {
  return ISSUE_DEFINITION_BY_TYPE.get(String(type || '').trim()) || null
}

export function getNarrativeReadabilityIssueDefinition(type) {
  return NARRATIVE_ISSUE_DEFINITION_BY_TYPE.get(String(type || '').trim()) || null
}

export function mapIssueTypeToQualitySignals(type) {
  const definition = getQualityIssueDefinition(type)
  if (!definition) {
    return {
      issueTypes: [],
      aiTraceDimensions: [],
      humanTextureDimensions: [],
      narrativeReadabilityDimensions: []
    }
  }
  return {
    issueTypes: [definition.type],
    aiTraceDimensions: [...(definition.aiTraceDimensions || [])],
    humanTextureDimensions: [...(definition.humanTextureDimensions || [])],
    narrativeReadabilityDimensions: [...(definition.gateDimensions || definition.narrativeReadabilityDimensions || [])]
  }
}

export function getDimensionLabel(id) {
  return [...AI_TRACE_DIMENSIONS, ...HUMAN_TEXTURE_DIMENSIONS, ...NARRATIVE_READABILITY_GATES]
    .find(item => item.id === id)?.label || id
}

export function getQualityLevelLabel(id) {
  return QUALITY_LEVELS.find(item => item.id === id)?.label || id
}

export function getRhythmQualitySignals(analysis = {}) {
  const issueTypes = []
  if (Number(analysis.shortParagraphRate || 0) >= 0.32 || Number(analysis.maxShortStreak || 0) >= 6) {
    issueTypes.push('prose_rhythm_flat')
  }
  if (Number(analysis.aiContrastCount || 0) > 6) issueTypes.push('not_x_but_y')
  if (Number(analysis.maxSameLeadingSubjectCount || 0) >= 5) issueTypes.push('repetitive_subject_opening')

  const mapped = issueTypes.map(mapIssueTypeToQualitySignals)
  return {
    issueTypes: unique(issueTypes),
    aiTraceDimensions: unique(mapped.flatMap(item => item.aiTraceDimensions)),
    humanTextureDimensions: unique(mapped.flatMap(item => item.humanTextureDimensions)),
    narrativeReadabilityDimensions: unique(mapped.flatMap(item => item.narrativeReadabilityDimensions))
  }
}
