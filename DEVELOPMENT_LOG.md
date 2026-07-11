# 开发日志

> 只保留当前仍有效的决策级记录。日期：`2026-07-11`。不粘贴密钥、原始运行日志或本地截图。

## 2026-07-11 Writer Core V1 reset 决策

- 批准 `docs/superpowers/specs/2026-07-11-writer-core-v1-design.md` 为总体产品设计。
- 批准 `docs/superpowers/plans/2026-07-11-writer-core-v1-roadmap.md` 为 M1–M8 交付顺序。
- 唯一实施基线为 `4b85e8d`，实施分支为 `codex/writer-core-v1`。
- 采用“保留产品外壳、替换写作内核”，不恢复旧数据库结构、旧 API、旧状态链、dual-write、legacy fallback 或旧 runner。
- M1 只建设 Schema、Canon/Projection、实体身份、事务基础和只读产品入口；Writer 在 M1 保持停用。

## 2026-07-11 跨库 reconciliation

本机产品状态统一到 MySQL `8.4.10` 的 `127.0.0.1:3307/novel_creator`。MySQL `5.7.25-log` 只读保留为回滚来源，不参与产品运行。

迁移后的 foundation：

- `永乐大典`，Project ID `88d63943-ab7d-42c4-9319-998b6d61e413`
- `典镇山河`（selected）、`文渊山海`、`永乐长明`
- `9` 个 Provider profiles
- Preferred Provider/model：`联通云 / deepseek-v4-flash`
- `8` 个任务级绑定项

未迁移旧派生写作状态。Writer Core Schema 为 `writer-core-v1.0.0`，manifest 为 `0697b6da4826b98c8e502ff7ad68a61b51fe7037b167b6d8175ae9d78dcff826`，共 `34` 张表；Canon/Projection heads 为 `0/0`，`25/25` 张派生写作表为空。

## 2026-07-11 实机 dry-run 编码修复

跨库 dry-run 暴露并通过 TDD 修复两个 MySQL 5.7 编码边界：

1. `latin1` 连接下，非 ASCII title literal 的普通等值无法稳定命中相同 UTF-8 bytes。固定项目/种子过滤条件改为 ASCII-only 的 UTF-8 hex `BINARY` 精确比较。
2. mysql client stdout 可能包含非 UTF-8 byte，导致 text-mode subprocess 在 reader thread 失败。四条固定 source `SELECT` 统一输出 `HEX(JSON_OBJECT(...))`；客户端捕获 bytes，并严格执行 ASCII hex、UTF-8 和 JSON object 解码。

修复没有扩大 whitelist、表或列，也没有写入旧库。错误路径只返回泛化错误，不回显原始输出。

## 2026-07-11 M1 证据与结论

- 证据等级：**L4 M1 No-Provider Ready**，仅此等级。
- Provider 敏感行内存核对：`9/9`。
- API 明文敏感值命中：`0`；精确禁止键命中：`0`。
- 真实 MySQL 8 cross-server integration：`2/2`。
- Final M1 gate 基于代码快照 `f9bfd2f`；`npm run test:milestone1` exit `0`。
- Unit：Python `393`、scripts `24`、frontend `11`。
- Integration：`30 passed, 1 deselected`；disposable databases created `29`、cleaned `29`、remaining `0`。
- Browser：`2/2`，browser disposable database 已 drop。
- Post-test product DB counts：`PASS`；gate 结束后端口 `8000` / `5173` free。
- 产品浏览器：`8` 个产品请求，全部为 `GET`，其中包含 `/api/providers` 配置读取；AI completion / upstream Provider model calls `0`；console errors/warnings `0/0`。
- 旧 Writer 入口返回项目库，Writer 明确停用。
- 截图保存在本地忽略目录 `output/playwright/product-ui`，不进入 Git。

完整收口证据见 `docs/development/writer-core-m1-evidence.md`。

M1 没有 AI completion / upstream Provider model call、正文生成或人工内容验收，因此没有正文质量结论，也不授予更高 Ready 等级。

## 下一步决策

当前只允许编写和审计 M2 detailed plan，范围为 `CreationContract`、`StyleContract`、Corpus assets 和 Experience assets。详细计划批准前不开始 M2 实现。M3–M8 继续服从 Writer Core V1 roadmap。

## 日志纪律

本文只记录当前有效决策和证据摘要。原始 DB 输出、浏览器 network/console dump、Provider 配置值、截图和完整测试日志不进入本文档。
