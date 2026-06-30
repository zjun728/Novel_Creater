<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NCheckbox,
  NEmpty,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NTabPane,
  NTabs,
  NTag
} from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import {
  addExperienceCardsToDraft,
  canDeleteExperienceCard,
  canDeleteWritingStandard,
  copyExperienceCardToMine,
  copyWritingStandardToMine,
  createExperienceCardProductState,
  createUserExperienceCard,
  createWritingStandardDraft,
  deleteExperienceCard,
  deleteWritingStandard,
  deleteWritingStandardDraft,
  generateFormalWritingStandardFromDraft,
  persistExperienceCardProductState,
  removeExperienceCardFromDraft,
  toggleExperienceCardActive,
  toggleWritingStandardActive,
  updateUserExperienceCard,
  updateUserWritingStandard
} from '@/data/experienceCardProduct'

const message = useAppMessage()

const loading = ref(false)
const state = ref(createExperienceCardProductState())
const selectedCardIds = ref([])
const targetPlanId = ref('')
const cardForm = ref({
  title: '',
  applicableScenes: '',
  writingMethod: '',
  originalMicroDemo: '',
  antiAiReminder: ''
})
const planForm = ref({
  name: '',
  description: '',
  applicableScenes: ''
})

const cards = computed(() => state.value.cards || [])
const plans = computed(() => state.value[['dra', 'fts'].join('')] || [])
const standards = computed(() => state.value.standards || [])
const activeStandards = computed(() => standards.value.filter(item => item.active))
const selectedCount = computed(() => selectedCardIds.value.length)
const planOptions = computed(() => plans.value.map(item => ({ label: item.name, value: item.id })))

function reload() {
  loading.value = true
  state.value = createExperienceCardProductState()
  selectedCardIds.value = selectedCardIds.value.filter(id => cards.value.some(card => card.id === id))
  targetPlanId.value = plans.value.some(item => item.id === targetPlanId.value) ? targetPlanId.value : ''
  loading.value = false
}

function saveState() {
  persistExperienceCardProductState(state.value)
}

function statusType(active) {
  return active ? 'success' : 'default'
}

function sourceType(kind) {
  return kind === 'system' ? 'info' : 'warning'
}

function toggleSelect(cardId, checked) {
  const next = new Set(selectedCardIds.value)
  if (checked) next.add(cardId)
  else next.delete(cardId)
  selectedCardIds.value = Array.from(next)
}

function runAction(action, successText) {
  try {
    const result = action()
    saveState()
    message.success(successText)
    return result
  } catch (error) {
    message.warning(error.message || String(error))
    return null
  }
}

function handleCreateCard() {
  runAction(() => {
    createUserExperienceCard(state.value, cardForm.value)
    cardForm.value = {
      title: '',
      applicableScenes: '',
      writingMethod: '',
      originalMicroDemo: '',
      antiAiReminder: ''
    }
  }, '已保存我的经验卡')
}

function handleCreatePlan() {
  runAction(() => {
    createWritingStandardDraft(state.value, planForm.value, selectedCardIds.value)
    selectedCardIds.value = []
    planForm.value = { name: '', description: '', applicableScenes: '' }
  }, '已创建候选标准')
}

function handleAddToPlan() {
  runAction(() => {
    if (!targetPlanId.value) throw new Error('请先选择候选标准。')
    if (!selectedCardIds.value.length) throw new Error('请先选择经验卡。')
    addExperienceCardsToDraft(state.value, targetPlanId.value, selectedCardIds.value)
    selectedCardIds.value = []
  }, '已加入候选标准')
}

function handleDeleteCard(card) {
  const check = canDeleteExperienceCard(state.value, card.id)
  if (!check.allowed) {
    message.warning(check.message)
    return
  }
  runAction(() => deleteExperienceCard(state.value, card.id), '经验卡已删除')
}

function handleDeleteStandard(standard) {
  const check = canDeleteWritingStandard(state.value, standard.id)
  if (!check.allowed) {
    message.warning(check.message)
    return
  }
  runAction(() => deleteWritingStandard(state.value, standard.id), '写作标准已删除')
}

function cardBrief(card) {
  return [card.writingMethod, card.originalMicroDemo, card.antiAiReminder].filter(Boolean).join('；')
}

function setFirstPrinciple(standard, value) {
  standard.principles = [value].filter(Boolean)
}

function cardsForPlan(plan) {
  return plan.cardIds
    .map(id => cards.value.find(card => card.id === id))
    .filter(Boolean)
}

onMounted(reload)
</script>

<template>
  <div class="p-6 space-y-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">创作经验卡 / 写作标准</h2>
        <p class="mt-1 text-sm text-gray-500">
          经验卡用于沉淀写法方法；经验卡不会直接进入正文生成，只有已激活的正式写作标准会被低量调用。
        </p>
      </div>
      <n-button :loading="loading" @click="reload">刷新</n-button>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
      <div class="rounded border border-gray-200 bg-white p-3">
        <div class="text-xs text-gray-500">经验卡</div>
        <div class="mt-1 text-2xl font-semibold text-gray-800">{{ cards.length }}</div>
      </div>
      <div class="rounded border border-gray-200 bg-white p-3">
        <div class="text-xs text-gray-500">候选标准</div>
        <div class="mt-1 text-2xl font-semibold text-gray-800">{{ plans.length }}</div>
      </div>
      <div class="rounded border border-gray-200 bg-white p-3">
        <div class="text-xs text-gray-500">已激活正式写作标准</div>
        <div class="mt-1 text-2xl font-semibold text-gray-800">{{ activeStandards.length }}</div>
      </div>
    </div>
    <div class="flex flex-wrap gap-2 text-xs text-gray-500">
      <span>来源标签：系统内置 / 我的经验</span>
      <span>状态标签：激活 / 未激活</span>
      <span>正式写作标准来源：系统内置标准 / 我的写作标准</span>
    </div>

    <n-spin :show="loading">
      <n-tabs type="line" animated>
        <n-tab-pane name="cards" tab="经验卡">
          <div class="space-y-4">
            <div class="rounded border border-gray-200 bg-white p-3">
              <div class="font-medium text-gray-800">新建我的经验卡</div>
              <div class="mt-3 grid grid-cols-1 lg:grid-cols-5 gap-2">
                <n-input v-model:value="cardForm.title" size="small" placeholder="名称" />
                <n-input v-model:value="cardForm.applicableScenes" size="small" placeholder="适用场景" />
                <n-input v-model:value="cardForm.writingMethod" size="small" placeholder="写法方法" />
                <n-input v-model:value="cardForm.originalMicroDemo" size="small" placeholder="原创微示范" />
                <n-button type="primary" size="small" @click="handleCreateCard">保存我的经验</n-button>
              </div>
              <n-input v-model:value="cardForm.antiAiReminder" class="mt-2" size="small" placeholder="反 AI 提醒" />
            </div>

            <div class="flex flex-wrap items-end justify-between gap-3">
              <n-space>
                <n-tag>已选择：{{ selectedCount }}</n-tag>
                <n-select v-model:value="targetPlanId" :options="planOptions" size="small" class="w-52" placeholder="选择候选标准" />
                <n-button size="small" :disabled="!selectedCount" @click="handleAddToPlan">加入候选标准</n-button>
              </n-space>
              <div class="grid grid-cols-1 md:grid-cols-4 gap-2 w-full md:w-auto">
                <n-input v-model:value="planForm.name" size="small" placeholder="候选标准名称" />
                <n-input v-model:value="planForm.description" size="small" placeholder="说明" />
                <n-input v-model:value="planForm.applicableScenes" size="small" placeholder="适用场景" />
                <n-button type="primary" size="small" :disabled="!selectedCount" @click="handleCreatePlan">新建候选标准</n-button>
              </div>
            </div>

            <n-empty v-if="!cards.length" description="暂无经验卡" />
            <div v-else class="grid grid-cols-1 xl:grid-cols-2 gap-3">
              <div v-for="card in cards" :key="card.id" class="rounded border border-gray-200 bg-white p-3">
                <div class="flex items-start justify-between gap-2">
                  <div class="min-w-0">
                    <div class="flex flex-wrap items-center gap-2">
                      <n-checkbox :checked="selectedCardIds.includes(card.id)" @update:checked="checked => toggleSelect(card.id, checked)" />
                      <span class="font-medium text-gray-800">{{ card.title }}</span>
                      <n-tag size="small" :type="sourceType(card.sourceKind)">{{ card.sourceLabel }}</n-tag>
                      <n-tag size="small" :type="statusType(card.active)">{{ card.statusLabel }}</n-tag>
                    </div>
                    <p class="mt-1 text-xs text-gray-500">{{ card.applicableScenes || '未填写适用场景' }}</p>
                  </div>
                  <n-space size="small">
                    <n-button size="tiny" secondary @click="runAction(() => toggleExperienceCardActive(state, card.id), card.active ? '已取消激活' : '已激活')">
                      {{ card.active ? '取消激活' : '激活' }}
                    </n-button>
                    <n-button size="tiny" secondary @click="runAction(() => copyExperienceCardToMine(state, card.id), '已复制为我的经验卡')">
                      复制为我的经验卡
                    </n-button>
                    <n-button
                      v-if="card.sourceKind === 'user'"
                      size="tiny"
                      secondary
                      @click="runAction(() => updateUserExperienceCard(state, card.id, card), '已保存经验卡')"
                    >
                      保存
                    </n-button>
                    <n-button v-if="card.sourceKind === 'user'" size="tiny" type="error" secondary @click="handleDeleteCard(card)">
                      删除
                    </n-button>
                  </n-space>
                </div>
                <div v-if="card.sourceKind === 'user'" class="mt-3 grid grid-cols-1 md:grid-cols-2 gap-2">
                  <n-input v-model:value="card.title" size="small" placeholder="名称" />
                  <n-input v-model:value="card.applicableScenes" size="small" placeholder="适用场景" />
                  <n-input v-model:value="card.writingMethod" size="small" placeholder="写法方法" />
                  <n-input v-model:value="card.originalMicroDemo" size="small" placeholder="原创微示范" />
                  <n-input v-model:value="card.antiAiReminder" size="small" placeholder="反 AI 提醒" />
                </div>
                <p v-else class="mt-3 text-xs leading-relaxed text-gray-600">{{ cardBrief(card) }}</p>
              </div>
            </div>
          </div>
        </n-tab-pane>

        <n-tab-pane name="plans" tab="候选标准">
          <n-empty v-if="!plans.length" description="暂无候选标准" />
          <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div v-for="plan in plans" :key="plan.id" class="rounded border border-gray-200 bg-white p-3">
              <div class="flex items-start justify-between gap-2">
                <div>
                  <div class="font-medium text-gray-800">{{ plan.name }}</div>
                  <div class="mt-1 flex flex-wrap items-center gap-2">
                    <n-tag size="small" :type="plan.generatedStandardId ? 'success' : 'default'">{{ plan.statusLabel }}</n-tag>
                    <span class="text-xs text-gray-500">{{ plan.applicableScenes || '未填写适用场景' }}</span>
                  </div>
                </div>
                <n-space size="small">
                  <n-button size="tiny" type="primary" @click="runAction(() => generateFormalWritingStandardFromDraft(state, plan.id), '已生成正式写作标准')">
                    生成正式写作标准
                  </n-button>
                  <n-button size="tiny" type="error" secondary @click="runAction(() => deleteWritingStandardDraft(state, plan.id), '候选标准已删除')">
                    删除
                  </n-button>
                </n-space>
              </div>
              <div class="mt-3 grid grid-cols-1 md:grid-cols-3 gap-2">
                <n-input v-model:value="plan.name" size="small" placeholder="候选标准名称" />
                <n-input v-model:value="plan.description" size="small" placeholder="说明" />
                <n-input v-model:value="plan.applicableScenes" size="small" placeholder="适用场景" />
              </div>
              <n-button class="mt-2" size="tiny" secondary @click="runAction(() => saveState(), '候选标准已保存')">
                保存候选标准
              </n-button>
              <div class="mt-3 flex flex-wrap gap-2">
                <n-tag
                  v-for="card in cardsForPlan(plan)"
                  :key="card.id"
                  size="small"
                  closable
                  @close="runAction(() => removeExperienceCardFromDraft(state, plan.id, card.id), '已移除经验卡')"
                >
                  {{ card.title }}
                </n-tag>
              </div>
            </div>
          </div>
        </n-tab-pane>

        <n-tab-pane name="standards" tab="正式写作标准">
          <n-empty v-if="!standards.length" description="暂无正式写作标准" />
          <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-3">
            <div v-for="standard in standards" :key="standard.id" class="rounded border border-gray-200 bg-white p-3">
              <div class="flex items-start justify-between gap-2">
                <div>
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="font-medium text-gray-800">{{ standard.name }}</span>
                    <n-tag size="small" :type="sourceType(standard.sourceKind)">{{ standard.sourceLabel }}</n-tag>
                    <n-tag size="small" :type="statusType(standard.active)">{{ standard.statusLabel }}</n-tag>
                  </div>
                  <p class="mt-1 text-xs text-gray-500">{{ standard.applicableScenes || standard.category }}</p>
                </div>
                <n-space size="small">
                  <n-button size="tiny" secondary @click="runAction(() => toggleWritingStandardActive(state, standard.id), standard.active ? '已取消激活' : '已激活')">
                    {{ standard.active ? '取消激活' : '激活' }}
                  </n-button>
                  <n-button size="tiny" secondary @click="runAction(() => copyWritingStandardToMine(state, standard.id), '已复制为我的写作标准')">
                    复制为我的写作标准
                  </n-button>
                  <n-button
                    v-if="standard.sourceKind === 'user'"
                    size="tiny"
                    secondary
                    @click="runAction(() => updateUserWritingStandard(state, standard.id, standard), '已保存写作标准')"
                  >
                    保存
                  </n-button>
                  <n-button v-if="standard.sourceKind === 'user'" size="tiny" type="error" secondary @click="handleDeleteStandard(standard)">
                    删除
                  </n-button>
                </n-space>
              </div>
              <div class="mt-3 text-xs leading-relaxed text-gray-600 space-y-1">
                <div v-if="standard.sourceKind === 'user'" class="grid grid-cols-1 md:grid-cols-2 gap-2 text-sm">
                  <n-input v-model:value="standard.name" size="small" placeholder="标准名称" />
                  <n-input v-model:value="standard.applicableScenes" size="small" placeholder="适用场景" />
                  <n-input :value="standard.principles?.[0] || ''" size="small" placeholder="写法原则" @update:value="value => setFirstPrinciple(standard, value)" />
                  <n-input v-model:value="standard.originalMicroDemo" size="small" placeholder="原创微示范" />
                  <n-input v-model:value="standard.antiAiReminder" size="small" placeholder="反 AI 提醒" />
                </div>
                <p><span class="font-medium text-gray-700">写法原则：</span>{{ standard.principles?.[0] || standard.shortRule }}</p>
                <p><span class="font-medium text-gray-700">原创微示范：</span>{{ standard.originalMicroDemo || '无' }}</p>
                <p><span class="font-medium text-gray-700">反 AI 提醒：</span>{{ standard.antiAiReminder || '无' }}</p>
                <p><span class="font-medium text-gray-700">调用强度：</span>{{ standard.callStrength }}</p>
                <p><span class="font-medium text-gray-700">关联经验卡：</span>{{ standard.experienceCardSnapshots?.length || 0 }} 张快照</p>
              </div>
            </div>
          </div>
        </n-tab-pane>
      </n-tabs>
    </n-spin>
  </div>
</template>
