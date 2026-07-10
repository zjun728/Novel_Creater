import { createHash } from 'node:crypto'


function assertValidString(value) {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index)
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1)
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        throw new TypeError('Value is not valid restricted JCS.')
      }
      index += 1
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      throw new TypeError('Value is not valid restricted JCS.')
    }
  }
}

function canonicalizeValue(value, ancestors) {
  if (typeof value === 'string') {
    assertValidString(value)
    return JSON.stringify(value)
  }
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) {
      throw new TypeError('Value is not valid restricted JCS.')
    }
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) {
    if (ancestors.has(value)) throw new TypeError('Value is not valid restricted JCS.')
    ancestors.add(value)
    try {
      const items = []
      for (let index = 0; index < value.length; index += 1) {
        if (!Object.hasOwn(value, index)) {
          throw new TypeError('Value is not valid restricted JCS.')
        }
        items.push(canonicalizeValue(value[index], ancestors))
      }
      return `[${items.join(',')}]`
    } finally {
      ancestors.delete(value)
    }
  }
  if (value !== null && typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    if (ancestors.has(value)) throw new TypeError('Value is not valid restricted JCS.')
    ancestors.add(value)
    try {
      const keys = Object.keys(value)
      for (const key of keys) assertValidString(key)
      keys.sort()
      return `{${keys.map(key => `${JSON.stringify(key)}:${canonicalizeValue(value[key], ancestors)}`).join(',')}}`
    } finally {
      ancestors.delete(value)
    }
  }
  throw new TypeError('Value is not valid restricted JCS.')
}

export function canonicalize(value) {
  return canonicalizeValue(value, new Set())
}

export function canonicalSha256(value) {
  return createHash('sha256').update(new TextEncoder().encode(canonicalize(value))).digest('hex')
}
