<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'

import MarketDiscoveryPanel from '@/components/topics/MarketDiscoveryPanel.vue'
import TopicCandidatesPanel from '@/components/topics/TopicCandidatesPanel.vue'
import TopicCenterHeader from '@/components/topics/TopicCenterHeader.vue'
import TopicDirectionsPanel from '@/components/topics/TopicDirectionsPanel.vue'
import TopicDiscussionPanel from '@/components/topics/TopicDiscussionPanel.vue'
import TopicSuggestionStart from '@/components/topics/TopicSuggestionStart.vue'
import { enterTopicSubject } from '@/application/topics/topicContext'
import { topicDiscussionsPath } from '@/router/projectRoutes'
import { useMarketSourceStore } from '@/stores/marketSourceStore'
import { useTopicCenterStore } from '@/stores/topicCenterStore'

const props = defineProps({ activeSection: { type: String, required: true } })
const router = useRouter()
const route = useRoute()
const market = useMarketSourceStore()
const topics = useTopicCenterStore()
const { selectedEvidence, discussionSubject } = storeToRefs(topics)
const pageError = ref('')
const suggestionBusy = ref(false)
let sectionGeneration = 0

const identities = Object.freeze({
  market: 'MARKET DISCOVERY', discussions: 'IDEA CONVERSATION',
  directions: 'DIRECTION LIBRARY', candidates: 'CANDIDATE LIBRARY',
})

async function ensureDiscussion(generation) {
  await topics.loadDiscussions()
  if (generation !== sectionGeneration) return
  const first = topics.discussions[0]
  if (topics.activeDiscussion?.discussion?.id) await topics.openDiscussion(topics.activeDiscussion.discussion.id)
  else if (first && route.query.new !== '1') await topics.openDiscussion(first.id)
}

async function loadSection(section) {
  const generation = ++sectionGeneration
  topics.leaveSection()
  pageError.value = ''
  try {
    if (section === 'market') {
      await market.loadSources()
    } else if (section === 'discussions') {
      await ensureDiscussion(generation)
    } else if (section === 'directions') {
      await topics.loadDirections()
      if (generation !== sectionGeneration) return
      if (topics.directions[0]) await topics.openDirection(topics.directions[0].id)
    } else if (section === 'candidates') {
      await topics.loadCandidates('active')
      if (generation !== sectionGeneration) return
      if (!topics.activeCandidate && topics.candidates[0]) await topics.openCandidate(topics.candidates[0].id)
    }
  } catch (failure) {
    if (generation !== sectionGeneration) return
    pageError.value = failure?.message || '选题中心数据加载失败'
  }
}

function removeEvidence(snapshotId) {
  selectedEvidence.value = selectedEvidence.value.filter(item => item.snapshotId !== snapshotId)
}

async function continueDiscussion(subject) {
  pageError.value = ''
  try {
    await enterTopicSubject(topics, subject)
    await router.push(topicDiscussionsPath())
  } catch (failure) { pageError.value = failure.message || '来源讨论打开失败' }
}

watch(() => props.activeSection, loadSection, { immediate: true })
onBeforeUnmount(() => { sectionGeneration += 1; topics.leaveSection() })
</script>

<template>
  <section class="topic-center" :data-page-identity="identities[activeSection]" aria-labelledby="topic-center-page-title">
    <TopicCenterHeader :active-section="activeSection" />
    <p v-if="pageError" class="page-error" role="alert" aria-live="assertive">{{ pageError }}</p>

    <div v-if="activeSection === 'market'" class="market-workspace">
      <TopicSuggestionStart @busy="suggestionBusy = $event" />
      <details :inert="suggestionBusy"><summary>查看市场来源、榜单与采集时间</summary><MarketDiscoveryPanel class="market-discovery" v-model:selected-evidence="selectedEvidence" /></details>
    </div>
    <TopicDiscussionPanel v-else-if="activeSection === 'discussions'" :evidence="selectedEvidence" :subject="discussionSubject" @remove-evidence="removeEvidence" @clear-subject="discussionSubject = null" />
    <TopicDirectionsPanel v-else-if="activeSection === 'directions'" @continue-discussion="continueDiscussion" />
    <TopicCandidatesPanel v-else-if="activeSection === 'candidates'" @continue-discussion="continueDiscussion" />
  </section>
</template>

<style scoped>
.topic-center { min-width:0; min-height:100%; overflow-x:hidden; padding:20px 36px 100px; color:#302d28; background:#f5f2eb; }
.topic-center>:not(:first-child){margin-top:20px}.market-workspace{display:grid;grid-template-columns:minmax(0,1fr);gap:20px;min-width:0}.market-discovery,.market-candidates{grid-column:1/-1}.page-error{padding:12px;border-left:3px solid #9a4938;color:#6c342b;background:#fff4ef}.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
@media(max-width:1080px){.market-workspace{grid-template-columns:1fr}}
@media(max-width:720px){.topic-center{padding:16px}.topic-center>:not(:first-child){margin-top:16px}.market-workspace{grid-template-columns:minmax(0,1fr)}}
@media(prefers-reduced-motion:reduce){.topic-center *{scroll-behavior:auto!important;transition-duration:.01ms!important}}
@media(min-width:1120px) and (max-height:820px){.topic-center{padding-top:12px}.topic-center>:not(:first-child){margin-top:14px}}
</style>
