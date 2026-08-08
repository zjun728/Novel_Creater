# Test Gate Policy

状态：Current
权威设计：`docs/superpowers/specs/2026-08-08-lean-test-gate-policy-design.md`

## 原则

保留全部正式测试和现有测试命令。测试证据按风险分为 focused、slice、Phase 和
release 四级；完整回归不是每次修改或每轮 review 的默认动作。

## Focused

开发 RED/GREEN/refactor 和失败诊断只运行明确命名的相关测试文件或测试选择器。
命令必须由当前实施计划列明，不使用自动 diff 推断。数据库行为未改变时，不运行
disposable-MySQL integration；页面关键路径未改变时，不运行浏览器门禁。

## Slice

切片实现完成后运行一次 fresh slice evidence：相关 Python unit/API、root Node、frontend
Node；修改生产前端时运行 build；修改持久化或事务时运行相关 disposable-MySQL 测试；
修改浏览器关键路径时运行对应的最窄正式 fake-provider browser scenario。

Implementer 记录该证据。Specification review 和 quality review 在没有代码变化、没有发现
遗漏测试类别时复用同一证据，不默认重复执行。代码变化只使受影响证据失效。

## Phase

所有切片通过且代码停止变化后，主控串行 fresh 运行一次：

1. `npm test`
2. `npm run test:integration`
3. `npm run build`
4. 当前 Phase 的正式 UI-only fake-provider browser gate
5. owned database/process/port/temp/cache residue audit

Phase gate 后发生代码变化时，只重跑受影响 focused/slice evidence；在新的 Phase 完成声明前
重新运行完整 Phase gate。

## Release

Release candidate 重复 Phase matrix，并增加当时适用的 product-shell、启动/打包、备份/导入、
秘密扫描和 release resource ledger。真实 Provider、live 网站和产品数据库必须获得用户明确
批准，永不由自动 release gate 隐式调用。

## 失败与输出

失败后执行 systematic debugging，记录 exit、count、首因和 owned-resource ledger；禁止盲目
重跑。日志和 artifact 禁止输出密钥、DSN、provider 原文或正文 body。

## 计划要求

未来实施计划必须列出精确 focused/slice 命令。只有记录了具体跨层风险时，才可在切片阶段
提前运行全量回归；验收文档必须标明使用的 evidence level。
