# 开发日志

> 只记录当前有效的决策与证据摘要。日期：`2026-08-09`。不记录密钥、DSN、原始运行日志或本地截图。

## 2026-07-18 产品主规格重置

- 批准
  `docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`
  为当前产品主规格。
- 产品目标冻结为“故事好看、内容丰满、人物鲜活、作者可控”，不以高级文学性为首要目标。
- 采用 Canon 唯一事实源、已发生事实与未来计划分离、作者一次确认完整
  `FinalizationChangeSet`、后端单事务定稿。
- 不兼容旧数据库、旧 API、旧 Store、旧写作页、phase-e shadow QA 或旧 artifact。
- 七阶段按纵向闭环交付，第一阶段只交付产品壳层和项目生命周期。

## 2026-07-18 Phase 1 实现

- 分支：`codex/product-shell-lifecycle`。
- 代码验收快照：`dd40cf2e452243c6c8085fd486a3831b6e059796`。
- 新增正式项目库、项目概览、已归档项目页、只读归档状态页、Provider 设置页和 Not Found。
- 项目卡片只通过明确按钮导航；有可恢复 Session 时才显示“继续写作”。
- 创建和重命名仅编辑项目名称。
- 归档立即执行并提供 Toast 撤销；恢复立即执行；永久删除只在已归档页并要求一次危险确认。
- 后端用 `archived_at` 与 `lifecycle_revision` 区分生命周期和写作状态，采用事务、行锁和 CAS。
- Schema 所有权负责项目私有数据级联清理；跨项目来源置空；共享资产保留。
- 所有正式写服务统一增加 active-project 写入围栏。
- 路由成为项目上下文来源；刷新、深链接、missing/error/archived 状态均有明确页面。
- 全局反馈改为 Toast/就地错误；阻断操作使用单一 overlay、shell inert、焦点恢复和路由守卫。
- 旧 `/project/...`、旧 `/writer/...` 字面路由和旧项目删除实现从生产代码清除。

## 2026-07-18 Phase 1 发布门禁

环境变量只核对存在性，没有打印值。基于 `dd40cf2`：

- `npm test` exit `0`：
  - Python `1398 passed, 3 skipped`
  - scripts `185 passed`
  - frontend `184 passed`
- `npm run test:integration` exit `0`：
  - `154 passed`
  - disposable databases `created=153`、`cleaned=153`、`remaining=0`
- `npm run test:browser:product-shell` exit `0`
- `npm --prefix frontend run build` exit `0`，`2855 modules transformed`
- `git diff --check` exit `0`
- Schema source：`writer-core-v1.2.0`
- Manifest：
  `6164f0f57d3acd59dcab054549d634a4138b82a18962f145140fd56f0244ab4b`
- Provider/model calls：`0`
- Product DB reads/writes：`0/0`

真实浏览器验收覆盖创建、打开、刷新、重命名、归档、撤销、恢复、永久删除、
missing/error/retry、IME、Tab 焦点循环、Escape 焦点恢复、全局阻断 overlay、
键盘/程序化/Back 导航拦截、重叠 operation token 和敏感值扫描。

浏览器 runner 仅启动并清理自己拥有的动态端口进程；不会终止用户已有服务。
测试库名严格符合 `^novel_creator_test_[a-f0-9]{32}$`。

## 2026-07-18 安全与数据库边界

- Provider 公共序列化删除 `apiKey/api_key/baseURL/base_url`，只返回配置状态布尔值。
- Provider 列表、创建和更新响应统一经过该序列化器。
- 本阶段未启动、查询或重建产品数据库。
- 源码 Schema 已前进到 v1.2，但产品数据库现存版本未在本阶段重新验证。
- 产品服务按 v1.2 正式启动前，需要单独明确批准一次开发数据库重建；正常启动不得自动执行 DDL。
- 本阶段没有真实 Provider、正文生成或作者内容阅读，不能推导正文质量。

## 2026-07-23 Phase 2 Creative Foundation 完成

- Phase 2 完成创作资产、Provider/模型设置、市场与种子、故事发动机与创作契约、
  创作圣经及其正式页面。
- 最终自动验收提交：`0a855f4`；验收报告提交：`c0b8663`。
- Phase 2 acceptance chain 进入 canonical `main` 后的链末提交：`f11faad`。
- Committed acceptance 报告记录的证据边界是 No-Provider、Disposable MySQL 8、
  UI-only 真实浏览器；本日志不把该历史门禁冒充本轮重新运行结果。
- Product DB Ready、Real Provider Ready、Phase 4 Writer Loop、Phase 5
  Finalization 和 Content Quality Ready 均未评估。

## 2026-07-24 Phase 3 Story Planning 启动

- Canonical release branch：`main`。
- 当前开发分支：`codex/phase3-story-planning`。
- 已批准
  `docs/superpowers/specs/2026-07-24-phase-3-story-planning-design.md`。
- 当前工作是 Planning aggregate、Volume、Plot、StoryBlock、Stage、SceneTask
  和 ChapterOutline，不是正文写作或定稿。
- Planning 只保存未来计划；实际完成状态只允许从 Canon/Projection 读取。
- Phase 3A 从空库建立目标 Schema，不迁移旧 Planning 数据，不保留第二套 Store、
  状态或生成链路。

## 2026-07-24 Phase 3A Planning Aggregate Foundation 完成

- 完成 `writer-core-v1.5.0`、Planning/Outline 聚合、稳定节点身份、
  canonical hash、显式 Draft 保存、幂等确认、不可变历史与完整 CAS。
- Seed/Contract/Style/Bible generation fence 已封住 confirmed A → B → A
  旧 Planning、旧 Outline 和既有 ChapterSession 的复活路径。
- ChapterSession 创建和既有会话返回都先重校验当前 Planning Head/generation、
  Outline、Canon 与 Projection。
- 当前公共 Planning/Outline 输入只接受 camelCase；未恢复 snake_case 兼容、
  旧 Planning 表、旧 Store 或旧生成链。
- 当前 schema 的开发重置只清除派生数据并原子重建 Contract/Bible/Planning/
  Canon/Projection revision 0；不执行旧 schema 迁移。
- 规格审查和质量审查最终均为 `0/0/0`。
- Fresh `npm test`：Python `2353 passed, 6 skipped`，根级 Node `191 passed`，
  前端 `365 passed`，失败 `0`。
- Fresh Disposable MySQL integration：`300 passed`；数据库
  `created=299 cleaned=299 remaining=0`，独立查询残留 `0`。
- Fresh build：Vite `2937 modules transformed`；`git diff --check` exit `0`。
- Product DB reads/writes：`0/0`；Provider calls：`0`。
- Phase 3B–3D、Real Provider、Product DB、Phase 4 Writer Loop、Phase 5
  Finalization 和 Content Quality 均未评估。
- 详细证据：
  `docs/acceptance/2026-07-24-phase-3a-planning-aggregate.md`。

## 2026-07-26 Phase 3B Volumes and Plots 完成

- 分支：`codex/phase3b-volumes-plots`；代码验收快照：`e3c7d18b23fa`。
- 交付正式 Volume/Plot API、共享 Planning 页面、单一 Store、手工 Draft 和显式
  AI 生成 Draft。
- AI 链使用已确认 Seed/Contract/Bible 构建冻结 safe manifest，采用确定性
  `40 KiB` 预算、前后秘密扫描、两段短事务、幂等键、租约、fencing token 和
  精确 Draft CAS。
- 作者编辑或项目生命周期、basis、head、binding、fence 漂移时，迟到结果不会
  覆盖 Draft；未知结果只按 operation ID 回读，不重复生成。
- 历史 current/superseded/archived 状态和项目 next action 均由后端权威决定；
  archived/superseded 状态可读不可写。
- Task 10 验收文档与事实合同规格审查：`Critical 0 / Important 0 / Minor 0`。
- Task 10 验收文档与事实合同质量审查：`Critical 0 / Important 0 / Minor 0`。
- Fresh focused gates：Python `193 passed`；Node/Frontend `59 passed`。
- Fresh `npm run test:browser:phase3b`：manual/gateway 两个 UI-only 场景通过；
  数据库 `created=2 cleaned=2 remaining=0`，owned resource residue `0`。
- Fresh `npm test`：Python `2542 passed, 6 skipped`，Node `216 passed`，
  frontend `415 passed`，失败 `0`。
- Fresh Disposable MySQL integration：`317 passed`；数据库
  `created=316 cleaned=316 remaining=0`；独立查询残留 `0`。
- Fresh build：Vite `2949 modules transformed`；`git diff --check` exit `0`。
- 一次先前的 integration 会话被交互中断并留下一个严格匹配
  `novel_creator_test_<32 lowercase hex>` 的 disposable 库；主控只查询测试
  namespace、校验名称后删除该库并确认残留 `0`，随后从头完成上述 fresh
  integration。
- Product DB reads/writes：`0/0`；Real Provider calls：`0`；Live website
  access：`0`；任何公共响应、日志、报告和 artifact 均未输出明文 API key。
- 尚未评估 StoryBlock/Stage/SceneTask、ChapterOutline 作者工作流、Phase 4
  Writer Loop、Phase 5 Finalization、Product DB、Real Provider 和 Content
  Quality。
- 详细证据：
  `docs/acceptance/2026-07-24-phase-3b-volumes-plots.md`。

## 2026-07-30 Phase 3C Story Blocks and Chapter Outlines 完成

- 分支：`codex/phase3c-story-blocks-outlines`；交付基线：`main@59d80d739ef39a09bcd54e1888e4e4da90a98fa3`；功能代码 HEAD：`056520c1f270fdf8f3888be2713647fff03bf2b8`。
- 交付唯一 `planning-v1`/`planningStore` 上的 StoryBlock/Stage/SceneTask 第三
  Planning tab，以及手工 ChapterOutline Draft、save CAS、confirm 和 history。
- 显式 AI 只通过 fake 外部边界生成可编辑 Outline；AI 不确认、不创建 Session；
  authority drift 会 supersede 迟到结果。
- 后端权威章节算法与每项目最多一个 drafting Session 约束已接通；已存在 Session
  保留旧 pins 并支持幂等重放。
- Overview、Outline、Session 与 Writer 使用 backend `targetPath` 和权威 chapter；
  Writer 只读 Outline 摘要并从空 WorkingDraft 进入。
- 交付代码顺序规格/质量、M1 follow-up 与 pinned-session follow-up 的最终
  `Critical/Important/Minor` 均为 `0/0/0`。
- Task 12 验收文档与事实合同规格审查最终：`C/I/M 0/0/0`；质量审查最终：`C/I/M 0/0/0`；只覆盖本次五文件 Task 12 包，不外推为任何未评估产品能力 Ready。
- Fresh focused gates：Python `250 passed, 0 skipped, 0 failed`；Node `144/144 passed, 0 failed, 0 skipped`。
- 第三次从头 final 五门禁全部 exit `0`；browser `7` 场景，完整 Python `2814 passed, 6 skipped, 0 failed`，root Node `243/243`，frontend Node `522/522`，integration `342 passed`，build `2956 modules transformed`，whitespace errors `0`。
- browser/integration Disposable MySQL 均 created=cleaned、remaining `0`，最终独立
  cleanup 的 owned process、port、Phase 3C temp roots、Vite cache 和 test DB
  均为 `0`。
- Real Provider calls `0`；Product DB reads/writes `0/0`；live website `0`；secret scan findings `0`。
- `writer-core-v1.5.0` 未变；Phase 3C 没有 Schema、migration 或 compatibility。
- Phase 3D 是唯一下一步；正式写作、Finalization、真实 Provider、产品数据库与小说内容质量仍未评估。
- 详细证据：
  `docs/acceptance/2026-07-26-phase-3c-story-blocks-outlines.md`。

## 2026-07-30 Phase 3 Story Planning 完成

- Phase 3D 与完整 Phase 3 已完成。
- 唯一下一产品包：Phase 4 Writer Loop。
- 分支：`codex/phase3d-boundary-acceptance`；交付基线：`main@e8aebd9eb851ccc64f160022984342344905cd15`；功能代码 HEAD：`382dcefa57f575209cc703d3af0e60fd1b11137d`。
- 当前源码 Schema 为 `writer-core-v1.6.0`；Candidate 身份包含 Outline/Planning/Canon/Projection 依据，Phase 3D 不提供 migration 或 compatibility path。
- Future Plan/Actual Progress/Canon Projection 在同一 revision 只读组合，Planning 读取不写 lifecycle。
- 完整 Fresh 门禁为 browser `6/6`、Python `2871 passed, 6 skipped, 0 failed`、root Node `345/345 passed, 0 failed`、frontend `547/547 passed, 0 failed`、integration `341 passed, 0 failed`、`created=339, cleaned=339, remaining=0`、Vite `8.0.13` 和 `2958 modules`；所有命令 exit `0`。
- owned process、port、temp、artifact、cache 与 test DB 均为 `0`；Provider `0`、Product DB reads/writes `0/0`、live `0`、UI bypass `0`、secret `0`。
- Seed、Contract 与 Bible 的已确认内容为永久基线；未来 Planning 只处理尚未实现的内容。正文定稿前对应大纲可以调整，正文定稿后大纲与事实不可修改，均以已实现和规格明确支持的范围为准。
- Setting 与知识库仍在 Phase 5 通过 Canon/Projection 落地；Phase 4 Writer Loop、Phase 5 Finalization、真实 Provider、产品数据库与内容质量仍未就绪。
- 规格与质量审查均为 `Critical/Important/Minor = 0/0/0`；详细证据：
  `docs/acceptance/2026-07-30-phase-3-story-planning.md` 与
  `docs/acceptance/2026-07-31-phase-3-immutable-boundary-alignment.md`。

## 2026-08-09 Phase 4B3 Selection Tools / One-step Undo 完成

- 分支：`codex/phase3d-boundary-acceptance`；功能代码验收快照：`caaeace`；源码 Schema：
  `writer-core-v1.10.0`。
- 交付同一纯文本编辑器中的精确选区 AI 改写、润色、扩写、缩写、独立 replacement
  preview、局部取消保留原稿，以及最近一次未被触碰结果的一步追加式撤销。
- 后端在任何 provider 副作用前验证 revision/hash、Unicode scalar range 与 selected-text
  hash；完成时短事务重校验 fence/CAS，只替换目标范围并返回完整权威 WorkingDraft。
- 没有新增表或列、同步 AI 旁路、scheduler 扩展、candidate/fusion、Canon 或 finalization
  行为；Schema 只扩展既有 CHECK 枚举。
- Fresh slice gates：Python/API `312 passed`，Node `190/190 passed`，Vite build
  `2966 modules transformed`，affected MySQL `75 passed` 且 `75/75/0`，UI-only browser
  `1/1 passed`。
- 最终资源账本：owned process、开发端口、Phase4B3 temp、Vite `deps_temp`、test DB
  均为 `0`；Real Provider calls `0`；Product DB reads/writes `0/0`。
- 规格与质量审查均为 `Critical/Important/Minor = 0/0/0`；详细证据：
  `docs/acceptance/2026-08-09-phase-4b3-selection-tools-undo.md`。
- 本切片按精简风险门禁验收；完整 unit、364 项 MySQL、历史 Phase 4 browser 和 release
  matrix 延期到 Phase 4 收口串行运行一次。
- Full-draft rewrite、candidate load/compare/fusion、finalization、Canon projection、
  download/export、real-provider quality 与 product-database readiness 仍未验收。

## 2026-08-09 Phase 4C Candidate Load / Read-only Compare 完成

- 分支：`codex/phase3d-boundary-acceptance`；功能代码验收快照：`05491f2`；源码 Schema：
  `writer-core-v1.11.0`。
- 交付严格 CAS 的 immutable Candidate load、同事务 before/update/after recovery，以及最多两份
  Candidate 的紧凑只读并排比较。
- 载入前 flush 可见编辑，client 只采用身份/content/hash/revision 全部校准的完整 server
  workspace；迟到响应、错误 owner、过期 CAS、活跃 operation 与损坏 Candidate 均不能写回。
- 没有 Candidate fusion、全文 AI 改写、通用 recovery browser、第二编辑器、Canon 写入或
  finalization 行为；browser 不启动 Provider。
- Fresh slice gates：Python/API/schema `230 passed`，Node `118/118 passed`，Vite build
  `2966 modules transformed`，affected MySQL `1 passed` 且 `1/1/0`，UI-only browser
  `1/1 passed`。
- 最终资源账本：owned process/listener、Phase4C temp、pytest temp、Vite `deps_temp`、test DB
  均为 `0`；Real Provider calls `0`；Product DB reads/writes `0/0`。
- 规格与质量审查均为 `Critical/Important/Minor = 0/0/0`；详细证据：
  `docs/acceptance/2026-08-09-phase-4c-candidate-load-compare.md`。
- 本切片按精简风险门禁验收；完整 unit/integration、历史 Phase 4 browser 与 release matrix
  延期到 Phase 4 close 串行运行一次。

## 下一步

唯一下一步是 Phase 4 close 的完整串行回归与阶段事实收口；AI fusion、full-draft rewrite、
真实 Provider、产品数据库和 live 网站继续延期。
