# Phase 7A Reliability Hardening Acceptance

## 结论与接受边界

Phase 7A 已关闭 Phase 6 明确延期的九项可靠性问题：导入 digest claim 的有界等待与所有权、
repository rollback/release 错误优先级、package service 清理重试与安全告警、下载 controller 的
状态恢复与主错误保留、备份专用 20 分钟超时、DOM anchor 清理，以及 Phase 6A 的 context-wide
观测、公开 fixture 边界和 runner 清理审计。

这九项可靠性修复本身不改变 public route、DTO、schema、UI state、Provider 行为或既有错误码。
同一分支还记录两个分别批准的窄边界：

- Finalization empty-state companion 仅将“session 存在但没有 attempt”从 HTTP `404` 改为闭合的
  HTTP `200` `{ "state": "empty" }`；session/authority 真正缺失仍为 `404`。
- Phase 6 direct-first-cause closure 将 backup ZIP 里既有 corpus
  `indexPayload.fragmentId/chapterId` 的值从物理数据库 UUID 改为 portable logical identity，导入时再
  映射为目标 UUID。这会改变确定性 archive bytes，但不新增 route、DTO key、schema、UI state 或
  Provider 行为。Phase 6A/6B/6C public fixture 对齐与 Phase 2C dispatcher 隔离只改变测试边界。

## 接受的不变量

- 同 digest 协调使用 monotonic 30 秒 deadline、10ms 起始且 250ms 封顶的指数退避；
  `CancelledError` 原样传播。project import publication/补偿清理、普通 corpus import publication、
  startup recovery 与 CorpusLibrary permanent delete 使用同一内部 claim namespace。每次 acquisition
  带唯一 incarnation token，旧的同-command owner 不能释放 retry 的 claim。
- claim 通过私有完整文件加原子 no-overwrite link 发布，并覆盖文件决策及对应数据库 transaction。
  project-import 补偿清理还必须持有 exact fingerprint/owner/live-lease row fence；失权旧 runner 只能
  释放自己的 exact claim，必须保留 root/manifest。corpus import 与 permanent delete 持有 claim 到
  transaction commit/rollback。
- startup recovery 遇 live foreign owner 或 claim-release 失败时继续当前 manifest；其他 manifest/DB/
  file-operation 失败把余项延期到后续 pass。所有延期都保留完整 command root/manifest。
  project-import compensating multi-blob cleanup 尝试所有 blob/claim；已有 operation primary 不被后续
  ordinary 或 flow-control cleanup error 覆盖，无 operation primary 时 flow-control 优先。
- claim 临时别名和 held claims 均执行有界两次清理；瞬时失败可恢复。共享 helper 的永久普通失败是
  固定持久化错误，CorpusImport 与 CorpusLibrary 分别映射为既有 `CorpusImportFailed` 与
  `CorpusLifecycleConflict`；已有主失败或 flow-control exception 保持主因，成功路径不静默吞清理失败。
- package repository 的 rollback/release 普通失败只产生固定安全错误；flow-control
  `BaseException` 原样传播；安全 warning 本身失败不会覆盖原始结果。
- package service 的失败清理和 stale scan 使用本地有界重试与固定类别，不输出路径、正文、SQL、
  DSN、secret 或 Provider 数据。
- novel download 与 project backup 在 API/save 主失败和 revoke/finish 次失败并存时保留主失败；
  blocking/busy 状态最终释放并可重试。备份调用单独使用 `1_200_000ms`，不改变 JSON、import 或其他
  binary 请求的 timeout。临时 anchor 始终在 `finally` 中移除，object URL 仍由 controller 唯一 revoke。
- Phase 6A fixture 仅编排公开 service/repository/domain DTO；不导入 test helper 或 router 私有对象，
  不调用 Provider。runtime observer 在 BrowserContext 层覆盖初始页面与 popup 的 request/response，
  固定整数计数 fail closed，并按 listener identity 验证自身监听器全部移除。
- Phase 6A runner 对 port release、root audit、root removal 分别做有界两次尝试，最终摘要仅包含固定
  类别与整数；所有 DB、process、port、temp、download、artifact 和 Vite ownership 都进入 finally。

## Fresh focused evidence

- 最终树 Python focused：`248 passed`，exit `0`。
- 最终树 Node controller/API/panel/runner/observer focused：`50/50 passed`，exit `0`。
- 最终树五个 Python owner modules `py_compile`：exit `0`；`git diff --check`：exit `0`。
- 四方 claim 协议收口的 unit：`108 passed, 1 skipped`；最终跨 worker MySQL recovery/corpus guard：
  `2/2 passed`，Disposable MySQL `created=2 cleaned=2 remaining=0`。

## Full regression and browser evidence

- 最终树 `npm test`：exit `0`；Python unit/API 为 `3937 passed, 6 skipped`，Node 为
  `783/783 passed`。
- 最终树完整 `npm run test:integration`：exit `0`，`393/393 passed`，Disposable MySQL
  `created=391 cleaned=391 remaining=0`，耗时 `30:32`。
- 最终树 frontend build：exit `0`，Vite `2978 modules transformed`。
- 最终树 Phase 6A/6B/6C browser gates：均 exit `0`、visible scenario `1/1`。
- 三个 browser ledger 的 owned DB/process/ports/temp/quarantine/staging/download/artifact/Vite residue
  均为 `0`；Provider/outbound 为 `0/0`；product DB reads/writes 为 `0/0`。

## Review 结论

- 最终 specification review：Active `Critical/Important/Minor = 0/0/0`。
- 最终 quality review：Active `Critical/Important = 0/0`。
- 所有 review 发现均按最小 TDD 或窄文档修订闭合；没有通过放宽 observer、错误映射、schema 断言或
  清理审计获得假绿。

## 已知延期 Minor

- Phase 6B 大 blob browser fixture 通过导入 authority 生成 8MiB payload，但其 index/blob 内容一致性仍是
  fixture 质量限制；产品 writer/reader/hash 检查未放宽。留待后续 fixture 精化，不阻断 Phase 7A。
- Phase 6A scenario 失败分支不会执行 spec 末尾的 `runtime.finish()`，因此失败路径的 listener residue
  主要依赖 runner finally 与 observer unit contract，而不是同一次 browser failure 的终态 evidence。
  留待后续 harness 精化，不改变产品或本次成功 gate。

## 后续边界

Product-database readiness 仍属 Phase 7B；真实 Provider 的质量、预算、隐私与内容评价仍属 Phase 7C；
deployment、live-site security operations 与 monitoring 仍属 Phase 7D。本阶段没有调用真实 Provider、
产品数据库或 live site，也未 merge 或 push。
