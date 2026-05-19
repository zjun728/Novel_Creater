import { h } from 'vue'
import { useDialog } from 'naive-ui'
import { api } from '@/api/db/client'

function stateSummary(state) {
  return [
    `章节：${state.chaptersCount || 0} 章`,
    `正文/候选版本：${state.chapterVersions || 0} 个`,
    `种子：${state.seedsCount || 0} 个`,
    `设定：${state.settingsCount || 0} 条`
  ].join('，')
}

function dialogContent(text) {
  return () => h('div', { class: 'app-message-dialog-content' }, text)
}

function openConfirm(dialog, type, options) {
  return new Promise(resolve => {
    const open = dialog[type] || dialog.warning
    open({
      title: options.title,
      content: dialogContent(options.content),
      positiveText: options.positiveText || '确认',
      negativeText: options.negativeText || '取消',
      maskClosable: false,
      closeOnEsc: false,
      closable: false,
      onPositiveClick: () => resolve(true),
      onNegativeClick: () => resolve(false),
      onClose: () => resolve(false)
    })
  })
}

export function useResetConfirmation() {
  const dialog = useDialog()

  async function confirmStageReset({
    projectId,
    title,
    safeContent,
    riskContent,
    finalContent,
    positiveText = '确认删除'
  }) {
    const state = await api.projects.contentState(projectId)
    if (!state.hasChapterContent) {
      const confirmed = await openConfirm(dialog, 'warning', {
        title,
        content: `${safeContent}\n\n当前项目状态：${stateSummary(state)}`,
        positiveText
      })
      return { confirmed, state }
    }

    const first = await openConfirm(dialog, 'warning', {
      title: '已有章节内容，继续操作有风险',
      content: `${riskContent}\n\n当前项目状态：${stateSummary(state)}`,
      positiveText: '我知道风险，继续'
    })
    if (!first) return { confirmed: false, state }

    const second = await openConfirm(dialog, 'error', {
      title: '最终确认',
      content: finalContent || '这会删除当前阶段数据。已写章节不会被删除，但后续写作可能失去原有规划依据。',
      positiveText
    })
    return { confirmed: second, state }
  }

  return { confirmStageReset }
}
