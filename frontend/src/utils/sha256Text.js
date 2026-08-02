import { unicodeScalarLength } from './unicodeScalarText.js'

const HASH_BYTES = 32

export async function sha256Text(value) {
  try {
    unicodeScalarLength(value)
    if (
      typeof TextEncoder !== 'function'
      || typeof globalThis.crypto?.subtle?.digest !== 'function'
    ) throw new TypeError()
    const encoded = new TextEncoder().encode(value)
    const digest = await globalThis.crypto.subtle.digest('SHA-256', encoded)
    const bytes = new Uint8Array(digest)
    if (bytes.length !== HASH_BYTES) throw new TypeError()
    return Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
  } catch {
    throw new TypeError('Unable to hash text')
  }
}
