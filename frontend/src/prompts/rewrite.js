/**
 * 选区重写 Prompt
 */

export function buildRewriteSystemPrompt() {
  return `你是一位专业小说编辑，擅长局部改写和润色。

原则：
- 保持原文的风格和人物声音。
- 改写要有明确的改进方向，不是为改而改。
- 不要改变已确认的事实、剧情动作、人物关系、视角归属和信息量。
- 不要新增设定、人物、关键道具、剧情转折或未出现的动机。
- 处理“去 AI 腔/润色”时，优先把抽象判断、解释腔和套路化反差句改成具体动作、感官细节、物象变化、对白停顿或人物反应。
- 降低高频句式：不是……而是……、不是……是……、像是……又像是……、某种……、仿佛有什么东西……、终于意识到……。处理去 AI 腔时，非对白叙述中应尽量清零这类结构；确需保留也只能保留最必要的一处。
- 降低段首重复点名：不要连续多段都以同一个角色姓名开头；能承接时改用动作、物件、环境、感官、对白、心理余波或代词起段，必要时才点名。
- 不要把文本改成审稿意见、总结说明或创作解析。
- 输出改写后的完整段落，不只是修改建议。`
}

export const REWRITE_MODES = {
  dialogue: '改写对话，让每个角色的台词更有辨识度和个性',
  conflict: '加强冲突张力，让人物之间的对抗更激烈',
  psychology: '加强人物心理描写，展现更多内心活动',
  webStyle: '改成更有网感的写法，节奏更快，句子更短',
  literary: '改成更文学化的写法，增加意象和氛围描写',
  polish: '去 AI 腔并润色文字：不改变剧情、事实、人物意图和信息量，降低套路化反差句、虚化判断和解释腔，修正语病并改善节奏',
  describe: '丰富场景描写，增强画面感',
  action: '加强动作描写，让场景更有动态感',
}

export function buildRewritePrompt(selectedText, mode, context) {
  const modeDesc = REWRITE_MODES[mode] || mode
  const polishRules = mode === 'polish'
    ? `
## 去 AI 腔要求
- 保留原段落的剧情信息、人物意图、视角和节奏功能。
- 尽量清除“不是……而是……”“不是……是……”“像是……又像是……”“某种……”等高频 AI 感句式；如确实需要，最多保留必要的一处，且不得连续出现。
- 把抽象解释改成具体动作、感官细节、物象变化、对白停顿或人物即时反应。
- 如果多段连续用同一个角色姓名起段，改为动作承接、物件状态、环境变化、感官细节、对白或代词起段；不要改变视角归属。
- 去掉过度总结、过度升华、重复强调和一眼能看出模板化的反差表达。
- 不要把文字改得过度华丽，也不要为了网感强行加梗。
- 不新增设定、新人物、新道具、新剧情转折。
`
    : ''

  return `请改写以下段落。

改写方向：${modeDesc}
${polishRules}

## 上下文
${context?.styleBible ? `风格要求：${context.styleBible}` : ''}
${context?.characters?.length ? `相关角色：${context.characters.map(c => `${c.name}（${c.personality || ''}）`).join('、')}` : ''}
${context?.volumeStage ? `分卷阶段：${formatVolumeStageForRewrite(context.volumeStage)}` : ''}
${context?.settingLibrary ? `设定库：${context.settingLibrary}` : ''}
${context?.recentFacts ? `已确认事实：${context.recentFacts}` : ''}
${context?.activeCorrectionTasks ? `未完成纠偏任务：${context.activeCorrectionTasks}` : ''}

## 原文
---
${selectedText}
---

请输出改写后的完整段落。`
}

function formatVolumeStageForRewrite(stage) {
  if (!stage) return ''
  if (typeof stage === 'string') return stage
  return [
    stage.title ? `当前分卷=${stage.title}` : '',
    stage.coreGoal ? `分卷目标=${stage.coreGoal}` : '',
    stage.mainConflict ? `核心冲突=${stage.mainConflict}` : '',
    stage.currentSummary ? `阶段摘要=${stage.currentSummary}` : '',
    stage.continuityNotes?.length ? `连续性约束=${stage.continuityNotes.map(formatItem).join('；')}` : ''
  ].filter(Boolean).join('；')
}

function formatItem(item) {
  if (typeof item === 'string') return item
  if (!item || typeof item !== 'object') return ''
  return item.name || item.title || item.change || item.note || JSON.stringify(item)
}
