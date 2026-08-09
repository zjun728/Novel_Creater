import { useOperationStore } from '../stores/operationStore.js'

export function createBeforeUnloadManager(
  getWindow = () => (typeof window === 'undefined' ? null : window),
) {
  let listening = false
  const handleBeforeUnload = event => {
    event.preventDefault()
    event.returnValue = ''
    return ''
  }

  function setBlocking(nextBlocking) {
    const target = getWindow()
    const next = Boolean(nextBlocking)
    if (!target || next === listening) return
    listening = next
    if (next) target.addEventListener('beforeunload', handleBeforeUnload)
    else target.removeEventListener('beforeunload', handleBeforeUnload)
  }

  function dispose() {
    setBlocking(false)
  }

  return { setBlocking, dispose }
}

export function createOperationNavigationGuard(
  getOperationStore = () => useOperationStore(),
) {
  return function operationNavigationGuard() {
    return getOperationStore().blocking ? false : true
  }
}

export function installOperationNavigationGuard(
  router,
  getOperationStore = () => useOperationStore(),
) {
  return router.beforeEach(createOperationNavigationGuard(getOperationStore))
}
