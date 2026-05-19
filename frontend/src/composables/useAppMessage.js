import { h } from 'vue'
import { useDialog } from 'naive-ui'

const TITLE_MAP = {
  success: '操作完成',
  error: '操作失败',
  warning: '需要注意',
  info: '提示'
}

function normalizeContent(content) {
  if (content == null) return ''
  if (typeof content === 'string') return content
  return String(content)
}

export function useAppMessage() {
  const dialog = useDialog()

  function open(type, content, options = {}) {
    const createDialog = dialog[type] || dialog.info
    return createDialog({
      title: options.title || TITLE_MAP[type] || TITLE_MAP.info,
      content: () => h('div', { class: 'app-message-dialog-content' }, normalizeContent(content)),
      positiveText: options.positiveText || '关闭',
      maskClosable: false,
      closeOnEsc: false,
      closable: false,
      ...options
    })
  }

  return {
    success: (content, options) => open('success', content, options),
    error: (content, options) => open('error', content, options),
    warning: (content, options) => open('warning', content, options),
    info: (content, options) => open('info', content, options)
  }
}
