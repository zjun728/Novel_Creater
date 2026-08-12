# Phase 6C Atomic Project Import Acceptance

## 结论与范围

Phase 6C 已在随机 Disposable MySQL、真实 FastAPI/Vue 链和可见浏览器操作边界下验收。
一个 Phase 6B `novel-creator-project` v1 包会先经过 raw ZIP、canonical manifest、typed graph、
identity/hash rewrite 和完整引用预检，再以一个最终 MySQL 事务发布为新的 active 项目。Provider
绑定统一恢复为 Not Ready；unknown-result 使用同一 command 通过 GET 恢复，不会重复发布项目。

本阶段只接受 strict atomic project import with disposable local data。真实 Provider 质量、产品数据库
readiness、live-site readiness 和小说内容质量均未验收。

## 接受的不变量

- 包格式固定为 `novel-creator-project` version `1`、hash algorithm `sha256`。reader 先验证 raw ZIP
  header/entry/size/path，再验证 canonical manifest、entry digest、JSON/JSONL、typed records、logical
  identity、revision/hash pins 与递归敏感字段；未知、额外、悬空或类型错配一律 fail closed。
- 所有目标标识由 command-scoped UUIDv5 确定性生成。仅显式 typed slots 可重写；小说正文、候选正文、
  corpus bytes 和任意普通字符串不会做全局替换。DraftCandidate 保留历史 WorkingDraft revision 与完整
  Outline/Planning/Canon/Projection basis provenance，并按目标 authority 重算 production basis hash。
- Provider 配置、profile、model snapshot 和可执行绑定不恢复。八个 binding task 均完整但 unbound，
  新项目在 UI 和 preparation boundary 明确显示 Provider Not Ready。
- publication plan 只含静态登记的真实表、列和 FK 顺序。最终 publication 在 caller-owned 单事务内锁定
  command，复验 target/fingerprint/package/manifest/title/idMap/owner/lease，确认目标不存在，写入完整
  authority/provenance，基于目标 Canon 重建并比较 Projection，最后 fenced 标记成功。任一步失败都会
  回滚，因此不存在部分可见项目。
- corpus blob 先进入 command-owned staging；promotion 使用 per-digest exclusive claim 与同卷
  no-overwrite link。已有 blob 必须满足 hash/length/storage-key 三元组；普通失败清理只认本命令实际
  安装的 runtime ownership，crash recovery 还要求 DB manifest 与磁盘 canonical manifest 完全一致。
- startup recovery 由数据库选择最多 32 个 terminal/expired commands，再逐个 row-lock/CAS fence；只处理
  exact command root、exact owner claim 和 DB 未引用的 command-created blob。取消、断流和清理异常不会
  覆盖原始错误。
- API 只开放三条 project-import routes。multipart 直接从 request stream 解析，并同步限制 aggregate、
  file、field、header 与 exact part ledger；所有异常出口关闭 request-owned handle/root，disconnect 与
  `CancelledError` 保持主因。
- 前端在同一 File、command id、idempotency key、fingerprint 和 title 上完成 preflight/import/recovery。
  unknown 只轮询 GET；retry-required 才复用同一身份重投；成功先解除 blocking operation 再导航，导航
  失败保留恢复身份。
- 浏览器验收只使用可见 UI：真实备份下载、Library 文件选择、预检、改名、单次导入、断开首次成功响应、
  GET 恢复、打开新项目、验证 Provider Not Ready、下载定稿 TXT。没有 `page.request`、`page.route`、
  `fetch`、`axios` 或 `page.evaluate` 绕行。

## Fresh focused evidence

- Tasks 1–9 Python domain/security/schema/repository/service/lifespan/API focused：`356 passed`，exit `0`。
- Task 8 frontend focused：`45/45 passed`；Task 9 runner contracts：`16/16 passed`，exit `0`。
- Disposable MySQL publication/recovery focused：`15/15 passed`，数据库
  `created=15 cleaned=15 remaining=0`，exit `0`。
- Tasks 1–9 的 `py_compile`、frontend build（`2978 modules transformed`）和 `git diff --check` 均
  exit `0`；focused owned temp、process、ports 和文件资源均为 `0`。

## Full Phase 6 matrix

- `npm test`：exit `0`。Python unit/API 为 `3842 passed, 6 skipped`；script/runner Node 为
  `389/389 passed`；frontend Node 为 `769/769 passed`。
- `npm run test:integration` 首轮完整结果为 `391 passed, 2 failed`；两处同一首因是 schema bootstrap
  的严格 `EXPECTED_TABLES` 仍漏掉 Phase 6C 两张正式表。保持严格集合相等，仅补齐这两项后，定向
  `2/2 passed`；fresh full integration 为 `393/393 passed`、exit `0`，数据库
  `created=391 cleaned=391 remaining=0`。
- `npm run build`：exit `0`，Vite `2978 modules transformed`。plugin timing 仅为性能提示，无编译警告
  或错误。
- `npm run test:browser:phase6c`：exit `0`，visible UI scenario `1/1 passed`；注入边界为
  `owned-import-response-close-after-publication`，GET recovery 返回同一目标项目。

## 版本与完整性证据

- Writer Core schema version：`writer-core-v1.13.0`。
- Schema manifest SHA-256：`89b21cba12141afa1a2076cb70c559cd2bd13d71eb904c37c6ce5becc24fd857`。
- Schema 表闭集：`91`，其中 Phase 6C 只新增 `project_package_import_commands` 与
  `project_import_provenance`。
- Package format/version/hash：`novel-creator-project / 1 / sha256`。
- 浏览器链验证 source project 不变、target project 仅一个、import terminal success、Provider Not Ready、
  finalized TXT bytes 可下载；Provider 调用为 `0`。

## 首因历史

- 初始 runner contract RED 为 Phase 6C script/config/spec 缺失；最小 wiring 后闭合。
- 真实 Phase 6B 包依次暴露旧 importer 与当前 exporter 的 closed-shape 差异：Bible/Planning/
  Finalization embedded identity、confirmation pins、Canon revision 从 0 开始、frozen asset refs、corpus
  source identity/selection window、CreationContract manifest role、finalization inert extraction id 与
  chapter fencing token。每项均以 typed、有限注册表和 fail-closed 负例修复，没有通用字符串重写。
- 首次 visible flow 的下载按钮不可用，最终定位为 imported CreationContract corpus source identity 与
  relational source id 不一致；修复后 preparation、options 与 TXT download 均通过。
- Runtime observer 曾把配置中的 timeout 字段误判为测试 timeout，并混合预期 Chromium network/CORS
  console；最终改为 exact origin/method/path/query、exact one request failure、bounded adjacent console
  分类，其他 console/page/request/non-2xx/origin/pending/listener evidence 仍 fail closed。
- Task 9 最终审查发现 DraftCandidate 被重建为当前 WorkingDraft 且丢失完整 basis provenance；闭集补齐
  历史 revision/full provenance，按目标 authority 重算 hash，生产 `basis_status` 验证为 current。
- Task 10 integration 前两次只因外层 120 秒、900 秒执行时限终止且无 assertion summary；逐文件采样
  证明 393 个真实 MySQL tests 自然超过该时限。长时完整运行随后给出唯一产品外首因：schema bootstrap
  预期表清单陈旧。补齐后完整矩阵全绿。

## Review 与延期项

- 最终 specification review：`Critical/Important/Minor = 0/0/0`，批准。
- 最终 quality review：阻断项 `Critical/Important = 0/0`；累计 `Minor = 1`，按停止规则不阻断验收。
- 延期 Minor：不同 command 并发导入同一 digest 时，claim 等待只做 64 次 event-loop yield；当持有者
  正等待 manifest DB 事务时，等待者可能不必要地以 conflict 结束。该问题只影响极端并发可用性，
  不损坏数据、原子性、幂等、安全、secret 或 cleanup ownership，留待 Phase 7 使用实际 deadline/
  backoff 和 delayed-persist concurrency test 加固。

## 资源与控制面账本

- 最终 browser ledger：DB/process/ports/quarantine/project-import-staging/temp/download/artifact/Vite
  residue 全为 `0`；outbound/Provider calls `0`；product DB reads/writes `0/0`。
- Fresh full integration ledger：Disposable MySQL `created=391 cleaned=391 remaining=0`。
- 最终独立审计：task-owned Python/Node/Vite/Playwright process、listen ports、pytest temp、quarantine、
  staging、download、artifact 与测试数据库均为 `0`。系统已有 MySQL/Chrome 进程不属于本任务，未操作。
- 测试未调用真实 Provider、产品数据库或 live website；未记录正文 body、secret、DSN、SQL、Provider
  output 或本机绝对路径；本阶段未 push。

## 接受边界

> Phase 6 finalized download, deterministic secret-free backup, and strict atomic import are accepted with disposable local data. Real-provider quality, product-database readiness, live-site readiness, and novel content quality remain unaccepted.
