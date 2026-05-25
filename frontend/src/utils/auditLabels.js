export function auditSeverityLabel(severity) {
  const labels = {
    critical: '严重',
    major: '主要',
    minor: '轻微',
    suggestion: '建议'
  }
  return labels[severity] || severity || '问题'
}

export function auditIssueTypeLabel(type) {
  const labels = {
    contradiction: '设定矛盾',
    character_inconsistency: '人物不一致',
    world_rule_violation: '世界规则冲突',
    pacing: '节奏问题',
    dialogue: '对白问题',
    logic: '逻辑问题',
    quality: '质量问题',
    human_motivation: '人性动机',
    emotional_logic: '情绪因果',
    ai_tone: 'AI 腔',
    plot: '剧情问题',
    emotion: '情绪问题',
    continuity: '连续性问题',
    foreshadowing: '伏笔问题',
    mainline: '主线问题',
    structure: '结构问题',
    setting: '设定问题',
    character: '人物问题',
    market: '选题问题',
    next_action: '后续动作'
  }
  return labels[type] || type || '通用问题'
}
