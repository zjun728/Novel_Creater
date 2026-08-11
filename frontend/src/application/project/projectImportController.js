import { computed, ref } from 'vue'
import { isNavigationFailure } from 'vue-router'

import { ApiError } from '../../api/db/api-error.js'

const PREFLIGHT_ERROR = '无法检查此备份，请重新选择或重试。'
const IMPORT_ERROR = '项目导入失败，请重试。'
const TITLE_ERROR = '请输入 1 至 200 个字符的项目名称。'
const POLL_DELAY_MS = 1_000

export const PROJECT_IMPORT_PHASES = Object.freeze([
  '正在上传项目备份',
  '正在检查项目备份',
  '正在暂存项目资料',
  '正在发布新项目',
  '正在恢复导入状态',
])

function defaultIdentity() {
  if (typeof globalThis.crypto?.randomUUID !== 'function') {
    throw new TypeError('secure UUID generation is unavailable')
  }
  return {
    commandId: globalThis.crypto.randomUUID(),
    idempotencyKey: globalThis.crypto.randomUUID(),
  }
}

function defaultWait(delay, signal) {
  return new Promise((resolve, reject) => {
    let settled = false
    const finish = callback => {
      if (settled) return
      settled = true
      signal?.removeEventListener?.('abort', abort)
      callback()
    }
    const timer = setTimeout(() => finish(resolve), delay)
    const abort = () => {
      clearTimeout(timer)
      finish(() => reject(new DOMException('aborted', 'AbortError')))
    }
    if (signal?.aborted) abort()
    else signal?.addEventListener?.('abort', abort, { once: true })
  })
}

function isUnknownResult(error) {
  return error instanceof ApiError && (
    error.status === 0
    || error.code === 'request_timeout'
    || error.code === 'request_failed'
  )
}

export function createProjectImportController({
  api,
  router,
  operationStore,
  createIdentity = defaultIdentity,
  abortControllerFactory = () => new AbortController(),
  wait = defaultWait,
} = {}) {
  if (
    typeof api?.projectImports?.preflight !== 'function'
    || typeof api?.projectImports?.publish !== 'function'
    || typeof api?.projectImports?.get !== 'function'
    || typeof router?.push !== 'function'
    || typeof operationStore?.start !== 'function'
    || typeof operationStore?.update !== 'function'
    || typeof operationStore?.finish !== 'function'
    || typeof createIdentity !== 'function'
    || typeof abortControllerFactory !== 'function'
    || typeof wait !== 'function'
  ) throw new TypeError('project import dependencies are required')

  const selectedFile = ref(null)
  const preflightSummary = ref(null)
  const proposedTitle = ref('')
  const busyState = ref(false)
  const error = ref('')
  let ownedIdentity = null
  let ownedCommand = null
  let generation = 0
  let disposed = false
  let inFlight = null

  const filename = computed(() => selectedFile.value?.name || '')
  const busy = computed(() => busyState.value)
  const titleEditable = computed(() => !ownedCommand && !busyState.value)
  const ready = computed(() => Boolean(
    selectedFile.value
    && preflightSummary.value
    && proposedTitle.value === proposedTitle.value.trim()
    && proposedTitle.value.length >= 1
    && proposedTitle.value.length <= 200
    && !busyState.value,
  ))

  function abortCurrent() {
    inFlight?.abortController?.abort()
    inFlight = null
  }

  async function selectFile(nextFile) {
    if (disposed) return false
    if (typeof File === 'undefined' || !(nextFile instanceof File)) {
      throw new TypeError('project import requires a File')
    }
    abortCurrent()
    const token = ++generation
    const abortController = abortControllerFactory()
    selectedFile.value = nextFile
    preflightSummary.value = null
    proposedTitle.value = ''
    ownedIdentity = createIdentity()
    ownedCommand = null
    error.value = ''
    busyState.value = true
    inFlight = { token, abortController, kind: 'preflight' }
    const active = () => !disposed && generation === token && inFlight?.token === token
    try {
      const result = await api.projectImports.preflight(nextFile, {
        signal: abortController.signal,
      })
      if (!active()) return false
      preflightSummary.value = result
      proposedTitle.value = String(result?.proposedTitle || '')
      return true
    } catch (failure) {
      if (!active()) return false
      error.value = PREFLIGHT_ERROR
      return false
    } finally {
      if (active()) {
        inFlight = null
        busyState.value = false
      }
    }
  }

  function setTitle(value) {
    if (disposed || busyState.value || ownedCommand) return false
    proposedTitle.value = String(value ?? '')
    error.value = ''
    return true
  }

  async function importProject() {
    if (disposed || inFlight || !selectedFile.value || !preflightSummary.value) return false
    const title = proposedTitle.value
    if (title !== title.trim() || title.length < 1 || title.length > 200) {
      error.value = TITLE_ERROR
      return false
    }
    const token = ++generation
    const abortController = abortControllerFactory()
    const retainedFile = selectedFile.value
    ownedCommand ||= Object.freeze({
      commandId: ownedIdentity.commandId,
      idempotencyKey: ownedIdentity.idempotencyKey,
      expectedPackageHash: preflightSummary.value.packageHash,
      newTitle: title,
    })
    const command = ownedCommand
    inFlight = { token, abortController, kind: 'import' }
    busyState.value = true
    error.value = ''
    const active = () => !disposed && generation === token && inFlight?.token === token
    let operationId = null
    let phaseIndex = 0
    const advance = target => {
      while (phaseIndex < target && active()) {
        phaseIndex += 1
        operationStore.update(operationId, {
          label: PROJECT_IMPORT_PHASES[phaseIndex], detail: '',
        })
      }
    }

    async function postRetained() {
      try {
        return await api.projectImports.publish(retainedFile, command, {
          signal: abortController.signal,
        })
      } catch (failure) {
        if (!isUnknownResult(failure)) throw failure
        return null
      }
    }

    try {
      operationId = operationStore.start({
        label: PROJECT_IMPORT_PHASES[0], detail: '', blocking: true,
      })
      let outcome = await postRetained()
      if (!active()) return false
      if (outcome === null) advance(4)
      else advance(1)

      while (active()) {
        if (outcome?.status === 'succeeded' && outcome.targetProjectId) {
          advance(4)
          if (operationId !== null) {
            operationStore.finish(operationId)
            operationId = null
          }
          const navigationFailure = await router.push(
            `/projects/${encodeURIComponent(outcome.targetProjectId)}/overview`,
          )
          if (isNavigationFailure(navigationFailure)) throw navigationFailure
          if (!active()) return false
          selectedFile.value = null
          preflightSummary.value = null
          proposedTitle.value = ''
          ownedIdentity = null
          ownedCommand = null
          return true
        }
        if (outcome?.status === 'failed') {
          error.value = IMPORT_ERROR
          return false
        }
        if (outcome?.status === 'running' && outcome.retryRequired === true) {
          advance(3)
          outcome = await postRetained()
          if (!active()) return false
          if (outcome === null) advance(4)
          continue
        }
        if (outcome?.phase === 'staged') advance(2)
        else if (outcome?.phase === 'publishing') advance(3)
        advance(4)
        if (outcome?.status === 'running') {
          await wait(POLL_DELAY_MS, abortController.signal)
          if (!active()) return false
        }
        try {
          outcome = await api.projectImports.get(command.commandId, {
            signal: abortController.signal,
          })
        } catch (failure) {
          if (!isUnknownResult(failure)) throw failure
          await wait(POLL_DELAY_MS, abortController.signal)
          outcome = null
        }
      }
      return false
    } catch (failure) {
      if (!active()) return false
      error.value = IMPORT_ERROR
      return false
    } finally {
      if (operationId !== null) operationStore.finish(operationId)
      if (inFlight?.token === token) {
        inFlight = null
        busyState.value = false
      }
    }
  }

  function dispose() {
    if (disposed) return
    disposed = true
    generation += 1
    abortCurrent()
    busyState.value = false
  }

  return {
    file: selectedFile,
    filename,
    summary: preflightSummary,
    title: proposedTitle,
    busy,
    ready,
    titleEditable,
    error,
    selectFile,
    setTitle,
    importProject,
    dispose,
  }
}
