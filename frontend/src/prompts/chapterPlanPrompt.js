import {
  buildChapterBeatPrompt,
  buildChapterBeatSystemPrompt
} from './chapter.js'

export function buildScenePlanSystemPrompt() {
  return `${buildChapterBeatSystemPrompt()}

补充定位：
- 这是“场景型小纲”，不是写正文，也不是审稿报告。
- 小纲要规划场景摩擦、人物遮掩、信息释放、有效选择和结尾余波。
- 不要把正文句子写死，只锁定可执行路线。`
}

export function buildScenePlanPrompt(context = {}) {
  const prefix = [
    '## 场景型小纲补充目标',
    '- 场景摩擦：本章不能只顺滑推进，至少要有误判、阻滞、遮掩、迟疑、关系压力或现实打断之一。',
    '- 信息释放：关键内容优先通过证据、行动失败、物件反应、关系变化或旁人遮掩被发现。',
    '- 有效选择：关键选择必须有不同损失；如果不是两难，要写清真正压力来自哪里。',
    '- 人味呼吸：预留一处沉默、跑题对白、生活痕迹或无用但真实的细节。',
    context.writingFingerprint ? `## 写作指纹\n${context.writingFingerprint}` : ''
  ].filter(Boolean).join('\n')

  return `${prefix}\n\n${buildChapterBeatPrompt(context)}`
}
