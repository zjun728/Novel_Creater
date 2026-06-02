import assert from 'node:assert/strict'

import {
  buildChapterStateLedger,
  hasHardStateSignal
} from '../frontend/src/utils/chapterStateLedger.js'

const ledger = buildChapterStateLedger({
  chapterNum: 8,
  settingEntities: [
    {
      id: 'char-1',
      entityType: 'character',
      name: '林逐',
      category: '主角',
      status: 'active',
      summary: '逐愿师传承者，左臂在第六章后消失。',
      profile: {
        currentLocation: '废墟外山道',
        physicalStatus: '左臂已消失，不能无解释恢复',
        inventory: '持有白玉符一枚',
        currentGoal: '追查林家旧档案'
      }
    },
    {
      id: 'item-1',
      entityType: 'item',
      name: '白玉符',
      status: 'active',
      summary: '压制旧咒的信物。',
      profile: {
        owner: '林逐',
        usesLeft: '剩余 1 次'
      }
    },
    {
      id: 'system-1',
      entityType: 'power_system',
      name: '代价交易系统',
      status: 'active',
      summary: '林逐已完成第三次交易，剩余寿命七十一年，下次交易冷却时间为三天后。',
      profile: {
        transactionCount: '第三次交易已完成',
        remainingLifespan: '剩余寿命七十一年',
        cooldownUntil: '三天后才能再次交易',
        costRule: '隐性消耗会持续扣减寿命'
      }
    },
    {
      id: 'item-2',
      entityType: 'item',
      name: '银叶草',
      status: 'active',
      summary: '能治百病的稀有药草，价值不得无解释低估。',
      profile: {
        valueLevel: '稀有高价值',
        price: '不得低于普通灵药价格'
      }
    }
  ],
  settingChangeEvents: [
    {
      status: 'accepted',
      chapterNum: 6,
      entityName: '林逐',
      entityType: 'character',
      fieldPath: 'physicalStatus',
      newValue: '左臂已消失'
    },
    {
      status: 'pending_review',
      chapterNum: 7,
      entityName: '林逐',
      entityType: 'character',
      fieldPath: 'physicalStatus',
      newValue: '左臂恢复'
    }
  ],
  canonFacts: [
    {
      status: 'accepted',
      chapterNum: 5,
      factType: '道具',
      content: '白玉符已经使用一次，剩余一次。'
    },
    {
      status: 'accepted',
      chapterNum: 8,
      factType: '未来',
      content: '本章之后才发生的内容不应进入第八章前置账本。'
    }
  ]
})

assert.match(ledger, /章节状态账本/)
assert.match(ledger, /林逐/)
assert.match(ledger, /左臂已消失/)
assert.match(ledger, /白玉符/)
assert.match(ledger, /剩余 1 次/)
assert.match(ledger, /第三次交易已完成/)
assert.match(ledger, /剩余寿命七十一年/)
assert.match(ledger, /三天后才能再次交易/)
assert.match(ledger, /银叶草/)
assert.match(ledger, /稀有高价值/)
assert.doesNotMatch(ledger, /左臂恢复/)
assert.doesNotMatch(ledger, /本章之后才发生/)

assert.equal(hasHardStateSignal('剩余 1 次，左臂已消失'), true)
assert.equal(hasHardStateSignal('第三次交易完成，冷却三天，寿命剩余七十一年'), true)
assert.equal(hasHardStateSignal('银叶草价值稀有，售价五万五千'), true)
assert.equal(hasHardStateSignal('月光很好，气氛沉静'), false)

console.log('CHAPTER_STATE_LEDGER_TEST_OK')
