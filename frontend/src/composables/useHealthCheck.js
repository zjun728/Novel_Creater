import { ref } from 'vue'
import { api } from '@/api/db/client'

const backendOnline = ref(true)
const lastCheck = ref(null)
const checking = ref(false)

let checkTimer = null

export function useHealthCheck() {
  async function check() {
    checking.value = true
    try {
      await api.health()
      backendOnline.value = true
    } catch {
      backendOnline.value = false
    } finally {
      lastCheck.value = Date.now()
      checking.value = false
    }
  }

  function startPeriodic(intervalMs = 60000) {
    stopPeriodic()
    check()
    checkTimer = setInterval(check, intervalMs)
  }

  function stopPeriodic() {
    if (checkTimer) {
      clearInterval(checkTimer)
      checkTimer = null
    }
  }

  return {
    backendOnline,
    lastCheck,
    checking,
    check,
    startPeriodic,
    stopPeriodic
  }
}
