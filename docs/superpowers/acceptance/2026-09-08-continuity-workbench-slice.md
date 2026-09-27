# 连续性与工作台验收进度

2026-09-08（Asia/Shanghai）。用户在安全暂停后已要求继续，当前采用常规中档协作。仅验收 PC 1440×900 / 1920×1080。本文记录已有证据，不代表完整三章真实创作已通过。

## 本轮已实现

- 连续性问题独立管理类别、严重度、待处理/已解决/已忽略、处理说明和定稿来源；不改写 Canon、Projection、Planning 或历史正文。
- 创建结果未知时保留同一请求编号和原内容；处理冲突保留作者说明；归档仅可读，旧 active 响应不会覆盖后来确认的归档/删除状态。
- 概览按同一只读快照统计当前项目待处理问题总数，失败不冒充零；创建及处理后重新读取可反映变化。
- 工作台支持事实/进度排除、修正未保存时的离开保护、定稿后历史审查；当前导航与候选采用最新已确认小纲，历史章保留定稿依据。
- 问题记录纳入项目包字段审计、来源闭合验证、ID 重映射及永久删除。修复四类合法 revision 0 空指针的导入兼容，以及失败确认历史的 provenance 分类/编号冲突。

## 已验证

| 证据 | 结果 | 边界 |
| --- | --- | --- |
| 完整 `npm test` | 后端 6346 passed / 17 skipped；脚本 460 passed；前端 1208 passed；exit 0 | `output/continuity-workbench-phase-unit-green.log`，作为完整单元基线；后续导出挂载与菜单层叠修复另有定向及实际浏览器证据 |
| 扩展 Phase5 正式浏览器 | 1/1 passed | `output/continuity-workbench-phase5.log`；最新代码重跑，覆盖排除、未保存保护、确认/撤销/定稿、历史审查、问题创建/处理/刷新/筛选/来源回链 |
| Phase5 资源 | DB/process/port/temp/artifact/Vite residue=0 | 假质量/提取 Provider；真实 Provider 0，产品库读写 0/0 |
| 问题项目包真实 MySQL | 3 passed；created=3 / cleaned=3 / remaining=0 | 六种有源/无源状态、导出→导入→再导出、来源重映射、空白旧包兼容、精确永久删除 |
| 概览计数真实 MySQL | 1 passed；created=1 / cleaned=1 / remaining=0 | 真实 OverviewService 验证 0→1→2→resolved 后 1→ignored 后 0→归档后 0 |
| 迁移切片 | 143 单测；34 单测/MySQL（8 库全清）；9 项链式升级/bootstrap/readiness | 前迁移代理本轮已运行并交接；这些是隔离库证据，不是产品迁移完成 |
| 最新生产构建 | 通过 | `output/continuity-workbench-phase-build.log`；包含概览标签改动 |
| Phase8A 正式浏览器 | 1/1 passed，1440×900 | `output/continuity-workbench-phase8a-events.log`；阅读/小纲/前后章/刷新/下载/归档/损坏稿件保护，已知关联错误4、意外console及pageerror及requestfailure均0，所有owned资源0；脚本契约15项通过 |
| 完整 MySQL 首轮及失败修复复验 | 首轮 426 passed / 6 failed；归档文件修复后 21 passed | `output/continuity-workbench-phase-integration.log` 与 `output/archive-revision-regression.log`；423+20 库全部清理。仅修正测试中的旧生命周期版本，保留锁/租约/回滚/基线断言，复用其余通过结果；首轮命令仍为 exit 1 |

定向红绿修复过程和精确命令见[收口计划](../plans/2026-09-05-author-flow-closure.md)。早期失败均保留记录：旧清单/标签/自动建会话预期、SSR stub导入匹配、固定轮询异步测试已修复；没有删除隔离、只读请求或正文秘密保护断言。

## 正在执行与剩余

1. MySQL 首轮六个失败已由修复后的归档文件复验覆盖。生产代码未变化，不重复扩大回归，分别保留首轮失败与定向通过证据。
2. 最新构建、Phase5、Phase8A通过。Phase6C修复CLI runtime/旧夹具版本及当前导出入口后，定位并修复导出页初次挂载竞争（onBeforeMount先刷新项目，再挂面板；真实SFC红绿4项）。正式Phase6C最终1/1通过，所有owned资源0，产品库/Provider调用0（`output/continuity-workbench-phase6c-export-ready.log`）；最新构建`output/continuity-workbench-export-build.log`通过。
3. 产品库 `novel_creator_v113` 已按backup-first流程由v1.14/99表升级到v1.15/100表，仅新增单表。升级前重新核实1020行/79非空表、无其他产品连接；2,258,026字节完整私密SQL备份及hash核验成功后执行DDL。回执`output/v115-upgrade-receipt.log`，备份目录`D:/NovelCreatorBackups/continuity-issues-v115-20260908`。后端与前端启动，`/api/health`返回ok。
4. 升级后两个 PC 尺寸实际验证当前工作台及历史审查；临时项目通过问题创建/刷新、概览 1→0、处理说明、已忽略刷新、归档只读。发现并修复项目卡片更多菜单被相邻卡片遮挡，21 项定向及实际命中/归档验证通过。项目 9ed9f7f2-7303-4b5e-a1f7-3fd2eec8f3f6 已从 UI 永久删除并核实 GET 404；最新构建 output/continuity-workbench-pc-final-build.log 通过。
5. 已进入保留 QA 项目的真实三章验收。连续诊断修复了模型段落列表漏项（Provider 改用起止段落，原文区间/hash 不变，100 项回归）和合法嵌套 JSON 的规划建议转换异常（改用既有 change_set_payload，94 项回归）。最新 attempt 49fa3ffc-f7ff-45d8-adcc-80ae7d09f4c9 两类解析成功，但父级进度完成条件校验拒绝；failed/changeSet null，未确认/定稿。当前正补模型对本章任务与父级剩余任务的明确上下文，不放宽守卫。重试旧错误提示修复39项与真实busy展示、最新构建通过。各次失败详见收口计划和安全步骤日志。现有 QA 项目及历史均保留，不能把这些修复当作三章通过。

没有提交、推送或改动持久模型配置；无周额度停止条件。当前与历史结果均以[项目状态](../../../CURRENT_PROJECT_STATE.md)、对应原始日志及后续实际核查为准。

## 最新暂停现场

按用户要求，本次事实修正与补录功能已收尾后安全停止。前端63/63、构建通过，正式UI保存作者修正R2并刷新核验；11条事实的原文区间/hash全部一致，两个PC尺寸无横向溢出。attempt f74b7744-91b8-4140-99db-80123d315b05，R2 hash 67ac535c35aa03bb4a6ca4ee67f41f12647a283063ea34add3a6d04b4a032556，仍awaiting_author且confirmation=null/currentChapter0。回执output/fact-correction-r2-receipt.json，完整过程见收口计划。

三个子任务结束，浏览器与自有前后端已关闭，8000/5173无监听。开发终端曾出现ResizeObserver loop通知，暂记后续核查，不以console零错误替代pageerror完整验收。未确认/定稿，三章仍未完成；等待用户明确恢复。
