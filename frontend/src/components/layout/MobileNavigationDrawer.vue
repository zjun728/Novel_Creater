<script>
export function navigationModeForWidth(width) {
  const pixels = Number(width)
  if (pixels <= 760) return 'mobile'
  if (pixels < 1120) return 'compact'
  return 'desktop'
}

export function createMobileNavigationController({
  documentRef = globalThis.document,
  schedule = callback => Promise.resolve().then(callback),
  onRequestClose = () => {},
} = {}) {
  let active = false
  let drawer = null
  let applicationRegion = null
  let trigger = null
  let previousOverflow = ''

  function focusables() {
    return [...(drawer?.querySelectorAll?.(
      'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])',
    ) || [])].filter(item => item?.isConnected !== false)
  }

  function handleKeydown(event) {
    if (!active) return
    if (event.key === 'Escape') {
      event.preventDefault?.()
      onRequestClose()
      return
    }
    if (event.key !== 'Tab') return
    const items = focusables()
    if (!items.length) return
    const first = items[0]
    const last = items.at(-1)
    if (event.shiftKey && documentRef?.activeElement === first) {
      event.preventDefault?.()
      last.focus?.()
    } else if (!event.shiftKey && documentRef?.activeElement === last) {
      event.preventDefault?.()
      first.focus?.()
    }
  }

  async function activate(options = {}) {
    if (active) return
    active = true
    drawer = options.drawer || null
    applicationRegion = options.applicationRegion || null
    trigger = options.trigger || documentRef?.activeElement || null
    previousOverflow = documentRef?.body?.style?.overflow || ''
    if (documentRef?.body?.style) documentRef.body.style.overflow = 'hidden'
    if (applicationRegion) applicationRegion.inert = true
    documentRef?.addEventListener?.('keydown', handleKeydown)
    await schedule(() => focusables()[0]?.focus?.())
  }

  function deactivate({ restoreFocus = true } = {}) {
    if (!active) return
    active = false
    documentRef?.removeEventListener?.('keydown', handleKeydown)
    if (applicationRegion) applicationRegion.inert = false
    if (documentRef?.body?.style) documentRef.body.style.overflow = previousOverflow
    if (restoreFocus && trigger?.isConnected !== false) trigger?.focus?.()
    drawer = null
    applicationRegion = null
    trigger = null
  }

  return { activate, deactivate, handleKeydown }
}
</script>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  open: { type: Boolean, required: true },
  shell: { type: Object, required: true },
  applicationRegion: { type: Object, default: null },
  trigger: { type: Object, default: null },
})
const emit = defineEmits(['close', 'navigate'])
const drawerRef = ref(null)
const controller = createMobileNavigationController({
  schedule: nextTick,
  onRequestClose: () => emit('close'),
})

function close() {
  emit('close')
}

function navigate() {
  emit('navigate')
  emit('close')
}

watch(
  () => props.open,
  async open => {
    if (!open) {
      controller.deactivate()
      return
    }
    await nextTick()
    await controller.activate({
      drawer: drawerRef.value,
      applicationRegion: props.applicationRegion,
      trigger: props.trigger,
    })
  },
  { immediate: true },
)

onBeforeUnmount(() => controller.deactivate())
</script>

<template>
  <div
    v-if="open"
    class="mobile-navigation-drawer__backdrop"
    @mousedown.self="close"
  >
    <aside
      id="mobile-navigation-drawer"
      ref="drawerRef"
      class="mobile-navigation-drawer"
      role="dialog"
      aria-modal="true"
      aria-labelledby="mobile-navigation-title"
    >
      <header class="mobile-navigation-drawer__header">
        <div>
          <p>Novel Creator</p>
          <h2 id="mobile-navigation-title">作品导航</h2>
        </div>
        <button type="button" aria-label="关闭作品导航" @click="close">关闭</button>
      </header>

      <nav aria-label="全局导航">
        <router-link
          v-for="item in shell.globalNavigation"
          :key="item.key"
          :to="item.path"
          :aria-current="item.selected ? 'page' : undefined"
          @click="navigate"
        >
          <span aria-hidden="true">{{ item.mark }}</span>
          <span>{{ item.label }}</span>
        </router-link>
      </nav>

      <nav
        v-if="shell.globalNavigation.find(item => item.key === 'assets')?.selected"
        aria-label="创作资产分类"
        class="mobile-navigation-drawer__subnav"
      >
        <router-link
          v-for="item in shell.assetNavigation"
          :key="item.key"
          :to="item.path"
          :aria-current="item.selected ? 'page' : undefined"
          @click="navigate"
        >
          {{ item.label }}
        </router-link>
      </nav>

      <section
        v-if="shell.projectContext"
        class="mobile-navigation-drawer__project"
        :aria-label="`当前项目：${shell.projectContext.title}`"
      >
        <p>当前作品</p>
        <h3>{{ shell.projectContext.title }}</h3>
        <span v-if="shell.projectContext.archived">已归档</span>
        <nav v-if="shell.projectContext.modules.length" aria-label="项目模块">
          <router-link
            v-for="module in shell.projectContext.modules"
            :key="module.key"
            :to="module.path"
            :aria-current="module.selected ? 'page' : undefined"
            @click="navigate"
          >
            <span aria-hidden="true">{{ module.mark }}</span>
            <span>{{ module.label }}</span>
          </router-link>
        </nav>
      </section>

      <p class="mobile-navigation-drawer__local"><span aria-hidden="true"></span>仅限本机</p>
    </aside>
  </div>
</template>

<style scoped>
.mobile-navigation-drawer__backdrop {
  position: fixed;
  z-index: 2200;
  inset: 0;
  display: flex;
  align-items: stretch;
  overflow: hidden;
  background: rgba(48, 42, 35, .48);
  animation: drawer-backdrop-in .16s ease-out;
}

.mobile-navigation-drawer {
  width: min(336px, calc(100vw - 32px));
  max-width: 100%;
  height: 100%;
  padding: 18px 16px;
  overflow-y: auto;
  overflow-wrap: anywhere;
  color: var(--nc-ink);
  background: var(--nc-paper);
  box-shadow: 18px 0 54px rgba(48, 42, 35, .22);
  animation: drawer-panel-in .18s ease-out;
}

.mobile-navigation-drawer__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 2px 16px;
  border-bottom: 1px solid var(--nc-border);
}

.mobile-navigation-drawer__header p,
.mobile-navigation-drawer__project > p {
  margin: 0 0 4px;
  color: var(--nc-vermilion);
  font: 700 10px Georgia, serif;
  letter-spacing: .14em;
  text-transform: uppercase;
}

.mobile-navigation-drawer h2,
.mobile-navigation-drawer h3 {
  margin: 0;
  font-family: Georgia, 'Noto Serif SC', serif;
}

.mobile-navigation-drawer h2 { font-size: 22px; }
.mobile-navigation-drawer h3 { overflow-wrap: anywhere; font-size: 18px; line-height: 1.55; }

.mobile-navigation-drawer button,
.mobile-navigation-drawer a {
  min-width: 44px;
  min-height: 44px;
}

.mobile-navigation-drawer button {
  padding: 0 14px;
  border: 1px solid var(--nc-border);
  color: var(--nc-ink);
  background: var(--nc-paper);
  cursor: pointer;
  font: inherit;
}

.mobile-navigation-drawer nav {
  display: grid;
  gap: 4px;
  padding: 12px 0;
}

.mobile-navigation-drawer a {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-radius: 5px;
  color: var(--nc-muted);
  font-weight: 650;
  line-height: 1.5;
  text-decoration: none;
}

.mobile-navigation-drawer a[aria-current="page"] {
  color: var(--nc-vermilion);
  background: #efe2d3;
  box-shadow: inset 3px 0 0 var(--nc-vermilion);
}

.mobile-navigation-drawer__subnav {
  margin-top: -8px;
  padding-left: 32px !important;
  border-bottom: 1px solid var(--nc-border);
}

.mobile-navigation-drawer__project {
  margin-top: 8px;
  padding: 18px 2px 4px;
  border-top: 1px solid var(--nc-border);
}

.mobile-navigation-drawer__project > span {
  display: inline-block;
  margin-top: 8px;
  color: var(--nc-muted);
  font-size: 13px;
}

.mobile-navigation-drawer__local {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 18px 2px 0;
  color: var(--nc-muted);
  font-size: 13px;
}

.mobile-navigation-drawer__local span {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #70815d;
}

.mobile-navigation-drawer :is(a, button):focus-visible {
  outline: 3px solid rgba(143, 61, 50, .34);
  outline-offset: 2px;
}

@keyframes drawer-backdrop-in { from { opacity: 0; } }
@keyframes drawer-panel-in { from { transform: translateX(-20px); } }

@media (prefers-reduced-motion: reduce) {
  .mobile-navigation-drawer__backdrop,
  .mobile-navigation-drawer {
    animation: none;
    transition: none;
  }
}
</style>
