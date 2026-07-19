# Phase 2A：资产、语料与 Provider 设置验收

## 证据边界

- 环境：runner 独占创建并最终删除的 **Disposable MySQL** 数据库，以及 runner 独占创建并删除的 discovery / managed 语料根目录。
- 执行面：生产 FastAPI、生产 Vue/Vite 与 Chromium **真实浏览器**；全部业务写操作只由语义化 UI 操作触发。
- Provider 连接测试：后端进程内注入 **fake connection gateway**，只验证已保存的私密配置能够到达服务边界，不发起外部网络请求。
- Provider/model calls：`0`
- Product DB reads/writes：`0/0`
- 永久删除证据：浏览器确认危险操作后，必须先等到语料抽屉关闭且无错误提示，证明前端 API promise 已成功完成，之后才验证列表结果并允许导航。浏览器审计唯一一条精确语料来源 `DELETE` 请求、确认正文和 `204` 响应；生产后端的 bounded streaming access-log observer 独立确认同类精确路径有且仅有一条 `204`。全部 15 条写响应均按 method、path、status、count 精确验收；任何 aborted 请求均使验收失败。

## 正式覆盖

- 全局路由、项目创建及浏览器前进/后退。
- 已批准资产库存：10 套风格模板、64 张经验卡，以及搜索和详情。
- 合成语料的发现、导入、同来源新版本、归档、恢复、永久删除和被创作契约引用时的删除保护。
- Provider 编辑时私密字段留空、公开备注更新、fake 连接测试及清除 API Key。
- 应用 fallback，以及项目简单模式和高级八项模型绑定。
- 每个主要路由/检查点的 DOM 与可见文本，以及请求/响应体、控制台、服务日志和验收报告的运行时敏感值扫描。
- 浏览器验收关闭 trace、screenshot、video，并设置 `preserveOutput: never`；Playwright 输出目录位于 runner 临时根目录内且由 `finally` 整体删除，不生成或保留无法可靠 OCR 审计的 PNG/媒体证据。

## 隔离声明

旧 M2 Settings 规格仅保留作历史追溯，处于 **quarantined** 状态，不是本验收入口，也不作为 Phase 2A 证据引用。

本报告同时记录 Phase 2A focused runner 与主控在冻结差异上串行执行的完整单元、集成和生产构建门禁。

## 2026-07-19 执行结果

- Focused component / view / source / dispatcher / runtime contracts：`76/76` 通过。
- 正式入口 `node scripts/run-tests.mjs browser-phase2a`：退出码 `0`。
- 浏览器写操作：`15/15` 的 method、path、status、count 精确匹配；唯一语料永久删除由浏览器响应与后端 access log 同时确认 `204`。
- 敏感值扫描：DOM、可见文本、请求/响应、控制台、服务日志和报告 `match_count=0`；Provider/model 外部调用 `0`；产品数据库读写 `0/0`。
- 根 `npm test`：Python `1634 passed, 6 skipped`；Node `199/199`；前端 `213/213`。
- 根 `npm run test:integration`：`180/180` 通过；`created=179`、`cleaned=179`、`remaining=0`。
- 根 `npm run build`：退出码 `0`。
- 独立冻结复审：规格 `0 Critical / 0 Important / 0 Minor`；质量 `0 Critical / 0 Important / 0 新增 Minor`。
- 运行后清理：`disposable_database_count=0`，`owned_root_count=0`，`owned_process_candidate_count=0`，静态 Playwright 产物 `0`。
