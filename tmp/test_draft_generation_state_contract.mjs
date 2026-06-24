import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

assert.match(
  writerView,
  /finally\s*\{[\s\S]*streamingContent\.value\s*=\s*false[\s\S]*activeWriterAction\.value\s*=\s*''[\s\S]*\}/,
  '正文生成异常或成功后必须在 finally 中清理 streamingContent 和 activeWriterAction'
)

assert.match(
  writerStore,
  /draft_save_failed/,
  '正文候选保存失败必须抛出 draft_save_failed，而不是只保留生成中状态'
)

assert.match(
  writerView,
  /draft_save_failed[\s\S]{0,240}正文候选保存失败/,
  'WriterView 必须对 draft_save_failed 显示明确错误'
)

assert.match(
  writerStore,
  /generationStream\.value\s*=\s*content[\s\S]*createVersion/,
  '正文内容生成完成后必须先更新 generationStream，再进入候选版本保存'
)
