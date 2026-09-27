import {
  onMounted,
  onServerPrefetch,
  onUnmounted,
  ref,
  shallowRef,
  watch,
} from 'vue'

import {
  corpusLibraryPath,
  experienceLibraryPath,
  projectLibraryPath,
  projectContractPath,
  projectBiblePath,
  projectContinuityPath,
  continuityIssuesPath,
  planningVolumesPath,
  planningPlotsPath,
  planningStoryBlocksPath,
  planningOutlinesPath,
  parsePositiveChapterNumber,
  manuscriptPath,
  projectModelSettingsPath,
  projectSettingsPath,
  projectExportPath,
  projectOverviewPath,
  projectSeedsPath,
  providerSettingsPath,
  styleLibraryPath,
  topicMarketPath,
} from '../../router/projectRoutes.js'

export const DESKTOP_SIDEBAR_BREAKPOINT = 1120
export const SHELL_PROJECT_CONTEXT = Symbol('shell-project-context')

export const GLOBAL_SHELL_DESTINATIONS = Object.freeze([
  Object.freeze({
    key: 'topics',
    label: '选题中心',
    path: topicMarketPath(),
    mark: '题',
  }),
  Object.freeze({
    key: 'projects',
    label: '项目库',
    path: projectLibraryPath(),
    mark: '库',
  }),
  Object.freeze({
    key: 'assets',
    label: '创作资产',
    path: styleLibraryPath(),
    mark: '创',
  }),
  Object.freeze({
    key: 'settings',
    label: '设置',
    path: providerSettingsPath(),
    mark: '设',
  }),
])

function routeName(route) {
  return String(route?.name || '')
}

function routeProjectId(route) {
  return String(route?.params?.projectId || '')
}

function isArchived(project) {
  return project?.archivedAt != null
}

function isMissingProject(error) {
  return Number(error?.status) === 404
    || ['ProjectNotFound', 'project_not_found', 'not_found'].includes(error?.code)
}

function routeTitle(route, project) {
  const name = routeName(route)
  if (name === 'ContinuityIssues') return isArchived(project) ? '已归档连续性问题' : '连续性问题'
  if (name === 'ProjectContinuity') return ({ settings: '设定库', 'state-memory': '当前状态与记忆', arcs: '人物弧光', clues: '线索与伏笔' }[route?.params?.section] || '世界与连续性')
  if (name === 'ProjectLibrary') return '项目库'
  if (name === 'TopicMarket') return '市场发现'
  if (name === 'TopicDiscussions') return '选题讨论'
  if (name === 'TopicDirections') return '方向库'
  if (name === 'TopicCandidates') return '候选种子库'
  if (name === 'ArchivedProjects') return '已归档项目'
  if (name === 'ProviderSettings') return '服务商与模型'
  if (name === 'ApplicationSettings') return '应用默认与诊断'
  if (name === 'StyleLibrary') return '风格模板库'
  if (name === 'ExperienceLibrary') return '经验卡库'
  if (name === 'CorpusLibrary') return '语料档案室'
  if (name === 'ProjectOverview') {
    return isArchived(project) ? '已归档项目' : '项目概览'
  }
  if (name === 'ProjectSeeds') {
    return isArchived(project) ? '已归档种子档案' : '创作种子'
  }
  if (name === 'ProjectContract') {
    return isArchived(project) ? '已归档创作契约' : '创作契约'
  }
  if (name === 'ProjectBible') {
    return isArchived(project) ? '已归档创作圣经' : '创作圣经'
  }
  if (name === 'ProjectPlanningVolumes') {
    return isArchived(project) ? '已归档分卷规划' : '分卷规划'
  }
  if (name === 'ProjectPlanningPlots') {
    return isArchived(project) ? '已归档情节线规划' : '情节线规划'
  }
  if (name === 'ProjectPlanningStoryBlocks') {
    return isArchived(project) ? '已归档故事块规划' : '故事块规划'
  }
  if (name === 'ProjectPlanningOutlines') return isArchived(project) ? '已归档章节小纲' : '章节小纲'
  if (name === 'ProjectModelSettings') {
    return isArchived(project) ? '已归档模型绑定' : '模型绑定'
  }
  if (name === 'ProjectSettings') {
    return isArchived(project) ? '已归档项目资料' : '项目资料'
  }
  if (name === 'ProjectExport') {
    return isArchived(project) ? '已归档项目导出与备份' : '导出与备份'
  }
  if (name === 'ProjectManuscript') return '作品稿件'
  if (name === 'FinalChapterReader') {
    try { return `第 ${parsePositiveChapterNumber(route?.params?.chapterNumber)} 章定稿` } catch { return '章节定稿' }
  }
  if (name === 'ChapterWriter') {
    try { return `第 ${parsePositiveChapterNumber(route?.params?.chapterNumber)} 章写作` } catch { return '写作台' }
  }
  if (name === 'ChapterWorkbench') {
    try { return `第 ${parsePositiveChapterNumber(route?.params?.chapterNumber)} 章工作台` } catch { return '章节工作台' }
  }
  if (name === 'NotFound' || name === 'NotFoundFallback') return '页面不存在'
  return String(route?.meta?.shellTitle || 'Novel Creator')
}

function globalSelected(item, route) {
  const name = routeName(route)
  if (item.key === 'topics') return name.startsWith('Topic')
  if (item.key === 'assets') {
    return ['StyleLibrary', 'ExperienceLibrary', 'CorpusLibrary'].includes(name)
  }
  if (item.key === 'settings') {
    return name === 'ProviderSettings' || name === 'ApplicationSettings'
  }
  return name === 'ProjectLibrary' || name === 'ArchivedProjects'
}

export function createProductShellModel({
  route,
  project = null,
  viewportWidth = 1440,
} = {}) {
  const projectId = routeProjectId(route)
  const hasMatchingProject = Boolean(
    projectId
    && project?.id != null
    && String(project.id) === projectId,
  )
  const archived = hasMatchingProject && isArchived(project)
  const overviewPath = hasMatchingProject
    ? projectOverviewPath(project.id)
    : null
  let projectContext = null
  if (hasMatchingProject) {
    const section = (label, items) => ({ label, items })
    const item = (key, label, path, mark, routeNames) => ({
      key,
      label,
      path,
      mark,
      selected: routeNames.includes(routeName(route)),
    })
    const sections = [
      section('', [
        item('workbench', '工作台', `/projects/${encodeURIComponent(project.id)}/workbench`, '写', ['ChapterWorkbench', 'ChapterWriter', 'ProjectWorkbench']),
        item('overview', '项目概览', overviewPath, '概', ['ProjectOverview']),
        item('manuscript', '作品稿件', manuscriptPath(project.id), '稿', ['ProjectManuscript', 'FinalChapterReader']),
        item('planning', '故事规划', planningVolumesPath(project.id), '规', ['ProjectPlanningVolumes', 'ProjectPlanningPlots', 'ProjectPlanningStoryBlocks', 'ProjectPlanningOutlines']),
      ]),
      section('创作基础', [
        ...(!archived ? [
          item('seeds', '创作种子', projectSeedsPath(project.id), '种', ['ProjectSeeds']),
        ] : []),
        item('contract', '创作契约', projectContractPath(project.id), '契', ['ProjectContract']),
        item('bible', '创作圣经', projectBiblePath(project.id), '圣', ['ProjectBible']),
      ]),
      section('设定与连续性', [
        ...Object.entries({ settings: '设定库', 'state-memory': '当前状态与记忆', arcs: '人物弧光', clues: '线索与伏笔' }).map(([key, label]) => ({
          ...item(`continuity-${key}`, label, projectContinuityPath(project.id, key), '续', []),
          selected: routeName(route) === 'ProjectContinuity' && route?.params?.section === key,
        })),
        item('continuity-issues', '连续性问题', continuityIssuesPath(project.id), '问', ['ContinuityIssues']),
      ]),
      section('项目设置', [
        item('project-settings', '项目资料', projectSettingsPath(project.id), '资', ['ProjectSettings']),
        ...(!archived ? [
          item('models', '模型绑定', projectModelSettingsPath(project.id), '模', ['ProjectModelSettings']),
        ] : []),
        item('export', '导出与备份', projectExportPath(project.id), '存', ['ProjectExport']),
      ]),
    ]
    projectContext = {
        id: String(project.id),
        title: String(project.title || '未命名项目'),
        archived,
        statusLabel: archived ? '已归档' : '',
        sections,
        modules: sections.flatMap(group => group.items),
      }
  }

  const assetBreadcrumbs = routeName(route) === 'StyleLibrary'
    ? [
        { label: '创作资产', path: styleLibraryPath() },
        { label: '风格模板', path: styleLibraryPath() },
      ]
    : routeName(route) === 'ExperienceLibrary'
      ? [
          { label: '创作资产', path: styleLibraryPath() },
          { label: '经验卡', path: experienceLibraryPath() },
        ]
      : routeName(route) === 'CorpusLibrary'
        ? [
            { label: '创作资产', path: styleLibraryPath() },
            { label: '语料档案室', path: corpusLibraryPath() },
          ]
      : []
  const breadcrumbs = projectContext
    ? [
        { label: '项目库', path: projectLibraryPath() },
        { label: projectContext.title, path: overviewPath },
      ]
    : assetBreadcrumbs

  return {
    globalNavigation: GLOBAL_SHELL_DESTINATIONS.map(item => ({
      ...item,
      selected: globalSelected(item, route),
    })),
    assetNavigation: [
      {
        key: 'styles',
        label: '风格模板',
        path: styleLibraryPath(),
        selected: routeName(route) === 'StyleLibrary',
      },
      {
        key: 'experience',
        label: '经验卡',
        path: experienceLibraryPath(),
        selected: routeName(route) === 'ExperienceLibrary',
      },
      {
        key: 'corpus',
        label: '语料档案室',
        path: corpusLibraryPath(),
        selected: routeName(route) === 'CorpusLibrary',
      },
    ],
    projectContext,
    breadcrumbs,
    routeTitle: routeTitle(route, hasMatchingProject ? project : null),
    sidebarCollapsed: Number(viewportWidth) < DESKTOP_SIDEBAR_BREAKPOINT,
  }
}

export function useViewportWidth(defaultWidth = 1440) {
  const width = ref(defaultWidth)

  function update() {
    width.value = globalThis.window?.innerWidth ?? defaultWidth
  }

  onMounted(() => {
    update()
    globalThis.window?.addEventListener?.('resize', update, { passive: true })
  })
  onUnmounted(() => {
    globalThis.window?.removeEventListener?.('resize', update)
  })

  return width
}

export function useShellProjectHydration({ route, store }) {
  const state = ref('idle')
  const project = shallowRef(null)
  const error = shallowRef(null)
  let requestId = 0
  let pendingProjectId = ''
  let pending = null

  function hydrate({ force = false } = {}) {
    const projectId = routeProjectId(route)
    if (!projectId) {
      requestId += 1
      pendingProjectId = ''
      pending = null
      project.value = null
      error.value = null
      state.value = 'idle'
      return Promise.resolve(null)
    }
    if (
      !force
      &&
      store.currentProject?.id != null
      && String(store.currentProject.id) === projectId
    ) {
      project.value = store.currentProject
      error.value = null
      state.value = isArchived(store.currentProject) ? 'archived' : 'active'
      return Promise.resolve(store.currentProject)
    }
    if (pending && pendingProjectId === projectId) return pending

    const generation = ++requestId
    pendingProjectId = projectId
    state.value = 'loading'
    project.value = null
    error.value = null
    const request = Promise.resolve(store.loadProject(projectId))
      .then(loaded => {
        if (generation !== requestId) return loaded
        project.value = loaded
        state.value = isArchived(loaded) ? 'archived' : 'active'
        return loaded
      })
      .catch(failure => {
        if (generation !== requestId) return null
        if (isMissingProject(failure)) {
          error.value = null
          state.value = 'missing'
        } else {
          error.value = failure
          state.value = 'error'
        }
        return null
      })
      .finally(() => {
        if (pending === request) {
          pending = null
          pendingProjectId = ''
        }
      })
    pending = request
    return request
  }

  watch(
    () => routeProjectId(route),
    () => {
      void hydrate()
    },
    { immediate: true },
  )
  onServerPrefetch(hydrate)

  return {
    state,
    project,
    error,
    reload: hydrate,
  }
}
