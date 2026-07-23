import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api } from '@/api/db/client'
import { useProjectStore } from './projectStore'
import { findDuplicateSettingChangeEvent } from '@/utils/settingChangeDedup'
import { normalizeStateProvenance } from '@/utils/stateProvenance'

export const ENTITY_TYPES = [
  { value: 'character', label: '人物' },
  { value: 'faction', label: '势力' },
  { value: 'location', label: '地点' },
  { value: 'power_system', label: '体系' },
  { value: 'technique', label: '功法' },
  { value: 'item', label: '物品' }
]


export const useSettingStore = defineStore('setting', () => {
  const entities = ref([])
  const relations = ref([])
  const changeEvents = ref([])
  const loading = ref(false)



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
    const payload = preserveProvenancePayload(data)
    const result = data.id
      ? await api.settings.relations.update(projectId, data.id, payload)
      : await api.settings.relations.create(projectId, payload)

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

    const payload = preserveProvenancePayload(data)
    const result = data.id
      ? await api.settings.changeEvents.update(projectId, data.id, payload)
      : await api.settings.changeEvents.create(projectId, payload)

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

  return {
    entities,
    relations,
    changeEvents,
    loading,
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
    deleteChangeEvent
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

function normalizeEntityPayload(data) {
  const provenance = normalizeStateProvenance(data)
  const profile = {
    ...(data.profile || {})
  }
  if (hasProvenance(provenance)) {
    profile.provenance = provenance
  }
  return {
    entityType: data.entityType || 'character',
    name: data.name || '',
    category: data.category || '',
    summary: data.summary || '',
    status: data.status || 'active',
    importance: Number(data.importance || 3),
    aliases: splitLines(data.aliases),
    tags: splitLines(data.tags),
    profile,
    firstChapter: numberOrNull(data.firstChapter),
    lastChapter: numberOrNull(data.lastChapter),
    sourceChapterNum: provenance.sourceChapterNum,
    sourceVersionId: provenance.sourceVersionId,
    runId: provenance.runId,
    finalizationId: provenance.finalizationId,
    commitStatus: provenance.commitStatus,
    provenance
  }
}

function preserveProvenancePayload(data = {}) {
  const provenance = normalizeStateProvenance(data)
  return hasProvenance(provenance)
    ? {
        ...data,
        sourceChapterNum: provenance.sourceChapterNum,
        sourceVersionId: provenance.sourceVersionId,
        runId: provenance.runId,
        finalizationId: provenance.finalizationId,
        commitStatus: provenance.commitStatus,
        provenance
      }
    : data
}

function hasProvenance(provenance = {}) {
  return Boolean(
    provenance.sourceChapterNum ||
    provenance.sourceVersionId ||
    provenance.runId ||
    provenance.finalizationId ||
    (provenance.commitStatus && provenance.commitStatus !== 'unknown')
  )
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
