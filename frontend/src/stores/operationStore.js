import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

let operationSequence = 0

export function createOperationStore(storeId = 'operation') {
  return defineStore(storeId, () => {
    const current = ref(null)
    const active = computed(() => Boolean(current.value))
    const blocking = computed(() => Boolean(current.value?.blocking))

    function start({
      label = '正在处理',
      detail = '',
      blocking: shouldBlock = false,
    } = {}) {
      operationSequence += 1
      const operation = {
        id: `operation-${operationSequence}`,
        label: String(label || '正在处理'),
        detail: String(detail || ''),
        blocking: Boolean(shouldBlock),
      }
      current.value = operation
      return operation.id
    }

    function finish(operationId) {
      if (!current.value) return false
      if (operationId && current.value.id !== operationId) return false
      current.value = null
      return true
    }

    return {
      current,
      active,
      blocking,
      start,
      finish,
    }
  })
}

export const useOperationStore = createOperationStore()
