import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('frontend/src/api/db/client.js', 'utf8')

assert.match(
  source,
  /import\.meta\.env\.VITE_API_BASE_URL/,
  'frontend db client should allow configuring API base URL for non-default dev ports'
)

assert.match(
  source,
  /http:\/\/127\.0\.0\.1:8000\/api/,
  'frontend db client should default to 127.0.0.1:8000 instead of localhost'
)

assert.doesNotMatch(
  source,
  /const BASE = 'http:\/\/localhost:8000\/api'/,
  'frontend db client should not hard-code localhost API base'
)

assert.match(
  source,
  /\.replace\(\s*\/\\\/\+\$\/,\s*''\s*\)/,
  'frontend db client should trim trailing slashes from configured API base'
)

console.log('FRONTEND_API_BASE_CONTRACT_OK')
