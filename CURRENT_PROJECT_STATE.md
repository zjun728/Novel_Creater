# 当前项目状态

> 新线程或上下文压缩后，先读本文件。历史过程报告只在追溯问题时查看。

## 文档优先级

1. `STORY_QUALITY_CHARTER.md`：最高故事质量原则。
2. `CURRENT_PROJECT_STATE.md`：当前有效状态和下一步。
3. `PRODUCT_DEVELOPMENT_PLAN.md`：当前产品规划。
4. `FUNCTION_TEST_CHECKLIST.md`：验收清单。
5. `WRITING_STYLE_STANDARDS.md`：写作风格标准库。

不要从旧测试报告、旧临时脚本或旧提交里恢复写作规则，除非主产品线程重新确认。

## 当前长篇项目

- 项目名：`LongformBrowser240w_20260625_153055`
- projectId：`2da6152a-c083-41ee-8bcb-f11b0fae387d`
- 当前进度：第 90 章 final，《玉牌》
- 第 90 finalVersionId：`db524497-287f-4cc4-87a3-fdc16baec455`
- 第 91 章：不存在
- 第 91 beat plan：不存在
- 当前唯一 active story block：《商盟玉牌与两线抉择》
- 当前下一阶段：`stage-2`，在缺指男人交易时限下确定救小九、探商盟或并行反制方案。

最新只读验收状态：

- pending settings/facts：`0/0`
- active relation count：`43`
- relation risk synthetic/self/wrong-layer/missingEndpoint：`0/0/0/0`
- 83-90 已 final 正文不得重写；能 metadata-only 修复的只修元数据。

## 当前架构状态

已完成一轮架构规范整理与功能解耦治理，恢复长篇测试的门槛已通过：

- 章名模块已迁移到 `frontend/src/domain/chapter-title/`，以正向素材候选为主，坏标题规则只作兜底。
- `WriterView.vue` 的若干流程编排已抽到 `frontend/src/application/writer-flow/`。
- 正文草稿 AI 内容辅助已抽到 `frontend/src/domain/chapter-draft/`。
- live runner 的冻结护栏、健康审计、报告写入、服务管理已沉淀到 `tmp/live-qa/`。
- 定稿状态机增加 marker/action、retry、postprocess、story block settlement 等合同。
- 第 89、90 单章 canary 已验证真实链路未越界：未启动后续章，未污染关系，prompt 边界保持 1/1/1。

架构治理的当前结论：不继续大重构，下一步用小范围真实生成验证剩余阶段。

## 当前产品边界

- 故事块是卷与章节之间的剧情任务单元，不是单章容器。
- 故事块只能向前滚动；已定稿章节依赖的目标、入场状态、已完成阶段和故事任务不能回改。
- 当前章小纲必须绑定当前 active story block 的当前 planned stage。
- 正文生成只能读取已激活正式写作标准；经验卡和候选标准不能直连正文。
- 正式写作标准低量调用：每章最多 1 条原则、1 个原创微示范、1 条反 AI 提醒。
- 样本库只提供抽象写法参考，不得泄漏原文、人物名、地名、专有设定或 source 字段。
- 失败即停，不通过新建项目、跳章或改报告标签掩盖问题。

## 当前质量方向

平台目标是低理解成本地讲一个吸引人的长篇故事。

当前质量优先级：

1. 读者愿意继续看。
2. 故事清楚。
3. 长篇连续性稳定。
4. 人物有选择和后果。
5. 阅读负担低。
6. 文字自然。
7. 降低 AI 痕迹。

AI 风格指标主要用于审稿和 QA 观察，不应压过故事清楚度，也不应把正文 prompt 变成检查清单。

## 下一步

下一步建议执行：**第 91 章单章 canary 验证**。

硬边界：

- 只生成并尝试定稿第 91 章。
- 成功或失败都立即停止。
- 不启动第 92 章，不跑第 50 章，不跑范围生成。
- 不新建项目，不改模型配置，不改 prompt，不改正式写作标准内容。
- 不重写 83-90 正文。

第 91 的核心验收点：

- 跑前第 91 章和第 91 beat plan 仍不存在。
- 第 91 绑定《商盟玉牌与两线抉择》stage-2。
- 不重复 stage-1 的伤势处理/玉牌判读。
- 不跳到 stage-3/4 直接执行商盟潜入或交易反制。
- 定稿后 pending settings/facts 仍为 0/0，关系风险仍为 0/0/0/0。

## 文档纪律

`CURRENT_PROJECT_STATE.md`、`PRODUCT_DEVELOPMENT_PLAN.md` 和 `DEVELOPMENT_LOG.md` 只记录当前有效事实、产品边界和决策级总结。详细 live 报告、runner 产物、临时诊断、历史复盘默认不入库；需要追溯时看 git 历史或本地短期产物。
