# Phase 3B Volumes and Plots 验收报告

> 验收日期：`2026-07-26`
> 分支：`codex/phase3b-volumes-plots`
> Fresh package gates 的功能代码 HEAD：`e3c7d18b23fa`
> 基线：`main@0b57f7987ee7be4cc5afe2dabda79b063cafb2d7`

本报告和同步更新的事实合同随最终 acceptance commit 提交；该文档提交不反向改写
自身 SHA。

## 验收结论

Phase 3B 的 **Volumes / Plots Planning** 交付范围通过自动门禁：

- 作者可以在正式产品 UI 中创建、编辑、排序、退役并保存分卷与持续情节线；
- `/planning/volumes` 与 `/planning/plots` 使用同一个 `planningStore`、同一个
  Planning workspace 和同一份本地 Draft，不存在第二套状态或生成链；
- 手工 Planning 不依赖模型；模型未就绪时，手工编辑与保存仍可用；
- “AI 生成规划”只在作者明确点击后调用生产 gateway 边界，并把结果加载到点击时
  那一份未发生漂移的已保存 Draft；
- 作者编辑、项目生命周期、上游 basis、Planning Head、模型绑定或 fencing token
  在生成期间变化时，迟到结果不会覆盖作者内容；
- Planning revision/history 不可变，当前、已被取代和已归档状态由后端权威计算；
- archived/superseded 历史可读但不可写；
- 项目下一步由后端单一 preparation snapshot 决定，不由浏览器拼接推断；
- 公共 API、日志、错误和浏览器 artifact 未导出 prompt、原始模型输出、语料正文、
  input manifest、密码、DSN、Authorization header 或明文 API key。

本报告只授予上述范围的 Phase 3B 自动验收，不外推为整个 Phase 3、真实模型、
产品数据库、正文写作或小说内容质量 Ready。

## 已交付产品链路

### 手工规划

```text
Project Planning route
-> planningStore
-> canonical Planning API
-> PlanningService / PlanningRepository
-> active Draft / immutable Revision / authoritative Head
```

- 分卷只表达叙事方向，不反向保存 Plot 或 StoryBlock ID。
- Plot 表达可持续发展的故事线，不反向保存 StoryBlock ID。
- 只含 Volume/Plot 的手工 Draft 可以保存，但不能绕过 Phase 3A 的完整聚合确认约束。
- Volumes 与 Plots 同项目路由切换保留未保存编辑；离开 Planning、切换项目或关闭
  页面时执行一次离开保护。

### AI 可编辑 Draft

```text
author click
-> reserve transaction
-> frozen safe story manifest
-> production Planning gateway boundary
-> publish transaction
-> exact Draft CAS load or safe supersede
```

- reserve/publish 使用短事务、幂等键、租约、单调 fencing token 和精确 Draft
  revision/hash。
- story manifest 来自已确认 Seed、Creation Contract 和 Bible，使用公开的
  camelCase 结构；在 hash、持久化和 gateway 调用前执行确定性 `40 KiB` 预算。
- secret scan 在压缩前后各执行一次；高熵 token、编码后的敏感前缀及秘密字段
  都会 fail closed。
- `get_operation` 只读取权威状态，不隐式重试，也不会再次调用 Provider。
- 自动验收只在外部 Provider 边界使用严格 fake gateway；正式 router、service、
  repository、store 和 UI 均走产品链。

### 生命周期与历史

- 活跃且未过期的 Planning generation lease 会阻止项目归档/删除等冲突生命周期操作。
- terminal 或过期 operation 释放生命周期门禁。
- archived 项目只读；superseded revision 只读；任何 mutation 均由后端拒绝。
- 项目 Overview 的下一步指向 canonical Planning route，并按后端权威优先级处理
  活跃 operation、既有会话、Seed、Contract、Bible 与 Planning 状态。

## 独立审查

- Task 9 浏览器门禁规格审查：`Critical 0 / Important 0 / Minor 0`
- Task 9 浏览器门禁质量审查：`Critical 0 / Important 0 / Minor 0`
- Planning story manifest、生命周期 fencing 与浏览器 fixture 的最终联合复审：
  `Critical 0 / Important 0 / Minor 0`
- Task 10 验收文档与事实合同规格审查：`Critical 0 / Important 0 / Minor 0`
- Task 10 验收文档与事实合同质量审查：`Critical 0 / Important 0 / Minor 0`

审查期间发现并修复：

- Planning prompt 原先没有完整钉住已确认故事事实；现由 Seed、Contract、Bible
  的正式 payload 构建冻结 manifest。
- 极端 manifest 可能超过 gateway 输入上限；现先确定性压缩到 `40 KiB` 再 hash、
  持久化与调用。
- 活跃 generation lease 原先未进入项目生命周期 busy 判断；现归档等操作先经过
  repository 权威查询。
- 浏览器 fake fixture 原先可能掩盖正式字段漂移；现使用正式 payload 和行为探针，
  并拒绝 secret/corpus/provenance 泄漏。

## Fresh 最终门禁

所有门禁严格串行执行；前一项成功后才开始后一项。

### Focused gates

- Python Planning unit/API：`193 passed, 0 failed`；exit `0`
- Node/Frontend focused contracts：`59 passed, 0 failed`；exit `0`

### `npm run test:browser:phase3b`

- UI-only Playwright：`2` 个正式场景通过（manual / gateway）
- 命令结果：exit `0`
- Browser API bypass：`0`
- 数据库：`created=2, cleaned=2, remaining=0`
- owned process / port / temp root / Vite `deps_temp_*`：`0`
- secret scan findings：`0`

浏览器未使用 `page.request`、`page.route`、`page.evaluate`、浏览器 `fetch`、
Axios 或其他 API 写旁路。

### `npm test`

- Python unit / API：`2542 passed, 6 skipped, 0 failed`
- 根级 Node 合同：`216 passed, 0 skipped, 0 failed`
- 前端 unit：`415 passed, 0 skipped, 0 failed`
- 命令结果：exit `0`

### `npm run test:integration`

- Disposable MySQL integration：`317 passed, 0 failed`
- 命令结果：exit `0`
- 数据库：`created=316, cleaned=316, remaining=0`
- pytest 耗时：`2816.62s`
- 结束后独立查询 `information_schema.SCHEMATA` 中
  `novel_creator_test_%`：`remaining=0`
- owned test process / Phase 3B temp root / Vite `deps_temp_*`：`0`

### `npm run build`

- Vite：`2949 modules transformed`
- 构建结果：exit `0`

### `git diff --check`

- 结果：exit `0`
- whitespace errors：`0`

## 隔离与未评估边界

- Real Provider calls：`0`
- Product DB reads/writes：`0/0`
- Live website access：`0`
- 自动门禁只使用随机命名 Disposable MySQL 8，并在结束后独立证明残留为 `0`。
- API、日志、报告、浏览器 artifact 和命令输出未导出明文 API key。

以下能力尚未由 Phase 3B 交付或验收：

- StoryBlock、Stage、SceneTask 的正式编辑工作流；
- ChapterOutline Draft/Revision 的作者工作流与确认；
- ChapterSession 和三栏写作台的正式接入；
- WorkingDraft 新稿、改写、扩写、压缩、候选、对比和融合；
- `FinalizationChangeSet`、Canon 写入、单事务定稿与回滚；
- 真实 `deepseek-v4-flash` Provider 验收；
- 产品数据库 readiness；
- 《典镇山河》正文质量和“是否愿意继续阅读”的人工验收。

## 下一步

先编写并批准 **Phase 3C Story Blocks and Chapter Outlines** 详细实施计划，在
现有 `planning-v1` 聚合和唯一 `planningStore` 上继续建设 StoryBlock、Stage、
SceneTask、小纲 Draft/AI 草稿/确认/历史、ChapterSession 权威钉住和可靠写作入口，
不创建第二套 Planning 实体、Store、页面或生成链。Phase 3C 自动门禁继续使用
Disposable MySQL 和严格 fake Provider 边界；不得据此授予真实模型或内容质量
Ready。
