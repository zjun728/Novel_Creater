<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { BIBLE_PROPOSAL_SCOPES } from '@/application/bible/bibleProposalScopes.js'
import { createModalFocusManager } from '@/components/common/modalFocusManager.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  snapshot: { type: Object, default: null },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['adopt', 'cancel'])
const dialog = ref(null)
const cancelButton = ref(null)
const teleportEnabled = typeof document !== 'undefined'
let componentMounted = false
let focusGeneration = 0
let focusActive = false
let restoreTarget = null
let returnSectionId = ''
let pageScroll = { scroller: null, left: 0, top: 0, windowLeft: 0, windowTop: 0 }
const sectionScopes = BIBLE_PROPOSAL_SCOPES.filter(scope => scope.key !== 'whole')
const visibleSections = computed(() => props.snapshot?.scope === 'whole'
  ? sectionScopes
  : sectionScopes.filter(scope => scope.key === props.snapshot?.scope))
const focusManager = createModalFocusManager({
  getDialog: () => dialog.value,
  getInitialFocus: () => cancelButton.value,
})

function fieldValue(document, field) {
  const value = document?.[field]
  return Array.isArray(value) ? value : String(value || '')
}
function fieldLabel(field) {
  return ({
    premiseAndPromise: '作品承诺', worldRules: '世界规则', powerOrProgressionSystem: '力量／成长体系',
    protagonist: '主角', coreCast: '核心人物', factions: '势力', longTermConflicts: '长期冲突',
    relationshipDynamics: '关系动力', toneAndNarrativeBoundaries: '基调与叙事边界', continuityGuardrails: '连贯性护栏',
    openDesignQuestions: '开放设计问题',
  })[field] || field
}
async function openFocus() {
  if (focusActive) return
  const generation = ++focusGeneration
  const documentRef = globalThis.document
  const scroller = documentRef?.querySelector?.('#main-content') || null
  restoreTarget = documentRef?.activeElement || null
  returnSectionId = props.snapshot?.scope && props.snapshot.scope !== 'whole' ? `bible-section-${props.snapshot.scope}` : ''
  pageScroll = {
    scroller,
    left: Number(scroller?.scrollLeft || 0),
    top: Number(scroller?.scrollTop || 0),
    windowLeft: Number(globalThis.window?.scrollX || 0),
    windowTop: Number(globalThis.window?.scrollY || 0),
  }
  await nextTick()
  if (!componentMounted || generation !== focusGeneration || !props.open) return
  if (dialog.value) dialog.value.scrollTop = 0
  focusActive = true
  focusManager.mount()
}
function closeFocus() {
  if (!focusActive) return
  focusGeneration += 1
  focusManager.unmount()
  const targetUnavailable = !restoreTarget || restoreTarget.isConnected === false
    || restoreTarget.disabled === true || restoreTarget.props?.disabled === true
    || restoreTarget.getAttribute?.('aria-disabled') === 'true'
  if (targetUnavailable) {
    const documentRef = globalThis.document
    const safeTarget = (returnSectionId ? documentRef?.getElementById?.(returnSectionId) : null)
      || documentRef?.querySelector?.('#main-content')
    safeTarget?.focus?.({ preventScroll: true })
  }
  if (pageScroll.scroller?.isConnected !== false && pageScroll.scroller) {
    if (typeof pageScroll.scroller.scrollTo === 'function') pageScroll.scroller.scrollTo({ left: pageScroll.left, top: pageScroll.top, behavior: 'auto' })
    else { pageScroll.scroller.scrollLeft = pageScroll.left; pageScroll.scroller.scrollTop = pageScroll.top }
  } else {
    globalThis.window?.scrollTo?.({ left: pageScroll.windowLeft, top: pageScroll.windowTop, behavior: 'auto' })
  }
  focusActive = false
  restoreTarget = null
  returnSectionId = ''
}
function cancel() { if (!props.busy) emit('cancel') }
function handleKeydown(event) {
  if (event.key === 'Escape') { event.preventDefault(); cancel(); return }
  if (event.key === 'Tab' && !focusManager.trapTab(event)) { event.preventDefault(); dialog.value?.focus?.() }
}

onMounted(() => { componentMounted = true; if (props.open) void openFocus() })
watch(() => props.open, open => { if (open) void openFocus(); else void nextTick().then(closeFocus) })
onBeforeUnmount(() => { componentMounted = false; closeFocus() })
</script>

<template>
  <Teleport to="body" :disabled="!teleportEnabled">
    <div v-if="open && snapshot" class="bible-proposal-review__overlay">
      <section ref="dialog" class="bible-proposal-review" role="dialog" aria-modal="true" aria-labelledby="bible-proposal-title" tabindex="-1" @keydown="handleKeydown">
        <header>
          <p>AI PROPOSAL · REVIEW ONLY</p>
          <h2 id="bible-proposal-title">{{ snapshot.scopeLabel }}建议对照</h2>
          <span>采纳前不会改动草稿</span>
        </header>
        <section class="bible-proposal-review__request">
          <strong>作者要求</strong>
          <p>{{ snapshot.authorInstructions || '未填写额外要求' }}</p>
        </section>
        <section v-for="section in visibleSections" :key="section.key" class="bible-proposal-review__section">
          <h3>{{ section.label }}</h3>
          <div v-for="field in section.fields" :key="field" class="bible-proposal-review__comparison">
            <h4>{{ fieldLabel(field) }}</h4>
            <article><strong>修改前</strong><ol v-if="Array.isArray(fieldValue(snapshot.current, field))"><li v-for="item in fieldValue(snapshot.current, field)" :key="item.id">{{ item.text }}</li></ol><p v-else>{{ fieldValue(snapshot.current, field) || '尚未填写' }}</p></article>
            <article><strong>建议后</strong><ol v-if="Array.isArray(fieldValue(snapshot.proposal, field))"><li v-for="item in fieldValue(snapshot.proposal, field)" :key="item.id">{{ item.text }}</li></ol><p v-else>{{ fieldValue(snapshot.proposal, field) || '尚未填写' }}</p></article>
          </div>
        </section>
        <footer>
          <button ref="cancelButton" type="button" :disabled="busy" @click="cancel">取消</button>
          <button type="button" :disabled="busy" @click="emit('adopt')">采纳建议</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.bible-proposal-review__overlay { position:fixed; z-index:36; inset:0; display:grid; min-width:0; padding:24px; place-items:center; background:color-mix(in srgb,var(--nc-ink) 42%,transparent); }
.bible-proposal-review { width:min(1080px,100%); max-height:calc(100vh - 48px); min-width:0; overflow:auto; overscroll-behavior:contain; padding:clamp(22px,4vw,38px); color:var(--nc-ink); background:var(--nc-paper); border:1px solid var(--nc-vermilion); box-shadow:0 26px 70px color-mix(in srgb,var(--nc-ink) 28%,transparent); }
.bible-proposal-review > header { display:grid; grid-template-columns:minmax(0,1fr) auto; gap:7px 16px; padding-bottom:16px; border-bottom:2px solid var(--nc-vermilion); }
.bible-proposal-review > header p { grid-column:1 / -1; margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.17em; }
.bible-proposal-review h2 { margin:0; font:600 clamp(27px,4vw,40px)/1.2 Georgia,'Noto Serif SC',serif; }
.bible-proposal-review > header span { align-self:end; color:var(--nc-muted); font-size:12px; }
.bible-proposal-review__request { margin:18px 0; padding:13px; border-left:2px solid var(--nc-vermilion); background:color-mix(in srgb,var(--nc-paper) 82%,var(--nc-canvas)); }
.bible-proposal-review__request p { margin:6px 0 0; color:var(--nc-muted); white-space:pre-wrap; }
.bible-proposal-review__section { min-width:0; padding:20px 0; border-top:1px solid var(--nc-border); }
.bible-proposal-review__section h3 { margin:0 0 12px; font:600 23px Georgia,'Noto Serif SC',serif; }
.bible-proposal-review__comparison { display:grid; grid-template-columns:1fr 1fr; gap:10px; min-width:0; }
.bible-proposal-review__comparison h4 { grid-column:1 / -1; margin:8px 0 0; color:var(--nc-vermilion); font:700 11px Georgia,'Noto Serif SC',serif; letter-spacing:.1em; }
.bible-proposal-review__comparison article { min-width:0; padding:13px; border:1px solid var(--nc-border); background:color-mix(in srgb,var(--nc-paper) 88%,var(--nc-canvas)); }
.bible-proposal-review__comparison article > strong { color:var(--nc-muted); font-size:11px; letter-spacing:.08em; }
.bible-proposal-review__comparison p,.bible-proposal-review__comparison ol { margin:8px 0 0; line-height:1.72; white-space:pre-wrap; }
.bible-proposal-review footer { position:sticky; bottom:-1px; display:flex; justify-content:flex-end; gap:10px; margin-top:18px; padding:14px 0 0; background:var(--nc-paper); }
.bible-proposal-review button { min-height:40px; border:1px solid var(--nc-border); padding:8px 14px; color:var(--nc-ink); background:var(--nc-paper); font:600 14px Georgia,'Noto Serif SC',serif; cursor:pointer; }
.bible-proposal-review button:last-child { color:var(--nc-paper); border-color:var(--nc-vermilion); background:var(--nc-vermilion); }
.bible-proposal-review button:focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:3px; }
@media (max-width:700px) { .bible-proposal-review__overlay { padding:10px; } .bible-proposal-review { max-height:calc(100vh - 20px); } .bible-proposal-review__comparison { grid-template-columns:1fr; } .bible-proposal-review__comparison h4 { grid-column:1; } }
@media (prefers-reduced-motion:reduce) { .bible-proposal-review,.bible-proposal-review * { scroll-behavior:auto !important; transition:none !important; } }
</style>
