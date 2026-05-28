# Novel Creator 开发记录

本文件用于记录产品开发过程中的事实、决策、已完成内容和下一步任务。

维护规则：

- 每完成一个功能块必须追加记录。
- 每次修改重要架构或产品决策必须记录。
- 每次运行测试、构建或验证必须记录结果。
- 如果开发中断或上下文压缩，优先阅读本文件和 `PRODUCT_DEVELOPMENT_PLAN.md`。

## 当前状态

- 产品规划已重写为本地版 AI 全程创作工作台。
- v0.1 本地地基版已完成。
- v0.2 AI 创作闭环版已完成。
- v0.3 记忆与审稿版已完成。
- v0.4 选题雷达版已完成。
- v0.5 体验增强版已完成。
- 已完成 IndexedDB → FastAPI + MySQL 迁移。
- v0.6 设定库与世界观一致性版已完成主体闭环：设定库、关系、待确认变更、定稿提取、冲突检测和写作上下文接入均已可用。
- v1.0 本地稳定版进入补强与验收阶段：重点是章节生成链路稳定性、上下文透明化、纠偏闭环和长篇项目端到端验证。

## 文档入口

- 产品开发规划：`PRODUCT_DEVELOPMENT_PLAN.md`
- 开发记录：`DEVELOPMENT_LOG.md`

## 已确认产品决策

- 采用前后端分离架构：Vue 3 前端 + FastAPI 后端 + MySQL 5.7 数据库。
- AI 调用前端直连供应商（不经过后端 AI Gateway）。
- 后端提供 RESTful API，前端通过 `src/api/db/client.js` 统一访问。
- 前端使用 Vue 3 + Vite + Naive UI + Tailwind + Pinia + Vue Router。
- 正文编辑器使用纯 textarea。
- AI 内容默认进入候选版本，不直接覆盖正式稿。
- 所有正式内容必须经过用户确认。
- 多模型配置是底层核心能力。
- 选题雷达作为市场观察和原创选题孵化，不抓取小说正文。
- 设定库作为长篇小说结构化记忆底座，负责人物、势力、世界观、修炼体系、物品、关系和状态变更。
- 创作圣经只保存作品级核心原则，不承载完整百科式资料。
- 章节定稿后由 AI 提取待确认设定变更，必须经用户确认后才能写入设定库。
- 设定库提取分为两条不同流程：项目初始阶段的“圣经/种子初始化提取”和写作过程中的“章节定稿增量提取”，后续开发不得混用。
- 初始化提取可以分类型处理长篇圣经和种子；章节增量提取只能基于本章定稿正文和已有设定库，不允许重新扫描圣经覆盖正式设定。

## 版本进度

| 版本 | 状态 | 目标 |
| --- | --- | --- |
| v0.1 本地地基版 | 已完成 | 项目、存储、模型配置、本地导入导出 |
| v0.2 AI 创作闭环版 | 已完成 | 种子、候选章节、写作台、定稿 |
| v0.3 记忆与审稿版 | 已完成 | 摘要、事实、角色状态、伏笔、审稿 |
| v0.4 选题雷达版 | 已完成 | 网页抓取热门排行、分类展示、AI 选题顾问、大纲生成 |
| v0.5 体验增强版 | 已完成 | 多模型对比、融合、风格和节奏分析、人物弧光/伏笔可视化 |
| v0.6 设定库与世界观一致性版 | 主体完成，继续补强 | 人物、势力、世界观、修炼体系、关系图谱、状态变更日志 |
| v1.0 本地稳定版 | 补强与验收中 | 稳定整合、章节生成稳定性和长篇项目验证 |

## 下一步任务

当前开发必须围绕 `PRODUCT_DEVELOPMENT_PLAN.md` 的 v1.0 本地稳定版验收推进，优先补齐“长篇可持续创作”的实用闭环，不新增偏炫技功能。

1. v1.0 浏览器端手工验收：在真实页面中按“选题 → 种子 → 圣经 → 设定库初始化 → 章节小纲 → 正文生成 → 定稿入库 → 审稿纠偏 → 下一章生成”的完整路径点击验证。
2. 长篇项目验证：准备 50-100 章规模的模拟或真实项目数据，观察设定库注入、章节列表、版本列表、审稿和导出导入性能。

注意：以上为已确认的待修复/待验收队列；当前按用户确认后的优先级逐项执行，完成一项即同步文档和验证结果。

暂缓事项：

- SaaS 化、多用户、计费、云同步暂不进入当前开发。
- 重型爬虫、平台正文抓取、向量检索、复杂富文本编辑器暂不进入当前开发。
- 新增功能必须服务当前长篇创作主流程，避免偏离“实用创作平台”目标。

## 2026-05-24 - 本章审稿逐条修订面板

### 问题
- 本章审稿弹窗关闭或点击返回修改后，用户回到正文界面看不到原来的修改建议，只能反复“审稿 -> 生成修订版本 -> 再审稿”，修稿成本高。
- 实测发现审稿 `location` 片段与正文只要存在空格、换行或引号差异，一键替换就会提示“正文中未找到该片段”。

### 本次完成
- 审稿 Prompt 新增 `replacement` 字段，要求模型为每个问题尽量提供可直接替换原文的正文片段。
- 审稿结果解析保留 `replacement`，并补齐 `human_motivation`、`emotional_logic`、`ai_tone` 等审稿类型。
- 写字台右侧新增“审稿修改建议”面板：审稿报告关闭后仍保留问题列表、原文、建议和替换文本。
- 支持逐条定位原文：点击后在正文 textarea 中选中对应片段。
- 支持逐条替换：只替换当前正文中仍能精确找到的原文片段，替换后正文进入未另存状态并触发临时草稿保存。
- 支持忽略单条问题；找不到原文时提示正文已变化，不做模糊替换。
- 替换定位升级为安全宽松匹配：允许忽略空白、换行、中英文引号和常见标点差异，但必须唯一命中，避免误替换相似段落。
- 半句定位保护已补齐：当审稿 `location` 只定位到半句、但 `replacement` 是完整句时，自动扩展到当前完整句再替换，避免把完整句插入到半句话中。
- 审稿 Prompt 已明确要求 `location` 必须从正文逐字复制，且 `replacement` 与 `location` 粒度一致。

### 修改文件
- `frontend/src/prompts/audit.js`
- `frontend/src/stores/memoryStore.js`
- `frontend/src/utils/auditRevisionTools.js`
- `frontend/src/views/WriterView.vue`
- `tmp/test_audit_revision_tools.mjs`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `node tmp\test_audit_revision_tools.mjs` 通过。
- `node tmp\test_chapter_title_generation.mjs` 通过。
- `node tmp\test_chapter_word_prompt_guard.mjs` 通过。
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-24 - AI 腔句式硬约束升级

### 问题
- 实际生成章节中，“不是X，是Y / 不是X，而是Y”句式一章可出现 20 多次，软性提示不足以约束模型。

### 本次完成
- 正文生成系统提示词从“避免高频”升级为可计数硬约束：非对白叙述中同类句式整章最多 2 次。
- 输出前静默自检新增同类句式数量检查，超过阈值必须改成动作、感官、物象、对白停顿或人物反应。
- 本章审稿新增 `ai_tone` 问题类型，超过阈值时应作为“AI 腔”问题提出。
- 去 AI 腔/润色 Prompt 升级为尽量清零同类句式，不再只是减少。

### 修改文件
- `frontend/src/prompts/chapter.js`
- `frontend/src/prompts/audit.js`
- `frontend/src/prompts/rewrite.js`
- `frontend/src/utils/auditLabels.js`
- `tmp/test_human_motivation_prompts.mjs`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `node tmp\test_human_motivation_prompts.mjs` 通过。
- `node tmp\test_finalize_endpoint_contract.mjs` 通过。
- `node tmp\test_correction_manual_closure.mjs` 通过。
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-24 - 定稿接口锁定顺序修复

### 问题
- 用户点击定稿后出现 `API error 409: 本章已经定稿，正文、小纲和版本已锁定，不能再修改。`
- 根因是前端先把候选版本更新为 `final`，再调用普通章节更新接口写入 `finalVersionId`、状态和字数；后端章节锁定保护检测到章节已定稿后拒绝普通更新。

### 本次完成
- 后端新增版本专用定稿接口，一次性完成版本 final 标记、章节 finalVersionId、章节状态、字数和更新时间写入。
- 前端定稿流程改为调用专用定稿接口，不再在定稿过程中调用普通章节更新接口。
- 保留已定稿章节的普通更新锁定保护，避免定稿后再次修改正文、小纲或版本。

### 修改文件
- `backend/routers/chapters.py`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/writerStore.js`
- `tmp/test_finalize_endpoint_contract.mjs`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `node tmp\test_finalize_endpoint_contract.mjs` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-24 - 纠偏设定候选手动闭环提示

### 产品决策
- 点击“生成设定候选”只生成待确认设定变更，不自动确认入库，也不自动完成纠偏任务。
- 用户需要到设定库确认或拒绝候选；确认入库后回到纠偏任务点击“完成”，拒绝后可以“忽略本次”或继续人工处理。

### 本次完成
- 新增纠偏设定候选状态判断工具，区分待确认、已确认、已拒绝和本地刚生成状态。
- 纠偏任务卡片新增手动闭环提示，并在待确认状态提供“去设定库确认”入口。
- 生成设定候选后的成功提示改为明确说明下一步，不再让用户误以为任务已经处理完。

### 修改文件
- `frontend/src/utils/correctionManualClosure.js`
- `frontend/src/components/correction/CorrectionTaskBoard.vue`
- `tmp/test_correction_manual_closure.mjs`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `node tmp\test_correction_manual_closure.mjs` 通过。

## 2026-05-23 - 人物弧光时间线说明补充

### 本次完成
- 在人物弧光时间线标题下方新增小字说明，解释硬状态、软状态、双重变更、有事实和未出现的判定含义。
- 保留原有颜色图例，用于快速识别各章节的人物状态变化。

### 修改文件
- `frontend/src/components/bible/CharacterArcView.vue`
- `DEVELOPMENT_LOG.md`

### 验证
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-23 - 生成本章质量护栏前置

### 产品决策
- 本章审稿继续保留为事后质检，不用生成提示词替代审稿。
- 生成本章前置轻量规则，只作为创作边界，不把正文写成固定模板，避免压制想象力。

### 本次完成
- 章节正文系统提示词补充：允许合理反转，但必须通过隐藏真相、角色认知有限或误导解除成立。
- 章节正文系统提示词补充：新增关键人物、势力、地点、物品或能力时必须有清晰叙事作用，便于后续进入设定库。
- 章节正文任务末尾新增“输出前静默自检”，要求模型在心中检查承接、小纲完成、设定冲突、新增关键设定和开头乱序，并自行修正但不输出检查过程。
- 产品规划和功能测试清单已同步新增该质量护栏要求。

### 修改文件
- `frontend/src/prompts/chapter.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-23 - 审稿标签中文化

### 本次完成
- 新增审稿标签映射工具，统一把 `critical`、`major`、`minor`、`suggestion` 显示为严重、主要、轻微、建议。
- 统一把 `contradiction`、`pacing`、`logic`、`quality` 等审稿问题类型显示为中文。
- 本章审稿、分卷审稿、全局审稿和纠偏任务板已接入中文展示。

### 修改文件
- `frontend/src/utils/auditLabels.js`
- `frontend/src/views/WriterView.vue`
- `frontend/src/views/ProjectView.vue`
- `frontend/src/components/chapter/VolumePlanner.vue`
- `frontend/src/components/correction/CorrectionTaskBoard.vue`
- `DEVELOPMENT_LOG.md`

### 验证
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-23 - 小纲静默自检护栏

### 产品决策
- 小纲阶段只做 AI 静默自检，不新增人工审查环节，避免创作流程变重。

### 本次完成
- 小纲系统提示词要求输出前先在心中自检并修正，不输出检查过程。
- 小纲任务提示词新增静默自检项：上一章承接、自然时间顺序、设定一致性、人物行动合理性、本章目标和正文发挥空间。
- 产品规划和功能测试清单已同步小纲质量护栏。

### 修改文件
- `frontend/src/prompts/chapter.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-23 - 定稿前审稿门禁

### 产品决策
- 定稿前先审稿，定稿后只做记忆和设定提取，避免正文锁定后才发现可修订问题。
- 审稿不能自动改写或自动定稿修订内容；修订仍进入候选版本，必须由用户确认。

### 本次完成
- 写字台定稿流程改为：点击定稿 -> 本章一致性审稿 -> 严重/主要问题拦截 -> 用户选择修订、仍然定稿或返回修改。
- 轻微/建议类问题会提示用户继续定稿或返回修改。
- 定稿后处理不再重复执行本章审稿，只保留摘要、记忆事实和设定变更提取。
- 定稿后处理完成弹窗文案改为显示记忆事实和待确认设定变更数量，不再把审稿问题混在“记忆提取”里。
- 产品规划和功能测试清单已同步定稿前审稿门禁。

### 修改文件
- `frontend/src/views/WriterView.vue`
- `frontend/src/stores/memoryStore.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-23 - 正文生成降低 AI 腔

### 本次完成
- 章节正文系统提示词新增“降低 AI 腔”规则，减少“不是……而是……”“不是……是……”“像是……又像是……”“某种……”等套路化反差句和虚化判断的高频使用。
- 输出前静默自检新增 AI 腔句式检查，要求重复出现时改成具体动作、感官、物象或人物反应。
- 产品规划和功能测试清单已同步该质量要求。

### 修改文件
- `frontend/src/prompts/chapter.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-22 - 纠偏任务硬/软分层与生成门禁

### 产品决策
- 章节纠偏只用于未定稿章节，属于硬纠偏；未处理前阻断本章定稿和继续生成。
- 已定稿章节不再回改正文，分卷/全局纠偏默认作为软纠偏进入后续章节上下文，用自然补解释、补动机、回收伏笔的方式修复偏差。
- 涉及设定库或记忆的纠偏不自动覆盖正式资料，只生成待确认候选。

### 本次完成
- 纠偏任务增加 `correctionMode` 与 `blocking` 元数据，用于区分硬纠偏、软纠偏、设定候选、记忆候选和建议。
- 写字台生成小纲、正文、多候选、续写、扩写、压缩、选区改写、多模型对比和定稿前，会检查阻断型纠偏任务。
- 软纠偏任务不阻断生成，但会进入 AI 写作上下文，并明确要求后续章节自然修复，不回改已定稿正文。
- 本章审稿报告在未定稿章节可转为本章硬纠偏任务；已定稿章节不提供正文修订型纠偏入口。
- 纠偏任务板显示纠偏类型，正文修订草案只对硬纠偏任务开放。

## 2026-05-20 - 写字台小纲确认弹窗与记忆导航修复

### 问题
- 本章小纲确认弹窗在小纲较长时会把底部按钮挤到视口底部，保存、重新生成和开始生成按钮不够稳定。
- 写字台顶部进入“记忆”视图后，两个按钮都可能显示“写字台”，导航语义混乱。
- 重新生成小纲原逻辑会立即保存新小纲，存在误覆盖已保存小纲的风险。

### 本次完成
- 小纲弹窗改为内容区滚动、底部操作区固定，长小纲不会遮挡操作按钮。
- “重新生成小纲”改为只更新当前弹窗草稿，不立即覆盖已保存小纲。
- 点击“保存小纲”或“开始生成本章”时，才会把当前小纲保存到章节小纲记录。
- 顶部“记忆”按钮在记忆视图中仍显示“记忆”，左侧按钮负责从圣经/记忆返回写字台。
- 顶部“已有小纲”标记改为只基于已保存小纲显示，避免临时草稿误导用户。
- AI 工具区按钮改为无保存小纲时显示“先做小纲”，有保存小纲后显示“查看小纲”。
- AI 工具区 loading 状态从全局生成态拆出具体动作态，避免生成正文或生成小纲时“基于小纲生成多版本”按钮误显示旋转进度。
- 版本差异对比改为“当前正文/定稿作为默认基准 + 已加入对比的候选作为对比对象”，加入一个候选即可打开差异对比。
- 基于小纲生成多版本后不再自动把第一个候选加载进编辑器，避免覆盖用户正在看的原版正文基准。
- 差异对比基准选择补强：如果当前选中的版本已经加入对比池，会优先选择未加入对比池的原始生成版本作为基准，避免“基准=候选”导致误报没有候选版本。
- 差异对比弹窗选项补入“当前编辑器正文”和章节全部版本，选项文案改为显示版本类型、来源说明和时间，避免多个 `AI 候选` 难以区分。
- 多候选生成逻辑收敛：已有正文时只补充“强冲突版/意外转向版”两个替代候选，并保留当前正文作为默认基准；无正文时直接生成三版候选，并默认载入第一版到编辑器。
- 顶部“保存草稿”改为“另存为版本”，会把当前编辑器正文创建为 `用户草稿` 版本进入版本列表。
- 从版本列表切换版本时，如果当前编辑器内容相对已载入版本有手动改动，会弹窗提示先另存为版本、直接切换或继续编辑，避免误以为候选版本被自动覆盖。
- 续写、扩写、压缩和选区改写执行期间，写字台正文编辑器会显示处理遮罩并禁用编辑，避免 AI 回写过程中用户继续修改导致内容错位。
- 版本列表定稿逻辑收紧：本章已有定稿后，其他版本不再允许继续点击定稿，避免重复覆盖 `finalVersionId` 和重复触发记忆提取。

### 修改文件
- `frontend/src/views/WriterView.vue`
- `frontend/src/components/writer/AIActionPanel.vue`
- `frontend/src/components/writer/VersionDiffModal.vue`
- `DEVELOPMENT_LOG.md`

### 验证
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-20 - v1.0 接口级完整链路冒烟验收

### 本次完成
- 新增临时冒烟脚本 `tmp/v1_e2e_smoke.ps1`，用于验证后端核心数据流，不依赖外部 AI。
- 通过临时项目完整跑通：项目创建、内容状态检查、创作种子、创作圣经、设定变更确认入库、分卷、章节、小纲、候选正文、定稿、内容状态锁定、全局审稿报告、纠偏任务、纠偏忽略状态和项目清理。
- 修复项目删除遗漏：删除项目时现在会同步清理 `project_audit_reports` 和 `correction_tasks`，避免审稿/纠偏孤儿数据残留。
- 修复设定变更接口鲁棒性：`oldValue` / `newValue` 现在支持对象或数组入参，后端会统一转为 JSON 字符串存储，避免 AI 提取候选直接传对象时 500。
- 验收过程中使用 `8010` 临时后端验证新代码，结束后已关闭临时进程；不影响用户已有 `8000` 本地服务。

### 修改文件
- `backend/routers/projects.py`
- `backend/routers/settings_library.py`
- `tmp/v1_e2e_smoke.ps1`
- `DEVELOPMENT_LOG.md`
- `PRODUCT_DEVELOPMENT_PLAN.md`

### 验证
- `powershell.exe -ExecutionPolicy Bypass -File tmp\v1_e2e_smoke.ps1` 在 `NOVEL_SMOKE_BASE=http://127.0.0.1:8010/api` 下通过，输出 `SMOKE_OK` 和 `CLEANUP_OK`。
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。

### 后续
- 接口级闭环已通过，下一步需要在浏览器页面做手工验收，重点看弹窗、按钮状态、页面状态流转、AI 生成失败提示和用户可见交互是否一致。

## 2026-05-20 - 选题雷达方向建议解析与兜底修复

### 问题
- 浏览器端抓取热点后，AI 已返回接近正确的 `{ "directions": [...] }` 方向建议，但前端提示“AI 没有返回可解析的方向建议 JSON”。
- 根因之一是解析器会收集 JSON 内部的单个方向对象，但归一化逻辑只接受数组或顶层 `directions`，不接受单个方向对象。
- 如果 AI 输出被截断或修复仍失败，当前流程会直接报错，没有把已抓取热点转成可继续讨论的保守方向建议。

### 本次完成
- `extractMarketDirections` 已支持单个方向对象解析，能从 `{ title, genre, readerExpectation... }` 这种候选中恢复方向建议。
- 新增 `buildFallbackMarketDirections`：当 AI JSON 解析和修复都失败时，基于已抓取热点样本按题材、平台、标签生成本地保守方向建议。
- `generateMarketDirections` 不再在有热点样本时直接失败；解析失败会记录 warning，并保存本地保守方向建议，保证选题雷达流程不中断。

### 修改文件
- `frontend/src/prompts/marketDirections.js`
- `frontend/src/stores/marketStore.js`
- `tmp/test_market_directions.mjs`

### 验证
- `node tmp\test_market_directions.mjs` 通过：覆盖顶层 `directions`、单个方向对象、本地保守兜底三类情况。
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-20 - 章节管理按钮语义拆分

### 问题
- 章节管理页里的“按目标章节初始化”位于分卷规划区域，实际功能是自动创建分卷规划，不是创建章节小纲，也不是批量创建空章节。
- 该文案容易让用户误以为它是章节小纲或空章节创建入口。

### 本次完成
- 分卷规划按钮文案改为“自动生成分卷规划”，成功/失败提示也同步改为分卷规划语义。
- 章节列表区域新增“批量创建空章节”按钮，真正按项目目标章节数补齐缺失章节记录。
- 批量创建空章节只创建缺失章节，不覆盖已有章节、小纲、正文、候选版本或定稿。

### 修改文件
- `frontend/src/components/chapter/VolumePlanner.vue`
- `frontend/src/views/ProjectView.vue`
- `frontend/src/stores/writerStore.js`

### 验证
- 已检索旧文案“按目标章节初始化/初始化分卷”，确认页面不再残留误导文案。
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-20 - 纠偏任务忽略状态独立化

### 本次完成
- “忽略本次”从原先复用 `rejected` 调整为独立状态 `ignored`。
- `rejected` 保留为历史兼容和“已拒绝”语义，仍视为关闭状态，不进入写作台 AI 上下文。
- 纠偏任务板按钮统一使用“是否仍为打开任务”判断，已完成、已忽略、已拒绝、已取消和已归档任务都不再显示生成候选、定位、完成或忽略按钮。
- 后端纠偏任务列表排序补入 `ignored`，历史任务列表显示顺序与状态语义保持一致。

### 修改文件
- `frontend/src/stores/correctionTaskStore.js`
- `frontend/src/components/correction/CorrectionTaskBoard.vue`
- `backend/routers/correction_tasks.py`

### 验证
- 已检查源码中纠偏任务面板不再写死 `done/rejected` 判断。
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `git diff --check` 通过，仅有既有 CRLF 换行提示。

## 2026-05-20 - 项目目标规模锁定规则复核

### 本次完成
- 项目目标字数和目标章节数的锁定规则从“只要有章节记录就锁定”调整为“已有真实正文资产才锁定”。
- 空章节、自动创建的章节记录和仅有小纲不再锁定目标规模，避免用户刚进入写字台后就无法调整项目目标。
- 后端 `/projects/{pid}/content-state` 新增 `tempDrafts` 统计，并将 `hasChapterContent` 定义为：存在含正文状态的章节、正文/候选版本或临时草稿。
- 后端更新项目时同样使用真实正文资产判断，防止前端放开后后端仍因空章节误拦截。
- 项目库首页和项目详情页编辑弹窗统一使用 `hasChapterContent` 判断是否锁定，并在提示中分别显示含正文状态章节、正文/候选版本、临时草稿数量。

### 修改文件
- `backend/routers/projects.py`
- `frontend/src/views/HomeView.vue`
- `frontend/src/views/ProjectView.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- backend/routers/projects.py frontend/src/views/HomeView.vue frontend/src/views/ProjectView.vue PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过，仅有既有 CRLF 提示。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

### 当前决策
- 目标字数和目标章节数属于项目规划尺度；只有在真实写作内容已经产生后才锁定。空章节和小纲可以随目标规模调整继续滚动规划。

## 2026-05-20 - 写字台 AI 操作上下文加载保护

### 本次完成
- 写字台新增章节加载、上下文加载和上下文就绪状态，顶部会显示“正在加载章节资料 / 正在加载创作上下文 / 创作上下文尚未就绪”。
- AI 工具面板在上下文未就绪时禁用小纲、正文生成、多候选、对比、续写、扩写和选区改写等会读取创作上下文的操作。
- 关键 AI 操作函数增加二次保护：即使通过事件或弹窗触发，也会先确认上下文已加载；未就绪时阻止执行，避免空上下文进入模型。
- 如果上下文尚未标记为已加载，会先尝试重新加载；加载失败时给出错误提示并阻止 AI 操作。
- 上下文预览按钮在上下文未就绪时禁用，避免用户误以为空白预览就是实际将注入的资料。

### 修改文件
- `frontend/src/views/WriterView.vue`
- `frontend/src/components/writer/AIActionPanel.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- frontend/src/views/WriterView.vue frontend/src/components/writer/AIActionPanel.vue PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过，仅有既有 CRLF 提示。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

### 当前决策
- 正文生成、小纲、多候选、对比、续写、扩写和选区改写都必须等待写作上下文加载完成；压缩场景不依赖上下文，但仍受当前生成状态保护。

## 2026-05-20 - 多候选版本拆分增强

### 本次完成
- 多候选生成 Prompt 改为要求模型使用固定分隔协议：`<<<VARIANT:版本名>>>` 与 `<<<END_VARIANT>>>`，减少多个候选粘连成一个版本的概率。
- 新增 `parseMultiVariantText` 本地解析器，优先识别固定分隔协议；如果模型未完全遵守，也兼容 Markdown 标题、`版本一/版本二/版本三`、`【稳妥推进版】` 等常见格式。
- 多候选保存逻辑改为基于解析后的 `{ label, content }` 列表创建版本，每个候选单独清理正文标题和解释性文字。
- 解析失败时仍保留兜底：把完整结果保存为一个“候选”，避免生成结果丢失。

### 修改文件
- `frontend/src/prompts/chapter.js`
- `frontend/src/stores/writerStore.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `node --input-type=module -e "...parseMultiVariantText..."` 冒烟测试通过，固定分隔符、Markdown 标题和版本编号三种格式都能拆出 3 个候选。
- `git diff --check -- frontend/src/prompts/chapter.js frontend/src/stores/writerStore.js PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过，仅有既有 CRLF 提示。

### 当前决策
- 多候选版本属于候选区资产，即使解析器只能兜底保存一个版本，也不能自动覆盖草稿或定稿。

## 2026-05-20 - 圣经/种子设定初始化分类型提取

### 本次完成
- 圣经/种子到设定库初始化从单次大模型提取升级为分类型批次提取，依次处理人物、势力/组织、世界规则/能力体系、地点/物品和长期关系。
- 每个批次只要求模型提取当前类型，并把前面批次已提取候选作为去重上下文，降低长篇种子过长导致的 JSON 截断、偏科和重复创建风险。
- 长期关系批次只允许输出 relationship，避免把关系误存成实体；非关系批次默认只保留 new_entity。
- 新增初始化候选合并去重逻辑：同名同类型实体不重复创建，关系按来源、目标和关系类型去重；已有正式设定库中的同名实体不会重复进入初始化候选。
- 保留原有保守兜底：所有分类型提取都失败或为空时，仍会基于圣经和选中种子生成保守版待确认候选，但不会自动写入正式设定。

### 修改文件
- `frontend/src/prompts/settingsFromBible.js`
- `frontend/src/stores/settingStore.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- frontend/src/prompts/settingsFromBible.js frontend/src/stores/settingStore.js PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过，仅有既有 CRLF 提示。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

### 当前决策
- 项目初始化提取和章节定稿增量提取继续保持分离：初始化可以读取圣经和种子并分批提取；章节定稿后只能基于本章正文和已有设定库做增量候选，不允许重新扫描圣经覆盖正式设定。

## 2026-05-20 - 设定库上下文相关性排序

### 本次完成
- 写字台设定库上下文从单纯按重要度排序，升级为“本章相关性优先 + 重要度兜底”。
- 相关性评分会参考本章目标、当前分卷目标/冲突/阶段摘要、分卷关键人物、最近已确认设定变更、实体首末出现章节、实体位置/归属/持有者等信息。
- 关系注入从“只保留两端都在高重要度实体内”调整为“任一端与当前上下文相关即可进入候选关系”，并按两端相关性和重要度排序。
- 重要度仍保留为排序兜底，避免当前章节缺少明确线索时上下文为空。

### 修改文件
- `frontend/src/utils/contextBuilder.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- frontend/src/utils/contextBuilder.js PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

### 当前决策
- 长篇写作上下文不能长期塞入全书最高重要度设定，而应优先服务当前章节和当前分卷，减少无关设定稀释模型注意力。

## 2026-05-20 - 章节小纲备份迁移闭环

### 本次完成
- `schema.sql` 补入 `chapter_beat_plans` 表，保证新环境按 schema 初始化时包含章节小纲表。
- 全量导出新增 `chapterBeatPlans`，项目备份会包含每章已确认/已保存小纲。
- 全量导入新增 `chapterBeatPlans` 还原逻辑，导入新项目时重新绑定新项目 ID，并按新项目 ID + 章节号生成小纲记录 ID。
- 删除项目时同步清理 `chapter_beat_plans`，避免删除项目后遗留孤儿小纲数据。

### 修改文件
- `backend/schema.sql`
- `backend/routers/export.py`
- `backend/routers/projects.py`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- backend/schema.sql backend/routers/export.py backend/routers/projects.py frontend/src/prompts/settingExtraction.js frontend/src/stores/memoryStore.js PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

### 当前决策
- 章节小纲属于章节级创作资产，必须随项目备份、导入和删除生命周期一起流转。

## 2026-05-20 - 定稿设定增量提取 JSON 解析增强

### 本次完成
- 章节定稿后的设定变更提取 Prompt 改为要求输出 `{ "settingChanges": [] }` 对象，减少 JSON mode 与数组顶层结构冲突。
- 增加专用解析器，兼容模型返回数组、`settingChanges`、`settings`、`changes`、`data`、`items`、`events`、`results` 等常见顶层字段。
- 增加 Markdown 代码块清理和均衡 JSON 块扫描，避免前后解释文字干扰解析。
- 增加一次 JSON 修复调用：只修复模型已经输出的候选，不新增、不脑补；修复后仍只进入章节定稿增量提取链路。
- 保持和“圣经/种子初始化提取”分离：本次没有复用初始化兜底生成，也不从圣经重新扫描覆盖正式设定。

### 修改文件
- `frontend/src/prompts/settingExtraction.js`
- `frontend/src/stores/memoryStore.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- frontend/src/prompts/settingExtraction.js frontend/src/stores/memoryStore.js PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

### 当前决策
- 定稿设定增量提取可以修复模型 JSON 结构，但不能在解析失败时本地伪造设定候选；没有可靠候选时返回空数组，由用户通过摘要、审稿或手动设定维护补充。

## 2026-05-20 - 多模型对比接入完整章节上下文

### 本次完成
- 写字台多模型对比改为必须基于当前确认小纲启动。
- 点击“对比”时，如果本章已有小纲，直接使用该小纲和写字台完整上下文打开多模型对比。
- 如果本章没有小纲，先生成小纲并打开确认弹窗；用户点击“开始多模型对比”后才启动候选生成。
- 多模型对比弹窗不再自行临时构建简化上下文，而是接收写字台统一组装后的上下文，包含创作种子、设定库、分卷上下文、顺序规则和未完成纠偏任务。
- 切换章节时会关闭当前对比弹窗并清空旧章节的对比上下文，避免跨章节误用。

### 修改文件
- `frontend/src/views/WriterView.vue`
- `frontend/src/components/writer/CompareModal.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- frontend/src/views/WriterView.vue frontend/src/components/writer/CompareModal.vue PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

### 当前决策
- 多模型对比属于章节正文候选生成链路，必须和“生成本章”“生成多候选版本”一样遵守小纲确认和完整上下文注入规则。
- 对比结果仍只进入候选版本/对比池，不自动覆盖当前草稿或正式定稿。

## 2026-05-20 - 项目当前章节进度同步

### 本次完成
- `projectStore` 新增 `updateCurrentChapterNum`，用于只向前推进项目当前章节号，不回退旧章节。
- 写字台生成单章候选、多候选版本、纠偏候选后，会同步项目 `currentChapterNum`。
- 用户确认定稿后，也会同步项目 `currentChapterNum`，保证导入旧候选或手动定稿时进度仍能更新。
- 同步失败不会阻断候选生成或定稿流程，只记录警告，避免因为项目进度更新失败污染正文生成结果。

### 修改文件
- `frontend/src/stores/projectStore.js`
- `frontend/src/stores/writerStore.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- frontend/src/views/WriterView.vue frontend/src/components/writer/CompareModal.vue frontend/src/stores/projectStore.js frontend/src/stores/writerStore.js PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

### 当前决策
- 当前章节号代表“项目已经推进到的最远写作章节”，只能向前推进，不因修订旧章节或旧章节纠偏而回退。

## 2026-05-20 - 章节小纲持久化

### 本次完成
- 新增章节级小纲持久化表 `chapter_beat_plans`，按项目和章节号唯一保存小纲。
- 新增后端接口：读取、保存、删除章节小纲。
- 前端 API 与写作台 store 接入小纲读写。
- 写字台加载章节时恢复已保存小纲。
- AI 生成或重新生成小纲后自动保存。
- 小纲确认弹窗新增“保存小纲”，用户手动修改后可落库。
- 点击“开始生成本章”或“生成多候选版本”前，会先保存当前确认的小纲。

### 修改文件
- `backend/database.py`
- `backend/routers/chapters.py`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/views/WriterView.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- backend/database.py backend/routers/chapters.py frontend/src/api/db/client.js frontend/src/stores/writerStore.js frontend/src/views/WriterView.vue PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

## 2026-05-20 - 写作台上下文预览增强

### 本次完成
- 上下文预览弹窗新增“复制全部上下文”。
- 每个上下文模块新增单独复制按钮，便于排查某一块资料是否正确注入。
- 缺失项从纯文本提示改为可点击入口，可跳转到创作种子、创作圣经、章节管理、设定库或纠偏任务模块补资料。
- 写字台接收上下文预览跳转事件，自动回到项目页对应标签。
- 项目页支持 `?tab=xxx` 查询参数打开指定模块，并在用户切换标签时同步地址栏。

### 修改文件
- `frontend/src/components/writer/ContextPreviewModal.vue`
- `frontend/src/views/WriterView.vue`
- `frontend/src/views/ProjectView.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- frontend/src/components/writer/ContextPreviewModal.vue frontend/src/views/WriterView.vue frontend/src/views/ProjectView.vue PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

## 2026-05-20 - 圣经提取设定库兜底修复

### 本次完成
- 修复“从创作圣经提取到设定库”在 AI 返回 JSON 被截断或格式损坏时直接失败的问题。
- 圣经提取解析失败且 JSON 修复仍失败时，会基于当前创作圣经和当前选中种子生成保守版设定候选，避免用户卡死。
- 保守版候选优先提取长篇后续必需追踪的实体：主角、关键人物、核心组织、世界底层规则、理念派系和明确关系。
- 优化圣经提取 Prompt，要求 `profilePatch` 字段保持短值，减少模型把整段原文塞进 JSON 导致截断。

### 修改文件
- `frontend/src/prompts/settingsFromBible.js`
- `frontend/src/stores/settingStore.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check -- frontend/src/prompts/settingsFromBible.js frontend/src/stores/settingStore.js PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md` 通过。
- Vite 仍提示 `writerStore` 同时被动态和静态导入，这是既有非阻塞警告。

### 后续边界补充
- 圣经/种子提取到设定库只用于项目初始阶段，属于初始化提取。
- 后续章节定稿后的设定更新属于章节增量提取，只读取本章定稿正文和已有设定库。
- 两条流程最终都进入待确认设定变更，但触发时机、上下文来源和禁止事项必须区分，避免后续开发把初始化逻辑用于覆盖已写章节设定。

## 2026-05-20 - 写作流程风险排查记录

### 本次完成
- 全面排查当前规划、已开发功能和关键数据流，重点检查会影响实际写作连续性的链路。
- 确认整体方向仍按“选题 → 种子 → 圣经 → 设定库 → 章节小纲 → 正文生成 → 定稿入库 → 审稿纠偏 → 下一章生成”推进。
- 发现一批待修复风险，已同步到本文件顶部“下一步任务”和 `PRODUCT_DEVELOPMENT_PLAN.md` 的 v1.0 待修复风险。

### 重点风险
- 多模型试写对比目前可能绕过完整上下文和当前确认小纲。
- 项目 `currentChapterNum` 可能没有随生成/定稿同步更新。
- 章节定稿后的设定增量提取解析能力不如圣经初始化提取稳健。
- 章节小纲未完全进入 schema、导入导出和删除清理链路。
- 设定库上下文注入目前偏全局重要度，后续长篇需要改为本章相关性优先。
- 圣经/种子初始化到设定库分类型提取已在后续开发中完成。
- 多候选版本拆分、上下文加载保护、项目目标锁定规则和忽略状态语义仍需后续复核。

### 当前决策
- 本轮只记录和同步，不做代码修复。
- 等用户明确通知后，再按顶部下一步任务顺序执行修复。

## 2026-05-17 - AI 设定提取与确认入库闭环

### 本次完成
- 新增专门的设定变更提取 Prompt：`settingExtraction.js`。
- 定稿后的记忆流程新增“设定库变更提取”，覆盖新人物、势力、地点、修炼体系、功法、物品和关系变化。
- AI 提取结果不直接写入正式设定库，而是保存为 `pending_review` 待确认变更。
- 后端新增确认 / 拒绝接口：
  - `POST /projects/{pid}/settings/change-events/{cid}/accept`
  - `POST /projects/{pid}/settings/change-events/{cid}/reject`
- 确认变更后会自动创建或更新设定实体。
- relationship 类型变更确认后会自动创建或更新实体关系。
- 前端设定库“确认”按钮改为真正写入设定库，确认后会选中新创建 / 更新的实体。
- 待确认变更展示增加说明：确认后写入正式设定库，拒绝则不入库。
- Vite 配置固定 `root`，修复 Windows/Rolldown 构建时把 HTML 入口解析成绝对输出路径的问题。

### 修改文件
- `backend/routers/settings_library.py`
- `frontend/src/prompts/settingExtraction.js`
- `frontend/src/stores/memoryStore.js`
- `frontend/src/stores/settingStore.js`
- `frontend/src/api/db/client.js`
- `frontend/src/components/settings-library/SettingLibrary.vue`
- `frontend/vite.config.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd run build`（工作目录 `frontend`）通过。
- `npm.cmd --prefix frontend run build` 通过。
- 已重启 FastAPI：`http://127.0.0.1:8000`。
- `/api/health` 返回 `ok=True`。
- 前端 `http://127.0.0.1:5173/` 返回 HTTP 200。
- 临时 new_entity 变更验证通过：确认后自动创建实体并写入 `profile.realm`，临时数据已清理。
- 临时 relationship 变更验证通过：确认后自动创建两端实体和关系，临时数据已清理。

### 当前决策
- AI 不直接改正式设定库，所有提取结果必须先进入待确认列表。
- 确认操作由后端执行实体创建 / 更新，避免前端状态和数据库状态不一致。
- 新实体的 `newValue` 使用 JSON 字符串携带 summary、category、importance、profile、tags；关系变更的 `newValue` 使用 JSON 字符串携带 targetEntityName、targetEntityType、relationType、stance、summary。

### 未完成 / 阻塞
- 待确认变更目前只能确认 / 拒绝，尚未支持确认前逐条编辑。
- AI 提取效果需要用真实章节内容验证，尤其要观察是否过度提取路人或漏掉关键设定。

### 下一步
- 浏览器端用真实章节定稿跑一次完整流程：正文定稿 → AI 提取待确认设定 → 确认入库 → 下一章生成上下文查看。
- 增加待确认变更的编辑弹窗，让用户确认前可以改字段路径、实体名和新值。

## 2026-05-17 - v0.6 设定库第一条可用竖切

### 本次完成
- 后端新增 `setting_entities`、`setting_relations`、`setting_change_events` 三张表，启动 FastAPI 时自动创建缺失表。
- 新增设定库 REST API：实体、关系、设定变更的列表、新增、更新、删除。
- 导入导出加入设定库数据，项目包 JSON 会包含设定实体、关系和变更日志。
- 前端新增 `settingStore` 和 API 客户端封装。
- 项目页新增“设定库”一级标签。
- 新增 `SettingLibrary` 页面：支持人物、势力、地点、体系、功法、物品六类档案；支持关系管理；支持查看和处理待确认设定变更。
- 写作台上下文构建器接入设定库，会把高重要度活跃设定、关键关系、最近已确认设定变化注入章节生成 prompt。
- 写作台右侧“上下文记忆”面板新增关键设定和最近设定变化速览。
- 定稿后的记忆处理会基于摘要中的人物变化生成待确认设定变更记录。

### 修改文件
- `backend/database.py`
- `backend/main.py`
- `backend/schema.sql`
- `backend/routers/helpers.py`
- `backend/routers/export.py`
- `backend/routers/settings_library.py`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/settingStore.js`
- `frontend/src/components/settings-library/SettingLibrary.vue`
- `frontend/src/views/ProjectView.vue`
- `frontend/src/views/WriterView.vue`
- `frontend/src/utils/contextBuilder.js`
- `frontend/src/prompts/chapter.js`
- `frontend/src/components/writer/ContextMemoryPanel.vue`
- `frontend/src/stores/memoryStore.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- 已重启 FastAPI：`http://127.0.0.1:8000`。
- `/api/health` 返回 `ok=True`。
- 设定库实体接口 GET 可访问，返回空列表。
- 设定库实体接口 POST / DELETE 临时数据验证通过，临时数据已删除。
- Vite 前端 `http://127.0.0.1:5173/` 返回 HTTP 200。

### 当前决策
- v0.6 第一版采用通用实体表，而不是为人物、势力、地点、功法分别建大量专表；这样能先覆盖长篇创作的主要设定记忆，后续再按使用频率拆分或加专用字段。
- 设定库主数据源是 `setting_entities`，旧 `characters` 继续服务人物弧光等历史功能。
- 第一版确认 / 拒绝设定变更先作为日志状态处理；下一步再实现“确认后自动写入实体字段”。

### 未完成 / 阻塞
- 需要浏览器端目视验证设定库页面布局和表单体验。
- 待确认设定变更目前不会自动应用到实体字段，需要下一步补齐。
- AI 提取设定变化还复用摘要结果，尚未做专门的设定变更提取 prompt。

### 下一步
- 在浏览器中创建一个人物、一个宗门、一个地点和一个境界体系，验证写作台上下文记忆能显示并注入。
- 实现设定变更确认后的实体字段更新逻辑。

## 2026-05-17 - v0.6 设定库与世界观一致性规划

### 本次完成
- 将“设定库与世界观一致性系统”加入产品规划，作为长篇小说核心记忆模块。
- 明确创作圣经与设定库的边界：创作圣经保存作品级总纲，设定库保存实体级资料和状态变化。
- 规划人物档案、势力档案、世界观档案、修炼 / 能力体系、关系图谱、状态变更日志。
- 规划章节定稿后的同步流程：AI 提取候选设定变化 → 用户确认 / 编辑 / 拒绝 → 写入设定库 → 下一章上下文注入。
- 将 v1.0 验收前增加 v0.6 补强阶段，避免在人物、功法、势力、地理等长篇核心设定未结构化前进入稳定版验收。

### 修改文件
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本次为产品规划和开发记录更新，未修改代码，暂不需要运行构建。

### 当前决策
- 设定库不做开局强制百科填写，采用“最小设定启动，边写边更新，定稿后确认入库”。
- 人物弧光、伏笔看板等视图可以保留，但不作为主数据源。
- 第一版不做复杂地图编辑器、重型知识图谱可视化、向量库依赖，也不允许 AI 未经确认自动覆盖正式设定。

### 未完成 / 阻塞
- 需要确认 v0.6 的界面入口和第一批最小字段。
- 需要开始数据库表结构、API 和前端实现规划。

### 下一步
- 设计 v0.6 实施方案：表结构、后端接口、前端页面、写作台接入点、定稿入库流程、上下文构建器改造。

## 2026-05-15 23:45 - 固化开发规划 Skill

### 本次完成
- 创建本地 Codex skill：`project-development-planning`。
- Skill 用于在新项目中快速生成开发规划、版本路线、执行协议和 `DEVELOPMENT_LOG.md`。
- 触发语覆盖“开发规划1”、“新项目开发规划”、“固定开发规范”、“版本规划”、“开发日志”、“防止上下文压缩断层”等场景。

### 修改文件
- `C:\Users\zhangjun\.codex\skills\project-development-planning\SKILL.md`
- `C:\Users\zhangjun\.codex\skills\project-development-planning\agents\openai.yaml`
- `D:\Projects\Novel_Creater\DEVELOPMENT_LOG.md`

### 验证结果
- 已运行 `quick_validate.py`。
- 校验结果：`Skill is valid!`

### 当前决策
- 后续新项目可直接要求使用 `project-development-planning` 或说“执行开发规划1”。
- Skill 默认生成或更新 `PROJECT_PLAN.md` 与 `DEVELOPMENT_LOG.md`。
- 如果项目已有 `CLAUDE.md`、`AGENTS.md` 或用户指定规划文件，则优先更新已有文件，避免重复规划。

### 未完成 / 阻塞
- 无。

### 下一步
- 当前项目继续从 `v0.1 本地地基版` 开始开发。

## 2026-05-16 00:20 - v0.2 AI 创作闭环版

### 本次完成
- 创建完整 Prompt 系统（9 个 prompt 模块）：种子生成、章节生成、脑洞发散、大纲规划、选区重写、章节摘要、事实提取、一致性审稿、风格分析。
- 实现 seedStore：创意种子 CRUD、AI 批量生成种子、种子选中/归档。
- 实现 novelStore：创作圣经管理、滚动大纲管理、角色管理、伏笔线索管理、Canon 事实管理（确认/拒绝）、可能性池管理。
- 实现 writerStore：章节管理、版本管理（AI 候选/用户草稿/润色/定稿/存档）、自动保存 tempDraft、AI 章节生成、AI 续写、多候选版本生成、选区重写、扩写、压缩、确认定稿。
- 创建 SeedWorkbench 组件：手动创建种子、AI 批量生成种子、种子详情查看、种子选择、从种子一键创建创作圣经。
- 创建 SeedCard 组件：种子卡片展示（题材标签、来源标签、选中状态）。
- 创建 CreativeBible 组件：创作圣经编辑/查看面板（作品定位、风格要求、主题母题、世界规则、禁止方向）。
- 创建 AIActionPanel 组件：所有 AI 操作按钮面板（生成章节、多候选、续写、扩写、压缩、选区改写等）。
- 创建 ChapterVersionList 组件：版本列表展示、版本切换加载、定稿确认、版本删除。
- 重写 WriterView 为完整写作台：三栏布局（章节列表 + 编辑器 + AI 工具面板）、自动保存草稿（2 秒防抖）、选区检测、上下文构建器集成、TXT/Markdown 导出。
- 实现 contextBuilder 工具：按任务类型和 token 预算构建 AI 上下文，不同优先级的内容注入策略。
- 实现 export 工具：全书 TXT 导出、全书 Markdown 导出、文件下载。
- 重写 ProjectView 为项目仪表板：Tab 页（章节管理/创作种子/创作圣经）、章节列表（状态标签、字数、摘要）、快速进入写作台。

### 修改文件
- 新建：`src/prompts/seed.js`、`chapter.js`、`brainstorm.js`、`outline.js`、`rewrite.js`、`summary.js`、`extraction.js`、`audit.js`、`style.js`
- 新建：`src/stores/seedStore.js`、`src/stores/novelStore.js`、`src/stores/writerStore.js`
- 新建：`src/components/seed/SeedWorkbench.vue`、`SeedCard.vue`
- 新建：`src/components/bible/CreativeBible.vue`
- 新建：`src/components/writer/AIActionPanel.vue`、`ChapterVersionList.vue`
- 新建：`src/utils/contextBuilder.js`、`src/utils/export.js`
- 修改：`src/views/WriterView.vue` - 完整重写为写作台
- 修改：`src/views/ProjectView.vue` - 重写为项目仪表板
- 修改：`DEVELOPMENT_LOG.md` - 更新状态和版本进度

### 验证结果
- `npm run build` 成功，生成 dist 目录，所有新增模块编译通过。
- 构建产物：WriterView (22.96KB gzip:7.83KB)、ProjectView (47.90KB gzip:13.55KB)、CreativeBible (27.19KB gzip:10.06KB)。
- Dev server 启动正常（http://localhost:5173/）。
- 未在浏览器中进行完整 UI 验证（headless 环境）。

### 当前决策
- 写作台采用三栏布局：左（章节列表）中（编辑器）右（AI 操作 + 版本列表）。
- 编辑器使用 NInput type="textarea"（纯文本），字体使用 Georgia/Noto Serif SC，行高 1.8。
- 自动保存采用 2 秒防抖，保存到 tempDrafts 表。
- AI 生成内容默认进入 ai_candidate 版本，不直接覆盖正式稿。
- 定稿操作需要用户点击确认。
- 种子和圣经通过 ProjectView 内的 Tab 页访问，不增加独立路由。
- 写作台支持在写作视图和圣经视图之间切换（顶部按钮）。

### 未完成 / 阻塞
- 记忆与审稿系统未实现（v0.3）：章节摘要自动生成、Canon 事实提取、角色状态提取、伏笔提取、待确认变更面板、一致性检查。
- 上下文构建器已有基础实现，但未在实际 AI 调用中充分集成 token 预算裁剪。
- 角色管理和伏笔管理 UI 未创建（数据层已就绪）。
- 可能性池 UI 未创建（数据层已就绪）。
- 滚动大纲 UI 未创建（数据层已就绪）。
- 选题雷达未开始（v0.4）。
- 未在浏览器中手动验证完整 UI 流程。

### 下一步
- 开始 v0.3 记忆与审稿版：章节摘要自动生成、Canon 事实提取、角色状态提取、待确认变更面板、一致性检查。
- 或先进行浏览器端 UI 手动验证，确保 v0.2 功能可用后再进入 v0.3。

## 2026-05-15 23:53 - v0.1 本地地基版

### 本次完成
- 初始化 Vite + Vue 3 项目，安装 Naive UI、Tailwind CSS 4、Pinia、Vue Router 4、Dexie.js、uuid。
- 配置 Tailwind CSS 4（@tailwindcss/vite 插件）、`@/` 路径别名、中文 Naive UI。
- 建立基础目录结构：api/ai、components/layout、components/settings、stores、views、router、utils。
- 建立 Dexie 数据库，完整定义 14 张表的 schema（projects、providerProfiles、taskModelBindings、chapters、chapterVersions 等），为后续功能预留表结构。
- 实现项目库基础能力：新建、打开、删除、更新、持久化（projectStore.js）。
- 实现项目 JSON 导出与导入（exportProjectJson / importProjectJson）。
- 实现 Provider 配置基础能力：新增、编辑、删除、持久化（providerStore.js）。
- 实现 Claude 原生适配器（AnthropicAdapter）和 OpenAI-compatible 通用适配器（OpenaiCompatibleAdapter），均实现 chatCompletion 和 testConnection。
- 实现模型连通性测试（通过 ProviderSettings 的"测试连接"按钮触发）。
- 实现任务模型映射基础版（TaskModelBinding 组件）。
- 建立基础路由：HomeView、SettingsView、ProjectView、WriterView。
- 建立基础布局：Sidebar（含项目库菜单、当前项目菜单、返回按钮）、TopBar（面包屑导航）。
- 创建 jsconfig.json 支持 IDE 路径别名解析。

### 修改文件
- `package.json` - 更新项目名称为 novel-creater，添加所有依赖
- `vite.config.js` - 添加 Tailwind 插件、`@/` 路径别名
- `index.html` - 更新标题为中文
- `src/main.js` - 引入 Pinia + Vue Router
- `src/App.vue` - 完整布局：Naive UI ConfigProvider + Sidebar + TopBar + RouterView
- `src/style.css` - 引入 Tailwind，重置基础样式
- `src/utils/db.js` - Dexie 数据库完整 schema
- `src/utils/id.js` - UUID 生成工具
- `src/router/index.js` - 路由配置（Home、Project、Writer、Settings）
- `src/stores/projectStore.js` - 项目库 Store（CRUD + 导入导出）
- `src/stores/providerStore.js` - Provider Store（CRUD + 任务模型映射）
- `src/components/layout/Sidebar.vue` - 侧边栏导航
- `src/components/layout/TopBar.vue` - 顶部面包屑
- `src/components/settings/ProviderSettings.vue` - Provider 列表 + 测试连接
- `src/components/settings/ProviderForm.vue` - Provider 新增/编辑表单
- `src/components/settings/TaskModelBinding.vue` - 任务模型映射面板
- `src/views/HomeView.vue` - 项目库主页（列表 + 新建 + 删除 + 导出 + 导入）
- `src/views/ProjectView.vue` - 项目详情页
- `src/views/WriterView.vue` - 写作台（纯 textarea）
- `src/views/SettingsView.vue` - 设置页
- `src/api/ai/adapterBase.js` - 适配器基类
- `src/api/ai/anthropicAdapter.js` - Claude 原生适配器
- `src/api/ai/openaiCompatibleAdapter.js` - OpenAI-compatible 通用适配器
- `src/api/ai/providerPresets.js` - Provider 预设配置
- `src/api/ai/index.js` - AI 适配器导出入口
- `jsconfig.json` - IDE 路径别名支持

### 验证结果
- `npm run build` 成功，生成 dist 目录。
- 构建产物包含所有视图组件和适配器代码，无报错。
- 未运行 `npm run dev` 实际 UI 验证（headless 环境）。

### 当前决策
- 不使用 `NTextarea`（Naive UI 中不存在该组件），改用 `NInput type="textarea"`。
- Tailwind CSS 4 通过 `@tailwindcss/vite` 插件引入，无需 `tailwind.config.js` 和 `postcss.config.js`。
- ProviderForm 的保存/取消按钮直接放在组件内 div 中，而非使用插槽（避免 Vue 3 模板编译错误）。
- 适配器默认写入 `providerPresets.js` 中预设多个常用服务的 baseURL 和模型 ID，用户可修改。

### 未完成 / 阻塞
- 正文编辑器当前为纯 textarea，缺少自动保存、AI 生成等功能（属于 v0.2）。
- 章节系统（chapters、chapterVersions 表已建）未实现 UI（属于 v0.2）。
- 选题雷达、角色系统、伏笔系统均未开始（v0.3-v0.4）。
- 未在浏览器中手动验证 UI 渲染（后续需要 visual test）。

### 下一步
- 验证 dev server 启动正常（`npm run dev`）。
- 如果编译无误，可以开始 v0.2 AI 创作闭环版开发。

### 本次完成
- 将主规划文档从 `CLAUDE (1).md` 重命名为 `PRODUCT_DEVELOPMENT_PLAN.md`。
- 更新开发日志中的主规划文档引用。
- 增加“文档入口”小节，方便后续 Claude Code 或其他开发工具快速定位核心文档。

### 修改文件
- `D:\Projects\Novel_Creater\PRODUCT_DEVELOPMENT_PLAN.md`
- `D:\Projects\Novel_Creater\DEVELOPMENT_LOG.md`

### 验证结果
- 已确认旧文件名引用已从开发日志交接入口更新为新文件名。

### 当前决策
- 后续统一把 `PRODUCT_DEVELOPMENT_PLAN.md` 作为产品与开发规划主文档。
- `DEVELOPMENT_LOG.md` 作为持续开发交接记录。

### 未完成 / 阻塞
- 无。

### 下一步
- 使用新启动提示词让 Claude Code 从 `v0.1 本地地基版` 开始开发。

## 2026-05-16 00:45 - v0.3 记忆与审稿版

### 本次完成
- 实现 memoryStore：AI 驱动的章节摘要自动生成、Canon 事实提取、一致性审稿。支持从章节内容中自动提取角色变化和新角色。定稿后自动触发记忆管道（摘要→事实提取→审稿→角色状态更新→新角色创建→章节摘要保存）。
- 创建 CanonReviewPanel：展示 AI 提取的待确认事实列表（按类型分组：世界观/角色/情节/关系/时间线/风格）。用户可逐条确认、编辑后确认或忽略。显示信心分数。展示已确认记忆历史。
- 创建 ContextMemoryPanel：写作台上下文记忆面板。展示主要角色硬状态/软状态速览、进行中的伏笔、世界规则摘要、禁止方向。为空状态提供引导文案。
- 增强 contextBuilder：实现 ContextBuilder 类，支持优先级预算管理（P1-P10）、必须项（required）、token 上限裁剪（maxTokens）、低优先级项超出预算自动跳过。为不同任务类型预设预算（writing:12k, brainstorm:4k, audit:16k, summary:8k, extraction:8k, outline:8k）。角色和事实在超出预算时自动简化字段集。
- 实现一致性审稿功能：写作台顶部新增"审稿"按钮，调用 audit prompt，在弹窗中展示分级问题列表（critical/major/minor/suggestion），含问题类型、位置、修改建议和原因。附带风格一致性和角色一致性评价。
- 集成记忆管道到定稿流程：用户确认定稿后自动触发 processChapterFinalization，依次执行摘要生成、事实提取、一致性审稿。提取的事实自动保存为 pending_review 状态，角色变化自动更新角色状态，新角色自动创建。结果通过 message 通知用户。
- 增强写作台右侧面板：添加"AI 工具"/"上下文"切换标签，在 AI 操作面板和上下文记忆面板之间切换。新增"记忆"顶部视图（独立全屏记忆管理页面）。

### 修改文件
- 新建：`src/stores/memoryStore.js` - 记忆提取/审稿管道
- 新建：`src/components/writer/CanonReviewPanel.vue` - 待确认记忆面板
- 新建：`src/components/writer/ContextMemoryPanel.vue` - 上下文记忆面板
- 修改：`src/utils/contextBuilder.js` - 重构为 ContextBuilder 类，增强 token 预算
- 修改：`src/views/WriterView.vue` - 集成记忆管道、审稿弹窗、上下文面板、记忆视图
- 修改：`DEVELOPMENT_LOG.md` - 更新状态

### 验证结果
- `npm run build` 成功，WriterView 从 22.96KB 增至 46.14KB（gzip: 15.11KB）。
- 所有新增模块编译通过，无报错。
- Dev server 运行正常。
- 未在浏览器中手动验证记忆提取和审稿流程。

### 当前决策
- 定稿后自动触发记忆提取管道，不强制用户手动操作。
- 记忆提取采用容错设计：某个步骤失败不影响其他步骤。
- 事实提取后默认进入 pending_review 状态，用户必须主动确认/编辑/忽略。
- 角色变化通过摘要中的 characterChanges 字段追踪，AI 负责识别变化。
- 审稿结果独立弹窗展示，不打断写作流程。

### 未完成 / 阻塞
- 角色管理 UI 未创建（数据层已就绪）。
- 伏笔管理 UI 未创建（数据层已就绪）。
- 滚动大纲 UI 未创建（数据层已就绪）。
- 可能性池 UI 未创建（数据层已就绪）。
- 选题雷达未开始（v0.4）。
- 多模型对比/融合未开始（v0.5）。
- 未在浏览器中手动验证完整 UI 流程。

### 下一步
- 开始 v0.4 选题雷达版：手动录入作品卡片、公开元数据解析、题材聚类、AI 提炼卖点、AI 生成原创选题。

## 2026-05-16 01:00 - 流式输出与 DeepSeek V4 适配修复

### 本次完成
- 修正 DeepSeek 预设：baseURL 改为 `https://api.deepseek.com`（官方文档），model 改为 `deepseek-v4-pro`，新增 `thinking` 参数支持（`{ type: 'enabled', reasoning_effort: 'high' }`），移除已弃用的 `deepseek-chat`。
- 为 OpenaiCompatibleAdapter 新增 `chatCompletionStream()` 方法：完整 SSE 解析（`text/event-stream`），逐 chunk 解析 `data: [DONE]` 终止标记，提取 `choices[0].delta.content`，支持 `readNext()` 逐块读取和 `readAll()` 全部读取，支持 `cancel()` 取消。
- 为 `buildRequestBody` 新增 DeepSeek V4 thinking 参数透传、`response_format: json_object` 支持、`stream_options.include_usage` 支持。
- 在 `index.js` 导出 `chatCompletionStream()` 函数。
- 更新 `writerStore.generateChapter()`：优先使用流式请求，失败时自动回退到非流式；支持 `onStream` 回调实时推送增量内容；实时更新 `generationStream` ref。
- 更新 `WriterView.vue`：生成章节时通过 `onStream` 回调实时更新编辑器内容；新增"流式生成中"动画指示器（绿色脉冲圆点）。

### 修改文件
- 修改：`src/api/ai/providerPresets.js` - DeepSeek 预设修正
- 修改：`src/api/ai/openaiCompatibleAdapter.js` - 新增流式支持 + thinking 参数
- 修改：`src/api/ai/index.js` - 导出 chatCompletionStream
- 修改：`src/stores/writerStore.js` - generateChapter 使用流式 + 回退
- 修改：`src/views/WriterView.vue` - 流式实时更新 + 指示器

### 验证结果
- `npm run build` 成功，所有模块编译通过。

### 当前决策
- 流式输出优先使用，失败时自动回退到非流式（兼容不支持 stream 的老接口）。
- 流式内容通过 `onStream` 回调实时推送到 UI，不做缓冲批量更新。
- DeepSeek thinking 参数通过 provider 配置或 options 透传，不硬编码。
- 流式请求可被 `cancel()` 取消（用户切换到其他章节等场景）。

### 下一步
- 开始 v0.4 选题雷达版。

## 2026-05-16 01:30 - IndexedDB → FastAPI + MySQL 迁移

### 本次完成
- 目录重组：前端文件统一归入 `frontend/`，后端文件在 `backend/`。
- 创建 MySQL Schema（14 张表，utf8mb4，LONGTEXT 存正文，JSON 存数组/对象字段）。
- 创建 FastAPI 后端：入口 `main.py` + CORS + 6 个路由模块（projects、providers、chapters、seeds、novel、export），覆盖全部 CRUD + 全量导入导出。
- 创建前端 API 客户端层 `src/api/db/client.js`：封装所有 HTTP 请求，提供与 Dexie 相似的接口（list/create/get/update/delete）。
- 重构全部 6 个 Store：projectStore、providerStore、seedStore、novelStore、writerStore、memoryStore — Dexie 调用全部替换为 API 调用。
- 更新 export.js 和 backup.js：通过 API 客户端获取数据，不再直接读 IndexedDB。
- 修复 memoryStore.getProvider() 中 getBindings 调用缺少 await 的 bug。

### 修改文件
- 新建：`backend/main.py`、`config.py`、`database.py`、`schema.sql`、`requirements.txt`
- 新建：`backend/routers/__init__.py`、`projects.py`、`providers.py`、`chapters.py`、`seeds.py`、`novel.py`、`export.py`
- 新建：`frontend/src/api/db/client.js`
- 移动：`src/` → `frontend/src/`、`public/` → `frontend/public/`、`index.html`、`package.json`、`vite.config.js`、`jsconfig.json`、`node_modules/`
- 修改：`frontend/src/stores/projectStore.js`、`providerStore.js`、`seedStore.js`、`novelStore.js`、`writerStore.js`、`memoryStore.js`
- 修改：`frontend/src/utils/export.js`、`backup.js`

### 验证结果
- `npm run build` 成功，主包从 484KB 降至 389KB（移除 Dexie）。
- MySQL schema 已执行，14 张表创建完毕。
- FastAPI 后端启动正常（http://127.0.0.1:8000）。
- 未在浏览器中验证完整前后端联通。

### 当前决策
- 前端通过 `http://localhost:8000/api` 访问后端。
- AI 调用仍走浏览器直连（不经过后端 AI Gateway）。
- CORS 仅允许 localhost:5173。
- MySQL 连接池使用 aiomysql，自动管理生命周期。
- 旧 IndexedDB 数据可通过后端 `/api/import/full` 导入 MySQL。

### 下一步
- 启动方式：先启动 FastAPI（`cd backend && uvicorn main:app --port 8000`），再启动前端（`cd frontend && npm run dev`）。
- 开始 v0.4 选题雷达版。

## 2026-05-16 02:30 - v0.4 选题雷达版

### 本次完成

**后端：网页抓取 + market_items CRUD**
- 创建 `backend/routers/market.py`（5 个 API 端点 + 页面抓取引擎）。
- `POST /api/market/scrape`：并发抓取 5 个已知可读排行榜页面（书旗、纵横、潇湘、52书库、小说阅读网），正则提取《书名》格式和作者、简介、分类元数据，写入 market_items 表。
- `GET /api/market/items?projectId=`：按项目筛选 market items。
- `POST /api/market/items`：手动创建 market item。
- `PUT /api/market/items/{mid}`：更新（存储 AI 分析结果，含 extractedHooks/extractedAppeals/aiSummary/plagiarismRiskNotes）。
- `DELETE /api/market/items/{mid}`：删除。
- 抓取策略：httpx.AsyncClient + asyncio.gather 并发请求，超时 15s，正则提取 `extract_page_info()` 补充简介/分类/作者。

**前端：选题雷达 UI + AI 对话面板**
- 创建 `frontend/src/components/market/MarketRadar.vue`：左侧卡片网格 + 右侧 AI 对话面板双栏布局。搜索栏 + 8 个预设关键词按钮、平台/分类筛选下拉框、分类统计可点击标签、2 列卡片网格、详情弹窗。
- 创建 `frontend/src/components/market/MarketCard.vue`：小说卡片（平台彩色标签、书名、作者、排名、分类标签、3 行简介截断、标签展示），底部"AI 总结"/"展开"/"删除"按钮。
- 创建 `frontend/src/components/market/AIChatPanel.vue`：对话气泡（用户右蓝/ AI 左灰）、textarea 输入（Enter 发送 / Shift+Enter 换行）、自动滚到底部、AI 回复中种子数提示、清空对话确认。欢迎消息含 3 个示例提示。
- 创建 `frontend/src/stores/marketStore.js`：items/loading/scraping/chatMessages/chatLoading 状态、scrapeMarket/loadItems/createItem/updateItem/deleteItem/analyzeItem/sendChatMessage/clearChat 方法、buildChatContext 上下文构建器。
- 创建 `frontend/src/prompts/market.js`：buildMarketChatSystemPrompt（注入市场数据 20 条、项目背景、圣经约束、已有种子）、extractSeedsFromText（正则提取 JSON 种子数组，支持 ```json 代码块和裸 JSON 数组）。

**集成与 Schema 变更**
- `backend/main.py`：注册 market 路由。
- `backend/requirements.txt`：添加 `httpx>=0.27.0`。
- `backend/schema.sql`：market_items 表增加 `project_id CHAR(36)` 列和索引。
- `frontend/src/api/db/client.js`：新增 `market` API 域（scrape/list/create/update/delete）。
- `frontend/src/views/ProjectView.vue`：新增第 4 个 TabPane "选题雷达"，引入 MarketRadar 组件。

### 修改文件
- 新建：`backend/routers/market.py`、`frontend/src/prompts/market.js`、`frontend/src/stores/marketStore.js`、`frontend/src/components/market/MarketRadar.vue`、`frontend/src/components/market/MarketCard.vue`、`frontend/src/components/market/AIChatPanel.vue`
- 修改：`backend/main.py`、`backend/requirements.txt`、`backend/schema.sql`、`frontend/src/api/db/client.js`、`frontend/src/views/ProjectView.vue`

### 验证结果
- FastAPI 后端启动正常（http://127.0.0.1:8000）。
- POST `/api/market/scrape`（keywords="热门小说"，projectId=有效 UUID）返回 count=60+ 条数据。
- GET `/api/market/items?projectId=xxx` 返回已入库数据，含 platform/category 字段。
- 前端 Vite 启动正常（http://localhost:5173），build 成功。
- 验证了 6 个小说平台可读性：shuqi.com ✓、zongheng.com ✓、xxsy.net ✓、52shuku.net ✓、readnovel.com ✓、fanqienovel.com 部分可读。
- DuckDuckGo HTML 搜索被证实不可用（httpx 请求返回 202），改为直接抓取已知排行页面。
- 未在浏览器端完整验证前后端联通和 AI 对话功能。

### 当前决策
- 抓取策略：不通过搜索引擎中转，直接并抓取已知可读的排行榜页面。未来新增平台可通过扩展 KNOWN_RANK_PAGES 列表。
- AI 对话不持久化历史（刷新即清空），只保存 AI 生成的创作种子到 creative_seeds 表。
- 种子从 AI 回复中通过正则提取 JSON 数组，自动保存到 seedStore，用户在"创作种子"标签页管理。
- 版权合规：只提取公开可见的元数据（书名、作者、简介、分类、排名），不抓取正文、付费内容或需登录的内容。

### 未完成 / 阻塞
- 浏览器端完整端到端验证（抓取 → 展示 → AI 对话 → 种子生成 → 写作台）。
- 作者提取正则可进一步优化（部分页面布局导致作者信息不准确）。
- 部分非小说条目（导航文字、分类名）被误抓，需用户手动删除。

### 下一步
- 浏览器端验证 v0.4 完整流程。
- 开始 v0.5 体验增强版。

## 2026-05-16 04:30 - v0.5 体验增强版

### 本次完成

**Phase 1：备份提醒 + 导出优化**
- 创建 `BackupReminder.vue`：挂载时读取 localStorage 上次备份时间，超 7 天显示 NAlert 提醒，调用 backup.js downloadBackup()。
- 修改 App.vue 引入 BackupReminder（TopBar 与 router-view 之间）。
- 重写 export.js：exportTxt/exportMarkdown 改为批量 Parallel fetch（Promise.all），新增 exportSelectedChapters、exportProjectBundle（bible+outline+characters+chapters JSON）。
- ProjectView 头部增加导出 n-dropdown（导出全部 TXT/MD、项目包 JSON）。
- WriterView 合并 TXT/MD 导出按钮为单个下拉。

**Phase 2：人物弧光 + 伏笔看板**
- 创建 `CharacterArcView.vue`：CSS Grid 时间线（行=角色，列=章节），格子颜色表示硬状态（蓝）、软状态（橙）、双重变更（紫）、有事实（绿）、未出现（灰）。支持角色筛选下拉框，悬停 NPopover 显示详情。
- 创建 `PlotThreadBoard.vue`：三列 Kanban（planted/developing/resolved），卡片含标题、内容预览、关联角色标签、章节标记点。n-collapse 展开详细（埋设/回收章节、备注）。顶部章节时间线。
- ProjectView 新增两个 tab："人物弧光"、"伏笔看板"，onMounted 加载 characters/plotThreads/canonFacts。

**Phase 3：风格分析 + 节奏分析**
- 创建 `StyleAnalysisPanel.vue`：7 维度指标条形图（纯 Tailwind div）、一致性评分、优点/弱项/风格近似列表。"应用为风格圣经"按钮将分析结果追加到 bible.styleBible。
- 创建 `prompts/pacing.js`：分段张力评分（1-10）、高潮定位、转折点识别、整体节奏评价。
- 创建 `PacingChart.vue`：柱状图（绿→黄→红渐变）、平均张力/高潮位置/整体节奏汇总卡、段落详情列表、转折点、节奏建议。纯 CSS 实现，无图表库。
- memoryStore 新增 analyzeStyle/analyzePacing 方法，导入 style/pacing prompt，供应商解析用现有绑定系统。
- WriterView 右侧面板增加"风格分析"和"节奏分析"按钮，结果以 NModal 展示。

**Phase 4：多模型试写对比 + 融合**
- 创建 `compareStore.js`：runningJobs（Map<providerId, {streaming, content, version, error}>）、startComparison（并行调用 writerStore.generateChapter，各模型独立流式更新）、fuseFragments（调用 chatCompletion + buildFusionPrompt）、cancelAll/clearComparison。
- 创建 `CompareModal.vue`：Step 1 多选模型（至少 2 个），Step 2 并排实时结果区（每列 280px 横向滚动），流式更新内容。完成计数 "X/Y 完成"。
- 创建 `CompareInline.vue`：右侧面板紧凑对比结果展示，点击结果加载版本到编辑器。
- 创建 `FusionPanel.vue`：左侧源版本列表，右侧融合编辑区。"智能融合"调用 compareStore.fuseFragments，保存为 ai_candidate 版本（label: "融合版"）。
- `prompts/chapter.js` 新增 buildFusionPrompt：多个候选 + 本章目标 → 合并最佳元素。
- AIActionPanel 新增"对比"按钮 + emit('compare')，生成本章与对比按钮并排。
- WriterView 集成 CompareModal/FusionPanel/CompareInline，右侧面板显示对比结果和"融合多模型版本"入口。

### 修改文件
- 新建（11）：`BackupReminder.vue`、`CharacterArcView.vue`、`PlotThreadBoard.vue`、`StyleAnalysisPanel.vue`、`PacingChart.vue`、`pacing.js`、`compareStore.js`、`CompareModal.vue`、`CompareInline.vue`、`FusionPanel.vue`
- 修改（10）：`App.vue`、`export.js`、`WriterView.vue`、`ProjectView.vue`、`AIActionPanel.vue`、`memoryStore.js`、`novelStore.js`（无变更，bible.styleProfile 通过 saveBible 文本追加实现）、`prompts/chapter.js`、`DEVELOPMENT_LOG.md`

### 验证结果
- `npm run build` 成功，主包 123KB gzip，WriterView 68KB，ProjectView 83KB。
- 所有 11 个新组件 + 5 个修改文件通过 Vite 编译。
- 未在浏览器端验证（需启动 FastAPI + Vite 端到端测试）。

### 当前决策
- 风格分析结果以文本形式追加到 bible.styleBible 字段，无需改后端 schema。
- 多模型对比直接调用 writerStore.generateChapter 生成版本，version 自动关联 sourceModelId。
- 人物弧光和伏笔看板为只读视图，数据来自现有 novelStore 的 characters/plotThreads/canonFacts。
- 导出优化使用 Promise.all 批量获取版本，避免 N+1 请求。

### 未完成 / 阻塞
- 浏览器端端到端验证所有 v0.5 功能。
- 对比结果的 model 名称显示依赖 sourceModelId 到 provider name 的映射（当前用 providerStore 查找）。

### 下一步
- 启动 FastAPI + Vite 进行浏览器端验证。
- 开始 v1.0 本地稳定版。

## 2026-05-16 23:30 - v1.0 本地稳定版

### 本次完成

全量错误处理加固，覆盖全部 6 个 Pinia Store + API 客户端 + 3 个视图 + 工具函数：

**1. API 客户端加固（`src/api/db/client.js`）**
- 添加 `AbortController` 超时机制（默认 30s）。
- 保护 `JSON.parse`，解析失败时抛出详细错误（含前 200 字符）。
- `AbortError` 转换为中文超时提示。

**2. 全部 Store 错误处理**
- `novelStore.js`：17 个方法全部添加 try/catch + console.error，`loading` ref 实际用于加载类操作。
- `writerStore.js`：12 个方法全部添加 try/catch。`saveTempDraft` 静默失败（不中断用户输入），`loadTempDraft` 失败返回 null。
- `projectStore.js`：7 个方法全部添加 try/catch。
- `providerStore.js`：6 个方法全部添加 try/catch。
- `seedStore.js`：6 个方法全部添加 try/catch。
- `marketStore.js`：修复 `buildChatContext` 中的 `.catch(() => {})` 静默吞错，`createItem`/`updateItem`/`deleteItem` 添加错误处理。
- `compareStore.js`：`fuseFragments` 添加 try/catch 和结果提取逻辑（支持 string/content/choices 三种返回格式）。
- `memoryStore.js`：`generateSummary`/`extractFacts`/`auditChapter` 添加 try/catch。

**3. 视图层加固**
- `App.vue`：添加 `onErrorCaptured` 全局错误边界，集成健康检查横条。
- `WriterView.vue`：`onMounted` + `loadContextData` 添加 try/catch。autosave 依赖 writerStore 静默失败。
- `ProjectView.vue`：`onMounted` Promise.all 添加 try/catch，`targetWords` null 值防护（`? (x/10000).toFixed(0) : '0'`）。

**4. 备份可靠性**
- `backup.js`：添加 `backupRunning` 并发锁，防止 `setInterval` 重复触发备份。
- `downloadBackup` 包装在 try/finally 中确保锁释放。

**5. 健康检查**
- 新建 `src/composables/useHealthCheck.js`：`backendOnline` 响应式状态，每分钟 ping `/api/health`。
- `App.vue`：挂载时启动周期性检查，后端离线时显示 `NAlert` error 横条。

### 修改文件
| 文件 | 变更 |
|------|------|
| `src/api/db/client.js` | 添加 AbortController 超时 + JSON.parse 保护 |
| `src/stores/novelStore.js` | 17 方法添加 try/catch + loading ref 实际使用 |
| `src/stores/writerStore.js` | 12 方法添加 try/catch |
| `src/stores/projectStore.js` | 7 方法添加 try/catch |
| `src/stores/providerStore.js` | 6 方法添加 try/catch |
| `src/stores/seedStore.js` | 6 方法添加 try/catch |
| `src/stores/marketStore.js` | 修复静默吞错 + 添加错误处理 |
| `src/stores/compareStore.js` | fuseFragments 添加 try/catch + 结果提取 |
| `src/stores/memoryStore.js` | 3 核心方法添加 try/catch |
| `src/App.vue` | onErrorCaptured + 健康检查集成 |
| `src/views/WriterView.vue` | onMounted + loadContextData 错误处理 |
| `src/views/ProjectView.vue` | onMounted 错误处理 + targetWords 防护 |
| `src/utils/backup.js` | 并发锁 |
| `src/composables/useHealthCheck.js` | 新建 |

### 验证结果
- Vite build 通过，无 error/warning。
- 总共修改 13 个文件，新建 1 个文件。
- 打包体积：400KB (index) + 84KB (ProjectView) + 69KB (WriterView)。

### 当前决策
- Store 错误统一使用 `console.error` + `throw e` 模式，由调用方（视图层）使用 `message.error()` 展示用户消息。
- 草稿保存（autosave）采用静默失败策略，不打断用户输入。
- 健康检查失败用 NAlert 横条提示（非弹窗），避免干扰操作。
- 备份并发控制用简单的布尔锁，不需要队列（备份操作本身很快）。

### 未完成 / 阻塞
- 浏览器端端到端验证所有 v1.0 功能。
- 长篇（100 章+）项目实际性能压测。

### 下一步
- 启动 FastAPI + Vite 进行浏览器端验证。
- 根据实际使用反馈优化。

## 2026-05-17 - v1.0 审查修复

### 本次完成
- 修复 `backend/database.py`：`aiomysql.Pool.release()` 改为同步调用，避免连接释放时抛出 TypeError。
- 修复后端 `convert_row()`：统一反序列化 MySQL JSON 字段，前端可直接使用 `nearChapters`、`hardState`、`tags` 等数组/对象。
- 修复 Claude 原生适配器：将 `system` message 提取为 Anthropic 顶层 `system` 字段，非流式调用强制 `stream:false`。
- Provider Store 增加 `ensureProvidersLoaded()`，写作、记忆、选题、种子、多模型融合等入口在取模型前自动加载配置。
- 优化全量导入导出：单项目导出按 `projectId` 过滤，默认不导出 API Key，导入失败不再静默吞错，并修复章节定稿版本映射。
- 清理 Dexie 当前架构残留：删除依赖和旧 `src/utils/db.js`，产品规划改为 FastAPI + MySQL 数据层。
- 修复 `frontend/index.html` 的损坏 title 标签，恢复 Vite 构建。
- 新增 `.gitignore`，排除 `node_modules`、`dist`、`.vite`、`__pycache__`、本地环境文件和临时数据库检查脚本。

### 修改文件
- `backend/database.py`
- `backend/routers/helpers.py`
- `backend/routers/export.py`
- `frontend/index.html`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/src/api/ai/anthropicAdapter.js`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/providerStore.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/stores/memoryStore.js`
- `frontend/src/stores/marketStore.js`
- `frontend/src/stores/seedStore.js`
- `frontend/src/stores/compareStore.js`
- `frontend/src/stores/projectStore.js`
- `frontend/src/utils/db.js`
- `.gitignore`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm run build` 通过。
- 通过 `database.fetchone('SELECT 1 AS ok')` 验证后端数据库连接获取与释放正常。

### 当前决策
- v1.0 状态调整为“开发完成，待验收”，不能在浏览器端端到端验证前标记为完全完成。
- 当前版本不继续新增功能，优先完成真实浏览器工作流和长篇项目压测。

### 未完成 / 阻塞
- 浏览器端端到端验证所有 v1.0 功能。
- 100 章以上长篇项目性能与实际写作流程验证。

### 下一步
- 启动 FastAPI + Vite，按“创建项目 → 配置模型 → 生成种子 → 生成章节 → 定稿 → 记忆提取 → 导出/导入”的路径做完整验收。

## 2026-05-17 - 创作种子详情布局修复

### 本次完成
- 修复“当前选中的种子”详情区域长文本拥挤问题：从两列栅格改为单列阅读流，增加行高、段落间距和自动换行。
- 种子列表改为响应式布局：默认单列，超宽屏再显示两列，避免长题材卡片在中等宽度下挤压。

### 修改文件
- `frontend/src/components/seed/SeedWorkbench.vue`

### 验证结果
- 清理 `frontend/dist` 后重新执行 `npm run build`，构建通过。

### 当前决策
- 长篇创作类文本字段优先使用阅读流布局，不再用两列信息表硬排长段落。

### 未完成 / 阻塞
- 需用户在浏览器中刷新后目视确认阅读体验。

### 下一步
- 若仍显拥挤，再把长字段拆成独立小节卡片。

## 2026-05-17 - 章节生成顺序与正文约束修复

### 本次完成
- 重写 `frontend/src/prompts/chapter.js`：章节生成 prompt 明确要求只输出正文，不输出标题、提纲、解释或 Markdown 标题。
- 将本章目标、近景大纲、角色状态、伏笔、世界规则等结构化上下文格式化为清晰条目，避免对象被直接塞进 prompt。
- 新增 `cleanGeneratedChapterText()`，保存候选版本前清理模型偶尔输出的 Markdown 标题、代码块和“以下是正文”类提示语。
- `writerStore.generateChapter()` 和多候选生成接入正文清洗。
- `buildWritingContext()` 增加 `premise` 高优先级上下文，让章节生成先理解作品定位，再写本章。
- `vite.config.js` 显式设置 `build.emptyOutDir = true`，修复 Vite 8/Rolldown 在 Windows 下重复构建时偶发 HTML 入口路径报错。

### 修改文件
- `frontend/src/prompts/chapter.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/utils/contextBuilder.js`
- `frontend/vite.config.js`

### 验证结果
- `npm run build` 通过。
- FastAPI 已启动：`http://127.0.0.1:8000`，`/api/health` 返回 `{"ok":true}`。
- Vite 已启动：`http://127.0.0.1:5173/`，首页返回 HTTP 200。

### 当前决策
- 章节生成必须走“结构化上下文 → 明确正文任务 → 输出清洗”三步，降低 AI 把设定说明和正文混排的概率。

### 未完成 / 阻塞
- 需要在浏览器中重新点击“生成本章”验证新输出；旧草稿不会自动重排。

### 下一步
- 若仍出现叙事错序，需要增加“章节计划预览/确认”步骤，让 AI 先给本章 5-8 个节拍，再按节拍生成正文。

## 2026-05-17 - 风格试写对比模块

### 本次完成
- 新增“风格试写对比”功能，位置在“创作种子”页、选中种子之后、创建创作圣经之前。
- 支持默认风格：快节奏爽文、冷峻克制、轻松吐槽、文学质感、悬疑压迫、群像史诗。
- 支持用户粘贴自定义风格参考文本，AI 会提取风格指纹并生成一个自定义参考风格试写版本。
- 每个风格版本包含：定位、风格指纹、同一开局片段试写、适配度、稳定性、想象空间、风险和推荐理由。
- 用户可以将任一风格“设为主风格”，创建创作圣经时会写入 `styleBible` 作为长期风格基准。
- 新增构建配置 `rollupOptions.input.app`，稳定 Vite 8/Rolldown 在 Windows 下重复构建时的 HTML 入口处理。

### 修改文件
- `frontend/src/prompts/styleTrial.js`
- `frontend/src/stores/styleTrialStore.js`
- `frontend/src/components/seed/StyleTrialPanel.vue`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `frontend/vite.config.js`

### 验证结果
- 连续两次执行 `npm run build` 均通过。
- 浏览器中已试用风格对比功能，用户反馈“没问题”。

### 当前决策
- 风格对比放在“创作种子 → 创作圣经”之间，负责把“怎么写”定调。
- 创作圣经只保存最终确认的主风格和风格指纹，不保存所有候选风格。
- 用户示例文本只用于提取风格特征，不要求 AI 照搬示例内容。

### 未完成 / 阻塞
- 风格试写结果目前是前端会话态，刷新后会丢失；已选主风格写入创作圣经后可持久保存。

### 下一步
- 在浏览器中用真实模型测试“默认风格 + 自定义示例”生成效果。

## 2026-05-17 - 章节小纲确认流程

### 本次完成
- 在写作台右侧 AI 工具中新增“先做小纲”入口。
- 新增章前小纲生成 prompt：要求 AI 只生成 5-8 条剧情节拍、写作约束和可发散空间，不直接写正文。
- 写作台新增“本章小纲确认”弹窗，用户可编辑、重排或补充节拍。
- 新增“按此小纲生成正文”流程：确认后的小纲会注入章节生成 prompt，正文生成按小纲顺序展开，但保留场景、对白和细节发挥空间。
- 章节候选版本的 `promptBrief` 会区分普通章节生成和“按确认小纲生成章节”。

### 修改文件
- `frontend/src/prompts/chapter.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/components/writer/AIActionPanel.vue`
- `frontend/src/views/WriterView.vue`

### 验证结果
- `npm run build` 通过。

### 当前决策
- 正式创作推荐流程调整为“创作圣经 → 章前小纲确认 → 生成正文 → 版本挑选/定稿”。
- 小纲用于约束关键剧情顺序，不把正文完全模板化；用户仍可在确认弹窗中保留开放式发挥点。

### 未完成 / 阻塞
- 小纲目前不单独持久化，刷新后未定稿的小纲会丢失；后续可考虑保存到章节草稿元数据或独立表。
- 需用户在浏览器中用真实模型验证“小纲 → 正文”的质量提升。

### 下一步
- 浏览器端试用新流程：先生成小纲，手动确认后再生成第 1 章正文。

## 2026-05-17 - 选题雷达抓取修复

### 本次完成
- 修复选题雷达抓取结果为空的问题：后端不再只依赖通用正则，改为按站点书籍链接结构解析榜单条目。
- 新增中文页面解码兜底，处理 `GBK/GB18030` 页面导致的乱码问题。
- 新增来源诊断信息：每个榜单来源返回 HTTP 状态、解析数量和错误信息，避免失败时被静默吞掉。
- 新增本地趋势参考样本兜底：当实时抓取全部失败时，返回明确标记为“本地趋势样本”的参考数据，避免页面完全空白。
- 前端抓取提示支持显示后端返回的成功、兜底或失败信息。

### 修改文件
- `backend/routers/market.py`
- `frontend/src/components/market/MarketRadar.vue`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm run build` 通过。
- 真实联网调用 `search_and_fetch('热门小说')` 返回 86 条：纵横 25 条、潇湘 25 条、小说阅读网 11 条、52书库 25 条。
- 重启 FastAPI 后调用 `/api/market/scrape`，有效 36 位项目 ID 下返回 `count=86`、`fallback=false`、`saveErrors=0`。
- 测试写入的临时项目数据已清理。

### 当前决策
- 选题雷达先以可直接读取的榜单页为主，遇到动态渲染、字体混淆或强反爬站点不强行硬抓。
- 书旗当前 TLS 请求失败；起点排行榜返回 202；番茄页面可访问但书名存在字体混淆，暂不作为稳定来源。
- 当前功能定位是“市场观察/选题辅助”，只抓取公开榜单元数据，不抓正文。

### 未完成 / 阻塞
- 若后续必须稳定覆盖书旗、起点、番茄，需要引入浏览器渲染抓取或改为用户手动导入榜单页面数据。
- 当前抓取结果的简介字段依赖榜单页本身，部分站点只提供书名和链接，概要可能为空。

### 下一步
- 浏览器端重新点击“开始抓取”，确认选题雷达列表能显示真实数据。

## 2026-05-17 - 选题雷达多源 Web Search

### 本次完成
- 在固定榜单抓取之外，新增多源 Web Search 层。
- 默认搜索源覆盖：综合 Web、夸克小说、UC小说、七猫小说、番茄小说、起点小说。
- Web Search 优先使用 Bing RSS 输出，失败时回退到 HTML 搜索结果解析。
- 搜索结果会以 `Web Search：来源名` 写入选题雷达，保留标题、摘要、来源域名、URL 和推断分类。
- 前端新增“来源状态”标签，显示每个榜单/搜索源本次解析到的数量，避免抓取失败时黑盒化。
- 修复 Vite Windows 构建入口配置：`rollupOptions.input.app` 改为相对路径 `index.html`，避免 Rolldown 将绝对路径当作输出文件名。

### 修改文件
- `backend/routers/market.py`
- `frontend/src/components/market/MarketRadar.vue`
- `frontend/vite.config.js`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm run build` 通过。
- 真实联网调用 `search_and_fetch('玄幻 热门')` 返回 91 条，其中 Web Search 结果 5 条。
- 重启 FastAPI 后调用 `/api/market/scrape`，有效 36 位项目 ID 下返回 `count=92`、`fallback=false`、`saveErrors=0`。
- 测试写入的临时项目数据已清理。

### 当前决策
- Web Search 是补充层，不替代固定榜单页；能扩大来源范围，但搜索引擎结果质量不如可解析榜单稳定。
- 对来源名做匹配过滤，避免把“UC浏览器”“七这个汉字”等明显跑偏结果混进选题雷达。
- 夸克/UC/七猫在 Bing 当前结果中不稳定，来源状态会真实显示为 0，不伪造实时数据。

### 未完成 / 阻塞
- 若要让夸克/UC/七猫稳定返回小说榜单级数据，需要接入专门搜索 API、浏览器渲染抓取，或允许用户手动粘贴榜单 URL。
- Web Search 结果多为网页/平台/文章级线索，不一定是单本小说条目，后续更适合作为 AI 市场分析输入。

### 下一步
- 浏览器端用“玄幻 热门”“都市 热门”等关键词测试来源状态和 Web Search 条目展示。

## 2026-05-17 - 章节生成顺序控制修复

### 本次完成
- 修复“生成本章”容易从后续会议、追查结果、余波段落开头的问题。
- “生成本章”现在默认先自动生成一份本章顺序小纲，再按小纲生成正文；手动“先做小纲”入口仍保留。
- 写作上下文新增创作种子、第一章开局锚点和顺序控制规则，第一章优先从开局钩子或主角初始处境进入。
- 章节正文 prompt 强化执行要求：第一段必须对应小纲第 1 条，禁止把后续结果、事后复盘、任务奖励提前到开头。
- 多候选版本生成也复用同一份顺序小纲，避免不同版本都出现开场顺序漂移。

### 修改文件
- `frontend/src/views/WriterView.vue`
- `frontend/src/prompts/chapter.js`
- `frontend/src/components/writer/AIActionPanel.vue`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 正式章节创作默认走“顺序小纲 -> 正文生成”，小纲只锁定节拍顺序和关键节点，不锁死对白与细节，继续保留模型的想象力。
- 如果用户已经手动编辑过小纲，生成时直接使用用户确认的小纲，不再自动覆盖。

### 未完成 / 阻塞
- 需要用户在浏览器中用真实模型重新生成第 1 章，确认开头是否从主角初始场景进入，而不是从后续势力会议或结果段落进入。

### 下一步
- 浏览器端点击“生成本章”重试第 1 章；如果仍有错序，再增加生成后的顺序审稿/自动返修环节。

## 2026-05-17 - 小纲审阅流程与流式输出修复

### 本次完成
- 修正“生成本章”交互：点击后只准备并打开本章小纲弹窗，不再自动继续生成正文。
- 小纲弹窗保留用户审阅流程：支持重新生成小纲、编辑小纲、点击“开始生成本章”后再关闭弹窗并生成正文。
- 右侧“先做小纲”按钮改为“查看小纲”；若已有小纲则直接查看，若没有则先生成后打开。
- 小纲生成不再读取当前编辑器正文草稿，避免乱序废稿污染下一次小纲。
- 修复 OpenAI-compatible 流式 SSE 解析：一次网络 chunk 内多条 `data:` 事件会全部处理，不再只取第一条后丢弃后续片段。

### 修改文件
- `frontend/src/views/WriterView.vue`
- `frontend/src/components/writer/AIActionPanel.vue`
- `frontend/src/api/ai/openaiCompatibleAdapter.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 正文生成必须经过“小纲审阅确认”这道门，除非后续单独增加“一键自动模式”。
- 当前优先保留流式显示，但修复流式解析丢片段问题；若真实模型仍出现文字错乱，再为章节正文增加“非流式稳定生成”开关。

### 未完成 / 阻塞
- 需要浏览器端重新生成一章，确认流式文本不再出现句内词序碎裂。

### 下一步
- 刷新前端后点击“生成本章”：应先打开小纲弹窗；审阅后点击“开始生成本章”再生成正文。

## 2026-05-17 - 写字台小纲与生成入口状态机整理

### 本次完成
- 明确“查看小纲 / 生成本章 / 基于小纲生成多版本”三类入口职责。
- “生成本章”逻辑调整为：没有小纲时先生成小纲并弹窗等待审阅；已有小纲时直接按当前小纲生成正文。
- 小纲弹窗底部按钮调整为“重新生成小纲”和“开始生成本章 / 生成多候选版本”，移除“稍后再说”按钮。
- “生成多候选版本”定义为基于同一份小纲生成多个正文展开版本，不再依赖当前编辑器是否已有正文。
- 多候选入口没有小纲时同样先生成小纲并弹窗，已有小纲时直接生成候选版本。

### 修改文件
- `frontend/src/views/WriterView.vue`
- `frontend/src/components/writer/AIActionPanel.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 小纲是章节正文生成和多候选生成的共同执行计划。
- 续写、扩写、压缩、选区改写只处理当前正文局部，不负责整章剧情重排。

### 未完成 / 阻塞
- 需要浏览器端验证三个入口：无小纲生成本章、有小纲生成本章、无小纲生成多候选版本。

### 下一步
- 若续写和选区改写需要更安全，增加“改写预览 / 替换选区确认”流程。

## 2026-05-17 - 选题到种子的创作前流程整理

### 本次完成
- 项目页按真实长篇小说准备顺序重排为：选题雷达 → 创作种子 → 创作圣经 → 设定库 → 章节管理。
- 项目页新增“创作准备流程”状态条，显示每一步是否已就绪，并可直接跳转到对应模块。
- 创作种子详情弹窗改为“查看 / 调整种子”，支持手动编辑标题、题材、一句话、主角、欲望、核心矛盾、世界压力、开局钩子、情绪价值、差异化和风格目标。
- 种子详情支持“保存修改”和“另存为新种子”，当前选中种子卡片新增“手动调整”入口。
- 选题雷达 AI 对话中，如果用户明确要求修改/调整当前种子，且 AI 返回更新后的种子 JSON，会更新当前选中的种子；否则仍按新候选种子保存。
- 选题雷达 AI 对话消息增加“已更新当前创作种子”的反馈，避免 AI 文案说改了但数据库没变。

### 修改文件
- `frontend/src/views/ProjectView.vue`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `frontend/src/components/seed/SeedCard.vue`
- `frontend/src/components/market/AIChatPanel.vue`
- `frontend/src/components/market/MarketRadar.vue`
- `frontend/src/stores/seedStore.js`
- `frontend/src/stores/marketStore.js`
- `frontend/src/prompts/market.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 当前版本继续保持“项目内选题和种子”模式，不立刻拆出项目外创意孵化池。
- 种子是项目创作前的核心可编辑资产，不是一次性 AI 输出结果。
- 从种子创建项目作为后续增强方向，当前先把项目内流程跑顺。

### 未完成 / 阻塞
- 选题 AI 对话的“修改当前种子”依赖 AI 按提示返回完整种子 JSON；如果模型只口头描述但不输出 JSON，仍不会落库。
- 后续可以增加显式“应用到当前种子 / 另存为新种子”确认按钮，让 AI 修改建议更可控。

### 下一步
- 浏览器端验证：选题对话生成种子 → 要求调整当前种子 → 创作种子页查看是否已更新 → 手动调整保存。

## 2026-05-18 - 种子 JSON 解析与选题对话落库修复

### 本次完成
- 新增统一的种子 JSON 解析工具，兼容 Markdown 代码块、裸 JSON 数组、单对象、`{ seeds: [...] }` 包装、snake_case 字段和部分中文字段名。
- 修复“创作种子”模块 AI 生成种子时因 JSON 包装或字段格式略有差异导致的“JSON 结构错误”。
- 修复“选题雷达”AI 对话中模型输出种子 JSON 但前端没有保存到创作种子列表的问题。
- 选题对话保存失败不再静默吞掉，改为在聊天消息和提示条中显示失败原因。
- 选题对话面板新增“生成新种子”显式入口，不再要求用户靠自然语言猜触发方式。
- 选题对话发送给模型前会剥离前端内部字段，只保留 `role/content`，避免部分 OpenAI-compatible 接口拒绝请求。
- 创作种子手动创建和详情编辑补充“风险提示”字段，避免 AI 生成内容落库后无法维护。
- 后端种子更新接口补充 `riskNotes` 字段，支持风险提示后续编辑保存。

### 修改文件
- `frontend/src/utils/seedParser.js`
- `frontend/src/stores/seedStore.js`
- `frontend/src/stores/marketStore.js`
- `frontend/src/prompts/market.js`
- `frontend/src/components/market/AIChatPanel.vue`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `backend/routers/seeds.py`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- AI 生成种子是“生成内容 + 解析 + 落库”的完整动作，不能只把 JSON 展示给用户。
- 选题雷达对话保留自由讨论，但生成种子必须提供显式按钮，降低误操作和不可预期。

### 未完成 / 阻塞
- 仍需浏览器端用实际模型验证：种子页 AI 生成、选题对话“生成新种子”、对话中“修改当前种子”三条链路。

### 下一步
- 若模型仍偶尔输出非 JSON 建议，可增加“从上一条回复保存为种子”的手动解析按钮作为兜底。

## 2026-05-18 - 本地启动脚本补充

### 本次完成
- 新增后端启动脚本 `start_backend.bat`，用于手动启动 FastAPI 服务。
- 新增前端启动脚本 `start_frontend.bat`，用于手动启动 Vite 前端服务。
- 脚本优先使用当前机器固定路径下的 Python / npm，路径不存在时回退到系统 PATH。

### 修改文件
- `start_backend.bat`
- `start_frontend.bat`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 未运行脚本，脚本内容已按当前项目路径和既有启动命令生成。

## 2026-05-18 - 选题雷达顾问记忆与方向建议

### 本次完成
- 选题雷达 AI 顾问聊天记录改为按项目保存到 MySQL，刷新页面后可继续基于历史上下文沟通。
- 聊天记录会保存用户消息、AI 回复、种子创建/更新结果和保存失败提示。
- 清空对话改为同步清空数据库中的当前项目顾问记录，不影响已生成的创作种子。
- 抓取热点小说后会自动调用市场模型生成 4-6 个“AI 选题方向建议”。
- 方向建议以卡片展示读者期待、当前依据、可切入角度、风险，并提供“和 AI 顾问讨论”按钮把方向带入聊天输入框。
- 方向建议报告保存到 MySQL，刷新页面后保留最近一次建议。
- 项目导出/导入补充 `marketItems`、`marketChatMessages`、`marketDirectionReports`。

### 修改文件
- `backend/schema.sql`
- `backend/database.py`
- `backend/routers/market.py`
- `backend/routers/export.py`
- `backend/routers/helpers.py`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/marketStore.js`
- `frontend/src/components/market/AIChatPanel.vue`
- `frontend/src/components/market/MarketRadar.vue`
- `frontend/src/prompts/marketDirections.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- 后端已重启，`/api/health` 正常。
- `GET /api/market/chat?projectId=__healthcheck__` 正常返回空列表。
- `GET /api/market/directions?projectId=__healthcheck__` 正常返回空列表。

### 当前决策
- 选题雷达不只展示抓取结果，还要给出可讨论、可孵化的题材方向。
- 选题顾问对话属于项目创作资产，必须持久化，方便后续基于历史脉络调整种子。

### 未完成 / 阻塞
- 方向建议质量仍依赖市场模型配置和抓取结果质量，需要浏览器端用真实数据验证。

### 下一步
- 如实际体验中方向建议过多或偏泛，可增加“偏男频/女频/短篇/长篇/平台风格”的筛选约束。

## 2026-05-18 - AI 种子解析兜底与详情弹窗修复

### 本次完成
- 强化创作种子解析器：会扫描 AI 回复中的多个 JSON 候选段，不再只取第一个 `[` 或 `{`。
- 解析器新增中文标签兜底，支持从“标题：/题材：/开局钩子：/风险提示：”这类非 JSON 结构中提取种子。
- AI 生成种子 Prompt 改为要求顶层 `{ "seeds": [...] }` 合法 JSON，减少模型输出 Markdown 或说明文字。
- 当首次解析失败时，自动追加一次“JSON 修复器”调用，把模型原始输出转成可保存种子 JSON，再尝试落库。
- 修复“查看 / 调整种子”弹窗长文本撑开页面的问题：弹窗宽度增大，内容区内部滚动，底部按钮固定在弹窗底部。

### 修改文件
- `frontend/src/utils/seedParser.js`
- `frontend/src/prompts/seed.js`
- `frontend/src/stores/seedStore.js`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- 本地解析样例验证通过：标准 JSON、带前置干扰文本的 JSON、中文标签式种子都可解析。

### 当前决策
- AI 种子生成不能依赖模型一次性输出完美 JSON，必须有解析兜底和格式修复链路。
- 长文本种子编辑需要稳定弹窗布局，不能让表单内容撑破页面。

## 2026-05-18 - 方向建议失败策略调整

### 本次完成
- 选题方向建议解析器改为扫描多个 JSON 候选段，支持顶层 `{ "directions": [...] }`。
- 当 AI 返回方向建议但格式不合法时，自动追加一次“JSON 修复器”调用，只修复格式，不新增本地市场判断。
- 抓取失败进入本地参考样本时，不再自动生成 AI 选题方向建议，避免长期输出同一套本地保守方向。
- 抓取失败时会清空当前方向建议并提示用户更换关键词或稍后重试实时抓取。

### 修改文件
- `frontend/src/prompts/marketDirections.js`
- `frontend/src/stores/marketStore.js`
- `frontend/src/components/market/MarketRadar.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本地方向建议 JSON 解析样例通过。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 方向建议必须基于真实抓取结果或真实 AI 输出，不用本地兜底样本伪装市场结论。

## 2026-05-18 - 结构化生成二次加固

### 本次完成
- AI 生成种子启用模型 JSON 输出约束（当 Provider 支持 JSON 时）。
- AI 方向建议启用模型 JSON 输出约束（当 Provider 支持 JSON 时）。
- 种子解析器补充英文、snake_case、英文空格标签和 Markdown 粗体标签解析，例如 `Opening Hook`、`Core Conflict`、`Risk Notes`。
- 方向建议解析器补充 Markdown/编号/英文标签解析，例如 `Reader Expectation`、`Seed Angle`、`Discussion Prompt`。
- 种子和方向建议在解析失败时，错误信息会附带 AI 返回片段，便于判断模型实际输出内容。
- 格式修复 Prompt 调整为“从原文已有信息结构化”，不是只修 JSON 标点，提升非 JSON 回复的可恢复性。

### 修改文件
- `frontend/src/utils/seedParser.js`
- `frontend/src/prompts/seed.js`
- `frontend/src/prompts/marketDirections.js`
- `frontend/src/stores/seedStore.js`
- `frontend/src/stores/marketStore.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本地英文 Markdown 标签解析样例通过。
- 本地 JSON 包装解析样例通过。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 创意生成允许模型自由发挥，但落库前必须经历“解析 → 格式修复 → 带原文片段报错”的结构化链路。

## 2026-05-18 - 完整种子 JSON 直存与截断风险降低

### 本次完成
- 创作种子 AI 生成入口增加“输入直解析”：如果用户在创作想法里粘贴完整种子 JSON / 中文标签种子，系统会直接保存为种子，不再交给 AI 重写。
- AI 生成种子默认数量从 3-5 个调整为 1-3 个。
- 开局钩子建议长度从 200-400 字调整为 120-220 字。
- Prompt 增加每字段 300 字以内约束，降低模型输出过长导致 JSON 中途截断的概率。

### 修改文件
- `frontend/src/stores/seedStore.js`
- `frontend/src/prompts/seed.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本地完整种子 JSON 解析样例通过。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 粘贴完整种子时应视为“导入/保存种子”，而不是再次让 AI 扩写，避免长 JSON 被模型重写后截断。

## 2026-05-18 - JSON-like 粘贴种子解析修复

### 本次完成
- 创作想法直存解析支持 `"title":`、`"genre":` 这类带引号的 JSON-like 字段名。
- 支持字段值里存在真实换行的非严格 JSON 文本，尽量按字段边界提取为种子。
- 支持 `endingAnchor` / `结局锚点` 作为额外字段边界，但当前不写入种子表，避免污染风险提示字段。
- 修复用户粘贴长种子 JSON-like 内容时仍然走 AI 重写并被截断的问题。

### 修改文件
- `frontend/src/utils/seedParser.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本地“带引号字段名 + 字段值真实换行 + endingAnchor 额外字段”的种子解析样例通过。
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-18 - 粘贴种子显式保存入口

### 本次完成
- “AI 生成种子”弹窗新增“保存粘贴种子”按钮，用于把已整理好的 JSON / JSON-like / 中文标签种子直接保存到种子库。
- “生成”按钮执行前也会先尝试解析粘贴内容，解析成功则直接保存，不再调用大模型。
- 粘贴解析失败时只在用户点击“保存粘贴种子”时提示字段要求；普通 AI 生成仍可继续。

### 修改文件
- `frontend/src/components/seed/SeedWorkbench.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- 后端 `/api/health` 正常。

### 当前决策
- “粘贴已有种子”和“让 AI 生成新种子”是两个不同动作，界面上必须给显式入口，避免误走外部 AI 网络请求。

## 2026-05-18 - 种子长字段保存与 endingAnchor 支持

### 本次完成
- `creative_seeds` 新增 `ending_anchor` 字段，用于保存结局锚点。
- `emotional_promise`、`style_target` 从短文本扩容为 `TEXT`，避免长种子保存时数据库截断/报错。
- 后端种子创建/更新接口新增 `endingAnchor`。
- 前端种子解析器把 `endingAnchor` / `结局锚点` 纳入正式种子字段。
- 手动创建种子、查看/编辑种子增加“结局锚点”输入项。
- 手动创建种子增加异常捕获，保存失败时会明确提示错误，不再表现为点击无反应。

### 修改文件
- `backend/schema.sql`
- `backend/database.py`
- `backend/routers/seeds.py`
- `frontend/src/utils/seedParser.js`
- `frontend/src/prompts/seed.js`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- 后端已重启，`/api/health` 正常。
- 使用超长 `emotionalPromise` / `styleTarget` / `endingAnchor` 调用创建种子接口成功，并删除测试数据成功。

### 当前决策
- 结局锚点是长篇创作种子的重要资产，应进入种子模型，而不是丢弃或混入风险提示。

## 2026-05-18 - 创作种子生成创作圣经补强

### 本次完成
- 新增“创作种子 -> 创作圣经”的专用 AI 生成链路，不再只是把种子的 `logline` / `styleTarget` / `worldPressure` 简单搬运到圣经字段。
- 创作圣经生成会从题材、情绪价值、核心矛盾、世界压力、风格试写、风险提示和结局锚点中推导 `targetReader`、`themeBible`、`styleBible`、`worldRules` 和 `forbiddenDirections`。
- 新增创作圣经 JSON 解析与修复提示，模型返回非标准结构时会先尝试修复；仍失败时保留返回片段报错，不静默写入低质量内容。
- 创作圣经编辑页增加 store 同步：从种子页生成或更新圣经后，点击编辑会先读取最新数据，避免看到旧的空表单。

### 修改文件
- `frontend/src/prompts/bibleFromSeed.js`
- `frontend/src/stores/novelStore.js`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `frontend/src/components/bible/CreativeBible.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 创作圣经 JSON 解析器本地样例通过。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 创作圣经是作品级蓝图，应由 AI 基于种子做“编辑推导”，不能由前端做机械字段映射；目标读者和主题母题属于必填核心字段。

## 2026-05-18 - 创作圣经生成 JSON 源头排查与修复

### 本次完成
- 排查“以此创建创作圣经”失败链路：种子传入和按钮逻辑正常，失败点在模型返回的创作圣经内容不是严格 JSON。
- 触发原因：原 Prompt 要求 `styleBible`、`themeBible`、`worldRules` 输出长字符串，模型容易在字符串内部直接换行，导致“看起来像 JSON，但不是合法 JSON”。
- 调整 Prompt：长字段改为 JSON 短句数组输出，要求所有字符串内部不直接换行，每个数组元素控制为短句。
- 增强创作圣经解析器：当严格 JSON 解析失败时，会按字段边界从 JSON-like 文本中提取 `premise`、`targetReader`、`styleBible`、`themeBible`、`worldRules`、`forbiddenDirections`。

### 修改文件
- `frontend/src/prompts/bibleFromSeed.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本地构造“字段值内部未转义换行”的非法 JSON 样例，解析成功。
- 本地构造“长字段为数组”的合法 JSON 样例，解析成功并转换为前端文本。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 模型输出给程序落库时，长段落字段应优先使用数组短句，而不是单个长字符串，降低 JSON 损坏概率。

## 2026-05-18 - 创作圣经数组字符串清洗

### 本次完成
- 修复创作圣经生成成功后，`styleBible`、`themeBible`、`worldRules` 字段显示为 `[` 开头的问题。
- 原因是部分模型会把数组整体作为字符串返回，例如 `"styleBible": "[...]"`，严格 JSON 可解析，但字段内容仍带数组外壳。
- 标准化逻辑新增“数组字符串”识别：支持合法 JSON 数组字符串和多行 JSON-like 数组文本，统一转换为换行文本。
- 创作圣经查看态和编辑态都改为使用标准化后的数据，已保存的旧脏数据打开页面时也会被清洗展示。

### 修改文件
- `frontend/src/prompts/bibleFromSeed.js`
- `frontend/src/components/bible/CreativeBible.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本地构造 `styleBible: "[...]"`、`themeBible: "[...]"`、`worldRules: "[...]"` 样例，均成功清洗为换行文本。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- AI 返回结构化数据时，要同时防御“数组”和“数组字符串”两种形态，不能只按理想 JSON 处理。

## 2026-05-18 - 禁止方向落库修复

### 本次完成
- 排查“页面有禁止方向标签，但数据库 `creative_bible.forbidden_directions` 显示 `[]`”的问题。
- 原因之一是模型可能返回中文字段名 `"禁止方向"`，严格 JSON 解析成功后提前走标准化，但旧逻辑只读取 `forbiddenDirections` 等英文 key，导致中文 key 未映射落库。
- `normalizeBiblePayload` 改为遍历所有字段并通过别名表映射，支持中文 key、snake_case、camelCase 等多种形态。
- `novelStore.saveBible` 保存前强制执行标准化，确保编辑页或生成页传入的数据都会以标准字段落库。

### 修改文件
- `frontend/src/prompts/bibleFromSeed.js`
- `frontend/src/stores/novelStore.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本地构造 `"禁止方向": [...]` 样例，成功归并到 `forbiddenDirections`。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 任何写入创作圣经的入口都必须先标准化，不能只在展示层清洗。

## 2026-05-18 - 创作圣经到设定库初始化入口

### 本次完成
- 在创作圣经卡片新增“提取到设定库”入口。
- 新增从创作圣经和当前选中创作种子提取初始设定候选的 Prompt。
- 提取结果不直接写入正式设定库，而是保存到 `setting_change_events`，状态为 `pending_review`。
- 复用现有设定库“待确认设定变更”流程，用户确认后再创建/更新 `setting_entities` 或 `setting_relations`。
- 设定库待确认区说明更新为支持“创作圣经初始化”和“章节定稿提取”两个来源。

### 修改文件
- `frontend/src/prompts/settingsFromBible.js`
- `frontend/src/stores/settingStore.js`
- `frontend/src/components/bible/CreativeBible.vue`
- `frontend/src/components/settings-library/SettingLibrary.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本地初始设定候选 JSON 解析样例通过。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 圣经到设定库必须走“待确认设定变更”，不允许 AI 直接污染正式设定库。

## 记录模板

```md
## YYYY-MM-DD HH:mm - 阶段名称

### 本次完成
- 

### 修改文件
- 

### 验证结果
- 

### 当前决策
- 

### 未完成 / 阻塞
- 

### 下一步
- 
```

## 2026-05-18 - 圣经到设定库提取容错与流程锁

### 本次完成
- 增强“创作圣经 -> 设定库”提取解析器：支持中文字段名、snake_case、`settings/entities/candidates/设定候选` 等多种 AI 返回结构。
- 新增设定候选 JSON 修复二次调用：首次解析失败时，让模型只做格式修复，不新增内容。
- 设定库初始化结果统一打上“创作圣经初始化”来源标记，便于识别初始化是否已执行。
- 创作圣经页加载设定变更记录后显示初始化状态；已提取过时按钮变为“已提取到设定库”并禁止再次提取。
- 从种子生成创作圣经增加流程保护：项目已有设定库数据或已写章节后，不再允许从种子覆盖圣经，只能在圣经页局部编辑。

### 修改文件
- `frontend/src/prompts/settingsFromBible.js`
- `frontend/src/stores/settingStore.js`
- `frontend/src/components/bible/CreativeBible.vue`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 本地构造中文 key、`entities`、`设定候选`、关系候选等样例，均能解析为可保存的设定变更。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 创作圣经到设定库是一次性初始化动作。初始化后，设定来源应转为“章节定稿提取 + 设定库人工确认”，避免旧种子或新圣经覆盖已经写作过的世界状态。
- 写作开始后不允许从种子重新生成并覆盖创作圣经；后续如需要大改，应设计为“新版圣经草案/差异对比/人工确认迁移”，不能直接覆盖。

## 2026-05-18 - 全局提醒改为手动关闭弹窗

### 本次完成
- 新增统一提醒组合函数 `useAppMessage`，对外保留 `success/error/warning/info` 调用方式。
- 将前端所有原 `useMessage` 短暂 toast 替换为 Naive UI Dialog 弹窗提醒。
- 弹窗默认不可点击遮罩或 ESC 自动关闭，必须点击“关闭”按钮手动关闭。
- 长错误信息支持换行与自动换行，避免 AI 返回片段或异常信息被截断难读。

### 修改文件
- `frontend/src/composables/useAppMessage.js`
- `frontend/src/style.css`
- `frontend/src/components/**`
- `frontend/src/views/**`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 全项目已无 `useMessage` 调用。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 完成、失败、警告、普通提示统一使用手动关闭弹窗，避免关键反馈几秒后消失。

## 2026-05-18 - 禁止种子重复覆盖创作圣经

### 本次完成
- 修复“创作圣经已生成后，种子页仍可点击以此创建创作圣经并重生成”的问题。
- 种子页点击前会重新读取当前项目创作圣经；只要已有圣经，就弹窗提示并阻止覆盖。
- `novelStore.generateBibleFromSeed` 增加 store 层硬拦截，避免未来其他入口误调用导致覆盖。

### 修改文件
- `frontend/src/components/seed/SeedWorkbench.vue`
- `frontend/src/stores/novelStore.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 从种子创建圣经只能发生在“项目尚无创作圣经”的阶段。
- 已有圣经后的调整只能在创作圣经页局部编辑；后续若需要大改，应另做“新版圣经草案/差异对比”功能。

## 2026-05-18 - 阶段数据清空与项目更新时间同步

### 本次完成
- 修复创作圣经保存后，项目页“项目信息”更新时间不刷新的问题：保存/删除圣经会同步更新 `projects.updated_at` 并刷新前端当前项目。
- 新增项目内容状态接口 `/projects/{pid}/content-state`，用于判断是否已有章节正文或候选版本。
- 新增清空/删除接口：删除创作圣经、清空创作种子、清空设定库。
- 种子页新增“清空种子”按钮；圣经页新增“删除圣经”按钮；设定库新增“清空设定库”按钮。
- 清空操作会根据章节内容状态弹窗确认：没有章节内容时一次确认；已有章节内容时二次警告确认。
- 项目删除时补充清理市场数据与设定库数据，避免残留孤立数据。

### 修改文件
- `backend/routers/helpers.py`
- `backend/routers/projects.py`
- `backend/routers/novel.py`
- `backend/routers/seeds.py`
- `backend/routers/settings_library.py`
- `frontend/src/api/db/client.js`
- `frontend/src/composables/useResetConfirmation.js`
- `frontend/src/stores/novelStore.js`
- `frontend/src/stores/seedStore.js`
- `frontend/src/stores/settingStore.js`
- `frontend/src/components/bible/CreativeBible.vue`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `frontend/src/components/settings-library/SettingLibrary.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 阶段回退允许存在，但必须显式确认；已有章节内容时必须二次确认。
- 删除种子、圣经、设定库都不删除章节正文，只清理对应阶段数据。

## 2026-05-18 - 项目库基础信息编辑

### 本次完成
- 项目库卡片新增“编辑”按钮，可修改项目名称、题材、简介、目标字数和目标章节数。
- 新增“编辑项目信息”弹窗，复用新建项目的基础字段。
- 编辑时会读取项目内容状态；如果已有章节或正文候选版本，目标字数和目标章节数会锁定不可编辑。
- 后端 `PUT /projects/{pid}` 增加硬保护：已有章节或章节版本时，不允许修改目标字数或目标章节数。
- 项目更新后会刷新项目库卡片与当前项目状态。

### 修改文件
- `backend/routers/projects.py`
- `frontend/src/views/HomeView.vue`
- `frontend/src/stores/projectStore.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 项目名称、题材、简介属于基础描述，可随时修改。
- 目标字数和目标章节数属于章节规划约束；项目已有章节后不再允许修改，避免影响后续章节规划和进度判断。

## 2026-05-19 - 长篇承载第一步：分卷规划

### 本次完成
- 新增 `project_volumes` 分卷 / 阶段规划表，作为长篇小说的阶段锚点。
- 新增分卷规划后端接口：
  - `GET /projects/{pid}/volumes`
  - `POST /projects/{pid}/volumes`
  - `PUT /projects/{pid}/volumes/{vid}`
  - `DELETE /projects/{pid}/volumes/{vid}`
- 项目导入导出补充分卷规划数据 `projectVolumes`。
- 项目删除时同步清理分卷规划，避免残留数据。
- 前端新增 `volumeStore` 管理分卷数据。
- 章节管理页新增“分卷规划”模块，支持：
  - 按项目目标章节快速初始化分卷；
  - 手动新增 / 编辑 / 删除分卷；
  - 维护章节范围、目标字数、阶段目标、核心冲突、关键人物、阶段摘要和状态；
  - 删除分卷时若范围内已有章节，会提示删除只移除规划，不删除正文。

### 修改文件
- `backend/database.py`
- `backend/main.py`
- `backend/schema.sql`
- `backend/routers/helpers.py`
- `backend/routers/projects.py`
- `backend/routers/export.py`
- `backend/routers/volumes.py`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/volumeStore.js`
- `frontend/src/components/chapter/VolumePlanner.vue`
- `frontend/src/views/ProjectView.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。

### 当前决策
- 分卷规划是长篇工程化的第一层结构，不直接修改章节正文。
- 先把“卷”作为人工可控的阶段锚点落地，后续再把章节生成上下文、阶段总结、伏笔回收审计接入分卷范围。

## 2026-05-19 - 分卷审稿 v1

### 本次完成
- 在 `project_volumes` 中新增 `audit_report` 和 `audit_updated_at` 字段，用于保存每一卷最近一次审稿结果。
- 新增分卷上下文接口 `GET /projects/{pid}/volumes/{vid}/context`，返回该卷章节范围内的章节列表、定稿正文和统计信息。
- 新增分卷审稿保存接口 `PUT /projects/{pid}/volumes/{vid}/audit`。
- 前端新增 `volumeAudit` Prompt，按分卷目标、章节摘要、正文节选、Canon 事实、设定库、关系和伏笔生成阶段审稿报告。
- `memoryStore` 新增 `auditVolume`，复用审稿模型绑定生成分卷报告。
- 分卷规划卡片新增“分卷审稿 / 重新审稿 / 查看报告”操作。
- 审稿报告会保存到当前分卷，并支持回看：
  - 总体评价
  - 阶段判断
  - 当前优点
  - 主要问题
  - 人物弧光
  - 设定一致性
  - 伏笔状态
  - 节奏判断
  - 下一步建议
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`，把分卷 / 阶段审稿写回需求文档。

### 修改文件
- `backend/database.py`
- `backend/schema.sql`
- `backend/routers/helpers.py`
- `backend/routers/volumes.py`
- `frontend/src/api/db/client.js`
- `frontend/src/prompts/volumeAudit.js`
- `frontend/src/stores/memoryStore.js`
- `frontend/src/stores/volumeStore.js`
- `frontend/src/components/chapter/VolumePlanner.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 分卷审稿 v1 先保存“每卷最近一次报告”，不做历史报告表。
- 审稿上下文以“章节摘要 + 关键正文节选 + 结构化记忆”为主，不强行塞整卷全部正文，优先保证稳定和可用。

### 下一步
- 做“分卷阶段总结”，让每卷在写作推进过程中自动沉淀阶段事实和接力点。
- 再把分卷规划 / 阶段总结接入写作台上下文，提升长篇连续生成的稳定性。

## 2026-05-19 - 分卷阶段总结 v1

### 本次完成
- `project_volumes` 新增 `stage_summary_report` 和 `summary_updated_at` 字段，用于保存每卷最近一次阶段总结。
- 新增后端接口 `PUT /projects/{pid}/volumes/{vid}/summary-report`，保存结构化阶段总结，并同步更新分卷卡片摘要。
- 前端新增 `volumeSummary` Prompt，要求 AI 输出阶段总览、已完成节点、未解问题、人物变化、设定变化、伏笔状态、下一卷接力点、连续性约束和下一卷剧情种子。
- `memoryStore` 新增 `summarizeVolume`，复用分卷上下文接口，读取章节摘要/正文节选、创作圣经、Canon 事实、设定库、关系、伏笔和最近审稿报告。
- `volumeStore` 新增 `saveStageSummary`。
- 分卷卡片新增“生成总结 / 更新总结 / 查看总结”操作，并展示最近总结时间。
- 新增“分卷阶段总结”弹窗，支持回看结构化总结内容。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`，把分卷阶段总结写回需求规划。

### 修改文件
- `backend/database.py`
- `backend/schema.sql`
- `backend/routers/helpers.py`
- `backend/routers/volumes.py`
- `frontend/src/api/db/client.js`
- `frontend/src/prompts/volumeSummary.js`
- `frontend/src/stores/memoryStore.js`
- `frontend/src/stores/volumeStore.js`
- `frontend/src/components/chapter/VolumePlanner.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 阶段总结先保存“每卷最近一次结果”，不单独做历史版本表。
- 分卷总结会更新分卷摘要，方便卡片快速浏览；完整结构化内容仍保存在 `stage_summary_report` 中。
- 阶段总结不自动改写设定库，设定变更仍走章节定稿后的待确认流程，避免已写设定被阶段总结反向覆盖。

## 2026-05-19 - 写作台接入分卷阶段上下文

### 本次完成
- `buildWritingContext` 新增分卷识别能力，会根据当前章节号找到所属分卷。
- 写作上下文新增 `volumeStage`，包含：
  - 当前分卷标题、章节范围、目标字数、状态。
  - 分卷目标、核心冲突、关键人物。
  - 分卷短摘要、阶段总结、已完成节点、未解问题。
  - 人物变化、设定变化、伏笔状态、下一卷接力点、连续性约束。
  - 最近分卷审稿结论和待处理问题。
  - 最近两个前卷阶段摘要。
- 章节小纲、生成本章、多候选版本会自动注入分卷阶段上下文。
- 续写、扩写、选区改写也接入轻量分卷上下文，减少局部操作跑偏。
- 写作台顶部新增当前章节所属分卷标签，便于用户确认本章承接位置。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`。

### 修改文件
- `frontend/src/utils/contextBuilder.js`
- `frontend/src/prompts/chapter.js`
- `frontend/src/prompts/rewrite.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/views/WriterView.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 分卷上下文作为“中间层约束”注入写作任务，不要求模型读取整卷全文。
- 续写和局部改写只注入必要的分卷、设定和事实信息，避免局部操作被过多历史资料压垮。
- 分卷上下文不替代设定库；人物境界、功法、归属、关系等仍以设定库和 Canon 事实为准。

## 2026-05-19 - 全局审稿 v1

### 本次完成
- 新增 `project_audit_reports` 表，用于保存项目级审稿报告。
- 新增后端接口：
  - `GET /projects/{pid}/global-audits`
  - `POST /projects/{pid}/global-audits`
  - `DELETE /projects/{pid}/global-audits/{rid}`
- 项目导入导出补充 `projectAuditReports`，避免全局审稿报告丢失。
- 前端新增 `globalAudit` Prompt，要求 AI 从主线、人物、设定、伏笔、节奏、读者承诺六个角度输出结构化审稿报告。
- `novelStore` 新增全局审稿报告加载、生成、删除能力。
- 项目页顶部新增“全局审稿”按钮，生成后弹窗展示完整报告。
- 项目页新增最近全局审稿提示，可回看最近报告。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`。

### 修改文件
- `backend/database.py`
- `backend/schema.sql`
- `backend/routers/helpers.py`
- `backend/routers/novel.py`
- `backend/routers/export.py`
- `frontend/src/api/db/client.js`
- `frontend/src/prompts/globalAudit.js`
- `frontend/src/stores/novelStore.js`
- `frontend/src/views/ProjectView.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 全局审稿 v1 保存历史报告，但项目页默认只展示最近一次。
- 全局审稿只提出项目级风险和行动建议，不自动改写圣经、设定库、分卷规划或章节正文。
- 上下文以结构化摘要为主，不塞全书全文；后续可补“指定章节范围审稿”或“审稿后生成修订任务清单”。

## 2026-05-19 - 审稿纠偏任务 v1

### 本次完成
- 新增 `correction_tasks` 表，用于保存审稿发现后的纠偏任务。
- 新增后端接口：
  - `GET /projects/{pid}/correction-tasks`
  - `POST /projects/{pid}/correction-tasks`
  - `POST /projects/{pid}/correction-tasks/bulk`
  - `PUT /projects/{pid}/correction-tasks/{task_id}`
  - `DELETE /projects/{pid}/correction-tasks/{task_id}`
- 项目导入导出补充 `correctionTasks`。
- 前端新增 `correctionTaskStore`，支持加载、批量创建、状态更新和删除。
- 新增 `CorrectionTaskBoard` 任务板，支持按状态筛选，以及接受、处理中、完成、拒绝。
- 分卷审稿报告新增“生成纠偏任务”按钮，可从 `issues` 转成分卷纠偏任务。
- 全局审稿报告新增“生成纠偏任务”按钮，可从 `criticalIssues` 和 `nextActions` 转成全局纠偏任务。
- 项目页新增“6 纠偏任务”流程入口和未完成任务提醒。
- 写作台上下文新增未完成纠偏任务，生成小纲、正文、续写和局部改写时会提醒 AI 避免继续扩大问题。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`。

### 修改文件
- `backend/database.py`
- `backend/schema.sql`
- `backend/main.py`
- `backend/routers/helpers.py`
- `backend/routers/export.py`
- `backend/routers/correction_tasks.py`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/correctionTaskStore.js`
- `frontend/src/components/correction/CorrectionTaskBoard.vue`
- `frontend/src/components/chapter/VolumePlanner.vue`
- `frontend/src/views/ProjectView.vue`
- `frontend/src/views/WriterView.vue`
- `frontend/src/utils/contextBuilder.js`
- `frontend/src/prompts/chapter.js`
- `frontend/src/prompts/rewrite.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 纠偏任务 v1 只做任务化和状态流转，不自动改正文、设定库、伏笔或圣经。
- 正文相关纠偏后续如果支持应用，也只能生成候选版本，不直接覆盖正文。
- 设定/Canon/伏笔类纠偏后续可接入“待确认变更”，仍由用户确认后入库。

## 2026-05-19 - 纠偏任务应用 v2（低风险入口）

### 本次完成
- 纠偏任务状态文案调整：底层仍使用 `rejected`，界面展示为“忽略本次”，更贴合作品创作里的主动偏离。
- 纠偏任务板新增“生成Canon候选”：
  - 从任务标题、描述、建议动作生成待确认 Canon 事实。
  - Canon 事实状态为 `pending_review`，需要用户在 Canon 面板确认后才生效。
- 纠偏任务板新增“生成设定候选”：
  - 从任务生成待确认设定变更事件。
  - 设定变更状态为 `pending_review`，需要用户在设定库变更面板确认后才入库。
- 生成候选后，纠偏任务自动进入“处理中”，表示已经转入对应模块等待确认。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`。

### 修改文件
- `frontend/src/components/correction/CorrectionTaskBoard.vue`
- `frontend/src/stores/correctionTaskStore.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 纠偏任务 v2 先只支持低风险应用：Canon 候选、设定变更候选。
- 不自动改正文，不自动覆盖正式设定。
- 伏笔、分卷规划、创作圣经类任务后续先做“跳转定位”，再考虑可控的局部应用。

## 2026-05-19 - 选题顾问种子落库与结局锚点修复

### 本次完成
- 选题雷达 AI 顾问的种子生成模板补回 `endingAnchor`，结局锚点继续作为长篇收束字段保留。
- 选题顾问对话在用户明确要求生成/保存种子时，如果首次解析 AI 回复失败，会追加一次 JSON 修复器调用后再尝试落库。
- 选题顾问种子保存成功后强制刷新种子 Store，避免聊天侧已创建但种子页未同步。
- 种子解析器保留 Markdown 代码块内文本参与中文标签兜底解析，避免代码块 JSON 略有问题时直接丢失可提取内容。
- 当用户要求生成种子但无法解析或保存时，会把失败原因写入聊天消息元数据，便于回看排查。

### 修改文件
- `frontend/src/prompts/market.js`
- `frontend/src/stores/marketStore.js`
- `frontend/src/utils/seedParser.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- `endingAnchor` 不取消。它不是第一章写作必须字段，但对长篇终局方向、主题归宿和后续圣经生成很有价值。
- 选题顾问生成种子不是“只把 JSON 发到聊天框”，必须完成解析、修复、落库和种子页同步闭环。

## 2026-05-19 - 流程状态同步与创作阶段保护

### 本次完成
- 项目页创作准备流程改为真实数据驱动状态：
  - 种子：无种子为“待完善”，有候选无选中为“待确认”，有选中为“已就绪”。
  - 圣经：有核心内容为“已就绪”。
  - 设定库：有待确认变更为“有待确认”，有正式设定为“已就绪”。
  - 章节：已有正文或定稿为“已开始”。
  - 纠偏：有未完成任务为“待处理”，已处理过为“已处理”。
- 创建第一条种子时自动设为当前选中种子，顶部流程直接进入“已就绪”；后续新增种子不覆盖当前选中。
- 清空种子后，种子 Store 清空，流程状态自然回到“待完善”。
- 项目已有正文内容后，禁止新增、导入、生成、修改、另存、选择、删除或清空创作种子。
- 项目已有正文内容后，禁止删除创作圣经；圣经仍允许局部编辑，但保存前弹出写作阶段风险确认。
- 项目已有正文内容后，禁止清空设定库；仍允许维护单条设定和关系，保留变更连续性。
- 阶段重置确认组件新增 `blockWhenChapterContent` 保护开关，用于核心规划资产的硬拦截。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`。

### 修改文件
- `frontend/src/views/ProjectView.vue`
- `frontend/src/stores/seedStore.js`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `frontend/src/components/bible/CreativeBible.vue`
- `frontend/src/components/settings-library/SettingLibrary.vue`
- `frontend/src/composables/useResetConfirmation.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 创作开始前允许自由重置种子、圣经和设定库；创作开始后，核心资产只能局部维护，不能整块清空或删除。
- 种子是前期选题资产，进入正文创作后不再作为可重写地基使用；后续大改应走纠偏任务、新草案或人工迁移流程。

## 2026-05-19 - 选题顾问更新当前种子入口

### 本次完成
- AI 选题顾问输入区新增“更新当前种子”按钮。
- “生成新种子”继续保留，用于新增候选种子。
- “更新当前种子”会基于当前选中种子、选题雷达数据和最近对话，要求 AI 输出完整修订版种子 JSON，并应用到当前选中的种子。
- 选题顾问更新识别规则补充“最新种子/当前种子”前置表达，避免按钮指令被误判为新增。
- 选题顾问 Prompt 中标记已有种子的“当前选中/候选”状态，帮助 AI 明确要更新的对象。

### 修改文件
- `frontend/src/components/market/AIChatPanel.vue`
- `frontend/src/stores/marketStore.js`
- `frontend/src/prompts/market.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 选题顾问里“生成新种子”和“更新当前种子”是两个独立动作：前者新增候选，后者修改已选中种子。

## 2026-05-19 - 待确认设定变更编辑

### 本次完成
- 设定库“待确认设定变更”列表新增“编辑”按钮。
- 新增编辑弹窗，支持在确认入库前调整：
  - 实体类型。
  - 绑定已有实体。
  - 实体名称。
  - 变更类型。
  - 字段路径。
  - 章节号。
  - 置信度。
  - 原值 / 新值。
  - 证据。
- 编辑后仍保持 `pending_review` 状态，用户可以继续确认或拒绝。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`。

### 修改文件
- `frontend/src/components/settings-library/SettingLibrary.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- AI 提取设定变更不能默认完美，确认前必须允许人工修正关键字段。
- 编辑弹窗先保持通用字段，不为不同实体类型拆复杂表单，避免设定库入口过重。

## 2026-05-19 - 创作种子结局锚点输出规则

### 本次完成
- 强化选题顾问种子 Prompt：`endingAnchor` 字段必须保留，能判断时输出终局画面、情绪收束或主题归宿；信息不足时填空字符串。
- 强化创作种子 AI 生成 Prompt：每个种子对象必须包含 `endingAnchor` 字段，但该字段不作为阻塞保存的必填内容。
- 强化种子 JSON 修复 Prompt：原文没有结局锚点时补空字符串，不删除字段。

### 修改文件
- `frontend/src/prompts/market.js`
- `frontend/src/prompts/seed.js`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 结局锚点继续保留在创作种子模型中；它用于长篇方向和主题收束，不等于固定详细结局。

## 2026-05-19 - 主规划同步整理

### 本次完成
- 将近期需求变更从开发日志沉淀到 `PRODUCT_DEVELOPMENT_PLAN.md` 对应章节：
  - 用户核心流程补充选题顾问“生成新种子 / 更新当前种子”和结局锚点说明。
  - 选题雷达补充对话历史持久化、种子落库闭环、解析失败提示和 `endingAnchor` 字段规则。
  - 创作种子补充字段清单、首个种子自动选中、流程状态规则和写作阶段锁定规则。
  - 新增“创作流程状态”章节，统一待完善、待确认、已就绪、有待确认、已开始、待处理等状态口径。
  - 创作圣经补充生成限制、一次性提取到设定库、写作后禁止删除和局部编辑提醒。
  - 设定库补充待确认变更确认前编辑字段、写作后禁止清空设定库的规则。

### 修改文件
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 文档整理，无需构建。

### 当前决策
- `PRODUCT_DEVELOPMENT_PLAN.md` 保存稳定产品规则；细粒度实现历史继续记录在 `DEVELOPMENT_LOG.md`。

## 2026-05-19 - 纠偏任务定位处理

### 本次完成
- 纠偏任务板新增“定位处理”按钮。
- 根据任务目标模块和问题类型自动定位：
  - 圣经类任务跳转到创作圣经。
  - 设定 / 人物类任务跳转到设定库。
  - 伏笔类任务跳转到伏笔看板。
  - 主线 / 结构 / 分卷规划类任务跳转到章节管理。
  - 章节 / 节奏 / 情绪类任务优先进入写作台对应章节。
- 点击定位后，待确认或已接受任务会自动进入“处理中”。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`。

### 修改文件
- `frontend/src/components/correction/CorrectionTaskBoard.vue`
- `frontend/src/views/ProjectView.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 伏笔、分卷规划、创作圣经和正文类纠偏先做定位处理，不自动修改正式内容。

## 2026-05-19 - 风格试写主风格持久化

### 本次完成
- 风格试写对比结果按 `projectId + seedId` 保存到本地存储，刷新种子页后可恢复对比结果和已选主风格。
- “设为主风格”按钮在当前已选风格上显示为“已选风格”，未选中的结果仍显示“设为主风格”。
- 当前选中种子卡片底部提示改为显示具体风格名称：`已选择风格：xxx。创建创作圣经时会写入风格基准。`
- 新生成风格试写时不再默认选中第一项，必须由用户主动设为主风格；清空对比会同步清除已选风格提示和本地缓存。
- 修复种子页和风格试写组件中部分历史乱码导致的模板 / 字符串损坏问题。

### 修改文件
- `frontend/src/stores/styleTrialStore.js`
- `frontend/src/components/seed/StyleTrialPanel.vue`
- `frontend/src/components/seed/SeedWorkbench.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

## 2026-05-19 - 种子页按钮乱码修复

### 本次完成
- 修复种子页顶部按钮、当前种子操作按钮、AI 生成弹窗按钮、手动创建弹窗按钮、详情弹窗按钮中的乱码文案。
- 修复风格试写组件“清空对比”按钮乱码。
- 扫描 `frontend/src/components/seed` 下种子相关组件，剩余乱码只存在历史注释，不影响界面显示。

### 修改文件
- `frontend/src/components/seed/SeedWorkbench.vue`
- `frontend/src/components/seed/StyleTrialPanel.vue`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍出现既有动态导入告警：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。
## 2026-05-19 - 全局审稿范围选择

### 本次完成
- 全局审稿新增范围选择弹窗，支持“全书”和“指定章节”两种模式。
- 指定章节模式下，可填写起始章节和结束章节；系统会按章节号裁剪章节摘要、Canon 事实和设定变更上下文。
- 全局审稿 Prompt 增加审稿范围说明，要求 AI 只审当前范围，同时判断该范围对后续全书推进的影响。
- 审稿报告标题写入审稿范围，例如“项目名 第 10-20 章审稿”，方便后续回看区分。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`，记录全局审稿范围选择规则。

### 修改文件
- `frontend/src/prompts/globalAudit.js`
- `frontend/src/views/ProjectView.vue`
- `frontend/src/stores/novelStore.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍提示既有动态导入警告：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 范围审稿先作为“局部审稿入口”使用，不自动修改正文、设定库或圣经。
- 审稿后如需处理问题，仍通过纠偏任务板转成可执行任务，由用户确认后再进入 Canon、设定库、章节或圣经模块处理。
## 2026-05-19 - 项目基础信息编辑

### 本次完成
- 项目库项目卡片新增“编辑”入口，可调整项目名称、题材和简介。
- 编辑弹窗支持目标字数、目标章节数修改，但会先检查项目内容状态。
- 当项目已有章节或正文/候选版本时，目标字数和目标章节数自动锁定，并显示锁定原因，避免影响后续章节规划和进度判断。
- 清理项目库首页乱码文案，恢复新建、导入、导出、编辑、删除、打开等按钮和弹窗中文显示。
- 清理 `projectStore` 中项目相关错误日志乱码。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md` 的项目库编辑规则。

### 修改文件
- `frontend/src/views/HomeView.vue`
- `frontend/src/stores/projectStore.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- Vite 构建仍提示既有动态导入警告：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 项目名称、题材、简介属于轻量基础信息，可随时编辑。
- 目标字数和目标章节数属于项目规划尺度，已有章节后不在项目库直接修改，后续如果要调整应通过分卷规划或阶段规划承接。
## 2026-05-19 - 核心页面乱码收口与项目详情编辑入口

### 本次完成
- 重写项目详情页 `ProjectView.vue` 的可见文案，清理流程状态、审稿、纠偏、章节管理、项目信息、弹窗和按钮中的历史乱码。
- 项目详情页顶部新增“编辑项目信息”入口，可修改项目名称、题材、简介。
- 项目详情页编辑入口复用项目内容状态检查：已有章节或正文/候选版本时，目标字数和目标章节数自动锁定。
- 重写写字台 `WriterView.vue` 的可见文案，清理顶部工具栏、章节列表、AI 工具区、小纲弹窗、审稿弹窗、节奏分析弹窗和导出提示中的历史乱码。
- 修复设置页标题乱码。
- 重写后端项目路由文案，项目不存在、目标规划锁定等接口错误提示恢复为中文。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`，补充项目详情页编辑入口和核心页面文案可读性要求。

### 修改文件
- `frontend/src/views/ProjectView.vue`
- `frontend/src/views/WriterView.vue`
- `frontend/src/views/SettingsView.vue`
- `backend/routers/projects.py`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `git diff --check` 通过。
- Vite 构建仍提示既有动态导入警告：`writerStore` 同时被静态和动态引用；不影响当前功能，可后续单独清理。

### 当前决策
- 项目详情页和项目库都允许编辑项目基础信息；目标字数/章节数在写作开始后锁定。
- 写字台这次只清理文案和保留原有流程，不改变正文生成、定稿、记忆提取和多候选版本的业务逻辑。
## 2026-05-19 - 正文类纠偏候选草案

### 本次完成
- 清理纠偏任务板可见乱码，恢复任务状态、按钮、说明、标签等中文文案。
- 清理 `correctionTaskStore` 中纠偏任务状态和审稿转任务文案乱码。
- 新增 `correctionDraft` Prompt，用于根据纠偏任务和原章节正文生成完整章节修订候选稿。
- `writerStore` 新增 `generateCorrectionDraft` 方法：读取模型输出后创建 `correction_candidate` 类型章节版本。
- 纠偏任务板新增“生成章节修订草案”按钮：
  - 仅对章节类、节奏类、情绪类、剧情类或带章节引用的任务显示。
  - 自动读取对应章节的定稿版本或最新候选版本作为修订源。
  - 生成结果保存为新的章节候选版本，不覆盖正文，不自动定稿。
  - 成功后任务进入“处理中”，用户可到写字台版本列表审阅。

### 修改文件
- `frontend/src/components/correction/CorrectionTaskBoard.vue`
- `frontend/src/stores/correctionTaskStore.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/prompts/correctionDraft.js`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check` 通过。
- Vite 构建仍提示既有动态导入警告：`writerStore` 同时被静态和动态引用；新增纠偏任务板引用后警告列表包含该组件，但不影响当前功能。

### 当前决策
- 正文类纠偏只生成候选版本，绝不直接覆盖当前正文。
- 纠偏任务是否完成仍由用户判断；生成草案只代表进入“处理中”。
## 2026-05-19 - 纠偏候选版本识别与对比池

### 本次完成
- 重写章节版本列表文案，清理历史乱码。
- 版本列表新增 `correction_candidate` 类型识别，显示为“纠偏候选”。
- 版本卡片显示 `promptBrief` 来源说明，纠偏候选可看到对应纠偏任务来源。
- 版本列表新增“加入对比 / 已加入对比”操作，可把任意版本加入对比池。
- 写字台接入版本对比事件，加入或移除版本时给出提示。
- 对比池组件同时展示多模型对比结果和手动加入的版本，支持从对比池移除。
- 清理多模型对比弹窗和 compareStore 的乱码文案。
- 同步更新 `PRODUCT_DEVELOPMENT_PLAN.md`，补充纠偏候选版本和对比池规则。

### 修改文件
- `frontend/src/components/writer/ChapterVersionList.vue`
- `frontend/src/components/writer/CompareInline.vue`
- `frontend/src/components/writer/CompareModal.vue`
- `frontend/src/stores/compareStore.js`
- `frontend/src/views/WriterView.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check` 通过。
- Vite 构建仍提示既有动态导入警告：`writerStore` 同时被静态和动态引用；不影响当前功能。

### 当前决策
- 纠偏候选不自动采纳，必须在版本列表中人工审阅、对比、再定稿。
- 对比池先做轻量版本集合，不强制两栏 diff；后续如需要再做逐段差异对比。

## 2026-05-19 - 对比池版本差异视图

### 本次完成
- 写字台对比池新增“差异对比”入口，当对比池内至少有两个版本时可打开。
- 新增版本差异弹窗，支持选择基准版本和对比版本。
- 差异视图提供字数变化、新增段落、删除段落、保留段落和改动段落预览。
- 差异算法使用本地段落级 LCS 对比，优先帮助用户判断纠偏候选是否值得采纳，不依赖额外 AI 调用。
- 支持从差异弹窗加载对比版本到编辑器，但不会自动覆盖定稿，也不会自动完成纠偏任务。

### 修改文件
- `frontend/src/components/writer/VersionDiffModal.vue`
- `frontend/src/views/WriterView.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `git diff --check` 通过。
- Vite 构建仍提示既有动态导入警告：`writerStore` 同时被静态和动态引用；不影响当前功能。

### 当前决策
- 差异视图只做审阅辅助，不自动采纳。
- 纠偏候选的正式采用仍走用户人工加载、编辑、保存版本或确认定稿流程。

## 2026-05-20 - 纠偏任务上下文过滤

### 本次完成
- 纠偏任务 store 新增上下文活跃任务集合，明确只有 `pending`、`accepted`、`in_progress` 会进入写作台 AI 上下文。
- `done`、`rejected`、`ignored`、`cancelled`、`archived` 统一视为关闭状态，不再计入未完成纠偏任务。
- 写作上下文构建器优先读取上下文活跃任务，避免已完成或已忽略任务继续影响生成、小纲、续写和选区改写。
- 章节引用过滤兼容字符串和数字，避免 `chapterRefs` 类型不一致导致任务匹配错位。
- 纠偏任务板的“忽略本次”增加确认弹窗，并说明忽略后会从写作台 AI 上下文移除，但历史任务仍保留。
- 纠偏任务板说明文案补充“已完成或忽略的任务不会再进入写作台 AI 上下文”。

### 修改文件
- `frontend/src/stores/correctionTaskStore.js`
- `frontend/src/utils/contextBuilder.js`
- `frontend/src/components/correction/CorrectionTaskBoard.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `git diff --check` 通过。

### 当前决策
- 忽略本次不是物理删除，而是关闭任务并保留历史。
- 关闭类纠偏任务不再进入 AI 写作上下文，避免用户已经放弃的问题反复污染后续正文。

## 2026-05-20 - 纠偏候选定稿完成闭环

### 本次完成
- 纠偏任务生成章节修订候选时，会在版本来源说明中写入关联纠偏任务 ID。
- 写字台定稿版本时，如果当前版本来自纠偏任务，会自动把对应纠偏任务标记为 `done`。
- 自动完成任务不会打断原有定稿流程，后续仍继续执行清空临时草稿、记忆提取和审稿结果展示。
- 版本列表会隐藏内部关联标记，用户只看到正常的来源说明。

### 修改文件
- `frontend/src/stores/writerStore.js`
- `frontend/src/views/WriterView.vue`
- `frontend/src/components/writer/ChapterVersionList.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `git diff --check` 通过。

### 当前决策
- 纠偏任务和纠偏候选版本采用轻量来源标记关联，暂不新增版本 metadata 字段，避免数据库迁移。
- 只有用户确认纠偏候选为定稿后，任务才自动完成；生成候选或加载候选都不代表任务已解决。

## 2026-05-20 - 定稿后设定库自动提取增强

### 本次完成
- 重写设定变更提取 Prompt，明确从定稿章节提取人物、势力、地点、体系、功法、物品和关系变化。
- 设定提取上下文新增已有关系列表，AI 在生成候选时可以避免重复创建关系。
- 定稿后保存设定候选前新增标准化和去重：同一章节、同一实体、同一字段、同一新值不会重复写入待确认变更。
- 新增对 relationship 类型候选的规范化处理，确保关系候选可被后端设定库确认逻辑消费。
- 设定库“待确认设定变更”区域新增“批量确认”和“批量拒绝”，便于处理章节定稿后产生的多条低风险候选。

### 修改文件
- `frontend/src/prompts/settingExtraction.js`
- `frontend/src/stores/memoryStore.js`
- `frontend/src/components/settings-library/SettingLibrary.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `git diff --check` 通过。

### 当前决策
- 定稿后设定提取仍然只生成待确认候选，不直接写入正式设定库。
- 批量确认是效率工具，不改变“正式设定必须由用户确认”的原则。

## 2026-05-20 - 设定库冲突检测基础版

### 本次完成
- 待确认设定变更新增冲突检测：当候选会覆盖已有概要、分类、状态、人物归属、境界、功法、武器、位置、势力控制、体系规则、物品持有者等硬设定时，界面显示“冲突风险”。
- 冲突候选卡片展示具体风险说明，例如“境界将从 A 变为 B”。
- 单条确认冲突候选时弹出二次确认，用户必须明确选择“仍然确认”才会写入设定库。
- 批量确认时自动跳过有冲突风险的候选，只确认低风险变更，并提示跳过数量。
- 关系类候选会检查已有 source-target-relationType 关系，发现重复或立场/说明变化时提示风险。

### 修改文件
- `frontend/src/components/settings-library/SettingLibrary.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `git diff --check` 通过。

### 当前决策
- 冲突检测先做前端基础版，不阻止用户强制确认。
- 批量确认默认保守：跳过冲突项，要求用户逐条审阅。

## 2026-05-20 - 写作台上下文预览

### 本次完成
- 新增 `ContextPreviewModal`，用于展示写作台当前会注入 AI 的核心上下文。
- 写作台右侧 AI 工具区新增“预览 AI 上下文”入口；上下文页新增“预览本章 AI 上下文”入口。
- 预览内容复用真实的 `buildWritingContext` 和写作台补充上下文逻辑，包含创作种子、作品定位、本章目标、分卷上下文、设定库摘要、最近设定变更、未完成纠偏任务、Canon 事实、伏笔、风格要求、禁止方向、正文顺序规则和当前草稿片段。
- 弹窗显示已注入上下文数量、token 估算和缺失项，方便排查 AI 为什么没有承接某些设定。
- 上下文预览只用于透明化，不会修改 Prompt 或自动补全资料。

### 修改文件
- `frontend/src/components/writer/ContextPreviewModal.vue`
- `frontend/src/views/WriterView.vue`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `git diff --check` 通过。

### 当前决策
- 上下文预览先做只读基础版；后续如果需要，可再增加“复制上下文”和“按模块跳转补资料”。
## 2026-05-21 - 设定库已有正文后的删除保护

### 问题
- 项目已有章节内容时，`清空设定库` 已经会被阻止，但设定库内的单个实体和关系仍然可以点击删除。
- 单条删除会破坏后续写作、审稿、纠偏依赖的长期设定连续性，风险与清空设定库同类。

### 本次完成
- 项目详情页新增项目内容状态读取，并把“已有章节内容”的删除锁传入设定库。
- 设定库实体删除新增业务拦截：已有章节内容时不允许物理删除人物、地点、势力、体系、功法、物品等实体。
- 设定库关系删除新增同样拦截：已有章节内容时不允许物理删除实体关系。
- 拦截时使用手动关闭弹窗说明原因，并提示改用修改设定、调整状态为隐藏/失效/存档，或通过待确认设定变更记录修正。

### 修改文件
- `frontend/src/views/ProjectView.vue`
- `frontend/src/components/settings-library/SettingLibrary.vue`
- `DEVELOPMENT_LOG.md`

### 当前决策
- 已进入章节写作后，设定库不再允许物理删除正式设定资产；后续只能通过“修改/状态变更/设定变更记录”保留可追溯历史。
## 2026-05-21 - 分卷与章节删除安全规则

### 问题
- 章节管理中可以删除当前分卷，即使该分卷范围内已有章节，容易造成“分卷规划被删但章节仍存在”的结构断层。
- 章节列表没有删除入口；同时前端 store 里旧的 `deleteChapter` 只移除本地数组，没有真正调用后端删除。

### 本次完成
- 分卷删除改为保守规则：当前分卷范围内已有章节时禁止删除，并弹窗提示先移动或删除章节。
- 后端分卷删除接口同步增加校验，防止绕过前端直接删除有章节的分卷。
- 章节列表新增“删除”按钮。
- 章节删除改为只允许删除空章节或仅有小纲的章节；删除时会同步清理该章小纲。
- 如果章节已有正文、候选版本、定稿、临时草稿、Canon 事实或设定变更记录，后端拒绝物理删除。
- 前端对已有正文/定稿/字数记录的章节先行弹窗拦截，并说明后续应使用“废弃/归档章节”流程。

### 修改文件
- `backend/routers/chapters.py`
- `backend/routers/volumes.py`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/components/chapter/VolumePlanner.vue`
- `frontend/src/views/ProjectView.vue`
- `DEVELOPMENT_LOG.md`

### 当前决策
- 当前版本不做“连同正文资产一起删除”的高风险操作。
- 已产生正文资产的章节后续应走归档/废弃流程，而不是物理删除，以保护长篇写作上下文、记忆、设定库和纠偏链路。
## 2026-05-21 - 全量功能验收清单

### 本次完成
- 新增 `FUNCTION_TEST_CHECKLIST.md`，按真实创作流程整理本地版全量功能验收项。
- 清单覆盖启动、项目库、选题雷达、创作种子、创作圣经、设定库、章节管理、写字台、小纲、正文生成、版本对比、定稿入库、审稿、纠偏、导入导出和多模型配置。
- 清单明确标出当前已规划但待补能力，例如上下文复制/跳转、章节废弃/归档、Word/EPUB/分卷导出。

### 修改文件
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 当前决策
- 后续浏览器端验收优先按照 `FUNCTION_TEST_CHECKLIST.md` 逐项测试；发现问题后按功能块记录并修复。

## 2026-05-22 - 章节管理改为按当前卷创建空章节

### 问题
- 原“批量创建空章节”会按项目目标章节数一次性补齐全书章节，长篇项目会直接创建数百章空记录，过于激进。
- 章节列表展示全书所有章节，不利于围绕当前分卷推进。

### 本次完成
- 分卷卡片支持选中当前卷，选中态会高亮显示。
- 章节列表改为只展示当前卷范围内的章节。
- 章节号继续沿用全书全局编号，例如第 2 卷范围是 61-120 章时，列表显示第 61 章、第 62 章，不会在每卷内重新编号。
- “批量创建空章节”改为“按当前卷创建空章节”，只补齐当前卷章节范围内缺失的空章节，不再一次性创建全书目标章节。
- 保留已有章节、小纲、正文、候选版本和定稿，不做覆盖。

### 修改文件
- `frontend/src/views/ProjectView.vue`
- `frontend/src/components/chapter/VolumePlanner.vue`
- `frontend/src/stores/writerStore.js`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。

## 2026-05-22 - 写字台跨章节连续性与待确认设定保护

### 问题
- 切换到新章节后，对比池仍保留上一章节候选，容易把不同章节版本混入差异对比。
- 点击“查看小纲”时，已经打开小纲弹窗，还会额外弹出“已打开本章小纲，请审阅后再生成正文”的提示，交互重复。
- 正文生成 token 上限偏低，长章可能在句子中途被截断。
- 下一章生成上下文没有强制注入上一章结尾原文，导致章节开头可能跳到全新场景，前后不连贯。
- 上一章定稿后如果产生待确认设定变更，用户未确认就生成下一章时，下一章只会读取已确认设定库，容易遗漏上一章新增状态。

### 本次完成
- 写字台进入页面和切换章节时清空对比池。
- 查看已保存小纲时不再弹出额外成功提示，只保留小纲审阅弹窗。
- 正文生成流式与非流式 `maxTokens` 从 4096 提高到 8192，降低长章中途截断概率。
- 写字台加载当前章时同步读取上一章最终/最新版本的末尾片段，并注入正文生成上下文。
- 章节 Prompt 新增“上一章结尾原文（下一章必须承接）”约束，要求后续章节先承接上一章结尾的情绪、危险、动作或悬念。
- 新增待确认设定变更保护：生成新小纲、正文、多候选、续写、扩写、选区改写和多模型对比前，若设定库存在 `pending_review` 变更，会弹窗阻止，要求先确认或拒绝。

### 修改文件
- `frontend/src/views/WriterView.vue`
- `frontend/src/stores/writerStore.js`
- `frontend/src/prompts/chapter.js`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `npm.cmd --prefix frontend run build` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
### 2026-05-22 - 设定库确认后关系展示修正

- 排查“待确认设定变更确认后，林逐等人物详情看不到大量关系信息”的问题。
- 结论：多数候选是 relationship 类型，确认后写入 `setting_relations`，不会自动并入人物主档案字段；写作上下文可读取关系，但前端默认折叠导致像是信息丢失。
- 已调整：设定实体详情页新增“关联关系摘要”和“已确认变更记录”，直接展示当前实体相关关系与最近确认事件。
- 已调整：待确认关系候选标题从“实体名 + 关系”改为“主体 → 客体 + 关系/立场”，降低重复人物误判。
- 验证：`npm.cmd --prefix frontend run build` 通过；`D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
### 2026-05-22 - 上一章未定稿阻止下一章 AI 创作

- 排查发现：写字台原先只拦截“待确认设定变更”，没有拦截“上一章未定稿”；读取上一章结尾时还会在无定稿版本时使用最新候选版本，存在章节断层风险。
- 已调整：第 2 章及以后，生成小纲、生成正文、多候选生成、多模型对比、续写、扩写和选区改写前，必须检查上一章是否已定稿。
- 已调整：上一章结尾上下文只读取上一章定稿版本，不再使用未定稿候选版本作为下一章承接依据。
- 保留规则：仍允许提前创建空章节和进入章节页面，但不能执行会推进正文的 AI 创作操作。
- 验证：`npm.cmd --prefix frontend run build` 通过；`D:\Software\Python\Python312\python.exe -m compileall backend` 通过。

### 2026-05-22 - 已定稿章节锁死保护

- 规则确认：当前版本不做“修改已定稿章节”能力，避免重新牵动记忆、设定库、上下章衔接和纠偏链路。
- 前端调整：章节已定稿后，写字台正文编辑器锁定；生成本章、重新生成小纲、多候选、续写、扩写、压缩、选区改写、润色、另存版本和删除版本入口禁用或拦截。
- 前端保留：已定稿章节仍可查看正文、小纲、审稿、导出、上下文和记忆。
- 后端调整：章节已定稿后，拒绝新增/修改/删除版本，拒绝保存临时草稿，拒绝保存或删除本章小纲，防止绕过 UI 改动定稿章。

### 2026-05-22 - 设置页任务模型映射刷新回显修正

- 问题：任务模型映射按项目保存，但设置页刷新后可能没有当前项目上下文，导致下拉框恢复为空。
- 已调整：任务模型映射区新增“当前配置项目”选择，刷新后自动恢复上次配置项目。
- 已调整：前端统一规范化模型映射字段，兼容后端返回的不同字段形态，避免保存成功但回显失败。
- 验收补充：功能清单新增“刷新设置页后仍能回显上次配置项目和已选模型”检查项。

### 2026-05-23 - 同章多纠偏综合修订候选

- 问题：同一章存在多条纠偏任务时，逐条点击“生成章节修订草案”会生成多个彼此独立的候选版本，用户只能选择其中一个，无法一次解决全部问题。
- 已调整：正文类硬纠偏任务在同章存在多条未完成任务时，纠偏任务板显示“综合修订本章”按钮。
- 已调整：综合修订会把同章所有可生成章节修订草案的未完成硬纠偏任务一起交给 AI，生成一个完整章节综合修订候选版本。
- 已调整：综合候选版本会记录多个 `correctionTaskId`，该版本定稿后会把关联的多条纠偏任务一起标记完成。
- 保留：单条“生成章节修订草案”仍可用于只想单独参考某个问题的局部修订候选。

### 2026-05-23 - 本章审稿改为即时修订版本

- 产品决策：本章未定稿阶段的审稿属于即时修稿工具，不再要求先生成纠偏任务、再去纠偏任务板流转状态。
- 已调整：本章审稿弹窗底部按钮从“生成本章纠偏任务”改为“生成本章修订版本”。
- 已调整：点击后直接基于当前正文和本次审稿问题生成一个 `correction_candidate` 修订候选版本，进入版本列表，不覆盖当前正文。
- 已调整：生成完成后自动把修订候选加入对比池，并打开“当前正文 vs 修订候选”的差异对比。
- 保留：已定稿章节仍不允许生成正文修订版本；分卷/全局审稿继续走纠偏任务板，用于长期软纠偏和跨章节问题管理。

### 2026-05-23 - 选区去 AI 腔/润色

- 写字台右侧“润色”按钮升级为“去 AI 腔/润色”，继续沿用选区改写链路，避免直接改整章造成不可控变化。
- `polish` 改写模式新增去 AI 腔约束：不改变剧情事实、人物意图、视角和信息量，重点减少套路化反差句、虚化判断、解释腔和模板化升华。
- Prompt 要求将抽象表达优先替换为具体动作、感官细节、物象变化、对白停顿或人物即时反应。
- 功能清单补充去 AI 腔/润色验收项。

### 2026-05-23 - 本章审稿局部修订候选

- 本章审稿弹窗里的“生成本章修订版本”调整为“生成局部修订版本”。
- 新流程不再要求 AI 输出整章重写稿，而是先生成局部替换补丁：原文片段、替换片段、修改原因和置信度。
- 系统只应用能在当前正文中精确匹配且唯一匹配的补丁；无法匹配或重复匹配的补丁会跳过，避免误改相似段落。
- 应用补丁后的完整正文会保存为 `correction_candidate` 候选版本，自动加入对比池并打开差异对比；当前正文不被覆盖。
- 保留原有整章纠偏候选函数给纠偏任务板使用，本章即时审稿优先走局部修订，减少修订引入新问题。

### 2026-05-23 - 单章目标字数约束

- 问题：项目虽然有目标字数和目标章节数，但正文生成提示词没有明确单章目标体量，导致 300 万字 / 600 章这类项目有时生成 1 万字以上的超长章节。
- 已调整：写字台上下文会根据项目 `targetWords / targetChapters` 推导本章建议字数，并注入小纲生成和正文生成提示词。
- 已调整：默认合理浮动范围为目标字数的 90%-110%，硬边界为 80%-120%；例如 300 万字 / 600 章得到约 5000 字，建议 4500-5500 字，硬边界 4000-6000 字。
- 已调整：正文生成和多候选生成完成后会评估候选字数，明显超长或偏短时弹窗提醒用户压缩、拆章或补足推进。
- 设计原则：字数约束只作为节奏护栏，不机械截断正文，也不牺牲必要剧情；如果内容自然超量，应优先压缩重复描写、解释性设定和低效对白。
- 验证：`node tmp\test_chapter_word_target.mjs` 通过；`npm.cmd --prefix frontend run build` 通过。

### 2026-05-23 - 本章审稿局部修订失败兜底

- 问题：本章审稿后点击“生成局部修订版本”时，AI 可能只返回 `unpatchable` 或返回无法逐字匹配正文的片段，导致系统弹出“AI 没有返回可应用的局部修订补丁”。
- 根因：局部补丁链路过于严格，只接受 `patches` 且要求 `originalText` 与当前正文完全逐字匹配；审稿问题多为概括性描述时，模型容易不给补丁或忽略换行差异。
- 已调整：局部补丁解析兼容 `changes`、`edits`、`items`、`oldText/newText`、`before/after`、`find/replace` 等常见字段。
- 已调整：补丁应用增加空白差异容错；当 `originalText` 与正文只存在换行或空格差异时，只要压缩空白后唯一命中，就允许安全替换。
- 已调整：AI 首次未返回可用补丁时，会追加一次“重新定位最小原文片段”的局部补丁重试。
- 已调整：如果重试后仍然没有可应用局部补丁，则生成“审稿修订候选”兜底版，进入版本列表并打开差异对比，不覆盖当前正文。
- 验证：`node tmp\test_local_revision_patch.mjs` 通过；`node tmp\test_chapter_word_target.mjs` 通过；`npm.cmd --prefix frontend run build` 通过。

### 2026-05-23 - 定稿后记忆/设定提取门禁

- 问题：上一章定稿后，摘要、记忆事实和设定变更仍在提取时，用户可以关闭提示并进入下一章生成小纲，导致下一章可能读不到上一章刚产生的人物状态和设定变更。
- 已调整：写字台定稿后立即写入章节后处理标记，并显示不可关闭遮罩，处理期间阻止章节切换、AI 生成、续写、改写等推进操作。
- 已调整：第 2 章及以后执行小纲、正文、多候选、续写、扩写、压缩、选区改写和多模型对比前，会检查上一章是否仍处于定稿后处理状态。
- 已调整：定稿后处理完成后清理处理标记；若产生待确认设定变更，继续沿用待确认设定变更门禁，要求用户确认或拒绝后再生成下一章。
- 验收补充：功能清单新增“定稿后处理遮罩”和“上一章处理未完成时阻止下一章生成”检查项。

### 2026-05-23 - 纠偏任务板操作说明补充

- 问题：纠偏任务板中的接受、处理中、定位处理、生成设定候选、生成 Canon 候选、生成章节修订草案、完成和忽略本次等按钮含义不够直观。
- 已调整：纠偏任务板标题说明下方新增常驻操作说明，解释每个按钮点击后的结果、是否会自动改正文/设定库，以及任务是否仍会进入后续 AI 上下文。
- 验收补充：功能清单新增纠偏任务板操作说明检查项。

### 2026-05-24 - 人性动机与代入感护栏

- 问题：AI 正文容易只完成设定、爽点和漂亮句子，但缺少人物欲望、恐惧、遮掩、选择代价和情绪残留，读者代入感不足。
- 已调整：章节正文系统提示词新增“人物代入感 / 人性动机”护栏，要求外部事件必须通过人物内在动机产生代入感，避免人物沦为推动剧情或解释设定的工具人。
- 已调整：本章小纲生成新增“人物动机层”，要求在写正文前明确关键人物想得到什么、害怕失去什么、为什么不能直说、选择代价和情绪残留。
- 已调整：本章审稿新增人物动机与代入感检查，支持 `human_motivation` 和 `emotional_logic` 问题类型，并在前端标签中以中文展示。
- 验收补充：功能清单新增小纲人物动机层、正文人性动机约束和审稿中文标签检查项。

### 2026-05-24 - 纠偏设定候选重复生成保护

- 问题：纠偏任务板中“生成设定候选”可重复点击，每次都会新增一条相同的待确认设定变更。
- 根因：纠偏任务状态变为处理中后仍属于 open 状态，按钮仍显示；前端 store 和后端创建接口都没有按同一来源证据和候选内容做幂等去重。
- 已调整：前端生成设定候选前会加载待确认设定变更，并在已存在同任务候选时显示“已生成设定候选”，阻止重复点击。
- 已调整：`settingStore.saveChangeEvent` 新增待确认候选去重；后端创建 `setting_change_events` 时也会按项目、实体、字段、章节、证据和新值返回已有记录，避免绕过前端重复插入。
- 验收补充：功能清单新增“同一纠偏任务重复生成设定候选不新增重复记录”检查项。

### 2026-05-24 - 选题顾问空种子入库拦截

- 问题：AI 选题顾问聊天中显示“已生成创作种子”，但种子页出现空种子或字段大量为空。
- 根因：种子解析器只要识别到标题、logline 或开局钩子就会当作可保存种子；部分方向建议 JSON 或未确认方案会被误判为种子并入库。
- 已调整：种子解析器新增可保存完整度校验，要求至少有题材，并在一句话、主角、欲望、核心矛盾、开局钩子、情绪价值中满足 3 项。
- 已调整：前端 `createSeed` 和后端 `/seeds` 创建接口都加同样的完整度保护，防止空种子从聊天、手动粘贴或直接接口进入数据库。
- 验收补充：功能清单新增“方向建议/字段不足方案不会生成空种子”检查项。
## 2026-05-24 - 单章字数浮动规则收紧

### 本次完成
- 单章目标字数的正常范围从较宽松的 85%-120% 调整为 90%-110%。
- 单章硬边界调整为 80%-120%，低于硬下限或高于硬上限时都应提醒用户处理。
- 例如 300 万字 / 600 章时，单章目标约 5000 字，正常范围为 4500-5500 字，硬边界为 4000-6000 字。
- 正文生成提示词补充质量优先规则：接近硬上限时主动收束场景，把未展开内容留作下一章钩子；不得为了压字数省略关键动作、情绪转折或因果交代。
- 小纲生成提示词补充单章体量规则：节拍按一章可完成范围设计，剧情自然超量时减少支线节拍，把后续冲突或余波留到下一章。

### 修改文件
- `frontend/src/utils/chapterWordTarget.js`
- `frontend/src/prompts/chapter.js`
- `tmp/test_chapter_word_target.mjs`
- `tmp/test_chapter_word_prompt_guard.mjs`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

## 2026-05-24 - 定稿时默认章名与显示优化

### 本次完成
- 新增章节命名 prompt：用户定稿时，如果当前章节标题仍是默认“第 N 章”，系统会基于定稿正文生成一个默认章名。
- 章名清洗限制为 2-14 个汉字，自动去掉“第 N 章”、书名号、引号、Markdown 标题和“章名：”等包装文本。
- 章名生成失败不会阻断定稿，也不会影响已保存的正文候选版本；后续如新增章节标题编辑入口，只调整章节元数据，不回改已定稿正文。
- 候选版本阶段不再自动改章节标题，避免不同候选版本切换导致章名漂移。
- 写字台顶部改为显示“第 N 章 · 章名”；左侧章节列表保留章节号，并在下一行显示章名。
- TXT / Markdown 导出标题改为包含章节号，有章名时为“第 N 章 · 章名”，无章名时为“第 N 章”。

### 修改文件
- `frontend/src/prompts/chapter.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/views/WriterView.vue`
- `frontend/src/utils/export.js`
- `tmp/test_chapter_title_generation.mjs`
- `tmp/test_chapter_display_title.mjs`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

## 2026-05-25 - 定稿后处理重复触发防护

### 问题
- 在定稿前审稿发现问题后，用户可在审稿弹窗点击“仍然定稿”。如果按钮反馈较慢并被连续点击，可能并发触发多次定稿后摘要、记忆和设定变更提取。
- 同一章节的多次 AI 提取结果不是逐字重复，但会产生大量语义重复的待确认设定变更，增加后续确认成本。

### 本次完成
- 新增定稿运行锁：同一项目、同一章节、同一版本在定稿或定稿后处理期间只能进入一次执行链路。
- 定稿运行锁会在真正调用定稿接口前写入本地 pending 标记，堵住定稿接口返回前的连点窗口。
- 版本列表定稿、轻微问题继续定稿、严重/主要问题后的“仍然定稿”统一走同一条 `performFinalize` 兜底防重链路。
- 定稿执行中禁用相关定稿按钮，并显示处理中提示，避免重复触发记忆/设定提取。

### 修改文件
- `frontend/src/utils/finalizationGuard.js`
- `frontend/src/views/WriterView.vue`
- `frontend/src/components/writer/ChapterVersionList.vue`
- `tmp/test_finalization_guard.mjs`
- `tmp/test_writer_finalization_lock_contract.mjs`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证
- `node .\tmp\test_finalization_guard.mjs` 通过。
- `node .\tmp\test_writer_finalization_lock_contract.mjs` 通过。
- `npm.cmd --prefix frontend run build` 通过。

## 2026-05-28 - 核心写作链路保护与任务模型映射补强

### 本次完成
- 写作台 AI 调用改为优先读取“任务模型映射”，正文创作、小纲规划、审稿/纠偏、摘要压缩、结构化提取、选区改写、润色和章名生成都会按任务类型选择模型，不再固定取第一个 Provider。
- 设置页任务模型映射保存时支持显式清空，刷新后不会把已清空的模型又恢复成空白异常状态。
- 后端新增核心规划保护：项目已有正文内容后，禁止新增、导入、生成、修改、选择、删除或清空创作种子。
- AI 选题顾问生成种子时也会检查项目是否已有正文，避免绕过种子页保护直接写入空种子或覆盖种子。
- 项目已有正文后，禁止从创作圣经再次初始化提取到设定库，避免覆盖已经进入写作阶段的设定体系。
- 项目已有正文后，禁止删除创作圣经、清空设定库、删除设定实体和删除设定关系；章节定稿后的设定变更确认仍允许正常入库。
- 定稿后摘要、事实或设定变更提取如果出现必需步骤失败，会保留章节定稿后处理阻断标记，避免下一章在记忆/设定不完整时继续生成。
- 定稿后章节摘要写回改为专用接口，只更新派生摘要，不再走普通章节更新接口，避免触发“本章已定稿，正文、小纲和版本已锁定”的 409。

### 修改文件
- `backend/routers/guards.py`
- `backend/routers/chapters.py`
- `backend/routers/seeds.py`
- `backend/routers/novel.py`
- `backend/routers/settings_library.py`
- `backend/routers/providers.py`
- `frontend/src/api/db/client.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/stores/marketStore.js`
- `frontend/src/stores/memoryStore.js`
- `frontend/src/utils/finalizationGuard.js`
- `frontend/src/views/WriterView.vue`
- `frontend/src/components/bible/CreativeBible.vue`
- `tmp/test_task_model_bindings_contract.mjs`
- `tmp/test_core_planning_locks_contract.mjs`
- `tmp/test_finalization_postprocess_contract.mjs`
- `tmp/test_finalization_summary_writeback_contract.mjs`
- `tmp/test_provider_bindings_contract.mjs`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `node .\tmp\test_task_model_bindings_contract.mjs` 通过。
- `node .\tmp\test_core_planning_locks_contract.mjs` 通过。
- `node .\tmp\test_finalization_postprocess_contract.mjs` 通过。
- `node .\tmp\test_finalization_summary_writeback_contract.mjs` 通过。
- `node .\tmp\test_provider_bindings_contract.mjs` 通过。
- 既有章节、审稿、纠偏、种子解析、设定去重、定稿锁相关 Node 回归测试通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- `npm.cmd --prefix frontend run build` 通过；仅保留 Vite 既有动态导入提示。

### 当前决策
- 种子、圣经初始化和设定库初始化属于“写作前核心规划”，一旦已有正文内容就锁定。
- 定稿后的设定变更确认属于“写作中增量维护”，不能被核心规划锁误伤。
- 定稿后处理失败时宁可阻断下一章，也不让下一章读取缺失的记忆或设定上下文。

### 未完成 / 阻塞
- 后续可补一个“定稿后处理失败重试 / 解除阻断”入口，当前版本先以阻断保护为主。

### 下一步
- 继续做浏览器端完整链路验收，重点覆盖任务模型映射回显、已有正文后的核心资料锁、定稿后处理失败提示和下一章生成门禁。

## 2026-05-28 - 本地浏览器百万级规模 QA

### 本次完成
- 新增本地浏览器 QA 脚本，通过 Chrome DevTools Protocol 启动 headless Chrome，不依赖 Playwright npm 包。
- 自动创建临时 QA 项目，写入 200 章、每章约 5000 字的定稿正文，总计 1000000 字，用于模拟百万级小说体量。
- 验证首页、设置页、项目详情页、章节管理页和写字台可访问。
- 验证已有正文后，新增种子、删除圣经、删除设定实体会被 409 拦截。
- 验证已定稿章节普通更新被锁定，专用摘要写回接口仍可工作。
- 测试结束后自动删除 QA 项目，避免污染项目库。

### 修改文件
- `tmp/run_browser_qa.mjs`
- `tmp/browser-qa/latest-report.json`
- `tmp/browser-qa/latest-report.md`
- `tmp/browser-qa/*.png`
- `DEVELOPMENT_LOG.md`

### 验证结果
- 浏览器 QA：29/29 项通过。
- 百万级模拟数据：200 章 / 1000000 字。
- 页面加载耗时：项目库约 1268ms，设置页约 976ms，项目详情约 931ms，写字台约 876ms。
- 浏览器控制台错误：0。

### 当前发现
- headless 默认 800px 窄视口下，写字台三栏布局会明显挤压，正文只读提示和中间编辑区展示不够舒适；宽屏桌面可用，但后续需要补响应式优化。

### 下一步
- 后续浏览器验收建议补两档视口：1440px 宽屏主验收、800px 窄屏布局检查。
- 真正接入大模型后的验收仍需单独覆盖：选题抓取、AI 生成种子、圣经生成、设定提取、正文生成、审稿和局部替换。

## 2026-05-28 - 结构化 JSON 输出韧性修复

### 本次完成
- 修复 AI 生成种子、AI 选题顾问生成/更新种子、全局审稿在长 JSON 被截断或格式不稳定时容易直接失败的问题。
- 种子生成新增三段式兜底：正常生成 -> JSON 修复 -> 基于用户输入和可见输出压缩重试，压缩重试只生成 1 条可保存种子并保留 `endingAnchor`。
- AI 选题顾问在用户明确要求生成或更新种子时，也会执行同样的压缩重试，避免对话里看似生成了 JSON、种子页却新增空种子或不新增。
- 全局审稿新增 JSON 修复和精简重试，失败时保留更有效的返回片段，便于定位模型格式问题。
- 将相关结构化调用的 `maxTokens` 从 4096 提升到 6000，降低长字段中途截断概率。

### 修改文件
- `frontend/src/prompts/seed.js`
- `frontend/src/prompts/globalAudit.js`
- `frontend/src/stores/seedStore.js`
- `frontend/src/stores/marketStore.js`
- `frontend/src/stores/novelStore.js`
- `tmp/test_structured_json_resilience_contract.mjs`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `node tmp\test_structured_json_resilience_contract.mjs` 通过。
- `node tmp\test_seed_parser_completeness.mjs` 通过。
- `node tmp\test_market_directions.mjs` 通过。
- `node tmp\test_provider_bindings_contract.mjs` 通过。
- `node tmp\test_task_model_bindings_contract.mjs` 通过。
- `npm.cmd --prefix frontend run build` 通过；仅保留 Vite 既有动态导入提示。

### 下一步
- 从真实流程测试项目 `真实流程测试200万_20260528063230` 继续生成第 3-20 章，每 20 章暂停确认是否继续。

## 2026-05-28 - 记忆事实提取 JSON 韧性修复

### 本次完成
- 真实 200 万字流程续跑时发现：第 4 章定稿后，事实记忆提取返回的 `facts` JSON 被截断，导致流程中断。
- 将章节事实提取补齐为三段式流程：正常结构化输出 -> JSON 修复 -> 极简事实重试。
- 极简事实重试最多输出 3 条短事实，限制 `content/evidence` 长度，避免长篇章节中事实提取再次因输出过长截断。
- 真实流程 QA 脚本同步增加事实提取和设定变更提取的紧凑重试；二次失败时记录失败项并继续生成，便于 20 章节点完整观察问题分布。

### 修改文件
- `frontend/src/prompts/extraction.js`
- `frontend/src/stores/memoryStore.js`
- `tmp/run_realistic_longform_flow.mjs`
- `tmp/test_memory_extraction_json_resilience_contract.mjs`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `node tmp\test_memory_extraction_json_resilience_contract.mjs` 通过。
- `node --check tmp\run_realistic_longform_flow.mjs` 通过。
- `node tmp\test_structured_json_resilience_contract.mjs` 通过。
- `node tmp\test_finalization_postprocess_contract.mjs` 通过。
- `node tmp\test_provider_bindings_contract.mjs` 通过。
- `node tmp\test_task_model_bindings_contract.mjs` 通过。
- `npm.cmd --prefix frontend run build` 通过；仅保留 Vite 既有动态导入提示。

### 下一步
- 继续从项目 `真实流程测试200万_20260528063230` 续跑到第 20 章，重点观察章节字数、审稿问题复发、事实/设定提取稳定性和上下章衔接。

## 2026-05-28 - 真实流程 QA 审稿 JSON 截断兜底

### 本次完成
- 续跑到第 7 章时，章节审稿返回的 `issues` JSON 中途截断，导致测试脚本中断。
- 为真实流程 QA 脚本增加章节审稿结构化兜底：正常审稿 -> JSON 修复 -> 审稿紧凑重试。
- 紧凑重试最多保留 3 个关键问题，并限制 `location/issue/suggestion/replacement` 字段长度，避免审稿报告过长再次截断。
- 若紧凑重试仍失败，记录失败项并让章节继续进入后续流程，便于长篇规模测试持续观察。

### 修改文件
- `tmp/run_realistic_longform_flow.mjs`
- `tmp/test_memory_extraction_json_resilience_contract.mjs`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `node tmp\test_memory_extraction_json_resilience_contract.mjs` 通过。
- `node --check tmp\run_realistic_longform_flow.mjs` 通过。

### 下一步
- 从同一测试项目继续续跑到第 20 章；第 7 章会重新生成/审稿，继续观察审稿 JSON 稳定性。

## 2026-05-28 - 设定变更 status 字段后端容错

### 本次完成
- 真实流程续跑到第 9 章后，自动确认设定变更时后端返回 500。
- 根因：AI 将“人物当前状态变化”输出为 `fieldPath: status`，后端直接写入 `setting_entities.status VARCHAR(30)`；长文本状态导致数据库写入失败。
- 修复：`status` 字段只有 `active/inactive/hidden/archived` 等系统状态才写入实体状态列；普通剧情状态文本改写入 `profile.currentState`。

### 修改文件
- `backend/routers/settings_library.py`
- `tmp/test_setting_event_status_field_contract.mjs`
- `DEVELOPMENT_LOG.md`

### 验证结果
- `node tmp\test_setting_event_status_field_contract.mjs` 通过。
- `D:\Software\Python\Python312\python.exe -m compileall backend` 通过。
- 本地后端已重启，`GET /api/health` 通过。
- 对失败事件 `23413eb1-b16f-4ab3-80fb-7fab4c1f550b` 重新执行确认，接口返回 200。

### 下一步
- 继续从真实流程测试项目续跑到第 20 章；脚本会先处理第 9 章剩余待确认设定变更，再从第 10 章继续。

## 2026-05-28 - 真实流程 QA 质量门禁与多章验收

### 本次完成
- 修复真实长篇流程 QA 脚本中的审稿兜底逻辑：章节审稿 JSON 连续解析失败时，不再被当作“零问题章节”静默放行，而是记录审稿结构化失败、增加纠偏任务并标记质量门禁失败。
- 新增章节字数验收护栏：按项目目标字数 / 目标章节数推导单章目标，记录初稿字数和最终定稿字数；超出硬范围时在报告中标记失败。
- 新增审稿修订字数漂移保护：审稿后的修订候选如果相对原稿字数漂移过大，或超出单章硬边界，会回退到修订前正文并记录失败，避免“修一处问题，整章体量失控”。
- 新增长篇多章一致性验收模块：基于最近最多 20 个已定稿章节的摘要、首尾片段、设定库和 Canon 事实，检查人物设定漂移、情节矛盾、时间线、世界规则、伏笔、重复冗余、风格漂移、状态承接和上下章衔接。
- 真实流程报告新增“多章一致性验收”章节，并区分候选初稿字数与最终定稿字数。

### 修改文件
- `tmp/run_realistic_longform_flow.mjs`
- `tmp/test_realistic_longform_acceptance_contract.mjs`
- `DEVELOPMENT_LOG.md`
- `FUNCTION_TEST_CHECKLIST.md`
- `PRODUCT_DEVELOPMENT_PLAN.md`

### 验证结果
- `node tmp\test_realistic_longform_acceptance_contract.mjs` 通过。
- `node tmp\test_memory_extraction_json_resilience_contract.mjs` 通过。
- `node tmp\test_setting_event_status_field_contract.mjs` 通过。
- `node --check tmp\run_realistic_longform_flow.mjs` 通过。

### 下一步
- 继续从真实流程测试项目续跑下一批章节时，每 20 章查看多章验收报告，重点判断上下章衔接、设定库同步、记忆事实覆盖和章节字数是否稳定。
