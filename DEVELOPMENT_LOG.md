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
- v0.6 设定库与世界观一致性版已开始开发，第一条可用竖切已完成。
- v1.0 本地稳定版调整为待 v0.6 补强后验收。

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

## 版本进度

| 版本 | 状态 | 目标 |
| --- | --- | --- |
| v0.1 本地地基版 | 已完成 | 项目、存储、模型配置、本地导入导出 |
| v0.2 AI 创作闭环版 | 已完成 | 种子、候选章节、写作台、定稿 |
| v0.3 记忆与审稿版 | 已完成 | 摘要、事实、角色状态、伏笔、审稿 |
| v0.4 选题雷达版 | 已完成 | 网页抓取热门排行、分类展示、AI 选题顾问、大纲生成 |
| v0.5 体验增强版 | 已完成 | 多模型对比、融合、风格和节奏分析、人物弧光/伏笔可视化 |
| v0.6 设定库与世界观一致性版 | 开发中 | 人物、势力、世界观、修炼体系、关系图谱、状态变更日志 |
| v1.0 本地稳定版 | 待 v0.6 补强后验收 | 稳定整合和长篇项目验证 |

## 下一步任务

1. 浏览器端用真实章节定稿验证 AI 设定变更提取质量。
2. 在设定库中检查“待确认 → 确认入库”体验，确认是否需要增加逐条编辑弹窗。
3. 继续优化设定提取字段映射，尤其是玄幻/修真场景的境界、功法、法宝、宗门关系。
4. 长篇项目实际写作流程验证，观察设定库注入后章节生成是否减少错乱。

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
