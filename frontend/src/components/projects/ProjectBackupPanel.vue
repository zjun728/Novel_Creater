<script setup>
import { computed, onBeforeUnmount } from 'vue'

import { api } from '../../api/db/client.js'
import { createProjectBackupController } from '../../application/project/projectBackupController.js'
import { useOperationStore } from '../../stores/operationStore.js'

const props = defineProps({
  projectId: { type: [String, Number], default: '' },
  title: { type: String, default: '' },
  lifecycleRevision: { type: Number, default: null },
  archived: { type: Boolean, default: false },
  flushCurrentDraft: { type: Function, default: async () => true },
})

function saveDownload(objectUrl, filename) {
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  link.hidden = true
  document.body.append(link)
  link.click()
  link.remove()
}

const operationStore = useOperationStore()
const controller = createProjectBackupController({
  api,
  operationStore,
  flushCurrentDraft: () => props.flushCurrentDraft(),
  createObjectURL: blob => URL.createObjectURL(blob),
  revokeObjectURL: objectUrl => URL.revokeObjectURL(objectUrl),
  saveBlob: saveDownload,
})
const canBackup = computed(() => (
  Boolean(props.projectId)
  && Number.isInteger(props.lifecycleRevision)
  && props.lifecycleRevision >= 0
  && !controller.busy.value
))

async function backup() {
  if (!canBackup.value) return
  try {
    await controller.backup(
      String(props.projectId),
      props.lifecycleRevision,
      { archived: props.archived },
    )
  } catch {
    // The controller owns the fixed public error copy.
  }
}

onBeforeUnmount(() => controller.dispose())
</script>

<template>
  <section class="project-backup-panel" aria-labelledby="project-backup-title">
    <div class="project-backup-panel__copy">
      <p>PROJECT ARCHIVE · 项目留存</p>
      <h2 id="project-backup-title">项目备份</h2>
      <span v-if="title">{{ title }}</span>
      <small>下载当前项目的完整备份包，用于离线留存；不会改变项目状态。</small>
    </div>

    <div class="project-backup-panel__action-area">
      <p v-if="controller.error.value" class="project-backup-panel__error" role="alert">
        {{ controller.error.value }}
      </p>
      <button
        type="button"
        class="project-backup-panel__action"
        :disabled="!canBackup"
        :aria-busy="controller.busy.value"
        @click="backup"
      >
        {{ controller.busy.value ? '正在创建备份…' : '创建项目备份' }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.project-backup-panel {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: 20px;
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid var(--nc-border);
  color: var(--nc-ink);
}
.project-backup-panel__copy { display: grid; min-width: 0; gap: 4px; }
.project-backup-panel__copy p {
  margin: 0;
  color: var(--nc-vermilion);
  font: 700 10px Georgia, 'Noto Serif SC', serif;
  letter-spacing: .15em;
}
.project-backup-panel__copy h2 {
  margin: 0;
  font: 600 20px Georgia, 'Noto Serif SC', serif;
}
.project-backup-panel__copy span,
.project-backup-panel__copy small {
  color: var(--nc-muted);
  font-size: 12px;
  line-height: 1.65;
}
.project-backup-panel__copy small { margin-top: 3px; }
.project-backup-panel__action-area {
  display: grid;
  flex: 0 0 auto;
  justify-items: end;
  gap: 8px;
}
.project-backup-panel__error {
  max-width: 34ch;
  margin: 0;
  color: var(--nc-vermilion);
  font-size: 12px;
  line-height: 1.5;
  text-align: right;
}
.project-backup-panel__action {
  min-height: 34px;
  padding: 6px 13px;
  border: 1px solid var(--nc-ink);
  border-radius: 3px;
  color: var(--nc-ink);
  background: transparent;
  font: 650 13px Georgia, 'Noto Serif SC', serif;
  cursor: pointer;
}
.project-backup-panel__action:hover:not(:disabled) {
  border-color: var(--nc-vermilion);
  color: var(--nc-vermilion);
}
.project-backup-panel__action:disabled { opacity: .5; cursor: not-allowed; }
.project-backup-panel__action:focus-visible {
  outline: 2px solid var(--nc-vermilion);
  outline-offset: 2px;
}
@media (max-width: 560px) {
  .project-backup-panel { align-items: stretch; flex-direction: column; }
  .project-backup-panel__action-area { justify-items: stretch; }
  .project-backup-panel__error { max-width: none; text-align: left; }
  .project-backup-panel__action { width: 100%; }
}
</style>
