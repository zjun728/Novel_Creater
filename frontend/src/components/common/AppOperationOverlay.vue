<script>
import { storeToRefs } from 'pinia'
import {
  defineComponent,
  nextTick,
  onUnmounted,
  ref,
  watch,
} from 'vue'

import { useOperationStore } from '../../stores/operationStore.js'

export function createOperationOverlayFocusManager({
  getDocument = () => globalThis.document,
  getOverlay = () => null,
  schedule = callback => { void nextTick(callback) },
} = {}) {
  let blocking = false
  let restoreTarget = null

  function restoreFocus() {
    const target = restoreTarget
    restoreTarget = null
    if (target?.isConnected !== false) target?.focus?.()
  }

  function setBlocking(nextBlocking) {
    const next = Boolean(nextBlocking)
    if (next === blocking) return
    blocking = next
    if (next) {
      restoreTarget = getDocument?.()?.activeElement ?? null
      schedule(() => {
        if (blocking) getOverlay()?.focus?.({ preventScroll: true })
      })
      return
    }
    schedule(restoreFocus)
  }

  function dispose() {
    blocking = false
    restoreFocus()
  }

  return {
    setBlocking,
    dispose,
  }
}

export default defineComponent({
  name: 'AppOperationOverlay',
  setup() {
    const operationStore = useOperationStore()
    const { current, blocking } = storeToRefs(operationStore)
    const overlay = ref(null)
    const focusManager = createOperationOverlayFocusManager({
      getOverlay: () => overlay.value,
    })

    watch(blocking, focusManager.setBlocking, { immediate: true })
    onUnmounted(focusManager.dispose)

    return {
      current,
      blocking,
      overlay,
    }
  },
})
</script>

<template>
  <aside
    v-if="current"
    ref="overlay"
    class="app-operation-overlay"
    :class="blocking
      ? 'app-operation-overlay--blocking'
      : 'app-operation-overlay--notice'"
    :role="blocking ? 'dialog' : 'status'"
    :aria-modal="blocking ? 'true' : undefined"
    aria-labelledby="app-operation-overlay-title"
    :aria-live="blocking ? 'assertive' : 'polite'"
    :tabindex="blocking ? -1 : undefined"
    :data-blocks-navigation="String(blocking)"
  >
    <div class="app-operation-overlay__panel">
      <span class="app-operation-overlay__seal" aria-hidden="true">作</span>
      <div>
        <strong id="app-operation-overlay-title">{{ current.label }}</strong>
        <p v-if="current.detail">{{ current.detail }}</p>
      </div>
      <span class="app-operation-overlay__progress" aria-hidden="true"></span>
    </div>
  </aside>
</template>
