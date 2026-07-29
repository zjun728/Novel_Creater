# Phase 3C Story Blocks and Chapter Outlines 验收报告

## 元数据

- 验收日期：`2026-07-30`
- 基线：`main@59d80d739ef39a09bcd54e1888e4e4da90a98fa3`
- 交付分支：`codex/phase3c-story-blocks-outlines`
- Fresh package gates 的功能代码 HEAD：`056520c1f270fdf8f3888be2713647fff03bf2b8`
- 源码 Schema：`writer-core-v1.5.0`；Phase 3C 无 Schema 变更、migration 或 compatibility。
- acceptance commit 不反向改写自身 SHA。

## 验收结论

Phase 3C 的 Story Blocks and Chapter Outlines 交付范围通过自动门禁。作者可以在
正式 UI 中完成 Planning 故事块层级，手工或显式使用 AI 准备下一权威章节的小纲，
确认后进入唯一且正确钉住的 ChapterSession。

- Planning 权威保持唯一 `planning-v1` 聚合与唯一 `planningStore`；第三个 Planning tab 交付 StoryBlock/Stage/SceneTask。
- Planning 不含 target chapter count、completed 或 manual actual progress 字段。
- Outline 支持手工 Draft、save CAS、confirm、history 与 fake 外部边界 AI；AI 不确认 Outline，也不创建 ChapterSession。
- authority drift 会 supersede 迟到结果；权威 chapter 算法决定当前章节；每项目最多一个 drafting Session。
- 已存在 Session 保留旧 Planning/Outline pins，并支持幂等重放。
- Overview、Outline、Session 与 Writer 只使用 backend `targetPath` 和权威 chapter；Writer 只读 Outline 摘要并从空 WorkingDraft 进入。

本报告只授予上述 Phase 3C 自动验收，不把门禁外推为 Phase 3 总验收、内容质量、
真实模型、产品数据库、正式正文写作或产品 Ready。

## 已交付链路

### 唯一 Planning 聚合

```text
ProjectPlanningView
-> PlanningWorkspace third tab
-> one planningStore
-> canonical planning-v1 aggregate
-> StoryBlock / Stage / SceneTask
```

StoryBlock、Stage 与 SceneTask 使用现有 Planning Draft/Revision/Head 和稳定身份。
它们不绑定目标章节数，不把 `completed` 或作者手工实际进度写入未来计划。

### ChapterOutline

```text
manual Draft or explicit AI request
-> save CAS
-> confirm
-> immutable history
-> current confirmed Outline
```

手工路径在模型未就绪时仍可工作。AI 路径只在作者明确请求后越过 production
gateway 边界；自动验收在该外部边界使用严格 fake。AI 结果只装入精确 Draft，
不会自动确认 Outline 或创建 ChapterSession；上游 authority 漂移时迟到 operation
保留为 superseded 证据而不覆盖作者内容。

### 权威章节与可靠写作入口

若项目已有 active drafting Session，权威章节就是该 Session 的章节；否则若有
最大 final 章节，权威章节为其加一；否则为第一章。每个项目最多存在一个 drafting
Session。匹配同一 authority 的请求幂等返回既有 Session，且既有 Session 保留创建
时的旧 Planning/Outline pins。

Overview、Outline、Session 与 Writer 不在浏览器计算下一章节；它们使用后端返回的
`targetPath` 和权威章节。Writer 只读展示当前 Outline 摘要，并从空 WorkingDraft
进入；这不是正式三栏写作 UX 或正文生成。

## 独立审查

- 交付代码顺序规格审查最终：`Critical 0 / Important 0 / Minor 0`
- 交付代码顺序质量审查最终：`Critical 0 / Important 0 / Minor 0`
- M1 follow-up 最终：`Critical 0 / Important 0 / Minor 0`
- pinned-session follow-up 最终：`Critical 0 / Important 0 / Minor 0`
- Task 12 验收文档与事实合同规格审查最终：`C/I/M 0/0/0`
- Task 12 验收文档与事实合同质量审查最终：`C/I/M 0/0/0`

Task 12 规格/质量审查只覆盖本次五文件 Task 12 包，不外推为任何未评估产品能力
Ready。

## Fresh 最终门禁

Focused gates 和第三次从头 final 五门禁均为本交付代码 HEAD 的 fresh 证据。
五门禁严格串行执行，前一项成功后才开始后一项。

### Focused gates

- Focused Python：exit `0`；`250 passed, 0 skipped, 0 failed`；`71.10s`。
- Focused Python Disposable MySQL：`created=24, cleaned=24, remaining=0`。
- Focused Node：exit `0`；`144/144 passed, 0 failed, 0 skipped`；duration `1990.3702ms`。

### `npm run test:browser:phase3c`

- 命令：`npm run test:browser:phase3c`；exit `0`。
- UI-only scenarios：`7 passed, 0 failed, 0 skipped`。
- 场景：`manual / gateway / supersession / archived / missing-upstream / canon-mismatch / wrong-chapter`。
- Browser Disposable MySQL aggregate：`created=7, cleaned=7, remaining=0`。
- 每场 owned process / port / temp / cache：`0/0/0/0`。
- Browser HTTP：`allowed=37029, forbidden=0`。
- deny proxy：`HTTP=0, CONNECT=0`。
- Browser Real Provider calls：`0`。
- Browser Product DB reads/writes：`0/0`。
- Browser live website access：`0`。
- UI bypass 禁令命中：`0`。
- Browser secret scan findings：`0`。

### `npm test`

- 命令：`npm test`；exit `0`。
- Python：`2814 passed, 6 skipped, 0 failed`；`46.06s`。
- root Node：`243/243 passed, 0 failed, 0 skipped`；duration `5013.793ms`。
- frontend Node：`522/522 passed, 0 failed, 0 skipped`；duration `11141.5774ms`。

### `npm run test:integration`

- 命令：`npm run test:integration`；exit `0`。
- integration：`342 passed, 0 failed, 0 skipped`；`1015.78s`。
- Integration Disposable MySQL：`created=341, cleaned=341, remaining=0`。
- 独立 `information_schema` residual：`0`。

### `npm run build`

- 命令：`npm run build`；exit `0`。
- Vite `8.1.5`：`2956 modules transformed`；built in `982ms`。

### `git diff --check`

- 命令：`git diff --check`；exit `0`；whitespace errors `0`。

### 最终清理

- 最终独立 cleanup：owned process `0`、port `0`、Phase 3C temp roots `0`、Vite `deps_temp` `0`、test DB `0`。

## 隔离与未评估边界

- 自动验收未调用真实 Provider、产品数据库或 live 网站。
- API、log、report 与 artifact 不含明文 key、Authorization、password/DSN、prompt、manifest、raw provider output 或 corpus text。
- Phase 3D：Future Plan/Actual Progress/Canon Projection 同 revision 只读组合及 Phase 3 总验收。
- 正式三栏写作 UX、streamed 正文生成、candidate comparison/fusion、AI 味/冲突审核、Canon extraction/finalization、Real Provider readiness、Product DB readiness、novel-content quality acceptance 均未评估。
- 自动验收不构成内容质量或产品 Ready。

## 下一步

唯一下一步是 **Phase 3D Future Plan / Actual Progress / Canon Projection**：完成同 revision 只读组合与 Phase 3 总验收。
