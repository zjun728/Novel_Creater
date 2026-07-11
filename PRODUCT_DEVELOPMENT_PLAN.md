# 产品开发规划

> 当前有效规划。日期：`2026-07-11`。

## 1. 产品权威层级

产品和实现判断按以下层级执行：

1. `STORY_QUALITY_CHARTER.md`：最高产品质量原则。
2. `docs/superpowers/specs/2026-07-11-writer-core-v1-design.md`：Writer Core V1 实现权威。
3. `docs/superpowers/plans/2026-07-11-writer-core-v1-roadmap.md`：M1–M8 交付权威。

`STORY_QUALITY_CHARTER.md` 的质量总纲不能被 Writer Core design/roadmap 替代。总体设计定义实现规则，roadmap 定义交付顺序；本文件只汇总当前完成度和下一里程碑授权。

实施分支为 `codex/writer-core-v1`，唯一基线为 `4b85e8d`。旧数据库结构、旧 API、旧独立写作状态链、旧 runner 和旧 artifact 不恢复，不增加兼容层、dual-write 或 fallback。

远端 `main` 在 `4b85e8d` 后已有 `13` 个尚未合并的旧 control-plane 分叉提交。`codex/writer-core-v1` 可以安全推送为独立分支，但 canonical `main` 的 promotion/replacement policy 必须单独明确；禁止把旧分叉或兼容链无脑 merge/cherry-pick 回来。

## 2. 产品目标

Writer Core V1 采用“保留产品外壳、替换写作内核”的路线：后端是正式状态的唯一写入口，Canon 是已发生事实的唯一事实源，作者对候选、ChangeSet 和定稿拥有最终决定权。

完整 V1 目标仍是通过正式产品 UI 手动完成《典镇山河》前 30 章，并经过 Provider、事务、浏览器和人工内容验收。M1 只是这一依赖链的基础，不代表完整产品可写。

## 3. M1 — 已完成

M1 已完成干净 Schema、Canon/Projection 基础、实体身份、事务边界和产品基础页收束。

当前证据：

- 等级：**L4 M1 No-Provider Ready**
- 产品数据库：MySQL `8.4.10`，`127.0.0.1:3307/novel_creator`
- Schema：`writer-core-v1.0.0`
- Manifest：`0697b6da4826b98c8e502ff7ad68a61b51fe7037b167b6d8175ae9d78dcff826`
- Foundation：`永乐大典`、三个种子、9 个 Provider profiles、8 个任务级绑定项
- Canon/Projection：`0 / 0`
- 空派生写作表：`25/25`
- Writer：停用；旧 Writer 入口返回项目库
- AI completion / upstream Provider model calls：`0`

完整证据见 `docs/development/writer-core-m1-evidence.md`。

## 4. M2 — 待编写并审计详细计划

M2 名称：创作契约、模型绑定、风格/语料/经验资产。

详细计划文件尚待创建：

`docs/superpowers/plans/2026-07-11-creation-contract-and-assets.md`

M2 的规划范围必须覆盖：

- `CreationContract`：从 selected seed、故事发动机和作者选择形成明确的项目创作契约。
- `StyleContract`：主风格、次要风味、偏好和禁忌的可确认契约。
- Corpus assets：本机原始语料、文件哈希、章节边界、规范化文本、索引和分析版本。
- Experience assets：可复用的高质量经验卡、原创微示范和结构化方法。
- Model bindings：新项目复制与逐项确定性回退；无 enabled model 时阻止 AI 操作。

M2 详细计划必须先对照总体设计和 roadmap 审计，明确 Schema/API/UI、TDD 顺序、资产质量门禁、敏感信息边界和验收证据。当前只允许写计划和做审计，**不开始实现**。

## 5. M3–M8 顺序

M2 获批并完成后，严格按 roadmap 推进：

1. M3：StoryBlock、StoryStage、SceneTask 和章节容量。
2. M4：ChapterSession、WorkingDraft、DraftCandidate 和编辑流程。
3. M5：分场景生成、参考检索、防复制和质量审核。
4. M6：FinalizationChangeSet 与原子定稿。
5. M7：Writer UI 收束和跨层浏览器诊断。
6. M8：《典镇山河》前 30 章人工验收。

不得跨里程碑提前恢复写作入口，也不得用低等级 evidence 代替 Provider 或人工内容验收。

## 6. 共同门禁

每个后续里程碑都必须：

- 从上一个已验收里程碑继续，不引入旧兼容链。
- 先批准详细计划，再以 TDD 实现。
- 通过正式 unit、必要的 disposable MySQL integration 和固定 browser 回归。
- 由主控执行真实浏览器探索并审计同次状态证据。
- 不在 API、日志、错误、诊断、导出或浏览器 payload 中暴露 Provider 敏感值。
- 只授予实际取得的证据等级。

真实 Provider 和正文生成只在相应后续里程碑明确授权后运行。M1 文档不得据此推导任何正文或内容质量结论。

## 7. 当前授权

当前唯一授权任务是：创建、评审并批准 M2 detailed plan。完成该审计前停止，不进入 M2 代码、资产导入、Provider 调用或正文生成。
