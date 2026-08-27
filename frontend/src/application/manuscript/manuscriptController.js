import { shallowRef } from 'vue'
import { mapProjectNextAction } from '../projects/projectNextAction.js'

const COPY = Object.freeze({
  'missing-project': '项目不存在或已被删除', 'missing-chapter': '章节不存在',
  'invalid-address': '章节地址无效', 'integrity-failure': '章节内容校验失败', unavailable: '正文暂时无法加载',
})
const ERROR_STATUS = Object.freeze({ ManuscriptProjectNotFound: 'missing-project', FinalChapterNotFound: 'missing-chapter', ManuscriptRequestInvalid: 'invalid-address', ManuscriptIntegrityFailure: 'integrity-failure', ManuscriptTemporarilyUnavailable: 'unavailable' })
function normalizeProjectId(value) { if (typeof value !== 'string') return null; const id = value.trim(); return id && !/[\u0000-\u001f\u007f]/u.test(id) ? id : null }
const normalizeChapter = value => Number.isSafeInteger(value) && value > 0 ? value : null
function contentState(status, { data = null, correlationId = '' } = {}) { return Object.freeze({ status, title: COPY[status] || '', correlationId, data }) }
const preparationState = (status, nextAction = null) => Object.freeze({ status, nextAction })
const safeCorrelationId = value => typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/u.test(value) ? value : ''
const correlation = error => ['ManuscriptIntegrityFailure', 'ManuscriptTemporarilyUnavailable'].includes(error?.code) ? safeCorrelationId(error?.correlationId) : ''

export function createManuscriptController({ api, abortControllerFactory = () => new AbortController() } = {}) {
  if (!api?.manuscripts || !api?.projects || typeof abortControllerFactory !== 'function') throw new TypeError('manuscript API and abortControllerFactory are required')
  const content = shallowRef(contentState('idle')); const preparation = shallowRef(preparationState('idle'))
  let generation = 0; let preparationGeneration = 0; let key = ''; let controller = null; let disposed = false
  function invalidate(state) { generation += 1; key = ''; controller?.abort(); controller = null; content.value = state }
  function makeController() { const value = abortControllerFactory(); if (!value?.signal || typeof value.abort !== 'function') throw new TypeError('abortControllerFactory returned invalid controller'); return value }
  async function load(kind, rawProjectId, rawChapterNumber, { force = false } = {}) {
    const projectId = normalizeProjectId(rawProjectId); const chapterNumber = kind === 'chapter' ? normalizeChapter(rawChapterNumber) : null
    if (!projectId || (kind === 'chapter' && !chapterNumber)) { invalidate(contentState('invalid-address')); return content.value }
    const nextKey = `${kind}\u0000${projectId}\u0000${chapterNumber ?? ''}`; const same = nextKey === key
    if (same && !force) return content.value
    const prior = content.value.data; controller?.abort(); controller = makeController(); key = nextKey; const token = ++generation
    content.value = contentState('loading', { data: same && force ? prior : null })
    try {
      const data = kind === 'chapter' ? await api.manuscripts.chapter(projectId, chapterNumber, { signal: controller.signal }) : await api.manuscripts.index(projectId, { signal: controller.signal })
      if (data?.projectId !== projectId || (kind === 'chapter' && data?.chapter?.number !== chapterNumber)) { if (!disposed && token === generation) content.value = contentState('integrity-failure'); return content.value }
      if (!disposed && token === generation) content.value = contentState(kind === 'directory' && data.volumes.length === 0 ? 'empty' : 'ready', { data })
    } catch (error) {
      if (disposed || token !== generation) return content.value
      const status = ERROR_STATUS[error?.code] || 'unavailable'
      content.value = contentState(status, { data: same && force && error?.code === 'ManuscriptTemporarilyUnavailable' ? prior : null, correlationId: correlation(error) })
    }
    return content.value
  }
  const loadContent = (projectId, chapterNumber, options) => load('chapter', projectId, chapterNumber, options)
  const loadDirectory = (projectId, options) => load('directory', projectId, null, options)
  async function loadPreparation(rawProjectId) {
    const projectId = normalizeProjectId(rawProjectId); if (!projectId) { preparation.value = preparationState('unavailable'); return preparation.value }
    const token = ++preparationGeneration; preparation.value = preparationState('loading')
    try { const mapped = mapProjectNextAction(await api.projects.preparation(projectId)); if (!disposed && token === preparationGeneration) preparation.value = preparationState(mapped.state === 'archived' ? 'archived' : mapped.state === 'available' ? 'ready' : 'unavailable', mapped) } catch { if (!disposed && token === preparationGeneration) preparation.value = preparationState('unavailable') }
    return preparation.value
  }
  function dispose() { disposed = true; generation += 1; preparationGeneration += 1; controller?.abort() }
  return { content, preparation, loadContent, loadDirectory, loadPreparation, dispose }
}
