# 当前项目状态

> 核查日期：2026-09-05（Asia/Shanghai）。记录实际状态、证据边界和用户决定，不代表完整产品已验收。
> 原 2026-08-09 状态已原样保存至 [历史快照](docs/history/2026-08-09-current-project-state.md)。其中“下一步 Phase 6”等结论仅适用于当时。

## 1. 当前任务及决定来源

用户已先后批准方案 A 和 B。A 已快进合并到本地 main；B 已独立提交为 `4cf3c35` 并通过相关验证，原 QA 的已确认 R2 已通过正式界面撤销。正文、候选和审查证据保留，未重新调用模型，真实创作验收尚未恢复。

- 直接交接任务：`Novel_Creater Phase4B2 收口与真实文章测试`，ID `019fdfff-b380-7ec3-af1c-49065da3f383`。
- 当前任务：`GPT-6 · Novel Creator 完整流程接管`，ID `01a07028-ff03-7403-a04d-6c72f93449ae`。
- 已补读直接交接任务最近几轮用户决定和发给当前任务的交接内容，未以早期大任务替代当前现场。
- 用户已选择将项目资料功能本地合并到 main；未授权推送。
- 原交接顺序：只读接管 → 项目资料真实 smoke → 完整真实创作流程 → 质量评估及必要修复 → 最终验证。
- 当前用户纠正了执行顺序，要求先熟悉项目、核实状态与卡点；随后同意先更新状态，再提供定稿阻断最小修复方案供审阅。
- 在方案审阅后，用户同意先实施 A。方案 A 已从 `codex/finalization-preflight` 快进合并到本地 main，未推送。
- 随后用户以“开始吧”批准 B：显式撤销已确认但未定稿的审查，并通过正式界面恢复原 QA R2。当前结果见 [B 验证记录](docs/superpowers/acceptance/2026-09-05-finalization-revocation-b.md)。
- “立即实施 P0-E”是接管者根据总设计提出的建议，不是旧任务已确认的立即执行项。P0-E/F/G 仍为后续产品工作，不因本文件获得实施授权。

## 2. 产品目标与权威边界

帮助作者持续创作至少约 200 万字的长篇小说；新项目默认 240 万字、720 章。目标是故事清楚、具体、有因果、有选择和后果，人物与事件能跨章延续。

```text
市场参考或自由创意 → AI 讨论 → 候选种子版本 → 创建项目
→ 作者确认项目种子 → 创作契约 → 创作圣经
→ 分卷／情节线／故事块／阶段／场景任务 → 当前章小纲
→ 正文工作稿 → 候选 → 质量审查和一次结构化提取
→ 作者确认完整变更集 → 原子定稿 → 下一章
```

- Canon 是“已发生事实”的唯一权威来源；状态、记忆、弧光、线索和实际进度由它确定性投影。
- Planning 描述未来意图，不能当成已发生事实。AI 只产生草稿、候选或建议，作者决定确认及定稿。
- 单章顺序推进，不批量自动写作；上一章未完整定稿，不推进下一章。
- 已确认的种子、契约、圣经保持永久基线；已定稿正文、小纲及其钉住依据不可改写。
- 确认契约、圣经、规划、小纲后使用侧栏手动切换，不强制跨模块“继续下一步”。
- 工作台目标是统一当前章生产、按卷章节导航、历史只读和小纲查看；目标尚未全部实现。
- 使用现有产品数据库，不另建长期产品库，暂不迁移旧项目；不得恢复旧写入链或建立第二套事实源。

依据：[故事质量总纲](STORY_QUALITY_CHARTER.md)、[P0 总设计](docs/superpowers/specs/2026-08-30-p0-author-product-design.md)、当前用户指示及后续专项规格。早期规格冲突以明确的后续修订为准。

## 3. Git 与运行现场

| 项目 | 核查结果 |
| --- | --- |
| 工作目录 | `D:\Projects\Novel_Creater` |
| 本地代码版本 | `main@4cf3c35`（B 独立提交）；接管文档另作提交，最新 HEAD 以 Git 为准 |
| 本地远端跟踪引用 | `origin/main@ef73a917618fc5559c9659a1c276f150423d86a0` |
| 差异 | A 合并时领先 9、落后 0，此后新增 B 及接管记录提交；未 fetch，不外推远端服务器此刻状态 |
| 主工作区 | B 实现、测试及验收记录已本地提交；接管文档与历史断言来源另行记录；保留无关未跟踪资源 |
| 产品数据库 | 配置名 `novel_creator_v113`，loopback MySQL 端口 3307 |
| 运行 Schema | 正式只读 API 返回 `writer-core-v1.14.0`，数据库名称不代表 Schema 版本 |
| 自有后端 | B 恢复后 PID 35188，loopback 8000，已载入 A/B；本次启动关闭市场定时器 |
| 自有前端 | B 恢复时 loopback 5173，Vite 8.0.13，已载入 A/B |

进程 ID 仅为接管时快照，后续操作须重新核对归属。A 的验证仅启停自有临时测试服务，使用 disposable 数据库和模拟 Provider；产品服务、业务数据及真实模型未操作，未迁移或推送。

## 4. 实际开发进展

| 范围 | 状态及证据边界 |
| --- | --- |
| Writer Core、规划、小纲、工作稿、候选、审查、原子定稿 | 已有实现及 Phase 3–5 阶段验收；早期生成和审查主要注入模拟 Provider，不能等同真实内容质量通过 |
| 下载、备份、导入 | 已有 Phase 6A/B/C 独立验收记录，不是当前待从零建设的功能 |
| 产品数据库 | Phase 7B 于 2026-08-23 验收，后续选题中心沿用原产品库升级；本次只读核对当前运行版本 |
| 作品稿件阅读 | Phase 8A 有按卷目录、定稿正文、钉住小纲、阅读和下载验收，不等同统一工作台完成 |
| P0-A/B | 核心保护、工作台领域契约、项目壳层与概览已有实现和测试入口 |
| P0-C 及真实榜单补齐 | 全局讨论、证据、方向、候选版本和原子交接已有实现；直接交接报告真实闭环完成并推送至 ef73a91，5 个可刷新来源及 5 个手动导入来源；可用性不外推到未来日期 |
| P0-D | 种子、契约、圣经作者文档界面及显式提案采用已有实现、浏览器门禁代码和后续修复，不是空白模块 |
| 项目资料 | 五字段创建／编辑、归档只读、生命周期 CAS、并发修复及消费者刷新已进入 main；该功能提交 cde7f2e |
| P0-E | 规划与连续性作者化未完整交付。Canon/current-state/memories/arcs/plot-threads 底层接口已存在；连续性作者页面未进入正式路由，概览返回 pending_module |
| P0-F | 有 workbench 领域契约，实际路由仍分为 manuscript 与 write/chapters；统一工作台和独立 planning/outlines 入口尚未落地 |
| P0-G | 连续三章真实验收、状态传递、内容质量及千章规模等综合门槛未完成 |

可追溯记录：

- [Phase 6 完整阶段门禁](docs/acceptance/2026-08-10-phase-6c-atomic-project-import.md)
- [Phase 7B](docs/superpowers/acceptance/2026-08-14-phase7b-product-database-readiness.md)
- [Phase 8A](docs/superpowers/acceptance/2026-08-24-phase8a-manuscript-productization.md)
- [P0-A 接口契约](docs/superpowers/contracts/2026-08-30-p0-author-product-interfaces.md)
- [P0-D 实施计划](docs/superpowers/plans/2026-08-31-p0-d-creative-foundation-authoring.md)
- [真实选题中心计划](docs/superpowers/plans/2026-09-04-topic-center-live-market-closure.md)
- [项目资料计划](docs/superpowers/plans/2026-09-05-project-metadata-settings.md)

部分近期计划复选框未更新，部分阶段有门禁代码但本次检索未找到独立验收报告。判断完成情况须结合提交、直接交接证据和实际接口，不能仅凭文件名、测试数量或复选框作结论。

## 5. 已执行的接管测试及其边界

### 项目资料 smoke：已执行，不应无理由重做

正式界面验证五字段、默认规模、创建、编辑保存、刷新持久化及归档只读；本步骤没有 Provider 调用。

自有项目 `4687717a-3268-4c44-b44f-4b5d1b09baa0` 经精确归属核查后，通过正式删除 API 清理：204 后 GET 404。未处理其他 QA 项目。

### 完整真实创作探索：暂停，不能判定通过

接管者此前过早推进了创作探索。已执行真实讨论、候选、种子、契约、圣经、规划、小纲、正文和审查；故事块／阶段／场景任务由人工填写，部分 AI 内容经人工纠正，不能计作全自动生成成功。

- 测试讨论：`QA-ASTRA-20260905-1407-长篇创作闭环`。
- 测试项目：`QA-ASTRA-20260905-1407-江夜行`，ID `a95c9cd9-c3f0-5e5d-81f3-bc0fb7127a6a`。
- 第一章会话：`63765638-303f-48ae-aed3-b5734a2ee833`。
- 原阻塞：已确认变更集 R2，包含 4 个规划补丁，定稿请求返回 409。B 恢复后同一审查 `33055437-cef5-4070-a330-893263f51004` 状态为 cancelled，确认仍为 R2，原 payload/hash 保留。
- 只读查询：定稿数 0、项目 currentChapter=0、Canon head=0、Projection head=0，投影同步。
- 原工作稿及两个候选与撤销前逐项相同；界面恢复候选选择及“审查并定稿”入口。尚未重新审查或定稿，第二章承接未测试；本次唯一业务写入来自正式界面的显式撤销。
- 测试项目和讨论保留；后续处置须核查精确归属及关联关系，不能批量清理同名 QA 数据。

局部过程记录在 `output/playwright/astra-20260905-1404-progress.md`；它不是完整验收报告，部分记录落后，以本文件核查结论为准。

### 接管阶段已有测试证据

- 直接交接报告：合并后的 main 后端 6088 passed／17 skipped，前端 1131 passed，构建成功，独立审查 Ready。
- 接管探索期间：主工作区后端 6088 passed／17 skipped；隔离推荐提示修复分支前端 1132 passed、脚本 457 passed、构建通过，独立审查无问题。
- 后一组前端证据含尚未合并的 1 个新增测试，不能写成 main 已有 1132 项。
- 接管文档初稿阶段没有重跑测试或浏览器门禁；这些历史证据不能证明完整真实定稿和跨章流程通过。

### A 隔离分支最终验证：2026-09-05

- 后端 unit/API：6114 passed／17 skipped；脚本：457 passed；前端：1137 passed；生产构建通过。
- 受影响 disposable MySQL：仓储 SQL、原子提交及新增审查转换到最终提交的 3 个用例均已通过，测试库已清理。
- 正式 Phase 5 浏览器 1/1：转建议 → 删除另一未来补丁 → 保存 R2 → 确认 → 原子定稿；最终事实与进度投影、规划更新及章节记录符合后置条件。
- 规范及代码质量独立审查通过。使用模拟 Provider，产品数据库读写 0/0；自有临时数据库、进程、端口和测试产物残留 0。
- 验证记录：[A 验证与集成边界](docs/superpowers/acceptance/2026-09-05-finalization-preflight-a.md)。A 合并时 main 与已验证分支代码一致，复用原测试结果；当时未恢复 QA R2、未重启产品服务。后续 B 已完成恢复并启动包含 A/B 的产品服务。

## 6. 卡点与待办

| 问题 | 已知事实 | 处理边界 |
| --- | --- | --- |
| 定稿前后校验不一致 | A 已进入 main，补齐受保护节点预检、转建议及未来补丁完整规划试算 | 最终回归及独立审查通过，已本地合并；保留 commit 保护，不解锁历史、不直接改库 |
| 确认后的恢复缺口 | B 新增精确审查撤销与只读结果核对，原 QA R2 已恢复 | 原确认、修订、候选与正文不变；重审须作者再次点击，不自动生成 |
| 审查证据质量 | 事实引用区间与对应事件位置不符，质量建议均指向 0–1；界面不能修正引用 | 独立质量与交互问题；索引合法和 hash 一致不能证明语义支持 |
| 推荐失败提示 | rankingUnavailable 被显示成“无推荐”，完整库仍可手选 | 隔离修复尚未提交合并，不代表推荐服务本身已修好 |
| AI 内容与规划范围 | 小纲过度展开、承接字段混入章末结果、能力及场景连续性需人工纠正；规划 AI 目前只编辑 volumes/plots | 整理提示词、上下文和交互差距，不能擅自扩大生成范围 |
| 作者页面不完整 | P0-E/F 目标尚未全部落地 | 后续独立界定范围，不把目标规格当作已有能力 |

方案见 [定稿阻断最小修复方案（A/B 已批准并实现）](docs/superpowers/specs/2026-09-05-finalization-review-blocker-design.md)。B 的后端、前端、数据库并发及浏览器证据详见 [B 验证记录](docs/superpowers/acceptance/2026-09-05-finalization-revocation-b.md)。

## 7. 当前待处置资源

- A 隔离分支 `codex/finalization-preflight`，目录 `.worktrees/finalization-preflight`，基线 cde7f2e，本地提交 `4dd2b18`；分支工作树干净，已快进合并 main，未推送。前端 node_modules 是指向主目录的连接，不能递归删除。
- 隔离分支 `codex/astra-recommendation-status`，目录 `.worktrees/astra-recommendation-status`，基线同 cde7f2e。
- 仅 3 个未提交文件：StyleSelectionStep.vue、AssetScopeStep.vue、projectContractView.test.mjs；未合并、推送。
- 自有额外未跟踪路径：`.codex-test-artifacts/`、`tmp/astra-qa-deps/`，当前不删除、不提交。
- `output/playwright/` 下有自有记录、日志及截图，不作为业务源数据。
- 原有 `.review-worktrees/` 及五个 tmp HTML 必须保留：brainstorm-topic-center-flow-v2.html、brainstorm-topic-center-flow.html、brainstorm-topic-center-options.html、brainstorm-topic-center-waiting.html、p0-d-foundation-layout-options.html。
- 其他历史 worktree 保持原状，不能因目录旧或分支多就认定可以删除。
- 依赖曾因缺包补齐，后按现有 lock 执行 npm ci 恢复；package 与 lock 无受跟踪修改。隔离分支 node_modules 仍通过目录连接使用主目录依赖，不能随意递归删除。

## 8. 下一步顺序

1. A 实现、验证及本地 main 集成已完成，提交 `4dd2b18`；未推送，分支和工作树保留。
2. B 已完成原 QA R2 恢复。接下来从保留的候选稿重新审查，检查 A 对受保护规划补丁的转换及事实证据质量，再决定作者确认与定稿；本轮未执行这段真实模型流程。
3. 推荐提示修复作为独立已有成果待处置，不在定稿修复里混入无关改动。
4. P0-E/F 各自形成范围受控的工作；它们是后续待办，不是旧交接已授权立即重做的模块。
5. 修复及必要产品能力就绪后，再明确范围恢复真实创作验收；复用已完成 smoke，不反复建设测试框架。
6. 未经用户明确要求不推送。此次授权只覆盖指定旧 R2 的正式恢复，不授权批量清理或恢复其他审查。
