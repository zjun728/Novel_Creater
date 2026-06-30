export function getFinalizationMarkerAction(marker) {
  if (!marker) {
    return {
      kind: 'none',
      canRetryPostprocess: false,
      tagText: '',
      buttonText: '',
      warning: ''
    }
  }

  const chapterNum = Number(marker.chapterNum || marker.chapter_num || 0)
  if (marker.storyBlockSettlementFailure) {
    return {
      kind: 'manual_story_block_settlement',
      canRetryPostprocess: false,
      tagText: '故事块结算待处理',
      buttonText: '',
      warning: `第 ${chapterNum || ''} 章故事块结算失败；通用定稿后提取重试只会重跑记忆/设定，不会重跑故事块结算，请先处理故事块阶段冲突或在专门流程中恢复。`.replace(/\s+/g, ' ').trim()
    }
  }

  if (marker.retryablePostprocessFailure || marker.postFinalizeFailed) {
    return {
      kind: 'retry_postprocess',
      canRetryPostprocess: true,
      tagText: '定稿后处理待重试',
      buttonText: `重试第 ${chapterNum || ''} 章定稿后提取`.replace(/\s+/g, ' ').trim(),
      warning: ''
    }
  }

  return {
    kind: 'pending_postprocess',
    canRetryPostprocess: false,
    tagText: '定稿后处理未完成',
    buttonText: '',
    warning: ''
  }
}
