/**
 * 四层规划 Prompt
 *
 * 当前章小纲由 chapter.js 负责；这里负责更高一层的滚动规划：
 * - 近景滚动规划：未来 3-5 章，进入章节生成上下文。
 * - 当前卷规划：当前卷 10-60 章的大结构，和分卷规划互相校准。
 * - 长线蓝图：后续几卷粗颗粒方向，不细化到章节，也不直接进入每章正文生成。
 */

export function buildOutlineSystemPrompt() {
  return `你是一位长篇小说结构设计师，负责维护可滚动迭代的创作规划。

核心原则：
- 当前章小纲不在这里生成，当前章小纲由单章写作流程单独确认。
- 近景滚动规划只规划未来 3-5 章，用于防止上下章断层、人物状态跳变和伏笔遗忘。
- 当前卷规划负责本卷大结构：阶段目标、核心冲突、人物弧光、关键反转和卷尾状态。
- 长线蓝图负责后续几卷的大方向，不细化到章节，不写成几十章详细大纲。
- 远景模糊，近景清晰；规划是可能路线，不是把故事写死。
- 每次更新都要尊重已经写出的正文、创作圣经、设定库、已确认事实和当前卷实际进展。
- 进度锁：不得回退到已写章节之前，不得重写、重排或撤销已经定稿的正文。
- 不能重新规划已经发生过的“首次”事件，例如首次获得系统、首次加点、首次突破、首次进入宗门、首次发现核心秘密等；已经发生的事件只能承接后果。
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
  return `请根据以下资料，更新小说的滚动规划。

## 项目信息
${formatContextBlock(context.projectInfo)}

## 创作种子
${formatContextBlock(context.seedInfo)}

## 创作圣经
${formatContextBlock(context.bibleInfo)}

## 当前进度
当前章节：第 ${context.currentChapterNum || 1} 章
${formatContextBlock(context.currentVolumeInfo, '')}

## 进度锁
- currentChapterNum 表示当前待写章节，不是已经写完的章节。
- nearChapters 的 chapterNum 必须从当前待写章节开始递增，只规划 currentChapterNum 到 currentChapterNum+4 之间的未来 3-5 章。
- 不得回退到已写章节之前，不得重写、重排或撤销已定稿正文。
- 不能重新规划已经发生过的“首次”事件，例如首次获得系统、首次加点、首次突破、首次进入宗门、首次发现核心秘密等；如果这些事件已经在已写章节摘要、设定库或事实中出现，只能承接后果。
- 如模型发现当前卷规划/长线蓝图与已写正文冲突，必须以已写正文、设定库和已确认事实为准，给出滚动后的新规划。

## 分卷规划
${formatContextBlock(context.volumeInfo, '暂无分卷规划')}

## 已写章节摘要
${formatContextBlock(context.chapterInfo, '暂无已写章节')}

## 已确认事实与设定
${formatContextBlock(context.factInfo, '暂无')}
${formatContextBlock(context.settingInfo, '')}

## 现有滚动规划
${formatContextBlock(context.existingOutlineInfo, '暂无')}

请只输出以下 JSON：
{
  "farVision": {
    "theme": "长线蓝图的核心主题或终局方向",
    "finalPressure": "后期会持续逼近主角和世界的终局压力",
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
    "mustNotAdvanceYet": ["本卷或近几章暂时不能提前写掉的内容"]
  },
  "nearChapters": [
    {
      "chapterNum": 1,
      "title": "章节临时标题",
      "goal": "本章必须完成的推进",
      "conflict": "本章核心冲突",
      "turn": "本章转折",
      "emotionalBeat": "人物动机、恐惧、代价或情绪残留",
      "requiredFacts": ["必须承接或写入的事实"],
      "doNotResolveYet": ["本章不能提前解决的内容"],
      "handoff": "交给下一章的接力点"
    }
  ]
}

要求：
- nearChapters 只规划未来 3-5 章，从当前待写章节开始。
- nearChapters 的 chapterNum 必须从 currentChapterNum 开始递增，不能填写已写章节编号。
- nearChapters 要能服务当前章小纲生成，但不要把每句对白、每个动作规定死。
- currentVolume 要和分卷规划保持一致，如实际正文已经改变，应给出更贴近当前正文的阶段修正。
- farVision 是长线蓝图，只保留后续几卷粗颗粒方向，不细化到章节。
- 如果现有规划和已写正文冲突，以已写正文、设定库和已确认事实为准，给出滚动后的新规划。`
}

export function buildRollingPlanReroutePrompt(context = {}) {
  return `请在每章定稿后，校验剩余近景规划，并微调近景滚动规划。

## 已定稿章节
第 ${context.finalizedChapterNum || context.currentChapterNum || '?'} 章
${formatContextBlock(context.finalizedChapterInfo || context.chapterInfo, '暂无')}

## 本章实际正文摘要/事实
${formatContextBlock(context.factInfo, '暂无')}
${formatContextBlock(context.settingInfo, '')}

## 原近景规划
${formatContextBlock(context.existingOutlineInfo, '暂无')}

## 当前卷规划
${formatContextBlock(context.currentVolumeInfo || context.volumeInfo, '暂无')}

任务：
1. 检查本章实际写出来的事件、人物状态、代价、线索推进，是否让剩余近景规划的前提失效。
2. 只校验并微调未来 3-5 章 nearChapters，不得重写已定稿章节，不得撤销已发生事实。
3. 如果角色做出了合理但超出原规划的选择，优先顺着已定稿正文重路由，而不是强行拉回旧规划。
4. 当前卷规划和长线蓝图只做必要的轻微校准；远景保持粗颗粒，不细化到章节。

请只输出合法 JSON，字段结构与滚动规划一致：farVision、currentVolume、nearChapters。`
}

export function buildOutlineRepairPrompt(text) {
  return `下面是一次滚动规划生成结果，但它不是合法 JSON。请修复为合法 JSON，并保持字段结构不变。

要求：
- 只输出 JSON。
- 必须包含 farVision、currentVolume、nearChapters。
- nearChapters 必须是数组。
- 不要输出 Markdown 或解释。

原始内容：
${text || ''}`
}
