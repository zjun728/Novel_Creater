import { computed, ref } from 'vue'

function draftFrom(workspace) {
  return workspace?.workingDraft || null
}

export function createChapterEditorState() {
  const editorValue = ref('')
  const baselineContent = ref('')
  const baselineRevision = ref(null)
  const editGeneration = ref(0)

  const editorContent = computed({
    get: () => editorValue.value,
    set: value => {
      editorValue.value = String(value ?? '')
      editGeneration.value += 1
    },
  })
  const dirty = computed(() => editorValue.value !== baselineContent.value)

  function setBaseline(workspace, { synchronizeEditor }) {
    const draft = draftFrom(workspace)
    const content = String(draft?.content ?? '')
    baselineContent.value = content
    baselineRevision.value = draft?.revision ?? null
    if (synchronizeEditor) editorValue.value = content
  }

  function syncFromWorkspace(workspace) {
    setBaseline(workspace, { synchronizeEditor: true })
  }

  function beginSave() {
    return { editGeneration: editGeneration.value }
  }

  function finishSave(workspace, token) {
    const canSynchronize = token?.editGeneration === editGeneration.value
    setBaseline(workspace, { synchronizeEditor: canSynchronize })
  }

  function finishGeneration(workspace) {
    setBaseline(workspace, { synchronizeEditor: true })
  }

  return {
    editorContent,
    baselineContent,
    baselineRevision,
    dirty,
    syncFromWorkspace,
    beginSave,
    finishSave,
    finishGeneration,
  }
}

export function decideChapterNavigation({
  busy,
  dirty,
  confirmDiscard,
}) {
  if (busy) return false
  if (!dirty) return true
  return Boolean(confirmDiscard())
}
