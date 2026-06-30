import fs from 'node:fs'
import assert from 'node:assert/strict'

import {
  resolveInitialEditorState,
  runLoadWriterContextData,
  runLoadWriterChapterSession
} from '../frontend/src/application/writer-flow/context-session.js'

const draftState = resolveInitialEditorState({
  chapter: { finalVersionId: 'final-1' },
  versions: [{ id: 'final-1', content: 'final content' }],
  draft: { content: 'draft content' }
})
assert.equal(draftState.editorContent, 'draft content')
assert.equal(draftState.loadedEditorSnapshot, 'draft content')
assert.equal(draftState.currentVersion, null)
assert.equal(draftState.shouldUpdateCurrentVersion, false)
assert.equal(draftState.source, 'draft')

const finalState = resolveInitialEditorState({
  chapter: { finalVersionId: 'final-1' },
  versions: [
    { id: 'candidate-1', content: 'candidate content' },
    { id: 'final-1', content: 'final content' }
  ],
  draft: null
})
assert.equal(finalState.editorContent, 'final content')
assert.deepEqual(finalState.currentVersion, { id: 'final-1', content: 'final content' })
assert.equal(finalState.shouldUpdateCurrentVersion, true)
assert.equal(finalState.source, 'final')

const snakeFinalIgnoredState = resolveInitialEditorState({
  chapter: { final_version_id: 'final-1' },
  versions: [
    { id: 'candidate-1', content: 'candidate content' },
    { id: 'final-1', content: 'final content' }
  ],
  draft: null
})
assert.equal(snakeFinalIgnoredState.editorContent, 'candidate content')
assert.deepEqual(snakeFinalIgnoredState.currentVersion, { id: 'candidate-1', content: 'candidate content' })
assert.equal(snakeFinalIgnoredState.source, 'latestVersion')

const latestState = resolveInitialEditorState({
  chapter: {},
  versions: [{ id: 'candidate-1', content: 'candidate content' }],
  draft: null
})
assert.equal(latestState.editorContent, 'candidate content')
assert.deepEqual(latestState.currentVersion, { id: 'candidate-1', content: 'candidate content' })
assert.equal(latestState.shouldUpdateCurrentVersion, true)
assert.equal(latestState.source, 'latestVersion')

const emptyState = resolveInitialEditorState({ chapter: {}, versions: [], draft: null })
assert.equal(emptyState.editorContent, '')
assert.equal(emptyState.loadedEditorSnapshot, '')
assert.equal(emptyState.currentVersion, null)
assert.equal(emptyState.shouldUpdateCurrentVersion, true)
assert.equal(emptyState.source, 'empty')

const contextCalls = []
const contextLoaderNames = [
  'loadBible',
  'loadOutline',
  'loadCharacters',
  'loadPlotThreads',
  'loadCanonFacts',
  'loadSettingEntities',
  'loadSettingRelations',
  'loadSettingChangeEvents',
  'loadVolumes',
  'loadStoryBlocks',
  'loadCorrectionTasks',
  'loadSeeds'
]
await runLoadWriterContextData({
  projectId: 'p1',
  loaders: Object.fromEntries(contextLoaderNames.map(name => [
    name,
    async (projectId) => contextCalls.push([name, projectId])
  ]))
})
assert.deepEqual(contextCalls.map(call => call[0]), contextLoaderNames)
assert.deepEqual([...new Set(contextCalls.map(call => call[1]))], ['p1'])

const expectedError = new Error('boom')
await assert.rejects(
  () => runLoadWriterContextData({
    projectId: 'p1',
    loaders: {
      ...Object.fromEntries(contextLoaderNames.map(name => [name, async () => null])),
      loadSeeds: async () => { throw expectedError }
    }
  }),
  expectedError
)

const sessionCalls = []
const session = await runLoadWriterChapterSession({
  projectId: 'p1',
  chapterNum: 8,
  loaders: {
    loadChapters: async (projectId) => { sessionCalls.push(['loadChapters', projectId]); return [] },
    loadBlocks: async (projectId) => { sessionCalls.push(['loadBlocks', projectId]); return [] },
    getOrCreateChapter: async (projectId, chapterNum) => {
      sessionCalls.push(['getOrCreateChapter', projectId, chapterNum])
      return { id: 'c8', chapterNum: 8, finalVersionId: 'v-final' }
    },
    loadVersions: async (projectId, chapterId) => {
      sessionCalls.push(['loadVersions', projectId, chapterId])
      return [
        { id: 'v-candidate', content: 'candidate content' },
        { id: 'v-final', content: 'final content' }
      ]
    },
    loadChapterBeatPlan: async (projectId, chapterNum) => {
      sessionCalls.push(['loadChapterBeatPlan', projectId, chapterNum])
      return {
        content: 'beat plan',
        blockStageSnapshot: { storyBlockId: 'b1' }
      }
    },
    loadPreviousChapterEnding: async () => {
      sessionCalls.push(['loadPreviousChapterEnding'])
      return 'previous ending'
    },
    loadRecentChapterEndings: async () => {
      sessionCalls.push(['loadRecentChapterEndings'])
      return [{ chapterNum: 7, ending: 'recent ending' }]
    },
    loadTempDraft: async (projectId, chapterNum) => {
      sessionCalls.push(['loadTempDraft', projectId, chapterNum])
      return null
    }
  }
})
assert.deepEqual(sessionCalls.map(call => call[0]), [
  'loadChapters',
  'loadBlocks',
  'getOrCreateChapter',
  'loadVersions',
  'loadChapterBeatPlan',
  'loadPreviousChapterEnding',
  'loadRecentChapterEndings',
  'loadTempDraft'
])
assert.equal(session.chapter.id, 'c8')
assert.equal(session.versions.length, 2)
assert.equal(session.beatPlanText, 'beat plan')
assert.equal(session.beatPlanSavedText, 'beat plan')
assert.deepEqual(session.beatPlanStageSnapshot, { storyBlockId: 'b1' })
assert.equal(session.previousChapterEnding, 'previous ending')
assert.deepEqual(session.recentChapterEndings, [{ chapterNum: 7, ending: 'recent ending' }])
assert.equal(session.editorContent, 'final content')
assert.equal(session.loadedEditorSnapshot, 'final content')
assert.equal(session.currentVersion.id, 'v-final')
assert.equal(session.shouldUpdateCurrentVersion, true)

const moduleSource = fs.readFileSync('frontend/src/application/writer-flow/context-session.js', 'utf8')
const forbiddenPurePatterns = [
  /from ['"]vue['"]/,
  /pinia/,
  /stores\//,
  /api\//,
  /router/,
  /naive/i,
  /prompts\//,
  /chatCompletion/,
  /localStorage|sessionStorage/,
  /\bwindow\b|\bdocument\b/
]
for (const pattern of forbiddenPurePatterns) {
  assert.equal(pattern.test(moduleSource), false, `context session module must stay adapter-pure: ${pattern}`)
}

const writerViewSource = fs.readFileSync('frontend/src/views/WriterView.vue', 'utf8')
assert.match(writerViewSource, /@\/application\/writer-flow\/context-session/)
assert.match(writerViewSource, /async function loadContextData/)
assert.match(writerViewSource, /async function loadChapter/)
assert.match(writerViewSource, /初始化写字台失败/)
assert.match(writerViewSource, /创作上下文加载失败/)
assert.match(writerViewSource, /加载章节失败/)
assert.match(writerViewSource, /资料加载中/)
assert.match(writerViewSource, /function buildBaseContextResult/)
assert.match(writerViewSource, /function openContextPreview/)
assert.match(writerViewSource, /runLoadWriterContextData/)
assert.match(writerViewSource, /runLoadWriterChapterSession/)

console.log('writer flow context session contract passed')
