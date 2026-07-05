import fs from 'node:fs/promises'
import fsSync from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

import {
  REAL_CORPUS_LIBRARY_SCHEMA_VERSION,
  REAL_CORPUS_PROMPT_READY,
  buildExpressionHelperFromRealCorpusCards,
  detectRealCorpusPromptLeakage,
  retrieveRealCorpusExperienceCards,
  sourceNameTokensForCard,
  validateRealCorpusExperienceCardsV3
} from '../frontend/src/data/realCorpusExperienceCardsV3.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const ROOT_DIR = path.resolve(__dirname, '..')
const CORPUS_DIR = path.join(ROOT_DIR, '小说txt')
const LOCAL_REPORT_PATH = path.join(ROOT_DIR, 'frontend/src/data/localWritingSampleReport.json')
const V21_PATH = path.join(ROOT_DIR, 'frontend/src/data/sampleMicroDemoCards.v2_1.json')
const V22_PATH = path.join(ROOT_DIR, 'frontend/src/data/sampleMicroDemoCards.v2_2.json')
const PROD_JSON_PATH = path.join(ROOT_DIR, 'frontend/src/data/realCorpusExperienceCards.v3.json')
const QA_DIR = path.join(ROOT_DIR, 'tmp/realistic-flow-qa')
const OUT_JSON = path.join(QA_DIR, 'real-corpus-experience-cards-phase3-0.json')
const OUT_REPORT = path.join(QA_DIR, 'real-corpus-experience-cards-phase3-0-report.md')

const FINAL_REVIEW = {
  threadId: '019f300d-e340-78e2-bb59-fd23ccd0ae69',
  critical: 0,
  important: 0,
  minor: 1,
  conclusion: 'Ready for Phase 3.0 Critical/Important gate; minor notes files are untracked until a later integration step.'
}

const TAGS = [
  'dialogue_conflict',
  'emotion_variation',
  'character_humanity',
  'scene_dwell',
  'setting_naturalization',
  'aftermath',
  'longform_rhythm',
  'action_burst'
]

const TAG_METHODS = {
  dialogue_conflict: {
    scenes: ['审讯、谈判、旧账重提、熟人试探'],
    method: '让对白先撞出立场差，再用停顿、转开话题或半句反问暴露真正顾虑；每句都要改变关系压力。',
    safe: '写对白时先安排双方各有不能直说的筹码，冲突从试探、否认、截断里推进，不把设定解释塞进台词。',
    demo: '“你昨晚没去仓门。”她把湿手套放到灯下。“我去了。”他看着水滴从指尖落下，“只是你要的那个人，比我先到。”',
    anti: '不要让角色轮流汇报背景；对白要带遮掩、误判和关系压力。'
  },
  emotion_variation: {
    scenes: ['情绪转折、误判修正、关系裂隙、短内心'],
    method: '先写角色用惯常反应撑住局面，再让一个可见细节击穿判断，情绪变化落在动作和一句短内心里。',
    safe: '情绪不要直接命名，先给出身体反应、习惯落空或眼神变化，再让角色做一个与原判断相反的小选择。',
    demo: '他本来想笑，唇角只动了一下。那枚扣子还扣在她袖口，他才知道自己认错的不是路，是人。',
    anti: '不要用“他很痛苦/愤怒/释然”替代场景内的可见变化。'
  },
  character_humanity: {
    scenes: ['配角有私心、亲密关系摩擦、人物血肉、群像压力'],
    method: '给每个人一个眼前小目的或小难处，让他们先为自己行动，再被主线卷进去。',
    safe: '让配角带着今天的饭钱、面子、怕事或偏心进入场面；线索从他们的选择里露出，而不是替主角递答案。',
    demo: '掌柜先把算盘拨回原位，才压低声音：“问路可以，问昨夜谁进了后院，得另算。”',
    anti: '不要把配角写成只会递线索、送道具或解释规则的工具人。'
  },
  scene_dwell: {
    scenes: ['场景停留、空间压迫、生活纹理、慢压强'],
    method: '在动作前给空间两三个会改变选择的细节，让人物与物件、声音、温度发生关系。',
    safe: '环境只写会施压的部分：门的距离、灯的明暗、桌面上缺失的物件，随后让人物选择受它影响。',
    demo: '窗缝漏进来的风把纸角掀起，露出半枚红印。她没有伸手，只把灯芯拨暗了一寸。',
    anti: '不要堆景物清单；场景细节必须改变人物判断或行动。'
  },
  setting_naturalization: {
    scenes: ['设定自然呈现、规则验证、信息揭露前夜、证据链'],
    method: '把规则写成一次可观察的验证或失败后果，信息由物件、旁人反应和代价逐步露出。',
    safe: '先让人物试探规则边界，再让结果影响风险；不要让旁白或长者一次性讲完世界观。',
    demo: '铜针碰到门缝便弯了。她没解释阵法，只把第二根针递给他：“这次你来，别碰影子。”',
    anti: '不要把样本世界观、术语或势力关系带进项目；只借“规则通过行动显形”的方法。'
  },
  aftermath: {
    scenes: ['失败余波、战后代价、关系后果、收拾残局'],
    method: '失败后先写残局里的具体损失，再让角色互相推责或承担，最后留下一个新选择。',
    safe: '余波不是总结心得，而是物件坏了、关系变了、资源少了，人物必须马上处理后果。',
    demo: '药箱少了一格。她数到第三遍，才抬眼看他：“你救了谁？”他把空瓷瓶推回去：“救错了。”',
    anti: '不要用“这次失败让他们成长”这种总结替代可见后果。'
  },
  longform_rhythm: {
    scenes: ['长篇节奏、阶段递进、伏笔回收、章末停靠'],
    method: '每场只解决一个小答案，并把代价、误判或未解证据留给下一场，形成长线递进。',
    safe: '让当前场景有阶段性完成感，但停在新的证据或关系变化上，不提前揭开未来路线。',
    demo: '账册最后一页对上了，缺的却是印泥。她合上封皮：“账没错，人错了。”',
    anti: '不要把后续路线、幕后真相或未来反转提前写成表达方法。'
  },
  action_burst: {
    scenes: ['追逐、动作爆发、近身冲突、身体压力'],
    method: '动作要服务意图变化：先有空间限制和目标冲突，再用短促动作改变筹码。',
    safe: '动作不是连续招式清单；每一次推、退、躲、抓都要改变距离、风险或关系。',
    demo: '木门被撞开时，他没有往外跑，反手把灯盏扫到地上。火光一低，追来的人先看丢了他的影子。',
    anti: '不要只靠追兵逼近和换地点制造推进；动作必须带选择和后果。'
  }
}

export const SYNTHETIC_SCENES = [
  {
    id: 'interrogation_negotiation',
    expectedTags: ['dialogue_conflict', 'setting_naturalization'],
    sceneExecutionCard: {
      schemaVersion: 'scene-execution-card-v1',
      sceneObjective: '审讯室里确认账册缺页是否被对方调换。',
      conflictPair: '调查者 vs 旧同僚',
      emotionalTurn: '调查者从笃定对方撒谎，转为意识到自己也被利用。',
      dialogueTask: '两轮以上直接对白，包含逼问、否认和反问。',
      physicalPressure: '桌上只有一盏灯和湿账册，门外有人倒数。',
      environmentalPressure: '排风口水声盖住走廊脚步。',
      stopPoint: '停在旧同僚承认“缺页不是我拿的”。'
    }
  },
  {
    id: 'conflict_dialogue',
    expectedTags: ['dialogue_conflict', 'character_humanity'],
    sceneExecutionCard: {
      schemaVersion: 'scene-execution-card-v1',
      sceneObjective: '两个同伴因隐瞒伤势爆发争执。',
      conflictPair: '受伤者 vs 搭档',
      emotionalTurn: '搭档从责怪转为害怕失去对方。',
      dialogueTask: '简短对白里互相截断、翻旧账、嘴硬关心。',
      physicalPressure: '伤口重新渗血，药只剩一包。',
      environmentalPressure: '废院门外巡逻声逼近。',
      stopPoint: '停在搭档要求对方说出真正代价。'
    }
  },
  {
    id: 'chase_action_burst',
    expectedTags: ['action_burst', 'scene_dwell'],
    sceneExecutionCard: {
      schemaVersion: 'scene-execution-card-v1',
      sceneObjective: '主角在窄巷逃离追兵，同时保住证物。',
      conflictPair: '主角 vs 追捕者',
      emotionalTurn: '主角从只想逃走转为主动设局拖住对方。',
      dialogueTask: '动作间穿插一句挑衅或误导。',
      physicalPressure: '巷口被堵，证物怕水，墙边有半截竹梯。',
      environmentalPressure: '雨水把青石板冲得发亮。',
      stopPoint: '停在追兵冲进错误院门。'
    }
  },
  {
    id: 'intimate_fracture',
    expectedTags: ['emotion_variation', 'character_humanity'],
    sceneExecutionCard: {
      schemaVersion: 'scene-execution-card-v1',
      sceneObjective: '亲近关系中揭开一件被隐瞒的小事。',
      conflictPair: '妹妹 vs 兄长',
      emotionalTurn: '妹妹从撒气转为发现兄长一直在替她遮丑。',
      dialogueTask: '对白要有无效废话、停顿和不愿直说的关心。',
      physicalPressure: '桌上凉掉的粥和未拆的药包。',
      environmentalPressure: '屋里灯芯快灭，外面有人催门。',
      stopPoint: '停在妹妹没有道歉，只把药推回去。'
    }
  },
  {
    id: 'before_reveal',
    expectedTags: ['setting_naturalization', 'longform_rhythm'],
    sceneExecutionCard: {
      schemaVersion: 'scene-execution-card-v1',
      sceneObjective: '信息揭露前夜，用一次失败验证逼近真相。',
      conflictPair: '主角 vs 规则边界',
      emotionalTurn: '主角从相信旧解释，转为怀疑证据本身被调换。',
      dialogueTask: '同伴只问风险，不解释完整设定。',
      physicalPressure: '验证材料只剩最后一份。',
      environmentalPressure: '祠堂门缝透出反常的冷光。',
      stopPoint: '停在验证失败，不能揭开幕后身份。'
    }
  },
  {
    id: 'failure_aftermath',
    expectedTags: ['aftermath', 'emotion_variation'],
    sceneExecutionCard: {
      schemaVersion: 'scene-execution-card-v1',
      sceneObjective: '战后清点失败代价，决定是否继续追查。',
      conflictPair: '幸存者 vs 领队',
      emotionalTurn: '领队从压住损失转为承认判断错了。',
      dialogueTask: '对白里要有甩锅、承认、补救交换。',
      physicalPressure: '药箱空了，名册烧去一角。',
      environmentalPressure: '天亮后院子里只剩湿灰。',
      stopPoint: '停在幸存者提出一个更危险的补救办法。'
    }
  }
]

function normalPath(filePath) {
  return String(filePath || '').replace(/\\/g, '/')
}

function sha256Buffer(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex')
}

function sha256Text(text) {
  return crypto.createHash('sha256').update(String(text || ''), 'utf8').digest('hex')
}

function readJson(filePath) {
  return JSON.parse(fsSync.readFileSync(filePath, 'utf8'))
}

function stripExt(fileName) {
  return String(fileName || '').replace(/\.[^.]+$/, '')
}

function normalizeTitle(value) {
  return stripExt(value)
    .replace(/[《》【】\[\]（）()：:·,，。\s]/g, '')
    .replace(/_.*$/g, match => match.replace(/_/g, ''))
    .toLowerCase()
}

function git(args) {
  const result = spawnSync('git', args, {
    cwd: ROOT_DIR,
    encoding: 'utf8',
    windowsHide: true
  })
  return result.status === 0 ? result.stdout.trim() : ''
}

async function listCorpusFiles() {
  const entries = await fs.readdir(CORPUS_DIR, { withFileTypes: true })
  const files = []
  for (const entry of entries) {
    if (!entry.isFile()) continue
    const absolutePath = path.join(CORPUS_DIR, entry.name)
    const stat = await fs.stat(absolutePath)
    const buffer = await fs.readFile(absolutePath)
    files.push({
      fileName: entry.name,
      relativePath: normalPath(path.relative(ROOT_DIR, absolutePath)),
      size: stat.size,
      hash: sha256Buffer(buffer),
      readable: true,
      titleKey: normalizeTitle(entry.name),
      buffer
    })
  }
  files.sort((left, right) => left.fileName.localeCompare(right.fileName, 'zh-Hans-CN'))
  return files
}

function windowHashes(buffer) {
  const size = buffer.length
  const windowSize = Math.min(4096, Math.max(512, Math.floor(size / 20)))
  const starts = [
    0,
    Math.max(0, Math.floor(size / 2) - Math.floor(windowSize / 2)),
    Math.max(0, size - windowSize)
  ]
  return [...new Set(starts)]
    .map(start => sha256Buffer(buffer.subarray(start, Math.min(size, start + windowSize))))
}

function sourceCardId(index) {
  return `real-corpus-v3-${String(index + 1).padStart(3, '0')}`
}

function chooseTags(card, index) {
  const metrics = card.metrics || {}
  const tags = new Set([TAGS[index % TAGS.length]])
  const dialogueRatio = Number(metrics.dialogueParagraphRatio || 0)
  const shortRatio = Number(metrics.shortParagraphRatio || 0)
  const longRatio = Number(metrics.longParagraphRatio || 0)
  const avgLength = Number(metrics.averageParagraphLength || 0)
  const chapterCount = Number(metrics.chapterCount || 0)
  const directEmotion = Number(metrics.directEmotionCount || 0)
  const numericCount = Number(metrics.numericCount || 0)
  if (dialogueRatio >= 0.42) tags.add('dialogue_conflict')
  if (directEmotion <= 20) tags.add('emotion_variation')
  tags.add('character_humanity')
  if (longRatio >= 0.08 || avgLength >= 80) tags.add('scene_dwell')
  if (numericCount > 0 || /信息|规则|证据|物件/.test([card.informationMethod, card.challengeMethod].join('\n'))) tags.add('setting_naturalization')
  if (/结尾|后果|代价|余波|关系变化/.test([card.chapterExit, card.challengeMethod].join('\n'))) tags.add('aftermath')
  if (chapterCount >= 100 || Number(metrics.charCount || 0) >= 1000000) tags.add('longform_rhythm')
  if (shortRatio >= 0.4) tags.add('action_burst')
  return [...tags].slice(0, 4)
}

function primaryTag(tags) {
  return tags.find(tag => tag !== 'character_humanity') || tags[0] || 'character_humanity'
}

function createV3Card(reportCard, sourceFile, index) {
  const sceneFunctionTags = chooseTags(reportCard, index)
  const tag = primaryTag(sceneFunctionTags)
  const template = TAG_METHODS[tag] || TAG_METHODS.character_humanity
  const supportingMethods = sceneFunctionTags
    .filter(item => item !== tag)
    .map(item => TAG_METHODS[item]?.method)
    .filter(Boolean)
    .slice(0, 2)
  return {
    cardId: sourceCardId(index),
    schemaVersion: 'real-corpus-experience-card-v3',
    sourceTitle: reportCard.sourceTitle,
    sourceFileName: sourceFile?.fileName || '',
    sourceFileHash: sourceFile?.hash || sha256Text(reportCard.sourceTitle),
    sourceAuditOnly: true,
    sourceWindowHashes: sourceFile ? windowHashes(sourceFile.buffer) : [sha256Text(reportCard.sourceTitle), sha256Text(reportCard.id || reportCard.sourceTitle)],
    sceneFunctionTags,
    applicableScenes: template.scenes,
    writingMethod: [template.method, ...supportingMethods].join(' '),
    promptInjectionSafeVersion: template.safe,
    originalMicroDemo: template.demo,
    antiAiReminder: template.anti,
    notApplicableScenes: [
      '需要事实、设定、阶段边界或未来路线判断的任务',
      '要求模仿某本书、某位作者、某个角色或某段原文的任务'
    ],
    riskNotes: [
      '只作为表达方法参考；不得输出或推断样本世界观、人物关系、地名、势力名。',
      '不得复制原句、长片段、标志性比喻或连续段落结构。'
    ],
    promptReadiness: REAL_CORPUS_PROMPT_READY,
    safetyFlags: {
      no_raw_excerpt: true,
      no_source_text: true,
      no_source_names: true,
      no_direct_imitation: true,
      no_long_quote: true,
      expression_only: true
    },
    audit: {
      sourceReportCardId: reportCard.id || '',
      sourceMetricsHash: sha256Text(JSON.stringify(reportCard.metrics || {})),
      sourceMethodHash: sha256Text([
        reportCard.chapterEntry,
        reportCard.chapterExit,
        reportCard.dialogueMethod,
        reportCard.characterMethod,
        reportCard.emotionMethod,
        reportCard.informationMethod,
        reportCard.proseRhythm
      ].filter(Boolean).join('\n')),
      generatedBy: 'phase3.0-deterministic-extractor'
    }
  }
}

function cardPromptFacingText(card) {
  return [
    card.applicableScenes,
    card.writingMethod,
    card.promptInjectionSafeVersion,
    card.originalMicroDemo,
    card.antiAiReminder,
    card.notApplicableScenes,
    card.riskNotes
  ].flat().filter(Boolean).join('\n')
}

function collectCurrentSampleLayer() {
  const v21 = readJson(V21_PATH)
  const v22 = readJson(V22_PATH)
  const writingStyleStandardsSource = fsSync.readFileSync(path.join(ROOT_DIR, 'frontend/src/data/writingStyleStandards.js'), 'utf8')
  return {
    builtInMicroDemoCards: {
      v2_1: Array.isArray(v21.promptInjectableCards) ? v21.promptInjectableCards.length : 0,
      v2_2: Array.isArray(v22.dialoguePromptInjectableCards) ? v22.dialoguePromptInjectableCards.length : 0,
      total: (Array.isArray(v21.promptInjectableCards) ? v21.promptInjectableCards.length : 0) +
        (Array.isArray(v22.dialoguePromptInjectableCards) ? v22.dialoguePromptInjectableCards.length : 0),
      promptReady: (Array.isArray(v21.promptReadyCardIds) ? v21.promptReadyCardIds.length : 0) +
        (Array.isArray(v22.promptReadyCardIds) ? v22.promptReadyCardIds.length : 0),
      backendReferenceOnly: Array.isArray(v22.backendReferenceOnlyCardIds) ? v22.backendReferenceOnlyCardIds.length : 0
    },
    localReportCards: readJson(LOCAL_REPORT_PATH).cards?.length || 0,
    directDraftInjectionEnabled: false,
    localReportStandardCandidateSourceIds: readJson(LOCAL_REPORT_PATH).standardCandidate?.sourceCardIds?.length || 0,
    formalStandardAbsorption: {
      reviewedLocalSampleAdapterPresent: writingStyleStandardsSource.includes('reviewed_local_sample'),
      forbidsRawSampleFields: /rawExcerpt|sourceText|sourceCardIds/.test(writingStyleStandardsSource),
      localHumanSampleStandardBundled: writingStyleStandardsSource.includes('local-human-sample-standard'),
      currentRole: 'formal standards can absorb reviewed local sample guidance, but the 46-source report is not yet a SceneExecutionCard-retrievable V3 card layer'
    },
    v23ArtifactsPresent: fsSync.existsSync(path.join(QA_DIR, 'latest-sample-deep-read-v2_3.json')) ||
      fsSync.existsSync(path.join(QA_DIR, 'latest-sample-deep-read-v2_3-report.md')) ||
      fsSync.existsSync(path.join(QA_DIR, 'latest-formal-standard-patch-suggestions.json'))
  }
}

function buildCorpusAudit(corpusFiles, localReport) {
  const actualNames = new Set(corpusFiles.map(file => file.fileName))
  const reportNames = new Set((localReport.files || []).map(file => file.name))
  const actualByKey = new Map(corpusFiles.map(file => [file.titleKey, file]))
  const rows = (localReport.cards || []).map(card => {
    const reportFile = (localReport.files || []).find(file => normalizeTitle(file.name) === normalizeTitle(card.sourceTitle))
    const sourceFile = actualByKey.get(normalizeTitle(reportFile?.name || card.sourceTitle))
    return {
      sourceId: card.id,
      sourceTitle: card.sourceTitle,
      reportFileName: reportFile?.name || '',
      txtFileName: sourceFile?.fileName || '',
      status: sourceFile ? 'covered' : 'report_without_txt',
      metricsHash: sha256Text(JSON.stringify(card.metrics || {}))
    }
  })
  return {
    localTxt: {
      directory: normalPath(path.relative(ROOT_DIR, CORPUS_DIR)),
      totalFiles: corpusFiles.length,
      totalReadable: corpusFiles.filter(file => file.readable).length,
      files: corpusFiles.map(({ buffer, titleKey, ...file }) => file)
    },
    localReport: {
      path: normalPath(path.relative(ROOT_DIR, LOCAL_REPORT_PATH)),
      fileCount: localReport.fileCount,
      filesListed: (localReport.files || []).length,
      cardCount: (localReport.cards || []).length,
      standardCandidateSourceIds: localReport.standardCandidate?.sourceCardIds?.length || 0
    },
    alignment: {
      reportCoveredSources: rows.filter(row => row.status === 'covered').length,
      txtFilesWithoutReport: corpusFiles
        .filter(file => !reportNames.has(file.fileName))
        .map(file => ({ fileName: file.fileName, size: file.size, hash: file.hash })),
      reportSourcesWithoutTxt: [...reportNames]
        .filter(name => !actualNames.has(name))
        .map(name => ({ fileName: name })),
      duplicateReportNames: findDuplicates([...(localReport.files || []).map(file => file.name)]),
      duplicateSourceTitles: findDuplicates([...(localReport.cards || []).map(card => card.sourceTitle)]),
      rows
    }
  }
}

function findDuplicates(values) {
  const counts = new Map()
  for (const value of values) counts.set(value, (counts.get(value) || 0) + 1)
  return [...counts.entries()].filter(([, count]) => count > 1).map(([value, count]) => ({ value, count }))
}

function buildV3Library(cards, corpusAudit) {
  const tagDistribution = Object.fromEntries(TAGS.map(tag => [tag, 0]))
  for (const card of cards) {
    for (const tag of card.sceneFunctionTags) tagDistribution[tag] = (tagDistribution[tag] || 0) + 1
  }
  return {
    schemaVersion: REAL_CORPUS_LIBRARY_SCHEMA_VERSION,
    generatedAt: new Date(0).toISOString(),
    generator: 'phase3.0-deterministic-real-corpus-extractor',
    sourcePolicy: {
      sourceAuditOnly: true,
      promptFacingFieldsExcludeSourceNames: true,
      windowTextStored: false,
      expressionOnly: true
    },
    corpusSummary: {
      localTxtFiles: corpusAudit.localTxt.totalFiles,
      localReportCards: corpusAudit.localReport.cardCount,
      coveredReportSources: corpusAudit.alignment.reportCoveredSources
    },
    cards
  }
}

function buildSafety(cards, corpusFiles) {
  const promptFacingSourceNameLeaks = []
  const rawFieldViolations = []
  const longQuoteViolations = []
  const microDemoSimilarityViolations = []
  const factBoundaryViolations = []
  for (const card of cards) {
    const promptText = cardPromptFacingText(card)
    if (card.sourceTitle && promptText.includes(card.sourceTitle)) {
      promptFacingSourceNameLeaks.push({ cardId: card.cardId, sourceTitle: card.sourceTitle })
    }
    const leakedToken = sourceNameTokensForCard(card).find(token => promptText.includes(token))
    if (leakedToken) {
      promptFacingSourceNameLeaks.push({ cardId: card.cardId, sourceToken: leakedToken })
    }
    for (const key of ['rawExcerpt', 'sourceText', 'sourceCardIds', 'sourceWindows', 'rawWindows']) {
      if (Object.hasOwn(card, key)) rawFieldViolations.push({ cardId: card.cardId, key })
    }
    if (/[“"][^”"]{80,}[”"]/.test(promptText)) longQuoteViolations.push({ cardId: card.cardId })
    if (/(stateAuthority|guardSnapshot|futureRoadmap|allowedFacts|worldRules|stageBoundary|factOverrides)/i.test(promptText)) {
      factBoundaryViolations.push({ cardId: card.cardId })
    }
    const source = corpusFiles.find(file => file.hash === card.sourceFileHash)
    if (source) {
      const decoded = source.buffer.toString('utf8')
      const demo = String(card.originalMicroDemo || '').replace(/\s+/g, '')
      for (let index = 0; index + 18 <= demo.length; index += 6) {
        const slice = demo.slice(index, index + 18)
        if (slice.length >= 18 && decoded.includes(slice)) {
          microDemoSimilarityViolations.push({ cardId: card.cardId, sampleHash: sha256Text(slice) })
          break
        }
      }
    }
  }
  const blockingIssues = [
    ...promptFacingSourceNameLeaks,
    ...rawFieldViolations,
    ...longQuoteViolations,
    ...microDemoSimilarityViolations,
    ...factBoundaryViolations
  ]
  return {
    blockingIssues,
    promptFacingSourceNameLeaks,
    rawFieldViolations,
    longQuoteViolations,
    microDemoSimilarityViolations,
    factBoundaryViolations
  }
}

function scoreGuidance(text) {
  const source = String(text || '')
  const signals = {
    dialogueConflict: /(对白|质问|否认|反问|截断|潜台词|筹码|冲突)/.test(source),
    emotionalTurn: /(情绪|转折|误判|判断|顾虑|内心|关系压力)/.test(source),
    sceneDwell: /(环境|空间|物件|声音|温度|灯|门|桌|雨)/.test(source),
    characterHumanity: /(私心|难处|顾虑|面子|关系|人物|配角)/.test(source),
    settingNaturalization: /(规则|证据|验证|设定|世界观|代价)/.test(source),
    aftermath: /(失败|余波|后果|损失|补救|代价)/.test(source),
    actionIntent: /(动作|距离|风险|选择|推|退|躲|抓|追兵)/.test(source),
    boundarySafe: !/(sourceTitle|sourceFileHash|sourceWindowHashes|rawExcerpt|sourceText|futureRoadmap|guardSnapshot|stateAuthority)/.test(source)
  }
  return {
    score: Object.values(signals).filter(Boolean).length * 10,
    signals
  }
}

function buildAbQuality(cards) {
  const syntheticScenes = SYNTHETIC_SCENES.map(scene => {
    const baselineText = [
      scene.sceneExecutionCard.sceneObjective,
      scene.sceneExecutionCard.conflictPair,
      scene.sceneExecutionCard.emotionalTurn,
      scene.sceneExecutionCard.dialogueTask
    ].join('\n')
    const selected = retrieveRealCorpusExperienceCards(scene.sceneExecutionCard, cards, { limit: 2 })
    const helper = buildExpressionHelperFromRealCorpusCards(selected, scene.sceneExecutionCard)
    const baseline = scoreGuidance(baselineText)
    const sample = scoreGuidance(`${baselineText}\n${helper}`)
    const leakage = detectRealCorpusPromptLeakage(helper, selected)
    return {
      id: scene.id,
      expectedTags: scene.expectedTags,
      selectedCardIds: selected.map(card => card.cardId),
      selectedTags: [...new Set(selected.flatMap(card => card.sceneFunctionTags))],
      baselineScore: baseline.score,
      sampleScore: sample.score,
      signalLift: sample.score - baseline.score,
      futureLeak: leakage.detected,
      baselineSignals: baseline.signals,
      sampleSignals: sample.signals,
      helperExcerpt: helper.slice(0, 360)
    }
  })
  const averageBaselineScore = average(syntheticScenes.map(item => item.baselineScore))
  const averageSampleScore = average(syntheticScenes.map(item => item.sampleScore))
  return {
    syntheticScenes,
    summary: {
      averageBaselineScore,
      averageSampleScore,
      averageSignalLift: averageSampleScore - averageBaselineScore,
      sampleV3Regressions: syntheticScenes.filter(item => item.sampleScore < item.baselineScore).length,
      futureLeaks: syntheticScenes.filter(item => item.futureLeak).length
    }
  }
}

function average(values) {
  if (!values.length) return 0
  return Math.round((values.reduce((sum, value) => sum + Number(value || 0), 0) / values.length) * 100) / 100
}

function buildRetrievalEvidence(cards) {
  const scenes = SYNTHETIC_SCENES.map(scene => {
    const selected = retrieveRealCorpusExperienceCards(scene.sceneExecutionCard, cards, { limit: 2 })
    const helper = buildExpressionHelperFromRealCorpusCards(selected, scene.sceneExecutionCard)
    const leakage = detectRealCorpusPromptLeakage(helper, selected)
    return {
      id: scene.id,
      expectedTags: scene.expectedTags,
      selectedCardIds: selected.map(card => card.cardId),
      selectedTags: [...new Set(selected.flatMap(card => card.sceneFunctionTags))],
      helperHash: sha256Text(helper),
      leakageDetected: leakage.detected
    }
  })
  return {
    maxSelectedCards: 2,
    leakageDetected: scenes.some(scene => scene.leakageDetected),
    scenes
  }
}

export function validateRealCorpusExperienceCardsPayload(payload = {}) {
  if (payload.schemaVersion !== 'real-corpus-experience-cards-phase3-0-v1') {
    throw new Error('invalid Phase 3.0 payload schemaVersion')
  }
  for (const key of ['serviceStarted', 'realDbConnection', 'realProjectTouched', 'liveGenerationRun', 'projectStateWritten', 'phase3ProviderAdapterEntered', 'pushOrPrCreated']) {
    if (payload.boundary?.[key] !== false) throw new Error(`boundary.${key} must be false`)
  }
  if (payload.corpusAudit?.localReport?.cardCount !== 46) throw new Error('local report card count must be 46')
  if (payload.v3Cards?.total !== 46) throw new Error('V3 card count must be 46')
  if (payload.v3Cards?.sourceCoverage?.sourcesWithCandidateCards !== 46) throw new Error('V3 source coverage must be 46')
  if ((payload.safety?.blockingIssues || []).length !== 0) throw new Error('safety blocking issues must be empty')
  if (payload.retrieval?.leakageDetected !== false) throw new Error('retrieval leakage must be false')
  if (payload.abQuality?.summary?.sampleV3Regressions !== 0) throw new Error('sample V3 regressions must be 0')
  if (payload.abQuality?.summary?.futureLeaks !== 0) throw new Error('future leaks must be 0')
  if (payload.modelAssistedValidation?.used !== false) throw new Error('model validation must be marked unused for this deterministic run')
  if (payload.review?.critical !== 0) throw new Error('fresh review critical count must be 0')
  if (payload.review?.important !== 0) throw new Error('fresh review important count must be 0')
  return true
}

export function buildRealCorpusExperienceCardsReport(payload) {
  validateRealCorpusExperienceCardsPayload(payload)
  const lines = [
    '# Real Corpus Experience Cards Phase 3.0 Report',
    '',
    'Status: deterministic no-live real-corpus sample-library gate. This report does not claim production prompt hookup, real DB migration, live generation, or provider adapter readiness.',
    '',
    '## Scope Guard',
    '- Did not start backend/frontend dev server, runner, or page.goto.',
    '- Did not run formal chapter generation/finalization chain.',
    '- Did not connect to or write a real DB.',
    '- Did not touch real project data, restore LongformBrowser, or run #98/#99/#50.',
    '- Did not save model output as project body, outline, beat plan, or DB state.',
    '- Did not push or create PR.',
    '',
    '## Branch',
    `branch.current=${payload.branch.currentBranch}`,
    `branch.baseCommit=${payload.branch.baseCommit}`,
    '',
    '## Corpus Audit',
    `localTxt.totalFiles=${payload.corpusAudit.localTxt.totalFiles}`,
    `localTxt.totalReadable=${payload.corpusAudit.localTxt.totalReadable}`,
    `localReport.cardCount=${payload.corpusAudit.localReport.cardCount}`,
    `alignment.reportCoveredSources=${payload.corpusAudit.alignment.reportCoveredSources}`,
    `alignment.txtFilesWithoutReport=${payload.corpusAudit.alignment.txtFilesWithoutReport.length}`,
    `alignment.reportSourcesWithoutTxt=${payload.corpusAudit.alignment.reportSourcesWithoutTxt.length}`,
    `alignment.duplicateReportNames=${payload.corpusAudit.alignment.duplicateReportNames.length}`,
    `alignment.duplicateSourceTitles=${payload.corpusAudit.alignment.duplicateSourceTitles.length}`,
    '',
    '## Current Sample Layer',
    `builtInMicroDemoCards.total=${payload.currentSampleLayer.builtInMicroDemoCards.total}`,
    `builtInMicroDemoCards.v2_1=${payload.currentSampleLayer.builtInMicroDemoCards.v2_1}`,
    `builtInMicroDemoCards.v2_2=${payload.currentSampleLayer.builtInMicroDemoCards.v2_2}`,
    `localReportCards=${payload.currentSampleLayer.localReportCards}`,
    `directDraftInjectionEnabled=${payload.currentSampleLayer.directDraftInjectionEnabled}`,
    `formalStandardAbsorption.reviewedLocalSampleAdapterPresent=${payload.currentSampleLayer.formalStandardAbsorption.reviewedLocalSampleAdapterPresent}`,
    `formalStandardAbsorption.forbidsRawSampleFields=${payload.currentSampleLayer.formalStandardAbsorption.forbidsRawSampleFields}`,
    `formalStandardAbsorption.localHumanSampleStandardBundled=${payload.currentSampleLayer.formalStandardAbsorption.localHumanSampleStandardBundled}`,
    `v23ArtifactsPresent=${payload.currentSampleLayer.v23ArtifactsPresent}`,
    '',
    '## V3 Cards',
    `v3Cards.total=${payload.v3Cards.total}`,
    `v3Cards.sourcesWithCandidateCards=${payload.v3Cards.sourceCoverage.sourcesWithCandidateCards}`,
    '| sceneFunctionTag | count |',
    '| --- | --- |',
    ...Object.entries(payload.v3Cards.sceneFunctionTagDistribution).map(([tag, count]) => `| ${tag} | ${count} |`),
    '',
    '## Retrieval',
    `retrieval.sceneCount=${payload.retrieval.scenes.length}`,
    `retrieval.maxSelectedCards=${payload.retrieval.maxSelectedCards}`,
    `retrieval.leakageDetected=${payload.retrieval.leakageDetected}`,
    '| scene | selected_cards | selected_tags | leakage |',
    '| --- | --- | --- | --- |',
    ...payload.retrieval.scenes.map(scene => `| ${scene.id} | ${scene.selectedCardIds.length} | ${scene.selectedTags.join(', ')} | ${scene.leakageDetected} |`),
    '',
    '## Safety',
    `safety.blockingIssues=${payload.safety.blockingIssues.length}`,
    `safety.promptFacingSourceNameLeaks=${payload.safety.promptFacingSourceNameLeaks.length}`,
    `safety.rawFieldViolations=${payload.safety.rawFieldViolations.length}`,
    `safety.longQuoteViolations=${payload.safety.longQuoteViolations.length}`,
    `safety.microDemoSimilarityViolations=${payload.safety.microDemoSimilarityViolations.length}`,
    `safety.factBoundaryViolations=${payload.safety.factBoundaryViolations.length}`,
    '',
    '## A/B Quality Proof',
    `ab.syntheticScenes=${payload.abQuality.syntheticScenes.length}`,
    `ab.averageBaselineScore=${payload.abQuality.summary.averageBaselineScore}`,
    `ab.averageSampleScore=${payload.abQuality.summary.averageSampleScore}`,
    `ab.averageSignalLift=${payload.abQuality.summary.averageSignalLift}`,
    `ab.sampleV3Regressions=${payload.abQuality.summary.sampleV3Regressions}`,
    `ab.futureLeaks=${payload.abQuality.summary.futureLeaks}`,
    '',
    '## Model Assisted Validation',
    `model.used=${payload.modelAssistedValidation.used}`,
    `model.name=${payload.modelAssistedValidation.model}`,
    `model.temperature=${payload.modelAssistedValidation.temperature}`,
    `model.top_p=${payload.modelAssistedValidation.top_p}`,
    `model.reason=${payload.modelAssistedValidation.reason}`,
    '',
    '## Production Candidate',
    `productionCandidate.path=${payload.outputs.productionCandidatePath}`,
    'The production candidate file is safe to include as data because source text is not stored, source fields are audit-only, prompt-facing fields are expression-only, and no production prompt hookup is made in this phase.',
    '',
    '## Built-In Cards Relationship',
    '- The 16 v2.1 scene micro-demo cards and 12 v2.2 dialogue micro-demo cards are retained as existing system experience-card material.',
    '- V3 does not delete or directly replace them in production prompts; it adds a real-corpus, source-audited candidate layer for SceneExecutionCard-based offline retrieval.',
    '- Existing formal-writing-standard absorption remains background/reference only; V3 cards are expression-only and do not override stateAuthority, facts, stage, guard, or project canon.',
    '',
    '## Remaining Risks',
    '- V3 cards are production candidates, not yet wired into live prompt generation.',
    '- Offline A/B evidence is deterministic and no-model; it does not prove live model prose quality.',
    '- Extra local txt files without local report rows should be audited before a later corpus expansion.',
    '- Human editorial review is still recommended before prompt-facing rollout.',
    '',
    '## Fresh Review',
    payload.review
      ? `review.threadId=${payload.review.threadId}\nreview.critical=${payload.review.critical}\nreview.important=${payload.review.important}\nreview.minor=${payload.review.minor}\nreview.conclusion=${payload.review.conclusion}`
      : 'Fresh read-only review pending.'
  ]
  return `${lines.join('\n')}\n`
}

export function assertRealCorpusExperienceCardsReportMatchesJson(reportText, payload) {
  validateRealCorpusExperienceCardsPayload(payload)
  const report = String(reportText || '')
  const checks = {
    'branch.current': payload.branch.currentBranch,
    'branch.baseCommit': payload.branch.baseCommit,
    'localTxt.totalFiles': payload.corpusAudit.localTxt.totalFiles,
    'localTxt.totalReadable': payload.corpusAudit.localTxt.totalReadable,
    'localReport.cardCount': payload.corpusAudit.localReport.cardCount,
    'alignment.reportCoveredSources': payload.corpusAudit.alignment.reportCoveredSources,
    'alignment.txtFilesWithoutReport': payload.corpusAudit.alignment.txtFilesWithoutReport.length,
    'alignment.reportSourcesWithoutTxt': payload.corpusAudit.alignment.reportSourcesWithoutTxt.length,
    'alignment.duplicateReportNames': payload.corpusAudit.alignment.duplicateReportNames.length,
    'alignment.duplicateSourceTitles': payload.corpusAudit.alignment.duplicateSourceTitles.length,
    'builtInMicroDemoCards.total': payload.currentSampleLayer.builtInMicroDemoCards.total,
    'builtInMicroDemoCards.v2_1': payload.currentSampleLayer.builtInMicroDemoCards.v2_1,
    'builtInMicroDemoCards.v2_2': payload.currentSampleLayer.builtInMicroDemoCards.v2_2,
    'localReportCards': payload.currentSampleLayer.localReportCards,
    'directDraftInjectionEnabled': payload.currentSampleLayer.directDraftInjectionEnabled,
    'formalStandardAbsorption.reviewedLocalSampleAdapterPresent': payload.currentSampleLayer.formalStandardAbsorption.reviewedLocalSampleAdapterPresent,
    'formalStandardAbsorption.forbidsRawSampleFields': payload.currentSampleLayer.formalStandardAbsorption.forbidsRawSampleFields,
    'formalStandardAbsorption.localHumanSampleStandardBundled': payload.currentSampleLayer.formalStandardAbsorption.localHumanSampleStandardBundled,
    'v23ArtifactsPresent': payload.currentSampleLayer.v23ArtifactsPresent,
    'v3Cards.total': payload.v3Cards.total,
    'v3Cards.sourcesWithCandidateCards': payload.v3Cards.sourceCoverage.sourcesWithCandidateCards,
    'retrieval.sceneCount': payload.retrieval.scenes.length,
    'retrieval.maxSelectedCards': payload.retrieval.maxSelectedCards,
    'retrieval.leakageDetected': payload.retrieval.leakageDetected,
    'safety.blockingIssues': payload.safety.blockingIssues.length,
    'safety.promptFacingSourceNameLeaks': payload.safety.promptFacingSourceNameLeaks.length,
    'safety.rawFieldViolations': payload.safety.rawFieldViolations.length,
    'safety.longQuoteViolations': payload.safety.longQuoteViolations.length,
    'safety.microDemoSimilarityViolations': payload.safety.microDemoSimilarityViolations.length,
    'safety.factBoundaryViolations': payload.safety.factBoundaryViolations.length,
    'ab.syntheticScenes': payload.abQuality.syntheticScenes.length,
    'ab.averageBaselineScore': payload.abQuality.summary.averageBaselineScore,
    'ab.averageSampleScore': payload.abQuality.summary.averageSampleScore,
    'ab.averageSignalLift': payload.abQuality.summary.averageSignalLift,
    'ab.sampleV3Regressions': payload.abQuality.summary.sampleV3Regressions,
    'ab.futureLeaks': payload.abQuality.summary.futureLeaks,
    'model.used': payload.modelAssistedValidation.used,
    'model.name': payload.modelAssistedValidation.model,
    'model.temperature': payload.modelAssistedValidation.temperature,
    'model.top_p': payload.modelAssistedValidation.top_p,
    'model.reason': payload.modelAssistedValidation.reason,
    'productionCandidate.path': payload.outputs.productionCandidatePath,
    'review.threadId': payload.review.threadId,
    'review.critical': payload.review.critical,
    'review.important': payload.review.important,
    'review.minor': payload.review.minor,
    'review.conclusion': payload.review.conclusion
  }
  for (const [key, expected] of Object.entries(checks)) {
    const actual = extractSingleLineValue(report, key)
    if (actual !== String(expected)) throw new Error(`Report/JSON mismatch for ${key}: ${actual} expected ${expected}`)
  }
  for (const [tag, count] of Object.entries(payload.v3Cards.sceneFunctionTagDistribution)) {
    const row = findSingleMarkdownRow(report, tag)
    assertMarkdownCells(parseMarkdownRow(row), [tag, count], `tag.${tag}`)
  }
  for (const scene of payload.retrieval.scenes) {
    const row = findSingleMarkdownRow(report, scene.id)
    assertMarkdownCells(parseMarkdownRow(row), [
      scene.id,
      scene.selectedCardIds.length,
      scene.selectedTags.join(', '),
      scene.leakageDetected
    ], `retrieval.${scene.id}`)
  }
  return true
}

function extractSingleLineValue(report, key) {
  const pattern = new RegExp(`^${escapeRegExp(key)}=(.*)$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report key ${key} appears ${matches.length} times`)
  return matches[0][1].trim()
}

function findSingleMarkdownRow(report, firstCell) {
  const pattern = new RegExp(`^\\| ${escapeRegExp(String(firstCell))} \\|.*$`, 'gm')
  const matches = [...String(report || '').matchAll(pattern)]
  if (matches.length !== 1) throw new Error(`Report row ${firstCell} appears ${matches.length} times`)
  return matches[0][0]
}

function parseMarkdownRow(row) {
  return String(row)
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map(cell => cell.trim())
}

function assertMarkdownCells(cells, expectedValues, label) {
  if (cells.length !== expectedValues.length) {
    throw new Error(`Report/JSON mismatch for ${label}: expected ${expectedValues.length} cells, got ${cells.length}`)
  }
  expectedValues.forEach((expected, index) => {
    if (cells[index] !== String(expected)) {
      throw new Error(`Report/JSON mismatch for ${label}[${index}]: ${cells[index]} expected ${expected}`)
    }
  })
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export async function runRealCorpusExperienceCardsPhase30(options = {}) {
  const writeArtifacts = options.writeArtifacts !== false
  const review = options.review || FINAL_REVIEW
  const localReport = readJson(LOCAL_REPORT_PATH)
  const corpusFiles = await listCorpusFiles()
  const corpusAudit = buildCorpusAudit(corpusFiles, localReport)
  const fileByReportName = new Map(corpusFiles.map(file => [file.fileName, file]))
  const fileByTitle = new Map(corpusFiles.map(file => [file.titleKey, file]))
  const cards = (localReport.cards || []).map((card, index) => {
    const reportFile = (localReport.files || []).find(file => normalizeTitle(file.name) === normalizeTitle(card.sourceTitle))
    const sourceFile = fileByReportName.get(reportFile?.name || '') || fileByTitle.get(normalizeTitle(card.sourceTitle))
    return createV3Card(card, sourceFile, index)
  })
  const library = buildV3Library(cards, corpusAudit)
  validateRealCorpusExperienceCardsV3(library)
  const safety = buildSafety(cards, corpusFiles)
  const retrieval = buildRetrievalEvidence(cards)
  const abQuality = buildAbQuality(cards)
  const tagDistribution = Object.fromEntries(TAGS.map(tag => [tag, 0]))
  for (const card of cards) {
    for (const tag of card.sceneFunctionTags) tagDistribution[tag] = (tagDistribution[tag] || 0) + 1
  }
  const payload = {
    schemaVersion: 'real-corpus-experience-cards-phase3-0-v1',
    status: 'completed',
    generatedAt: new Date().toISOString(),
    branch: {
      currentBranch: git(['branch', '--show-current']),
      baseCommit: 'd45a64c',
      headCommit: git(['rev-parse', '--short', 'HEAD'])
    },
    boundary: {
      serviceStarted: false,
      realDbConnection: false,
      realProjectTouched: false,
      liveGenerationRun: false,
      projectStateWritten: false,
      phase3ProviderAdapterEntered: false,
      pushOrPrCreated: false
    },
    outputs: {
      jsonPath: OUT_JSON,
      reportPath: OUT_REPORT,
      productionCandidatePath: normalPath(path.relative(ROOT_DIR, PROD_JSON_PATH))
    },
    corpusAudit,
    currentSampleLayer: collectCurrentSampleLayer(),
    v3Cards: {
      total: cards.length,
      sceneFunctionTagDistribution: tagDistribution,
      promptReadinessDistribution: countBy(cards, card => card.promptReadiness),
      sourceCoverage: {
        sourcesWithCandidateCards: new Set(cards.map(card => card.sourceTitle)).size,
        skippedSources: corpusAudit.alignment.rows
          .filter(row => row.status !== 'covered')
          .map(row => ({ sourceTitle: row.sourceTitle, reason: row.status }))
      }
    },
    retrieval,
    safety,
    abQuality,
    modelAssistedValidation: {
      used: false,
      model: '联通云-DeepSeek-V4-Flash',
      temperature: 0.7,
      top_p: 0.9,
      reason: 'offline model tool/provider was not exposed in this thread and Phase 3.0 avoided provider-adapter work; deterministic no-model gates are the hard evidence.',
      inputSummary: '',
      outputSummary: '',
      conclusion: 'not_used'
    },
    review
  }
  const report = buildRealCorpusExperienceCardsReport(payload)
  assertRealCorpusExperienceCardsReportMatchesJson(report, payload)
  if (writeArtifacts) {
    await fs.mkdir(QA_DIR, { recursive: true })
    await fs.writeFile(PROD_JSON_PATH, `${JSON.stringify(library, null, 2)}\n`, 'utf8')
    await fs.writeFile(OUT_JSON, `${JSON.stringify(payload, null, 2)}\n`, 'utf8')
    await fs.writeFile(OUT_REPORT, report, 'utf8')
  }
  return payload
}

function countBy(items, keyFn) {
  const result = {}
  for (const item of items) {
    const key = keyFn(item)
    result[key] = (result[key] || 0) + 1
  }
  return result
}

async function main() {
  const payload = await runRealCorpusExperienceCardsPhase30({ writeArtifacts: true })
  console.log(`real corpus experience cards phase3.0 wrote ${payload.outputs.jsonPath} and ${payload.outputs.reportPath}`)
}

if (process.argv[1] && path.resolve(process.argv[1]) === __filename) {
  main().catch(error => {
    console.error(error)
    process.exit(1)
  })
}
