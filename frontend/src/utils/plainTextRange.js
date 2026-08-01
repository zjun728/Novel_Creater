function requireText(text) {
  if (typeof text !== 'string') {
    throw new TypeError('plain text must be a string')
  }
}

function requireInteger(value, name) {
  if (!Number.isInteger(value)) {
    throw new TypeError(`${name} must be an integer`)
  }
}

function requireRange(start, end, maximum) {
  requireInteger(start, 'start offset')
  requireInteger(end, 'end offset')
  if (start < 0 || end < start || end > maximum) {
    throw new RangeError('plain-text range is out of bounds')
  }
}

export function capturePlainTextRange(text, selectionStart, selectionEnd) {
  requireText(text)
  requireRange(selectionStart, selectionEnd, text.length)
  let codeUnitOffset = 0
  let scalarOffset = 0
  let startOffset = selectionStart === 0 ? 0 : null
  let endOffset = selectionEnd === 0 ? 0 : null

  for (const scalar of text) {
    requireScalar(scalar)
    codeUnitOffset += scalar.length
    scalarOffset += 1
    if (codeUnitOffset === selectionStart) {
      startOffset = scalarOffset
    }
    if (codeUnitOffset === selectionEnd) {
      endOffset = scalarOffset
    }
  }
  if (startOffset === null || endOffset === null) {
    throw new RangeError('selection falls inside a surrogate pair')
  }

  return {
    startOffset,
    endOffset,
    selectedText: text.slice(selectionStart, selectionEnd),
  }
}

export function capturePlainTextInput(target) {
  if (target === null || typeof target !== 'object') {
    throw new TypeError('plain text input target must be an object')
  }
  const { value, selectionStart, selectionEnd } = target
  requireText(value)
  return {
    value,
    selection: capturePlainTextRange(value, selectionStart, selectionEnd),
  }
}

export function scalarRangeToCodeUnits(text, startOffset, endOffset) {
  requireText(text)
  requireInteger(startOffset, 'start offset')
  requireInteger(endOffset, 'end offset')
  if (startOffset < 0 || endOffset < startOffset) {
    throw new RangeError('plain-text range is out of bounds')
  }
  let codeUnitOffset = 0
  let scalarOffset = 0
  let selectionStart = startOffset === 0 ? 0 : null
  let selectionEnd = endOffset === 0 ? 0 : null

  for (const scalar of text) {
    requireScalar(scalar)
    codeUnitOffset += scalar.length
    scalarOffset += 1
    if (scalarOffset === startOffset) {
      selectionStart = codeUnitOffset
    }
    if (scalarOffset === endOffset) {
      selectionEnd = codeUnitOffset
    }
  }
  if (selectionStart === null || selectionEnd === null) {
    throw new RangeError('plain-text range is out of bounds')
  }

  return {
    selectionStart,
    selectionEnd,
  }
}

export function locatePlainTextRange(textarea, text, startOffset, endOffset) {
  if (textarea === null || typeof textarea !== 'object') {
    throw new TypeError('textarea must be an object')
  }
  if (typeof textarea.focus !== 'function' || typeof textarea.setSelectionRange !== 'function') {
    throw new TypeError('textarea must support focus and selection')
  }
  requireText(text)
  if (textarea.value !== text) {
    throw new RangeError('textarea text does not match the requested text')
  }
  const range = scalarRangeToCodeUnits(text, startOffset, endOffset)
  textarea.focus()
  if (textarea.value !== text) {
    throw new RangeError('textarea text changed while focusing')
  }
  textarea.setSelectionRange(range.selectionStart, range.selectionEnd)
  return range
}

function requireScalar(scalar) {
  const codeUnit = scalar.charCodeAt(0)
  if (
    scalar.length === 1
    && codeUnit >= 0xd800
    && codeUnit <= 0xdfff
  ) {
    throw new RangeError('plain text contains an unpaired surrogate')
  }
}
