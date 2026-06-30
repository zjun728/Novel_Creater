import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import {
  collectPositiveChapterTitleCandidates,
  cleanGeneratedChapterTitle,
  deriveFallbackChapterTitle,
  evaluateChapterTitlePolicy,
  getChapterTitleQuality
} from '../frontend/src/prompts/chapter.js'

const PROJECT_ID = process.env.PROJECT_ID || '2da6152a-c083-41ee-8bcb-f11b0fae387d'
const PROJECT_NAME = 'LongformBrowser240w_20260625_153055'
const QA_DIR = path.join(process.cwd(), 'tmp', 'realistic-flow-qa')
const OUT_JSON = path.join(QA_DIR, 'latest-chapter-title-source-strategy-verification.json')
const OUT_MD = path.join(QA_DIR, 'latest-chapter-title-source-strategy-verification.md')
const PRIOR_VERIFICATION = path.join(QA_DIR, 'latest-83-87-verification.json')

const badInitialSamples = ['就是这里', '还有多远', '这通向哪', '不一定', '可支撑', '坐']
const goodTitleSamples = [
  '庚七密室',
  '星账换令',
  '密约残页',
  '两封相反的信',
  '星账最后一页',
  '星债会地窖',
  '铁盒纸条',
  '铁箱账本',
  '三号仓钥',
  '染坊钥匙',
  '东城染坊'
]

function policyResult(title) {
  const policy = evaluateChapterTitlePolicy(title, { chapterNum: 83, titleSource: 'verification' })
  return {
    title,
    status: policy.status,
    reason: policy.reason,
    normalizedTitle: policy.title,
    titleValid: policy.status !== 'fail'
  }
}

function dbSnapshot() {
  const python = String.raw`
import asyncio
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path.cwd()
sys.path.insert(0, str(ROOT / "backend"))
from database import fetchall, get_pool  # noqa: E402

PROJECT_ID = "${PROJECT_ID}"

def is_synthetic_name(name):
    return "_" in str(name or "").strip()

def is_orgish_name(name):
    return bool(re.search(r"(星债会|巡天司|商盟|会|司|盟|宗|门派|宗门|商会|官署|机构|组织|势力|帮|阁|堂|府|衙|院)$", str(name or "").strip()))

async def main():
    chapters = await fetchall("""
        SELECT c.id, c.chapter_num, c.title, c.status, c.word_count, c.final_version_id,
               v.id AS version_id, v.content
        FROM chapters c
        LEFT JOIN chapter_versions v ON c.final_version_id = v.id
        WHERE c.project_id=%s AND c.chapter_num BETWEEN 78 AND 87
        ORDER BY c.chapter_num
    """, (PROJECT_ID,))
    chapter_rows = []
    for row in chapters:
        content = row.get("content") or ""
        chapter_rows.append({
            "chapterNum": row.get("chapter_num"),
            "chapterId": row.get("id"),
            "title": row.get("title"),
            "status": row.get("status"),
            "wordCount": row.get("word_count"),
            "finalVersionId": row.get("final_version_id"),
            "versionId": row.get("version_id"),
            "contentHash": hashlib.sha256(content.encode("utf-8")).hexdigest() if content else None,
        })

    pending = await fetchall("""
        SELECT id, entity_name, change_type, field_path, chapter_num, status
        FROM setting_change_events
        WHERE project_id=%s AND status='pending_review'
        ORDER BY chapter_num, created_at
    """, (PROJECT_ID,))

    entities = await fetchall("""
        SELECT id, entity_type, name, status
        FROM setting_entities
        WHERE project_id=%s
    """, (PROJECT_ID,))
    relations = await fetchall("""
        SELECT id, source_entity_id, target_entity_id, relation_type, status
        FROM setting_relations
        WHERE project_id=%s
    """, (PROJECT_ID,))
    entity_map = {row.get("id"): row for row in entities}
    active_relations = [row for row in relations if (row.get("status") or "active") == "active"]
    synthetic = []
    self_relations = []
    wrong_layer = []
    for relation in active_relations:
        source = entity_map.get(relation.get("source_entity_id")) or {}
        target = entity_map.get(relation.get("target_entity_id")) or {}
        if is_synthetic_name(source.get("name")) or is_synthetic_name(target.get("name")):
            synthetic.append(relation.get("id"))
        if relation.get("source_entity_id") and relation.get("source_entity_id") == relation.get("target_entity_id"):
            self_relations.append(relation.get("id"))
        if (
            (source.get("entity_type") == "character" and is_orgish_name(source.get("name")))
            or (target.get("entity_type") == "character" and is_orgish_name(target.get("name")))
        ):
            wrong_layer.append(relation.get("id"))

    pool = await get_pool()
    pool.close()
    await pool.wait_closed()
    chapter87 = next((row for row in chapter_rows if row.get("chapterNum") == 87), None)
    print(json.dumps({
        "chapters": chapter_rows,
        "chapter87Exists": any(row.get("chapter_num") == 87 for row in chapters),
        "chapter87HasContent": bool(chapter87 and (chapter87.get("contentHash") or int(chapter87.get("wordCount") or 0) > 0)),
        "chapter87Status": chapter87.get("status") if chapter87 else None,
        "chapter87FinalVersionId": chapter87.get("finalVersionId") if chapter87 else None,
        "pendingSettingsCount": len(pending),
        "pendingSettings": pending,
        "relationshipAudit": {
            "activeRelationCount": len(active_relations),
            "activeSyntheticRelationCount": len(set(synthetic)),
            "activeSelfRelationCount": len(set(self_relations)),
            "activeWrongLayerRelationCount": len(set(wrong_layer)),
        },
    }, ensure_ascii=False))

asyncio.run(main())
`
  return JSON.parse(execFileSync('python', ['-c', python], {
    cwd: process.cwd(),
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe']
  }))
}

function priorHashes() {
  if (!existsSync(PRIOR_VERIFICATION)) return {}
  const data = JSON.parse(readFileSync(PRIOR_VERIFICATION, 'utf8'))
  const rows = Array.isArray(data.dbChapters78To88) ? data.dbChapters78To88 : []
  return Object.fromEntries(rows.map(row => [String(row.chapterNum), row.contentHash]))
}

function markdown(report) {
  const badLines = report.badInitialPolicy.map(item => `- ${item.title}: ${item.status}/${item.reason}`).join('\n')
  const goodLines = report.goodTitlePolicy.map(item => `- ${item.title}: ${item.status}/${item.reason}`).join('\n')
  const materialLines = report.chapter88PositiveMaterials.map(item => `- ${item.title}: ${item.type}`).join('\n')
  const hashLines = report.chapter83To86HashCheck.map(item => `- 第${item.chapterNum}章：${item.currentHash}；prior=${item.priorHash || 'n/a'}；unchanged=${item.unchangedAgainstPrior}`).join('\n')
  return `# 章名源头策略验证报告

- 项目：${PROJECT_NAME} (${PROJECT_ID})
- 生成时间：${report.createdAt}
- 本报告只读 DB 和策略函数；未生成新章，未跑89，未改正文。

## 坏样例策略结果

${badLines}

## 好标题策略结果

${goodLines}

## 清洗与 fallback

- mixedCandidateSelected：${report.mixedCandidateSelected}
- chapter88MixedCandidateSelected：${report.chapter88MixedCandidateSelected}
- fallbackFromDialogueHeavyText：${report.fallbackFromDialogueHeavyText}
- metadataRepairCountsAsSourceStrategyPassed：${report.metadataRepairCountsAsSourceStrategyPassed}

## 第88章正向素材池

${materialLines}

## 后端与 DB 复核

- backendPolicyContract：${report.backendPolicyContract}
- 第87章存在：${report.chapter87Exists}
- 第87章已有正文/定稿：${report.chapter87HasContent}；status=${report.chapter87Status || 'n/a'}；finalVersionId=${report.chapter87FinalVersionId || 'n/a'}
- pendingSettingsCount：${report.pendingSettingsCount}
- active synthetic/self/wrong-layer relation count：${report.relationshipAudit.activeSyntheticRelationCount}/${report.relationshipAudit.activeSelfRelationCount}/${report.relationshipAudit.activeWrongLayerRelationCount}

## 第83-86章正文 Hash

${hashLines}

## 边界检查

- formalWritingStandardBoundaryTest：${report.formalWritingStandardBoundaryTest}
- sourceLeakageAndExperienceDirectTest：${report.sourceLeakageAndExperienceDirectTest}
- noNewChapterGeneratedByThisScript：true
`
}

mkdirSync(QA_DIR, { recursive: true })

const badInitialPolicy = badInitialSamples.map(policyResult)
const goodTitlePolicy = goodTitleSamples.map(title => ({
  ...policyResult(title),
  quality: getChapterTitleQuality(title, { chapterNum: 83, titleSource: 'verification' })
}))

const mixedCandidateSelected = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '还有多远', type: 'event', reason: '路程对白碎片' },
    { title: '这通向哪', type: 'place', reason: '方向问句' },
    { title: '不一定', type: 'result', reason: '口语判断' },
    { title: '坐', type: 'event', reason: '单字动作' },
    { title: '星债会地窖', type: 'place', reason: '本章核心地点' },
    { title: '铁盒纸条', type: 'item', reason: '关键物证' }
  ]
}), {
  chapterNum: 83,
  content: '陆沉舟进了星债会地窖，摸到铁盒纸条。'
})

const chapter88Context = {
  chapterNum: 88,
  beatPlan: '陆沉舟进入星债会地窖，在东城染坊找到铁箱账本和三号仓钥。',
  content: '马三低声说“就是这里”。陆沉舟没有接话，先打开铁箱账本，又把三号仓钥和染坊钥匙压在账页下。'
}
const chapter88PositiveMaterials = collectPositiveChapterTitleCandidates(chapter88Context)
const chapter88MixedCandidateSelected = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '就是这里', type: 'place', reason: '对白位置残片' },
    { title: '铁箱账本', type: 'item', reason: '关键证据' }
  ]
}), chapter88Context)

const fallbackFromDialogueHeavyText = deriveFallbackChapterTitle({
  chapterNum: 84,
  beatPlan: '马三问“这通向哪”，陆沉舟没有答。他们最终进入东城染坊，发现铁盒纸条和染坊钥匙。',
  content: '“还有多远？”\n“不一定。”\n铁盒纸条压在袖口里。东城染坊的后门开着，染坊钥匙挂在门内。'
})

const db = dbSnapshot()
const prior = priorHashes()
const chapter83To86HashCheck = db.chapters
  .filter(row => row.chapterNum >= 83 && row.chapterNum <= 86)
  .map(row => ({
    chapterNum: row.chapterNum,
    currentHash: row.contentHash,
    priorHash: prior[String(row.chapterNum)] || null,
    unchangedAgainstPrior: prior[String(row.chapterNum)] ? prior[String(row.chapterNum)] === row.contentHash : null
  }))

const backendPolicyContract = execFileSync('python', ['tmp/test_chapter_title_backend_policy_contract.py'], {
  cwd: process.cwd(),
  encoding: 'utf8'
}).trim()

const formalWritingStandardBoundaryOutput = execFileSync('node', ['tmp/test_writing_standard_prompt_boundary_contract.mjs'], {
  cwd: process.cwd(),
  encoding: 'utf8'
}).trim()
const formalWritingStandardBoundaryTest = formalWritingStandardBoundaryOutput || 'passed'

const sourceLeakageAndExperienceDirectOutput = execFileSync('node', ['tmp/test_writing_sample_library_frontend_contract.mjs'], {
  cwd: process.cwd(),
  encoding: 'utf8'
}).trim()
const sourceLeakageAndExperienceDirectTest = sourceLeakageAndExperienceDirectOutput || 'passed'

assert.ok(badInitialPolicy.every(item => item.status === 'fail'))
assert.ok(goodTitlePolicy.every(item => item.status !== 'fail'))
assert.equal(mixedCandidateSelected, '星债会地窖')
assert.equal(chapter88MixedCandidateSelected, '铁箱账本')
assert.match(fallbackFromDialogueHeavyText, /^(东城染坊|铁盒纸条|染坊钥匙)$/)

const report = {
  createdAt: new Date().toISOString(),
  projectId: PROJECT_ID,
  projectName: PROJECT_NAME,
  badInitialPolicy,
  goodTitlePolicy,
  mixedCandidateSelected,
  chapter88PositiveMaterials,
  chapter88MixedCandidateSelected,
  fallbackFromDialogueHeavyText,
  metadataRepairCountsAsSourceStrategyPassed: false,
  backendPolicyContract,
  chapters78To87: db.chapters,
  chapter83To86HashCheck,
  chapter87Exists: db.chapter87Exists,
  chapter87HasContent: db.chapter87HasContent,
  chapter87Status: db.chapter87Status,
  chapter87FinalVersionId: db.chapter87FinalVersionId,
  pendingSettingsCount: db.pendingSettingsCount,
  pendingSettings: db.pendingSettings,
  relationshipAudit: db.relationshipAudit,
  formalWritingStandardBoundaryTest,
  sourceLeakageAndExperienceDirectTest,
  noNewChapterGeneratedByThisScript: true
}

writeFileSync(OUT_JSON, JSON.stringify(report, null, 2), 'utf8')
writeFileSync(OUT_MD, markdown(report), 'utf8')

console.log(JSON.stringify({
  ok: true,
  outJson: OUT_JSON,
  badInitialPolicy: badInitialPolicy.map(({ title, status, reason }) => ({ title, status, reason })),
  goodTitleCount: goodTitlePolicy.length,
  mixedCandidateSelected,
  chapter88MixedCandidateSelected,
  fallbackFromDialogueHeavyText,
  chapter87Exists: db.chapter87Exists,
  chapter87HasContent: db.chapter87HasContent,
  chapter87Status: db.chapter87Status,
  pendingSettingsCount: db.pendingSettingsCount,
  relationshipAudit: db.relationshipAudit,
  chapter83To86HashesUnchangedAgainstPrior: chapter83To86HashCheck.every(item => item.unchangedAgainstPrior === true)
}, null, 2))
