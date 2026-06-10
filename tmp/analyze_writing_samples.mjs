import fs from 'node:fs'
import path from 'node:path'
import { TextDecoder } from 'node:util'
import {
  analyzeWritingSampleText,
  createWritingStandardCandidate,
  formatWritingSampleAnalysisMarkdown
} from '../frontend/src/data/writingSampleAnalyzer.js'

function parseArgs(argv) {
  const args = {}
  for (let i = 0; i < argv.length; i += 1) {
    const item = argv[i]
    if (!item.startsWith('--')) continue
    const key = item.slice(2)
    const next = argv[i + 1]
    if (!next || next.startsWith('--')) {
      args[key] = true
    } else {
      args[key] = next
      i += 1
    }
  }
  return args
}

function decodeText(buffer) {
  const utf8 = buffer.toString('utf8')
  const badUtf8 = (utf8.match(/\uFFFD/g) || []).length
  if (badUtf8 <= 8) return utf8
  try {
    return new TextDecoder('gb18030').decode(buffer)
  } catch {
    return utf8
  }
}

function listTextFiles(inputPath, limit) {
  const resolved = path.resolve(inputPath)
  const stat = fs.statSync(resolved)
  const files = stat.isFile()
    ? [resolved]
    : fs.readdirSync(resolved)
        .filter(name => /\.(txt|text)$/i.test(name))
        .map(name => path.join(resolved, name))
        .filter(file => fs.statSync(file).isFile())
        .sort((a, b) => path.basename(a).localeCompare(path.basename(b), 'zh-Hans-CN'))
  return Number.isFinite(limit) && limit > 0 ? files.slice(0, limit) : files
}

function titleFromFile(file) {
  return path.basename(file).replace(/\.(txt|text)$/i, '')
}

const args = parseArgs(process.argv.slice(2))
const input = args.input || '小说txt'
const output = args.output || 'tmp/writing-sample-analysis'
const limit = args.limit ? Number(args.limit) : 0
const files = listTextFiles(input, limit)

if (!files.length) {
  throw new Error(`没有找到可分析的 txt 文件：${input}`)
}

const cards = files.map((file, index) => {
  const title = titleFromFile(file)
  const text = decodeText(fs.readFileSync(file))
  return analyzeWritingSampleText(text, {
    id: `local-sample-${String(index + 1).padStart(3, '0')}-${title.replace(/[^\w\u4e00-\u9fa5]+/g, '-').slice(0, 32)}`,
    sourceTitle: title,
    genreTags: args.genre ? String(args.genre).split(/[、,，\s]+/).filter(Boolean) : [],
    windowSize: args.windowSize ? Number(args.windowSize) : 3600,
    maxWindows: args.maxWindows ? Number(args.maxWindows) : 3
  })
})

const standardCandidate = createWritingStandardCandidate(cards, {
  id: args['standard-id'] || 'local-sample-standard',
  name: args['standard-name'] || '本地样本写作标准',
  category: args.category || '本地样本 / 待审核'
})

const result = {
  generatedAt: new Date().toISOString(),
  input: path.resolve(input),
  fileCount: files.length,
  files: files.map(file => ({ name: path.basename(file), size: fs.statSync(file).size })),
  cards,
  standardCandidate
}

fs.mkdirSync(output, { recursive: true })
fs.writeFileSync(path.join(output, 'writing-sample-analysis.json'), JSON.stringify(result, null, 2), 'utf8')
fs.writeFileSync(path.join(output, 'writing-sample-analysis.md'), formatWritingSampleAnalysisMarkdown(result), 'utf8')

console.log(`已分析 ${files.length} 个样本`)
console.log(path.join(output, 'writing-sample-analysis.json'))
console.log(path.join(output, 'writing-sample-analysis.md'))
