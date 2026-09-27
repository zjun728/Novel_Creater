// Suggestions are immutable within a completed request. Derive the command identity
// from that source so an uncertain response can be retried even after a reload.
export async function topicSuggestionKey(discussionId, requestId, kind, index) {
  const source = JSON.stringify(['topic-suggestion-v1', discussionId, requestId, kind, index])
  const hash = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(source))
  return Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, '0')).join('')
}
