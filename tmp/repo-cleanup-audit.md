# 仓库清理审计报告

审计时间：2026-06-22  
仓库：`D:/Projects/Novel_Creater`  
边界：本次只审计并生成报告；未删除文件，未执行 `git reset` / `git checkout` / `git clean`，未修改 `.gitignore`，未提交，未运行 10/20 章测试。

> 说明：以下 git 状态快照生成于写入本报告之前；本报告自身 `tmp/repo-cleanup-audit.md` 是本次新增的审计产物，未计入快照的 759 条状态。

## 1. 当前分支和 worktree 状态

- 当前分支：`codex/story-block-v1`
- 当前 HEAD：`5535098`
- 工作树：有未提交改动。
- 暂存区：无暂存改动，`git diff --cached --name-status` 输出为空。
- `git status --porcelain=v1 --untracked-files=all` 汇总：
  - 总计：759 条
  - `M` 修改：57 条
  - `D` 删除：553 条
  - `??` 未跟踪：149 条
- `git diff --stat` 跟踪文件统计：610 个跟踪文件变化，约 8,856 行新增、162,630 行删除；其中大量删除来自浏览器 profile/cache。
- `git worktree list`：
  - `D:/Projects/Novel_Creater 5535098 [codex/story-block-v1]`

## 2. 本地/远端分支列表

本地分支：

- `* codex/story-block-v1 5535098 1`
- `main 5535098 [origin/main] 1`

远端分支：

- `origin/main 5535098 1`

远端：

- `origin https://github.com/zjun728/Novel_Creater.git`

## 3. 未提交改动分类总览

| 分类 | 数量与状态 | 审计判断 |
| --- | ---: | --- |
| 核心产品代码/工程配置 | 2：`M=1`，`??=1` | `.gitignore` 已有本地修改，`package.json` 为新增根配置；需进一步确认是否纳入后续提交。 |
| 后端代码 | 10：`M=8`，`??=2` | 包含 story block、AI proxy、设定库/模型映射相关修复；暂不清理。 |
| 前端代码 | 54：`M=41`，`D=1`，`??=12` | 包含 story block UI、AI proxy 前端适配、模型绑定/设定库修复；暂不清理。 |
| 新增故事块 / AI proxy / 模型映射相关代码 | 交叉分类 | 分布在后端、前端、合同测试和 live 脚本中；属于当前主线工作，不应删除。 |
| 合同测试 | 142：`D=51`，`M=4`，`??=87` | 新增合同测试应保留；历史 deleted 合同测试需按批次确认是否接受删除。 |
| live 测试脚本/当前运行产物 | 21：`??=21` | 当前 PHASE_TARGET / story block live 验收链路相关；在修复线程结束前保留。 |
| tmp 历史测试脚本 | 24：`D=23`，`??=1` | 多数是旧 realistic flow、旧 QA runner、旧服务启动脚本；明显清理候选。 |
| 浏览器缓存/profile | 460：`D=460` | `tmp/browser-qa/chrome-profile/`，明显清理候选；当前已表现为跟踪文件删除。 |
| 历史报告/截图 | 17：`D=17` | 旧 QA 报告、截图、历史写作样本分析产物；明显清理候选。 |
| 文档 | 6：`M=3`，`D=1`，`??=2` | 当前产品状态文档需保留；历史 QA 文档/旧计划需确认。 |
| 需进一步确认 | 23：`??=23` | `.playwright-cli/page-2026-06-17*.yml`，看起来是旧 Playwright 快照；建议确认无活动会话后清理并加入 ignore。 |

## 4. 分类细节

### 4.1 核心产品代码/工程配置

- `M .gitignore`
  - 已加入/准备加入多条 QA、browser、runtime artifact ignore 规则。
  - 本次不修改；建议在后续清理批次中单独审查并提交。
- `?? package.json`
  - 根目录 npm 包描述文件，当前内容接近 `npm init` 默认骨架。
  - 需确认是否被新的 Node 合同测试/脚本依赖；未确认前不要删除。

### 4.2 后端代码

暂时不能删：

- `M backend/database.py`
- `M backend/main.py`
- `M backend/routers/chapters.py`
- `M backend/routers/helpers.py`
- `M backend/routers/projects.py`
- `M backend/routers/providers.py`
- `M backend/routers/settings_library.py`
- `M backend/schema.sql`
- `?? backend/routers/ai_proxy.py`
- `?? backend/routers/story_blocks.py`

判断：这些路径覆盖 story block v1、AI proxy、provider/model binding、设定库字段/摘要写入等当前修复主题，应纳入功能审查，不能作为仓库清理对象处理。

### 4.3 前端代码

暂时不能删，需跟随 story block v1 / AI proxy / 设定库修复一起审查：

- AI API/DB：`frontend/src/api/ai/*`、`frontend/src/api/db/client.js`
- 章节/写作入口：`frontend/src/views/WriterView.vue`、`frontend/src/views/ProjectView.vue`、`frontend/src/components/writer/*`
- Story block 新增组件与 store：`frontend/src/components/story-block/*`、`frontend/src/components/writer/StoryBlockPanel.vue`、`frontend/src/stores/storyBlockStore.js`
- 设定库/模型绑定：`frontend/src/components/settings-library/SettingLibrary.vue`、`frontend/src/components/settings/ProviderSettings.vue`、`frontend/src/components/settings/TaskModelBinding.vue`、`frontend/src/stores/providerStore.js`、`frontend/src/stores/settingStore.js`
- prompts/quality/utils：`frontend/src/prompts/*`、`frontend/src/quality/*`、`frontend/src/utils/storyBlock*.js`、`frontend/src/utils/settingChangeRisk.js`

需进一步确认：

- `D frontend/src/qualityRules/aiTraceRules.js`
  - 看起来可能被 `frontend/src/quality/*` 新结构替代。
  - 接受删除前应确认引用已迁移完毕。

### 4.4 新增故事块 / AI proxy / 模型映射相关代码

明确保留候选：

- Story block 源码：`backend/routers/story_blocks.py`、`frontend/src/components/story-block/*`、`frontend/src/components/writer/StoryBlockPanel.vue`、`frontend/src/prompts/storyBlockPrompt.js`、`frontend/src/stores/storyBlockStore.js`、`frontend/src/utils/storyBlockGranularity.js`、`frontend/src/utils/storyBlockSnapshot.js`
- AI proxy 源码：`backend/routers/ai_proxy.py`、`backend/main.py`、`frontend/src/api/ai/*`
- 模型映射/设定库修复：`backend/routers/providers.py`、`backend/routers/settings_library.py`、`frontend/src/components/settings/*`、`frontend/src/stores/providerStore.js`、`frontend/src/stores/settingStore.js`、`frontend/src/utils/settingChangeRisk.js`
- 长文/小纲/故事块绑定链路：`backend/routers/chapters.py`、`frontend/src/prompts/chapter*.js`、`frontend/src/stores/writerStore.js`、`frontend/src/stores/volumeStore.js`

### 4.5 合同测试

保留候选：

- Story block 合同：`tmp/test_story_block_*`
- AI proxy 合同：`tmp/test_ai_proxy_*`、`tmp/test_frontend_ai_proxy_retry_contract.mjs`
- Beat plan / longform / live report 合同：`tmp/test_beat_plan_*`、`tmp/test_longform_*`、`tmp/test_live_*`
- 设定库/模型映射合同：`tmp/test_setting_*`、`tmp/test_model_binding_inheritance_contract.mjs`
- 后端策略合同：`tmp/test_*_backend_contract.py`，例如 owner/rule/summary/field tiers/write policy
- 当前修改的合同：`tmp/test_chapter_title_generation.mjs`、`tmp/test_finalization_retry_contract.mjs`、`tmp/test_manual_chapter_title_regen_contract.mjs`、`tmp/test_writer_finalization_lock_contract.mjs`

可清理或确认删除候选：

- 已标记删除的旧 realistic QA 合同：`tmp/test_realistic_qa_*`
- 已标记删除的旧质量链路合同：`tmp/test_quality_*`、`tmp/test_prose_rhythm_*`
- 已标记删除的旧 AI trace / audit prompt 合同：`tmp/test_ai_trace_*`、`tmp/test_audit_ai_trace_contract.mjs`
- 已标记删除的旧写作链路边界合同：`tmp/test_writer_store_prompt_boundaries.mjs`、`tmp/test_prompt_boundary_modules.mjs`

建议：不要一刀切删除 `tmp/test_*`。先把“新增当前合同”与“旧 deleted 合同”分批审查；当前 story block、AI proxy、设定库、模型映射相关合同必须保留。

### 4.6 live 测试脚本

暂时不能删：

- `tmp/run_longform_browser_240w_phase1.mjs`
  - 含 `PHASE_TARGET` 逻辑，默认 `20`，支持环境变量裁剪；当前要求不运行 10/20 章测试。
- `tmp/run_story_block_live_acceptance.mjs`
  - 当前 story block v1 live 验收脚本。
- `tmp/run_story_block_realistic_flow.mjs`
  - story block realistic flow v1，含 dry-run/live 模式；当前不建议删除。
- `tmp/diagnose_chapter3_beat_plan_failure.mjs`
- `tmp/diagnose_model_vs_chain_20260619.mjs`
- `tmp/realistic-flow-qa/latest-longform-browser-live-report.*`
- `tmp/realistic-flow-qa/latest-story-block-live-report.*`
- `tmp/realistic-flow-qa/*diagnostics.*`
- `tmp/realistic-flow-qa/phase-target-*.pid`
- `tmp/realistic-flow-qa/live-service-pids.txt`
- `tmp/live-server-logs/*`

判断：这些文件/产物与当前 live 修复线程直接相关。即使其中有运行产物，也应等当前线程结束并确认报告已归档后再清理。

### 4.7 tmp 历史测试脚本

明显清理候选：

- 旧 realistic flow runner：`tmp/run_realistic_flow_HEAD.mjs`、`tmp/run_realistic_longform_flow.mjs`、`tmp/run_realistic_longform_flow_fixed.mjs`、`tmp/run_realistic_longform_flow.bak.mjs`
- 旧 browser QA runner：`tmp/run_browser_qa.mjs`、`tmp/headless_browser_acceptance.py`
- 旧 v1 / standards / rolling planning runner：`tmp/v1_e2e_smoke.ps1`、`tmp/run_standards_qa.bat`、`tmp/run_rolling_planning_runtime_check.mjs`
- 旧前后端启动脚本/标记文件：`tmp/start_backend_dev.bat`、`tmp/start_frontend_dev.bat`、`tmp/start_frontend_detached.js`、`tmp/start_frontend_wrapper.js`、`tmp/run_frontend_server.js`、`tmp/serve_frontend_static.ps1`、`tmp/backend_bat_started.txt`、`tmp/frontend_bat_started.txt`、`tmp/background_test.txt`
- 其他旧检查脚本：`tmp/analyze_qa_project.mjs`、`tmp/check_store_import.mjs`、`tmp/quality_guardrails_test.mjs`

需进一步确认：

- `tmp/debug_chapter_generation_click.mjs`
  - 未跟踪，像临时调试脚本；建议确认不属于当前修复线程后再清理。

### 4.8 浏览器缓存/profile

明显清理候选：

- `tmp/browser-qa/chrome-profile/`
  - 当前有 460 条 `D`，均为跟踪文件删除。
  - 包含 `Cache`、`Code Cache`、`GPUCache`、`ShaderCache`、`Web Data`、`History`、`Cookies`、`Local State` 等浏览器运行缓存/profile 文件。

判断：这些内容不应进入仓库历史。后续应接受删除并确保 ignore 生效。

### 4.9 历史报告/截图

明显清理候选：

- `_manual_home.png`
- `docs/REALISTIC_FLOW_QA_2026-06-06.md`
- `docs/REALISTIC_FLOW_QA_2026-06-11.md`
- `tmp/browser-qa/home.png`
- `tmp/browser-qa/project-chapters.png`
- `tmp/browser-qa/project-overview.png`
- `tmp/browser-qa/writer-finalized.png`
- `tmp/browser-qa/latest-report.json`
- `tmp/browser-qa/latest-report.md`
- `tmp/realistic-flow-qa/latest-realistic-report.json`
- `tmp/realistic-flow-qa/latest-realistic-report.md`
- `tmp/realistic-flow-qa/standards-secondary-analysis.json`
- `tmp/realistic-flow-qa/standards-secondary-analysis.md`
- `tmp/realistic-flow-qa/project-detail.png`
- `tmp/realistic-flow-qa/writer-chapter-1.png`
- `tmp/writing-sample-analysis/writing-sample-analysis.json`
- `tmp/writing-sample-analysis/writing-sample-analysis.md`

判断：这些是旧 QA 文档、旧截图、旧报告或历史分析产物；如无追溯要求，可进入清理批次。

### 4.10 文档

暂时不能删：

- `M DEVELOPMENT_LOG.md`
- `M FUNCTION_TEST_CHECKLIST.md`
- `M PRODUCT_DEVELOPMENT_PLAN.md`
- `?? CURRENT_PROJECT_STATE.md`
- `?? STORY_QUALITY_CHARTER.md`
- `?? tmp/realistic-flow-qa/README.md`

需进一步确认：

- `D docs/superpowers/plans/2026-06-05-writing-quality-chain-refactor.md`
  - 看起来是历史计划文档删除；建议确认是否还需要作为开发记录保留。

### 4.11 浏览器/Playwright 快照

需进一步确认，倾向清理：

- `.playwright-cli/page-2026-06-17T11-40-45-254Z.yml`
- `.playwright-cli/page-2026-06-17T11-41-04-592Z.yml`
- `.playwright-cli/page-2026-06-17T11-42-27-377Z.yml`
- `.playwright-cli/page-2026-06-17T11-42-44-364Z.yml`
- `.playwright-cli/page-2026-06-17T11-42-48-928Z.yml`
- `.playwright-cli/page-2026-06-17T11-43-01-764Z.yml`
- `.playwright-cli/page-2026-06-17T11-43-57-417Z.yml`
- `.playwright-cli/page-2026-06-17T11-44-26-215Z.yml`
- `.playwright-cli/page-2026-06-17T11-45-51-251Z.yml`
- `.playwright-cli/page-2026-06-17T11-45-58-839Z.yml`
- `.playwright-cli/page-2026-06-17T11-47-28-006Z.yml`
- `.playwright-cli/page-2026-06-17T11-47-31-125Z.yml`
- `.playwright-cli/page-2026-06-17T11-47-52-915Z.yml`
- `.playwright-cli/page-2026-06-17T11-54-20-980Z.yml`
- `.playwright-cli/page-2026-06-17T11-54-25-737Z.yml`
- `.playwright-cli/page-2026-06-17T11-54-43-244Z.yml`
- `.playwright-cli/page-2026-06-17T11-54-57-223Z.yml`
- `.playwright-cli/page-2026-06-17T11-55-14-170Z.yml`
- `.playwright-cli/page-2026-06-17T11-55-18-768Z.yml`
- `.playwright-cli/page-2026-06-17T11-55-39-094Z.yml`
- `.playwright-cli/page-2026-06-17T12-00-22-262Z.yml`
- `.playwright-cli/page-2026-06-17T12-00-28-028Z.yml`
- `.playwright-cli/page-2026-06-17T12-00-48-232Z.yml`

判断：这些像 2026-06-17 的 Playwright CLI 页面快照；建议确认没有仍需复现的 UI 调试上下文后清理。

## 5. 可删除候选

优先级 A，明显运行产物/缓存：

- `tmp/browser-qa/chrome-profile/`
- `tmp/browser-qa/*.png`
- `tmp/browser-qa/latest-report.*`

优先级 B，旧报告/旧截图/历史 QA 文档：

- `_manual_home.png`
- `docs/REALISTIC_FLOW_QA_2026-06-06.md`
- `docs/REALISTIC_FLOW_QA_2026-06-11.md`
- `tmp/realistic-flow-qa/latest-realistic-report.*`
- `tmp/realistic-flow-qa/standards-secondary-analysis.*`
- `tmp/realistic-flow-qa/project-detail.png`
- `tmp/realistic-flow-qa/writer-chapter-1.png`
- `tmp/writing-sample-analysis/*`

优先级 C，旧 realistic flow / old QA runner：

- `tmp/run_realistic_flow_HEAD.mjs`
- `tmp/run_realistic_longform_flow.mjs`
- `tmp/run_realistic_longform_flow_fixed.mjs`
- `tmp/run_realistic_longform_flow.bak.mjs`
- `tmp/run_browser_qa.mjs`
- `tmp/headless_browser_acceptance.py`
- `tmp/v1_e2e_smoke.ps1`
- `tmp/run_continue_qa_60.bat`
- `tmp/run_standards_qa.bat`
- `tmp/run_rolling_planning_runtime_check.mjs`

优先级 D，旧启动脚本/临时标记：

- `tmp/start_backend_dev.bat`
- `tmp/start_frontend_dev.bat`
- `tmp/start_frontend_detached.js`
- `tmp/start_frontend_wrapper.js`
- `tmp/run_frontend_server.js`
- `tmp/serve_frontend_static.ps1`
- `tmp/backend_bat_started.txt`
- `tmp/frontend_bat_started.txt`
- `tmp/background_test.txt`
- `tmp/test_background_start.bat`

优先级 E，疑似已被 story block live 脚本替代的旧测试：

- `tmp/test_realistic_qa_*`
- `tmp/test_realistic_longform_acceptance_contract.mjs`
- `tmp/test_quality_chain_contract.mjs`
- `tmp/test_quality_first_generation_contract.mjs`
- `tmp/test_ai_trace_*`
- `tmp/test_audit_ai_trace_contract.mjs`
- `tmp/test_writer_store_prompt_boundaries.mjs`
- `tmp/test_prompt_boundary_modules.mjs`

## 6. 需保留候选

必须保留到当前修复线程结束：

- 当前 PHASE_TARGET live 脚本：`tmp/run_longform_browser_240w_phase1.mjs`
- 当前 story block live 脚本：`tmp/run_story_block_live_acceptance.mjs`
- story block realistic flow v1：`tmp/run_story_block_realistic_flow.mjs`
- 当前诊断脚本：`tmp/diagnose_chapter3_beat_plan_failure.mjs`、`tmp/diagnose_model_vs_chain_20260619.mjs`
- 当前 live 报告、诊断报告、pid/service 文件：`tmp/realistic-flow-qa/latest-longform-browser-live-report.*`、`tmp/realistic-flow-qa/latest-story-block-live-report.*`、`tmp/realistic-flow-qa/*diagnostics.*`、`tmp/realistic-flow-qa/*.pid`、`tmp/live-server-logs/*`
- 当前合同测试：`tmp/test_story_block_*`、`tmp/test_ai_proxy_*`、`tmp/test_beat_plan_*`、`tmp/test_setting_*`、`tmp/test_model_binding_inheritance_contract.mjs`、`tmp/test_longform_*`、`tmp/test_live_*`
- story block v1 源码：`backend/routers/story_blocks.py`、`frontend/src/components/story-block/*`、`frontend/src/components/writer/StoryBlockPanel.vue`、`frontend/src/prompts/storyBlockPrompt.js`、`frontend/src/stores/storyBlockStore.js`、`frontend/src/utils/storyBlock*.js`
- AI proxy 源码：`backend/routers/ai_proxy.py`、`frontend/src/api/ai/*`
- 模型映射/设定库修复源码：`backend/routers/providers.py`、`backend/routers/settings_library.py`、`frontend/src/components/settings*`、`frontend/src/stores/providerStore.js`、`frontend/src/stores/settingStore.js`、`frontend/src/utils/settingChangeRisk.js`
- 当前产品状态文档：`CURRENT_PROJECT_STATE.md`、`STORY_QUALITY_CHARTER.md`、`DEVELOPMENT_LOG.md`、`FUNCTION_TEST_CHECKLIST.md`、`PRODUCT_DEVELOPMENT_PLAN.md`

## 7. 需进一步确认候选

- `package.json`
  - 新增根配置文件；确认是否是当前 Node 合同测试依赖，或只是误生成骨架。
- `.gitignore`
  - 本地已有 ignore 规则修改；后续可单独审查，不在本次修改。
- `frontend/src/qualityRules/aiTraceRules.js`
  - 删除前确认是否已被 `frontend/src/quality/*` 完整替代。
- `docs/superpowers/plans/2026-06-05-writing-quality-chain-refactor.md`
  - 历史计划文档是否保留，由项目文档策略决定。
- `tmp/debug_chapter_generation_click.mjs`
  - 未跟踪临时调试脚本，确认当前线程不需要后再清理。
- `.playwright-cli/page-2026-06-17*.yml`
  - 倾向清理，但建议确认没有需要保留的 UI 调试快照。
- `tmp/realistic-flow-qa/latest-story-block-report.*`
  - 当前 `.gitignore` 修改中已有规则；若是旧非 live 报告，可清理；若用于当前对照，先保留。

## 8. 建议新增到 `.gitignore` 的路径

当前工作树中的 `.gitignore` 已有本地修改，包含 `tmp/browser-qa/`、`tmp/browser-qa*/`、`tmp/writing-sample-analysis/`、`tmp/realistic-flow-qa/latest-realistic-report.*` 等规则。本次不修改 `.gitignore`，仅建议后续审查时补充/确认：

- `.playwright-cli/`
- `tmp/live-server-logs/`
- `tmp/realistic-flow-qa/*.pid`
- `tmp/realistic-flow-qa/live-service-pids.txt`
- `tmp/realistic-flow-qa/latest-longform-browser-live-report.*`
- `tmp/realistic-flow-qa/latest-story-block-live-report.*`
- `tmp/realistic-flow-qa/*diagnostics.*`
- `tmp/realistic-flow-qa/*-live-report.*`
- `tmp/browser-qa/`
- `tmp/browser-qa*/`
- `tmp/browser_acceptance/`
- `tmp/archive/`
- `tmp/db-backups/`
- `tmp/writing-sample-analysis/`

注意：`*.log` 已存在于 `.gitignore`，理论上覆盖当前大量 `tmp/*.log` 与 `tmp/realistic-flow-qa/*.log`。

## 9. 后续实际清理步骤

建议等待当前 story block 修复线程结束后，再按批次执行实际清理：

1. 冻结当前状态：再次运行只读状态检查，确认没有新的故事块修复线程正在写入 `tmp/realistic-flow-qa/` 或 `tmp/live-server-logs/`。
2. 先处理 ignore 策略：审查 `.gitignore` 现有本地修改，并补充本报告第 8 节中确认需要的规则。
3. 第一批清理运行产物：处理 `tmp/browser-qa/chrome-profile/`、`tmp/browser-qa/` 旧截图/报告、`.playwright-cli/` 快照。
4. 第二批清理旧报告/文档：处理旧 `REALISTIC_FLOW_QA` 文档、旧 realistic report、writing-sample-analysis 产物。
5. 第三批清理旧 runner：处理 `tmp/run_realistic_*`、`tmp/run_browser_qa.mjs`、`tmp/headless_browser_acceptance.py`、旧启动脚本。
6. 第四批审查旧合同测试：只接受确认已被 story block live/当前合同覆盖的旧 `tmp/test_realistic_qa_*` 等删除；保留 story block、AI proxy、beat plan、setting/model binding 合同。
7. 单独审查源码与文档：story block v1、AI proxy、模型映射、设定库修复源码，以及当前产品状态文档，不与清理批次混合。
8. 清理后验证：只运行轻量合同/静态检查；除非明确要求，不运行 10/20 章 live 测试。
9. 分批提交：运行产物清理、ignore 更新、旧测试清理、源码功能变更应拆成不同提交，避免把业务修复与仓库清理混在一起。

## 10. 审计结论

最安全的清理边界是：先接受浏览器 profile/cache、旧截图/旧报告、旧 realistic flow runner 和旧 QA 文档的清理；保留当前 PHASE_TARGET live 脚本、当前合同测试、story block v1 源码、AI proxy 源码、模型映射/设定库修复源码和当前产品状态文档。

当前工作树中“清理项”和“业务修复项”高度混杂。建议实际清理时严格分批，不要用全局清理命令，也不要在当前故事块修复线程仍运行时处理 live 报告、pid、service log 或 current PHASE_TARGET 脚本。
