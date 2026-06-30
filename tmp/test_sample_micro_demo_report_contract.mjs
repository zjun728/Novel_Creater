import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  analyzeChapter
} from './story_humanity_rerun_21_25.mjs'

const liveRunner = fs.readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const storyHumanity = fs.readFileSync('tmp/story_humanity_rerun_21_25.mjs', 'utf8')

for (const field of [
  'sampleCardInjected',
  'sampleCardId',
  'sampleCardTitle',
  'sampleCardType',
  'sampleInjectionReason',
  'microDemoChars',
  'sourceFieldsStripped',
  'sampleLeakageDetected'
]) {
  assert.ok(liveRunner.includes(field), `live runner should write ${field}`)
  assert.ok(storyHumanity.includes(field), `story humanity report should read ${field}`)
}
assert.ok(
  liveRunner.includes('existingReport.sampleCardInjected === true'),
  'live runner must not overwrite an earlier true sample injection with a later false diagnostics refresh'
)

const chapter = analyzeChapter({
  chapterNum: 63,
  reportEntry: {
    title: '嘴硬',
    finalized: true,
    wordCount: 4600,
    sampleCardInjected: true,
    sampleCardId: 'dialogue-v2_2-01-tough-care',
    sampleCardTitle: '嘴硬关心：嫌弃话里藏照顾',
    sampleCardType: 'prompt_injectable_dialogue',
    sampleInjectionReason: '对话场景匹配：嘴硬关心',
    microDemoChars: 124,
    sourceFieldsStripped: true,
    sampleLeakageDetected: false
  },
  beat: {
    content: JSON.stringify({
      emotionalAnchor: '嘴硬关心',
      relationshipDelta: '互相多等半步',
      stageAnswerForReader: '确认两人还愿意合作'
    })
  },
  content: '小九嘴上嫌他麻烦，手上却先把药塞过去。陆沉舟说没事，她沉默了一下，把话岔开。'
})

assert.equal(chapter.sampleCardInjected, true)
assert.equal(chapter.sampleCardId, 'dialogue-v2_2-01-tough-care')
assert.equal(chapter.sampleCardType, 'prompt_injectable_dialogue')
assert.equal(chapter.sampleInjectionReason, '对话场景匹配：嘴硬关心')
assert.equal(chapter.microDemoChars, 124)
assert.equal(chapter.sourceFieldsStripped, true)
assert.equal(chapter.sampleLeakageDetected, false)

console.log('sample micro demo report contract passed')
