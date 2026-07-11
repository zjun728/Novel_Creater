# 当前项目状态

> 新线程或上下文压缩后先读本文件。日期：`2026-07-11`。

## 当前事实来源

按以下权威层级理解产品与 Writer Core V1：

1. `STORY_QUALITY_CHARTER.md`：最高产品质量原则。
2. `docs/superpowers/specs/2026-07-11-writer-core-v1-design.md`：Writer Core V1 实现权威。
3. `docs/superpowers/plans/2026-07-11-writer-core-v1-roadmap.md`：M1–M8 交付权威。
4. `docs/development/writer-core-m1-evidence.md`：M1 实机与浏览器证据。
5. `CURRENT_PROJECT_STATE.md`：当前有效状态和唯一允许的下一步。
6. `PRODUCT_DEVELOPMENT_PLAN.md`：当前里程碑规划。

Writer Core design/roadmap 不能替代 `STORY_QUALITY_CHARTER.md` 的质量总纲；质量判断始终服从 Charter，代码实现和里程碑交付分别服从 design 与 roadmap。

旧长篇项目、旧章节进度、旧状态链、旧 runner 和旧 artifact 不再是当前事实，也不得恢复为兼容路径或 Ready 证据。

## 当前结论

- Branch: `codex/writer-core-v1`
- Baseline: `4b85e8d`
- 当前里程碑：M1 已完成
- 证据等级：**L4 M1 No-Provider Ready**，不得升级表述
- Writer 状态：明确停用；旧 Writer 入口返回项目库

M1 只证明 Schema、Canon/Projection 基础、事务边界、产品只读页面和无 Provider 的产品状态。它不证明正文生成、Provider 链路或内容质量。

## 当前本机产品状态

- 产品数据库：MySQL `8.4.10`，`127.0.0.1:3307/novel_creator`
- 只读回滚源：MySQL `5.7.25-log`
- Schema version：`writer-core-v1.0.0`
- Manifest：`0697b6da4826b98c8e502ff7ad68a61b51fe7037b167b6d8175ae9d78dcff826`
- 表数量：`34`
- Canon head / Projection head：`0 / 0`
- 空派生写作表：`25/25`

旧 MySQL 5.7 仅用于只读回滚和来源核对。产品运行不读取旧库，不保留 dual-write、legacy fallback 或旧状态兼容。

## 当前项目基础数据

- 项目：`永乐大典`
- Project ID：`88d63943-ab7d-42c4-9319-998b6d61e413`
- 种子：`典镇山河`（selected）、`文渊山海`、`永乐长明`
- Provider profiles：`9`
- Preferred Provider/model：`联通云 / deepseek-v4-flash`
- 任务级绑定项：`8`，全部指向 preferred Provider/model

Provider 敏感行的内存核对为 `9/9`；API 明文敏感值命中 `0`，精确禁止键命中 `0`。M1 的 AI completion / upstream Provider model calls 为 `0`。

## 当前验收事实

- 真实 MySQL 8 cross-server integration：`2/2`。
- Final M1 gate 代码快照：`f9bfd2f`。
- `npm run test:milestone1`：exit `0`。
- Unit：Python `393`、scripts `24`、frontend `11`。
- Integration：`30 passed, 1 deselected`；disposable databases created `29`、cleaned `29`、remaining `0`。
- Browser：`2/2`；browser disposable database 已 drop。
- Post-test product DB counts：`PASS`。
- Gate 结束后端口 `8000` / `5173`：free。
- 产品浏览器：`8` 个产品 `GET` 请求，其中包含 `/api/providers` 配置读取；AI completion / upstream Provider model calls 为 `0`。
- Console errors / warnings：`0 / 0`。
- 截图只保存在本地忽略目录 `output/playwright/product-ui`，不进入 Git。

实机 dry-run 曾暴露两个编码问题，均已 TDD 修复：

- `latin1` 连接下，中文 title 普通等值不可靠；固定查询改为 ASCII-only 的 UTF-8 hex `BINARY` 精确条件。
- mysql client stdout 可含非 UTF-8 字节；四条固定查询统一使用 ASCII `HEX(JSON_OBJECT(...))` 传输，reader 以 bytes 严格解码。

## 分支与发布边界

- 远端 `main` 在 `4b85e8d` 之后已有 `13` 个旧 control-plane 分叉提交，尚未合并到 Writer Core V1。
- `codex/writer-core-v1` 可以安全推送为独立分支。
- canonical `main` 的 promotion/replacement policy 必须单独明确；当前不自动提升、不替换远端主线。
- 禁止把这 `13` 个旧分叉提交或旧兼容链无脑 merge/cherry-pick 回 Writer Core V1。

## 唯一允许的下一步

下一步只允许：**编写并审计 M2 detailed plan**。

M2 规划范围：

- `CreationContract`
- `StyleContract`
- Corpus assets
- Experience assets

当前不得开始 M2 实现，不得发起 AI completion / upstream Provider model call，不得生成正文，不得恢复旧兼容链。M2 详细计划经单独批准后，才可进入实现。

M2 之后继续按 roadmap 顺序推进：M3 滚动规划、M4 章节会话与候选、M5 场景生成与审核、M6 原子定稿、M7 Writer UI、M8《典镇山河》30 章人工验收。

## 文档纪律

当前状态文档只记录已取得的证据等级和当前授权。没有 Provider 调用、正文生成和人工阅读证据时，不得写更高 Ready 等级、产品完成或内容质量结论。
