import assert from 'node:assert/strict'
import test from 'node:test'
import { createPlanningContinuation } from '../../src/application/planning/planningContinuation.js'

test('confirmed planning uses authoritative chapter and workbench mapping, never a fixed chapter', async () => {
  const paths = []
  const action = createPlanningContinuation({ projectId: () => 'p', loadPreparation: async () => ({ lifecycle: 'active', nextAction: 'prepare_chapter_outline', authoritativeChapterNumber: 7, targetPath: '/projects/p/planning/outlines' }), navigate: path => paths.push(path) })
  await action.proceed()
  assert.deepEqual(paths, ['/projects/p/workbench/chapters/7'])
})
test('pending synchronization and read failure never navigate or repeat confirmation', async () => {
  const paths = []
  const action = createPlanningContinuation({ projectId: () => 'p', loadPreparation: async () => ({ lifecycle: 'active', nextAction: 'prepare_chapter_outline', targetPath: '/projects/p/planning/outlines', reasons: ['canon_projection_unsynchronized'] }), navigate: path => paths.push(path) })
  assert.equal(await action.proceed(), false)
  assert.match(action.message.value, /同步/)
  assert.deepEqual(paths, [])
  const failed = createPlanningContinuation({ projectId: () => 'p', loadPreparation: async () => { throw Error('offline') }, navigate: path => paths.push(path) })
  await failed.proceed()
  assert.match(failed.message.value, /无需重复确认/)
})
test('late response after project change does not redirect the new project', async () => {
  let project = 'a', resolve
  const paths = [], response = new Promise(done => { resolve = done })
  const action = createPlanningContinuation({ projectId: () => project, loadPreparation: () => response, navigate: path => paths.push(path) })
  const pending = action.proceed()
  project = 'b'; action.reset()
  resolve({ lifecycle: 'active', nextAction: 'prepare_chapter_outline', authoritativeChapterNumber: 1, targetPath: '/projects/a/planning/outlines' })
  assert.equal(await pending, false)
  assert.deepEqual(paths, [])
  assert.equal(action.pending.value, false)
})
test('a mismatched preparation destination cannot open another project', async () => {
  const paths = []
  const action = createPlanningContinuation({ projectId: () => 'a', loadPreparation: async () => ({ lifecycle: 'active', nextAction: 'continue_planning', targetPath: '/projects/b/planning/volumes' }), navigate: path => paths.push(path) })
  assert.equal(await action.proceed(), false)
  assert.deepEqual(paths, [])
  assert.match(action.message.value, /不匹配/)
})
