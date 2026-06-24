import assert from 'node:assert/strict'

import {
  buildChapterTitlePrompt,
  buildChapterTitleSystemPrompt,
  cleanGeneratedChapterTitle
} from '../frontend/src/prompts/chapter.js'

const systemPrompt = buildChapterTitleSystemPrompt()
assert.match(systemPrompt, /真实网文目录/)
assert.match(systemPrompt, /朴素/)
assert.match(systemPrompt, /1-6/)
assert.match(systemPrompt, /JSON/)
assert.match(systemPrompt, /event\|place\|person\|skill\|weapon\|item\|organization\|conflict\|result/)

const prompt = buildChapterTitlePrompt({
  chapterNum: 84,
  beatPlan: '本章事件：林远在火灶房审问回收组女人。核心冲突：她不肯说出金龙宝行的下一步。',
  content: '火灶房里还留着柴灰。林远按住黄金棺材上的裂口，侯小妹站在门边，没有替他说话。',
  existingTitles: ['档案室', '第七封信', '服软']
})

assert.match(prompt, /本章正文/)
assert.match(prompt, /简短小纲/)
assert.match(prompt, /最近 5 个章名/)
assert.match(prompt, /可以直接使用第一次出现的重要人物、功法、武器、组织、地点或道具名/)
assert.doesNotMatch(prompt, /物象 \+ 状态/)
assert.doesNotMatch(prompt, /必须换标题结构/)

for (const title of ['审问', '火灶房', '侯小妹', '炼灵', '黄金棺材', '金龙宝行', '服软']) {
  assert.equal(cleanGeneratedChapterTitle(title), title, `${title} should be accepted as a simple catalog title`)
}

console.log('CHAPTER_TITLE_SIMPLE_CANDIDATES_CONTRACT_OK')
