import {
  buildFallbackMarketDirections,
  extractMarketDirections
} from '../frontend/src/prompts/marketDirections.js'

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

const wrapped = extractMarketDirections(`{
  "directions": [
    {
      "title": "全球化背景下的东方玄幻逆袭文",
      "genre": "都市玄幻",
      "readerExpectation": "文化冲突和东方神秘力量的爽感",
      "whyNow": "异域背景加东方玄幻受欢迎",
      "seedAngle": "小人物在海外觉醒东方传承",
      "evidence": "起点样本",
      "risks": "文化刻板",
      "discussionPrompt": "讨论这个方向"
    }
  ]
}`)

const single = extractMarketDirections(`{
  "title": "单对象方向",
  "genre": "都市",
  "readerExpectation": "爽感",
  "whyNow": "热度",
  "seedAngle": "切入"
}`)

const fallback = buildFallbackMarketDirections({
  keywords: '玄幻 热门',
  items: [
    { title: '样本A', platform: '起点', category: '都市玄幻', tags: ['异能', '升级'] },
    { title: '样本B', platform: '番茄', category: '都市玄幻', tags: ['系统', '爽文'] }
  ]
})

assert(wrapped.length === 1 && wrapped[0].title.includes('全球化'), 'wrapped directions should parse')
assert(single.length === 1 && single[0].title === '单对象方向', 'single direction object should parse')
assert(fallback.length >= 1 && fallback[0].title, 'fallback directions should be generated')

console.log(JSON.stringify({ wrapped, single, fallback }, null, 2))
