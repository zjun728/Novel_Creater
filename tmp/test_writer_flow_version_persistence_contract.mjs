import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStoreSource = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const writerViewSource = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const fusionPanelSource = readFileSync('frontend/src/components/writer/FusionPanel.vue', 'utf8')

assert.match(
  writerStoreSource,
  /async function createVersion\s*\(\s*projectId\s*,\s*chapterId\s*,\s*chapterNum\s*,\s*data\s*\)/,
  'writerStore createVersion signature should remain explicit: projectId, chapterId, chapterNum, data'
)

assert.match(
  writerStoreSource,
  /api\.versions\.create\(projectId,\s*chapterId,\s*{\s*title:\s*data\.title\s*\|\|\s*''/,
  'writerStore createVersion should normalize payload before API persistence'
)

assert.match(
  writerViewSource,
  /@\/application\/writer-flow\/version-creation-command/,
  'WriterView manual save should use the object-shaped version creation command'
)

assert.match(
  fusionPanelSource,
  /@\/application\/writer-flow\/version-creation-command/,
  'FusionPanel should use the object-shaped version creation command'
)

assert.match(
  writerViewSource,
  /runCreateVersionCommand\(\s*{[\s\S]*chapterNum:\s*chapterNum\.value[\s\S]*createVersion:\s*writerStore\.createVersion/,
  'WriterView should pass chapterNum through object-shaped command input'
)

assert.match(
  fusionPanelSource,
  /runCreateVersionCommand\(\s*{[\s\S]*chapterNum:\s*props\.chapterNum[\s\S]*createVersion:\s*writerStore\.createVersion/,
  'FusionPanel should pass props.chapterNum through object-shaped command input'
)

assert.doesNotMatch(
  writerViewSource,
  /writerStore\.createVersion\(/,
  'WriterView should not directly call positional createVersion'
)

assert.doesNotMatch(
  fusionPanelSource,
  /writerStore\.createVersion\(/,
  'FusionPanel should not directly call positional createVersion'
)

console.log('writer flow version persistence contract passed')
