# Phase 4 Lean Writer Loop Acceptance

## 结论与范围

The lean Phase 4 Writer Loop is accepted under injected fake-provider and
provider-free Candidate boundaries.

本阶段完成并整体验证：纯文本 WorkingDraft 自动暂存、`generate_new` 流式生成与重连/取消、
精确选区改写/润色/扩写/缩写、局部取消保留原稿、最近一次局部 AI 修改的一步追加式撤销、
显式 Candidate 冻结、Candidate 载入，以及最多两份 Candidate 的只读并排比较。

Phase4B2 generate_new streaming, automatic reconnect, and cancellation are accepted
with an injected fake streaming provider. Phase4B3 local tools and undo are accepted
with the same fake-provider boundary. Phase4C Candidate load and read-only comparison
are accepted without a Provider process.

Full-draft rewrite, Candidate fusion, general recovery browsing, Canon/finalization,
real-provider quality, product-database readiness, and content quality remain
unaccepted.

## 闭合的不变量

- 屏幕上唯一正文编辑器对应唯一 WorkingDraft；普通编辑自动暂存，只有显式“保存为候选”才
  创建不可变 Candidate。
- 所有 AI 写入在 Provider 副作用前冻结/验证 authority，Provider 调用不持有长事务；终态只在
  短事务中重新验证 fence/CAS 后提交完整权威 WorkingDraft。
- streaming delta 与局部替换预览不直接写正文；取消、失败、超时、过期、未知结果与迟到完成
  不得覆盖作者编辑。
- 局部工具验证精确 Unicode scalar 选区与 selected-text hash；一步 undo 只恢复最近一次仍未被
  后续写入触碰的局部结果，并以新 revision 追加历史。
- Candidate load 在同一事务中写 before/update/after，源 Candidate 保持不可变；客户端先 flush，
  只采用完整校准的 server workspace，迟到响应不能写回。
- 比较状态只存在于当前页面，最多两份，只读 `<pre>` 展示；没有第二编辑器、融合按钮、diff、
  modal 或持久化比较状态。
- 当前 create-only Schema 为 `writer-core-v1.11.0`；没有 runtime migration、旧写作兼容路径、
  新同步 AI 旁路、scheduler 扩展、Canon 写入或 finalization 行为。
- 自动门禁只使用 loopback fake/provider-free 边界和随机 disposable MySQL；日志、artifact 与公共
  错误不包含密钥、DSN、Provider 原文、选区或正文/Candidate body。

## Fresh Phase evidence

- `npm test`：Python `3322 passed, 6 skipped`；root Node `374/374 passed`；frontend Node
  `701/701 passed`；失败 `0`。
- `npm run test:integration`：`368 passed`；disposable database
  `created=366 cleaned=366 remaining=0`。
- `npm run build`：Vite `8.0.13`，`2966 modules transformed`。
- 正式 Phase 4 UI-only browser：Phase4B2 `4/4`、Phase4B3 `1/1`、Phase4C `1/1`，合计
  `6/6 passed`；各 runner 均报告 DB/process/port/temp/artifact/Vite residue `0`。
- 独立本轮资源账本：owned process `0`、owned listener `0`、常见开发端口 `0`、pytest temp
  `0`、Vite `deps_temp` `0`、本轮 browser roots `0`、`novel_creator_test_*` database `0`。
- Real Provider calls `0`；Product DB reads/writes `0/0`；live website `0`；UI bypass `0`。
- 最终 specification review：`Critical/Important/Minor = 0/0/0`；quality review：
  `Critical/Important/Minor = 0/0/0`；`git diff --check` exit `0`。

独立 temp 审计还看到一个 2026-08-08 创建的 `novel-creator-phase4b2-manual-*` 旧手工 Vite
cache，仅含稳定 `vite-cache`，没有 `deps_temp` 或占用进程。它早于本 runner，不能证明由本轮
拥有，故按资源所有权规则没有删除，也不计入本轮 runner residue。

## Phase gate 中发现并收口的测试契约漂移

第一次 full unit 发现全局正式路由 inventory 未登记已验收的 undo 与 Candidate-load 路由；
第二次发现 Phase3 历史事实测试仍硬编码 Phase4B2 进行中；第三次发现旧 SSR Candidate fixture
缺少 Phase4C 的公开 metadata 且仍断言已移除的 revision 文案。三处均只更新测试契约，未放宽
产品校验或修改生产代码；focused 证据转绿后，从头 full `npm test` 取得上述最终结果。

## 后续边界

这是精简产品策略下的 Phase 4 close，不把已明确延期的 full-draft rewrite、Candidate fusion 或
通用 recovery 浏览追认为完成。下一产品阶段是 Phase 5：先设计最小质量审核、单次
`FinalizationChangeSet`、作者整体确认与原子定稿闭环。

阶段门禁快照为 `840d90a`。真实文章生成、真实模型 smoke、产品数据库或 live 网站仍须用户
另行明确批准；本报告不授予 real-provider、product-database 或 content-quality readiness。
