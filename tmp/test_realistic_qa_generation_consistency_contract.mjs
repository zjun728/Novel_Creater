import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow_fixed.mjs', 'utf8')
const chapterPromptSource = readFileSync('frontend/src/prompts/chapter.js', 'utf8')

for (const keyword of ['时间线连续性', '状态延续', '道具来源', '人物铺垫', '伏笔铺垫']) {
  assert.match(source, new RegExp(keyword), `真实流程 QA 生成链路应覆盖 ${keyword}`)
}

assert.match(
  `${source}\n${chapterPromptSource}`,
  /不要输出[\s\S]*标题[\s\S]*Markdown 标题[\s\S]*# 第N章[\s\S]*第N章/,
  '真实流程 QA 正文生成提示词应禁止章节标题泄漏'
)

assert.match(
  source,
  /function cleanQaGeneratedText\(text\)[\s\S]*isOpeningMetaLine[\s\S]*第\\s\*/,
  '真实流程 QA 应清洗开头 Markdown/章节标题'
)

assert.match(
  source,
  /best\.length <= 1300[\s\S]*第 \$\{chapterNum\} 章小纲已自动压缩/,
  '真实流程 QA 小纲压缩只有进入 1300 字符以内才算自动压缩通过'
)

console.log('realistic QA generation consistency contract tests passed')
