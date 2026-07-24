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
- 当前完成交付包：**Phase 3A Planning Aggregate Foundation**。
- 当前开发分支：`codex/phase3-story-planning`。
- 当前工作：**Phase 3B Volumes and Plots**。
- 当前自动证据边界：No-Provider、Disposable MySQL 8；Phase 3A 未运行浏览器验收。
- Phase 3B–3D、Product DB、Real Provider、Phase 4 Writer Loop、Phase 5
  Finalization 和 Content Quality 均未评估，不得据 Phase 3A 门禁宣告 Ready。

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

## Phase 3A 已完成能力

- `writer-core-v1.5.0` Planning/Outline 闭合领域模型和完整 Schema。
- Planning Draft、显式保存、幂等确认、不可变历史、稳定节点身份、canonical
  hash、完整 CAS 和事务回滚。
- Seed/Contract/Style/Bible generation fence；A → B → A 不复活旧 Planning。
- ChapterSession 精确钉住当前 Planning、Outline、Canon 与 Projection；
  existing-session 快速路径不能绕过权威重校验。
- 当前 schema 同版本开发重置；v1.1/v1.4 迁移、旧 Planning 表、旧 Store 和旧
  生成链已从当前运行面退役。

Phase 3A committed acceptance 见：

- `docs/acceptance/2026-07-24-phase-3a-planning-aggregate.md`

## 当前 Schema 与数据库边界

- 当前开发分支 committed 源码 Schema：`writer-core-v1.5.0`。
- 产品数据库现存 Schema 未读取、未重建、未验证。
- 源码 Schema 版本不得推导为产品数据库现存版本。
- 不迁移旧数据，不保留旧 Planning 表兼容查询。
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

从干净的 Phase 3A 提交继续实施 **Phase 3B Volumes and Plots**：交付手工与
AI Planning Draft、分卷/情节线正式 API 和页面、项目导航及 archived/superseded
只读历史。自动门禁继续禁止真实 Provider 和产品数据库。
