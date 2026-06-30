import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Home',
    component: () => import('@/views/HomeView.vue')
  },
  {
    path: '/project/:id',
    name: 'Project',
    component: () => import('@/views/ProjectView.vue'),
    props: true
  },
  {
    path: '/writer/:projectId/:chapterNum?',
    name: 'Writer',
    component: () => import('@/views/WriterView.vue'),
    props: true
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('@/views/SettingsView.vue')
  },
  {
    path: '/experience-cards',
    name: 'ExperienceCards',
    component: () => import('@/views/ExperienceCardsView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
