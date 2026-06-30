function requireLoader(loaders = {}, name) {
  const loader = loaders[name]
  if (typeof loader !== 'function') {
    throw new Error(`missing writer context loader: ${name}`)
  }
  return loader
}

export function resolveInitialEditorState({
  chapter = null,
  versions = [],
  draft = null
} = {}) {
  if (draft?.content) {
    return {
      source: 'draft',
      editorContent: draft.content,
      loadedEditorSnapshot: draft.content,
      currentVersion: null,
      shouldUpdateCurrentVersion: false
    }
  }

  if (chapter?.finalVersionId) {
    const final = (Array.isArray(versions) ? versions : []).find(version => version.id === chapter.finalVersionId)
    const content = final?.content || ''
    return {
      source: 'final',
      editorContent: content,
      loadedEditorSnapshot: content,
      currentVersion: final || null,
      shouldUpdateCurrentVersion: true
    }
  }

  if (Array.isArray(versions) && versions.length > 0) {
    const currentVersion = versions[0]
    return {
      source: 'latestVersion',
      editorContent: currentVersion?.content || '',
      loadedEditorSnapshot: currentVersion?.content || '',
      currentVersion,
      shouldUpdateCurrentVersion: true
    }
  }

  return {
    source: 'empty',
    editorContent: '',
    loadedEditorSnapshot: '',
    currentVersion: null,
    shouldUpdateCurrentVersion: true
  }
}

export async function runLoadWriterContextData({
  projectId,
  loaders = {}
} = {}) {
  const loaderNames = [
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

  await Promise.all(loaderNames.map(name => requireLoader(loaders, name)(projectId)))
  return { ok: true }
}

export async function runLoadWriterChapterSession({
  projectId,
  chapterNum,
  loaders = {}
} = {}) {
  await requireLoader(loaders, 'loadChapters')(projectId)
  await requireLoader(loaders, 'loadBlocks')(projectId)
  const chapter = await requireLoader(loaders, 'getOrCreateChapter')(projectId, chapterNum)
  const versions = await requireLoader(loaders, 'loadVersions')(projectId, chapter.id)
  const savedBeatPlan = await requireLoader(loaders, 'loadChapterBeatPlan')(projectId, chapterNum)
  const previousChapterEnding = await requireLoader(loaders, 'loadPreviousChapterEnding')()
  const recentChapterEndings = await requireLoader(loaders, 'loadRecentChapterEndings')()
  const draft = await requireLoader(loaders, 'loadTempDraft')(projectId, chapterNum)
  const initialEditorState = resolveInitialEditorState({
    chapter,
    versions,
    draft
  })

  return {
    chapter,
    versions: Array.isArray(versions) ? versions : [],
    beatPlanText: savedBeatPlan?.content || '',
    beatPlanSavedText: savedBeatPlan?.content || '',
    beatPlanStageSnapshot: savedBeatPlan?.blockStageSnapshot || null,
    previousChapterEnding,
    recentChapterEndings,
    editorContent: initialEditorState.editorContent,
    loadedEditorSnapshot: initialEditorState.loadedEditorSnapshot,
    shouldUpdateCurrentVersion: initialEditorState.shouldUpdateCurrentVersion,
    currentVersion: initialEditorState.currentVersion,
    initialEditorSource: initialEditorState.source
  }
}
