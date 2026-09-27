export async function saveThenAdjustReview({ reference, isCurrent, saveCandidate, generate }) {
  if (!reference || !isCurrent()) throw new Error('审稿或正文已变化，请重新核对。')
  if (!await saveCandidate()) throw new Error('旧稿未能保存，尚未开始整章调整。')
  if (!isCurrent()) throw new Error('保存期间正文或审稿已变化，旧稿已保留，请重新核对。')
  return generate({ reviewReference: reference })
}
