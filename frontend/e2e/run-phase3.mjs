import { randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import {
  assertDatabaseName,
  createDatabaseName,
  createOwnedRoot,
  removeOwnedRoot,
  reserveLocalPort,
  runBoundedOwnedCommand,
  runOwnedProductLifecycle,
  startOwnedServer,
  stopOwnedServer,
  validateTestEnvironment,
  waitForOwnedServer,
} from './support/product-runner.mjs'
import { assertDatabaseResidue } from './support/database-residue.mjs'
import { DENY_PROXY_SOURCE, assertDenyProxyLedger } from './support/deny-proxy.mjs'
import { collectLeafFailures, redactDiagnostic } from './support/safe-diagnostics.mjs'
import { assertNoPrivateEvidenceMarkers, runtimeSensitiveValues } from './runtime-observer.mjs'

export const FORMAL_SPECS = Object.freeze(['phase3-story-planning.spec.ts'])
export const FORMAL_CONFIG = 'playwright.phase3.config.ts'
export const FORMAL_SCENARIOS = Object.freeze([
  'foundation-manual-r1',
  'revision-outline-session',
  'unused-outline-supersession',
  'pinned-session',
  'baseline-lock',
  'archived-navigation',
])

const here = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(here, '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const OWNED_ROOT_PREFIX = 'novel-creator-phase3-'
const DEADLINES = Object.freeze({ commandMs: 90_000, healthMs: 45_000, browserMs: 180_000, stopMs: 8_000 })
const SAFE_MARKERS = Object.freeze(['prompt', 'manifest', 'raw provider', 'corpus', 'api key', 'authorization', 'password', 'dsn'])
// Server logs include normal public method/path/status access records. Keep
// their scanner precise: dynamic secrets plus raw-provider field names, never
// bare public route words such as "corpus" or "prompt".
export const OWNED_SERVER_LOG_MARKERS = Object.freeze([
  'inputManifest', 'InputManifest', 'INPUT_MANIFEST',
  'manifest=', 'manifest: ', '"manifest":',
  'prompt=', 'prompt: ', '"prompt":',
  'corpusText', 'CorpusText', 'CORPUS_TEXT', 'corpus_text',
  'apiKey', 'ApiKey', 'API_KEY', 'api_key',
  'password=', 'password: ', '"password":',
  'dsn=', 'dsn: ', '"dsn":', 'DSN=',
  'rawOutput', 'RawOutput', 'RAW_OUTPUT', 'raw_output',
  'providerOutput', 'ProviderOutput', 'PROVIDER_OUTPUT', 'provider_output',
  'rawProviderOutput', 'RawProviderOutput', 'RAW_PROVIDER_OUTPUT', 'raw_provider_output',
  'Authorization: Bearer', 'authorization: bearer',
])
const phase3FailureContexts = new WeakMap()
const FAKE_PROVIDER_SOURCE = String.raw`
const http = require('node:http')
const port = Number(process.argv[2])
const nonce = process.env.M2_BROWSER_RUN_NONCE
function send(response, status, value) { response.writeHead(status, { 'content-type': 'application/json' }); response.end(JSON.stringify(value)) }
function bible() { return { premiseAndPromise: '证据与代价共同推动选择。', worldRules: [{ id: 'rule-1', text: '每次选择都留下代价。' }], powerOrProgressionSystem: '成长来自训练与承担。', protagonist: '沈砚谨慎、重证据并愿意承担代价。', coreCast: [{ id: 'cast-1', text: '同伴有独立目标。' }], factions: [{ id: 'faction-1', text: '势力围绕秩序竞争。' }], longTermConflicts: [{ id: 'conflict-1', text: '真相与秩序冲突。' }], relationshipDynamics: [{ id: 'relation-1', text: '信任通过共同选择建立。' }], toneAndNarrativeBoundaries: '克制叙事。', continuityGuardrails: [{ id: 'guard-1', text: '代价不可无条件撤销。' }], openDesignQuestions: [{ id: 'question-1', text: '谁先承担代价？' }] } }
const server = http.createServer(async (request, response) => {
  if (request.method === 'GET' && request.url === '/health') return send(response, 200, { browserRunNonce: nonce })
  if (request.method !== 'POST' || request.url !== '/v1/chat/completions') return send(response, 404, { error: { code: 'not_found' } })
  const chunks = []; for await (const chunk of request) chunks.push(chunk)
  let body; try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')) } catch { return send(response, 400, { error: { code: 'invalid_json' } }) }
  let instruction = {}; let evidence = {}; try { instruction = JSON.parse(body.messages?.[0]?.content || '{}'); evidence = JSON.parse(body.messages?.[1]?.content || '{}') } catch {}
  const content = instruction.task === 'Rank only the supplied eligible asset and corpus candidates.'
    ? { assetRecommendations: evidence.assetCandidates?.[0] ? [{ assetRevisionId: evidence.assetCandidates[0].assetRevisionId, reason: 'fixture recommendation', confidence: 0.2 }] : [], corpusRecommendations: [] }
    : bible()
  send(response, 200, { choices: [{ message: { role: 'assistant', content: JSON.stringify(content) } }] })
})
server.listen(port, '127.0.0.1')
`

export function validateSpecs(specs) {
  if (!Array.isArray(specs) || specs.length !== 1 || specs[0] !== FORMAL_SPECS[0]) {
    throw new Error('Phase 3 requires its one exact formal browser spec')
  }
  return [...FORMAL_SPECS]
}

export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList) || argumentsList.length !== 0) {
    throw new Error('Phase 3 browser runner does not accept spec paths')
  }
  return [...FORMAL_SPECS]
}

function resolveScenarios(environment) {
  const focus = environment.PHASE3_FOCUS_SCENARIO
  if (!focus) return [...FORMAL_SCENARIOS]
  if (!FORMAL_SCENARIOS.includes(focus)) throw new Error('PHASE3_FOCUS_SCENARIO must name one formal scenario')
  return [focus]
}

function childOptions(cwd, env) {
  return { cwd, env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true }
}

function buildViteConfig(baseConfigUrl, ownedRoot) {
  return [
    `import base from ${JSON.stringify(baseConfigUrl)}`,
    'export default { ...base,',
    `  cacheDir: ${JSON.stringify(path.join(ownedRoot, 'vite-cache'))},`,
    '  optimizeDeps: { ...base.optimizeDeps, noDiscovery: false },',
    '}',
  ].join('\n')
}

function assertSafeFiles(root, sensitiveValues) {
  if (!existsSync(root)) return
  const stack = [root]
  while (stack.length) {
    const entry = stack.pop()
    for (const child of readdirSync(entry, { withFileTypes: true })) {
      const target = path.join(entry, child.name)
      if (child.isDirectory()) stack.push(target)
      else if (child.isFile()) {
        const text = readFileSync(target, 'utf8')
        assertNoPrivateEvidenceMarkers([text])
        for (const sensitive of sensitiveValues) if (sensitive && text.includes(sensitive)) throw new Error('Phase 3 artifact contains sensitive evidence')
      }
    }
  }
}

function assertSafeTextFile(target, sensitiveValues) {
  const text = readFileSync(target, 'utf8')
  assertNoPrivateEvidenceMarkers([text])
  for (const sensitive of sensitiveValues) {
    if (sensitive && text.includes(sensitive)) {
      throw new Error('Phase 3 artifact contains sensitive evidence')
    }
  }
}

export function auditAndRemovePhase3Root({
  ownedRoot,
  denyLedgerPath,
  artifactRoot,
  safeAuditPaths,
  sensitiveValues,
  readFile = readFileSync,
  assertDenyLedger = assertDenyProxyLedger,
  assertArtifacts = assertSafeFiles,
  assertSafeFile = assertSafeTextFile,
  removeRoot = removeOwnedRoot,
  rootExists = existsSync,
}) {
  const errors = []
  let denyAudit = null
  let denyAuditChecked = false
  let rootRemoved = false
  try {
    if (denyLedgerPath) {
      denyAuditChecked = true
      denyAudit = assertDenyLedger(readFile(denyLedgerPath, 'utf8'))
    }
  } catch (error) { errors.push(error) }
  try {
    if (artifactRoot) assertArtifacts(artifactRoot, sensitiveValues)
    for (const target of safeAuditPaths) assertSafeFile(target, sensitiveValues)
  } catch (error) { errors.push(error) }
  try {
    removeRoot(ownedRoot, OWNED_ROOT_PREFIX)
    rootRemoved = !rootExists(ownedRoot)
  } catch (error) { errors.push(error) }
  return { denyAudit, denyAuditChecked, rootRemoved, errors }
}

export async function exercisePhase3Lifecycle({
  registerRoot,
  initialize,
  cleanupServers,
  cleanupReservations,
  cleanupDatabase,
  cleanupRoot,
}) {
  return runOwnedProductLifecycle({
    async body(lifecycle) {
      // Root registration is deliberately first: even a failed initialization
      // must leave a bounded cleanup target under runner ownership.
      registerRoot(lifecycle)
      return initialize(lifecycle)
    },
    stopServer: cleanupServers,
    releaseReservation: cleanupReservations,
    dropDatabase: cleanupDatabase,
    removeRoot: cleanupRoot,
  })
}

function browserReportTests(suites, tests = []) {
  for (const suite of suites || []) {
    for (const spec of suite?.specs || []) {
      for (const item of spec?.tests || []) {
        tests.push({ specTitle: String(spec?.title || ''), test: item })
      }
    }
    browserReportTests(suite?.suites, tests)
  }
  return tests
}

function browserReportSpecs(suites, specs = []) {
  for (const suite of suites || []) {
    for (const spec of suite?.specs || []) specs.push(spec)
    browserReportSpecs(suite?.suites, specs)
  }
  return specs
}

function browserFailureMessages(value, messages = [], seen = new Set()) {
  if (!value || typeof value !== 'object' || seen.has(value)) return messages
  seen.add(value)
  if (typeof value.message === 'string') messages.push(value.message)
  for (const nested of [value.errors, value.error, value.cause]) {
    if (Array.isArray(nested)) {
      for (const item of nested) browserFailureMessages(item, messages, seen)
    } else browserFailureMessages(nested, messages, seen)
  }
  return messages
}

function safeApiPath(value) {
  const pathValue = String(value || '')
  if (!/^\/api\/projects\/(?:[A-Za-z0-9-]+|:id)(?:\/[A-Za-z0-9._~:-]+)*$/u.test(pathValue)) return null
  return pathValue.replace(/\/[0-9a-f]{8}-[0-9a-f-]{27,}/giu, '/:id')
}

function safeRuntimeApiPath(value) {
  const pathValue = String(value || '')
  if (!/^\/api(?:\/[A-Za-z0-9._~:-]+)*$/u.test(pathValue)) return null
  return pathValue.replace(/\/[0-9a-f]{8}-[0-9a-f-]{27,}/giu, '/:id')
}

function safeSpecProjectionLine(message) {
  const auditStage = /^category=audit leaf=audit-stage stage=(settlement|dynamic-sensitive|private-marker|runtime-health|network-access|exact-writes) method=unavailable path=unavailable status=unavailable count=1$/u.exec(message)
  if (auditStage) {
    return `category=audit leaf=audit-stage stage=${auditStage[1]} method=unavailable path=unavailable status=unavailable count=1`
  }
  const healthSummary = /^category=audit leaf=runtime-health-summary responseFailureCount=(\d+) consoleErrorCount=(\d+) pageErrorCount=(\d+) requestFailureCount=(\d+) apiReadErrorCount=(\d+) requestReadErrorCount=(\d+) forbiddenRequestCount=(\d+) forbiddenResponseCount=(\d+) responseMethod=(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|unavailable) responsePath=(\/api(?:\/[A-Za-z0-9._~:-]+)*|unavailable) responseStatus=([1-5]\d{2}|unavailable) requestMethod=(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|unavailable) requestPath=(\/api(?:\/[A-Za-z0-9._~:-]+)*|unavailable) requestStatus=unavailable readMethod=(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS|unavailable) readPath=(\/api(?:\/[A-Za-z0-9._~:-]+)*|unavailable) readStatus=([1-5]\d{2}|unavailable) responseInventory=(none|(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS):\/api(?:\/[A-Za-z0-9._~:-]+)*:[1-5]\d{2}:[1-9]\d*(?:\|(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS):\/api(?:\/[A-Za-z0-9._~:-]+)*:[1-5]\d{2}:[1-9]\d*){0,7}) unavailableCount=(\d+) inventoryOmittedCount=(\d+) consoleKnownLinkedCount=(\d+) consoleOtherCount=(\d+)$/u.exec(message)
  if (healthSummary) {
    const [, responseFailureCount, consoleErrorCount, pageErrorCount, requestFailureCount, apiReadErrorCount, requestReadErrorCount, forbiddenRequestCount, forbiddenResponseCount, responseMethod, responsePath, responseStatus, requestMethod, requestPath, readMethod, readPath, readStatus, responseInventory, unavailableCount, inventoryOmittedCount, consoleKnownLinkedCount, consoleOtherCount] = healthSummary
    if (
      (responsePath !== 'unavailable' && !safeRuntimeApiPath(responsePath))
      || (requestPath !== 'unavailable' && !safeRuntimeApiPath(requestPath))
      || (readPath !== 'unavailable' && !safeRuntimeApiPath(readPath))
    ) return null
    if (Number(consoleKnownLinkedCount) + Number(consoleOtherCount) !== Number(consoleErrorCount)) return null
    return `category=audit leaf=runtime-health-summary responseFailureCount=${responseFailureCount} consoleErrorCount=${consoleErrorCount} pageErrorCount=${pageErrorCount} requestFailureCount=${requestFailureCount} apiReadErrorCount=${apiReadErrorCount} requestReadErrorCount=${requestReadErrorCount} forbiddenRequestCount=${forbiddenRequestCount} forbiddenResponseCount=${forbiddenResponseCount} responseMethod=${responseMethod} responsePath=${responsePath} responseStatus=${responseStatus} requestMethod=${requestMethod} requestPath=${requestPath} requestStatus=unavailable readMethod=${readMethod} readPath=${readPath} readStatus=${readStatus} responseInventory=${responseInventory} unavailableCount=${unavailableCount} inventoryOmittedCount=${inventoryOmittedCount} consoleKnownLinkedCount=${consoleKnownLinkedCount} consoleOtherCount=${consoleOtherCount}`
  }
  const runtimeListener = /^category=behavior leaf=runtime-listener stage=(after-model-settings|before-planning-create|after-planning-create) state=detached$/u.exec(message)
  if (runtimeListener) {
    return `category=behavior leaf=runtime-listener stage=${runtimeListener[1]} state=detached`
  }
  const planningCreateFlow = /^category=behavior leaf=planning-create-flow stage=(navigation|listener-check|wait-registration|button-click|response-wait) method=POST path=\/api\/projects\/:id\/planning\/drafts status=unavailable$/u.exec(message)
  if (planningCreateFlow) {
    return `category=behavior leaf=planning-create-flow stage=${planningCreateFlow[1]} method=POST path=/api/projects/:id/planning/drafts status=unavailable`
  }
  const planningCreateStatus = /^category=behavior leaf=planning-create-status method=POST path=\/api\/projects\/:id\/planning\/drafts status=([1-5]\d{2})$/u.exec(message)
  if (planningCreateStatus) {
    return `category=behavior leaf=planning-create-status method=POST path=/api/projects/:id/planning/drafts status=${planningCreateStatus[1]}`
  }
  const planningManualFlow = /^category=behavior leaf=planning-manual-flow stage=(ai-disabled|add-volume|fill-volume|settle-volume|open-plots|add-plot|fill-plot|settle-plot|open-blocks|add-block|fill-block|add-stage|fill-stage|add-scene-task|fill-scene-task|activate-block|save-wait-registration|save-click|save-response|preview-click|confirm-wait-registration|confirm-click|confirm-response|final-settlement) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (planningManualFlow) {
    return `category=behavior leaf=planning-manual-flow stage=${planningManualFlow[1]} method=unavailable path=unavailable status=unavailable`
  }
  const planningRevisionFlow = /^category=behavior leaf=planning-revision-flow stage=(navigation|create-wait-registration|create-click|create-response|volume-card|fill-title|save-wait-registration|save-click|save-response|preview-click|confirm-wait-registration|confirm-click|confirm-response|final-settlement) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (planningRevisionFlow) {
    return `category=behavior leaf=planning-revision-flow stage=${planningRevisionFlow[1]} method=unavailable path=unavailable status=unavailable`
  }
  const outlineFlow = /^category=behavior leaf=outline-flow stage=(navigation|create-wait-registration|create-click|create-response|outline-sheet|reference-selects|stage-references|scene-task-references|fill-goal|fill-characters|fill-continuation|fill-tasks|fill-scenes|fill-forbidden|save-wait-registration|save-click|save-response|preview-click|confirm-wait-registration|confirm-click|confirm-response|final-settlement) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (outlineFlow) {
    return `category=behavior leaf=outline-flow stage=${outlineFlow[1]} method=unavailable path=unavailable status=unavailable`
  }
  const seedSelectionCardCount = /^category=behavior leaf=seed-selection-card-count count=(zero|many)$/u.exec(message)
  if (seedSelectionCardCount) {
    return `category=behavior leaf=seed-selection-card-count count=${seedSelectionCardCount[1]}`
  }
  const phase2PreparationFlow = /^category=behavior leaf=phase2-preparation-flow stage=(seed-navigation|seed-editor|seed-save|seed-select|seed-settlement|contract-navigation|contract-manual|engine-save|style-save|asset-save|capacity-save|contract-confirm|contract-settlement|bible-navigation|bible-generate|bible-preview|bible-confirm|final-settlement) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (phase2PreparationFlow) {
    return `category=behavior leaf=phase2-preparation-flow stage=${phase2PreparationFlow[1]} method=unavailable path=unavailable status=unavailable`
  }
  const phase2SeedSelection = /^category=behavior leaf=phase2-seed-selection-flow stage=(card-count|card-visible|card-click|modal-visible|wait-registration|confirm-click|response|generation|settlement) method=(PUT|unavailable) path=(\/api\/projects\/:id\/selected-seed|unavailable) status=unavailable$/u.exec(message)
  if (phase2SeedSelection) {
    const [, stage, method, path] = phase2SeedSelection
    const writeStage = ['wait-registration', 'confirm-click', 'response', 'generation', 'settlement'].includes(stage)
    if ((writeStage && method === 'PUT' && path === '/api/projects/:id/selected-seed') || (!writeStage && method === 'unavailable' && path === 'unavailable')) {
      return `category=behavior leaf=phase2-seed-selection-flow stage=${stage} method=${method} path=${path} status=unavailable`
    }
  }
  const baselineSeedLock = /^category=behavior leaf=baseline-seed-lock stage=(navigation|settlement|saved-section|generation|new-absent|select-absent|edit-count|edit-disabled) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (baselineSeedLock) {
    return `category=behavior leaf=baseline-seed-lock stage=${baselineSeedLock[1]} method=unavailable path=unavailable status=unavailable`
  }
  const baselineStaleBibleUnavailable = /^category=behavior leaf=baseline-stale-bible stage=(wait-registration|click|response) method=POST path=\/api\/projects\/:id\/bible\/confirm status=unavailable$/u.exec(message)
  if (baselineStaleBibleUnavailable) {
    return `category=behavior leaf=baseline-stale-bible stage=${baselineStaleBibleUnavailable[1]} method=POST path=/api/projects/:id/bible/confirm status=unavailable`
  }
  const baselineStaleBibleStatus = /^category=behavior leaf=baseline-stale-bible stage=status method=POST path=\/api\/projects\/:id\/bible\/confirm status=([1-5]\d{2})$/u.exec(message)
  if (baselineStaleBibleStatus) {
    return `category=behavior leaf=baseline-stale-bible stage=status method=POST path=/api/projects/:id/bible/confirm status=${baselineStaleBibleStatus[1]}`
  }
  const baselineStaleBiblePublic = /^category=behavior leaf=baseline-stale-bible stage=(public-error|reload-action) method=POST path=\/api\/projects\/:id\/bible\/confirm status=409$/u.exec(message)
  if (baselineStaleBiblePublic) {
    return `category=behavior leaf=baseline-stale-bible stage=${baselineStaleBiblePublic[1]} method=POST path=/api/projects/:id/bible/confirm status=409`
  }
  const revisionOutlineSession = /^category=behavior leaf=revision-outline-session stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|verify-r1|planning-revision|history-r1|outline-before-confirm|outline-confirm|writer-session) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (revisionOutlineSession) {
    return `category=behavior leaf=revision-outline-session stage=${revisionOutlineSession[1]} method=unavailable path=unavailable status=unavailable`
  }
  const unusedOutlineSupersession = /^category=behavior leaf=unused-outline-supersession stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|outline|planning-revision|supersession-navigation|history-open|history-dialog|history-status|history-close|readonly-note|save-absent|final-settlement) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (unusedOutlineSupersession) {
    return `category=behavior leaf=unused-outline-supersession stage=${unusedOutlineSupersession[1]} method=unavailable path=unavailable status=unavailable`
  }
  const pinnedSession = /^category=behavior leaf=pinned-session stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|outline|writer-before|planning-revision|writer-after) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (pinnedSession) {
    return `category=behavior leaf=pinned-session stage=${pinnedSession[1]} method=unavailable path=unavailable status=unavailable`
  }
  const baselineLock = /^category=behavior leaf=baseline-lock stage=(create-project|phase2-preparation|seed-lock-view|contract-lock-view|bible-lock-view|stale-bible-confirm|stale-bible-reload|final-baseline-reload) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (baselineLock) {
    return `category=behavior leaf=baseline-lock stage=${baselineLock[1]} method=unavailable path=unavailable status=unavailable`
  }
  const archivedNavigation = /^category=behavior leaf=archived-navigation stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|outline|archive|volumes-readonly|plots-navigation|browser-history|blocks-readonly) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (archivedNavigation) {
    return `category=behavior leaf=archived-navigation stage=${archivedNavigation[1]} method=unavailable path=unavailable status=unavailable`
  }
  const foundationStage = /^category=behavior leaf=foundation-stage stage=(create-project|phase2-preparation|disable-planning-model|manual-planning|post-planning) method=unavailable path=unavailable status=unavailable$/u.exec(message)
  if (foundationStage) {
    return `category=behavior leaf=foundation-stage stage=${foundationStage[1]} method=unavailable path=unavailable status=unavailable`
  }
  const observerProgress = /^category=behavior leaf=observer-progress method=POST path=\/api\/projects\/:id\/planning\/drafts status=201 requestStage=(unseen|entry|metadata|recorded|scheduled) responseStage=(unseen|entry|metadata|recorded|scheduled)$/u.exec(message)
  if (observerProgress) {
    return `category=behavior leaf=observer-progress method=POST path=/api/projects/:id/planning/drafts status=201 requestStage=${observerProgress[1]} responseStage=${observerProgress[2]}`
  }
  const observerMetadata = /^category=behavior leaf=observer-metadata method=POST path=\/api\/projects\/:id\/planning\/drafts status=201 requestMatch=([01]) responseMatch=([01])$/u.exec(message)
  if (observerMetadata) {
    return `category=behavior leaf=observer-metadata method=POST path=/api/projects/:id/planning/drafts status=201 requestMatch=${observerMetadata[1]} responseMatch=${observerMetadata[2]}`
  }
  const writeCount = /^category=audit leaf=write-count ruleIndex=(\d+) method=(POST|PUT|PATCH|DELETE) path=(\/api(?:\/[A-Za-z0-9._~:-]+)*|allowed) status=allowed expectedCount=(\d+) actualCount=(\d+)(?: requestMetadataCount=(\d+) responseMetadataCount=(\d+)(?: normalizedRequestMetadataCount=(\d+) normalizedResponseMetadataCount=(\d+))?)?$/u.exec(message)
  if (writeCount) {
    const [, ruleIndex, method, pathValue, expectedCount, actualCount, requestMetadataCount, responseMetadataCount, normalizedRequestMetadataCount, normalizedResponseMetadataCount] = writeCount
    if (pathValue !== 'allowed' && !safeRuntimeApiPath(pathValue)) return null
    const metadata = requestMetadataCount === undefined
      ? ''
      : ` requestMetadataCount=${requestMetadataCount} responseMetadataCount=${responseMetadataCount}${normalizedRequestMetadataCount === undefined ? '' : ` normalizedRequestMetadataCount=${normalizedRequestMetadataCount} normalizedResponseMetadataCount=${normalizedResponseMetadataCount}`}`
    return `category=audit leaf=write-count ruleIndex=${ruleIndex} method=${method} path=${pathValue} status=allowed expectedCount=${expectedCount} actualCount=${actualCount}${metadata}`
  }
  const match = /^category=(audit|behavior) leaf=(write-unmatched|write-status|write-count|runtime-settlement|unavailable) method=(POST|PUT|PATCH|DELETE|GET|allowed|unavailable) path=(\/api(?:\/[A-Za-z0-9._~:-]+)*|allowed|unavailable) status=([1-5]\d{2}|unmatched|unexpected|matched|allowed|unavailable) count=(\d+|unexpected|matched|mismatch|allowed|unavailable)$/u.exec(message)
  if (!match) return null
  const [, category, leaf, method, pathValue, status, count] = match
  if (pathValue.startsWith('/api') && !safeApiPath(pathValue)) return null
  return `category=${category} leaf=${leaf} method=${method} path=${pathValue} status=${status} count=${count}`
}

function withoutSpecProjectionErrorPrefix(line) {
  return line.startsWith('AggregateError: ')
    ? line.slice('AggregateError: '.length)
    : line.startsWith('Error: ')
      ? line.slice('Error: '.length)
      : line
}

function safeSpecProjection(value, sensitiveValues = []) {
  const rawMessage = String(value || '')
  if (sensitiveValues.some(sensitive => typeof sensitive === 'string' && sensitive.length > 0 && rawMessage.includes(sensitive))) return null
  // Playwright can append a call log after the error's first line. Keep only one
  // recognized prefix and one closed projection, while rejecting a second candidate.
  const [firstLine, ...suffixLines] = rawMessage.split(/\r?\n/u)
  const projection = safeSpecProjectionLine(withoutSpecProjectionErrorPrefix(firstLine))
  if (!projection) return null
  if (suffixLines.some(line => safeSpecProjectionLine(withoutSpecProjectionErrorPrefix(line)))) return null
  return projection
}

function safeBrowserLeaf(messages) {
  for (const message of messages) {
    const unmatched = /Unmatched runtime write:\s*([A-Z]+)\s+(\/api\/projects\/[^\s]+)/u.exec(message)
    const pathValue = unmatched && safeApiPath(unmatched[2])
    if (unmatched && pathValue) {
      return `browser.leaf=write-unmatched method=${unmatched[1]} path=${pathValue} status=unmatched count=unexpected`
    }
    const status = /Unexpected runtime write status for\s+([A-Z]+)\s+(\/api\/projects\/[^\s]+)/u.exec(message)
    const statusPath = status && safeApiPath(status[2])
    if (status && statusPath) {
      return `browser.leaf=write-status method=${status[1]} path=${statusPath} status=unexpected count=matched`
    }
    if (message.includes('Runtime write count did not match allowlist entry')) {
      return 'browser.leaf=write-count method=allowed path=allowed status=allowed count=mismatch'
    }
  }
  return 'browser.leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable'
}

const REPORT_ERROR_NAMES = new Set(['Error', 'AggregateError', 'TimeoutError'])
const TOP_LEVEL_ERROR_CATEGORIES = new Set([
  'configuration', 'module-load', 'syntax', 'reference', 'type', 'timeout', 'unknown',
])

function topLevelReportErrors(report) {
  return Array.isArray(report?.errors)
    ? report.errors.filter(item => item && typeof item === 'object')
    : []
}

function closedTopLevelCategory(errorObjects) {
  const categories = new Set(errorObjects.map((item) => {
    if (item?.name === 'SyntaxError') return 'syntax'
    if (item?.name === 'ReferenceError') return 'reference'
    if (item?.name === 'TypeError') return 'type'
    if (item?.name === 'TimeoutError') return 'timeout'
    if (item?.name === 'ConfigurationError' || item?.name === 'ConfigError') return 'configuration'
    if (item?.name === 'ModuleNotFoundError') return 'module-load'
    const message = typeof item?.message === 'string' ? item.message : ''
    if (/^Error: (?:Configuration |Invalid configuration|Failed to load config)/u.test(message)) return 'configuration'
    if (/^Error: Cannot find (?:module|package) /u.test(message)) return 'module-load'
    return 'unknown'
  }))
  const [category] = categories
  return categories.size === 1 && TOP_LEVEL_ERROR_CATEGORIES.has(category) ? category : 'unknown'
}

function closedReportErrorName(errorObjects) {
  const names = new Set(errorObjects.map((item) => (
    REPORT_ERROR_NAMES.has(item?.name) ? item.name : 'Unknown'
  )))
  return names.size === 1 ? [...names][0] : 'Unknown'
}

function browserReportFallback(report, scenario) {
  const tests = browserReportTests(report?.suites)
    .filter(item => item.specTitle.includes(scenario))
    .map(item => item.test)
  const results = tests.flatMap(item => Array.isArray(item?.results) ? item.results : [])
  const failedResults = results.filter(result => result?.status !== 'passed')
  const errorObjects = failedResults.flatMap(result => (
    Array.isArray(result?.errors) ? result.errors.filter(item => item && typeof item === 'object') : []
  ))
  const topLevelErrors = tests.length === 0 ? topLevelReportErrors(report) : []
  const allErrorObjects = [...errorObjects, ...topLevelErrors]
  const messageCount = allErrorObjects.filter(item => typeof item?.message === 'string').length
  const leaf = tests.length === 0
    ? 'test-missing'
    : failedResults.length === 0
      ? 'failed-result-missing'
        : allErrorObjects.length === 0
          ? 'error-object-missing'
        : messageCount === 0
          ? 'message-missing'
          : 'message-unrecognized'
  return `category=browser leaf=report-${leaf} errorName=${closedReportErrorName(allErrorObjects)} testCount=${tests.length} resultCount=${results.length} errorCount=${allErrorObjects.length} messageCount=${messageCount} topLevelErrorCount=${topLevelErrors.length} topLevelCategory=${closedTopLevelCategory(topLevelErrors)}`
}

export function phase3BrowserFailure(report, scenario, sensitiveValues) {
  try {
    const matchingTests = browserReportTests(report?.suites)
      .filter(item => item.specTitle.includes(scenario))
      .map(item => item.test)
    const failed = matchingTests.find(item => (
      (item?.results || []).some(result => result.status !== 'passed')
    ))
    const messages = (failed?.results || []).flatMap(result => (
      browserFailureMessages(result)
    ))
    if (matchingTests.length === 0) {
      messages.push(...topLevelReportErrors(report)
        .filter(item => typeof item?.message === 'string')
        .map(item => item.message))
    }
    const projection = messages.map(message => safeSpecProjection(message, sensitiveValues)).find(Boolean)
    const browserLeaf = safeBrowserLeaf(messages)
    const detail = projection || (
      browserLeaf.includes('browser.leaf=unavailable')
        ? browserReportFallback(report, scenario)
        : `category=browser ${browserLeaf}`
    )
    throw new Error(redactDiagnostic(
      `Phase 3 browser assertion failed: scenario=${scenario} ${detail}`,
      sensitiveValues,
    ))
  } catch (error) {
    if (error instanceof Error && error.message.startsWith('Phase 3 browser assertion failed:')) throw error
    throw new Error(`Phase 3 browser assertion failed: scenario=${scenario} category=browser browser.leaf=unavailable method=unavailable path=unavailable status=unavailable count=unavailable`)
  }
}

export function assertFocusedScenarioReport(report, scenario) {
  const specs = browserReportSpecs(report?.suites)
    .filter(spec => String(spec?.title || '').includes(scenario))
  const tests = specs.length === 1 && Array.isArray(specs[0]?.tests)
    ? specs[0].tests
    : []
  if (
    specs.length !== 1
    || tests.length !== 1
    || !Array.isArray(tests[0].results)
    || tests[0].results.length !== 1
    || tests[0].results[0]?.status !== 'passed'
  ) throw new Error('browser report must contain exactly one passed focused scenario')
  return true
}

export function assertScenarioReports(reports, scenarios) {
  if (!Array.isArray(reports) || !Array.isArray(scenarios) || reports.length !== scenarios.length) {
    throw new Error('browser reports must cover every requested formal scenario')
  }
  for (const [index, scenario] of scenarios.entries()) {
    assertFocusedScenarioReport(reports[index], scenario)
  }
  return true
}

function attachPhase3FailureContext(error, scenario) {
  if (error && (typeof error === 'object' || typeof error === 'function')) {
    phase3FailureContexts.set(error, { scenario })
  }
  return error
}

function diagnosticCategory(error) {
  const messages = collectLeafFailures(error).map(item => String(item?.message || ''))
  if (messages.some(message => message.includes('category=browser'))) return 'browser'
  if (messages.some(message => message.includes('category=audit'))) return 'audit'
  if (messages.some(message => message.includes('category=behavior'))) return 'behavior'
  if (messages.some(message => /log contained runtime-sensitive|artifact contains sensitive|private evidence|authorization|password|dsn|raw.*provider/iu.test(message))) return 'audit'
  if (messages.some(message => /cleanup|residue|root audit/iu.test(message))) return 'cleanup'
  return 'initialization'
}

function safeBrowserWriteProjection(value) {
  const match = /^category=browser browser\.leaf=(write-unmatched|write-status|write-count|unavailable) method=(POST|PUT|PATCH|DELETE|GET|allowed|unavailable) path=(\/api(?:\/[A-Za-z0-9._~:-]+)*|allowed|unavailable) status=(unmatched|unexpected|matched|allowed|unavailable) count=(unexpected|matched|mismatch|allowed|unavailable)$/u.exec(value)
  if (!match) return null
  const [, leaf, method, pathValue, status, count] = match
  if (pathValue.startsWith('/api') && !safeApiPath(pathValue)) return null
  return `category=browser browser.leaf=${leaf} method=${method} path=${pathValue} status=${status} count=${count}`
}

function safeReportStructureProjection(value) {
  const match = /^category=browser leaf=report-(test-missing|failed-result-missing|error-object-missing|message-missing|message-unrecognized) errorName=(Error|AggregateError|TimeoutError|Unknown) testCount=(\d+) resultCount=(\d+) errorCount=(\d+) messageCount=(\d+) topLevelErrorCount=(\d+) topLevelCategory=(configuration|module-load|syntax|reference|type|timeout|unknown)$/u.exec(value)
  if (!match) return null
  const [, leaf, errorName, testCount, resultCount, errorCount, messageCount, topLevelErrorCount, topLevelCategory] = match
  return `category=browser leaf=report-${leaf} errorName=${errorName} testCount=${testCount} resultCount=${resultCount} errorCount=${errorCount} messageCount=${messageCount} topLevelErrorCount=${topLevelErrorCount} topLevelCategory=${topLevelCategory}`
}

function safePhase3BrowserDetail(value, sensitiveValues = []) {
  const match = /^Phase 3 browser assertion failed: scenario=([a-z0-9-]+) (.+)$/u.exec(value)
  if (!match) return null
  const [, scenario, detail] = match
  const projection = safeSpecProjection(detail, sensitiveValues)
    || safeBrowserWriteProjection(detail)
    || safeReportStructureProjection(detail)
  return projection ? `scenario=${scenario} ${projection}` : null
}

export function formatPhase3CommandFailure(error, {
  environment = process.env,
  scenario = 'unavailable',
} = {}) {
  const sensitive = [...runtimeSensitiveValues(environment), environment.TEST_MYSQL_PASSWORD].filter(Boolean)
  const failures = collectLeafFailures(error)
  const lines = [
    'Phase 3 browser runner failed.',
    `scenario=${scenario}`,
    `error.count=${failures.length}`,
    `category=${diagnosticCategory(error)}`,
  ]
  for (const failure of failures) {
    const message = String(failure?.message || '')
    const safeBrowserDetail = safePhase3BrowserDetail(message, sensitive)
    if (safeBrowserDetail) lines.push(safeBrowserDetail)
  }
  return redactDiagnostic(lines.join('\n'), sensitive)
}

export async function runOneScenario({
  spec,
  scenario,
  environment,
  databaseNameFactory = createDatabaseName,
  ownedRootFactory = createOwnedRoot,
  lifecycleRunner = exercisePhase3Lifecycle,
  ownedRootRemover = removeOwnedRoot,
  portReservationFactory = reserveLocalPort,
  deadlines = DEADLINES,
}) {
  let databaseName = ''
  let nonce = ''
  const ports = []
  let root = null
  let databaseCreated = 0
  let databaseCleaned = 0
  let databaseRemaining = 1
  let rootRemoved = false
  let denyAudit = null
  let denyAuditChecked = false
  let browserReport = null
  let sensitiveValues = []
  let serverLogSensitiveValues = []
  let artifactRoot = null
  let denyLedgerPath = null
  const safeAuditPaths = []
  let scenarioError = null
  try {
    await lifecycleRunner({
      registerRoot(lifecycle) {
        root = lifecycle.setRoot(ownedRootFactory(OWNED_ROOT_PREFIX))
      },
      async initialize(lifecycle) {
        databaseName = databaseNameFactory()
        assertDatabaseName(databaseName)
        nonce = randomUUID()
        lifecycle.setDatabase(databaseName)
        artifactRoot = path.join(root, 'artifacts')
        mkdirSync(artifactRoot)
        const resultPath = path.join(root, 'browser-result.json')
        denyLedgerPath = path.join(root, 'deny-proxy.log')
        const viteConfigPath = path.join(root, 'vite.config.mjs')
        const denyProxyPath = path.join(root, 'deny-proxy.cjs')
        const providerPath = path.join(root, 'fake-provider.cjs')
        safeAuditPaths.push(resultPath, denyLedgerPath)
        writeFileSync(denyLedgerPath, '', 'utf8')
        writeFileSync(denyProxyPath, DENY_PROXY_SOURCE, 'utf8')
        writeFileSync(providerPath, FAKE_PROVIDER_SOURCE, 'utf8')
        const backendPort = lifecycle.registerReservation(await portReservationFactory())
        const vitePort = lifecycle.registerReservation(await portReservationFactory())
        const denyPort = lifecycle.registerReservation(await portReservationFactory())
        const providerPort = lifecycle.registerReservation(await portReservationFactory())
        ports.push(backendPort.port, vitePort.port, denyPort.port, providerPort.port)
        if (new Set(ports).size !== ports.length) throw new Error('Phase 3 owned ports must be unique')
        const backendUrl = `http://127.0.0.1:${backendPort.port}`
        const viteUrl = `http://127.0.0.1:${vitePort.port}`
        const denyUrl = `http://127.0.0.1:${denyPort.port}`
        const providerUrl = `http://127.0.0.1:${providerPort.port}/v1`
        const common = {
          ...environment,
          MYSQL_HOST: environment.TEST_MYSQL_HOST,
          MYSQL_PORT: environment.TEST_MYSQL_PORT,
          MYSQL_USER: environment.TEST_MYSQL_USER,
          MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
          MYSQL_DB: databaseName,
          BROWSER_PROVIDER_BASE_URL: providerUrl,
          BROWSER_SECRET_SENTINEL: 'phase3-fake-provider-secret',
          BROWSER_MODEL_SENTINEL: 'phase3-fake-provider-model',
          M2_BROWSER_RUN_NONCE: nonce,
          BROWSER_OWNED_ROOT: root,
          BROWSER_ARTIFACT_ROOT: artifactRoot,
          BROWSER_RESULT_PATH: resultPath,
          BROWSER_DENY_PROXY_LEDGER_PATH: denyLedgerPath,
          BROWSER_DENY_PROXY_URL: denyUrl,
          BROWSER_ALLOWED_ORIGINS: JSON.stringify([backendUrl, viteUrl]),
          PLAYWRIGHT_BASE_URL: viteUrl,
          VITE_API_BASE_URL: `${backendUrl}/api`,
          PHASE3_FOCUS_SCENARIO: scenario,
        }
        sensitiveValues = [...runtimeSensitiveValues(common), ...SAFE_MARKERS]
        serverLogSensitiveValues = [
          ...runtimeSensitiveValues(common),
          ...OWNED_SERVER_LOG_MARKERS,
        ]
        writeFileSync(viteConfigPath, buildViteConfig(
          pathToFileURL(path.join(frontendRoot, 'vite.config.js')).href,
          root,
        ), 'utf8')
        const python = environment.PYTHON || 'python'
        await runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_phase2_browser_db', '--database', databaseName], childOptions(repositoryRoot, common), { label: 'Phase 3 database preparation', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs })
        databaseCreated = 1
        await lifecycle.releaseReservation(providerPort)
        const provider = lifecycle.registerServer(startOwnedServer(process.execPath, [providerPath, String(providerPort.port)], childOptions(repositoryRoot, common), { label: 'Phase 3 fake provider', sensitiveValues: serverLogSensitiveValues }))
        await waitForOwnedServer(provider, `http://127.0.0.1:${providerPort.port}/health`, { expectedNonce: nonce, timeoutMs: deadlines.healthMs })
        await lifecycle.releaseReservation(denyPort)
        const deny = lifecycle.registerServer(startOwnedServer(process.execPath, [denyProxyPath, String(denyPort.port)], childOptions(repositoryRoot, common), { label: 'Phase 3 deny proxy', sensitiveValues: serverLogSensitiveValues }))
        await waitForOwnedServer(deny, `${denyUrl}/health`, { expectedNonce: nonce, timeoutMs: deadlines.healthMs })
        await lifecycle.releaseReservation(backendPort)
        const backend = lifecycle.registerServer(startOwnedServer(python, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', String(backendPort.port)], childOptions(repositoryRoot, common), { label: 'Phase 3 backend', sensitiveValues: serverLogSensitiveValues }))
        await waitForOwnedServer(backend, `${backendUrl}/api/health`, { expectedNonce: nonce, timeoutMs: deadlines.healthMs })
        await lifecycle.releaseReservation(vitePort)
        const vite = lifecycle.registerServer(startOwnedServer(process.execPath, [path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js'), '--config', viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort.port), '--strictPort'], childOptions(frontendRoot, common), { label: 'Phase 3 Vite', sensitiveValues: serverLogSensitiveValues }))
        await waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, { expectedNonce: nonce, timeoutMs: deadlines.healthMs })
        try {
          await runBoundedOwnedCommand(process.execPath, [path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js'), 'test', `e2e/${spec}`, '--config', `e2e/${FORMAL_CONFIG}`, '--grep', scenario], childOptions(frontendRoot, common), { label: 'Phase 3 browser test', sensitiveValues, timeoutMs: deadlines.browserMs, stopTimeoutMs: deadlines.stopMs })
        } catch {
          phase3BrowserFailure(JSON.parse(readFileSync(resultPath, 'utf8')), scenario, sensitiveValues)
        }
        browserReport = JSON.parse(readFileSync(resultPath, 'utf8'))
        assertFocusedScenarioReport(browserReport, scenario)
      },
      cleanupServers: server => stopOwnedServer(server, { sensitiveValues: serverLogSensitiveValues, timeoutMs: deadlines.stopMs }),
      cleanupReservations: reservation => reservation.release(),
      async cleanupDatabase(database) {
        await runBoundedOwnedCommand(environment.PYTHON || 'python', ['-m', 'backend.scripts.prepare_phase2_browser_db', '--database', database, '--drop'], childOptions(repositoryRoot, environment), { label: 'Phase 3 database cleanup', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs })
        databaseCleaned = 1
        databaseRemaining = 0
      },
      async cleanupRoot(ownedRoot) {
        // Generated helper and Vite-cache source is infrastructure, not runtime
        // evidence. Audit only retained browser evidence and the deny ledger.
        const audit = auditAndRemovePhase3Root({
          ownedRoot,
          denyLedgerPath,
          artifactRoot,
          safeAuditPaths,
          sensitiveValues,
          removeRoot: ownedRootRemover,
        })
        denyAudit = audit.denyAudit
        denyAuditChecked = audit.denyAuditChecked
        rootRemoved = audit.rootRemoved
        if (audit.errors.length === 1) throw audit.errors[0]
        if (audit.errors.length > 1) throw new AggregateError(audit.errors, 'Phase 3 root audit and cleanup failed')
      },
    })
  } catch (error) {
    scenarioError = error
  }
  const errors = scenarioError ? [scenarioError] : []
  try {
    if (databaseName) assertDatabaseResidue(databaseName, databaseName, { created: databaseCreated, cleaned: databaseCleaned, remaining: databaseRemaining })
  } catch (error) {
    errors.push(error)
  }
  if (
    !rootRemoved
    || (denyLedgerPath && (!denyAuditChecked || !denyAudit || denyAudit.deniedHttpCount !== 0 || denyAudit.deniedConnectCount !== 0))
    || (!scenarioError && !browserReport)
  ) errors.push(new Error('Phase 3 resource audit failed'))
  if (errors.length === 1) throw attachPhase3FailureContext(errors[0], scenario)
  if (errors.length > 1) throw attachPhase3FailureContext(new AggregateError(errors, 'Phase 3 scenario and resource audit failed'), scenario)
  return browserReport
}

export async function runPhase3({ specs = FORMAL_SPECS, environment = process.env, runOneScenarioImpl = runOneScenario } = {}) {
  validateTestEnvironment(environment)
  const scenarios = resolveScenarios(environment)
  const reports = []
  for (const spec of validateSpecs(specs)) for (const scenario of scenarios) {
    reports.push(await runOneScenarioImpl({ spec, scenario, environment }))
  }
  assertScenarioReports(reports, scenarios)
  return 0
}

export async function runPhase3CommandLine({ specs, environment = process.env, runPhase3Impl = runPhase3, writeError = message => console.error(message) }) {
  try { return await runPhase3Impl({ specs, environment }) } catch (error) {
    const context = phase3FailureContexts.get(error)
    writeError(formatPhase3CommandFailure(error, {
      environment,
      scenario: context?.scenario || 'unavailable',
    }))
    return 1
  }
}

function isMain(argumentPath, modulePath) {
  try { return realpathSync(argumentPath) === realpathSync(modulePath) } catch { return false }
}

if (isMain(process.argv[1], fileURLToPath(import.meta.url))) {
  let specs
  try { specs = resolveCommandLineSpecs(process.argv.slice(2)) } catch { process.exitCode = 2 }
  if (specs) runPhase3CommandLine({ specs }).then(status => { process.exitCode = status })
}
