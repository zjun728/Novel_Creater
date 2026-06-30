import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runDraftRepairPipeline } from '../frontend/src/application/writer-flow/draft-repair-pipeline.js'

const calls = []
const result = await runDraftRepairPipeline({
  rawContent: ' raw draft ',
  cleaner: content => {
    calls.push(`clean:${content}`)
    return 'cleaned'
  },
  repairProseRhythm: async content => {
    calls.push(`prose:${content}`)
    return `${content}|prose`
  },
  repairNotXButY: async content => {
    calls.push(`notxy:${content}`)
    return `${content}|notxy`
  },
  repairParagraphRepetition: async content => {
    calls.push(`paragraph:${content}`)
    return `${content}|paragraph`
  }
})

assert.equal(result, 'cleaned|prose|notxy|paragraph')
assert.deepEqual(calls, [
  'clean: raw draft ',
  'prose:cleaned',
  'notxy:cleaned|prose',
  'paragraph:cleaned|prose|notxy'
])

await assert.rejects(
  () => runDraftRepairPipeline({
    rawContent: 'raw',
    cleaner: () => 'kept',
    repairProseRhythm: async () => '   ',
    repairNotXButY: async content => content,
    repairParagraphRepetition: async content => content,
    emptyDraftErrorMessage: 'empty draft guard works'
  }),
  /empty draft guard works/
)

const identityResult = await runDraftRepairPipeline({
  rawContent: 'raw',
  cleaner: content => content.trim()
})
assert.equal(identityResult, 'raw', 'missing repair callbacks should behave as identity steps')

const moduleSource = readFileSync('frontend/src/application/writer-flow/draft-repair-pipeline.js', 'utf8')
assert.doesNotMatch(
  moduleSource,
  /@\/stores|@\/api|chatCompletion|buildChapterPrompt|buildProseRhythm|buildNotXButY|buildParagraph|finalizeVersion|storyBlock|setting|prompt/i,
  'draft repair pipeline command must stay orchestration-only and avoid store/API/prompt/finalization/story dependencies'
)

const writerSource = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
assert.match(writerSource, /runDraftRepairPipeline/, 'writerStore should call the extracted draft repair pipeline')
assert.doesNotMatch(
  writerSource,
  /content\s*=\s*cleanGeneratedChapterText\(content\)\s*[\r\n]+\s*content\s*=\s*await repairProseRhythmIfNeeded\([^)]*\)\s*[\r\n]+\s*content\s*=\s*await repairNotXButYIfNeeded\([^)]*\)\s*[\r\n]+\s*content\s*=\s*await repairParagraphRepetitionIfNeeded\([^)]*\)/,
  'writerStore should not keep the old inline draft repair sequence'
)
assert.match(
  writerSource,
  /emptyDraftErrorMessage:\s*'AI 生成正文为空，请重新生成或切换模型后重试。'/,
  'writerStore must preserve the existing empty draft error message'
)

console.log('writer flow draft repair pipeline contract passed')
