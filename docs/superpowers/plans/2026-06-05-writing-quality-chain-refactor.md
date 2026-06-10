# Writing Quality Chain Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the novel writing quality chain so AI-style prevention, detection, review, and repair are explicit, testable, and separated by responsibility.

**Architecture:** The platform should stop treating "AI tone" as a single sentence-pattern problem. Generation uses concise writing-method guidance and a per-book writing fingerprint; outline planning designs scene friction and information discovery; audit detects issues; AI-trace review decides whether issues are real and how to handle them; revision repairs with local context. Prompt rules become data-backed modules instead of scattered string fragments.

**Tech Stack:** Vue 3 frontend, Pinia stores, Vite, Node test runner, FastAPI backend where API support is needed later.

---

### Task 1: Quality Rule Data Layer

**Files:**
- Create: `frontend/src/qualityRules/aiTraceRules.js`
- Test: `tmp/test_quality_chain_contract.mjs`

- [x] **Step 1: Write the failing test**

```js
import assert from 'node:assert/strict'
import {
  AI_TRACE_RULES,
  formatAiTraceRulesForAudit,
  formatAiTraceRulesForGeneration,
  AI_TRACE_ISSUE_TYPES
} from '../frontend/src/qualityRules/aiTraceRules.js'

assert.ok(AI_TRACE_RULES.length >= 10)
assert.ok(AI_TRACE_ISSUE_TYPES.includes('info_dump'))
assert.ok(AI_TRACE_ISSUE_TYPES.includes('overfunctional_density'))
assert.match(formatAiTraceRulesForGeneration(), /写作方法/)
assert.doesNotMatch(formatAiTraceRulesForGeneration(), /必须报问题/)
assert.match(formatAiTraceRulesForAudit(), /反证/)
```

- [x] **Step 2: Run test to verify it fails**

Run: `node tmp/test_quality_chain_contract.mjs`

Expected: FAIL because `frontend/src/qualityRules/aiTraceRules.js` does not exist.

- [x] **Step 3: Implement quality rule exports**

Create a small data module with rule ids, Chinese labels, source prevention guidance, audit signal, and repair strategy. Keep generation guidance positive and concise.

- [x] **Step 4: Run test to verify it passes**

Run: `node tmp/test_quality_chain_contract.mjs`

Expected: PASS.

### Task 2: AI Trace Second Review Prompt

**Files:**
- Create: `frontend/src/prompts/aiTraceReview.js`
- Modify: `frontend/src/prompts/audit.js`
- Test: `tmp/test_ai_trace_review_prompt.mjs`

- [x] **Step 1: Write the failing test**

```js
import assert from 'node:assert/strict'
import {
  buildAiTraceReviewSystemPrompt,
  buildAiTraceReviewPrompt,
  AI_TRACE_REVIEW_DECISIONS
} from '../frontend/src/prompts/aiTraceReview.js'

assert.ok(AI_TRACE_REVIEW_DECISIONS.includes('ignore'))
assert.ok(AI_TRACE_REVIEW_DECISIONS.includes('local_window_revision'))
assert.match(buildAiTraceReviewSystemPrompt(), /AI 痕迹二审/)
assert.match(buildAiTraceReviewSystemPrompt(), /反证/)
assert.match(buildAiTraceReviewSystemPrompt(), /不要直接改正文/)

const prompt = buildAiTraceReviewPrompt({
  chapterNum: 3,
  chapterContent: '林逐握住铜钱。雨声停了一瞬。',
  issues: [{ type: 'ai_tone', location: '雨声停了一瞬。', description: '疑似模板化' }]
})

assert.match(prompt, /待二审问题/)
assert.match(prompt, /处理决策/)
assert.match(prompt, /local_window_revision/)
```

- [x] **Step 2: Run test to verify it fails**

Run: `node tmp/test_ai_trace_review_prompt.mjs`

Expected: FAIL because `frontend/src/prompts/aiTraceReview.js` does not exist.

- [x] **Step 3: Implement prompt**

The prompt should review only audit issues related to AI traces and return JSON with `decision`, `confidence`, `evidence`, `sourceLevel`, `repairScope`, and `nextAction`.

- [x] **Step 4: Run test to verify it passes**

Run: `node tmp/test_ai_trace_review_prompt.mjs`

Expected: PASS.

### Task 3: Prompt Boundary Modules

**Files:**
- Create: `frontend/src/prompts/chapterPlanPrompt.js`
- Create: `frontend/src/prompts/chapterDraftPrompt.js`
- Create: `frontend/src/prompts/chapterRevisionPrompt.js`
- Test: `tmp/test_prompt_boundary_modules.mjs`

- [x] **Step 1: Write the failing test**

```js
import assert from 'node:assert/strict'
import { buildScenePlanPrompt } from '../frontend/src/prompts/chapterPlanPrompt.js'
import { buildDraftPrompt, buildDraftSystemPrompt } from '../frontend/src/prompts/chapterDraftPrompt.js'
import { buildLocalWindowRevisionPrompt } from '../frontend/src/prompts/chapterRevisionPrompt.js'

assert.match(buildScenePlanPrompt({ chapterNum: 1 }), /场景型小纲/)
assert.match(buildDraftSystemPrompt(), /正文生成/)
assert.doesNotMatch(buildDraftSystemPrompt(), /必须报问题/)

const draft = buildDraftPrompt({ chapterNum: 1, beatPlan: '### 本章节拍\n1. 雨夜开场' })
assert.match(draft, /写作指纹/)
assert.match(draft, /连续性硬约束/)

const revision = buildLocalWindowRevisionPrompt({
  issue: { location: '雨声停了一瞬。', replacement: '雨停得太突然，瓦檐还在往下滴。' },
  before: '林逐握住铜钱。',
  target: '雨声停了一瞬。',
  after: '他没有立刻抬头。'
})
assert.match(revision, /滑窗局部修订/)
assert.match(revision, /接缝/)
```

- [x] **Step 2: Run test to verify it fails**

Run: `node tmp/test_prompt_boundary_modules.mjs`

Expected: FAIL because boundary modules do not exist.

- [x] **Step 3: Implement boundary modules**

Create wrappers with clearer naming and future-safe boundaries. They may reuse existing functions internally in this phase, but must expose the new quality-chain vocabulary and avoid embedding full audit checklists in generation prompts.

- [x] **Step 4: Run test to verify it passes**

Run: `node tmp/test_prompt_boundary_modules.mjs`

Expected: PASS.

### Task 4: Documentation Sync

**Files:**
- Modify: `PRODUCT_DEVELOPMENT_PLAN.md`
- Modify: `DEVELOPMENT_LOG.md`
- Modify: `FUNCTION_TEST_CHECKLIST.md`

- [x] **Step 1: Update product plan**

Record the new chain:

`写作指纹 -> 场景型小纲 -> 轻规则正文生成 -> 审稿 -> AI 痕迹二审 -> 滑窗局部修订 -> 定稿前闸门 -> 记忆/设定提取`

- [x] **Step 2: Update development log**

Add an entry for the quality-chain refactor, including deleted/downgraded hard rules and new module boundaries.

- [x] **Step 3: Update checklist**

Add acceptance items for rule data layer, AI trace second review, prompt boundary modules, and sliding-window repair.

### Task 5: Verification

**Files:**
- Test: `tmp/test_quality_chain_contract.mjs`
- Test: `tmp/test_ai_trace_review_prompt.mjs`
- Test: `tmp/test_prompt_boundary_modules.mjs`
- Test: `frontend/tests/promptQuality.test.mjs`

- [x] **Step 1: Run focused prompt tests**

Run:

```powershell
node tmp/test_quality_chain_contract.mjs
node tmp/test_ai_trace_review_prompt.mjs
node tmp/test_prompt_boundary_modules.mjs
node --test frontend\tests\promptQuality.test.mjs
```

- [x] **Step 2: Run frontend build**

Run: `npm --prefix frontend run build`

- [x] **Step 3: Run diff check**

Run: `git diff --check`

Expected: no whitespace errors.
