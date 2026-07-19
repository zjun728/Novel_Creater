import { defineStore } from 'pinia'
import { ref } from 'vue'

import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'


const PROVIDER_IDENTITY_FIELDS = Object.freeze([
  'id',
  'name',
  'providerType',
  'model',
  'ready',
])

const DIAGNOSTIC_FIELDS = Object.freeze([
  'schemaVersion',
  'schemaManifestMatch',
  'databaseReachable',
  'managedCorpusStoreReady',
  'schedulerEnabled',
  'schedulerState',
  'applicationVersion',
])


function publicProviderIdentity(value) {
  if (!value || typeof value !== 'object') return null
  return Object.fromEntries(
    PROVIDER_IDENTITY_FIELDS.map(field => [
      field,
      field === 'ready' ? value[field] === true : value[field],
    ]),
  )
}


function publicSettings(value = {}) {
  return {
    revision: Number(value.revision),
    fallbackProvider: publicProviderIdentity(value.fallbackProvider),
  }
}


function publicDiagnostics(value = {}) {
  return Object.fromEntries(
    DIAGNOSTIC_FIELDS.map(field => [
      field,
      field.endsWith('Match')
        || field.endsWith('Reachable')
        || field.endsWith('Ready')
        || field.endsWith('Enabled')
        ? value[field] === true
        : value[field],
    ]),
  )
}


export const useApplicationSettingsStore = defineStore(
  'application-settings',
  () => {
    const settings = ref(null)
    const diagnostics = ref(null)
    const loading = ref(false)
    const diagnosticsLoading = ref(false)
    const saving = ref(false)
    const settingsGuard = createLatestRequestGuard()
    const diagnosticsGuard = createLatestRequestGuard()

    async function loadSettings() {
      const generation = settingsGuard.begin()
      loading.value = true
      try {
        const result = publicSettings(await api.applicationSettings.get())
        if (settingsGuard.isCurrent(generation)) settings.value = result
        return result
      } finally {
        if (settingsGuard.isCurrent(generation)) loading.value = false
      }
    }

    async function updateFallback(fallbackProviderId) {
      if (!settings.value || saving.value) return null
      const expectedRevision = settings.value.revision
      saving.value = true
      try {
        const result = publicSettings(
          await api.applicationSettings.updateDefaultModel({
            expectedRevision,
            fallbackProviderId: fallbackProviderId ?? null,
          }),
        )
        settingsGuard.invalidate()
        settings.value = result
        loading.value = false
        return result
      } finally {
        saving.value = false
      }
    }

    async function loadDiagnostics() {
      const generation = diagnosticsGuard.begin()
      diagnosticsLoading.value = true
      try {
        const result = publicDiagnostics(
          await api.applicationSettings.diagnostics(),
        )
        if (diagnosticsGuard.isCurrent(generation)) diagnostics.value = result
        return result
      } finally {
        if (diagnosticsGuard.isCurrent(generation)) {
          diagnosticsLoading.value = false
        }
      }
    }

    return {
      settings,
      diagnostics,
      loading,
      diagnosticsLoading,
      saving,
      loadSettings,
      updateFallback,
      loadDiagnostics,
    }
  },
)
