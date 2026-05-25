export function buildCorrectionDraftPrompt({ chapterNum, originalContent, task, tasks }) {
  const taskList = Array.isArray(tasks) && tasks.length ? tasks : (task ? [task] : [])
  const taskText = taskList.map((item, index) => [
    `### 纠偏任务 ${index + 1}`,
    `标题：${item?.title || '未命名纠偏任务'}`,
    `类型：${item?.issueType || 'general'}`,
    `严重程度：${item?.severity || 'minor'}`,
    `描述：${item?.description || '无'}`,
    `建议动作：${item?.suggestedAction || '无'}`
  ].join('\n')).join('\n\n')

  return `你是长篇小说修订编辑。请基于纠偏任务，生成“完整章节修订候选稿”。

规则：
- 只输出修订后的正文，不要输出解释、标题、Markdown 或修改说明。
- 保留原章节已经成立的剧情、人物关系、设定和文风。
- 必须综合处理下方所有纠偏任务，尽量用一次连贯修订同时解决，不要为每条任务分别输出版本。
- 只针对纠偏任务指出的问题做必要调整，不要重写成另一篇故事。
- 如果任务要求处理节奏、情绪、冲突或伏笔，请通过场景顺序、信息释放、对白和动作细节修正。
- 不要直接覆盖原文；你的输出会被保存为候选版本，由用户人工选择。

## 章节
第 ${chapterNum} 章

## 纠偏任务
${taskText || '无'}

## 原章节正文
${originalContent || ''}
`
}
