function formatIssue(issue, index) {
  return [
    `### 问题 ${index + 1}`,
    `严重程度：${issue?.severity || 'minor'}`,
    `类型：${issue?.type || 'general'}`,
    `描述：${issue?.description || '无'}`,
    `位置：${issue?.location || '无'}`,
    `建议：${issue?.suggestion || '无'}`,
    `原因：${issue?.reason || '无'}`
  ].join('\n')
}

export function buildCorrectionPatchPrompt({ chapterNum, originalContent, issues }) {
  const issueText = (Array.isArray(issues) ? issues : [])
    .map(formatIssue)
    .join('\n\n')

  return `你是长篇小说局部修订编辑。请根据审稿问题，为章节生成“局部替换补丁”，不要重写整章。

核心目标：
- 只改审稿指出的问题片段。
- 其他正文必须保持不变。
- 如果问题不能通过局部替换解决，标记为 unpatchable，不要硬改。

补丁规则：
- originalText 必须是原章节正文中连续出现的一段原文，必须逐字复制，不要省略，不要改标点。
- replacementText 只替换 originalText 这一段，不要包含周围无关正文。
- 原片段尽量短，但要足够唯一定位；建议 20-200 字。
- 生成补丁前必须阅读问题片段前后约 500 字的滑窗上下文，检查替换后的接缝是否顺畅。
- 如果只替换半句话会造成前后句断裂，可以把前后各一句纳入 originalText，但仍要保持局部、唯一、可定位。
- contextBefore/contextAfter 用于说明你参考的前后接缝上下文，最多各 120 字；它们不是替换内容。
- 不要新增设定、人物、道具、境界、地点或额外剧情转折。
- 不要为同一个问题输出多个补丁。
- 不要输出完整章节正文。
- 只输出合法 JSON，不要 Markdown，不要解释。

JSON 格式：
{
  "patches": [
    {
      "issueIndex": 1,
      "originalText": "从原文逐字复制的待替换片段",
      "replacementText": "替换后的片段",
      "contextBefore": "原片段前的接缝上下文",
      "contextAfter": "原片段后的接缝上下文",
      "reason": "为什么这样改",
      "confidence": 0.8
    }
  ],
  "unpatchable": [
    {
      "issueIndex": 2,
      "reason": "无法用局部替换安全解决的原因"
    }
  ]
}

## 章节
第 ${chapterNum} 章

## 审稿问题
${issueText || '无'}

## 原章节正文
---
${originalContent || ''}
---`
}

export function buildCorrectionPatchRepairPrompt(rawText) {
  return `下面是一段“局部修订补丁”模型输出，但它可能不是合法 JSON。

请修复为合法 JSON，只输出 JSON，不要解释。字段结构如下：

{
  "patches": [
    {
      "issueIndex": 1,
      "originalText": "原文片段",
      "replacementText": "替换片段",
      "contextBefore": "原片段前的接缝上下文",
      "contextAfter": "原片段后的接缝上下文",
      "reason": "修改原因",
      "confidence": 0.8
    }
  ],
  "unpatchable": []
}

要求：
- 保留原输出中的补丁，不新增不存在的补丁。
- 如果没有可用补丁，输出 {"patches":[],"unpatchable":[]}。
- 不要输出 Markdown。

原始输出：
---
${String(rawText || '').slice(0, 12000)}
---`
}

export function buildCorrectionPatchRetryPrompt({ chapterNum, originalContent, issues, previousOutput }) {
  const issueText = (Array.isArray(issues) ? issues : [])
    .map(formatIssue)
    .join('\n\n')

  return `你上一次没有返回可应用的局部修订补丁。请重新处理。

任务：从原章节正文中找到能解决审稿问题的最小连续原文片段，输出局部替换补丁。

必须遵守：
- 优先输出 patches，不要只输出 unpatchable。
- originalText 必须来自原文，可以跨换行，但不要省略、概括或使用省略号。
- replacementText 只替换 originalText，不要输出整章。
- 必须根据原文前后约 500 字滑窗检查接缝；必要时可以把前后各一句纳入 originalText，避免半句替换导致缝合感。
- 输出 contextBefore/contextAfter，标明你参考的接缝上下文，最多各 120 字。
- 如果审稿问题是“地名、称谓、数值、逻辑跳跃、解释不足、AI 腔句式”，通常都可以通过局部替换解决。
- 只有必须重排全章结构、必须新增大段剧情或无法定位原文时，才放入 unpatchable。
- 只输出合法 JSON，不要 Markdown，不要解释。

输出格式：
{
  "patches": [
    {
      "issueIndex": 1,
      "originalText": "从原文复制的最小连续片段",
      "replacementText": "局部修订后的片段",
      "contextBefore": "原片段前的接缝上下文",
      "contextAfter": "原片段后的接缝上下文",
      "reason": "修改原因",
      "confidence": 0.8
    }
  ],
  "unpatchable": []
}

## 章节
第 ${chapterNum} 章

## 审稿问题
${issueText || '无'}

## 上一次输出
---
${String(previousOutput || '').slice(0, 4000)}
---

## 原章节正文
---
${originalContent || ''}
---`
}
