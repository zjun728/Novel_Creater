import { h } from 'vue'
import { useMessage } from 'naive-ui'

function normalizeContent(content) {
  if (content == null) return ''
  if (typeof content === 'string') return content
  return String(content)
}

function actionOnce(action) {
  let actionPromise
  return () => {
    if (actionPromise) return actionPromise
    actionPromise = Promise.resolve().then(action)
    return actionPromise
  }
}

export function createAppMessage(message) {
  function open(type, content, options = {}) {
    const show = message[type] || message.info
    const normalizedContent = normalizeContent(content)
    let renderedContent = normalizedContent
    if (options.actionLabel && typeof options.onAction === 'function') {
      const runAction = actionOnce(options.onAction)
      renderedContent = () => h('span', { class: 'app-message-with-action' }, [
        h('span', { class: 'app-message-with-action__text' }, normalizedContent),
        h('button', {
          type: 'button',
          class: 'app-message-with-action__button',
          onClick: runAction,
        }, normalizeContent(options.actionLabel)),
      ])
    }
    const messageOptions = {}
    for (const key of [
      'duration',
      'closable',
      'keepAliveOnHover',
      'showIcon',
      'icon',
      'onClose',
      'onLeave',
    ]) {
      if (options[key] !== undefined) messageOptions[key] = options[key]
    }
    return show(renderedContent, messageOptions)
  }

  return {
    success: (content, options) => open('success', content, options),
    error: (content, options) => open('error', content, options),
    warning: (content, options) => open('warning', content, options),
    info: (content, options) => open('info', content, options)
  }
}

export function useAppMessage() {
  return createAppMessage(useMessage())
}
