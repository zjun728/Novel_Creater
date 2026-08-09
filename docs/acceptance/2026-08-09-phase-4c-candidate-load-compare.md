# Phase 4C Candidate Load / Read-only Compare Acceptance

## 结论与范围

Phase4C immutable Candidate load and two-candidate read-only comparison are accepted
without a Provider process.

本验收只覆盖：把一份不可变 Candidate 在 CAS 与短事务保护下载入当前 WorkingDraft，以及在
Writer 右侧卡片中最多选择两份 Candidate 并排只读查看。没有实现 Candidate fusion、全文 AI
改写、通用 recovery 浏览器、Canon 写入、定稿或第二个正文编辑器。

Candidate fusion, full-draft rewrite, general recovery browsing, Canon/finalization,
real-provider quality, and product-database readiness remain unaccepted.

## 已验收的不变量

- 载入路由只接受 project/session/Candidate 身份和当前 WorkingDraft revision/hash；跨 owner、
  过期 CAS、非 drafting/superseded Session、活跃 DraftOperation 与损坏正文/hash 均在写入前失败。
- 成功载入只在一个短事务中追加 before recovery、更新 WorkingDraft revision `+1`、追加 after
  recovery；任一步失败全部回滚，源 Candidate 不更新、不删除。
- recovery 的 `candidate_load` 只引用 `source_candidate_id`；既有 Provider 操作原因仍只引用
  `source_operation_id`。Schema 为 create-only `writer-core-v1.11.0`，没有 runtime migration。
- 客户端先 flush 可见编辑，再冻结 Candidate 与 WorkingDraft authority；只有完整校准且内容、
  hash、身份、revision 全部一致的 server workspace 才能替换当前状态，迟到响应不能写回。
- Candidate load 不进入一步局部 AI undo，并会清除该临时 undo 能力。
- UI 只增加紧凑 Candidate 卡片、公开派生元数据、最多两个原生选择框和两个 `<pre>` 只读窗；
  没有融合按钮、modal、diff 算法、持久化选择或第三列正文编辑器。
- 自动证据没有 Provider 进程/调用、live 网站或产品数据库；日志和 artifact 不含密钥、DSN、
  Candidate/WorkingDraft body 或原始异常。

## Fresh slice evidence

- affected Python/API/schema：`230 passed`；相关 Python 编译与语法检查 exit `0`。
- affected frontend/root Node：`118/118 passed`。
- production frontend build：exit `0`，Vite `2966 modules transformed`。
- affected disposable-MySQL integrity：`1 passed`；`created=1 cleaned=1 remaining=0`。
- UI-only browser：保存两份 Candidate、选择两份只读比较、载入第一份，`1/1 passed`；runner
  报告 DB/process/port/temp/artifact/Vite residue `0`。
- 独立最终资源账本：owned process `0`、owned listener `0`、Phase4C temp root `0`、pytest
  temp `0`、Vite `deps_temp` `0`、`novel_creator_test_*` database `0`。
- Real Provider calls `0`；Product DB reads/writes `0/0`；UI bypass `0`。
- 最终 specification review：`Critical/Important/Minor = 0/0/0`；quality review：
  `Critical/Important/Minor = 0/0/0`；`git diff --check` exit `0`。

第一次浏览器执行在 canonical fixture 阶段失败，首因是误复用的 Phase4B2 fixture 强制要求
Provider 地址。修复后 Phase4C fixture 只建立真实的确认小纲→ChapterSession→WorkingDraft 链，
不再配置或启动 Provider；独立临时库复现及其后的两次完整 browser 执行均通过并清零资源。

## 证据策略与后续边界

本报告按 `docs/testing/test-gate-policy.md` 运行受影响 Python/Node/MySQL、生产 build 和一个窄
UI-only browser。完整 unit、完整 integration、历史 Phase 4 browser 与 release matrix 没有在
本切片重复运行，将在 Phase 4 close 串行运行一次。

功能代码验收快照为 `05491f2`。下一步是 Phase 4 close 的完整回归与阶段事实收口，而不是新增
fusion 或 full-draft rewrite。任何真实文章生成、真实模型 smoke 或产品数据库操作仍须用户另行
明确批准。
