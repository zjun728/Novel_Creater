const SOURCE_KEYS = ['id', 'stableKey', 'displayName', 'adapterKey', 'platform', 'rankingName', 'category', 'policyStatus', 'policyVersion', 'checkedAt', 'evidenceURL', 'automaticRefreshAllowed', 'canManualImport', 'canRefresh', 'canSchedule', 'refreshStatus', 'lastAttemptedAt', 'lastSucceededAt', 'lastSnapshotId', 'publicErrorCode']
const SUMMARY_KEYS = ['id', 'sourceId', 'capturedAt', 'platform', 'rankingName', 'category', 'sourceURL', 'contentHash', 'entryCount', 'captureMode', 'adapterVersion']
const DETAIL_KEYS = [...SUMMARY_KEYS, 'entries']
const ENTRY_KEYS = ['rank', 'title', 'author', 'category', 'workURL', 'publicMetrics']
const VERSION = /^[a-z0-9]+(?:-[a-z0-9]+)*-v[1-9][0-9]*$/
const HASH = /^[a-f0-9]{64}$/
const STRUCTURAL_ESCAPE = /%(?:2e|2f|5c|25|[01][0-9a-f]|7f)/i
const MARKET_ORIGINS = new Set(['https://www.qidian.com', 'https://book.qq.com', 'https://fanqienovel.com', 'https://www.qimao.com', 'https://www.shuqi.com', 'https://www.zongheng.com', 'https://www.jjwxc.net', 'https://www.heiyan.com', 'https://www.readnovel.com', 'https://www.xxsy.net'])

export function marketSnapshotMatchesSource(snapshot, source) {
  return Boolean(snapshot && source)
    && snapshot.sourceId === source.id
    && snapshot.platform === source.platform
    && snapshot.rankingName === source.rankingName
    && snapshot.category === source.category
}

function invalid() { throw new TypeError('Invalid market source response') }
function exact(value, keys) { if (!value || typeof value !== 'object' || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value)) || Reflect.ownKeys(value).length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) invalid(); for (const key of keys) { const descriptor = Object.getOwnPropertyDescriptor(value, key); if (!descriptor || !Object.hasOwn(descriptor, 'value') || descriptor.get || descriptor.set) invalid() } }
function text(value, max = 256) { try { if (typeof value !== 'string' || !value || unicodeScalarLength(value) > max || value !== value.trim() || /[\u0000-\u001f\u007f]/u.test(value)) invalid() } catch { invalid() }; return value }
function nullableText(value, max) { return value === null ? null : text(value, max) }
function integer(value, { positive = false, max = Number.MAX_SAFE_INTEGER } = {}) { if (!Number.isSafeInteger(value) || value < (positive ? 1 : 0) || value > max) invalid(); return value }
function nullableInteger(value) { return value === null ? null : integer(value) }
function nullablePositiveInteger(value) { return value === null ? null : integer(value, { positive: true }) }
function bool(value) { if (typeof value !== 'boolean') invalid(); return value }
function freeze(value) { if (Array.isArray(value)) value.forEach(freeze); else if (value && typeof value === 'object') Object.values(value).forEach(freeze); return Object.freeze(value) }
function canonicalPublicHttps(value) {
  const raw = text(value, 2048)
  if (STRUCTURAL_ESCAPE.test(raw) || /%(?![0-9a-f]{2})/i.test(raw)) invalid()
  let parsed
  try { parsed = new URL(raw) } catch { invalid() }
  const host = parsed.hostname
  const labels = host.split('.')
  if (raw !== parsed.href || parsed.protocol !== 'https:' || parsed.username || parsed.password || parsed.port || parsed.hash || labels.length < 2 || labels.some(label => !/^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label)) || host === 'localhost' || host.endsWith('.localhost') || host.endsWith('.local') || host.endsWith('.internal') || host.endsWith('.test') || /^[0-9.]+$/.test(host)) invalid()
  return raw
}
function registeredMarketURL(value) { const raw = canonicalPublicHttps(value); if (!MARKET_ORIGINS.has(new URL(raw).origin)) invalid(); return raw }
function provenance(modeValue, versionValue) {
  const captureMode = text(modeValue, 16)
  const adapterVersion = text(versionValue, 120)
  if ((captureMode === 'manual' && adapterVersion === 'manual-snapshot-v1') || (captureMode === 'network' && adapterVersion !== 'manual-snapshot-v1' && VERSION.test(adapterVersion))) return { captureMode, adapterVersion }
  invalid()
}
function metrics(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value) || Object.keys(value).length > 32) invalid()
  const result = Object.create(null)
  for (const [key, metric] of Object.entries(value)) {
    if (!/^[A-Za-z][A-Za-z0-9_]{0,63}$/.test(key)) invalid()
    if (typeof metric === 'string') result[key] = text(metric, 200)
    else if (typeof metric === 'boolean') result[key] = metric
    else if (typeof metric === 'number' && Number.isFinite(metric)) result[key] = metric
    else invalid()
  }
  return result
}
function snapshotBase(value, keys) {
  exact(value, keys)
  const hash = text(value.contentHash, 64)
  if (!HASH.test(hash)) invalid()
  return { id: text(value.id, 36), sourceId: text(value.sourceId, 36), capturedAt: integer(value.capturedAt, { positive: true }), platform: text(value.platform, 120), rankingName: text(value.rankingName, 160), category: text(value.category, 160), sourceURL: registeredMarketURL(value.sourceURL), contentHash: hash, entryCount: integer(value.entryCount, { positive: true, max: 100 }), ...provenance(value.captureMode, value.adapterVersion) }
}
function entry(value, expectedRank, sourceURL) {
  exact(value, ENTRY_KEYS)
  const workURL = canonicalPublicHttps(value.workURL)
  if (new URL(workURL).origin !== new URL(sourceURL).origin) invalid()
  const parsed = { rank: integer(value.rank, { positive: true, max: 100 }), title: text(value.title, 300), author: text(value.author, 200), category: text(value.category, 160), workURL, publicMetrics: metrics(value.publicMetrics) }
  if (parsed.rank !== expectedRank) invalid()
  return parsed
}
export function parseMarketSource(value) { exact(value, SOURCE_KEYS); const status = value.policyStatus === null ? null : text(value.policyStatus, 64); if (status !== null && !['verified_public', 'manual_only', 'disabled'].includes(status)) invalid(); if (value.canSchedule !== false || value.canRefresh !== value.automaticRefreshAllowed || (status === 'disabled' && value.canManualImport) || (status !== 'disabled' && !value.canManualImport) || (value.automaticRefreshAllowed && status !== 'verified_public') || !['idle', 'leased'].includes(text(value.refreshStatus, 24))) invalid(); return freeze({ id: text(value.id, 36), stableKey: text(value.stableKey, 160), displayName: text(value.displayName, 200), adapterKey: text(value.adapterKey, 120), platform: text(value.platform, 160), rankingName: text(value.rankingName, 160), category: text(value.category, 160), policyStatus: status, policyVersion: nullableText(value.policyVersion, 120), checkedAt: nullablePositiveInteger(value.checkedAt), evidenceURL: value.evidenceURL === null ? null : registeredMarketURL(value.evidenceURL), automaticRefreshAllowed: bool(value.automaticRefreshAllowed), canManualImport: bool(value.canManualImport), canRefresh: bool(value.canRefresh), canSchedule: bool(value.canSchedule), refreshStatus: value.refreshStatus, lastAttemptedAt: nullableInteger(value.lastAttemptedAt), lastSucceededAt: nullableInteger(value.lastSucceededAt), lastSnapshotId: nullableText(value.lastSnapshotId, 36), publicErrorCode: nullableText(value.publicErrorCode, 64) }) }
export function parseMarketSourceList(value) { if (!Array.isArray(value) || value.length > 100) invalid(); return freeze(value.map(parseMarketSource)) }
export function parseMarketSnapshotSummary(value) { return freeze(snapshotBase(value, SUMMARY_KEYS)) }
export function parseMarketSnapshotList(value) { if (!Array.isArray(value) || value.length > 100) invalid(); return freeze(value.map(parseMarketSnapshotSummary)) }
export function parseMarketSnapshotDetail(value) { const base = snapshotBase(value, DETAIL_KEYS); if (!Array.isArray(value.entries) || value.entries.length < 1 || value.entries.length > 100 || value.entries.length !== base.entryCount) invalid(); return freeze({ ...base, entries: value.entries.map((item, index) => entry(item, index + 1, base.sourceURL)) }) }
import { unicodeScalarLength } from '../../utils/unicodeScalarText.js'
