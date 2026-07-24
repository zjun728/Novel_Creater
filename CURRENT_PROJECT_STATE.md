# 当前项目状态

> 新任务或上下文压缩后先读本文件。事实日期：`2026-07-24`。

## 当前权威

按以下顺序判断产品事实：

1. `STORY_QUALITY_CHARTER.md`：内容质量最高原则。
2. `docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`：
   产品、交互和写作闭环主规格。
3. `docs/superpowers/specs/2026-07-24-phase-3-story-planning-design.md`：
   当前 Phase 3 领域设计。
4. 当前阶段实施计划及其验收报告。
5. 本文件、`PRODUCT_DEVELOPMENT_PLAN.md` 和 `DEVELOPMENT_LOG.md`：
   已取得的证据与下一步。

旧 Writer Core 路线、phase-e shadow QA、旧 runner、旧 artifact 和其他 worktree
都不是当前运行事实，也不得作为兼容或 Ready 证据。

## 当前结论

- Canonical release branch：`main`。
- Phase 2 验收链已进入 `main`，链末提交：
  `f11faad531f04250f2a987390a468dfd14bf06a3`。
- 当前完成阶段：**Phase 2 Creative Foundation（创作地基）**。
- 当前开发分支：`codex/phase3-story-planning`。
- 当前工作：**Phase 3 Story Planning（故事规划）**。
- 当前自动证据边界：No-Provider、Disposable MySQL 8、UI-only 真实浏览器。
- Product DB、Real Provider、Phase 4 Writer Loop、Phase 5 Finalization 和
  Content Quality 均未评估，不得据 Phase 2 门禁宣告 Ready。

## Phase 2 已完成能力

- 创作资产：10 套批准风格模板、64 张批准经验卡和受管本地语料。
- Provider/模型设置保持公共响应无明文秘密，并具有项目模型绑定与 fallback。
- 市场来源、不可变快照、趋势分析、种子保存与单一活动种子选择。
- 故事发动机、创作契约、创作圣经及其不可变 revision、上游绑定与
  superseded 围栏。
- 项目中心和正式导航中的创作地基入口。
- 正常启动只验证 Schema，不执行历史兼容 DDL。

Phase 2 的 committed acceptance 见：

- `docs/acceptance/2026-07-18-phase-2a-assets-providers.md`
- `docs/acceptance/2026-07-18-phase-2b-market-seeds.md`
- `docs/acceptance/2026-07-18-phase-2c-contract.md`
- `docs/acceptance/2026-07-23-phase-2-creative-foundation.md`

上述报告记录了当时的自动门禁结果；本文件没有重新运行这些门禁，也不把报告范围
外推为产品数据库、真实模型或小说内容质量事实。

## 当前 Schema 与数据库边界

- `main` 当前 committed 源码 Schema：`writer-core-v1.4.0`。
- Phase 3 设计目标是从空库建立 `writer-core-v1.5.0`，不迁移旧数据，
  不保留旧 Planning 表兼容查询。
- 当前阶段不得把源码 Schema 版本当作产品数据库现存版本。
- 当前没有重新读取、重建或验证产品数据库。
- Phase 3 自动集成只能使用随机命名的 Disposable MySQL 测试库。

## 尚未完成

- Phase 3：Planning aggregate、分卷、情节、故事块、阶段、场景任务、小纲，
  以及未来计划与只读实际进度的边界。
- Phase 4：正式三栏写作台、可靠自动暂存、流式新稿、改写/扩写/压缩、候选、
  对比和融合。
- Phase 5：质量审核、单次 `FinalizationChangeSet` 提取、整体确认、
  Canon 写入、单事务定稿和完整回滚。
- Phase 6：小说下载、安全项目备份、预检和导入。
- Phase 7：产品数据库、真实 Provider、自由浏览器探索和《典镇山河》前 30 章
  人工内容验收。

## 唯一下一步

按已批准的 Phase 3 设计和实施计划完成 **Phase 3 Story Planning**。当前先实施
Phase 3A Planning Aggregate Foundation；不得提前调用真实 Provider、读写产品
数据库，或把 Phase 4 写作环、Phase 5 定稿和内容质量标记为已完成。
