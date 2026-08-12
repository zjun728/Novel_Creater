# Novel Creator 不可变边界修订 V2

- 日期：2026-07-31
- 状态：作者已确认核心方案；待作者复核书面规格
- 适用范围：项目创作主链、Planning、Chapter Outline、ChapterSession、
  正文定稿、Canon 与 Projection
- 文档性质：对既有总体设计和 Phase 3 规格中冲突条款的优先修订

## 1. 修订目的

Novel Creator 必须同时满足三个要求：

1. AI 草稿和作者工作过程可以反复调整；
2. 已经确定的项目基线和已经定稿的历史不能漂移；
3. 长篇小说尚未实现的未来仍然可以根据实际写作结果调整。

本修订统一种子、创作契约、创作圣经、Planning、小纲、正文和 Canon 的
不可变边界，消除“确认后只读但仍可建立替代 revision”“Planning Head 推进后
已采用小纲自动失效”等互相冲突的旧规则。

## 2. 产品流程

项目采用单向、逐步完成的创作流程：

```text
创建项目
  -> 选择并确认种子
  -> 建立并确认创作契约
  -> 建立并确认创作圣经
  -> 建立未来 Planning
  -> 建立本章小纲
  -> 采用当前小纲进入写作
  -> 生成、编辑和保存候选正文
  -> 提取一次 FinalizationChangeSet
  -> 作者整体确认
  -> 最终小纲、正文、Canon 与 Projection 原子定稿
  -> 进入下一章
```

正式下游写入必须由服务端验证上一步已完成。直接 URL、浏览器缓存状态或客户端
提交的上游身份都不能绕过该顺序。

## 3. 核心不变量

### 3.1 项目基线永久不变

- 已确认种子是项目唯一故事起点；
- 已确认创作契约是项目唯一创作约束；
- 已确认创作圣经是项目唯一初始世界和角色基线；
- 三者确认后均不可编辑、切换或建立替代正式 revision；
- Provider、模型和运行时绑定可以更换，但不能改变已确认内容。

### 3.2 小纲随正文共同定稿

- 正文未定稿前，小纲是当前章节的可调整写作依据；
- 作者可以修改、重新生成或重新采用小纲；
- 已有工作稿和候选不会因小纲调整而删除；
- 绑定旧小纲 revision 的候选不能直接正式定稿；
- 作者必须基于当前小纲重新保存候选；
- 正文正式定稿时，当前小纲与正文在同一事务中冻结；
- 正文定稿后，该章小纲永久不可修改、替换或删除。

### 3.3 已发生事实与未来计划分离

- Canon 只保存已定稿正文产生的事实；
- Planning 只保存尚未发生的未来计划；
- 已实现的 Planning 路径不可修改；
- 未承诺、未实现的未来子树仍可调整；
- 历史问题只能通过同一项目的未来内容承接；
- 不提供历史重开、Canon 回滚或项目分支。

### 3.4 服务端是唯一锁定裁决者

- 浏览器只展示服务端派生的能力和锁定原因；
- 浏览器不能提交 `locked`、`completed` 或事实进度；
- 所有正式写操作都必须在事务中重新读取当前权威；
- 锁定状态不能依赖前端禁用按钮。

## 4. 术语

### 4.1 Draft

尚未形成正式历史的可编辑工作状态。Draft 可以保存、修改、重新生成或替换。

### 4.2 Confirmed Baseline

作者已最终确认的种子、创作契约或创作圣经。确认后永久不可变。

### 4.3 Planning Revision

一次已确认的完整未来规划快照。Revision 本身不可覆盖，但作者可以从当前 Head
建立新 Draft，只调整尚未锁定的未来内容。

### 4.4 Active Outline

当前章节正在采用的写作小纲。正文未定稿前可以调整，并以新 revision 推进
Outline Head。

### 4.5 Final Outline

与定稿正文在同一事务中冻结的小纲。它是该章永久写作依据，不再允许修改。

### 4.6 Commitment Lock

作者对项目基线作出不可逆确认，或已定稿章节对其最终小纲和规划依据作出正式
承诺所形成的锁。

### 4.7 Fact Lock

正文定稿并写入 Canon 后形成的永久事实锁。Fact Lock 覆盖正文、Canon Event、
实际实现的 Planning 路径和相应 Projection。

### 4.8 Dependency Evidence

Outline、Session、WorkingDraft、Candidate 或 FinalizationRecord 对精确 revision
的引用证据。它不是第三套可编辑生命周期，也不独立决定事实；服务端使用它解释
锁定原因和验证来源。

### 4.9 Retired

作者在新 Planning Revision 中不再准备推进的未来节点。只有未承诺、未实现节点
可以 retired。`retired` 不表示正文已经完成或放弃了某个情节。

## 5. 不可变矩阵

| 对象 | 正式锁定前 | 正式锁定后 |
| --- | --- | --- |
| 种子候选 | 可新增、编辑、删除、重新生成 | 未选且未引用候选仍可清理 |
| 已确认种子 | 确认前可比较候选 | 项目永久基线 |
| 创作契约草稿 | 可编辑、重新生成 | 确认后永久只读 |
| 创作圣经草稿 | 可编辑、重新生成 | 确认后永久只读 |
| Planning Draft | 可编辑未来内容 | 确认后形成不可变 Revision |
| 未锁定 Planning 节点 | 可修改、移动、retire | 被最终章节实现后永久锁定 |
| 小纲草稿或活动小纲 | 正文未定稿前可调整 | 随正文定稿后永久锁定 |
| WorkingDraft | 可编辑、重新生成 | 不单独成为正式事实 |
| Candidate | 可保留多个精确依据版本 | 只有被定稿的 Candidate 成为历史依据 |
| 定稿正文 | 定稿前可形成新 Candidate | 定稿后永久只读 |
| Canon Event | 不接受浏览器直接写入 | 只追加、不覆盖、不删除 |
| Projection | 不接受人工编辑 | 从 Canon 确定性重建 |

## 6. 种子、创作契约与创作圣经

### 6.1 种子

项目开始时可以创建和比较多个候选。正式动作是：

> 确认这个种子并进入创作契约

确认必须明确提示不可逆。成功后：

- 项目只有一个已确认种子；
- 不再提供切换种子的产品能力；
- 不存在 A -> B -> A selection generation；
- 下游生成失败只允许重试下游，不允许回退种子；
- 未引用候选可以清理，但已引用证据不能伪装成另一条活动创作链。

### 6.2 创作契约

确认前可以调整故事发动机、风格、容量、禁区和经验方法。确认后：

- 内容永久只读；
- 不允许建立“只影响未来”的新契约 revision；
- 全部 Planning、小纲和正文继续引用同一基线；
- 模型绑定变化只记录运行 provenance，不改变契约。

### 6.3 创作圣经

确认前可以手工编辑或使用 AI 生成工作稿。确认后：

- 内容永久只读；
- 不提供“调整未来设计”的圣经 revision；
- 后续人物、关系和世界变化由定稿正文进入 Canon；
- 对既有设定的新解释必须通过后续正文和 Canon 追加，不能回写圣经；
- 不建立独立 `Canon Correction Note` 作为第二事实源。

## 7. Planning 的可变边界

Planning 包含 Volume、Plot、StoryBlock、Stage 和 SceneTask。

### 7.1 Revision 规则

- 每个已确认 Planning Revision 永久不可变；
- 当前 Head 可以克隆为新的活动 Draft；
- 新 Draft 只能修改未被历史事实锁定的未来内容；
- 新 Head 不会重写旧 Revision；
- 历史 Outline、Session、Candidate 和 FinalizationRecord 继续钉住原 Revision。

### 7.2 三个派生约束维度

服务端按证据计算编辑能力，不在节点上保存浏览器可写的多个 `locked` 布尔值。

#### Identity Constraint

- 稳定 ID 一旦分配永不变化或复用；
- 节点类型不能改变；
- 已进入正式 Revision 的节点不能物理删除。

#### Core Content Constraint

节点被定稿章节实现后，以下核心内容不可覆盖：

- 标题；
- 初始目标；
- 核心冲突；
- 叙事意义；
- 已建立的角色关系意义；
- 已实现时的父级和顺序。

#### Future Structure Constraint

- 父节点被锁定不等于所有未来子节点被冻结；
- 可以在锁定父节点下新增未来子节点；
- 未被定稿正文实现的子节点仍可调整或 retired；
- 已实现子节点不能移动、retire 或重新归属。

### 7.3 部分实现结构

#### Volume

卷已有定稿内容后，Volume 身份和已经建立的叙事定位锁定；仍可新增或调整尚未
实现的后续 StoryBlock。

#### StoryBlock

故事块已经被定稿正文推进后，其身份、核心目标和已实现 Stage 锁定；尚未实现的
未来 Stage 可以新增、调整或 retired。

#### Stage 与 SceneTask

已由正文实现的 Stage/SceneTask 永久锁定。未实现节点仍属于可调整未来。

核心规则是：

> 锁定已实现路径，不冻结尚未实现的子树。

## 8. 小纲与正文工作过程

### 8.1 活动小纲

每个项目的权威下一章只能有一个 Outline Head。正文未定稿前，作者可以：

- 保存小纲；
- 修改小纲；
- 重新生成小纲；
- 采用当前小纲进入写作；
- 在已有工作稿或候选后再次调整小纲。

“采用当前小纲进入写作”表示建立本次写作依据，不表示永久定稿。

### 8.2 小纲 revision 与旧草稿

- 每次被生成、Session、WorkingDraft 或 Candidate 使用的小纲保存精确 revision/hash；
- 从未被任何操作引用的旧草稿可以直接替换；
- 被引用的小纲 revision 保留最小内部 provenance；
- 旧 revision 不作为作者可恢复的平行分支；
- 作者界面只把随正文定稿的最终小纲显示为正式历史。

### 8.3 小纲调整后的正文

小纲 Head 推进后：

- 旧 WorkingDraft 和 Candidate 不删除；
- 它们继续钉住原小纲 revision；
- UI 明确显示其写作依据已经变化；
- 作者可以保留正文继续手工修改，也可以按新小纲重新生成；
- 作者再次保存 Candidate 时，新 Candidate 绑定当前小纲；
- 绑定旧小纲的 Candidate 不能直接定稿；
- 系统不得把旧 Candidate 静默重新绑定到新小纲。

### 8.4 Planning Head 推进

小纲和正文尚未定稿时，Planning 可以继续调整未来内容。若 Planning Head 推进：

- 旧小纲 revision 仍保留为已有稿件的精确依据；
- 当前活动小纲必须基于合法 Planning 依据重新保存或调整；
- 不能静默把旧小纲 rebase 到新 Planning；
- 已定稿章节的小纲和 Planning pins 永远不受新 Head 影响。

## 9. ChapterSession、WorkingDraft 与 Candidate

### 9.1 ChapterSession

- 章节号由服务端决定；
- 同一项目最多一个活动 ChapterSession；
- Session 记录进入写作时的小纲和 Planning revision；
- 当前活动小纲后续可以调整；
- 每次生成和保存 Candidate 都记录实际使用的 Outline revision；
- Session 不能覆盖历史生成操作的 provenance。

### 9.2 WorkingDraft

- WorkingDraft 是可持续编辑的正文工作区；
- AI 生成只能产生或更新 WorkingDraft，不能定稿；
- 小纲变化不删除 WorkingDraft；
- 作者决定正文是否继续使用、手工调整或重新生成。

### 9.3 Candidate

- Candidate 是一次可审核、可定稿的正文快照；
- Candidate 必须钉住精确 Outline revision、Planning revision 和 Canon baseline；
- 可以保留多个 Candidate；
- 只有绑定当前 Outline Head 的 Candidate 可以进入最终定稿；
- 同一 Candidate 内容变化必须形成新 hash 和新候选身份，不能原地伪造历史依据。

## 10. 正文与小纲原子定稿

正式定稿前，服务端必须验证：

- Candidate 仍属于当前活动 Session；
- Candidate 绑定当前 Outline Head 的 revision/hash；
- Candidate 内容 hash 未漂移；
- Outline 引用的 Planning revision 和节点仍合法；
- Canon Head 与 Projection Head 同步；
- 预期章节号仍是服务端权威下一章；
- 项目没有并发定稿或归档。

随后执行：

```text
Candidate
  -> 质量检查
  -> 一次 FinalizationChangeSet 提取
  -> 确定性 Canon 冲突检查
  -> 作者整体确认
  -> 单事务提交
```

同一事务必须同时写入：

- 定稿正文；
- 最终小纲及其 revision/hash；
- FinalizationRecord；
- 已确认 FinalizationChangeSet；
- Canon Revision 与原子 Canon Events；
- Planning realization evidence；
- 所有确定性 Projection；
- ChapterSession finalized 状态；
- 幂等结果。

任一步失败全部回滚。不能出现正文已经定稿但小纲、Canon 或 Planning 进度没有同步
冻结的中间状态。

## 11. Canon 与纠错

### 11.1 Canon 唯一事实源

- Canon 只能由定稿事务写入；
- 设定库、记忆、人物状态、伏笔和故事进度都是 Canon 的 Projection；
- 任何 Projection 都不能成为独立写入口；
- 不允许手工标记故事块完成或手工同步记忆。

### 11.2 原子事实粒度

Canon Event 使用 entity、fact kind、field path、value、operator、cardinality、
生效章节和正文证据表达一个可独立比较的事实。

以下认知步骤不得合并成模糊的“大事件”：

- 获得信息载体；
- 接触或读取信息；
- 相信、怀疑或声称信息；
- 信息在世界中的客观真假；
- 后续证据对该信息的证实或否定。

“角色听说某事”不能直接提取为“世界中某事为真”。

### 11.3 定稿前冲突

候选正文或 ChangeSet 与当前 Canon 存在真实硬冲突时：

- 阻止定稿；
- 作者修改 Candidate 或尚未确认的 ChangeSet；
- 重新执行 schema 和确定性冲突检查；
- 不写入任何正式状态。

### 11.4 定稿后问题

章节定稿后才发现问题时：

- 不修改旧正文；
- 不修改最终小纲；
- 不回滚 Canon；
- 不修改已实现 Planning；
- 调整尚未实现的未来结构和后续小纲；
- 通过后续正文追加解释、例外、代价或新的事实。

系统不提供项目分支，也不把新建项目作为当前项目的纠错出口。

## 12. Planning 实现进度

实际进度只允许来自：

```text
定稿正文
  -> 已确认 FinalizationChangeSet
  -> Canon Event
  -> 确定性 Planning Realization Projection
```

不得使用单一 `completed=true` 表达复杂长篇情节。Phase 5 必须为实现进度定义闭合、
可确定性投影的类型化语义，至少区分开始、推进、解决、重新打开和正文明确放弃。

具体枚举属于 Phase 5 FinalizationChangeSet 设计范围，但必须满足：

- 只由定稿事实产生；
- 不能由浏览器提交；
- `retired` 未来计划和正文中实际放弃某目标是不同概念；
- Projection 可以从 Canon 完整重建；
- Planning 写入围栏读取该 Projection，而不是读取 UI 状态。

## 13. 叙事身份边界

已实现节点的初始目标、核心冲突和叙事意义属于其不可覆盖的核心内容。未来允许：

- 增加新的解释；
- 揭示隐藏动机；
- 引入更大冲突；
- 让已有事实产生新的后果。

未来不允许通过覆盖旧 Planning 字段来否定历史意义。系统使用原 Planning revision、
稳定节点身份、核心字段和 canonical hash 保留该边界，不建立另一套
`narrative_identity_snapshot` 权威表。

系统可以阻止数据层重写历史，但不能把所有文学性重解释都当作确定性错误。

## 14. 作者历史与内部审计

### 14.1 作者可见正式历史

- 已确认项目基线；
- Planning Revision；
- 每章最终小纲；
- Candidate 与定稿正文；
- Canon 事实来源；
- 正式确认和定稿时间。

### 14.2 不作为作者正式历史

- 未被引用的小纲草稿；
- 每次重新生成前的临时内容；
- 超时或晚返回结果；
- 请求重试和幂等命中；
- Provider 原始请求、响应和 prompt；
- 内部失败堆栈。

### 14.3 最小内部 provenance

被生成、WorkingDraft 或 Candidate 引用的旧小纲 revision 可以保留：

- operation ID；
- revision/hash；
- 固定状态；
- 安全失败类别；
- 创建时间；
- 引用关系。

不得保存或输出明文密钥、DSN、Provider 原文或不必要的正文副本。

## 15. 服务端事务围栏

### 15.1 基线围栏

- 种子确认后永久拒绝切换；
- 契约确认后永久拒绝新正式 revision；
- 圣经确认后永久拒绝新正式 revision；
- 归档项目拒绝所有写入。

### 15.2 Planning 围栏

保存或确认 Planning 时，服务端在同一事务中锁定并读取：

- 项目状态；
- 已确认种子、契约和圣经；
- Planning Head 与 Draft revision；
- 定稿小纲和章节 pins；
- Canon Head 与 Projection Head；
- Planning realization evidence。

服务端计算变更节点集合，拒绝修改已实现节点、已实现父级关系或历史核心内容。

### 15.3 小纲与 Candidate 围栏

- Outline 保存使用 CAS；
- 旧生成结果不能覆盖当前 Outline Head；
- Candidate 保存钉住当时的 Outline revision；
- 小纲 Head 推进后，旧 Candidate 不能定稿；
- 定稿只接受当前 Outline Head 和当前 Candidate hash。

### 15.4 固定安全冲突码

公共错误至少区分：

- `seed_already_confirmed`
- `contract_already_confirmed`
- `bible_already_confirmed`
- `planning_node_realized`
- `planning_parent_locked`
- `outline_revision_drift`
- `candidate_outline_stale`
- `canon_projection_unsynchronized`
- `stale_revision`
- `project_archived`

公共错误不得输出数据库内部信息、请求正文、Provider 原文或密钥。

## 16. UI 行为

项目中心根据服务端状态提供一个主要下一步：

1. 继续种子；
2. 继续创作契约；
3. 继续创作圣经；
4. 开始或继续故事规划；
5. 准备下一章小纲；
6. 采用当前小纲进入写作；
7. 继续写作；
8. 当前小纲已调整，更新正文或重新保存 Candidate；
9. 审核并正式定稿；
10. 准备下一章。

小纲相关文案统一为：

- 保存小纲；
- 采用此小纲进入写作；
- 调整本章小纲；
- 按新小纲重新生成；
- 正式定稿正文与小纲。

正文定稿前不把活动小纲描述为“永久确认”。

Planning 页面必须解释锁定原因，例如“已在第 12 章正文中实现”，而不是只显示
“不可编辑”。

## 17. 迁移原则

正式迁移已有项目时采用 Migration Freeze：

```text
停止创作写入
  -> 备份和校验
  -> 识别当前基线与章节依据
  -> 建立 realization evidence
  -> 重建 Projection
  -> 一致性检查
  -> 原子切换 schema/version
  -> 恢复写入
```

迁移不得通过清库、删除历史或简单选择“最新 revision”解决冲突。

- 当前权威种子、契约和圣经 Head 成为永久基线；
- 已定稿章节及其 Outline/Planning pins 优先；
- 活动 Session 引用优先于无引用小纲；
- 同一未定稿章节存在多个相互冲突的正式依据时停止迁移并显式处理；
- 一致性检查失败时应用保持只读。

Migration Freeze 是数据库升级纪律，不是长期创作产品功能。

## 18. 废止的旧规则

本修订明确覆盖以下旧规则：

1. 第一章定稿前可以切换种子；
2. A -> B -> A 形成新的 selection generation；
3. 确认契约后可以建立只影响未来的新契约 revision；
4. 确认圣经后可以建立调整未来设计的新圣经 revision；
5. Planning Head 推进后，无 Session 的已确认小纲自动 superseded；
6. 小纲进入写作后立即永久不可修改；
7. 旧 Candidate 可以在小纲变化后静默重新绑定；
8. 根本性历史错误无法前向修正时新建项目；
9. `actualProgress` 只展示而不参与 Planning 写入围栏；
10. 使用独立完成状态或手工同步旁路修改故事进度。

旧文档中与本修订不冲突的产品目标、Canon 唯一事实源、单次结构化提取、作者整体
确认和原子定稿规则继续有效。

## 19. 验收标准

### 19.1 固定流程

- 未确认上游时，后端拒绝正式下游写入；
- 直接 URL 和浏览器缓存不能绕过流程；
- 种子、契约和圣经确认后永久不可修改。

### 19.2 小纲可调

- 正文未定稿时可以调整或重新生成小纲；
- 调整小纲不删除旧 WorkingDraft/Candidate；
- 旧稿继续显示精确依据；
- 旧 Candidate 不能直接定稿；
- 基于当前小纲保存的新 Candidate 可以进入定稿。

### 19.3 正文与小纲共同定稿

- 定稿同时冻结正文和最终小纲；
- 任一步失败全部回滚；
- 定稿后小纲、正文和 pins 均不可修改；
- 重复幂等请求不产生第二次定稿。

### 19.4 未来 Planning 可调

- 未实现节点可以调整；
- 已实现节点不能修改、移动或 retired；
- 锁定父节点下仍可新增未来子节点；
- 已实现路径和未来子树在 UI 中清楚分离。

### 19.5 Canon 与纠错

- 硬冲突在定稿前阻止提交；
- Canon Event 保持原子事实粒度；
- 定稿后问题只能通过未来章节承接；
- 不存在历史重开、Canon 回滚或项目分支。

### 19.6 并发

- 小纲保存、Candidate 保存和定稿的 revision 竞态只能有一个合法结果；
- 旧 AI 结果不能覆盖新小纲；
- Planning 写入与章节定稿并发时不能越过事实锁；
- Canon/Projection 不同步时依赖写入统一拒绝。

## 20. 最终原则

本修订的产品含义是：

> 项目基线确认后永久不变；小纲在正文定稿前是可调整的当前写作依据；正文定稿时
> 小纲、正文和事实一起冻结；历史永不重写，未来始终可以在未实现边界内调整。
