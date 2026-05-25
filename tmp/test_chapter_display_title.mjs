import assert from 'node:assert/strict'
import {
  formatChapterDisplayTitle,
  isDefaultChapterTitle
} from '../frontend/src/prompts/chapter.js'

const defaultChapter = { chapterNum: 12, title: '第 12 章' }
const namedChapter = { chapterNum: 12, title: '旧宅无名' }

assert.equal(isDefaultChapterTitle(defaultChapter.title, defaultChapter.chapterNum), true)
assert.equal(formatChapterDisplayTitle(defaultChapter), '第 12 章')
assert.equal(formatChapterDisplayTitle(namedChapter), '第 12 章 · 旧宅无名')
assert.equal(formatChapterDisplayTitle(namedChapter, { includeNumber: false }), '旧宅无名')

console.log('CHAPTER_DISPLAY_TITLE_OK')
