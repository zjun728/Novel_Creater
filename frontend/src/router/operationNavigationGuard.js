import { useOperationStore } from '../stores/operationStore.js'

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
