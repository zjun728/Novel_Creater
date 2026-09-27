# ContinuityIssue 独立持久化边界

日期：2026-09-08。状态：只读设计完成，尚未实施或迁移产品数据库。

依据：`2026-08-30-p0-author-product-design.md` §9.5、§11，以及已批准的作者全流程修复计划。它记录时间、位置、人物状态、规则、已发生事实冲突和跨章补偿；普通文风建议仍属于章节审查。问题记录及状态处理绝不修改 Canon、Projection、历史正文或 Planning。

## 实施顺序

1. 固定历史 v114 升级边界。现有 `backend/scripts/upgrade_product_database_v114.py` 从当前 manifest 排除 Topic fragment 推导 v113，并依赖当前版本常量；新增 fragment 前须固定 v113/v114 的 fragment 集合、版本、manifest hash 和 91/99 表目标。保留旧迁移的真实含义，不能把旧迁移目标改成 100 表。
2. 新增 `65_continuity_issues.sql`，放在 Canon 之后、导入 fragment 之前。版本升为 `writer-core-v1.15.0`，总表数 100。只增加 ID、项目、类别、严重度、三状态、来源章节/Finalization/Canon revision、问题说明、处理建议、未来处理目标、处理说明、时间戳。处理说明属于已有“说明”范围；不添加人员、排期、事件日志、调度系统。
3. 独立新增领域模型、仓储、服务和 router。GET 列表/单条，创建及状态处理；列表最多 50 条。状态仅 `pending/resolved/ignored`；后两者处理说明必填。`lock_active_project` 后校验项目与来源，使用 `expectedUpdatedAt` 防止覆盖并发修改。创建用稳定请求 UUID 安全重试。未来处理目标只保存作者说明，不能调用 Planning 写服务。
4. 同时闭合项目备份、导入和删除。问题属于项目作者数据，不得归入内部排除表。导出新记录类型、显式字段策略与来源逻辑引用；导入重映射来源 Finalization ID、校验同章同定稿关系并保留状态与说明；旧包无问题记录仍可导入。永久删除顺序将新表置于 Finalization 之前。
5. 增加独立 `/continuity/issues` PC 页面与连续性导航。提供三状态筛选、创建、处理、来源跳转、空态和重试。归档项目只读。历史证据入口可以创建未来纠偏记录，但状态“已解决”仅代表作者记录的处理结论。
6. 测试代码和一次性 MySQL 增量升级均通过后，准备独立 v114→v115 升级命令。产品执行顺序：停止写入、生命周期隔离、来源 inventory/结构/hash 核验、私密完整备份及回执校验、单表 DDL、metadata CAS、100 表与 manifest 核验、恢复服务。禁止 initializer 重建、市场重播或自动删库恢复。

## 来源与一致性

- `(project_id, source_finalization_id)` 复合外键引用 `finalization_records(project_id,id)`；Canon revision 以项目和 revision_number 复合引用，不能跨项目。
- 服务联查来源 `final_chapters`，确认来源章节、Finalization、committed Canon revision 属于同一条定稿。各个字段分别存在不足以证明一致性。
- 从历史证据创建时，服务填入完整正式来源；尚无正式来源的手工记录明确为空，不能把当前 head 冒充来源。来源字段创建后固定。
- 更新说明与状态采用时间戳 CAS；新更新时间必须严格大于旧值。所有查询带项目条件，写入先走归档守卫。
- MySQL DDL 会自动提交。DDL 后失败必须保留备份回执并报告恢复所需状态，不能声称事务自动回滚。旧版服务回退必须与数据库兼容性一起处理，不能静默修改 schema metadata。

## 必须接入的封闭清单

- `backend/repositories/project_packages.py`：PROJECT_OWNED_TABLES、PROJECT_TABLE_RECORD_TYPES、逐字段 PROJECT_TABLE_COLUMN_POLICIES、逻辑引用映射及导出决策 fingerprint；审计每个字段后更新 fingerprint。
- `backend/domain/project_packages.py`：continuity-issue 字段白名单。
- `backend/domain/project_import_plans.py`：正式记录分类、必填字段、三状态与来源引用验证；同章同定稿一致性。
- `backend/domain/project_import_publication.py`：encoder、STATIC_TABLE_COLUMNS、枚举及 Finalization 之后的发布顺序。
- `backend/repositories/projects.py`：删除顺序；`test_archived_write_inventory.py`：每个新增写入口。
- `backend/schema_manifest.py`、`schema_version.py`：100 表与版本；报错指引须指向无损增量升级，不只提示重建数据库。

## 精准验证命令

以下新增测试文件名作为实施约定，实施前尚不存在的文件不能被报告为已通过。MySQL 测试按项目测试门禁分配一次性测试库、核验归属并清理，不连接产品库。

```powershell
python -m pytest backend/tests/unit/test_continuity_issues.py backend/tests/unit/test_continuity_issue_repository.py backend/tests/api/test_continuity_issue_routes.py -q
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_initialize_database.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_project_import_schema.py backend/tests/unit/test_upgrade_product_database_v114.py backend/tests/unit/test_upgrade_product_database_v115.py -q
python -m pytest backend/tests/unit/test_project_package_repository.py backend/tests/unit/test_project_import_graph.py backend/tests/unit/test_project_import_authority_rewrite.py backend/tests/unit/test_project_lifecycle_repository.py backend/tests/unit/test_archived_write_inventory.py -q
python -m pytest backend/tests/integration/test_continuity_issues_mysql.py backend/tests/integration/test_upgrade_product_database_v115_mysql.py backend/tests/integration/test_project_package_snapshot_mysql.py backend/tests/integration/test_project_import_publication_mysql.py backend/tests/integration/test_product_database_readiness_mysql.py -q
node --test frontend/tests/unit/continuityIssuesView.test.mjs frontend/tests/unit/productShell.test.mjs
```

验收重点：来源跨项目和不一致三元组拒绝；空说明拒绝；三状态闭合；并发修改拒绝；归档拒写；创建重试不重复；没有其他权威表写入；100 表分类与列策略闭合；v114 历史升级仍为 99 表；v115 仅增一表；备份失败前零 DDL；DDL 后失败保留回执；问题记录导出→导入→再导出与来源重映射；旧包兼容。

PC 浏览器采用 1440×900、1920×1080，验证创建→刷新→处理→刷新→来源定稿跳转、错误重试与归档只读。所有演示记录使用独立、可识别测试项目；按精确 ID 清理并以 GET 404 证明删除。此计划不构成已完成声明。
