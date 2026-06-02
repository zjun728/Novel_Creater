import assert from 'node:assert/strict'

import {
  buildChapterPrompt,
  buildChapterBeatPrompt,
  cleanGeneratedChapterText
} from '../frontend/src/prompts/chapter.js'

const leakedHeading = cleanGeneratedChapterText(`

# 第 2 章

林逐把铜钱按在掌心。
`)

assert.equal(
  leakedHeading,
  '林逐把铜钱按在掌心。',
  '正文清洗应移除开头空行后的 Markdown 章节标题'
)

const chineseHeading = cleanGeneratedChapterText(`
第十二章 旧井回声

井壁上的水忽然停了。
`)

assert.equal(
  chineseHeading,
  '井壁上的水忽然停了。',
  '正文清洗应移除中文数字章节标题，避免正文泄漏目录标题'
)

const proseStartsWithChapterPhrase = cleanGeneratedChapterText('第十二章，林逐终于明白井底那句话不是玩笑。')
assert.equal(
  proseStartsWithChapterPhrase,
  '第十二章，林逐终于明白井底那句话不是玩笑。',
  '正文清洗不能误删正常叙事句'
)

const prompt = buildChapterPrompt({
  chapterNum: 4,
  previousChapterEnding: '他把星盘碎片塞进口袋，听见井底有人叫他的名字。',
  beatPlan: '1. 林逐回到井边确认星盘来源。\n2. 黑衣人截断归路。'
})

for (const keyword of ['时间线连续性', '状态延续', '道具来源', '人物铺垫', '伏笔铺垫']) {
  assert.match(prompt, new RegExp(keyword), `正文提示词应前置 ${keyword} 防线`)
}

assert.match(
  prompt,
  /不要输出标题[\s\S]*Markdown[\s\S]*第\s*N\s*章/,
  '正文提示词应明确禁止输出 Markdown 或“第N章”章节标题'
)

const beatPrompt = buildChapterBeatPrompt({
  chapterNum: 4,
  previousChapterEnding: '他把星盘碎片塞进口袋，听见井底有人叫他的名字。',
  wordTarget: { target: 5000, min: 4500, max: 6500, hardMin: 4000, hardMax: 7000 }
})

for (const keyword of ['时间线连续性', '状态延续', '道具来源', '人物铺垫', '伏笔铺垫']) {
  assert.match(beatPrompt, new RegExp(keyword), `小纲提示词应前置 ${keyword} 自检`)
}

assert.match(
  beatPrompt,
  /小纲总长度控制在 700-1100 字[\s\S]*超过 1300 字/,
  '小纲提示词应把 700-1100 字作为目标，并明确超过 1300 字需要压缩'
)

console.log('chapter generation consistency contract tests passed')
