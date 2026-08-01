# 当前项目状态

> 新任务或上下文压缩后先读本文件。事实日期：`2026-08-01`。

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
- 当前完成交付包：**Phase 3 Story Planning**。
- 当前开发分支：`codex/phase3d-boundary-acceptance`。
- Phase 3D 与 Phase 3 已完成：Future Plan/Actual Progress/Canon Projection 同 revision 只读组合与完整 Phase 3 门禁。
- 唯一下一步：**Phase 4 Writer Loop**。
- 交付基线：`main@e8aebd9eb851ccc64f160022984342344905cd15`。
- 功能代码 HEAD：`382dcefa57f575209cc703d3af0e60fd1b11137d`。
- 当前自动证据边界：Real Provider calls `0`、Product DB reads/writes `0/0`、
  Disposable MySQL 8、UI-only 真实浏览器；正式 Writer Loop、Finalization 和
  Content Quality 仍未就绪。

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

## Phase 3B 已完成能力

- 正式 `/planning/volumes` 与 `/planning/plots` 路由，共享一个
  `ProjectPlanningView`、一个 Planning workspace 和一个 `planningStore`。
- 作者可以手工创建、编辑、排序、退役并保存 Volume/Plot Draft；模型未就绪不影响
  手工工作。
- AI Planning 使用 production gateway 边界、冻结故事 manifest、两段短事务、
  幂等键、租约、fencing token 与精确 Draft CAS；迟到结果不覆盖作者编辑。
- Planning history 的 current/superseded/archived 状态及项目下一步均由后端权威
  计算；归档和被取代历史可读不可写。
- 正式 UI-only 浏览器门禁覆盖手工、AI、并发漂移、未知结果恢复、历史只读、
  canonical route、后端下一步和秘密扫描。
- 最终门禁：focused Python `193`、focused Node `59`；完整 Python
  `2542 passed, 6 skipped`、Node `216 passed`、frontend `415 passed`；
  integration `317 passed`，数据库 `316/316/0`；browser 数据库 `2/2/0`；
  build `2949 modules transformed`。

Phase 3B committed acceptance 见：

- `docs/acceptance/2026-07-24-phase-3b-volumes-plots.md`

## Phase 3C 已完成能力

- 唯一 `planning-v1` 聚合、唯一 `planningStore` 和第三个 Planning tab 现已覆盖
  StoryBlock、Stage 与 SceneTask；Planning 不保存 target chapter count、
  completed 或 manual actual progress。
- 作者可手工创建、CAS 保存、确认和查看 ChapterOutline 历史；显式 AI 生成只经过
  fake 外部边界，不自动确认 Outline，也不创建 ChapterSession。
- authority drift 会 supersede 迟到结果；当前章节由后端权威算法决定，每个项目最多
  一个 drafting Session。
- 已存在 Session 保留创建时的 Planning/Outline pins，并可按相同 authority
  幂等重放。
- Overview、Outline、Session 和 Writer 均使用后端 `targetPath` 与权威章节；
  Writer 只读 Outline 摘要并从空 WorkingDraft 进入。
- 最终门禁：focused Python `250 passed`、focused Node `144/144 passed`；
  browser `7` 场景；完整 Python `2814 passed, 6 skipped`、root Node `243/243`、
  frontend Node `522/522`；integration `342 passed`；build
  `2956 modules transformed`。

Phase 3 acceptance 见：

- `docs/acceptance/2026-07-26-phase-3c-story-blocks-outlines.md`
- `docs/acceptance/2026-07-30-phase-3-story-planning.md`
- `docs/acceptance/2026-07-31-phase-3-immutable-boundary-alignment.md`

## 当前 Schema 与数据库边界

- 当前开发分支 committed 源码 Schema：`writer-core-v1.6.0`。
- Phase 3B 没有 Schema 变更、迁移或兼容路径。
- Phase 3C 没有 Schema 变更、迁移或兼容路径。
- Phase 3D 将 Candidate 依据身份纳入 `writer-core-v1.6.0`；没有 migration 或 compatibility path。
- 产品数据库现存 Schema 未读取、未重建、未验证。
- 源码 Schema 版本不得推导为产品数据库现存版本。
- 不迁移旧数据，不保留旧 Planning 表兼容查询。
- Phase 3 自动集成只能使用随机命名的 Disposable MySQL 测试库。

## 尚未完成

- Phase 4：正式三栏写作台、可靠自动暂存、流式新稿、改写/扩写/压缩、候选、
  对比和融合。
- Phase 5：质量审核、单次 `FinalizationChangeSet` 提取、整体确认、
  Canon 写入、单事务定稿和完整回滚。
- Phase 6：小说下载、安全项目备份、预检和导入。
- Phase 7：产品数据库、真实 Provider、自由浏览器探索和《典镇山河》前 30 章
  人工内容验收。

## 唯一下一步

建设并验收 **Phase 4 Writer Loop**。它以前序完整的 Phase 3 规划链为基础；自动
门禁继续禁止真实 Provider、产品数据库和 live 网站。Seed、Contract 与 Bible 的
已确认内容保持永久基线；未来 Planning 只处理尚未实现的内容。正文定稿前对应
大纲可以调整，正文定稿后大纲与事实不可修改，均以已实现和规格明确支持的范围为准。
Setting 与知识库仍在 Phase 5 通过 Canon/Projection 落地，不在本阶段声称已实现。
