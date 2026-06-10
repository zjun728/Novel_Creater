function safeJson(value) {
  return JSON.stringify(value ?? null, null, 2)
}

export function buildLocalWindowRevisionSystemPrompt() {
  return `你是一位小说滑窗局部修订编辑。

任务边界：
- 只修订目标片段以及必要的接缝句，不重写整章。
- 必须保留剧情事实、人物意图、视角归属、设定和节奏功能。
- 允许为了接缝自然，轻微调整目标片段前后各一句。
- 如果目标片段无法安全替换，返回 skipped，并说明原因。
- 只输出 JSON，不要 Markdown 或解释前缀。`
}

export function buildLocalWindowRevisionPrompt({ issue = {}, before = '', target = '', after = '', chapterContext = '' } = {}) {
  return `请执行一次滑窗局部修订。

## 审稿问题
${safeJson(issue)}

## 前文滑窗
${before}

## 目标片段
${target || issue.location || ''}

## 后文滑窗
${after}

## 章节上下文
${chapterContext || '未提供'}

修订要求：
- 优先解决审稿问题，不新增新剧情。
- 检查修订后与前文滑窗、后文滑窗的接缝是否顺。
- replacement 必须是可以替换目标片段的小说正文。
- 如果需要微调接缝，返回 adjustedBeforeTail 或 adjustedAfterHead；不需要则为空字符串。

只输出 JSON：
{
  "status": "applied|skipped",
  "original": "原目标片段",
  "replacement": "替换文本",
  "adjustedBeforeTail": "可选：微调后的前文末句",
  "adjustedAfterHead": "可选：微调后的后文首句",
  "seamCheck": "接缝检查结论",
  "reason": "跳过或修订理由"
}`
}
