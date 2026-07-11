# Writer Core V1 Delivery Roadmap

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `4b85e8d` 上互相漂移的旧写作状态链替换为以 Canon 为唯一事实源、以作者确认和后端原子事务为边界的 Writer Core V1，并用《典镇山河》前 30 章验证内容质量与产品可靠性。

**Architecture:** 采用“保留项目外壳、按依赖替换写作内核”的八个可独立验收里程碑。每个里程碑只允许从真实产品入口进入，使用统一测试命令和分级证据；旧 API、旧状态表和旧 runner 不提供兼容层，也不能证明新链路 Ready。

**Tech Stack:** Vue 3、Pinia、Vite、FastAPI、Pydantic、aiomysql、MySQL 8、pytest、Node `node:test`、Playwright。

---

## 1. 程序边界

唯一实施基线是 `4b85e8d`。本路线图和详细计划保存在设计分支；业务实现必须新建 `codex/writer-core-v1`，并从 `4b85e8d` 创建干净 worktree。不得把当前脏 worktree、`codex/novel-creater-platform-rc`、`tmp` runner、e.* artifact 或旧迁移提交 cherry-pick 到实施分支。

所有里程碑共同遵守：

- 正式状态只由后端服务写入。
- 正式 AI 调用只走后端 `/api/ai/*`；浏览器 direct-provider 分支在里程碑 5 删除。
- API、日志、错误、诊断和导出永不返回明文 API key 或真实 Provider base URL。
- `npm test` 只枚举正式测试目录；`tmp` 永不进入正式入口。
- fake 只能给 L1；Disposable MySQL 给 L2；固定浏览器给 L3；主控探索浏览器给 L4；真实 Provider/产品库人工验收给 L5。
- 每个里程碑最高只能授予其实际取得的证据等级，不使用 “Live Ready”“DB Ready” 等越级结论。
- 已批准的《Writer Core V1 总体设计》是需求源；本文件只定义交付顺序，不改变产品规则。

## 2. 里程碑依赖图

```mermaid
flowchart LR
    M1["M1 Schema / Canon / Transaction"] --> M2["M2 Contract / Corpus Assets"]
    M2 --> M3["M3 StoryBlock / Stage / SceneTask"]
    M3 --> M4["M4 ChapterSession / Draft / Candidate"]
    M4 --> M5["M5 Scene Generation / Review / Copy Check"]
    M5 --> M6["M6 ChangeSet / Atomic Finalization"]
    M6 --> M7["M7 Writer UI / Browser Diagnostics"]
    M7 --> M8["M8 典镇山河 30-Chapter Acceptance"]
```

## 3. 分阶段交付

### Task 1: M1 — 干净 Schema、Canon、实体身份、投影和事务基础

**Detailed plan:** `docs/superpowers/plans/2026-07-11-writer-core-foundation.md`

**Working product:** 项目列表与项目基础页从新 Schema 读取“永乐大典”和三个种子；页面显示 Schema/Canon/Projection 状态。旧写作入口明确停用，不再调用旧 chapters/settings/story-block/finalization API。

**Exit evidence:**

- [ ] `npm test` 通过领域单元测试、API 单元测试和前端单元测试。
- [ ] Disposable MySQL 完成 fresh bootstrap、版本拒绝、事务回滚、revision、投影、幂等和别名歧义测试。
- [ ] 真实浏览器从首页进入项目页，看到项目、三个种子和同步的 Canon/Projection head。
- [ ] 浏览器 network/console/API body 不含 `apiKey`、`api_key`、真实 base URL 或旧测试专名。
- [ ] 主控完成刷新、后退、重复打开、错误数据库版本的探索测试。
- [ ] 最高结论为 L4 `M1 No-Provider Ready`。

### Task 2: M2 — 创作契约、模型绑定、风格/语料/经验资产

**Detailed plan file to create before implementation:** `docs/superpowers/plans/2026-07-11-creation-contract-and-assets.md`

**Working product:** 作者在种子池中唯一选择 `典镇山河`，比较三个故事发动机，预览并选择主风格/次风味和经验卡，确认后生成不可含糊的 CreationContract/StyleContract。完整语料保存在本机文件目录，DB 保存哈希、规范化文本和索引。

**Required implementation files:**

- `backend/domain/contracts.py`
- `backend/services/contracts.py`
- `backend/services/model_bindings.py`
- `backend/services/corpus_import.py`
- `backend/routers/contracts.py`
- `backend/routers/corpus.py`
- `frontend/src/stores/creationContractStore.js`
- `frontend/src/views/ProjectView.vue`
- `frontend/src/components/project/CreationContractWizard.vue`

**Exit evidence:**

- [ ] 项目只能有一个 selected seed 关系；首章定稿后选种锁定。
- [ ] 新项目复制最近项目完整模型绑定；无效项逐项回退到稳定排序首个 enabled model。
- [ ] 无 enabled model 时 AI 操作阻止，不使用 fake 或内置 fallback。
- [ ] 《典镇山河》所有任务初始绑定“联通云 / deepseek-v4-flash”。
- [ ] 导入语料文件时记录 SHA-256、章节边界、规范化文本和分析版本；原始文件不进入 Git。
- [ ] 首批 8 个主风格模板和 40–60 张高质量经验卡通过人工资产检查。

### Task 3: M3 — StoryBlock、StoryStage、SceneTask 和章节容量

**Detailed plan file to create before implementation:** `docs/superpowers/plans/2026-07-11-rolling-planning.md`

**Working product:** 作者能确认卷方向、建立 active StoryBlock、调整未执行阶段和 SceneTask；正在执行的任务可无限跨章，章节接近容量上限时只停止领取新场景。

**Required implementation files:**

- `backend/domain/planning.py`
- `backend/services/planning.py`
- `backend/routers/planning.py`
- `frontend/src/stores/planningStore.js`
- `frontend/src/components/planning/StoryBlockWorkspace.vue`
- `frontend/src/components/planning/SceneTaskList.vue`

**Exit evidence:**

- [ ] StoryBlock 不含 target chapter count 或 continuation count。
- [ ] `pending -> in_progress -> completed` 是 StoryStage 唯一正常状态机。
- [ ] 已被定稿引用的 Stage/SceneTask snapshot 不可改；未来项可调整/取消。
- [ ] 《典镇山河》容量默认 3500–4500 字，约 5200 为自然收束安全上限。
- [ ] 不强制每章钩子、反转或完成整个 Stage。

### Task 4: M4 — ChapterSession、WorkingDraft、DraftCandidate

**Detailed plan file to create before implementation:** `docs/superpowers/plans/2026-07-11-chapter-session-and-candidates.md`

**Working product:** 作者手动创建章节会话，确认场景计划，编辑自动暂存的 WorkingDraft，并只在点击“保存为候选”时冻结完整 DraftCandidate。

**Required implementation files:**

- `backend/domain/drafts.py`
- `backend/services/chapter_sessions.py`
- `backend/routers/chapter_sessions.py`
- `frontend/src/stores/chapterSessionStore.js`
- `frontend/src/stores/workingDraftStore.js`
- `frontend/src/stores/candidateStore.js`
- `frontend/src/components/writer/WorkingDraftEditor.vue`

**Exit evidence:**

- [ ] 输入和 autosave 不创建候选。
- [ ] 显式保存候选冻结内容、SHA-256、来源会话和来源模型输出。
- [ ] 原始模型输出不可覆盖；工作稿可恢复到来源候选。
- [ ] 定稿入口拒绝未保存的 WorkingDraft。
- [ ] finalized chapter 的任何编辑/删除 API 均返回 409。

### Task 5: M5 — 分场景生成、参考检索、防复制和质量审核

**Detailed plan file to create before implementation:** `docs/superpowers/plans/2026-07-11-scene-generation-and-review.md`

**Working product:** 作者逐场景生成正文；每场只接收允许的四类上下文，失败只重试当前场景。定稿前可运行 AI 味/一般质量审核和全语料原文重合检查。

**Required implementation files:**

- `backend/services/ai_gateway.py`
- `backend/services/reference_retrieval.py`
- `backend/services/copy_detection.py`
- `backend/services/quality_review.py`
- `backend/routers/generation.py`
- `frontend/src/application/writer-flow/scene-generation-command.js`
- `frontend/src/stores/referenceStore.js`
- `frontend/src/stores/reviewStore.js`

**Exit evidence:**

- [ ] 删除 `VITE_AI_DIRECT_PROVIDER` 和浏览器 adapter 正式分支。
- [ ] Prompt contract 测试证明正文 Prompt 只有当前剧情/人物、StyleContract+1–2 参考、事实/字数/停止位置。
- [ ] Prompt 不含完整 Rubric、数字化防 AI 清单、固定对白轮次、身体反应、每章钩子或旧人物名。
- [ ] 40 连续中文字近似复制，或同源三处 24 字独特表达命中时提供原文定位并阻止定稿。
- [ ] 检测服务不可用时阻止定稿；AI 味/一般质量审核失败只标记未完成，不夺走作者权限。

### Task 6: M6 — FinalizationChangeSet 与原子定稿

**Detailed plan file to create before implementation:** `docs/superpowers/plans/2026-07-11-atomic-finalization.md`

**Working product:** 作者选择候选，统一提取一次 FinalizationChangeSet，编辑/确认全部变化，后端单事务冻结正文、追加 Canon、推进规划并重建全部投影。

**Required implementation files:**

- `backend/domain/finalization.py`
- `backend/services/change_set_extraction.py`
- `backend/services/finalization.py`
- `backend/routers/finalization.py`
- `frontend/src/stores/finalizationStore.js`
- `frontend/src/components/writer/FinalizationChangeSetPanel.vue`

**Exit evidence:**

- [ ] ChangeSet 明确分开 `canonChanges` 与 `planSuggestions`。
- [ ] 后续设定、记忆、弧光、线索不再次调用模型读取正文。
- [ ] 请求校验候选 hash、expected Canon head、StoryBlock revision 和章节状态。
- [ ] final chapter、record、revision、events、planning、projections、project head 同事务成功或回滚。
- [ ] 幂等键绑定 project/chapter/candidate/hash/expected head；重复请求返回首次结果。
- [ ] 不存在 replacement、reopen、Canon rollback 或历史分支接口。

### Task 7: M7 — Writer UI 收束与跨层诊断

**Detailed plan file to create before implementation:** `docs/superpowers/plans/2026-07-11-writer-workspace.md`

**Working product:** Writer 页面收束为左侧规划导航、中间工作稿编辑器、右侧候选/参考/审核/ChangeSet；页面只编排 store，不再包含领域事务。

**Required implementation files:**

- `frontend/src/views/WriterView.vue`
- `frontend/src/components/writer/WriterWorkspace.vue`
- `frontend/src/components/writer/WriterNavigationPane.vue`
- `frontend/src/components/writer/WorkingDraftEditor.vue`
- `frontend/src/components/writer/WriterInspectorPane.vue`
- `frontend/e2e/writer/*.spec.ts`

**Exit evidence:**

- [ ] 删除被新 store 取代的旧 `writerStore.js` 编排和旧 finalization commands。
- [ ] 页面刷新、中断、切章、重复提交、乱序点击、返回和弹窗恢复经过固定浏览器回归。
- [ ] 主控进行非脚本探索，API/DB 只作读诊断，不直接写入替代页面操作。
- [ ] 每次证据记录 commit、分支、入口、环境、同次 finalization/revision/hash。

### Task 8: M8 — 《典镇山河》前 30 章人工验收

**Detailed plan file to create before implementation:** `docs/superpowers/plans/2026-07-11-dian-zhen-shan-he-30-chapter-acceptance.md`

**Working product:** 作者通过正式 UI 手动逐章生成、编辑、保存候选和定稿 30 章，至少自然完成一个 StoryBlock。

**Exit evidence:**

- [ ] 每章硬门禁全部通过。
- [ ] 前 3 章阅读牵引力平均不低于 4。
- [ ] 至少 24/30 章牵引力为 4–5，其余不低于 3，且不连续两章为 3。
- [ ] 八项内容质量平均均不低于 3.8，任何单项不出现 1。
- [ ] 至少一个 StoryBlock 通过块级验收。
- [ ] 章节不以历史材料、文献摘要、档案报告或设定说明书为主要读感。
- [ ] 作者读完 30 章后明确仍愿意继续阅读和创作。
- [ ] 在完成 L5 Provider/Product DB 与人工内容验收之前，不确定远端 canonical main/release policy。

## 4. 每个里程碑的执行节奏

每个详细计划都按以下顺序执行：

1. 从上一个已验收里程碑 commit 创建干净 worktree。
2. 主控审核测试入口，确认没有 direct API write、fake 越级或 `tmp` runner。
3. 逐任务 TDD 实现并频繁提交。
4. 运行 unit、integration、browser 固定回归。
5. 主控用真实浏览器执行非固定探索。
6. 对照规格做代码审查和结果审计。
7. 只合并已达到本里程碑证据等级的提交。
8. 记录未覆盖风险，但不通过新增平行 runner 伪造闭环。

## 5. 路线图完成定义

Writer Core V1 只有同时满足以下条件才算完成：

- 八个里程碑全部通过各自门禁。
- 旧 facts/settings/memory/arcs/plot-thread 独立写链和旧 finalize API 已物理删除。
- 正式根测试入口不引用 `tmp`、e.*、fixture adapter 或旧 artifact。
- 真实 UI、AI Proxy、后端服务、产品数据库和 UI 回读形成同次证据。
- 《典镇山河》30 章人工内容验收通过。
- 用户另行确认 canonical branch、远端 main 和发布策略。
