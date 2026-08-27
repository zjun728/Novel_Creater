import { ref, shallowRef } from 'vue'
import { mapProjectNextAction } from '../projects/projectNextAction.js'

const CONTENT_COPY = Object.freeze({
  'missing-project': '项目不存在或已被删除', 'missing-chapter': '章节不存在',
  'invalid-address': '章节地址无效', 'integrity-failure': '章节内容校验失败',
  unavailable: '正文暂时无法加载',
})
const validProjectId = value => typeof value === 'string' && value.trim() !== ''
const validChapter = value => Number.isInteger(value) && value > 0
function contentState(status, data = {}) { return Object.freeze({ status, title: CONTENT_COPY[status] || '', correlationId: data.correlationId || '', directory: data.directory || null, chapter: data.chapter || null, outline: data.outline || null }) }
function preparationState(status, data = {}) { return Object.freeze({ status, nextAction: data.nextAction || null }) }
function safeCorrelationId(value) { return typeof value === 'string' && /^[A-Za-z0-9_-]{1,128}$/u.test(value) ? value : '' }
function errorStatus(error) {
  return ({ ManuscriptProjectNotFound: 'missing-project', FinalChapterNotFound: 'missing-chapter', ManuscriptRequestInvalid: 'invalid-address', ManuscriptIntegrityFailure: 'integrity-failure', ManuscriptTemporarilyUnavailable: 'unavailable' })[error?.code] || 'unavailable'
}

export function createManuscriptController({ api, abortControllerFactory = () => new AbortController() } = {}) {
  if (!api?.manuscripts || !api?.projects || typeof abortControllerFactory !== 'function') throw new TypeError('manuscript API and abortControllerFactory are required')
  const content = shallowRef(contentState('idle'))
  const preparation = shallowRef(preparationState('idle'))
  let generation = 0; let preparationGeneration = 0; let currentKey = ''; let currentAbort = null; let disposed = false
  function publishContent(token, state) { if (!disposed && token === generation) content.value = state }
  async function loadContent(projectId, chapterNumber, { force = false } = {}) {
    if (!validProjectId(projectId) || !validChapter(chapterNumber)) { content.value = contentState('invalid-address'); return content.value }
    const key = `${projectId}\u0000${chapterNumber}`
    if (!force && key === currentKey) return content.value
    currentAbort?.abort(); currentAbort = abortControllerFactory()
    if (!currentAbort || typeof currentAbort.abort !== 'function' || !currentAbort.signal) throw new TypeError('abortControllerFactory returned invalid controller')
    currentKey = key; const token = ++generation
    const prior = content.value
    content.value = contentState('loading', { chapter: prior.chapter, outline: prior.outline, directory: prior.directory })
    try {
      const result = await api.manuscripts.chapter(projectId, chapterNumber, { signal: currentAbort.signal })
      if (result?.projectId !== projectId || result?.chapter?.number !== chapterNumber) return publishContent(token, contentState('integrity-failure'))
      publishContent(token, contentState('ready', { chapter: result.chapter, outline: result.outline }))
    } catch (error) {
      if (currentAbort.signal.aborted && token !== generation) return content.value
      const status = errorStatus(error)
      const retain = status === 'unavailable' ? { chapter: prior.chapter, outline: prior.outline, directory: prior.directory } : {}
      publishContent(token, contentState(status, { ...retain, correlationId: ['integrity-failure', 'unavailable'].includes(status) ? safeCorrelationId(error?.correlationId) : '' }))
    }
    return content.value
  }
  async function loadDirectory(projectId, { force = false } = {}) {
    if (!validProjectId(projectId)) { content.value = contentState('invalid-address'); return content.value }
    const key = `${projectId}\u0000`
    if (!force && key === currentKey) return content.value
    currentAbort?.abort(); currentAbort = abortControllerFactory(); if (!currentAbort?.signal || typeof currentAbort.abort !== 'function') throw new TypeError('abortControllerFactory returned invalid controller')
    currentKey = key; const token = ++generation; content.value = contentState('loading')
    try { const directory = await api.manuscripts.index(projectId, { signal: currentAbort.signal }); if (directory?.projectId !== projectId) publishContent(token, contentState('integrity-failure')); else publishContent(token, contentState(directory.volumes.every(volume => volume.chapters.length === 0) ? 'empty' : 'ready', { directory })) }
    catch (error) { if (!(currentAbort.signal.aborted && token !== generation)) publishContent(token, contentState(errorStatus(error), { correlationId: safeCorrelationId(error?.correlationId) })) }
    return content.value
  }
  async function loadPreparation(projectId) {
    if (!validProjectId(projectId)) { preparation.value = preparationState('unavailable'); return preparation.value }
    const token = ++preparationGeneration
    preparation.value = preparationState('loading')
    try { const authority = await api.projects.preparation(projectId); const nextAction = mapProjectNextAction(authority); if (!disposed && token === preparationGeneration) preparation.value = preparationState(nextAction.state === 'archived' ? 'archived' : nextAction.state === 'available' ? 'ready' : 'unavailable', { nextAction }); }
    catch { if (!disposed && token === preparationGeneration) preparation.value = preparationState('unavailable') }
    return preparation.value
  }
  function dispose() { disposed = true; generation += 1; preparationGeneration += 1; currentAbort?.abort() }
  return { content, preparation, loadContent, loadDirectory, loadPreparation, dispose }
}
