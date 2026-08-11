<script setup>
import { computed, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'

import { api } from '../../api/db/client.js'
import { createProjectImportController } from '../../application/project/projectImportController.js'
import { useOperationStore } from '../../stores/operationStore.js'

const props = defineProps({
  controller: { type: Object, default: null },
})

const ownedController = props.controller ? null : createProjectImportController({
  api,
  router: useRouter(),
  operationStore: useOperationStore(),
})
const controller = props.controller || ownedController

const countSummary = computed(() => {
  const counts = controller.summary.value?.counts
  if (!counts || typeof counts !== 'object' || Array.isArray(counts)) return []
  const count = key => Number.isInteger(counts[key]) && counts[key] >= 0 ? counts[key] : 0
  const total = Object.values(counts).reduce(
    (sum, value) => sum + (Number.isInteger(value) && value >= 0 ? value : 0),
    0,
  )
  return [
    ['记录', total],
    ['章节', count('chapter')],
    ['素材', count('asset')],
    ['语料版本', count('corpus-revision')],
  ].filter(([, value], index) => index === 0 || value > 0)
})

async function choose(event) {
  const input = event.currentTarget
  const selected = input?.files?.length === 1 ? input.files[0] : null
  if (input) input.value = ''
  if (selected) await controller.selectFile(selected)
}

function editTitle(event) {
  controller.setTitle(event.currentTarget.value)
}

async function publish() {
  await controller.importProject()
}

onBeforeUnmount(() => ownedController?.dispose())
</script>

<template>
  <section class="project-import-panel" aria-labelledby="project-import-title">
    <div class="project-import-panel__entry">
      <p id="project-import-title">导入项目备份</p>
      <label class="project-import-panel__picker">
        <span>{{ controller.busy.value && !controller.summary.value ? '正在检查备份…' : '选择项目备份' }}</span>
        <input
          type="file"
          accept=".zip,application/zip"
          :disabled="controller.busy.value"
          @change="choose"
        >
      </label>
    </div>

    <div v-if="controller.file.value" class="project-import-panel__details" aria-live="polite">
      <p class="project-import-panel__filename" :title="controller.filename.value">
        {{ controller.filename.value }}
      </p>

      <template v-if="controller.summary.value">
        <p class="project-import-panel__source">
          来源：{{ controller.summary.value.sourceTitle }}
        </p>
        <dl class="project-import-panel__counts" aria-label="备份内容数量">
          <div v-for="([label, value]) in countSummary" :key="label">
            <dt>{{ label }}</dt><dd>{{ value }}</dd>
          </div>
        </dl>
        <label class="project-import-panel__title">
          <span>新项目名称</span>
          <input
            type="text"
            maxlength="200"
            :value="controller.title.value"
            :disabled="!controller.titleEditable.value"
            @input="editTitle"
          >
        </label>
        <p class="project-import-panel__warning">
          <strong>Provider Not Ready</strong>
          导入后八项任务绑定均为空，请在项目设置中重新配置。
        </p>
        <button
          type="button"
          class="project-import-panel__action"
          :disabled="!controller.ready.value"
          :aria-busy="controller.busy.value"
          @click="publish"
        >
          {{ controller.busy.value ? '正在导入…' : '导入为新项目' }}
        </button>
      </template>
    </div>

    <p v-if="controller.error.value" class="project-import-panel__error" role="alert">
      {{ controller.error.value }}
    </p>
  </section>
</template>

<style scoped>
.project-import-panel {
  position: relative;
  display: grid;
  min-width: min(360px, 78vw);
  gap: 9px;
  padding: 11px 13px;
  border: 1px solid #d4c7b2;
  border-radius: 8px;
  color: var(--nc-ink, #302a23);
  background: #fbf7ef;
  box-shadow: 0 8px 24px rgba(61, 49, 35, .08);
}
.project-import-panel__entry {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.project-import-panel__entry p,
.project-import-panel__filename,
.project-import-panel__source,
.project-import-panel__warning,
.project-import-panel__error { margin: 0; }
.project-import-panel__entry p {
  font: 650 13px 'Noto Serif SC', 'Songti SC', Georgia, serif;
}
.project-import-panel__picker {
  color: var(--nc-vermilion, #8f3d32);
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.project-import-panel__picker input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
}
.project-import-panel__picker:focus-within {
  outline: 2px solid var(--nc-vermilion, #8f3d32);
  outline-offset: 3px;
}
.project-import-panel__details { display: grid; gap: 8px; padding-top: 8px; border-top: 1px solid #e3d9ca; }
.project-import-panel__filename {
  overflow: hidden;
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-import-panel__source { color: var(--nc-muted, #766c60); font-size: 12px; }
.project-import-panel__counts { display: flex; flex-wrap: wrap; gap: 6px; margin: 0; }
.project-import-panel__counts div {
  display: flex;
  gap: 5px;
  padding: 3px 7px;
  border-radius: 999px;
  background: #eee5d7;
  font-size: 11px;
}
.project-import-panel__counts dt { color: var(--nc-muted, #766c60); }
.project-import-panel__counts dd { margin: 0; font-weight: 750; }
.project-import-panel__title { display: grid; gap: 4px; color: var(--nc-muted, #766c60); font-size: 11px; }
.project-import-panel__title input {
  min-height: 34px;
  padding: 6px 9px;
  border: 1px solid #cfc1ad;
  border-radius: 5px;
  color: var(--nc-ink, #302a23);
  background: #fffdf8;
  font: inherit;
  font-size: 13px;
}
.project-import-panel__warning {
  padding-left: 9px;
  border-left: 2px solid #b98237;
  color: #715a37;
  font-size: 11px;
  line-height: 1.5;
}
.project-import-panel__warning strong { display: block; color: #6b4c20; letter-spacing: .02em; }
.project-import-panel__action {
  min-height: 35px;
  border: 0;
  border-radius: 5px;
  color: #fffaf0;
  background: var(--nc-vermilion, #8f3d32);
  font: inherit;
  font-size: 12px;
  font-weight: 700;
  cursor: pointer;
}
.project-import-panel__action:disabled { opacity: .5; cursor: not-allowed; }
.project-import-panel__action:focus-visible,
.project-import-panel__title input:focus-visible {
  outline: 2px solid var(--nc-vermilion, #8f3d32);
  outline-offset: 2px;
}
.project-import-panel__error { color: #822e29; font-size: 12px; }
@media (max-width: 720px) {
  .project-import-panel { width: 100%; min-width: 0; }
}
</style>
