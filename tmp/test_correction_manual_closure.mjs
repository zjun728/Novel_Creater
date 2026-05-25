import assert from 'node:assert/strict'
import {
  correctionTaskEvidenceKey,
  settingCandidateStateForTask
} from '../frontend/src/utils/correctionManualClosure.js'

const task = { id: 't1', title: '林逐血脉归属不清' }

assert.equal(correctionTaskEvidenceKey(task), '纠偏任务：林逐血脉归属不清')

assert.equal(
  settingCandidateStateForTask([], task).buttonText,
  '生成设定候选'
)

const pendingState = settingCandidateStateForTask([
  { status: 'pending_review', evidence: '来自全局审稿纠偏任务：林逐血脉归属不清' }
], task)
assert.equal(pendingState.locked, true)
assert.equal(pendingState.buttonText, '已生成设定候选')
assert.match(pendingState.hint, /设定库/)

const acceptedState = settingCandidateStateForTask([
  { status: 'accepted', evidence: '来自全局审稿纠偏任务：林逐血脉归属不清' }
], task)
assert.equal(acceptedState.locked, true)
assert.equal(acceptedState.buttonText, '设定候选已确认')
assert.match(acceptedState.hint, /完成/)

const rejectedState = settingCandidateStateForTask([
  { status: 'rejected', evidence: '来自全局审稿纠偏任务：林逐血脉归属不清' }
], task)
assert.equal(rejectedState.locked, false)
assert.equal(rejectedState.buttonText, '重新生成设定候选')
assert.match(rejectedState.hint, /忽略本次/)

const localState = settingCandidateStateForTask([], task, true)
assert.equal(localState.locked, true)
assert.equal(localState.buttonText, '已生成设定候选')

console.log('correction manual closure tests passed')
