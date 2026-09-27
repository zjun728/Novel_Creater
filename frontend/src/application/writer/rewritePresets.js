export const rewritePresets = Object.freeze([
  { label: '改对白', instruction: '调整选区对白，使人物声音有区分、对话有回应和潜台词。' },
  { label: '加强冲突', instruction: '强化选区中已有的目标冲突、阻力与代价，不新增事件。' },
  { label: '加强心理', instruction: '通过具体感受、判断和犹豫加强选区心理描写，保留人物意图。' },
  { label: '改网感', instruction: '让选区表达更直接、节奏更明快，保持画面与推进，避免套路化口号。' },
  { label: '改文学化', instruction: '让选区语言更细腻、有层次，保持清晰和人物声音，不堆砌辞藻。' },
])

export function appendRewritePreset(instruction, label, limit = 1000) {
  const preset = rewritePresets.find(item => item.label === label)
  if (!preset) return instruction
  const addition = `${preset.instruction}保留既定事实、剧情走向和信息量。`
  if (instruction.includes(addition)) return instruction
  const result = instruction ? `${instruction}\n${addition}` : addition
  if (Array.from(result).length > limit) return null
  return result
}
