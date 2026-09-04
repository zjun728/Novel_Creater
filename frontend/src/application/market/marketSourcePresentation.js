const NETWORK_CAPABILITY = Object.freeze({ label: '网络刷新', tagType: 'success' })
const MANUAL_CAPABILITY = Object.freeze({ label: '人工导入', tagType: 'warning' })
const DISABLED_CAPABILITY = Object.freeze({ label: '已停用', tagType: 'default' })

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
