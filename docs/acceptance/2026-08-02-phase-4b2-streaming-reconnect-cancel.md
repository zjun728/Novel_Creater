# Phase 4B2 Streaming / Reconnect / Cancel Acceptance

## 结论与范围

Phase4B2 generate_new streaming, automatic reconnect, and cancellation are
accepted with an injected fake streaming provider. Rewrite/local tools, undo,
full Phase4B, real-provider quality, and product-database readiness remain
unaccepted.

本验收只覆盖既有持久化 `generate_new` 的真实 SSE 消费、受界 partial 持久化、浏览器自动
reconnect 与幂等 cancel。自动门禁仅使用 loopback injected fake streaming provider 和
disposable `novel_creator_test_*` 数据库；没有调用真实 provider、live 网站或产品数据库。

## 关键不变量

- 一个绝对 1200 秒 deadline 覆盖 provider connect/send/read/parse；独立短 cleanup
  deadline 尝试关闭 response 与 client，调用方 `CancelledError` 保持优先，外部错误固定脱敏。
- streaming partial 只作为只读显示缓冲，不进入 autosave；terminal snapshot 可与最后 raw delta
  hash 解耦，完成或带结果取消后才重新加载权威 WorkingDraft。
- event cursor、operation id、terminal evidence 与 completed/failed/cancelled 结果严格校准；
  coordinator 先 validate/drain/calibrate，再 publish，并由 cancel fence 阻止迟到状态污染。
- draft worker registry 使用 inactive/active/closing/closed generation；bounded shutdown 后由
  transfer 强引用继续 drain。draft 与 market 都成功 drain 后 pool exactly once；失败、取消、
  pending 或 generic close failure 均 fail closed，下一 generation 在任何副作用前拒绝启动。
- public error、日志、测试摘要与 artifact 不包含密钥、DSN、provider 原文或正文 body。

## 审查与修复收口

- frontend terminal/timeline/coordinator：交接前 specification 与 quality 均为 `0/0/0`。
- backend shutdown ownership：specification `0/0/0`，quality `0/0/0`；focused `63 passed`。
- provider absolute/cleanup deadline：specification `0/0/0`，quality `0/0/0`；focused
  SSE/gateway `102 passed`。
- 一个非当前活跃路径的 pool 子 task 自取消测试缺口和一个 10ms 测试窗口理论抖动已记录为
  Deferred；按 Task12 硬停止条件未扩展实现范围。
- 全门禁发现未修改 SFC integration 夹具漏填公开 DTO 必填字段
  `activeDraftOperationId`；以 `null` 最小修复后，单文件 `7/7` 与完整 frontend `681/681`。
- 功能代码提交：`abec8414cb765bdd9dbd70c62724d5f2d4fcd296`。

## Fresh controller evidence

- `git diff --check 8ff40f0..HEAD`：exit `0`；controller 范围为 `59 files`。
- `npm test`：exit `0`；Python `3256 passed, 6 skipped`，script Node `368/368`，
  frontend Node `681/681`。
- `npm run test:integration`：exit `0`；`364 passed`，`1385.33s`；disposable MySQL
  `created=cleaned`，最终 `novel_creator_test_* remaining=0`。
- `npm run build`：exit `0`，Vite build `1.04s`。
- `npm run test:browser:phase4b2`：exit `0`，complete/reconnect/cancel-output/cancel-empty
  `4/4`；每场景 `DB/process/port/temp/artifact/Vite residue=0`。
- 最终资源账本：owned Node/Python/pytest process `0`、listener `0`、known dev port
  listener `0`、Phase4B2 temp root `0`、pytest artifact `0`、Vite `deps_temp` `0`、
  `novel_creator_test_*` database `0`。
- Real provider calls `0`；Product DB reads/writes `0/0`。

## 后续边界

不得把本报告解释为 full Phase4B、真实 provider 质量或产品数据库 readiness。Rewrite/local
tools、undo 与其余 Phase4B 能力仍未验收；任何真实文章生成或真实模型 smoke 必须等待本验收
提交完成后，由用户另行明确批准。
