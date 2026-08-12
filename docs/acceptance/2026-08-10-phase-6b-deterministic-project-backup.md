# Phase 6B Deterministic Project Backup Acceptance

## 结论与范围

Phase 6B 已在随机 Disposable MySQL、真实 FastAPI/Vue 链和可见浏览器操作边界下验收。
活动项目与归档项目均可从项目概览下载确定性、无密钥的 ZIP 项目备份包；活动项目会先完成
现有保存边界，归档项目使用已冻结的生命周期修订。

本阶段只接受 deterministic secret-free project backup with disposable local data。项目导入、完整
Phase 6、真实 Provider 质量和产品数据库 readiness 均未验收。

## 闭合的不变量

- 包格式为 `novel-creator-project` version `1`，hash algorithm 为 `sha256`。结构化数据使用
  canonical UTF-8 JSON/JSONL 和单末尾 LF；ZIP 条目按 ASCII 路径排序，`ZIP_STORED`，固定
  `1980-01-01T00:00:00`、Unix regular-file `0600`、无 comment/extra/data descriptor。
- `manifest.json` 只列 payload entries；`manifest.sha256` 是 exact canonical manifest bytes 的
  SHA-256，避免自引用。条目数、单项、总未压缩字节、ZIP 字节、路径和 JSON 深度均有固定上限。
- Repository 在一个 MySQL repeatable-read read-only consistent snapshot 中显式读取完整项目拥有
  图；60 个项目表有静态 ownership/query/column/export decision，不使用 `SELECT *`。
- Planning、Bible、Outline、CreationContract、Finalization ChangeSet、QualityFinding、receipt、
  Canon 和语料选择全部经严格领域模型解析，并把数据库或局部标识改写为 package-local logical
  IDs。悬空、类型错配、hash/revision 漂移、未知或额外字段统一 fail closed。
- Provider 配置、密钥、Base URL、活动 lease/token、prompt、Provider 原文和投影 authority 不入包。
  Provider history 只保留不可执行的名称/model/task/binding/hash 证据；导入后匹配不属于本阶段。
- 冻结资产只打包项目确切引用的 revision；冻结语料包含 exact revision、chapters/fragments 和
  content-addressed blob。blob 路径、长度与 SHA-256 重新核验，选择子区间必须落在权威片段内。
- 私密 Provider 值只在内存中做 exact raw/JSON-escaped 扫描，并在 `finally` 清零；普通小说词汇
  不做启发式误杀。所有公开错误均固定、脱敏且不回显内部 ID、正文、路径或 Provider 数据。
- 临时目录与 ZIP 在 POSIX 验证 `0700/0600`；Windows 使用当前进程 SID 的 protected DACL 和
  exact single full-control ACE 后验验证。成功、异常、取消、断流和 background cleanup 共享可重试
  的幂等清理所有权。
- 前端只新增一次 POST binary download；active flush 失败时零请求，archived 跳过 flush，single-
  flight、四个固定 blocking 阶段、dispose/abort generation fence、URL revoke 和安全 ZIP 文件名闭合。
- 自动验收不调用真实 Provider、不读取产品数据库、不新增 schema/migration/job/workflow，不记录
  正文 body、DSN、密钥、Provider 原文或本机语料绝对路径。

## Fresh focused evidence

- 组合 Python focused：domain/security/repository/service/API/route inventory/lifespan 共 `201 passed`，
  exit `0`。
- 规格审查回流修复后的 package focused：`134 passed`；repository focused：`51 passed`；主控独立
  package 复验 `134 passed`，均 exit `0`。
- `python -m pytest -q backend/tests/integration/test_project_package_snapshot_mysql.py`：`2 passed`；
  disposable database `created=2 cleaned=2 remaining=0`，exit `0`。
- 前端 API/controller/panel/overview、既有 download regression 与 runner contract：`61/61 passed`，
  exit `0`。
- `npm run test:browser:phase6b`：visible UI scenario `1/1 passed`。活动与归档两份真实 ZIP 均通过
  entry order/set、固定 metadata、manifest/hash/payload digest、lifecycle revision、final/draft/assets/
  corpus/terminal operation/provider/projection 与 secret exclusion 验证；held response consumer close 的
  cleanup audit 通过。
- Browser runner 报告 disposable DB、API/Vite/deny-proxy process、owned ports、temp、corpus、
  downloads、artifacts、Vite `deps_temp` residue 均为 `0`；outbound/Provider calls `0`，product DB
  reads/writes `0/0`。
- `npm --prefix frontend run build`：Vite build passed，`2975 modules transformed`；相关 `py_compile`、
  `git diff --check` 和 repository `SELECT *` scan 均 exit `0`。

## 首因历史

- Runner contract 首次 RED：Phase 6B scripts/config/spec 尚不存在；最小 wiring 后 `2/2`。
- 复用 fixture 首先暴露语料 hash 在确认后被修改、Bible payload 仍是旧占位形状；改为在真实确认链
  前建立 canonical authority，没有绕过产品校验。
- 真实快照依次暴露并修复：Canon finalization source 错指向 record 而非 change set；CreationContract
  内部引用未改写；合法语料选择窗口被错误要求与整片段完全相等；finalization receipt 的章节和规划
  ID 未改写；冻结 projection 的嵌套只读映射未深度解冻。
- 首次规格审查发现非空 FinalizationChangeSet 与 QualityFinding 仍按 generic JSON 导出；修复为严格
  typed rewrite，并覆盖 local IDs、Canon/Planning cross-refs 与 dangling/type/extra fail-closed。
- 浏览器 held-response 首次残留来自 runner 的通用 HTTP middleware 把生产流拆到独立任务；移除该
  测试中间件，改为 runner-only 流延迟包装并在 `finally` 传播同一幂等 cleanup。
- ZIP verifier 首次要求 terminal operation 非空，但旧 fixture 没有该历史；改用真实 operation
  reserve→cancel 路径并用 ProviderMustNotRun 证明 Provider 调用为零且正文不变。

以上失败均先定位单一首因后受控复跑；没有放宽 raw-ID、secret、完整性或 UI 门禁，也没有读取产品库。

## Review 与延期项

- 最终 specification review：新发现 `Critical/Important/Minor = 0/0/0`，批准。
- 最终 quality review：新发现 `Critical/Important/Minor = 0/0/0`，批准。
- 已知非阻断延期项：repository rollback/release 双故障、service cleanup 双故障、startup stale-cleanup
  warning 可观测性；前端合法大包仍沿用 30 秒 binary timeout，anchor `click()` 抛错时 remove 不在
  `finally`。这些均不属于当前活跃路径的数据损坏、安全或必现失败，按停止规则留待 Phase 7 hardening。

## 资源与控制面账本

- 最终独立审计：owned Python/Node/browser process `0`、Phase6B temp candidate `0`、Vite
  `deps_temp` `0`；最终 MySQL focused ledger `created=2 cleaned=2 remaining=0`。
- Browser 成功账本中的 DB/process/ports/temp/corpus/download/artifact/Vite residue 全为 `0`，
  outbound/Provider `0`，产品数据库访问 `0/0`。
- 本阶段未新增 schema、migration、backup ledger、job/workflow 或取消协议；未 push。
- 禁止 checkout 中既有的两条误写 RED 测试不属于本分支；本阶段未读取、测试或清理该 checkout。

## 后续边界

下一切片是 Phase 6C：严格预检与原子导入为一个全新的项目。Phase 6C 负责 package ZIP 防御性解析、
兼容性和完整性预检、Provider Not Ready、导入 command/staging ledger、单事务落库与失败零残留；不会
恢复或自动匹配 Provider，也不会读取产品数据库或调用真实 Provider。
