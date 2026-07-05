# State Provenance Persistence + Project Health Check Phase 1.2

Date: 2026-07-05

## Goal

把 ContextPack v2 Phase 1.1 的前端合同继续下沉到状态来源写入、项目健康检查、可恢复状态投影的 no-model 平台底座。当前阶段没有进入 Phase 2 写作引擎，没有跑 live 章节链路，没有写真实 DB。

## 改动文件

- `frontend/src/utils/stateProvenance.js`
- `frontend/src/utils/projectHealthCheck.js`
- `frontend/src/utils/finalizationProtocol.js`
- `frontend/src/utils/contextPackV2.js`
- `frontend/src/utils/contextBuilder.js`
- `frontend/src/utils/finalizationGuard.js`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/stores/memoryStore.js`
- `frontend/src/stores/settingStore.js`
- `frontend/src/stores/volumeStore.js`
- `frontend/src/views/WriterView.vue`
- `frontend/src/prompts/audit.js`
- `frontend/src/prompts/chapter.js`
- `backend/routers/provenance_support.py`
- `backend/routers/chapters.py`
- `backend/routers/novel.py`
- `backend/routers/settings_library.py`
- `backend/routers/volumes.py`
- `backend/migrations/20260705_state_provenance_phase1_2.sql`
- `tmp/test_state_provenance_phase1_2_contract.mjs`
- `tmp/test_context_pack_v2_phase1_contract.mjs`
- `tmp/test_finalization_guard.mjs`
- `tmp/test_finalization_postprocess_contract.mjs`
- `tmp/test_finalize_endpoint_contract.mjs`
- `tmp/realistic-flow-qa/contextpack-v2-phase1-report.md`
- `tmp/realistic-flow-qa/state-provenance-phase1-2-report.md`

`frontend/package-lock.json` 仍保留 Phase 1.1 的 optional wasm metadata 修复，`package.json` 未变。

## Provenance 写入路径审计表

| 路径 | 当前状态 | Phase 1.2 修复方式 | 剩余风险 |
| --- | --- | --- | --- |
| `chapter_versions` | 旧 schema 无 provenance columns，版本创建/定稿此前只写 content/version_type | `writerStore.createVersion/finalizeVersion` 构造 `sourceChapterNum/sourceVersionId/runId/finalizationId/commitStatus/provenance`；`backend/routers/chapters.py` 在 columns 存在时条件持久化；迁移草案补 columns/index | 真实旧 DB 需要人工执行迁移后才会落列；未迁移时 health-check 仍按 unknown/degraded 暴露 |
| `chapter_beat_plans` | content-only；小纲不能当事实源 | `saveChapterBeatPlan` 默认 `commitStatus=plan_only`；backend 条件持久化；ContextPack 仍只放进 `guardSnapshot`，projection dry-run 拒绝为 authority | 真实旧 DB 未迁移时 provenance 不落列；小纲冲突由 health warning 暴露 |
| `canon_facts` | 有 `chapter_num/status/evidence`，缺 finalization provenance | `processChapterFinalization` 用 `buildFinalizationProvenance` 包装 facts；backend 条件持久化 | 接受旧 facts 时仍可能缺 run/finalization id，health-check 标 unknown/degraded |
| `characters` | `hard_state/soft_state` 可存 JSON，但无统一 provenance columns | 定稿后角色 state 写入 `lastStateProvenance`，payload 带 provenance；backend 条件持久化 | 手工编辑旧角色仍可能 unknown；暂未做强制阻断 |
| `setting_entities` | `profile` 可存 JSON，旧 schema 无专用 provenance columns | `normalizeEntityPayload` 把 provenance 放入 `profile.provenance`，同时 payload 带 scalar provenance；backend 条件持久化 | 未迁移时只有 profile fallback；旧 active entity 缺来源会 warning |
| `setting_change_events` | 有 `chapter_num/status/evidence`，缺 commit provenance | 定稿提取的 change event 用 finalization provenance 包装；backend 条件持久化；accept 时把 event provenance 传播到派生 entity/relation | 旧 accepted event 缺来源会 warning/block，不能静默当高可信 |
| `setting_relations` | 有 chapter/status/evidence，缺 provenance | `saveRelation` 保留 provenance payload；accept relationship event 时传播 provenance；backend 条件持久化 | 旧关系缺来源会 unknown/degraded |
| `project_volumes.stage_summary_report` | report JSON 可承载 settlement，但 ContextPack 此前只看顶层 snapshot provenance | `saveStageSummary` 写 `snapshotProvenance/sourceExplanation`；ContextPack 同时读取顶层与 `stageSummaryReport.snapshotProvenance`；backend 条件持久化 project_volumes | 本阶段不做真实长篇 story block 重建，只提供 dry-run/projection 入口 |

## Project Health Check / Dry-Run

新增 `checkProjectStateHealth(snapshot, { chapterNum })`，输入合成 project snapshot，输出：

- `blocked`
- `issues`
- `contextPack`
- `creativeContext`

Fixture 覆盖点与输出摘要：

- 空章但存在 accepted setting/change event：输出 blocking `empty_chapter_authority`。
- failed/unfinalized 来源 active entity / accepted event：输出 blocking `untrusted_source`。
- failed story block snapshot：输出 blocking `untrusted_stage_snapshot`，不进入 `creativeStageContract.activeStoryBlock`。
- unknown/degraded 来源进入 prompt-facing context：输出 warning `unknown_provenance` 与 `prompt_facing_degraded_context`，并带 `trustLevel=unknown/degraded`，不静默当 high-trust。
- pending/half-success/failure-after-chapter-commit finalization marker：输出 blocking `finalization_pending`。
- saved beat plan 与 final fact 冲突：输出 warning `saved_beat_plan_conflict`，beat plan 不进入 projection authority。
- guard-only roadmap/future secret：`guardSnapshot` 可保留；`creativeContext` 不含 future secret、guard-only forbidden 或 saved beat plan。

## Projection Rebuild Dry-Run

新增 `rebuildStateProjectionFromFinals(snapshot, { chapterNum })`：

- 只从 final chapters / final versions / final provenance 解释 `stateAuthority.finalChapters` 和可接受 facts/settings。
- 明确拒绝 non-final chapter version、failed candidate、plan-only beat plan。
- fixture 证明 `v97-final` 与 final fact 可进入 projection，`v98-failed` 失败候选正文和冲突小纲不会进入 projection JSON。

## Finalization State Protocol

新增 `finalizationProtocol.js`：

- `createFinalizationProtocol`: 初始 `staged`。
- `transitionFinalizationProtocol`: 支持 `validated`、`committed`、`failed_pre_commit`、`failed_after_chapter_commit`。
- `finalizationProtocolToMarker`: 非 committed 状态转 durable marker；`committed` 返回 `null`。

集成变化：

- `beginChapterFinalizationRun` 生成 `runId/finalizationId`。
- `WriterView.performFinalize` 把 `runId/finalizationId/sourceVersionId` 传给 `writerStore.finalizeVersion` 和 `memoryStore.processChapterFinalization`。
- 半成功/后处理失败仍保留 durable `failed_after_chapter_commit` marker，下一章 health-check 阻断。

## No-Model 测试与结果

已执行并通过：

- `node tmp\test_context_pack_v2_phase1_contract.mjs`
  - 结果：`context pack v2 phase1 contract tests passed`
- `node tmp\test_state_provenance_phase1_2_contract.mjs`
  - 结果：`state provenance phase1.2 contract tests passed`
- `node tmp\test_finalization_guard.mjs`
  - 结果：`finalization guard tests passed`
- `node tmp\test_finalization_postprocess_contract.mjs`
  - 结果：`finalization postprocess contract tests passed`
- `node tmp\test_finalization_generation_gate_contract.mjs`
  - 结果：`finalization generation gate contract tests passed`
- `node tmp\test_finalization_retry_contract.mjs`
  - 结果：`finalization retry contract passed`
- `node tmp\test_finalize_endpoint_contract.mjs`
  - 结果：`finalize endpoint contract tests passed`
- `node tmp\test_setting_event_status_field_contract.mjs`
  - 结果：`setting event status field contract OK`
- `python -m py_compile backend\routers\provenance_support.py backend\routers\chapters.py backend\routers\novel.py backend\routers\settings_library.py backend\routers\volumes.py`
  - 结果：通过，无输出。

## Static Build

已执行：

- `npm --prefix frontend run build`
  - 结果：通过，Vite 输出 `✓ built`。
  - 提示：存在 Vite `INEFFECTIVE_DYNAMIC_IMPORT` warning，原因是 `writerStore.js` 同时被动态和静态导入；不是 Phase 1.2 新阻断。

本阶段没有再次运行 `npm ci`。Phase 1.1 已修复 lockfile 并验证 `npm ci`；Phase 1.2 未新增依赖。

## 模型辅助验证

本阶段没有执行新的离线模型辅助验证。Phase 1.2 的硬验收是 deterministic/no-model health-check、projection dry-run 和 contract tests。

## Fresh Review

已开启 fresh read-only review 子线程：

- 子线程 ID：`019f2e30-2fc1-7401-9dc0-e495984e543e`
- Goal：只读审查 Phase 1 + Phase 1.1 + Phase 1.2 未提交 diff，关注 ContextPack 分层、provenance 写入/条件持久化、health-check/projection/finalization protocol、测试与报告。
- 边界：不启动服务、不跑 live、不写真实 DB、不执行真实 migration、不恢复 LongformBrowser、不跑第98/99/50、不进入 Phase 2。
- 初次结论：发现 2 个 Critical、3 个 Important，判定不 Ready。
- 已处理：
  - `persist_provenance_if_columns` 现在只有 incoming payload 或 fallback 含 meaningful provenance 时才写入，避免普通更新覆盖已有 provenance 为 unknown。
  - backend provenance normalize 改为非空字段优先，nested provenance 不再被 Pydantic 默认空字符串覆盖。
  - `update_canon_fact` 跳过 `provenance/sourceProvenance/snapshotProvenance/sourceChapterNum/sourceVersionId/runId/finalizationId/commitStatus`，统一交给 provenance helper。
  - `backend/routers/helpers.py` 将 `provenance` 加入 `JSON_FIELDS`。
  - retry finalization postprocess 现在把 `sourceVersionId/runId/finalizationId` 传入 `processChapterFinalization`，失败 marker 也保留这些字段。
  - no-model tests 增加静态合同断言覆盖上述修复点。
- 二次复核：剩余 1 个 Important，指出 `update_canon_fact` 在 provenance-only update 时 early return，helper 未执行。
- 最终处理：`update_canon_fact` 的 `if not sets` 分支现在先调用 `persist_provenance_if_columns("canon_facts", fid, data)` 再返回，provenance-only update 可正常交给 helper。
- 最终复核结论：同一只读 review 子线程确认无新的 Critical/Important，`Ready for Phase 1.2 handoff`。

## 未完成风险 / Phase 2 入口

- 迁移文件是 dry-run 草案，当前线程未执行真实 DB migration；旧 DB 在未迁移前依靠条件持久化 fallback 与 health-check warning/blocking 防护。
- health-check 目前支持合成 snapshot / contextOptions 输入；后续可接项目级 CLI/API，把真实项目读取做成 read-only dry-run。
- projection rebuild 是 no-model 入口，不做真实长篇全量重建；Phase 2 前可扩展为项目级 projection report。
- NarrativeVoiceContract 仍保持 Phase 1 schema/lint，不改文学写作引擎。
- 未进入 Phase 2、未跑 live 章节、未写真实 DB、未恢复 LongformBrowser、未跑第98/99/50。
