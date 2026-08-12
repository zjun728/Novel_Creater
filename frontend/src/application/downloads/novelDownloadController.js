import { computed, ref, shallowRef } from 'vue'

function safeOptions(value) {
  if (
    !value
    || typeof value !== 'object'
    || typeof value.available !== 'boolean'
    || !Array.isArray(value.formats)
    || !Array.isArray(value.volumes)
    || !Array.isArray(value.chapters)
    || !(value.reason === null || value.reason === undefined || typeof value.reason === 'string')
  ) {
    throw new TypeError('invalid novel download options')
  }
  const formats = value.formats.map(format => {
    if (format !== 'txt' && format !== 'markdown') throw new TypeError('invalid novel download format')
    return format
  })
  const volumes = value.volumes.map(volume => {
    if (
      !volume
      || typeof volume.id !== 'string'
      || !volume.id
      || !Number.isInteger(volume.order)
      || volume.order < 1
      || typeof volume.title !== 'string'
    ) throw new TypeError('invalid novel download volume')
    return Object.freeze({ id: volume.id, order: volume.order, title: volume.title })
  })
  const chapters = value.chapters.map(chapter => {
    if (
      !chapter
      || !Number.isInteger(chapter.number)
      || chapter.number < 1
      || typeof chapter.title !== 'string'
      || typeof chapter.volumeId !== 'string'
      || !chapter.volumeId
    ) throw new TypeError('invalid novel download chapter')
    return Object.freeze({
      number: chapter.number, title: chapter.title, volumeId: chapter.volumeId,
    })
  })
  return Object.freeze({
    available: value.available,
    reason: typeof value.reason === 'string' ? value.reason : null,
    formats: Object.freeze(formats),
    volumes: Object.freeze(volumes),
    chapters: Object.freeze(chapters),
  })
}

function fallbackFilename(selector) {
  return selector?.format === 'markdown' ? 'novel.md' : 'novel.txt'
}

function safeFilename(value) {
  if (typeof value !== 'string' || !value || value === '.' || value === '..') return null
  if (/[\\/\u0000-\u001f\u007f]/u.test(value)) return null
  if (!/\.(?:txt|md)$/iu.test(value)) return null
  return value
}

export function filenameFromContentDisposition(contentDisposition, selector) {
  if (typeof contentDisposition !== 'string') return fallbackFilename(selector)
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
  return fallbackFilename(selector)
}

export function createNovelDownloadController({
  api,
  operationStore,
  createObjectURL,
  revokeObjectURL,
  saveBlob,
  abortControllerFactory = () => new AbortController(),
} = {}) {
  if (!api?.novelDownloads || !operationStore || !createObjectURL || !revokeObjectURL || !saveBlob) {
    throw new TypeError('novel download dependencies are required')
  }

  const options = shallowRef(null)
  const loadingState = ref(false)
  const busyState = ref(false)
  const error = ref('')
  let loadGeneration = 0
  let downloadGeneration = 0
  let disposed = false
  let inFlight = null

  const loading = computed(() => loadingState.value)
  const busy = computed(() => busyState.value)
  const available = computed(() => options.value?.available === true)

  async function loadOptions(projectId) {
    if (disposed || loadingState.value) return false
    const token = ++loadGeneration
    const active = () => !disposed && token === loadGeneration
    loadingState.value = true
    error.value = ''
    try {
      const loaded = safeOptions(await api.novelDownloads.options(projectId))
      if (!active()) return false
      options.value = loaded
      return loaded
    } catch (failure) {
      if (active()) error.value = '下载选项加载失败，请重试。'
      throw failure
    } finally {
      if (active()) loadingState.value = false
    }
  }

  async function download(projectId, selector) {
    if (disposed || inFlight || !available.value) return false
    const token = ++downloadGeneration
    const abortController = abortControllerFactory()
    if (!abortController?.signal || typeof abortController.abort !== 'function') {
      throw new TypeError('abortControllerFactory must return an AbortController')
    }
    const active = () => !disposed && inFlight?.token === token
    const operationId = operationStore.start({
      label: '正在准备下载', detail: '', blocking: true,
    })
    inFlight = { token, abortController }
    busyState.value = true
    error.value = ''
    let objectUrl = null
    try {
      const result = await api.novelDownloads.download(projectId, selector, {
        signal: abortController.signal,
      })
      if (!active()) return false
      objectUrl = createObjectURL(result?.blob)
      const filename = filenameFromContentDisposition(result?.contentDisposition, selector)
      saveBlob(objectUrl, filename)
      return true
    } catch (failure) {
      if (active()) error.value = '下载失败，请重试。'
      throw failure
    } finally {
      try {
        if (objectUrl !== null) revokeObjectURL(objectUrl)
      } finally {
        operationStore.finish(operationId)
        if (inFlight?.token === token) {
          inFlight = null
          busyState.value = false
        }
      }
    }
  }

  function dispose() {
    if (disposed) return
    disposed = true
    loadGeneration += 1
    inFlight?.abortController.abort()
    busyState.value = false
  }

  return {
    options,
    loading,
    busy,
    error,
    available,
    loadOptions,
    download,
    dispose,
  }
}
