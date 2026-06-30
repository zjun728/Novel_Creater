import { evaluateChapterTitlePolicy, inferChapterTitleType, normalizeChapterTitleKey } from './policy.js'

const MATERIAL_PATTERNS = [
  { type: 'item', pattern: /[\u4e00-\u9fa5一二三四五六七八九十百千万零〇两0-9]{1,8}(?:密信|信件|账册|账本|纸条|仓钥|钥匙|残卷|残页|凭证|令牌|玉牌|玉简|铜盘|铜扣|棺材|灵髓|信物|短讯|断钥|符宝|法器|丹药|灵药|卡|令|符|钥|信|书|页|扣)/g },
  { type: 'place', pattern: /[\u4e00-\u9fa5一二三四五六七八九十百千万零〇两0-9]{1,8}(?:粮栈|客栈|地窖|染坊|密室|矿道|档案室|火灶房|山庄|山门|后院|祠堂|地牢|钟楼|街|仓|库|栈|房|室|堂|殿|院|庄|寺|阁|楼|城|寨|谷|门|道)/g },
  { type: 'organization', pattern: /[\u4e00-\u9fa5一二三四五六七八九十百千万零〇两0-9]{1,8}(?:宝行|商行|商盟|商会|寺|庙|宗|门派|帮|会|阁|楼|院|书院|镖局|司|盟)/g },
  { type: 'skill', pattern: /[\u4e00-\u9fa5一二三四五六七八九十百千万零〇两0-9]{1,8}(?:长生功|功法|心法|身法|剑法|刀法|秘术|灵术|炼灵|术|诀|法)/g },
  { type: 'weapon', pattern: /[\u4e00-\u9fa5一二三四五六七八九十百千万零〇两0-9]{1,8}(?:剑|刀|枪|弓|戟)/g },
  { type: 'event', pattern: /[\u4e00-\u9fa5一二三四五六七八九十百千万零〇两0-9]{1,6}(?:换账|换债|取信|取图|审问|争夺|交易|破局|追击|伏击|救人|烧信|验信|开门|关门|放信号)/g },
  { type: 'person', pattern: /[\u4e00-\u9fa5]{1,4}(?:和尚|道士|师兄|师姐|师妹|师弟|掌柜|先生|夫人|小姐|长老|真人|婆婆|姑娘)/g }
]
const EXPLICIT_SHORT_ITEM_PATTERN = /(?:黑卡|白卡|金卡|银卡|铜卡|木牌|木盒|铁盒|账本|账册|凭证|钥匙|断钥|密信|纸条|残页|令牌|玉牌|玉简|铜盘|铜扣|信物|符宝|法器|丹药|灵药)/g
const EXPLICIT_EVENT_PATTERN = /(?:交易|中毒|返回|选择|聚集|赌约|破禁|出手|突变|恶斗|挑战|拔毒|试毒|谈判|火起|雷灭|对策|遇敌)/g
const CULTIVATION_LEVEL_PATTERN = /(?:炼气|练气|筑基|结丹|金丹|元婴|化神|炼虚|合体|大乘|渡劫|炼灵)(?:[一二三四五六七八九十百千万零〇两0-9]+(?:层|重|品|阶|等|转)|初期|中期|后期|圆满|大圆满|初成|小成|大成)?/g
const POWER_LEVEL_PATTERN = /(?:(?:法力|灵力|真元|灵压|灵息)[一二三四五六七八九十百千万零〇两0-9]+(?:层|重|品|阶|等|转)|[一二三四五六七八九十百千万零〇两0-9]+(?:层|重|品|阶|等|转)(?:法力|灵力|真元|灵压|灵息))/g

function stringifyContextValue(value) {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(stringifyContextValue).filter(Boolean).join('\n')
  if (typeof value === 'object') return Object.values(value).map(stringifyContextValue).filter(Boolean).join('\n')
  return String(value)
}

function collectSourceText(context = {}) {
  return [
    context.chapterGoal,
    context.beatPlan,
    context.storyBlockStage,
    context.blockStageSnapshot,
    context.stageSnapshot,
    context.narrativeReadability?.irreversibleChange,
    context.narrativeProgression?.irreversibleChange,
    context.irreversibleChange,
    context.content
  ].map(stringifyContextValue).filter(Boolean).join('\n')
}

function cleanMaterialTitle(value = '') {
  let text = String(value || '')
    .replace(/^[，。！？；：、,.!?;:\s]+/, '')
    .replace(/[，。！？；：、,.!?;:\s]+$/, '')
    .trim()
  for (let i = 0; i < 4; i += 1) {
    const next = text
      .replace(/^[\u4e00-\u9fa5]{1,6}(?:进了|进入|走进|绕进|转进|钻进|来到|回到|抵达|赶到|到|交出|拿出|递出|递给|取出|翻出|掏出|交给|留下)/, '')
      .replace(/^(?:有人|那人|此人|他|她|他们|她们|伙计|掌柜)(?:在|从|向|到)/, '')
      .replace(/^[\u4e00-\u9fa5]{1,4}(?:约在|约到|约去)/, '')
      .replace(/^(?:只剩|只把|把|将|被|在|从|向|和|与|对|到|没有|已经|刚|才知道|才明白|必须判断是否当场|是否当场|当场|先|又|再|查看|打开|发现|找到|拿到|取得|带走|压住|压在|验完|验过|验证|验明|一个|一只|一枚|一把|一封|一页|内含|含有)/, '')
      .trim()
    if (next === text) break
    text = next
  }
  return text.replace(/(?:压在|放在|挂在|留在|指向).+$/, '').trim()
}

function pushMaterial(out, candidate, type, source, sourceIndex) {
  const title = cleanMaterialTitle(candidate)
  if (!title) return
  if (/(?:没有|没|不|未)?(?:进|出)门$/u.test(title)) return
  const connectorParts = title.split(/和(?!尚)|与|或|、/u).map(cleanMaterialTitle).filter(Boolean)
  if (connectorParts.length > 1) {
    for (const part of connectorParts) {
      pushMaterial(out, part, type, source, sourceIndex)
    }
    return
  }
  const inferredType = type || inferChapterTitleType(title)
  const policy = evaluateChapterTitlePolicy(title, { materials: [{ title, type: inferredType }] })
  if (policy.status === 'fail') return
  const key = normalizeChapterTitleKey(policy.title)
  if (!key || out.some(item => normalizeChapterTitleKey(item.title) === key)) return
  out.push({
    title: policy.title,
    type: inferredType || 'material',
    reason: 'positive_chapter_material',
    evidence: source.slice(Math.max(0, sourceIndex - 24), Math.min(source.length, sourceIndex + title.length + 36)).trim(),
    sourceIndex
  })
}

export function collectChapterTitleMaterials(context = {}) {
  const source = collectSourceText(context)
  if (!source.trim()) return []
  const out = []

  for (const { type, pattern } of MATERIAL_PATTERNS) {
    for (const match of source.matchAll(pattern)) {
      pushMaterial(out, match[0], type, source, match.index || 0)
    }
  }

  for (const match of source.matchAll(EXPLICIT_SHORT_ITEM_PATTERN)) {
    pushMaterial(out, match[0], 'item', source, match.index || 0)
  }

  for (const match of source.matchAll(EXPLICIT_EVENT_PATTERN)) {
    pushMaterial(out, match[0], 'event', source, match.index || 0)
  }

  for (const match of source.matchAll(CULTIVATION_LEVEL_PATTERN)) {
    pushMaterial(out, match[0], 'result', source, match.index || 0)
  }

  for (const match of source.matchAll(POWER_LEVEL_PATTERN)) {
    pushMaterial(out, match[0], 'result', source, match.index || 0)
  }

  const sorted = out.sort((left, right) => {
    const typePriority = new Map([
      ['place', 10],
      ['item', 9],
      ['organization', 7],
      ['event', 6],
      ['person', 5],
      ['skill', 5],
      ['weapon', 5],
      ['result', 4]
    ])
    return (left.sourceIndex - right.sourceIndex) ||
      ((typePriority.get(right.type) || 0) - (typePriority.get(left.type) || 0)) ||
      (right.title.length - left.title.length)
  })
  return sorted.filter(candidate => !sorted.some(other =>
    other.title !== candidate.title &&
    (other.type === candidate.type ||
      (candidate.type === 'place' && other.type === 'item' && candidate.title.length <= 3)) &&
    other.title.includes(candidate.title) &&
    other.title.length > candidate.title.length &&
    Math.abs((other.sourceIndex || 0) - (candidate.sourceIndex || 0)) <= Math.max(other.title.length, candidate.title.length) + 4
  ))
}
