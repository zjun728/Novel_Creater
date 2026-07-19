<script setup>
import {
  NAlert,
  NButton,
  NDrawer,
  NDrawerContent,
  NSpin,
  NTag,
} from 'naive-ui'
import { computed } from 'vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  kind: { type: String, default: 'style' },
  detail: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['update:show', 'retry'])

const payload = computed(() => props.detail?.payload || {})
const title = computed(() => (
  props.detail?.name
  || props.detail?.title
  || (props.kind === 'style' ? '风格模板详情' : '经验卡详情')
))
const approvedExample = computed(() => (
  payload.value.approvedExample
  || payload.value.standardSceneExample
  || ''
))
const completeUseExample = computed(() => (
  payload.value.completeUseExample
  || payload.value.completeApplicationExample
  || ''
))
const positiveExample = computed(() => (
  payload.value.positiveExample
  || payload.value.originalMicroDemo
  || ''
))
const usage = computed(() => (
  payload.value.usage
  || payload.value.applicability
  || []
))
const negativeExamples = computed(() => (
  payload.value.negativeExamples
  || payload.value.nonApplicability
  || []
))

function close() {
  emit('update:show', false)
}
</script>

<template>
  <n-drawer
    :show="show"
    :width="720"
    placement="right"
    @update:show="value => emit('update:show', value)"
  >
    <n-drawer-content
      :title="kind === 'style' ? '风格模板详情' : '经验卡详情'"
      closable
    >
      <n-spin :show="loading">
        <n-alert v-if="error" type="error" class="drawer-state">
          {{ error }}
          <template #action>
            <n-button size="small" @click="emit('retry')">重试</n-button>
          </template>
        </n-alert>

        <article v-else-if="detail" class="asset-folio">
          <header class="folio-header">
            <div>
              <p>{{ detail.stableKey }} · revision {{ detail.revision }}</p>
              <h2>{{ title }}</h2>
            </div>
            <n-tag :bordered="false">只读</n-tag>
          </header>

          <template v-if="kind === 'style'">
            <section class="folio-section folio-section--lead">
              <span>APPROVED EXAMPLE · 批准示例</span>
              <p>{{ approvedExample }}</p>
            </section>
            <section v-if="completeUseExample" class="folio-section">
              <span>COMPLETE USE · 完整应用</span>
              <p>{{ completeUseExample }}</p>
            </section>
            <div class="boundary-grid">
              <section>
                <span>适用边界</span>
                <ul>
                  <li v-for="item in payload.applicability || []" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section>
                <span>不适用边界</span>
                <ul>
                  <li v-for="item in payload.nonApplicability || []" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section>
                <span>推荐写法</span>
                <ul>
                  <li v-for="item in payload.preferredTechniques || []" :key="item">{{ item }}</li>
                </ul>
              </section>
              <section>
                <span>常见风险</span>
                <ul>
                  <li v-for="item in payload.risks || []" :key="item">{{ item }}</li>
                </ul>
              </section>
            </div>
          </template>

          <template v-else>
            <section class="method-panel">
              <span>METHOD · 方法</span>
              <p>{{ payload.method }}</p>
            </section>
            <section class="folio-section folio-section--lead">
              <span>POSITIVE EXAMPLE · 正向示例</span>
              <p>{{ positiveExample }}</p>
            </section>
            <div class="boundary-grid">
              <section>
                <span>使用范围</span>
                <ul><li v-for="item in usage" :key="item">{{ item }}</li></ul>
              </section>
              <section>
                <span>反向示例 / 不适用</span>
                <ul><li v-for="item in negativeExamples" :key="item">{{ item }}</li></ul>
              </section>
              <section>
                <span>使用风险</span>
                <ul><li v-for="item in payload.risks || []" :key="item">{{ item }}</li></ul>
              </section>
            </div>
          </template>
        </article>

        <p v-else-if="!loading" class="drawer-placeholder">选择一项资产查看详情。</p>
      </n-spin>

      <template #footer>
        <n-button @click="close">关闭</n-button>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<style scoped>
.drawer-state { margin-bottom: 18px; }
.asset-folio { color: #312b24; }
.folio-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid #d9cebb;
}
.folio-header p,
.folio-section > span,
.method-panel > span,
.boundary-grid span {
  margin: 0;
  color: #8c6845;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .13em;
}
.folio-header h2 {
  margin: 6px 0 0;
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 28px;
  font-weight: 650;
}
.folio-section,
.method-panel {
  margin-top: 18px;
  padding: 20px;
  border: 1px solid #dfd4c2;
  background: #fffdf8;
}
.folio-section--lead {
  border-left: 4px solid #7e4036;
  background: #faf4e9;
}
.folio-section p,
.method-panel p {
  margin: 10px 0 0;
  color: #50483f;
  font-family: 'Noto Serif SC', 'Songti SC', Georgia, serif;
  font-size: 14px;
  line-height: 1.95;
  white-space: pre-wrap;
}
.method-panel {
  border-left: 4px solid #5f765e;
}
.method-panel p { font-family: inherit; }
.boundary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  margin-top: 18px;
  overflow: hidden;
  border: 1px solid #dfd4c2;
  background: #dfd4c2;
}
.boundary-grid section {
  min-height: 132px;
  padding: 17px;
  background: #fffdf8;
}
.boundary-grid ul {
  margin: 9px 0 0;
  padding-left: 18px;
  color: #655c50;
  font-size: 12px;
  line-height: 1.75;
}
.drawer-placeholder {
  padding: 48px 0;
  color: #827667;
  text-align: center;
}
@media (max-width: 620px) {
  .boundary-grid { grid-template-columns: 1fr; }
}
</style>
