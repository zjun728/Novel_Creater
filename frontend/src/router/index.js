import { createRouter, createWebHistory } from 'vue-router'

import { installOperationNavigationGuard } from './operationNavigationGuard.js'
import { projectRoutes } from './projectRoutes.js'

const router = createRouter({
  history: createWebHistory(),
  routes: projectRoutes,
})

installOperationNavigationGuard(router)

export default router
