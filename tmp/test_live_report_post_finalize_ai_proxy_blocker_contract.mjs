import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(
  liveScript,
  /post_finalize_ai_proxy_failed/,
  'live report must classify post-finalize AI proxy failures explicitly'
)
assert.match(
  liveScript,
  /promotePostFinalizeAiProxyFailureFromConsole/,
  'browser console AI proxy failures must be promoted before writing report'
)
assert.match(
  liveScript,
  /后端 AI 代理请求失败[\s\S]*502[\s\S]*memory_auditModelId/,
  'live report blocker classifier must recognize memory_auditModelId 502 errors'
)
assert.match(
  liveScript,
  /postFinalizeFailed/,
  'chapterReports must carry postFinalizeFailed state'
)
assert.match(
  liveScript,
  /report\.acceptance\.reason\s*=\s*report\.blocker\.message/,
  'promoted post-finalize blocker must populate acceptance.reason'
)

console.log('live report post-finalize AI proxy blocker contract passed')
