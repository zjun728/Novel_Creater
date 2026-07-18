import { useDialog } from 'naive-ui'

export function createDangerousConfirmation(dialog) {
  function confirm(options = {}) {
    return new Promise(resolve => {
      let settled = false
      let actionPromise
      let actionStarted = false
      let dialogHandle

      function settle(result) {
        if (settled) return
        settled = true
        resolve(result)
      }

      function cancel() {
        if (actionStarted && !settled) return false
        settle(false)
        return undefined
      }

      function markActionPending() {
        if (!dialogHandle) return
        dialogHandle.loading = true
        dialogHandle.closeOnEsc = false
        dialogHandle.positiveButtonProps = {
          ...dialogHandle.positiveButtonProps,
          loading: true,
          disabled: true,
        }
        dialogHandle.negativeButtonProps = {
          ...dialogHandle.negativeButtonProps,
          disabled: true,
        }
      }

      function runPositiveAction() {
        if (actionStarted) return actionPromise
        if (settled) return Promise.resolve()
        actionStarted = true
        markActionPending()
        actionPromise = Promise.resolve()
          .then(() => options.onConfirm?.())
          .then(result => {
            settle(true)
            return result
          })
          .catch(() => {
            settle(false)
            return undefined
          })
        return actionPromise
      }

      dialogHandle = dialog.warning({
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
