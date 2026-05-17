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
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NSpace,
  NTag,
  useMessage
} from 'naive-ui'
import { ENTITY_TYPES, useSettingStore } from '@/stores/settingStore'

const props = defineProps({
  projectId: { type: String, required: true }
})

const settingStore = useSettingStore()
const message = useMessage()

const activeType = ref('character')
const selectedEntityId = ref('')
const saving = ref(false)
const relationSaving = ref(false)

const draft = reactive(createBlankDraft())
const relationDraft = reactive(createBlankRelation())

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

function typeLabel(type) {
  return ENTITY_TYPES.find(t => t.value === type)?.label || '设定'
}

function relationName(entityId) {
  return settingStore.entities.find(e => e.id === entityId)?.name || '未知设定'
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
              这些候选由 AI 在定稿后提取。确认后会自动创建或更新设定档案；拒绝则不会进入正式设定库。
            </n-alert>
            <div v-if="settingStore.pendingChangeEvents.length" class="change-list">
              <div v-for="event in settingStore.pendingChangeEvents" :key="event.id" class="change-row">
                <div>
                  <div class="change-title">
                    <n-tag size="tiny">{{ typeLabel(event.entityType) }}</n-tag>
                    <strong>{{ event.entityName || '未命名实体' }}</strong>
                    <span>{{ event.fieldPath || event.changeType }}</span>
                    <span v-if="event.chapterNum">第 {{ event.chapterNum }} 章</span>
                  </div>
                  <p v-if="event.oldValue">原：{{ displayEventValue(event.oldValue) }}</p>
                  <p>新：{{ displayEventValue(event.newValue) }}</p>
                  <p v-if="event.evidence" class="evidence">证据：{{ event.evidence }}</p>
                </div>
                <n-space>
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
  </div>
</template>

<style scoped>
.setting-library {
  color: #1f2937;
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
