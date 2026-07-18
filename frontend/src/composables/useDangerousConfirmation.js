import { useDialog } from 'naive-ui'

export function createDangerousConfirmation(dialog) {
  function confirm(options = {}) {
    return new Promise(resolve => {
      let settled = false
      let actionPromise

      function settle(result) {
        if (settled) return
        settled = true
        resolve(result)
      }

      function cancel() {
        settle(false)
      }

      function runPositiveAction() {
        if (actionPromise) return actionPromise
        actionPromise = Promise.resolve()
          .then(() => options.onConfirm?.())
          .then(result => {
            settle(true)
            return result
          })
          .catch(error => {
            actionPromise = null
            throw error
          })
        return actionPromise
      }

      dialog.warning({
        title: options.title || '确认永久删除',
        content: options.content || '此操作无法恢复。',
        positiveText: options.positiveText || '永久删除',
        negativeText: options.negativeText || '取消',
        positiveButtonProps: {
          type: 'error',
          ...(options.positiveButtonProps || {}),
        },
        negativeButtonProps: {
          type: 'default',
          ...(options.negativeButtonProps || {}),
        },
        closable: false,
        maskClosable: false,
        closeOnEsc: true,
        onNegativeClick: cancel,
        onEsc: cancel,
        onClose: cancel,
        onPositiveClick: runPositiveAction,
      })
    })
  }

  return { confirm }
}

export function useDangerousConfirmation() {
  return createDangerousConfirmation(useDialog())
}
