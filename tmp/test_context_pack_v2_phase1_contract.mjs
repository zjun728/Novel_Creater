import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  assertContextPackHealthy,
  buildContextPackV2,
  buildCreativeContextFromPack,
  lintNarrativeVoiceContract
} from '../frontend/src/utils/contextPackV2.js'
import { buildWritingContext } from '../frontend/src/utils/contextBuilder.js'
import { buildDraftPrompt } from '../frontend/src/prompts/chapterDraftPrompt.js'

const POLLUTED_ENTITY = '污染实体-第98失败稿'
const POLLUTED_EVENT = '失败候选把铜镜写成龙门'
const POLLUTED_THREAD = '失败候选伏笔线'
const FAILED_RELATION = '失败候选关系：白玉钥匙已经归污染实体'
const NO_ID_REJECTED_FACT = '无ID失败候选事实不应作为 rejected target 泄漏'
const NO_ID_REJECTED_ENTITY = '无ID失败候选实体名称不应泄漏'
const FUTURE_SECRET = '第100章才揭示祖母是真正门主'
const GUARD_ONLY_FORBIDDEN = 'guard-only: 不得提前写祖母门主身份'
const CONFLICTING_SAVED_PLAN = '第97章小纲曾计划白玉钥匙被赵青夺走'
const FINAL_FACT = '第97章定稿正文确认白玉钥匙仍在林逐掌心，剩余一次。'

const novelStore = {
  bible: {
    premise: '主角以考据破解异常规则。',
    worldRules: '所有代价必须有来源和后果。',
    styleBible: '冷静、具体、少解释。',
    forbiddenDirections: [GUARD_ONLY_FORBIDDEN],
    writingProfile: { primaryStandard: 'rational-fantasy' }
  },
  outline: {
    nearChapters: [
      {
        chapterNum: 99,
        title: '镜裂之后',
        goal: '林逐确认铜镜裂纹和白玉钥匙仍有关联。',
        conflict: '他必须在不暴露钥匙剩余次数的情况下试探赵青。',
        doNotResolveYet: ['祖母身份只保留为疑点，不正向揭示。'],
        handoff: '停在铜镜第二次裂响。'
      },
      {
        chapterNum: 100,
        title: '门主',
        goal: FUTURE_SECRET,
        conflict: '未来章才处理的身份反转。'
      }
    ]
  },
  characters: [],
  plotThreads: [
    {
      id: 'thread-failed-98',
      title: POLLUTED_THREAD,
      status: 'developing',
      content: '来自第98章失败候选，不得进入 stateAuthority 或 creative prompt。',
      provenance: {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-failed',
        runId: 'run-98-failed',
        commitStatus: 'failed'
      }
    }
  ],
  canonFacts: [
    {
      id: 'fact-final-97',
      status: 'accepted',
      chapterNum: 97,
      factType: '道具',
      content: FINAL_FACT,
      provenance: {
        sourceChapterNum: 97,
        sourceVersionId: 'v97-final',
        finalizationId: 'fin-97',
        commitStatus: 'final'
      }
    },
    {
      id: 'fact-failed-98',
      status: 'accepted',
      chapterNum: 98,
      factType: '设定',
      content: POLLUTED_EVENT,
      provenance: {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-failed',
        runId: 'run-98-failed',
        commitStatus: 'failed'
      }
    },
    {
      id: 'fact-empty-98',
      status: 'accepted',
      chapterNum: 98,
      factType: '空章污染',
      content: '空章却声称赵青已经离开渭水。',
      provenance: {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-empty',
        commitStatus: 'empty_chapter'
      }
    },
    {
      status: 'accepted',
      chapterNum: 98,
      factType: '无ID失败污染',
      content: NO_ID_REJECTED_FACT,
      provenance: {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-failed',
        runId: 'run-98-failed',
        commitStatus: 'failed'
      }
    }
  ]
}

const settingStore = {
  entities: [
    {
      id: 'white-key',
      entityType: 'item',
      name: '白玉钥匙',
      status: 'active',
      importance: 9,
      summary: '仍在林逐掌心，剩余一次。',
      profile: { owner: '林逐', usesLeft: '剩余 1 次' },
      provenance: {
        sourceChapterNum: 97,
        sourceVersionId: 'v97-final',
        finalizationId: 'fin-97',
        commitStatus: 'final'
      }
    },
    {
      id: 'polluted-active-entity',
      entityType: 'location',
      name: POLLUTED_ENTITY,
      status: 'active',
      importance: 10,
      summary: '来自第98章失败候选，不应进入任何 creative context。',
      provenance: {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-failed',
        runId: 'run-98-failed',
        commitStatus: 'failed'
      }
    },
    {
      id: 'tainted-active-entity',
      entityType: 'character',
      name: '带毒但仍active的人物',
      status: 'active',
      tainted: true,
      summary: 'tainted active entity 不得进入 creativeStageContract。',
      provenance: {
        sourceChapterNum: 97,
        sourceVersionId: 'v97-final',
        commitStatus: 'final'
      }
    },
    {
      id: 'quarantined-active-entity',
      entityType: 'item',
      name: '隔离物品',
      status: 'active',
      quarantineStatus: 'quarantined',
      summary: 'quarantined active entity 不得进入 creativeStageContract。',
      provenance: {
        sourceChapterNum: 97,
        sourceVersionId: 'v97-final',
        commitStatus: 'final'
      }
    },
    {
      entityType: 'location',
      name: NO_ID_REJECTED_ENTITY,
      status: 'active',
      importance: 10,
      summary: '无 id failed entity 的 name/content 不得通过 rejectedSources 进入 creative context。',
      provenance: {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-failed',
        runId: 'run-98-failed',
        commitStatus: 'failed'
      }
    }
  ],
  relations: [
    {
      id: 'relation-failed-98',
      sourceEntityId: 'white-key',
      targetEntityId: 'white-key',
      relationType: '污染关系',
      status: 'active',
      summary: FAILED_RELATION,
      provenance: {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-failed',
        runId: 'run-98-failed',
        commitStatus: 'failed'
      }
    }
  ],
  changeEvents: [
    {
      id: 'event-final-97',
      status: 'accepted',
      chapterNum: 97,
      entityId: 'white-key',
      entityName: '白玉钥匙',
      entityType: 'item',
      fieldPath: 'usesLeft',
      newValue: '剩余 1 次',
      provenance: {
        sourceChapterNum: 97,
        sourceVersionId: 'v97-final',
        finalizationId: 'fin-97',
        commitStatus: 'final'
      }
    },
    {
      id: 'event-failed-98',
      status: 'accepted',
      chapterNum: 98,
      entityName: POLLUTED_ENTITY,
      entityType: 'location',
      fieldPath: 'summary',
      newValue: POLLUTED_EVENT,
      provenance: {
        sourceChapterNum: 98,
        sourceVersionId: 'v98-failed',
        runId: 'run-98-failed',
        commitStatus: 'failed'
      }
    },
    {
      id: 'event-quarantined-97',
      status: 'accepted',
      chapterNum: 97,
      entityName: '隔离物品',
      entityType: 'item',
      fieldPath: 'summary',
      newValue: '这条 accepted event 已隔离，不得进 creative stage。',
      quarantined: true,
      provenance: {
        sourceChapterNum: 97,
        sourceVersionId: 'v97-final',
        commitStatus: 'final'
      }
    }
  ]
}

const volumeStore = {
  volumes: [
    {
      id: 'block-3',
      title: '第三卷',
      volumeNum: 3,
      startChapter: 90,
      endChapter: 120,
      status: 'active',
      coreGoal: '围绕铜镜和白玉钥匙推进。',
      mainConflict: '林逐必须判断赵青是否可信。',
      stageSummaryReport: {
        compactSummary: '第97章后，白玉钥匙仍在林逐手中。',
        completedBeats: [FINAL_FACT],
        handoffToNext: ['第99章只验证铜镜，不揭示祖母身份。']
      },
      snapshotProvenance: {
        sourceChapterNum: 97,
        sourceVersionId: 'v97-final',
        finalizationId: 'fin-97',
        commitStatus: 'final'
      }
    }
  ]
}

const contextOptions = {
  chapters: [
    { chapterNum: 97, status: 'final', finalVersionId: 'v97-final', wordCount: 5400 },
    { chapterNum: 98, status: 'drafting', finalVersionId: null, wordCount: 0 }
  ],
  chapterVersions: [
    { id: 'v97-final', chapterNum: 97, versionType: 'final', content: FINAL_FACT },
    { id: 'v98-failed', chapterNum: 98, versionType: 'ai_candidate', content: POLLUTED_EVENT, runStatus: 'failed' },
    { id: 'v98-empty', chapterNum: 98, versionType: 'ai_candidate', content: '', runStatus: 'failed' }
  ],
  savedBeatPlans: [
    {
      chapterNum: 97,
      content: CONFLICTING_SAVED_PLAN,
      provenance: { sourceChapterNum: 97, sourceVersionId: 'beat-97', commitStatus: 'plan_only' }
    }
  ],
  finalizationMarkers: []
}

const pack = buildContextPackV2({
  novelStore,
  chapterNum: 99,
  settingStore,
  volumeStore,
  contextOptions
})

assert.equal(pack.schemaVersion, 'context-pack-v2')
assert.ok(pack.stateAuthority, 'ContextPack v2 should expose stateAuthority')
assert.ok(pack.creativeStageContract, 'ContextPack v2 should expose creativeStageContract')
assert.ok(pack.narrativeVoiceContract, 'ContextPack v2 should expose narrativeVoiceContract')
assert.ok(pack.guardSnapshot, 'ContextPack v2 should expose guardSnapshot')
assert.equal(pack.healthCheck.blocked, true, 'accepted/active data from failed or empty chapters should block context preparation')
assert.throws(
  () => assertContextPackHealthy(pack),
  /untrusted_source/,
  'polluted active/accepted sources should be recognized by the health check'
)

const authorityText = JSON.stringify(pack.stateAuthority)
assert.match(authorityText, /白玉钥匙仍在林逐掌心/)
assert.doesNotMatch(authorityText, new RegExp(POLLUTED_ENTITY))
assert.doesNotMatch(authorityText, new RegExp(POLLUTED_EVENT))
assert.doesNotMatch(authorityText, new RegExp(POLLUTED_THREAD))
assert.doesNotMatch(authorityText, new RegExp(FAILED_RELATION))
assert.doesNotMatch(authorityText, new RegExp(NO_ID_REJECTED_FACT))
assert.doesNotMatch(authorityText, new RegExp(NO_ID_REJECTED_ENTITY))
assert.doesNotMatch(authorityText, /空章却声称赵青已经离开渭水/)
assert.doesNotMatch(authorityText, new RegExp(CONFLICTING_SAVED_PLAN))

const creativeContext = buildCreativeContextFromPack(pack, {
  chapterNum: 99,
  beatPlan: '1. 林逐只验证铜镜裂纹。\n2. 章末停在第二次裂响。'
})
const creativeText = JSON.stringify(creativeContext)
assert.match(creativeText, /白玉钥匙/)
assert.match(creativeText, /剩余 1 次/)
assert.doesNotMatch(creativeText, new RegExp(POLLUTED_ENTITY))
assert.doesNotMatch(creativeText, new RegExp(POLLUTED_THREAD))
assert.doesNotMatch(creativeText, new RegExp(FAILED_RELATION))
assert.doesNotMatch(creativeText, new RegExp(NO_ID_REJECTED_FACT))
assert.doesNotMatch(creativeText, new RegExp(NO_ID_REJECTED_ENTITY))
assert.doesNotMatch(creativeText, /带毒但仍active/)
assert.doesNotMatch(creativeText, /隔离物品/)
assert.doesNotMatch(creativeText, new RegExp(FUTURE_SECRET))
assert.doesNotMatch(creativeText, new RegExp(GUARD_ONLY_FORBIDDEN))
assert.doesNotMatch(creativeText, new RegExp(CONFLICTING_SAVED_PLAN))

const guardText = JSON.stringify(pack.guardSnapshot)
assert.match(guardText, new RegExp(FUTURE_SECRET))
assert.match(guardText, new RegExp(GUARD_ONLY_FORBIDDEN))

const cleanNovelStore = {
  ...novelStore,
  plotThreads: [],
  canonFacts: novelStore.canonFacts.filter(fact => fact.id === 'fact-final-97')
}
const cleanSettingStore = {
  ...settingStore,
  entities: settingStore.entities.filter(entity => entity.id === 'white-key'),
  relations: [],
  changeEvents: settingStore.changeEvents.filter(event => event.id === 'event-final-97')
}
const cleanPack = buildContextPackV2({
  novelStore: cleanNovelStore,
  chapterNum: 99,
  settingStore: cleanSettingStore,
  volumeStore,
  contextOptions
})
assert.equal(cleanPack.healthCheck.blocked, false, 'clean trusted fixture should pass context preparation')
assert.doesNotThrow(() => assertContextPackHealthy(cleanPack))
assert.equal(
  cleanPack.stateAuthority.activeStoryBlock.sourceExplanation.sourceType,
  'final_state',
  'trusted active stage should explain that it is backed by final-state provenance'
)

const cleanCreativeContext = buildCreativeContextFromPack(cleanPack, {
  chapterNum: 99,
  beatPlan: '1. 林逐只验证铜镜裂纹。\n2. 章末停在第二次裂响。'
})
const promptText = buildDraftPrompt(creativeContext)
assert.doesNotMatch(promptText, new RegExp(FUTURE_SECRET))
assert.doesNotMatch(promptText, new RegExp(GUARD_ONLY_FORBIDDEN))
assert.doesNotMatch(promptText, new RegExp(POLLUTED_EVENT))
assert.doesNotMatch(buildDraftPrompt(cleanCreativeContext), new RegExp(FUTURE_SECRET))
assert.doesNotMatch(buildDraftPrompt(cleanCreativeContext), new RegExp(GUARD_ONLY_FORBIDDEN))

const integrated = buildWritingContext(
  cleanNovelStore,
  99,
  12000,
  cleanSettingStore,
  volumeStore,
  { tasks: [] },
  contextOptions
)
assert.equal(integrated.contextPack.schemaVersion, 'context-pack-v2')
assert.equal(integrated.healthCheck.blocked, false)
assert.doesNotMatch(JSON.stringify(integrated.context), new RegExp(POLLUTED_EVENT))
assert.doesNotMatch(JSON.stringify(integrated.context), new RegExp(FUTURE_SECRET))

const failedRelationshipResult = buildWritingContext(
  {
    bible: {},
    outline: {
      nearChapters: [
        { chapterNum: 9, title: '关系污染校验', goal: '赵青只观察白玉钥匙。' }
      ]
    },
    characters: [
      {
        name: '赵青',
        role: 'protagonist',
        relationshipNotes: '失败候选关系：赵青已经夺走白玉钥匙。',
        hardState: { location: '渭水' },
        provenance: {
          sourceChapterNum: 8,
          sourceVersionId: 'v8-failed',
          commitStatus: 'failed'
        }
      }
    ],
    canonFacts: [],
    plotThreads: []
  },
  9,
  12000,
  { entities: [], relations: [], changeEvents: [] },
  { volumes: [] },
  { tasks: [] },
  {}
)
assert.equal(failedRelationshipResult.healthCheck.blocked, true)
assert.doesNotMatch(
  JSON.stringify(failedRelationshipResult.context),
  /失败候选关系：赵青已经夺走白玉钥匙/,
  'legacy relationshipNotes from failed characters must be overwritten by ContextPack v2 projection'
)

const unknownCharacterResult = buildWritingContext(
  {
    bible: {},
    outline: {
      nearChapters: [
        { chapterNum: 9, title: '角色 provenance 校验', goal: '赵青检查白玉钥匙。' }
      ]
    },
    characters: [
      {
        name: '赵青',
        role: 'protagonist',
        hardState: { location: '旧宅' },
        softState: { emotion: '警惕' }
      }
    ],
    canonFacts: [],
    plotThreads: []
  },
  9,
  12000,
  { entities: [], relations: [], changeEvents: [] },
  { volumes: [] },
  { tasks: [] },
  {}
)
assert.match(JSON.stringify(unknownCharacterResult.context.contextHealth), /unknown_provenance/)
assert.match(
  buildDraftPrompt(unknownCharacterResult.context),
  /赵青（protagonist） \[trustLevel=unknown\]/,
  'unknown-provenance characters should be visibly downgraded in prompt-facing character state'
)

const writerViewSource = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const ensureContextReadyIndex = writerViewSource.indexOf('async function ensureAiContextReady')
const healthAssertIndex = writerViewSource.indexOf('assertContextPackHealthy', ensureContextReadyIndex)
assert.ok(writerViewSource.includes("import { assertContextPackHealthy } from '@/utils/contextPackV2'"), 'writer generation prep should import ContextPack health assertion')
assert.ok(healthAssertIndex > -1, 'writer generation prep should use ContextPack health assertion')
assert.ok(
  healthAssertIndex > ensureContextReadyIndex,
  'ContextPack health assertion should run during AI context readiness checks'
)
assert.match(
  writerViewSource,
  /buildWritingContext\([\s\S]*chapters:\s*writerStore\.chapters[\s\S]*finalizationMarkers[\s\S]*\}\s*\)/,
  'WriterView should pass chapter ledger and finalization markers into ContextPack v2'
)

const blockedPack = buildContextPackV2({
  novelStore,
  chapterNum: 99,
  settingStore,
  volumeStore,
  contextOptions: {
    ...contextOptions,
    finalizationMarkers: [
      {
        projectId: 'synthetic',
        chapterNum: 98,
        sourceVersionId: 'v98-final',
        startedAt: Date.now(),
        commitStatus: 'pending'
      }
    ]
  }
})
assert.equal(blockedPack.healthCheck.blocked, true)
assert.throws(
  () => assertContextPackHealthy(blockedPack),
  /finalization_pending/,
  'half-success finalization should block next chapter context preparation'
)

const validatedMarkerPack = buildContextPackV2({
  novelStore,
  chapterNum: 99,
  settingStore,
  volumeStore,
  contextOptions: {
    ...contextOptions,
    finalizationMarkers: [
      {
        projectId: 'synthetic',
        chapterNum: 98,
        sourceVersionId: 'v98-final',
        runId: 'run-98-validated',
        finalizationId: 'fin-98',
        commitStatus: 'validated'
      }
    ]
  }
})
assert.equal(
  validatedMarkerPack.healthCheck.blocked,
  true,
  'validated-but-not-committed finalization should block next chapter context preparation'
)
assert.match(
  JSON.stringify(validatedMarkerPack.healthCheck.issues),
  /validated/,
  'validated finalization marker should remain visible as blocking provenance evidence'
)
assert.throws(
  () => assertContextPackHealthy(validatedMarkerPack),
  /finalization_pending/
)

const legacyPack = buildContextPackV2({
  novelStore: {
    bible: {},
    outline: {
      nearChapters: [
        {
          chapterNum: 9,
          title: '旧记录校验',
          goal: '林逐检查白玉钥匙旧来源。',
          conflict: '旧设定来源缺失，不能当高可信事实。'
        }
      ]
    },
    characters: [],
    plotThreads: [],
    canonFacts: [
      {
        id: 'legacy-fact-no-provenance',
        status: 'accepted',
        chapterNum: 7,
        factType: 'legacy',
        content: '旧记录声称白玉钥匙已经改由赵青持有。'
      }
    ]
  },
  chapterNum: 9,
  settingStore: {
    entities: [
      {
        id: 'legacy-entity-no-provenance',
        entityType: 'item',
        name: '白玉钥匙',
        status: 'active',
        summary: '旧记录缺少 provenance 的白玉钥匙状态。',
        profile: { owner: '赵青' }
      }
    ],
    relations: [],
    changeEvents: []
  },
  volumeStore: { volumes: [] },
  contextOptions: {}
})
assert.equal(legacyPack.healthCheck.blocked, false, 'legacy unknown provenance should warn, not block by default')
assert.match(
  JSON.stringify(legacyPack.healthCheck.issues),
  /unknown_provenance/,
  'legacy records without provenance should be surfaced in health-check'
)
assert.match(
  JSON.stringify(legacyPack.stateAuthority),
  /trustLevel":"unknown"/,
  'legacy records admitted without a chapter ledger should be labeled unknown trust'
)
const legacyCreativeContext = buildCreativeContextFromPack(legacyPack, { chapterNum: 9 })
assert.match(
  JSON.stringify(legacyCreativeContext.contextHealth),
  /unknown_provenance/,
  'legacy unknown provenance should remain visible as a creative-context health warning code'
)
assert.doesNotMatch(
  JSON.stringify(legacyCreativeContext.contextHealth),
  /旧记录声称白玉钥匙已经改由赵青持有/,
  'creative-context health summary should not leak diagnostic target text into prompt-facing context'
)
assert.match(
  legacyCreativeContext.stateLedger,
  /trustLevel=unknown/,
  'legacy unknown provenance should not appear as an unmarked high-trust ledger fact'
)

const halfProvenancePack = buildContextPackV2({
  novelStore: {
    bible: {},
    outline: {
      nearChapters: [
        { chapterNum: 9, title: '半 provenance 校验', goal: '只验证旧事实可信度。' }
      ]
    },
    characters: [],
    plotThreads: [],
    canonFacts: [
      {
        id: 'half-provenance-fact',
        status: 'accepted',
        chapterNum: 7,
        factType: 'legacy',
        content: '半 provenance 旧事实不能静默升级为 trusted。',
        provenance: {
          sourceChapterNum: 7,
          sourceVersionId: 'legacy-v7'
        }
      }
    ]
  },
  chapterNum: 9,
  settingStore: { entities: [], relations: [], changeEvents: [] },
  volumeStore: { volumes: [] },
  contextOptions: {}
})
assert.match(JSON.stringify(halfProvenancePack.healthCheck.issues), /unknown_provenance/)
assert.equal(
  halfProvenancePack.stateAuthority.canonFacts[0]?.trustLevel,
  'degraded',
  'sourceChapter/sourceVersion without final proof or chapter ledger should be degraded, not trusted'
)

const degradedStagePack = buildContextPackV2({
  novelStore: {
    bible: {},
    outline: {
      nearChapters: [
        { chapterNum: 9, title: '阶段校验', goal: '只验证当前阶段来源。' }
      ]
    },
    canonFacts: [],
    plotThreads: [],
    characters: []
  },
  chapterNum: 9,
  settingStore: { entities: [], relations: [], changeEvents: [] },
  volumeStore: {
    volumes: [
      {
        id: 'legacy-stage',
        title: '旧阶段',
        startChapter: 1,
        endChapter: 20,
        status: 'active',
        coreGoal: '旧阶段快照没有 final provenance。',
        mainConflict: '需要 health warning。',
        stageSummaryReport: {
          compactSummary: '来源不可解释的旧 stage snapshot。'
        }
      }
    ]
  },
  contextOptions: {}
})
assert.equal(degradedStagePack.healthCheck.blocked, false)
assert.match(JSON.stringify(degradedStagePack.healthCheck.issues), /stage_degraded_provenance/)
assert.equal(
  degradedStagePack.stateAuthority.activeStoryBlock.sourceExplanation.sourceType,
  'degraded_fallback',
  'active stage without final/provenance support should explain degraded fallback source'
)

const failedStagePack = buildContextPackV2({
  novelStore: {
    bible: {},
    outline: {
      nearChapters: [
        { chapterNum: 9, title: '失败 stage 校验', goal: '不能读取失败 stage。' }
      ]
    },
    canonFacts: [],
    plotThreads: [],
    characters: []
  },
  chapterNum: 9,
  settingStore: { entities: [], relations: [], changeEvents: [] },
  volumeStore: {
    volumes: [
      {
        id: 'failed-stage',
        title: '失败阶段',
        startChapter: 1,
        endChapter: 20,
        status: 'active',
        coreGoal: '失败候选 stage 不得进入创作上下文。',
        mainConflict: '污染 stage conflict。',
        stageSummaryReport: {
          compactSummary: '失败 stage summary 污染。'
        },
        snapshotProvenance: {
          sourceChapterNum: 8,
          sourceVersionId: 'v8-failed',
          commitStatus: 'failed'
        }
      }
    ]
  },
  contextOptions: {}
})
assert.equal(failedStagePack.healthCheck.blocked, true)
assert.match(JSON.stringify(failedStagePack.healthCheck.issues), /untrusted_stage_snapshot/)
assert.equal(failedStagePack.stateAuthority.activeStoryBlock, null)
assert.equal(failedStagePack.creativeStageContract.activeStoryBlock, null)
assert.doesNotMatch(
  JSON.stringify(buildCreativeContextFromPack(failedStagePack, { chapterNum: 9 })),
  /失败候选 stage|污染 stage|失败 stage summary/
)

const voiceLint = lintNarrativeVoiceContract({
  tone: '冷静、具体、少解释',
  rhythm: '长短句自然交错',
  factOverrides: ['把白玉钥匙改成赵青持有'],
  stageBoundary: '提前揭示祖母身份'
})
assert.equal(voiceLint.ok, false)
assert.match(voiceLint.issues.join('\n'), /事实|stage|边界/)

const voiceSanitizedPack = buildContextPackV2({
  novelStore: { bible: {}, outline: { nearChapters: [] }, canonFacts: [], plotThreads: [], characters: [] },
  chapterNum: 1,
  settingStore: { entities: [], relations: [], changeEvents: [] },
  volumeStore: { volumes: [] },
  contextOptions: {
    narrativeVoiceContract: {
      tone: '冷静',
      factOverrides: ['把白玉钥匙改给赵青'],
      stageBoundary: '提前揭示祖母身份'
    }
  }
})
assert.equal(voiceSanitizedPack.narrativeVoiceContract.lint.ok, false)
assert.equal(voiceSanitizedPack.narrativeVoiceContract.factOverrides, undefined)
assert.equal(voiceSanitizedPack.narrativeVoiceContract.stageBoundary, undefined)

console.log('context pack v2 phase1 contract tests passed')
