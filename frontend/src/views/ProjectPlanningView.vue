<script setup>
import { computed, onBeforeUnmount, onMounted, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute } from 'vue-router'

import { createPlanningWorkspaceController } from '../application/planning/planningWorkspaceController.js'
import PlanningWorkspace from '../components/planning/PlanningWorkspace.vue'
import { useAppMessage } from '../composables/useAppMessage.js'
import { useRouteProject } from '../composables/useRouteProject.js'
import {
  planningPlotsPath,
  planningStoryBlocksPath,
  planningVolumesPath,
} from '../router/projectRoutes.js'
import { useOperationStore } from '../stores/operationStore.js'
import { usePlanningStore } from '../stores/planningStore.js'
import NotFoundView from './NotFoundView.vue'

const props = defineProps({
  activeTab: {
    type: String,
    default: '',
    validator: value => ['', 'volumes', 'plots', 'story-blocks'].includes(value),
  },
})
const route = useRoute()
const routeProject = useRouteProject()
const planningStore = usePlanningStore()
const operationStore = useOperationStore()
const message = useAppMessage()
const projectId = computed(() => String(route.params.projectId || ''))
const ROUTE_TABS = Object.freeze({
  ProjectPlanningVolumes: 'volumes',
  ProjectPlanningPlots: 'plots',
  ProjectPlanningStoryBlocks: 'story-blocks',
})
const activeTab = computed(() => (
  props.activeTab || ROUTE_TABS[String(route.name)] || 'volumes'
))

const controller = createPlanningWorkspaceController({
  store: planningStore,
  projectId: () => projectId.value,
  isArchived: () => routeProject.state.value === 'archived',
  operationStore,
  confirmLeave: () => window.confirm(
    '存在未保存或尚未核对的规划状态。确定离开故事规划吗？',
  ),
})

watch(
  () => [projectId.value, routeProject.state.value],
  ([nextProjectId, lifecycle]) => {
    controller.enterProject(nextProjectId)
    if (
      nextProjectId
      && ['active', 'archived'].includes(lifecycle)
    ) {
      void planningStore.ensureLoaded(nextProjectId).catch(() => {})
    }
  },
  { immediate: true },
)
watch(
  () => controller.notice.value,
  value => {
    if (value) message.success(value)
  },
)

onBeforeRouteLeave(to => controller.requestRouteLeave(to))
onBeforeRouteUpdate(to => controller.requestRouteLeave(to))
onMounted(() => window.addEventListener('beforeunload', controller.beforeUnload))
onBeforeUnmount(() => (
  window.removeEventListener('beforeunload', controller.beforeUnload)
))
</script>

<template>
  <section class="planning-page">
    <nav
      v-if="['active', 'archived'].includes(routeProject.state.value)"
      class="planning-tabs"
      aria-label="故事规划分区"
    >
      <router-link
        :to="planningVolumesPath(projectId)"
        :aria-current="activeTab === 'volumes' ? 'page' : undefined"
      >
        分卷
      </router-link>
      <router-link
        :to="planningPlotsPath(projectId)"
        :aria-current="activeTab === 'plots' ? 'page' : undefined"
      >
        情节线
      </router-link>
      <router-link
        :to="planningStoryBlocksPath(projectId)"
        :aria-current="activeTab === 'story-blocks' ? 'page' : undefined"
      >
        故事块
      </router-link>
    </nav>

    <section v-if="routeProject.state.value === 'loading'" class="route-sheet" aria-busy="true">
      正在读取项目…
    </section>
    <not-found-view
      v-else-if="routeProject.state.value === 'missing'"
      title="项目不存在"
      description="无法打开这个项目的故事规划。"
    />
    <section v-else-if="routeProject.state.value === 'error'" class="route-sheet">
      <h1>项目暂时无法加载</h1>
      <button type="button" @click="routeProject.reload">重试</button>
    </section>
    <planning-workspace
      v-else
      :store="planningStore"
      :controller="controller"
      :active-tab="activeTab"
    />
  </section>
</template>

<style scoped>
.planning-page { min-height:100%; padding:clamp(18px,4vw,54px); color:var(--nc-ink); background:var(--nc-canvas); }
.planning-tabs { display:flex; width:min(1120px,100%); gap:4px; margin:0 auto 16px; border-bottom:1px solid var(--nc-border); }
.planning-tabs a { position:relative; padding:10px 18px; color:var(--nc-muted); text-decoration:none; }
.planning-tabs a[aria-current="page"] { color:var(--nc-ink); font-weight:700; }
.planning-tabs a[aria-current="page"]::after { position:absolute; right:12px; bottom:-1px; left:12px; height:2px; background:var(--nc-vermilion); content:''; }
.route-sheet { width:min(1120px,100%); margin:auto; padding:32px; border:1px solid var(--nc-border); background:var(--nc-paper); }
</style>
