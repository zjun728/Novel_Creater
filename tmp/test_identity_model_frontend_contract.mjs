import assert from 'node:assert/strict'
import {
  buildCanonicalCharacterRows,
  buildCharacterAliasIndex,
  buildIdentityKnowledgeNote,
  factMatchesCharacter,
  summarizeCharacterFactCoverage
} from '../frontend/src/utils/characterFactMatcher.js'

const characters = [
  { id: 'xu-row-1', name: '徐正清' },
  { id: 'xu-row-2', name: '徐主簿（巡天司主簿）' },
  { id: 'hei-row', name: '黑衣人' },
  { id: 'lu-row', name: '陆长庚' }
]

const settingEntities = [
  {
    id: 'xu-setting',
    entityType: 'character',
    name: '徐正清',
    aliases: ['徐主簿'],
    profile: {
      canonicalName: '徐正清',
      personas: [
        {
          name: '青先生',
          type: 'codename',
          firstSeenChapter: 3,
          revealedChapter: 8,
          status: 'revealed',
          knownBy: ['读者'],
          evidence: '青先生留下徐正清私印。'
        }
      ],
      identityReveals: [
        {
          chapterNum: 8,
          fromName: '青先生',
          toCanonicalName: '徐正清',
          revealedTo: ['读者'],
          confidence: 0.9,
          evidence: '私印。'
        }
      ]
    }
  },
  {
    id: 'hei-setting',
    entityType: 'character',
    name: '黑衣人',
    profile: {
      canonicalName: '黑衣人',
      identityClaims: [
        {
          chapterNum: 4,
          claimedAs: '陆长庚',
          claimedBy: ['众人'],
          evidence: '背影相似。'
        }
      ],
      mistakenIdentities: [
        {
          chapterNum: 6,
          name: '黑衣人',
          mistakenAs: '陆长庚',
          status: 'disproved',
          evidence: '陆长庚同时在巡天司衙门。'
        }
      ]
    }
  }
]

const facts = [
  { id: 'fact-qing', chapterNum: 3, relatedCharacters: ['青先生'], content: '青先生派人送信。' },
  { id: 'fact-hei', chapterNum: 4, relatedCharacters: ['黑衣人'], content: '众人以为黑衣人是陆长庚。' },
  { id: 'fact-xu-id', chapterNum: 5, canonicalCharacters: ['xu-setting'], content: '徐正清身份线继续推进。' }
]

const rows = buildCanonicalCharacterRows(characters, settingEntities)
assert.equal(rows.filter(row => row.canonicalName === '徐正清').length, 1, '徐正清 and 徐主簿 should merge into one canonical row')
assert.equal(rows.some(row => row.canonicalName === '徐主簿'), false, 'alias row should not remain as a separate canonical person')
assert.deepEqual(facts[0].relatedCharacters, ['青先生'], 'Canon facts should keep chapter-local character naming')

const aliasIndex = buildCharacterAliasIndex(rows, settingEntities)
const xu = rows.find(row => row.canonicalName === '徐正清')
const lu = rows.find(row => row.canonicalName === '陆长庚')
const black = rows.find(row => row.canonicalName === '黑衣人')

assert.equal(factMatchesCharacter(facts[0], xu, aliasIndex), true, '青先生 fact should aggregate to 徐正清')
assert.equal(factMatchesCharacter(facts[2], xu, aliasIndex), true, 'canonicalCharacters entity id should aggregate to canonical person')
assert.equal(factMatchesCharacter(facts[1], lu, aliasIndex), false, 'mistaken identity claim must not merge 黑衣人 facts into 陆长庚')
assert.equal(black.mistakenIdentities[0].mistakenAs, '陆长庚', 'disproved mistaken identity should remain on the actual ambiguous person')

const coverage = summarizeCharacterFactCoverage({ characters: rows, settingEntities, canonFacts: facts })
assert.deepEqual(
  coverage.characterCoverage.find(item => item.canonicalName === '徐正清').chapters,
  [3, 5],
  'character arc should show codename chapter under canonical person'
)

const note = buildIdentityKnowledgeNote(settingEntities[0], ['陆沉舟'])
assert.match(note, /青先生/)
assert.match(note, /主角未知|陆沉舟未知/)
assert.doesNotMatch(note, /青先生就是徐正清/, 'writing context should not present hidden identity as public protagonist knowledge')

console.log('identity model frontend contract passed')
