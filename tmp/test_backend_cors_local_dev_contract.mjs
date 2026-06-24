import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('backend/main.py', 'utf8')

assert.match(
  source,
  /allow_origin_regex\s*=\s*r["']http:\/\/\(localhost\|127\\\.0\\\.0\\\.1\):\\d\+["']/,
  'backend CORS should allow local Vite dev ports beyond 5173'
)

assert.match(
  source,
  /allow_origins=\[/,
  'backend CORS should keep explicit stable origins for normal local usage'
)

console.log('BACKEND_CORS_LOCAL_DEV_CONTRACT_OK')
