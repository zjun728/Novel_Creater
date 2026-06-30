import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  buildLiveRunnerRuntimeConfig,
  parseChapterList,
  parsePositiveInt,
  validateLiveRunnerRuntimeConfig
} from './live-qa/runners/live-runner-runtime-config.mjs'

function assertConfigFails(input, code) {
  assert.throws(
    () => buildLiveRunnerRuntimeConfig(input),
    error => {
      assert.equal(error.code, code)
      return true
    }
  )
}

const resumeConfig = buildLiveRunnerRuntimeConfig({
  env: {
    EXISTING_PROJECT_ID: 'p1',
    EXISTING_PROJECT_NAME: 'Project One',
    START_CHAPTER: '88',
    PHASE_TARGET: '88',
    RESUME_CHAPTER_WINDOW: '1'
  }
})
assert.equal(resumeConfig.existingProjectId, 'p1')
assert.equal(resumeConfig.existingProjectName, 'Project One')
assert.equal(resumeConfig.createCleanProject, false)
assert.equal(resumeConfig.startChapter, 88)
assert.equal(resumeConfig.phaseTarget, 88)
assert.equal(resumeConfig.runChapterCount, 1)
assert.equal(resumeConfig.autoForbiddenNextChapter, 89)
assert.deepEqual(resumeConfig.forbiddenChapters, [89])

const mergedForbidden = buildLiveRunnerRuntimeConfig({
  env: {
    EXISTING_PROJECT_ID: 'p1',
    START_CHAPTER: '88',
    PHASE_TARGET: '88',
    RESUME_CHAPTER_WINDOW: '1',
    FREEZE_FORBIDDEN_CHAPTERS: '90, 89,foo,90'
  }
})
assert.deepEqual(mergedForbidden.envForbiddenChapters, [89, 90])
assert.deepEqual(mergedForbidden.forbiddenChapters, [89, 90])

const cappedConfig = buildLiveRunnerRuntimeConfig({
  env: {
    EXISTING_PROJECT_ID: 'p1',
    START_CHAPTER: '88',
    PHASE_TARGET: '95',
    RESUME_CHAPTER_WINDOW: '5'
  }
})
assert.equal(cappedConfig.maxPhaseTarget, 92)
assert.equal(cappedConfig.phaseTarget, 92)
assert.equal(cappedConfig.runChapterCount, 5)
assert.equal(cappedConfig.autoForbiddenNextChapter, 93)
assert.ok(cappedConfig.forbiddenChapters.includes(93))

assertConfigFails({ env: { START_CHAPTER: '1' } }, 'cleanProjectCreationNotAllowed')
assertConfigFails({
  env: {
    START_CHAPTER: '2',
    ALLOW_CREATE_CLEAN_PROJECT: '1'
  }
}, 'resumeRequiresExistingProject')

const createAllowed = buildLiveRunnerRuntimeConfig({
  env: {
    START_CHAPTER: '1',
    ALLOW_CREATE_CLEAN_PROJECT: '1'
  }
})
assert.equal(createAllowed.allowCreateCleanProject, true)
assert.equal(createAllowed.createCleanProject, true)
assert.equal(createAllowed.phaseTarget, 20)
assert.equal(createAllowed.runChapterCount, 20)
assert.equal(createAllowed.autoForbiddenNextChapter, 21)
assert.ok(createAllowed.forbiddenChapters.includes(21))

assert.equal(parsePositiveInt('', 7), 7)
assert.equal(parsePositiveInt('foo', 7), 7)
assert.equal(parsePositiveInt('-1', 7), 7)
assert.equal(parsePositiveInt('03', 7), 3)
assert.deepEqual(parseChapterList(' 90, 89,foo,90, ,0,-1'), [89, 90])
assert.equal(validateLiveRunnerRuntimeConfig(resumeConfig), resumeConfig)

const runnerSource = fs.readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
assert.match(runnerSource, /live-runner-runtime-config\.mjs/, 'runner should import runtime config module')
assert.match(runnerSource, /const runtimeConfig = buildLiveRunnerRuntimeConfig\(\{[\s\S]*?env:\s*process\.env[\s\S]*?\}\)/)
assert.match(runnerSource, /const EXISTING_PROJECT_ID = runtimeConfig\.existingProjectId/)
assert.match(runnerSource, /const EXISTING_PROJECT_NAME = runtimeConfig\.existingProjectName/)
assert.match(runnerSource, /const START_CHAPTER = runtimeConfig\.startChapter/)
assert.match(runnerSource, /const RESUME_CHAPTER_WINDOW = runtimeConfig\.resumeChapterWindow/)
assert.match(runnerSource, /const DEFAULT_PHASE_TARGET = runtimeConfig\.defaultPhaseTarget/)
assert.match(runnerSource, /const MAX_PHASE_TARGET = runtimeConfig\.maxPhaseTarget/)
assert.match(runnerSource, /const PHASE_TARGET = runtimeConfig\.phaseTarget/)
assert.match(runnerSource, /const RUN_CHAPTER_COUNT = runtimeConfig\.runChapterCount/)
assert.match(runnerSource, /const FREEZE_FORBIDDEN_CHAPTERS = runtimeConfig\.forbiddenChapters/)
assert.match(runnerSource, /const EXPECTED_PROVIDER_ID = runtimeConfig\.expectedProviderId/)
assert.match(runnerSource, /createdCleanProject:\s*runtimeConfig\.createCleanProject/)
assert.doesNotMatch(runnerSource, /createdCleanProject:\s*!EXISTING_PROJECT_ID/)
assert.doesNotMatch(runnerSource, /String\(process\.env\.EXISTING_PROJECT_ID/)
assert.doesNotMatch(runnerSource, /Number\(process\.env\.START_CHAPTER/)
assert.doesNotMatch(runnerSource, /String\(process\.env\.FREEZE_FORBIDDEN_CHAPTERS/)
assert.doesNotMatch(runnerSource, /live-service-manager|backend\/routers|domain\/chapter-title|chapter-title/i)

const moduleSource = fs.readFileSync('tmp/live-qa/runners/live-runner-runtime-config.mjs', 'utf8')
assert.doesNotMatch(
  moduleSource,
  /node:fs|node:path|process\.env|fetch\s*\(|api\s*\(|mysql|aiomysql|SELECT\s+|chromium|playwright|星债会|铁箱账本|东城染坊/i,
  'runtime config module must stay pure and project-agnostic'
)

console.log('live runner runtime config contract passed')
