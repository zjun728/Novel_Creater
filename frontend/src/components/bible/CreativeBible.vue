<script setup>
import { ref, onMounted, watch } from 'vue'
import { NButton, NCard, NInput, NSpace, NTag, NDynamicTags, useMessage } from 'naive-ui'
import { useNovelStore } from '@/stores/novelStore'

const props = defineProps({
  projectId: { type: String, required: true }
})

const novelStore = useNovelStore()
const message = useMessage()

const editing = ref(false)
const formData = ref({
  premise: '',
  targetReader: '',
  styleBible: '',
  themeBible: '',
  worldRules: '',
  forbiddenDirections: []
})

onMounted(async () => {
  await novelStore.loadBible(props.projectId)
  if (novelStore.bible) {
    formData.value = {
      premise: novelStore.bible.premise || '',
      targetReader: novelStore.bible.targetReader || '',
      styleBible: novelStore.bible.styleBible || '',
      themeBible: novelStore.bible.themeBible || '',
      worldRules: novelStore.bible.worldRules || '',
      forbiddenDirections: novelStore.bible.forbiddenDirections || []
    }
  }
})

watch(() => props.projectId, async (newId) => {
  if (newId) {
    await novelStore.loadBible(newId)
  }
})

async function handleSave() {
  await novelStore.saveBible(props.projectId, formData.value)
  message.success('创作圣经已保存')
  editing.value = false
}
</script>

<template>
  <n-card title="创作圣经" size="small">
    <template #header-extra>
      <n-button size="tiny" @click="editing = !editing">{{ editing ? '取消' : '编辑' }}</n-button>
    </template>

    <div v-if="!editing && novelStore.bible" class="space-y-3 text-sm">
      <div v-if="novelStore.bible.premise">
        <span class="font-medium text-gray-500">作品定位：</span>
        <p class="text-gray-700">{{ novelStore.bible.premise }}</p>
      </div>
      <div v-if="novelStore.bible.targetReader">
        <span class="font-medium text-gray-500">目标读者：</span>
        <span>{{ novelStore.bible.targetReader }}</span>
      </div>
      <div v-if="novelStore.bible.styleBible">
        <span class="font-medium text-gray-500">风格要求：</span>
        <p class="text-gray-700 whitespace-pre-wrap">{{ novelStore.bible.styleBible }}</p>
      </div>
      <div v-if="novelStore.bible.themeBible">
        <span class="font-medium text-gray-500">主题与母题：</span>
        <p class="text-gray-700 whitespace-pre-wrap">{{ novelStore.bible.themeBible }}</p>
      </div>
      <div v-if="novelStore.bible.worldRules">
        <span class="font-medium text-gray-500">世界规则：</span>
        <p class="text-gray-700 whitespace-pre-wrap">{{ novelStore.bible.worldRules }}</p>
      </div>
      <div v-if="novelStore.bible.forbiddenDirections?.length">
        <span class="font-medium text-gray-500">禁止方向：</span>
        <n-space>
          <n-tag v-for="d in novelStore.bible.forbiddenDirections" :key="d" size="small" type="error">{{ d }}</n-tag>
        </n-space>
      </div>
    </div>

    <div v-if="!editing && !novelStore.bible" class="text-sm text-gray-400 text-center py-4">
      尚未创建创作圣经。选择一个创作种子后可以快速创建。
    </div>

    <div v-if="editing" class="space-y-3">
      <div>
        <label class="text-xs text-gray-500 mb-1 block">作品定位（一句话）</label>
        <n-input v-model:value="formData.premise" type="textarea" rows="2" placeholder="用一句话说清这是什么故事" />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">目标读者</label>
        <n-input v-model:value="formData.targetReader" placeholder="如：男频 20-35 岁、喜欢节奏明快的读者" />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">风格要求</label>
        <n-input v-model:value="formData.styleBible" type="textarea" rows="3" placeholder="描述期望的写作风格..." />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">主题与母题</label>
        <n-input v-model:value="formData.themeBible" type="textarea" rows="3" placeholder="作品探讨的主题、母题..." />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">世界规则（不可违背）</label>
        <n-input v-model:value="formData.worldRules" type="textarea" rows="4" placeholder="世界观的基本规则..." />
      </div>
      <div>
        <label class="text-xs text-gray-500 mb-1 block">禁止方向</label>
        <n-dynamic-tags v-model:value="formData.forbiddenDirections" />
      </div>
      <n-button type="primary" size="small" @click="handleSave">保存</n-button>
    </div>
  </n-card>
</template>
