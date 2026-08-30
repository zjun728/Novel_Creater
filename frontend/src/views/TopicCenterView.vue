<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'

import MarketDiscoveryPanel from '@/components/topics/MarketDiscoveryPanel.vue'
import TopicCandidatesPanel from '@/components/topics/TopicCandidatesPanel.vue'
import TopicCenterHeader from '@/components/topics/TopicCenterHeader.vue'
import TopicDirectionsPanel from '@/components/topics/TopicDirectionsPanel.vue'
import TopicDiscussionPanel from '@/components/topics/TopicDiscussionPanel.vue'
import { topicDiscussionsPath } from '@/router/projectRoutes'
import { useMarketSourceStore } from '@/stores/marketSourceStore'
import { useTopicCenterStore } from '@/stores/topicCenterStore'

const props = defineProps({ activeSection: { type: String, required: true } })
const router = useRouter()
const market = useMarketSourceStore()
const topics = useTopicCenterStore()
const selectedEvidence = ref([])
const discussionSubject = ref(null)
const pageError = ref('')

const identities = Object.freeze({
  market: 'MARKET DISCOVERY', discussions: 'IDEA CONVERSATION',
  directions: 'DIRECTION LIBRARY', candidates: 'CANDIDATE LIBRARY',
})

async function ensureDiscussion() {
  await topics.loadDiscussions()
  const first = topics.discussions[0]
  if (first && !topics.activeDiscussion) await topics.openDiscussion(first.id)
}

async function loadSection(section) {
  topics.leaveSection()
  pageError.value = ''
  try {
    if (section === 'market') {
      await Promise.all([market.loadSources(), ensureDiscussion(), topics.loadCandidates('active')])
    } else if (section === 'discussions') {
      await ensureDiscussion()
    } else if (section === 'directions') {
      await topics.loadDirections()
      if (topics.directions[0]) await topics.openDirection(topics.directions[0].id)
    } else if (section === 'candidates') {
      await topics.loadCandidates('active')
      if (topics.candidates[0]) await topics.openCandidate(topics.candidates[0].id)
    }
  } catch (failure) {
    pageError.value = failure?.message || '选题中心数据加载失败'
  }
}

function removeEvidence(snapshotId) {
  selectedEvidence.value = selectedEvidence.value.filter(item => item.snapshotId !== snapshotId)
}

async function continueDiscussion(subject) {
  discussionSubject.value = subject
  await router.push(topicDiscussionsPath())
}

watch(() => props.activeSection, loadSection, { immediate: true })
onBeforeUnmount(() => topics.leaveSection())
</script>

<template>
  <section class="topic-center" :data-page-identity="identities[activeSection]" aria-labelledby="topic-center-page-title">
    <h1 id="topic-center-page-title" class="visually-hidden">选题中心</h1>
    <TopicCenterHeader :active-section="activeSection" />
    <p v-if="pageError" class="page-error" role="alert" aria-live="assertive">{{ pageError }}</p>

    <div v-if="activeSection === 'market'" class="market-workspace">
      <MarketDiscoveryPanel v-model:selected-evidence="selectedEvidence" />
      <TopicDiscussionPanel :evidence="selectedEvidence" :subject="discussionSubject" compact @remove-evidence="removeEvidence" @clear-subject="discussionSubject = null" />
      <TopicCandidatesPanel class="market-candidates" compact @continue-discussion="continueDiscussion" />
    </div>
    <TopicDiscussionPanel v-else-if="activeSection === 'discussions'" :evidence="selectedEvidence" :subject="discussionSubject" @remove-evidence="removeEvidence" @clear-subject="discussionSubject = null" />
    <TopicDirectionsPanel v-else-if="activeSection === 'directions'" @continue-discussion="continueDiscussion" />
    <TopicCandidatesPanel v-else-if="activeSection === 'candidates'" @continue-discussion="continueDiscussion" />
  </section>
</template>

<style scoped>
.topic-center { min-width:0; min-height:100%; overflow-x:hidden; padding:clamp(24px,4vw,48px); color:#302923; background:radial-gradient(circle at 92% 2%,rgba(154,73,56,.08),transparent 27rem),linear-gradient(180deg,#fbf8f1 0%,#f4ecdf 100%); }
.topic-center>:not(:first-child){margin-top:24px}.market-workspace{display:grid;grid-template-columns:minmax(360px,.78fr) minmax(500px,1.22fr);gap:14px;min-width:0}.market-candidates{grid-column:1/-1}.page-error{padding:12px;border-left:3px solid #9a4938;color:#6c342b;background:#fff4ef}.visually-hidden{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}
@media(max-width:1080px){.market-workspace{grid-template-columns:1fr}}
@media(max-width:720px){.topic-center{padding:16px}.topic-center>:not(:first-child){margin-top:16px}.market-workspace{grid-template-columns:minmax(0,1fr)}}
@media(prefers-reduced-motion:reduce){.topic-center *{scroll-behavior:auto!important;transition-duration:.01ms!important}}
</style>
