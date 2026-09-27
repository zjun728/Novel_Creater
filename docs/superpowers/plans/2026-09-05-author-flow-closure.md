# 作者前端全流程收口

用户于 2026-09-05 同意按整体审查后的调整执行。沿用 P0 总设计与既有核心，不重做 B/C/D，不将局部完成写成全部交付。主工作区已有证据/进度修复及诊断文件完整保留；未经授权不推送。

用户已取消周额度停止条件。2026-09-10 按“开始吧”恢复连续性模块缺口修复；保留此前“当前任务完成后先安全停止”的交付边界，未自动进入正文生成。

最新界面范围：用户明确只需常规 PC 宽高尺寸，后续按 1440×900 / 1920×1080 桌面验证，不再开展窄屏适配或专项验收。

## 已确认调整

- 规划按当前卷和故事块组织；阶段、场景任务在块内展开。
- 连续性各入口共用实体详情，按显式实体引用展示事实、状态、记忆、弧光与来源；不按名称合并事实。
- 小纲编辑和确认归规划页；工作台复用只读查看，历史钉住版本不变。
- 工作台左右栏可收起，当前章所属卷为默认卷；候选与审查使用宽面板。
- 审查支持原文、事实修正/排除、重新校验及明确失败恢复。
- 连续性问题仅管理跨章问题，处理说明不冒充事实变更。
- 契约/圣经永久基线不变，确认前明确后果。
- 每批通过正式界面验证；三章真实综合验收在主体完成之后。

## 实施与验收记录

| 批次 | 范围与主要位置 | 验收终点 | 状态 |
| --- | --- | --- | --- |
| T0 | 选题中心四页：市场、讨论、方向、候选与项目交接；复用已完成 P0-C 与真实市场闭环 | 内容可读、证据可选、讨论可继续、方向/候选可明确保存与修订、指定版本交接后种子待确认；失败保留输入；已有来源接入不重复建设 | 核心真实链路已通过；小说阅读网刷新失败、模型间歇失败仍需跟进，详见 2026-09-07 验收记录 |
| E1 | continuity 只读服务/仓储/路由；共用详情和分页；项目导航 | 项目与实体隔离、同步快照、来源章节、空态/失败/重试及过期响应保护；无写入 | 9月10日只读详情及人物计划明确关联、节点编辑/确认/版本/ZIP往返均通过模块验收；真实三章综合链仍待验收 |
| E2 | PlanningWorkspace、独立小纲路由；连续性问题最小边界 | 当前规划易定位，小纲单一编辑职责；问题处理有说明且不修改事实 | 独立小纲、当前卷筛选及连续性问题处理已实现并分段验证；综合链待验收 |
| F1 | workbench bootstrap、卷摘要、有界索引 | 服务端区分历史/当前/未来，无读取建会话；1000+ 章生产查询有界 | 已实现；1001 章一次性 MySQL 库分页通过，综合验收待完成 |
| F2 | 统一工作台及历史阅读，复用现有写作 controller/store | 可收起三栏、当前卷定位、小纲查看、选区操作、候选比较；旧 URL 纯重定向 | 主入口、导航、小纲、选区预设及旧路由重定向已实现；相关正式分段门禁通过 |
| F3 | FinalizationPanel 与错误分类；现有待提交修复收口；推荐错误反馈 | 作者可纠错并重校验；模型失败保留输入；未确认内容不写事实 | 9月8日事实修正/证据补录及63项前端测试通过，产品UI保存R2并刷新验证；仍待确认/定稿综合链 |
| 验收 | 相关单测/数据库/浏览器与构建，真实三章按已授权边界执行 | 逐批证据明确；完整链与跨章质量独立记录 | 分段已有证据；真实三章尚未完成，必须后置于E1剩余功能 |

读接口使用数据库只读事务和薄响应，不能为了界面拼装全书正文或复制事实表。新逻辑用行为测试；视觉沿用现有纸张、墨色与朱红强调体系。任何运行时迁移需使用现有迁移流程，不绕过 schema 契约。

用户进一步明确选题中心内容规划也需纳入：先完成 T0 的现状复核及实质问题修复，再继续 E/F。E1 已开始的只读页面与验证成果保留；T0 不扩展成新增平台采集专项。整体真实三章仍后置，选题环节自身的必要真实讨论验收另记范围。

### 2026-09-07 续做记录

- T0 保存返回成功不再依赖库列表刷新；同一不可变建议重试使用同一保存标识。选题中心到模型设置再返回，当前证据与续谈对象由同一 Store 保留。28 项选题测试通过；这些结果不替代完整真实讨论/交接验收。
- E2 小纲迁至 `/projects/:projectId/planning/outlines`，复用原编辑器及离开保护；项目侧栏、规划分区、写作页回链及项目概览下一动作同步指向该入口。故事块默认显示当前卷，同时保留未分卷新草稿的可见性，不截断完整保存内容。
- 正式浏览器读取《典镇山河》当前第 4 章小纲，桌面及 390px 窄屏均已检查；没有新建该项目草稿或触发模型生成。截图位于 `output/playwright/outlines-sep7.png` 与 `outlines-mobile-sep7.png`（窄屏页签后续已做不拆字调整）。
- 本批最终证据：选题、规划、导航、小纲及连续性前端定向测试 101 项通过，补齐同项目小纲页切换保护后 controller 19 项通过；项目概览服务 31 项通过；最终构建通过。正式浏览器已操作切换其他卷（明确空态）及“定位当前卷”（恢复 1 个故事块），故事块页不再挂载小纲编辑器。390px 页面及主内容宽度无溢出。关联旧浏览器断言已同步更新，尚未重跑全部 Phase 浏览器门禁。

- 续做：五个真实市场适配器只读资格验证均成功，包含先前失败的小说阅读网；见 `output/market-continuation-verification.log`。这次没有发布新榜单快照，也未绕过刷新冷却。先前模型间歇失败原因仍未确认。
- E1 增加独立“实际故事进度”，与线索、伏笔分开；进度名称来自来源定稿章节钉住的规划版本。真实数据库读取《典镇山河》三个阶段均返回名称与来源章。只读响应禁缓存，版本变化返回标准错误码；前端分页拒绝不同版本结果。
- E1 正式页面已验证阶段名称、人物搜索、实体详情、重要记忆、校验通过的原文引用和弧光空态。模拟 409 后中文提示及重新读取恢复通过（故障为模拟，恢复读取为真实服务）。390px 查找按钮拆字已修复；截图 `output/playwright/continuity-progress-sep7.png`、`continuity-evidence-sep7.png`。后端定向 10 项、前端 controller 5 项通过；尚不代表综合三章验收或完整 E/F 交付。

### 2026-09-07 工作台续做（进行中）

- 通用周额度最近剩余 88%，继续执行。F3 保留工作树内的推荐状态修复已核对后复制到主工作区；契约组件 59 项通过，区分“推荐不可用”与“无推荐”，手工选择保留。
- F1 增加只读 bootstrap、卷摘要与最多 100 章索引；真实《典镇山河》第 2/4/5 章分别返回历史/当前/未来模式，未创建会话。两个真实索引页面分别返回 1–2 和 3–4 章。1001 章测试是服务层有界测试，不能冒充 1000+ 章真实数据库压力验收。
- 历史阅读前后章查询改为最多三条元数据。相关单测/API 47 项、MySQL 6 项通过，六个测试库清理成功；工作台 MySQL 1 项通过且测试库清理成功。
- 旧写作入口读取会自动建会话，已改为明确“开始本章写作”；写作页和 Store 39 项通过。工作台相关域、服务/API、原写作服务/仓储 228 项通过（后续索引扩展另有 9 项定向通过）。
- F2 当前/历史页复用同一按卷导航，当前页可收起目录和小纲/审查栏、展开审查及候选宽面板。当前页桌面/390px 已实际操作；截图 `output/playwright/workbench-navigation-sep7.png`、`workbench-wide-review-sep7.png`、`workbench-mobile-sep7.png`。统一 canonical URL 及旧 URL 重定向尚未实施。
- 正式 `@manual` 浏览器门禁首次停在 fixture 准备：旧脚本未安装运行时配置，独立调用复现 `RuntimeConfigurationError`。已补 fixture 与验证脚本配置初始化，正在重跑；此前失败不计通过。

本轮 focused/slice 命令：

```powershell
python -m pytest backend/tests/unit/test_continuity_reader.py backend/tests/api/test_continuity_routes.py -q
node --test frontend/tests/unit/continuityController.test.mjs
node --test frontend/tests/unit/projectContractView.test.mjs
python -m pytest backend/tests/unit/test_manuscript_repository.py backend/tests/unit/test_manuscript_service.py backend/tests/api/test_manuscript_routes.py -q
python -m pytest backend/tests/integration/test_manuscript_repository_mysql.py -q
python -m pytest backend/tests/unit/test_workbench_domain.py backend/tests/unit/test_workbench_reader.py backend/tests/api/test_workbench_routes.py backend/tests/unit/test_chapter_session_service.py backend/tests/unit/test_chapter_session_repository.py -q
python -m pytest backend/tests/integration/test_workbench_repository_mysql.py -q
node --test frontend/tests/unit/chapterSessionStore.test.mjs frontend/tests/unit/chapterWriterView.test.mjs
npm run build --prefix frontend
$env:PHASE3C_GREP='@manual'; node frontend/e2e/run-phase3c.mjs
```

### PC 工作台与选区交互续做

- 最新用户范围：只考虑常规 PC，后续验证 1440×900 / 1920×1080，不再做窄屏专项。
- canonical 入口 `/projects/:projectId/workbench/chapters/:chapterNumber` 已实现，旧写作/阅读 URL 仅重定向；当前/历史/未来由服务端 bootstrap 决定。正式 Phase3C `@manual` 已通过，HTTP allowed=306/forbidden=0；测试库 created=1/cleaned=1/remaining=0，过程/端口/临时/缓存残留均为 0，无真实模型或产品库调用。
- F1 追加真实一次性 MySQL 库的 1001 章合成数据验证：分页每页最多 100 章，不返回正文和完整规划；2 项 MySQL 测试通过，测试库 created=2/cleaned=2/remaining=0。此证据不代表模型生成了 1001 章。
- 当前和历史小纲均可弹窗放大，长内容内部滚动；实际 PC 浏览器打开、Esc 关闭通过，无重复 DOM id。截图见 `output/playwright/workbench-current-outline-modal-pc1440-sep7.png` 和 `workbench-history-outline-modal-pc1440-sep7.png`。
- 选区润色更名“去 AI 味/润色”，提示词保留事实、剧情、意图和信息量。五种改写预设填入同一临时要求，保留作者输入，超过 1000 字拒绝追加，不自动发起生成。
- 相关阅读/写作前端 37 项、预设与写作 16 项、提示词 6 项通过；小纲弹窗初版构建通过，最终选区版本构建及正式选区门禁待完成。周额度最近剩余 82%。

本批 focused/slice 精确命令：

```powershell
node --test frontend/tests/unit/rewritePresets.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/finalChapterReaderView.test.mjs
python -m pytest backend/tests/unit/test_chapter_draft_prompt.py -q
npm run build --prefix frontend
node frontend/e2e/run-phase4b3.mjs
```

- 2026-09-08：正式 Phase4B3 选区门禁 1/1 通过，覆盖预设填入、四种选区操作、停止生成及撤销。假模型、一次性数据库；DB/process/port/temp/artifact/Vite 残留均为 0，真实 Provider 调用及产品库读写为 0。初次失败定位为临时要求输入框缺少可访问名称，修复后通过。最终 PC 工作台构建通过。

### 2026-09-08 审查交互与连续性问题边界

继续已授权范围，周额度剩余 82%。先运行正式审查闭环，复核失败恢复、作者修正、确认、撤销及定稿后历史入口。并行只读复核工作台代码及连续性问题的独立迁移边界。后者不修改 Canon、Projection 或 Planning。

本批精确 focused/slice 命令：

```powershell
node --test frontend/tests/unit/finalizationPanel.test.mjs frontend/tests/unit/finalizationController.test.mjs frontend/tests/unit/finalizationEvidence.test.mjs
node frontend/e2e/run-phase5.mjs
```

用户于 2026-09-08 取消周额度停止条件，要求使用最大可用并行子代理推进。当前四路按文件分工，正式浏览器测试仍串行。

补充 focused/slice 命令：

```powershell
node --test frontend/tests/unit/writerNavigationGuard.test.mjs frontend/tests/unit/chapterWriterView.test.mjs
python -m pytest backend/tests/unit/test_workbench_review_reader.py backend/tests/api/test_workbench_review_routes.py -q
python -m pytest backend/tests/integration/test_workbench_review_mysql.py -q
python -m pytest backend/tests/integration/test_workbench_volume_versions_mysql.py -q
```

F5 修改前正式门禁 1/1 通过（假质量/提取Provider，测试库及过程资源残留=0，产品库读写=0）；新增排除入口与历史审查后需跑受影响切片。连续性问题独立边界计划见 `2026-09-08-continuity-issues-boundary.md`，当前没有修改schema或执行DDL。

### 2026-09-08 N/F 集成收口

用户要求所有子代理使用最高推理。三路继承模型并显式配置 ultra；快速模式无工具参数，未切换。最新取消周额度条件优先于上述历史快照。

- N 独立问题记录后端与页面已实现；v115 新增单表，历史 v114 迁移固定 91→99，新增 v115 为 99→100。升级单测/真实 MySQL 已通过，产品库目前仍 99 表，未执行 DDL。
- F3 排除事实/实际进度、修正未保存离开保护、历史定稿只读审查已实现。卷名使用已定稿章钉住的最新卷元数据；当前导航使用与候选/AI 一致的最新已确认小纲。
- 扩展 Phase5 正式 fake-provider 场景 1/1 通过，包含 N 创建、处理、重载、筛选及来源回链；修复下拉可访问名称和 query 切换时重复 bootstrap。测试库及过程资源残留 0，产品库/真实 Provider 调用为 0。
- 当前相关前端 81/81，项目包 unit/graph/identity 133/133。N 项目包加入显式字段审计、来源闭合验证与导入编码；真实 MySQL 导出/导入/删除闭环正在执行。
- 页面审查发现列表加载失败导致表单隐藏、归档后的不确定创建缺少退出路径，修复并补回归。代码稳定后执行完整 Phase matrix，随后 backup-first 产品库升级及 PC 真实验收；完整三章仍后置。

新增精确 focused/slice 命令：

```powershell
python -m pytest backend/tests/unit/test_continuity_issue_packages.py backend/tests/unit/test_project_package_repository.py backend/tests/unit/test_project_import_graph.py backend/tests/unit/test_project_import_identity.py -q --basetemp=.codex-test-artifacts/issues-package-unit
python -m pytest backend/tests/integration/test_continuity_issue_packages_mysql.py -q --basetemp=.codex-test-artifacts/issues-package-mysql
node --test frontend/tests/unit/continuityIssuesView.test.mjs frontend/tests/unit/finalizationPanel.test.mjs frontend/tests/unit/writerNavigationGuard.test.mjs frontend/tests/unit/chapterWriterView.test.mjs frontend/tests/unit/finalChapterReaderView.test.mjs frontend/tests/unit/finalReviewController.test.mjs frontend/tests/unit/finalReviewSummary.test.mjs
node frontend/e2e/run-phase5.mjs
```

### 2026-09-08 09:15 用户要求安全暂停

用户要求子代理与当前任务恢复常规推理，随后安全停止。三路子代理已以 medium 接续，现全部结束；主任务无可调用的自身推理档位配置工具，不能声明已切换。当前暂停决定覆盖此前连续推进授权。

- 最终正式 Phase5 切片1/1通过（output/phase5-final-slice.log），测试资源残留0；产品库与真实Provider调用0。8000/5173均无监听。
- 尚未修复：旧active列表响应覆盖保存拒绝后archived状态的竞争；四类合法revision0 heads导入兼容（新增32例为RED，12failed/20passed，其中4个fixture需核对）。导入heads实现尚未修改。
- provenance导出已改graph_records，相关110单测通过，完整MySQL包往返尚未复验。独立issues永久删除1项MySQL通过，测试库已清理。
- 产品库v114/99表保持原状；未迁移、未提交/推送。完整Phase、产品PC、真实三章均待恢复后执行。
- 用户明确恢复前，不启动新任务或服务。

### 暂停后恢复执行

用户明确“继续”，并要求当前任务及子代理均恢复常规中档状态。子代理沿 medium 接续，不请求最高推理或快速模式。先修归档响应竞争、空版本head包导入，再完成Phase与产品PC验收。

归档响应竞争已按先复现后修复完成：旧列表/详情不能覆盖后来确认的归档/删除状态，新读取仍能恢复合法active状态，29项前端测试通过；独立复核原创建拒绝时序通过。

本批精确命令：
```powershell
node --test frontend/tests/unit/continuityIssuesView.test.mjs
python -m pytest backend/tests/unit/test_project_import_empty_heads.py backend/tests/unit/test_project_import_graph.py backend/tests/unit/test_project_import_identity.py -q --basetemp=.codex-test-artifacts/issues-empty-head-unit
python -m pytest backend/tests/integration/test_continuity_issue_packages_mysql.py -q --basetemp=.codex-test-artifacts/issues-package-mysql
node frontend/e2e/run-phase5.mjs
```
代码稳定后执行既定Phase矩阵：npm test、npm run test:integration、npm run build、npm run test:browser:phase5，并核对owned资源残留。项目包UI受导入修复影响，追加既有正式Phase6C；历史入口追加Phase8A，之后产品库backup-first增量升级与PC真实路径。

恢复后切片补记：4类合法零版本head闭环113定向+3MySQL通过，3库全清；非成功确认历史provenance分支统一graph和编号，序列化真实ZIP预检新回归，98项通过。完整unit初轮6326passed/17skipped/2failed，根因新路由清单与只读MIN白名单；补齐后118项通过。重新执行完整Phase中。
补充精确命令：python -m pytest backend/tests/unit/test_router_domain_boundary.py backend/tests/unit/test_verify_manuscript_product_smoke.py -q --basetemp=.codex-test-artifacts/resumed-inventory-unit；python -m pytest backend/tests/unit/test_project_package_repository.py backend/tests/unit/test_project_import_package_reader.py -q --basetemp=.codex-test-artifacts/issues-provenance-final。
完整前端预检1198passed/10failed，主要为phase2旧清单、旧自动建Session预期、SSR stub导入精确文本及overview旧目的地。按当前已批准显式创建/统一工作台/独立小纲更新测试，保留隔离与只读请求断言。根脚本3处旧契约断言已对齐，19+15定向通过。概览与候选SSR两文件12项通过。
本批定向命令：node --test scripts/tests/phase3cSuite.test.mjs scripts/tests/phase4B3BrowserContract.test.mjs；node --test scripts/tests/phase8aBrowserContract.test.mjs；node --test frontend/tests/unit/projectPlanningView.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs；node --test frontend/tests/unit/phase2RuntimeInventory.test.mjs；node --test frontend/tests/unit/projectRouteSfcIntegration.test.mjs。

概览连续性已按既有接口契约接通同一只读快照的pending总数；157项overview定向通过，真实MySQL验证0→1→2→resolved后1→ignored后0→归档0（1库清理）。主页面标签改为连续性问题，不新增接口/schema。精确命令：python -m pytest backend/tests/unit/test_project_overview_repository.py backend/tests/unit/test_project_overview_service.py backend/tests/unit/test_project_overview_domain.py backend/tests/api/test_product_routes.py -q --basetemp=.codex-test-artifacts/overview-continuity-unit；python -m pytest backend/tests/integration/test_continuity_issue_packages_mysql.py::test_permanent_delete_cleans_manual_and_formal_source_issues -q --basetemp=.codex-test-artifacts/overview-continuity-mysql。
前端全量第二轮1207passed/1failed：异步旧章隔离测试使用20次setImmediate轮询，有时早于digest后的读请求开始；改为两个真实读取启动信号后reset，保持原晚到响应断言，finalizationController25项通过。源码脚本全量460/460通过；Phase矩阵第三轮执行中（output/continuity-workbench-phase-unit-green.log）。

完整Phase单元门禁已通过：npm test exit0，backend6346passed/17skipped、scripts460passed、frontend1208passed（output/continuity-workbench-phase-unit-green.log）。持久化完整门禁已启动：npm run test:integration，启用实际MySQL8.4客户端路径，产品库无写入。

2026-09-08 矩阵补记：完整 MySQL 首轮 426 passed / 6 failed（423库全清）。六处归档测试在确认契约后仍使用 lifecycle revision 0；仅修复该测试文件版本/精确断言，文件复验21 passed（20库全清），日志 output/archive-revision-regression.log。生产代码未变，复用其余通过证据，不将首轮命令记为exit0。最新构建通过（output/continuity-workbench-phase-build.log），正式Phase5再次1/1通过且资源残留0（output/continuity-workbench-phase5.log）。

正式Phase6C首轮停在fixture-CorpusImportFailed，已定位独立CLI没有安装runtime配置，子任务正在修复入口。Phase8A已修概览旧链接与小纲模糊定位；流程到达损坏稿件错误事件审计，正在复验异步console事件收齐；目前不能标记Phase6C/8A通过，产品库保持v114。

2026-09-08 产品实测：v115升级成功（100表），完整备份回执output/v115-upgrade-receipt.log；owned后端exec23139/PID2156、Vite exec77200，浏览器session continuity-sep8。正式6C最终1/1、owned资源0，修复导出页onBeforeMount生命周期并通过真实SFC回归4项及构建。

本次新建临时QA项目9ed9f7f2-7303-4b5e-a1f7-3fd2eec8f3f6（QA-CONTINUITY-PC-20260908），问题843ede07-027e-42d9-837c-f844c7ad98de：UI创建→刷新保留→概览pending1→已解决+说明→概览pending0→已忽略+说明→刷新保留均通过。尚待归档/永久删除及GET404清理，勿遗忘此精确ID。既有典镇山河当前/历史审查仅GET读取，两PC尺寸截图已保存。

产品归档实测新缺陷：1920×1080首卡更多菜单归档按钮被下一张article遮挡，elementFromPoint证实目标不可命中，没有归档HTTP或数据变更；截图output/playwright/archive-button-diagnostic.png。子任务修复ProjectCard菜单层叠，主任务后续同页实测；不绕过此UI缺陷完成归档。

2026-09-08 产品PC验收闭环：菜单层叠CSS修复后同一位置elementFromPoint从下一张ARTICLE变为目标BUTTON；UI归档成功，project.lifecycleRevision0→1，问题页无新增/处理写入控件，只读详情保留。UI永久删除QA项目9ed9f7f2-7303-4b5e-a1f7-3fd2eec8f3f6后GET404，关联问题843ede07-027e-42d9-837c-f844c7ad98de随项目清理。两个PC尺寸已查看截图（workbench-current-v115-*、final-review-v115-*、continuity-resolved-v115-*），工作台document/main无横向溢出：1440时main1177/scroll1177，1920时1657/1657。卡片/库21项通过，最新构建output/continuity-workbench-pc-final-build.log通过。

后续按既定顺序进入真实三章：保留QA项目a95c9cd9-c3f0-5e5d-81f3-bc0fb7127a6a，准备态八任务ready、contract/bible/planning/outline均current、authoritativeChapterNumber1、currentChapter0；本批只读核查，尚无真实Provider请求。先回看既有候选/失败审查，再决定保留候选重审，禁止把历史失败当通过或改写已确认基础。

2026-09-08 真实第一章重审：正式 UI 对保留候选 b157ec4d-366e-412f-915e-40aced2b9733（e0d1f3cd 是正文 hash 前缀）发起 prepare，attempt 444411f8-7413-4791-918a-c824cecb2e55 返回 failed、quality_not_completed、changeSet/confirmation null。尚未确认/定稿，无新正文生成，保留候选与历史失败。正在区分 manifest、transport、响应校验阶段，尚不能断言根因或真实上游调用是否到达。独立全文复核未发现本章直接阻断矛盾；第二章必须有无月雾夜条件及耳伤后续影响，不能将仅完成第一项任务的阶段/故事块整体判为完成。

真实审查安全诊断：离线 SELECT-only/READ ONLY 快照重建两类 manifest、messages 及当前配置 MockTransport 请求前置均成功，无外网调用。临时内容隔离 trace 后正式 UI 新 attempt 96f5258c-e0e3-454f-9d8f-8432bfc69402：两项均 HTTP200/transport succeeded，均在 _hydrate_evidence 的连续、唯一、按序 paragraphIds 校验（finalization_provider.py:82）拒绝；failed/quality_not_completed、changeSet/confirmation null。证据 output/finalization-safe-trace-20260908.jsonl 仅记录固定代码步骤、状态码及固定异常类别，不含正文、凭据或异常文本。该次结果明确新请求失败环节，但不能追认上一次同因。正在强化提示词区间示例，保留严格原文校验；没有确认、定稿或新增正文。

区间列表示例补强后 prompt/evidence/gateway 37 项通过。正式 UI attempt 09d631e3-2a28-4e02-91e8-6e9ccdfae58b：quality completed、findings 空、hardBlocks 空；extraction HTTP200/transport 成功但仍在连续列表校验拒绝，最终 failed/changeSet null。未盲目继续同样重试，改为 Provider 输入输出局部适配：以起止段落表达同一完整连续区间，服务端仍从未改动的候选截取原文并计算 hash，持久 evidence 契约不变；旧列表/精确引句兼容校验保持严格。另修重试期间旧failed提示，panel/controller红绿39项通过，实际busy展示待下一次请求核验。

Provider 区间适配完成：paragraphRange={start,end}，仅接受真实输入段落、正向或单段范围，完整原文切片含中间段落/Unicode/CRLF，旧列表及quote校验不变；prompt/gateway/evidence/domain/service 100项通过。重试提示的实际 UI 验证：点击正式按钮后150ms，inProgress=true、oldFailureVisible=false；前端构建 output/finalization-retry-pc-build.log 通过。当前新范围方案正式重审进行中，尚无确认/定稿。

起止段落真实 attempt 9e8c114c-b6e2-458f-92fc-de14b7362bdb：HTTP200，两类解析均成功；quality completed/10项findings/0hardBlocks；最终failed/changeSet null。随后的离线合成复现表明，demote_protected_planning_patches 对合法嵌套Canon value调用裸 model_dump(mode=json) 会触发 PydanticSerializationError，不依赖Provider或受保护patch。当前修复使用项目既有 change_set_payload（不可变JSON正常展开），不修改持久契约。既有trace未覆盖该异常类，因此不能单凭其日志断言真实attempt同因，需修复后正式验证。

嵌套JSON修复已完成（checks中调用change_set_payload），preflight/checks/service/parent_progress/domain94项通过，真实prepare型回归覆盖合法字符串数组patch与深嵌套Canon值。正式新attempt49fa3ffc-f7ff-45d8-adcc-80ae7d09f4c9两类解析成功，但validate_parent_progress明确拒绝父级completed而子任务未完成（安全trace checks:372→415→prepare:911）；quality completed，failed/changeSet null。保护符合第一章尚未登船的事实界限，不放宽。正在核查能否把当前小纲任务与剩余任务关系明确派生到提示词，禁止硬编码QA或自动丢弃错误进度。

progressScope派生提示补强52项通过。正式attempt f74b7744-91b8-4140-99db-80123d315b05 已awaiting_author，R1 hash dbce91803d35cf12ce2f425e35c2d33ba4e6f7dff060dceedbb0afa884f0c3c5；quality completed，两解析/业务校验通过。独立审阅：ear_injury.value.severity=轻度无原文支持；payWages缺交易结果；缺烧鞋事实和章末耳鸣/持牌状态。当前面板仅能排除事实，不能正确局部修正或补录，按前端直接修复授权新增这两项作者审查操作，仍走既有correct/CAS/证据校验。尚未修改QA R1。临时内容隔离trace服务已结束，启动器tmp/finalization_safe_trace_20260908.py精确删除，安全步骤日志保留；普通uvicorn恢复exec28073/PID56296，Vite继续77200。

用户最新指示：当前任务完成后先安全停止。已将范围限定为本次审查事实值修正/补录、必要测试和真实UI保存修正验证；审查保持未确认，不接续定稿或第二/三章。两开发子任务收尾后结束，主任务记录保存的review revision并停止自有服务。此停止要求覆盖此前自动连续推进授权，恢复需用户明确要求。

### 2026-09-08 当前事实修正任务完成后安全停止

事实递归值编辑、alias删除、原文段落补录已集成。指定五组前端63/63通过（output/continuity-fact-editor-tests.log），构建通过（output/continuity-fact-editor-build.log），diff check通过。正式UI删除ear severity、修正condition、工资事件补result、移除alias哥哥；从p25补烧鞋，从p54分别补持牌和耳鸣持续。点击保存修正成功后重新进入页面：R2、11条Canon（新增3）、1条当前scene_task进度，所有11条证据hash与原候选一致，补录范围1480–1596及3153–3258。回执output/fact-correction-r2-receipt.json；attempt f74b7744-91b8-4140-99db-80123d315b05，R2 hash 67ac535c35aa03bb4a6ca4ee67f41f12647a283063ea34add3a6d04b4a032556。仍awaiting_author/confirmation=null，currentChapter0，workingDraft revision3/candidates2。

1440×900及1920×1080实际截图已查看（output/playwright/fact-correction-r2-1440.png、fact-correction-r2-1920.png），document宽度分别1440/1920，无横向溢出；刷新后无保存修正按钮（无脏稿），3条补录显示。browser console命令0 errors/0 warnings；停止时Vite终端另见此前与12:09:44的ResizeObserver loop通知，未据此宣称所有pageerror为0，此开发态现象留作恢复后的核查项，不扩大本次停止前范围。

所有三个子任务已结束，浏览器continuity-sep8关闭，自有后端exec28073及Vite77200均结束；核实8000/5173无监听。临时trace启动器已删除，安全步骤日志、私密完整DB备份和本次验收回执保留。没有确认/定稿、生成新正文、提交或推送。下一轮须用户明确恢复，再从已保存R2核查并接续；不重复Provider重审或覆盖本次作者修正。


### 2026-09-12 三章作者闭环与默认生成验收

按用户恢复与连续推进授权，已完成第一、二、三章真实生成/作者审查/定稿；currentChapter=3，Canon R3。第三章遵循用户新要求，将作者临时要求留空，先记录默认输出失败，再修复自动小纲执行边界和字数读取；最终以未人工改写的3286字符原稿完成定稿。人物弧光实际变化、原文依据、三章历史正文与审查回读已验证，PC两尺寸截图已查看。第一、二章有临时要求和人工修文，不能称为连续三章全留空质量验收。

正文TXT和完整ZIP已从正式前端下载，实际包预检200。正在收尾真实备份恢复：多次审查的精确quality关联、失败attempt历史恢复及隔离MySQL发布验证。不要把ZIP预检通过当成已完成导入；当前详细证据见2026-09-12-author-flow-resume.md。本次未提交/推送，不改模型配置。


三章恢复收尾完成：新包正式API预检200、前端下载hash一致、实际包隔离MySQL发布成功；12次审查的状态及精确quality关联、3章正文hash全部保留，两个恢复测试库清理为0残留。原“正在恢复验收”为历史进度。后续质量验证须继续使用临时要求留空的真实用户路径；不要将第1/2章的补充要求结果泛化为默认质量通过。
