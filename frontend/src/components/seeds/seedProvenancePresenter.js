export function presentSeedProvenance(provenance) {
  const kind = String(provenance?.kind || 'unknown')
  const snapshots = Array.isArray(provenance?.snapshots) ? provenance.snapshots : []
  const sources = snapshots.map(item => item.sourceURL || item.sourceId || item.id).filter(Boolean)
  const snapshotBasis = sources.length ? [`采样依据：${sources.join('；')}`] : []
  const analysisBasis = provenance?.analysis?.id ? [`分析依据：${provenance.analysis.id}`] : []
  const inspirationBasis = provenance?.inspirationAttempt?.id ? [`对话依据：${provenance.inspirationAttempt.id}`] : []
  if (kind === 'manual') return { label: '作者手动创建', basis: [] }
  if (kind === 'topic_candidate') return { label: `选题中心候选 · 版本 ${provenance?.topicCandidate?.version ?? '—'}`, basis: [] }
  if (kind === 'market_snapshot') return { label: '市场快照', basis: snapshotBasis }
  if (kind === 'market_analysis') return { label: '市场分析', basis: [...snapshotBasis, ...analysisBasis] }
  if (kind === 'ai_chat') return { label: 'AI 灵感对话', basis: [...snapshotBasis, ...analysisBasis, ...inspirationBasis] }
  return { label: `未识别来源（类型：${kind}）`, basis: [`诊断：未识别的来源类型 ${kind}`] }
}
