<script setup>
import { storeToRefs } from 'pinia'

import { useOperationStore } from '../../stores/operationStore.js'

const operationStore = useOperationStore()
const { current, blocking } = storeToRefs(operationStore)
</script>

<template>
  <aside
    v-if="current"
    class="app-operation-overlay"
    :class="blocking
      ? 'app-operation-overlay--blocking'
      : 'app-operation-overlay--notice'"
    :role="blocking ? 'dialog' : 'status'"
    :aria-modal="blocking ? 'true' : undefined"
    :aria-live="blocking ? 'assertive' : 'polite'"
    :data-blocks-navigation="String(blocking)"
  >
    <div class="app-operation-overlay__panel">
      <span class="app-operation-overlay__seal" aria-hidden="true">作</span>
      <div>
        <strong>{{ current.label }}</strong>
        <p v-if="current.detail">{{ current.detail }}</p>
      </div>
      <span class="app-operation-overlay__progress" aria-hidden="true"></span>
    </div>
  </aside>
</template>
