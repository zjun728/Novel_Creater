const SYSTEM_TAG_TITLES = new Set([
  '主线推进',
  '世界观',
  '身体状态',
  '时间线',
  '时间紧迫线',
  '关键道具清单',
  '线索判断',
  '章节锚点',
  '硬状态账本',
  '关键地点线',
  '势力斗争线',
  '追捕线',
  '感情关系线'
])

const REAL_THREAD_TITLES = new Set([
  '星账代价线',
  '父亲线索线',
  '第三密栈行动',
  '庚字号门后的真相',
  '天池裂隙',
  '徐正清身份疑点',
  '小九身世线',
  '反派阴谋线',
  '主角身世线',
  '关键道具线'
])

const BROAD_UNRESOLVABLE_TITLES = new Set([
  '主角身世线',
  '关键道具线',
  '反派阴谋线',
  '星账代价线',
  '主线推进'
])

const EXPLICIT_RESOLVE_PATTERNS = [
  /真相揭开/,
  /谜底是/,
  /证实为/,
  /已确认答案/,
  /找到真正原因/,
  /完成回收/,
  /正式揭示/
]

const SYSTEM_TITLE_PATTERN = /(状态|清单|时间节点|时间线|位置|所在地|持有物|下一步行动|地形信息|普通状态|身体|伤势|伤口|规则|机制|世界观|章节锚点|硬状态账本)$/
const REAL_TITLE_PATTERN = /(线$|真相|之谜|秘密|疑点|阴谋|黑幕|密栈|裂隙|门后|代价|旧案|身世)/

export function normalizePlotThreadTitle(value = '') {
  return String(value || '')
    .trim()
    .replace(/^[#＃]+/, '')
    .replace(/^[「《【[(（\s]+|[」》】\])）\s]+$/g, '')
    .replace(/[：:、，,。；;]+$/g, '')
    .trim()
}

function textOf(thread = {}) {
  return [
    thread.title,
    thread.content,
    thread.notes,
    thread.evidence
  ].filter(Boolean).join(' ')
}

function isFutureCandidate(thread = {}) {
  const status = thread.status || ''
  const text = textOf(thread)
  return status === 'candidate' && /候选来源|foreshadowingPlan|分卷规划|未来候选|尚未由 Canon facts 证明/.test(text)
}

function isSystemTagTitle(title = '') {
  if (SYSTEM_TAG_TITLES.has(title)) return true
  if (REAL_THREAD_TITLES.has(title)) return false
  return SYSTEM_TITLE_PATTERN.test(title)
}

export function inferPlotThreadType(thread = {}) {
  const title = normalizePlotThreadTitle(thread.title)
  if (/主线|父亲|身世|旧案/.test(title)) return 'mainline'
  if (/小九|徐正清|陆沉舟|陆长庚|身份/.test(title)) return 'character'
  if (/钥匙|账|星账|道具|玉佩|印|门/.test(title)) return 'prop'
  if (/巡天司|商盟|星债会|密栈|势力|反派/.test(title)) return 'faction'
  if (/灵脉|规则|天池|裂隙|代价|世界观/.test(title)) return 'setting'
  return 'other'
}

export function latestPlotThreadChapter(thread = {}) {
  const notes = String(thread.notes || '')
  const matches = [...notes.matchAll(/第\s*(\d+)\s*章/g)].map(match => Number(match[1])).filter(Boolean)
  return Number(thread.latestChapter || thread.latest_chapter || 0) ||
    (matches.length ? Math.max(...matches) : 0) ||
    Number(thread.resolvedChapter || thread.resolved_chapter || 0) ||
    Number(thread.plantedChapter || thread.planted_chapter || 0)
}

export function latestPlotThreadSummary(thread = {}) {
  const notes = String(thread.notes || '')
  const match = notes.match(/最近推进：第\s*\d+\s*章[，,]\s*(.+)$/)
  if (match?.[1]) return match[1]
  return notes || thread.content || ''
}

export function plotThreadNodeSummary(thread = {}) {
  const planted = Number(thread.plantedChapter || thread.planted_chapter || 0)
  const latest = latestPlotThreadChapter(thread)
  const resolved = Number(thread.resolvedChapter || thread.resolved_chapter || 0)
  const nodes = []
  if (planted) nodes.push(`第 ${planted} 章埋设`)
  if (latest && latest !== planted && latest !== resolved) nodes.push(`第 ${latest} 章推进`)
  if (resolved) nodes.push(`第 ${resolved} 章回收`)
  return nodes.join(' -> ')
}

export function shouldResolvePlotThread(thread = {}, facts = []) {
  const title = normalizePlotThreadTitle(thread.title)
  if (BROAD_UNRESOLVABLE_TITLES.has(title)) return false
  const source = [
    textOf(thread),
    ...facts.map(fact => textOf(fact))
  ].join(' ')
  return EXPLICIT_RESOLVE_PATTERNS.some(pattern => pattern.test(source))
}

export function classifyPlotThread(thread = {}) {
  const title = normalizePlotThreadTitle(thread.title)
  let threadClass = 'system_tag'
  if (isFutureCandidate(thread)) {
    threadClass = 'future_candidate'
  } else if (isSystemTagTitle(title)) {
    threadClass = 'system_tag'
  } else if (REAL_THREAD_TITLES.has(title) || REAL_TITLE_PATTERN.test(title)) {
    threadClass = 'real_thread'
  }
  return {
    ...thread,
    normalizedTitle: title,
    threadClass,
    threadType: thread.threadType || thread.thread_type || inferPlotThreadType(thread),
    latestChapter: latestPlotThreadChapter(thread),
    latestSummary: latestPlotThreadSummary(thread),
    nodeSummary: plotThreadNodeSummary(thread)
  }
}

export function classifyPlotThreads(threads = []) {
  return threads.map(classifyPlotThread)
}

export function defaultVisiblePlotThreads(threads = []) {
  return classifyPlotThreads(threads)
    .filter(thread => thread.threadClass === 'real_thread')
    .sort((a, b) => {
      const statusOrder = { developing: 0, planted: 1, resolved: 2, transformed: 3, abandoned: 4 }
      return (statusOrder[a.status] ?? 5) - (statusOrder[b.status] ?? 5) ||
        Number(b.latestChapter || 0) - Number(a.latestChapter || 0) ||
        String(a.title || '').localeCompare(String(b.title || ''), 'zh-Hans-CN')
    })
}
