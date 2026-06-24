import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import { normalizeBiblePayload } from '@/prompts/bibleFromSeed'
import {
  SETTING_INITIALIZATION_GROUPS,
  buildCompactBibleContext,
  buildSettingsFromBibleSegmentPrompt,
  buildSettingsFromBibleRepairPrompt,
  buildSettingsFromBibleSystemPrompt,
  buildFallbackSettingsFromBibleEvents,
  buildSettingInitializationDedupKey,
  dedupeSettingInitializationEvents,
  filterEventsForInitializationGroup,
  extractSettingsFromBibleText
} from '@/prompts/settingsFromBible'
import { useProviderStore } from './providerStore'
import { useProjectStore } from './projectStore'
import { useSeedStore } from './seedStore'
import { findDuplicateSettingChangeEvent } from '@/utils/settingChangeDedup'

export const ENTITY_TYPES = [
  { value: 'character', label: '人物' },
  { value: 'faction', label: '势力' },
  { value: 'location', label: '地点' },
  { value: 'power_system', label: '体系' },
  { value: 'technique', label: '功法' },
  { value: 'item', label: '物品' }
]

const BIBLE_INITIALIZATION_MARK = '创作圣经初始化'
const BIBLE_INITIALIZATION_PROGRESS_PREFIX = 'setting-bible-initialization'

export const useSettingStore = defineStore('setting', () => {
  const entities = ref([])
  const relations = ref([])
  const changeEvents = ref([])
  const loading = ref(false)
  const initializingFromBible = ref(false)
  const bibleInitializationProgress = ref(null)
  const bibleInitializationDiagnostics = ref([])

  const currentGroupLabel = computed(() => bibleInitializationProgress.value?.currentGroupLabel || '')
  const failedGroups = computed(() => Object.values(bibleInitializationProgress.value?.groups || {})
    .filter(group => group.status === 'failed'))

  const entitiesByType = computed(() => {
    const groups = {}
    for (const type of ENTITY_TYPES) groups[type.value] = []
    for (const entity of entities.value) {
      const key = entity.entityType || 'character'
      if (!groups[key]) groups[key] = []
      groups[key].push(entity)
    }
    return groups
  })

  const pendingChangeEvents = computed(() =>
    changeEvents.value.filter(e => e.status === 'pending_review')
  )

  const hasBibleInitialization = computed(() =>
    changeEvents.value.some(isBibleInitializationEvent)
  )

  async function loadEntities(projectId, filters = {}) {
    loading.value = true
    try {
      entities.value = await api.settings.entities.list(projectId, filters)
      return entities.value
    } catch (e) {
      console.error('加载设定库失败', e.message)
      throw e
    } finally {
      loading.value = false
    }
  }

  async function saveEntity(projectId, data) {
    const payload = normalizeEntityPayload(data)
    const result = data.id
      ? await api.settings.entities.update(projectId, data.id, payload)
      : await api.settings.entities.create(projectId, payload)

    const idx = entities.value.findIndex(e => e.id === result.id)
    if (idx === -1) entities.value.unshift(result)
    else entities.value[idx] = result
    return result
  }

  async function deleteEntity(projectId, entityId) {
    await api.settings.entities.delete(projectId, entityId)
    entities.value = entities.value.filter(e => e.id !== entityId)
    relations.value = relations.value.filter(r =>
      r.sourceEntityId !== entityId && r.targetEntityId !== entityId
    )
    await refreshProject(projectId)
  }

  async function clearSettings(projectId) {
    await api.settings.clear(projectId)
    entities.value = []
    relations.value = []
    changeEvents.value = []
    await refreshProject(projectId)
  }

  async function loadRelations(projectId, entityId = '') {
    relations.value = await api.settings.relations.list(projectId, entityId)
    return relations.value
  }

  async function saveRelation(projectId, data) {
    const result = data.id
      ? await api.settings.relations.update(projectId, data.id, data)
      : await api.settings.relations.create(projectId, data)

    const idx = relations.value.findIndex(r => r.id === result.id)
    if (idx === -1) relations.value.unshift(result)
    else relations.value[idx] = result
    return result
  }

  async function deleteRelation(projectId, relationId) {
    await api.settings.relations.delete(projectId, relationId)
    relations.value = relations.value.filter(r => r.id !== relationId)
  }

  async function loadChangeEvents(projectId, filters = {}) {
    changeEvents.value = await api.settings.changeEvents.list(projectId, filters)
    return changeEvents.value
  }

  async function saveChangeEvent(projectId, data) {
    const duplicate = findDuplicateSettingChangeEvent(changeEvents.value, data)
    if (!data.id && duplicate) return duplicate

    const result = data.id
      ? await api.settings.changeEvents.update(projectId, data.id, data)
      : await api.settings.changeEvents.create(projectId, data)

    const idx = changeEvents.value.findIndex(e => e.id === result.id)
    if (idx === -1) changeEvents.value.unshift(result)
    else changeEvents.value[idx] = result
    return result
  }

  async function acceptChangeEvent(projectId, eventId, options = undefined) {
    const result = await api.settings.changeEvents.accept(projectId, eventId, options)
    if (result?.event) {
      upsert(changeEvents.value, result.event)
    }
    if (result?.entity) {
      upsert(entities.value, result.entity)
    }
    if (result?.relation) {
      upsert(relations.value, result.relation)
    }
    return result
  }

  async function rejectChangeEvent(projectId, eventId) {
    const result = await api.settings.changeEvents.reject(projectId, eventId)
    if (result?.event) {
      upsert(changeEvents.value, result.event)
    }
    return result
  }

  async function deleteChangeEvent(projectId, eventId) {
    await api.settings.changeEvents.delete(projectId, eventId)
    changeEvents.value = changeEvents.value.filter(e => e.id !== eventId)
  }

  async function initializeFromBible(projectId, bible) {
    const normalizedBible = normalizeBiblePayload(bible)
    if (!normalizedBible?.premise && !normalizedBible?.worldRules && !normalizedBible?.themeBible) {
      throw new Error('请先生成或填写创作圣经')
    }

    initializingFromBible.value = true
    try {
      const context = await prepareBibleInitialization(projectId, normalizedBible)
      const progress = createBibleInitializationProgress(projectId)
      bibleInitializationProgress.value = progress
      saveBibleInitializationProgress(projectId, progress)
      return await runBibleInitializationGroups({
        projectId,
        bible: normalizedBible,
        groups: SETTING_INITIALIZATION_GROUPS,
        provider: context.provider,
        selectedSeed: context.selectedSeed,
        continueOnError: true
      })
    } finally {
      initializingFromBible.value = false
    }
  }

  async function retryFailedBibleInitializationGroups(projectId, bible) {
    const normalizedBible = normalizeBiblePayload(bible)
    const savedProgress = loadBibleInitializationProgress(projectId)
    const groups = SETTING_INITIALIZATION_GROUPS.filter(group =>
      savedProgress?.groups?.[group.key]?.status === 'failed'
    )
    if (!groups.length) return []

    initializingFromBible.value = true
    try {
      const context = await prepareBibleInitialization(projectId, normalizedBible, { allowExisting: true })
      bibleInitializationProgress.value = {
        ...createBibleInitializationProgress(projectId, savedProgress),
        status: 'running',
        failedGroups: []
      }
      saveBibleInitializationProgress(projectId, bibleInitializationProgress.value)
      return await runBibleInitializationGroups({
        projectId,
        bible: normalizedBible,
        groups,
        provider: context.provider,
        selectedSeed: context.selectedSeed,
        continueOnError: true
      })
    } finally {
      initializingFromBible.value = false
    }
  }

  async function prepareBibleInitialization(projectId, normalizedBible, options = {}) {
    const providerStore = useProviderStore()
    const provider = await providerStore.resolveTaskProvider({
      projectId,
      bindingKeys: ['extractionModelId', 'brainstormModelId', 'writingModelId'],
      taskName: 'setting_initialization'
    })

    await loadChangeEvents(projectId)
    if (!options.allowExisting && hasBibleInitialization.value) {
      throw new Error('已完成创作圣经到设定库的初始化。为避免覆盖已写作设定，后续请通过章节定稿提取或在设定库中手动维护。')
    }
    await loadEntities(projectId)

    const seedStore = useSeedStore()
    try {
      await seedStore.loadSeeds(projectId)
    } catch {
      // Seed context is helpful but not required for initialization.
    }
    const selectedSeed = seedStore.seeds.find(seed => seed.status === 'selected') || null
    return { provider, selectedSeed, normalizedBible }
  }

  async function runBibleInitializationGroups({
    projectId,
    bible,
    groups,
    provider,
    selectedSeed,
    continueOnError = true
  }) {
    const created = []
    const extractedEvents = []
    const savedInitializationKeys = new Set()
    const existingPendingKeys = buildExistingPendingKeys(changeEvents.value)
    let firstError = null
    let lastText = ''

    for (const group of groups) {
      try {
        const result = await runBibleInitializationGroup({
          projectId,
          bible,
          group,
          provider,
          selectedSeed,
          extractedEvents,
          existingPendingKeys,
          savedInitializationKeys
        })
        lastText = result.lastText || lastText
        created.push(...result.created)
        extractedEvents.push(...result.events)
      } catch (error) {
        console.warn(`初始化提取${group.label}失败`, error)
        firstError ||= error
        markBibleInitializationGroup(projectId, group, {
          status: 'failed',
          error: error.message || String(error),
          diagnostics: error.settingInitializationDiagnostics || null
        })
        if (!continueOnError) throw error
      }
    }

    if (!created.length && !firstError) {
      const fallbackEvents = buildFallbackSettingsFromBibleEvents({
        bible,
        seed: selectedSeed,
        existingSettings: entities.value
      })
      for (const event of fallbackEvents) {
        if (skipDuplicateInitializationEvent(event, existingPendingKeys, savedInitializationKeys)) continue
        const saved = await saveInitializationEvent(projectId, event)
        created.push(saved)
        savedInitializationKeys.add(buildSettingInitializationDedupKey(event))
      }
    }

    const progress = bibleInitializationProgress.value
    if (progress) {
      progress.generatedCandidates = created.length
      progress.completedGroups = Object.values(progress.groups).filter(group => group.status === 'success').length
      progress.failedGroups = Object.values(progress.groups).filter(group => group.status === 'failed').map(group => group.key)
      progress.status = progress.failedGroups.length ? 'partial_failed' : 'completed'
      progress.currentGroupKey = ''
      progress.currentGroupLabel = ''
      progress.endedAt = new Date().toISOString()
      saveBibleInitializationProgress(projectId, progress)
    }

    if (!created.length) {
      if (firstError) throw firstError
      throw new Error(`AI 没有返回可保存的设定候选。返回片段：${snippet(lastText)}`)
    }
    return created
  }

  async function runBibleInitializationGroup({
    projectId,
    bible,
    group,
    provider,
    selectedSeed,
    extractedEvents,
    existingPendingKeys,
    savedInitializationKeys
  }) {
    markBibleInitializationGroup(projectId, group, { status: 'running', error: '' })
    const bibleContext = buildCompactBibleContext({ bible, seed: selectedSeed, group })
    const prompt = buildSettingsFromBibleSegmentPrompt({
      bibleContext,
      seed: selectedSeed,
      existingSettings: entities.value,
      existingEvents: extractedEvents,
      group
    })
    const diagnostics = createGroupDiagnostics({ provider, prompt, group })

    try {
      const result = await chatCompletion(provider, [
        { role: 'system', content: buildSettingsFromBibleSystemPrompt() },
        { role: 'user', content: prompt }
      ], jsonOptions(provider, {
        maxTokens: Math.max(1800, Math.min(2600, (group.maxItems || 8) * 260)),
        temperature: 0.2
      }))

      const text = getCompletionText(result)
      diagnostics.rawHead = snippet(text, 1500)
      diagnostics.rawTail = tailSnippet(text, 800)
      let failureReason = ''
      let groupEvents = []
      if (!String(text || '').trim()) {
        failureReason = `${group.label}提取空响应`
      } else {
        groupEvents = filterEventsForInitializationGroup(extractSettingsFromBibleText(text), group)
      }
      if (!groupEvents.length && text.trim()) {
        diagnostics.repairTriggered = true
        const repairResult = await chatCompletion(provider, [
          { role: 'system', content: '你是 JSON 修复器。只能输出合法 JSON，不要解释。' },
          { role: 'user', content: buildSettingsFromBibleRepairPrompt(text) }
        ], jsonOptions(provider, {
          maxTokens: 2200,
          temperature: 0
        }))
        const repairedText = getCompletionText(repairResult)
        groupEvents = filterEventsForInitializationGroup(extractSettingsFromBibleText(repairedText), group)
        diagnostics.repairSucceeded = groupEvents.length > 0
        diagnostics.rawTail = tailSnippet(repairedText || text, 800)
        if (!groupEvents.length) failureReason = `${group.label}未解析出可保存候选`
      }
      if (!groupEvents.length) {
        const fallbackEvents = buildFallbackEventsForInitializationGroup({
          group,
          bible,
          selectedSeed,
          extractedEvents,
          existingSettings: entities.value
        })
        if (fallbackEvents.length) {
          diagnostics.fallbackTriggered = true
          diagnostics.fallbackReason = `${failureReason || `${group.label}AI 结果不可用`}，已生成待确认占位候选`
          groupEvents = fallbackEvents
        } else {
          throw new Error(`${failureReason || `${group.label}未解析出可保存候选`}，请重试该分组`)
        }
      }

      const events = dedupeSettingInitializationEvents(groupEvents, entities.value)
      const created = []
      for (const event of events) {
        if (skipDuplicateInitializationEvent(event, existingPendingKeys, savedInitializationKeys)) continue
        const saved = await saveInitializationEvent(projectId, event)
        created.push(saved)
        savedInitializationKeys.add(buildSettingInitializationDedupKey(event))
      }

      diagnostics.candidateCount = events.length
      diagnostics.savedCount = created.length
      diagnostics.savedSuccessfully = true
      diagnostics.endedAt = new Date().toISOString()
      bibleInitializationDiagnostics.value.push(diagnostics)
      markBibleInitializationGroup(projectId, group, {
        status: 'success',
        candidateCount: events.length,
        savedCount: created.length,
        savedSuccessfully: true,
        diagnostics
      })
      return { created, events, lastText: text }
    } catch (error) {
      diagnostics.error = error.message || String(error)
      const fallbackEvents = buildFallbackEventsForInitializationGroup({
        group,
        bible,
        selectedSeed,
        extractedEvents,
        existingSettings: entities.value
      })
      if (fallbackEvents.length) {
        diagnostics.fallbackTriggered = true
        diagnostics.fallbackReason = `${group.label}模型调用失败：${diagnostics.error}，已生成待确认占位候选`
        const events = dedupeSettingInitializationEvents(fallbackEvents, entities.value)
        const created = []
        for (const event of events) {
          if (skipDuplicateInitializationEvent(event, existingPendingKeys, savedInitializationKeys)) continue
          const saved = await saveInitializationEvent(projectId, event)
          created.push(saved)
          savedInitializationKeys.add(buildSettingInitializationDedupKey(event))
        }
        diagnostics.candidateCount = events.length
        diagnostics.savedCount = created.length
        diagnostics.savedSuccessfully = true
        diagnostics.endedAt = new Date().toISOString()
        bibleInitializationDiagnostics.value.push(diagnostics)
        markBibleInitializationGroup(projectId, group, {
          status: 'success',
          candidateCount: events.length,
          savedCount: created.length,
          savedSuccessfully: true,
          diagnostics
        })
        return { created, events, lastText: '' }
      }

      diagnostics.endedAt = new Date().toISOString()
      bibleInitializationDiagnostics.value.push(diagnostics)
      error.settingInitializationDiagnostics = diagnostics
      throw error
    }
  }

  async function saveInitializationEvent(projectId, event) {
    const existingEntity = entities.value.find(entity =>
      entity.entityType === event.entityType && entity.name === event.entityName
    )
    const saved = await saveChangeEvent(projectId, {
      ...event,
      entityId: existingEntity?.id || null,
      chapterNum: null,
      evidence: markBibleInitialization(event.evidence),
      status: 'pending_review'
    })
    return saved
  }

  return {
    entities,
    relations,
    changeEvents,
    loading,
    initializingFromBible,
    bibleInitializationProgress,
    bibleInitializationDiagnostics,
    currentGroupLabel,
    failedGroups,
    hasBibleInitialization,
    entitiesByType,
    pendingChangeEvents,
    loadEntities,
    saveEntity,
    deleteEntity,
    clearSettings,
    loadRelations,
    saveRelation,
    deleteRelation,
    loadChangeEvents,
    saveChangeEvent,
    acceptChangeEvent,
    rejectChangeEvent,
    deleteChangeEvent,
    initializeFromBible,
    retryFailedBibleInitializationGroups,
    loadBibleInitializationProgress
  }
})

async function refreshProject(projectId) {
  try {
    const projectStore = useProjectStore()
    if (projectStore.currentProject?.id === projectId) {
      await projectStore.openProject(projectId)
    }
  } catch {
    // Project metadata refresh should not block the primary action.
  }
}

function createBibleInitializationProgress(projectId, previous = null) {
  const previousGroups = previous?.groups || {}
  const groups = {}
  for (const group of SETTING_INITIALIZATION_GROUPS) {
    groups[group.key] = {
      key: group.key,
      label: group.label,
      status: previousGroups[group.key]?.status === 'success' ? 'success' : 'pending',
      candidateCount: previousGroups[group.key]?.candidateCount || 0,
      savedCount: previousGroups[group.key]?.savedCount || 0,
      error: '',
      diagnostics: previousGroups[group.key]?.diagnostics || null
    }
  }
  return {
    projectId,
    status: 'running',
    totalGroups: SETTING_INITIALIZATION_GROUPS.length,
    completedGroups: Object.values(groups).filter(group => group.status === 'success').length,
    generatedCandidates: Object.values(groups).reduce((sum, group) => sum + Number(group.savedCount || 0), 0),
    currentGroupKey: '',
    currentGroupLabel: '',
    failedGroups: [],
    startedAt: previous?.startedAt || new Date().toISOString(),
    endedAt: '',
    groups
  }
}

function markBibleInitializationGroup(projectId, group, patch = {}) {
  const store = useSettingStore()
  const progress = store.bibleInitializationProgress || createBibleInitializationProgress(projectId)
  if (!store.bibleInitializationProgress) store.bibleInitializationProgress = progress
  if (!progress.groups?.[group.key]) return
  progress.currentGroupKey = patch.status === 'running' ? group.key : ''
  progress.currentGroupLabel = patch.status === 'running' ? group.label : ''
  progress.groups[group.key] = {
    ...progress.groups[group.key],
    ...patch,
    key: group.key,
    label: group.label
  }
  progress.completedGroups = Object.values(progress.groups).filter(item => item.status === 'success').length
  progress.generatedCandidates = Object.values(progress.groups).reduce((sum, item) => sum + Number(item.savedCount || 0), 0)
  progress.failedGroups = Object.values(progress.groups).filter(item => item.status === 'failed').map(item => item.key)
  saveBibleInitializationProgress(projectId, progress)
}

function loadBibleInitializationProgress(projectId) {
  try {
    const raw = storageGet(`${BIBLE_INITIALIZATION_PROGRESS_PREFIX}:${projectId}`)
    const progress = raw ? JSON.parse(raw) : null
    try {
      const store = useSettingStore()
      store.bibleInitializationProgress = progress
    } catch {
      // Store may not be active in isolated prompt tests.
    }
    return progress
  } catch {
    return null
  }
}

function saveBibleInitializationProgress(projectId, progress) {
  try {
    storageSet(`${BIBLE_INITIALIZATION_PROGRESS_PREFIX}:${projectId}`, JSON.stringify(progress))
  } catch {
    // Local progress is diagnostic only; persisted change events remain the source of truth.
  }
}

function createGroupDiagnostics({ provider, prompt, group }) {
  return {
    groupKey: group.key,
    groupLabel: group.label,
    providerId: provider?.id || '',
    modelName: provider?.model || provider?.modelName || '',
    supportsJSON: provider?.supportsJSON !== false,
    promptChars: String(prompt || '').length,
    startedAt: new Date().toISOString(),
    endedAt: '',
    repairTriggered: false,
    repairSucceeded: false,
    fallbackTriggered: false,
    fallbackReason: '',
    candidateCount: 0,
    savedCount: 0,
    savedSuccessfully: false,
    error: '',
    rawHead: '',
    rawTail: ''
  }
}

function buildFallbackEventsForInitializationGroup({
  group,
  bible,
  selectedSeed,
  extractedEvents = [],
  existingSettings = []
} = {}) {
  const entityFallback = filterEventsForInitializationGroup(
    buildFallbackSettingsFromBibleEvents({ bible, seed: selectedSeed, existingSettings }),
    group
  )
  if (entityFallback.length) return entityFallback
  if (!group?.relationshipOnly) return []

  const sources = (extractedEvents || []).filter(event =>
    event?.changeType !== 'relationship' && event.entityName && ['character', 'faction'].includes(event.entityType)
  )
  if (sources.length < 2) return []

  const source = sources.find(event => event.entityType === 'character') || sources[0]
  const target = sources.find(event => event.entityName !== source.entityName && event.entityType === 'character')
    || sources.find(event => event.entityName !== source.entityName)
  if (!target) return []

  return [{
    entityType: source.entityType,
    entityName: source.entityName,
    changeType: 'relationship',
    fieldPath: '关系',
    summary: `${source.entityName}与${target.entityName}的长期关系需要人工确认。`,
    category: '待确认长期关系',
    importance: 3,
    newValue: {
      targetEntityName: target.entityName,
      targetEntityType: target.entityType,
      relationType: target.entityType === 'faction' ? '追查/对立' : '亲缘/牵引',
      stance: '待确认',
      summary: '创作圣经初始化占位候选；需人工确认后再进入正式设定库。'
    },
    evidence: selectedSeed?.desire || selectedSeed?.coreConflict || selectedSeed?.logline || '创作圣经初始化占位候选',
    confidence: 0.55,
    status: 'pending_review'
  }]
}

function buildExistingPendingKeys(events = []) {
  return new Set((events || [])
    .filter(event => event.status !== 'rejected')
    .map(event => buildSettingInitializationDedupKey(event))
    .filter(Boolean))
}

function skipDuplicateInitializationEvent(event, existingPendingKeys, savedInitializationKeys) {
  const key = buildSettingInitializationDedupKey(event)
  return existingPendingKeys.has(key) || savedInitializationKeys.has(key)
}

function storageGet(key) {
  if (typeof window === 'undefined' || !window.localStorage) return ''
  return window.localStorage.getItem(key)
}

function storageSet(key, value) {
  if (typeof window === 'undefined' || !window.localStorage) return
  window.localStorage.setItem(key, value)
}

function getCompletionText(result) {
  if (typeof result === 'string') return result
  if (result?.content) return result.content
  if (result?.choices?.[0]?.message?.content) return result.choices[0].message.content
  return ''
}

function jsonOptions(provider, options = {}) {
  return provider?.supportsJSON === false
    ? options
    : { ...options, responseFormat: 'json' }
}

function normalizeEntityPayload(data) {
  return {
    entityType: data.entityType || 'character',
    name: data.name || '',
    category: data.category || '',
    summary: data.summary || '',
    status: data.status || 'active',
    importance: Number(data.importance || 3),
    aliases: splitLines(data.aliases),
    tags: splitLines(data.tags),
    profile: data.profile || {},
    firstChapter: numberOrNull(data.firstChapter),
    lastChapter: numberOrNull(data.lastChapter)
  }
}

export function splitLines(value) {
  if (Array.isArray(value)) return value.filter(Boolean)
  if (!value) return []
  return String(value)
    .split(/[\n,，、]/)
    .map(item => item.trim())
    .filter(Boolean)
}

function numberOrNull(value) {
  if (value === '' || value == null) return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function upsert(list, item) {
  const idx = list.findIndex(row => row.id === item.id)
  if (idx === -1) list.unshift(item)
  else list[idx] = item
}

function isBibleInitializationEvent(event) {
  if (!event || event.status === 'rejected') return false
  return String(event.evidence || '').includes(BIBLE_INITIALIZATION_MARK)
    || String(event.newValue || '').includes(BIBLE_INITIALIZATION_MARK)
}

function markBibleInitialization(evidence) {
  const text = String(evidence || '').trim()
  if (text.includes(BIBLE_INITIALIZATION_MARK)) return text
  return text ? `${BIBLE_INITIALIZATION_MARK}：${text}` : BIBLE_INITIALIZATION_MARK
}

function snippet(text, limit = 240) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  return clean ? clean.slice(0, limit) : '空响应'
}

function tailSnippet(text, limit = 800) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  return clean ? clean.slice(Math.max(0, clean.length - limit)) : ''
}
