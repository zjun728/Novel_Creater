# Phase 3 故事规划设计

> **2026-07-31 precedence notice:** Where this document permits replacing a
> confirmed Seed/Bible, treats a drafting ChapterSession as an Outline freeze,
> or invalidates an adopted Outline merely because Planning Head advances,
> `docs/superpowers/specs/2026-07-31-immutable-boundaries-revision-design.md`
> takes precedence.

> 状态：作者已确认总体方案；本文冻结 Phase 3 的领域边界、数据权威、
> 页面入口和验收范围，供详细实施计划与代码审查使用。

## 1. 目标与权威

Phase 3 建立从已确认创作圣经到可确认章节小纲的正式故事规划链：

```text
当前 Seed Selection
  -> 已确认 Creation Contract
  -> 已确认 Creation Bible
  -> 当前 Planning Revision
  -> 已确认 Chapter Outline Revision
  -> 下一阶段的 Chapter Session
```

产品最高权威仍是
`docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`。
本文只细化其中的 Phase 3，不改变已经确认的产品目标。

Phase 3 必须让作者能够：

- 规划分卷、跨块情节线、故事块、阶段和场景任务；
- 让一个故事块和其中阶段自然跨越任意数量章节；
- 手工建立规划，或显式要求 AI 生成一份可编辑草稿；
- 在确认前完整编辑，在确认后保留不可变历史 revision；
- 为下一章建立、编辑并确认小纲；
- 清楚区分“未来准备怎么写”和“正文已经发生了什么”；
- 从项目中心沿唯一下一步进入规划或写作，不依赖手敲 URL。

Phase 3 不授予写作闭环、原子定稿、真实 Provider、产品数据库或内容质量
Ready。

## 2. 不采用的方案

### 2.1 继续扩展现有可变 Planning 表

现有 `volume_plans/story_blocks/story_stages/scene_tasks` 只支持一份确定性初始
规划，缺少 Plot、活动草稿、不可变历史和 ChapterOutline。继续给这些行增加
状态会让“未来计划状态”和“实际完成状态”混在同一套字段中，因此不采用。

### 2.2 为每个规划节点建立独立活动 Head

Volume、Plot、StoryBlock、Stage 和 SceneTask 如果分别推进 Head，作者一次确认
就可能得到跨表不一致的组合，后续 ChapterSession 也无法钉住一份完整依据。因此
不采用多个独立权威 Head。

### 2.3 采用单一 Planning Aggregate

Phase 3 采用一个项目级 Planning aggregate：

- 编辑时只有一份活动 Planning Draft；
- 确认时冻结完整 Planning Revision；
- 项目只有一个 Planning Head；
- aggregate 内每个节点使用稳定 ID、局部 revision 和内容 hash；
- ChapterOutline 与后续 ChapterSession 钉住完整 Planning revision/hash，并
  同时记录本章实际引用的节点 ID、revision 和 hash。

这种设计用一个原子 Head 保证全局一致性，同时避免多个模块各自维护一套完成状态。

稳定节点身份遵循以下闭合规则：

- 新节点只提交一次请求内有效的 `clientNodeKey`；首次保存时由服务端分配稳定 ID，
  浏览器不能指定正式 ID；
- 稳定 ID 在一个项目的全部历史中永不复用；
- 节点规范内容 hash 未变化时保留原局部 revision；
- 节点内容、顺序、父级关系或 `active -> retired` 发生变化时，局部 revision
  精确增加一；
- 已确认节点一旦 retired，不得以同一 ID 重新 active；作者决定恢复相似规划时
  创建新 ID，并保留旧节点历史；
- 仅存在于尚未确认 Draft、从未进入任何 Planning Revision 的新增节点可以物理
  移除。

## 3. 领域层级

### 3.1 Volume

`Volume` 表示一卷的宏观叙事方向和阶段承诺，包含：

- 稳定 ID、显示顺序和标题；
- 本卷核心变化、主要压力、人物群像重点；
- 明确禁止提前发生的内容。

Volume 不保存目标章节数。目标总字数和章节容量来自已确认创作契约；分卷只表达
叙事方向。Volume 不反向保存 Plot 或 StoryBlock ID；一卷包含哪些故事块，以及
这些故事块推进哪些情节线，统一从 StoryBlock 的 `volumeId/plotIds` 派生。

### 3.2 Plot

`Plot` 是可以跨 Volume 或 StoryBlock 延续的情节线，职责区别于 StoryBlock：

- Plot 回答“哪条矛盾、人物关系或长期问题正在发展”；
- StoryBlock 回答“接下来用哪一段连续剧情实际推动它”。

Plot 具有稳定 ID、标题、类型、故事问题、当前未来方向、预期回报和相关角色说明。
V1 类型为：

- `main`：主线；
- `character`：人物成长或人物选择线；
- `relationship`：人物关系线；
- `conflict`：阵营、对手或资源冲突线；
- `mystery`：秘密、伏笔或认知差线；
- `other`：作者自定义情节线。

类型只用于组织和筛选，不改变生成逻辑。一个 StoryBlock 可以推进多个 Plot，一个
Plot 也可以跨多个 StoryBlock。Plot 不反向保存 StoryBlock ID，Plot 详情中的关联
故事块由 StoryBlock 的 `plotIds` 派生。

### 3.3 StoryBlock

`StoryBlock` 是一段可以滚动推进的完整连续剧情，归属一个 Volume，并关联一个或
多个 Plot。它包含：

- 稳定 ID、显示顺序和标题；
- 进入局面、块目标、主要阻力、预期变化和未解决问题；
- 参与人物与关联 Plot；
- 有序 Stage；
- 每个 Stage 下的有序 SceneTask。

StoryBlock、Stage 和 SceneTask 均不得保存目标章节数或“本章必须完成”规则。
SceneTask 只描述要发生的具体情节任务及完成证据，不把文风规则写成任务清单。

Planning 中的 `activeStoryBlockId` 只表示作者当前准备推进的未来计划焦点，不表示
该块已经发生或完成。

### 3.4 ChapterOutline

`ChapterOutline` 是独立于 Planning aggregate 的带 revision 实体。它至少包含：

- 章节号；
- 固定的 Planning revision/hash；
- 当前 Volume、StoryBlock、Stage 和 SceneTask 的稳定 ID、revision、hash；
- 本章目标；
- 预计出场人物；
- 承接的未完成情节；
- 计划推进的任务；
- 主要场景；
- 明确不应提前发生的内容；
- 从创作契约读取的目标字数与安全上限。

小纲可以手工建立，也可以由 AI 生成草稿。只有作者确认的 revision 才能创建
ChapterSession。建立新版小纲不会删除或静默改变钉住旧 revision 的工作稿和候选。

## 4. 唯一事实源与规划边界

Planning 只保存未来计划。它不能保存正文已经完成了哪些 Stage 或 SceneTask。

实际完成状态遵循以下唯一方向：

```text
已定稿正文
  -> Phase 5 单次 FinalizationChangeSet 提取
  -> 作者整体确认
  -> Canon Event
  -> 确定性 Projection
  -> Planning 页面中的只读实际进度
```

Phase 3 不实现 Canon 写入口，不提供“标记已完成”“手工同步记忆”或“修正故事块
完成状态”等旁路。Phase 3 的 Planning API 只返回：

- `futurePlan`：当前 Planning Head 指向的可调整未来设计；
- `actualProgress`：同一 Canon/Projection revision 上已有的只读事实；没有事实时
  返回空集合，而不是把未来计划伪装成已经发生；
- `canonProjectionStatus`：Canon head、Projection head 及是否同步。

在 Phase 5 接入前，正式新项目的 `actualProgress` 可以为空。接口与 UI 必须如实
显示“尚无已定稿事实”。

Planning 节点不得使用 `completed` 表示计划生命周期。未来计划节点只允许
`active` 或 `retired`：

- `active`：仍属于当前未来设计；
- `retired`：作者在新 Planning revision 中不再准备推进，但历史引用仍可读取。

未来调整不能物理删除已经被确认小纲、ChapterSession、候选或定稿记录引用的稳定
节点。

## 5. 修订与事务

### 5.1 Planning Draft

每个项目最多一份活动 Planning Draft。Draft 固定以下服务端依据：

- Seed selection revision；
- Seed revision/hash；
- Creation Contract revision/id/hash；
- Style Contract revision/id/hash；
- Creation Bible revision/id/hash。

浏览器只提交作者可编辑的规划内容、当前 draft revision 和幂等键，不能提交或覆盖
上述依据。

Provider、模型和 `planning` binding revision/hash 不属于手工 Planning Draft 的
固定依据。它们记录在每次 generation attempt；只有作者明确把该 attempt 结果载入
Draft 时，Draft provenance 才记录 attempt ID 和公开模型摘要。后续手工编辑不改变
该 attempt 历史，也不会把模型身份伪装成当前规划依据。

首次创建 Draft 使用空白但合法的规划结构，并从契约读取容量政策。不得再生成
《典镇山河》专用的硬编码 Volume、典籍知识情节或角色名。作者可以直接手工填写，
也可以显式点击 AI 生成规划草稿。

保存 Draft 使用 CAS：

- 相同 revision 的一次保存原子推进 revision；
- revision 漂移返回固定冲突，保留浏览器未保存内容；
- 每次输入不建立正式 Planning Revision；
- 归档项目或上游依据 superseded 时统一拒绝写入。

### 5.2 Planning Confirmation

确认命令在一个数据库事务内：

1. 锁定活动项目、当前 selection、contract、bible、Planning head 和 Draft；
2. 重新验证全部依据、draft revision 和内容 hash；
3. 验证完整规划闭合 schema、稳定 ID 唯一性、父子引用和 Plot 关联；
4. 写入不可变 Planning Revision；
5. 推进唯一 Project Planning Head；
6. 将活动 Draft 退出活动状态；
7. 写入确认幂等结果。

任何一步失败都完整回滚，原 Draft 保持可编辑。相同幂等键和相同请求指纹返回首次
结果；同键不同指纹返回冲突。

后续“调整未来规划”从当前 Head 克隆新的活动 Draft。历史 Revision 不可覆盖。

### 5.3 ChapterOutline

每个项目、章节号最多一份活动 Outline Draft。Draft 固定当前 Planning revision/
hash、Canon/Projection revision 和所引用规划节点。

确认命令在一个事务内冻结 Outline Revision、推进该章节 Outline Head、退出活动
Draft 并保存幂等结果。确认前任一 Planning、Canon 或 Projection baseline 漂移都
使请求冲突，不自动把旧小纲转换到新依据。

Planning Head 推进后：

- 尚未创建 ChapterSession 的已确认 Outline 立即成为只读 superseded，项目下一步
  回到“准备下一章小纲”；
- 已经创建 ChapterSession 的 Outline、WorkingDraft 和候选继续钉住原 Planning/
  Outline revision，不被重写或失效；项目下一步仍优先“继续写作”；
- 当前活动 Session 结束后，下一章必须使用当时最新 Planning Head 重新建立 Outline；
- 服务端权威章节号优先取活动非 final ChapterSession 的章节号；没有活动 Session
  时取最大已定稿章节号加一；两者都不存在时为第一章。浏览器不得自行递增或使用
  项目列表中的缓存数字替代。

## 6. AI 操作边界

AI 生成规划和小纲只产生 Draft，不产生正式 Revision，不修改 Canon，也不自动进入
写作。

所有调用必须：

- 从后端正式 AI gateway 发起；
- 使用项目 `planning` 任务的实际模型绑定；
- 在调用前事务中读取并冻结输入 manifest，然后关闭事务；
- Provider 调用期间不持有数据库事务；
- 返回后在短事务中重新验证 operation ID、draft revision/hash、上游依据和项目
  lifecycle；
- 旧结果只能保存为 attempt 证据，不能覆盖较新的作者输入；
- 通过闭合 schema 校验后才可载入 Draft；
- 不向 API、日志、浏览器 artifact 或错误输出 prompt、raw Provider 响应、语料
  原文或秘密。

每个 Planning Draft 或 Outline Draft 最多只有一个活动 generation operation。
operation 使用服务端 operation ID、幂等键和请求指纹；指纹固定项目、Draft
revision/hash、全部上游 basis、模型绑定 revision/hash 和生成参数。同键同指纹返回
首次 operation，同键不同指纹冲突。新 operation 取得单调 fencing token，旧结果
只能作为 superseded attempt 保留。

网络结果未知时，浏览器必须按 operation ID 查询状态，不能直接重新生成。公开状态
只返回 `pending/succeeded/failed/superseded`、固定失败 code、可安全展示的模型摘要
和结果是否已载入 Draft，不返回输入 manifest、prompt 或 raw output。

没有可用模型时，“AI 生成”显示明确恢复入口；手工建立、保存和确认规划始终可用。
自动验收只在外部 gateway 边界使用严格 fake，不访问真实 Provider。

## 7. Schema 目标

Phase 3 在空库 manifest 中一次性建立新 schema，不迁移旧数据，也不保留旧表兼容
查询。目标版本在详细实施计划中固定为 `writer-core-v1.5.0`。

`30_planning.sql` 使用：

- `planning_drafts`；
- `planning_generation_attempts`；
- `planning_revisions`；
- `project_planning_heads`；
- `planning_confirmation_requests`；
- `chapter_outline_drafts`；
- `chapter_outline_generation_attempts`；
- `chapter_outline_revisions`；
- `project_chapter_outline_heads`；
- `chapter_outline_confirmation_requests`。

Planning Revision 的 `content_json` 是完整规范 aggregate；其中每个节点有稳定 ID、
局部 revision 和内容 hash。数据库 Head 与 revision/hash 形成唯一权威。

`40_drafts.sql` 中的 ChapterSession 改为钉住：

- Planning revision ID/revision/hash；
- StoryBlock ID/revision/hash；
- ChapterOutline revision ID/revision/hash；
- expected Canon revision。

旧 `volume_plans/story_blocks/story_stages/scene_tasks` 表和
`expected_story_block_revision` 直接引用不再保留。没有旧库迁移或 runtime fallback。

## 8. 后端职责

正式后端只保留一条 Planning 链：

```text
planning router
  -> PlanningService
  -> PlanningRepository
  -> Planning aggregate tables
```

职责拆分：

- `PlanningDomain`：闭合 schema、稳定 ID、父子引用、节点 hash 和 aggregate hash；
- `PlanningService`：Draft、AI attempt、确认、历史和 superseded/archived 围栏；
- `ChapterOutlineService`：小纲 Draft、AI attempt、确认和当前章节 Head；
- `PlanningReadService`：组合 Future Plan、只读实际进度和 Canon/Projection 同步状态；
- `ProjectLifecycleService`：计算唯一下一步；
- `ChapterSessionService`：只接受服务端当前且已确认的小纲 revision。

公共错误使用固定 code/message，不插入作者内容、SQL、Provider 输出或文件路径。

## 9. API 与路由

公共 API 至少覆盖：

```text
GET    /api/projects/:projectId/planning
GET    /api/projects/:projectId/planning/history
POST   /api/projects/:projectId/planning/drafts
PUT    /api/projects/:projectId/planning/drafts/:draftId
POST   /api/projects/:projectId/planning/drafts/:draftId/generate
GET    /api/projects/:projectId/planning/operations/:operationId
POST   /api/projects/:projectId/planning/drafts/:draftId/confirm

GET    /api/projects/:projectId/chapter-outlines/:chapterNumber
GET    /api/projects/:projectId/chapter-outlines/:chapterNumber/history
POST   /api/projects/:projectId/chapter-outlines/:chapterNumber/drafts
PUT    /api/projects/:projectId/chapter-outlines/:chapterNumber/drafts/:draftId
POST   /api/projects/:projectId/chapter-outlines/:chapterNumber/drafts/:draftId/generate
GET    /api/projects/:projectId/chapter-outlines/operations/:operationId
POST   /api/projects/:projectId/chapter-outlines/:chapterNumber/drafts/:draftId/confirm
```

前端正式路由使用主规格已经冻结的：

```text
/projects/:projectId/planning/volumes
/projects/:projectId/planning/plots
/projects/:projectId/planning/story-blocks
```

章节小纲放在 Story Blocks 页面中的“下一章小纲”工作区，并在写作台左栏复用只读
摘要，不新建第四个重复规划入口。

## 10. 前端与交互

Phase 3 继续使用唯一 `planningStore`，扩展它管理服务端 Planning authority、活动
Draft、历史和 Outline 子状态。不得新建 `planningV2Store` 或恢复旧 `writerStore`。

项目上下文导航增加：

- 分卷规划；
- 情节规划；
- 故事块。

未确认圣经时这些页面显示明确前置条件；已归档项目显示同一页面的只读历史，不创建
另一套 Archived 组件链。

三个页面共享同一 Planning revision：

- 分卷页编辑 Volume 与总体顺序；
- 情节页编辑跨块 Plot；
- 故事块页编辑 StoryBlock、Stage、SceneTask 和下一章小纲；
- 页面切换不自动确认、不丢失同一 Draft；
- 有未保存编辑时离开提供一次明确保护；
- AI 操作只遮罩当前规划工作区，作者可以查看其他只读模块；
- 确认期间使用一个全局阻断遮罩，防止重复提交；
- 普通保存成功只使用 Toast，不增加重复确认；
- 删除从已确认 revision 克隆来的 Draft 节点可从历史 revision 恢复；删除本次
  Draft 新增节点在保存前提供本地撤销，因此两者都不弹危险确认；
- 已被历史引用的节点只能在新 revision 中 retired，不能物理删除。

项目中心仍使用主规格冻结的完整服务端优先级，Phase 3 状态只插入对应位置，不建立
一份简化状态机：

1. 正在执行写入或定稿：查看当前操作；
2. Canon 与 Projection 不同步：重建状态视图；
3. 存在自动暂存失败的活动工作稿：返回写作台恢复正文；
4. 存在仍有效的活动 Session 或工作稿：继续写作；
5. 未选择种子：选择种子；
6. 未确认契约：继续创作契约；
7. 未确认圣经：继续创作圣经；
8. 没有当前 Planning Head：建立故事规划；
9. 存在当前 Planning Draft：继续故事规划；
10. 权威下一章没有当前确认小纲：准备下一章小纲；
11. 当前条件就绪：进入对应章节写作页。

项目库和项目中心的写作入口必须读取同一个服务端权威章节号。URL 章节号与服务端
ChapterSession/Outline 不一致时返回明确冲突或 Not Found，不静默打开另一章。

## 11. 删除与替换

Phase 3 纵向切片完成时同步删除：

- 硬编码《典镇山河》内容的 `create_initial_plan` 生产逻辑；
- 旧 `POST /planning/initial`；
- 旧可变 planning 表及其 ChapterSession FK；
- 任何把 Planning status 当作实际完成事实的代码；
- 任何未钉住 ChapterOutline 的章节会话创建路径；
- 已被新行为测试替代的源码正则合同。

可以保留 `planningStore`、正式后端 gateway、Canon/Projection 基础和通用 UI 组件，
但必须在同一正式链中改造，不允许保留隐藏路由、兼容 alias 或第二套状态源。
现有 `frontend/src/components/planning/PlanningWorkspace.vue` 明确在原路径就地重写为
三个 Phase 3 路由共用的唯一工作区；旧“创建确定性 initial plan”模板和事件处理从
该文件中删除，不再另建 `PlanningWorkspaceV2`。

## 12. 失败与恢复

- 上游 selection/contract/bible 改变：旧 Planning/Outline 全部只读
  `superseded`，不能重新激活；
- Planning Draft CAS 冲突：保留本地编辑，要求作者重新读取后决定；
- AI 超时或连接失败：保留当前 Draft，不创建空 Revision；
- AI 返回非法结构：记录固定失败分类，不把 raw 内容返回前端；
- 网络结果未知：按 operation/command ID 查询权威状态，不能直接发起第二次生成或
  确认；
- Canon/Projection 不同步：规划历史可读，Planning 确认、Outline 确认和
  ChapterSession 创建均拒绝；
- 项目归档：全部写入拒绝，历史规划与小纲可读；
- 任一确认步骤失败：完整回滚，Head 和 Draft 均不发生半更新。

## 13. 实施包

### Phase 3A：Planning Aggregate Foundation

- `writer-core-v1.5.0` schema；
- Planning/Outline 闭合领域模型；
- Planning Draft、确认、历史和上游 generation fence；
- 移除旧 initial-plan 硬编码与旧表权威；
- Disposable MySQL 原子性、CAS、幂等和回滚验证。

### Phase 3B：Volumes and Plots

- 手工与 AI Planning Draft；
- 分卷、情节线 API 和正式页面；
- 项目中心下一步与项目导航；
- archived/superseded 只读历史。

### Phase 3C：Story Blocks and Chapter Outlines

- StoryBlock、Stage、SceneTask 编辑；
- 小纲 Draft、AI 草稿、确认和历史；
- ChapterSession 钉住 Planning/Outline；
- 权威章节号与可靠写作入口。

### Phase 3D：Boundary and Acceptance

- Future Plan/Actual Progress/Canon Projection 同 revision 只读组合；
- 完整 Phase 3 UI-only Playwright；
- Python、Node、前端、Disposable MySQL、build、泄密扫描和资源清理门禁；
- Phase 3 验收报告和 main 集成。

每个包按 TDD 完成，先独立规格审查，再独立质量审查。共享 Schema、MySQL 和 build
门禁不得并行。

## 14. 验收标准

Phase 3 完成必须证明：

- 项目从已确认圣经进入规划，不再停在不可点击 Phase boundary；
- 作者能手工建立并确认 Volume、Plot、StoryBlock、Stage 和 SceneTask；
- 模型不可用时手工链仍可完成；
- AI 只生成 Draft，不能自动确认或修改 Canon；
- StoryBlock/Stage/SceneTask 没有目标章节数和强制每章完成规则；
- 一个 Plot 可跨多个 StoryBlock，一个 StoryBlock 可推进多个 Plot；
- Planning 只有一个项目 Head，一次确认不会产生跨模块半更新；
- 未来计划没有第二套权威“实际完成”状态；
- 无 Canon 事实时实际进度明确为空；
- 下一章小纲未确认时后端拒绝创建 ChapterSession；
- 新版小纲不改变钉住旧 revision 的历史工作；
- selection A→B→A 不复活旧 Planning 或 Outline；
- archived 项目所有规划写入均拒绝，历史可读；
- Canon/Projection 不同步时所有依赖写操作由后端拒绝；
- 项目中心、项目卡和直接 URL 使用同一个权威章节号；
- 浏览器自动验收只通过 UI 完成，不使用 API 旁路；
- fake gateway 只替换外部 Provider 边界；
- Disposable MySQL `created=cleaned`、`remaining=0`；
- API、错误、日志、截图和 artifact 的秘密泄漏扫描为零；
- 旧 Planning initial、旧可变完成状态和无 Outline 会话路径不可达且被物理删除。

## 15. 明确不在 Phase 3

- 正式三栏写作台、自动暂存、流式正文、改写、扩写、压缩、对比和融合；
- 质量审核与 AI 味审核；
- `FinalizationChangeSet` 提取；
- Canon 冲突确认和 Canon 写入；
- 原子定稿与故事块实际进度推进；
- 小说下载、项目备份和导入；
- 产品数据库重建；
- 真实 Provider 调用；
- 《典镇山河》正文内容质量验收。

这些能力分别保留在 Phase 4–7，Phase 3 不以 schema 占位或 fake 测试冒充已经完成。
