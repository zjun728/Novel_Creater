# Phase 5 Lean Quality Review and Atomic Finalization Acceptance

## 结论与范围

Phase 5 最小质量审核与原子定稿闭环已在注入 fake quality/extraction Provider、随机
Disposable MySQL 和真实 UI 操作边界下验收。

作者可以从当前不可变 Candidate 发起质量审核和单次 Canon ChangeSet 提取，查看硬阻断与
建议，修正 ChangeSet，整体确认，并以一次事务提交最终正文、Canon revision、Projection、
Planning 实现进度和 ChapterSession final 状态。Provider 调用在事务外完成；确认与提交不调用
Provider。

真实 Provider 质量、产品数据库、小说下载/备份/导入和小说内容质量仍未验收。

## 闭合的不变量

- 只允许当前 Session 的当前 Candidate 进入定稿；candidate/basis/Canon/Planning/Outline 漂移、
  活跃 Draft Operation、硬质量阻断或 Canon 冲突都会 fail closed。
- 每次准备只发布一个持久化质量报告和一个 ChangeSet revision；作者修正创建不可变的新
  revision，确认精确钉住 revision/hash，不存在逐项确认或第二套事实源。
- 最终提交固定锁顺序并在一个事务内写 FinalChapter、Canon、Projection、Planning progress 和
  Session final；任一步失败都整体回滚，幂等重放不重复写入。
- 定稿后最终正文和对应 Outline/Planning 已实现边界不可修改；未来 Planning 只能承接尚未实现
  内容。Canon 是已确认事实的唯一权威，Projection 仅由同一次 Canon commit 确定性重建。
- Writer 只增加一个紧凑 finalization panel，没有新 router/store/editor、通用 workflow、评分框架
  或后台 job 系统。
- 当前 create-only Schema 为 `writer-core-v1.12.0`；没有 runtime migration、产品库读取或旧
  finalization 兼容路径。
- 自动门禁不调用真实 Provider，不读取产品库，不输出密钥、DSN、Provider 原文或正文 body。

## Fresh Phase evidence

- `npm test`：Python `3430 passed, 6 skipped`；root scripts Node `378/378 passed`；frontend
  Node `710/710 passed`；失败 `0`。
- `npm run test:integration`：`370 passed`；disposable database
  `created=368 cleaned=368 remaining=0`。
- `npm run build`：Vite `8.0.13`，`2969 modules transformed`。
- `npm run test:browser:phase5`：visible UI atomic-finalization scenario `1/1 passed`；runner
  报告 DB/process/port/temp/artifact/Vite residue `0`，real Provider calls `0`，Product DB
  reads/writes `0/0`。
- 独立资源审计：owned Python/Node process `0`、Phase5 temp `0`、Vite `deps_temp` `0`、
  test artifact root `0`、`novel_creator_test_%` database `0`。
- 最终 specification review：`Critical/Important/Minor = 0/0/0`；quality review：
  `Critical/Important/Minor = 0/0/0`；`py_compile` 与 `git diff --check` exit `0`。

## Phase gate 中收口的测试契约漂移

第一次 full unit 发现正式 route inventory 未登记 5 条 Phase 5 路由，旧 Writer SFC fixtures
未处理新增的初始 finalization GET，Phase 5 browser contract 与并发 Node 套件共享 pytest temp
lifecycle。第一次 full integration 又发现两个旧测试夹具仍按占位 schema 写 finalization 行。
这些问题均以测试清单、fixture 和 lifecycle 隔离的最小更新收口，没有修改生产行为或放宽产品
校验；定向测试转绿后，完整门禁从头通过。

## 后续边界

这是精简产品策略下的 Phase 5 close。下一产品阶段是 Phase 6：小说下载、安全备份、预检与
导入。真实文章生成、真实模型 smoke、产品数据库或 live 网站仍须用户另行明确批准；本报告
不授予 real-provider、product-database、export/backup 或 content-quality readiness。

阶段门禁快照为 `8edc651`，未 push。
