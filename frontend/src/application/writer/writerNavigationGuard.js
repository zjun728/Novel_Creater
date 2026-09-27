export async function canLeaveWriter({ canNavigate, dirty, confirmDiscard }) {
  if (!await canNavigate()) return false
  return !dirty() || Boolean(await confirmDiscard())
}
