import assert from 'node:assert/strict'

import { buildWritingContext } from '../frontend/src/utils/contextBuilder.js'

const novelStore = {
  bible: {
    premise: '主角以考据和代价交换破解异常规则。',
    worldRules: '所有代价必须有来源和后果。',
    styleBible: '冷静、具体、少解释。'
  },
  outline: {
    nearChapters: [
      {
        chapterNum: 12,
        title: '潮声里的钥匙',
        goal: '林逐在渭水暗河找到白玉钥匙，确认赵青仍在跟踪他。',
        conflict: '白玉钥匙会消耗左臂残余知觉，赵青必须决定是否暴露身份。'
      }
    ]
  },
  characters: [],
  plotThreads: [
    { title: '白玉钥匙线', status: 'developing', content: '白玉钥匙与渭水暗河有关。' },
    { title: '远古帝都线', status: 'developing', content: '暂不进入本章。' }
  ],
  canonFacts: [
    {
      status: 'accepted',
      chapterNum: 10,
      factType: '道具',
      content: '白玉钥匙已经使用一次，剩余一次。',
      relatedPlotThreads: ['#白玉钥匙线']
    },
    {
      status: 'accepted',
      chapterNum: 3,
      factType: '道具',
      content: '黑铁铃已经被陈默带走，本章不相关。',
      relatedPlotThreads: ['#远古帝都线']
    },
    {
      status: 'accepted',
      chapterNum: 11,
      factType: '状态',
      content: '赵青知道林逐左臂已经失去知觉。'
    }
  ]
}

const settingStore = {
  entities: [
    {
      id: 'lin-zhu',
      entityType: 'character',
      name: '林逐',
      category: '主角',
      status: 'active',
      importance: 10,
      summary: '逐愿师传承者，左臂残余知觉正在消失。',
      profile: {
        physicalStatus: '左臂残余知觉不足三成',
        currentLocation: '渭水暗河'
      }
    },
    {
      id: 'zhao-qing',
      entityType: 'character',
      name: '赵青',
      status: 'active',
      importance: 7,
      summary: '跟踪林逐的人，身份尚未公开。',
      profile: { currentLocation: '渭水暗河入口' }
    },
    {
      id: 'white-key',
      entityType: 'item',
      name: '白玉钥匙',
      status: 'active',
      importance: 8,
      summary: '开启暗河门的钥匙，剩余一次。',
      profile: { owner: '林逐', usesLeft: '剩余 1 次' }
    },
    {
      id: 'black-bell',
      entityType: 'item',
      name: '黑铁铃',
      status: 'active',
      importance: 9,
      summary: '三十章后才会回收的远线道具。',
      profile: { owner: '陈默', usesLeft: '剩余 9 次' }
    }
  ],
  relations: [
    {
      sourceEntityId: 'lin-zhu',
      targetEntityId: 'zhao-qing',
      relationType: '被跟踪',
      status: 'active',
      summary: '赵青正在跟踪林逐。'
    },
    {
      sourceEntityId: 'black-bell',
      targetEntityId: 'lin-zhu',
      relationType: '远线伏笔',
      status: 'active',
      summary: '本章不应进入。'
    }
  ],
  changeEvents: [
    {
      status: 'accepted',
      chapterNum: 11,
      entityId: 'white-key',
      entityName: '白玉钥匙',
      entityType: 'item',
      fieldPath: 'usesLeft',
      newValue: '剩余 1 次'
    },
    {
      status: 'accepted',
      chapterNum: 2,
      entityId: 'black-bell',
      entityName: '黑铁铃',
      entityType: 'item',
      fieldPath: 'owner',
      newValue: '陈默'
    }
  ]
}

const correctionTaskStore = {
  tasks: [
    {
      id: 'current-critical',
      status: 'accepted',
      severity: 'critical',
      targetModule: 'chapter',
      sourceType: 'chapter_audit',
      chapterRefs: [12],
      title: '白玉钥匙次数不能重置',
      suggestedAction: '本章必须保留剩余 1 次。'
    },
    {
      id: 'global-major',
      status: 'accepted',
      severity: 'major',
      targetModule: 'plot',
      sourceType: 'global_audit',
      chapterRefs: [],
      title: '远古帝都线不要提前交代',
      suggestedAction: '只在相关章节提醒。'
    },
    {
      id: 'minor-noise',
      status: 'accepted',
      severity: 'minor',
      targetModule: 'style',
      sourceType: 'chapter_audit',
      chapterRefs: [12],
      title: '一个轻微句式建议',
      suggestedAction: '不应进入写作上下文。'
    }
  ]
}

const result = buildWritingContext(
  novelStore,
  12,
  12000,
  settingStore,
  { volumes: [] },
  correctionTaskStore
).context

const serialized = JSON.stringify(result)

assert.match(serialized, /林逐/)
assert.match(serialized, /赵青/)
assert.match(serialized, /白玉钥匙/)
assert.match(serialized, /剩余 1 次/)
assert.match(serialized, /白玉钥匙次数不能重置/)
assert.match(serialized, /赵青知道林逐左臂已经失去知觉/)

assert.doesNotMatch(serialized, /黑铁铃/)
assert.doesNotMatch(serialized, /陈默带走/)
assert.doesNotMatch(serialized, /远古帝都线不要提前交代/)
assert.doesNotMatch(serialized, /一个轻微句式建议/)

console.log('CONTEXT_RELEVANCE_FILTER_CONTRACT_OK')
