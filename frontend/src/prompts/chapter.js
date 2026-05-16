/**
 * 章节生成 Prompt
 */

export function buildChapterSystemPrompt() {
  return `你是一位专业小说作者，擅长长篇叙事。你的任务是撰写小说章节。

创作原则：
- 严格遵守已确认的世界规则和角色状态。
- 在给定框架内发挥创造力，但不要推翻已有事实。
- 人物行为要符合其性格、欲望和当前状态。
- 对话要有各自的声音，不要所有人说一样的话。
- 场景要有画面感，但不要过度描写。
- 每章要有推进感：情节、人物或悬念至少推进一项。

你输出的内容是候选稿，不是正式定稿。请大胆创作，但保持与已有内容的一致性。`
}

export function buildChapterPrompt(context) {
  const parts = []

  // 创作圣经
  if (context.bible) {
    parts.push(`## 作品定位\n${context.bible.premise || '无'}`)
    if (context.bible.styleBible) {
      parts.push(`## 风格要求\n${context.bible.styleBible}`)
    }
    if (context.bible.worldRules) {
      parts.push(`## 世界规则（不可违背）\n${context.bible.worldRules}`)
    }
    if (context.bible.forbiddenDirections?.length) {
      parts.push(`## 禁止方向\n${context.bible.forbiddenDirections.join('\n')}`)
    }
  }

  // 本章目标
  if (context.chapterGoal) {
    parts.push(`## 本章目标\n${context.chapterGoal}`)
  }

  // 近景大纲
  if (context.nearOutline?.length) {
    parts.push(`## 近景大纲\n${context.nearOutline.map(o => `- 第${o.chapterNum}章：${o.title || ''} — ${o.goal || ''}`).join('\n')}`)
  }

  // 当前卷信息
  if (context.currentVolume) {
    parts.push(`## 当前卷\n- 标题：${context.currentVolume.title || '无'}\n- 目标：${context.currentVolume.goal || '无'}\n- 主要冲突：${context.currentVolume.mainConflict || '无'}`)
  }

  // 前几章摘要
  if (context.recentSummaries?.length) {
    parts.push(`## 前情摘要\n${context.recentSummaries.map(s => `- 第${s.chapterNum}章：${s.summary}`).join('\n')}`)
  }

  // 相关角色
  if (context.characters?.length) {
    const charLines = context.characters.map(c => {
      let line = `### ${c.name}（${c.role || '配角'}）\n`
      if (c.personality) line += `- 性格：${c.personality}\n`
      if (c.desire) line += `- 欲望：${c.desire}\n`
      if (c.fear) line += `- 恐惧：${c.fear}\n`
      if (c.hardState?.location) line += `- 当前位置：${c.hardState.location}\n`
      if (c.hardState?.physicalStatus) line += `- 身体状态：${c.hardState.physicalStatus}\n`
      if (c.softState?.emotion) line += `- 当前情绪：${c.softState.emotion}\n`
      if (c.softState?.currentDesire) line += `- 当前欲望：${c.softState.currentDesire}\n`
      return line
    })
    parts.push(`## 角色状态\n${charLines.join('\n')}`)
  }

  // 相关伏笔
  if (context.plotThreads?.length) {
    parts.push(`## 进行中的伏笔\n${context.plotThreads.filter(t => t.status === 'planted' || t.status === 'developing').map(t => `- ${t.title}：${t.content}（状态：${t.status}）`).join('\n')}`)
  }

  // 已有草稿
  if (context.currentDraft) {
    parts.push(`## 当前草稿（请在此基础上续写或改写）\n${context.currentDraft}`)
  }

  parts.push(`\n---\n请撰写第 ${context.chapterNum || '?'} 章。`)
  if (context.instruction) {
    parts.push(`\n特别要求：${context.instruction}`)
  }

  return parts.join('\n\n')
}

/**
 * 章节续写 prompt
 */
export function buildContinuePrompt(currentContent, instruction) {
  return `以下是小说的当前内容：

---
${currentContent}
---

请从最后一句自然续写。${instruction ? `\n续写方向：${instruction}` : ''}

要求：
- 保持一致的风格和人物声音。
- 向前推进情节或深化人物。
- 不要重复已有内容。
- 续写长度：800-2000 字。`
}

/**
 * 多候选版本 prompt
 */
export function buildMultiVariantPrompt(context) {
  const basePrompt = buildChapterPrompt(context)
  return `${basePrompt}

请生成 3 个不同方向的版本：

1. **稳妥推进版**：按照大纲自然推进，风格稳健。
2. **强冲突版**：加强矛盾和冲突，节奏更快，张力更强。
3. **意外转向版**：在合理范围内引入意外发展，制造惊喜。

每个版本输出为一个独立章节，标注版本名称。`
}

/**
 * 扩写 prompt
 */
export function buildExpandPrompt(selectedText, context) {
  return `请扩写以下段落，丰富细节、心理描写和场景氛围：

---
${selectedText}
---

扩写要求：
- 保持原有人物性格和对话风格。
- 可以增加内心独白、环境描写、动作细节。
- 扩写后长度约为原来的 2-3 倍。
- 不要让扩写后的文字变得冗长拖沓。`
}

/**
 * 压缩 prompt
 */
export function buildCompressPrompt(selectedText) {
  return `请压缩以下段落，保留核心情节和关键对话，删除冗余描写：

---
${selectedText}
---

压缩要求：
- 保留情节推进的关键节点。
- 保留重要对话和人物反应。
- 压缩后长度约为原来的一半。`
}

/**
 * 多模型融合 prompt
 */
export function buildFusionPrompt(fragments, context) {
  const fragmentText = fragments.map((f, i) =>
    `### 候选 ${i + 1}（来源：${f.label || `模型 ${i + 1}`}）\n\n${f.content}`
  ).join('\n\n---\n\n')

  return `请将以下多个 AI 生成的章节候选版本融合成一个最佳版本。

${fragmentText}

融合要求：
- 提取每个候选中最精彩的情节走向和描写。
- 保持统一的叙事风格和人物声音。
- 解决候选之间的冲突和矛盾。
- 确保情节连贯，过渡自然。
- 融合后的长度应接近原候选的平均长度。
- 不要添加与候选中完全无关的新情节。

${context.chapterNum ? `这是第${context.chapterNum}章。` : ''}

请直接输出融合后的完整章节文本。`
}

