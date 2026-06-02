export function normalizeWordCount(value) {
  const num = Number(value || 0)
  return Number.isFinite(num) && num > 0 ? Math.round(num) : 0
}

export function buildChapterWordTarget(project = {}, volumeStage = null) {
  const projectTargetWords = normalizeWordCount(project.targetWords || project.target_words)
  const projectTargetChapters = normalizeWordCount(project.targetChapters || project.target_chapters)

  let target = 0
  if (projectTargetWords && projectTargetChapters) {
    target = Math.round(projectTargetWords / projectTargetChapters)
  }

  if (!target && volumeStage?.targetWords && volumeStage?.chapterRange) {
    const range = String(volumeStage.chapterRange).match(/(\d+)\s*[-~至到]\s*(\d+)/)
    if (range) {
      const count = Number(range[2]) - Number(range[1]) + 1
      if (count > 0) target = Math.round(normalizeWordCount(volumeStage.targetWords) / count)
    }
  }

  if (!target) return null

  const min = Math.max(800, Math.round(target * 0.9))
  const max = Math.round(target * 1.3)
  const hardMin = Math.max(500, Math.round(target * 0.8))
  const hardMax = Math.round(target * 1.4)

  return { target, min, max, hardMin, hardMax }
}

export function assessChapterWordCount(text, target) {
  const count = String(text || '').trim().length
  if (!target?.target || !count) return { count, level: 'none', message: '' }

  if (count < target.hardMin) {
    return {
      count,
      level: 'hard_under',
      message: `本章约 ${count} 字，明显低于目标 ${target.target} 字（建议 ${target.min}-${target.max} 字）。建议补足关键场景、人物反应、因果交代或章节钩子。`
    }
  }

  if (count > target.hardMax) {
    return {
      count,
      level: 'hard_over',
      message: `本章约 ${count} 字，明显超过目标 ${target.target} 字（建议 ${target.min}-${target.max} 字）。建议检查是否塞入两章容量，优先在自然断点拆章。`
    }
  }

  if (count > target.max) {
    return {
      count,
      level: 'over',
      message: `本章约 ${count} 字，略高于建议范围 ${target.min}-${target.max} 字；如章节情绪和因果完整，可保留。`
    }
  }

  if (count < target.min) {
    return {
      count,
      level: 'under',
      message: `本章约 ${count} 字，低于建议范围 ${target.min}-${target.max} 字，如剧情推进不足可适当扩展。`
    }
  }

  return { count, level: 'ok', message: '' }
}
