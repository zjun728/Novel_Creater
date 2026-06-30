import assert from 'node:assert/strict'
import {
  cleanGeneratedChapterTitle,
  evaluateChapterTitlePolicy
} from '../frontend/src/prompts/chapter.js'

const weakSamples = [
  '这沟通哪儿',
  '有水',
  '那么明显',
  '加钱也没用',
  '后面走',
  '哪走',
  '马三呢',
  '赵庚呢',
  '去哪儿',
  '怎么办',
  '操',
  '这边有血迹',
  '前头也有',
  '收啥啊',
  '走门'
]

for (const title of weakSamples) {
  const policy = evaluateChapterTitlePolicy(title, { chapterNum: 31 })
  assert.notEqual(
    policy.status,
    'pass',
    `weak oral/action fragment ${title} should not pass title policy`
  )
}

assert.equal(
  evaluateChapterTitlePolicy('操', { chapterNum: 31 }).status,
  'fail',
  'single-character profanity or interjection title should fail, not merely warn'
)

assert.notEqual(
  evaluateChapterTitlePolicy('走不了', { chapterNum: 31 }).status,
  'pass',
  'oral state fragment title should be downgraded at least to warning'
)

assert.equal(
  evaluateChapterTitlePolicy('马三', { chapterNum: 31 }).status,
  'pass',
  'plain person-name short title should remain valid'
)

for (const title of ['北街', '旧仓', '庚库', '铜扣', '旧债', '残页', '马三', '赵庚', '换债', '放信号']) {
  assert.equal(
    evaluateChapterTitlePolicy(title, { chapterNum: 31 }).status,
    'pass',
    `concrete short title ${title} should remain valid`
  )
}

const selected = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '马三呢', type: 'person', reason: '疑问残片' },
    { title: '加钱也没用', type: 'event', reason: '对白残片' },
    { title: '那么明显', type: 'result', reason: '抽象口语' },
    { title: '铜盘', type: 'item', reason: '关键道具' },
    { title: '平安客栈', type: 'place', reason: '关键地点' },
    { title: '客栈取信', type: 'event', reason: '核心事件' }
  ]
}), {
  chapterNum: 31,
  content: '陆沉舟到平安客栈取信，掌柜交出铜盘。'
})

assert.equal(
  selected,
  '平安客栈',
  'chapter title ranking should prefer concrete place/item/event candidates over oral fragments'
)

console.log('chapter title weak fragment contract passed')
