/**
 * 选区重写 Prompt
 */

export function buildRewriteSystemPrompt() {
  return `你是一位专业小说编辑，擅长局部改写和润色。

原则：
- 保持原文的风格和人物声音。
- 改写要有明确的改进方向，不是为改而改。
- 不要改变已确认的事实。
- 输出改写后的完整段落，不只是修改建议。`
}

export const REWRITE_MODES = {
  dialogue: '改写对话，让每个角色的台词更有辨识度和个性',
  conflict: '加强冲突张力，让人物之间的对抗更激烈',
  psychology: '加强人物心理描写，展现更多内心活动',
  webStyle: '改成更有网感的写法，节奏更快，句子更短',
  literary: '改成更文学化的写法，增加意象和氛围描写',
  polish: '润色文字，修正语病，改善节奏',
  describe: '丰富场景描写，增强画面感',
  action: '加强动作描写，让场景更有动态感',
}

export function buildRewritePrompt(selectedText, mode, context) {
  const modeDesc = REWRITE_MODES[mode] || mode

  return `请改写以下段落。

改写方向：${modeDesc}

## 上下文
${context?.styleBible ? `风格要求：${context.styleBible}` : ''}
${context?.characters?.length ? `相关角色：${context.characters.map(c => `${c.name}（${c.personality || ''}）`).join('、')}` : ''}

## 原文
---
${selectedText}
---

请输出改写后的完整段落。`
}
