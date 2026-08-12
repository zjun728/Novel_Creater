import { computed, ref } from 'vue'

const FLUSH_ERROR = '保存当前正文失败，未创建备份。'
const BACKUP_ERROR = '创建项目备份失败，请重试。'
const FALLBACK_FILENAME = 'project-backup.zip'
const PHASES = Object.freeze([
  '正在核对项目状态',
  '正在建立一致快照',
  '正在写入备份包',
  '正在准备下载',
])

function safeFilename(value) {
  if (typeof value !== 'string' || !value || value === '.' || value === '..') return null
  if (/[\\/\u0000-\u001f\u007f]/u.test(value)) return null
  if (!/\.zip$/iu.test(value)) return null
  return value
}

export function filenameFromContentDisposition(contentDisposition) {
  if (typeof contentDisposition !== 'string') return FALLBACK_FILENAME
  const encoded = /(?:^|;)\s*filename\*\s*=\s*UTF-8''([^;]*)/iu.exec(contentDisposition)
  if (encoded) {
    try {
      const filename = safeFilename(decodeURIComponent(encoded[1]))
      if (filename) return filename
    } catch {
      // Continue to the quoted ASCII fallback below.
    }
  }
  const quoted = /(?:^|;)\s*filename\s*=\s*"([^"]*)"/iu.exec(contentDisposition)
  if (quoted && /^[\x20-\x7e]*$/u.test(quoted[1])) {
    const filename = safeFilename(quoted[1])
    if (filename) return filename
  }
  return FALLBACK_FILENAME
}

export function createProjectBackupController({
  api,
  operationStore,
  flushCurrentDraft,
  createObjectURL,
  revokeObjectURL,
  saveBlob,
  abortControllerFactory = () => new AbortController(),
} = {}) {
  if (
    typeof api?.projectBackups?.create !== 'function'
    || typeof operationStore?.start !== 'function'
    || typeof operationStore?.update !== 'function'
    || typeof operationStore?.finish !== 'function'
    || typeof flushCurrentDraft !== 'function'
    || typeof createObjectURL !== 'function'
    || typeof revokeObjectURL !== 'function'
    || typeof saveBlob !== 'function'
    || typeof abortControllerFactory !== 'function'
  ) {
    throw new TypeError('project backup dependencies are required')
  }

  const busyState = ref(false)
  const error = ref('')
  let generation = 0
  let disposed = false
  let inFlight = null

  const busy = computed(() => busyState.value)

  async function backup(projectId, expectedLifecycleRevision, { archived = false } = {}) {
    if (disposed || inFlight) return false
    const token = ++generation
    inFlight = { token, abortController: null }
    busyState.value = true
    error.value = ''
    const active = () => !disposed && inFlight?.token === token
    let operationId = null
    let objectUrl = null

    try {
      if (!archived) {
        let flushed
        try {
          flushed = await flushCurrentDraft()
        } catch (failure) {
          if (active()) error.value = FLUSH_ERROR
          throw failure
        }
        if (!active()) return false
        if (flushed === false) {
          error.value = FLUSH_ERROR
          return false
        }
      }
      if (!active()) return false

      const abortController = abortControllerFactory()
      if (!abortController?.signal || typeof abortController.abort !== 'function') {
        throw new TypeError('abortControllerFactory must return an AbortController')
      }
      inFlight.abortController = abortController
      operationId = operationStore.start({
        label: PHASES[0], detail: '', blocking: true,
      })
      operationStore.update(operationId, { label: PHASES[1], detail: '' })
      const result = await api.projectBackups.create(projectId, expectedLifecycleRevision, {
        signal: abortController.signal,
      })
      if (!active()) return false

      operationStore.update(operationId, { label: PHASES[2], detail: '' })
      objectUrl = createObjectURL(result?.blob)
      operationStore.update(operationId, { label: PHASES[3], detail: '' })
      saveBlob(objectUrl, filenameFromContentDisposition(result?.contentDisposition))
      return true
    } catch (failure) {
      if (!active()) return false
      if (!error.value) error.value = BACKUP_ERROR
      throw failure
    } finally {
      try {
        if (objectUrl !== null) revokeObjectURL(objectUrl)
      } catch (failure) {
        if (active()) error.value = BACKUP_ERROR
        throw failure
      } finally {
        try {
          if (operationId !== null) operationStore.finish(operationId)
        } finally {
          if (inFlight?.token === token) {
            inFlight = null
            busyState.value = false
          }
        }
      }
    }
  }

  function dispose() {
    if (disposed) return
    disposed = true
    generation += 1
    inFlight?.abortController?.abort()
    busyState.value = false
  }

  return {
    busy,
    error,
    backup,
    dispose,
  }
}
