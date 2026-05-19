import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/db/client'
import { chatCompletion } from '@/api/ai'
import { normalizeBiblePayload } from '@/prompts/bibleFromSeed'
import {
  buildSettingsFromBiblePrompt,
  buildSettingsFromBibleRepairPrompt,
  buildSettingsFromBibleSystemPrompt,
  extractSettingsFromBibleText
} from '@/prompts/settingsFromBible'
import { useProviderStore } from './providerStore'
import { useProjectStore } from './projectStore'
import { useSeedStore } from './seedStore'

export const ENTITY_TYPES = [
  { value: 'character', label: '人物' },
  { value: 'faction', label: '势力' },
  { value: 'location', label: '地点' },
  { value: 'power_system', label: '体系' },
  { value: 'technique', label: '功法' },
  { value: 'item', label: '物品' }
]

const BIBLE_INITIALIZATION_MARK = '创作圣经初始化'

export const useSettingStore = defineStore('setting', () => {
  const entities = ref([])
  const relations = ref([])
  const changeEvents = ref([])
  const loading = ref(false)
  const initializingFromBible = ref(false)

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
    const result = data.id
      ? await api.settings.changeEvents.update(projectId, data.id, data)
      : await api.settings.changeEvents.create(projectId, data)

    const idx = changeEvents.value.findIndex(e => e.id === result.id)
    if (idx === -1) changeEvents.value.unshift(result)
    else changeEvents.value[idx] = result
    return result
  }

  async function acceptChangeEvent(projectId, eventId) {
    const result = await api.settings.changeEvents.accept(projectId, eventId)
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
      const providerStore = useProviderStore()
      await providerStore.ensureProvidersLoaded()
      const bindings = await providerStore.getBindings(projectId)
      const modelId = bindings?.extractionModelId || bindings?.brainstormModelId || bindings?.writingModelId
      const provider = modelId
        ? providerStore.providers.find(p => p.id === modelId)
        : providerStore.providers[0]
      if (!provider) throw new Error('请先在设置中配置模型')

      await loadChangeEvents(projectId)
      if (hasBibleInitialization.value) {
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

      const result = await chatCompletion(provider, [
        { role: 'system', content: buildSettingsFromBibleSystemPrompt() },
        {
          role: 'user',
          content: buildSettingsFromBiblePrompt({
            bible: normalizedBible,
            seed: selectedSeed,
            existingSettings: entities.value
          })
        }
      ], jsonOptions(provider, {
        maxTokens: 8192,
        temperature: 0.25
      }))

      const text = getCompletionText(result)
      let events = extractSettingsFromBibleText(text)
      if (!events.length && text.trim()) {
        const repairResult = await chatCompletion(provider, [
          { role: 'system', content: '你是 JSON 修复器。只能输出合法 JSON，不要解释。' },
          { role: 'user', content: buildSettingsFromBibleRepairPrompt(text) }
        ], jsonOptions(provider, {
          maxTokens: 8192,
          temperature: 0
        }))
        events = extractSettingsFromBibleText(getCompletionText(repairResult))
      }
      if (!events.length) {
        throw new Error(`AI 没有返回可保存的设定候选。返回片段：${snippet(text)}`)
      }

      const created = []
      for (const event of events) {
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
        created.push(saved)
      }
      return created
    } finally {
      initializingFromBible.value = false
    }
  }

  return {
    entities,
    relations,
    changeEvents,
    loading,
    initializingFromBible,
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
    initializeFromBible
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

function snippet(text) {
  const clean = String(text || '').replace(/\s+/g, ' ').trim()
  return clean ? clean.slice(0, 240) : '空响应'
}
