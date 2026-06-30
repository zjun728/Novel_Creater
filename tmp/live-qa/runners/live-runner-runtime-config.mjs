function cleanText(value = '') {
  return String(value || '').trim()
}

function truthyFlag(value) {
  return /^(1|true|yes|y|on)$/i.test(cleanText(value))
}

function runtimeConfigError(code, message, details = {}) {
  const error = new Error(`${code}: ${message}`)
  error.code = code
  error.details = details
  return error
}

export function parsePositiveInt(value, fallback) {
  const text = cleanText(value)
  if (!text) return fallback
  const parsed = Number(text)
  if (!Number.isInteger(parsed) || parsed < 1) return fallback
  return parsed
}

export function parseChapterList(value = '') {
  return [...new Set(
    String(value || '')
      .split(',')
      .map(item => Number(cleanText(item)))
      .filter(item => Number.isInteger(item) && item > 0)
  )].sort((a, b) => a - b)
}

export function validateLiveRunnerRuntimeConfig(config = {}) {
  if (!config.existingProjectId && config.startChapter > 1) {
    throw runtimeConfigError('resumeRequiresExistingProject', 'resumed live runs require EXISTING_PROJECT_ID', {
      startChapter: config.startChapter
    })
  }
  if (!config.existingProjectId && !config.allowCreateCleanProject) {
    throw runtimeConfigError('cleanProjectCreationNotAllowed', 'creating a clean longform project requires ALLOW_CREATE_CLEAN_PROJECT=1')
  }
  if (config.phaseTarget < config.startChapter || config.phaseTarget > config.maxPhaseTarget) {
    throw runtimeConfigError('phaseTargetOutOfRange', 'phaseTarget must be within startChapter and maxPhaseTarget', {
      startChapter: config.startChapter,
      phaseTarget: config.phaseTarget,
      maxPhaseTarget: config.maxPhaseTarget
    })
  }
  if (config.runChapterCount !== config.phaseTarget - config.startChapter + 1) {
    throw runtimeConfigError('runChapterCountMismatch', 'runChapterCount must match phaseTarget - startChapter + 1', {
      runChapterCount: config.runChapterCount,
      expectedRunChapterCount: config.phaseTarget - config.startChapter + 1
    })
  }
  return config
}

export function buildLiveRunnerRuntimeConfig({
  env = {},
  defaults = {}
} = {}) {
  const existingProjectId = cleanText(env.EXISTING_PROJECT_ID)
  const existingProjectName = cleanText(env.EXISTING_PROJECT_NAME)
  const allowCreateCleanProject = truthyFlag(
    env.ALLOW_CREATE_CLEAN_PROJECT ??
    env.ALLOW_CREATE_LONGFORM_PROJECT ??
    env.CREATE_CLEAN_PROJECT
  )
  const createCleanProject = !existingProjectId && allowCreateCleanProject
  const startChapter = parsePositiveInt(env.START_CHAPTER, defaults.startChapter ?? 1)
  const resumeChapterWindow = parsePositiveInt(env.RESUME_CHAPTER_WINDOW, defaults.resumeChapterWindow ?? 5)
  const defaultPhaseTarget = parsePositiveInt(env.DEFAULT_PHASE_TARGET, defaults.defaultPhaseTarget ?? 20)
  const maxPhaseTarget = startChapter > 1
    ? startChapter + resumeChapterWindow - 1
    : defaultPhaseTarget
  const requestedPhaseTarget = parsePositiveInt(env.PHASE_TARGET, defaultPhaseTarget)
  const phaseTarget = Math.min(maxPhaseTarget, Math.max(startChapter, requestedPhaseTarget))
  const runChapterCount = phaseTarget - startChapter + 1
  const envForbiddenChapters = parseChapterList(env.FREEZE_FORBIDDEN_CHAPTERS)
  const autoForbiddenNextChapter = phaseTarget + 1
  const forbiddenChapters = [...new Set([
    ...envForbiddenChapters,
    autoForbiddenNextChapter
  ])].sort((a, b) => a - b)
  const expectedProviderId = cleanText(env.EXPECTED_PROVIDER_ID)

  return validateLiveRunnerRuntimeConfig({
    existingProjectId,
    existingProjectName,
    allowCreateCleanProject,
    createCleanProject,
    startChapter,
    resumeChapterWindow,
    defaultPhaseTarget,
    maxPhaseTarget,
    phaseTarget,
    runChapterCount,
    forbiddenChapters,
    envForbiddenChapters,
    autoForbiddenNextChapter,
    expectedProviderId
  })
}
