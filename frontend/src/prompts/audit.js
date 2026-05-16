/**
 * 一致性审稿 Prompt
 */

export function buildAuditSystemPrompt() {
  return `你是一位专业小说审稿编辑，负责检查章节的一致性、逻辑和写作质量。

审稿原则：
- 以建设性方式提出建议，不贬低作者。
- 区分"必须修改的问题"和"可以斟酌的建议"。
- 重点关注前后矛盾、人物行为不合理、世界规则违背等问题。
- 也关注写作质量：节奏、对话、描写、信息密度等。`
}

export function buildAuditPrompt(chapterContent, context) {
  return `请审稿以下章节，检查一致性和质量问题。

## 第 ${context.chapterNum || '?'} 章正文
---
${chapterContent}
---

## 参考信息
${context.bible ? `### 世界规则\n${context.bible.worldRules || '无'}\n### 风格要求\n${context.bible.styleBible || '无'}` : ''}

${context.characters?.length ? `### 角色状态\n${context.characters.map(c => `- ${c.name}：位置=${c.hardState?.location || '未知'}，情绪=${c.softState?.emotion || '未知'}`).join('\n')}` : ''}

${context.canonFacts?.length ? `### 已确认事实\n${context.canonFacts.map(f => `- [${f.factType}] ${f.content}`).join('\n')}` : ''}

${context.plotThreads?.length ? `### 进行中的伏笔\n${context.plotThreads.filter(t => t.status === 'planted' || t.status === 'developing').map(t => `- ${t.title}`).join('\n')}` : ''}

请输出 JSON 格式：

\`\`\`json
{
  "issues": [
    {
      "severity": "critical|major|minor|suggestion",
      "type": "contradiction|character_inconsistency|world_rule_violation|pacing|dialogue|logic|quality",
      "description": "问题描述",
      "location": "原文引用（标记出问题的部分）",
      "suggestion": "修改建议",
      "reason": "为什么这是个问题"
    }
  ],
  "overallAssessment": "总体评价（100字以内）",
  "styleConsistency": "风格一致性评价",
  "characterConsistency": "角色一致性评价",
  "recommendations": ["总体建议1", "总体建议2"]
}
\`\`\``
}
