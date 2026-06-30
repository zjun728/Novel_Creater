import {
  ALLOWED_STORY_BLOCK_REVIEW_DECISIONS,
  normalizeStoryBlockReviewDecision,
  storyBlockSnapshotBrief
} from '../utils/storyBlockSnapshot.js'

function compactJson(value) {
  return JSON.stringify(value || {}, null, 2)
}

function listLines(items = []) {
  return (Array.isArray(items) ? items : [])
    .map(item => typeof item === 'string' ? item : JSON.stringify(item))
    .filter(Boolean)
    .map(item => `- ${item}`)
    .join('\n')
}

export function buildStoryBlockPlanningSystemPrompt() {
  return `你是长篇小说故事块策划。
故事块是分卷目标和当前章小纲之间的剧情任务单元，不是章节容器，也不是固定章节数量。你的任务是规划接下来一段连续剧情的目标、故事功能、压力、阶段和下一章可写入口。
边界：
- 只创建或补充未执行剧情阶段。
- 不写正文。
- 不输出审稿报告。
- 不把章节数量写死。
- 不允许为了每章生成一个新块；块完成必须基于剧情任务自然完成、失败、重大转向或外力打断。
- 不把表层 AI 句式指标当作规划中心。
- stagePlan 通常建议 3-6 个可推进阶段，每个字段必须短；大型任务可以更多，秘境、潜入、追杀、攻防、大案、比赛等可以持续 10 章以上。
- 关系任务字段只辅助故事变好看：记录一段人物关系如何轻微变化，不作为审稿硬闸，不扩写成正文。
- 开局、过渡或短冲突块可以少于 3 个阶段，但必须说明短块原因，并给出后续可承接方向。
- 如果内容过多，优先缩短字段，不要破坏 JSON。
只输出合法 JSON，不要 Markdown，不要解释，不要编号列表。`
}

export function buildStoryBlockPlanningPrompt(context = {}) {
  return `请为当前卷规划一个 active 故事块。
## 当前章节
${compactJson({
  chapterNum: context.chapterNum || null,
  openingHook: context.openingHook || context.seed?.openingHook || '',
  openingAnchor: context.openingAnchor || context.seed?.openingAnchor || context.seed?.openingHook || ''
})}

## 当前卷
${compactJson(context.currentVolume || context.volumeStage || {})}

## 当前卷远端交接点（只能作为卷尾方向，不能作为首个故事块入场状态或 stage-1）
${(context.currentVolume || context.volumeStage || {}).handoffPoint || (context.currentVolume || context.volumeStage || {}).handoff_point || '无'}

## 分卷规划
${compactJson(context.volumePlanning || context.volumes || [])}

## 创作圣经/作品方向
${compactJson(context.bible || {})}

## 近期章节
${listLines(context.recentSummaries || []) || '无'}

## 上一章结尾
${context.previousChapterEnding || '无'}

## 设定和记忆边界
${[context.settingLibrary, context.stateLedger, context.recentFacts].filter(Boolean).map(compactJson).join('\n\n') || '无'}

## 新故事块承接种子
${compactJson(context.newBlockSeed || {})}

输出 JSON：
{
  "title": "短标签",
  "goal": "这段连续剧情要完成什么",
  "storyFunction": "铺垫|施压|揭示|追击|反转|代价兑现|过渡",
  "entryState": "进入故事块时的局面",
  "exitTarget": "自然完成时的目标状态",
  "mainPressure": "主要阻力",
  "keyCharacters": ["人物"],
  "relationshipFocus": "本块重点人物关系，如陆沉舟/小九",
  "relationshipStart": "关系起点，用短句说明当前信任、误会或亏欠",
  "relationshipTask": "本块关系任务：误会|信任|亏欠|交易|救助|隐瞒|背叛之一或相近变化",
  "relationshipEndHint": "期望关系变化，不写成结论保证",
  "sceneVarietyHint": "本块玩法变化，不能只连续潜入/追逃；可选关系对峙、代价后果、信息验证、市井/组织规则观察、主动布局、失败后的修补或低压喘息",
  "stagePlan": [
    {
      "id": "stage-1",
      "purpose": "阶段目的",
      "sceneOrAction": "可写的场景或行动",
      "choice": "人物选择",
      "costOrConsequence": "代价或后果",
      "status": "planned"
    }
  ],
  "nextStageSuggestion": "下一章优先写的阶段",
  "unresolvedQuestions": ["未解决问题"],
  "dontAdvanceYet": ["暂不推进内容"],
  "capacityAssessment": "normal|dense|overloaded",
  "shortBlockReason": "如果 stagePlan 少于 3 个阶段，说明为什么这是短过渡/短冲突块；否则留空"
}

要求：
- 故事块是剧情任务单元，不是章节容器；不允许每章新故事块。
- 新块不能只服务当前章小纲，必须给出后续可承接方向。
- stagePlan 通常写 3-6 个阶段；大型任务可以更多；短过渡、开局或短冲突可以更少，但必须写 shortBlockReason。
- stagePlan 是剧情推进阶段，不等于章节；一章可以完成一个阶段，也可以跨阶段。
- 每个字段用短句，不写正文，不展开对白。
- relationshipFocus、relationshipStart、relationshipTask、relationshipEndHint、sceneVarietyHint 是轻量规划辅助；缺少可靠人物关系时可短写“待定”，不要为了字段扩写剧情。
- relationshipTask 优先让人物产生误会、信任、亏欠、交易、救助、隐瞒或背叛，不要只写“共同找线索”。
- sceneVarietyHint 要给出和连续潜入/追逃不同的场景玩法，例如处理伤口、吃饭、交易、静态压迫、吵架、分赃或小人物闲话。
- 如果近期连续追逃/搜查/撤离占主导，后续阶段优先安排主动布局、关系对峙、代价后果或信息验证之一作为骨架。
- 如果 chapterNum=1 或当前没有近期章节，首个故事块必须从 openingHook/openingAnchor 对应的读者可见开场事件开始。
- 首个故事块的 entryState 和 stage-1 必须是第 1 章实际会看到的开局场景；不得把当前卷 handoffPoint 当作 entryState 或 stage-1。
- 第 1 章首块应围绕开局钩子、主角初始处境、第一处压力、首次异常或第一条线索推进；不要直接跳到卷尾交接点。
- 禁止输出 Markdown、代码块、解释文字、编号列表。
- 如果内容过多，优先缩短字段，不要破坏 JSON。`
}

export function buildStoryBlockPlanningRepairPrompt(rawText = '') {
  return `下面是一段故事块规划模型输出，格式可能不是合法 JSON。请只修复为合法 JSON。
边界：
- 只修复 JSON 语法、代码块包裹、前后缀说明、缺失引号、尾逗号等格式问题。
- 不新增剧情。
- 不扩写正文。
- 不改写已有字段含义。
- 不输出 Markdown，不输出解释。

必须输出这个故事块 schema：
{
  "title": "",
  "goal": "",
  "storyFunction": "",
  "entryState": "",
  "exitTarget": "",
  "mainPressure": "",
  "keyCharacters": [],
  "relationshipFocus": "",
  "relationshipStart": "",
  "relationshipTask": "",
  "relationshipEndHint": "",
  "sceneVarietyHint": "",
  "stagePlan": [
    {
      "id": "stage-1",
      "purpose": "",
      "sceneOrAction": "",
      "choice": "",
      "costOrConsequence": "",
      "status": "planned"
    }
  ],
  "nextStageSuggestion": "",
  "unresolvedQuestions": [],
  "dontAdvanceYet": [],
  "capacityAssessment": "normal",
  "shortBlockReason": ""
}

原始输出：
${String(rawText || '').slice(0, 12000)}`
}

export function buildStoryBlockReviewSystemPrompt() {
  return `你是长篇小说故事块回看编辑。
核心原则：
- 故事块只允许向前滚动。
- 已被小纲引用或定稿章节依赖的目标、入场状态和阶段快照不得回改。
- 已完成阶段只能标记和记录，不能改写。
- 正文超量时，只处理未定稿内容：拆分未定稿内容、顺延后续章节，或开启新故事块承接。
- 不能因为一章结束就返回 complete_current_block 或 open_new_block。
- 返回 complete_current_block 或 open_new_block 必须给出 completionEvidence，证明块目标已完成或失败、角色目标明确转向、场景/任务自然结束、外力打断导致旧块不再适用，或进入新任务/新地点/新敌我态势。
- 如果 completionEvidence 不充分，返回 continue_current_block 或 adjust_remaining_stages。
- 阶段耗尽但块目标未完成时，应补充或调整未执行阶段，而不是直接结束块。
- 如果当前块只覆盖 1 章就结束，不硬拒绝，但必须输出 singleChapterBlockReason。
- 如果输出 stageContinues=true，必须同时输出 stageContinueReason；stageContinueReason 必须说明本阶段为什么没有完成、下一章继续完成哪个具体动作/冲突/选择、本章已经完成了什么且剩下什么。
- 判断阶段是否完成时看故事功能，不逐字验收原阶段措辞；错误信任、低估敌人、被反制、小九被绑、星账代价加剧、行动选择受限等已经完成同等故事功能时，应关闭当前阶段。

允许的 decision 只能是：
${ALLOWED_STORY_BLOCK_REVIEW_DECISIONS.map(item => `- ${item}`).join('\n')}

只输出合法 JSON，不要 Markdown，不要解释。`
}

export function buildStoryBlockReviewPrompt(context = {}) {
  return `请根据本章定稿结果做块级回看。
## 第 ${context.chapterNum || '?'} 章定稿摘要
${context.finalizedSummary || '无'}

## 本章结尾
${context.chapterEnding || '无'}

## block_stage_snapshot（历史判断只能读这个快照）
${compactJson(context.blockStageSnapshot || {})}

## snapshot 摘要
${storyBlockSnapshotBrief(context.blockStageSnapshot || {}) || '无'}

## 当前 live story block（只用于判断未执行阶段，不用于改写历史小纲）
${compactJson(context.storyBlock || {})}

## stage continuation diagnostics
${compactJson({
  stageContinuationDepth: context.stageContinuationDepth ?? 0,
  previousOpenStageId: context.previousOpenStageId || '',
  stageContinuationLimit: 2
})}

## 定稿后提取
${compactJson({
  facts: context.facts || [],
  settingChanges: context.settingChanges || []
})}

判断要求：
- 如果本章完成了 snapshot 当前阶段，可把该阶段记为完成。
- 故事功能等价完成只能关闭 snapshot 当前阶段：不要求正文逐字写出“判断失误”。如果本章已经通过误信/错误信任、低估敌人、被反制、小九被绑、星账代价加剧、行动选择受限、关系或局势不可逆变化等方式完成同等功能，返回 stageContinues=false，并写 settlementDecision="completed_by_equivalent_story_function"、equivalentCompletionScope="current_stage_only"。
- 如果正文触碰了后续 stage 内容，只记录 futureStageTouched=true、futureStageEvidence、replanRemainingStages=true，不得把后续 stage 一并写入 completedStageIds。
- 如果还在当前目标内，返回 continue_current_block；默认含义是当前 snapshot 阶段已完成，下一章进入下一个未完成阶段。
- 只有当前阶段需要跨章继续时，才允许继续同一阶段，并必须输出 "stageContinues": true 和明确 "stageContinueReason"。
- stageContinueReason 必须具体说明：本阶段为什么没有完成；下一章继续完成哪个具体动作、冲突或选择；本章已经完成了什么，剩下什么。
- 如果 stageContinuationDepth >= 2，不得继续返回同一阶段的 stageContinues=true；只能选择 completed_by_equivalent_story_function、split_remaining_stage、opened_new_block_for_residue 或 blocked_for_manual_review。
- 如果只需要改变未执行、未引用、未定稿依赖的后续阶段，返回 adjust_remaining_stages。
- 已定稿章节不得返回 split_unfinalized_content；如发现内容过载，只能返回 continue_current_block、adjust_remaining_stages 或 open_new_block，并把顺延建议写入 carryOverToNextChapter。
- 不能因为一章结束就返回 complete_current_block 或 open_new_block。
- 如果当前块自然结束，返回 complete_current_block，并写明 completionEvidence。
- 如果后续方向变化较大，返回 open_new_block，当前块应 closed 或 completed 后由新块承接，并写明 completionEvidence。
- 如果 completionEvidence 不充分，返回 continue_current_block；如果阶段耗尽但块目标未完成，返回 adjust_remaining_stages，并补充 remainingStages。
- 如果当前块只覆盖 1 章就结束，必须写 singleChapterBlockReason；短块可以存在，但要说明这是开局、过渡、短冲突或外力转向。
- 不得回改 goal、entryState、已完成阶段、已定稿章节依赖的故事任务。

输出 JSON：
{
  "decision": "continue_current_block|adjust_remaining_stages|split_unfinalized_content|complete_current_block|open_new_block",
  "completedStageIds": ["stage-1"],
  "stageContinues": false,
  "stageContinueReason": "仅 stageContinues=true 必填：本阶段未完成原因 + 下一章继续动作/冲突/选择 + 本章已完成和剩余内容",
  "remainingStages": [],
  "nextStageSuggestion": "下一阶段建议",
  "unresolvedQuestions": [],
  "carryOverToNextChapter": [],
  "newBlockSeed": {
    "title": "",
    "goal": "",
    "entryState": "",
    "storyFunction": ""
  },
  "completionEvidence": "仅 complete_current_block/open_new_block 必填：任务完成/失败/转向/自然结束/外力打断/新态势证据",
  "singleChapterBlockReason": "若当前块只覆盖 1 章就结束，说明为什么允许短块；否则留空",
  "stageContinuationDepth": 0,
  "previousOpenStageId": "",
  "settlementDecision": "",
  "settlementEvidence": [],
  "equivalentCompletionScope": "",
  "futureStageTouched": false,
  "futureStageEvidence": [],
  "futureStageOverClosed": false,
  "needsFutureStageReplan": false,
  "replanRemainingStages": false,
  "whetherStageClosedBeforeNextBeatPlan": false,
  "closedBy": "ai_review",
  "reason": "100字以内"
}`
}

export function buildStoryBlockReviewRepairPrompt(rawText = '') {
  return `下面是一段故事块回看模型输出，格式可能不是合法 JSON。请只修复为合法 JSON。
边界：
- 只修复 JSON 语法、代码块包裹、前后缀说明、缺失引号、尾逗号等格式问题。
- 不新增剧情。
- 不扩写正文。
- 不改写已有字段含义。
- 不输出 Markdown，不输出解释。

必须输出这个故事块回看 schema：
{
  "decision": "continue_current_block",
  "completedStageIds": [],
  "stageContinues": false,
  "stageContinueReason": "",
  "remainingStages": [],
  "nextStageSuggestion": "",
  "unresolvedQuestions": [],
  "carryOverToNextChapter": [],
  "newBlockSeed": {
    "title": "",
    "goal": "",
    "entryState": "",
    "storyFunction": ""
  },
  "completionEvidence": "",
  "singleChapterBlockReason": "",
  "stageContinuationDepth": 0,
  "previousOpenStageId": "",
  "settlementDecision": "",
  "settlementEvidence": [],
  "equivalentCompletionScope": "",
  "futureStageTouched": false,
  "futureStageEvidence": [],
  "futureStageOverClosed": false,
  "needsFutureStageReplan": false,
  "replanRemainingStages": false,
  "whetherStageClosedBeforeNextBeatPlan": false,
  "closedBy": "ai_review",
  "reason": ""
}

原始输出：
${String(rawText || '').slice(0, 12000)}`
}

export function normalizeStoryBlockReviewResult(raw = {}) {
  const decision = normalizeStoryBlockReviewDecision(raw.decision)
  const stageContinueReason = raw.stageContinueReason || raw.stage_continue_reason || ''
  return {
    decision,
    completedStageIds: Array.isArray(raw.completedStageIds) ? raw.completedStageIds : [],
    stageContinues: raw.stageContinues === true,
    stageContinueReason,
    remainingStages: Array.isArray(raw.remainingStages) ? raw.remainingStages : [],
    nextStageSuggestion: raw.nextStageSuggestion || '',
    unresolvedQuestions: Array.isArray(raw.unresolvedQuestions) ? raw.unresolvedQuestions : [],
    carryOverToNextChapter: Array.isArray(raw.carryOverToNextChapter) ? raw.carryOverToNextChapter : [],
    newBlockSeed: raw.newBlockSeed && typeof raw.newBlockSeed === 'object' ? raw.newBlockSeed : null,
    completionEvidence: raw.completionEvidence || raw.completion_evidence || '',
    singleChapterBlockReason: raw.singleChapterBlockReason || raw.single_chapter_block_reason || '',
    stageContinuationDepth: Number(raw.stageContinuationDepth ?? raw.stage_continuation_depth ?? 0) || 0,
    previousOpenStageId: raw.previousOpenStageId || raw.previous_open_stage_id || '',
    settlementDecision: raw.settlementDecision || raw.settlement_decision || '',
    settlementEvidence: Array.isArray(raw.settlementEvidence) ? raw.settlementEvidence : [],
    equivalentCompletionScope: raw.equivalentCompletionScope || raw.equivalent_completion_scope || '',
    futureStageTouched: raw.futureStageTouched === true || raw.future_stage_touched === true,
    futureStageEvidence: Array.isArray(raw.futureStageEvidence) ? raw.futureStageEvidence : (Array.isArray(raw.future_stage_evidence) ? raw.future_stage_evidence : []),
    futureStageOverClosed: raw.futureStageOverClosed === true || raw.future_stage_over_closed === true,
    needsFutureStageReplan: raw.needsFutureStageReplan === true || raw.needs_future_stage_replan === true,
    replanRemainingStages: raw.replanRemainingStages === true || raw.replan_remaining_stages === true,
    whetherStageClosedBeforeNextBeatPlan: raw.whetherStageClosedBeforeNextBeatPlan === true || raw.whether_stage_closed_before_next_beat_plan === true,
    closedBy: raw.closedBy || raw.closed_by || 'ai_review',
    storyBlockStalled: raw.storyBlockStalled === true || raw.story_block_stalled === true,
    reason: raw.reason || '',
    aiReviewFallback: raw.aiReviewFallback === true,
    aiReviewError: raw.aiReviewError || '',
    aiReviewDiagnostics: raw.aiReviewDiagnostics || null,
    source: raw.source || ''
  }
}

export function buildStoryBlockReviewSemanticRepairPrompt(review = {}, context = {}) {
  return `下面是一段故事块回看 JSON，语义字段可能不完整。请只输出修复后的合法 JSON，不要 Markdown，不要解释。
修复目标：
- 如果 stageContinues=true，必须填写 stageContinueReason。
- stageContinueReason 必须说明：本阶段为什么没有完成；下一章继续完成哪个具体动作/冲突/选择；本章已经完成了什么，剩下什么。
- 如果本章已经用错误信任、低估敌人、被反制、小九被绑、星账代价加剧或行动选择受限完成了故事功能等价完成，则把 stageContinues 改为 false，并填写 settlementDecision="completed_by_equivalent_story_function"；completedStageIds 只允许包含当前 snapshot stage。
- 如果本章文本碰到后续 stage，只写 futureStageTouched/futureStageEvidence/replanRemainingStages，不要把未来 stage 算 completed。
- 如果 stageContinuationDepth >= 2，不得继续返回同一阶段 stageContinues=true；关闭当前阶段，把残余动作拆成未来未锁定阶段或标记 blocked_for_manual_review。
- 如果无法给出具体 stageContinueReason，则把 stageContinues 改为 false，并让下一章进入下一可执行阶段。
- 不新增大剧情，只根据本章摘要、结尾、stage snapshot 和原 JSON 修复。

本章摘要：
${context.finalizedSummary || '无'}

本章结尾：
${context.chapterEnding || '无'}

block_stage_snapshot：
${compactJson(context.blockStageSnapshot || {})}

当前 story block：
${compactJson(context.storyBlock || {})}

stage continuation diagnostics：
${compactJson({
  stageContinuationDepth: context.stageContinuationDepth ?? 0,
  previousOpenStageId: context.previousOpenStageId || ''
})}

原 JSON：
${compactJson(review || {})}`
}
