const GENRE_LABELS = Object.freeze({
  general: '通用题材',
  fantasy: '玄幻',
  xianxia: '仙侠',
  wuxia: '武侠',
  historical: '历史',
  horror: '恐怖',
  mystery: '悬疑',
  romance: '言情',
  science_fiction: '科幻',
  urban: '都市',
})

const CREATION_STAGE_LABELS = Object.freeze({
  contract: '创作契约',
  planning: '故事规划',
  chapter_outline: '章节小纲',
  drafting: '正文写作',
  revision: '修订',
  quality_audit: '质量审核',
})

function displayLabel(labels, value) {
  const stableValue = value == null ? '' : String(value)
  return labels[stableValue] || stableValue
}

export function genreLabel(value) {
  return displayLabel(GENRE_LABELS, value)
}

export function creationStageLabel(value) {
  return displayLabel(CREATION_STAGE_LABELS, value)
}

const CATEGORY_LABELS = Object.freeze({ action_conflict: '动作与冲突', character_arcs: '人物弧光', dialogue: '对话', emotion: '情绪', ensemble: '群像', information_release: '信息揭示', interiority: '内心活动', long_arc_continuity: '长篇连续性', pacing: '节奏', plot_organization: '情节组织', progression_economy: '成长与资源', suspense: '悬念' })
export function categoryLabel(value) { return displayLabel(CATEGORY_LABELS, value) }
