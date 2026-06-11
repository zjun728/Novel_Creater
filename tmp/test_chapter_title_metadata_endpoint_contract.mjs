import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const chaptersRouter = readFileSync('backend/routers/chapters.py', 'utf8')
const apiClient = readFileSync('frontend/src/api/db/client.js', 'utf8')
const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')

assert.match(
  chaptersRouter,
  /class ChapterTitleUpdate\(BaseModel\):[\s\S]*title:\s*str\s*=\s*""/,
  'backend should expose a dedicated title-only payload model'
)

assert.match(
  chaptersRouter,
  /@router\.put\("\/projects\/\{pid\}\/chapters\/\{cid\}\/title"\)/,
  'backend should expose a dedicated chapter title update endpoint'
)

const titleEndpointStart = chaptersRouter.indexOf('@router.put("/projects/{pid}/chapters/{cid}/title")')
assert.ok(titleEndpointStart > -1, 'title endpoint should exist')
const titleEndpointBlock = chaptersRouter.slice(titleEndpointStart, chaptersRouter.indexOf('@router.', titleEndpointStart + 1))
assert.doesNotMatch(
  titleEndpointBlock,
  /_raise_if_finalized/,
  'title-only endpoint should not use the finalized chapter content lock'
)
assert.match(
  titleEndpointBlock,
  /UPDATE chapters SET title=%s, updated_at=%s WHERE project_id=%s AND id=%s/,
  'title-only endpoint should update only title metadata and timestamp'
)

assert.match(
  apiClient,
  /updateTitle:\s*\(projectId,\s*chapterId,\s*data\)\s*=>\s*put\(`\/projects\/\$\{projectId\}\/chapters\/\$\{chapterId\}\/title`,\s*data\)/,
  'API client should expose chapters.updateTitle'
)

assert.match(
  writerStore,
  /api\.chapters\.updateTitle\(projectId,\s*chapter\.id,\s*\{\s*title\s*\}\)/,
  'chapter title generation should use the title-only metadata endpoint'
)

console.log('chapter title metadata endpoint contract passed')
