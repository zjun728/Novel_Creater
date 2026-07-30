import { assertDatabaseName } from './product-runner.mjs'


export function assertDatabaseResidue(ownedDatabaseName, actualDatabaseName, {
  created,
  cleaned,
  remaining,
} = {}) {
  try {
    assertDatabaseName(ownedDatabaseName)
    assertDatabaseName(actualDatabaseName)
    if (ownedDatabaseName !== actualDatabaseName) {
      throw new Error('database ownership did not match')
    }
    if (created !== 1 || cleaned !== 1 || remaining !== 0) {
      throw new Error('invalid database residue counters')
    }
  } catch {
    throw new Error('database residue accounting is invalid')
  }
  return { created, cleaned, remaining }
}
