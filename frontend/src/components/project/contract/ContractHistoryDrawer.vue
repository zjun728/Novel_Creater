<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { NAlert, NButton, NDrawer, NDrawerContent, NEmpty, NSpin, NTag } from 'naive-ui'

import { useCreationContractStore } from '@/stores/creationContractStore.js'
import { createLatestRequestGuard } from '@/utils/latestRequest.js'
import ContractDecisionSummary from './ContractDecisionSummary.vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  projectId: { type: String, required: true },
  currentSelectionRevision: { type: Number, default: 0 },
  readOnly: { type: Boolean, default: false },
})
const emit = defineEmits(['update:show', 'cloned'])
const store = useCreationContractStore()
const errorMessage = ref('')
const errorRegion = ref(null)
const cloningRevision = ref(null)
const requestGuard = createLatestRequestGuard()

const rows = computed(() => [...store.history].sort((a, b) => b.revision - a.revision))

function shortHash(value) {
  const text = String(value || '')
  return text ? `${text.slice(0, 12)}…` : '—'
}

function canClone(item) {
  return !props.readOnly
    && Number(item?.selectionRevision) === Number(props.currentSelectionRevision)
}

function reasonLabel(reason) {
  return {
    contract_revision_replaced: '已被更新修订取代',
    selection_generation_superseded: '种子选择代次已改变',
    seed_drift: '种子身份已改变',
    binding_drift: '模型绑定已改变',
  }[reason] || reason
}

async function loadHistory({ append = false } = {}) {
  const generation = requestGuard.begin()
  const targetProjectId = props.projectId
  errorMessage.value = ''
  try {
    const params = append
      ? {
          limit: 20,
          beforeRevision: store.historyNextBeforeRevision,
          append: true,
        }
      : { limit: 20 }
    await store.loadHistory(targetProjectId, params)
  } catch (error) {
    if (!requestGuard.isCurrent(generation)) return
    errorMessage.value = error?.message || '历史修订加载失败'
    await nextTick()
    if (!requestGuard.isCurrent(generation)) return
    errorRegion.value?.focus({ preventScroll: false })
  }
}

function loadMore() {
  if (store.historyLoading || store.historyNextBeforeRevision == null) return
  void loadHistory({ append: true })
}

async function cloneRevision(item) {
  if (!canClone(item) || store.cloning) return
  const generation = requestGuard.begin()
  const targetProjectId = props.projectId
  errorMessage.value = ''
  cloningRevision.value = item.revision
  try {
    const result = await store.cloneRevision(targetProjectId, item.revision)
    if (!requestGuard.isCurrent(generation)) return
    emit('update:show', false)
    emit('cloned', result)
  } catch (error) {
    if (!requestGuard.isCurrent(generation)) return
    errorMessage.value = error?.message || '未来设计草稿创建失败'
    await nextTick()
    if (!requestGuard.isCurrent(generation)) return
    errorRegion.value?.focus({ preventScroll: false })
  } finally {
    if (requestGuard.isCurrent(generation)) cloningRevision.value = null
  }
}

function resetDrawerState() {
  requestGuard.invalidate()
  errorMessage.value = ''
  cloningRevision.value = null
  store.clearHistory()
}

watch(
  () => [props.show, props.projectId],
  ([show, projectId], previous = []) => {
    const [wasShowing, previousProjectId] = previous
    if (!show) {
      if (wasShowing) resetDrawerState()
      return
    }
    if (wasShowing && projectId !== previousProjectId) resetDrawerState()
    void loadHistory()
  },
  { immediate: true },
)

onBeforeUnmount(() => resetDrawerState())
</script>

<template>
  <n-drawer
    :show="props.show"
    width="min(620px, 100vw)"
    placement="right"
    @update:show="emit('update:show', $event)"
  >
    <n-drawer-content title="创作契约历史" closable>
      <p class="drawer-intro">签印修订不可覆盖。只有与当前种子选择代次完全一致的历史修订，才可克隆为面向未来的新草稿。</p>

      <n-alert
        v-if="errorMessage"
        ref="errorRegion"
        tabindex="-1"
        type="error"
        aria-live="assertive"
      >
        {{ errorMessage }}
        <template #action><n-button size="small" @click="loadHistory">重新加载</n-button></template>
      </n-alert>

      <n-spin :show="store.historyLoading">
        <n-empty v-if="!store.historyLoading && !rows.length" description="尚无已签印的历史修订" />
        <div v-else class="history-list">
          <article v-for="item in rows" :key="item.revision" class="history-card">
            <header>
              <div>
                <span>REVISION</span>
                <h3>R{{ item.revision }}</h3>
              </div>
              <n-tag :type="canClone(item) ? 'success' : 'warning'" round>
                选择代次 R{{ item.selectionRevision }}
              </n-tag>
            </header>

            <div v-if="item.supersededReasons?.length" class="superseded-reasons" aria-label="历史失效原因">
              <span v-for="reason in item.supersededReasons" :key="reason">{{ reasonLabel(reason) }}</span>
            </div>

            <dl class="history-facts">
              <div><dt>创作摘要</dt><dd>{{ shortHash(item.creationHash) }}</dd></div>
              <div><dt>风格摘要</dt><dd>{{ shortHash(item.styleHash) }}</dd></div>
            </dl>

            <ContractDecisionSummary
              :creation-contract="item.creationContract"
              :style-contract="item.styleContract"
              :likes="item.likes"
              :dislikes="item.dislikes"
              :heading="`R${item.revision} 作者决策`"
              compact
            />

            <section class="pinned-identities">
              <h4>完整冻结身份</h4>

              <article class="identity-card">
                <strong>种子</strong>
                <dl>
                  <div><dt>ID</dt><dd>{{ item.seedRef?.id || '—' }}</dd></div>
                  <div><dt>修订 ID</dt><dd>{{ item.seedRef?.revisionId || '—' }}</dd></div>
                  <div class="identity-hash"><dt>内容摘要</dt><dd>{{ item.seedRef?.contentHash || '—' }}</dd></div>
                </dl>
              </article>

              <article class="identity-card">
                <strong>故事发动机</strong>
                <dl>
                  <div><dt>ID</dt><dd>{{ item.engineRef?.id || '—' }}</dd></div>
                  <div><dt>批次 ID</dt><dd>{{ item.engineRef?.batchId || '—' }}</dd></div>
                  <div class="identity-hash"><dt>内容摘要</dt><dd>{{ item.engineRef?.contentHash || '—' }}</dd></div>
                </dl>
              </article>

              <article v-for="style in item.styleRefs || []" :key="`style-${style.id}-${style.revision}`" class="identity-card">
                <strong>风格模板</strong>
                <p>ID {{ style.id }} · 修订 R{{ style.revision }}</p>
                <code>{{ style.contentHash }}</code>
              </article>

              <article v-for="card in item.experienceCardRefs || []" :key="`card-${card.id}-${card.revision}`" class="identity-card">
                <strong>经验卡</strong>
                <p>ID {{ card.id }} · 修订 R{{ card.revision }}</p>
                <code>{{ card.contentHash }}</code>
              </article>

              <article v-for="corpus in item.corpusSourceRefs || []" :key="`corpus-${corpus.id}-${corpus.revisionId}`" class="identity-card corpus-identity">
                <header>
                  <strong>语料来源</strong>
                  <n-tag size="small" :type="corpus.pinnedHistoricalRevision ? 'warning' : 'default'">
                    {{ corpus.pinnedHistoricalRevision ? '历史版本已钉住' : '确认时版本' }}
                  </n-tag>
                </header>
                <dl>
                  <div><dt>ID</dt><dd>{{ corpus.id }}</dd></div>
                  <div><dt>修订 ID</dt><dd>{{ corpus.revisionId }}</dd></div>
                  <div><dt>修订序号</dt><dd>R{{ corpus.revision }}</dd></div>
                  <div class="identity-hash"><dt>内容摘要</dt><dd>{{ corpus.contentHash }}</dd></div>
                </dl>
                <section class="fragment-identities">
                  <h5>冻结片段 · {{ corpus.fragments?.length || 0 }}</h5>
                  <article v-for="fragment in corpus.fragments || []" :key="`${fragment.chapterId}-${fragment.fragmentId}`">
                    <p>章节 {{ fragment.chapterId }} · 片段 {{ fragment.fragmentId }}</p>
                    <code>{{ fragment.fragmentHash }}</code>
                    <small>范围 {{ fragment.chapterCharStart }}–{{ fragment.chapterCharEnd }} · 用途 {{ fragment.referenceUse }}</small>
                  </article>
                  <p v-if="!corpus.fragments?.length">该来源未冻结片段</p>
                </section>
              </article>

              <p v-if="!(item.styleRefs?.length || item.experienceCardRefs?.length || item.corpusSourceRefs?.length)">未冻结额外资产</p>
            </section>

            <footer>
              <small v-if="!canClone(item)">
                {{ props.readOnly ? '归档项目仅供只读查看' : '跨种子选择代次的设计不能复活' }}
              </small>
              <n-button
                type="primary"
                :disabled="!canClone(item)"
                :loading="store.cloning && cloningRevision === item.revision"
                @click="cloneRevision(item)"
              >调整未来设计</n-button>
            </footer>
          </article>
          <n-button
            v-if="store.historyNextBeforeRevision !== null"
            class="history-load-more"
            block
            secondary
            :loading="store.historyLoading"
            @click="loadMore"
          >加载更多</n-button>
        </div>
      </n-spin>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.drawer-intro { margin: 0 0 18px; color: var(--muted, #786e60); font-size: 12px; line-height: 1.8; }
.history-list { display: grid; gap: 14px; }
.history-card { padding: 18px; border: 1px solid var(--rule, #d9ccb7); border-radius: 10px; color: var(--ink, #302b24); background: var(--paper, #fffdf7); }
.history-card header, .history-card footer { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.history-card header span { color: var(--cinnabar, #9c3d2f); font: 700 11px Georgia, serif; letter-spacing: .15em; }
.history-card h3 { margin: 3px 0 0; color: var(--ink, #302b24); font-family: Georgia, serif; font-size: 24px; }
.superseded-reasons { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 12px; }
.superseded-reasons span { padding: 4px 7px; border-radius: 999px; color: var(--cinnabar, #8a4b3f); background: color-mix(in srgb, var(--cinnabar, #8a4b3f) 10%, var(--paper, #fffdf7)); font-size: 11px; }
.history-facts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin: 16px 0; }
.history-facts div { min-width: 0; padding: 10px; background: color-mix(in srgb, var(--paper, #fffdf7) 90%, var(--jade, #47675a)); }
.history-facts dt { color: var(--muted, #93836e); font-size: 11px; }
.history-facts dd { overflow: hidden; margin: 3px 0 0; font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.pinned-identities { display: grid; gap: 8px; padding-top: 13px; border-top: 1px solid var(--rule, #e2d7c5); }
.pinned-identities > h4 { margin: 0 0 2px; font-family: 'Noto Serif SC', serif; font-size: 13px; }
.identity-card { padding: 11px; border: 1px solid var(--rule, #e3d8c7); border-radius: 7px; background: var(--paper, #faf6ed); }
.identity-card > strong, .identity-card header strong { color: var(--ink, #574c3e); font-size: 12px; }
.identity-card > p, .fragment-identities p { margin: 5px 0 0; color: var(--muted, #776c5e); font-size: 12px; line-height: 1.55; overflow-wrap: anywhere; }
.identity-card code, .identity-card dd { overflow-wrap: anywhere; word-break: break-all; }
.identity-card code { display: block; margin-top: 5px; color: var(--muted, #765c43); font: 11px/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; }
.identity-card dl { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 7px; margin: 8px 0 0; }
.identity-card dl div { min-width: 0; }
.identity-card dl .identity-hash { grid-column: 1 / -1; }
.identity-card dt { color: var(--muted, #93836e); font-size: 11px; }
.identity-card dd { margin: 2px 0 0; font-size: 12px; }
.corpus-identity > header { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.fragment-identities { margin-top: 10px; padding-top: 9px; border-top: 1px dashed var(--rule, #ded2bf); }
.fragment-identities h5 { margin: 0 0 6px; color: var(--ink, #6d6255); font-size: 12px; }
.fragment-identities article { display: grid; gap: 3px; padding: 7px 0; border-top: 1px solid var(--rule, #eadfce); }
.fragment-identities article:first-of-type { border-top: 0; }
.fragment-identities small { color: var(--muted, #8b725c); font-size: 11px; }
.history-card footer { align-items: flex-end; margin-top: 16px; }
.history-card footer small { color: var(--muted, #927568); font-size: 11px; }
.history-load-more { margin-top: 2px; color: var(--jade, #47675a); }
@media (max-width: 520px) { .history-facts { grid-template-columns: 1fr; } .history-card footer { align-items: stretch; flex-direction: column; } }
</style>
