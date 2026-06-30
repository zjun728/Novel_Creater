import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

function loadVolumePlanApi() {
  const source = readFileSync('frontend/src/stores/volumeStore.js', 'utf8')
    .replace(/^import[\s\S]*?from\s+['"][^'"]+['"]\s*\n/gm, '')
    .replace(/export\s+const\s+/g, 'const ')
    .replace(/export\s+function\s+/g, 'function ')

  const sandbox = {
    console,
    defineStore: () => ({}),
    ref: value => ({ value })
  }
  vm.runInNewContext(`${source}
globalThis.__volumePlanApi = {
  parseVolumePlan,
  normalizeGeneratedVolumesWithDiagnostics,
  compactVolumePlanningDiagnostics
}`, sandbox)
  return sandbox.__volumePlanApi
}

const {
  parseVolumePlan,
  normalizeGeneratedVolumesWithDiagnostics,
  compactVolumePlanningDiagnostics
} = loadVolumePlanApi()

function makeVolume(index) {
  const startChapter = (index - 1) * 60 + 1
  return {
    volumeNum: index,
    title: `第${index}卷`,
    startChapter,
    endChapter: startChapter + 59,
    coreGoal: `第${index}卷目标：围绕星账推进主线`,
    mainConflict: `第${index}卷冲突：陆沉舟与追索者周旋`,
    summary: `第${index}卷摘要：完成一段清晰的追查与反击任务。`,
    keyCharacters: ['陆沉舟', '掌柜', '巡天司旧识'],
    unresolvedItems: ['星账代价', '父亲线索']
  }
}

const eightVolumePlan = {
  volumes: Array.from({ length: 8 }, (_, index) => makeVolume(index + 1)),
  planningNotes: {
    keyCharacters: ['陆沉舟', '掌柜', '巡天司旧识', '星债会信使'],
    unresolvedItems: ['星账代价', '父亲线索']
  }
}

{
  const diagnostics = {}
  const parsed = parseVolumePlan(JSON.stringify(eightVolumePlan), diagnostics)
  assert.equal(parsed?.volumes?.length, 8, 'top-level volumes must win over nested arrays')
  assert.equal(diagnostics.parsedCandidateSource, 'cleaned_json')
  assert.equal(diagnostics.parsedCandidateType, 'object_with_volumes')
  assert.equal(
    JSON.stringify(diagnostics.parsedFirstItemKeys.slice(0, 4)),
    JSON.stringify(['volumeNum', 'title', 'startChapter', 'endChapter'])
  )
  const normalized = normalizeGeneratedVolumesWithDiagnostics(parsed.volumes, {
    targetChapters: 480,
    targetWords: 2400000
  })
  assert.equal(normalized.volumes.length, 8, 'latest reduced sample should normalize to 8 volumes')
  assert.equal(normalized.droppedVolumes.length, 0)
}

{
  const diagnostics = {}
  const parsed = parseVolumePlan(JSON.stringify(['陆沉舟', '掌柜', '巡天司旧识', '星债会信使']), diagnostics)
  assert.equal(parsed, null, 'string arrays must not be accepted as volume plans')
  assert.ok(
    diagnostics.rejectedParsedCandidates.some(candidate =>
      ['array_items_not_volume_objects', 'nested_array_not_volume_plan'].includes(candidate.reason)
    ),
    'string arrays should be rejected with a shape reason'
  )
}

{
  const diagnostics = {}
  const text = `候选人物：["陆沉舟","掌柜","巡天司旧识","星债会信使"]\n真正分卷：${JSON.stringify(eightVolumePlan.volumes)}`
  const parsed = parseVolumePlan(text, diagnostics)
  assert.equal(parsed?.volumes?.length, 8, 'parser should skip the first balanced character array and keep looking')
  assert.ok(
    diagnostics.rejectedParsedCandidates.some(candidate => candidate.reason === 'nested_array_not_volume_plan'),
    'diagnostics should record skipped nested arrays'
  )
  assert.equal(diagnostics.parsedCandidateType, 'array')
  assert.equal(diagnostics.parsedFirstItemType, 'object')
}

{
  const diagnostics = compactVolumePlanningDiagnostics({
    parsedCandidateSource: 'balanced_candidate',
    parsedCandidateType: 'array',
    parsedFirstItemType: 'string',
    parsedFirstItemKeys: [],
    rejectedParsedCandidates: [{ source: 'balanced_candidate', reason: 'nested_array_not_volume_plan' }]
  })
  assert.equal(diagnostics.parsedCandidateSource, 'balanced_candidate')
  assert.equal(diagnostics.rejectedParsedCandidates[0].reason, 'nested_array_not_volume_plan')
}

console.log('volume plan parser shape contract tests passed')
