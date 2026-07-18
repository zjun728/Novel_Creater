<script>
import { computed, defineComponent } from 'vue'

export function createProjectCardActions(emit, project) {
  const currentProject = typeof project === 'function' ? project : () => project
  const send = event => () => emit(event, currentProject())
  return {
    open: send('open'),
    resume: send('resume'),
    rename: send('rename'),
    archive: send('archive'),
    restore: send('restore'),
    permanentlyDelete: send('delete'),
  }
}

function workflowLabel(status) {
  return {
    drafting: '创作中',
    planning: '规划中',
    completed: '已完成',
  }[status] || '准备中'
}

export default defineComponent({
  name: 'ProjectCard',
  props: {
    project: {
      type: Object,
      required: true,
    },
    archived: {
      type: Boolean,
      default: false,
    },
    pending: {
      type: Boolean,
      default: false,
    },
    resumableChapterNumber: {
      type: Number,
      default: null,
    },
  },
  emits: ['open', 'resume', 'rename', 'archive', 'restore', 'delete'],
  setup(props, { emit }) {
    const actions = createProjectCardActions(emit, () => props.project)
    const canResume = computed(() => (
      !props.archived
      && Number.isInteger(props.resumableChapterNumber)
      && props.resumableChapterNumber > 0
    ))
    const chapterLabel = computed(() => {
      const chapter = Number(props.project?.currentChapter || 0)
      return chapter > 0 ? `已推进至第 ${chapter} 章` : '尚未开始正文'
    })
    return {
      ...actions,
      canResume,
      chapterLabel,
      workflowLabel,
    }
  },
})
</script>

<template>
  <article class="project-card" :class="{ 'project-card--archived': archived }">
    <div class="project-card__marker" aria-hidden="true">{{ archived ? '藏' : '稿' }}</div>

    <div class="project-card__body">
      <div class="project-card__eyebrow">
        <span>{{ archived ? 'ARCHIVED MANUSCRIPT' : 'LONG-FORM MANUSCRIPT' }}</span>
        <span class="project-card__status">{{ archived ? '已归档' : workflowLabel(project.status) }}</span>
      </div>
      <h2>{{ project.title }}</h2>
      <p>{{ archived ? '正文、工作稿和候选均已保留' : chapterLabel }}</p>
    </div>

    <div v-if="!archived" class="project-card__actions">
      <button
        v-if="canResume"
        type="button"
        class="project-action project-action--primary"
        :disabled="pending"
        @click="resume"
      >继续写作</button>
      <button
        type="button"
        class="project-action"
        :class="canResume ? 'project-action--secondary' : 'project-action--primary'"
        :disabled="pending"
        @click="open"
      >打开项目</button>
      <details class="project-more">
        <summary>更多</summary>
        <div class="project-more__menu">
          <button type="button" :disabled="pending" @click="rename">重命名</button>
          <button type="button" :disabled="pending" @click="archive">归档</button>
        </div>
      </details>
    </div>

    <div v-else class="project-card__actions project-card__actions--archived">
      <button
        type="button"
        class="project-action project-action--secondary"
        :disabled="pending"
        @click="restore"
      >恢复</button>
      <button
        type="button"
        class="project-action project-action--danger"
        :disabled="pending"
        @click="permanentlyDelete"
      >永久删除</button>
    </div>
  </article>
</template>

<style scoped>
.project-card {
  position: relative;
  display: grid;
  grid-template-columns: 52px minmax(0, 1fr) auto;
  gap: 22px;
  align-items: center;
  min-height: 158px;
  padding: 24px 26px;
  border: 1px solid var(--nc-border, #d8cbb7);
  border-radius: 12px;
  background: var(--nc-paper, #fffdf8);
  box-shadow: 0 14px 36px rgba(54, 42, 29, .06);
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.project-card:hover {
  border-color: #c4b39a;
  box-shadow: 0 18px 42px rgba(54, 42, 29, .09);
  transform: translateY(-1px);
}

.project-card--archived {
  background: #f8f4ec;
}

.project-card__marker {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border: 1px solid rgba(143, 61, 50, .24);
  border-radius: 50%;
  color: var(--nc-vermilion, #8f3d32);
  background: rgba(143, 61, 50, .06);
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 18px;
}

.project-card__eyebrow {
  display: flex;
  gap: 10px;
  align-items: center;
  color: var(--nc-muted, #766c60);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: .13em;
}

.project-card__status {
  padding-left: 10px;
  border-left: 1px solid #d9cdbb;
  color: var(--nc-vermilion, #8f3d32);
  font-family: 'Noto Sans SC', sans-serif;
  letter-spacing: .04em;
}

.project-card h2 {
  margin: 10px 0 7px;
  color: var(--nc-ink, #302a23);
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: clamp(21px, 2.2vw, 28px);
  font-weight: 600;
  letter-spacing: .02em;
}

.project-card p {
  margin: 0;
  color: var(--nc-muted, #766c60);
  font-size: 13px;
}

.project-card__actions {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: flex-end;
}

.project-action,
.project-more summary,
.project-more button {
  border: 0;
  border-radius: 7px;
  font: inherit;
  font-weight: 650;
  cursor: pointer;
}

.project-action {
  min-height: 38px;
  padding: 0 16px;
}

.project-action--primary {
  color: #fffaf0;
  background: var(--nc-vermilion, #8f3d32);
}

.project-action--primary:hover {
  background: #743128;
}

.project-action--secondary {
  color: var(--nc-ink, #302a23);
  background: #eee6da;
}

.project-action--danger {
  color: #9b2825;
  background: #f5dfda;
}

.project-more {
  position: relative;
}

.project-more summary {
  min-height: 38px;
  padding: 9px 12px;
  color: var(--nc-muted, #766c60);
  list-style: none;
  user-select: none;
}

.project-more summary::-webkit-details-marker {
  display: none;
}

.project-more__menu {
  position: absolute;
  z-index: 8;
  top: calc(100% + 7px);
  right: 0;
  display: grid;
  width: 112px;
  padding: 6px;
  border: 1px solid var(--nc-border, #d8cbb7);
  border-radius: 9px;
  background: var(--nc-paper, #fffdf8);
  box-shadow: 0 14px 34px rgba(54, 42, 29, .14);
}

.project-more button {
  padding: 9px 10px;
  color: var(--nc-ink, #302a23);
  text-align: left;
  background: transparent;
}

.project-more button:hover {
  background: #f2ebdf;
}

button:focus-visible,
summary:focus-visible {
  outline: 3px solid rgba(143, 61, 50, .28);
  outline-offset: 2px;
}

button:disabled,
summary:has(+ .project-more__menu button:disabled) {
  cursor: wait;
  opacity: .58;
}

@media (max-width: 760px) {
  .project-card {
    grid-template-columns: 42px minmax(0, 1fr);
  }

  .project-card__marker {
    width: 40px;
    height: 40px;
  }

  .project-card__actions {
    grid-column: 1 / -1;
    justify-content: flex-start;
    padding-left: 64px;
  }
}
</style>
