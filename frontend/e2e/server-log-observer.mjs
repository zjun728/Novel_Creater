import { StringDecoder } from 'node:string_decoder'


const DEFAULT_MAX_BYTES = 64 * 1024


function countOccurrences(text, value) {
  if (!value) return 0
  return text.split(value).length - 1
}


function normalizedValues(values) {
  return [...new Set((values || []).filter(value => (
    typeof value === 'string' && value.length > 0
  )))]
}


function sameValues(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index])
}


function createStreamScanner(sensitiveValues) {
  const tails = new Map(sensitiveValues.map(value => [value, '']))
  let matchCount = 0
  return {
    scan(text) {
      for (const value of sensitiveValues) {
        const tail = tails.get(value)
        const combined = tail + text
        let fromIndex = 0
        while (fromIndex <= combined.length - value.length) {
          const index = combined.indexOf(value, fromIndex)
          if (index === -1) break
          if (index + value.length > tail.length) matchCount += 1
          fromIndex = index + value.length
        }
        tails.set(value, combined.slice(-Math.max(0, value.length - 1)))
      }
    },
    matchCount() {
      return matchCount
    },
  }
}


export function createServerLogObserver(child, {
  maxBytes = DEFAULT_MAX_BYTES,
  sensitiveValues = [],
} = {}) {
  if (!Number.isInteger(maxBytes) || maxBytes < 1) {
    throw new TypeError('maxBytes must be a positive integer')
  }
  const chunks = []
  let capturedBytes = 0
  let truncated = false
  let finished = false
  const configuredValues = normalizedValues(sensitiveValues)
  const stdoutScanner = createStreamScanner(configuredValues)
  const stderrScanner = createStreamScanner(configuredValues)
  const stdoutDecoder = new StringDecoder('utf8')
  const stderrDecoder = new StringDecoder('utf8')

  const capture = (chunk, scanner, decoder) => {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk), 'utf8')
    scanner.scan(decoder.write(buffer))
    const available = maxBytes - capturedBytes
    if (available <= 0) {
      truncated = true
      return
    }
    const accepted = buffer.subarray(0, available)
    chunks.push(accepted)
    capturedBytes += accepted.length
    if (accepted.length < buffer.length) truncated = true
  }

  const captureStdout = chunk => capture(chunk, stdoutScanner, stdoutDecoder)
  const captureStderr = chunk => capture(chunk, stderrScanner, stderrDecoder)

  child?.stdout?.on?.('data', captureStdout)
  child?.stderr?.on?.('data', captureStderr)

  return {
    finish(sensitiveValues = []) {
      if (finished) throw new Error('server log observer already finished')
      finished = true
      child?.stdout?.off?.('data', captureStdout)
      child?.stderr?.off?.('data', captureStderr)
      stdoutScanner.scan(stdoutDecoder.end())
      stderrScanner.scan(stderrDecoder.end())
      const text = Buffer.concat(chunks).toString('utf8')
      const values = normalizedValues(sensitiveValues)
      const streamMatchCount = stdoutScanner.matchCount() + stderrScanner.matchCount()
      return {
        matchCount: sameValues(values, configuredValues)
          ? streamMatchCount
          : values.reduce(
            (count, value) => count + countOccurrences(text, value),
            0,
          ),
        truncated,
      }
    },
  }
}
