# Phase 4B3 Selection Tools / One-step Undo Acceptance

## 结论与范围

Phase4B3 exact-selection rewrite, polish, expand, compress, cancellation, and
one-step undo are accepted with an injected fake streaming provider.

本验收只覆盖同一个 `PlainTextDraftEditor` 中的精确非空选区、四种局部 AI 操作、独立替换
预览、成功后的权威 WorkingDraft 重载，以及最近一次未被后续写入触碰的局部 AI 修改撤销。
自动门禁只使用 loopback injected fake streaming provider 和 disposable
`novel_creator_test_*` 数据库；没有调用真实 provider、live 网站或产品数据库。

Full-draft rewrite, candidate load/compare/fusion, finalization, Canon projection,
download/export, real-provider quality, and product-database readiness remain
unaccepted.

## 已验收的不变量

- 浏览器只在有效非空选区显示 AI 改写、润色、扩写、缩写；UTF-16 浏览器位置在边界转换为
  Unicode scalar offset，后端用 revision、正文 hash、范围和选中文字 hash 重新验证权威目标。
- Provider 输入仅包含操作意图、精确选中文字、最多两侧各 300 个 scalar 的正文上下文、
  一次性作者要求和最小已确认小纲上下文。
- 流式 delta 只进入独立替换预览，不在终态提交前修改编辑器或 WorkingDraft。
- 成功提交在短事务内重新校验 fence/CAS，只替换目标范围，追加前后 recovery revision，并
  以完整终态 WorkingDraft snapshot 更新编辑器和恢复选区。
- 取消、失败、超时、过期、重连耗尽和迟到完成均保留原 WorkingDraft；局部 partial 只能
  留作有界预览证据，不能部分写入正文。
- 一步撤销只允许最近一次仍为当前权威结果的局部 AI 修改；撤销追加新 revision，不倒退
  revision、不删除 operation、不修改历史，手工或后续写入会立即使其失效。
- 没有新增数据库表或列、第二条同步 AI 写路径、调度器行为、候选/融合行为、Canon 写入或
  定稿行为。Schema 只扩展既有 operation/replacement CHECK 枚举到 `writer-core-v1.10.0`。
- 公共错误、日志、测试摘要和 artifact 不包含密钥、DSN、provider 原文、选区或正文 body。

## Fresh slice evidence

- affected Python unit/API：`312 passed`；相关 Python 模块 `py_compile` exit `0`。
- affected frontend/root Node：`190/190 passed`。
- production frontend build：exit `0`，Vite `2966 modules transformed`。
- affected disposable-MySQL：`75 passed`；`created=75 cleaned=75 remaining=0`。
- UI-only browser：rewrite/polish/expand-cancel/compress/undo 单场景 `1/1 passed`；
  runner 报告 DB/process/port/temp/artifact/Vite residue `0`。
- 独立最终资源账本：owned process `0`、开发端口 listener `0`、Phase4B3 temp root `0`、
  Vite `deps_temp` `0`、`novel_creator_test_*` database `0`。
- Real provider calls `0`；Product DB reads/writes `0/0`；UI bypass `0`。
- 最终 specification review：`Critical/Important/Minor = 0/0/0`；quality review：
  `Critical/Important/Minor = 0/0/0`；`git diff --check` exit `0`。

第一次 MySQL 门禁只因工具的 120 秒包装时限退出；收集确认本切片为 75 个独立 schema
夹具后，相关进程与临时库均为 `0`，再以足够时限从头执行并取得上述 `75/75` fresh 结果。

## 证据策略与后续边界

本报告遵循 `docs/testing/test-gate-policy.md` 的精简风险分层：切片收口只运行受影响单元/API、
受影响 MySQL、生产 build 和一个窄 UI-only 浏览器场景。完整 unit、完整 364 项 MySQL、历史
Phase 4 浏览器矩阵和 release matrix 不在本切片重复运行，将在 Phase 4 收口时串行执行一次。

功能代码验收快照为 `caaeace`。下一产品切片是 Phase 4C candidate load 与 two-candidate
read-only comparison；AI fusion 继续延期。任何真实文章生成、真实模型 smoke 或产品数据库
操作仍须用户另行明确批准。
