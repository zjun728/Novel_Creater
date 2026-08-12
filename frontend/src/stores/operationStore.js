import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

let operationSequence = 0

export function createOperationStore(storeId = 'operation') {
  return defineStore(storeId, () => {
    const operations = ref([])
    const current = computed(() => {
      const blockers = operations.value.filter(operation => operation.blocking)
      return blockers.at(-1) ?? operations.value.at(-1) ?? null
    })
    const active = computed(() => operations.value.length > 0)
    const blocking = computed(() => operations.value.some(operation => operation.blocking))

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
      operations.value.push(operation)
      return operation.id
    }

    function finish(operationId) {
      const index = operations.value.findIndex(operation => operation.id === operationId)
      if (index < 0) return false
      operations.value.splice(index, 1)
      return true
    }

    function update(operationId, patch = {}) {
      if (!patch || typeof patch !== 'object' || Array.isArray(patch)) {
        throw new TypeError('operation update accepts label or detail strings')
      }
      const keys = Object.keys(patch)
      if (
        keys.length === 0
        || keys.some(key => !['label', 'detail'].includes(key))
        || keys.some(key => typeof patch[key] !== 'string')
      ) {
        throw new TypeError('operation update accepts label or detail strings')
      }
      const index = operations.value.findIndex(operation => operation.id === operationId)
      if (index < 0) return false
      operations.value.splice(index, 1, {
        ...operations.value[index],
        ...patch,
      })
      return true
    }

    return {
      current,
      active,
      blocking,
      start,
      finish,
      update,
    }
  })
}

export const useOperationStore = createOperationStore()
