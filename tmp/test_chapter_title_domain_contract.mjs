import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  collectChapterTitleMaterials,
  deriveFallbackChapterTitle,
  evaluateChapterTitlePolicy,
  normalizeChapterTitle,
  rankChapterTitleCandidates,
  selectChapterTitle
} from '../frontend/src/domain/chapter-title/index.js'

const chapter88Context = {
  chapterNum: 88,
  chapterGoal: {
    goal: '进入东城染坊地下仓库，找到父亲留下的东西',
    conflict: '追兵逼近，必须判断是否当场查看铁箱账本',
    turn: '账本和三号仓钥指向下一处仓库'
  },
  beatPlan: {
    stagePurpose: '进入染坊地下仓库，找到父亲留下的东西',
    stageAction: '解开暗格，发现一个铁箱，内含账本、信件或信物',
    stageChoice: '是否当场查看内容，还是带走后查看'
  },
  blockStageSnapshot: {
    blockGoal: '东城染坊取物',
    stagePurpose: '进入染坊地下仓库，找到父亲留下的东西',
    stageAction: '发现一个铁箱或暗格，内含账本、信件或信物'
  },
  content: '马三低声说“就是这里”。陆沉舟没有接话，先打开铁箱账本，又把三号仓钥和染坊钥匙压在账页下。'
}

assert.equal(normalizeChapterTitle('《铁箱账本》'), '铁箱账本')

const materials = collectChapterTitleMaterials(chapter88Context)
const materialTitles = materials.map(item => item.title)
assert.ok(materialTitles.includes('东城染坊'), 'materials should include concrete place from context')
assert.ok(materialTitles.includes('铁箱账本'), 'materials should include concrete object evidence from context')
assert.ok(materialTitles.includes('三号仓钥'), 'materials should include concrete key/item from context')
assert.ok(!materialTitles.includes('就是这里'), 'spoken pointer fragment must not become positive material')

const weakFragments = ['就是这里', '就在这里', '就是这儿', '就是这边', '还有多远', '这通向哪', '不一定', '坐', '第88章', 'reason', '别动']
const weakResults = Object.fromEntries(weakFragments.map(title => [title, evaluateChapterTitlePolicy(title, { chapterNum: 88 })]))
for (const [title, result] of Object.entries(weakResults)) {
  assert.equal(result.status, 'fail', `${title} must hard fail instead of pass`)
}
assert.equal(weakResults['就是这里'].reason, 'location_pointer_fragment')
assert.equal(weakResults['还有多远'].reason, 'route_question_fragment')
assert.equal(weakResults['这通向哪'].reason, 'direction_question_fragment')
assert.equal(weakResults['不一定'].reason, 'oral_judgment_fragment')
assert.equal(weakResults['坐'].reason, 'single_character_action_fragment')
assert.equal(weakResults['第88章'].reason, 'default_title')
assert.equal(weakResults.reason.reason, 'internal_field')
assert.equal(weakResults['别动'].reason, 'dialogue_fragment')

const allowedTitles = ['陆沉舟', '青鸾', '平安粮栈', '东城染坊', '庚七密室', '星债会地窖', '铁箱账本', '三号仓钥', '铁盒纸条', '星债会', '断钥换账', '黑铁令', '长生功']
for (const title of allowedTitles) {
  const result = evaluateChapterTitlePolicy(title, {
    chapterNum: 88,
    materials: allowedTitles.map(item => ({ title: item, type: 'fixture', evidence: item }))
  })
  assert.equal(result.status, 'pass', `${title} should be allowed when backed by chapter materials`)
}

const ranked = rankChapterTitleCandidates([
  { title: '就是这里', type: 'place', reason: '对白位置残片' },
  { title: '铁箱账本', type: 'item', reason: '关键证据' },
  { title: '三号仓钥', type: 'item', reason: '关键道具' }
], materials, chapter88Context)
assert.equal(ranked[0].title, '铁箱账本', 'positive concrete material should rank first')
assert.equal(ranked.find(item => item.title === '就是这里')?.policy.status, 'fail')

const selected = selectChapterTitle({
  modelResponse: JSON.stringify({
    candidates: [
      { title: '就是这里', type: 'place', reason: '对白位置残片' },
      { title: '铁箱账本', type: 'item', reason: '关键证据' }
    ]
  }),
  context: chapter88Context
})
assert.equal(selected.title, '铁箱账本')
assert.equal(selected.rejected.find(item => item.title === '就是这里')?.reason, 'location_pointer_fragment')
assert.match(selected.selectedEvidence, /铁箱账本|账本|铁箱/)

const fallback = deriveFallbackChapterTitle(chapter88Context)
assert.match(fallback, /^(铁箱账本|三号仓钥|染坊钥匙|东城染坊)$/)

for (const productionFile of [
  'frontend/src/prompts/chapter.js',
  'frontend/src/domain/chapter-title/policy.js',
  'frontend/src/domain/chapter-title/source-extractor.js',
  'frontend/src/domain/chapter-title/ranker.js'
]) {
  const source = readFileSync(productionFile, 'utf8')
  assert.doesNotMatch(
    source,
    /铁箱账本|就是这里|三号仓钥|铁盒纸条|庚七密室|东城染坊|星债会地窖|星债会|巡天司|马三|赵庚|徐正清|甲十七|染坊钥匙|密约残页|旧铜钥匙|星账换令|星账最后一页/,
    `${productionFile} must not hardcode current project terms`
  )
  assert.doesNotMatch(
    source,
    /const\s+directTerms\s*=|PREFERRED_(?:PLACE|ITEM|PERSON_OR_ORG)_TITLES|排水道|平安客栈|父亲账册|金龙宝行|大梵音寺/,
    `${productionFile} must not keep legacy hardcoded fallback title lists`
  )
}

console.log('chapter title domain contract passed')
