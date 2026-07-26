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

const STORY_BLOCK_FIELDS = Object.freeze([
  'title',
  'volumeRef',
  'plotRefs',
  'entrySituation',
  'blockGoal',
  'mainPressure',
  'expectedChange',
  'openQuestions',
  'involvedCharacters',
])

const STAGE_FIELDS = Object.freeze([
  'title',
  'purpose',
  'dramaticQuestion',
])

const SCENE_TASK_FIELDS = Object.freeze([
  'task',
  'completionEvidence',
])

const clone = value => (
  value == null ? value : JSON.parse(JSON.stringify(value))
)
const active = node => node?.lifecycle === 'active'
const identity = node => String(node?.id || node?.clientNodeKey || '')

function activeNodes(items) {
  return Array.isArray(items) ? items.filter(active) : []
}

function hasText(value) {
  return String(value || '').trim().length > 0
}

function validMoveDirection(direction) {
  return direction === -1 || direction === 1
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
  if (volumes.some(volume => (
    !hasText(volume.title) || !hasText(volume.coreChange)
  ))) return false
  if (plots.some(plot => (
    !hasText(plot.title) || !hasText(plot.storyQuestion)
  ))) return false

  const activeBlockId = String(content.activeStoryBlockRef || '')
  if (!blockIds.has(activeBlockId)) return false
  const block = storyBlocks.find(node => identity(node) === activeBlockId)
  const stages = activeNodes(block?.stages)
  const plotRefs = Array.isArray(block?.plotRefs)
    ? block.plotRefs.map(plotRef => String(plotRef || ''))
    : []
  const sceneTasks = stages.flatMap(stage => activeNodes(stage.sceneTasks))
  return (
    hasText(block?.title)
    && hasText(block?.blockGoal)
    && volumeIds.has(String(block?.volumeRef || ''))
    && plotRefs.length > 0
    && new Set(plotRefs).size === plotRefs.length
    && plotRefs.every(plotRef => plotIds.has(plotRef))
    && stages.length > 0
    && stages.every(stage => (
      hasText(stage.title)
      && hasText(stage.purpose)
      && hasText(stage.dramaticQuestion)
    ))
    && sceneTasks.length > 0
    && sceneTasks.every(sceneTask => (
      hasText(sceneTask.task)
      && hasText(sceneTask.completionEvidence)
    ))
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
    [
      'ProjectPlanningVolumes',
      'ProjectPlanningPlots',
      'ProjectPlanningStoryBlocks',
    ].includes(String(route?.name || ''))
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
  const storyBlockUndo = ref(null)
  const canUndoStoryBlockEdit = computed(() => (
    storyBlockUndoRecoverable(storyBlockUndo.value, store.localContent)
  ))
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
    if (!validMoveDirection(direction)) return false
    const items = [...(store.localContent?.[collection] || [])]
    const from = items.findIndex(item => identity(item) === String(nodeKey))
    if (from < 0 || !active(items[from])) return false
    const activeIndexes = items
      .map((item, index) => active(item) ? index : -1)
      .filter(index => index >= 0)
    const activePosition = activeIndexes.indexOf(from)
    const targetPosition = activePosition + direction
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

  function nextOrder(items) {
    return Math.max(
      0,
      ...(Array.isArray(items) ? items : []).map(item => Number(item.order) || 0),
    ) + 1
  }

  function newEditableNode(fields, childCollection = '') {
    const node = {
      clientNodeKey: String(keyFactory()),
      order: 1,
      lifecycle: 'active',
    }
    for (const field of fields) node[field] = field.endsWith('s') ? [] : ''
    if (childCollection) node[childCollection] = []
    return node
  }

  function editStoryContent(edit) {
    if (!editable.value || editorLocked.value || !store.localContent) return false
    const content = clone(store.localContent)
    if (!edit(content)) return false
    store.editLocal(content)
    return true
  }

  function activeIndex(items, nodeKey) {
    return (Array.isArray(items) ? items : []).findIndex(node => (
      identity(node) === String(nodeKey) && active(node)
    ))
  }

  function storyBlockUndoRecoverable(undo, content) {
    if (!undo || !content) return false
    const undoKey = identity(undo.node)
    if (!undoKey) return false
    const storyBlocks = Array.isArray(content.storyBlocks)
      ? content.storyBlocks
      : []
    if (undo.kind === 'block') {
      return !storyBlocks.some(block => identity(block) === undoKey)
    }

    const blockIndex = activeIndex(storyBlocks, undo.blockKey)
    if (blockIndex < 0) return false
    const stages = Array.isArray(storyBlocks[blockIndex].stages)
      ? storyBlocks[blockIndex].stages
      : []
    if (undo.kind === 'stage') {
      return !stages.some(stage => identity(stage) === undoKey)
    }
    if (undo.kind !== 'task') return false

    const stageIndex = activeIndex(stages, undo.stageKey)
    if (stageIndex < 0) return false
    const sceneTasks = Array.isArray(stages[stageIndex].sceneTasks)
      ? stages[stageIndex].sceneTasks
      : []
    return !sceneTasks.some(sceneTask => identity(sceneTask) === undoKey)
  }

  function patchNode(node, patch, fields) {
    const allowed = new Set(fields)
    for (const [field, value] of Object.entries(patch || {})) {
      if (allowed.has(field)) node[field] = clone(value)
    }
  }

  function moveActiveSibling(items, nodeKey, direction) {
    if (!validMoveDirection(direction)) return false
    const from = activeIndex(items, nodeKey)
    if (from < 0) return false
    const activeIndexes = items
      .map((item, index) => active(item) ? index : -1)
      .filter(index => index >= 0)
    const activePosition = activeIndexes.indexOf(from)
    const targetPosition = activePosition + direction
    if (targetPosition < 0 || targetPosition >= activeIndexes.length) return false
    const to = activeIndexes[targetPosition]
    const fromOrder = items[from].order
    const toOrder = items[to].order
    const moved = { ...items[from], order: toOrder }
    const displaced = { ...items[to], order: fromOrder }
    items[from] = displaced
    items[to] = moved
    return true
  }

  function retireHistoricalSceneTasks(sceneTasks) {
    return (Array.isArray(sceneTasks) ? sceneTasks : []).flatMap(sceneTask => {
      return sceneTask.id
        ? [{ ...sceneTask, lifecycle: 'retired' }]
        : []
    })
  }

  function retireHistoricalStages(stages) {
    return (Array.isArray(stages) ? stages : []).flatMap(stage => {
      return stage.id
        ? [{
            ...stage,
            lifecycle: 'retired',
            sceneTasks: retireHistoricalSceneTasks(stage.sceneTasks),
          }]
        : []
    })
  }

  function addStoryBlock() {
    return editStoryContent(content => {
      const storyBlocks = Array.isArray(content.storyBlocks) ? content.storyBlocks : []
      const block = newEditableNode(STORY_BLOCK_FIELDS, 'stages')
      block.order = nextOrder(storyBlocks)
      content.storyBlocks = [...storyBlocks, block]
      return true
    })
  }

  function updateStoryBlock(blockKey, patch) {
    return editStoryContent(content => {
      const index = activeIndex(content.storyBlocks, blockKey)
      if (index < 0) return false
      patchNode(content.storyBlocks[index], patch, STORY_BLOCK_FIELDS)
      return true
    })
  }

  function removeStoryBlock(blockKey) {
    let undo = null
    const changed = editStoryContent(content => {
      const index = activeIndex(content.storyBlocks, blockKey)
      if (index < 0) return false
      const block = content.storyBlocks[index]
      const activeStoryBlockRef = content.activeStoryBlockRef
      const wasActive = String(activeStoryBlockRef || '') === identity(block)
      if (block.id) {
        content.storyBlocks[index] = {
          ...block,
          lifecycle: 'retired',
          stages: retireHistoricalStages(block.stages),
        }
      } else {
        undo = {
          kind: 'block',
          index,
          node: clone(block),
        }
        if (wasActive) undo.restoreActiveStoryBlockRef = activeStoryBlockRef
        content.storyBlocks.splice(index, 1)
      }
      if (wasActive) content.activeStoryBlockRef = null
      return true
    })
    if (changed && undo) storyBlockUndo.value = undo
    return changed
  }

  function moveStoryBlock(blockKey, direction) {
    return editStoryContent(content => (
      moveActiveSibling(content.storyBlocks, blockKey, direction)
    ))
  }

  function selectActiveStoryBlock(blockKey) {
    return editStoryContent(content => {
      if (activeIndex(content.storyBlocks, blockKey) < 0) return false
      content.activeStoryBlockRef = String(blockKey)
      return true
    })
  }

  function addStage(blockKey) {
    return editStoryContent(content => {
      const blockIndex = activeIndex(content.storyBlocks, blockKey)
      if (blockIndex < 0) return false
      const block = content.storyBlocks[blockIndex]
      const stages = Array.isArray(block.stages) ? block.stages : []
      const stage = newEditableNode(STAGE_FIELDS, 'sceneTasks')
      stage.order = nextOrder(stages)
      block.stages = [...stages, stage]
      return true
    })
  }

  function updateStage(blockKey, stageKey, patch) {
    return editStoryContent(content => {
      const blockIndex = activeIndex(content.storyBlocks, blockKey)
      if (blockIndex < 0) return false
      const stages = content.storyBlocks[blockIndex].stages
      const stageIndex = activeIndex(stages, stageKey)
      if (stageIndex < 0) return false
      patchNode(stages[stageIndex], patch, STAGE_FIELDS)
      return true
    })
  }

  function removeStage(blockKey, stageKey) {
    let undo = null
    const changed = editStoryContent(content => {
      const blockIndex = activeIndex(content.storyBlocks, blockKey)
      if (blockIndex < 0) return false
      const stages = content.storyBlocks[blockIndex].stages
      const stageIndex = activeIndex(stages, stageKey)
      if (stageIndex < 0) return false
      const stage = stages[stageIndex]
      if (stage.id) {
        stages[stageIndex] = {
          ...stage,
          lifecycle: 'retired',
          sceneTasks: retireHistoricalSceneTasks(stage.sceneTasks),
        }
      } else {
        undo = {
          kind: 'stage',
          blockKey: String(blockKey),
          index: stageIndex,
          node: clone(stage),
        }
        stages.splice(stageIndex, 1)
      }
      return true
    })
    if (changed && undo) storyBlockUndo.value = undo
    return changed
  }

  function moveStage(blockKey, stageKey, direction) {
    return editStoryContent(content => {
      const blockIndex = activeIndex(content.storyBlocks, blockKey)
      if (blockIndex < 0) return false
      return moveActiveSibling(
        content.storyBlocks[blockIndex].stages,
        stageKey,
        direction,
      )
    })
  }

  function addSceneTask(blockKey, stageKey) {
    return editStoryContent(content => {
      const blockIndex = activeIndex(content.storyBlocks, blockKey)
      if (blockIndex < 0) return false
      const stages = content.storyBlocks[blockIndex].stages
      const stageIndex = activeIndex(stages, stageKey)
      if (stageIndex < 0) return false
      const stage = stages[stageIndex]
      const sceneTasks = Array.isArray(stage.sceneTasks) ? stage.sceneTasks : []
      const sceneTask = newEditableNode(SCENE_TASK_FIELDS)
      sceneTask.order = nextOrder(sceneTasks)
      stage.sceneTasks = [...sceneTasks, sceneTask]
      return true
    })
  }

  function updateSceneTask(blockKey, stageKey, taskKey, patch) {
    return editStoryContent(content => {
      const blockIndex = activeIndex(content.storyBlocks, blockKey)
      if (blockIndex < 0) return false
      const stages = content.storyBlocks[blockIndex].stages
      const stageIndex = activeIndex(stages, stageKey)
      if (stageIndex < 0) return false
      const sceneTasks = stages[stageIndex].sceneTasks
      const taskIndex = activeIndex(sceneTasks, taskKey)
      if (taskIndex < 0) return false
      patchNode(sceneTasks[taskIndex], patch, SCENE_TASK_FIELDS)
      return true
    })
  }

  function removeSceneTask(blockKey, stageKey, taskKey) {
    let undo = null
    const changed = editStoryContent(content => {
      const blockIndex = activeIndex(content.storyBlocks, blockKey)
      if (blockIndex < 0) return false
      const stages = content.storyBlocks[blockIndex].stages
      const stageIndex = activeIndex(stages, stageKey)
      if (stageIndex < 0) return false
      const sceneTasks = stages[stageIndex].sceneTasks
      const taskIndex = activeIndex(sceneTasks, taskKey)
      if (taskIndex < 0) return false
      const sceneTask = sceneTasks[taskIndex]
      if (sceneTask.id) {
        sceneTasks[taskIndex] = { ...sceneTask, lifecycle: 'retired' }
      } else {
        undo = {
          kind: 'task',
          blockKey: String(blockKey),
          stageKey: String(stageKey),
          index: taskIndex,
          node: clone(sceneTask),
        }
        sceneTasks.splice(taskIndex, 1)
      }
      return true
    })
    if (changed && undo) storyBlockUndo.value = undo
    return changed
  }

  function moveSceneTask(blockKey, stageKey, taskKey, direction) {
    return editStoryContent(content => {
      const blockIndex = activeIndex(content.storyBlocks, blockKey)
      if (blockIndex < 0) return false
      const stages = content.storyBlocks[blockIndex].stages
      const stageIndex = activeIndex(stages, stageKey)
      if (stageIndex < 0) return false
      return moveActiveSibling(
        stages[stageIndex].sceneTasks,
        taskKey,
        direction,
      )
    })
  }

  function restorePhysicalNode(items, index, node) {
    const restored = clone(node)
    if (items.some(item => Number(item.order) === Number(restored.order))) {
      restored.order = nextOrder(items)
    }
    items.splice(Math.min(index, items.length), 0, restored)
  }

  function undoStoryBlockEdit() {
    if (!storyBlockUndo.value) return false
    const undo = storyBlockUndo.value
    if (!storyBlockUndoRecoverable(undo, store.localContent)) {
      storyBlockUndo.value = null
      return false
    }
    const changed = editStoryContent(content => {
      if (undo.kind === 'block') {
        if (content.storyBlocks.some(block => identity(block) === identity(undo.node))) {
          return false
        }
        restorePhysicalNode(content.storyBlocks, undo.index, undo.node)
      } else {
        const blockIndex = activeIndex(content.storyBlocks, undo.blockKey)
        if (blockIndex < 0) return false
        const stages = content.storyBlocks[blockIndex].stages
        if (undo.kind === 'stage') {
          if (stages.some(stage => identity(stage) === identity(undo.node))) return false
          restorePhysicalNode(stages, undo.index, undo.node)
        } else {
          const stageIndex = activeIndex(stages, undo.stageKey)
          if (stageIndex < 0) return false
          const sceneTasks = stages[stageIndex].sceneTasks
          if (sceneTasks.some(task => identity(task) === identity(undo.node))) return false
          restorePhysicalNode(sceneTasks, undo.index, undo.node)
        }
      }
      if (
        'restoreActiveStoryBlockRef' in undo
        && content.activeStoryBlockRef == null
      ) {
        content.activeStoryBlockRef = undo.restoreActiveStoryBlockRef
      }
      return true
    })
    if (changed) storyBlockUndo.value = null
    return changed
  }

  function enterProject(nextProjectId) {
    const normalized = String(nextProjectId || '')
    if (normalized === activeProject.value) return false
    activeProject.value = normalized
    authorInstructions.value = ''
    notice.value = ''
    historyOpen.value = false
    storyBlockUndo.value = null
    projectScope.value += 1
    return true
  }

  function checkpointStoryBlockUndo() {
    storyBlockUndo.value = null
  }

  function projectTicket(targetProjectId = String(projectId() || '')) {
    return {
      scope: projectScope.value,
      targetProjectId,
      activeProject: activeProject.value,
    }
  }

  function projectTicketIsCurrent(ticket) {
    return (
      projectScope.value === ticket.scope
      && String(projectId() || '') === ticket.targetProjectId
      && activeProject.value === ticket.activeProject
    )
  }

  async function hydrate() {
    const targetProjectId = String(projectId() || '')
    if (!targetProjectId) return undefined
    enterProject(targetProjectId)
    const ticket = projectTicket(targetProjectId)
    const result = await store.ensureLoaded(targetProjectId)
    if (projectTicketIsCurrent(ticket)) checkpointStoryBlockUndo()
    return result
  }

  async function createManualDraft() {
    if (!canCreateDraft.value) return undefined
    const targetProjectId = String(projectId())
    const ticket = projectTicket(targetProjectId)
    const result = await store.createDraft(targetProjectId, {
      idempotencyKey: String(keyFactory()),
    })
    if (projectTicketIsCurrent(ticket)) {
      checkpointStoryBlockUndo()
      if (store.localContent == null) store.editLocal(emptyPlanningContent())
      notice.value = '已建立空白规划工作稿'
    }
    return result
  }

  async function save() {
    if (!canSave.value) return undefined
    const ticket = projectTicket()
    const result = await store.saveDraft({
      idempotencyKey: String(keyFactory()),
    })
    if (projectTicketIsCurrent(ticket)) {
      checkpointStoryBlockUndo()
      notice.value = '规划工作稿已保存'
    }
    return result
  }

  async function generate(instructions = authorInstructions.value) {
    if (!canGenerate.value) return undefined
    const ticket = projectTicket()
    const result = await store.generateDraft({
      idempotencyKey: String(keyFactory()),
      authorInstructions: String(instructions || ''),
    })
    if (result?.status === 'succeeded' && projectTicketIsCurrent(ticket)) {
      checkpointStoryBlockUndo()
      notice.value = 'AI 规划已写入当前工作稿'
    }
    return result
  }

  async function reconcile() {
    const ticket = projectTicket()
    const result = await store.reconcileGeneration()
    if (result?.status === 'succeeded' && projectTicketIsCurrent(ticket)) {
      checkpointStoryBlockUndo()
      notice.value = '已恢复并核对生成结果'
    }
    return result
  }

  async function confirm() {
    if (!canConfirm.value) return undefined
    const ticket = projectTicket()
    const operationId = operationStore?.start?.({
      label: '正在确认故事规划',
      detail: '确认会创建不可变规划修订',
      blocking: true,
    })
    try {
      const result = await store.confirmDraft({
        idempotencyKey: String(keyFactory()),
      })
      if (projectTicketIsCurrent(ticket)) {
        checkpointStoryBlockUndo()
        notice.value = '已确认新的故事规划修订'
      }
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
    canUndoStoryBlockEdit,
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
    addStoryBlock,
    updateStoryBlock,
    removeStoryBlock,
    moveStoryBlock,
    selectActiveStoryBlock,
    addStage,
    updateStage,
    removeStage,
    moveStage,
    addSceneTask,
    updateSceneTask,
    removeSceneTask,
    moveSceneTask,
    undoStoryBlockEdit,
    restoreNode: () => false,
    save,
    generate,
    reconcile,
    confirm,
    requestRouteLeave,
    beforeUnload,
  }
}
