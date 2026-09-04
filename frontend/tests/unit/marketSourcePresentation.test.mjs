import assert from 'node:assert/strict'
import test from 'node:test'

import {
  marketCapabilityPresentation,
  marketFailureCopy,
} from '../../src/application/market/marketSourcePresentation.js'

test('first source failure never claims that a historical snapshot was retained', () => {
  assert.equal(
    marketFailureCopy({ lastSucceededAt: null }, []),
    '尚无可用快照，本次刷新失败',
  )
  assert.equal(
    marketFailureCopy({ lastSucceededAt: 1_752_800_000 }, []),
    '尚无可用快照，本次刷新失败',
  )
})

test('later source failure names the retained history only when it remains readable', () => {
  assert.equal(
    marketFailureCopy({ lastSucceededAt: 1_752_800_000 }, [{ id: 'snapshot-1' }]),
    '来源暂不可用，历史快照仍保留',
  )
})

test('source capability labels come from effective actions including no capability', () => {
  assert.deepEqual(
    marketCapabilityPresentation({ canRefresh: true, canManualImport: true }),
    { label: '网络刷新', tagType: 'success' },
  )
  assert.deepEqual(
    marketCapabilityPresentation({ canRefresh: false, canManualImport: true }),
    { label: '人工导入', tagType: 'warning' },
  )
  assert.deepEqual(
    marketCapabilityPresentation({ canRefresh: false, canManualImport: false }),
    { label: '已停用', tagType: 'default' },
  )
})
