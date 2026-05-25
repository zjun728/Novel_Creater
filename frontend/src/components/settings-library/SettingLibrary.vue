<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NCollapse,
  NCollapseItem,
  NDivider,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NTag,
  useDialog
} from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useResetConfirmation } from '@/composables/useResetConfirmation'
import { ENTITY_TYPES, useSettingStore } from '@/stores/settingStore'

const props = defineProps({
  projectId: { type: String, required: true },
  deleteLocked: { type: Boolean, default: false }
})

const settingStore = useSettingStore()
const message = useAppMessage()
const dialog = useDialog()
const { confirmStageReset } = useResetConfirmation()

const activeType = ref('character')
const selectedEntityId = ref('')
const saving = ref(false)
const relationSaving = ref(false)
const clearingSettings = ref(false)
const showChangeEditModal = ref(false)
const changeSaving = ref(false)
const batchAcceptingChanges = ref(false)
const batchRejectingChanges = ref(false)

const draft = reactive(createBlankDraft())
const relationDraft = reactive(createBlankRelation())
const changeDraft = reactive(createBlankChangeDraft())

const typeOptions = ENTITY_TYPES.map(t => ({ label: t.label, value: t.value }))

const statusOptions = [
  { label: '活跃', value: 'active' },
  { label: '隐藏', value: 'hidden' },
  { label: '死亡/失效', value: 'inactive' },
  { label: '存档', value: 'archived' }
]

const importanceOptions = [
  { label: '核心', value: 5 },
  { label: '重要', value: 4 },
  { label: '常规', value: 3 },
  { label: '背景', value: 2 },
  { label: '备忘', value: 1 }
]

const currentTypeLabel = computed(() =>
  ENTITY_TYPES.find(t => t.value === activeType.value)?.label || '设定'
)

const filteredEntities = computed(() =>
  settingStore.entities.filter(e => (e.entityType || 'character') === activeType.value)
)

const selectedEntity = computed(() =>
  settingStore.entities.find(e => e.id === selectedEntityId.value)
)

const entityOptions = computed(() =>
  settingStore.entities.map(entity => ({
    label: `${entity.name || '未命名'} · ${typeLabel(entity.entityType)}`,
    value: entity.id
  }))
)

const relatedRelations = computed(() => {
  if (!selectedEntityId.value) return settingStore.relations
  return settingStore.relations.filter(r =>
    r.sourceEntityId === selectedEntityId.value || r.targetEntityId === selectedEntityId.value
  )
})

const acceptedEventsForSelectedEntity = computed(() => {
  if (!selectedEntity.value) return []
  return settingStore.changeEvents
    .filter(event => event.status === 'accepted' && isEventRelatedToSelectedEntity(event))
    .slice(0, 12)
})

const activeProfileFields = computed(() => PROFILE_FIELDS[draft.entityType] || PROFILE_FIELDS.character)

const entityStats = computed(() => {
  const stats = {}
  for (const type of ENTITY_TYPES) {
    stats[type.value] = settingStore.entities.filter(e => e.entityType === type.value).length
  }
  return stats
})

onMounted(async () => {
  await Promise.all([
    settingStore.loadEntities(props.projectId),
    settingStore.loadRelations(props.projectId),
    settingStore.loadChangeEvents(props.projectId)
  ])
  if (filteredEntities.value[0]) {
    selectEntity(filteredEntities.value[0])
  }
})

function selectType(type) {
  activeType.value = type
  const first = settingStore.entities.find(e => e.entityType === type)
  if (first) selectEntity(first)
  else startCreate(type)
}

function selectEntity(entity) {
  selectedEntityId.value = entity.id
  Object.assign(draft, entityToDraft(entity))
  relationDraft.sourceEntityId = entity.id
}

function startCreate(type = activeType.value) {
  selectedEntityId.value = ''
  Object.assign(draft, createBlankDraft(type))
  Object.assign(relationDraft, createBlankRelation())
}

function updateDraftType(type) {
  activeType.value = type
  draft.entityType = type
}

async function saveEntity() {
  if (!draft.name.trim()) {
    message.warning('先填写名称')
    return
  }
  saving.value = true
  try {
    const saved = await settingStore.saveEntity(props.projectId, {
      ...draft,
      id: selectedEntityId.value || undefined,
      profile: { ...draft.profile }
    })
    selectedEntityId.value = saved.id
    Object.assign(draft, entityToDraft(saved))
    message.success('设定已保存')
  } catch (e) {
    message.error('保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}

async function deleteCurrentEntity() {
  if (!selectedEntityId.value) return
  if (props.deleteLocked) {
    warnDeleteLocked('设定实体')
    return
  }
  try {
    await settingStore.deleteEntity(props.projectId, selectedEntityId.value)
    message.success('设定已删除')
    const next = filteredEntities.value[0]
    if (next) selectEntity(next)
    else startCreate(activeType.value)
  } catch (e) {
    message.error('删除失败：' + e.message)
  }
}

function warnDeleteLocked(targetLabel = '设定') {
  dialog.warning({
    title: `不能删除${targetLabel}`,
    content: '当前项目已有章节内容，设定库已经成为后续写作、审稿和纠偏的连续性依据，不能再物理删除人物、地点、势力、体系或关系。需要调整时，请修改设定内容、变更状态为隐藏/失效/存档，或通过待确认设定变更记录修正。',
    positiveText: '知道了'
  })
}

async function handleClearSettings() {
  const count = settingStore.entities.length + settingStore.relations.length + settingStore.changeEvents.length
  if (!count) {
    message.warning('当前设定库为空，不需要清空')
    return
  }

  const { confirmed } = await confirmStageReset({
    projectId: props.projectId,
    title: '清空设定库',
    safeContent: '将清空设定实体、关系和待确认变更。因为还没有章节内容，清空后可以重新从圣经提取设定。',
    riskContent: '清空设定库不会删除已写章节，但会移除人物、势力、地点、功法、关系等长期状态记录。已有章节可能失去一致性约束。',
    finalContent: '最终确认：清空设定库后，所有设定实体、关系和待确认变更都会被删除。已写章节不会删除。',
    positiveText: '确认清空设定库',
    blockWhenChapterContent: true,
    blockedContent: '当前项目已有正文内容，不能清空设定库。设定库会作为后续写作、审稿和纠偏的连续性依据；如需调整，请新增或修改具体设定，并保留变更记录。'
  })
  if (!confirmed) return

  clearingSettings.value = true
  try {
    await settingStore.clearSettings(props.projectId)
    selectedEntityId.value = ''
    startCreate(activeType.value)
    message.success('设定库已清空，可以重新从圣经提取')
  } catch (e) {
    message.error('清空设定库失败：' + e.message)
  } finally {
    clearingSettings.value = false
  }
}

async function saveRelation() {
  if (!relationDraft.sourceEntityId || !relationDraft.targetEntityId) {
    message.warning('请选择关系两端')
    return
  }
  relationSaving.value = true
  try {
    await settingStore.saveRelation(props.projectId, { ...relationDraft })
    Object.assign(relationDraft, createBlankRelation(selectedEntityId.value))
    message.success('关系已保存')
  } catch (e) {
    message.error('关系保存失败：' + e.message)
  } finally {
    relationSaving.value = false
  }
}

async function deleteRelation(relationId) {
  if (props.deleteLocked) {
    warnDeleteLocked('设定关系')
    return
  }
  try {
    await settingStore.deleteRelation(props.projectId, relationId)
    message.success('关系已删除')
  } catch (e) {
    message.error('删除关系失败：' + e.message)
  }
}

async function markChangeEvent(eventId, status) {
  try {
    if (status === 'accepted') {
      const event = settingStore.changeEvents.find(item => item.id === eventId)
      const conflicts = getConflictWarnings(event)
      if (conflicts.length) {
        const confirmed = await confirmConflictAccept(conflicts)
        if (!confirmed) return
      }
      const result = await settingStore.acceptChangeEvent(props.projectId, eventId)
      if (result?.entity) {
        activeType.value = result.entity.entityType || activeType.value
        selectEntity(result.entity)
      }
      message.success('变更已确认并写入设定库')
    } else {
      await settingStore.rejectChangeEvent(props.projectId, eventId)
      message.success('变更已拒绝')
    }
  } catch (e) {
    message.error('处理变更失败：' + e.message)
  }
}

async function acceptAllPendingChanges() {
  const events = [...settingStore.pendingChangeEvents]
  if (!events.length) {
    message.warning('暂无待确认设定变更')
    return
  }
  batchAcceptingChanges.value = true
  let success = 0
  const safeEvents = events.filter(event => !getConflictWarnings(event).length)
  const skipped = events.length - safeEvents.length
  try {
    for (const event of safeEvents) {
      await settingStore.acceptChangeEvent(props.projectId, event.id)
      success += 1
    }
    message.success(skipped
      ? `已确认 ${success} 条低风险设定变更，跳过 ${skipped} 条冲突风险项，请逐条确认`
      : `已确认 ${success} 条设定变更`)
  } catch (e) {
    message.error(`批量确认中断：已确认 ${success} 条，失败原因：${e.message}`)
  } finally {
    batchAcceptingChanges.value = false
  }
}

function confirmConflictAccept(conflicts) {
  return new Promise(resolve => {
    dialog.warning({
      title: '设定冲突风险',
      content: () => conflicts.join('\n'),
      positiveText: '仍然确认',
      negativeText: '先不确认',
      maskClosable: false,
      onPositiveClick: () => resolve(true),
      onNegativeClick: () => resolve(false),
      onClose: () => resolve(false)
    })
  })
}

async function rejectAllPendingChanges() {
  const events = [...settingStore.pendingChangeEvents]
  if (!events.length) {
    message.warning('暂无待确认设定变更')
    return
  }
  batchRejectingChanges.value = true
  let success = 0
  try {
    for (const event of events) {
      await settingStore.rejectChangeEvent(props.projectId, event.id)
      success += 1
    }
    message.success(`已拒绝 ${success} 条设定变更`)
  } catch (e) {
    message.error(`批量拒绝中断：已拒绝 ${success} 条，失败原因：${e.message}`)
  } finally {
    batchRejectingChanges.value = false
  }
}

function editChangeEvent(event) {
  Object.assign(changeDraft, eventToChangeDraft(event))
  showChangeEditModal.value = true
}

async function saveChangeEventEdit() {
  if (!changeDraft.entityName.trim()) {
    message.warning('请填写实体名称')
    return
  }
  changeSaving.value = true
  try {
    await settingStore.saveChangeEvent(props.projectId, {
      ...changeDraft,
      confidence: Number(changeDraft.confidence || 0.8),
      chapterNum: changeDraft.chapterNum ?? null
    })
    showChangeEditModal.value = false
    message.success('待确认变更已更新')
  } catch (e) {
    message.error('保存变更失败：' + e.message)
  } finally {
    changeSaving.value = false
  }
}

function typeLabel(type) {
  return ENTITY_TYPES.find(t => t.value === type)?.label || '设定'
}

function relationName(entityId) {
  return settingStore.entities.find(e => e.id === entityId)?.name || '未知设定'
}

function relationCounterpartName(relation) {
  if (!selectedEntityId.value) return relationName(relation.targetEntityId)
  const counterpartId = relation.sourceEntityId === selectedEntityId.value
    ? relation.targetEntityId
    : relation.sourceEntityId
  return relationName(counterpartId)
}

function relationDirectionLabel(relation) {
  if (!selectedEntityId.value) {
    return `${relationName(relation.sourceEntityId)} → ${relation.relationType || '关系'} → ${relationName(relation.targetEntityId)}`
  }
  const isSource = relation.sourceEntityId === selectedEntityId.value
  const counterpart = relationCounterpartName(relation)
  return isSource
    ? `对 ${counterpart}：${relation.relationType || '关系'}`
    : `来自 ${counterpart}：${relation.relationType || '关系'}`
}

function parseRelationPayload(event) {
  if (event?.changeType !== 'relationship') return null
  const parsed = parseMaybeJson(event.newValue)
  return parsed && typeof parsed === 'object' ? parsed : null
}

function changeEventTitle(event) {
  const payload = parseRelationPayload(event)
  if (payload) {
    return `${event.entityName || '未命名实体'} → ${payload.targetEntityName || payload.targetName || payload.target || '未知对象'}`
  }
  return event.entityName || '未命名实体'
}

function changeEventMeta(event) {
  const payload = parseRelationPayload(event)
  if (payload) {
    return [payload.relationType || event.fieldPath || '关系', payload.stance].filter(Boolean).join(' / ')
  }
  return event.fieldPath || event.changeType
}

function isEventRelatedToSelectedEntity(event) {
  const selected = selectedEntity.value
  if (!selected || !event) return false
  if (event.entityId && event.entityId === selected.id) return true
  if (event.entityName && event.entityName === selected.name && (event.entityType || selected.entityType) === selected.entityType) return true
  const payload = parseRelationPayload(event)
  if (!payload) return false
  const targetName = payload.targetEntityName || payload.targetName || payload.target
  const targetType = payload.targetEntityType || payload.targetType || selected.entityType
  return targetName === selected.name && targetType === selected.entityType
}

function displayEventValue(value) {
  if (!value) return '空'
  try {
    const parsed = JSON.parse(value)
    if (parsed.targetEntityName || parsed.relationType) {
      return `${parsed.relationType || '关系'}：${parsed.targetEntityName || ''}${parsed.summary ? `，${parsed.summary}` : ''}`
    }
    if (parsed.summary || parsed.category || parsed.profile) {
      const profile = parsed.profile || {}
      const profileText = Object.entries(profile)
        .filter(([, v]) => v)
        .map(([k, v]) => `${k}=${v}`)
        .join('；')
      return [parsed.summary, parsed.category, profileText].filter(Boolean).join('；') || value
    }
    return JSON.stringify(parsed)
  } catch {
    return value
  }
}

function getConflictWarnings(event) {
  if (!event) return []
  if (event.changeType === 'relationship') return getRelationConflictWarnings(event)
  return getEntityConflictWarnings(event)
}

function getEntityConflictWarnings(event) {
  const warnings = []
  const entity = findEntityForEvent(event)
  const newValue = parseMaybeJson(event.newValue)

  if (event.changeType === 'new_entity' && entity) {
    warnings.push(`已存在同名${typeLabel(entity.entityType)}「${entity.name}」，确认后会更新已有档案，而不是创建全新实体。`)
  }

  if (!entity) return warnings
  const fieldPath = normalizeEventFieldPath(event.fieldPath, event.changeType)
  const existingValue = readEntityField(entity, fieldPath)
  const incomingValue = stringifyDisplayValue(
    event.changeType === 'new_entity' && newValue?.summary ? newValue.summary : event.newValue
  )

  if (isHardSettingField(fieldPath) && existingValue && incomingValue && existingValue !== incomingValue) {
    warnings.push(`硬设定字段「${fieldLabel(fieldPath)}」将从「${existingValue}」变为「${incomingValue}」。`)
  }

  if (event.changeType === 'new_entity' && newValue?.profile && typeof newValue.profile === 'object') {
    for (const [key, value] of Object.entries(newValue.profile)) {
      const profilePath = `profile.${key}`
      const current = readEntityField(entity, profilePath)
      const next = stringifyDisplayValue(value)
      if (isHardSettingField(profilePath) && current && next && current !== next) {
        warnings.push(`硬设定字段「${fieldLabel(profilePath)}」将从「${current}」变为「${next}」。`)
      }
    }
  }

  return warnings
}

function getRelationConflictWarnings(event) {
  const payload = parseMaybeJson(event.newValue)
  if (!payload || typeof payload !== 'object') return []
  const source = findEntityByName(event.entityType || 'character', event.entityName)
  const target = findEntityByName(payload.targetEntityType || payload.targetType || 'character', payload.targetEntityName || payload.targetName || payload.target)
  if (!source || !target) return []

  const relationType = payload.relationType || event.fieldPath || '关系'
  const existing = settingStore.relations.find(relation =>
    relation.sourceEntityId === source.id &&
    relation.targetEntityId === target.id &&
    relation.relationType === relationType
  )
  if (!existing) return []

  const warnings = [`关系「${source.name} -> ${relationType} -> ${target.name}」已存在，确认后会覆盖该关系记录。`]
  if (existing.stance && payload.stance && existing.stance !== payload.stance) {
    warnings.push(`关系立场将从「${existing.stance}」变为「${payload.stance}」。`)
  }
  if (existing.summary && payload.summary && existing.summary !== payload.summary) {
    warnings.push('关系说明与现有记录不同，建议逐条确认。')
  }
  return warnings
}

function findEntityForEvent(event) {
  return event.entityId
    ? settingStore.entities.find(entity => entity.id === event.entityId)
    : findEntityByName(event.entityType || 'character', event.entityName)
}

function findEntityByName(entityType, name) {
  const normalizedName = String(name || '').trim()
  if (!normalizedName) return null
  return settingStore.entities.find(entity =>
    entity.entityType === entityType &&
    entity.name === normalizedName
  )
}

function normalizeEventFieldPath(fieldPath, changeType) {
  const value = String(fieldPath || '').trim()
  if (value) return value
  return changeType === 'new_entity' ? 'summary' : 'notes'
}

function readEntityField(entity, fieldPath) {
  if (!entity || !fieldPath) return ''
  if (fieldPath.startsWith('profile.')) {
    const key = fieldPath.split('.', 2)[1]
    return stringifyDisplayValue(entity.profile?.[key])
  }
  if (fieldPath === 'summary') return stringifyDisplayValue(entity.summary)
  if (fieldPath === 'category') return stringifyDisplayValue(entity.category)
  if (fieldPath === 'status') return stringifyDisplayValue(entity.status)
  return stringifyDisplayValue(entity.profile?.[fieldPath])
}

function parseMaybeJson(value) {
  if (!value) return null
  if (typeof value === 'object') return value
  try {
    return JSON.parse(value)
  } catch {
    return null
  }
}

function stringifyDisplayValue(value) {
  if (value == null) return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value).trim()
}

function isHardSettingField(fieldPath) {
  return HARD_SETTING_FIELDS.has(fieldPath)
}

function fieldLabel(fieldPath) {
  return FIELD_LABELS[fieldPath] || fieldPath
}

function createBlankDraft(type = 'character') {
  return {
    entityType: type,
    name: '',
    category: '',
    summary: '',
    status: 'active',
    importance: 3,
    aliases: '',
    tags: '',
    firstChapter: null,
    lastChapter: null,
    profile: {}
  }
}

function entityToDraft(entity) {
  return {
    entityType: entity.entityType || 'character',
    name: entity.name || '',
    category: entity.category || '',
    summary: entity.summary || '',
    status: entity.status || 'active',
    importance: Number(entity.importance || 3),
    aliases: (entity.aliases || []).join('\n'),
    tags: (entity.tags || []).join('\n'),
    firstChapter: entity.firstChapter ?? null,
    lastChapter: entity.lastChapter ?? null,
    profile: { ...(entity.profile || {}) }
  }
}

function createBlankRelation(entityId = '') {
  return {
    sourceEntityId: entityId,
    targetEntityId: '',
    relationType: '',
    stance: '',
    summary: '',
    isHidden: false,
    evidence: '',
    chapterNum: null,
    status: 'active'
  }
}

function createBlankChangeDraft() {
  return {
    id: '',
    entityType: 'character',
    entityId: null,
    entityName: '',
    changeType: 'update',
    fieldPath: '',
    oldValue: '',
    newValue: '',
    chapterNum: null,
    evidence: '',
    confidence: 0.8,
    status: 'pending_review'
  }
}

function eventToChangeDraft(event = {}) {
  return {
    id: event.id || '',
    entityType: event.entityType || 'character',
    entityId: event.entityId || null,
    entityName: event.entityName || '',
    changeType: event.changeType || 'update',
    fieldPath: event.fieldPath || '',
    oldValue: event.oldValue || '',
    newValue: event.newValue || '',
    chapterNum: event.chapterNum ?? null,
    evidence: event.evidence || '',
    confidence: Number(event.confidence || 0.8),
    status: event.status || 'pending_review'
  }
}

const HARD_SETTING_FIELDS = new Set([
  'summary',
  'category',
  'status',
  'profile.family',
  'profile.sect',
  'profile.faction',
  'profile.nation',
  'profile.rankTitle',
  'profile.realm',
  'profile.realmLevel',
  'profile.techniques',
  'profile.weapons',
  'profile.location',
  'profile.physicalStatus',
  'profile.currentGoal',
  'profile.leader',
  'profile.territory',
  'profile.resources',
  'profile.controller',
  'profile.realms',
  'profile.breakthroughRules',
  'profile.grade',
  'profile.owner',
  'profile.ability',
  'profile.itemStatus'
])

const FIELD_LABELS = {
  summary: '概要',
  category: '分类',
  status: '状态',
  'profile.family': '家族',
  'profile.sect': '宗门/门派',
  'profile.faction': '阵营',
  'profile.nation': '国家',
  'profile.rankTitle': '身份/职位',
  'profile.realm': '境界',
  'profile.realmLevel': '境界层级',
  'profile.techniques': '功法',
  'profile.weapons': '武器/法宝',
  'profile.location': '当前位置',
  'profile.physicalStatus': '身体状态',
  'profile.currentGoal': '当前目标',
  'profile.leader': '掌权者',
  'profile.territory': '控制范围',
  'profile.resources': '资源',
  'profile.controller': '控制者',
  'profile.realms': '境界顺序',
  'profile.breakthroughRules': '突破规则',
  'profile.grade': '品阶',
  'profile.owner': '持有者',
  'profile.ability': '能力',
  'profile.itemStatus': '物品状态'
}

const PROFILE_FIELDS = {
  character: [
    ['family', '家族'],
    ['sect', '宗门/门派'],
    ['faction', '阵营'],
    ['nation', '国家'],
    ['rankTitle', '职位/辈分'],
    ['realm', '当前境界'],
    ['realmLevel', '境界层级'],
    ['techniques', '功法'],
    ['weapons', '武器/法宝'],
    ['personality', '性格'],
    ['desire', '欲望'],
    ['fear', '恐惧'],
    ['secret', '秘密'],
    ['location', '当前位置'],
    ['physicalStatus', '身体状态'],
    ['mentalState', '心理状态'],
    ['currentGoal', '当前目标'],
    ['relatives', '亲属'],
    ['mentors', '师承'],
    ['friends', '友方'],
    ['enemies', '敌对']
  ],
  faction: [
    ['leader', '掌权者'],
    ['territory', '控制范围'],
    ['hierarchy', '等级结构'],
    ['resources', '资源'],
    ['inheritance', '传承/功法'],
    ['allies', '盟友'],
    ['enemies', '敌对势力'],
    ['rules', '规矩'],
    ['goal', '明面目标'],
    ['hiddenGoal', '隐藏目标']
  ],
  location: [
    ['parentLocation', '上级地点'],
    ['neighbors', '相邻地点'],
    ['geography', '地貌'],
    ['climate', '气候'],
    ['resources', '资源分布'],
    ['controller', '控制势力'],
    ['dangerLevel', '危险等级'],
    ['restrictions', '出入限制'],
    ['history', '历史事件']
  ],
  power_system: [
    ['realms', '境界顺序'],
    ['breakthroughRules', '突破规则'],
    ['techniqueGrades', '功法品阶'],
    ['itemGrades', '物品等级'],
    ['resourceRules', '资源规则'],
    ['forbiddenBreaks', '禁忌/例外'],
    ['limits', '实力边界']
  ],
  technique: [
    ['techniqueType', '类型'],
    ['grade', '品阶'],
    ['origin', '来源'],
    ['owner', '持有者/传承'],
    ['requirements', '修炼要求'],
    ['effects', '效果'],
    ['limitations', '限制/代价']
  ],
  item: [
    ['itemType', '类型'],
    ['grade', '品阶'],
    ['owner', '当前持有者'],
    ['origin', '来源'],
    ['ability', '能力'],
    ['limitation', '限制/代价'],
    ['itemStatus', '当前状态']
  ]
}
</script>

<template>
  <div class="setting-library">
    <div class="library-toolbar">
      <div>
        <h3>设定库</h3>
        <p>维护长篇写作中的人物、势力、地点、体系和关系状态。</p>
      </div>
      <n-button
        size="small"
        type="error"
        secondary
        :loading="clearingSettings"
        :disabled="!settingStore.entities.length && !settingStore.relations.length && !settingStore.changeEvents.length"
        @click="handleClearSettings"
      >
        清空设定库
      </n-button>
    </div>

    <div class="setting-layout">
      <aside class="setting-sidebar">
        <div class="type-list">
          <button
            v-for="type in ENTITY_TYPES"
            :key="type.value"
            class="type-button"
            :class="{ active: activeType === type.value }"
            @click="selectType(type.value)"
          >
            <span>{{ type.label }}</span>
            <span>{{ entityStats[type.value] || 0 }}</span>
          </button>
        </div>

        <n-divider style="margin: 12px 0" />

        <div class="entity-list">
          <button
            v-for="entity in filteredEntities"
            :key="entity.id"
            class="entity-button"
            :class="{ active: selectedEntityId === entity.id }"
            @click="selectEntity(entity)"
          >
            <span class="entity-name">{{ entity.name || '未命名' }}</span>
            <span class="entity-meta">{{ entity.category || typeLabel(entity.entityType) }}</span>
          </button>
        </div>

        <n-empty
          v-if="filteredEntities.length === 0"
          size="small"
          :description="`暂无${currentTypeLabel}`"
          class="empty-state"
        />

        <n-button block type="primary" class="mt-3" @click="startCreate(activeType)">
          新增{{ currentTypeLabel }}
        </n-button>
      </aside>

      <main class="setting-main">
        <div class="main-head">
          <div>
            <h3>{{ selectedEntityId ? draft.name || '未命名设定' : `新增${currentTypeLabel}` }}</h3>
            <p>用于写作上下文和定稿后的设定变更确认</p>
          </div>
          <n-space>
            <n-popconfirm v-if="selectedEntityId" @positive-click="deleteCurrentEntity">
              <template #trigger>
                <n-button>删除</n-button>
              </template>
              删除后相关关系也会移除。
            </n-popconfirm>
            <n-button type="primary" :loading="saving" @click="saveEntity">保存设定</n-button>
          </n-space>
        </div>

        <n-alert v-if="!selectedEntityId && filteredEntities.length === 0" type="info" :bordered="false" class="mb-4">
          从最容易错乱的人物、宗门、地点或修炼体系开始记录即可，不需要开局填完整百科。
        </n-alert>

        <div class="form-grid">
          <label>
            <span>类型</span>
            <n-select v-model:value="draft.entityType" :options="typeOptions" @update:value="updateDraftType" />
          </label>
          <label>
            <span>名称</span>
            <n-input v-model:value="draft.name" placeholder="例如：苏月 / 青玄宗 / 云州 / 筑基境" />
          </label>
          <label>
            <span>分类</span>
            <n-input v-model:value="draft.category" placeholder="主角、宗门、秘境、功法品阶等" />
          </label>
          <label>
            <span>状态</span>
            <n-select v-model:value="draft.status" :options="statusOptions" />
          </label>
          <label>
            <span>重要度</span>
            <n-select v-model:value="draft.importance" :options="importanceOptions" />
          </label>
          <label>
            <span>首次章节</span>
            <n-input-number v-model:value="draft.firstChapter" clearable class="w-full" />
          </label>
          <label>
            <span>最近章节</span>
            <n-input-number v-model:value="draft.lastChapter" clearable class="w-full" />
          </label>
        </div>

        <label class="block mt-4">
          <span class="field-label">概要</span>
          <n-input
            v-model:value="draft.summary"
            type="textarea"
            :autosize="{ minRows: 3, maxRows: 6 }"
            placeholder="一句话写清它在故事中的作用、当前状态和不可违背的规则"
          />
        </label>

        <div class="form-grid mt-4">
          <label>
            <span>别名</span>
            <n-input v-model:value="draft.aliases" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="每行一个" />
          </label>
          <label>
            <span>标签</span>
            <n-input v-model:value="draft.tags" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="每行一个" />
          </label>
        </div>

        <n-card title="档案字段" size="small" class="mt-4">
          <div class="profile-grid">
            <label v-for="[key, label] in activeProfileFields" :key="key">
              <span>{{ label }}</span>
              <n-input
                v-model:value="draft.profile[key]"
                type="textarea"
                :autosize="{ minRows: 1, maxRows: 4 }"
              />
            </label>
          </div>
        </n-card>

        <n-card v-if="selectedEntityId" title="关联关系摘要" size="small" class="mt-4">
          <div v-if="relatedRelations.length" class="relation-summary-list">
            <div v-for="relation in relatedRelations" :key="relation.id" class="relation-summary-row">
              <div class="relation-summary-title">
                <strong>{{ relationDirectionLabel(relation) }}</strong>
                <n-tag v-if="relation.stance" size="tiny" :bordered="false">{{ relation.stance }}</n-tag>
              </div>
              <p>{{ relation.summary || relation.evidence || '暂无关系说明' }}</p>
            </div>
          </div>
          <n-empty v-else size="small" description="暂无已确认关系" class="py-3" />
        </n-card>

        <n-card v-if="selectedEntityId && acceptedEventsForSelectedEntity.length" title="已确认变更记录" size="small" class="mt-4">
          <div class="accepted-change-list">
            <div v-for="event in acceptedEventsForSelectedEntity" :key="event.id" class="accepted-change-row">
              <div class="change-title">
                <n-tag size="tiny">{{ typeLabel(event.entityType) }}</n-tag>
                <strong>{{ changeEventTitle(event) }}</strong>
                <span>{{ changeEventMeta(event) }}</span>
                <span v-if="event.chapterNum">第 {{ event.chapterNum }} 章</span>
              </div>
              <p>{{ displayEventValue(event.newValue) }}</p>
              <p v-if="event.evidence" class="evidence">证据：{{ event.evidence }}</p>
            </div>
          </div>
        </n-card>

        <n-collapse class="mt-4">
          <n-collapse-item title="关系管理" name="relations">
            <div class="relation-form">
              <n-select v-model:value="relationDraft.sourceEntityId" :options="entityOptions" placeholder="主体" filterable />
              <n-select v-model:value="relationDraft.targetEntityId" :options="entityOptions" placeholder="客体" filterable />
              <n-input v-model:value="relationDraft.relationType" placeholder="关系类型：亲属 / 师承 / 敌对 / 盟友" />
              <n-input v-model:value="relationDraft.stance" placeholder="立场：亲近 / 中立 / 敌对 / 利用" />
              <n-input v-model:value="relationDraft.summary" placeholder="关系说明" />
              <n-button type="primary" :loading="relationSaving" @click="saveRelation">保存关系</n-button>
            </div>

            <div v-if="relatedRelations.length" class="relation-list">
              <div v-for="relation in relatedRelations" :key="relation.id" class="relation-row">
                <div>
                  <strong>{{ relationName(relation.sourceEntityId) }}</strong>
                  <span> → {{ relation.relationType || '关系' }} → </span>
                  <strong>{{ relationName(relation.targetEntityId) }}</strong>
                  <n-tag v-if="relation.stance" size="tiny" class="ml-2">{{ relation.stance }}</n-tag>
                  <p>{{ relation.summary }}</p>
                </div>
                <n-popconfirm @positive-click="deleteRelation(relation.id)">
                  <template #trigger>
                    <n-button size="small">删除</n-button>
                  </template>
                  删除这条关系？
                </n-popconfirm>
              </div>
            </div>
            <n-empty v-else size="small" description="暂无关系" class="py-3" />
          </n-collapse-item>

          <n-collapse-item :title="`待确认设定变更（${settingStore.pendingChangeEvents.length}）`" name="changes">
            <n-alert type="info" :bordered="false" class="mb-3">
              这些候选由 AI 从创作圣经初始化或在章节定稿后提取。确认后会自动创建或更新设定档案；拒绝则不会进入正式设定库。
            </n-alert>
            <div v-if="settingStore.pendingChangeEvents.length" class="change-actions">
              <n-button
                size="small"
                type="primary"
                secondary
                :loading="batchAcceptingChanges"
                @click="acceptAllPendingChanges"
              >
                批量确认
              </n-button>
              <n-button
                size="small"
                secondary
                :loading="batchRejectingChanges"
                @click="rejectAllPendingChanges"
              >
                批量拒绝
              </n-button>
            </div>
            <div v-if="settingStore.pendingChangeEvents.length" class="change-list">
              <div v-for="event in settingStore.pendingChangeEvents" :key="event.id" class="change-row">
                <div>
                  <div class="change-title">
                    <n-tag size="tiny">{{ typeLabel(event.entityType) }}</n-tag>
                    <n-tag v-if="getConflictWarnings(event).length" size="tiny" type="error" :bordered="false">
                      冲突风险
                    </n-tag>
                    <strong>{{ changeEventTitle(event) }}</strong>
                    <span>{{ changeEventMeta(event) }}</span>
                    <span v-if="event.chapterNum">第 {{ event.chapterNum }} 章</span>
                  </div>
                  <p v-if="event.oldValue">原：{{ displayEventValue(event.oldValue) }}</p>
                  <p>新：{{ displayEventValue(event.newValue) }}</p>
                  <p v-if="event.evidence" class="evidence">证据：{{ event.evidence }}</p>
                  <div v-if="getConflictWarnings(event).length" class="conflict-box">
                    <strong>确认前请检查：</strong>
                    <ul>
                      <li v-for="warning in getConflictWarnings(event)" :key="warning">{{ warning }}</li>
                    </ul>
                  </div>
                </div>
                <n-space>
                  <n-button size="small" @click="editChangeEvent(event)">编辑</n-button>
                  <n-button size="small" type="primary" @click="markChangeEvent(event.id, 'accepted')">确认</n-button>
                  <n-button size="small" @click="markChangeEvent(event.id, 'rejected')">拒绝</n-button>
                </n-space>
              </div>
            </div>
            <n-empty v-else size="small" description="暂无待确认变更" class="py-3" />
          </n-collapse-item>
        </n-collapse>
      </main>
    </div>

    <n-modal
      v-model:show="showChangeEditModal"
      preset="card"
      title="编辑待确认设定变更"
      style="width: min(760px, calc(100vw - 48px));"
    >
      <n-form :model="changeDraft" label-placement="left" label-width="100">
        <div class="form-grid">
          <n-form-item label="实体类型">
            <n-select v-model:value="changeDraft.entityType" :options="typeOptions" />
          </n-form-item>
          <n-form-item label="关联实体">
            <n-select
              v-model:value="changeDraft.entityId"
              :options="entityOptions"
              placeholder="可选：绑定已有实体"
              clearable
              filterable
            />
          </n-form-item>
        </div>
        <n-form-item label="实体名称">
          <n-input v-model:value="changeDraft.entityName" placeholder="例如：苏月 / 青玄宗 / 筑基境" />
        </n-form-item>
        <div class="form-grid">
          <n-form-item label="变更类型">
            <n-select
              v-model:value="changeDraft.changeType"
              :options="[
                { label: '新增实体', value: 'new_entity' },
                { label: '字段更新', value: 'update' },
                { label: '关系变更', value: 'relationship' }
              ]"
            />
          </n-form-item>
          <n-form-item label="字段路径">
            <n-input v-model:value="changeDraft.fieldPath" placeholder="如：profile.realm / summary / relationship" />
          </n-form-item>
        </div>
        <div class="form-grid">
          <n-form-item label="章节">
            <n-input-number v-model:value="changeDraft.chapterNum" clearable class="w-full" />
          </n-form-item>
          <n-form-item label="置信度">
            <n-input-number v-model:value="changeDraft.confidence" :min="0" :max="1" :step="0.05" class="w-full" />
          </n-form-item>
        </div>
        <n-form-item label="原值">
          <n-input
            v-model:value="changeDraft.oldValue"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 5 }"
            placeholder="可留空"
          />
        </n-form-item>
        <n-form-item label="新值">
          <n-input
            v-model:value="changeDraft.newValue"
            type="textarea"
            :autosize="{ minRows: 4, maxRows: 10 }"
            placeholder="字段更新可写普通文本；新增实体或关系可保留 JSON"
          />
        </n-form-item>
        <n-form-item label="证据">
          <n-input
            v-model:value="changeDraft.evidence"
            type="textarea"
            :autosize="{ minRows: 2, maxRows: 6 }"
            placeholder="来自圣经、章节原文或人工说明"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showChangeEditModal = false">取消</n-button>
          <n-button type="primary" :loading="changeSaving" @click="saveChangeEventEdit">保存修改</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<style scoped>
.setting-library {
  color: #1f2937;
}

.library-toolbar {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.library-toolbar h3 {
  margin: 0;
  font-size: 18px;
  font-weight: 750;
}

.library-toolbar p {
  margin: 4px 0 0;
  color: #8b95a1;
  font-size: 13px;
}

.setting-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  gap: 20px;
  align-items: start;
}

.setting-sidebar {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  background: #fafafa;
}

.type-list,
.entity-list {
  display: grid;
  gap: 6px;
}

.type-button,
.entity-button {
  width: 100%;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  padding: 9px 10px;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.16s ease, background 0.16s ease;
}

.type-button {
  display: flex;
  justify-content: space-between;
  font-weight: 600;
}

.type-button.active,
.entity-button.active {
  border-color: #16a34a;
  background: #edf8f1;
  color: #166534;
}

.entity-button:hover,
.type-button:hover {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.entity-name,
.entity-meta {
  display: block;
}

.entity-name {
  font-weight: 600;
  color: #374151;
}

.entity-meta {
  margin-top: 2px;
  font-size: 12px;
  color: #8b95a1;
}

.empty-state {
  padding: 24px 0;
}

.setting-main {
  min-width: 0;
}

.main-head {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 16px;
}

.main-head h3 {
  margin: 0;
  font-size: 22px;
  font-weight: 750;
}

.main-head p {
  margin: 4px 0 0;
  color: #8b95a1;
  font-size: 13px;
}

.form-grid,
.profile-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

label span,
.field-label {
  display: block;
  margin-bottom: 6px;
  color: #6b7280;
  font-size: 13px;
  font-weight: 600;
}

.relation-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 12px;
}

.relation-list,
.change-list {
  display: grid;
  gap: 8px;
}

.relation-summary-list,
.accepted-change-list {
  display: grid;
  gap: 10px;
}

.relation-summary-row,
.accepted-change-row {
  border: 1px solid #edf0f2;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fbfdff;
}

.relation-summary-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.relation-summary-row p,
.accepted-change-row p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.change-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-bottom: 10px;
}

.relation-row,
.change-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid #edf0f2;
  border-radius: 8px;
  padding: 10px 12px;
  background: #fff;
}

.relation-row p,
.change-row p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
  white-space: pre-wrap;
}

.change-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.evidence {
  color: #8b95a1;
}

.conflict-box {
  margin-top: 8px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  background: #fef2f2;
  padding: 8px 10px;
  color: #b91c1c;
  font-size: 12px;
  line-height: 1.6;
}

.conflict-box ul {
  margin: 4px 0 0;
  padding-left: 18px;
}

@media (max-width: 980px) {
  .setting-layout {
    grid-template-columns: 1fr;
  }

  .form-grid,
  .profile-grid,
  .relation-form {
    grid-template-columns: 1fr;
  }
}
</style>
