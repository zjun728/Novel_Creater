import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '../api/db/client.js'
import { parseAssistantResult, parseHandoff } from '../application/topics/topicContracts.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'


export function createTopicCenterStore(topicApi = api.topics, storeId = 'topic-center') {
  return defineStore(storeId, () => {
    const discussions = ref([])
    const directions = ref([])
    const candidates = ref([])
    const activeDiscussion = ref(null)
    const activeDirection = ref(null)
    const activeCandidate = ref(null)
    const loading = ref(false)
    const sending = ref(false)
    const handoffBusy = ref(false)
    const error = ref(null)
    const discussionListGuard = createLatestRequestGuard()
    const directionListGuard = createLatestRequestGuard()
    const candidateListGuard = createLatestRequestGuard()
    const discussionGuard = createLatestRequestGuard()
    const directionGuard = createLatestRequestGuard()
    const candidateGuard = createLatestRequestGuard()

    async function guardedList(guard, target, operation) {
      const generation = guard.begin()
      loading.value = true
      try {
        const rows = await operation()
        if (guard.isCurrent(generation)) target.value = Array.isArray(rows) ? rows : []
        return rows
      } catch (failure) {
        if (guard.isCurrent(generation)) error.value = failure
        throw failure
      } finally {
        if (guard.isCurrent(generation)) loading.value = false
      }
    }

    const loadDiscussions = () => guardedList(
      discussionListGuard, discussions, () => topicApi.listDiscussions(),
    )
    const loadDirections = () => guardedList(
      directionListGuard, directions, () => topicApi.listDirections(),
    )
    const loadCandidates = (status = 'active') => guardedList(
      candidateListGuard, candidates, () => topicApi.listCandidates(status),
    )

    async function openDiscussion(id) {
      const generation = discussionGuard.begin()
      const value = await topicApi.getDiscussion(id)
      if (discussionGuard.isCurrent(generation)) activeDiscussion.value = value
      return value
    }
    async function openDirection(id) {
      const generation = directionGuard.begin()
      const value = await topicApi.getDirection(id)
      if (directionGuard.isCurrent(generation)) activeDirection.value = value
      return value
    }
    async function openCandidate(id) {
      const generation = candidateGuard.begin()
      const value = await topicApi.getCandidate(id)
      if (candidateGuard.isCurrent(generation)) activeCandidate.value = value
      return value
    }

    async function createDiscussion(title) {
      const created = await topicApi.createDiscussion(title)
      discussions.value = [created, ...discussions.value.filter(item => item.id !== created.id)]
      return openDiscussion(created.id)
    }

    async function sendMessage(discussionId, data) {
      sending.value = true
      error.value = null
      try {
        const response = await topicApi.sendMessage(discussionId, data)
        const result = parseAssistantResult(response.result)
        await openDiscussion(discussionId)
        return { ...response, result }
      } catch (failure) {
        error.value = failure
        throw failure
      } finally {
        sending.value = false
      }
    }

    async function saveDirection(discussionId, data) {
      const value = await topicApi.saveDirection(discussionId, data)
      await loadDirections()
      return value
    }
    async function saveCandidate(discussionId, data) {
      const value = await topicApi.saveCandidate(discussionId, data)
      await loadCandidates()
      return value
    }
    async function archiveCandidate(candidateId, expectedVersion) {
      const value = await topicApi.archiveCandidate(candidateId, expectedVersion)
      candidates.value = candidates.value.filter(item => item.id !== candidateId)
      if (activeCandidate.value?.id === candidateId) activeCandidate.value = null
      return value
    }
    async function handoff(candidateId, version, data) {
      handoffBusy.value = true
      try {
        return parseHandoff(await topicApi.handoff(candidateId, version, data))
      } finally {
        handoffBusy.value = false
      }
    }

    function leaveSection() {
      discussionGuard.invalidate()
      directionGuard.invalidate()
      candidateGuard.invalidate()
    }

    return {
      discussions, directions, candidates, activeDiscussion, activeDirection,
      activeCandidate, loading, sending, handoffBusy, error,
      loadDiscussions, loadDirections, loadCandidates, openDiscussion,
      openDirection, openCandidate, createDiscussion, sendMessage,
      saveDirection, saveCandidate, archiveCandidate, handoff, leaveSection,
    }
  })
}

export const useTopicCenterStore = createTopicCenterStore()
