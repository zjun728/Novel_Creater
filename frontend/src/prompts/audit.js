/**
 * 一致性审稿 Prompt
 */

export function buildAuditSystemPrompt() {
  return `你是一位专业小说审稿编辑，负责检查章节的一致性、逻辑和写作质量。

审稿原则：
- 以建设性方式提出建议，不贬低作者。
- 区分"必须修改的问题"和"可以斟酌的建议"。
- 重点关注前后矛盾、人物行为不合理、世界规则违背等问题。
- 也关注写作质量：节奏、对话、描写、信息密度等。
- 重点检查人物动机与代入感：人物是否像工具人、选择是否有欲望/恐惧支撑、情绪是否有因果、关键选择是否有代价和情绪残留。
- 统计明显 AI 腔句式，尤其是非对白叙述中的“不是X，而是Y”“不是X，是Y”；整章超过 2 次应作为写作质量问题提出。
- 检查句式节奏是否失衡：长中短句应混合，短句独段只适合局部强调；如果整章大量“一句一段”、连续短句独段超过 3 段，应作为 AI 痕迹或节奏问题提出。
- 专项检查 AI 痕迹：章节结尾模板化、表层情绪、工具人配角、信息倾倒、套话意象；这些问题会让读者感觉“像 AI 写的”。
- 如果提供了题材/风格标准，要检查章节是否偏离对应读者承诺、章节引擎、信息释放方式、人物写法和常见风险。
- 必须只输出合法 JSON，不要输出 Markdown 代码块、解释、前后缀。`
}

export function buildAuditPrompt(chapterContent, context) {
  return `请审稿以下章节，检查一致性、质量问题和人物动机与代入感。

## 第 ${context.chapterNum || '?'} 章正文
---
${chapterContent}
---

## 参考信息
${context.bible ? `### 世界规则\n${context.bible.worldRules || '无'}\n### 风格要求\n${context.bible.styleBible || '无'}` : ''}

${context.styleStandardBrief ? `### 题材/风格标准\n${context.styleStandardBrief}` : ''}

${context.characters?.length ? `### 角色状态\n${context.characters.map(c => `- ${c.name}：位置=${c.hardState?.location || '未知'}，情绪=${c.softState?.emotion || '未知'}`).join('\n')}` : ''}

${context.canonFacts?.length ? `### 已确认事实\n${context.canonFacts.map(f => `- [${f.factType}] ${f.content}`).join('\n')}` : ''}

${context.plotThreads?.length ? `### 进行中的伏笔\n${context.plotThreads.filter(t => t.status === 'planted' || t.status === 'developing').map(t => `- ${t.title}`).join('\n')}` : ''}

## 人物动机与代入感检查
- 关键人物是否有清晰欲望、恐惧、遮掩或不能直说的东西。
- 关键选择是否由人物内在动机推动，而不是为了推动剧情或解释设定。
- 情绪转折是否有前后因果，是否通过动作、停顿、对白或细节表现。
- 章节爽点是否来自压力下的选择和代价，而不是单纯开挂、堆信息或华丽句子。
- 场景结束后是否留下情绪残留，让后续章节有心理惯性。

## AI 腔句式检查
- 统计非对白叙述中“不是X，而是Y”“不是X，是Y”的出现次数；超过 2 次必须提出问题。
- 检查“像是……又像是……”“某种……”“仿佛有什么东西……”“终于意识到……”是否连续或密集出现。
- 检查是否整章句式过短、段落过碎、连续短句独段。短句如果只出现在战斗、惊惧、情绪崩裂或章节钩子中，不要报问题；如果连续多段都像分镜脚本，应按 ai_tone、pacing 或 quality 提出。
- 句式节奏类问题只有影响整章阅读时才给 major；局部可斟酌问题给 minor 或 suggestion，不要把所有短句都当成错误。
- 建议应指向具体替换方法：动作、感官、物象、对白停顿、人物即时反应，而不是笼统说“减少 AI 味”。
- 每个问题尽量给出可直接替换原文的 replacement。replacement 必须是小说正文片段，不要写“建议改为”“可以改成”等说明文字。
- location 必须从正文中逐字复制原文，不能改标点、不能合并句子、不能转述；优先给完整句或完整段，不要只给半句。
- replacement 的粒度必须和 location 一致：location 是半句时，replacement 也只能替换半句；replacement 是完整句/完整段时，location 也必须是对应完整句/完整段。

## AI 痕迹与文学质感专项检查
- 章节结尾模板化：是否连续用抬头、转身、闭眼、握拳、走进黑暗、状态总结或内心独白收尾。
- 表层情绪：人物情感变化是否像开关，只写“失去信任/没有希望/感受不到爱”，缺少迟疑、残留、反复、身体反应或自我辩解。
- 工具人：配角是否只负责解释设定、递道具、推动主角或制造障碍，没有自己的目的、顾虑、习惯或小细节。
- 信息倾倒：关键设定是否由老人、系统、反派、会议或旁白长段说明，而不是通过证据、行动后果、失败尝试或误判解除呈现。
- 套话意象：环境描写是否反复使用月光、影子、黑暗、风、沉默、孤独等通用意象，却没有角色视角里的独特观察。

请输出 JSON 格式：

{
  "issues": [
    {
      "severity": "critical|major|minor|suggestion",
      "type": "contradiction|character_inconsistency|world_rule_violation|pacing|dialogue|logic|quality|human_motivation|emotional_logic|ai_tone|template_ending|surface_emotion|tool_character|info_dump|cliche_imagery",
      "description": "问题描述",
      "location": "从正文逐字复制的原文引用，优先完整句或完整段",
      "suggestion": "修改建议",
      "replacement": "可直接替换 location 原文的新文本；必须和 location 粒度一致，必须是小说正文，不要写解释",
      "reason": "为什么这是个问题"
    }
  ],
  "overallAssessment": "总体评价（100字以内）",
  "styleConsistency": "风格一致性评价",
  "characterConsistency": "角色一致性评价",
  "recommendations": ["总体建议1", "总体建议2"]
}`
}

export function buildAuditRepairPrompt(rawText) {
  return `下面是一段小说章节审稿结果，但它不是合法 JSON，可能被截断、混入 Markdown 或缺少括号。

请把它修复为合法 JSON，只输出 JSON，不要解释。字段结构如下：

{
  "issues": [
    {
      "severity": "critical|major|minor|suggestion",
      "type": "contradiction|character_inconsistency|world_rule_violation|pacing|dialogue|logic|quality|human_motivation|emotional_logic|ai_tone|template_ending|surface_emotion|tool_character|info_dump|cliche_imagery",
      "description": "问题描述",
      "location": "从正文逐字复制的原文引用，优先完整句或完整段",
      "suggestion": "修改建议",
      "replacement": "可直接替换 location 原文的新文本；必须和 location 粒度一致，必须是小说正文，不要写解释",
      "reason": "为什么这是个问题"
    }
  ],
  "overallAssessment": "总体评价",
  "styleConsistency": "风格一致性评价",
  "characterConsistency": "角色一致性评价",
  "recommendations": ["总体建议1"]
}

原始内容：
${rawText}`
}
