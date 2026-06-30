import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  cleanGeneratedChapterTitle,
  deriveFallbackChapterTitle,
  getChapterTitleQuality
} from '../frontend/src/prompts/chapter.js'

function quality(title) {
  return getChapterTitleQuality(title, { chapterNum: 70, titleSource: 'contract' })
}

for (const title of ['reason', 'title', 'stage', 'chapter', 'draft', 'final', 'summary', 'outline', 'beat', 'scene']) {
  const result = quality(title)
  assert.equal(result.titleValid, false, `${title} should be hard rejected`)
  assert.match(result.titleInvalidReason, /internal|latin|json|code|field/i, `${title} should explain internal/latin residue`)
}

for (const title of ['Reason', 'FINAL', 'scene_id']) {
  assert.equal(quality(title).titleValid, false, `${title} should not be accepted as a final chapter title`)
}

const rejected78To82SourceTitleSamples = ['别管我', '别动', '谁派你来的', '……怎么了', '里面', '这边', '前面']
for (const title of rejected78To82SourceTitleSamples) {
  const result = quality(title)
  assert.equal(result.titleValid, false, `${title} should be hard rejected as dialogue/direction fragment`)
  assert.match(result.titleInvalidReason, /dialogue|direction|oral|fragment/i, `${title} should explain fragment rejection`)
  assert.equal(cleanGeneratedChapterTitle(title, { chapterNum: 78 }), '', `${title} must not survive generated title cleanup`)
}

const rejected83To86InitialTitleSamples = [
  '还有多远',
  '多远了',
  '走多久',
  '到哪了',
  '这通向哪',
  '往哪走',
  '去哪儿',
  '哪走',
  '就是这里',
  '就在这儿',
  '就是这边',
  '不一定',
  '可支撑',
  '也许吧',
  '可能吧',
  '假的',
  '真的',
  '坐',
  '走',
  '追',
  '看',
  '等',
  '跑',
  '停',
  '开',
  '关',
  '这边',
  '那边',
  '里面',
  '前头也有'
]
for (const title of rejected83To86InitialTitleSamples) {
  const result = quality(title)
  assert.equal(result.titleValid, false, `${title} should be hard rejected at initial title policy`)
  assert.match(
    result.titleInvalidReason,
    /dialogue|direction|oral|fragment|single_character|weak|question/i,
    `${title} should explain generalized weak spoken/fragment rejection`
  )
  assert.equal(cleanGeneratedChapterTitle(title, { chapterNum: 83 }), '', `${title} must not survive generated title cleanup`)
}

const acceptedShortCatalogTitles = [
  '庚七密室',
  '东城染坊',
  '星债会地窖',
  '火灶房',
  '十一号门',
  '铁盒纸条',
  '铁箱账本',
  '三号仓钥',
  '染坊钥匙',
  '密约残页',
  '旧铜钥匙',
  '星账换令',
  '两封相反的信',
  '审问',
  '交易',
  '破局',
  '星账最后一页'
]
for (const title of acceptedShortCatalogTitles) {
  const result = quality(title)
  assert.equal(result.titleValid, true, `${title} should remain an accepted catalog title`)
  assert.notEqual(result.status, 'fail', `${title} should not be hard rejected`)
}

for (const title of ['{"title":"旧铜钥匙"}', 'title: 旧铜钥匙', '"reason": "too short"']) {
  const result = quality(title)
  assert.equal(result.titleValid, false, `${title} should reject JSON/key/value fragments`)
}

for (const title of ['能走吗', '冲不进来', '今晚住这儿']) {
  const result = quality(title)
  assert.equal(result.titleValid, true, `${title} can remain metadata if already finalized`)
  assert.notEqual(result.status, 'pass', `${title} must not be treated as a clean pass`)
  assert.ok(result.reason, `${title} should carry a warning reason`)
}

{
  const result = quality('放那儿')
  assert.equal(result.titleValid, false, 'short imperative dialogue fragments should be hard rejected')
  assert.equal(result.titleInvalidReason, 'oral_fragment')
}

const cleaned = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: 'reason', reason: 'bad' },
    { title: '旧铜钥匙', type: 'item', reason: 'specific item' }
  ]
}), { chapterNum: 70 })
assert.equal(cleaned, '旧铜钥匙', 'internal words must not win final title selection')

const selectedFrom78To82Regression = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '别管我', type: 'result', reason: '对白碎片' },
    { title: '里面', type: 'place', reason: '方向残片' },
    { title: '谁派你来的', type: 'conflict', reason: '对白问句' },
    { title: '庚七密室', type: 'place', reason: '本章核心地点' },
    { title: '星账换令', type: 'result', reason: '不可逆代价' },
    { title: '密约残页', type: 'item', reason: '关键物证' }
  ]
}), {
  chapterNum: 78,
  content: '陆沉舟进了庚七密室，星账换令之后，只剩密约残页留在桌上。'
})
assert.equal(
  selectedFrom78To82Regression,
  '庚七密室',
  'candidate selection should prefer core place/item/cost/stage-answer titles over dialogue or direction fragments'
)

const selectedFrom83To86Regression = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '还有多远', type: 'event', reason: '路程对白碎片' },
    { title: '这通向哪', type: 'place', reason: '方向问句' },
    { title: '不一定', type: 'result', reason: '口语判断' },
    { title: '坐', type: 'event', reason: '单字动作' },
    { title: '星债会地窖', type: 'place', reason: '本章核心地点' },
    { title: '铁盒纸条', type: 'item', reason: '关键物证' },
    { title: '染坊钥匙', type: 'item', reason: '关键道具' },
    { title: '东城染坊', type: 'place', reason: '主要场景' }
  ]
}), {
  chapterNum: 83,
  content: '陆沉舟进了星债会地窖，摸到铁盒纸条，又在东城染坊拿到染坊钥匙。'
})
assert.equal(
  selectedFrom83To86Regression,
  '星债会地窖',
  'candidate selection should prefer concrete place/item/result titles over route questions, oral judgments, and one-character actions'
)

const chapter88PositiveContext = {
  chapterNum: 88,
  beatPlan: '陆沉舟进入星债会地窖，在东城染坊找到铁箱账本和三号仓钥。',
  content: '马三低声说“就是这里”。陆沉舟没有接话，先打开铁箱账本，又把三号仓钥和染坊钥匙压在账页下。'
}
{
  const result = getChapterTitleQuality('就是这里', { ...chapter88PositiveContext, titleSource: 'initial_title' })
  assert.equal(result.titleValid, false, 'chapter 88 initialTitle=就是这里 must hard fail')
  assert.match(result.titleInvalidReason, /direction|location|fragment/i)
}

const selectedFrom88PositiveMaterial = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '就是这里', type: 'place', reason: '对白位置残片' },
    { title: '铁箱账本', type: 'item', reason: '关键证据' }
  ]
}), chapter88PositiveContext)
assert.equal(
  selectedFrom88PositiveMaterial,
  '铁箱账本',
  'positive concrete material should beat demonstrative dialogue fragments'
)

assert.match(
  cleanGeneratedChapterTitle('就是这里', chapter88PositiveContext),
  /^(铁箱账本|三号仓钥|染坊钥匙|东城染坊|星债会地窖)$/,
  'cleanup should fall back to positive chapter facts instead of accepting a bad generated title'
)

const positiveFallbackTitle = deriveFallbackChapterTitle(chapter88PositiveContext)
assert.match(
  positiveFallbackTitle,
  /^(铁箱账本|三号仓钥|染坊钥匙|东城染坊|星债会地窖)$/,
  'fallback should derive a positive material title from chapter facts'
)

const fallbackFromDialogueHeavyText = deriveFallbackChapterTitle({
  chapterNum: 84,
  beatPlan: '两人沿暗道走，马三问“这通向哪”，陆沉舟没有答。他们最终进入东城染坊，发现铁盒纸条和染坊钥匙。',
  content: '“还有多远？”\n“不一定。”\n陆沉舟没有接话，只把铁盒纸条压进袖口。东城染坊的后门开着，染坊钥匙挂在门内。'
})
assert.notEqual(fallbackFromDialogueHeavyText, '还有多远', 'fallback must not use route-question dialogue as title')
assert.notEqual(fallbackFromDialogueHeavyText, '这通向哪', 'fallback must not use direction-question dialogue as title')
assert.notEqual(fallbackFromDialogueHeavyText, '不一定', 'fallback must not use oral judgment dialogue as title')
assert.match(
  fallbackFromDialogueHeavyText,
  /^(东城染坊|铁盒纸条|染坊钥匙)$/,
  'fallback should choose a concrete place or item from outline/content'
)

const backendChapters = readFileSync('backend/routers/chapters.py', 'utf8')
assert.match(backendChapters, /CHAPTER_TITLE_INTERNAL_FIELD_RE/, 'backend title endpoint should share internal field hard gate')
assert.match(backendChapters, /CHAPTER_TITLE_ORAL_FRAGMENT_RE/, 'backend title endpoint should reject short oral imperative fragments')
assert.match(backendChapters, /CHAPTER_TITLE_ROUTE_QUESTION_RE/, 'backend title endpoint should reject route/distance questions')
assert.match(backendChapters, /CHAPTER_TITLE_ORAL_JUDGMENT_RE/, 'backend title endpoint should reject oral judgment answers')
assert.match(backendChapters, /CHAPTER_TITLE_SINGLE_ACTION_RE/, 'backend title endpoint should reject single-character actions')
assert.match(backendChapters, /UPDATE chapters SET title=%s, updated_at=%s/, 'metadata-only title endpoint should update chapter metadata')
assert.doesNotMatch(
  backendChapters.match(/async def update_chapter_title[\s\S]*?async def update_chapter_summary/)?.[0] || '',
  /chapter_versions/,
  'metadata-only title repair must not edit chapter_versions content'
)

console.log('chapter title quality contract passed')
