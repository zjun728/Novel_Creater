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
