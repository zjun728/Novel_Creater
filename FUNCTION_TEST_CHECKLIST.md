# 功能测试清单

> 当前有效验收清单。旧历史清单和运行流水不再作为默认验收入口。

## 1. 文档与事实来源

- [x] `STORY_QUALITY_CHARTER.md` 作为最高故事质量来源。
- [x] `CURRENT_PROJECT_STATE.md` 记录当前项目、章节、故事块和下一步。
- [x] `PRODUCT_DEVELOPMENT_PLAN.md` 只保留当前有效产品规划。
- [x] `DEVELOPMENT_LOG.md` 只保留决策级摘要。
- [ ] 改变写作规则、硬门禁、故事块边界、定稿行为或 prompt 前，必须先核对当前事实文档。

## 2. 长篇 live 流程门禁

每次 live 生成前必须检查：

- [ ] 使用当前项目 `2da6152a-c083-41ee-8bcb-f11b0fae387d`，不新建项目。
- [ ] 目标章节不存在，目标章节 beat plan 不存在。
- [ ] 不启动禁止章节，例如 50、下一章之后的章节或范围生成。
- [ ] pending settings/facts 为 `0/0`。
- [ ] relation risk synthetic/self/wrong-layer/missingEndpoint 为 `0/0/0/0`。
- [ ] 当前唯一 active story block 和 planned stage 与目标章节一致。

每次 live 生成后必须检查：

- [ ] 目标章节 final 或失败即停。
- [ ] 下一章未启动。
- [ ] 禁止章节未触碰。
- [ ] 83 章之后已 final 正文 hash 未被意外改动。
- [ ] finalization marker 已清理或保留为明确可恢复失败。
- [ ] runner/service 进程和端口监听已清理。

## 3. 故事块验收

- [ ] 故事块位于分卷规划和章节小纲之间。
- [ ] 章节小纲绑定当前 active story block 的当前 planned stage。
- [ ] stage 完成后只标记当前 stage，不提前关闭未来 stage。
- [ ] 如果正文触及未来 stage，下一章前先做 metadata-only replan 预检。
- [ ] `nextStageSuggestion` 必须与下一 planned stage 一致。
- [ ] 已定稿章节依赖的 story block 目标、入场状态、完成阶段和故事任务不得回改。
- [ ] 当前块完成时应关闭旧块并开启/确认新 active block。

## 4. 正文与小纲质量

- [ ] 小纲先定义具体事件，再处理主题、情绪或象征。
- [ ] 小纲包含压力、行动、选择、代价和交接点。
- [ ] 正文完成本章事件，不把多章内容塞进一章。
- [ ] 正文默认清楚、直接、可读。
- [ ] 读者能用一句普通话说清楚本章发生了什么。
- [ ] 人物有选择、反应、损失、隐瞒、误会、交易或关系变化。
- [ ] AI 风格指标只作观察，除非已经造成结构性失败。

## 5. 章名验收

- [ ] 章名优先来自关键地点、物件、人物、组织、武器功法、阶段答案或转折事件。
- [ ] 可接受朴素目录名，不追求高大上。
- [ ] 拒绝默认章名、英文残留、对白碎片、方向/位置残片。
- [ ] 如果 metadata repair 触发，必须确认正文 hash 未变。
- [ ] live 报告记录 initialTitle、finalTitle、titleQuality 和 titleSourceStrategyLivePassed。

## 6. 正式写作标准、样本库和经验卡

- [ ] 正文只读取已激活正式写作标准。
- [ ] 每章正式标准低量调用不超过 1/1/1。
- [ ] 经验卡和候选标准不能直连正文。
- [ ] 样本库不得泄漏原文、source 字段、人物名、地名、专有设定或标志性表达。
- [ ] 报告包含 `sampleLeakageDetected=false`、`hasExperienceCardDirectField=false`、`sourceFieldsStripped=true`。

## 7. 定稿状态机

- [ ] preflight 失败不得创建 pending marker。
- [ ] finalize 成功后，memory/settings/story block settlement 失败必须保留 marker。
- [ ] storyBlockSettlementFailure 不能走通用 memory/settings retry 清 marker。
- [ ] reconcile 清 marker 必须满足章节 final、pending settings/facts 为 0、beat plan 有 storyBlockId、故事块 review 已保存。
- [ ] post-finalize 可重试失败和不可重试失败必须分类清楚。

## 8. 模型配置

- [ ] 新建项目继承最近保存的任务模型映射；没有历史映射时保持未配置。
- [ ] 当前项目没有任务模型映射时，不得静默使用 Provider 列表第一个模型。
- [ ] 显式兜底模型必须在 UI 或报告中写明实际 provider/model。
- [ ] live 报告记录关键任务实际使用的 provider/model。

## 9. 推荐验证命令

常用静态验证：

- `node tmp/test_chapter_title_quality_contract.mjs`
- `node tmp/test_writing_standard_prompt_boundary_contract.mjs`
- `node tmp/test_sample_micro_demo_injection_contract.mjs`
- `node tmp/test_live_runner_freeze_guards_contract.mjs`
- `node tmp/test_writer_flow_finalization_callsite_contract.mjs`
- `npm --prefix frontend run build`

live 生成后还必须做只读 DB 检查和 runner/service process scan。
