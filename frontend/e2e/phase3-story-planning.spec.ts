import { expect, test } from '@playwright/test'

import {
  assertExactWrites,
  assertNoPrivateEvidenceMarkers,
  assertRuntimeEvidenceHealthy,
  observeRuntime,
  publicRuntimeDiagnostic,
  runtimeFailureDiagnostic,
  runtimeSensitiveValues,
  scanRuntimeEvidence,
  settleNavigationBoundary,
} from './runtime-observer.mjs'
import { SYNTHETIC_STORY_ENGINE_OPTIONS } from './synthetic-story-engine-options.mjs'

const FOCUS = String(process.env.PHASE3_FOCUS_SCENARIO || '')
const SCENARIOS = [
  'foundation-manual-r1',
  'revision-outline-session',
  'outline-adjustment-before-finalization',
  'pinned-session',
  'baseline-lock',
  'archived-navigation',
]
if (!SCENARIOS.includes(FOCUS)) throw new Error('Phase 3 browser scenario is not configured')
let PROJECT_ID = ''

let allowedOrigins: string[]
try { allowedOrigins = JSON.parse(process.env.BROWSER_ALLOWED_ORIGINS || '') } catch { throw new Error('Phase 3 browser origins are not configured') }
if (!Array.isArray(allowedOrigins) || allowedOrigins.length !== 2) throw new Error('Phase 3 browser origins are not configured')

const overview = () => `/projects/${PROJECT_ID}/overview`
const volumes = () => `/projects/${PROJECT_ID}/planning/volumes`
const plots = () => `/projects/${PROJECT_ID}/planning/plots`
const blocks = () => `/projects/${PROJECT_ID}/planning/story-blocks`
const writer = () => `/projects/${PROJECT_ID}/write/chapters/1`
const planningDrafts = () => `/api/projects/${PROJECT_ID}/planning/drafts`
const outlineDrafts = () => `/api/projects/${PROJECT_ID}/chapter-outlines/1/drafts`
const session = () => `/api/projects/${PROJECT_ID}/chapter-sessions/1`
const assetRecommendations = () => `/api/projects/${PROJECT_ID}/asset-recommendations`

function pathname(value: string) { return new URL(value).pathname }
function isResponse(response, method: string, expected: string | RegExp) {
  const actual = pathname(response.url())
  return response.request().method() === method && (typeof expected === 'string' ? actual === expected : expected.test(actual))
}
function draftPath(root: string) { return new RegExp(`^${root}/[^/]+$`, 'u') }
function confirmPath(root: string) { return new RegExp(`^${root}/[^/]+/confirm$`, 'u') }
function workingDraftPath() { return new RegExp(`^/api/projects/${PROJECT_ID}/chapter-sessions/[^/]+/working-draft$`, 'u') }
function candidatePath() { return new RegExp(`^/api/projects/${PROJECT_ID}/chapter-sessions/[^/]+/candidates$`, 'u') }

function normalizedRuntimeApiPath(value) {
  const raw = String(value || '')
  if (!/^\/api(?:\/[A-Za-z0-9._~:-]+)*$/u.test(raw)) return null
  return raw.replace(/\/[0-9a-f]{8}-[0-9a-f-]{27,}/giu, '/:id')
}

const WRITE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])

function runtimeWritePath(value) {
  let pathname = String(value || '')
  try { pathname = new URL(pathname).pathname } catch {}
  return /^\/api(?:\/[A-Za-z0-9._~:-]+)*$/u.test(pathname) ? pathname : null
}

function isExactWriteRule(rule) {
  return (
    WRITE_METHODS.has(rule?.method)
    && (typeof rule.path === 'string' || rule.path instanceof RegExp)
    && Number.isInteger(rule.count)
    && rule.count > 0
    && Array.isArray(rule.statuses)
    && rule.statuses.length > 0
    && rule.statuses.every(status => Number.isInteger(status) && status >= 100 && status <= 599)
  )
}

function matchesExactWriteRule(rule, method, path) {
  if (rule.method !== method) return false
  if (typeof rule.path === 'string') return rule.path === path
  rule.path.lastIndex = 0
  const matches = rule.path.test(path)
  rule.path.lastIndex = 0
  return matches
}

function exactWriteRulesOverlap(left, right) {
  if (left.method !== right.method) return false
  if (typeof left.path === 'string' && typeof right.path === 'string') return left.path === right.path
  if (left.path instanceof RegExp && typeof right.path === 'string') return matchesExactWriteRule(left, left.method, right.path)
  if (typeof left.path === 'string' && right.path instanceof RegExp) return matchesExactWriteRule(right, right.method, left.path)
  return true
}

const IRRELEVANT_METADATA_RECORD = Symbol('irrelevant-metadata-record')

function safeLoopbackMetadataRecord(item, includesStatus) {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return null
  if (typeof item.url !== 'string' || typeof item.method !== 'string' || !SAFE_HTTP_METHODS.has(item.method)) return null
  let parsed
  try { parsed = new URL(item.url) } catch { return null }
  if (includesStatus && (!Number.isInteger(item.status) || item.status < 100 || item.status > 599)) return null
  if (!['http:', 'https:'].includes(parsed.protocol)) return IRRELEVANT_METADATA_RECORD
  if (parsed.hostname !== '127.0.0.1' || !parsed.pathname.startsWith('/')) return null
  return { method: item.method, pathname: parsed.pathname }
}

function safeRuleMetadataCounts(evidence, rule) {
  if (!Array.isArray(evidence?.requests) || !Array.isArray(evidence?.responses)) return null
  const normalizedRulePath = typeof rule.path === 'string' ? normalizedRuntimeApiPath(rule.path) : null
  let requestMetadataCount = 0
  let responseMetadataCount = 0
  let normalizedRequestMetadataCount = 0
  let normalizedResponseMetadataCount = 0
  for (const item of evidence.requests) {
    const record = safeLoopbackMetadataRecord(item, false)
    if (record === IRRELEVANT_METADATA_RECORD) continue
    if (!record) return null
    if (matchesExactWriteRule(rule, record.method, record.pathname)) requestMetadataCount += 1
    if (normalizedRulePath && record.method === rule.method && normalizedRuntimeApiPath(record.pathname) === normalizedRulePath) normalizedRequestMetadataCount += 1
  }
  for (const item of evidence.responses) {
    const record = safeLoopbackMetadataRecord(item, true)
    if (record === IRRELEVANT_METADATA_RECORD) continue
    if (!record) return null
    if (matchesExactWriteRule(rule, record.method, record.pathname)) responseMetadataCount += 1
    if (normalizedRulePath && record.method === rule.method && normalizedRuntimeApiPath(record.pathname) === normalizedRulePath) normalizedResponseMetadataCount += 1
  }
  return {
    requestMetadataCount,
    responseMetadataCount,
    normalizedRequestMetadataCount,
    normalizedResponseMetadataCount,
  }
}

function safeWriteCountProjection(error, evidence, writes) {
  const indexMatch = /^Runtime write count did not match allowlist entry (\d+)$/u.exec(String(error?.message || ''))
  if (!indexMatch || !Array.isArray(writes)) return null
  const ruleIndex = Number(indexMatch[1])
  if (!Number.isSafeInteger(ruleIndex) || ruleIndex < 0 || ruleIndex >= writes.length) return null
  if (!writes.every(isExactWriteRule)) return null
  const rule = writes[ruleIndex]
  if (writes.some((entry, index) => index !== ruleIndex && exactWriteRulesOverlap(rule, entry))) return null
  const outputPath = typeof rule.path === 'string' ? normalizedRuntimeApiPath(rule.path) : 'allowed'
  if (!outputPath) return null
  let actualCount = 0
  for (const response of evidenceItems(evidence?.apiResponses)) {
    const method = String(response?.method || '').toUpperCase()
    if (!WRITE_METHODS.has(method)) continue
    const path = runtimeWritePath(response?.url)
    if (!path) return null
    const matchingRules = writes.flatMap((entry, index) => (
      matchesExactWriteRule(entry, method, path) ? [index] : []
    ))
    if (matchingRules.length !== 1) return null
    if (!writes[matchingRules[0]].statuses.includes(response?.status)) return null
    if (matchingRules[0] === ruleIndex) actualCount += 1
  }
  const metadata = safeRuleMetadataCounts(evidence, rule)
  if (metadata === null) {
    if (!Array.isArray(evidence?.requests) && !Array.isArray(evidence?.responses)) {
      return `category=audit leaf=write-count ruleIndex=${ruleIndex} method=${rule.method} path=${outputPath} status=allowed expectedCount=${rule.count} actualCount=${actualCount}`
    }
    return null
  }
  return `category=audit leaf=write-count ruleIndex=${ruleIndex} method=${rule.method} path=${outputPath} status=allowed expectedCount=${rule.count} actualCount=${actualCount} requestMetadataCount=${metadata.requestMetadataCount} responseMetadataCount=${metadata.responseMetadataCount} normalizedRequestMetadataCount=${metadata.normalizedRequestMetadataCount} normalizedResponseMetadataCount=${metadata.normalizedResponseMetadataCount}`
}

function projectedRuntimeFailure(error, evidence, writes) {
  const message = String(error?.message || '')
  const unmatched = /Unmatched runtime write:\s*([A-Z]+)\s+(\/api\/[^\s]+)/u.exec(message)
  const unmatchedPath = unmatched && normalizedRuntimeApiPath(unmatched[2])
  if (unmatched && unmatchedPath) {
    return `category=audit leaf=write-unmatched method=${unmatched[1]} path=${unmatchedPath} status=unmatched count=unexpected`
  }
  const status = /Unexpected runtime write status for\s+([A-Z]+)\s+(\/api\/[^\s]+)/u.exec(message)
  const statusPath = status && normalizedRuntimeApiPath(status[2])
  if (status && statusPath) {
    return `category=audit leaf=write-status method=${status[1]} path=${statusPath} status=unexpected count=matched`
  }
  const countProjection = safeWriteCountProjection(error, evidence, writes)
  if (countProjection) return countProjection
  if (message.includes('Runtime write count did not match allowlist entry')) {
    return 'category=audit leaf=write-count method=allowed path=allowed status=allowed count=mismatch'
  }
  const diagnostic = runtimeFailureDiagnostic(error)
  const failure = diagnostic?.responseFailures?.[0] || diagnostic?.requestFailures?.[0]
  const path = normalizedRuntimeApiPath(failure?.path)
  if (failure && path && /^[A-Z]+$/u.test(failure.method)) {
    const statusValue = Number.isInteger(failure.status) ? failure.status : 'unavailable'
    return `category=audit leaf=runtime-settlement method=${failure.method} path=${path} status=${statusValue} count=1`
  }
  return null
}

const AUDIT_STAGES = Object.freeze([
  'settlement',
  'dynamic-sensitive',
  'private-marker',
  'runtime-health',
  'network-access',
  'exact-writes',
])
const SAFE_HTTP_METHODS = new Set(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
const MAX_RUNTIME_HEALTH_INVENTORY_ENTRIES = 8

function auditStageProjection(stage) {
  if (!AUDIT_STAGES.includes(stage)) return null
  return `category=audit leaf=audit-stage stage=${stage} method=unavailable path=unavailable status=unavailable count=1`
}

function evidenceItems(value) {
  return Array.isArray(value) ? value : []
}

function closedEvidenceCount(value) {
  return Number.isInteger(value) && value >= 0 ? value : 0
}

function normalizedEvidenceApiPath(value) {
  let pathname = String(value || '')
  try { pathname = new URL(pathname).pathname } catch {}
  return normalizedRuntimeApiPath(pathname)
}

function safeResponseFailureInventory(evidence) {
  const groups = new Map()
  let unavailableCount = 0
  for (const rawFailure of evidenceItems(evidence?.responseFailures)) {
    const match = /^(\d{3}) ([A-Z]+) (\S+)$/u.exec(String(rawFailure || ''))
    if (!match) {
      unavailableCount += 1
      continue
    }
    const status = Number(match[1])
    const method = match[2]
    let parsedUrl
    try { parsedUrl = new URL(match[3]) } catch {
      unavailableCount += 1
      continue
    }
    const path = normalizedRuntimeApiPath(parsedUrl.pathname)
    if (
      !['http:', 'https:'].includes(parsedUrl.protocol)
      || parsedUrl.hostname !== '127.0.0.1'
      || !SAFE_HTTP_METHODS.has(method)
      || !path
      || status < 100
      || status > 599
    ) {
      unavailableCount += 1
      continue
    }
    const key = `${method}\u0000${path}\u0000${status}`
    groups.set(key, { method, path, status, count: (groups.get(key)?.count || 0) + 1 })
  }
  const sorted = [...groups.values()].sort((left, right) => (
    left.method.localeCompare(right.method)
    || left.path.localeCompare(right.path)
    || left.status - right.status
  ))
  const visible = sorted.slice(0, MAX_RUNTIME_HEALTH_INVENTORY_ENTRIES)
  return {
    inventory: visible.length > 0
      ? visible.map(item => `${item.method}:${item.path}:${item.status}:${item.count}`).join('|')
      : 'none',
    unavailableCount,
    inventoryOmittedCount: sorted.length - visible.length,
    groups,
  }
}

function safeLinkedConsoleCounts(evidence, runtimeAuditOptions, responseInventory) {
  const consoleErrors = evidenceItems(evidence?.consoleErrors)
  const responseRules = evidenceItems(runtimeAuditOptions?.responseFailureAllowlist)
  const consoleRules = evidenceItems(runtimeAuditOptions?.consoleErrorAllowlist)
  const exactResponseRule = (link) => responseRules.filter(rule => (
    Number.isInteger(rule?.status)
    && rule.status >= 100
    && rule.status <= 599
    && SAFE_HTTP_METHODS.has(rule?.method)
    && normalizedRuntimeApiPath(rule?.pathname)
    && rule.status === link.status
    && rule.method === link.method
    && normalizedRuntimeApiPath(rule.pathname) === link.path
    && Number.isInteger(rule.count)
    && rule.count > 0
  ))
  const normalizedRules = consoleRules.flatMap(rule => {
    const link = rule?.linkedResponseFailure
    const path = normalizedRuntimeApiPath(link?.pathname)
    if (
      typeof rule?.message !== 'string'
      || !Number.isInteger(rule.count)
      || rule.count < 1
      || !Number.isInteger(link?.status)
      || link.status < 100
      || link.status > 599
      || !SAFE_HTTP_METHODS.has(link?.method)
      || !path
    ) return []
    const responseRule = exactResponseRule({ status: link.status, method: link.method, path })
    const response = responseInventory.groups.get(`${link.method}\u0000${path}\u0000${link.status}`)
    if (responseRule.length !== 1 || response?.count !== responseRule[0].count) return []
    return [{ message: rule.message, count: rule.count }]
  })
  const counts = new Map()
  for (const message of consoleErrors) {
    const value = String(message || '')
    counts.set(value, (counts.get(value) || 0) + 1)
  }
  const knownLinkedCount = normalizedRules.reduce((count, rule) => (
    counts.get(rule.message) === rule.count ? count + rule.count : count
  ), 0)
  return { knownLinkedCount, otherCount: Math.max(0, consoleErrors.length - knownLinkedCount) }
}

function firstNon2xxApiResponse(evidence) {
  const response = evidenceItems(evidence?.apiResponses)
    .find(item => Number.isInteger(item?.status) && (item.status < 200 || item.status >= 300))
  const path = normalizedEvidenceApiPath(response?.url)
  if (
    !response
    || !path
    || !SAFE_HTTP_METHODS.has(response.method)
    || response.status < 100
    || response.status > 599
  ) {
    return { method: 'unavailable', path: 'unavailable', status: 'unavailable' }
  }
  return { method: response.method, path, status: response.status }
}

function firstPublicRequestFailure(evidence) {
  const diagnostic = publicRuntimeDiagnostic({ requestFailures: evidenceItems(evidence?.requestFailures) })
  const failure = diagnostic?.requestFailures?.[0]
  const path = normalizedRuntimeApiPath(failure?.path)
  if (!path || !SAFE_HTTP_METHODS.has(failure?.method)) {
    return { method: 'unavailable', path: 'unavailable', status: 'unavailable' }
  }
  return { method: failure.method, path, status: 'unavailable' }
}

function firstApiReadError(evidence) {
  const response = evidenceItems(evidence?.apiResponses)
    .find(item => item?.headersReadError || item?.bodyReadError)
  const path = normalizedEvidenceApiPath(response?.url)
  if (
    !response
    || !path
    || !SAFE_HTTP_METHODS.has(response.method)
    || !Number.isInteger(response.status)
    || response.status < 100
    || response.status > 599
  ) {
    return { method: 'unavailable', path: 'unavailable', status: 'unavailable' }
  }
  return { method: response.method, path, status: response.status }
}

function runtimeHealthSummary(evidence, runtimeAuditOptions = null) {
  const apiResponses = evidenceItems(evidence?.apiResponses)
  const requests = evidenceItems(evidence?.requests)
  const response = firstNon2xxApiResponse(evidence)
  const request = firstPublicRequestFailure(evidence)
  const read = firstApiReadError(evidence)
  const responseInventory = safeResponseFailureInventory(evidence)
  const consoleCounts = safeLinkedConsoleCounts(evidence, runtimeAuditOptions, responseInventory)
  const apiReadErrorCount = apiResponses.reduce((count, item) => (
    count + Number(Boolean(item?.headersReadError)) + Number(Boolean(item?.bodyReadError))
  ), 0)
  const requestReadErrorCount = requests.reduce((count, item) => (
    count + Number(Boolean(item?.headersReadError)) + Number(Boolean(item?.bodyReadError))
  ), 0)
  return `category=audit leaf=runtime-health-summary responseFailureCount=${evidenceItems(evidence?.responseFailures).length} consoleErrorCount=${evidenceItems(evidence?.consoleErrors).length} pageErrorCount=${evidenceItems(evidence?.pageErrors).length} requestFailureCount=${evidenceItems(evidence?.requestFailures).length} apiReadErrorCount=${apiReadErrorCount} requestReadErrorCount=${requestReadErrorCount} forbiddenRequestCount=${closedEvidenceCount(evidence?.networkAccess?.forbiddenRequestCount)} forbiddenResponseCount=${closedEvidenceCount(evidence?.networkAccess?.forbiddenResponseCount)} responseMethod=${response.method} responsePath=${response.path} responseStatus=${response.status} requestMethod=${request.method} requestPath=${request.path} requestStatus=${request.status} readMethod=${read.method} readPath=${read.path} readStatus=${read.status} responseInventory=${responseInventory.inventory} unavailableCount=${responseInventory.unavailableCount} inventoryOmittedCount=${responseInventory.inventoryOmittedCount} consoleKnownLinkedCount=${consoleCounts.knownLinkedCount} consoleOtherCount=${consoleCounts.otherCount}`
}

async function runRuntimeAuditStages(stages) {
  for (const { stage, run } of stages) {
    try { await run() } catch (error) { return { stage, error } }
  }
  return null
}

function strictSafeBehaviorProjection(bodyError) {
  const message = String(bodyError?.message || '')
  if (/^category=behavior leaf=runtime-listener stage=(after-model-settings|before-planning-create|after-planning-create) state=detached$/u.test(message)) return message
  if (/^category=behavior leaf=planning-create-flow stage=(navigation|listener-check|wait-registration|button-click|response-wait) method=POST path=\/api\/projects\/:id\/planning\/drafts status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=planning-create-status method=POST path=\/api\/projects\/:id\/planning\/drafts status=[1-5]\d{2}$/u.test(message)) return message
  if (/^category=behavior leaf=planning-manual-flow stage=(ai-disabled|add-volume|fill-volume|settle-volume|open-plots|add-plot|fill-plot|settle-plot|open-blocks|add-block|fill-block|add-stage|fill-stage|add-scene-task|fill-scene-task|activate-block|save-wait-registration|save-click|save-response|preview-click|confirm-wait-registration|confirm-click|confirm-response|final-settlement) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=planning-revision-flow stage=(navigation|create-wait-registration|create-click|create-response|volume-card|fill-title|save-wait-registration|save-click|save-response|preview-click|confirm-wait-registration|confirm-click|confirm-response|final-settlement) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=outline-flow stage=(navigation|create-wait-registration|create-click|create-response|outline-sheet|reference-selects|stage-references|scene-task-references|fill-goal|fill-characters|fill-continuation|fill-tasks|fill-scenes|fill-forbidden|save-wait-registration|save-click|save-response|preview-click|confirm-wait-registration|confirm-click|confirm-response|final-settlement) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=phase2-preparation-flow stage=(seed-navigation|seed-editor|seed-save|seed-select|seed-settlement|contract-navigation|contract-manual|engine-save|style-save|asset-save|capacity-save|contract-confirm|contract-settlement|bible-navigation|bible-generate|bible-preview|bible-confirm|final-settlement) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=phase2-engine-save stage=(click|heading|response) method=POST path=\/api\/projects\/:id\/asset-recommendations status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=phase2-engine-save stage=status method=POST path=\/api\/projects\/:id\/asset-recommendations status=[1-5]\d{2}$/u.test(message)) return message
  const phase2SeedSelection = /^category=behavior leaf=phase2-seed-selection-flow stage=(card-count|card-visible|card-click|modal-visible|wait-registration|confirm-click|response|generation|settlement) method=(PUT|unavailable) path=(\/api\/projects\/:id\/selected-seed|unavailable) status=unavailable$/u.exec(message)
  if (phase2SeedSelection) {
    const [, stage, method, path] = phase2SeedSelection
    const writeStage = ['wait-registration', 'confirm-click', 'response', 'generation', 'settlement'].includes(stage)
    if ((writeStage && method === 'PUT' && path === '/api/projects/:id/selected-seed') || (!writeStage && method === 'unavailable' && path === 'unavailable')) return message
  }
  if (/^category=behavior leaf=baseline-seed-lock stage=(navigation|settlement|saved-section|generation|new-absent|select-absent|edit-count|edit-disabled) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=baseline-stale-bible stage=(wait-registration|click|response) method=POST path=\/api\/projects\/:id\/bible\/confirm status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=baseline-stale-bible stage=status method=POST path=\/api\/projects\/:id\/bible\/confirm status=[1-5]\d{2}$/u.test(message)) return message
  if (/^category=behavior leaf=baseline-stale-bible stage=(public-error|reload-action) method=POST path=\/api\/projects\/:id\/bible\/confirm status=409$/u.test(message)) return message
  if (/^category=behavior leaf=revision-outline-session stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|verify-r1|planning-revision|history-r1|outline-before-confirm|outline-confirm|writer-session) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=writer-overview-flow mode=(create|replay) stage=(preparation-wait-registration|overview-click|preparation-response|overview-url|action-count|action-href|session-wait-registration|action-click|session-response|writer-heading|final-settlement) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=writer-overview-target mode=(create|replay) target=(seeds|contract|bible|model-settings|writer-variant|story-blocks-variant|volumes-variant|plots-variant|planning-other|write-other|project-other|missing|absolute-loopback|other) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=writer-preparation-target mode=(create|replay) action=(select-seed|continue-contract|continue-bible|continue-planning|establish-planning|recover-planning|recover-outline|prepare-outline|continue-outline|start-session|continue-writing|unavailable) target=(writer|non-writer|unavailable) method=GET path=\/api\/projects\/:id\/preparation status=([1-5]\d{2}|unavailable)$/u.test(message)) return message
  if (/^category=behavior leaf=writer-outline-navigation stage=(link-count|link-visible|link-click|path|workspace-visible|settlement) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=outline-adjustment-before-finalization stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|outline-r1|writer-entry|working-draft-save|candidate-a-save|outline-link-navigation|outline-r2|writer-return-navigation|preserved-draft-and-stale-a|candidate-b-save|current-b|final-settlement) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=pinned-session stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|outline|writer-before|planning-revision|writer-after) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=baseline-lock stage=(create-project|phase2-preparation|seed-lock-view|contract-lock-view|bible-lock-view|stale-bible-confirm|stale-bible-reload|final-baseline-reload) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=archived-navigation stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|outline|archive|volumes-readonly|plots-navigation|browser-history|blocks-readonly) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=foundation-stage stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|post-planning) method=unavailable path=unavailable status=unavailable$/u.test(message)) return message
  if (/^category=behavior leaf=observer-progress method=POST path=\/api\/projects\/:id\/planning\/drafts status=201 requestStage=(unseen|entry|metadata|recorded|scheduled) responseStage=(unseen|entry|metadata|recorded|scheduled)$/u.test(message)) return message
  if (/^category=behavior leaf=observer-metadata method=POST path=\/api\/projects\/:id\/planning\/drafts status=201 requestMatch=[01] responseMatch=[01]$/u.test(message)) return message
  return null
}

function projectPhase3FailureMessage(bodyError, auditError, auditStage, evidence, writes, runtimeAuditOptions = null) {
  const behaviorProjection = strictSafeBehaviorProjection(bodyError)
  if (behaviorProjection) return behaviorProjection
  if (auditError) {
    return projectedRuntimeFailure(auditError, evidence, writes)
      || (auditStage === 'runtime-health' ? runtimeHealthSummary(evidence, runtimeAuditOptions) : null)
      || auditStageProjection(auditStage)
      || 'category=audit leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable'
  }
  return 'category=behavior leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable'
}

const CONTRACT_DRAFT_404_MESSAGE = 'error: Failed to load resource: the server responded with a status of 404 (Not Found)'
const STALE_BIBLE_CONFIRM_409_MESSAGE = 'error: Failed to load resource: the server responded with a status of 409 (Conflict)'
const CONTRACT_DRAFT_404_COUNTS = new Set([1, 3])

function phase3RuntimeAuditOptions(projectId, { allowStaleBibleConfirm409 = false, contractDraft404Count = 1 } = {}) {
  if (!CONTRACT_DRAFT_404_COUNTS.has(contractDraft404Count)) {
    throw new TypeError('Phase 3 contract-draft 404 count is invalid')
  }
  const contractDraftPath = `/api/projects/${projectId}/contract-draft`
  const staleBibleConfirmPath = `/api/projects/${projectId}/bible/confirm`
  return {
    responseFailureAllowlist: [
      {
        status: 404,
        method: 'GET',
        pathname: contractDraftPath,
        count: contractDraft404Count,
      },
      ...(allowStaleBibleConfirm409 ? [{
        status: 409,
        method: 'POST',
        pathname: staleBibleConfirmPath,
        count: 1,
      }] : []),
    ],
    consoleErrorAllowlist: [
      {
        message: CONTRACT_DRAFT_404_MESSAGE,
        count: contractDraft404Count,
        linkedResponseFailure: {
          status: 404,
          method: 'GET',
          pathname: contractDraftPath,
        },
      },
      ...(allowStaleBibleConfirm409 ? [{
        message: STALE_BIBLE_CONFIRM_409_MESSAGE,
        count: 1,
        linkedResponseFailure: {
          status: 409,
          method: 'POST',
          pathname: staleBibleConfirmPath,
        },
      }] : []),
    ],
  }
}

function phase2PreparationWrites() {
  return [
    { method: 'POST', path: '/api/projects', count: 1, statuses: [200] },
    { method: 'POST', path: `/api/projects/${PROJECT_ID}/seeds`, count: 1, statuses: [200] },
    { method: 'PUT', path: `/api/projects/${PROJECT_ID}/selected-seed`, count: 1, statuses: [200] },
    { method: 'POST', path: `/api/projects/${PROJECT_ID}/story-engine-batches/manual`, count: 1, statuses: [201] },
    { method: 'POST', path: `/api/projects/${PROJECT_ID}/asset-recommendations`, statuses: [200], count: 2 },
    { method: 'PUT', path: `/api/projects/${PROJECT_ID}/contract-draft`, count: 4, statuses: [200] },
    { method: 'POST', path: `/api/projects/${PROJECT_ID}/contracts/preview`, statuses: [200], count: 1 },
    { method: 'POST', path: `/api/projects/${PROJECT_ID}/contracts/confirm`, count: 1, statuses: [201] },
    { method: 'POST', path: `/api/projects/${PROJECT_ID}/bible/generate`, count: 1, statuses: [200] },
    { method: 'POST', path: `/api/projects/${PROJECT_ID}/bible/confirm`, count: 1, statuses: [201] },
    { method: 'PUT', path: `/api/projects/${PROJECT_ID}/bindings`, count: 1, statuses: [200] },
  ]
}

function baselineLockWrites() {
  return phase2PreparationWrites().filter(rule => (
    rule.path !== `/api/projects/${PROJECT_ID}/bindings`
  )).map(rule => (
    rule.method === 'POST' && rule.path === `/api/projects/${PROJECT_ID}/bible/confirm`
      ? { ...rule, count: 2, statuses: [201, 409] }
      : rule
  ))
}

function phase2SeedSelectionFailure(stage) {
  const writeStage = ['wait-registration', 'confirm-click', 'response', 'generation', 'settlement'].includes(stage)
  const method = writeStage ? 'PUT' : 'unavailable'
  const path = writeStage ? '/api/projects/:id/selected-seed' : 'unavailable'
  return `category=behavior leaf=phase2-seed-selection-flow stage=${stage} method=${method} path=${path} status=unavailable`
}

function phase2EngineSaveFailure(stage, status = 'unavailable') {
  const closedStatus = stage === 'status'
    && Number.isInteger(status)
    && status >= 100
    && status <= 599
    ? status
    : 'unavailable'
  return `category=behavior leaf=phase2-engine-save stage=${stage} method=POST path=/api/projects/:id/asset-recommendations status=${closedStatus}`
}

function baselineSeedLockFailure(stage) {
  return `category=behavior leaf=baseline-seed-lock stage=${stage} method=unavailable path=unavailable status=unavailable`
}

function baselineStaleBibleFailure(stage, status = 'unavailable') {
  const closedStatus = stage === 'status' && Number.isInteger(status) && status >= 100 && status <= 599
    ? status
    : ['public-error', 'reload-action'].includes(stage)
      ? 409
      : 'unavailable'
  return `category=behavior leaf=baseline-stale-bible stage=${stage} method=POST path=/api/projects/:id/bible/confirm status=${closedStatus}`
}

async function finishRuntime(runtime, bodyError: unknown, writes, runtimeAuditOptions = null) {
  const resolvedRuntimeAuditOptions = typeof runtimeAuditOptions === 'function'
    ? runtimeAuditOptions()
    : runtimeAuditOptions
  let evidence
  let health
  let expectedWrites
  const auditFailure = await runRuntimeAuditStages([
    { stage: 'settlement', run: async () => { evidence = await runtime.finish() } },
    { stage: 'dynamic-sensitive', run: async () => {
      expect(scanRuntimeEvidence(evidence, runtimeSensitiveValues(process.env))).toEqual({ matchCount: 0 })
    } },
    { stage: 'private-marker', run: async () => {
      assertNoPrivateEvidenceMarkers([
        ...evidence.consoleMessages,
        ...evidence.consoleErrors,
        ...evidence.pageErrors,
        evidence.pageContent,
      ])
    } },
    { stage: 'runtime-health', run: async () => {
      health = assertRuntimeEvidenceHealthy(evidence, resolvedRuntimeAuditOptions || phase3RuntimeAuditOptions(PROJECT_ID))
    } },
    { stage: 'network-access', run: async () => {
      expect(health.networkAccess).toMatchObject({ forbiddenRequestCount: 0, forbiddenResponseCount: 0 })
      test.info().annotations.push({ type: 'network-audit', description: JSON.stringify(health.networkAccess) })
    } },
    { stage: 'exact-writes', run: async () => {
      expectedWrites = typeof writes === 'function' ? writes() : writes
      assertExactWrites(evidence, expectedWrites)
    } },
  ])
  const safeProjection = projectPhase3FailureMessage(bodyError, auditFailure?.error, auditFailure?.stage, evidence, expectedWrites, resolvedRuntimeAuditOptions)
  if (bodyError || auditFailure) throw new Error(safeProjection)
}

function assertRuntimeListenersAttached(runtime, stage) {
  if (runtime.listenersAttached()) return
  throw new Error(`category=behavior leaf=runtime-listener stage=${stage} state=detached`)
}

async function runAudited(page, writes, body, { runtimeAuditOptions = null } = {}) {
  const runtime = observePhase3Runtime(page)
  let bodyError: unknown = null
  try { await body(runtime) } catch (error) { bodyError = error }
  await finishRuntime(runtime, bodyError, writes, runtimeAuditOptions)
}

function observePhase3Runtime(page) {
  const runtime = observeRuntime(page, { allowedOrigins })
  const context = page.context()
  const secondaryPages = new Set()
  const secondaryConsoleMessages = []
  const secondaryConsoleErrors = []
  const secondaryPageErrors = []
  let secondaryPageContentUnavailableCount = 0
  function attachPageEvidence(candidate) {
    if (candidate === page || secondaryPages.has(candidate)) return
    secondaryPages.add(candidate)
    candidate.on('console', message => {
      const rendered = `${message.type()}: ${message.text()}`
      secondaryConsoleMessages.push(rendered)
      if (message.type() === 'error') secondaryConsoleErrors.push(rendered)
    })
    candidate.on('pageerror', error => secondaryPageErrors.push(String(error?.message || error)))
  }
  for (const candidate of context.pages()) attachPageEvidence(candidate)
  context.on('page', attachPageEvidence)
  return {
    ...runtime,
    async finish() {
      const evidence = await runtime.finish()
      const secondaryPageContents = await Promise.all([...secondaryPages].map(async candidate => {
        try { return await candidate.content() } catch {
          secondaryPageContentUnavailableCount += 1
          return ''
        }
      }))
      return {
        ...evidence,
        consoleMessages: [...evidence.consoleMessages, ...secondaryConsoleMessages],
        consoleErrors: [...evidence.consoleErrors, ...secondaryConsoleErrors],
        pageErrors: [
          ...evidence.pageErrors,
          ...secondaryPageErrors,
          ...Array(secondaryPageContentUnavailableCount).fill('secondary-page-content-unavailable'),
        ],
        pageContent: [evidence.pageContent, ...secondaryPageContents].join('\n'),
        secondaryPageContentUnavailableCount,
      }
    },
  }
}

async function completePhase2PreparationUi(page, runtime, { beforeBibleConfirm = null } = {}) {
  let stage = 'seed-navigation'
  try {
  await page.goto(`/projects/${PROJECT_ID}/seeds`)
  stage = 'seed-editor'
  await page.getByRole('button', { name: /已存种子/u }).click()
  await page.getByRole('button', { name: '新建种子', exact: true }).click()
  const seed = page.getByRole('region', { name: '种子九字段编辑器' })
  for (const [label, value] of [
    ['种子标题', '雾港错钟'], ['题材类型', '历史穿越'],
    ['一句话故事', '守钟学徒发现潮汐钟会提前刻下海难。'],
    ['主角底色', '谨慎克制，愿意承担代价。'], ['核心欲望', '找回失踪导师。'],
    ['核心冲突', '每次用证据破局都会引来封存。'], ['世界压力', '风暴季压缩选择。'],
    ['开篇抓手', '第三声钟鸣提前落下。'], ['差异化支点', '证据不能消除代价。'],
  ]) await seed.locator('label').filter({ hasText: label }).locator('input, textarea').fill(value)
  stage = 'seed-save'
  const createdResponse = page.waitForResponse(response => isResponse(response, 'POST', `/api/projects/${PROJECT_ID}/seeds`))
  await seed.getByRole('button', { name: '保存种子', exact: true }).click()
  expect((await createdResponse).status()).toBe(200)
  stage = 'seed-select'
  let selectionStage = 'card-count'
  try {
    const card = page.locator('.seed-record').filter({ has: page.getByRole('heading', { name: '雾港错钟', exact: true }) })
    await expect(card).toHaveCount(1)
    selectionStage = 'card-visible'
    await expect(card).toBeVisible()
    selectionStage = 'card-click'
    await card.getByRole('button', { name: '确认这个种子并进入创作契约', exact: true }).click()
    selectionStage = 'modal-visible'
    const selectionDialog = page.locator('.seed-confirm-dialog').filter({ hasText: '确认创作种子' })
    await expect(selectionDialog).toHaveCount(1)
    await expect(selectionDialog).toBeVisible()
    await expect(selectionDialog.getByText('确认创作种子', { exact: true })).toBeVisible()
    selectionStage = 'wait-registration'
    const selectedResponse = page.waitForResponse(response => isResponse(response, 'PUT', `/api/projects/${PROJECT_ID}/selected-seed`))
    selectionStage = 'confirm-click'
    await selectionDialog.getByRole('button', { name: '确认这个种子并进入创作契约', exact: true }).click()
    selectionStage = 'response'
    expect((await selectedResponse).status()).toBe(200)
    selectionStage = 'generation'
    await expect(page.getByText('选定代次 1', { exact: true })).toBeVisible()
    selectionStage = 'settlement'
    await settleNavigationBoundary(page, runtime)
  } catch (error) {
    if (strictSafeBehaviorProjection(error)) throw error
    void error
    throw new Error(phase2SeedSelectionFailure(selectionStage))
  }
  stage = 'seed-settlement'
  stage = 'contract-navigation'
  await page.goto(`/projects/${PROJECT_ID}/contract`)
  stage = 'contract-manual'
  await page.locator('label').filter({ hasText: '渠道定位标识' }).locator('input').fill('phase3-manual-channel')
  await page.locator('label').filter({ hasText: '题材定位标识' }).locator('input').fill('历史穿越')
  await page.getByRole('button', { name: '普通字段手动录入' }).click()
  const labels = [
    ['方案名称', option => option.name], ['故事承诺', option => option.storyPromise],
    ['主角欲望', option => option.protagonistDesire], ['持续压力', option => option.sustainedPressure],
    ['成长方向', option => option.growthDirection], ['冲突循环', option => option.conflictLoop],
    ['群像角色', option => option.ensembleRoles.map(role => `${role.role}：${role.purpose}`).join('\n')],
    ['优势与代价', option => option.advantageAndCost], ['满足感来源', option => option.satisfactionSources.join('\n')],
    ['长线变化', option => option.longFormVariation.join('\n')], ['结局锚点', option => option.endingAnchor],
    ['风险', option => option.risks.join('\n')], ['差异化', option => option.differentiation],
  ]
  const options = page.locator('.manual-sheet article')
  for (let index = 0; index < SYNTHETIC_STORY_ENGINE_OPTIONS.length; index += 1) {
    for (const [label, value] of labels) await options.nth(index).locator('label').filter({ hasText: label }).locator('input, textarea').fill(value(SYNTHETIC_STORY_ENGINE_OPTIONS[index]))
  }
  await page.getByRole('button', { name: '建立手动三案' }).click()
  await page.getByRole('radio', { name: /潮钟追凶/u }).click()
  const engine = page.locator('section.engine-step')
  const styleRecommendationsResponse = page.waitForResponse(response => isResponse(response, 'POST', assetRecommendations()))
  stage = 'engine-save'
  let engineSaveStage = 'click'
  try {
    await engine.getByRole('button', { name: '保存草稿并继续' }).click()
    engineSaveStage = 'heading'
    await expect(page.getByRole('heading', { name: '先定阅读感受，再谈写法', exact: true })).toBeVisible()
    engineSaveStage = 'response'
    const response = await styleRecommendationsResponse
    engineSaveStage = 'status'
    const status = response.status()
    if (status !== 200) throw new Error(phase2EngineSaveFailure(engineSaveStage, status))
  } catch (error) {
    const projection = strictSafeBehaviorProjection(error)
    if (projection) throw new Error(projection)
    void error
    throw new Error(phase2EngineSaveFailure(engineSaveStage))
  }
  const styleStep = page.locator('section.contract-step').filter({
    has: page.getByRole('heading', { name: '先定阅读感受，再谈写法', exact: true }),
  })
  const styles = styleStep.locator('.select-grid')
  await chooseVisibleSelectOption(page, styles.locator('label').filter({ hasText: '主风格' }), '克制悬疑型 · r1')
  await chooseVisibleSelectOption(page, styles.locator('label').filter({ hasText: '次风格' }), '沉浸群像型 · r1')
  const assetRecommendationsResponse = page.waitForResponse(response => isResponse(response, 'POST', assetRecommendations()))
  stage = 'style-save'
  await styleStep.getByRole('button', { name: '保存草稿并继续' }).click()
  await expect(page.getByRole('heading', { name: '逐项授权，片段级冻结', exact: true })).toBeVisible()
  expect((await assetRecommendationsResponse).status()).toBe(200)
  const assetScope = page.locator('section.asset-step').filter({
    has: page.getByRole('heading', { name: '逐项授权，片段级冻结', exact: true }),
  })
  stage = 'asset-save'
  await assetScope.getByRole('button', { name: '保存草稿并继续' }).click()
  await expect(page.getByRole('heading', { name: '给长篇一副可调整的骨架', exact: true })).toBeVisible()
  const capacity = page.locator('section.capacity-step').filter({
    has: page.getByRole('heading', { name: '给长篇一副可调整的骨架', exact: true }),
  })
  for (const [label, value] of [['目标总字数', '720000'], ['预计卷数', '8'], ['预计章节数', '240'], ['下限', '2200'], ['上限', '3200']]) await capacity.locator('label').filter({ hasText: label }).locator('input').fill(value)
  stage = 'capacity-save'
  await capacity.getByRole('button', { name: '保存草稿并继续' }).click()
  await expect(page.getByRole('heading', { name: '预览全部变化，再一次确认', exact: true })).toBeVisible()
  stage = 'contract-confirm'
  await page.getByRole('button', { name: '一次确认完整契约' }).click()
  stage = 'contract-settlement'
  await settleNavigationBoundary(page, runtime)
  stage = 'bible-navigation'
  await page.goto(`/projects/${PROJECT_ID}/bible`)
  const generation = page.getByRole('region', { name: 'AI 生成创作圣经' })
  stage = 'bible-generate'
  await generation.getByRole('button', { name: '生成创作圣经' }).click()
  stage = 'bible-preview'
  await page.getByRole('button', { name: '预览并确认', exact: true }).click()
  if (beforeBibleConfirm) await beforeBibleConfirm()
  stage = 'bible-confirm'
  await page.getByRole('dialog', { name: '确认创作圣经', exact: true }).getByRole('button', { name: '确认签印', exact: true }).click()
  stage = 'final-settlement'
  await settleNavigationBoundary(page, runtime)
  } catch (error) {
    if (strictSafeBehaviorProjection(error)) throw error
    void error
    throw new Error(`category=behavior leaf=phase2-preparation-flow stage=${stage} method=unavailable path=unavailable status=unavailable`)
  }
}

async function assertBaselineSeedLockUi(page, runtime) {
  let stage = 'navigation'
  try {
    await page.goto(`/projects/${PROJECT_ID}/seeds`)
    stage = 'settlement'
    await settleNavigationBoundary(page, runtime)
    stage = 'saved-section'
    await page.getByRole('button', { name: /已存种子/u }).click()
    stage = 'generation'
    await expect(page.getByText('选定代次 1', { exact: true })).toBeVisible()
    stage = 'new-absent'
    await expect(page.getByRole('button', { name: '新建种子', exact: true })).toHaveCount(0)
    stage = 'select-absent'
    await expect(page.getByRole('button', { name: '确认这个种子并进入创作契约', exact: true })).toHaveCount(0)
    stage = 'edit-count'
    const edit = page.getByRole('button', { name: '编辑', exact: true })
    await expect(edit).toHaveCount(1)
    stage = 'edit-disabled'
    await expect(edit).toBeDisabled()
  } catch (error) {
    if (strictSafeBehaviorProjection(error)) throw error
    void error
    throw new Error(baselineSeedLockFailure(stage))
  }
}

async function assertBaselineStaleBibleConfirmUi(staleBiblePage) {
  let stage = 'wait-registration'
  try {
    const staleConfirm = staleBiblePage.getByRole('dialog', { name: '确认创作圣经', exact: true })
    const staleResponse = staleBiblePage.waitForResponse(response => isResponse(response, 'POST', `/api/projects/${PROJECT_ID}/bible/confirm`))
    stage = 'click'
    await staleConfirm.getByRole('button', { name: '确认签印', exact: true }).click()
    stage = 'response'
    const response = await staleResponse
    stage = 'status'
    const status = response.status()
    if (status !== 409) throw new Error(baselineStaleBibleFailure(stage, status))
    stage = 'public-error'
    await expect(staleConfirm.getByText('保存冲突：本地编辑仍保留，请重新加载权威版本后再继续。', { exact: true })).toBeVisible()
    stage = 'reload-action'
    await expect(staleConfirm.getByRole('button', { name: '重新加载权威版本', exact: true })).toBeVisible()
  } catch (error) {
    if (strictSafeBehaviorProjection(error)) throw error
    void error
    throw new Error(baselineStaleBibleFailure(stage))
  }
}

async function chooseVisibleSelectOption(page, select, label: string) {
  const trigger = select.locator('.n-base-selection')
  await trigger.click()
  const candidate = page.locator('.n-base-select-option:visible').filter({ hasText: new RegExp(label.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u') })
  await expect(candidate).not.toHaveCount(0)
  await candidate.last().click()
}

async function createProjectUi(page, runtime) {
  await page.goto('/projects')
  await page.locator('.project-library-heading').getByRole('button', { name: '新建项目', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '新建项目' })
  await dialog.getByLabel('项目名称').fill('Phase 3 foundation')
  await dialog.getByRole('button', { name: '创建并打开', exact: true }).click()
  await expect.poll(() => new URL(page.url()).pathname).toMatch(/^\/projects\/[0-9a-f-]{36}\/overview$/u)
  PROJECT_ID = new URL(page.url()).pathname.split('/')[2]
  await settleNavigationBoundary(page, runtime)
}

async function disablePlanningModelUi(page, runtime) {
  await page.goto(`/projects/${PROJECT_ID}/settings/models`)
  await expect(page.getByRole('heading', { name: '项目模型绑定', exact: true })).toBeVisible()
  const binding = page.locator('.binding-ledger')
  await expect(binding).toHaveCount(1)
  await expect(binding).toBeVisible()
  await binding.getByRole('button', { name: /高级设置 · 分别绑定八项/u }).click()
  const planningBinding = binding.locator('.binding-row').filter({
    hasText: '创作规划',
  })
  await expect(planningBinding).toHaveCount(1)
  await expect(planningBinding).toBeVisible()
  const planningSelect = planningBinding.getByRole('textbox')
  await expect(planningSelect).toHaveCount(1)
  await expect(planningSelect).toBeVisible()
  const planningClear = planningBinding.locator('.n-base-clear')
  await expect(planningClear).toHaveCount(1)
  await expect(planningClear).toBeVisible()
  await planningClear.click()
  const savedResponse = page.waitForResponse(response => isResponse(response, 'PUT', `/api/projects/${PROJECT_ID}/bindings`))
  await binding.getByRole('button', { name: '保存完整八项', exact: true }).click()
  expect((await savedResponse).status()).toBe(200)
  await expect(binding.getByText('完整八项快照已保存；当前仍有待恢复项。', { exact: true })).toBeVisible()
  await settleNavigationBoundary(page, runtime)
  assertRuntimeListenersAttached(runtime, 'after-model-settings')
}

async function fillManualVolume(page, title: string) {
  const volumeCards = page.locator('.planning-editor .manuscript-card')
  await expect(volumeCards).toHaveCount(1)
  await expect(volumeCards).toBeVisible()
  await volumeCards.getByLabel('卷名', { exact: true }).fill(title)
  await volumeCards.getByLabel('核心变化', { exact: true }).fill('主角从逃亡者变成能保护同伴的人。')
  await volumeCards.getByLabel('主要压力', { exact: true }).fill('旧敌封锁北境商路。')
  await volumeCards.getByLabel('群像焦点（每行一项）', { exact: true }).fill('沈砚\n陆青禾')
  await volumeCards.getByLabel('本卷禁区（每行一项）', { exact: true }).fill('不提前揭露幕后人')
}

async function fillManualPlot(page) {
  const plotCards = page.locator('.planning-editor .manuscript-card')
  await expect(plotCards).toHaveCount(1)
  await expect(plotCards).toBeVisible()
  await plotCards.getByLabel('情节线名称', { exact: true }).fill('残卷来历')
  const plotType = plotCards.getByRole('combobox')
  await expect(plotType).toHaveCount(1)
  await plotType.selectOption('main')
  await plotCards.getByLabel('故事问题', { exact: true }).fill('残卷为何只在沈砚手中显字？')
  await plotCards.getByLabel('未来走向', { exact: true }).fill('线索从边城指向京城旧档。')
  await plotCards.getByLabel('预期回报', { exact: true }).fill('揭开第一层来历。')
  await plotCards.getByLabel('相关人物（每行一项）', { exact: true }).fill('沈砚\n陆青禾')
}

async function fillManualStoryBlock(page) {
  const block = page.locator('.story-block-card')
  await expect(block).toHaveCount(1)
  await expect(block).toBeVisible()
  await block.getByLabel('故事块标题', { exact: true }).fill('夜渡封锁线')
  const volumeAssociation = block.locator('.block-fields select')
  await expect(volumeAssociation).toHaveCount(1)
  await volumeAssociation.selectOption({ index: 1 })
  const plotAssociation = block.getByRole('checkbox')
  await expect(plotAssociation).toHaveCount(1)
  await plotAssociation.check()
  await block.getByLabel('进入情境', { exact: true }).fill('二人被困在废弃驿站。')
  await block.getByLabel('故事块目标', { exact: true }).fill('穿过封锁线。')
  await block.getByLabel('主要压力', { exact: true }).fill('追兵压缩路线。')
  await block.getByLabel('预期变化', { exact: true }).fill('二人建立信任。')
  await block.getByLabel('开放问题（每行一项）', { exact: true }).fill('内应是谁')
  await block.getByLabel('涉及人物（每行一项）', { exact: true }).fill('沈砚\n陆青禾')
  return block
}

async function createManualPlanning(page, title: string, runtime) {
  const created = await (async () => {
    let stage = 'navigation'
    try {
      await page.goto(volumes())
      stage = 'listener-check'
      assertRuntimeListenersAttached(runtime, 'before-planning-create')
      stage = 'wait-registration'
      const createdResponse = page.waitForResponse(response => isResponse(response, 'POST', planningDrafts()))
      stage = 'button-click'
      await page.getByRole('button', { name: '建立空白规划工作稿' }).click()
      stage = 'response-wait'
      return await createdResponse
    } catch (error) {
      void error
      throw new Error(`category=behavior leaf=planning-create-flow stage=${stage} method=POST path=/api/projects/:id/planning/drafts status=unavailable`)
    }
  })()
  const createdStatus = created.status()
  if (createdStatus !== 201) throw new Error(`category=behavior leaf=planning-create-status method=POST path=/api/projects/:id/planning/drafts status=${createdStatus}`)
  const requestStage = runtime.observationStage(created.request())
  const responseStage = runtime.observationStage(created)
  if (requestStage !== 'scheduled' || responseStage !== 'scheduled') throw new Error(`category=behavior leaf=observer-progress method=POST path=/api/projects/:id/planning/drafts status=201 requestStage=${requestStage} responseStage=${responseStage}`)
  const requestMatch = Number(runtime.requestObservationMatches(created.request(), 'POST', planningDrafts()))
  const responseMatch = Number(runtime.responseObservationMatches(created, 'POST', planningDrafts(), 201))
  if (!requestMatch || !responseMatch) throw new Error(`category=behavior leaf=observer-metadata method=POST path=/api/projects/:id/planning/drafts status=201 requestMatch=${requestMatch} responseMatch=${responseMatch}`)
  assertRuntimeListenersAttached(runtime, 'after-planning-create')
  await (async () => {
    let stage = 'ai-disabled'
    try {
      await expect(page.getByRole('button', { name: 'AI 生成当前规划工作稿' })).toBeDisabled()
      stage = 'add-volume'
      await page.getByRole('button', { name: '新增分卷' }).click()
      stage = 'fill-volume'
      await fillManualVolume(page, title)
      stage = 'settle-volume'
      await settleNavigationBoundary(page, runtime)
      stage = 'open-plots'
      await page.getByRole('link', { name: '情节线', exact: true }).click()
      stage = 'add-plot'
      await page.getByRole('button', { name: '新增情节线' }).click()
      stage = 'fill-plot'
      await fillManualPlot(page)
      stage = 'settle-plot'
      await settleNavigationBoundary(page, runtime)
      stage = 'open-blocks'
      await page.getByRole('link', { name: '故事块', exact: true }).click()
      stage = 'add-block'
      await page.getByRole('button', { name: '新增故事块' }).click()
      stage = 'fill-block'
      const block = await fillManualStoryBlock(page)
      stage = 'add-stage'
      await block.getByRole('button', { name: '新增阶段' }).click()
      const stageCard = block.locator('.stage-card')
      await expect(stageCard).toHaveCount(1)
      stage = 'fill-stage'
      await stageCard.getByLabel('阶段标题', { exact: true }).fill('寻找缺口')
      await stageCard.getByLabel('阶段目的', { exact: true }).fill('确认封锁薄弱处。')
      await stageCard.getByLabel('戏剧问题', { exact: true }).fill('能否在暴露前找到缺口？')
      stage = 'add-scene-task'
      await stageCard.getByRole('button', { name: '新增场景任务' }).click()
      const task = stageCard.locator('.scene-task')
      await expect(task).toHaveCount(1)
      stage = 'fill-scene-task'
      await task.getByLabel('场景任务', { exact: true }).fill('观察换岗。')
      await task.getByLabel('完成证据', { exact: true }).fill('取得换岗间隔。')
      stage = 'activate-block'
      const activate = block.getByRole('button', { name: '设为当前活动块', exact: true })
      const activateCount = await activate.count()
      if (activateCount === 1) await activate.click()
      if (activateCount > 1) throw new Error('ambiguous active story block control')
      stage = 'save-wait-registration'
      const savedResponse = page.waitForResponse(response => isResponse(response, 'PUT', draftPath(planningDrafts())))
      stage = 'save-click'
      await page.getByRole('button', { name: '保存工作稿' }).click()
      stage = 'save-response'
      expect((await savedResponse).status()).toBe(200)
      stage = 'preview-click'
      await page.getByRole('button', { name: '预览并确认' }).click()
      stage = 'confirm-wait-registration'
      const confirmedResponse = page.waitForResponse(response => isResponse(response, 'POST', confirmPath(planningDrafts())))
      stage = 'confirm-click'
      await page.getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()
      stage = 'confirm-response'
      expect((await confirmedResponse).status()).toBe(201)
      stage = 'final-settlement'
      await settleNavigationBoundary(page, runtime)
    } catch (error) {
      void error
      throw new Error(`category=behavior leaf=planning-manual-flow stage=${stage} method=unavailable path=unavailable status=unavailable`)
    }
  })()
}

async function createOutline(page, goal: string, runtime, { confirm = true, navigate = true, adoptionLabel = '采用小纲' } = {}) {
  let stage = 'navigation'
  try {
    if (navigate) await page.goto(blocks())
    stage = 'create-wait-registration'
    const createdResponse = page.waitForResponse(response => isResponse(response, 'POST', outlineDrafts()))
    stage = 'create-click'
    await page.getByRole('button', { name: '建立新工作稿' }).click()
    stage = 'create-response'
    expect((await createdResponse).status()).toBe(201)
    stage = 'outline-sheet'
    const outlineSheet = page.locator('.outline-sheet')
    await expect(outlineSheet).toHaveCount(1)
    await expect(outlineSheet).toBeVisible()
    stage = 'reference-selects'
    const references = outlineSheet.locator('.reference-grid select')
    await expect(references).toHaveCount(2)
    await references.nth(0).selectOption({ index: 1 })
    await references.nth(1).selectOption({ index: 1 })
    stage = 'stage-references'
    const stageReferences = outlineSheet.getByRole('group', { name: '关联阶段', exact: true }).getByRole('checkbox')
    await expect(stageReferences).toHaveCount(1)
    await stageReferences.check()
    stage = 'scene-task-references'
    const sceneTaskReferences = outlineSheet.getByRole('group', { name: '关联场景任务', exact: true }).getByRole('checkbox')
    await expect(sceneTaskReferences).toHaveCount(1)
    await sceneTaskReferences.check()
    stage = 'fill-goal'
    await outlineSheet.getByLabel('本章目标', { exact: true }).fill(goal)
    stage = 'fill-characters'
    await outlineSheet.getByLabel('预计出场人物（每行一项）', { exact: true }).fill('沈砚\n陆青禾')
    stage = 'fill-continuation'
    await outlineSheet.getByLabel('承接的未完成情节（每行一项）', { exact: true }).fill('承接被困局面')
    stage = 'fill-tasks'
    await outlineSheet.getByLabel('计划推进的任务（每行一项）', { exact: true }).fill('观察换岗')
    stage = 'fill-scenes'
    await outlineSheet.getByLabel('主要场景（每行一项）', { exact: true }).fill('废弃驿站侦察')
    stage = 'fill-forbidden'
    await outlineSheet.getByLabel('不应提前发生的内容（每行一项）', { exact: true }).fill('不可提前揭示内应')
    stage = 'save-wait-registration'
    const savedResponse = page.waitForResponse(response => isResponse(response, 'PUT', draftPath(outlineDrafts())))
    stage = 'save-click'
    await page.getByRole('button', { name: '保存小纲工作稿' }).click()
    stage = 'save-response'
    expect((await savedResponse).status()).toBe(200)
    if (confirm) {
      stage = 'preview-click'
      await page.getByRole('button', { name: adoptionLabel, exact: true }).click()
      stage = 'confirm-wait-registration'
      const confirmedResponse = page.waitForResponse(response => isResponse(response, 'POST', confirmPath(outlineDrafts())))
      stage = 'confirm-click'
      await page.getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()
      stage = 'confirm-response'
      expect((await confirmedResponse).status()).toBe(201)
      stage = 'final-settlement'
      await settleNavigationBoundary(page, runtime)
    }
  } catch (error) {
    void error
    throw new Error(`category=behavior leaf=outline-flow stage=${stage} method=unavailable path=unavailable status=unavailable`)
  }
}

async function createPlanningRevision(page, title: string, runtime) {
  let stage = 'navigation'
  try {
    await page.goto(volumes())
    stage = 'create-wait-registration'
    const createdResponse = page.waitForResponse(response => isResponse(response, 'POST', planningDrafts()))
    stage = 'create-click'
    await page.getByRole('button', { name: '建立空白规划工作稿' }).click()
    stage = 'create-response'
    expect((await createdResponse).status()).toBe(201)
    stage = 'volume-card'
    const volumeCards = page.locator('.planning-editor .manuscript-card')
    await expect(volumeCards).toHaveCount(1)
    await expect(volumeCards).toBeVisible()
    stage = 'fill-title'
    await volumeCards.getByLabel('卷名', { exact: true }).fill(title)
    stage = 'save-wait-registration'
    const savedResponse = page.waitForResponse(response => isResponse(response, 'PUT', draftPath(planningDrafts())))
    stage = 'save-click'
    await page.getByRole('button', { name: '保存工作稿' }).click()
    stage = 'save-response'
    expect((await savedResponse).status()).toBe(200)
    stage = 'preview-click'
    await page.getByRole('button', { name: '预览并确认' }).click()
    stage = 'confirm-wait-registration'
    const confirmedResponse = page.waitForResponse(response => isResponse(response, 'POST', confirmPath(planningDrafts())))
    stage = 'confirm-click'
    await page.getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()
    stage = 'confirm-response'
    expect((await confirmedResponse).status()).toBe(201)
    stage = 'final-settlement'
    await settleNavigationBoundary(page, runtime)
  } catch (error) {
    void error
    throw new Error(`category=behavior leaf=planning-revision-flow stage=${stage} method=unavailable path=unavailable status=unavailable`)
  }
}

async function assertWriterPreparationTarget(response, mode: 'create' | 'replay') {
  let action = 'unavailable'
  let target = 'unavailable'
  let status = 'unavailable'
  try {
    const responseStatus = response.status()
    if (Number.isInteger(responseStatus) && responseStatus >= 100 && responseStatus <= 599) status = String(responseStatus)
    const { nextAction, targetPath } = await response.json()
    action = nextAction === 'select_seed' ? 'select-seed'
      : nextAction === 'continue_contract' ? 'continue-contract'
        : nextAction === 'continue_bible' ? 'continue-bible'
          : nextAction === 'continue_planning' ? 'continue-planning'
            : nextAction === 'establish_planning' ? 'establish-planning'
              : nextAction === 'recover_planning_operation' ? 'recover-planning'
                : nextAction === 'recover_chapter_outline_operation' ? 'recover-outline'
                  : nextAction === 'prepare_chapter_outline' ? 'prepare-outline'
                    : nextAction === 'continue_chapter_outline' ? 'continue-outline'
                      : nextAction === 'start_chapter_session' ? 'start-session'
                        : nextAction === 'continue_writing' ? 'continue-writing' : 'unavailable'
    target = targetPath === writer() ? 'writer' : typeof targetPath === 'string' ? 'non-writer' : 'unavailable'
  } catch {}
  const expectedAction = mode === 'create' ? 'start-session' : 'continue-writing'
  if (status !== '200' || action !== expectedAction || target !== 'writer') {
    throw new Error(`category=behavior leaf=writer-preparation-target mode=${mode} action=${action} target=${target} method=GET path=/api/projects/:id/preparation status=${status}`)
  }
}

async function writerOverviewTargetKind(nextAction) {
  let actualHref
  try { actualHref = await nextAction.getAttribute('href') } catch { return 'other' }
  if (actualHref === null) return 'missing'
  const projectPrefix = `/projects/${PROJECT_ID}/`
  if (actualHref === `${projectPrefix}seeds`) return 'seeds'
  if (actualHref === `${projectPrefix}contract`) return 'contract'
  if (actualHref === `${projectPrefix}bible`) return 'bible'
  if (actualHref === `${projectPrefix}settings/models`) return 'model-settings'
  if (actualHref.startsWith(`${projectPrefix}write/chapters/`)) return 'writer-variant'
  if (actualHref.startsWith(`${projectPrefix}planning/story-blocks`)) return 'story-blocks-variant'
  if (actualHref.startsWith(`${projectPrefix}planning/volumes`)) return 'volumes-variant'
  if (actualHref.startsWith(`${projectPrefix}planning/plots`)) return 'plots-variant'
  if (actualHref.startsWith(`${projectPrefix}planning/`)) return 'planning-other'
  if (actualHref.startsWith(`${projectPrefix}write/`)) return 'write-other'
  if (actualHref.startsWith(projectPrefix)) return 'project-other'
  try {
    const parsed = new URL(actualHref)
    if (parsed.hostname === '127.0.0.1' && parsed.pathname.startsWith(projectPrefix)) return 'absolute-loopback'
  } catch { return 'other' }
  return 'other'
}

async function assertWriterOverviewActionHref(nextAction, mode: 'create' | 'replay') {
  try {
    await expect(nextAction).toHaveAttribute('href', writer())
  } catch (error) {
    void error
    const targetKind = await writerOverviewTargetKind(nextAction)
    throw new Error(`category=behavior leaf=writer-overview-target mode=${mode} target=${targetKind} method=unavailable path=unavailable status=unavailable`)
  }
}

async function navigateWriterThroughOverview(page, runtime, mode: 'create' | 'replay') {
  let stage = 'preparation-wait-registration'
  try {
    const sessionMethod = mode === 'create' ? 'POST' : 'GET'
    const expectedStatus = mode === 'create' ? 201 : 200
    await settleNavigationBoundary(page, runtime)
    const preparation = page.waitForResponse(response => isResponse(response, 'GET', `/api/projects/${PROJECT_ID}/preparation`))
    stage = 'overview-click'
    await page.getByRole('link', { name: '项目概览', exact: true }).click()
    stage = 'preparation-response'
    const preparationResponse = await preparation
    await assertWriterPreparationTarget(preparationResponse, mode)
    stage = 'overview-url'
    await expect.poll(() => new URL(page.url()).pathname).toBe(overview())
    const nextAction = page.locator('a.overview-next-action')
    stage = 'action-count'
    await expect(nextAction).toHaveCount(1)
    stage = 'action-href'
    await assertWriterOverviewActionHref(nextAction, mode)
    stage = 'session-wait-registration'
    const sessionResponse = page.waitForResponse(response => isResponse(response, sessionMethod, session()))
    stage = 'action-click'
    await nextAction.click()
    stage = 'session-response'
    expect((await sessionResponse).status()).toBe(expectedStatus)
    stage = 'writer-heading'
    await expect(page.getByRole('heading', { name: '章节工作台', exact: true })).toBeVisible()
    stage = 'final-settlement'
    await settleNavigationBoundary(page, runtime)
  } catch (error) {
    if (strictSafeBehaviorProjection(error)) throw error
    void error
    throw new Error(`category=behavior leaf=writer-overview-flow mode=${mode} stage=${stage} method=unavailable path=unavailable status=unavailable`)
  }
}

async function navigateOutlineAdjustmentThroughVisibleLink(page, runtime) {
  let stage = 'link-count'
  try {
    const adjustOutline = page.getByRole('link', { name: '调整本章小纲', exact: true })
    await expect(adjustOutline).toHaveCount(1)
    stage = 'link-visible'
    await expect(adjustOutline).toBeVisible()
    stage = 'link-click'
    await adjustOutline.click()
    stage = 'path'
    await expect.poll(() => new URL(page.url()).pathname).toBe(blocks())
    stage = 'workspace-visible'
    await expect(page.getByText('调整本章小纲', { exact: true })).toBeVisible()
    stage = 'settlement'
    await settleNavigationBoundary(page, runtime)
  } catch (error) {
    void error
    throw new Error(`category=behavior leaf=writer-outline-navigation stage=${stage} method=unavailable path=unavailable status=unavailable`)
  }
}

async function runFoundationStage(stage, action) {
  try { return await action() } catch (error) {
    if (strictSafeBehaviorProjection(error)) throw error
    void error
    throw new Error(`category=behavior leaf=foundation-stage stage=${stage} method=unavailable path=unavailable status=unavailable`)
  }
}

async function runScenarioStage(kind, stage, action) {
  try { return await action() } catch (error) {
    if (strictSafeBehaviorProjection(error)) throw error
    void error
    throw new Error(`category=behavior leaf=${kind} stage=${stage} method=unavailable path=unavailable status=unavailable`)
  }
}

test('foundation-manual-r1: complete Phase 2 UI, manually confirm R1, and show Canon-0 empty text', async ({ page }) => {
  await runAudited(page, () => [...phase2PreparationWrites(),
    { method: 'POST', path: planningDrafts(), count: 1, statuses: [201] },
    { method: 'PUT', path: draftPath(planningDrafts()), count: 1, statuses: [200] },
    { method: 'POST', path: confirmPath(planningDrafts()), count: 1, statuses: [201] },
  ], async runtime => {
    await runFoundationStage('create-project', () => createProjectUi(page, runtime))
    await runFoundationStage('phase2-preparation', () => completePhase2PreparationUi(page, runtime))
    await runFoundationStage('disable-planning-model', () => disablePlanningModelUi(page, runtime))
    await runFoundationStage('manual-planning', () => createManualPlanning(page, '手工规划 R1', runtime))
    await runFoundationStage('post-planning', async () => {
      await settleNavigationBoundary(page, runtime)
      const planningVersions = page.getByLabel('规划版本')
      await expect(planningVersions).toHaveCount(1)
      await expect(planningVersions).toBeVisible()
      const confirmedRevision = planningVersions.getByText('R1', { exact: true })
      await expect(confirmedRevision).toHaveCount(1)
      await expect(confirmedRevision).toBeVisible()
      const actualProgress = page.getByRole('complementary', { name: '正文已发生', exact: true })
      await expect(actualProgress).toHaveCount(1)
      await expect(actualProgress).toBeVisible()
      const canonZero = actualProgress.getByText('尚无已定稿事实', { exact: true })
      await expect(canonZero).toHaveCount(1)
      await expect(canonZero).toBeVisible()
    })
  })
})

test('revision-outline-session: clone future design, keep R1 history, and create Session only after Outline confirmation', async ({ page }) => {
  await runAudited(page, () => [...phase2PreparationWrites(),
    { method: 'POST', path: planningDrafts(), count: 2, statuses: [201] },
    { method: 'PUT', path: draftPath(planningDrafts()), count: 2, statuses: [200] },
    { method: 'POST', path: confirmPath(planningDrafts()), count: 2, statuses: [201] },
    { method: 'POST', path: outlineDrafts(), count: 1, statuses: [201] },
    { method: 'PUT', path: draftPath(outlineDrafts()), count: 1, statuses: [200] },
    { method: 'POST', path: confirmPath(outlineDrafts()), count: 1, statuses: [201] },
    { method: 'POST', path: session(), count: 1, statuses: [201] },
  ], async runtime => {
    await runScenarioStage('revision-outline-session', 'create-project', () => createProjectUi(page, runtime))
    await runScenarioStage('revision-outline-session', 'phase2-preparation', () => completePhase2PreparationUi(page, runtime))
    await runScenarioStage('revision-outline-session', 'disable-planning-model', () => disablePlanningModelUi(page, runtime))
    await runScenarioStage('revision-outline-session', 'manual-planning', () => createManualPlanning(page, '规划 R1', runtime))
    await runScenarioStage('revision-outline-session', 'verify-r1', async () => {
      const currentPlanningVersions = page.getByLabel('规划版本')
      await expect(currentPlanningVersions).toHaveCount(1)
      await expect(currentPlanningVersions).toBeVisible()
      const currentR1 = currentPlanningVersions.getByText('R1', { exact: true })
      await expect(currentR1).toHaveCount(1)
      await expect(currentR1).toBeVisible()
    })
    await runScenarioStage('revision-outline-session', 'planning-revision', () => createPlanningRevision(page, '修订规划 R2', runtime))
    await runScenarioStage('revision-outline-session', 'history-r1', async () => {
      await page.getByRole('button', { name: '修订历史' }).click()
      const planningHistory = page.getByRole('dialog', { name: '规划修订历史', exact: true })
      await expect(planningHistory).toHaveCount(1)
      await expect(planningHistory).toBeVisible()
      const historicalR1 = planningHistory.getByText('R1', { exact: true })
      await expect(historicalR1).toHaveCount(1)
      await expect(historicalR1).toBeVisible()
      await planningHistory.getByRole('button', { name: '关闭' }).click()
    })
    await runScenarioStage('revision-outline-session', 'outline-before-confirm', async () => {
      let sessionPosts = 0
      page.on('request', request => { if (request.method() === 'POST' && pathname(request.url()) === session()) sessionPosts += 1 })
      await createOutline(page, '确认前不得创建会话', runtime, { confirm: false })
      expect(sessionPosts, 'zero Session POST before confirmation').toBe(0)
    })
    await runScenarioStage('revision-outline-session', 'outline-confirm', async () => {
      await page.getByRole('button', { name: '采用小纲', exact: true }).click()
      await page.getByRole('dialog').getByRole('button', { name: '确认并签印' }).click()
      await settleNavigationBoundary(page, runtime)
    })
    await runScenarioStage('revision-outline-session', 'writer-session', async () => {
      await page.goto(writer())
      await expect(page.getByText('Planning R2')).toBeVisible()
      await expect(page.getByText('Outline R1')).toBeVisible()
      await settleNavigationBoundary(page, runtime)
    })
  })
})

test('outline-adjustment-before-finalization: adopt r2 through visible navigation while retaining body and making candidate basis explicit', async ({ page }) => {
  await runAudited(page, () => [...phase2PreparationWrites(),
    { method: 'POST', path: planningDrafts(), count: 1, statuses: [201] },
    { method: 'PUT', path: draftPath(planningDrafts()), count: 1, statuses: [200] },
    { method: 'POST', path: confirmPath(planningDrafts()), count: 1, statuses: [201] },
    { method: 'POST', path: outlineDrafts(), count: 2, statuses: [201] },
    { method: 'PUT', path: draftPath(outlineDrafts()), count: 2, statuses: [200] },
    { method: 'POST', path: confirmPath(outlineDrafts()), count: 2, statuses: [201] },
    { method: 'POST', path: session(), count: 1, statuses: [201] },
    { method: 'PUT', path: workingDraftPath(), count: 1, statuses: [200] },
    { method: 'POST', path: candidatePath(), count: 2, statuses: [201] },
  ], async runtime => {
    await runScenarioStage('outline-adjustment-before-finalization', 'create-project', () => createProjectUi(page, runtime))
    await runScenarioStage('outline-adjustment-before-finalization', 'phase2-preparation', () => completePhase2PreparationUi(page, runtime))
    await runScenarioStage('outline-adjustment-before-finalization', 'disable-planning-model', () => disablePlanningModelUi(page, runtime))
    await runScenarioStage('outline-adjustment-before-finalization', 'manual-planning', () => createManualPlanning(page, '规划 R1', runtime))
    await runScenarioStage('outline-adjustment-before-finalization', 'outline-r1', () => createOutline(page, 'R1 小纲', runtime))
    await runScenarioStage('outline-adjustment-before-finalization', 'writer-entry', () => navigateWriterThroughOverview(page, runtime, 'create'))
    await runScenarioStage('outline-adjustment-before-finalization', 'working-draft-save', async () => {
      const workingDraft = page.getByPlaceholder('在这里手动输入、粘贴或继续编辑章节正文。AI 生成只会进入工作稿，不会自动保存候选。', { exact: true })
      await workingDraft.fill('正文 A 保持不变。')
      const savedResponse = page.waitForResponse(response => isResponse(response, 'PUT', workingDraftPath()))
      await page.getByRole('button', { name: '保存工作稿', exact: true }).click()
      expect((await savedResponse).status()).toBe(200)
    })
    await runScenarioStage('outline-adjustment-before-finalization', 'candidate-a-save', async () => {
      const saveCandidate = page.getByRole('button', { name: '保存为候选', exact: true })
      const savedResponse = page.waitForResponse(response => isResponse(response, 'POST', candidatePath()))
      await saveCandidate.click()
      expect((await savedResponse).status()).toBe(201)
      const candidateRows = page.locator('.candidate-list > li')
      await expect(candidateRows).toHaveCount(1)
      await expect(candidateRows.nth(0)).toContainText('依据当前小纲')
      await expect(saveCandidate).toBeEnabled()
    })
    await runScenarioStage('outline-adjustment-before-finalization', 'outline-link-navigation', () => navigateOutlineAdjustmentThroughVisibleLink(page, runtime))
    await runScenarioStage('outline-adjustment-before-finalization', 'outline-r2', () => createOutline(page, 'R2 小纲', runtime, { navigate: false, adoptionLabel: '更新当前小纲' }))
    await runScenarioStage('outline-adjustment-before-finalization', 'writer-return-navigation', () => navigateWriterThroughOverview(page, runtime, 'replay'))
    await runScenarioStage('outline-adjustment-before-finalization', 'preserved-draft-and-stale-a', async () => {
      const workingDraft = page.getByPlaceholder('在这里手动输入、粘贴或继续编辑章节正文。AI 生成只会进入工作稿，不会自动保存候选。', { exact: true })
      await expect(workingDraft).toHaveValue('正文 A 保持不变。')
      const candidateRows = page.locator('.candidate-list > li')
      await expect(candidateRows).toHaveCount(1)
      await expect(candidateRows.nth(0)).toContainText('依据旧小纲，不能定稿')
    })
    await runScenarioStage('outline-adjustment-before-finalization', 'candidate-b-save', async () => {
      const savedResponse = page.waitForResponse(response => isResponse(response, 'POST', candidatePath()))
      await page.getByRole('button', { name: '保存为候选', exact: true }).click()
      expect((await savedResponse).status()).toBe(201)
    })
    await runScenarioStage('outline-adjustment-before-finalization', 'current-b', async () => {
      const candidateRows = page.locator('.candidate-list > li')
      await expect(candidateRows).toHaveCount(2)
      await expect(candidateRows.nth(0)).toContainText('依据旧小纲，不能定稿')
      await expect(candidateRows.nth(1)).toContainText('依据当前小纲')
    })
    await runScenarioStage('outline-adjustment-before-finalization', 'final-settlement', async () => {
      await settleNavigationBoundary(page, runtime)
    })
  })
})

test('pinned-session: Session retains historical Planning and Outline pins after Planning Head advances and Writer refreshes', async ({ page }) => {
  await runAudited(page, () => [...phase2PreparationWrites(),
    { method: 'POST', path: planningDrafts(), count: 2, statuses: [201] },
    { method: 'PUT', path: draftPath(planningDrafts()), count: 2, statuses: [200] },
    { method: 'POST', path: confirmPath(planningDrafts()), count: 2, statuses: [201] },
    { method: 'POST', path: outlineDrafts(), count: 1, statuses: [201] },
    { method: 'PUT', path: draftPath(outlineDrafts()), count: 1, statuses: [200] },
    { method: 'POST', path: confirmPath(outlineDrafts()), count: 1, statuses: [201] },
    { method: 'POST', path: session(), count: 1, statuses: [201] },
  ], async runtime => {
    await runScenarioStage('pinned-session', 'create-project', () => createProjectUi(page, runtime))
    await runScenarioStage('pinned-session', 'phase2-preparation', () => completePhase2PreparationUi(page, runtime))
    await runScenarioStage('pinned-session', 'disable-planning-model', () => disablePlanningModelUi(page, runtime))
    await runScenarioStage('pinned-session', 'manual-planning', () => createManualPlanning(page, '规划 R1', runtime))
    await runScenarioStage('pinned-session', 'outline', () => createOutline(page, 'R1 小纲', runtime))
    await runScenarioStage('pinned-session', 'writer-before', async () => {
      await page.goto(writer())
      await expect(page.getByText('Planning R1')).toBeVisible()
      await expect(page.getByText('Outline R1')).toBeVisible()
      await settleNavigationBoundary(page, runtime)
    })
    await runScenarioStage('pinned-session', 'planning-revision', () => createPlanningRevision(page, '规划 R2', runtime))
    await runScenarioStage('pinned-session', 'writer-after', async () => {
      await page.goto(writer())
      await settleNavigationBoundary(page, runtime)
      await page.reload()
      await expect(page.getByText('Planning R1')).toBeVisible()
      await expect(page.getByText('Outline R1')).toBeVisible()
      await settleNavigationBoundary(page, runtime)
    })
  })
})

test('baseline-lock: the first Seed, Contract, and Bible stay immutable after a visible stale Bible confirmation conflict', async ({ page }) => {
  let staleBiblePage
  await runAudited(page, baselineLockWrites, async runtime => {
    await runScenarioStage('baseline-lock', 'create-project', () => createProjectUi(page, runtime))
    await runScenarioStage('baseline-lock', 'phase2-preparation', () => completePhase2PreparationUi(page, runtime, {
      beforeBibleConfirm: async () => {
        staleBiblePage = await page.context().newPage()
        await staleBiblePage.goto(`/projects/${PROJECT_ID}/bible`)
        await expect(staleBiblePage.getByRole('button', { name: '预览并确认', exact: true })).toBeVisible()
        await staleBiblePage.getByRole('button', { name: '预览并确认', exact: true }).click()
        await expect(staleBiblePage.getByRole('dialog', { name: '确认创作圣经', exact: true })).toBeVisible()
      },
    }))
    await runScenarioStage('baseline-lock', 'seed-lock-view', () => assertBaselineSeedLockUi(page, runtime))
    await runScenarioStage('baseline-lock', 'contract-lock-view', async () => {
      await page.goto(`/projects/${PROJECT_ID}/contract`)
      await expect(page.getByRole('heading', { name: '已确认，作为项目永久基线', exact: true })).toBeVisible()
      await expect(page.getByText('IMMUTABLE REVISION · R1', { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '普通字段手动录入', exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: '一次确认完整契约', exact: true })).toHaveCount(0)
      await settleNavigationBoundary(page, runtime)
    })
    await runScenarioStage('baseline-lock', 'bible-lock-view', async () => {
      await page.goto(`/projects/${PROJECT_ID}/bible`)
      await expect(page.getByText('已确认，作为项目永久基线。', { exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: '生成创作圣经', exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: '手动保存', exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: '预览并确认', exact: true })).toHaveCount(0)
    })
    await runScenarioStage('baseline-lock', 'stale-bible-confirm', () => assertBaselineStaleBibleConfirmUi(staleBiblePage))
    await runScenarioStage('baseline-lock', 'stale-bible-reload', async () => {
      await staleBiblePage.getByRole('dialog', { name: '确认创作圣经', exact: true }).getByRole('button', { name: '重新加载权威版本', exact: true }).click()
      await expect(staleBiblePage.getByText('已确认，作为项目永久基线。', { exact: true })).toBeVisible()
    })
    await runScenarioStage('baseline-lock', 'final-baseline-reload', async () => {
      await page.goto(`/projects/${PROJECT_ID}/seeds`)
      await expect(page.getByText('选定代次 1', { exact: true })).toBeVisible()
      await settleNavigationBoundary(page, runtime)
      await page.goto(`/projects/${PROJECT_ID}/contract`)
      await expect(page.getByText('IMMUTABLE REVISION · R1', { exact: true })).toBeVisible()
      await settleNavigationBoundary(page, runtime)
      await page.goto(`/projects/${PROJECT_ID}/bible`)
      await page.getByRole('button', { name: '修订历史', exact: true }).click()
      await expect(page.getByText('Revision 1', { exact: true })).toHaveCount(1)
      await settleNavigationBoundary(page, runtime)
    })
  }, { runtimeAuditOptions: () => phase3RuntimeAuditOptions(PROJECT_ID, { allowStaleBibleConfirm409: true, contractDraft404Count: 3 }) })
})

test('archived-navigation: archive through UI, then back, forward, and refresh all canonical Planning routes read-only', async ({ page }) => {
  await runAudited(page, () => [...phase2PreparationWrites(),
    { method: 'POST', path: planningDrafts(), count: 1, statuses: [201] },
    { method: 'PUT', path: draftPath(planningDrafts()), count: 1, statuses: [200] },
    { method: 'POST', path: confirmPath(planningDrafts()), count: 1, statuses: [201] },
    { method: 'POST', path: outlineDrafts(), count: 1, statuses: [201] },
    { method: 'PUT', path: draftPath(outlineDrafts()), count: 1, statuses: [200] },
    { method: 'POST', path: confirmPath(outlineDrafts()), count: 1, statuses: [201] },
    { method: 'POST', path: `/api/projects/${PROJECT_ID}/archive`, count: 1, statuses: [200] },
  ], async runtime => {
    await runScenarioStage('archived-navigation', 'create-project', () => createProjectUi(page, runtime))
    await runScenarioStage('archived-navigation', 'phase2-preparation', () => completePhase2PreparationUi(page, runtime))
    await runScenarioStage('archived-navigation', 'disable-planning-model', () => disablePlanningModelUi(page, runtime))
    await runScenarioStage('archived-navigation', 'manual-planning', () => createManualPlanning(page, '规划 R1', runtime))
    await runScenarioStage('archived-navigation', 'outline', () => createOutline(page, '归档前小纲', runtime))
    await runScenarioStage('archived-navigation', 'archive', async () => {
      await page.goto('/projects')
      const card = page.locator('.project-card').filter({
        has: page.getByRole('heading', { name: 'Phase 3 foundation', exact: true }),
      })
      await expect(card).toHaveCount(1)
      await expect(card).toBeVisible()
      await settleNavigationBoundary(page, runtime)
      await card.getByText('更多', { exact: true }).click()
      const archivedResponse = page.waitForResponse(response => isResponse(response, 'POST', `/api/projects/${PROJECT_ID}/archive`))
      await card.getByRole('button', { name: '归档', exact: true }).click()
      expect((await archivedResponse).status()).toBe(200)
      await settleNavigationBoundary(page, runtime)
    })
    await runScenarioStage('archived-navigation', 'volumes-readonly', async () => {
      await page.goto(volumes())
      await settleNavigationBoundary(page, runtime)
      await expect(page.getByText('当前项目或规划修订为只读状态；可以查阅正文规划与历史，不能克隆、编辑或写入。')).toBeVisible()
      await expect(page.getByRole('button', { name: '建立空白规划工作稿' })).toHaveCount(0)
      await page.reload()
      await settleNavigationBoundary(page, runtime)
      await expect(page.getByText('当前项目或规划修订为只读状态；可以查阅正文规划与历史，不能克隆、编辑或写入。')).toBeVisible()
      await expect(page.getByRole('button', { name: '建立空白规划工作稿' })).toHaveCount(0)
    })
    await runScenarioStage('archived-navigation', 'plots-navigation', async () => {
      await page.getByRole('link', { name: '情节线', exact: true }).click()
      await expect(page).toHaveURL(new RegExp(`${plots()}$`, 'u'))
      await expect(page.getByText('当前项目或规划修订为只读状态；可以查阅正文规划与历史，不能克隆、编辑或写入。')).toBeVisible()
    })
    await runScenarioStage('archived-navigation', 'browser-history', async () => {
      await page.goBack()
      await expect(page).toHaveURL(new RegExp(`${volumes()}$`, 'u'))
      await expect(page.getByRole('button', { name: '建立空白规划工作稿' })).toHaveCount(0)
      await page.goForward()
      await expect(page).toHaveURL(new RegExp(`${plots()}$`, 'u'))
      await page.reload()
      await expect(page.getByText('当前项目或规划修订为只读状态；可以查阅正文规划与历史，不能克隆、编辑或写入。')).toBeVisible()
    })
    await runScenarioStage('archived-navigation', 'blocks-readonly', async () => {
      await page.getByRole('link', { name: '故事块', exact: true }).click()
      await expect(page).toHaveURL(new RegExp(`${blocks()}$`, 'u'))
      await expect(page.getByText('当前项目或规划修订为只读状态；可以查阅正文规划与历史，不能克隆、编辑或写入。')).toBeVisible()
      await expect(page.getByText('当前小纲为只读权威记录；本地字段与正式引用均不会被改写。')).toBeVisible()
      await page.goBack()
      await expect(page).toHaveURL(new RegExp(`${plots()}$`, 'u'))
      await page.goForward()
      await expect(page).toHaveURL(new RegExp(`${blocks()}$`, 'u'))
      await page.reload()
      await expect(page.getByText('当前小纲为只读权威记录；本地字段与正式引用均不会被改写。')).toBeVisible()
      await settleNavigationBoundary(page, runtime)
    })
  })
})
