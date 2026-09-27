<script setup>
import { computed, watch, onBeforeUnmount } from 'vue'
import { NButton, NResult, NSkeleton } from 'naive-ui'
import { useRoute } from 'vue-router'

import NotFoundView from './NotFoundView.vue'
import { api } from '../api/db/client.js'
import { createProjectOverviewContext } from '../application/projects/projectOverviewContext.js'
import { artifactStatusLabel, continuitySummary } from '../application/projects/projectOverview.js'
import { useRouteProject } from '../composables/useRouteProject.js'
import {
  manuscriptPath,
  finalChapterPath,
  planningStoryBlocksPath,
  chapterWriterPath,
  planningOutlinesPath,
  planningVolumesPath,
  projectBiblePath,
  projectContractPath,
  projectSeedsPath,
} from '../router/projectRoutes.js'
import { useProjectStore } from '../stores/projectStore.js'

const route = useRoute()
const routeProject = useRouteProject()
const projectStore = useProjectStore()
const context = createProjectOverviewContext(api)
const contextState = computed(() => context.state.value.projectId === routeProjectId.value ? context.state.value : { status: 'loading' })
onBeforeUnmount(context.reset)

const routeProjectId = computed(() => String(route.params.projectId || ''))
const overview = computed(() => {
  const value = projectStore.currentOverview
  return projectStore.overviewStatus === 'ready'
    && projectStore.overviewProjectId === routeProjectId.value
    && value?.project?.id === routeProjectId.value
    ? value
    : null
})
const overviewState = computed(() => {
  if (projectStore.overviewProjectId !== routeProjectId.value) return 'stale'
  return projectStore.overviewStatus
})

const number = value => new Intl.NumberFormat('zh-CN').format(value)
const date = value => new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
}).format(new Date(value))

const progressItems = computed(() => {
  if (!overview.value) return []
  const { project, progress } = overview.value
  return [
    { label: '全书目标', value: `${number(project.targetWords)} 字`, note: `预计 ${number(project.targetChapters)} 章` },
    { label: '已定稿', value: `${number(progress.finalizedScalarCount)} 字`, note: `共 ${number(progress.finalizedChapterCount)} 章` },
    {
      label: '当前分卷',
      value: progress.currentVolume
        ? `第 ${number(progress.currentVolume.order)} 卷 · ${progress.currentVolume.title}`
        : '尚未确认分卷',
      note: `当前权威：第 ${number(progress.authoritativeChapterNumber)} 章`,
    },
    {
      label: '最近定稿',
      value: progress.latestFinalChapter
        ? `第 ${number(progress.latestFinalChapter.number)} 章 · ${progress.latestFinalChapter.title}`
        : '尚无定稿章节',
      note: progress.latestFinalChapter
        ? date(progress.latestFinalChapter.finalizedAtMs)
        : '从当前权威章节开始创作',
    },
  ]
})

const moduleItems = computed(() => {
  if (!overview.value) return []
  const id = overview.value.project.id
  const status = overview.value.modules
  return [
    { key: 'seed', label: '创作种子', description: '题材、核心创意与作品方向', path: projectSeedsPath(id), status: status.seed },
    { key: 'contract', label: '创作契约', description: '全书目标与创作边界', path: projectContractPath(id), status: status.contract },
    { key: 'bible', label: '创作圣经', description: '世界、人物与长期设定', path: projectBiblePath(id), status: status.bible },
    { key: 'planning', label: '故事规划', description: '分卷、情节线与故事块', path: planningVolumesPath(id), status: status.planning },
    { key: 'outline', label: '本章小纲', description: '当前权威章节的写作依据', path: planningOutlinesPath(id), status: status.outline },
    { key: 'writing', label: '正文写作', description: '工作稿与已定稿章节', path: overview.value.project.lifecycle === 'archived' ? manuscriptPath(id) : chapterWriterPath(id, overview.value.progress.authoritativeChapterNumber), status: status.writing },
  ]
})

const writerCoreSummary = computed(() => {
  const core = overview.value?.writerCore
  if (!core) return ''
  return core.synchronized
    ? `创作核心已同步至第 ${number(core.canonRevision)} 版`
    : `创作核心尚未同步：正典第 ${number(core.canonRevision)} 版，写作投影第 ${number(core.projectionRevision)} 版`
})

async function loadProjectOverview({ force = false } = {}) {
  const projectId = routeProjectId.value
  if (!projectId || !['active', 'archived'].includes(routeProject.state.value)) return
  if (
    !force
    && projectStore.overviewProjectId === projectId
    && projectStore.overviewStatus === 'loading'
  ) return
  try {
    await Promise.all([projectStore.loadOverview(projectId), context.load(projectId)])
  } catch {
    // Store keeps the fixed retryable state; transport details are never rendered.
  }
}

async function retryOverview() {
  if (routeProject.state.value === 'error') await routeProject.reload({ force: true })
  await loadProjectOverview({ force: true })
}

watch(
  () => [routeProjectId.value, routeProject.state.value],
  () => { void loadProjectOverview() },
  { immediate: true },
)
</script>

<template>
  <section
    v-if="routeProject.state.value === 'loading'"
    class="overview-page"
    aria-busy="true"
  >
    <div class="overview-state" role="status" aria-live="polite">
      <p>正在读取项目身份</p>
      <n-skeleton text :repeat="4" />
    </div>
  </section>

  <not-found-view
    v-else-if="routeProject.state.value === 'missing'"
    title="项目不存在或已被删除"
    description="请返回项目库确认项目状态。系统不会打开其他项目作为替代。"
  />

  <section v-else-if="routeProject.state.value === 'error'" class="overview-page">
    <n-result
      role="alert"
      status="error"
      title="项目概览暂时无法加载"
      description="项目身份读取失败，请稍后重试。"
    >
      <template #footer>
        <n-button type="primary" @click="retryOverview">重试</n-button>
      </template>
    </n-result>
  </section>

  <section
    v-else-if="overviewState === 'error'"
    class="overview-page"
  >
    <n-result
      role="alert"
      status="error"
      title="项目概览暂时无法加载"
      description="已保留当前项目，请重新读取服务端概览。"
    >
      <template #footer>
        <n-button type="primary" @click="retryOverview">重试</n-button>
      </template>
    </n-result>
  </section>

  <section
    v-else-if="overviewState === 'loading' || overviewState === 'idle'"
    class="overview-page"
    aria-busy="true"
  >
    <div class="overview-state" role="status" aria-live="polite">
      <p>正在读取当前项目概览</p>
      <n-skeleton text :repeat="5" />
    </div>
  </section>

  <section
    v-else-if="overviewState === 'stale' || !overview"
    class="overview-page"
    aria-busy="true"
  >
    <div class="overview-state" role="status" aria-live="polite">
      <p>正在读取当前项目概览</p>
      <n-skeleton text :repeat="5" />
    </div>
  </section>

  <article v-else class="overview-page overview-ledger">
    <header class="overview-heading"><h1>作品概览</h1><p>{{ overview.project.title }} · {{ overview.project.genre }} · 已定稿 {{ overview.progress.finalizedChapterCount }} 章</p></header>
    <section class="overview-resume" aria-label="当前创作进度">
      <span class="overview-status">{{ overview.project.lifecycle === 'archived' ? '已归档 · 只读' : overview.writerCore?.synchronized ? '进度已同步' : '进度待核对' }}</span>
      <h2>{{ overview.progress.latestFinalChapter ? `第 ${overview.progress.latestFinalChapter.number} 章已完成` : '开始这部作品的创作' }}</h2>
      <p v-if="contextState.status === 'loading'" role="status">正在读取当前创作位置…</p>
      <template v-else-if="contextState.action?.state === 'available' && overview.project.lifecycle !== 'archived'">
        <p>{{ contextState.action.description }}</p>
        <router-link class="overview-primary" :to="contextState.action.targetPath">{{ contextState.action.label }}</router-link>
      </template>
      <router-link v-else-if="overview.project.lifecycle === 'archived'" class="overview-primary" :to="manuscriptPath(routeProjectId)">阅读作品稿件</router-link>
      <template v-else><p>{{ contextState.action?.description || '当前创作状态暂时无法核实，请重新读取后继续。' }}</p><n-button @click="context.load(routeProjectId)">{{ contextState.action?.label || '重新读取创作状态' }}</n-button></template>
    </section>
    <div class="overview-current-grid">
      <section aria-label="当前故事块">
        <h2>当前故事块{{ contextState.block ? ` · ${contextState.block.title}` : '' }}</h2>
        <template v-if="contextState.block"><p>{{ contextState.block.blockGoal }}</p><p class="overview-muted">{{ contextState.block.mainPressure }}</p><small>此处为已确认安排；实际完成情况请在故事规划中查看。</small></template>
        <p v-else>{{ contextState.status === 'loading' ? '正在读取故事安排…' : contextState.planningUnavailable ? '故事安排暂时无法读取。' : '尚未确认当前故事块。' }}</p>
        <router-link :to="planningStoryBlocksPath(routeProjectId)">查看故事规划</router-link>
      </section>
      <section aria-label="最近定稿">
        <h2>最近定稿</h2>
        <ul v-if="contextState.chapters?.length"><li v-for="chapter in contextState.chapters" :key="chapter.number"><router-link :to="finalChapterPath(routeProjectId, chapter.number)">第 {{ chapter.number }} 章 · {{ chapter.title }}</router-link></li></ul>
        <p v-else>{{ contextState.status === 'loading' ? '正在读取定稿目录…' : contextState.manuscriptUnavailable ? '定稿目录暂时无法读取。' : '尚无已定稿章节。' }}</p>
        <router-link :to="manuscriptPath(routeProjectId)">打开作品稿件</router-link>
      </section>
    </div>

    <details class="overview-more"><summary>创作基础与项目详情</summary>

    <section class="overview-progress" aria-labelledby="overview-progress-title">
      <div class="overview-section-heading">
        <p>PRODUCTION POSITION</p>
        <h2 id="overview-progress-title">创作进度</h2>
      </div>
      <dl>
        <div v-for="item in progressItems" :key="item.label">
          <dt>{{ item.label }}</dt>
          <dd>{{ item.value }}</dd>
          <small>{{ item.note }}</small>
        </div>
      </dl>
    </section>

    <section class="overview-modules" aria-labelledby="overview-modules-title">
      <div class="overview-section-heading">
        <p>AUTHORITIES</p>
        <h2 id="overview-modules-title">创作模块</h2>
        <span>按你的创作习惯手动进入，不代替确认与决策。</span>
      </div>
      <div class="overview-module-list">
        <router-link
          v-for="(item, index) in moduleItems"
          :key="item.key"
          class="overview-module"
          :to="item.path"
        >
          <span class="overview-module__index" aria-hidden="true">0{{ index + 1 }}</span>
          <span class="overview-module__copy">
            <strong>{{ item.label }}</strong>
            <small>{{ item.description }}</small>
          </span>
          <span class="overview-module__status">{{ artifactStatusLabel(item.status) }}</span>
        </router-link>
      </div>
    </section>

    <div class="overview-lower-grid">
      <section class="overview-core" aria-labelledby="overview-core-title">
        <div class="overview-section-heading">
          <p>STORY MEMORY</p>
          <h2 id="overview-core-title">长篇一致性</h2>
        </div>
        <dl>
          <div>
            <dt>创作核心</dt>
            <dd>{{ writerCoreSummary }}</dd>
          </div>
          <div>
            <dt>连续性问题</dt>
            <dd>{{ continuitySummary(overview.continuity) }}</dd>
          </div>
        </dl>
      </section>

      <section class="overview-achievements" aria-labelledby="overview-achievements-title">
        <div class="overview-section-heading">
          <p>RECENT MILESTONES</p>
          <h2 id="overview-achievements-title">最近完成</h2>
        </div>
        <ol v-if="overview.recentAchievements.length">
          <li
            v-for="achievement in overview.recentAchievements.slice(0, 5)"
            :key="`${achievement.kind}:${achievement.occurredAtMs}:${achievement.label}`"
            class="overview-achievement"
          >
            <span>{{ achievement.label }}</span>
            <time :datetime="new Date(achievement.occurredAtMs).toISOString()">
              {{ date(achievement.occurredAtMs) }}
            </time>
          </li>
        </ol>
        <p v-else class="overview-achievements__empty">完成首个创作确认后，这里会留下里程碑。</p>
      </section>
    </div>
    </details>
  </article>
</template>

<style scoped>
.overview-page {
  min-height: 100%;
  padding: clamp(22px, 4vw, 56px);
  color: var(--nc-ink);
  background: var(--nc-canvas);
}

.overview-ledger,
.overview-state {
  width: min(1180px, 100%);
  margin-inline: auto;
  border: 1px solid var(--nc-border);
  border-radius: 10px;
  background: var(--nc-paper);
  box-shadow: 0 24px 64px rgba(58, 43, 27, .065);
}

.overview-ledger {
  padding: 24px 32px;
  border:0; border-radius:0; box-shadow:none; background:var(--nc-canvas);
}
.overview-heading h1{font:500 28px Georgia,'Noto Serif SC',serif;margin:0 0 10px}.overview-heading p,.overview-muted{color:var(--nc-muted);font-size:13px}.overview-resume{margin:24px 0 18px;padding:24px;border:1px solid var(--nc-border);border-radius:5px;background:var(--nc-paper)}.overview-status{display:inline-block;padding:5px 12px;border-radius:5px;background:var(--nc-wash);color:var(--nc-muted);font-size:12px}.overview-resume h2{font:500 26px Georgia,'Noto Serif SC',serif;margin:20px 0 12px}.overview-resume p{font-size:14px;line-height:1.8}.overview-primary{display:block;width:fit-content;min-width:200px;margin:14px 0 0 auto;padding:11px 18px;border-radius:6px;background:var(--nc-vermilion);color:var(--nc-paper);text-decoration:none;text-align:center}.overview-current-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px}.overview-current-grid>section{display:flex;flex-direction:column;min-width:0;min-height:230px;padding:22px;border:1px solid var(--nc-border);border-radius:5px;background:var(--nc-paper)}.overview-current-grid h2{font:500 20px Georgia,'Noto Serif SC',serif;margin:0 0 16px}.overview-current-grid p{margin:0 0 12px;line-height:1.8;font-size:14px}.overview-current-grid small{color:var(--nc-muted);line-height:1.7}.overview-current-grid>section>a{margin-top:auto;padding-top:20px;color:var(--nc-vermilion);text-decoration:none;font-size:14px}.overview-current-grid ul{list-style:none;padding:0;margin:0 0 12px}.overview-current-grid li{border-bottom:1px solid var(--nc-border);padding:10px 0}.overview-current-grid li a{color:var(--nc-ink);text-decoration:none;font-size:14px}.overview-more{margin-top:24px}.overview-more>summary{cursor:pointer;color:var(--nc-muted);font-size:13px;padding:14px 0;border-top:1px solid var(--nc-border)}

.overview-state {
  min-height: 280px;
  padding: clamp(28px, 5vw, 54px);
}

.overview-state > p {
  margin: 0 0 18px;
  color: var(--nc-muted);
}

.overview-section-heading p {
  margin: 0 0 6px;
  color: var(--nc-vermilion);
  font: 700 9px Georgia, 'Noto Serif SC', serif;
  letter-spacing: .18em;
}

.overview-section-heading h2 {
  margin: 0;
  font-family: Georgia, 'Noto Serif SC', 'Songti SC', serif;
  font-size: 24px;
  font-weight: 600;
}

.overview-section-heading > span {
  display: block;
  margin-top: 7px;
  color: var(--nc-muted);
  font-size: 12px;
}

.overview-progress,
.overview-modules,
.overview-lower-grid {
  margin-top: 34px;
}

.overview-progress dl {
  display: grid;
  grid-template-columns: 1fr 1fr 1.35fr 1.35fr;
  margin: 20px 0 0;
  border-block: 1px solid var(--nc-border);
}

.overview-progress dl > div {
  min-width: 0;
  padding: 18px 18px 17px 0;
}

.overview-progress dl > div + div {
  padding-left: 18px;
  border-left: 1px solid var(--nc-border);
}

.overview-progress dt,
.overview-core dt {
  color: var(--nc-muted);
  font-size: 11px;
  letter-spacing: .06em;
}

.overview-progress dd {
  margin: 7px 0 0;
  overflow-wrap: anywhere;
  font-family: Georgia, 'Noto Serif SC', 'Songti SC', serif;
  font-size: clamp(17px, 2vw, 21px);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  line-height: 1.45;
}

.overview-progress small {
  display: block;
  margin-top: 6px;
  color: var(--nc-muted);
  font-size: 11px;
  line-height: 1.55;
}

.overview-module-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-top: 18px;
  border-top: 1px solid var(--nc-border);
}

.overview-module {
  display: grid;
  min-height: 88px;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  gap: 13px;
  align-items: center;
  padding: 15px 18px 15px 0;
  border-bottom: 1px solid var(--nc-border);
  color: inherit;
  text-decoration: none;
}

.overview-module:nth-child(even) {
  padding-left: 18px;
  border-left: 1px solid var(--nc-border);
}

.overview-module:hover .overview-module__copy strong {
  color: var(--nc-vermilion);
}

.overview-module:focus-visible {
  outline: 3px solid rgba(143, 61, 50, .25);
  outline-offset: -3px;
}

.overview-module__index {
  color: #a78d77;
  font: 600 13px Georgia, serif;
}

.overview-module__copy {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.overview-module__copy strong {
  font-family: Georgia, 'Noto Serif SC', 'Songti SC', serif;
  font-size: 17px;
  transition: color .14s ease;
}

.overview-module__copy small {
  color: var(--nc-muted);
  font-size: 11px;
  line-height: 1.5;
}

.overview-module__status {
  padding: 5px 8px;
  border: 1px solid var(--nc-border);
  border-radius: 999px;
  color: var(--nc-muted);
  background: var(--nc-wash);
  font-size: 11px;
  white-space: nowrap;
}

.overview-lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.25fr) minmax(280px, .75fr);
  gap: 34px;
  padding-top: 32px;
  border-top: 1px solid var(--nc-border);
}

.overview-core dl {
  display: grid;
  gap: 0;
  margin: 16px 0 0;
}

.overview-core dl > div {
  display: grid;
  grid-template-columns: 92px minmax(0, 1fr);
  gap: 14px;
  padding: 13px 0;
  border-top: 1px solid rgba(216, 203, 183, .72);
}

.overview-core dd {
  margin: 0;
  line-height: 1.7;
}

.overview-achievements ol {
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}

.overview-achievement {
  display: flex;
  justify-content: space-between;
  gap: 14px;
  padding: 10px 0;
  border-top: 1px solid rgba(216, 203, 183, .72);
  font-family: Georgia, 'Noto Serif SC', 'Songti SC', serif;
  font-size: 13px;
}

.overview-achievement time {
  flex: 0 0 auto;
  color: var(--nc-muted);
  font-family: 'Noto Sans SC', sans-serif;
  font-size: 10px;
}

.overview-achievements__empty {
  color: var(--nc-muted);
  line-height: 1.7;
}

@media (max-width: 900px) {
  .overview-progress dl { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .overview-progress dl > div:nth-child(3) { border-left: 0; }
  .overview-lower-grid { grid-template-columns: 1fr; }
}

@media (max-width: 620px) {
  .overview-progress dl,
  .overview-module-list { grid-template-columns: 1fr; }
  .overview-progress dl > div,
  .overview-progress dl > div + div { padding-inline: 0; border-left: 0; }
  .overview-module,
  .overview-module:nth-child(even) { padding-inline: 0; border-left: 0; }
  .overview-module { grid-template-columns: 28px minmax(0, 1fr); }
  .overview-module__status { grid-column: 2; width: fit-content; }
}

@media (prefers-reduced-motion: reduce) {
  .overview-module__copy strong { transition: none; }
}
</style>
