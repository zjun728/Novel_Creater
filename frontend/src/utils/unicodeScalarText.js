function scalarArray(value) {
  if (typeof value !== 'string') throw new TypeError('Expected Unicode text')
  const scalars = []
  for (const scalar of value) {
    const unit = scalar.charCodeAt(0)
    if (scalar.length === 1 && unit >= 0xD800 && unit <= 0xDFFF) {
      throw new TypeError('Malformed Unicode text')
    }
    scalars.push(scalar)
  }
  return scalars
}

export function unicodeScalarLength(value) {
  return scalarArray(value).length
}

export function limitUnicodeScalarText(value, maximum) {
  if (!Number.isInteger(maximum) || maximum < 0) {
    throw new TypeError('Invalid Unicode scalar limit')
  }
  const scalars = scalarArray(value)
  const truncated = scalars.length > maximum
  const limited = truncated ? scalars.slice(0, maximum) : scalars
  return Object.freeze({
    value: limited.join(''),
    length: limited.length,
    truncated,
  })
}
