import assert from 'node:assert/strict'
import {
  buildCharacterAliasIndex,
  factMatchesCharacter,
  summarizeCharacterFactCoverage
} from '../frontend/src/utils/characterFactMatcher.js'

const characters = [
  { id: 'char-lcz', name: '陆沉舟' },
  { id: 'char-lcg', name: '陆远之' },
  { id: 'char-xzq', name: '徐正清' },
  { id: 'char-zy', name: '周远（老周）' }
]

const settingEntities = [
  {
    id: 'setting-lcg',
    entityType: 'character',
    name: '陆远之',
    aliases: ['陆父', '陆长庚', '陆沉舟父亲']
  },
  {
    id: 'setting-xzq',
    entityType: 'character',
    name: '徐正清',
    aliases: '["徐主簿"]'
  }
]

const facts = [
  { id: 'fact-1', chapterNum: 1, relatedCharacters: ['陆沉舟'], content: '陆沉舟第一次使用星账。' },
  { id: 'fact-2', chapterNum: 2, relatedCharacters: ['陆长庚'], content: '陆长庚留下账册线索。' },
  { id: 'fact-3', chapterNum: 3, relatedCharacters: ['徐主簿'], content: '徐主簿暗中追查星账。' },
  { id: 'fact-4', chapterNum: 4, relatedCharacters: ['char-lcz'], content: '兼容旧 ID 写法。' },
  { id: 'fact-5', chapterNum: 5, relatedCharacters: ['周远'], content: '括注人物短名也应命中。' }
]

const aliasIndex = buildCharacterAliasIndex(characters, settingEntities)

assert.equal(factMatchesCharacter(facts[0], characters[0], aliasIndex), true, 'canonical name should match')
assert.equal(factMatchesCharacter(facts[1], characters[1], aliasIndex), true, 'setting alias should match')
assert.equal(factMatchesCharacter(facts[2], characters[2], aliasIndex), true, 'serialized aliases should match')
assert.equal(factMatchesCharacter(facts[3], characters[0], aliasIndex), true, 'id should remain compatible')
assert.equal(factMatchesCharacter(facts[4], characters[3], aliasIndex), true, 'short names should match decorated character names')

const coverage = summarizeCharacterFactCoverage({ characters, settingEntities, canonFacts: facts })
assert.equal(coverage.idHitCount, 1, 'id hits should be measured separately')
assert.equal(coverage.nameAliasHitCount, 4, 'name/alias hits should be counted')
assert.deepEqual(
  coverage.characterCoverage.find(item => item.name === '陆沉舟').chapters,
  [1, 4],
  'coverage should include name and id facts for a character'
)
assert.deepEqual(
  coverage.characterCoverage.find(item => item.name === '陆远之').chapters,
  [2],
  'coverage should include alias chapters'
)

console.log('character arc matching contract passed')
