# Lean Test Gate Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make risk-tiered test evidence the current project policy without changing tests, test dispatchers, package scripts, or product behavior.

**Architecture:** Add one operational policy document under `docs/testing/` and reference it from `CURRENT_PROJECT_STATE.md`. Existing commands remain authoritative execution mechanisms; the policy changes only when full suites are required and when unchanged review evidence may be reused.

**Tech Stack:** Markdown, Git, PowerShell read-only verification commands.

---

### Task 1: Add the authoritative operational policy

**Files:**
- Create: `docs/testing/test-gate-policy.md`
- Reference: `docs/superpowers/specs/2026-08-08-lean-test-gate-policy-design.md`

- [ ] **Step 1: Prove the operational policy does not already exist**

Run:

```powershell
Test-Path -LiteralPath docs/testing/test-gate-policy.md
```

Expected: `False`.

- [ ] **Step 2: Create the operational policy**

Create `docs/testing/test-gate-policy.md` with this complete content:

```markdown
# Test Gate Policy

状态：Current  
权威设计：`docs/superpowers/specs/2026-08-08-lean-test-gate-policy-design.md`

## 原则

保留全部正式测试和现有测试命令。测试证据按风险分为 focused、slice、Phase 和
release 四级；完整回归不是每次修改或每轮 review 的默认动作。

## Focused

开发 RED/GREEN/refactor 和失败诊断只运行明确命名的相关测试文件或测试选择器。
命令必须由当前实施计划列明，不使用自动 diff 推断。数据库行为未改变时，不运行
disposable-MySQL integration；页面关键路径未改变时，不运行浏览器门禁。

## Slice

切片实现完成后运行一次 fresh slice evidence：相关 Python unit/API、root Node、frontend
Node；修改生产前端时运行 build；修改持久化或事务时运行相关 disposable-MySQL 测试；
修改浏览器关键路径时运行对应的最窄正式 fake-provider browser scenario。

Implementer 记录该证据。Specification review 和 quality review 在没有代码变化、没有发现
遗漏测试类别时复用同一证据，不默认重复执行。代码变化只使受影响证据失效。

## Phase

所有切片通过且代码停止变化后，主控串行 fresh 运行一次：

1. `npm test`
2. `npm run test:integration`
3. `npm run build`
4. 当前 Phase 的正式 UI-only fake-provider browser gate
5. owned database/process/port/temp/cache residue audit

Phase gate 后发生代码变化时，只重跑受影响 focused/slice evidence；在新的 Phase 完成声明前
重新运行完整 Phase gate。

## Release

Release candidate 重复 Phase matrix，并增加当时适用的 product-shell、启动/打包、备份/导入、
秘密扫描和 release resource ledger。真实 Provider、live 网站和产品数据库必须获得用户明确
批准，永不由自动 release gate 隐式调用。

## 失败与输出

失败后执行 systematic debugging，记录 exit、count、首因和 owned-resource ledger；禁止盲目
重跑。日志和 artifact 禁止输出密钥、DSN、provider 原文或正文 body。

## 计划要求

未来实施计划必须列出精确 focused/slice 命令。只有记录了具体跨层风险时，才可在切片阶段
提前运行全量回归；验收文档必须标明使用的 evidence level。
```

- [ ] **Step 3: Verify the policy is complete and lean**

Run:

```powershell
Select-String -LiteralPath docs/testing/test-gate-policy.md -Pattern '^## Focused$','^## Slice$','^## Phase$','^## Release$'
git diff --check
git diff --name-only
```

Expected: all four headings are present; `git diff --check` exits `0`; the only implementation file listed is `docs/testing/test-gate-policy.md`.

- [ ] **Step 4: Commit the operational policy**

```powershell
git add -- docs/testing/test-gate-policy.md
git commit -m "docs: adopt risk-tiered test gates"
```

Expected: commit succeeds and contains only the operational policy.

### Task 2: Make the policy current project authority

**Files:**
- Modify: `CURRENT_PROJECT_STATE.md:5-19`
- Modify: `CURRENT_PROJECT_STATE.md:147-155`
- Test: documentation consistency checks only

- [ ] **Step 1: Prove the current-state file does not already claim the new authority**

Run:

```powershell
Select-String -LiteralPath CURRENT_PROJECT_STATE.md -Pattern 'docs/testing/test-gate-policy.md'
```

Expected: no match.

- [ ] **Step 2: Add the policy to the authority list**

Insert this item after the current stage implementation plan and acceptance report authority:

```markdown
5. `docs/testing/test-gate-policy.md`：当前测试证据分层、复用与失效规则。
```

Renumber the existing final authority item from `5.` to `6.`.

- [ ] **Step 3: Record the active execution rule**

Append this paragraph to `## 当前工程切片`:

```markdown

测试执行遵循 `docs/testing/test-gate-policy.md`：开发与 review 使用 focused/slice evidence，
未改代码的 review 复用同次 fresh 证据；完整 unit、disposable-MySQL、build、正式 browser 与
资源残留门禁只在 Phase 收口时串行运行一次。Release 候选另运行 release matrix。
```

- [ ] **Step 4: Verify authority, scope, and unchanged dispatcher files**

Run:

```powershell
Select-String -LiteralPath CURRENT_PROJECT_STATE.md -Pattern 'docs/testing/test-gate-policy.md','focused/slice evidence','Phase 收口'
git diff --check
git diff --name-only HEAD --
git status --short
```

Expected: the three policy references are present; diff check exits `0`; only `CURRENT_PROJECT_STATE.md` is modified; no product, test, package, or dispatcher file is listed.

- [ ] **Step 5: Commit the current-state update**

```powershell
git add -- CURRENT_PROJECT_STATE.md
git commit -m "docs: make lean gates current policy"
```

Expected: commit succeeds and contains only `CURRENT_PROJECT_STATE.md`.

### Task 3: Final documentation verification

**Files:**
- Verify: `docs/testing/test-gate-policy.md`
- Verify: `CURRENT_PROJECT_STATE.md`
- Verify unchanged: `scripts/run-tests.mjs`
- Verify unchanged: `package.json`

- [ ] **Step 1: Verify the two implementation commits changed documentation only**

Run:

```powershell
git diff --name-only HEAD~2 HEAD
git diff --check HEAD~2 HEAD
git status --short --branch
```

Expected: only `docs/testing/test-gate-policy.md` and `CURRENT_PROJECT_STATE.md` are listed; diff check exits `0`; the worktree is clean.

- [ ] **Step 2: Verify no test execution surface changed**

Run:

```powershell
git diff --exit-code HEAD~2 HEAD -- scripts/run-tests.mjs package.json
```

Expected: exit `0` with no output.

- [ ] **Step 3: Report the policy change without a product acceptance claim**

Report that future development uses focused/slice evidence and full regression is reserved for
Phase/release close. Do not claim new product functionality, new test coverage, or a fresh Phase
gate, because this implementation changes documentation only.
