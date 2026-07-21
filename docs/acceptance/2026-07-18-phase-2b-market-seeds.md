# Phase 2B 市场证据与创作种子验收

状态：Phase 2B Task 7 已完成独立规格与质量复审；2026-07-21 fresh 全量门禁通过。

## 验收边界

- 使用 runner 独占的 `127.0.0.1` 随机端口和 Disposable MySQL 8 数据库。
- 使用真实 Playwright 浏览器，只通过产品 UI 和正式 API 完成操作。
- Qidian 与 QQ 两份公开榜单使用独立的手动快照；不访问真实网站。
- 市场分析与种子灵感使用 runner 注入的 fake gateway。
- 起点后续刷新失败只由 test-only fake adapter 触发，正式
  `MarketSourceService` 保持不变；官方刷新接口返回 HTTP `503` 和固定公开码
  `MARKET_TRANSPORT_FAILED`，前端捕获后通过正式 GET 重读失败状态与上一份
  成功快照。
- scheduler 全局关闭；仅验证计划启用与停用状态，不触发网络。
- 后端启动前把 `httpx.AsyncClient` 替换为 fail-closed 的
  `ForbiddenOutboundAsyncClient`，并只向正式服务注入 fake gateway /
  adapter；因此真实 Provider、模型和网站传输在该验收依赖图中结构性不可达。
- runner 只下发随机 Disposable MySQL 名称，并通过
  `BROWSER_TEST_DATABASE` 与 `SELECT DATABASE()` 双重核对数据库身份；产品库名
  会在任何目录、端口或进程分配前被拒绝。

## 行为证据

- 验证来源初始化、快照导入、后续失败保留上次成功、冻结分析与引用。
- 验证三个手动种子以及 A → B → A 的单调选定代次。
- 验证旧 A 下游链保持 superseded，不因重新选择 A 而复活。
- 验证危险永久删除只出现一个确认框，归档项目只读。

## 精确运行结果

- 正式 Playwright spec：`1 passed`，共有 `77` 处 `expect(...)` 断言。
- 运行时写入：`15` 次，且只命中以下封闭 allowlist：
  - 手动导入 Qidian / QQ 快照：`2`
  - 启用 / 停用起点计划：`2`
  - 起点手动刷新：`1`
  - 冻结市场分析：`1`
  - 临时种子灵感：`1`
  - 新建手动种子：`3`
  - 选定 A → B → A：`3`
  - 永久删除未引用 C：`1`
  - 归档项目：`1`
- 除起点手动刷新精确返回一次预期 HTTP `503` 外，其余允许写入状态均为
  `200`；运行时审计精确核对该响应的 URL、方法、状态和公开响应体。
- 浏览器只出现这次预期 `503` 对应的一条资源错误；页面错误、请求失败及其他
  非 2xx 响应均为 `0`。
- 所有浏览器请求只访问 runner 独占的 Vite 与 FastAPI 本机 origin。
- API key、私有 Provider URL、私有模型标记和私有会话标记在请求、响应、
  DOM、可见文本、控制台和错误面上命中数均为 `0`。

## Disposable MySQL 事实

- 冻结市场快照：`2`，独立来源：`2`
- 成功市场分析：`1`
- 成功种子灵感 attempt：`1`
- 三个种子创建后永久删除 C，最终 seed / revision：`2 / 2`
- 选定历史修订：`3`，最终选定代次：`3`
- creation contract 仍冻结在选定代次 `1`，当前 readiness 原因为
  `selected_seed_drift`；重新选回 A 没有复活旧下游链。
- 起点 policy 最终修订：`4`，计划关闭，保留上一份成功快照，并记录
  `MARKET_TRANSPORT_FAILED`。
- fake market adapter / market analysis gateway / seed gateway / downstream
  fixture 调用次数均为 `1`。
- fail-closed outbound HTTP ledger 没有触发；结合服务依赖覆盖，证明正式外联
  路径不可达，而不是用手写 `0` 常量代替证据。
- 数据库自检读取的当前数据库身份与 runner 随机生成的
  `BROWSER_TEST_DATABASE` 完全一致。

## 验收中发现并修复的生产缺陷

- 持久化 market analysis 使用 canonical snake_case，seed prompt 曾直接按
  camelCase 读取，导致真实数据库链在 gateway 调用前返回
  `SEED_INSPIRATION_INVALID_RESPONSE`。现在统一经领域解析器规范化为 alias
  形态；canonical persisted 回归为 `5 passed` 中的一项。
- seed list 与 selected-seed 曾把归档项目过滤为不存在，导致只读页产生两个
  404。现在读取走共享 `read_project`，写入仍统一走
  `lock_active_project`；Disposable MySQL 回归同时证明 archived 可读且
  create / edit / select / delete / archive / restore 均抛
  `ProjectArchived`，且 identities / heads / revisions / selection /
  selection ledger 全状态逐次保持不变。
- 归档项目的 seed list 与 selected-seed 虽保持可读，但服务端过去仍返回部分
  mutation capabilities 为 `true`。现在 `archived_at` 进入统一能力计算，
  `canEdit` / `canSelect` / `canArchive` / `canRestore` /
  `canPermanentlyDelete` 全部为 `false`；`referenced` 与
  `hasFinalChapters` 仍保留真实事实。真实 FastAPI + Disposable MySQL API
  回归同时覆盖 list 与 selected 响应。

## 隔离与清理

- runner-owned Node / Python 进程与监听端口：`0`
- `%TEMP%/novel-creator-phase2b-*` 目录：`0`
- `novel_creator_test_%` Disposable MySQL 数据库：`0`
- Playwright trace / screenshot / video：全部关闭，输出目录由 runner 删除。
- runner 的 server、port reservation、database 与 root 由可注入生命周期统一登记；
  行为测试证明 body 失败后仍按序尝试全部清理，任一清理失败也不会阻止后续
  清理，并会保留 body 与 cleanup 的全部错误。

已通过的聚焦命令：

- `npm run test:browser:phase2b`：退出码 `0`（正式 package / dispatcher 入口）
- `node --test scripts/tests/phase2bSuite.test.mjs`：`18 passed`
- `node --test scripts/tests/phase2bLifecycle.test.mjs`：`2 passed`
- `node --test scripts/tests/runtime-observer.test.mjs`：`10 passed`
- seed service / prompt unit 与 seed API 聚焦：`37 passed`
- archived seed 聚焦 Disposable MySQL service / API 回归：`4 passed`，
  `created=4 cleaned=4 remaining=0`
- Phase 2B 真实浏览器与数据库事实核验：通过

## 2026-07-21 fresh 全量门禁

以下命令在同一未提交 Task 7 工作树中严格串行执行，前一条退出码为 `0`
后才启动下一条：

- `npm run test:browser:phase2b`：退出码 `0`，总耗时 `40.3s`；正式
  Phase 2B Playwright spec 为 `1 passed`。结束后独立核对 runner-owned
  process / listener / temp dir / Disposable MySQL 残留均为 `0`。
- `npm test`：退出码 `0`，总耗时 `53.5s`；后端 unit / API 为
  `1866 passed, 6 skipped, 0 failed`，前端 unit 为
  `226 passed, 0 skipped, 0 failed`，根级 Node 合同为
  `220 passed, 0 skipped, 0 failed`。
- `npm run test:integration`：退出码 `0`；`208 passed`，pytest 耗时
  `640.04s`。Disposable MySQL 汇总为
  `created=207 cleaned=207 remaining=0`；结束后独立查询仍为 `0`。
- `npm run build`：退出码 `0`；Vite `8.0.13` 转换 `2906` 个模块，
  生产构建耗时 `1.00s`。
- `git diff --check`：退出码 `0`，无 whitespace error。

最后一个 M1 observer 旧源码合同也已按 RED→GREEN 修正：旧合同错误要求
`finish()` 直接调用 body drain；新合同验证 `settle()` 的 request / API body
排空顺序、`finish()` 内同一个 `try/finally` 的两次 settle 与五类 listener
解绑，并包含跨函数反例和等价格式正例。该修正的独立规格审查和质量审查均为
`Critical 0 / Important 0 / Minor 0`。
