# Phase 3C Story Blocks and Chapter Outlines 设计

> **2026-07-31 precedence notice:** Where this document permits replacing a
> confirmed Seed/Bible, treats a drafting ChapterSession as an Outline freeze,
> or invalidates an adopted Outline merely because Planning Head advances,
> `docs/superpowers/specs/2026-07-31-immutable-boundaries-revision-design.md`
> takes precedence.

> 状态：方案 B 已批准；书面规格待作者复核。
>
> 基线：`main@59d80d739ef39a09bcd54e1888e4e4da90a98fa3`。
>
> 交付分支：`codex/phase3c-story-blocks-outlines`。

## 1. 目标

Phase 3C 在 Phase 3B 的唯一 Planning 链上完成三个连续纵向切片：

1. StoryBlock、Stage、SceneTask 的正式编辑与 Planning 完整确认；
2. ChapterOutline 的手工 Draft、AI 草稿、确认和不可变历史；
3. 服务端权威章节号、ChapterSession 精确钉住与可靠写作入口。

作者完成本阶段后，可以从已确认圣经开始建立完整未来规划，确认下一章小纲，再沿
项目中心提供的唯一入口创建对应 ChapterSession。整个过程不依赖浏览器推导章节号，
不建立第二套 Planning/Outline/Session 权威。

## 2. 不在本阶段

Phase 3C 不实现：

- Future Plan 与 Actual Progress 的 Canon/Projection 组合视图；该能力属于 Phase 3D；
- 正式三栏写作台、正文流式生成、改写、扩写、压缩、候选对比或融合；
- AI 味、冲突和内容质量审核；
- `FinalizationChangeSet`、Canon 写入、Projection 推进或原子定稿；
- 产品数据库重建、真实 Provider 调用或《典镇山河》内容质量验收；
- 旧数据库迁移、旧 API/Store/页面兼容或隐藏 fallback。

现有 `ChapterWriterView` 只接入权威 Outline、Session 创建和只读小纲摘要，不在
Phase 3C 扩建为正式 Phase 4 写作台。

## 3. 总体架构

Phase 3C 继续使用一个项目级 Planning aggregate 和一条正式链：

```text
ProjectPlanningView
  -> PlanningWorkspace
  -> planningStore
  -> planning / chapter-outlines API
  -> PlanningService / ChapterOutlineService
  -> PlanningRepository / ChapterOutlineRepository
  -> writer-core-v1.5.0 tables
```

Session 仍由独立但唯一的正式写作链创建：

```text
server-authoritative chapter entry
  -> confirmed current ChapterOutline
  -> ChapterSessionService
  -> chapter_sessions / working_drafts
```

以下边界冻结：

- 不新增 `planningV2Store`、`storyBlockStore` 或 `chapterOutlineStore`；
- 不新增 `PlanningWorkspaceV2`、独立 Outline 页面或 archived duplicate；
- 不恢复 `writerStore`、旧 StoryBlock 面板、`/planning/initial` 或旧可变 Planning 表；
- `chapterSessionStore` 只拥有 Session、WorkingDraft 和 Candidate，不复制 Planning
  或 Outline 权威；
- `writer-core-v1.5.0` Schema 保持不变；现有 Outline/Session 表已经足够；
- 单项目活动 Session 唯一性由项目行锁、正式 repository 查询和同一事务中的
  create-or-replay 共同保证，不增加兼容 DDL。

## 4. 交付切片

### 4.1 Slice 1：Story Blocks

新增第三个 canonical route：

```text
/projects/:projectId/planning/story-blocks
```

该路由继续挂载 `ProjectPlanningView` 和同一个 `PlanningWorkspace`。三个 Planning
tab 共享同一项目、同一活动 Draft、同一未保存状态和同一历史。

Story Blocks 工作区允许作者：

- 新增、编辑、排序、退役 StoryBlock；
- 为 StoryBlock 选择一个活动 Volume 和一个或多个活动 Plot；
- 编辑进入局面、块目标、主要压力、预期变化、未解决问题和参与人物；
- 新增、编辑、排序、退役 Stage；
- 新增、编辑、排序、退役 SceneTask；
- 选择唯一 `activeStoryBlockId`；
- 删除本次 Draft 新增且从未确认的节点，并提供本地撤销；
- 将已进入历史 revision 的节点改为 `retired`，不得物理删除或重新激活。

StoryBlock、Stage、SceneTask 不显示也不保存：

- 目标章节数；
- “本章必须完成”；
- `completed`；
- 手工实际进度；
- 文风或 AI 味规则清单。

完整 Planning 确认继续使用 Phase 3A 的闭合领域校验。Volume/Plot-only Draft 可以
保存，但只有 StoryBlock、Stage、SceneTask、引用关系和活动焦点全部合法时才可确认。

### 4.2 Slice 2：Chapter Outlines

ChapterOutline 是 Planning 下的独立 revision 实体，但前端状态仍作为
`planningStore` 的 outline 子状态管理：

- authoritative outline entry；
- current Draft 与本地编辑；
- immutable history/detail；
- saving/confirming；
- generation operation、未知结果核对和 authority reload；
- outline error 与恢复动作。

Outline 工作区位于“故事块”页面下半区，不增加第四个规划 tab 或 `/outlines`
前端路由。

作者可编辑：

- 当前 Volume、StoryBlock、Stage 和 SceneTask 引用；
- 本章目标；
- 预计出场人物；
- 承接的未完成情节；
- 计划推进的任务；
- 主要场景；
- 明确不应提前发生的内容。

作者不可编辑：

- authoritative chapter number；
- Planning revision/id/hash；
- Canon/Projection revision/hash；
- 节点正式 ID/revision/hash；
- 从已确认 Creation Contract 读取的目标字数和安全上限。

节点选择器只展示当前 Planning Head 中的活动节点。浏览器提交选择结果时携带服务端
返回的精确引用作为并发断言，后端仍重新读取并验证当前权威。

### 4.3 Slice 3：权威章节与 Session

服务端计算唯一 `authoritativeChapterNumber`：

1. 若存在活动非 final ChapterSession，使用该 Session 的章节号；
2. 否则使用最大 `final_chapters.chapter_num + 1`；
3. 若没有活动 Session 和定稿章节，使用第 1 章。

所有正式创建路径先锁项目行，再查询活动 Session，因此并发创建不能产生两个不同
章节的活动 Session。

项目中心下一步按以下 Phase 3 部分执行：

```text
active Session
  -> continue_writing

current Planning Draft
  -> continue_planning

no current Planning Head
  -> establish_planning

no current confirmed Outline for authoritative chapter
  -> prepare_chapter_outline

active Outline Draft
  -> continue_chapter_outline

current confirmed Outline and no Session
  -> start_chapter_session
```

上述 next action 均携带服务端生成的 canonical target path。浏览器不得从
`projects.current_chapter`、项目卡缓存、最大列表项或当前 URL 自行加一。

错误章节 URL 不静默跳转或打开另一章。页面显示固定 Conflict/Not Found，并提供
“前往第 N 章”的显式链接。

## 5. ChapterOutline 权威

### 5.1 Outline Draft basis

每个项目、权威章节号最多一份活动 Outline Draft。创建 Draft 时，后端在事务中冻结：

- 当前 Planning revision ID/revision/hash；
- 当前 Canon revision；
- 当前 Projection revision/hash；
- 当前活动 StoryBlock 及允许引用的 Volume/Stage/SceneTask；
- Creation Contract 的容量政策；
- 当前 Outline Head revision。

浏览器不能覆盖 basis。Planning、Canon、Projection 或章节号变化后，旧 Draft
只能读取为 `superseded`，不能静默 rebase。

### 5.2 保存

保存使用 `draftRevision + contentHash` CAS：

- 成功时原子推进 Draft revision；
- CAS 冲突保留浏览器本地输入；
- 网络结果未知时先 GET 权威 Draft，比较 revision/hash，不盲目重复 PUT；
- 每次键入不建立 revision；
- 普通保存只显示 Toast，不增加确认弹窗。

### 5.3 确认

Outline 确认在一个短事务内：

1. 锁项目与权威章节；
2. 锁当前 Planning Head、Canon/Projection Head；
3. 锁对应 Outline Head、活动 Draft 和 confirmation request；
4. 重验 Draft basis、节点引用、内容 hash 和幂等请求指纹；
5. 写入不可变 Outline Revision；
6. CAS 推进该章节 Outline Head；
7. 退出活动 Draft；
8. 完成幂等请求。

失败完整回滚，Draft 保持可编辑。相同幂等键与相同指纹返回首次结果；同键不同指纹
返回固定冲突。

### 5.4 历史状态

公共 Outline history 使用后端派生状态：

- `current`：仍匹配当前章节、Planning、Canon 和 Projection 权威；
- `superseded`：basis 已漂移且未被活动 Session 使用；
- `session_pinned`：已被活动或历史 Session 精确引用，即使 Planning Head 已推进；
- `archived`：项目已归档。

`session_pinned` Outline、对应 Planning revision、WorkingDraft 和 Candidate 保持
可读，不因未来 Planning 调整而重写。没有 Session 的 superseded Outline 只能基于
最新权威重新建立 Draft。

## 6. Outline AI

Outline AI 继续使用项目 `planning` 任务模型绑定，不增加新任务键。

正式链为：

```text
reserve transaction
  -> close transaction
  -> ChapterOutlineProvider gateway
  -> publish transaction
  -> exact Draft CAS load or superseded evidence
```

冻结的 safe manifest 至少包含：

- authoritative chapter number；
- 当前 Planning/Canon/Projection identity；
- 当前活动 StoryBlock 及可引用的 Stage/SceneTask；
- Volume/Plot 方向；
- Creation Contract 容量政策；
- 当前 Outline Draft revision/hash；
- author instructions；
- binding revision/hash 与公开模型身份。

manifest 在 hash、持久化和 gateway 调用前执行确定性大小预算与秘密扫描。API、日志、
错误、报告和浏览器 artifact 不返回 manifest、prompt、raw Provider output、语料
原文、API key、Authorization header、密码或 DSN。

每个 Outline Draft 最多一个 pending operation。operation 使用项目级幂等键、请求
指纹、租约和单调 fencing token。指纹在锁定 authority 后生成，覆盖完整 basis、
Draft、binding 和生成参数。

终态语义统一为：

- 结果合法且精确载入原 Draft：`succeeded, loaded=true`；
- Provider/解析失败：`failed`；
- Draft、Planning、Canon、Projection、章节号、binding、lifecycle、lease 或 fence
  漂移：`superseded`；
- 网络结果未知：浏览器按 idempotency key/operation ID GET，不发第二次 POST。

AI 不确认 Outline、不创建 Session、不写 Canon，也不持有跨 Provider 调用的数据库
事务。

Phase 3B Planning generation 中因 authority drift 仍返回
`succeeded, loaded=false` 的旧终态要在本阶段统一为 `superseded`，避免 Planning
与 Outline 对同一语义产生两套状态。

## 7. 后端组件

新增：

- `backend/repositories/chapter_outlines.py`
- `backend/services/chapter_outlines.py`
- `backend/prompts/chapter_outline.py`
- `backend/gateways/chapter_outline_provider.py`
- `backend/services/chapter_outline_generation.py`
- `backend/routers/chapter_outlines.py`

复用：

- `backend/domain/planning.py`
- `backend/domain/chapter_outlines.py`
- `backend/repositories/planning.py`
- `backend/services/planning.py`
- `backend/services/chapter_sessions.py`
- `backend/services/project_lifecycle.py`

锁顺序固定为：

```text
project
-> active Session / final chapter authority
-> Planning Head
-> Canon / Projection Head
-> Outline Head
-> Outline Draft
-> confirmation request or generation attempt
```

所有正式路径使用相同顺序，避免 Outline confirm、Session create、Planning confirm
和项目归档之间形成锁反转。

## 8. 公共 API

新增 canonical API：

```text
GET  /api/projects/:projectId/chapter-outlines/current
GET  /api/projects/:projectId/chapter-outlines/:chapterNumber
GET  /api/projects/:projectId/chapter-outlines/:chapterNumber/history
POST /api/projects/:projectId/chapter-outlines/:chapterNumber/drafts
PUT  /api/projects/:projectId/chapter-outlines/:chapterNumber/drafts/:draftId
POST /api/projects/:projectId/chapter-outlines/:chapterNumber/drafts/:draftId/generate
GET  /api/projects/:projectId/chapter-outlines/operations/by-key/:idempotencyKey
GET  /api/projects/:projectId/chapter-outlines/operations/:operationId
POST /api/projects/:projectId/chapter-outlines/:chapterNumber/drafts/:draftId/confirm
```

`current` 和 `operations` 静态路由必须先于 `:chapterNumber` 动态路由注册，避免被
动态路由错误解析为章节号。

`current` 返回服务端权威章节号、项目生命周期、Planning/Canon/Projection readiness、
当前 Outline/Draft 摘要、Session 摘要、capabilities 和固定 reason codes。

公共请求使用 camelCase 闭合 DTO，`extra=forbid`。公共响应只返回 UI 必需字段和公开
模型摘要，不返回数据库 JSON、内部 attempt 字段或秘密。

现有 ChapterSession create body 中的 Planning/Outline/Canon pins继续作为浏览器
看到的 authority 断言；服务端重新读取 current Outline 和权威章节号，不能把这些
字段当作权威来源。

## 9. 前端组件与交互

新增：

- `StoryBlockEditor.vue`
- `ChapterOutlineWorkspace.vue`
- `ChapterOutlineHistoryDrawer.vue`
- 必要的无状态 controller/helper。

修改：

- `ProjectPlanningView.vue`：增加第三个 tab；
- `PlanningWorkspace.vue`：在 story-blocks tab 装配两个工作区；
- `planningStore.js`：增加 Outline 子状态，不新建 Store；
- `projectRoutes.js`、`productShell.js`：增加 canonical route/title/selected；
- `ProjectOverviewView.vue`：消费新的后端 next action；
- `ChapterWriterView.vue`：最小接入 current Outline、Session create 和只读摘要。

交互规则：

- 同项目三个 Planning tab 切换不提示、不 reload、不丢失 Planning/Outline 本地状态；
- 离开 Planning、切项目或 unload 时，把 Planning dirty、Outline dirty、临时
  instructions、活动 generation 和待核对 operation 合并成一次离开保护；
- Planning AI 只将 Planning 编辑区设为 inert；
- Outline AI 只将 Outline 编辑区设为 inert；
- Planning confirm、Outline confirm、Session create 使用现有全局 blocking overlay；
- archived/superseded 状态沿用同一组件只读展示；
- Canon/Projection 不同步时历史可读，Outline confirm 和 Session create 禁用；
- 未确认 Bible 时显示明确的“去确认创作圣经”恢复入口；
- 所有错误只显示固定安全分类，本地未保存内容不因失败清空。

## 10. 测试与验收

### 10.1 TDD 层级

每个纵向切片均按以下顺序：

1. 领域/repository/service RED；
2. API/Store/controller RED；
3. 最小生产实现；
4. focused GREEN；
5. Disposable MySQL integration；
6. 独立规格审查至 `0/0/0`；
7. 独立质量审查至 `0/0/0`。

### 10.2 正式浏览器门禁

新增唯一入口：

```text
npm run test:browser:phase3c
```

正式 Playwright 至少覆盖：

1. 模型未就绪时手工 StoryBlock → Planning confirm → Outline confirm → Session；
2. Outline AI 只载入未漂移 Draft，未知结果只 GET 核对；
3. Planning R2 使无 Session 的旧 Outline superseded；
4. 已有 Session 时旧 Planning/Outline pins 保持可用；
5. 项目中心、直接 URL 和写作入口使用同一权威章节号；
6. archived、上游缺失、Canon/Projection 不同步和错误 URL；
7. refresh/back/forward 与三个 canonical Planning route；
8. 公共响应、日志和 artifact 秘密扫描。

浏览器 spec 禁止：

- `page.request`
- `page.route`
- `page.evaluate`
- 浏览器 `fetch`
- Axios
- 直接调用 API client、Pinia action 或数据库完成产品动作。

fake 只替换外部 Planning/Outline Provider gateway。Router、Service、Repository、
API、Store、Controller、组件和 Session 链保持正式产品实现。

runner 继续使用随机 Disposable MySQL 8、loopback 随机端口、scheduler off、严格
外部网络 fail-closed、反向 owned-resource cleanup，并证明：

- database `created=cleaned`、`remaining=0`；
- process/port/temp root/Vite cache residue 为 `0`；
- Real Provider calls 为 `0`；
- Product DB reads/writes 为 `0/0`；
- Live website access 为 `0`；
- secret scan findings 为 `0`。

## 11. 完成边界

Phase 3C 完成只证明：

- 作者能通过正式 UI 建立并确认完整 Planning；
- 作者能手工或显式用 AI 建立可编辑 Outline Draft；
- Outline revision/history、supersession 和 Session pin 可靠；
- 服务端权威章节号贯穿项目中心、Outline、Session 和写作入口；
- 无 Outline、错误章节或不同步 Canon/Projection 时 fail closed。

Phase 3C 不授予 Phase 3D、Phase 4 Writer Loop、Phase 5 Finalization、Real
Provider、Product DB 或 Content Quality Ready。
