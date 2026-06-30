import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const client = readFileSync('frontend/src/api/db/client.js', 'utf8')
const novelStore = readFileSync('frontend/src/stores/novelStore.js', 'utf8')
const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')
const board = readFileSync('frontend/src/components/bible/PlotThreadBoard.vue', 'utf8')
const projectView = readFileSync('frontend/src/views/ProjectView.vue', 'utf8')

assert.match(
  client,
  /syncFromCanonFacts:\s*\(projectId\)\s*=>\s*post\(`\/projects\/\$\{projectId\}\/plot-threads\/sync-canon-facts`/,
  'frontend API should expose plot thread sync from Canon facts'
)

assert.match(
  novelStore,
  /async function syncPlotThreadsFromCanonFacts\(projectId\)/,
  'novel store should expose syncPlotThreadsFromCanonFacts(projectId)'
)

assert.match(
  novelStore,
  /saveCanonFact[\s\S]*status:\s*'accepted'[\s\S]*syncPlotThreadsFromCanonFacts\(pid\)/,
  'saving an accepted Canon fact should trigger plot thread sync'
)

assert.match(
  memoryStore,
  /processChapterFinalization[\s\S]*syncPlotThreadsFromCanonFacts\(projectId\)/,
  'post-finalize accepted Canon facts should trigger plot thread sync'
)

assert.match(
  board,
  /暂无伏笔数据/,
  'board should show the plain no-data empty state'
)

assert.match(
  board,
  /已有线索标签，尚未同步到伏笔看板/,
  'board should distinguish Canon tags that have not been synced'
)

assert.match(
  board,
  /@click="\$emit\('sync'\)"/,
  'board should provide a sync entry when Canon tags exist but plot threads are empty'
)

assert.match(
  projectView,
  /syncPlotThreadsFromCanonFacts/,
  'project view should wire the sync entry or auto-backfill hook'
)

console.log('plot thread sync frontend contract passed')
