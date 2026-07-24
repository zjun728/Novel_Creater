import { computed, ref } from 'vue'

const VOLUME_FIELDS = Object.freeze([
  'title',
  'coreChange',
  'mainPressure',
  'ensembleFocus',
  'forbiddenEvents',
])

const PLOT_FIELDS = Object.freeze([
  'title',
  'plotType',
  'storyQuestion',
  'futureDirection',
  'expectedPayoff',
  'relatedCharacters',
])

const clone = value => (
  value == null ? value : JSON.parse(JSON.stringify(value))
)
const active = node => node?.lifecycle !== 'retired'
const identity = node => String(node?.id || node?.clientNodeKey || '')

function activeNodes(items) {
  return Array.isArray(items) ? items.filter(active) : []
}

function hasText(value) {
  return String(value || '').trim().length > 0
}

export function isCompletePlanningAggregate(content) {
  if (!content) return false
  const volumes = activeNodes(content.volumes)
  const plots = activeNodes(content.plots)
  const storyBlocks = activeNodes(content.storyBlocks)
  const volumeIds = new Set(volumes.map(identity).filter(Boolean))
  const plotIds = new Set(plots.map(identity).filter(Boolean))
  const blockIds = new Set(storyBlocks.map(identity).filter(Boolean))

  if (!volumes.length || !plots.length || !storyBlocks.length) return false
  if (volumes.some(volume => !hasText(volume.title))) return false
  if (plots.some(plot => !hasText(plot.title))) return false

  const activeBlockId = String(content.activeStoryBlockRef || '')
  if (!blockIds.has(activeBlockId)) return false
  const block = storyBlocks.find(node => identity(node) === activeBlockId)
  const stages = activeNodes(block?.stages)
  const plotRefs = Array.isArray(block?.plotRefs) ? block.plotRefs : []
  return (
    hasText(block?.title)
    && volumeIds.has(String(block?.volumeRef || ''))
    && plotRefs.length > 0
    && plotRefs.every(plotRef => plotIds.has(String(plotRef)))
    && stages.length > 0
    && stages.some(stage => activeNodes(stage.sceneTasks).length > 0)
  )
}

function emptyPlanningContent() {
  return {
    activeStoryBlockRef: null,
    volumes: [],
    plots: [],
    storyBlocks: [],
  }
}

function projectPlanningRoute(route, projectId) {
  return (
    ['ProjectPlanningVolumes', 'ProjectPlanningPlots'].includes(String(route?.name || ''))
    && String(route?.params?.projectId || '') === String(projectId || '')
  )
}

export function createPlanningWorkspaceController({
  store,
  projectId,
  isArchived = () => false,
  keyFactory = () => globalThis.crypto.randomUUID(),
  operationStore = null,
  confirmLeave = () => true,
} = {}) {
  if (!store || typeof projectId !== 'function') {
    throw new TypeError('store and projectId are required')
  }

  const historyOpen = ref(false)
  const authorInstructions = ref('')
  const notice = ref('')
  const activeProject = ref('')
  const projectScope = ref(0)
  const busy = computed(() => Boolean(
    store.loading
    || store.saving
    || store.confirming
    || store.generating
    || store.reconciling,
  ))
  const hasCriticalRecovery = computed(() => Boolean(
    store.generationOutcomeUnknown
    || store.awaitingAuthoritativeReload,
  ))
  const editorLocked = computed(() => busy.value || hasCriticalRecovery.value)
  const hasUnsavedLocalUI = computed(() => hasText(authorInstructions.value))
  const readOnly = computed(() => Boolean(
    isArchived()
    || store.state?.basisStatus === 'archived'
    || store.state?.draft?.status === 'superseded'
    || store.state?.capabilities?.edit === false,
  ))
  const editable = computed(() => (
    !readOnly.value
    && store.state?.capabilities?.edit === true
    && store.state?.draft != null
  ))
  const canCreateDraft = computed(() => (
    !readOnly.value
    && store.state?.capabilities?.edit === true
    && store.state?.draft == null
    && !busy.value
  ))
  const canSave = computed(() => (
    editable.value
    && store.dirty === true
    && !busy.value
    && !hasCriticalRecovery.value
  ))
  const complete = computed(() => isCompletePlanningAggregate(store.localContent))
  const canConfirm = computed(() => (
    editable.value
    && store.state?.capabilities?.confirm === true
    && store.dirty !== true
    && complete.value
    && !busy.value
    && !hasCriticalRecovery.value
  ))
  const canGenerate = computed(() => (
    editable.value
    && store.state?.capabilities?.generate === true
    && store.dirty !== true
    && !busy.value
    && !hasCriticalRecovery.value
  ))
  const localOverlay = computed(() => Boolean(
    store.generating || store.reconciling,
  ))
  const generationDisabledReason = computed(() => {
    if (hasCriticalRecovery.value) return '上次生成结果尚未核对，请先恢复权威状态。'
    if (store.dirty) return '请先保存本地修改，再使用 AI 生成。'
    if (!editable.value) return '当前规划不可编辑。'
    if (store.state?.capabilities?.generate !== true) {
      return '规划模型尚未就绪；手工规划仍可继续。'
    }
    if (busy.value) return '请等待当前操作完成。'
    return ''
  })

  function replaceCollection(collection, items) {
    if (!editable.value || editorLocked.value || !store.localContent) return false
    store.editLocal({
      ...clone(store.localContent),
      [collection]: items,
    })
    return true
  }

  function addNode(collection, fields) {
    if (!editable.value || editorLocked.value) return false
    const existing = store.localContent?.[collection] || []
    const node = {
      clientNodeKey: String(keyFactory()),
      order: Math.max(0, ...existing.map(item => Number(item.order) || 0)) + 1,
      lifecycle: 'active',
    }
    for (const field of fields) node[field] = field.endsWith('s') ? [] : ''
    return replaceCollection(collection, [
      ...existing,
      node,
    ])
  }

  function updateNode(collection, nodeKey, patch, fields) {
    const allowed = new Set(fields)
    const items = (store.localContent?.[collection] || []).map(node => {
      if (identity(node) !== String(nodeKey) || !active(node)) return node
      const next = { ...node }
      for (const [field, value] of Object.entries(patch || {})) {
        if (allowed.has(field)) next[field] = clone(value)
      }
      return next
    })
    return replaceCollection(collection, items)
  }

  function removeNode(collection, nodeKey) {
    const current = store.localContent?.[collection] || []
    const node = current.find(item => identity(item) === String(nodeKey))
    if (!node || !active(node)) return false
    const items = node.id
      ? current.map(item => (
          identity(item) === String(nodeKey)
            ? { ...item, lifecycle: 'retired' }
            : item
        ))
      : current.filter(item => identity(item) !== String(nodeKey))
    return replaceCollection(collection, items)
  }

  function moveNode(collection, nodeKey, direction) {
    const items = [...(store.localContent?.[collection] || [])]
    const from = items.findIndex(item => identity(item) === String(nodeKey))
    if (from < 0 || !active(items[from])) return false
    const activeIndexes = items
      .map((item, index) => active(item) ? index : -1)
      .filter(index => index >= 0)
    const activePosition = activeIndexes.indexOf(from)
    const targetPosition = activePosition + Math.sign(Number(direction) || 0)
    if (activePosition < 0 || targetPosition < 0 || targetPosition >= activeIndexes.length) {
      return false
    }
    const to = activeIndexes[targetPosition]
    const fromOrder = items[from].order
    const toOrder = items[to].order
    const moved = { ...items[from], order: toOrder }
    const displaced = { ...items[to], order: fromOrder }
    items[from] = displaced
    items[to] = moved
    return replaceCollection(collection, items)
  }

  function enterProject(nextProjectId) {
    const normalized = String(nextProjectId || '')
    if (normalized === activeProject.value) return false
    activeProject.value = normalized
    authorInstructions.value = ''
    notice.value = ''
    historyOpen.value = false
    projectScope.value += 1
    return true
  }

  async function hydrate() {
    const targetProjectId = String(projectId() || '')
    if (!targetProjectId) return undefined
    enterProject(targetProjectId)
    return store.ensureLoaded(targetProjectId)
  }

  async function createManualDraft() {
    if (!canCreateDraft.value) return undefined
    const result = await store.createDraft(String(projectId()), {
      idempotencyKey: String(keyFactory()),
    })
    if (store.localContent == null) store.editLocal(emptyPlanningContent())
    notice.value = '已建立空白规划工作稿'
    return result
  }

  async function save() {
    if (!canSave.value) return undefined
    const result = await store.saveDraft({
      idempotencyKey: String(keyFactory()),
    })
    notice.value = '规划工作稿已保存'
    return result
  }

  async function generate(instructions = authorInstructions.value) {
    if (!canGenerate.value) return undefined
    const result = await store.generateDraft({
      idempotencyKey: String(keyFactory()),
      authorInstructions: String(instructions || ''),
    })
    if (result?.status === 'succeeded') notice.value = 'AI 规划已写入当前工作稿'
    return result
  }

  async function reconcile() {
    const result = await store.reconcileGeneration()
    if (result?.status === 'succeeded') notice.value = '已恢复并核对生成结果'
    return result
  }

  async function confirm() {
    if (!canConfirm.value) return undefined
    const operationId = operationStore?.start?.({
      label: '正在确认故事规划',
      detail: '确认会创建不可变规划修订',
      blocking: true,
    })
    try {
      const result = await store.confirmDraft({
        idempotencyKey: String(keyFactory()),
      })
      notice.value = '已确认新的故事规划修订'
      return result
    } finally {
      if (operationId) operationStore?.finish?.(operationId)
    }
  }

  function requestRouteLeave(to) {
    if (projectPlanningRoute(to, projectId())) return true
    if (
      !store.dirty
      && !hasCriticalRecovery.value
      && !store.generating
      && !hasUnsavedLocalUI.value
    ) return true
    return confirmLeave()
  }

  function beforeUnload(event) {
    if (
      !store.dirty
      && !hasCriticalRecovery.value
      && !store.generating
      && !hasUnsavedLocalUI.value
    ) return undefined
    event.preventDefault()
    event.returnValue = ''
    return ''
  }

  return {
    historyOpen,
    authorInstructions,
    notice,
    projectScope,
    busy,
    editorLocked,
    readOnly,
    editable,
    canCreateDraft,
    canSave,
    canConfirm,
    canGenerate,
    complete,
    localOverlay,
    hasCriticalRecovery,
    generationDisabledReason,
    enterProject,
    hydrate,
    createManualDraft,
    addVolume: () => addNode('volumes', VOLUME_FIELDS),
    updateVolume: (nodeKey, patch) => (
      updateNode('volumes', nodeKey, patch, VOLUME_FIELDS)
    ),
    removeVolume: nodeKey => removeNode('volumes', nodeKey),
    moveVolume: (nodeKey, direction) => moveNode('volumes', nodeKey, direction),
    addPlot: () => addNode('plots', PLOT_FIELDS),
    updatePlot: (nodeKey, patch) => (
      updateNode('plots', nodeKey, patch, PLOT_FIELDS)
    ),
    removePlot: nodeKey => removeNode('plots', nodeKey),
    movePlot: (nodeKey, direction) => moveNode('plots', nodeKey, direction),
    restoreNode: () => false,
    save,
    generate,
    reconcile,
    confirm,
    requestRouteLeave,
    beforeUnload,
  }
}
