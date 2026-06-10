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
- 去 AI 腔不是把句子改华丽，而是让文字更像角色在真实处境里的感受和选择。
- 不要五感打勾式罗列；选择当前视角最敏感的一两种感官写深，让感官服务压力、误判、危险或欲望。
- 数字和术语必须影响风险、选择、代价、误判或剧情后果；如果只是装专业感，改成角色能观察到、会因此行动的细节。
- 不直接命名情绪；用动作迟疑、生理反应、错话、回避、沉默、残留习惯或自我辩解呈现。
- 允许少量不直接推进剧情但能让人物和世界更真实的闲笔、生活痕迹或无用细节，但不能新增关键设定或打断主线。
- 失去必须有过程：记忆、情感、存在痕迹、亲人、能力或道具的失去，要写出落空、残留、迟来的疼痛或自我欺骗。
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
- 不要五感打勾式罗列；优先选当前角色最敏感的一两种体验写深。
- 数字和术语必须服务危险、选择、代价、误判或后果；无效数字应改成角色可感知的压力或线索。
- 不直接命名情绪，改成身体反应、动作迟疑、错话、沉默、回避、自我辩解或情绪残留。
- 允许少量不直接推进剧情但符合角色、场景和生活质感的真实细节，让文字有呼吸感。
- 失去必须有过程；不要只写“他失去了信任/希望/爱/记忆”，要写习惯动作落空、残留反应或迟来的疼。
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
