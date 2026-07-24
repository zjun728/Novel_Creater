import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import test from 'node:test'

const source = relativePath => readFile(
  new URL(`../../src/${relativePath}`, import.meta.url),
  'utf8',
)

test('one project planning view hosts both canonical tabs and the shared workspace', async () => {
  const [view, workspace] = await Promise.all([
    source('views/ProjectPlanningView.vue'),
    source('components/planning/PlanningWorkspace.vue'),
  ])

  assert.match(view, /ProjectPlanningVolumes/)
  assert.match(view, /ProjectPlanningPlots/)
  assert.match(view, /<planning-workspace/)
  assert.match(view, /planningVolumesPath/)
  assert.match(view, /planningPlotsPath/)
  assert.match(workspace, /<volume-editor/)
  assert.match(workspace, /<plot-editor/)
  assert.match(workspace, /<planning-history-drawer/)
  assert.match(workspace, /只读流式模式/)
  assert.match(workspace, /完整规划摘要/)
  assert.match(workspace, /v-for="block in planningContent\.storyBlocks"/)
  assert.match(workspace, /stage\.sceneTasks/)
  assert.match(workspace, /createModalFocusManager/)
  assert.match(workspace, /trapTab/)
})

test('planning view owns one local aggregate and exact leave/load boundaries', async () => {
  const view = await source('views/ProjectPlanningView.vue')

  assert.match(view, /createPlanningWorkspaceController/)
  assert.match(view, /planningStore\.ensureLoaded/)
  assert.match(view, /onBeforeRouteLeave/)
  assert.match(view, /onBeforeRouteUpdate/)
  assert.match(view, /requestRouteLeave/)
  assert.match(view, /beforeunload/)
  assert.match(view, /useAppMessage/)
  assert.match(view, /message\.success/)
  assert.doesNotMatch(view, /useVolumeStore|usePlotStore|PlanningWorkspaceV2/)
})

test('history is immutable and retired duplicate planning surfaces stay absent', async () => {
  const history = await source('components/planning/PlanningHistoryDrawer.vue')

  assert.match(history, /只读/)
  assert.doesNotMatch(history, /@(?:click|input|change)[^>\n]*(?:clone|edit|save)/)
  assert.doesNotMatch(history, /emit\(['"](?:clone|edit|save)/)
  for (const retired of [
    'components/planning/PlanningWorkspaceV2.vue',
    'stores/volumeStore.js',
    'stores/plotStore.js',
  ]) {
    await assert.rejects(access(new URL(`../../src/${retired}`, import.meta.url)))
  }
})

test('planning editors expose only their owned fields and no reverse IDs', async () => {
  const [volume, plot] = await Promise.all([
    source('components/planning/VolumeEditor.vue'),
    source('components/planning/PlotEditor.vue'),
  ])

  for (const field of [
    'title', 'coreChange', 'mainPressure', 'ensembleFocus', 'forbiddenEvents',
  ]) {
    assert.match(volume, new RegExp(field))
  }
  assert.doesNotMatch(volume, /plotRefs|plotIds|storyBlock/i)

  for (const field of [
    'title', 'plotType', 'storyQuestion', 'futureDirection',
    'expectedPayoff', 'relatedCharacters',
  ]) {
    assert.match(plot, new RegExp(field))
  }
  for (const plotType of ['main', 'character', 'relationship', 'conflict', 'mystery', 'other']) {
    assert.match(plot, new RegExp(`value="${plotType}"`))
  }
  assert.doesNotMatch(plot, /value="(?:growth|world)"/)
  assert.doesNotMatch(plot, /storyBlock/i)
})
