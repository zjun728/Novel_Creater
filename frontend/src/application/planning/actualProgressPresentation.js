const MAX_VISIBLE_ROWS = 10

const KIND_LABELS = Object.freeze({
  story_block: '故事块',
  stage: '阶段',
  scene_task: '场景任务',
})

const STATUS_LABELS = Object.freeze({
  started: '已开始',
  advanced: '已推进',
  completed: '已完成',
})

const INVALID_MESSAGE = '正文进度状态需要重新读取。'
const SYNCING_MESSAGE = '正文进度正在同步，稍后重新读取。'
const NO_CANON_MESSAGE = '尚无已定稿正文带来的规划进度。'
const EMPTY_MESSAGE = '定稿事实已同步，当前没有规划项发生变化。'

export function presentActualProgress(input) {
  const root = readRootInput(input)
  if (!root) return makeModel('invalid', INVALID_MESSAGE)
  const { items, status, planningContent } = root
  const envelope = readEnvelope(status)
  if (!envelope) return makeModel('invalid', INVALID_MESSAGE)
  if (!envelope.synchronized) return makeModel('syncing', SYNCING_MESSAGE)
  if (envelope.canonRevision === 0) return makeModel('no-canon', NO_CANON_MESSAGE)

  const itemList = safeArray(items)
  if (itemList.length === 0) return makeModel('empty', EMPTY_MESSAGE)

  const hierarchy = buildHierarchyIndex(planningContent)
  const recognized = []
  let unrecognizedCount = 0
  let sequence = 0

  for (const item of itemList) {
    const record = readRecognizedRecord(item, hierarchy)
    if (!record) {
      unrecognizedCount += 1
      continue
    }
    record.sequence = sequence
    sequence += 1
    recognized.push(record)
  }

  const unique = deduplicateRecords(recognized)
  if (unique.length === 0) {
    return makeModel(
      'unrecognized',
      `定稿进度已同步，暂时无法生成作者摘要。共有 ${unrecognizedCount} 项暂不能展示。`,
      { unrecognizedCount },
    )
  }

  unique.sort((left, right) => right.chapterNumber - left.chapterNumber || left.sequence - right.sequence)
  const chapterCount = new Set(unique.map(record => record.chapterNumber)).size
  const visible = unique.slice(0, MAX_VISIBLE_ROWS)
  const rows = visible.map((record, index) => ({
    key: `progress-row-${index + 1}`,
    chapterLabel: `第 ${record.chapterNumber} 章`,
    kindLabel: KIND_LABELS[record.targetType],
    hierarchyLabel: record.hierarchyLabel,
    statusLabel: STATUS_LABELS[record.status],
  }))

  return makeModel('recognized', `已同步 ${chapterCount} 章定稿带来的规划进度。`, {
    rows,
    omittedRecognizedCount: unique.length - visible.length,
    unrecognizedCount,
  })
}

function readRootInput(input) {
  try {
    if (input === null || typeof input !== 'object' || Array.isArray(input)) return null
    return {
      items: input.items,
      status: input.status,
      planningContent: input.planningContent,
    }
  } catch {
    return null
  }
}

function readEnvelope(status) {
  try {
    if (status === null || typeof status !== 'object' || Array.isArray(status)) return null
    const { synchronized, canonRevision, projectionRevision } = status
    if (typeof synchronized !== 'boolean') return null
    if (!isSafeNonNegativeInteger(canonRevision) || !isSafeNonNegativeInteger(projectionRevision)) return null
    if (synchronized !== (canonRevision === projectionRevision)) return null
    return { synchronized, canonRevision, projectionRevision }
  } catch {
    return null
  }
}

function safeArray(value) {
  try {
    return Array.isArray(value) ? Array.from(value) : []
  } catch {
    return []
  }
}

function readRecognizedRecord(item, hierarchy) {
  try {
    if (item === null || typeof item !== 'object' || Array.isArray(item)) return null
    if (item.entityId !== null || item.subjectKey !== '__global__') return null

    const value = readProgressValue(item.value)
    if (!value) return null
    const { chapterNumber, status, targetId, targetType } = value
    if (item.fieldPath !== `plot.progress.${targetType}.${targetId}`) return null

    const hierarchyLabel = hierarchy[targetType].get(targetId)
    if (hierarchyLabel === undefined) return null
    return { chapterNumber, status, targetId, targetType, hierarchyLabel }
  } catch {
    return null
  }
}

function readProgressValue(value) {
  try {
    if (value === null || typeof value !== 'object' || Array.isArray(value)) return null
    const prototype = Object.getPrototypeOf(value)
    if (prototype !== Object.prototype && prototype !== null) return null
    const keys = Reflect.ownKeys(value)
      .filter(key => Object.prototype.propertyIsEnumerable.call(value, key))
    if (keys.some(key => typeof key !== 'string')) return null
    keys.sort()
    if (keys.length !== 4 || keys.join(',') !== 'chapterNumber,status,targetId,targetType') return null
    const chapterNumber = value.chapterNumber
    const status = value.status
    const targetId = value.targetId
    const targetType = value.targetType
    if (!isSafePositiveInteger(chapterNumber)
      || typeof status !== 'string'
      || !Object.hasOwn(STATUS_LABELS, status)
      || typeof targetId !== 'string'
      || targetId.trim().length === 0
      || typeof targetType !== 'string'
      || !Object.hasOwn(KIND_LABELS, targetType)) return null
    return { chapterNumber, status, targetId, targetType }
  } catch {
    return null
  }
}

function buildHierarchyIndex(planningContent) {
  const index = emptyHierarchyIndex()
  try {
    if (planningContent === null || typeof planningContent !== 'object' || Array.isArray(planningContent)) return index
    const blocks = planningContent.storyBlocks
    if (!Array.isArray(blocks)) return index
    for (const block of blocks) {
      if (block === null || typeof block !== 'object' || Array.isArray(block)) continue
      const blockId = block.id
      const blockLabel = labelFor(block.title)
      if (typeof blockId === 'string' && blockId.trim().length > 0) index.story_block.set(blockId, blockLabel)

      const stages = block.stages
      if (!Array.isArray(stages)) return emptyHierarchyIndex()
      for (const stage of stages) {
        if (stage === null || typeof stage !== 'object' || Array.isArray(stage)) continue
        const stageId = stage.id
        const stageLabel = labelFor(stage.title)
        const stageHierarchy = `${blockLabel} / ${stageLabel}`
        if (typeof stageId === 'string' && stageId.trim().length > 0) index.stage.set(stageId, stageHierarchy)

        const tasks = stage.sceneTasks
        if (!Array.isArray(tasks)) return emptyHierarchyIndex()
        for (const task of tasks) {
          if (task === null || typeof task !== 'object' || Array.isArray(task)) continue
          const taskId = task.id
          if (typeof taskId === 'string' && taskId.trim().length > 0) {
            index.scene_task.set(taskId, `${stageHierarchy} / ${labelFor(task.task)}`)
          }
        }
      }
    }
    return index
  } catch {
    return emptyHierarchyIndex()
  }
}

function emptyHierarchyIndex() {
  return {
    story_block: new Map(),
    stage: new Map(),
    scene_task: new Map(),
  }
}

function labelFor(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : '当前规划项'
}

function deduplicateRecords(records) {
  const chapters = new Map()
  const unique = []
  for (const record of records) {
    let kinds = chapters.get(record.chapterNumber)
    if (!kinds) {
      kinds = new Map()
      chapters.set(record.chapterNumber, kinds)
    }
    let targets = kinds.get(record.targetType)
    if (!targets) {
      targets = new Map()
      kinds.set(record.targetType, targets)
    }
    let statuses = targets.get(record.targetId)
    if (!statuses) {
      statuses = new Set()
      targets.set(record.targetId, statuses)
    }
    if (statuses.has(record.status)) continue
    statuses.add(record.status)
    unique.push(record)
  }
  return unique
}

function makeModel(state, message, values = {}) {
  return freezeDeep({
    state,
    heading: '正文进度',
    message,
    rows: values.rows ?? [],
    omittedRecognizedCount: values.omittedRecognizedCount ?? 0,
    unrecognizedCount: values.unrecognizedCount ?? 0,
  })
}

function freezeDeep(value) {
  if (value === null || typeof value !== 'object' || Object.isFrozen(value)) return value
  for (const child of Object.values(value)) freezeDeep(child)
  return Object.freeze(value)
}

function isSafeNonNegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0
}

function isSafePositiveInteger(value) {
  return Number.isSafeInteger(value) && value > 0
}
