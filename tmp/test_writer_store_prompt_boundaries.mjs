import assert from 'node:assert/strict'
import fs from 'node:fs'

const source = fs.readFileSync('frontend/src/stores/writerStore.js', 'utf8')

assert.match(source, /@\/prompts\/chapterDraftPrompt/, 'writer store should use draft prompt boundary')
assert.match(source, /@\/prompts\/chapterPlanPrompt/, 'writer store should use plan prompt boundary')
assert.match(source, /buildDraftSystemPrompt as buildChapterSystemPrompt/)
assert.match(source, /buildScenePlanPrompt as buildChapterBeatPrompt/)
assert.doesNotMatch(
  source,
  /buildChapterSystemPrompt,\s*\n\s*buildChapterPrompt,\s*\n\s*buildChapterBeatSystemPrompt,\s*\n\s*buildChapterBeatPrompt,/,
  'writer store should not import all main generation prompts from the legacy chapter module'
)
