# Phase 4B1 Formal Generation Acceptance

## 结论与范围

Phase4B1 formal generate_new is accepted with an injected fake provider.
Streaming, cancellation, rewrite/local tools, undo, full Phase4B, real-provider
quality and product-database readiness remain unaccepted.

本验收只覆盖一个持久化、幂等、fencing 的 `generate_new` 正式链路：浏览器先暂存可见
WorkingDraft，再提交一个 canonical UUID 幂等键；后端在 provider 调用前后使用短事务，
把结果作为新的 WorkingDraft revision 原子提交，并提供状态与事件读取。自动门禁没有调用
真实 provider、live 网站或产品数据库。

## 关键不变量

- 每个 ChapterSession 同时只有一个 active operation；同键重放不重复调用 provider，
  不同请求不能复用同一键。
- provider 等待期间不持有数据库事务；lease、fencing、CAS 与 authority drift 阻止迟到
  结果覆盖 WorkingDraft。
- 成功替换与 before/after recovery snapshots、terminal public event 同一原子提交；
  started event 在 reserve 短事务中持久化；不会自动创建 Candidate。
- HTTP 与前端仅投影 closed public contract；不暴露作者正文、provider body、密钥、base URL、
  DSN、lease、fencing token 或原始异常。
- B1 不伪造 token streaming；完成后只重新加载权威 workspace。

## 审查与修复收口

- Specification review：Critical/Important/Minor = `0/0/0`。
- Quality review：Critical/Important/Minor = `0/0/0`。
- 初次全量规格审查为 `0/3/1`：public DTO、未知结果恢复、stored-row strict
  projector 与 Unicode scalar 边界；修复后复审为 `0/0/0`。
- 初次质量审查为 `0/3/0`：provider 输出上限、租约到期结算、busy editor 键盘可读性；
  修复后发现并关闭一个压缩响应先解码后计数的问题，最终规格与质量均为 `0/0/0`。
- B1 commit 链从 `2ef5f53`（schema）到 `27e91c8`（最终 provider-response 边界修复）；
  formal acceptance 基线 HEAD 为 `27e91c81fabe316594fe8d775f0b973a0d33b4d9`。

## Fresh controller evidence

- `npm run test:integration`：`355 passed`，exit `0`，`1168.77s`；disposable MySQL
  `created=353, cleaned=353, remaining=0`。
- `npm run build`：exit `0`，Vite `2964 modules`。
- `git diff --check`：exit `0`。
- 资源账本：test database、owned process、listener、known port、integration temp 与
  Vite `deps_temp` residue 均为 `0`。
- 所有证据使用受控 fake provider 与 disposable MySQL；Real Provider calls `0`，
  Product DB reads/writes `0/0`。

## 后续边界

唯一下一工程阶段为 **Phase 4B2 streaming / reconnect / cancel**。受控 DeepSeek V3 Flash
smoke 仍需要用户明确批准和有效 token；它不是自动门禁，也不构成本报告的质量、真实 provider
或产品数据库验收。
