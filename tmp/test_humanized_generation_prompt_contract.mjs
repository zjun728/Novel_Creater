import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const chapterPrompt = readFileSync('frontend/src/prompts/chapter.js', 'utf8')

assert.match(
  chapterPrompt,
  /formatRecentChapterEndings/,
  'chapter prompt should format recent chapter endings so generation can avoid repeated ending templates'
)

assert.match(
  chapterPrompt,
  /最近章节结尾（避免重复模板）/,
  'chapter generation prompt should include recent ending anti-template context'
)

assert.match(
  chapterPrompt,
  /人性变化不能写成开关/,
  'chapter generation prompt should require gradual human/emotional state changes instead of switch-like behavior'
)

assert.match(
  chapterPrompt,
  /配角自主性/,
  'chapter generation prompt should explicitly require supporting characters to have their own agenda or habits'
)

assert.match(
  chapterPrompt,
  /信息揭示方式/,
  'chapter generation prompt should require reveals through evidence, action, failed attempts, or object response'
)

assert.match(
  chapterPrompt,
  /结尾形态/,
  'chapter beat prompt should plan the ending shape rather than falling back to a generic summary ending'
)

assert.match(
  chapterPrompt,
  /输出前静默自检[\s\S]*结尾模板[\s\S]*工具人[\s\S]*信息倾倒/,
  'chapter generation prompt should silently self-check template endings, tool-like characters, and information dumping'
)

console.log('humanized generation prompt contract tests passed')
