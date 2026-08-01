import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import test from 'node:test'
import { parse as parseTemplate } from '@vue/compiler-dom'

const source = relativePath => readFile(
  new URL(`../../src/${relativePath}`, import.meta.url),
  'utf8',
)
function hasPersistentOutlineLink(node, conditional = false) {
  if (!node || typeof node !== 'object') return false
  const nextConditional = conditional || (
    node.type === 1
    && node.props?.some(prop => (
      prop.type === 7 && ['if', 'else-if', 'else'].includes(prop.name)
    ))
  )
  if (
    node.type === 1
    && node.tag === 'router-link'
    && !nextConditional
    && node.props?.some(prop => (
      prop.type === 7
      && prop.name === 'bind'
      && prop.arg?.content === 'to'
      && prop.exp?.content === 'storyBlocksPath'
    ))
    && node.children?.some(child => (
      child.type === 2 && child.content.includes('调整本章小纲')
    ))
  ) return true
  return (node.children || []).some(child => (
    hasPersistentOutlineLink(child, nextConditional)
  ))
}

test('one project planning view hosts all three canonical tabs and the shared workspace', async () => {
  const [view, workspace, storyBlocks] = await Promise.all([
    source('views/ProjectPlanningView.vue'),
    source('components/planning/PlanningWorkspace.vue'),
    source('components/planning/StoryBlockEditor.vue'),
  ])

  assert.match(view, /ProjectPlanningVolumes/)
  assert.match(view, /ProjectPlanningPlots/)
  assert.match(view, /ProjectPlanningStoryBlocks/)
  assert.match(view, /<planning-workspace/)
  assert.match(view, /planningVolumesPath/)
  assert.match(view, /planningPlotsPath/)
  assert.match(view, /planningStoryBlocksPath/)
  assert.match(view, />\s*故事块\s*</)
  assert.match(workspace, /<volume-editor/)
  assert.match(workspace, /<plot-editor/)
  assert.match(workspace, /<story-block-editor/)
  assert.match(workspace, /activeTab === 'story-blocks'/)
  assert.match(workspace, /<planning-history-drawer/)
  assert.match(workspace, /只读流式模式/)
  assert.match(workspace, /完整规划摘要/)
  assert.match(workspace, /v-for="block in planningContent\.storyBlocks"/)
  assert.match(workspace, /stage\.sceneTasks/)
  assert.match(workspace, /createModalFocusManager/)
  assert.match(workspace, /trapTab/)
  assert.doesNotMatch(`${view}\n${workspace}\n${storyBlocks}`, /outlines|useStoryBlockStore/)
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
  assert.match(
    view,
    /onBeforeRouteLeave\(to => controller\.requestRouteLeave\(to\)\)/,
  )
  assert.match(
    view,
    /onBeforeRouteUpdate\(to => controller\.requestRouteLeave\(to\)\)/,
  )
  assert.doesNotMatch(view, /sameProjectPlanningRoute|requestPlanningRouteLeave/)
  assert.doesNotMatch(
    view,
    /useVolumeStore|usePlotStore|useStoryBlockStore|PlanningWorkspaceV2/,
  )
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

test('writer keeps the outline router link visible while the workspace loads', async () => {
  const writer = await source('views/ChapterWriterView.vue')
  const template = writer.match(/<template>([\s\S]*)<\/template>/u)?.[1]
  const ast = parseTemplate(template || '')

  assert.equal(hasPersistentOutlineLink(ast), true)
})

test('writer renders candidate basis statuses without location navigation', async () => {
  const writer = await source('views/ChapterWriterView.vue')

  assert.match(writer, /candidate\.basisStatus === 'current'/)
  assert.match(writer, /依据当前小纲/)
  assert.match(writer, /依据旧小纲，不能定稿/)
  assert.doesNotMatch(writer, /window\.location|page\.evaluate/)
})

test('planning editors expose only their owned fields and no reverse IDs', async () => {
  const [volume, plot, storyBlock] = await Promise.all([
    source('components/planning/VolumeEditor.vue'),
    source('components/planning/PlotEditor.vue'),
    source('components/planning/StoryBlockEditor.vue'),
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

  for (const field of [
    'title', 'volumeRef', 'plotRefs', 'entrySituation', 'blockGoal',
    'mainPressure', 'expectedChange', 'openQuestions', 'involvedCharacters',
    'purpose', 'dramaticQuestion', 'task', 'completionEvidence',
  ]) {
    assert.match(storyBlock, new RegExp(field))
  }
  assert.doesNotMatch(
    storyBlock,
    /targetChapterCount|completed|actualProgress|volumeId|plotIds|storyBlockId|stageId/,
  )
  assert.match(storyBlock, /emit\('add'/)
  assert.match(storyBlock, /emit\('remove'/)
  assert.match(storyBlock, /emit\('move'/)
  assert.match(storyBlock, /emit\('select'/)
  assert.match(storyBlock, /emit\('undo'/)
  assert.match(storyBlock, /emit\('add-stage'/)
  assert.match(storyBlock, /emit\('add-scene-task'/)
})
