# 当前项目状态

> 新任务或上下文压缩后先读本文件。事实日期：`2026-07-18`。

## 当前权威

按以下顺序判断产品事实：

1. `STORY_QUALITY_CHARTER.md`：内容质量最高原则。
2. `docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`：当前产品、交互和写作闭环主规格。
3. 当前阶段实施计划及其验收报告。
4. 本文件、`PRODUCT_DEVELOPMENT_PLAN.md` 和 `DEVELOPMENT_LOG.md`：已取得的证据与下一步。

旧 Writer Core 路线、phase-e shadow QA、旧 runner、旧 artifact 和其他 worktree
都不是当前运行事实，也不得作为兼容或 Ready 证据。

## 当前结论

- Canonical release branch：`main`。
- Phase 1 交付分支：`codex/product-shell-lifecycle`。
- Phase 1 代码验收快照：`dd40cf2e452243c6c8085fd486a3831b6e059796`。
- 当前完成阶段：**Phase 1 产品壳层与项目生命周期**。
- 证据边界：**No-Provider、Disposable MySQL 8、真实浏览器 Ready**。
- 完整产品重构、完整写作闭环、真实 Provider、正式产品数据库和内容质量均未据此宣告完成。

## Phase 1 已完成能力

- 正式产品壳层：项目库、当前项目上下文、项目概览、Provider 设置。
- 路由是项目上下文来源；刷新、深链接和浏览器前进/后退可恢复当前页面。
- 项目生命周期：按名称创建、打开、重命名、归档、Toast 撤销、恢复、永久删除。
- 永久删除只存在于已归档项目页，且只有一次红色危险确认。
- `archived_at` 与写作状态分离；`lifecycle_revision` 保护归档、恢复和永久删除并发。
- 已归档项目服务端统一拒绝写入；项目私有数据由 Schema 所有权关系清理，共享资产不会随项目误删。
- 普通反馈使用 Toast；表单错误就地显示；全局阻断操作使用唯一遮罩和焦点管理。
- Provider 公共响应只返回 `hasKey`、`hasBaseURL` 等布尔状态，不返回
  `apiKey/api_key/baseURL/base_url` 明文。
- 旧 `/project/...`、旧 `/writer/...` 字面路由和旧项目删除实现已从生产实现中清除。

## 当前 Schema 与数据库边界

- 当前源码 Schema：`writer-core-v1.2.0`。
- 当前源码 manifest：
  `6164f0f57d3acd59dcab054549d634a4138b82a18962f145140fd56f0244ab4b`。
- Phase 1 没有启动、读取或写入产品数据库。
- Phase 1 的集成与浏览器测试只使用
  `^novel_creator_test_[a-f0-9]{32}$` 随机测试库，并在每轮结束后删除。
- 本轮没有重新验证产品数据库的现存版本，因此旧文档中的产品库版本和计数不能当作
  Phase 1 当前事实。
- 源码已不提供运行时兼容迁移。产品服务下一次按 v1.2 正式启动前，必须另行明确批准
  一次开发数据库重建；不能让应用启动时自动执行 DDL。

## 当前测试证据

基于 `dd40cf2` 的发布门禁：

- `npm test`：exit `0`；Python `1398 passed, 3 skipped`，scripts
  `185 passed`，frontend `184 passed`。
- `npm run test:integration`：exit `0`；`154 passed`；测试库
  `created=153`、`cleaned=153`、`remaining=0`。
- `npm run test:browser:product-shell`：exit `0`。
- `npm --prefix frontend run build`：exit `0`，`2855 modules transformed`。
- `git diff --check`：exit `0`。
- Provider/model calls：`0`。
- 产品数据库 reads/writes：`0/0`。

完整证据见
`docs/acceptance/2026-07-18-phase-1-product-shell.md`。

## 尚未完成

- Phase 2：创作资产、市场来源、选题与种子、创作契约、圣经、模型继承和资产冻结。
- Phase 3：分卷、情节、故事块、小纲，以及“已发生事实/未来计划”分层。
- Phase 4：正式三栏写作台、可靠自动暂存、流式新稿、改写/扩写/压缩、候选、对比和融合。
- Phase 5：质量审核、单次 `FinalizationChangeSet` 提取、整体确认、单事务定稿和完整回滚。
- Phase 6：小说下载、安全项目备份、预检和导入。
- Phase 7：真实产品 MySQL 8、真实 Provider、自由浏览器探索和《典镇山河》前 30 章人工内容验收。

当前 `ChapterWriterView` 仍只是既有最小写作路径，不代表 Phase 4 已完成。任何真实正文
生成前，必须先关闭 WorkingDraft Integrity 风险：屏幕可见正文必须是候选冻结和 AI
操作的唯一输入，未保存编辑不得被响应覆盖，Provider 调用不得占用长数据库事务。

## 唯一下一步

先完成 Phase 1 合并发布。随后按主规格编写并审计 **Phase 2 创作准备实施计划**。
产品数据库 v1.2 重建是一个单独、显式批准的本机开发操作；没有该批准不得执行。
