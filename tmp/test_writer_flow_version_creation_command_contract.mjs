import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { runCreateVersionCommand } from '../frontend/src/application/writer-flow/version-creation-command.js'

{
  const calls = []
  const result = await runCreateVersionCommand({
    projectId: 'project-1',
    chapter: { id: 'chapter-1' },
    chapterNum: 12,
    title: '融合候选',
    content: '正文',
    versionType: 'ai_candidate',
    sourceModelId: 'model-1',
    promptBrief: '多模型融合版',
    createVersion: async (...args) => {
      calls.push(args)
      return { id: 'version-1', title: args[3].title }
    }
  })

  assert.equal(result.ok, true)
  assert.equal(result.version.id, 'version-1')
  assert.deepEqual(calls, [[
    'project-1',
    'chapter-1',
    12,
    {
      title: '融合候选',
      content: '正文',
      versionType: 'ai_candidate',
      sourceModelId: 'model-1',
      promptBrief: '多模型融合版'
    }
  ]])
}

{
  await assert.rejects(
    () => runCreateVersionCommand({
      projectId: 'project-1',
      chapter: { id: 'chapter-1' },
      chapterNum: 12,
      content: '   ',
      createVersion: async () => ({ id: 'never' })
    }),
    /version content is empty/
  )
}

{
  await assert.rejects(
    () => runCreateVersionCommand({
      projectId: 'project-1',
      chapter: {},
      chapterNum: 12,
      content: '正文',
      createVersion: async () => ({ id: 'never' })
    }),
    /chapter id is required/
  )
}

{
  await assert.rejects(
    () => runCreateVersionCommand({
      projectId: 'project-1',
      chapter: { id: 'chapter-1' },
      chapterNum: 0,
      content: '正文',
      createVersion: async () => ({ id: 'never' })
    }),
    /chapterNum is required/
  )
}

{
  const calls = []
  await runCreateVersionCommand({
    projectId: 'project-1',
    chapter: { id: 'chapter-1' },
    chapterNum: 12,
    content: '正文',
    createVersion: async (...args) => {
      calls.push(args)
      return { id: 'version-defaults' }
    }
  })
  assert.deepEqual(calls[0][3], {
    title: '',
    content: '正文',
    versionType: 'ai_candidate',
    sourceModelId: null,
    promptBrief: ''
  })
}

const moduleSource = readFileSync('frontend/src/application/writer-flow/version-creation-command.js', 'utf8')
assert.doesNotMatch(
  moduleSource,
  /@\/stores|@\/api|chatCompletion|build[A-Z]\w*Prompt|from ['"][^'"]*prompts|finalizeVersion|storyBlock|setting|window|document|localStorage/i,
  'version creation command must stay orchestration-only and avoid store/API/prompt/finalization/story dependencies'
)

const writerViewSource = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const fusionPanelSource = readFileSync('frontend/src/components/writer/FusionPanel.vue', 'utf8')
assert.match(writerViewSource, /@\/application\/writer-flow\/version-creation-command/)
assert.match(fusionPanelSource, /@\/application\/writer-flow\/version-creation-command/)
assert.match(writerViewSource, /runCreateVersionCommand\(/)
assert.match(fusionPanelSource, /runCreateVersionCommand\(/)
assert.doesNotMatch(writerViewSource, /writerStore\.createVersion\(/, 'WriterView should not directly call positional createVersion')
assert.doesNotMatch(fusionPanelSource, /writerStore\.createVersion\(/, 'FusionPanel should not directly call positional createVersion')

console.log('writer flow version creation command contract passed')
