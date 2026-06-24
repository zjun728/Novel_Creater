import {
  AI_TRACE_DIMENSIONS,
  HUMAN_TEXTURE_DIMENSIONS,
  NARRATIVE_READABILITY_GATES,
  NARRATIVE_READABILITY_ISSUE_DEFINITIONS,
  QUALITY_ISSUE_DEFINITIONS
} from './writingQualityStandard.js'

export function buildGenerationQualityBrief() {
  return [
    '## 正文写作方向（真人感优先）',
    '- 真实场景：让冲突落在具体地点、物件、气味、秩序和生活痕迹里。',
    '- 角色反应与人物选择：人物带着欲望、误判、遮掩和犹豫行动，身体反应先于解释。',
    '- 代价过程：选择带来的损失要有发生过程、残留和后续影响。',
    '- 自然留白与信息留白：真相通过证据、行动失败、沉默、误会和未完成露出，不一次讲透。',
    '- 不工整的人味：允许半句话、无用动作、跑题和不漂亮的反应。',
    '- 关系摩擦：配角带着顾虑、利益和不配合进入场景，不只负责解释设定。',
    '- 节奏呼吸：自然段落承载完整动作链、环境反应和人物反应；保留必要短句，但短句不能连续成片，不要写成分镜清单。',
    '',
    '语言节奏：段首不要连续使用同一主语；用动作承接、物件状态、环境变化、对白停顿或心理余波自然换段。',
    '段落节奏：常规叙事段建议 2-5 句，承载动作、因果、环境和人物反应；短句只用于爆点、恐惧、反转、沉默或停顿。',
    '反差句式：“不是X，是Y”只当偶尔节奏变化，目标 0-2 次；抽象判断优先变成可见场景变化、人物反应、对话错位或物件状态。',
    '轻量底线：章节要从感知、观察和理解转入人物行动、外部事件、关系摩擦或代价过程。',
    '信息露出：反派、系统或神秘声音不要主动完整交底；信息通过行动、阻挠、误导、物件反应和代价露出。',
    '真相露出：多用物件异常反应、主角行动失败、敌方阻挠或误导、代价发生、半句对话、沉默、打断，以及主角自己拼合证据。',
    '配角进入场景时带着自身目的、恐惧、迟疑、矛盾或损失，不只是解释设定；对话保留谎言、回避和未说完的部分。'
  ].join('\n')
}

export function buildAntiLoopPlanningBrief() {
  return [
    '## antiLoopPlanningBrief',
    '- 在生成下一章小纲前，动态检查最近 3-5 章的 repeatedObjects、repeatedLocations、repeatedActions、repeatedConcepts、repeatedSentencePatterns 和 repeatedConflictModes。',
    '- 动态重复证据需要过滤主角名、核心角色名、常用动作、高频虚词和题材必需词；这些词不能单独作为循环核心证据。',
    '- 除了物象重复，还要检查 sameEventPatternLoop：即使物象变化，只要仍是“进入编号场景 -> 观看记忆/凭证 -> 得到抽象结论 -> 选择 -> 离开”，也算结构循环。',
    '- 如果任意一组具体物象、地点、道具、场景模式、冲突类型或事件模板持续高频，下一章必须强制跳出循环。',
    '- 转向必须至少包含一个：newLocation、newCharacterAction、newEnemyPressure、oldClueConclusion、relationshipBreakOrRebuild、itemInvalidated、ruleFalsified、irreversibleChoice。',
    '- 连续编号结构规则：编号门、编号档案、编号画布、编号凭证可以建立 1-2 次规则；第三次必须变化、反转、跳切、合并、升级或被外部压力打断。',
    '- 禁止继续写：继续观察、继续触摸、继续确认、某个图案/状态又变化、某条规则又展开、某种损失又发生、主角又感觉到某种抽象结构。'
  ].join('\n')
}

export function buildBeatPlanProgressionGateBrief() {
  return [
    '## beatPlanProgressionGate',
    '- 小纲进入正文前要能回答：本章发生什么、人物要什么、冲突从哪里来、外部压力如何进入、代价是什么、发生了什么不可逆变化、结尾交给下一章什么。',
    '- 不可逆变化要具体，不能写成“主角更理解某条规则”“主角感受到更深真相”“某个物件显示更多信息”“某种结构继续变化”。',
    '- 合格变化示例：角色离开旧地点进入新地点；某段关系被公开切断；某个道具被毁坏并永久失效；敌方第一次主动出手；主角交出明确代价换取资格；反复出现的旧线索被证伪。',
    '- 小纲要对齐当前卷目标，但不需要把卷目标写成单独字段；让本章的行动、证据、阻挠、误导、关系摩擦或代价自然接上卷目标。',
    '- 小纲如果没有真实外部事件、具体人物行动和不可逆变化，应修复小纲，不进入正文生成。'
  ].join('\n')
}

export function buildNarrativeReadabilityQaRubric() {
  const gateLines = NARRATIVE_READABILITY_GATES.map(item => `- ${item.id} / ${item.label}：${item.description}`)
  const issueLines = NARRATIVE_READABILITY_ISSUE_DEFINITIONS.map(item => {
    const aliases = item.aliases?.length ? `；兼容旧类型：${item.aliases.join(', ')}` : ''
    return `- ${item.type} / ${item.label}${aliases}；维度：${item.gateDimensions.join(', ')}`
  })
  return [
    '## 叙事推进与可读性闸',
    '这是独立于 AI 风格五维和真人感八项的第三层质量闸，用于识别抽象循环型失控文本。',
    '需要输出 narrativeReadabilityGate、irreversibleChange、hasExternalEvent、hasConcreteAction、canReaderRetell、notXButYCount、narrativeReadabilityDimensions。',
    '',
    '### 闸门维度',
    ...gateLines,
    '',
    '### 问题类型',
    ...issueLines
  ].join('\n')
}

export function buildChapterAuditQualityRubric() {
  const aiLines = AI_TRACE_DIMENSIONS.map(item => `- ${item.id} / ${item.label}：${item.description}`)
  const humanLines = HUMAN_TEXTURE_DIMENSIONS.map(item => `- ${item.id} / ${item.label}：${item.description}`)
  const issueLines = QUALITY_ISSUE_DEFINITIONS.map(item => {
    const aliases = item.aliases?.length ? `；兼容旧类型：${item.aliases.join(', ')}` : ''
    return `- ${item.type} / ${item.label}${aliases}；提示：${item.auditHints.join('；')}`
  })

  return [
    '## 统一写作质量审稿 Rubric',
    '本节是 AI 痕迹、真人感与叙事推进可读性审稿的唯一标准入口。',
    '审稿必须输出并尽量填充以下字段：aiTraceLevel、humanTextureLevel、aiTraceDimensions、humanTextureDimensions、topQualityRisks、qualityAdvice、narrativeReadabilityGate、narrativeReadabilityDimensions。',
    '等级只能使用 low / medium / high / severe；中文含义为 极轻 / 中等 / 较重 / 极重。',
    '',
    '### AI 痕迹五维',
    ...aiLines,
    '',
    '### 真人感八项',
    ...humanLines,
    '',
    buildNarrativeReadabilityQaRubric(),
    '',
    '### 旧 issue type 到统一维度',
    ...issueLines,
    '',
    '### 判定原则',
    '- 不因单次出现情绪词、系统提示、短句或反差句就判 AI。',
    '- 只有高频、替代真实呈现、影响读感时才标记为 AI 痕迹。',
    '- 系统流/规则流允许系统提示，但不允许说明书式长篇交底。',
    '- 真人感不足通常作为建议或 warning，不直接阻断定稿。',
    '- 叙事推进与可读性闸可独立 hard fail：严重段落重复、概念空转、不可读、无真实事件且无不可逆变化时，不能只作为 warning。',
    '- 只有达到 severe / 极重，并且明显影响基本阅读质量时，才作为质量阻断候选。'
  ].join('\n')
}

export function buildRealisticQaQualityRubric() {
  return [
    '## 统一质量统计口径',
    '- 每章 AI 痕迹等级：读取或计算 aiTraceLevel。',
    '- 每章真人感等级：读取或计算 humanTextureLevel。',
    '- 每章五维/八项命中情况：统计 aiTraceDimensions 和 humanTextureDimensions。',
    '- 每章叙事推进与可读性闸：统计 narrativeReadabilityGate、irreversibleChange、hasExternalEvent、hasConcreteAction、canReaderRetell。',
    '- 本轮最高频问题维度：按统一维度聚合，包括 narrativeReadabilityDimensions，不再按散落正则单独分类。',
    '- 多章推进 QA：输出 recent5RepeatedObjects、recent5RepeatedActions、recent5RepeatedConcepts、eventPatternLoops、sameSceneOrObjectLoop、sameEventPatternLoop、mainGoalDrift、consecutiveNoExternalEvent、planningDegraded、recommendPauseGeneration。',
    '- 风险来源必须区分：词频重复、事件结构重复、卷目标漂移、本地安全重建连续发生和检测误伤。',
    '- 是否建议人工精修：high/severe 或多维高频命中时建议。',
    '- 是否影响继续生成：叙事推进 hard fail、severe 重复空转、连续章节无真实外部事件时提示暂停。',
    '- 多章趋势是否恶化：比较本轮章节 high/severe 占比、重复维度和推进闸失败数是否上升。'
  ].join('\n')
}

export function buildProseRhythmRepairBrief() {
  return [
    '节奏修订只处理局部句式节奏问题：连续短句独段、段首反复主角名、机械句式、过度碎片化段落。',
    '这些结果统一映射到 rhythmStructure / 节奏结构 和 languageTexture / 语言质感；不另立 AI 腔标准。',
    '如果检测到段落级复制、概念空转或不可读整章循环，只记录为叙事推进与可读性闸问题，不由局部节奏修订强行改写。',
    '不要新增剧情、人物、设定或结论；保留事件顺序、人物选择、对白含义、结尾钩子和已确认设定。'
  ].join('\n')
}
