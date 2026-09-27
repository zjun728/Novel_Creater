import { authorValue } from './continuityController.js'

const DIMENSIONS = Object.freeze({ stage: '当前阶段', currentStage: '当前阶段', goal: '目标', belief: '信念', relationship: '关系', ability: '能力', trust: '信任变化', growth: '成长变化' })
const THREAD_TYPES = Object.freeze({ main: '主线', mainline: '主线', subplot: '支线', sub: '支线', character: '人物线', mystery: '悬念', foreshadow: '伏笔', foreshadowing: '伏笔' })
const STATUSES = Object.freeze({ planted: '已埋设', introduced: '已引入', started: '已开始', advanced: '已推进', resolved: '已回收', completed: '已完成', open: '进行中' })
const own = (value, key) => Object.hasOwn(value, key)
const labelFor = (labels, key) => typeof key === 'string' && own(labels, key) ? labels[key] : ''
const objectValue = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const chapter = value => Number.isSafeInteger(value) && value > 0 ? `第 ${value} 章` : ''

// Canon accepts arbitrary JSON. Only explicit keys carry presentation semantics;
// a missing key is not evidence that a goal, arc or thread has been completed.
export function continuityRecordDetails(record = {}, kind = 'facts') {
  const value = record.value
  const object = objectValue(value) ? value : {}
  const segments = typeof record.field === 'string' ? record.field.split('.') : []
  const rows = []
  const consumed = new Set()
  function take(key, label, format = authorValue) {
    if (!own(object, key)) return
    const content = format(object[key])
    const lines = Array.isArray(content) ? content : [content]
    if (lines.filter(Boolean).length) { rows.push({ label, lines: lines.filter(Boolean) }); consumed.add(key) }
  }
  let title = kind === 'state' ? '当前状态' : kind === 'memory' ? (record.isClaim ? '记录中的人物说法' : '已发生的记忆') : ''
  if (kind === 'arcs') {
    title = '已发生的人物变化'
    for (const [key, label] of Object.entries(DIMENSIONS)) take(key, label)
    if (!objectValue(value) && labelFor(DIMENSIONS, segments[1])) rows.push({ label: labelFor(DIMENSIONS, segments[1]), lines: authorValue(value) })
  }
  if (kind === 'clues') {
    title = labelFor(THREAD_TYPES, segments[1]) || labelFor(THREAD_TYPES, object.threadType) || labelFor(THREAD_TYPES, object.type) || '情节线索 · 类别未注明'
    for (const key of ['threadType', 'type']) if (labelFor(THREAD_TYPES, object[key])) consumed.add(key)
    take('status', '当前进展', status => typeof status === 'string' ? labelFor(STATUSES, status) || status : authorValue(status))
    take('plannedResolutionChapter', '记录中的计划回收章（不代表已发生）', chapter)
    take('actualResolutionChapter', '实际回收章', chapter)
    if (labelFor(STATUSES, value)) rows.push({ label: '当前进展', lines: [labelFor(STATUSES, value)] })
  }
  const remaining = objectValue(value) ? Object.fromEntries(Object.entries(object).filter(([key]) => !consumed.has(key))) : value
  const lines = ['arcs', 'clues'].includes(kind) && !objectValue(value) && rows.length ? [] : authorValue(remaining)
  const source = chapter(record.sourceChapter)
  const formed = chapter(record.formedChapter)
  return {
    title, rows, lines,
    provenance: kind === 'memory' || kind === 'facts' ? (source ? `本条事件发生于${source}` : '') : [formed ? `首次形成于${formed}` : '', source ? `本项最近更新于${source}` : ''].filter(Boolean).join('；'),
    note: kind === 'arcs' ? '仅展示正文已确认的变化；未来弧光节点请对照未来计划。' : kind === 'memory' && record.isClaim ? '人物说法保留为记忆，不作为客观状态。' : '',
  }
}
