const ProjectLibraryView = () => import('../views/ProjectLibraryView.vue')
const ArchivedProjectsView = () => import('../views/ArchivedProjectsView.vue')
const ProjectOverviewView = () => import('../views/ProjectOverviewView.vue')
const ChapterWriterView = () => import('../views/ChapterWriterView.vue')
const ProviderSettingsView = () => import('../views/ProviderSettingsView.vue')
const ApplicationSettingsView = () => import('../views/ApplicationSettingsView.vue')
const ProjectModelSettingsView = () => import('../views/ProjectModelSettingsView.vue')
const NotFoundView = () => import('../views/NotFoundView.vue')

const segment = value => encodeURIComponent(String(value))

export function projectLibraryPath() {
  return '/projects'
}

export function archivedProjectsPath() {
  return '/projects/archived'
}

export function providerSettingsPath() {
  return '/settings/providers'
}

export function applicationSettingsPath() {
  return '/settings/application'
}

function positiveChapterNumber(value) {
  const chapterNumber = Number(value)
  if (!Number.isInteger(chapterNumber) || chapterNumber < 1) {
    throw new TypeError('Expected a positive chapter number')
  }
  return chapterNumber
}

export function projectOverviewPath(projectId) {
  return `/projects/${segment(projectId)}/overview`
}

export function projectModelSettingsPath(projectId) {
  return `/projects/${segment(projectId)}/settings/models`
}

export function chapterWriterPath(projectId, chapterNumber) {
  return `/projects/${segment(projectId)}/write/chapters/${positiveChapterNumber(chapterNumber)}`
}

export const projectRoutes = Object.freeze([
  {
    path: '/',
    redirect: '/projects',
  },
  {
    path: '/projects',
    name: 'ProjectLibrary',
    component: ProjectLibraryView,
  },
  {
    path: '/projects/archived',
    name: 'ArchivedProjects',
    component: ArchivedProjectsView,
  },
  {
    path: '/projects/:projectId/overview',
    name: 'ProjectOverview',
    component: ProjectOverviewView,
    props: true,
  },
  {
    path: '/projects/:projectId/settings/models',
    name: 'ProjectModelSettings',
    component: ProjectModelSettingsView,
    props: true,
  },
  {
    path: '/projects/:projectId/write/chapters/:chapterNumber([1-9]\\d*)',
    name: 'ChapterWriter',
    component: ChapterWriterView,
    props: true,
  },
  {
    path: '/settings/providers',
    name: 'ProviderSettings',
    component: ProviderSettingsView,
  },
  {
    path: '/settings/application',
    name: 'ApplicationSettings',
    component: ApplicationSettingsView,
  },
  {
    path: '/not-found',
    name: 'NotFound',
    component: NotFoundView,
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFoundFallback',
    component: NotFoundView,
    meta: { notFound: true },
  },
])
