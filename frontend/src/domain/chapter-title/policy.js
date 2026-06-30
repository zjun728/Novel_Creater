export const TITLE_POLICY_FAIL_REASONS = Object.freeze({
  EMPTY: 'empty',
  DEFAULT_TITLE: 'default_title',
  INTERNAL_FIELD: 'internal_field',
  LATIN_FRAGMENT: 'latin_fragment',
  JSON_OR_KEY_VALUE_FRAGMENT: 'json_or_key_value_fragment',
  DIALOGUE_FRAGMENT: 'dialogue_fragment',
  DIRECTION_FRAGMENT: 'direction_fragment',
  ROUTE_QUESTION_FRAGMENT: 'route_question_fragment',
  DIRECTION_QUESTION_FRAGMENT: 'direction_question_fragment',
  LOCATION_POINTER_FRAGMENT: 'location_pointer_fragment',
  ORAL_JUDGMENT_FRAGMENT: 'oral_judgment_fragment',
  SINGLE_CHARACTER_ACTION_FRAGMENT: 'single_character_action_fragment',
  LOCATION_FRAGMENT: 'location_fragment',
  ORAL_FRAGMENT: 'oral_fragment',
  TOO_LONG: 'too_long',
  PUNCTUATION: 'punctuation',
  SENTENCE_LIKE: 'sentence_like',
  DUPLICATE: 'duplicate',
  NOT_CONCRETE: 'not_concrete_catalog_label'
})

const TITLE_MOJIBAKE_PATTERN = /[\u6d63\u6b10\u4fef\u93c6\u6940\u5f7f\u7441\u509c\u68d4\u951f\ufffd\u9286\u7ed7\u9351\u93cb\u9428\u93c4\u6d93\u699b\u5997\u7039\u93b4\u93c3\u935a\u9366\u95c2]/
const TITLE_INTERNAL_FIELD_PATTERN = /^(?:reason|title|stage|chapter|draft|final|summary|outline|beat|scene|key|value|type|content|message|error|result|status|prompt|quality|analysis)(?:[_-]?(?:id|name|text|reason|summary|title|type|status))?$/i
const TITLE_LATIN_FRAGMENT_PATTERN = /^[A-Za-z][A-Za-z0-9 _-]{0,40}$/
const TITLE_KEY_VALUE_FRAGMENT_PATTERN = /^\s*["']?(?:reason|title|stage|chapter|draft|final|summary|outline|beat|scene|key|value|type|content|message|error|result|status|prompt|quality|analysis)["']?\s*[:=]\s*.+$/i
const TITLE_JSON_OR_CODE_FRAGMENT_PATTERN = /^\s*(?:[{[\]}]|["']?(?:reason|title|summary|content)["']?\s*:|(?:const|let|var|return|function|if|else)\b|`{1,3})/i

const HARD_DIALOGUE_FRAGMENT_TITLES = new Set([
  '别管我',
  '别动',
  '别问',
  '别说',
  '别碰',
  '闭嘴',
  '住手',
  '快走',
  '谁派你来的',
  '怎么了',
  '怎么回事'
])

const HARD_DIRECTION_FRAGMENT_TITLES = new Set([
  '里面',
  '外面',
  '这边',
  '那边',
  '这里',
  '那里',
  '这儿',
  '那儿',
  '前面',
  '后面',
  '前头',
  '后头',
  '左边',
  '右边',
  '上面',
  '下面'
])

const ORAL_JUDGMENT_FRAGMENT_TITLES = new Set([
  '不一定',
  '可支撑',
  '也许吧',
  '可能吧',
  '假的',
  '真的'
])

const SINGLE_ACTION_FRAGMENT_TITLES = new Set([
  '坐',
  '走',
  '追',
  '看',
  '等',
  '跑',
  '停',
  '开',
  '关'
])

const ORAL_STATE_FRAGMENT_TITLES = new Set([
  '走不了',
  '跑不了',
  '躲不了',
  '去不了',
  '过不去',
  '没办法',
  '撑不住',
  '假的'
])

const ROUTE_DISTANCE_QUESTION_PATTERN = /^(?:还(?:有|要)?多远|多远了?|走多久|要走多久|还有多久|多久到|到哪了?|到了没|到没到)$/u
const DIRECTION_PATH_QUESTION_PATTERN = /^(?:这(?:沟通|通向|通到|通往)哪(?:儿|里)?|往哪(?:儿|里)?走|向哪(?:儿|里)?走|从哪(?:儿|里)?走|哪(?:儿|里)?走|去哪(?:儿|里)?|去哪|怎么走)$/u
const LOCATION_POINTER_FRAGMENT_PATTERN = /^(?:就是|就在|就)(?:这里|这儿|这边|那里|那儿|那边|里面|外面|前头|后头)$/u

const ITEM_TAILS = [
  '密信',
  '信件',
  '账册',
  '账本',
  '纸条',
  '仓钥',
  '钥匙',
  '残卷',
  '残页',
  '凭证',
  '令牌',
  '黑铁令',
  '玉牌',
  '玉简',
  '铜盘',
  '铜扣',
  '棺材',
  '灵髓',
  '信物',
  '短讯',
  '尾号',
  '地址',
  '断钥',
  '卡',
  '令',
  '符',
  '钥',
  '信',
  '书',
  '页',
  '扣'
]
const PLACE_TAILS = [
  '粮栈',
  '客栈',
  '地窖',
  '染坊',
  '密室',
  '矿道',
  '档案室',
  '火灶房',
  '山庄',
  '山门',
  '后院',
  '祠堂',
  '地牢',
  '钟楼',
  '街',
  '仓',
  '库',
  '栈',
  '房',
  '室',
  '堂',
  '殿',
  '院',
  '庄',
  '寺',
  '阁',
  '楼',
  '城',
  '寨',
  '谷',
  '门',
  '道'
]
const ORG_TAILS = ['宝行', '商行', '商盟', '商会', '寺', '庙', '宗', '门派', '帮', '会', '阁', '楼', '院', '书院', '镖局', '司', '盟']
const SKILL_WEAPON_TAILS = ['长生功', '功法', '心法', '身法', '剑法', '刀法', '秘术', '灵术', '炼灵', '术', '诀', '法', '剑', '刀', '枪', '弓', '戟']
const EVENT_TAILS = ['审问', '争夺', '惊变', '服软', '背叛', '追击', '对峙', '交易', '回收', '归还', '失约', '离场', '入局', '破局', '救人', '反悔', '伏击', '烧信', '验信', '开门', '关门', '换债', '换账', '放信号', '取信', '取图']
const EVENT_PHRASE_TITLES = new Set(['交易', '中毒', '返回', '选择', '聚集', '赌约', '破禁', '出手', '突变', '恶斗', '挑战', '拔毒', '试毒', '谈判', '火起', '雷灭', '对策', '遇敌'])
const TITLE_STATE_TAILS = ['冷光', '裂痕', '裂纹', '余温', '暗号', '微光', '白光', '黑光', '字迹', '凭证', '倒计时']
const ABSTRACT_TITLE_SUBJECT_PARTS = ['核心', '规则', '系统', '真相', '答案', '线索', '记忆', '意识', '结构']
const CULTIVATION_LEVEL_PATTERN = /^(?:炼气|练气|筑基|结丹|金丹|元婴|化神|炼虚|合体|大乘|渡劫|炼灵)(?:[一二三四五六七八九十百千万零〇两0-9]+(?:层|重|品|阶|等|转)|初期|中期|后期|圆满|大圆满|初成|小成|大成)?$/u
const POWER_LEVEL_PATTERN = /^(?:(?:法力|灵力|真元|灵压|灵息)[一二三四五六七八九十百千万零〇两0-9]+(?:层|重|品|阶|等|转)|[一二三四五六七八九十百千万零〇两0-9]+(?:层|重|品|阶|等|转)(?:法力|灵力|真元|灵压|灵息))$/u
const SERIAL_TITLE_SUFFIX_PATTERN = /[（(][上中下][）)]$/u

function titleCharLength(title) {
  return Array.from(String(title || '')).length
}

function stripTitleFragmentEdgePunctuation(title = '') {
  return String(title || '')
    .trim()
    .replace(/^[…—\-，。！？!?,、；;：:\s]+/g, '')
    .replace(/[.…—\-，。！？!?,、；;：:\s]+$/g, '')
    .trim()
}

export function normalizeChapterTitle(title = '') {
  return String(title || '')
    .replace(/^\s*```(?:json|markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .trim()
    .split(/\r?\n/)
    .map(line => line.trim())
    .find(Boolean)
    ?.replace(/^[-*]\s*/, '')
    .replace(/^#{1,6}\s*/, '')
    .replace(/^(?:章名|标题|章节标题|title)\s*[：:]\s*/i, '')
    .replace(/^第\s*[\d一二三四五六七八九十百千万零〇两]+\s*章\s*[：:、，.\-—]?\s*/, '')
    .replace(/^[《“"「『【\[]+/, '')
    .replace(/[》”"」』】\]]+$/, '')
    .replace(/[。！？!?,，；;：:、\s]+$/g, '')
    .replace(/\s+/g, '')
    .trim() || ''
}

export function isDefaultChapterTitle(title, chapterNum) {
  const text = String(title || '').trim()
  if (!text || text === '未命名') return true
  const num = String(chapterNum || '').trim()
  if (!num) return /^第\s*\d+\s*章$/.test(text)
  return new RegExp(`^第\\s*${num}\\s*章$`).test(text)
}

export function normalizeChapterTitleKey(title) {
  return String(title || '')
    .replace(/\s+/g, '')
    .replace(/^第[\d一二三四五六七八九十百千万零〇两]+章[·:：、，.\-—]?/, '')
    .trim()
}

function titleBackedByMaterials(title, context = {}) {
  const key = normalizeChapterTitleKey(title)
  const materials = Array.isArray(context.materials) ? context.materials : []
  return materials.some(item => normalizeChapterTitleKey(item?.title || item) === key)
}

function collectExistingChapterTitleKeys(context = {}) {
  const values = [
    ...(Array.isArray(context.existingTitles) ? context.existingTitles : []),
    ...(Array.isArray(context.existingChapterTitles) ? context.existingChapterTitles : [])
  ]
  return new Set(values.map(normalizeChapterTitleKey).filter(Boolean))
}

export function isChapterTitleDuplicate(title, context = {}) {
  const key = normalizeChapterTitleKey(title)
  if (!key) return false
  return collectExistingChapterTitleKeys(context).has(key)
}

function isHardDialogueFragmentTitle(title = '') {
  const raw = String(title || '').trim()
  const text = stripTitleFragmentEdgePunctuation(raw)
  if (HARD_DIALOGUE_FRAGMENT_TITLES.has(raw) || HARD_DIALOGUE_FRAGMENT_TITLES.has(text)) return true
  if (/^别(?:管我|动|问|说|碰|过来|追|回头|看|吵|喊|理我?)$/u.test(text)) return true
  if (/^谁.{0,5}(?:派|让|叫).{0,4}(?:来|来的|去|去的)$/u.test(text)) return true
  if (/^(?:怎么了|怎么回事|出什么事了)$/u.test(text)) return true
  return false
}

function isHardDirectionFragmentTitle(title = '') {
  const text = stripTitleFragmentEdgePunctuation(title)
  if (HARD_DIRECTION_FRAGMENT_TITLES.has(text)) return true
  return /^(?:前|后|左|右|里|外|上|下)(?:面|边|头)$/u.test(text)
}

function detectIllegalChapterTitleFragment(title) {
  const text = String(title || '').trim()
  if (!text) return TITLE_POLICY_FAIL_REASONS.EMPTY
  const fragmentText = stripTitleFragmentEdgePunctuation(text)
  if (TITLE_INTERNAL_FIELD_PATTERN.test(text)) return TITLE_POLICY_FAIL_REASONS.INTERNAL_FIELD
  if (TITLE_LATIN_FRAGMENT_PATTERN.test(text)) return TITLE_POLICY_FAIL_REASONS.LATIN_FRAGMENT
  if (/^[\p{Punctuation}\p{Symbol}]+$/u.test(text)) return 'symbol_fragment'
  if (/^[{}[\]()`#>*_+=|\\/]+$/u.test(text)) return 'markup_or_json_fragment'
  if (/^(?:你|我|他|她|它|谁|这|那|嗯|啊|哦|呀|喂|哈|嘿)[—\-…~，。！？!?,]*$/u.test(text)) return TITLE_POLICY_FAIL_REASONS.DIALOGUE_FRAGMENT
  if (isHardDialogueFragmentTitle(text)) return TITLE_POLICY_FAIL_REASONS.DIALOGUE_FRAGMENT
  if (isHardDirectionFragmentTitle(text)) return TITLE_POLICY_FAIL_REASONS.DIRECTION_FRAGMENT
  if (ROUTE_DISTANCE_QUESTION_PATTERN.test(fragmentText)) return TITLE_POLICY_FAIL_REASONS.ROUTE_QUESTION_FRAGMENT
  if (DIRECTION_PATH_QUESTION_PATTERN.test(fragmentText)) return TITLE_POLICY_FAIL_REASONS.DIRECTION_QUESTION_FRAGMENT
  if (LOCATION_POINTER_FRAGMENT_PATTERN.test(fragmentText)) return TITLE_POLICY_FAIL_REASONS.LOCATION_POINTER_FRAGMENT
  if (ORAL_JUDGMENT_FRAGMENT_TITLES.has(fragmentText)) return TITLE_POLICY_FAIL_REASONS.ORAL_JUDGMENT_FRAGMENT
  if (SINGLE_ACTION_FRAGMENT_TITLES.has(fragmentText)) return TITLE_POLICY_FAIL_REASONS.SINGLE_CHARACTER_ACTION_FRAGMENT
  if (/^(?:这边|那边|这儿|那儿|这里|那里|里面|外面|前头|后头|前面|后面)(?:也)?有(?:[\u4e00-\u9fa5]{0,4})?$/u.test(fragmentText)) return TITLE_POLICY_FAIL_REASONS.LOCATION_FRAGMENT
  if (/^(?:操|艹|草|靠|淦|呸|啧|嗐|唉|哎|啊|嗯|哦|喂|嘿|哈)$/u.test(text)) return 'single_character_profanity_or_interjection'
  return ''
}

function isLikelyOralFragmentTitle(title = '') {
  const text = String(title || '').trim()
  if (!text) return false
  if (detectIllegalChapterTitleFragment(text)) return true
  if (/^(?:这边|那边|这儿|那儿|这里|那里|前头|后头|前面|后面)(?:也)?有[\u4e00-\u9fa5]{0,4}$/u.test(text)) return true
  if (/^(?:走门|后面走|前面走)$/u.test(text)) return true
  if (/^(?:前面|后面|左边|右边|前边|后边|左面|右面)?(?:往左|往右|向前|后退|快走|走|走了|哪走|后面走|前面走|进去|出来)$/.test(text)) return true
  if (/^[\u4e00-\u9fa5A-Za-z0-9·]{1,5}(?:呢|去哪儿|在哪儿|怎么办|干什么)$/.test(text)) return true
  if (/^(?:收|找|问|看|拿|要|给|交|查)[\u4e00-\u9fa5]{0,2}(?:啥|什么)(?:啊|呢|吗|吧)?$/u.test(text)) return true
  if (/^(?:这|那).{1,5}(?:哪儿|哪里|什么|明显|没用)$/u.test(text)) return true
  if (/^(?:有|没)[\u4e00-\u9fa5]{1,2}$/u.test(text)) return true
  if (/^(?:放|搁|摆|丢|扔)(?:这儿|这里|那儿|那里|这边|那边)$/u.test(text)) return true
  if (/^(?:来|给|拿|看|说|问|走|跑|开|关|让|把)[一二三四五六七八九十百千万零〇两0-9]?[个张句下把回眼]?$/u.test(text)) return true
  if (/^(?:你|我|他|她|它|咱|咱们|你们|我们|他们|她们).{1,5}(?:的|呢|吗|吧|啊|呀|么)?$/u.test(text)) return true
  if (/^(?:怎么|咋|干嘛|干什么|凭什么|为什么).{0,4}$/u.test(text)) return true
  return false
}

function isCompleteSentenceLikeTitle(title) {
  const text = String(title || '')
  if (titleCharLength(text) > 8) return true
  return /^[\u4e00-\u9fa5]{1,4}(?:站在|坐在|走进|进入|进了|到了|来到|回到|离开|发现|找到|看见|听见|想起|拿起|放下|说道|问道|按住|推开)/.test(text)
}

function isAbstractStateLikeTitle(title = '') {
  const text = String(title || '')
  if (titleCharLength(text) < 4) return false
  const tail = TITLE_STATE_TAILS.find(item => text.endsWith(item))
  if (!tail) return false
  const subject = text.slice(0, -tail.length)
  return ABSTRACT_TITLE_SUBJECT_PARTS.some(part => subject.includes(part))
}

function isWeakDialogueQuestionTitle(title = '') {
  const text = String(title || '').trim()
  if (!text) return false
  return /^[\u4e00-\u9fa5]{1,5}(?:吗|呢|么|啊|吧)$/u.test(text)
}

function isWeakDirectionOrActionFragmentTitle(title = '') {
  const text = String(title || '').trim()
  if (!text) return false
  if (/^(?:今晚|明天|现在|先|就)?(?:住|歇|睡|躲|等|留|藏)(?:这儿|这里|那儿|那里|一晚|一夜)$/u.test(text)) return true
  return /^(?:冲|走|跑|退|躲|逃|进|出|上|下|回|过|挡|拦|追|停)[\u4e00-\u9fa5]{0,4}(?:来|去|进来|出去|不了|不动|不进|不出|不来|不去)$/u.test(text)
}

function isConcreteStateTitle(title = '') {
  const text = String(title || '')
  const tail = TITLE_STATE_TAILS.find(item => text.endsWith(item))
  if (!tail) return false
  const subject = text.slice(0, -tail.length)
  return titleCharLength(subject) >= 1 && !ABSTRACT_TITLE_SUBJECT_PARTS.some(part => subject.includes(part))
}

function stripSerialTitleSuffix(title = '') {
  return String(title || '').trim().replace(SERIAL_TITLE_SUFFIX_PATTERN, '')
}

function isSerialChapterTitle(title = '') {
  const text = String(title || '').trim()
  const base = stripSerialTitleSuffix(text)
  return base !== text && titleCharLength(base) >= 2 && titleCharLength(base) <= 6
}

function isCultivationOrPowerLevelTitle(title = '') {
  const text = String(title || '').trim()
  return CULTIVATION_LEVEL_PATTERN.test(text) || POWER_LEVEL_PATTERN.test(text)
}

function isPairOrConfrontationTitle(title = '') {
  const text = stripSerialTitleSuffix(title)
  const match = text.match(/^([\u4e00-\u9fa5一二三四五六七八九十0-9]{1,4})(与|和|对)([\u4e00-\u9fa5一二三四五六七八九十0-9]{1,4})$/u)
  if (!match) return false
  return !['你', '我', '他', '她', '它', '这', '那'].includes(match[1]) &&
    !['你', '我', '他', '她', '它', '这', '那'].includes(match[3])
}

function isPossessiveCatalogTitle(title = '') {
  const text = stripSerialTitleSuffix(title)
  return /^[\u4e00-\u9fa5一二三四五六七八九十0-9]{1,4}之[\u4e00-\u9fa5一二三四五六七八九十0-9]{1,4}$/u.test(text)
}

function isPlainSceneOrPersonPhrase(title = '') {
  const text = String(title || '')
  return /^[\u4e00-\u9fa5]{1,4}(?:夜|雨|雪|风|客|归人|旧人|故人|来客)$/.test(text) ||
    /(?:归人|来客|旧人|故人)$/.test(text)
}

export function inferChapterTitleType(title = '', context = {}) {
  const raw = String(title || '')
  const text = stripSerialTitleSuffix(raw)
  if (titleBackedByMaterials(text, context)) {
    const material = (context.materials || []).find(item => normalizeChapterTitleKey(item?.title || item) === normalizeChapterTitleKey(text))
    return material?.type || 'material'
  }
  if (/^[\u4e00-\u9fa5]{1,6}(?:[一二三四五六七八九十百千万零〇两0-9]?号)?(?:门|画布|房间|空间)$/.test(text)) return 'place'
  if (PLACE_TAILS.some(tail => text.endsWith(tail))) return 'place'
  if (ITEM_TAILS.some(tail => text.endsWith(tail))) return 'item'
  if (ORG_TAILS.some(tail => text.endsWith(tail))) return 'organization'
  if (isCultivationOrPowerLevelTitle(text)) return 'result'
  if (isPairOrConfrontationTitle(text)) return 'conflict'
  if (isPossessiveCatalogTitle(text)) return 'item'
  if (SKILL_WEAPON_TAILS.some(tail => text.endsWith(tail))) return /(?:剑|刀|枪|弓|戟)$/.test(text) ? 'weapon' : 'skill'
  if (EVENT_PHRASE_TITLES.has(text)) return 'event'
  if (EVENT_TAILS.some(word => text === word || text.endsWith(word))) return 'event'
  if (/^[\u4e00-\u9fa5]{1,4}(?:和尚|道士|师兄|师姐|师妹|师弟|掌柜|先生|夫人|小姐|长老|真人|婆婆|姑娘)$/.test(text)) return 'person'
  if (/^[\u4e00-\u9fa5][\u4e00-\u9fa5一二三四五六七八九十0-9]{1,2}$/.test(text) && !/^(新的|旧的|这个|那个|这里|那里|里面|外面)/.test(text)) return 'person'
  if (isConcreteStateTitle(text)) return 'result'
  if (isPlainSceneOrPersonPhrase(text)) return 'event'
  return ''
}

function isConcreteCatalogLabelTitle(title = '', context = {}) {
  const text = String(title || '').trim()
  if (!text) return false
  if (isSerialChapterTitle(text)) return isConcreteCatalogLabelTitle(stripSerialTitleSuffix(text), context)
  if (isPairOrConfrontationTitle(text) || isPossessiveCatalogTitle(text)) return true
  if (titleBackedByMaterials(text, context)) return true
  if (inferChapterTitleType(text, context)) return true
  return false
}

function countChapterTitleChars(title) {
  const chars = Array.from(String(title || '').replace(/\s+/g, ''))
  let semantic = 0
  let punctuationOrSymbol = 0
  for (const char of chars) {
    if (/[\p{Letter}\p{Number}]/u.test(char)) semantic += 1
    else if (/[\p{Punctuation}\p{Symbol}]/u.test(char)) punctuationOrSymbol += 1
  }
  return { total: chars.length, semantic, punctuationOrSymbol }
}

export function evaluateChapterTitlePolicy(title, context = {}) {
  const rawText = String(title || '').trim()
  if (isDefaultChapterTitle(rawText, context.chapterNum)) return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.DEFAULT_TITLE, title: rawText }
  if (TITLE_KEY_VALUE_FRAGMENT_PATTERN.test(rawText) || TITLE_JSON_OR_CODE_FRAGMENT_PATTERN.test(rawText)) {
    return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.JSON_OR_KEY_VALUE_FRAGMENT, title: normalizeChapterTitle(title) || rawText }
  }
  const normalized = normalizeChapterTitle(title)
  if (!normalized) return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.EMPTY, title: '' }
  if (TITLE_MOJIBAKE_PATTERN.test(normalized)) return { status: 'fail', reason: 'mojibake', title: normalized }
  if (isDefaultChapterTitle(normalized, context.chapterNum)) return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.DEFAULT_TITLE, title: normalized }
  const illegalFragmentReason = detectIllegalChapterTitleFragment(normalized)
  if (illegalFragmentReason) return { status: 'fail', reason: illegalFragmentReason, title: normalized }
  const counts = countChapterTitleChars(normalized)
  if (counts.semantic === 0) return { status: 'fail', reason: 'symbol_fragment', title: normalized }
  const serialTitle = isSerialChapterTitle(normalized)
  if (!serialTitle && counts.punctuationOrSymbol >= counts.semantic && counts.punctuationOrSymbol > 0) return { status: 'fail', reason: 'punctuation_dominant', title: normalized }
  if (!serialTitle && /[，。！？；：、,.!?;:]/.test(normalized)) return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.PUNCTUATION, title: normalized }
  if (isCompleteSentenceLikeTitle(normalized)) return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.SENTENCE_LIKE, title: normalized }
  if (isLikelyOralFragmentTitle(normalized)) return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.ORAL_FRAGMENT, title: normalized }
  const length = titleCharLength(normalized)
  if (length > 8) return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.TOO_LONG, title: normalized }
  if (isChapterTitleDuplicate(normalized, context)) return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.DUPLICATE, title: normalized }
  if (isWeakDialogueQuestionTitle(normalized)) return { status: 'warning', reason: 'weak_dialogue_question', title: normalized }
  if (isWeakDirectionOrActionFragmentTitle(normalized)) return { status: 'warning', reason: 'weak_direction_or_action_fragment', title: normalized }
  if (ORAL_STATE_FRAGMENT_TITLES.has(normalized)) return { status: 'warning', reason: 'oral_state_fragment', title: normalized }
  if (length === 1) return { status: 'warning', reason: 'single_character_weak_title', title: normalized }
  if (isAbstractStateLikeTitle(normalized)) return { status: 'warning', reason: 'abstract_state_like_title', title: normalized }
  if (!isConcreteCatalogLabelTitle(normalized, context)) return { status: 'fail', reason: TITLE_POLICY_FAIL_REASONS.NOT_CONCRETE, title: normalized }
  if (length > 6) return { status: 'warning', reason: 'natural_long_title', title: normalized }
  return { status: 'pass', reason: 'simple_catalog_title', title: normalized }
}

export function getChapterTitleQuality(title, context = {}) {
  const policy = evaluateChapterTitlePolicy(title, context)
  return {
    titleValid: policy.status !== 'fail',
    titleInvalidReason: policy.status === 'fail' ? policy.reason : '',
    titleSource: context.titleSource || 'unknown',
    fallbackUsed: Boolean(context.fallbackUsed),
    normalizedTitle: policy.title,
    status: policy.status,
    reason: policy.reason
  }
}
