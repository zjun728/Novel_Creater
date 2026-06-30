# 开发日志

> 当前轻量开发日志。只记录仍有效的产品级决策和验证结论；完整运行产物不入本文档。

## 2026-06-17 文档事实来源清理

建立新的当前事实来源：

- `STORY_QUALITY_CHARTER.md`
- `CURRENT_PROJECT_STATE.md`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `FUNCTION_TEST_CHECKLIST.md`

旧长日志、旧真实流程报告、截图和临时补丁记录不再作为默认事实来源。后续开发线程改变写作规则、硬门禁、故事块边界、定稿行为或 prompt 前，必须先核对当前事实文档。

## 2026-06-17 故事块滚动规划准则

新增故事块作为分卷规划和章节小纲之间的正式规划层。

有效边界：

- 故事块控制一段连续剧情的目标、功能、压力、人物变化和未解决项。
- 故事块不预设固定章节数。
- 每章定稿后执行块级回看。
- 故事块只能向前滚动，已定稿章节依赖的目标、入场状态、已完成阶段和故事任务不能回改。
- `adjust_remaining_stages` 只调整尚未执行、未被小纲引用、未被定稿章节依赖的剩余阶段。

## 2026-06-26 故事性与人物血肉 v1

第 1-20 章只读复盘确认：主链路能推进，但故事质量短板从链路正确性转为人物关系、选择代价和场景停留。

有效改造方向：

- 故事块增加人物关系任务。
- 小纲增加情绪锚点。
- 正文提示保持轻量，只做短量正向引导。
- 设定呈现优先写行动后果。
- 重要配角建立声音卡。

该方向不得演变为正文 prompt 的完整 QA 清单。

## 2026-06-28 至 2026-06-29 样本库、经验卡与正式标准边界

样本库和经验卡已进入产品化方向：

- 样本库用于抽象创作经验，不复制原文。
- 经验卡和候选标准不能直连正文。
- 正文只能读取已激活正式写作标准。
- 正式标准低量调用：1 条原则、1 个原创微示范、1 条反 AI 提醒。
- 报告与合同持续检查 `sampleLeakageDetected=false`、`hasExperienceCardDirectField=false`、`sourceFieldsStripped=true`。

## 2026-06-29 至 2026-06-30 章名重构与架构治理

章名从黑名单补丁转为正向素材候选优先：

- 关键地点、物件、人物、组织、武器功法、阶段答案等朴素目录名优先。
- 对白碎片、位置残片、默认章名只作为拒绝项。
- 章名逻辑沉淀到 `frontend/src/domain/chapter-title/`。

架构治理完成一轮可恢复测试门槛：

- `frontend/src/application/writer-flow/` 承接 WriterView 流程 adapter。
- `frontend/src/domain/chapter-draft/` 承接正文草稿 AI 内容辅助。
- `tmp/live-qa/` 承接 runner freeze guards、project health audit、report writer、runtime config 和 service manager。
- 定稿状态机补齐 marker/action、retry、postprocess、story block settlement 合同。

结论：不继续大重构，回到单章 canary 验证真实链路。

## 2026-06-30 第 89/90 章 canary 与故事块切换

第 89 章单章 canary 通过：

- 第 89 final：《地下仓库》
- finalVersionId：`3ca8b60f-b0d7-4957-ba30-6580cac31e20`
- 未启动第 90/50。
- pending settings/facts：`0/0`
- relation risk：`0/0/0/0`

第 89 后发现旧块《东城染坊取物》已完成但仍 active，已做 metadata-only 修正：

- 旧块 completed。
- 新 active story block：《商盟玉牌与两线抉择》。

第 90 章单章 canary 通过：

- 第 90 final：《玉牌》
- finalVersionId：`db524497-287f-4cc4-87a3-fdc16baec455`
- 正确绑定新块 stage-1。
- 第 91 不存在。
- pending settings/facts：`0/0`
- relation risk：`0/0/0/0`

第 90 触及未来阶段，已做第 91 前 metadata-only replan：

- stage-1 保持 completed，completedChapterNum=90。
- stage-2/3/4 保持 planned，并根据第 90 的未来阶段证据重排。
- nextStageSuggestion 指向 stage-2。

## 下一步

执行第 91 章单章 canary。成功或失败都停止，不直接扩大到 92-94。

第 91 重点验收：

- 正确绑定《商盟玉牌与两线抉择》stage-2。
- 不重复 stage-1 的伤势处理/玉牌判读。
- 不跳到 stage-3/4。
- 不启动第 92/50。
- prompt、正式标准、样本库、经验卡、关系风险和 pending 后处理边界保持稳定。

## 日志纪律

不要把完整测试日志粘贴进本文件。详细运行产物默认不入库；必要结论应沉淀为当前事实、产品边界或验收清单。
