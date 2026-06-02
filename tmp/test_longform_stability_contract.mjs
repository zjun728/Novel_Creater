import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'

const root = process.cwd()
const read = file => fs.readFileSync(path.join(root, file), 'utf8')

const extractionPrompt = read('frontend/src/prompts/extraction.js')
assert.match(extractionPrompt, /threadTags/, 'fact extraction prompt should request threadTags')
assert.match(extractionPrompt, /#主角身世线|#反派阴谋线|#关键道具线/, 'fact extraction prompt should include concrete thread tag examples')
assert.match(extractionPrompt, /relatedPlotThreads/, 'fact extraction prompt should keep relatedPlotThreads compatibility')

const memoryStore = read('frontend/src/stores/memoryStore.js')
assert.match(memoryStore, /threadTags/, 'memory normalization should accept threadTags from extraction JSON')
assert.match(memoryStore, /fact\.tags|tags/, 'memory normalization should accept generic tags from extraction JSON')
assert.match(memoryStore, /relatedPlotThreads/, 'memory normalization should continue storing tags in relatedPlotThreads')

const contextBuilder = read('frontend/src/utils/contextBuilder.js')
assert.match(contextBuilder, /summarizeThreadFacts/, 'writing context should summarize thread-chain facts')
assert.match(contextBuilder, /threadFacts/, 'writing context should inject threadFacts into prompt context')
assert.match(contextBuilder, /relatedPlotThreads/, 'thread fact selection should use relatedPlotThreads')

const stateLedger = read('frontend/src/utils/chapterStateLedger.js')
assert.match(stateLedger, /currentTime|timeline|dayIndex/, 'state ledger should track current time/timeline keys')
assert.match(stateLedger, /sceneLocation|knowledgeBoundary|knownTo|unknownTo/, 'state ledger should track location and knowledge-boundary keys')
assert.match(stateLedger, /时空硬约束|视角可知范围/, 'state ledger prompt should surface time/location/visibility constraints')

const correctionPatch = read('frontend/src/prompts/correctionPatch.js')
assert.match(correctionPatch, /contextBefore/, 'local correction patch prompt should request contextBefore')
assert.match(correctionPatch, /contextAfter/, 'local correction patch prompt should request contextAfter')
assert.match(correctionPatch, /滑窗|接缝|前后.{0,20}500/, 'local correction patch prompt should mention sliding-window seam checks')

const localPatch = read('frontend/src/utils/localRevisionPatch.js')
assert.match(localPatch, /contextBefore/, 'patch normalizer should preserve contextBefore')
assert.match(localPatch, /contextAfter/, 'patch normalizer should preserve contextAfter')

const outlinePrompt = read('frontend/src/prompts/outline.js')
assert.match(outlinePrompt, /buildRollingPlanReroutePrompt/, 'outline prompt should expose a reroute prompt builder')
assert.match(outlinePrompt, /每章定稿后|定稿后/, 'reroute prompt should be designed for after-finalization checks')
assert.match(outlinePrompt, /校验.*近景规划|近景规划.*校验/, 'reroute prompt should validate remaining near rolling plan')

const novelStore = read('frontend/src/stores/novelStore.js')
assert.match(novelStore, /buildRollingPlanReroutePrompt/, 'novel store should import reroute prompt builder')
assert.match(novelStore, /rerouteOutlineAfterFinalization/, 'novel store should expose after-finalization outline reroute action')

const writerView = read('frontend/src/views/WriterView.vue')
assert.match(writerView, /rerouteOutlineAfterFinalization/, 'writer finalization flow should refresh rolling outline after chapter finalization')

console.log('longform stability contract ok')
