# ContextPack v2 / State Authority Contract Phase 1 Report

## Goal

建立平台级可信上下文合同，让生成准备链路明确区分：

- `stateAuthority`：只收可信定稿来源的事实、设定、角色/实体状态和 active story block/stage。
- `creativeStageContract`：当前章允许写什么、必须停在哪里、哪些信息只可作为当前章边界。
- `narrativeVoiceContract`：只描述表达方式，不允许覆盖事实和 stage 边界。
- `guardSnapshot`：保留 future/forbidden/roadmap 等 deterministic guard 信息，但不进入 creative prompt/context。

本阶段没有启动 backend/frontend/runner/page.goto，没有跑正式章节生成/定稿链路，没有写真实 DB，没有恢复 LongformBrowser，也没有做第98硬编码。

## Implementation Summary

- 新增 `frontend/src/utils/contextPackV2.js`，提供 `buildContextPackV2`、`buildCreativeContextFromPack`、`assertContextPackHealthy`、`lintNarrativeVoiceContract`。
- `buildWritingContext` 现在会构建 ContextPack v2，并将 v2 creative projection 覆盖旧扁平上下文中的高风险字段，例如 `nearOutline`、`volumeStage`、`forbiddenDirections`、`settingLibrary`、`stateLedger`、`recentFacts`。
- `WriterView.ensureAiContextReady` 新增 ContextPack health assertion，所有小纲/正文/续写/改写准备阶段共享同一道 deterministic gate。
- `WriterView.buildBaseContextResult` 向 ContextPack v2 传入 `writerStore.chapters` 和本地 pending finalization markers，确保真实准备路径也能识别空章/半成功定稿来源。
- `stateAuthority` 保留可信全集；creative projection 额外做本章相关性筛选，避免远线可信信息进入当前创作上下文。
- `guardSnapshot` 保留未来章 roadmap、guard-only forbidden directions、saved beat plans 和 rejected source diagnostics，但不会被 `buildCreativeContextFromPack` 输出。
- Phase 1.1 关闭 legacy 集成洞：prompt-facing relationships 只从 provenance-gated `stateAuthority.settingRelations` 派生；unknown/degraded 角色、事实、实体、事件会显示 `trustLevel` 标记。
- finalization guard marker 增加 durable `failed_after_chapter_commit` / `half_success` 语义，证明定稿后处理半成功不会在短 TTL 后静默放行下一章。

## Changed Files

- `frontend/package-lock.json`
- `frontend/src/prompts/audit.js`
- `frontend/src/prompts/chapter.js`
- `frontend/src/utils/finalizationGuard.js`
- `frontend/src/utils/contextPackV2.js`
- `frontend/src/utils/contextBuilder.js`
- `frontend/src/views/WriterView.vue`
- `tmp/test_finalization_guard.mjs`
- `tmp/test_finalization_postprocess_contract.mjs`
- `tmp/test_context_pack_v2_phase1_contract.mjs`
- `tmp/realistic-flow-qa/contextpack-v2-phase1-report.md`

## Tests

新增：

- `tmp/test_context_pack_v2_phase1_contract.mjs`

回归/相关：

- `tmp/test_context_relevance_filter_contract.mjs`
- `tmp/test_prompt_boundary_modules.mjs`
- `tmp/test_finalization_guard.mjs`
- `tmp/test_finalization_postprocess_contract.mjs`
- `tmp/test_finalization_retry_contract.mjs`
- `tmp/test_realistic_qa_frontend_context_contract.mjs`

## No-Model Commands And Results

- `node tmp\test_context_pack_v2_phase1_contract.mjs`
  Result: passed, `context pack v2 phase1 contract tests passed`
- `node tmp\test_context_relevance_filter_contract.mjs`
  Result: passed, `CONTEXT_RELEVANCE_FILTER_CONTRACT_OK`
- `node tmp\test_prompt_boundary_modules.mjs`
  Result: passed
- `node tmp\test_finalization_guard.mjs`
  Result: passed, `finalization guard tests passed`
- `node tmp\test_finalization_postprocess_contract.mjs`
  Result: passed, `finalization postprocess contract tests passed`
- `node tmp\test_finalization_retry_contract.mjs`
  Result: passed, `finalization retry contract passed`
- `node tmp\test_realistic_qa_frontend_context_contract.mjs`
  Result: passed, `realistic QA frontend-context contract ok`
- `node --check frontend\src\utils\contextPackV2.js`
  Result: passed
- `node --check frontend\src\utils\contextBuilder.js`
  Result: passed
- `node --check frontend\src\utils\finalizationGuard.js`
  Result: passed
- `node --check frontend\src\prompts\chapter.js`
  Result: passed
- `node --check frontend\src\prompts\audit.js`
  Result: passed

Static build note:

- Phase 1.1 reran dependency readiness and static build. See `Phase 1.1 Integration Hardening` below for the fresh result.

## Fixture Coverage

- Failed/unfinalized/empty chapter sources:
  - Fixture includes accepted canon fact, accepted setting event, active entity, active relation, and active plot thread from `commitStatus: failed` and `commitStatus: empty_chapter`.
  - They are excluded from `stateAuthority`.
  - Health-check emits blocking `untrusted_source` issues, so generation preparation is blocked.
  - Fixture includes a failed active story block snapshot; health-check emits blocking `untrusted_stage_snapshot`, and `activeStoryBlock` is not exposed to `stateAuthority`, `creativeStageContract`, or creative context.
  - Fixture includes failed character `relationshipNotes`; legacy `relationships` is overwritten by ContextPack v2 projection and the failed relationship text is absent from `buildWritingContext(...).context`.
- Tainted/quarantined setting/entity:
  - Fixture includes `tainted: true` active entity and `quarantined` entity/event.
  - They are excluded from creative projection and do not appear in prompt text.
- Guard-only roadmap:
  - Fixture includes future chapter secret and `guard-only` forbidden direction.
  - `guardSnapshot` retains both.
  - `buildCreativeContextFromPack` and `buildDraftPrompt` do not expose either string.
- Saved beat plan downgrade:
  - Fixture includes previous saved beat plan conflicting with final chapter fact.
  - Previous saved beat plan remains plan evidence only in guard snapshot.
  - Final fact / final version evidence wins in `stateAuthority` and creative context.
- Finalization half-success:
  - Fixture includes a pending finalization marker for the previous chapter.
  - `assertContextPackHealthy` throws `finalization_pending`, proving next-chapter preparation is blocked.
  - `finalizationGuard` fixture covers durable `failed_after_chapter_commit` marker persistence beyond the old short TTL and `endChapterFinalizationRun(... keepPending)` rewriting the marker with `sourceVersionId`.

## Independent Review

- Subtask ID: `019f2df6-be58-7ee2-9853-b29201f2837c` (`Lorentz`)
- Goal: read-only code review of current Phase 1 changes.
- Boundary: no file edits, no service start, no live generation/finalization, no DB writes, no LongformBrowser restore, no canary/rerun.
- Findings:
  - Failed `plotThreads` were not provenance-gated.
  - `settingRelations` were not provenance-gated.
  - `WriterView` did not pass chapter ledger/finalization markers into `buildWritingContext`.
- Resolution:
  - Added failed plot thread and failed relation fixture coverage.
  - Routed plot threads and setting relations through `collectAuthorityItems` / `sourceTrustStatus`.
  - Passed `chapters: writerStore.chapters` and collected `finalizationMarkers` from `WriterView.buildBaseContextResult`.

## Narrative Voice Contract

Phase 1 schema/lint is in place:

- `narrativeVoiceContract` carries tone/rhythm/diction/writing profile only.
- `lintNarrativeVoiceContract` rejects fact/stage override keys such as `factOverrides`, `stateAuthority`, `creativeStageContract`, `stageBoundary`, `mustReveal`, `mustStopAt`, and `worldRules`.
- The lint is deterministic and does not rewrite literary prompt behavior.
- Phase 1.1 sanitizes forbidden top-level fields out of the persisted `narrativeVoiceContract`; lint remains attached for audit, but fields such as `factOverrides` / `stageBoundary` do not remain in the contract object.

## Model-Assisted Validation

Phase 1.1 executed a small offline model-assisted prompt-risk audit. See `Phase 1.1 Integration Hardening` below.

## Phase 1.1 Integration Hardening

### Build Readiness

- Initial `npm --prefix frontend ci` failed because the checked-in `package-lock.json` had stale optional wasm dependency metadata:
  - top-level `@emnapi/wasi-threads` was locked at `1.2.1` while the current dependency graph expected `1.2.2`.
  - nested optional entries for `@rolldown/binding-wasm32-wasi` and `@tailwindcss/oxide-wasm32-wasi` were missing.
- Ran `npm --prefix frontend install --package-lock-only --ignore-scripts --no-audit --no-fund`.
  - `frontend/package.json` was unchanged.
  - `frontend/package-lock.json` received only optional wasm metadata updates for `@emnapi/*`, `@napi-rs/wasm-runtime`, `@tybys/wasm-util`, and `tslib`.
- Fresh `npm --prefix frontend ci` passed.
  - It reported `1 high severity vulnerability`; I did not run `npm audit fix` because that would be an unrelated dependency-policy change.
- Fresh `npm --prefix frontend run build` passed.
  - Vite warning observed: `src/stores/writerStore.js` is both dynamically and statically imported, so the dynamic import will not move it into another chunk. This is pre-existing bundling behavior, not a build failure.

### Legacy Provenance Strategy

`sourceTrustStatus` now classifies records as:

- `trusted`: explicit final provenance / trusted commit status, and when a chapter ledger exists, the source chapter is non-empty and finalized.
- `unknown`: legacy records without explicit provenance when no chapter ledger can prove or disprove them.
- `degraded`: reserved for legacy/fallback contexts that are admitted only with health warnings instead of high-trust treatment.
- `blocked`: failed, unfinalized, empty, candidate, plan-only, tainted, quarantined, rejected, future/current-chapter, or source chapter not final/non-empty.

Unknown/degraded records are no longer silent:

- `stateAuthority` entries carry `trustLevel`.
- Half provenance records with only `sourceChapterNum` / `sourceVersionId` and no final proof are `trustLevel: degraded`, not `trusted`.
- `healthCheck.issues` emits `unknown_provenance` / stage provenance warnings.
- prompt-facing ledger, entity, fact, event, and character-state lines carry `trustLevel=unknown` / `trustLevel=degraded` labels instead of appearing as unmarked hard facts.
- prompt-facing `context.contextHealth` contains only sanitized issue-code summaries, so diagnostics can warn without leaking unrelated target text into creative context.
- Full detailed health remains outside creative projection on `result.healthCheck` / `contextPack.healthCheck` for deterministic blocking and audit.

### Story Block / Stage Handoff

- Active story block now carries `sourceExplanation`.
- `sourceExplanation.sourceType` is:
  - `final_state` when explicit trusted final-state provenance supports the active stage.
  - `degraded_fallback` when a legacy/fallback stage is admitted only with warning.
  - `untrusted_snapshot` when the snapshot is not trusted.
- If the active stage is legacy/fallback but admitted, health-check emits warning `stage_degraded_provenance`.
- If the active stage is failed/untrusted, health-check emits blocking `untrusted_stage_snapshot` and the stage is not exposed to creative context.
- This phase does not rebuild real project story blocks from chapter text. It leaves a deterministic handoff point for Phase 2/state migration work.

### Finalization Saga Hardening

- `markChapterFinalizationPending` now stores `commitStatus`, `sourceVersionId`, `runId`, and `finalizationId` when available.
- `failed_after_chapter_commit` and `half_success` markers are durable by default; they do not expire via the old 30-minute pending TTL unless a test explicitly supplies `ttlMs`.
- `endChapterFinalizationRun(... keepPending)` rewrites a durable failed-postprocess marker.
- `WriterView.performFinalize` and retry postprocess pass `sourceVersionId` and `failed_after_chapter_commit` when final chapter commit succeeded but required postprocess did not complete.

### Offline Model-Assisted Validation

- Preferred model requested by policy: `联通云-DeepSeek-V4-Flash`.
- Available direct provider in this development environment: `DeepSeek planning provider fallback`, `model=deepseek-v4-pro`, `baseURL=https://api.deepseek.com`.
- Reason for fallback: the historical `联通云-DeepSeek-V4-Flash` base URL appears in prior QA reports, but no unmasked usable provider key/base pair was available to this thread without starting the app/backend or reading real project provider state. The shell environment did expose a DeepSeek planning provider key/base pair.
- Parameters: `temperature=0.7`, `top_p=0.9`, `max_tokens=900`, JSON response mode.
- Input summary:
  - A: creative projection only, containing final facts, allowed scope, stop point, and narrative voice contract.
  - B: the same creative projection plus an intentionally wrong `guardSnapshot` containing future roadmap, forbidden directions, and a failed saved beat plan.
- Output summary:
  - A risk score: `20`.
  - B risk score: `90`.
  - Model judged that adding `guardSnapshot` materially increases risk of future-roadmap leakage / overreach.
  - Model judged narrative voice should not override facts or stage boundaries.
- Conclusion: the model-assisted audit supports the Phase 1.1 design choice that `guardSnapshot` must stay deterministic-only and outside creative prompt/context. No model output was saved as project正文、小纲、beat plan, or DB state.

### Fresh Review

- Subtask ID: `019f2e0b-9176-7e53-ae5f-d0f15d16056e` (`Carver`)
- Boundary: read-only review; no service start, browser/page.goto, DB write, live generation/finalization, LongformBrowser restore, or #98/#99/#50 run.
- Initial findings:
  - Critical: failed/untrusted story block snapshot was warning-only and could enter creative context.
  - Important: half provenance could be silently trusted without final proof.
  - Important: unknown legacy facts/entities/events had health warnings but prompt-facing ledger lines lacked trust labels.
  - Important: local finalization marker durability was too short for postprocess-after-commit failure.
  - Important follow-up: legacy `relationships` and prompt-facing `characters` still needed ContextPack v2 projection/trust labels.
- Resolution:
  - Failed stage snapshot now blocks and returns `null`.
  - Half provenance now becomes `trustLevel: degraded` with `unknown_provenance`.
  - prompt-facing state lines and characters show trust labels.
  - relationships are derived only from provenance-gated `stateAuthority.settingRelations`.
  - finalization failed-postprocess markers are durable and carry source metadata.
- Final review result: no Critical or Important findings; Carver explicitly cleared final verification.

### Full Fresh Verification

- `npm --prefix frontend ci`: passed; still reports `1 high severity vulnerability`; no `npm audit fix` run.
- `npm --prefix frontend run build`: passed; Vite warning remains `INEFFECTIVE_DYNAMIC_IMPORT` for `writerStore.js`.
- `node tmp\test_context_pack_v2_phase1_contract.mjs`: passed.
- `node tmp\test_context_relevance_filter_contract.mjs`: passed.
- `node tmp\test_prompt_boundary_modules.mjs`: passed.
- `node tmp\test_finalization_guard.mjs`: passed.
- `node tmp\test_finalization_postprocess_contract.mjs`: passed.
- `node tmp\test_finalization_retry_contract.mjs`: passed.
- `node tmp\test_realistic_qa_frontend_context_contract.mjs`: passed.
- `node --check frontend\src\utils\contextPackV2.js`: passed.
- `node --check frontend\src\utils\contextBuilder.js`: passed.
- `node --check frontend\src\utils\finalizationGuard.js`: passed.
- `node --check frontend\src\prompts\chapter.js`: passed.
- `node --check frontend\src\prompts\audit.js`: passed.

## Remaining Risks And Phase 2 Entry

- Existing legacy records without provenance are still admitted with `trustLevel: unknown` and health warnings when no chapter ledger is supplied, to avoid breaking current projects before a DB migration. Phase 2 should add explicit provenance persistence/migration and project-level dry-run audit reports.
- `stateAuthority` currently uses compact deterministic formatting. Phase 2 can define richer `SceneExecutionContract` and literary prompt integration, but should not collapse it back into guard or state authority.
- Active story block reconstruction is exposed via `sourceExplanation` and `rebuildHint`; this phase does not fully rebuild stage state from final chapter text.
- Relationship display depends on relation records having usable source/target ids or names; missing relation metadata reduces prompt usefulness but does not re-admit untrusted legacy text.
- Static Vite build now passes after a minimal lockfile metadata refresh, but the npm audit high-severity advisory remains outside this task's dependency-policy scope.
