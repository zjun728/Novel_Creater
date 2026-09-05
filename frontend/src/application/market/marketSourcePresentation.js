import { marketSnapshotMatchesSource } from './marketContracts.js'

const NETWORK_CAPABILITY = Object.freeze({ label: '网络刷新', tagType: 'success' })
const MANUAL_CAPABILITY = Object.freeze({ label: '仅支持导入', tagType: 'warning' })
const DISABLED_CAPABILITY = Object.freeze({ label: '已停用', tagType: 'default' })
const HISTORICAL_SNAPSHOT_NAMES = Object.freeze({
  'qimao\u0000public_catalog\u0000all': '七猫公开书库',
})

export function marketCapabilityPresentation(source) {
  if (source?.canRefresh) return NETWORK_CAPABILITY
  if (source?.canManualImport) return MANUAL_CAPABILITY
  return DISABLED_CAPABILITY
}

export function marketFailureCopy(source, snapshots) {
  return source?.lastSucceededAt && Array.isArray(snapshots) && snapshots.length
    ? '来源暂不可用，历史快照仍保留'
    : '尚无可用快照，本次刷新失败'
}

export function marketSnapshotDisplayName(snapshot, source) {
  if (!snapshot) return source?.displayName || ''
  if (marketSnapshotMatchesSource(snapshot, source)) return source.displayName
  const key = `${snapshot.platform}\u0000${snapshot.rankingName}\u0000${snapshot.category}`
  return HISTORICAL_SNAPSHOT_NAMES[key] || `${snapshot.platform} · ${snapshot.rankingName}`
}
