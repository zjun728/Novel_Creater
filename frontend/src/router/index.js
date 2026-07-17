import { createRouter, createWebHistory } from 'vue-router'

import { projectRoutes } from './projectRoutes.js'

const router = createRouter({
  history: createWebHistory(),
  routes: projectRoutes,
})

export default router
