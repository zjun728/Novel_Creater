# 产品开发规划

> 当前有效规划。日期：`2026-07-24`。

## 1. 产品目标

Novel Creator 要帮助作者持续写出长篇、连贯、可控并且让人愿意继续读的小说。
目标不是追求高级文笔或文学奖式深度，而是把故事写得有血有肉：

- 情节有因果、阻力、变化和余波，不是大纲扩写或历史材料；
- 人物有欲望、判断、行动和彼此不同的声音；
- 对话符合身份、关系和情绪，有潜台词与自然反应；
- 情绪来自处境和选择，不依赖模板化身体反应；
- 允许未完成情节自然跨章，不强制每章钩子；
- 作者对候选、事实变更和定稿拥有最终决定权。

产品主规格为
`docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`。
不兼容旧数据库、旧 API、旧 Store、旧写作页或 shadow QA 链。

## 2. 交付顺序

| 阶段 | 范围 | 状态 |
| --- | --- | --- |
| Phase 1 | 产品壳层与项目生命周期 | 已完成门禁 |
| Phase 2 | 创作资产、Provider/模型设置、市场来源、选题与种子、契约、圣经、模型继承与资产冻结 | 已完成门禁 |
| Phase 3 | 分卷、情节、故事块、小纲、已发生事实与未来计划 | 进行中 |
| Phase 4 | 自动暂存、流式新稿、改写、扩写、压缩、候选、对比、融合 | 待开始 |
| Phase 5 | 质量审核、单次事实提取、整体确认、原子定稿与失败回滚 | 待开始 |
| Phase 6 | 小说下载、安全备份、预检与导入 | 待开始 |
| Phase 7 | 产品库、真实 Provider、自由浏览器探索、《典镇山河》30 章人工验收 | 待开始 |

## 3. Phase 2 完成边界

Phase 1 的产品壳层与项目生命周期保持为后续阶段基础。Phase 2 在其上完成：

- 10 套批准风格模板、64 张批准经验卡和受管本地语料；
- Provider 公共响应无明文秘密、项目模型绑定和确定性 fallback；
- 市场来源证据、不可变快照、趋势分析、种子保存与单一活动选择；
- 故事发动机、创作契约、创作圣经、不可变 revision 与 superseded 围栏；
- 创作资产、种子、契约和圣经的正式产品页面及 UI-only 浏览器验收。

Phase 2 的 acceptance chain 已进入 canonical `main`，链末为 `f11faad`。该自动验收
没有读取产品数据库、没有调用真实 Provider，也没有证明 Phase 4 Writer Loop、
Phase 5 Finalization 或小说内容质量。

## 4. Phase 3 规划要求

当前阶段按已批准的
`docs/superpowers/specs/2026-07-24-phase-3-story-planning-design.md`
和对应实施计划以 TDD 推进。Phase 3 必须覆盖：

- 一个项目级 Planning aggregate、活动 Draft、不可变 Revision 和唯一 Head；
- Volume、Plot、StoryBlock、Stage 与 SceneTask 的稳定身份和闭合引用；
- 故事块、阶段和场景任务可以自然跨章，不绑定固定章节数；
- 独立 ChapterOutline Draft/Revision，确认后才能创建 ChapterSession；
- Planning 只保存未来计划；实际进度只能由 Canon/Projection 只读提供；
- 手工规划不依赖模型；AI 只生成可编辑 Draft，不自动确认；
- 从空库建立 `writer-core-v1.5.0`，删除旧 Planning 权威，不做兼容迁移。

Phase 3 不实现正式正文写作、质量审核、Canon 写入或原子定稿，也不以 Schema
占位或 fake gateway 测试冒充这些能力已经完成。

## 5. 写作链路的先决修复

既有 `ChapterWriterView` 是临时最小路径。进入 Phase 4 或任何正式正文生成验收前，
必须完成 WorkingDraft Integrity：

1. AI 新稿、改写、扩写、压缩和候选冻结都以作者屏幕上看到的同一正文快照为输入；
2. 作者未保存编辑不能被迟到响应覆盖；
3. 点击“保存为候选”才创建不可变候选，每次键入不自动生成候选；
4. Provider 调用不持有长数据库事务，最终提交使用 manifest hash、幂等键和 CAS；
5. fake adapter 只能授予单元证据，不能授予 Provider/DB/内容 Ready。

随后建设单一 `FinalizationChangeSet`、Canon 唯一事实源和单事务定稿。设定、记忆、
人物弧光、伏笔和故事块状态只能由同一批已确认 Canon 变化投影，不能各自重新读正文。

## 6. 每阶段共同门禁

- 从 `main` 的上一已验收阶段创建隔离分支/worktree；
- 先批准详细计划，后按 TDD 实现；
- Python、Node、前端、MySQL 8 集成、真实浏览器和构建按风险完整验证；
- 测试使用 disposable 数据库并证明 created=cleaned、remaining=0；
- 真实 Provider 和产品数据库只在对应阶段明确批准后使用；
- 任何 API、错误、日志、截图、诊断、下载或备份都不得包含明文秘密；
- 不使用 fake adapter、源码正则或旧 artifact 冒充产品链证据；
- 只宣告实际取得的阶段，不跨阶段授予 Ready。

## 7. 完成定义

只有七个阶段全部完成，并由作者在网页中逐章阅读《典镇山河》前 30 章，确认故事丰满、
人物鲜活、对话人物化、机械味和 AI 味较淡且愿意继续读，才能宣布本轮产品重构完成。
