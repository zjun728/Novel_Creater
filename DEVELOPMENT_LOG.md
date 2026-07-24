# 开发日志

> 只记录当前有效的决策与证据摘要。日期：`2026-07-24`。不记录密钥、DSN、原始运行日志或本地截图。

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

## 下一步

按已批准设计和详细计划实施 Phase 3A Planning Aggregate Foundation。不得提前读写
产品数据库、调用真实 Provider，或将 Phase 4 Writer Loop、Phase 5 Finalization
和 Content Quality 标记为已完成。
