import assert from 'node:assert/strict'
import { extractSeedsFromText, isSavableSeed } from '../frontend/src/utils/seedParser.js'

const directionOnly = `这几个方向你可以先选一个。
\`\`\`json
[
  {
    "title": "直播鉴宝破案",
    "genre": "都市悬疑",
    "readerExpectation": "读者期待专业知识破局。",
    "whyNow": "市场上鉴宝和悬疑都有热度。"
  }
]
\`\`\`
`

assert.equal(extractSeedsFromText(directionOnly).length, 0)
assert.equal(isSavableSeed({ title: '只有标题' }), false)

const fullSeed = `[
  {
    "title": "旧货摊里的山海经",
    "genre": "都市奇幻",
    "logline": "旧货摊老板能从古物里读出妖怪遗愿。",
    "protagonist": "林逐，落魄古玩店学徒。",
    "desire": "找回父亲失踪的真相。",
    "coreConflict": "每次触碰古物都会替妖怪偿还一段因果。",
    "openingHook": "雨夜里，一枚裂开的铜钱开始说话。",
    "endingAnchor": "他在天亮前关上最后一扇旧货铺的门。"
  }
]`

const seeds = extractSeedsFromText(fullSeed)
assert.equal(seeds.length, 1)
assert.equal(seeds[0].title, '旧货摊里的山海经')
assert.equal(isSavableSeed(seeds[0]), true)

console.log('SEED_PARSER_COMPLETENESS_TEST_OK')
