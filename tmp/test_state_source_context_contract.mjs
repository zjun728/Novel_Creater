import assert from 'node:assert/strict'
import { buildWritingContext } from '../frontend/src/utils/contextBuilder.js'

const novelStore = {
  bible: { premise: '测试长篇', worldRules: '星账使用必须付出代价。' },
  outline: {
    nearChapters: [
      { chapterNum: 3, goal: '继续追查父亲账册线索和星账代价。' }
    ]
  },
  characters: [
    {
      id: 'qing-character-row',
      name: '青先生',
      role: 'antagonist',
      hardState: { location: '北城' },
      softState: {}
    }
  ],
  plotThreads: [],
  canonFacts: [
    {
      id: 'fact-1',
      status: 'accepted',
      chapterNum: 2,
      factType: 'plot',
      content: '陆沉舟在第 2 章确认父亲账册线索和星账代价。',
      relatedCharacters: ['陆沉舟'],
      relatedPlotThreads: ['父亲线索线']
    }
  ]
}

const settingStore = {
  entities: [
    {
      id: 'placeholder-1',
      status: 'active',
      entityType: 'item',
      name: '占位账本',
      summary: '第 1 章自动识别的设定',
      importance: 10,
      firstChapter: 1,
      lastChapter: 1,
      profile: {}
    },
    {
      id: 'real-1',
      status: 'active',
      entityType: 'item',
      name: '星账',
      summary: '记录活人代价的核心账册。',
      importance: 5,
      firstChapter: 1,
      lastChapter: 2,
      profile: { owner: '陆沉舟', possessionStatus: '当前携带' }
    },
    {
      id: 'xu-setting',
      status: 'active',
      entityType: 'character',
      name: '徐正清',
      summary: '巡天司主簿，另有青先生身份。',
      aliases: ['徐主簿'],
      profile: {
        canonicalName: '徐正清',
        personas: [
          {
            name: '青先生',
            type: 'codename',
            status: 'revealed',
            knownBy: ['读者'],
            evidence: '私印线索。'
          }
        ]
      }
    }
  ],
  relations: [],
  changeEvents: []
}

const result = buildWritingContext(novelStore, 3, 12000, settingStore, null, null, null)
const serializedContext = JSON.stringify(result.context)

assert.match(serializedContext, /星账/, 'real setting should still enter context')
assert.doesNotMatch(serializedContext, /占位账本/, 'placeholder summary entity should not enter generation context')
assert.doesNotMatch(serializedContext, /第 1 章自动识别的设定/, 'placeholder summary text should not enter settingLibrary or stateLedger')
assert.match(serializedContext, /"recentFacts"/, 'Canon facts should remain a first-class context source')
assert.match(serializedContext, /父亲账册线索/, 'recent Canon facts should enter generation context')
assert.match(serializedContext, /青先生：系统身份指向 徐正清/, 'writing context should carry hidden identity as scoped system knowledge')
assert.match(serializedContext, /陆沉舟未知|主角未知/, 'writing context should mark protagonist knowledge boundary')
assert.doesNotMatch(serializedContext, /青先生就是徐正清/, 'writing context should not phrase hidden identity as public protagonist knowledge')

console.log('state source context contract passed')
