/**
 * 卷级蓝图 Prompt
 *
 * 正式主链路是：分卷规划 -> 故事块滚动规划 -> 当前章小纲 -> 正文生成。
 * 这里只维护卷级方向和少量方向参考，不生成当前章小纲，也不把未来章节计划作为正文依据。
 */

export function buildOutlineSystemPrompt() {
  return `你是一位长篇小说结构设计师，负责维护卷级蓝图和长线方向参考。
核心原则：
- 当前章小纲不在这里生成；当前章小纲必须从当前故事块阶段生成。
- 分卷规划负责卷目标、核心冲突、关键人物、线索伏笔和卷尾交接点。
- 故事块是分卷与章节之间的正式规划层，负责接下来一段连续剧情，不固定章节数。
- nearChapters 仅作为方向参考，用于提醒可能的接力关系；它不能优先于故事块，也不能作为正文生成主依据。
- 长线蓝图只保留卷级方向，不细化成未来具体章节。
- 每次更新都要尊重已定稿正文、创作圣经、设定库、已确认事实和当前卷实际进展。
- 进度锁：不得重写、重排或撤销已定稿正文。
- 输出必须是合法 JSON，不要输出 Markdown、解释、寒暄或代码块。`
}

function formatContextBlock(value, emptyText = '无') {
  if (value == null || value === '') return emptyText
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

export function buildOutlinePrompt(context = {}) {
  return `请根据以下资料，更新小说的卷级蓝图和方向参考。

## 项目信息
${formatContextBlock(context.projectInfo)}

## 创作种子
${formatContextBlock(context.seedInfo)}

## 创作圣经
${formatContextBlock(context.bibleInfo)}

## 当前进度
当前待写章节：第 ${context.currentChapterNum || 1} 章
${formatContextBlock(context.currentVolumeInfo, '')}

## 职责边界
- 分卷规划只管卷级大方向：卷目标、核心冲突、关键人物、线索伏笔、卷尾交接点。
- 故事块负责连续剧情推进；当前章小纲必须从当前故事块阶段生成。
- nearChapters 只能作为方向参考，不得覆盖故事块阶段，不得直接驱动正文生成。
- 如卷级蓝图与已写正文冲突，以已写正文、设定库和已确认事实为准。

## 分卷规划
${formatContextBlock(context.volumeInfo, '暂无分卷规划')}

## 已写章节摘要
${formatContextBlock(context.chapterInfo, '暂无已写章节')}

## 已确认事实与设定
${formatContextBlock(context.factInfo, '暂无')}
${formatContextBlock(context.settingInfo, '')}

## 现有蓝图
${formatContextBlock(context.existingOutlineInfo, '暂无')}

请只输出以下 JSON：
{
  "farVision": {
    "theme": "长线蓝图的核心主题或终局方向",
    "finalPressure": "后期持续逼近主角和世界的终局压力",
    "futureVolumes": [
      {
        "volume": "后续卷名或阶段名",
        "direction": "这一卷的大方向，不细化到章节",
        "pressure": "这一卷主要压力",
        "handoff": "上一卷或当前卷如何接到这里"
      }
    ],
    "possibleEndings": ["可能结局或收束方向"],
    "unresolvedBigQuestions": ["全书级大问题"]
  },
  "currentVolume": {
    "title": "当前卷标题",
    "goal": "本卷阶段目标",
    "mainConflict": "本卷核心冲突",
    "emotionalArc": "本卷主要人物情绪/关系变化",
    "expectedChapterRange": [1, 60],
    "mustKeep": ["本卷必须保留的关键点"],
    "mustNotAdvanceYet": ["本卷暂时不能提前写掉的内容"]
  },
  "nearChapters": [
    {
      "chapterNum": 1,
      "title": "参考标题",
      "goal": "方向参考，不作为当前章小纲",
      "conflict": "可能冲突",
      "turn": "可能转折",
      "emotionalBeat": "可能的人物情绪或代价残留",
      "requiredFacts": ["必须尊重的事实"],
      "doNotResolveYet": ["不能提前解决的内容"],
      "handoff": "可能的接力点"
    }
  ]
}

要求：
- currentVolume 要和分卷规划保持一致；如实际正文已经改变，应给出更贴近当前正文的阶段修正。
- farVision 只保留后续几卷粗颗粒方向，不细化到章节。
- nearChapters 是低优先级方向参考；当前章仍以 block_stage_snapshot 和故事块阶段为准。
- 如果现有蓝图和已写正文冲突，以已写正文、设定库和已确认事实为准。`
}

export function buildRollingPlanReroutePrompt(context = {}) {
  return `请在章节定稿后，校验卷级蓝图和方向参考是否需要轻微校准。

## 已定稿章节
第 ${context.finalizedChapterNum || context.currentChapterNum || '?'} 章
${formatContextBlock(context.finalizedChapterInfo || context.chapterInfo, '暂无')}

## 本章实际正文摘要/事实
${formatContextBlock(context.factInfo, '暂无')}
${formatContextBlock(context.settingInfo, '')}

## 原蓝图
${formatContextBlock(context.existingOutlineInfo, '暂无')}

## 当前卷规划
${formatContextBlock(context.currentVolumeInfo || context.volumeInfo, '暂无')}

任务：
1. 检查本章实际事件、人物状态、代价和线索推进，是否让卷级方向参考的前提失效。
2. 只允许校准未写内容；不得重写已定稿章节，不得撤销已发生事实。
3. 如角色做出合理但超出原参考的选择，优先顺着已定稿正文重路由。
4. 当前卷规划和长线蓝图只做必要轻微校准；远景保持粗颗粒，不细化到章节。

请只输出合法 JSON，字段结构保持：farVision、currentVolume、nearChapters。`
}

export function buildOutlineRepairPrompt(text) {
  return `下面是一次卷级蓝图生成结果，但它不是合法 JSON。请修复为合法 JSON，并保持字段结构不变。
要求：
- 只输出 JSON。
- 必须包含 farVision、currentVolume、nearChapters。
- nearChapters 必须是数组，但它只是方向参考。
- 不要输出 Markdown 或解释。

原始内容：
${text || ''}`
}
