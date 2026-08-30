const ProjectLibraryView = () => import('../views/ProjectLibraryView.vue')
const TopicCenterView = () => import('../views/TopicCenterView.vue')
const ArchivedProjectsView = () => import('../views/ArchivedProjectsView.vue')
const ProjectOverviewView = () => import('../views/ProjectOverviewView.vue')
const ProjectSeedsView = () => import('../views/ProjectSeedsView.vue')
const ProjectContractView = () => import('../views/ProjectContractView.vue')
const ProjectBibleView = () => import('../views/ProjectBibleView.vue')
const ProjectPlanningView = () => import('../views/ProjectPlanningView.vue')
const StyleLibraryView = () => import('../views/assets/StyleLibraryView.vue')
const ExperienceLibraryView = () => import('../views/assets/ExperienceLibraryView.vue')
const CorpusLibraryView = () => import('../views/assets/CorpusLibraryView.vue')
const ChapterWriterView = () => import('../views/ChapterWriterView.vue')
const ManuscriptIndexView = () => import('../views/ManuscriptIndexView.vue')
const FinalChapterReaderView = () => import('../views/FinalChapterReaderView.vue')
const ProviderSettingsView = () => import('../views/ProviderSettingsView.vue')
const ApplicationSettingsView = () => import('../views/ApplicationSettingsView.vue')
const ProjectModelSettingsView = () => import('../views/ProjectModelSettingsView.vue')
const ProjectExportView = () => import('../views/ProjectExportView.vue')
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

export function styleLibraryPath() {
  return '/assets/styles'
}

export function experienceLibraryPath() {
  return '/assets/experience'
}

export function corpusLibraryPath() {
  return '/assets/corpus'
}

export function topicMarketPath() { return '/topics/market' }
export function topicDiscussionsPath() { return '/topics/discussions' }
export function topicDirectionsPath() { return '/topics/directions' }
export function topicCandidatesPath() { return '/topics/candidates' }

export function parsePositiveChapterNumber(value) {
  if (typeof value === 'number' && Number.isSafeInteger(value) && value > 0) return value
  if (typeof value === 'string' && /^[1-9]\d*$/u.test(value)) {
    const chapterNumber = Number(value)
    if (Number.isSafeInteger(chapterNumber) && String(chapterNumber) === value) return chapterNumber
  }
  throw new TypeError('Expected a positive chapter number')
}

function positiveChapterNumber(value) {
  try { return parsePositiveChapterNumber(value) } catch {
    throw new TypeError('Expected a positive chapter number')
  }
}

export function projectOverviewPath(projectId) {
  return `/projects/${segment(projectId)}/overview`
}

export function projectSeedsPath(projectId) {
  return `/projects/${segment(projectId)}/seeds`
}

export function projectContractPath(projectId) {
  return `/projects/${segment(projectId)}/contract`
}

export function projectBiblePath(projectId) {
  return `/projects/${segment(projectId)}/bible`
}

export function planningVolumesPath(projectId) {
  return `/projects/${segment(projectId)}/planning/volumes`
}

export function planningPlotsPath(projectId) {
  return `/projects/${segment(projectId)}/planning/plots`
}

export function planningStoryBlocksPath(projectId) {
  return `/projects/${segment(projectId)}/planning/story-blocks`
}

export function projectModelSettingsPath(projectId) {
  return `/projects/${segment(projectId)}/settings/models`
}

export function projectExportPath(projectId) {
  return `/projects/${segment(projectId)}/settings/export`
}

export function chapterWriterPath(projectId, chapterNumber) {
  return `/projects/${segment(projectId)}/write/chapters/${positiveChapterNumber(chapterNumber)}`
}

export function manuscriptPath(projectId) {
  return `/projects/${segment(projectId)}/manuscript`
}

export function finalChapterPath(projectId, chapterNumber) {
  return `${manuscriptPath(projectId)}/chapters/${positiveChapterNumber(chapterNumber)}`
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
    path: '/topics/market',
    name: 'TopicMarket',
    component: TopicCenterView,
    props: { activeSection: 'market' },
  },
  {
    path: '/topics/discussions',
    name: 'TopicDiscussions',
    component: TopicCenterView,
    props: { activeSection: 'discussions' },
  },
  {
    path: '/topics/directions',
    name: 'TopicDirections',
    component: TopicCenterView,
    props: { activeSection: 'directions' },
  },
  {
    path: '/topics/candidates',
    name: 'TopicCandidates',
    component: TopicCenterView,
    props: { activeSection: 'candidates' },
  },
  {
    path: '/projects/archived',
    name: 'ArchivedProjects',
    component: ArchivedProjectsView,
  },
  {
    path: '/assets/styles',
    name: 'StyleLibrary',
    component: StyleLibraryView,
  },
  {
    path: '/assets/experience',
    name: 'ExperienceLibrary',
    component: ExperienceLibraryView,
  },
  {
    path: '/assets/corpus',
    name: 'CorpusLibrary',
    component: CorpusLibraryView,
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
    path: '/projects/:projectId/settings/export',
    name: 'ProjectExport',
    component: ProjectExportView,
    props: true,
  },
  {
    path: '/projects/:projectId/seeds',
    name: 'ProjectSeeds',
    component: ProjectSeedsView,
    props: true,
  },
  {
    path: '/projects/:projectId/contract',
    name: 'ProjectContract',
    component: ProjectContractView,
    props: true,
  },
  {
    path: '/projects/:projectId/bible',
    name: 'ProjectBible',
    component: ProjectBibleView,
    props: true,
  },
  {
    path: '/projects/:projectId/planning/volumes',
    name: 'ProjectPlanningVolumes',
    component: ProjectPlanningView,
    props: true,
  },
  {
    path: '/projects/:projectId/planning/plots',
    name: 'ProjectPlanningPlots',
    component: ProjectPlanningView,
    props: true,
  },
  {
    path: '/projects/:projectId/planning/story-blocks',
    name: 'ProjectPlanningStoryBlocks',
    component: ProjectPlanningView,
    props: { activeTab: 'story-blocks' },
  },
  {
    path: '/projects/:projectId/manuscript',
    name: 'ProjectManuscript',
    component: ManuscriptIndexView,
    props: true,
  },
  {
    path: '/projects/:projectId/manuscript/chapters/:chapterNumber([1-9]\\d*)',
    name: 'FinalChapterReader',
    component: FinalChapterReaderView,
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
