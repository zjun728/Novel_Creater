import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { normalizeStoryHumanityReview } from './story_humanity_review_utils.mjs'

const QA_DIR = path.join(process.cwd(), 'tmp', 'realistic-flow-qa')
const BASELINE_PATH = path.join(QA_DIR, 'latest-story-humanity-review.json')
const API_BASE = process.env.API_BASE || 'http://127.0.0.1:8000/api'
const RANGE_START = Math.max(1, Number(process.env.STORY_HUMANITY_RANGE_START || 21) || 21)
const RANGE_END = Math.max(RANGE_START, Number(process.env.STORY_HUMANITY_RANGE_END || 25) || 25)
const OUT_STEM = process.env.STORY_HUMANITY_OUT_STEM || `latest-story-humanity-rerun-${RANGE_START}-${RANGE_END}`
const DEFAULT_RERUN_LIVE_PATH = path.join(QA_DIR, `latest-longform-browser-live-report-${RANGE_START}-${RANGE_END}.json`)
const RERUN_LIVE_PATH = process.env.STORY_HUMANITY_RERUN_SOURCE || DEFAULT_RERUN_LIVE_PATH
const OUT_JSON = path.join(QA_DIR, `${OUT_STEM}.json`)
const OUT_MD = path.join(QA_DIR, `${OUT_STEM}.md`)
const RERUN_RANGE = [RANGE_START, RANGE_END]
const PREVIOUS_STORY_HUMANITY_REPORT = process.env.PREVIOUS_STORY_HUMANITY_REPORT ||
  path.join(QA_DIR, `latest-story-humanity-rerun-${Math.max(1, RANGE_START - 5)}-${RANGE_START - 1}.json`)

const HUMANITY_KEYS = [
  'protagonistImmediateWant',
  'emotionalAnchor',
  'misbeliefOrFear',
  'relationshipDelta',
  'stageAnswerForReader'
]

const headingLabels = {
  protagonistImmediateWant: '主角即时欲望',
  emotionalAnchor: '情绪锚点',
  misbeliefOrFear: '误解或恐惧',
  relationshipDelta: '关系轻微变化',
  stageAnswerForReader: '给读者的阶段答案'
}

const termGroups = {
  chase: ['追', '跑', '逃', '躲', '封锁', '搜', '埋伏', '潜入', '暗道', '翻墙', '撤离', '地道', '追兵'],
  chaseContinuous: ['搜查', '撤离', '潜入', '地道', '追兵'],
  clue: ['账', '信', '钥匙', '印', '线索', '密栈', '档案', '路线图', '账本'],
  relationship: ['小九', '老陈', '老太太', '灰衣人', '徐主簿', '徐正清', '乙十七', '信任', '隐瞒', '误会', '亏欠', '交易'],
  explanation: ['这意味着', '也就是说', '应该是', '必须', '说明', '意味着', '换句话说', '规则', '原因'],
  humanity: ['嘴硬', '沉默', '打岔', '没事', '递', '吃', '伤口', '疼', '害怕', '不敢', '瞒', '误会', '不信'],
  stageAnswer: ['确认', '证实', '原来', '不是', '答案', '账本指向', '路线图', '天池', '第三密栈', '水渠'],
  restScene: ['包扎', '伤口', '吃饭', '冷饭', '喝水', '躲雨', '休整', '睡', '喘口气', '分赃'],
  relationshipScene: ['信任', '隐瞒', '误会', '亏欠', '交易', '救助', '背叛', '合作', '吵', '沉默', '递给', '没追问'],
  choiceScene: ['选择', '决定', '拒绝', '答应', '承认', '隐瞒', '交出', '留下', '离开', '相信', '不信'],
  costScene: ['代价', '失去', '记忆', '寿命', '黑纹', '疼', '暴露', '裂痕', '损毁'],
  relationshipConfrontation: ['对峙', '质问', '争执', '谈条件', '谈判', '摊牌', '信任', '隐瞒', '误会', '不信', '重新谈'],
  consequenceScene: ['后果', '代价', '失去', '记忆', '寿命', '黑纹', '裂开', '伤口', '包扎', '恶化', '改变计划'],
  activeSetup: ['主动设局', '设局', '布局', '安排', '假账页', '放风', '放话', '引', '等他', '诱', '反向'],
  organizationRules: ['巡天司', '商盟', '主簿', '衙门', '规矩', '令牌', '档案', '外档', '章程', '规则'],
  investigation: ['核验', '验证', '查', '确认', '证实', '翻账', '读账', '比对', '线索', '账页', '密信', '钥匙'],
  clueHandoff: ['下一地点', '下个地点', '新地址', '新入口', '转去', '赶往', '立刻去', '决定去', '指向', '带着线索', '拿到线索'],
  ruleDiscoveryByAction: ['试着', '尝试', '触发', '反噬', '出事', '付代价', '旁人反应', '看见后', '规则', '后果'],
  lowPressureRecovery: ['低声', '慢慢', '歇', '休息', '包扎', '喝水', '喘口气', '靠墙', '坐下'],
  organizationObservation: ['摊贩', '伙计', '船工', '码头规矩', '商盟规矩', '巡天司章程', '登记', '排队', '验牌']
}

const inferencePatterns = {
  protagonistImmediateWant: /只想|眼下想|最想|先活|必须先|得先|想先|打算/,
  emotionalAnchor: /害怕|嘴硬|不愿承认|父亲|亏欠|失去|不信|强撑|心里|沉默/,
  misbeliefOrFear: /误会|怕|害怕|不敢|嘴硬|隐瞒|藏|装作|没事/,
  relationshipDelta: /关系|信任|误会|隐瞒|交易|亏欠|救助|背叛|条件|不再|要求|拿走/,
  stageAnswerForReader: /确认|证实|原来|不是|答案|指向|入口|去向|水渠|天池|密栈/
}

const weakTitleExact = new Set([
  '往左',
  '后面走',
  '哪走',
  '往右',
  '向前',
  '后退',
  '快走',
  '走了',
  '能走',
  '进去',
  '出来',
  '有水',
  '这沟通哪儿',
  '那么明显',
  '加钱也没用',
  '这边有血迹',
  '前头也有',
  '收啥啊',
  '走门'
])

function readJson(filePath, fallback = null) {
  if (!fs.existsSync(filePath)) return fallback
  return JSON.parse(fs.readFileSync(filePath, 'utf8'))
}

function parseJsonMaybe(value, fallback = null) {
  if (!value) return fallback
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch {
    return fallback
  }
}

async function api(pathname) {
  const response = await fetch(`${API_BASE}${pathname}`)
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`)
  return response.json()
}

function countTerms(text, terms) {
  const source = String(text || '')
  return terms.reduce((sum, term) => sum + source.split(term).length - 1, 0)
}

function cleanValue(value) {
  return String(value ?? '').replace(/\s+/g, ' ').trim()
}

function cleanList(value) {
  if (Array.isArray(value)) return value.map(cleanValue).filter(Boolean)
  const text = cleanValue(value)
  return text ? [text] : []
}

function classifyDominantStoryFunction(content = '', counts = {}) {
  const text = String(content || '')
  const scores = {
    chase_escape: (Number(counts.chaseContinuous || 0) * 4) + countTerms(text, ['追兵', '搜查', '撤离', '逃', '躲藏', '潜入', '地道', '封锁', '翻墙']) * 2,
    relationship_confrontation: countTerms(text, termGroups.relationshipConfrontation) * 3,
    consequence_scene: countTerms(text, termGroups.consequenceScene) * 3,
    active_setup: countTerms(text, termGroups.activeSetup) * 3,
    recovery_rest: countTerms(text, termGroups.restScene) * 3,
    organization_rules: countTerms(text, termGroups.organizationRules) * 2,
    investigation: countTerms(text, termGroups.investigation) * 2
  }
  if (scores.relationship_confrontation >= 6 && scores.relationship_confrontation >= scores.chase_escape) return 'relationship_confrontation'
  if (scores.consequence_scene >= 6 && scores.consequence_scene >= scores.chase_escape) return 'consequence_scene'
  if (scores.active_setup >= 6 && scores.active_setup >= scores.chase_escape) return 'active_setup'
  if (scores.recovery_rest >= 6 && scores.recovery_rest >= scores.chase_escape) return 'recovery_rest'
  if (scores.chase_escape >= 8) return 'chase_escape'
  const ordered = Object.entries(scores).sort((left, right) => right[1] - left[1])
  const [name, score] = ordered[0] || ['investigation', 0]
  return score > 0 ? name : 'investigation'
}

export function classifyUnderlyingProgressionPattern(content = '', counts = null) {
  const text = String(content || '')
  const localCounts = counts || Object.fromEntries(
    Object.entries(termGroups).map(([key, terms]) => [key, countTerms(text, terms)])
  )
  const pursuitScore = (Number(localCounts.chaseContinuous || 0) * 4) +
    countTerms(text, ['追兵', '搜查', '撤离', '封锁', '包抄', '追捕', '逃', '躲', '潜入', '地道']) * 2
  const clueHandoffScore = countTerms(text, termGroups.clueHandoff) * 3 +
    (Number(localCounts.clue || 0) >= 4 && /(?:立刻|马上|转身|赶往|去|往|下一|下个)/.test(text) ? 5 : 0)
  const scores = {
    active_setup: countTerms(text, termGroups.activeSetup) * 3,
    relationship_negotiation: countTerms(text, ['谈条件', '谈判', '交换', '对峙', '质问', '摊牌', '试探', '不肯交', '打断', '逼他说']) * 3,
    consequence_processing: countTerms(text, termGroups.consequenceScene) * 2 + countTerms(text, ['改变计划', '承受', '撑住', '处理伤口', '后果']) * 3,
    rule_discovery_by_action: countTerms(text, termGroups.ruleDiscoveryByAction) * 3,
    low_pressure_recovery: countTerms(text, termGroups.lowPressureRecovery) * 3,
    organization_observation: countTerms(text, termGroups.organizationObservation) * 3 + countTerms(text, termGroups.organizationRules),
    clue_handoff: clueHandoffScore,
    pursuit_pressure: pursuitScore
  }
  if (scores.pursuit_pressure >= 10 && scores.pursuit_pressure >= Math.max(scores.active_setup, scores.relationship_negotiation, scores.rule_discovery_by_action)) {
    return 'pursuit_pressure'
  }
  if (scores.clue_handoff >= 8 && scores.clue_handoff >= Math.max(scores.active_setup, scores.relationship_negotiation, scores.rule_discovery_by_action)) {
    return 'clue_handoff'
  }
  for (const key of [
    'active_setup',
    'relationship_negotiation',
    'rule_discovery_by_action',
    'organization_observation',
    'low_pressure_recovery',
    'consequence_processing'
  ]) {
    if (scores[key] >= 6) return key
  }
  if (scores.pursuit_pressure >= 6) return 'pursuit_pressure'
  if (scores.clue_handoff >= 5) return 'clue_handoff'
  return 'consequence_processing'
}

function versionContent(chapterReport = {}) {
  return (
    chapterReport.flowEvents?.finalize_version_preflight_passed?.versions?.[0]?.content ||
    chapterReport.flowEvents?.finalize_click_started?.versions?.[0]?.content ||
    chapterReport.flowEvents?.draft_generated?.versions?.[0]?.content ||
    ''
  )
}

export function containsBeatPlanToolingLeak(text = '') {
  const source = String(text || '')
  return /第\s*\d+\s*章发生一件读者能复述的事/.test(source) ||
    /读者能复述的事/.test(source) ||
    /人物目标：围绕/.test(source) ||
    /围绕“[^”]+”/.test(source) ||
    /本章关系变化落在/.test(source) ||
    /不能只把配角当线索出口/.test(source) ||
    /下一阶段\s*[：:]\s*stage-[\dx]+/i.test(source) ||
    /主角要完成[\s\S]{0,80}并把结果接到/.test(source) ||
    /\bstage-(?:\d+|x)\b/i.test(source)
}

function collectBeatPlanToolingLeakSamples(text = '') {
  const source = String(text || '')
  const patterns = [
    /第\s*\d+\s*章发生一件读者能复述的事[^。\n]*/g,
    /读者能复述的事[^。\n]*/g,
    /人物目标：围绕[^。\n]*/g,
    /围绕“[^”]+”/g,
    /本章关系变化落在[^。\n]*/g,
    /不能只把配角当线索出口/g,
    /下一阶段\s*[：:]\s*stage-[\dx]+/gi,
    /主角要完成[\s\S]{0,80}并把结果接到[^。\n]*/g,
    /\bstage-(?:\d+|x)(?:[（(][^）)\n]+[）)])?/gi
  ]
  const samples = []
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      const sample = cleanValue(match[0]).slice(0, 120)
      if (sample && !samples.includes(sample)) samples.push(sample)
    }
  }
  return samples.slice(0, 5)
}

export function extractBeatPlanFields(beat = null) {
  const content = typeof beat?.content === 'string' ? beat.content : ''
  if (beat?.content && typeof beat.content === 'object') return beat.content
  if (!content.trim()) return {}
  try {
    const parsed = JSON.parse(content)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : { raw: content }
  } catch {
    const out = { raw: content }
    for (const key of HUMANITY_KEYS) {
      const match = content.match(new RegExp(`${key}\\s*[:：]\\s*([^\\n]+)`))
      if (match) out[key] = cleanValue(match[1])
      const heading = headingLabels[key]
      const headingMatch = heading
        ? content.match(new RegExp(`###\\s*${heading}\\s*\\n([\\s\\S]*?)(?=\\n###\\s|$)`))
        : null
      if (!out[key] && headingMatch) out[key] = cleanValue(headingMatch[1])
    }
    return out
  }
}

export function normalizeMysqlBeatPlanRow(row = {}) {
  if (!row || typeof row !== 'object') return null
  const chapterNum = Number(row.chapter_num ?? row.chapterNum ?? 0)
  if (!chapterNum) return null
  return {
    id: cleanValue(row.id),
    projectId: cleanValue(row.project_id ?? row.projectId),
    chapterNum,
    storyBlockId: cleanValue(row.story_block_id ?? row.storyBlockId),
    blockStageId: cleanValue(row.block_stage_id ?? row.blockStageId),
    blockStageSnapshot: parseJsonMaybe(row.block_stage_snapshot ?? row.blockStageSnapshot, null),
    beatPlanSource: cleanValue(row.beat_plan_source ?? row.beatPlanSource),
    derivedFromStoryBlock: Boolean(Number(row.derived_from_story_block ?? row.derivedFromStoryBlock ?? 0)),
    derivedReason: cleanValue(row.derived_reason ?? row.derivedReason),
    content: String(row.content || '')
  }
}

function loadBeatPlansFromMysql(projectId, range = RERUN_RANGE) {
  if (!projectId) return new Map()
  const script = `
import asyncio, json, sys
sys.path.insert(0, 'backend')
from database import fetchall, close_pool

async def main():
    project_id = sys.argv[1]
    start = int(sys.argv[2])
    end = int(sys.argv[3])
    rows = await fetchall(
        "SELECT * FROM chapter_beat_plans WHERE project_id=%s AND chapter_num BETWEEN %s AND %s ORDER BY chapter_num",
        (project_id, start, end),
    )
    print(json.dumps(rows, ensure_ascii=False, default=str))
    await close_pool()

asyncio.run(main())
`
  try {
    const output = execFileSync('python', ['-c', script, projectId, String(range[0]), String(range[1])], {
      cwd: process.cwd(),
      encoding: 'utf8',
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      windowsHide: true,
      timeout: 30000
    })
    return new Map((JSON.parse(output || '[]') || [])
      .map(normalizeMysqlBeatPlanRow)
      .filter(Boolean)
      .map(item => [Number(item.chapterNum), item]))
  } catch {
    return new Map()
  }
}

function isDerivedBeatPlan(beat = null, reportEntry = {}) {
  const source = cleanValue(beat?.beatPlanSource || reportEntry.beatPlanSource || '')
  return source === 'derived_from_story_block' ||
    source === 'local_safety_requires_review' ||
    Boolean(beat?.derivedFromStoryBlock || reportEntry.derivedFromStoryBlock)
}

export function analyzeHumanityFieldEvidence({ beatPlanFields = {}, beat = null, reportEntry = {}, content = '' } = {}) {
  const beatRaw = cleanValue(beatPlanFields.raw || beat?.content || '')
  const textForInference = `${beatRaw}\n${content}`
  const derived = isDerivedBeatPlan(beat, reportEntry)
  const evidence = {}
  const persistedHumanityFields = []
  const derivedHumanityFields = []
  const inferredHumanitySignals = []
  const missingHumanityFields = []

  for (const key of HUMANITY_KEYS) {
    const value = cleanValue(beatPlanFields[key])
    if (value) {
      const status = derived ? 'derived' : 'persisted'
      evidence[key] = {
        status,
        source: derived ? 'derived' : (cleanValue(beat?.beatPlanSource || reportEntry.beatPlanSource) || 'ai_or_saved_beat_plan'),
        value
      }
      if (derived) derivedHumanityFields.push(key)
      else persistedHumanityFields.push(key)
      continue
    }

    if (inferencePatterns[key]?.test(textForInference)) {
      evidence[key] = {
        status: 'inferred',
        source: beatRaw ? 'beat_plan_or_chapter_text_signal' : 'chapter_text_signal',
        value: ''
      }
      inferredHumanitySignals.push(key)
      continue
    }

    evidence[key] = {
      status: 'missing',
      source: '',
      value: ''
    }
    missingHumanityFields.push(key)
  }

  return {
    humanityFieldEvidence: evidence,
    persistedHumanityFields,
    derivedHumanityFields,
    inferredHumanitySignals,
    missingHumanityFields
  }
}

function isWeakChapterTitle(title = '') {
  const clean = cleanValue(title).replace(/^《|》$/g, '')
  if (!clean) return true
  if (weakTitleExact.has(clean)) return true
  if (Array.from(clean).length === 1) return true
  if (/^[\u4e00-\u9fa5A-Za-z0-9·]{1,5}(?:呢|去哪儿|在哪儿|怎么办|干什么)$/.test(clean)) return true
  if (/^(?:这边|那边|这儿|那儿|这里|那里|前头|后头|前面|后面)(?:也)?有[\u4e00-\u9fa5]{0,4}$/u.test(clean)) return true
  if (/^(?:收|找|问|看|拿|要|给|交|查)[\u4e00-\u9fa5]{0,2}(?:啥|什么)(?:啊|呢|吗|吧)?$/u.test(clean)) return true
  return clean.length <= 5 && /走|跑|躲|看|问|答|去|来|左|右|前|后|哪|开|拿|没用|明显|沟通|有水/.test(clean)
}

function extractShortDraftDiagnostics(reportEntry = {}) {
  const events = reportEntry.flowEvents || {}
  const diagnostic = events.below_hard_min_auto_regenerate_succeeded ||
    events.below_hard_min_expand_short_draft_accepted ||
    events.below_hard_min_auto_regenerate_failed ||
    events.below_hard_min_auto_regenerate_started ||
    events.below_hard_min_expand_short_draft_rejected ||
    events.below_hard_min_expand_short_draft_started ||
    null
  if (!diagnostic) return {}
  return {
    shortDraftStrategy: cleanValue(diagnostic.shortDraftStrategy || ''),
    originalWordCount: Number(diagnostic.originalWordCount || 0) || null,
    expandedWordCount: Number(diagnostic.expandedWordCount || 0) || null,
    finalCandidateWordCount: Number(diagnostic.finalCandidateWordCount || diagnostic.newWordCount || diagnostic.wordCount || 0) || null,
    expansionAccepted: diagnostic.expansionAccepted === true,
    expansionRejectedReason: cleanValue(diagnostic.expansionRejectedReason || ''),
    factDriftCheck: diagnostic.factDriftCheck || null,
    endingPreserved: diagnostic.endingPreserved || null,
    regenerateAttempted: diagnostic.regenerateAttempted === true,
    regenerateSucceeded: diagnostic.regenerateSucceeded === true
  }
}

async function loadChapterMaterial(projectId, liveReport, chapterNum, mysqlBeatPlans = new Map()) {
  const reportEntry = (liveReport.chapterReports || []).find(item => Number(item.chapterNum) === chapterNum) || {}
  let chapter = null
  let beat = null
  let versions = []
  if (projectId) {
    chapter = ((await api(`/projects/${projectId}/chapters`).catch(() => [])) || [])
      .find(item => Number(item.chapterNum) === chapterNum) || null
    beat = await api(`/projects/${projectId}/chapter-beat-plan/${chapterNum}`).catch(() => null)
    if (chapter?.id) versions = await api(`/projects/${projectId}/chapters/${chapter.id}/versions`).catch(() => [])
  }
  if (!beat?.content && mysqlBeatPlans.has(Number(chapterNum))) {
    beat = mysqlBeatPlans.get(Number(chapterNum))
  }
  const finalVersion = Array.isArray(versions)
    ? versions.find(version => version.id === chapter?.finalVersionId || version.versionType === 'final') || versions.at(-1)
    : null
  const content = String(finalVersion?.content || versionContent(reportEntry) || '')
  return {
    reportEntry,
    chapter,
    beat,
    content,
    beatPlanFields: extractBeatPlanFields(beat)
  }
}

export function analyzeChapter({ chapterNum, reportEntry = {}, chapter = null, beat = null, beatPlanFields = {}, content = '' }) {
  const counts = Object.fromEntries(
    Object.entries(termGroups).map(([key, terms]) => [key, countTerms(content, terms)])
  )
  const fieldEvidence = analyzeHumanityFieldEvidence({ beatPlanFields, beat, reportEntry, content })
  const beatPlanSource = cleanValue(beat?.beatPlanSource || reportEntry.beatPlanSource || '')
  const derivedFromStoryBlock = Boolean(beat?.derivedFromStoryBlock || reportEntry.derivedFromStoryBlock || beatPlanSource === 'derived_from_story_block')
  const hasEmotionalAnchor = ['emotionalAnchor', 'misbeliefOrFear', 'protagonistImmediateWant']
    .some(key => fieldEvidence.humanityFieldEvidence[key]?.status !== 'missing')
  const hasRelationshipDelta = fieldEvidence.humanityFieldEvidence.relationshipDelta?.status !== 'missing'
  const hasStageAnswer = fieldEvidence.humanityFieldEvidence.stageAnswerForReader?.status !== 'missing' ||
    countTerms(content, termGroups.stageAnswer) > 0
  const hasNonFunctionalCompanionSignal = Boolean(
    countTerms(content, ['小九', '老陈', '老太太', '灰衣人', '乙十七']) > 0 &&
    countTerms(content, ['嘴硬', '沉默', '打岔', '吃', '递', '伤口', '笑', '骂', '停了一下', '没事']) > 0
  )
  const textureSignals = {
    relationshipField: ['persisted', 'derived'].includes(fieldEvidence.humanityFieldEvidence.relationshipDelta?.status),
    restScene: counts.restScene > 0,
    relationshipScene: counts.relationshipScene > 0,
    choiceScene: counts.choiceScene > 0,
    costScene: counts.costScene > 0
  }
  const hasRelationshipRestOrChoiceScene = Boolean(
    textureSignals.relationshipField &&
    (textureSignals.restScene || textureSignals.relationshipScene || textureSignals.choiceScene || textureSignals.costScene)
  )
  const loopSignal = counts.chase >= 18 && counts.clue >= 18
    ? 'high_chase_clue_loop'
    : counts.chase >= 10 || counts.chaseContinuous > 0
      ? 'medium_chase_or_escape_loop'
      : 'not_continuous_chase_loop'
  const title = chapter?.title || reportEntry.title || ''
  const finalized = chapter?.status === 'final' || reportEntry.finalized === true
  const relationshipStatus = fieldEvidence.humanityFieldEvidence.relationshipDelta?.status || 'missing'
  const stageContinuationDepth = Number(reportEntry.stageContinuationDepth ?? reportEntry.stage_continuation_depth ?? 0) || 0
  const dominantStoryFunction = cleanValue(reportEntry.dominantStoryFunction || reportEntry.dominant_story_function || '') ||
    classifyDominantStoryFunction(content, counts)
  const underlyingProgressionPattern = cleanValue(reportEntry.underlyingProgressionPattern || reportEntry.underlying_progression_pattern || '') ||
    classifyUnderlyingProgressionPattern(content, counts)
  const shortDraftDiagnostics = extractShortDraftDiagnostics(reportEntry)
  const writerContextDiagnostics = reportEntry.writerContextDiagnostics || {}
  const sampleCardInjected = reportEntry.sampleCardInjected ?? writerContextDiagnostics.sampleCardInjected ?? false
  const sampleCardId = cleanValue(reportEntry.sampleCardId || writerContextDiagnostics.sampleCardId || '')
  const sampleCardTitle = cleanValue(reportEntry.sampleCardTitle || writerContextDiagnostics.sampleCardTitle || '')
  const sampleCardType = cleanValue(reportEntry.sampleCardType || writerContextDiagnostics.sampleCardType || '')
  const sampleInjectionReason = cleanValue(reportEntry.sampleInjectionReason || writerContextDiagnostics.sampleInjectionReason || '')
  const microDemoChars = Number(reportEntry.microDemoChars ?? writerContextDiagnostics.microDemoChars ?? 0) || 0
  const sourceFieldsStripped = reportEntry.sourceFieldsStripped ?? writerContextDiagnostics.sourceFieldsStripped ?? true
  const sampleLeakageDetected = reportEntry.sampleLeakageDetected ?? writerContextDiagnostics.sampleLeakageDetected ?? false

  return {
    chapterNum,
    title,
    finalized,
    wordCount: chapter?.wordCount || reportEntry.wordCount || content.length,
    storyBlockId: beat?.storyBlockId || reportEntry.storyBlockId || '',
    blockStageId: beat?.blockStageId || reportEntry.blockStageId || '',
    storyBlockStageContinues: Boolean(reportEntry.storyBlockStageContinues || reportEntry.stageContinues),
    storyBlockStageContinueReason: cleanValue(reportEntry.storyBlockStageContinueReason || reportEntry.stageContinueReason || ''),
    previousStoryBlockStageContinues: reportEntry.previousStoryBlockStageContinues ?? null,
    previousStoryBlockReviewDecision: reportEntry.previousStoryBlockReviewDecision || '',
    storyBlockReviewDecision: reportEntry.storyBlockReviewDecision || '',
    stageContinuationDepth,
    previousOpenStageId: cleanValue(reportEntry.previousOpenStageId || reportEntry.previous_open_stage_id || ''),
    settlementDecision: cleanValue(reportEntry.settlementDecision || reportEntry.settlement_decision || ''),
    settlementEvidence: cleanList(reportEntry.settlementEvidence || reportEntry.settlement_evidence || []),
    equivalentCompletionScope: cleanValue(reportEntry.equivalentCompletionScope || reportEntry.equivalent_completion_scope || ''),
    futureStageTouched: reportEntry.futureStageTouched === true || reportEntry.future_stage_touched === true,
    futureStageEvidence: cleanList(reportEntry.futureStageEvidence || reportEntry.future_stage_evidence || []),
    futureStageOverClosed: reportEntry.futureStageOverClosed === true || reportEntry.future_stage_over_closed === true,
    needsFutureStageReplan: reportEntry.needsFutureStageReplan === true || reportEntry.needs_future_stage_replan === true,
    replanRemainingStages: reportEntry.replanRemainingStages === true || reportEntry.replan_remaining_stages === true,
    whetherStageClosedBeforeNextBeatPlan: reportEntry.whetherStageClosedBeforeNextBeatPlan === true ||
      reportEntry.whether_stage_closed_before_next_beat_plan === true,
    ...shortDraftDiagnostics,
    dominantStoryFunction,
    underlyingProgressionPattern,
    sampleCardInjected: Boolean(sampleCardInjected),
    sampleCardId,
    sampleCardTitle,
    sampleCardType,
    sampleInjectionReason,
    microDemoChars,
    sourceFieldsStripped: Boolean(sourceFieldsStripped),
    sampleLeakageDetected: Boolean(sampleLeakageDetected),
    beatPlanSource,
    derivedFromStoryBlock,
    beatPlanFields,
    humanityFieldEvidence: fieldEvidence.humanityFieldEvidence,
    persistedHumanityFields: fieldEvidence.persistedHumanityFields,
    derivedHumanityFields: fieldEvidence.derivedHumanityFields,
    inferredHumanitySignals: fieldEvidence.inferredHumanitySignals,
    missingHumanityFields: fieldEvidence.missingHumanityFields,
    relationshipChangeSource: relationshipStatus,
    templateBeatPlanWording: containsBeatPlanToolingLeak(beat?.content || beatPlanFields.raw || ''),
    templateBeatPlanSamples: collectBeatPlanToolingLeakSamples(beat?.content || beatPlanFields.raw || ''),
    weakTitle: finalized ? isWeakChapterTitle(title) : false,
    indicators: {
      hasEmotionalAnchor,
      hasRelationshipDelta,
      hasStageAnswer,
      hasNonFunctionalCompanionSignal,
      hasRelationshipRestOrChoiceScene,
      textureSignals,
      loopSignal
    },
    counts,
    excerpts: {
      beatPlanEmotionalAnchor: beatPlanFields.emotionalAnchor || '',
      protagonistImmediateWant: beatPlanFields.protagonistImmediateWant || '',
      misbeliefOrFear: beatPlanFields.misbeliefOrFear || '',
      relationshipDelta: beatPlanFields.relationshipDelta || '',
      stageAnswerForReader: beatPlanFields.stageAnswerForReader || ''
    }
  }
}

export function classifyChaseLoop(chapters = []) {
  const loopChapters = chapters.filter(item => item.indicators?.loopSignal !== 'not_continuous_chase_loop')
  const continuousChapters = chapters.filter(item => Number(item.counts?.chaseContinuous || 0) > 0)
  const pursuitUnderlyingChapters = chapters.filter(item =>
    ['pursuit_pressure', 'clue_handoff'].includes(item.underlyingProgressionPattern)
  )
  const dominantChapters = chapters.filter(item =>
    Number(item.counts?.chase || 0) >= 14 &&
    (Number(item.counts?.clue || 0) >= 8 || Number(item.counts?.chaseContinuous || 0) > 0)
  )
  let legacyStatus = 'chaseLoopResolved'
  if (
    loopChapters.length >= Math.max(4, Math.ceil(chapters.length * 0.8)) ||
    dominantChapters.length >= 3 ||
    pursuitUnderlyingChapters.length >= Math.max(3, Math.ceil(chapters.length * 0.6))
  ) {
    legacyStatus = 'chaseLoopStillDominant'
  } else if (loopChapters.length >= 2 || continuousChapters.length >= 2 || pursuitUnderlyingChapters.length >= 2) {
    legacyStatus = 'chaseLoopReduced'
  }
  if (continuousChapters.length >= 3 && legacyStatus === 'chaseLoopResolved') legacyStatus = 'chaseLoopReduced'
  let currentStreak = 0
  let maxConsecutiveLoopChapters = 0
  for (const chapter of chapters) {
    if (chapter.indicators?.loopSignal !== 'not_continuous_chase_loop') {
      currentStreak += 1
      maxConsecutiveLoopChapters = Math.max(maxConsecutiveLoopChapters, currentStreak)
    } else {
      currentStreak = 0
    }
  }
  if (maxConsecutiveLoopChapters >= 3 && legacyStatus === 'chaseLoopResolved') legacyStatus = 'chaseLoopReduced'
  const insufficientSampleForResolved = chapters.length < 3
  const status = {
    chaseLoopResolved: 'resolved',
    chaseLoopReduced: 'reduced',
    chaseLoopStillDominant: 'still_dominant'
  }[legacyStatus]
  const normalizedStatus = insufficientSampleForResolved ? 'insufficient_sample' : status
  const verdicts = {
    resolved: '追逃循环基本解除',
    reduced: '追逃仍多，但相对基线已有切换',
    still_dominant: '追逃/搜查/撤离仍占主导',
    insufficient_sample: '样本不足 3 章，只记录本章主导功能，不判定追逃循环改善'
  }
  return {
    status: normalizedStatus,
    legacyStatus,
    normalizedStatus,
    rawStatusBeforeSampleGuard: status,
    verdict: verdicts[normalizedStatus],
    loopChapterCount: loopChapters.length,
    continuousChaseChapterCount: continuousChapters.length,
    pursuitUnderlyingPatternCount: pursuitUnderlyingChapters.length,
    dominantChapterCount: dominantChapters.length,
    maxConsecutiveLoopChapters,
    insufficientSampleForResolved,
    consecutiveLoopWarning: maxConsecutiveLoopChapters >= 3,
    consecutiveLoopWarningText: maxConsecutiveLoopChapters >= 3
      ? '连续 3 章以上出现拿线索/追逃/躲藏/解读/转地点式循环信号，需标为质量 warning。'
      : '',
    continuousTerms: termGroups.chaseContinuous
  }
}

function summarizeStoryFunctionMix(chapters = []) {
  const counts = Object.fromEntries([
    'chase_escape',
    'investigation',
    'relationship_confrontation',
    'consequence_scene',
    'active_setup',
    'recovery_rest',
    'organization_rules'
  ].map(key => [key, 0]))
  for (const chapter of chapters) {
    const key = chapter.dominantStoryFunction || 'investigation'
    counts[key] = (counts[key] || 0) + 1
  }
  const nonChaseDominantChapters = chapters
    .filter(item => item.dominantStoryFunction !== 'chase_escape')
    .map(item => ({
      chapterNum: item.chapterNum,
      title: item.title,
      dominantStoryFunction: item.dominantStoryFunction
    }))
  return {
    counts,
    chaseEscapeCount: counts.chase_escape || 0,
    nonChaseDominantCount: nonChaseDominantChapters.length,
    nonChaseDominantChapters,
    acceptanceNonChaseThresholdMet: nonChaseDominantChapters.length >= 2,
    verdict: nonChaseDominantChapters.length >= 2
      ? '本段至少两章不是追逃主导'
      : '本段非追逃主导章节不足两章，故事骨架仍偏追逃'
  }
}

function summarizeUnderlyingProgressionPattern(chapters = []) {
  const patternKeys = [
    'pursuit_pressure',
    'clue_handoff',
    'active_setup',
    'relationship_negotiation',
    'consequence_processing',
    'rule_discovery_by_action',
    'low_pressure_recovery',
    'organization_observation'
  ]
  const counts = Object.fromEntries(patternKeys.map(key => [key, 0]))
  for (const chapter of chapters) {
    const key = chapter.underlyingProgressionPattern || 'consequence_processing'
    counts[key] = (counts[key] || 0) + 1
  }
  const nonPursuitPatterns = chapters
    .filter(item => !['pursuit_pressure', 'clue_handoff'].includes(item.underlyingProgressionPattern))
    .map(item => ({
      chapterNum: item.chapterNum,
      title: item.title,
      dominantStoryFunction: item.dominantStoryFunction,
      underlyingProgressionPattern: item.underlyingProgressionPattern
    }))
  const pursuitOrClueHandoffChapters = chapters
    .filter(item => ['pursuit_pressure', 'clue_handoff'].includes(item.underlyingProgressionPattern))
    .map(item => ({
      chapterNum: item.chapterNum,
      title: item.title,
      dominantStoryFunction: item.dominantStoryFunction,
      underlyingProgressionPattern: item.underlyingProgressionPattern
    }))
  return {
    counts,
    pursuitOrClueHandoffCount: pursuitOrClueHandoffChapters.length,
    pursuitOrClueHandoffChapters,
    nonPursuitUnderlyingPatternCount: nonPursuitPatterns.length,
    nonPursuitUnderlyingPatternChapters: nonPursuitPatterns,
    acceptanceNonPursuitThresholdMet: nonPursuitPatterns.length >= 2,
    verdict: nonPursuitPatterns.length >= 2
      ? '本段至少两章底层推进不是追捕压力/线索交接'
      : '底层推进仍主要依赖追捕压力或拿线索换地点'
  }
}

function summarizeSceneTexture(chapters = []) {
  const chapterSignals = chapters.map(item => ({
    chapterNum: item.chapterNum,
    title: item.title,
    hasRelationshipRestOrChoiceScene: Boolean(item.indicators?.hasRelationshipRestOrChoiceScene),
    signals: item.indicators?.textureSignals || {}
  }))
  const texturedChapters = chapterSignals.filter(item => item.hasRelationshipRestOrChoiceScene)
  const windowSize = Math.min(5, Math.max(1, chapters.length))
  const windows = []
  for (let index = 0; index < chapters.length; index += windowSize) {
    const slice = chapterSignals.slice(index, index + windowSize)
    windows.push({
      chapters: slice.map(item => item.chapterNum),
      hasTexture: slice.some(item => item.hasRelationshipRestOrChoiceScene)
    })
  }
  return {
    chaptersWithTexture: texturedChapters.length,
    chapterSignals,
    windows,
    everyFiveChapterWindowHasTexture: windows.every(item => item.hasTexture),
    verdict: windows.every(item => item.hasTexture)
      ? '每个 3-5 章观察窗口都有关系、喘息、代价后果或人物选择场信号。'
      : '存在 3-5 章窗口缺少关系、喘息、代价后果或人物选择场信号。'
  }
}

function buildReaderRetell(chapters = [], rangeStart = RANGE_START, rangeEnd = RANGE_END) {
  const observed = chapters.filter(item => item.finalized)
  const sourceChapters = observed.length ? observed : chapters
  const titles = sourceChapters.map(item => item.title || `第${item.chapterNum}章`).join('、')
  const relationshipChapter = sourceChapters.find(item => ['persisted', 'derived'].includes(item.relationshipChangeSource)) ||
    sourceChapters.find(item => item.relationshipChangeSource === 'inferred')
  const relationship = relationshipChapter?.excerpts.relationshipDelta ||
    (relationshipChapter ? `第 ${relationshipChapter.chapterNum} 章出现关系变化信号（${relationshipChapter.relationshipChangeSource}）。` : '本段关系变化不足，需要下一轮继续观察。')
  const answerChapter = [...sourceChapters].reverse().find(item => item.excerpts.stageAnswerForReader)
  const answer = answerChapter?.excerpts.stageAnswerForReader ||
    '阶段性答案不足，读者仍主要靠正文线索自行归纳。'
  return [
    `第 ${rangeStart}-${rangeEnd} 章主要章节为：${titles}。`,
    `这一段的关系变化是：${relationship}`,
    `阶段成果是：${answer}`
  ]
}

function summarizeWeakTitles(chapters = []) {
  const samples = chapters
    .filter(item => item.finalized && item.weakTitle)
    .map(item => ({ chapterNum: item.chapterNum, title: item.title }))
  return {
    weakTitleCount: samples.length,
    weakTitleSamples: samples,
    readingImpact: samples.length
      ? '弱标题会削弱阶段记忆点；本轮只观察，不大改章名策略。'
      : '本段未见明显动作残片式弱标题。'
  }
}

function summarizeStageReuse(chapters = []) {
  const observed = chapters.filter(item => item.finalized)
  const stageContinuationDiagnostics = observed.map(item => ({
    chapterNum: item.chapterNum,
    storyBlockId: item.storyBlockId,
    stageId: item.blockStageId,
    stageContinues: Boolean(item.storyBlockStageContinues),
    stageContinuationDepth: Number(item.stageContinuationDepth || 0),
    previousOpenStageId: item.previousOpenStageId || '',
    settlementDecision: item.settlementDecision || '',
    settlementEvidence: item.settlementEvidence || [],
    equivalentCompletionScope: item.equivalentCompletionScope || '',
    futureStageTouched: Boolean(item.futureStageTouched),
    futureStageEvidence: item.futureStageEvidence || [],
    futureStageOverClosed: Boolean(item.futureStageOverClosed),
    needsFutureStageReplan: Boolean(item.needsFutureStageReplan),
    replanRemainingStages: Boolean(item.replanRemainingStages),
    whetherStageClosedBeforeNextBeatPlan: Boolean(item.whetherStageClosedBeforeNextBeatPlan)
  }))
  const groups = new Map()
  const openContinuations = observed
    .filter(item => item.storyBlockStageContinues === true)
    .map(item => ({
      chapterNum: item.chapterNum,
      storyBlockId: item.storyBlockId,
      stageId: item.blockStageId,
      status: cleanValue(item.storyBlockStageContinueReason) ? 'legal_continue' : 'missing_continue_reason',
      stageContinueReason: item.storyBlockStageContinueReason || '',
      stageContinuationDepth: Number(item.stageContinuationDepth || 0),
      settlementDecision: item.settlementDecision || '',
      explanation: cleanValue(item.storyBlockStageContinueReason)
        ? '本章声明阶段跨章继续，并给出明确 stageContinueReason。'
        : '本章声明阶段跨章继续，但缺少 stageContinueReason。'
    }))
  for (const chapter of observed) {
    const storyBlockId = cleanValue(chapter.storyBlockId)
    const stageId = cleanValue(chapter.blockStageId)
    if (!storyBlockId || !stageId) continue
    const key = `${storyBlockId}::${stageId}`
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(chapter)
  }

  const repeatedStages = []
  for (const group of groups.values()) {
    const ordered = [...group].sort((left, right) => Number(left.chapterNum) - Number(right.chapterNum))
    if (ordered.length < 2) continue
    const transitionChecks = []
    for (let index = 1; index < ordered.length; index += 1) {
      const previous = ordered[index - 1]
      const current = ordered[index]
      const legal = Boolean(previous.storyBlockStageContinues && cleanValue(previous.storyBlockStageContinueReason))
      transitionChecks.push({
        fromChapter: previous.chapterNum,
        toChapter: current.chapterNum,
        legal,
        stageContinues: Boolean(previous.storyBlockStageContinues),
        stageContinueReason: previous.storyBlockStageContinueReason || '',
        previousStoryBlockStageContinues: current.previousStoryBlockStageContinues,
        previousStoryBlockReviewDecision: current.previousStoryBlockReviewDecision || ''
      })
    }
    const illegalTransition = transitionChecks.find(item => !item.legal)
    const stageContinueReason = transitionChecks
      .map(item => item.stageContinueReason)
      .filter(Boolean)
      .join('；')
    const continuationDepthLimitReached = ordered.length >= 3 ||
      ordered.some(item => Number(item.stageContinuationDepth || 0) >= 2)
    repeatedStages.push({
      storyBlockId: ordered[0].storyBlockId,
      stageId: ordered[0].blockStageId,
      chapters: ordered.map(item => item.chapterNum),
      status: illegalTransition
        ? 'missing_continue_reason'
        : continuationDepthLimitReached
          ? 'continuation_depth_limit_reached'
          : 'legal_continue',
      stageContinueReason,
      transitionChecks,
      stageContinuationDepth: Math.max(...ordered.map(item => Number(item.stageContinuationDepth || 0))),
      explanation: illegalTransition
        ? '重复阶段缺少上一章 stageContinues=true 和明确 stageContinueReason，不能按正常推进隐藏。'
        : continuationDepthLimitReached
          ? '同一阶段已连续复用到上限，必须在下一章前完成 settlement，不能按正常推进隐藏。'
          : '重复阶段由上一章明确 stageContinues=true 且给出继续原因，属于合法跨章继续。'
    })
  }

  return {
    duplicateStageCount: repeatedStages.length,
    repeatedStages,
    openContinuations,
    stageContinuationDiagnostics,
    hasHiddenAbnormalReuse: repeatedStages.some(item => item.status !== 'legal_continue') ||
      openContinuations.some(item => item.status !== 'legal_continue' || Number(item.stageContinuationDepth || 0) >= 2),
    verdict: repeatedStages.length === 0
      ? (openContinuations.some(item => item.status !== 'legal_continue' || Number(item.stageContinuationDepth || 0) >= 2)
          ? (openContinuations.some(item => Number(item.stageContinuationDepth || 0) >= 2)
              ? '未发现本段重复绑定，但开放阶段已到连续上限，需要先完成 settlement。'
              : '未发现重复绑定，但存在缺少原因的开放阶段继续。')
          : (openContinuations.length
              ? '未发现重复绑定；开放阶段继续均有明确 stageContinueReason。'
              : '未发现同一故事块阶段在本观察段重复绑定。'))
      : (repeatedStages.some(item => item.status !== 'legal_continue') ||
          openContinuations.some(item => item.status !== 'legal_continue' || Number(item.stageContinuationDepth || 0) >= 2))
          ? (repeatedStages.some(item => item.status === 'continuation_depth_limit_reached') ||
              openContinuations.some(item => Number(item.stageContinuationDepth || 0) >= 2)
                ? '发现同一阶段连续复用到上限，需要先完成 settlement，不能按正常推进隐藏。'
                : '发现阶段复用/继续但缺少明确继续原因，需要复核绑定/报告逻辑。')
          : '阶段复用/继续均有明确 stageContinueReason，按合法跨章继续记录。'
  }
}

function summarizeStageSettlementScope(chapters = []) {
  const observed = chapters.filter(item => item.finalized)
  const scoped = observed.filter(item => item.settlementDecision || item.equivalentCompletionScope || item.futureStageTouched || item.futureStageOverClosed)
  const equivalentCompletions = scoped.filter(item => item.settlementDecision === 'completed_by_equivalent_story_function')
  const futureTouched = scoped.filter(item => item.futureStageTouched)
  const futureOverClosed = scoped.filter(item => item.futureStageOverClosed)
  return {
    equivalentCompletionCount: equivalentCompletions.length,
    currentStageOnlyEquivalentCompletions: equivalentCompletions.filter(item => item.equivalentCompletionScope === 'current_stage_only').length,
    futureStageTouchedCount: futureTouched.length,
    futureStageOverClosedCount: futureOverClosed.length,
    replanRemainingStagesCount: scoped.filter(item => item.replanRemainingStages || item.needsFutureStageReplan).length,
    futureStageTouchedSamples: futureTouched.map(item => ({
      chapterNum: item.chapterNum,
      title: item.title,
      evidence: item.futureStageEvidence || []
    })),
    futureStageOverClosedSamples: futureOverClosed.map(item => ({
      chapterNum: item.chapterNum,
      title: item.title,
      settlementDecision: item.settlementDecision,
      equivalentCompletionScope: item.equivalentCompletionScope
    })),
    verdict: futureOverClosed.length
      ? '发现 futureStageOverClosed，需停止扩大并复核 stage settlement。'
      : equivalentCompletions.length
        ? '等价完成已按当前 stage scope 记录，未发现未来 stage 被自动吞并。'
        : '本段未触发等价完成 settlement。'
  }
}

export function summarizePriorOpenContinuation(chapters = [], prior = null, settlementDiagnostics = null) {
  if (!prior || prior.storyBlockStageContinues !== true) {
    return {
      present: false,
      status: 'none',
      hasIssue: false,
      verdict: '未提供上一轮开放阶段继续。'
    }
  }
  const storyBlockId = cleanValue(prior.storyBlockId)
  const stageId = cleanValue(prior.blockStageId)
  const matches = chapters.filter(item => item.finalized).filter(item =>
    cleanValue(item.storyBlockId) === storyBlockId &&
    cleanValue(item.blockStageId) === stageId
  )
  const chapterSettlement = chapters.find(item =>
    item.whetherStageClosedBeforeNextBeatPlan &&
    cleanValue(item.previousOpenStageId) === stageId &&
    (!storyBlockId || cleanValue(item.storyBlockId) === storyBlockId || cleanValue(item.previousStoryBlockId) === storyBlockId)
  )
  const settlement = settlementDiagnostics || chapterSettlement || null
  const settlementStageId = cleanValue(settlement?.previousOpenStageId || settlement?.previous_open_stage_id || settlement?.priorStageId)
  const settlementBlockId = cleanValue(settlement?.activeBlockId || settlement?.storyBlockId || settlement?.priorStoryBlockId)
  const settlementClosesPrior = Boolean(
    settlement?.whetherStageClosedBeforeNextBeatPlan &&
    settlementStageId === stageId &&
    (!settlementBlockId || settlementBlockId === storyBlockId)
  )
  const matched = matches[0]
  if (!matched) {
    if (settlementClosesPrior) {
      return {
        present: true,
        status: 'closed_before_current_range_by_settlement',
        hasIssue: false,
        priorChapterNum: prior.chapterNum,
        priorStoryBlockId: storyBlockId,
        priorStageId: stageId,
        priorStageContinueReason: prior.storyBlockStageContinueReason || '',
        settlementDecision: settlement.settlementDecision || '',
        settlementEvidence: settlement.settlementEvidence || [],
        stageContinuationDepth: settlement.stageContinuationDepth || 0,
        verdict: `上一轮第 ${prior.chapterNum} 章开放阶段已在第 ${chapters[0]?.chapterNum || '?'} 章小纲前通过 settlement 关闭。`
      }
    }
    return {
      present: true,
      status: 'not_seen_in_current_range',
      hasIssue: true,
      priorChapterNum: prior.chapterNum,
      priorStoryBlockId: storyBlockId,
      priorStageId: stageId,
      priorStageContinueReason: prior.storyBlockStageContinueReason || '',
      verdict: '上一轮开放阶段继续未在本观察段读到承接章节。'
    }
  }
  const latestMatch = matches.at(-1) || matched
  const continued = latestMatch.storyBlockStageContinues === true
  const hasReason = Boolean(cleanValue(latestMatch.storyBlockStageContinueReason))
  const stillOpenAfter37 = continued &&
    Number(latestMatch.chapterNum) >= Number(prior.chapterNum || 0) + 2
  const status = continued
    ? (stillOpenAfter37 ? 'still_open_after_37' : (hasReason ? 'still_open_with_reason' : 'continued_without_reason'))
    : 'completed_in_current_range'
  return {
    present: true,
    status,
    hasIssue: status === 'continued_without_reason' || status === 'still_open_after_37',
    priorChapterNum: prior.chapterNum,
    priorStoryBlockId: storyBlockId,
    priorStageId: stageId,
    priorStageContinueReason: prior.storyBlockStageContinueReason || '',
    carriedByChapter: matched.chapterNum,
    carriedByTitle: matched.title,
    matchedChapters: matches.map(item => item.chapterNum),
    latestMatchedChapter: latestMatch.chapterNum,
    currentStageContinues: continued,
    currentStageContinueReason: latestMatch.storyBlockStageContinueReason || '',
    verdict: status === 'completed_in_current_range'
      ? `上一轮第 ${prior.chapterNum} 章开放阶段在第 ${matched.chapterNum} 章承接并关闭。`
      : status === 'still_open_with_reason'
        ? `上一轮第 ${prior.chapterNum} 章开放阶段在第 ${matched.chapterNum} 章继续保持开放，且有 reason。`
        : status === 'still_open_after_37'
          ? `上一轮第 ${prior.chapterNum} 章开放阶段到第 ${latestMatch.chapterNum} 章仍未关闭，36/37 未完成承接。`
          : `上一轮第 ${prior.chapterNum} 章开放阶段在第 ${matched.chapterNum} 章继续开放但缺少 reason。`
  }
}

function summarizeTemplateBeatPlanWording(chapters = []) {
  const samples = chapters
    .filter(item => item.templateBeatPlanWording)
    .map(item => ({
      chapterNum: item.chapterNum,
      title: item.title,
      samples: item.templateBeatPlanSamples || []
    }))
  return {
    chapterCount: samples.length,
    chapters: samples.map(item => item.chapterNum),
    samples,
    verdict: samples.length
      ? '仍有模板化小纲话术进入最终小纲'
      : '未读到模板化小纲话术进入最终小纲'
  }
}

function summarizeCompanionVoiceCards(chapters = [], liveReport = {}) {
  const knownNames = ['老陈', '小九', '老太太', '灰衣人', '徐主簿', '徐正清', '乙十七']
  const chapterSignals = chapters.map(item => ({
    chapterNum: item.chapterNum,
    namesInText: knownNames.filter(name => (item.beatPlanFields?.raw || '').includes(name) || item.excerpts.relationshipDelta.includes(name)),
    nonFunctionalSignal: item.indicators.hasNonFunctionalCompanionSignal
  }))
  const liveEvidence = (liveReport.chapterReports || [])
    .filter(item => Number(item.chapterNum) >= RERUN_RANGE[0] && Number(item.chapterNum) <= RERUN_RANGE[1])
    .map(item => ({
      chapterNum: item.chapterNum,
      companionVoiceCardsInjected: item.companionVoiceCardsInjected ?? item.writerContextDiagnostics?.companionVoiceCardsInjected ?? null,
      companionVoiceCardNames: item.companionVoiceCardNames || item.writerContextDiagnostics?.companionVoiceCardNames || []
    }))
  return {
    expectedByContextBuilder: true,
    actualInjectionEvidence: liveEvidence,
    chaptersWithNonFunctionalCompanionSignal: chapters.filter(item => item.indicators.hasNonFunctionalCompanionSignal).length,
    chapterSignals,
    verdict: liveEvidence.some(item => item.companionVoiceCardsInjected === true)
      ? 'live report 读到配角声音卡上下文注入证据'
      : 'live report 暂未提供声音卡注入诊断；只能结合合同测试与正文信号保守观察'
  }
}

function summarizeSampleMicroDemoCards(chapters = [], liveReport = {}) {
  const liveEvidence = (liveReport.chapterReports || [])
    .filter(item => Number(item.chapterNum) >= RERUN_RANGE[0] && Number(item.chapterNum) <= RERUN_RANGE[1])
    .map(item => {
      const diagnostics = item.writerContextDiagnostics || {}
      return {
        chapterNum: item.chapterNum,
        sampleCardInjected: item.sampleCardInjected ?? diagnostics.sampleCardInjected ?? false,
        sampleCardId: item.sampleCardId || diagnostics.sampleCardId || '',
        sampleCardTitle: item.sampleCardTitle || diagnostics.sampleCardTitle || '',
        sampleCardType: item.sampleCardType || diagnostics.sampleCardType || '',
        sampleInjectionReason: item.sampleInjectionReason || diagnostics.sampleInjectionReason || '',
        microDemoChars: Number(item.microDemoChars ?? diagnostics.microDemoChars ?? 0) || 0,
        sourceFieldsStripped: item.sourceFieldsStripped ?? diagnostics.sourceFieldsStripped ?? true,
        sampleLeakageDetected: item.sampleLeakageDetected ?? diagnostics.sampleLeakageDetected ?? false
      }
    })
  const injected = liveEvidence.filter(item => item.sampleCardInjected)
  const leakage = liveEvidence.filter(item => item.sampleLeakageDetected)
  return {
    expectedMaxPerChapter: 1,
    actualInjectionEvidence: liveEvidence,
    injectedChapterCount: injected.length,
    injectedChapters: injected.map(item => item.chapterNum),
    leakageDetected: leakage.length > 0,
    leakageChapters: leakage.map(item => item.chapterNum),
    verdict: leakage.length
      ? '检测到样本字段或来源信息泄漏，需停止扩大观察。'
      : injected.length
        ? `live report 读到 ${injected.length} 章低量样本微示范注入，未发现样本泄漏。`
        : 'live report 暂未读到样本微示范注入；按无明显匹配或诊断未写入记录。'
  }
}

export function summarizeRerun(chapters, baseline = {}, options = {}) {
  const completed = chapters.filter(item => item.finalized)
  const allFiveCompleted = completed.length === chapters.length
  const observedChapters = completed.length ? completed : chapters
  const chaseLoop = classifyChaseLoop(observedChapters)
  const storyFunctionMix = summarizeStoryFunctionMix(observedChapters)
  const underlyingProgressionPattern = summarizeUnderlyingProgressionPattern(observedChapters)
  const emotionalAnchorCount = observedChapters.filter(item => item.indicators.hasEmotionalAnchor).length
  const relationshipDeltaCount = observedChapters.filter(item => item.indicators.hasRelationshipDelta).length
  const companionSignalCount = observedChapters.filter(item => item.indicators.hasNonFunctionalCompanionSignal).length
  const explanationTotal = observedChapters.reduce((sum, item) => sum + item.counts.explanation, 0)
  const persistedOrDerivedEmotionRelationCount = observedChapters.filter(item =>
    ['emotionalAnchor', 'relationshipDelta'].some(key =>
      ['persisted', 'derived'].includes(item.humanityFieldEvidence?.[key]?.status)
    )
  ).length
  const chaptersWithAnyPersistedOrDerived = observedChapters.filter(item =>
    item.persistedHumanityFields.length || item.derivedHumanityFields.length
  ).length
  const baselineExplanation = baseline.evidenceMetrics?.totals?.counts?.explanation ?? null
  const baselineChapterCount = baseline.scope?.chapterCount || baseline.evidenceMetrics?.chapters?.length || 20
  const baselineExplanationPerChapter = baselineExplanation === null ? null : baselineExplanation / Math.max(1, baselineChapterCount)
  const rerunExplanationPerChapter = explanationTotal / Math.max(1, observedChapters.length)
  const rangeStart = options.rangeStart || chapters[0]?.chapterNum || RANGE_START
  const rangeEnd = options.rangeEnd || chapters.at(-1)?.chapterNum || RANGE_END
  const targetFinalChapter = completed.find(item => Number(item.chapterNum) === Number(rangeEnd)) || null
  const chaptersWithPersistedHumanityFields = observedChapters.filter(item => item.persistedHumanityFields.length).length
  const chaptersWithDerivedHumanityFields = observedChapters.filter(item => item.derivedHumanityFields.length).length
  const requiredPersistedHumanityChapters = chapters.length >= 10 ? 8 : chapters.length >= 5 ? 4 : 3

  return {
    allFiveCompleted,
    chaseLoop,
    storyFunctionMix,
    underlyingProgressionPattern,
    emotionalAnchors: {
      chaptersWithAnchor: emotionalAnchorCount,
      chaptersWithPersistedOrDerivedEmotionRelation: persistedOrDerivedEmotionRelationCount,
      verdict: persistedOrDerivedEmotionRelationCount >= 3
        ? '情绪锚点机制落盘基本生效'
        : '正文信号显示改善，但机制落盘未验证'
    },
    relationshipChanges: {
      chaptersWithDelta: relationshipDeltaCount,
      relationshipChangeSources: Object.fromEntries(observedChapters.map(item => [item.chapterNum, item.relationshipChangeSource])),
      verdict: relationshipDeltaCount >= 3 ? '人物关系变化可见' : relationshipDeltaCount >= 1 ? '有关系变化但不稳定' : '关系变化不足'
    },
    companionTexture: {
      chaptersWithNonFunctionalSignal: companionSignalCount,
      verdict: companionSignalCount >= 2 ? '配角有非功能性动作或对话信号' : '配角仍偏功能推进'
    },
    sceneTextureEvidence: summarizeSceneTexture(observedChapters),
    explanationSentences: {
      baselinePerChapter: baselineExplanationPerChapter,
      rerunPerChapter: rerunExplanationPerChapter,
      verdict: baselineExplanationPerChapter === null
        ? '无基线解释词均值'
        : rerunExplanationPerChapter <= baselineExplanationPerChapter * 0.85
          ? '解释连接词较基线下降'
          : rerunExplanationPerChapter <= baselineExplanationPerChapter
            ? '解释连接词略降或持平'
            : '解释连接词未下降'
    },
    finalChapterStageAnswer: {
      chapterNum: rangeEnd,
      finalized: Boolean(targetFinalChapter),
      hasStageAnswer: Boolean(targetFinalChapter?.indicators.hasStageAnswer),
      source: targetFinalChapter?.humanityFieldEvidence?.stageAnswerForReader?.status || 'missing',
      text: targetFinalChapter?.excerpts.stageAnswerForReader || '',
      verdict: targetFinalChapter
        ? (targetFinalChapter.indicators.hasStageAnswer ? `第 ${rangeEnd} 章给出阶段性答案信号` : `第 ${rangeEnd} 章阶段答案不足`)
        : `第 ${rangeEnd} 章未定稿，本轮不能判断阶段答案`
    },
    mechanismFieldPersistence: {
      chaptersWithPersistedHumanityFields,
      chaptersWithDerivedHumanityFields,
      chaptersWithPersistedOrDerivedHumanityFields: chaptersWithAnyPersistedOrDerived,
      chaptersWithPersistedOrDerivedEmotionRelation: persistedOrDerivedEmotionRelationCount,
      requiredPersistedHumanityChapters,
      persistedHumanityThresholdMet: chaptersWithPersistedHumanityFields >= requiredPersistedHumanityChapters,
      verdict: chaptersWithAnyPersistedOrDerived >= 3
        ? '小纲新增字段已有至少三章 persisted/derived 证据'
        : chaptersWithAnyPersistedOrDerived > 0
          ? '小纲新增字段部分落盘，但未达三章'
          : '未读到小纲新增字段落盘，判断只能来自 inferred 信号'
    },
    templatedBeatPlanWording: summarizeTemplateBeatPlanWording(observedChapters),
    stageReuse: summarizeStageReuse(observedChapters),
    stageSettlementScope: summarizeStageSettlementScope(observedChapters),
    priorOpenContinuation: summarizePriorOpenContinuation(
      chapters,
      options.priorOpenContinuation || null,
      options.stageSettlementDiagnostics || null
    ),
    weakTitles: summarizeWeakTitles(observedChapters),
    stateWarnings: options.stateWarnings || [],
    resolvedStateWarnings: options.resolvedStateWarnings || [],
    readerRetell3Sentences: buildReaderRetell(chapters, rangeStart, rangeEnd)
  }
}

function markdownTable(headers, rows) {
  return [
    `|${headers.join('|')}|`,
    `|${headers.map(() => '---').join('|')}|`,
    ...rows.map(row => `|${row.map(mdEscape).join('|')}|`)
  ].join('\n')
}

function mdEscape(value) {
  return String(value ?? '').replaceAll('|', '｜').replace(/\n+/g, ' ')
}

function evidenceSummary(item, key) {
  const evidence = item.humanityFieldEvidence?.[key]
  if (!evidence) return 'missing'
  return evidence.status
}

export function renderMarkdown(data) {
  const chapterRows = data.chapters.map(item => [
    item.chapterNum,
    item.title,
    item.finalized ? '是' : '否',
    item.wordCount,
    item.dominantStoryFunction,
    item.underlyingProgressionPattern,
    item.indicators.loopSignal,
    evidenceSummary(item, 'emotionalAnchor'),
    evidenceSummary(item, 'relationshipDelta'),
    item.relationshipChangeSource,
    item.templateBeatPlanWording ? '有' : '无',
    item.weakTitle ? '弱' : '正常',
    item.counts.explanation,
    evidenceSummary(item, 'stageAnswerForReader')
  ])

  return `# 故事性与人物血肉小跑观察：第 ${data.scope.chaptersReviewed[0]}-${data.scope.chaptersReviewed[1]} 章

- 项目：${data.project?.name || ''} (${data.project?.id || ''})
- 对比基线：第 ${data.scope.baselineChapters[0]}-${data.scope.baselineChapters[1]} 章故事性诊断
- live 报告：${data.sourceReports.rerunLiveReport || '无'}
- 未跑 50 章：${data.scope.didRun50Chapters ? '否' : '是'}
- 未改模型配置：${data.scope.changedModelConfig ? '否' : '是'}

## 总结

- 追逃循环：${data.comparison.chaseLoop.status}，${data.comparison.chaseLoop.verdict}
${data.comparison.chaseLoop.consecutiveLoopWarning ? `- 连续循环 warning：${data.comparison.chaseLoop.consecutiveLoopWarningText}` : '- 连续循环 warning：未触发'}
- 主导故事功能：非追逃主导 ${data.comparison.storyFunctionMix.nonChaseDominantCount} 章；${data.comparison.storyFunctionMix.verdict}
- 底层推进模式：非追捕/线索交接 ${data.comparison.underlyingProgressionPattern.nonPursuitUnderlyingPatternCount} 章；${data.comparison.underlyingProgressionPattern.verdict}
- 情绪锚点：${data.comparison.emotionalAnchors.verdict}
- 人物关系变化：${data.comparison.relationshipChanges.verdict}
- 关系/喘息/选择场：${data.comparison.sceneTextureEvidence.verdict}
- 小纲字段落盘：${data.comparison.mechanismFieldPersistence.verdict}
- 模板化小纲话术：${data.comparison.templatedBeatPlanWording.verdict}
- 阶段复用：${data.comparison.stageReuse.verdict}
- stage settlement scope：${data.comparison.stageSettlementScope.verdict}
- 上轮开放阶段承接：${data.comparison.priorOpenContinuation.verdict}
- 配角声音卡：${data.companionVoiceCardEvidence.verdict}
- 样本微示范：${data.sampleMicroDemoEvidence.verdict}
- 设定 warning：${data.comparison.stateWarnings.length ? `${data.comparison.stateWarnings.length} 条未解决` : '未读到未解决 pending/rejected'}
- 已解决中途设定 blocker：${data.comparison.resolvedStateWarnings?.length || 0} 条
- 弱标题：${data.comparison.weakTitles.weakTitleCount} 个；${data.comparison.weakTitles.readingImpact}
- 第 ${data.scope.chaptersReviewed[1]} 章阶段答案：${data.comparison.finalChapterStageAnswer.verdict}
- 服务清理诊断：killed=${data.serviceCleanupDiagnostics?.killedPids?.length || 0}，skipped=${data.serviceCleanupDiagnostics?.skippedStalePids?.length || 0}
- 短稿策略：${data.chapters.filter(item => item.shortDraftStrategy).length} 章触发

## 章节观察

${markdownTable(['章', '标题', '定稿', '字数', '主导功能', '底层推进', '循环信号', '情绪字段', '关系字段', '关系来源', '模板话术', '标题', '解释词', '阶段答案字段'], chapterRows)}

## 样本微示范注入证据

${markdownTable(['章', '注入', '卡名', '类型', '原因', '字数', '字段剥离', '泄漏'], data.sampleMicroDemoEvidence.actualInjectionEvidence.map(item => [
  item.chapterNum,
  item.sampleCardInjected ? '是' : '否',
  item.sampleCardTitle || '无',
  item.sampleCardType || '无',
  item.sampleInjectionReason || '无',
  item.microDemoChars || 0,
  item.sourceFieldsStripped ? '是' : '否',
  item.sampleLeakageDetected ? '是' : '否'
]))}

## 短稿策略

${data.chapters.filter(item => item.shortDraftStrategy).length
  ? markdownTable(['章', 'strategy', 'original', 'expanded', 'final', 'accepted', 'rejectReason', 'factDrift', 'endingPreserved'], data.chapters.filter(item => item.shortDraftStrategy).map(item => [
    item.chapterNum,
    item.shortDraftStrategy,
    item.originalWordCount || '无',
    item.expandedWordCount || '无',
    item.finalCandidateWordCount || item.wordCount || '无',
    item.expansionAccepted ? '是' : '否',
    item.expansionRejectedReason || '无',
    item.factDriftCheck?.passed === true ? 'pass' : (item.factDriftCheck?.passed === false ? `fail:${(item.factDriftCheck.missingGroups || []).join('、') || 'unknown'}` : '无'),
    item.endingPreserved?.passed === true ? 'pass' : (item.endingPreserved?.passed === false ? `fail:${(item.endingPreserved.missingGroups || []).join('、') || 'unknown'}` : '无')
  ]))
  : '- 未触发 3000-3999 字短稿扩写/重生策略。'}

## 主导故事功能

${markdownTable(['功能', '章数'], Object.entries(data.comparison.storyFunctionMix.counts || {}).map(([key, value]) => [key, value]))}

非追逃主导章节：${data.comparison.storyFunctionMix.nonChaseDominantChapters.length
  ? data.comparison.storyFunctionMix.nonChaseDominantChapters.map(item => `第 ${item.chapterNum} 章 ${item.dominantStoryFunction}`).join('；')
  : '无'}

## 底层推进模式

${markdownTable(['模式', '章数'], Object.entries(data.comparison.underlyingProgressionPattern.counts || {}).map(([key, value]) => [key, value]))}

非追捕/线索交接底层推进章节：${data.comparison.underlyingProgressionPattern.nonPursuitUnderlyingPatternChapters.length
  ? data.comparison.underlyingProgressionPattern.nonPursuitUnderlyingPatternChapters.map(item => `第 ${item.chapterNum} 章 ${item.underlyingProgressionPattern}`).join('；')
  : '无'}

## 字段证据

${data.chapters.map(item => {
  const lines = HUMANITY_KEYS.map(key => {
    const evidence = item.humanityFieldEvidence[key]
    const value = evidence?.value ? `：${evidence.value}` : ''
    return `  - ${key} = ${evidence?.status || 'missing'}${value}`
  })
  return `- 第 ${item.chapterNum} 章（beatPlanSource=${item.beatPlanSource || 'unknown'}）：\n${lines.join('\n')}`
}).join('\n')}

## 模板话术样本

${data.comparison.templatedBeatPlanWording.samples.length
  ? data.comparison.templatedBeatPlanWording.samples.map(item => `- 第 ${item.chapterNum} 章《${item.title}》：${(item.samples || []).join('；') || '有模板话术，未截取到样本'}`).join('\n')
  : '- templateBeatPlanWording=false；未读到 stage-x、围绕、关系任务脚手架或机械交接话术。'}

## Stage 复用 / 继续

${data.comparison.stageReuse.repeatedStages.length
  ? data.comparison.stageReuse.repeatedStages.map(item => `- block=${item.storyBlockId} stage=${item.stageId} chapters=${item.chapters.join(', ')} status=${item.status}；reason=${item.stageContinueReason || '缺失'}；${item.explanation}`).join('\n')
  : '- 未发现同一故事块 stage 在本观察段重复绑定。'}
${data.comparison.stageReuse.openContinuations.length
  ? data.comparison.stageReuse.openContinuations.map(item => `- 开放继续：第 ${item.chapterNum} 章 block=${item.storyBlockId} stage=${item.stageId} status=${item.status}；reason=${item.stageContinueReason || '缺失'}；${item.explanation}`).join('\n')
  : '- 未发现 stageContinues=true 的开放阶段继续。'}

上轮开放阶段承接：${data.comparison.priorOpenContinuation.verdict}

## Stage Settlement 诊断

${markdownTable(['章', 'stage', 'depth', 'previousOpenStageId', 'settlementDecision', 'scope', 'futureTouched', 'futureOverClosed', 'replan', 'closedBeforeBeatPlan'], data.comparison.stageReuse.stageContinuationDiagnostics.map(item => [
  item.chapterNum,
  item.stageId,
  item.stageContinuationDepth,
  item.previousOpenStageId,
  item.settlementDecision || '无',
  item.equivalentCompletionScope || '无',
  item.futureStageTouched ? '是' : '否',
  item.futureStageOverClosed ? '是' : '否',
  item.replanRemainingStages || item.needsFutureStageReplan ? '是' : '否',
  item.whetherStageClosedBeforeNextBeatPlan ? '是' : '否'
]))}

scope 统计：equivalent=${data.comparison.stageSettlementScope.equivalentCompletionCount}；currentOnly=${data.comparison.stageSettlementScope.currentStageOnlyEquivalentCompletions}；futureTouched=${data.comparison.stageSettlementScope.futureStageTouchedCount}；futureOverClosed=${data.comparison.stageSettlementScope.futureStageOverClosedCount}；replan=${data.comparison.stageSettlementScope.replanRemainingStagesCount}

## 关系 / 喘息 / 选择场

${markdownTable(['章', '标题', '有关系/喘息/选择场', '信号'], data.comparison.sceneTextureEvidence.chapterSignals.map(item => [
  item.chapterNum,
  item.title,
  item.hasRelationshipRestOrChoiceScene ? '是' : '否',
  Object.entries(item.signals || {}).filter(([, value]) => value).map(([key]) => key).join('、') || '无'
]))}

窗口检查：${data.comparison.sceneTextureEvidence.windows.map(item => `${item.chapters.join('-')}=${item.hasTexture ? '有' : '缺'}`).join('；')}

## 设定 Warning

${data.comparison.stateWarnings.length
  ? data.comparison.stateWarnings.map(item => `- 第 ${item.chapterNum || '?'} 章 ${item.entityName || item.id || ''} ${item.fieldPath || ''}：${item.reason || item.status || 'warning'}`).join('\n')
  : '- 未读到 rejected/pending 设定 warning。'}

已解决中途 blocker：
${data.comparison.resolvedStateWarnings?.length
  ? data.comparison.resolvedStateWarnings.map(item => `- 第 ${item.chapterNum || '?'} 章 ${item.entityName || item.id || ''} ${item.fieldPath || ''}：${item.originalReason || item.reason || 'resolved'}，已归位为 ${item.resolution || '动态身份/隶属揭示'}`).join('\n')
  : '- 无。'}

## Service Cleanup Diagnostics

- source：${data.serviceCleanupDiagnostics?.source || '无'}
- killedPids：${(data.serviceCleanupDiagnostics?.killedPids || []).join(', ') || '无'}
- skippedStalePids：${(data.serviceCleanupDiagnostics?.skippedStalePids || []).map(item => `${item.pid || '?'}:${item.skippedReason || item.reason || 'unknown'}`).join('；') || '无'}

## 三句话复述

${data.comparison.readerRetell3Sentences.map(item => `- ${item}`).join('\n')}

## 停止条件

本轮只观察第 ${data.scope.chaptersReviewed[0]}-${data.scope.chaptersReviewed[1]} 章。不扩大到 50 章；如果追逃仍多，按 reduced 或 still dominant 记录，不写 resolved。
`
}

async function collectStateWarnings(projectId, liveReport, range = RERUN_RANGE) {
  const [start, end] = range
  const fromLive = []
  const resolvedFromLive = []
  const resolvedKeys = new Set()
  for (const blocker of liveReport.resolvedIntermediateBlockers || []) {
    const chapterNum = Number(blocker.chapterNum || 0)
    for (const conflict of blocker.pendingHardConflicts || []) {
      resolvedKeys.add([
        chapterNum,
        conflict.entityName || '',
        conflict.fieldPath || '',
        conflict.oldValue || '',
        conflict.newValue || ''
      ].join('|'))
    }
  }
  for (const chapter of liveReport.chapterReports || []) {
    const chapterNum = Number(chapter.chapterNum || 0)
    if (chapterNum < start || chapterNum > end) continue
    for (const event of chapter.settingChanges || chapter.pendingSettingChanges || []) {
      if (['rejected', 'pending_review'].includes(String(event.status || ''))) {
        fromLive.push({ ...event, chapterNum, source: 'live_report' })
      }
    }
    const settingsFailure = chapter.flowEvents?.settings_confirmation_failed || chapter.settingReview || null
    for (const conflict of settingsFailure?.pendingHardConflicts || []) {
      const key = [
        chapterNum,
        conflict.entityName || '',
        conflict.fieldPath || '',
        conflict.oldValue || '',
        conflict.newValue || ''
      ].join('|')
      const item = {
        ...conflict,
        chapterNum,
        status: 'pending_review',
        reason: settingsFailure.code || 'hard_conflict_setting_review_required',
        source: 'live_report_settings_confirmation_failed'
      }
      if (resolvedKeys.has(key)) {
        resolvedFromLive.push({
          ...item,
          status: 'resolved',
          originalStatus: 'pending_review',
          originalReason: item.reason,
          reason: 'resolved_intermediate_setting_blocker',
          resolution: 'dynamic_affiliation_reveal_rehome',
          source: 'resolved_intermediate_blocker'
        })
      } else {
        fromLive.push(item)
      }
    }
  }
  if (!projectId) return { active: fromLive, resolved: resolvedFromLive }
  const rejected = await api(`/projects/${projectId}/settings/change-events?status=rejected`).catch(() => [])
  const pending = await api(`/projects/${projectId}/settings/change-events?status=pending_review`).catch(() => [])
  const activeFromApi = [...rejected, ...pending]
    .filter(event => Number(event.chapterNum || event.chapter_num || 0) >= start && Number(event.chapterNum || event.chapter_num || 0) <= end)
    .map(event => ({
      id: event.id,
      chapterNum: event.chapterNum || event.chapter_num,
      status: event.status,
      entityName: event.entityName || event.entity_name,
      fieldPath: event.fieldPath || event.field_path,
      reason: event.status === 'rejected' ? 'rejected_setting_candidate' : 'pending_setting_candidate',
      source: 'settings_api'
    }))
  return {
    active: [...fromLive, ...activeFromApi],
    resolved: resolvedFromLive
  }
}

function loadPriorOpenContinuation() {
  const previous = readJson(PREVIOUS_STORY_HUMANITY_REPORT, null)
  if (!previous) return null
  const open = previous.comparison?.stageReuse?.openContinuations
    ?.filter(item => item.status === 'legal_continue' || item.status === 'still_open_with_reason')
    ?.at(-1)
  if (open) {
    return {
      chapterNum: open.chapterNum,
      storyBlockId: open.storyBlockId,
      blockStageId: open.stageId,
      storyBlockStageContinues: true,
      storyBlockStageContinueReason: open.stageContinueReason || ''
    }
  }
  return previous.chapters
    ?.filter(item => item.storyBlockStageContinues === true)
    ?.at(-1) || null
}

function loadServiceCleanupDiagnostics() {
  const explicitPath = process.env.SERVICE_CLEANUP_DIAGNOSTICS || process.env.SERVICE_CLEANUP_DIAGNOSTICS_PATH || ''
  const candidates = [
    explicitPath,
    path.join(QA_DIR, `live-service-cleanup-${RANGE_START}-${RANGE_END}.json`),
    path.join(QA_DIR, `live-runner-cleanup-${RANGE_START}-${RANGE_END}.json`),
    path.join(QA_DIR, 'latest-live-service-cleanup.json')
  ].filter(Boolean)
  for (const candidate of candidates) {
    const report = readJson(candidate, null)
    if (!report) continue
    return {
      source: path.relative(process.cwd(), candidate).replaceAll('\\', '/'),
      killedPids: Array.isArray(report.killedPids) ? report.killedPids : [],
      skippedStalePids: Array.isArray(report.skippedStalePids) ? report.skippedStalePids : [],
      skippedReason: Array.isArray(report.skippedStalePids)
        ? report.skippedStalePids.map(item => item.skippedReason || item.reason || '').filter(Boolean)
        : [],
      decisions: Array.isArray(report.decisions) ? report.decisions : [],
      dryRun: report.dryRun === true,
      missing: false
    }
  }
  return {
    source: null,
    killedPids: [],
    skippedStalePids: [],
    skippedReason: [],
    decisions: [],
    dryRun: false,
    missing: true
  }
}

function loadStageSettlementDiagnostics(liveReport = {}) {
  if (liveReport.stageContinuationSettlementDiagnostics) return liveReport.stageContinuationSettlementDiagnostics
  const explicitPath = process.env.STAGE_SETTLEMENT_DIAGNOSTICS || process.env.STAGE_SETTLEMENT_DIAGNOSTICS_PATH || ''
  const candidates = [
    explicitPath,
    path.join(QA_DIR, `stage-continuation-settlement-before-${RANGE_START}.json`)
  ].filter(Boolean)
  for (const candidate of candidates) {
    const report = readJson(candidate, null)
    if (!report) continue
    return {
      ...report,
      source: path.relative(process.cwd(), candidate).replaceAll('\\', '/')
    }
  }
  return null
}

async function main() {
  const baseline = normalizeStoryHumanityReview(readJson(BASELINE_PATH, {}))
  const liveReport = readJson(RERUN_LIVE_PATH, {})
  const serviceCleanupDiagnostics = loadServiceCleanupDiagnostics()
  const stageSettlementDiagnostics = loadStageSettlementDiagnostics(liveReport)
  const project = liveReport.project || {
    id: process.env.EXISTING_PROJECT_ID || '2da6152a-c083-41ee-8bcb-f11b0fae387d',
    name: process.env.EXISTING_PROJECT_NAME || 'LongformBrowser240w_20260625_153055'
  }
  const chapters = []
  const mysqlBeatPlans = loadBeatPlansFromMysql(project.id, RERUN_RANGE)
  for (let chapterNum = RERUN_RANGE[0]; chapterNum <= RERUN_RANGE[1]; chapterNum += 1) {
    const material = await loadChapterMaterial(project.id, liveReport, chapterNum, mysqlBeatPlans)
    chapters.push(analyzeChapter({ chapterNum, ...material }))
  }
  const stateWarningBuckets = await collectStateWarnings(project.id, liveReport, RERUN_RANGE)
  const priorOpenContinuation = loadPriorOpenContinuation()
  const comparison = summarizeRerun(chapters, baseline, {
    rangeStart: RERUN_RANGE[0],
    rangeEnd: RERUN_RANGE[1],
    stateWarnings: stateWarningBuckets.active || [],
    resolvedStateWarnings: stateWarningBuckets.resolved || [],
    priorOpenContinuation,
    stageSettlementDiagnostics
  })
  const data = {
    createdAt: new Date().toISOString(),
    project,
    sourceReports: {
      baseline: path.relative(process.cwd(), BASELINE_PATH).replaceAll('\\', '/'),
      rerunLiveReport: fs.existsSync(RERUN_LIVE_PATH)
        ? path.relative(process.cwd(), RERUN_LIVE_PATH).replaceAll('\\', '/')
        : null
    },
    scope: {
      baselineChapters: [1, 20],
      chaptersReviewed: RERUN_RANGE,
      didRun50Chapters: false,
      changedModelConfig: false,
      changedMainFlow: false,
      mode: `story_humanity_rerun_${RERUN_RANGE[0]}_${RERUN_RANGE[1]}_observation`
    },
    baselineSnapshot: {
      overallVerdict: baseline.overallVerdict || {},
      p0Issues: (baseline.prioritizedIssues || []).filter(item => item.severity === 'P0').map(item => item.title)
    },
    chapters,
    comparison,
    stageContinuationSettlementDiagnostics: stageSettlementDiagnostics,
    serviceCleanupDiagnostics,
    companionVoiceCardEvidence: summarizeCompanionVoiceCards(chapters, liveReport),
    sampleMicroDemoEvidence: summarizeSampleMicroDemoCards(chapters, liveReport),
    acceptance: {
      stopAtChapter: RERUN_RANGE[1],
      allFiveCompleted: comparison.allFiveCompleted,
      atLeastThreePersistedOrDerivedEmotionRelation: comparison.mechanismFieldPersistence.chaptersWithPersistedOrDerivedEmotionRelation >= 3,
      persistedHumanityThresholdMet: comparison.mechanismFieldPersistence.persistedHumanityThresholdMet,
      nonChaseDominantThresholdMet: comparison.storyFunctionMix.nonChaseDominantCount >= 2,
      nonPursuitUnderlyingPatternThresholdMet: comparison.underlyingProgressionPattern.nonPursuitUnderlyingPatternCount >= 2,
      chaseEscapeDominantChapterCount: comparison.storyFunctionMix.chaseEscapeCount,
      pursuitOrClueHandoffUnderlyingPatternCount: comparison.underlyingProgressionPattern.pursuitOrClueHandoffCount,
      noFutureStageOverClosed: comparison.stageSettlementScope.futureStageOverClosedCount === 0,
      noTemplateBeatPlanWording: comparison.templatedBeatPlanWording.chapterCount === 0,
      noHiddenAbnormalStageReuse: !comparison.stageReuse.hasHiddenAbnormalReuse && !comparison.priorOpenContinuation.hasIssue,
      shouldExpandBeyondRange: false
    }
  }

  fs.writeFileSync(OUT_JSON, `${JSON.stringify(data, null, 2)}\n`, 'utf8')
  fs.writeFileSync(OUT_MD, renderMarkdown(data), 'utf8')
  console.log(`Wrote ${path.relative(process.cwd(), OUT_JSON)}`)
  console.log(`Wrote ${path.relative(process.cwd(), OUT_MD)}`)
}

if (import.meta.url === pathToFileURL(process.argv[1] || '').href) {
  main().catch(error => {
    console.error(error)
    process.exitCode = 1
  })
}
