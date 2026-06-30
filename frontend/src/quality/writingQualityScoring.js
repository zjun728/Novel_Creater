import {
  AI_TRACE_DIMENSIONS,
  HUMAN_TEXTURE_DIMENSIONS,
  NARRATIVE_READABILITY_GATES,
  getDimensionLabel,
  getQualityLevelLabel,
  getRhythmQualitySignals,
  mapIssueTypeToQualitySignals
} from './writingQualityStandard.js'

const SEVERITY_WEIGHT = {
  suggestion: 0.5,
  minor: 1,
  warning: 1,
  medium: 1.5,
  major: 2,
  high: 2,
  critical: 3,
  severe: 3
}

const LEVEL_RANK = { low: 1, medium: 2, high: 3, severe: 4 }

export const IRREVERSIBLE_CHANGE_RULES = [
  { type: 'relationship_change', label: '关系变化', pattern: /关系|决裂|破裂|信任|背叛|合作|拒绝|后退|让步|公开否认|同盟|重组/ },
  { type: 'clue_progress', label: '线索推进', pattern: /线索|地址|坐标|证据|名单|地图|暗号|新事实|阶段性结论|证伪|失效|不再作为/ },
  { type: 'location_change', label: '地点变化', pattern: /离开|抵达|进入|前往|转入|新地点|门外|楼下|车站|街口|室内|室外/ },
  { type: 'goal_change', label: '目标变化', pattern: /决定|选择|改为|不再|必须|放弃|转向|目标|资格|换取/ },
  { type: 'cost_paid', label: '代价兑现', pattern: /代价|烧掉|烧毁|失去|扣除|交出|付出|疼|伤|冷却|寿命|永久失效|换取/ },
  { type: 'enemy_state_change', label: '敌我态势变化', pattern: /追踪|追击|袭击|主动出手|暴露|包围|敌|威胁|警报|封锁|退后|打断|回收/ }
]
const VOLUME_HANDOFF_DERIVABLE_CHANGE_TYPES = new Set([
  'clue_progress',
  'location_change',
  'goal_change',
  'cost_paid',
  'enemy_state_change'
])

const LOOP_ACTION_MARKERS = ['观察', '看着', '盯着', '确认', '触摸', '感受', '感觉', '理解', '意识']
const EXTERNAL_ACTION_MARKERS = ['离开', '进入', '抵达', '前往', '打开', '关上', '烧毁', '摔碎', '交出', '拒绝', '换取', '拉住', '推开', '退后', '冲进', '走出', '藏起', '撕开', '锁死', '打断', '追上', '追击', '袭击', '包围', '封锁', '公开', '否认']
const ACTION_MARKERS = [...new Set([...LOOP_ACTION_MARKERS, ...EXTERNAL_ACTION_MARKERS, '选择', '放弃', '承认', '决定'])]
const COMMON_ACTION_EVIDENCE_STOP_TERMS = new Set([
  '观察', '看着', '盯着', '确认', '触摸', '感受', '感觉', '理解', '意识',
  '进入', '离开', '打开', '走', '走出', '说', '问', '选择', '决定', '继续',
  '拒绝', '交出', '站在', '公开'
])
const NGRAM_FRAGMENT_STOP_TERMS = new Set([
  '在那', '在那里', '色的', '墨看', '或规', '或规则', '入一', '着那',
  '个自', '个自己', '什么', '站在', '一章', '扇门', '愿望代', '望代价',
  '对愿望', '角对愿望', '敌方或规', '号门', '门开', '些门', '门里'
])
const ABSTRACT_CONTEXT_PATTERN = /不是|而是|感到|感觉|意识到|理解|确认|意味|意味着|象征|代表|证明|解释|概念|抽象|本质|逻辑|判断|结论/
const CONCRETE_OBJECT_PATTERN = /[门屋室楼街路巷桥井口铃钟纸卡册书证灯墙桌箱柜袋车船伞衣鞋瓶杯钥锁牌章票图线声痕印]/ 
const STOP_TERMS = new Set([
  '本章', '上一', '下一', '一个', '一种', '这里', '那里', '这个', '那个', '自己', '他们', '她们', '我们', '你们',
  '时候', '开始', '继续', '没有', '不是', '只是', '仍然', '已经', '可以', '不能', '必须', '因为', '所以',
  '正文', '章节', '小纲', '主角', '人物', '读者', '故事', '场景', '信息', '内容', '问题', '答案',
  '什么', '那些', '这个', '那个', '像是', '着那', '人说', '女人说', '男人说', '的声', '觉到', '能感',
  '规则', '系统', '愿望', '代价', '结果', '行动', '知道', '事情',
  '地点', '态势', '关系', '线索', '理解', '一章', '扇门', '空间', '房间', '目标', '冲突',
  '敌方', '证据'
])
const GENERIC_CHARACTER_LABELS = new Set(['男人', '女人', '老人', '少年', '少女', '孩子', '店员', '老师', '学生', '母亲', '父亲'])
const NUMBERED_ENTITY_PATTERN = /([0-9]{1,3}|[一二三四五六七八九十百千万两零〇]{1,5})号(?:门|房间|空间|档案|画布|凭证|卡|柜|箱)?/g
const EVENT_PATTERN_LOOP_THRESHOLD = 3
const HARD_SETTING_CONTRADICTION_TYPES = new Set([
  'world_rule',
  'setting_sync',
  'setting_contradiction',
  'plot_contradiction',
  'hard_state_conflict',
  'timeline',
  'state_carryover',
  'boundary_continuity'
])

function unique(values = []) {
  return [...new Set(values.filter(Boolean))]
}

function normalizeSeverity(severity) {
  return String(severity || 'minor').toLowerCase()
}

function addCounts(target, keys = [], weight = 1) {
  for (const key of keys) target[key] = Number(target[key] || 0) + weight
}

function levelFromScore(score, hasSevereIssue = false) {
  if (hasSevereIssue || score >= 7) return 'severe'
  if (score >= 3) return 'high'
  if (score >= 1.5) return 'medium'
  return 'low'
}

function levelFromHumanTextureScore(score, hasSevereIssue = false) {
  if (hasSevereIssue || score >= 10) return 'severe'
  if (score >= 8) return 'high'
  if (score >= 2) return 'medium'
  return 'low'
}

function maxLevel(...levels) {
  return levels
    .filter(Boolean)
    .sort((a, b) => (LEVEL_RANK[b] || 0) - (LEVEL_RANK[a] || 0))[0] || 'low'
}

function topCounts(counts, limit = 3) {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([dimension, count]) => ({
      dimension,
      label: getDimensionLabel(dimension),
      count
    }))
}

function countMatches(text, pattern) {
  const flags = pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`
  return String(text || '').match(new RegExp(pattern.source, flags))?.length || 0
}

function splitSentences(text = '') {
  return String(text || '')
    .split(/[。！？；;\n]+/)
    .map(item => item.trim())
    .filter(Boolean)
}

function escapeRegExp(value = '') {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function inferCharacterNamesFromSource(source = '') {
  const names = new Set()
  const text = String(source || '')
  const nameBeforeAction = /([\u4e00-\u9fa5]{2,4})(?:说|问|看着|站在|进入|离开|走出|抬头|低头|点头|摇头|回头|伸手|沉默)/g
  for (const match of text.matchAll(nameBeforeAction)) {
    const name = match[1]
    if (!STOP_TERMS.has(name) && !COMMON_ACTION_EVIDENCE_STOP_TERMS.has(name)) names.add(name)
  }
  for (const label of GENERIC_CHARACTER_LABELS) {
    if (text.includes(label)) names.add(label)
  }
  return [...names]
}

function buildTermFilters(source = '', options = {}) {
  const optionNames = Array.isArray(options.characterNames)
    ? options.characterNames
    : Array.isArray(options.coreCharacterNames)
      ? options.coreCharacterNames
      : []
  const characterNames = new Set([
    ...optionNames,
    ...inferCharacterNamesFromSource(source)
  ].map(item => String(item || '').trim()).filter(Boolean))
  return { characterNames }
}

function isCharacterTerm(value = '', filters = {}) {
  const names = filters && typeof filters === 'object' ? filters.characterNames || new Set() : new Set()
  for (const name of names) {
    if (!name) continue
    if (value === name || value.includes(name)) return true
  }
  return false
}

function isCommonActionEvidenceTerm(value = '') {
  if (COMMON_ACTION_EVIDENCE_STOP_TERMS.has(value)) return true
  return [...COMMON_ACTION_EVIDENCE_STOP_TERMS].some(action => value.includes(action))
}

function looksLikeNgramFragment(value = '') {
  const text = String(value || '').trim()
  if (NGRAM_FRAGMENT_STOP_TERMS.has(text)) return true
  if (/^(?:在那|在那里|色的|墨看|或规|入一|什么|站在)$/.test(text)) return true
  if (/^(?:色的|里色的|那里的|在那|在那里)/.test(text)) return true
  if (/^(?:案室|组的档案|的档案|的门)$/.test(text)) return true
  if (/^[\u4e00-\u9fa5]的(?:门|档案|画布|凭证|规则|线索)$/.test(text)) return true
  if (/或规/.test(text)) return true
  if (/^(?:号门|门开|些门|门里)$/.test(text)) return true
  if (/^(在|或|入|个|那|这|的|了|着|过)/.test(text)) return true
  if (/(的|地|得|了|着|过|那|这|个|一|或)$/.test(text)) return true
  if (/^[\u4e00-\u9fa5](?:看|说|问|进|入|走|离|感|觉|想|知|听)/.test(text)) return true
  if (/^[\u4e00-\u9fa5](?:规|则|自|己|什|么)$/.test(text)) return true
  if (/^(?:在|那|这|或|入|个|色|墨).{1,2}$/.test(text) && !CONCRETE_OBJECT_PATTERN.test(text)) return true
  return false
}

function hasNarrativeTermSignal(value = '') {
  const text = String(value || '').trim()
  if (CONCRETE_OBJECT_PATTERN.test(text)) return true
  if (ACTION_MARKERS.some(marker => text.includes(marker))) return true
  return /愿字|画布|钥匙|凭证|档案|账册|名单|证据|坐标|地址|身份|真相|交易所|回收组|敌方|同盟|封锁|追击|夺走|走廊|编号门|编号档案|编号画布|编号凭证/.test(text)
}

function isUsefulTerm(term = '', filterOptions = {}) {
  const filters = filterOptions && typeof filterOptions === 'object' ? filterOptions : {}
  const value = String(term || '').trim()
  if (value.length < 2 || value.length > 8) return false
  if (STOP_TERMS.has(value)) return false
  if (isCharacterTerm(value, filters)) return false
  if (isCommonActionEvidenceTerm(value)) return false
  if (looksLikeNgramFragment(value)) return false
  if (!hasNarrativeTermSignal(value)) return false
  if (/^[一二三四五六七八九十百千万年月日上下左右前后内外大小多少]+$/.test(value)) return false
  if (/^(这个|那个|一种|一个|已经|仍然|继续|没有|只是)/.test(value)) return false
  return /[\u4e00-\u9fa5]{2,8}/.test(value)
}

function sentenceTerms(sentence = '', filters = {}) {
  const terms = new Set()
  const runs = String(sentence || '').match(/[\u4e00-\u9fa5]{2,12}/g) || []
  for (const run of runs) {
    if (isUsefulTerm(run, filters)) terms.add(run)
    const chars = [...run]
    for (const size of [2, 3, 4]) {
      if (chars.length < size) continue
      for (let index = 0; index <= chars.length - size; index += 1) {
        const term = chars.slice(index, index + size).join('')
        if (isUsefulTerm(term, filters)) terms.add(term)
      }
    }
  }
  return [...terms]
}

function concreteNarrativeObjects(sentence = '', filters = {}) {
  const terms = new Set()
  for (const match of String(sentence || '').matchAll(NUMBERED_ENTITY_PATTERN)) {
    const suffix = match[0]
    if (isUsefulTerm(suffix, filters)) terms.add(suffix)
  }
  const concreteMatches = String(sentence || '').match(/[\u4e00-\u9fa5]{0,4}(?:愿字|画布|钥匙|凭证|档案|账册|名册|名单|信笺|黑卡|残页|椅子|走廊|封锁名单)/g) || []
  for (const item of concreteMatches) {
    const term = item.trim()
    if (isUsefulTerm(term, filters)) terms.add(term)
  }
  return [...terms]
}

function categoryForTerm(term, sentence, filters = {}) {
  if (!isUsefulTerm(term, filters)) return ''
  if (ACTION_MARKERS.some(marker => term.includes(marker))) return 'action'
  if (CONCRETE_OBJECT_PATTERN.test(term)) return 'object'
  if (ABSTRACT_CONTEXT_PATTERN.test(sentence)) return 'concept'
  return 'object'
}

function incrementTerm(map, term, chapterNum) {
  const item = map.get(term) || { key: term, label: term, count: 0, chapters: new Set() }
  item.count += 1
  if (chapterNum) item.chapters.add(Number(chapterNum))
  map.set(term, item)
}

export function extractNarrativeTermStats(source = '', options = {}) {
  const minCount = Number(options.minCount || 2)
  const chapterNum = options.chapterNum
  const filters = buildTermFilters(source, options)
  const buckets = {
    objects: new Map(),
    actions: new Map(),
    concepts: new Map()
  }
  for (const sentence of splitSentences(source)) {
    for (const object of concreteNarrativeObjects(sentence, filters)) {
      incrementTerm(buckets.objects, object, chapterNum)
    }
    for (const marker of ACTION_MARKERS) {
      if (COMMON_ACTION_EVIDENCE_STOP_TERMS.has(marker)) continue
      if (sentence.includes(marker)) incrementTerm(buckets.actions, marker, chapterNum)
    }
    for (const term of sentenceTerms(sentence, filters)) {
      const category = categoryForTerm(term, sentence, filters)
      if (!category) continue
      incrementTerm(category === 'concept' ? buckets.concepts : buckets.objects, term, chapterNum)
    }
  }

  const toList = (map, threshold = minCount) => [...map.values()]
    .filter(item => item.count >= threshold)
    .sort((a, b) => b.count - a.count)
    .slice(0, Number(options.limit || 12))
    .map(item => ({
      key: item.key,
      label: item.label,
      count: item.count,
      chapters: [...item.chapters].sort((a, b) => a - b)
    }))

  return {
    objects: toList(buckets.objects),
    actions: toList(buckets.actions, Number(options.actionMinCount || 1)),
    concepts: toList(buckets.concepts)
  }
}

export function filterNarrativeEvidenceLabels(labels = [], options = {}) {
  const source = String(options.source || labels.join('\n') || '')
  const filters = buildTermFilters(source, options)
  const category = options.category || ''
  return unique(labels
    .map(item => typeof item === 'string' ? item : item?.label || item?.key || '')
    .map(item => String(item || '').trim())
    .filter(item => {
      if (!isUsefulTerm(item, filters)) return false
      if (category === 'action' && isCommonActionEvidenceTerm(item)) return false
      return true
    }))
}

function normalizeParagraphForSimilarity(text = '') {
  return String(text || '')
    .replace(/[，。！？；：、“”‘’（）()\[\]【】《》…—\-_\s\d]/g, '')
    .replace(/[\u4e00-\u9fa5]{1,4}(?:先生|女士|小姐|师兄|师姐|老人|男人|女人)/g, '')
    .slice(0, 160)
}

function paragraphShape(text = '') {
  return normalizeParagraphForSimilarity(text)
    .replace(/不是[^。！？；\n]{0,24}(?:而是|是)[^。！？；\n]{0,24}/g, '不是X是Y')
    .replace(/在[^。！？；\n]{0,16}(?:下面|内部|位置|之下|当中)[^。！？；\n]{0,8}(?:展开|出现|浮现)/g, '在X展开')
    .replace(/[他她它][^。！？；\n]{0,10}感(?:到|觉到)[^。！？；\n]{0,20}/g, '角色感觉到X')
    .slice(0, 120)
}

function bigrams(text = '') {
  const chars = [...normalizeParagraphForSimilarity(text)]
  const set = new Set()
  for (let index = 0; index < chars.length - 1; index += 1) {
    set.add(`${chars[index]}${chars[index + 1]}`)
  }
  return set
}

function jaccard(a, b) {
  if (!a.size || !b.size) return 0
  let intersection = 0
  for (const item of a) if (b.has(item)) intersection += 1
  return intersection / (a.size + b.size - intersection)
}

function beatPlanStoryBearingText(text = '') {
  return String(text || '')
    .replace(/^#{1,6}\s*[^\n]+/gm, ' ')
    .replace(/本章|章节|小纲|读者|主角|角色|必须|不能|不要|不再|至少|之一|一个|当前|下一章|上一章/g, ' ')
    .replace(/关系变化|线索推进|地点变化|目标变化|代价兑现|敌我态势变化|不可逆变化/g, ' ')
    .replace(/新地点|具体人物行动|新敌我态势|外部压力|关系摩擦|旧线索阶段性结论|道具失效|规则证伪/g, ' ')
    .replace(/进入|离开|打开|拒绝|交出|抢先|验证|公开表态/g, ' ')
    .replace(/承接|转向要求|原地停留|可见行动|动作|代价|结果|证据|地点|态势|变化/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function detectParagraphRepetition(content = '') {
  const paragraphs = String(content || '')
    .split(/\n{2,}|\r?\n/)
    .map(item => item.trim())
    .filter(item => item.length >= 24)
    .slice(0, 80)
  let maxSimilarity = 0
  const repeatedPairs = []
  const skeletonCounts = new Map()

  for (let index = 0; index < paragraphs.length; index += 1) {
    const skeleton = paragraphShape(paragraphs[index])
    if (skeleton.length >= 18) skeletonCounts.set(skeleton, Number(skeletonCounts.get(skeleton) || 0) + 1)
    if (index === 0) continue
    const similarity = jaccard(bigrams(paragraphs[index - 1]), bigrams(paragraphs[index]))
    maxSimilarity = Math.max(maxSimilarity, similarity)
    if (similarity >= 0.55) repeatedPairs.push([index, index + 1, Number(similarity.toFixed(2))])
  }

  const repeatedSkeletons = [...skeletonCounts.entries()].filter(([, count]) => count >= 3)
  return {
    paragraphCount: paragraphs.length,
    maxSimilarity: Number(maxSimilarity.toFixed(2)),
    repeatedPairs,
    repeatedSkeletonCount: repeatedSkeletons.length,
    hasParagraphRepetition: repeatedPairs.length >= 2 || repeatedSkeletons.length > 0
  }
}

function detectTemplateRepetition(content = '', notXButYCount = 0) {
  const source = String(content || '')
  const templates = [
    { key: 'felt', label: '角色感觉到', count: countMatches(source, /[他她它][^。！？；\n]{0,8}感(?:到|觉到)/) },
    { key: 'under_expand', label: '在某处展开/浮现', count: countMatches(source, /在[^。！？；\n]{0,12}(?:下面|内部|位置|之下|当中)[^。！？；\n]{0,8}(?:展开|出现|浮现)/) },
    { key: 'continue_confirm', label: '继续观察/确认', count: countMatches(source, /继续(?:观察|确认|触摸|感受|看着|理解)/) },
    { key: 'not_x_but_y', label: '不是X是Y', count: notXButYCount }
  ].filter(item => item.count >= 3)
  return {
    templates,
    hasTemplateRepetition: templates.length > 0 || notXButYCount >= 3
  }
}

function hasNonNegatedMarker(source = '', marker = '') {
  const text = String(source || '')
  let index = text.indexOf(marker)
  while (index >= 0) {
    const prefix = text.slice(Math.max(0, index - 6), index)
    if (!/(没有|未曾|未|不|不能|不得|并未|也没|无)$/.test(prefix)) return true
    index = text.indexOf(marker, index + marker.length)
  }
  return false
}

function patternHasNonNegatedMatch(source = '', pattern) {
  const flags = pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`
  const regex = new RegExp(pattern.source, flags)
  for (const match of String(source || '').matchAll(regex)) {
    const prefix = String(source || '').slice(Math.max(0, match.index - 6), match.index)
    if (!/(没有|未曾|未|不|不能|不得|并未|也没|无)$/.test(prefix)) return true
  }
  return false
}

function extractMarkdownSection(source = '', headingPattern) {
  const lines = String(source || '').split(/\r?\n/)
  const buffer = []
  let collecting = false
  for (const line of lines) {
    const headingMatch = line.match(/^\s{0,3}#{1,6}\s*(.+?)\s*$/)
    if (headingMatch) {
      const heading = headingMatch[1].trim()
      if (collecting) break
      if (headingPattern.test(heading)) {
        collecting = true
        continue
      }
    }
    if (collecting) buffer.push(line)
  }
  return buffer.join('\n').trim()
}

function stripNegatedGuidance(text = '') {
  return splitSentences(text)
    .filter(sentence => !/(不能|不要|禁止|不得|避免|不允许|不能只|不得只|不要只|不再|不能写成)/.test(sentence))
    .join('。')
}

function hasAbstractIrreversibleChange(text = '') {
  const source = stripNegatedGuidance(text)
  const hasAbstractMarker = /更理解|更深的真相|感受到|显示(?:出)?更多|形成新的结构|新的结构|更多信息|展开|关系变化|局势变化|认知变化/.test(source)
  if (!hasAbstractMarker) return false
  const hasConcreteChange = /获得|拿到|交出|失去|夺走|烧毁|损坏|扭伤|受伤|死亡|暴露|拦截|追击|封锁|抵达|进入|离开|确认[^。；\n]{0,24}(?:联系|身份|证据|遗物|地点)|首次(?:主动)?(?:现身|出手|拦截)|敌我态势|身体状态|新负担|无法原样退回/.test(source)
  return !hasConcreteChange
}

function hasConcreteExternalEvent(source = '') {
  return EXTERNAL_ACTION_MARKERS.some(marker => hasNonNegatedMarker(source, marker))
}

function hasConcreteAction(source = '') {
  return EXTERNAL_ACTION_MARKERS.some(marker => hasNonNegatedMarker(source, marker))
}

export function inferIrreversibleChange(text = '') {
  const source = String(text || '')
  const hits = IRREVERSIBLE_CHANGE_RULES.filter(rule => patternHasNonNegatedMatch(source, rule.pattern))
  return {
    irreversibleChange: hits.length ? hits.map(item => item.label).join('、') : '未识别到明确不可逆变化',
    irreversibleChangeTypes: hits.map(item => item.type)
  }
}

function issue(type, severity, detail, extra = {}) {
  return { type, severity, detail, ...extra }
}

function normalizeCardList(value = []) {
  if (!Array.isArray(value)) return String(value || '').split(/[、,，;\s]+/)
  return value
    .map(item => {
      if (typeof item === 'string') return item
      return item?.label || item?.key || item?.title || item?.name || ''
    })
    .map(item => String(item || '').trim())
    .filter(Boolean)
}

function deriveFreshnessCardFromOptions(options = {}) {
  if (options.nearTurnDecisionCard) return options.nearTurnDecisionCard
  const recent = Array.isArray(options.recentChapters) ? options.recentChapters : []
  if (!recent.length) return null
  const analysis = analyzeMultiChapterNarrativeProgression(recent)
  return {
    repeatedObjects: analysis.recent5RepeatedObjects || [],
    repeatedActions: analysis.recent5RepeatedActions || [],
    repeatedConcepts: analysis.recent5RepeatedConcepts || [],
    requiredChange: '下一章必须引入新地点、具体人物行动、外部压力、关系摩擦或旧线索阶段性结论之一。',
    forbiddenWriting: '禁止继续围绕最近高频物象、动作或抽象概念观察、触摸、确认、理解。',
    requiredPlotIncrement: '下一章必须完成可被读者复述的真实事件。',
    handoffTarget: '结尾交接到具体动作、关系变化、物件状态或下一章问题。'
  }
}

function countMarkers(source = '', markers = []) {
  return markers.reduce((sum, marker) => sum + countMatches(source, new RegExp(marker, 'g')), 0)
}

const FRESH_TURN_PATTERNS = [
  /新地点|首次出现|外部压力|新敌我态势|敌方|追击|袭击|封锁|主动出手/,
  /阶段性结论|证伪|失效|不再作为|旧线索|名单|地址|坐标|证据|档案|记录|账册|名册/,
  /关系摩擦|关系破裂|公开否认|同盟|重组|背叛|拒绝|不配合/,
  /离开|进入|抵达|前往|转入|走出|推开|打开|烧毁|交出|换取|抢先|夺回/
]

function detectNumberedSequenceLoop(source = '', options = {}) {
  const text = stripNegatedGuidance(stripUnresolvedSection(String(source || '')))
  const numberedHits = [...text.matchAll(NUMBERED_ENTITY_PATTERN)].map(match => match[0])
  NUMBERED_ENTITY_PATTERN.lastIndex = 0
  const currentPattern = extractEventPatternSignature(text)
  const recent = Array.isArray(options.recentChapters) ? options.recentChapters : []
  const recentNumberedCount = recent
    .map(chapter => extractEventPatternSignature(chapter))
    .filter(signature => signature?.key === 'numbered_scene_observe_choose_exit')
    .length
  const hasBreak = /合并|跳切|反转|升级|打破|中断|封锁|敌方|回收组|主动出手|不再|略过|证伪|失效|公开否认|抢走|夺回|切回/.test(text)
  const mechanicalFlow = currentPattern?.key === 'numbered_scene_observe_choose_exit' ||
    (/进入|打开|走进/.test(text) && /看见|看到|记忆|愿望|画面/.test(text) && /选择|决定/.test(text) && /离开|出来|走出|准备进入/.test(text))
  return {
    hasLoop: recentNumberedCount >= 2 && numberedHits.length > 0 && mechanicalFlow && !hasBreak,
    recentNumberedCount,
    numberedHits,
    hasBreak,
    mechanicalFlow
  }
}

function importantVolumeTerms(text = '') {
  const source = String(text || '')
  const phrasePattern = /(?:真实身份|敌我态势|主动暴露|愿望代价|家族真相|逐愿规则|愿望交易所|回收组|封锁名单|阶段结论|主线压力|核心真相|身份真相|敌方压力|关系摩擦|旧线索|证伪|失效|追击|封锁|真相|身份|规则|代价|家族|主线|名单|证据|交易所)/g
  const phrases = (source.match(phrasePattern) || [])
    .map(item => item.replace(/^(查明|推动|关于|当前|这个|那个|个人|主角|第[一二三四五六七八九十0-9]+卷)/, ''))
    .map(item => item.trim())
    .filter(item => item.length >= 2 && item.length <= 8)
  const terms = source
    .split(/[，。！？；、,\s]+/)
    .map(item => item.replace(/^(查明|推动|关于|当前|这个|那个|个人|主角|第[一二三四五六七八九十0-9]+卷)/, '').trim())
    .filter(term => term.length >= 2 && term.length <= 8)
    .filter(term => !STOP_TERMS.has(term))
    .filter(term => !COMMON_ACTION_EVIDENCE_STOP_TERMS.has(term))
    .filter(term => !/^(查明|如何|并让|第一次|当前|目标|主线|之间|冲突|理解升级)$/.test(term))
  return unique([
    ...phrases,
    ...terms,
    ...(source.match(/回收组|真实身份|敌我态势|主动暴露|愿望代价|家族真相|逐愿规则|封锁|追击|交易所/g) || [])
  ]).slice(0, 12)
}

function stripUnresolvedSection(source = '') {
  return String(source || '')
    .replace(/###\s*(?:本章)?暂不解决[\s\S]*$/m, '')
}

function isWeakVolumeGoalHandoffTerm(term = '') {
  const value = String(term || '').trim()
  if (!value) return true
  if (/^(林远|林墨|主角|他|她|愿望|规则|系统|主线|目标|空间|问题)$/.test(value)) return true
  if (/^(如何|并让|当前|最近|下一章|第一次)$/.test(value)) return true
  return false
}

function isDeferredVolumeGoalSentence(sentence = '') {
  return /暂不解决|不解决|未解决|还差|缺口|准备进入|查看下一个|继续进入|继续查看|不安|只是|仍然|理解|确认/.test(String(sentence || ''))
}

function hasVolumeGoalProgressionEvidence(sentence = '') {
  const text = String(sentence || '')
  return FRESH_TURN_PATTERNS.some(pattern => patternHasNonNegatedMatch(text, pattern)) ||
    /证据|名单|地址|坐标|账册|记录|暴露|主动出手|封锁|追击|抢走|夺回|查明|证伪|失效|切回主线|敌方|回收组|身份/.test(text)
}

function detectVolumeGoalHandoffMissing(source = '', options = {}, numberedSequence = null) {
  const card = deriveFreshnessCardFromOptions(options)
  const volumeGoal = [
    card?.currentVolumeGoal,
    options.volumeStage?.coreGoal,
    options.volumeStage?.mainConflict,
    options.currentVolume?.goal,
    options.currentVolume?.mainConflict
  ].filter(Boolean).join('；')
  if (!volumeGoal.trim()) return { missing: false, volumeGoal: '', hitTerms: [], terms: [] }
  const terms = importantVolumeTerms(volumeGoal)
  if (!terms.length) return { missing: false, volumeGoal, hitTerms: [], terms }
  const storyText = stripUnresolvedSection(source)
  const hitTerms = terms.filter(term => storyText.includes(term))
  const strongTerms = terms.filter(term => !isWeakVolumeGoalHandoffTerm(term))
  const strongHitTerms = hitTerms.filter(term => !isWeakVolumeGoalHandoffTerm(term))
  const evidenceSentences = splitSentences(storyText).filter(sentence =>
    strongHitTerms.some(term => sentence.includes(term)) &&
    !isDeferredVolumeGoalSentence(sentence) &&
    hasVolumeGoalProgressionEvidence(sentence)
  )
  const hasLocalNumberedLoop = numberedSequence?.hasLoop || (/号(?:门|房间|空间|档案|画布|凭证)?/.test(storyText) && /继续|下一个|准备进入|去看/.test(storyText))
  const requiredStrongHits = Math.min(2, Math.max(1, strongTerms.length))
  const missing = hasLocalNumberedLoop && (strongHitTerms.length < requiredStrongHits || evidenceSentences.length < 1)
  return { missing, volumeGoal, hitTerms, strongHitTerms, evidenceSentences, terms }
}

function addUsefulHandoffTerm(target, term = '') {
  const value = String(term || '')
    .replace(/^(?:抵达|寻找|潜入|前往|确认|获得|查明|追查|使用|利用|打探|进入|离开|转入|暴露|推动)/, '')
    .replace(/(?:位置|地点|入口|来源|方向|风险|压力|缺口|目标)$/g, '')
    .trim()
  if (value.length < 2 || value.length > 16) return
  if (STOP_TERMS.has(value) || COMMON_ACTION_EVIDENCE_STOP_TERMS.has(value)) return
  if (/^(继续|下一个|编号结构|局部编号|当前卷)$/.test(value)) return
  target.add(value)
}

function extractHandoffTerms(text = '') {
  const source = String(text || '')
  const terms = new Set()
  const directPatterns = [
    /[\u4e00-\u9fa5]{1,8}城/g,
    /[\u4e00-\u9fa5]{1,8}矿山/g,
    /[\u4e00-\u9fa5]{1,5}号巷道/g,
    /[\u4e00-\u9fa5]{0,6}(?:星账|账册|账页|线索|证据|地图|坐标|地址|入口|父亲|母亲|记忆|追兵|巡天司|商盟|土匪|探子|暴露|潜入|代价)[\u4e00-\u9fa5]{0,4}/g
  ]
  for (const pattern of directPatterns) {
    for (const match of source.matchAll(pattern)) addUsefulHandoffTerm(terms, match[0])
  }
  for (const part of source.split(/[，。！？；、,;\s]+/)) {
    const value = part.trim()
    if (!/(城|矿|巷道|入口|星账|账|线索|证据|地图|坐标|地址|追兵|巡天司|商盟|土匪|探子|父亲|母亲|记忆|代价|暴露|潜入|封锁|追击|追踪)/.test(value)) continue
    addUsefulHandoffTerm(terms, value)
  }
  return [...terms]
}

function collectVolumeHandoffContextTerms(options = {}, volumeGoal = '') {
  const card = deriveFreshnessCardFromOptions(options)
  const snapshot = options.blockStageSnapshot || options.stageSnapshot || options.storyBlockStageSnapshot || {}
  const snapshotText = [
    snapshot.stagePurpose,
    snapshot.stageAction,
    snapshot.stageChoice,
    snapshot.stageCostOrConsequence,
    snapshot.exitTarget,
    snapshot.mainPressure,
    Array.isArray(snapshot.unresolvedQuestions) ? snapshot.unresolvedQuestions.join('；') : snapshot.unresolvedQuestions
  ].filter(Boolean).join('；')
  const volumeText = [
    volumeGoal,
    card?.currentVolumeGoal,
    card?.requiredChange,
    options.volumeStage?.coreGoal,
    options.volumeStage?.mainConflict,
    options.volumeStage?.handoffPoint,
    options.currentVolume?.goal,
    options.currentVolume?.mainConflict,
    options.currentVolume?.handoffPoint
  ].filter(Boolean).join('；')
  return unique([
    ...extractHandoffTerms(snapshotText),
    ...extractHandoffTerms(volumeText),
    ...importantVolumeTerms(volumeText)
  ]).filter(term => !isWeakVolumeGoalHandoffTerm(term))
}

function hasConcreteCostOrLoss(source = '') {
  return /代价|损失|失去|付出|牺牲|永久|受伤|扭伤|疼|伤口|暴露|风险|记忆|扣除|反噬/.test(String(source || ''))
}

function hasConcreteHandoff(source = '') {
  const text = String(source || '')
  return Boolean(text.trim()) && (
    hasConcreteAction(text) ||
    /必须|潜入|追查|打探|获得|确认|暴露|包围|掌握|前往|进入|抵达|下一章|后续|交接|线索/.test(text)
  )
}

function firstSentenceWithTerms(source = '', terms = []) {
  const sentences = splitSentences(source)
  return sentences.find(sentence => terms.some(term => sentence.includes(term))) || sentences[0] || ''
}

function deriveVolumeGoalHandoffDiagnostic(source = '', options = {}, volumeGoalHandoff = {}, irreversible = null) {
  const storyText = stripUnresolvedSection(source)
  const chapterEvent = extractMarkdownSection(storyText, /本章(?:真实|具体)?事件/) || ''
  const externalPressure = extractMarkdownSection(storyText, /外部(?:压力|阻力)/) || ''
  const costOrLoss = extractMarkdownSection(storyText, /(?:代价|损失)/) || ''
  const irreversibleSection = extractMarkdownSection(storyText, /(?:本章)?不可逆(?:变化|结果)/) || ''
  const endingHandoff = extractMarkdownSection(storyText, /结尾(?:交接|交接点|钩子)/) || ''
  const irreversibleResult = irreversible || inferIrreversibleChange(storyText)
  const derivableTypes = (irreversibleResult.irreversibleChangeTypes || [])
    .filter(type => VOLUME_HANDOFF_DERIVABLE_CHANGE_TYPES.has(type))
  const contextTerms = collectVolumeHandoffContextTerms(options, volumeGoalHandoff.volumeGoal || '')
  const matchedTerms = contextTerms.filter(term => storyText.includes(term)).slice(0, 12)
  const matchedInEnding = matchedTerms.filter(term => endingHandoff.includes(term))
  const matchedInIrreversible = matchedTerms.filter(term => irreversibleSection.includes(term))
  const matchedInEvent = matchedTerms.filter(term => chapterEvent.includes(term))
  const evidence = {
    hasConcreteEvent: hasConcreteExternalEvent(chapterEvent || storyText),
    hasConcreteAction: hasConcreteAction(chapterEvent || storyText),
    hasExternalPressure: hasConcreteExternalEvent(externalPressure) || /追兵|敌|盘查|拦路|搜身|威胁|封锁|追踪|暴露|包围|土匪|商盟|巡天司/.test(externalPressure || storyText),
    hasCostOrLoss: hasConcreteCostOrLoss(costOrLoss || storyText),
    hasIrreversibleChange: derivableTypes.length >= 2,
    hasEndingHandoff: hasConcreteHandoff(endingHandoff),
    derivableChangeTypeCount: derivableTypes.length
  }
  const hasCompleteConcreteHandoff = evidence.hasConcreteEvent &&
    evidence.hasConcreteAction &&
    evidence.hasExternalPressure &&
    evidence.hasCostOrLoss &&
    evidence.hasIrreversibleChange &&
    evidence.hasEndingHandoff
  const sourceField = matchedInEnding.length
    ? 'endingHandoff'
    : matchedInIrreversible.length
      ? 'irreversibleChange'
      : matchedInEvent.length
        ? 'chapterEvent'
        : (matchedTerms.length ? 'stageSnapshot' : (hasCompleteConcreteHandoff ? 'endingHandoff' : ''))
  const sourceText = sourceField === 'irreversibleChange'
    ? irreversibleSection
    : sourceField === 'chapterEvent'
      ? chapterEvent
      : endingHandoff || irreversibleSection || chapterEvent
  const derived = hasCompleteConcreteHandoff && (matchedTerms.length > 0 || hasConcreteHandoff(sourceText))
  return {
    status: derived ? 'derived_pass' : 'missing',
    derived,
    source: sourceField,
    matchedTerms,
    derivedHandoffText: derived ? firstSentenceWithTerms(sourceText, matchedTerms) : '',
    derivableChangeTypes: derivableTypes,
    evidence,
    contextTerms: contextTerms.slice(0, 16)
  }
}

export function detectBeatPlanTemplateFallbackRisk(text = '') {
  const source = String(text || '')
  const templatePhrases = [
    '主角遭遇可见外部压力',
    '旧线索、敌方压力、关系摩擦或代价选择',
    '落到关系变化、线索推进、地点变化、目标变化、代价兑现或敌我态势变化之一',
    '外部压力打断原地研究',
    '人物摩擦暴露不同动机',
    '主角做出选择并付出代价',
    '只释放一个新事实或新疑问',
    '停在新证据、危险、误解或关系变化上',
    '后续章节要继续保留的悬念'
  ]
  const hits = templatePhrases.filter(phrase => source.includes(phrase))
  const concreteTurnHits = FRESH_TURN_PATTERNS.filter(pattern => patternHasNonNegatedMatch(source, pattern)).length
  const hasTemplateFallbackRisk = hits.length >= 5 || (hits.length >= 3 && concreteTurnHits < 3)
  return {
    hasTemplateFallbackRisk,
    hits,
    concreteTurnHits
  }
}

export function validateBeatPlanFreshnessGate(text = '', options = {}) {
  const source = String(text || '').trim()
  const sourceWithoutGuidance = source.replace(/^#{1,6}\s*[^\n]+/gm, '')
  const card = deriveFreshnessCardFromOptions(options)
  const issues = []
  const repeatedObjects = normalizeCardList(card?.repeatedObjects).filter(isUsefulTerm).slice(0, 8)
  const repeatedActions = normalizeCardList(card?.repeatedActions).slice(0, 8)
  const repeatedConcepts = normalizeCardList(card?.repeatedConcepts).filter(isUsefulTerm).slice(0, 8)
  const staleObjectHits = repeatedObjects.filter(term => sourceWithoutGuidance.includes(term))
  const staleConceptHits = repeatedConcepts.filter(term => sourceWithoutGuidance.includes(term))
  const loopActionCount = countMarkers(sourceWithoutGuidance, LOOP_ACTION_MARKERS)
  const externalActionCount = countMarkers(sourceWithoutGuidance, EXTERNAL_ACTION_MARKERS)
  const hasFreshTurn = FRESH_TURN_PATTERNS.some(pattern => patternHasNonNegatedMatch(sourceWithoutGuidance, pattern))
  const numberedSequence = detectNumberedSequenceLoop(sourceWithoutGuidance, options)
  const irreversible = inferIrreversibleChange(sourceWithoutGuidance)
  const volumeGoalHandoff = detectVolumeGoalHandoffMissing(sourceWithoutGuidance, options, numberedSequence)
  const volumeGoalHandoffDiagnostic = deriveVolumeGoalHandoffDiagnostic(source, options, volumeGoalHandoff, irreversible)
  Object.assign(volumeGoalHandoff, volumeGoalHandoffDiagnostic)
  const cardRequiresNumberedBreak = card?.numberedSequenceStatus === 'must_break'
  const actionableText = stripNegatedGuidance(sourceWithoutGuidance)
  const numberedBreakOptionsHit = /合并编号序列|跳过编号流程|规则失效|敌方打断|切到现实地点|关系背叛|目标改变|阶段性结论|关闭编号|终止编号|打断编号|切回现实|封锁.*编号|敌方.*中断|敌方.*封锁/.test(actionableText)
  const continuesNumberedObjectFlow = /(?:进入|打开|走进|推门|触发).{0,18}(?:[0-9一二三四五六七八九十百千万两零〇]+)号(?:门|房间|空间|档案|画布|凭证|卡|柜|箱)?/.test(actionableText) &&
    /看见|看到|旁观|记忆|愿望|画面|记录|读出|解释|展示|感知/.test(actionableText) &&
    /选择|决定|拒绝|触碰|交出|换取|承认/.test(actionableText) &&
    /离开|出来|走出|回到|准备进入|去看/.test(actionableText)

  if (staleObjectHits.length && loopActionCount >= 2 && externalActionCount <= 1 && !hasFreshTurn) {
    issues.push(issue(
      'freshness_repeated_object_loop',
      'major',
      `小纲仍围绕最近高频物象继续观察/确认：${staleObjectHits.slice(0, 4).join('、')}`,
      { repeatedObjects: staleObjectHits.slice(0, 6) }
    ))
  }

  const repeatedLoopActions = repeatedActions.filter(action => LOOP_ACTION_MARKERS.includes(action) && sourceWithoutGuidance.includes(action))
  if ((loopActionCount >= 3 || repeatedLoopActions.length >= 2) && externalActionCount <= 1) {
    issues.push(issue(
      'freshness_loop_action_dominant',
      'major',
      `小纲主体动作仍偏观察/触摸/确认/理解，外部行动不足。`,
      { repeatedActions: repeatedLoopActions, loopActionCount, externalActionCount }
    ))
  }

  if ((staleConceptHits.length >= 2 || /更理解|更清楚|感受到|继续展开|答案更/.test(sourceWithoutGuidance)) && externalActionCount <= 1) {
    issues.push(issue(
      'freshness_concept_spinning_outline',
      'major',
      `小纲仍以抽象概念替换推进，缺少真实事件增量。`,
      { repeatedConcepts: staleConceptHits.slice(0, 6) }
    ))
  }

  if (card && !hasFreshTurn) {
    issues.push(issue(
      'freshness_required_turn_missing',
      'major',
      `小纲没有落实近景转向卡要求的新地点、外部压力、关系摩擦、阶段性结论或敌我态势变化。`,
      { requiredChange: card.requiredChange || '' }
    ))
  }

  if (numberedSequence.hasLoop) {
    issues.push(issue(
      'numbered_sequence_loop',
      'major',
      '小纲继续采用“一章一个编号对象：进入/观看/选择/离开”的机械结构；第三次编号结构必须合并、跳切、反转、升级或被外部压力打断。',
      {
        recentNumberedCount: numberedSequence.recentNumberedCount,
        numberedHits: numberedSequence.numberedHits
      }
    ))
  }

  if (cardRequiresNumberedBreak && (!numberedBreakOptionsHit || continuesNumberedObjectFlow)) {
    issues.push(issue(
      'numbered_sequence_loop',
      'major',
      '近景转向卡要求终止或反转编号序列，但小纲仍未选择合并、跳切、规则失效、敌方打断、切到现实地点、关系背叛、目标改变或阶段性结论。',
      {
        recentNumberedCount: card.numberedSequenceCount || numberedSequence.recentNumberedCount,
        requiredBreaks: card.requiredNumberedSequenceBreaks || []
      }
    ))
  }

  if (volumeGoalHandoff.missing) {
    if (volumeGoalHandoff.derived) {
      issues.push(issue(
        'volume_goal_handoff_missing_downgraded',
        'warning',
        '小纲未显式写出卷目标接力字段，但结尾交接、不可逆变化和故事块阶段已形成可派生接力。',
        {
          volumeGoal: volumeGoalHandoff.volumeGoal,
          hitTerms: volumeGoalHandoff.hitTerms,
          expectedTerms: volumeGoalHandoff.terms,
          volumeGoalHandoffDiagnostic
        }
      ))
      volumeGoalHandoff.warning = 'volume_goal_handoff_missing_downgraded'
      volumeGoalHandoff.missing = false
    } else {
      issues.push(issue(
        'volume_goal_handoff_missing',
        'major',
        '小纲继续局部编号结构，但没有推进当前卷目标缺口或切回主线压力。',
        {
          volumeGoal: volumeGoalHandoff.volumeGoal,
          hitTerms: volumeGoalHandoff.hitTerms,
          expectedTerms: volumeGoalHandoff.terms,
          volumeGoalHandoffDiagnostic
        }
      ))
    }
  }

  const templateRisk = detectBeatPlanTemplateFallbackRisk(source)
  if (templateRisk.hasTemplateFallbackRisk) {
    issues.push(issue(
      'freshness_template_fallback_like',
      'major',
      '小纲疑似本地安全重建模板化输出，只满足字段合规但缺少本章独有事件。',
      { templateHits: templateRisk.hits }
    ))
  }

  const recentPlans = (Array.isArray(options.recentChapters) ? options.recentChapters : [])
    .map(item => item.beatPlan || item.outline || '')
    .filter(Boolean)
  let maxRecentSimilarity = 0
  const storySource = beatPlanStoryBearingText(source)
  for (const plan of recentPlans) {
    const storyPlan = beatPlanStoryBearingText(plan)
    if (storySource.length < 40 || storyPlan.length < 40) continue
    const similarity = jaccard(bigrams(storySource), bigrams(storyPlan))
    maxRecentSimilarity = Math.max(maxRecentSimilarity, similarity)
  }
  const shouldFailForRecentSimilarity = maxRecentSimilarity >= 0.62 &&
    (templateRisk.hasTemplateFallbackRisk || !hasFreshTurn || staleObjectHits.length >= 2 || loopActionCount >= 3)
  if (shouldFailForRecentSimilarity) {
    issues.push(issue(
      'freshness_recent_structure_similarity',
      'major',
      `小纲与最近章节结构相似度过高：${maxRecentSimilarity.toFixed(2)}。`,
      { maxRecentSimilarity: Number(maxRecentSimilarity.toFixed(2)) }
    ))
  }

  const passed = !issues.some(item => ['critical', 'major', 'severe'].includes(normalizeSeverity(item.severity)))
  return {
    gate: passed ? 'pass' : 'fail',
    passed,
    issues,
    repeatedObjects,
    repeatedActions,
    repeatedConcepts,
    loopActionCount,
    externalActionCount,
    hasFreshTurn,
    templateRisk,
    numberedSequence,
    volumeGoalHandoff
  }
}

export function validateBeatPlanProgressionGate(text = '', options = {}) {
  const source = String(text || '').trim()
  const issues = []
  const requiredFields = [
    { id: 'chapterEvent', label: '本章事件', pattern: /本章事件|本章真实事件|本章具体事件/ },
    { id: 'characterGoal', label: '人物目标', pattern: /人物目标|人物当前目标|本章目标/ },
    { id: 'coreConflict', label: '核心冲突', pattern: /核心冲突|本章核心冲突/ },
    { id: 'externalPressure', label: '外部压力', pattern: /外部压力|外部阻力/ },
    { id: 'costOrLoss', label: '代价或损失', pattern: /代价或损失|代价|损失/ },
    { id: 'irreversibleChange', label: '不可逆变化', pattern: /不可逆变化|不可逆结果|本章不可逆变化/ },
    { id: 'endingHandoff', label: '结尾交接', pattern: /结尾交接|结尾交接点|结尾钩子/ }
  ]
  const missingFields = requiredFields.filter(field => !field.pattern.test(source)).map(field => field.id)
  if (missingFields.length) issues.push(issue('beat_plan_required_fields_missing', 'major', `缺少字段：${missingFields.join(',')}`, { missingFields }))

  const irreversible = inferIrreversibleChange(source)
  const irreversibleSection = extractMarkdownSection(source, /(?:本章)?不可逆(?:变化|结果)/) || source
  const abstractChange = hasAbstractIrreversibleChange(irreversibleSection)
  if (!irreversible.irreversibleChangeTypes.length) issues.push(issue('no_irreversible_change', 'major', '小纲未识别到具体不可逆变化。'))
  if (abstractChange) issues.push(issue('abstract_irreversible_change', 'major', '不可逆变化停留在理解、感受、显示更多信息或抽象结构变化。'))

  const loopExitSection = extractMarkdownSection(source, /离开上一循环/) || source
  const loopExitSource = stripNegatedGuidance(loopExitSection)
  const loopExit = /离开|进入|转入|新地点|敌方|追击|主动出手|公开否认|证伪|不再作为|烧毁|失效|关系破裂|关系重组|打破|关闭|中断|跳切|合并|反转|封锁|切回|结束|停止|改道|现实|走廊|回收组|外部压力|打断/.test(loopExitSource) &&
    !/继续(?:观察|触摸|确认|感受|理解)|又(?:观察|确认|理解)|仍然(?:观察|确认|理解)|更理解|更清楚/.test(loopExitSource)
  if (!loopExit) issues.push(issue('loop_exit_missing', 'major', '小纲没有明确离开上一轮观察/确认/物象变化循环。'))

  const freshness = validateBeatPlanFreshnessGate(source, options)
  for (const freshnessIssue of freshness.issues) issues.push(freshnessIssue)

  const passed = !issues.some(item => ['critical', 'major', 'severe'].includes(normalizeSeverity(item.severity)))
  return {
    gate: passed ? 'pass' : 'fail',
    passed,
    issues,
    irreversibleChange: irreversible.irreversibleChange,
    irreversibleChangeTypes: irreversible.irreversibleChangeTypes,
    loopExit,
    freshnessGate: freshness.gate,
    freshness
  }
}

export function analyzeNarrativeReadability(input = {}) {
  const content = String(input.content || '')
  const source = [input.summary, input.beatPlan, content].filter(Boolean).join('\n')
  const notXButYCount = countMatches(content, /不是[^。！？；\n]{0,30}(?:而是|是)[^。！？；\n]{0,30}/)
  const paragraphRepetition = detectParagraphRepetition(content)
  const templateRepetition = detectTemplateRepetition(content, notXButYCount)
  const termStats = extractNarrativeTermStats(source, { minCount: 2, limit: 10 })
  const abstractConceptCount = termStats.concepts.reduce((sum, item) => sum + item.count, 0)
  const observationActionCount = termStats.actions
    .filter(item => LOOP_ACTION_MARKERS.includes(item.label))
    .reduce((sum, item) => sum + item.count, 0)
  const concreteActionCount = termStats.actions
    .filter(item => EXTERNAL_ACTION_MARKERS.includes(item.label))
    .reduce((sum, item) => sum + item.count, 0)
  const hasExternalEvent = hasConcreteExternalEvent(source)
  const concreteAction = hasConcreteAction(source)
  const irreversible = inferIrreversibleChange(source)
  const conceptSpinScore = abstractConceptCount + notXButYCount + Math.max(0, observationActionCount - concreteActionCount)
  const conceptSpinning = conceptSpinScore >= 6 && concreteActionCount <= 2
  const issues = []

  if (!hasExternalEvent) issues.push(issue('no_external_event', 'major', '本章缺少真实外部事件。'))
  if (!concreteAction) issues.push(issue('no_concrete_action', 'major', '本章缺少具体人物行动。'))
  if (!irreversible.irreversibleChangeTypes.length) issues.push(issue('no_irreversible_change', 'major', '本章没有具体不可逆变化。'))
  if (paragraphRepetition.hasParagraphRepetition) {
    issues.push(issue('paragraph_level_repetition', 'critical', '检测到连续段落或结构近似复制。', { paragraphRepetition }))
  }
  if (templateRepetition.hasTemplateRepetition) {
    issues.push(issue('template_level_repetition', 'major', '检测到高频句式/模板重复。', { templateRepetition }))
  }
  if (notXButYCount >= 3) issues.push(issue('not_x_but_y_chain', 'major', `不是X是Y句式出现 ${notXButYCount} 次。`, { count: notXButYCount }))
  if (conceptSpinning) issues.push(issue('concept_spinning', 'critical', '抽象概念互相替换，但缺少动作、事件和剧情增量。', { conceptSpinScore }))
  if (!irreversible.irreversibleChangeTypes.length && (conceptSpinning || !hasExternalEvent)) {
    issues.push(issue('no_plot_increment', 'major', '有效剧情信息可一句话概括，正文缺少新增局面。'))
  }

  const canReaderRetell = hasExternalEvent && concreteAction && irreversible.irreversibleChangeTypes.length > 0 && !conceptSpinning
  if (!canReaderRetell && (conceptSpinning || paragraphRepetition.hasParagraphRepetition || templateRepetition.hasTemplateRepetition)) {
    issues.push(issue('unreadable_chapter', 'critical', '读者难以说清本章真实发生的外部事件。'))
  }

  const hardIssues = issues.filter(item => ['critical', 'severe'].includes(normalizeSeverity(item.severity)))
  const majorIssues = issues.filter(item => ['major', 'critical', 'severe'].includes(normalizeSeverity(item.severity)))
  const gate = hardIssues.length || majorIssues.length >= 3 ? 'fail' : majorIssues.length ? 'warn' : 'pass'

  return {
    gate,
    narrativeReadabilityGate: gate,
    severity: hardIssues.length ? 'critical' : majorIssues.length ? 'major' : 'minor',
    issues,
    irreversibleChange: irreversible.irreversibleChange,
    irreversibleChangeTypes: irreversible.irreversibleChangeTypes,
    hasExternalEvent,
    hasConcreteAction: concreteAction,
    canReaderRetell,
    notXButYCount,
    paragraphRepetition,
    templateRepetition,
    conceptSpinScore,
    repeatedObjects: termStats.objects.map(item => item.label),
    repeatedActions: termStats.actions.map(item => item.label),
    repeatedConcepts: termStats.concepts.map(item => item.label),
    repeatedTermStats: termStats
  }
}

function narrativeLevel(analysis = {}) {
  if (analysis.gate === 'fail') return 'severe'
  if (analysis.gate === 'warn') return 'high'
  return 'low'
}

export function mapAuditIssuesToQualitySignals(issues = []) {
  const aiCounts = {}
  const humanCounts = {}
  const narrativeCounts = {}
  const issueCounts = {}
  for (const issueItem of Array.isArray(issues) ? issues : []) {
    const mapped = mapIssueTypeToQualitySignals(issueItem?.type)
    const severity = normalizeSeverity(issueItem?.severity)
    const weight = SEVERITY_WEIGHT[severity] || 1
    for (const issueType of mapped.issueTypes) issueCounts[issueType] = Number(issueCounts[issueType] || 0) + 1
    addCounts(aiCounts, mapped.aiTraceDimensions, weight)
    addCounts(humanCounts, mapped.humanTextureDimensions, weight)
    addCounts(narrativeCounts, mapped.narrativeReadabilityDimensions, weight)
  }
  return {
    aiTraceDimensions: unique(Object.keys(aiCounts)),
    humanTextureDimensions: unique(Object.keys(humanCounts)),
    narrativeReadabilityDimensions: unique(Object.keys(narrativeCounts)),
    aiTraceDimensionCounts: aiCounts,
    humanTextureDimensionCounts: humanCounts,
    narrativeReadabilityDimensionCounts: narrativeCounts,
    issueCounts
  }
}

export function scoreChapterWritingQuality(input = {}) {
  const narrativeReadability = input.narrativeReadability || input.narrativeProgression || null
  const issues = [
    ...(Array.isArray(input.issues) ? input.issues : []),
    ...(Array.isArray(narrativeReadability?.issues) ? narrativeReadability.issues : [])
  ]
  const mapped = mapAuditIssuesToQualitySignals(issues)
  const aiScore = Object.values(mapped.aiTraceDimensionCounts).reduce((sum, value) => sum + value, 0)
  const humanScore = Object.values(mapped.humanTextureDimensionCounts).reduce((sum, value) => sum + value, 0)
  const hasSevereIssue = issues.some(issueItem => {
    const severity = normalizeSeverity(issueItem?.severity)
    const text = [issueItem?.description, issueItem?.issue, issueItem?.suggestion, issueItem?.detail].filter(Boolean).join(' ')
    return severity === 'critical' || severity === 'severe' || /基本不可读|严重影响|整章|unreadable|concept loop/i.test(text)
  }) || narrativeReadability?.gate === 'fail'
  const computedAiLevel = levelFromScore(aiScore, hasSevereIssue)
  const computedHumanLevel = levelFromHumanTextureScore(humanScore, hasSevereIssue)
  const narrativeMinLevel = narrativeLevel(narrativeReadability || {})
  const aiTraceLevel = maxLevel(input.aiTraceLevel, computedAiLevel, narrativeMinLevel)
  const humanTextureLevel = maxLevel(input.humanTextureLevel, computedHumanLevel, narrativeMinLevel)
  const topQualityRisks = [
    ...topCounts(mapped.aiTraceDimensionCounts),
    ...topCounts(mapped.humanTextureDimensionCounts),
    ...topCounts(mapped.narrativeReadabilityDimensionCounts)
  ].slice(0, 6)
  const qualityAdvice = topQualityRisks.map(item => `${item.label}：优先检查该维度是否高频替代真实呈现。`)
  const affectsContinuation = narrativeReadability?.gate === 'fail' || (aiTraceLevel === 'severe' && hasSevereIssue)

  return {
    aiTraceLevel,
    aiTraceLevelLabel: getQualityLevelLabel(aiTraceLevel),
    humanTextureLevel,
    humanTextureLevelLabel: getQualityLevelLabel(humanTextureLevel),
    narrativeReadabilityGate: narrativeReadability?.gate || 'pass',
    aiTraceDimensions: mapped.aiTraceDimensions,
    humanTextureDimensions: mapped.humanTextureDimensions,
    narrativeReadabilityDimensions: mapped.narrativeReadabilityDimensions,
    aiTraceDimensionCounts: mapped.aiTraceDimensionCounts,
    humanTextureDimensionCounts: mapped.humanTextureDimensionCounts,
    narrativeReadabilityDimensionCounts: mapped.narrativeReadabilityDimensionCounts,
    issueCounts: mapped.issueCounts,
    topQualityRisks,
    qualityAdvice,
    suggestManualPolish: ['high', 'severe'].includes(aiTraceLevel) || ['high', 'severe'].includes(humanTextureLevel),
    affectsContinuation,
    blocksFinalizationCandidate: affectsContinuation && (hasSevereIssue || narrativeReadability?.gate === 'fail')
  }
}

export function mapRhythmAnalysisToQualitySignals(analysis = {}) {
  const signals = getRhythmQualitySignals(analysis)
  return {
    source: 'prose_rhythm_guard',
    ...signals
  }
}

export function isQualityIssue(issue = {}) {
  return mapIssueTypeToQualitySignals(issue.type).issueTypes.length > 0 ||
    /AI|ai|模板|套路|反差句|不是.*(?:而是|是)|段首|短句|功能化|信息倾倒|情绪贴标签|感官打勾|无效数字|工具人|结尾模板|概念空转|推进不足|不可读|重复|循环/.test(
      [issue.type, issue.issue, issue.description, issue.suggestion, issue.replacement, issue.location, issue.detail, issue.title].filter(Boolean).join(' ')
    )
}

function chapterSource(chapter = {}) {
  return [chapter.title, chapter.summary, chapter.opening, chapter.ending, chapter.content, chapter.beatPlan].filter(Boolean).join('\n')
}

function normalizeChapterSourceInput(input = {}) {
  if (typeof input === 'string') return input
  return chapterSource(input)
}

export function extractEventPatternSignature(input = {}) {
  const source = normalizeChapterSourceInput(input)
  const text = String(source || '')
  const hasNumberedEntity = NUMBERED_ENTITY_PATTERN.test(text)
  NUMBERED_ENTITY_PATTERN.lastIndex = 0
  const hasEnter = /进入|走进|推门|打开|来到|触发/.test(text)
  const hasObserve = /看见|看到|旁观|记忆|愿望|画面|记录|读出|解释|展示/.test(text)
  const hasChoice = /选择|决定|拒绝|触碰|交出|换取|承认/.test(text)
  const hasExit = /离开|出来|走出|回到|准备进入|去看/.test(text)
  const numberedFlowScore = [hasEnter, hasObserve, hasChoice, hasExit].filter(Boolean).length
  if (hasNumberedEntity && numberedFlowScore >= 3) {
    return {
      key: 'numbered_scene_observe_choose_exit',
      label: '编号场景：进入/观看/选择/离开',
      score: numberedFlowScore
    }
  }
  if (/凭证|卡|档案|账册|名册|名单/.test(text) && /读出|现字|显示|确认|证明/.test(text)) {
    return {
      key: 'document_clue_read_confirm',
      label: '凭证/档案：读取/现字/确认',
      score: 3
    }
  }
  if (/试炼|挑战|房间|副本|空间/.test(text) && /进入|触发/.test(text) && /选择|通过|失败|离开/.test(text)) {
    return {
      key: 'trial_room_enter_resolve_exit',
      label: '试炼空间：进入/解决/离开',
      score: 3
    }
  }
  return null
}

function detectEventPatternLoops(chapters = []) {
  const byPattern = new Map()
  for (const chapter of chapters) {
    const signature = extractEventPatternSignature(chapter)
    if (!signature?.key) continue
    const item = byPattern.get(signature.key) || {
      key: signature.key,
      label: signature.label,
      count: 0,
      chapters: []
    }
    item.count += 1
    if (chapter.chapterNum) item.chapters.push(Number(chapter.chapterNum))
    byPattern.set(signature.key, item)
  }
  return [...byPattern.values()]
    .filter(item => item.count >= EVENT_PATTERN_LOOP_THRESHOLD)
    .sort((a, b) => b.count - a.count)
}

function repeatedTermsAcrossChapters(chapters = [], category, threshold = 3, options = {}) {
  const byTerm = new Map()
  for (const chapter of chapters) {
    const stats = extractNarrativeTermStats(chapterSource(chapter), {
      minCount: 1,
      chapterNum: chapter.chapterNum,
      limit: 80,
      characterNames: options.characterNames || options.coreCharacterNames || []
    })
    for (const item of stats[category] || []) {
      const existing = byTerm.get(item.key) || { key: item.key, label: item.label, count: 0, chapters: new Set() }
      existing.count += item.count
      for (const num of item.chapters || []) existing.chapters.add(num)
      byTerm.set(item.key, existing)
    }
  }
  return [...byTerm.values()]
    .map(item => ({
      key: item.key,
      label: item.label,
      count: item.count,
      chapters: [...item.chapters].sort((a, b) => a - b)
    }))
    .filter(item => item.chapters.length >= threshold)
    .sort((a, b) => b.chapters.length - a.chapters.length || b.count - a.count)
    .slice(0, 12)
}

export function analyzeMultiChapterNarrativeProgression(chapters = [], options = {}) {
  const recent = (Array.isArray(chapters) ? chapters : []).slice(-5)
  const chapterAnalyses = recent.map(chapter => ({
    chapterNum: chapter.chapterNum,
    ...analyzeNarrativeReadability({
      content: chapter.content || [chapter.opening, chapter.ending].filter(Boolean).join('\n\n'),
      summary: chapter.summary || '',
      beatPlan: chapter.beatPlan || ''
    })
  }))
  const recent5RepeatedObjects = repeatedTermsAcrossChapters(recent, 'objects', 3, options)
  const recent5RepeatedActions = repeatedTermsAcrossChapters(recent, 'actions', 3, options)
  const recent5RepeatedConcepts = repeatedTermsAcrossChapters(recent, 'concepts', 3, options)
  const eventPatternLoops = detectEventPatternLoops(recent)
  const sameSceneOrObjectLoop = recent5RepeatedObjects.some(item => item.chapters.length >= 4)
  const sameEventPatternLoop = eventPatternLoops.some(item => item.count >= EVENT_PATTERN_LOOP_THRESHOLD)
  const consecutiveNoExternalEvent = chapterAnalyses.reduce((max, item, index) => {
    if (item.hasExternalEvent) return max
    let streak = 0
    for (let cursor = index; cursor >= 0; cursor -= 1) {
      if (chapterAnalyses[cursor].hasExternalEvent) break
      streak += 1
    }
    return Math.max(max, streak)
  }, 0)
  const noIrreversibleCount = chapterAnalyses.filter(item => !item.irreversibleChangeTypes?.length).length
  const onlyLoopActions = recent5RepeatedActions.length > 0 &&
    recent5RepeatedActions.every(item => LOOP_ACTION_MARKERS.includes(item.label))
  const mainGoalDrift = recent5RepeatedConcepts.length >= 2 && onlyLoopActions
  const issues = []
  const latestAnalysis = chapterAnalyses[chapterAnalyses.length - 1] || {}
  const latestChangeTypes = latestAnalysis.irreversibleChangeTypes || []
  const latestHasNarrativeTurn = latestChangeTypes.some(type =>
    ['relationship_change', 'location_change', 'enemy_state_change', 'clue_progress'].includes(type)
  )
  const latestCannotRetell = latestAnalysis.canReaderRetell === false
  const structureHardFail = sameEventPatternLoop && !latestHasNarrativeTurn && latestCannotRetell

  if (sameSceneOrObjectLoop) {
    for (const item of recent5RepeatedObjects.filter(entry => entry.chapters.length >= 4)) {
      issues.push({
        severity: 'warning',
        type: 'same_object_loop',
        chapters: item.chapters,
        title: `同一高频物象循环：${item.label}`,
        detail: `最近 5 章反复围绕“${item.label}”或同一状态打转。`,
        suggestedAction: '下一章建议检查该物象的状态是否变化；若事件结构、敌我态势和关系推进均有增量，可继续写作。'
      })
    }
  }
  if (sameEventPatternLoop) {
    for (const item of eventPatternLoops) {
      issues.push({
        severity: structureHardFail ? 'major' : 'warning',
        type: 'same_event_pattern_loop',
        hardFail: structureHardFail,
        chapters: item.chapters,
        title: `同一事件结构循环：${item.label}`,
        detail: structureHardFail
          ? `最近 ${item.count} 章反复使用“${item.label}”结构，且当前章缺少关系/地点/敌我态势/阶段性答案，读者难以复述清晰剧情增量。`
          : `最近 ${item.count} 章反复使用“${item.label}”结构；若当前章已有明确转向，可作为 warning 观察。`,
        suggestedAction: '下一章优先改变场景关系或敌我态势，并用合并、跳切、反转、升级或外部打断结束机械流程。'
      })
    }
  }
  if (consecutiveNoExternalEvent >= 3) {
    issues.push({
      severity: structureHardFail ? 'major' : 'warning',
      type: 'no_external_event',
      hardFail: structureHardFail,
      chapters: chapterAnalyses.filter(item => !item.hasExternalEvent).map(item => item.chapterNum).filter(Boolean),
      title: '连续章节缺少真实外部事件',
      detail: `最近 5 章最长连续 ${consecutiveNoExternalEvent} 章缺少可见外部事件。`,
      suggestedAction: '下一章必须用外部压力和人物行动推进，而不是继续观察或确认。'
    })
  }
  if (mainGoalDrift || noIrreversibleCount >= 3) {
    issues.push({
      severity: structureHardFail ? 'major' : 'warning',
      type: mainGoalDrift ? 'main_goal_drift' : 'narrative_progression_fail',
      hardFail: structureHardFail,
      chapters: recent.map(item => item.chapterNum).filter(Boolean),
      title: mainGoalDrift ? '主线目标漂移' : '多章不可逆变化不足',
      detail: '多章围绕动态抽取出的高频概念或重复观察推进，缺少阶段性结果。',
      suggestedAction: '重建近景规划，让下一章承担明确转向和具体代价。'
    })
  }

  const hasHardIssue = issues.some(item => ['critical', 'major', 'severe'].includes(normalizeSeverity(item.severity)))
  const hasWarningIssue = issues.some(item => ['warning', 'minor', 'suggestion', 'medium'].includes(normalizeSeverity(item.severity)))
  const progressionGate = hasHardIssue ? 'fail' : hasWarningIssue ? 'warn' : 'pass'
  return {
    progressionGate,
    narrativeReadabilityGate: progressionGate,
    recent5RepeatedObjects,
    recent5RepeatedActions,
    recent5RepeatedConcepts,
    eventPatternLoops,
    sameSceneOrObjectLoop,
    sameEventPatternLoop,
    structureHardFail,
    latestHasNarrativeTurn,
    latestCanReaderRetell: latestAnalysis.canReaderRetell !== false,
    mainGoalDrift,
    consecutiveNoExternalEvent,
    recommendPauseGeneration: progressionGate === 'fail',
    issues,
    chapterAnalyses
  }
}

export function analyzeBeatPlanSourceDegradation(records = []) {
  const sorted = (Array.isArray(records) ? records : [])
    .map(item => ({
      chapterNum: Number(item.chapterNum || item.chapter_num || 0),
      source: item.source || item.type || '',
      reason: item.reason || ''
    }))
    .filter(item => item.chapterNum)
    .sort((a, b) => a.chapterNum - b.chapterNum)
  let currentStreak = 0
  let maxConsecutiveLocalRebuilds = 0
  let streakStart = null
  let maxStreakRange = []
  let previousChapterNum = null
  const localRebuildChapters = []
  const aiRecoveredChapters = []
  for (const item of sorted) {
    const local = item.source === 'local_safety_rebuild' || item.type === 'local_safety_rebuild'
    if (local) {
      localRebuildChapters.push(item.chapterNum)
      if (previousChapterNum !== null && item.chapterNum !== previousChapterNum + 1) {
        currentStreak = 0
        streakStart = null
      }
      if (!currentStreak) streakStart = item.chapterNum
      currentStreak += 1
      if (currentStreak > maxConsecutiveLocalRebuilds) {
        maxConsecutiveLocalRebuilds = currentStreak
        maxStreakRange = [streakStart, item.chapterNum]
      }
    } else {
      aiRecoveredChapters.push(item.chapterNum)
      currentStreak = 0
      streakStart = null
    }
    previousChapterNum = item.chapterNum
  }
  const currentConsecutiveLocalRebuilds = currentStreak
  const currentAiRecoveredChapters = []
  for (let index = sorted.length - 1; index >= 0; index -= 1) {
    const item = sorted[index]
    const local = item.source === 'local_safety_rebuild' || item.type === 'local_safety_rebuild'
    if (local) break
    currentAiRecoveredChapters.unshift(item.chapterNum)
  }
  const issues = []
  if (maxConsecutiveLocalRebuilds >= 2) {
    issues.push({
      severity: maxConsecutiveLocalRebuilds >= 3 ? 'critical' : 'major',
      type: maxConsecutiveLocalRebuilds >= 3 ? 'planning_local_rebuild_streak' : 'planning_degraded',
      chapters: maxStreakRange,
      title: maxConsecutiveLocalRebuilds >= 3 ? '连续本地安全重建达到硬失败阈值' : '近景规划质量降级',
      detail: `连续 ${maxConsecutiveLocalRebuilds} 章小纲依赖本地安全重建，AI 小纲未能主动通过推进/新鲜度闸。`,
      suggestedAction: '暂停扩大生成，先修近景规划、小纲 prompt 或卷目标接力。'
    })
  }
  return {
    planningDegraded: maxConsecutiveLocalRebuilds >= 2,
    currentPlanningDegraded: currentConsecutiveLocalRebuilds >= 2,
    hardFail: maxConsecutiveLocalRebuilds >= 3,
    currentHardFail: currentConsecutiveLocalRebuilds >= 3,
    recommendPauseGeneration: maxConsecutiveLocalRebuilds >= 3,
    maxConsecutiveLocalRebuilds,
    currentConsecutiveLocalRebuilds,
    maxStreakRange,
    historicalLocalRebuildChapters: localRebuildChapters,
    aiRecoveredChapters,
    currentAiRecoveredChapters,
    issues
  }
}

export function buildPlanningHealthRecord(input = {}) {
  const missingRequiredFields = Array.isArray(input.missingRequiredFields)
    ? input.missingRequiredFields.filter(Boolean)
    : []
  const consecutiveLocalRebuildCount = Number(input.consecutiveLocalRebuildCount || 0)
  const localSafetyRebuildUsed = Boolean(input.localSafetyRebuildUsed)
  const aiBeatPlanValid = Boolean(input.aiBeatPlanValid)
  return {
    chapterNum: Number(input.chapterNum || 0) || undefined,
    aiBeatPlanGenerated: Boolean(input.aiBeatPlanGenerated),
    aiBeatPlanValid,
    repairAttempted: Boolean(input.repairAttempted),
    repairSucceeded: Boolean(input.repairSucceeded),
    localSafetyRebuildUsed,
    consecutiveLocalRebuildCount,
    missingRequiredFields,
    volumeGoalHandoffStatus: input.volumeGoalHandoffStatus || (missingRequiredFields.includes('volumeGoalHandoff') ? 'fail' : 'pass'),
    planningDegraded: Boolean(input.planningDegraded) ||
      localSafetyRebuildUsed ||
      (localSafetyRebuildUsed && consecutiveLocalRebuildCount >= 2) ||
      !aiBeatPlanValid ||
      missingRequiredFields.length > 0 ||
      input.volumeGoalHandoffStatus === 'fail'
  }
}

export function summarizeProgressionRiskSources(acceptance = {}) {
  const issues = Array.isArray(acceptance.issues) ? acceptance.issues : []
  const riskTypes = new Set()
  const hardRiskTypes = new Set()
  const hasTermFrequencyLoop = (acceptance.recent5RepeatedObjects || []).length ||
    issues.some(item => item.type === 'same_object_loop')
  if (hasTermFrequencyLoop) riskTypes.add('term_frequency_loop')
  if (issues.some(item => ['same_event_pattern_loop', 'numbered_sequence_loop'].includes(item.type)) || acceptance.sameEventPatternLoop) {
    riskTypes.add('event_structure_loop')
  }
  if (issues.some(item => ['volume_goal_handoff_missing', 'volume_target_drift', 'main_goal_drift'].includes(item.type)) || acceptance.mainGoalDrift) {
    riskTypes.add('volume_goal_drift')
  }
  if (issues.some(item => ['planning_degraded', 'planning_local_rebuild_streak'].includes(item.type)) || acceptance.planningDegraded) {
    riskTypes.add('planning_degraded')
  }
  if (issues.some(item => ['no_external_event', 'narrative_progression_fail'].includes(item.type))) {
    riskTypes.add('narrative_progression_fail')
  }
  for (const item of issues) {
    if (!isHardContinuationIssue(item)) continue
    const type = item?.type
    if (type === 'same_object_loop') continue
    if (['same_event_pattern_loop', 'numbered_sequence_loop'].includes(type)) hardRiskTypes.add('event_structure_loop')
    if (['volume_goal_handoff_missing', 'volume_target_drift', 'main_goal_drift'].includes(type)) hardRiskTypes.add('volume_goal_drift')
    if (['planning_degraded', 'planning_local_rebuild_streak'].includes(type)) hardRiskTypes.add('planning_degraded')
    if (['no_external_event', 'narrative_progression_fail'].includes(type)) hardRiskTypes.add('narrative_progression_fail')
    if (isHardSettingContradictionIssue(item)) hardRiskTypes.add('setting_contradiction')
  }

  const localHardGate = acceptance.progressionGate === 'fail' ||
    acceptance.narrativeReadabilityGate === 'fail' ||
    hardRiskTypes.size > 0
  const localGateOverride = acceptance.safeToContinue === true && localHardGate
  const shouldTreatAsSafeToContinue = !localGateOverride &&
    !localHardGate &&
    acceptance.progressionGate !== 'fail' &&
    acceptance.narrativeReadabilityGate !== 'fail'

  const pieces = []
  if (localGateOverride) pieces.push('模型返回 safeToContinue=true，但本地硬门检测到不可继续风险，按本地 progressionGate 处理。')
  if (riskTypes.has('term_frequency_loop')) pieces.push('词频重复风险来自动态高频物象/地点/概念。')
  if (riskTypes.has('event_structure_loop')) pieces.push('事件结构风险来自连续章节使用相同进入、观看、选择、离开的流程。')
  if (riskTypes.has('volume_goal_drift')) pieces.push('卷目标风险来自小纲没有推进当前卷缺口或没有切回主线。')
  if (riskTypes.has('planning_degraded')) pieces.push('规划风险来自连续依赖本地安全重建，AI 小纲未主动合规。')
  if (riskTypes.has('narrative_progression_fail')) pieces.push('叙事推进风险来自缺少外部事件、不可逆变化或阶段性结果。')

  return {
    riskTypes: [...riskTypes],
    hardRiskTypes: [...hardRiskTypes],
    localGateOverride,
    shouldTreatAsSafeToContinue,
    explanation: pieces.join('') || '未发现本地硬门风险。'
  }
}

export function mergeSafeToContinueWithLocalGates(acceptance = {}) {
  const riskSummary = summarizeProgressionRiskSources(acceptance)
  const hardGateReasons = []
  const hasHardIssue = (acceptance.issues || []).some(isHardContinuationIssue)
  if (acceptance.progressionGate === 'fail') hardGateReasons.push('progressionGate=fail')
  if (acceptance.narrativeReadabilityGate === 'fail') hardGateReasons.push('narrativeReadabilityGate=fail')
  if (acceptance.recommendPauseGeneration && (hasHardIssue || acceptance.progressionGate === 'fail' || acceptance.narrativeReadabilityGate === 'fail')) hardGateReasons.push('recommendPauseGeneration=true')
  if (hasHardIssue) hardGateReasons.push('hardIssues')
  const shouldContinue = riskSummary.shouldTreatAsSafeToContinue && hardGateReasons.length === 0
  return {
    ...acceptance,
    safeToContinue: shouldContinue,
    recommendPauseGeneration: !shouldContinue,
    localGateOverride: riskSummary.localGateOverride || hardGateReasons.length > 0,
    safeToContinueReason: shouldContinue
      ? '模型验收和本地硬门均未发现阻断。'
      : `本地硬门归并为不可继续：${hardGateReasons.join('，') || riskSummary.explanation}`,
    progressionRiskSummary: riskSummary
  }
}

function normalizeChapterNumberSet(values = []) {
  return new Set((Array.isArray(values) ? values : [])
    .map(item => Number(item))
    .filter(Number.isFinite))
}

function issueChapterNums(issue = {}) {
  const chapters = Array.isArray(issue.chapters)
    ? issue.chapters
    : issue.chapterNum !== undefined
      ? [issue.chapterNum]
      : []
  return chapters
    .flatMap(item => String(item || '').split(/[,\s]+/))
    .map(item => Number(item))
    .filter(Number.isFinite)
}

function issueTouchesCurrentRun(issue = {}, currentRunSet = new Set()) {
  const chapters = issueChapterNums(issue)
  if (!chapters.length) return true
  return chapters.some(chapterNum => currentRunSet.has(chapterNum))
}

function isHardSettingContradictionIssue(issue = {}) {
  const severity = normalizeSeverity(issue.severity)
  if (!['critical', 'major', 'severe'].includes(severity)) return false
  const type = String(issue.type || '')
  if (HARD_SETTING_CONTRADICTION_TYPES.has(type)) return true
  return /设定矛盾|硬设定|世界规则|时间线矛盾|状态矛盾|setting contradiction|world rule/i.test(
    [issue.title, issue.detail, issue.suggestedAction].filter(Boolean).join(' ')
  )
}

function isHardContinuationIssue(issue = {}) {
  const type = String(issue.type || '')
  if (type === 'same_object_loop') return false
  if (type === 'same_event_pattern_loop' && issue.hardFail === false) return false
  if (['no_external_event', 'main_goal_drift', 'narrative_progression_fail'].includes(type) && issue.hardFail === false) return false
  return ['critical', 'major', 'severe'].includes(normalizeSeverity(issue.severity))
}

function riskSourcesFromIssues(issues = []) {
  const sources = new Set()
  for (const issue of issues) {
    const type = issue?.type
    if (type === 'same_object_loop') sources.add('term_frequency_loop')
    if (['same_event_pattern_loop', 'numbered_sequence_loop'].includes(type)) sources.add('event_structure_loop')
    if (['volume_goal_handoff_missing', 'volume_target_drift', 'main_goal_drift'].includes(type)) sources.add('volume_goal_drift')
    if (['planning_degraded', 'planning_local_rebuild_streak'].includes(type)) sources.add('planning_degraded')
    if (['no_external_event', 'narrative_progression_fail'].includes(type)) sources.add('narrative_progression_fail')
    if (isHardSettingContradictionIssue(issue)) sources.add('setting_contradiction')
  }
  return [...sources]
}

export function splitCurrentAndHistoricalAcceptance(acceptance = {}, options = {}) {
  const currentRunSet = normalizeChapterNumberSet(options.currentRunChapterNums || acceptance.currentRunChapterNums || [])
  const issues = Array.isArray(acceptance.issues) ? acceptance.issues : []
  const currentRunIssues = []
  const historicalDebt = []
  for (const issue of issues) {
    if (!currentRunSet.size) historicalDebt.push(issue)
    else if (issueTouchesCurrentRun(issue, currentRunSet)) currentRunIssues.push(issue)
    else historicalDebt.push(issue)
  }
  const historicalDebtBlocksCurrent = currentRunSet.size > 0 && historicalDebt.some(isHardSettingContradictionIssue)
  const currentRunRiskSources = riskSourcesFromIssues(currentRunIssues)
  const historicalDebtRiskSources = riskSourcesFromIssues(historicalDebt)
  const hasUnscopedHardGate = !issues.length &&
    (acceptance.progressionGate === 'fail' ||
      acceptance.narrativeReadabilityGate === 'fail' ||
      acceptance.recommendPauseGeneration === true ||
      acceptance.safeToContinue === false)
  const currentRunHardIssues = currentRunIssues.filter(isHardContinuationIssue)
  const currentRunSafeToContinue = !historicalDebtBlocksCurrent &&
    !hasUnscopedHardGate &&
    currentRunHardIssues.length === 0
  const overallSafeToContinue = currentRunSafeToContinue &&
    historicalDebt.length === 0 &&
    acceptance.safeToContinue !== false
  const overallRiskSources = unique([
    ...currentRunRiskSources,
    ...historicalDebtRiskSources,
    ...(historicalDebt.length ? ['historical_debt'] : [])
  ])
  return {
    ...acceptance,
    currentRunChapterNums: [...currentRunSet].sort((a, b) => a - b),
    currentRunIssues,
    historicalDebt,
    historicalDebtIssues: historicalDebt,
    historicalDebtBlocksCurrent,
    currentRunRiskSources,
    historicalDebtRiskSources,
    overallRiskSources,
    currentRunSafeToContinue,
    overallSafeToContinue,
    safeToContinue: currentRunSafeToContinue,
    recommendPauseGeneration: !currentRunSafeToContinue,
    overallRecommendPauseGeneration: !overallSafeToContinue,
    safeToContinueReason: currentRunSafeToContinue
      ? (historicalDebt.length
          ? `本轮新增章节未触发硬阻断；历史债务 ${historicalDebt.length} 项已单独记录。`
          : '本轮新增章节未触发硬阻断。')
      : historicalDebtBlocksCurrent
        ? '历史硬设定矛盾仍会阻断当前继续生成。'
        : `本轮新增章节存在硬阻断：${currentRunHardIssues.map(item => item.type).filter(Boolean).join('、') || 'local hard gate'}`
  }
}

function normalizeChapterNum(value) {
  const num = Number(value)
  return Number.isFinite(num) ? num : 0
}

function qualityFindingChapterNum(item = {}) {
  return normalizeChapterNum(item.chapterNum || item.chapter_num || item.chapter)
}

function isSevereQualityFinding(item = {}) {
  return item?.aiTraceLevel === 'severe' || item?.humanTextureLevel === 'severe'
}

function hasIssueType(analysis = {}, type = '') {
  return (analysis.issues || []).some(item => item.type === type)
}

function countCjkCharsForQuality(value = '') {
  return (String(value || '').match(/[\u4e00-\u9fff]/g) || []).length
}

export function shouldAcceptNarrativeReadabilityRepair(before, after, repairedText = '', originalText = '', options = {}) {
  if (!before || !after) return false
  const targetIssueType = options.targetIssueType || 'paragraph_level_repetition'
  if (!hasIssueType(before, targetIssueType)) return false
  if (hasIssueType(after, targetIssueType)) return false
  const beforeHardTypes = new Set((before.issues || [])
    .filter(item => ['critical', 'severe'].includes(normalizeSeverity(item.severity)))
    .map(item => item.type))
  const newHardIssue = (after.issues || []).some(item =>
    ['critical', 'severe'].includes(normalizeSeverity(item.severity)) &&
    !beforeHardTypes.has(item.type)
  )
  if (newHardIssue) return false
  if (before.hasExternalEvent && !after.hasExternalEvent) return false
  if (before.hasConcreteAction && !after.hasConcreteAction) return false
  if (before.canReaderRetell && !after.canReaderRetell) return false
  if (Number(after.notXButYCount || 0) > Number(before.notXButYCount || 0) + 1) return false
  const drift = countCjkCharsForQuality(repairedText) / Math.max(countCjkCharsForQuality(originalText), 1)
  if (drift < Number(options.minDrift ?? 0.35) || drift > Number(options.maxDrift ?? 1.18)) return false
  return true
}

export function mergeCurrentRunQualityRisk(acceptance = {}, qualityFindings = [], options = {}) {
  const currentRunChapters = normalizeChapterNumberSet(
    options.currentRunChapterNums ||
      acceptance.currentRunChapters ||
      acceptance.currentRunChapterNums ||
      []
  )
  const maxNotXButY = Number(options.maxNotXButY ?? 2)
  const latestByChapter = new Map()
  for (const item of Array.isArray(qualityFindings) ? qualityFindings : []) {
    const chapterNum = qualityFindingChapterNum(item)
    if (!chapterNum) continue
    if (currentRunChapters.size && !currentRunChapters.has(chapterNum)) continue
    const existing = latestByChapter.get(chapterNum)
    const itemPreferred = item?.qualityTextSource === 'final_version' ? 1 : 0
    const existingPreferred = existing?.qualityTextSource === 'final_version' ? 1 : 0
    if (!existing || itemPreferred >= existingPreferred) latestByChapter.set(chapterNum, item)
  }

  const holdItems = []
  for (const [chapterNum, item] of latestByChapter.entries()) {
    const notXButYCount = Number(item?.notXButYCount || 0)
    if (isSevereQualityFinding(item) || notXButYCount > maxNotXButY || item?.qualityHold === true) {
      holdItems.push({
        chapterNum,
        aiTraceLevel: item?.aiTraceLevel || 'low',
        humanTextureLevel: item?.humanTextureLevel || 'low',
        notXButYCount,
        reasons: [
          isSevereQualityFinding(item) ? `AI=${item?.aiTraceLevel || 'low'}, human=${item?.humanTextureLevel || 'low'}` : '',
          notXButYCount > maxNotXButY ? `notXButY=${notXButYCount}` : '',
          item?.qualityHoldReason || ''
        ].filter(Boolean)
      })
    }
  }

  const currentRunQualityRisk = holdItems.length > 0
  const qualityHoldReason = currentRunQualityRisk
    ? holdItems.map(item => `chapter ${item.chapterNum}: ${item.reasons.join(', ')}`).join('; ')
    : ''
  return {
    ...acceptance,
    currentRunQualityRisk,
    qualityHold: currentRunQualityRisk,
    qualityHoldChapters: holdItems.map(item => item.chapterNum),
    qualityHoldReason,
    recommendPauseGeneration: Boolean(acceptance.recommendPauseGeneration || currentRunQualityRisk)
  }
}

export function summarizeMultiChapterQuality(chapters = []) {
  const dimensionCounts = {}
  const chapterScores = chapters.map(chapter => {
    const qualityScore = chapter.qualityScore || scoreChapterWritingQuality(chapter)
    for (const dimension of qualityScore.aiTraceDimensions || []) {
      dimensionCounts[dimension] = Number(dimensionCounts[dimension] || 0) + 1
    }
    for (const dimension of qualityScore.humanTextureDimensions || []) {
      dimensionCounts[dimension] = Number(dimensionCounts[dimension] || 0) + 1
    }
    for (const dimension of qualityScore.narrativeReadabilityDimensions || []) {
      dimensionCounts[dimension] = Number(dimensionCounts[dimension] || 0) + 1
    }
    return { ...chapter, qualityScore }
  })
  const severeChapters = chapterScores
    .filter(item => item.qualityScore.aiTraceLevel === 'severe' || item.qualityScore.narrativeReadabilityGate === 'fail')
    .map(item => item.chapterNum)
    .filter(Boolean)
  const suggestManualPolishChapters = chapterScores
    .filter(item => item.qualityScore.suggestManualPolish)
    .map(item => item.chapterNum)
    .filter(Boolean)
  const severeRepeated = severeChapters.length >= 3 && severeChapters.length >= Math.ceil(chapterScores.length * 0.5)
  return {
    chapters: chapterScores,
    frequentDimensions: topCounts(dimensionCounts, 8),
    suggestManualPolishChapters,
    severeChapters,
    trendWorsened: severeRepeated,
    shouldContinue: !severeRepeated,
    aiTraceDimensionCatalog: AI_TRACE_DIMENSIONS.map(item => item.id),
    humanTextureDimensionCatalog: HUMAN_TEXTURE_DIMENSIONS.map(item => item.id),
    narrativeReadabilityGateCatalog: NARRATIVE_READABILITY_GATES.map(item => item.id)
  }
}
