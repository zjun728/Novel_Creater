import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(liveScript, /aiProxyUsed/, 'live report should record whether backend AI proxy was used')
assert.match(liveScript, /browserConsoleCorsErrors/, 'live report should count browser CORS console errors')
assert.match(liveScript, /providerChatCompletionUrls/, 'live report should record any provider chat/completions URLs seen in browser network')
assert.match(liveScript, /\/api\/ai\/chat-completions/, 'live browser script should detect backend AI proxy requests')
assert.match(liveScript, /providerName/, 'live report should include providerName')
assert.match(liveScript, /modelName/, 'live report should include modelName')
assert.match(liveScript, /realRequestStages/, 'live report should record real request stages')
assert.match(liveScript, /Access-Control-Allow-Origin|CORS policy/, 'live script should classify CORS console errors')

console.log('AI_PROXY_LIVE_REPORT_CONTRACT_OK')
