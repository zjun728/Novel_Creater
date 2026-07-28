<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { createModalFocusManager } from '../common/modalFocusManager.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  history: { type: Array, default: () => [] },
})
const emit = defineEmits(['close'])
const dialog = ref(null)
const initialFocus = ref(null)
const focus = createModalFocusManager({
  getDialog: () => dialog.value,
  getInitialFocus: () => initialFocus.value,
})
let ariaHiddenSnapshot = null

const STATUS_LABELS = Object.freeze({
  current: '当前小纲',
  superseded: '已被后续依据取代',
  session_pinned: '已钉住写作会话',
  archived: '项目已归档',
})
const listText = value => (
  Array.isArray(value) && value.length ? value.join('、') : '无'
)
const statusLabel = value => STATUS_LABELS[value] || '状态不可用'

function setBackgroundHidden(hidden) {
  const appRoot = globalThis.document?.querySelector?.('#app')
  if (!appRoot) return
  if (hidden) {
    ariaHiddenSnapshot = {
      root: appRoot,
      hadAttribute: appRoot.hasAttribute?.('aria-hidden') === true,
      value: appRoot.getAttribute?.('aria-hidden'),
    }
    appRoot.setAttribute?.('aria-hidden', 'true')
    return
  }
  if (!ariaHiddenSnapshot) return
  if (ariaHiddenSnapshot.hadAttribute) {
    ariaHiddenSnapshot.root.setAttribute?.(
      'aria-hidden',
      ariaHiddenSnapshot.value ?? '',
    )
  } else {
    ariaHiddenSnapshot.root.removeAttribute?.('aria-hidden')
  }
  ariaHiddenSnapshot = null
}

function close() {
  emit('close')
}

function handleKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    close()
    return
  }
  focus.trapTab(event)
}

watch(
  () => props.open,
  async open => {
    if (open) {
      setBackgroundHidden(true)
      await nextTick()
      focus.mount()
    } else {
      focus.unmount()
      setBackgroundHidden(false)
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  focus.unmount()
  setBackgroundHidden(false)
})
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="drawer-backdrop" @click.self="close">
      <aside
        ref="dialog"
        class="history-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="章节小纲历史"
        @keydown="handleKeydown"
      >
        <header>
          <div>
            <p>IMMUTABLE OUTLINE ARCHIVE</p>
            <h2>章节小纲历史</h2>
          </div>
          <button ref="initialFocus" type="button" @click="close">关闭</button>
        </header>
        <p class="read-only-note">只读档案：每份小纲都保留成稿时的精确规划依据。</p>
        <ol v-if="history.length" class="revision-list">
          <li
            v-for="item in history"
            :key="item.outlineRevisionId || item.revision"
            class="revision-card"
          >
            <div class="revision-heading">
              <span>R{{ item.revision }}</span>
              <strong>第 {{ item.chapterNumber }} 章</strong>
              <small>{{ statusLabel(item.status) }}</small>
            </div>
            <dl>
              <div><dt>本章目标</dt><dd>{{ item.content?.chapterGoal || '未填写' }}</dd></div>
              <div><dt>预计出场人物</dt><dd>{{ listText(item.content?.expectedCharacters) }}</dd></div>
              <div><dt>承接情节</dt><dd>{{ listText(item.content?.continuation) }}</dd></div>
              <div><dt>推进任务</dt><dd>{{ listText(item.content?.plannedTasks) }}</dd></div>
              <div><dt>主要场景</dt><dd>{{ listText(item.content?.scenes) }}</dd></div>
              <div><dt>禁止提前发生</dt><dd>{{ listText(item.content?.forbiddenEarlyEvents) }}</dd></div>
            </dl>
          </li>
        </ol>
        <p v-else class="empty-copy">尚无已确认章节小纲。</p>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.drawer-backdrop { position:fixed; z-index:36; inset:0; display:flex; justify-content:flex-end; background:color-mix(in srgb,var(--nc-ink) 32%,transparent); }
.history-drawer { width:min(620px,100%); height:100%; overflow:auto; padding:28px; color:var(--nc-ink); background:var(--nc-paper); box-shadow:-20px 0 50px color-mix(in srgb,var(--nc-ink) 18%,transparent); }
header { display:flex; align-items:start; justify-content:space-between; gap:20px; padding-bottom:16px; border-bottom:2px solid var(--nc-vermilion); }
header p { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.17em; }
h2 { margin:5px 0 0; font:600 26px Georgia,'Noto Serif SC',serif; }
button { border:1px solid var(--nc-border); border-radius:6px; padding:8px 12px; color:var(--nc-ink); background:var(--nc-paper); cursor:pointer; }
.read-only-note,.empty-copy { color:var(--nc-muted); line-height:1.7; }
.revision-list { display:grid; gap:18px; margin:18px 0 0; padding:0; list-style:none; }
.revision-card { padding:16px; border:1px solid var(--nc-border); border-radius:8px; background:color-mix(in srgb,var(--nc-paper) 96%,var(--nc-canvas)); }
.revision-heading { display:grid; grid-template-columns:auto 1fr; gap:3px 12px; padding-bottom:12px; border-bottom:1px solid var(--nc-border); }
.revision-heading span { grid-row:span 2; color:var(--nc-vermilion); font:600 22px Georgia,serif; }
.revision-heading small { color:var(--nc-muted); }
dl { display:grid; gap:8px; margin:14px 0 0; }
dl div { display:grid; grid-template-columns:110px 1fr; gap:12px; }
dt { color:var(--nc-muted); font-size:12px; }
dd { margin:0; line-height:1.65; }
</style>
