# 2026-09-10 连续性作者视图补齐

本轮接续用户指出的设定库、弧光、状态记忆和线索缺口。只增加读取与展示，没有生成正文、确认审查或改写产品 Canon。第一章 QA 作者修正 R2 保持未确认。

## 已实现

- 设定库按人物、势力、地点、物品分类查询；世界规则保留为全书规则/圣经内容，不伪造第五种 Canon 实体。
- 页面直接展开当前已确认圣经、情节未来方向/预期回收、故事块/阶段/场景任务；排除草稿和上游依据过期的确认头。独立刷新和记录重新加载均可刷新未来设计。
- 弧光按已有明确维度展示目标、阶段、信念、关系、能力等；线索按已有明确类型区分主线、支线、人物线、悬念、伏笔，兼容对象和标量进展。
- 状态、弧光和线索区分首次形成章、最近更新章。来源字段采用精确二进制比较。
- 同一实体/字段的变化历史有分页、版本校验和原文回看；全局记录必须显式全局范围；人物说法保留标签，不覆盖客观投影。

## 验证

- 后端相关单元/API：52 passed，`output/continuity-sep10-backend.log`。
- 前端相关行为：20 passed，`output/continuity-sep10-frontend.log`。
- 真实 MySQL：2 passed，创建2库、清理2库、残留0，`output/continuity-sep10-mysql.log`。通过 CanonService 生成非空投影，检查 claim、实体隔离、形成/更新章、原文 hash、字段范围和分页。
- 构建通过，`output/continuity-sep10-build.log`；`git diff --check` 通过。
- 产品库只读验证：QA 项目读取圣经 R1/规划 R1；《典镇山河》按人物分类、阿芸状态第1章形成/第2章更新、两次历史与原文回看。两个 PC 尺寸无横向溢出。
- 非空浏览器验证：一次性 MySQL 中的真实 Canon 投影，经产品 continuity router 的独立只读 HTTP 服务返回；浏览器只将该 fixture 项目的请求转发至8001，未伪造响应数据。弧光目标“独自追查”，历史“已经放弃”显示人物说法；悬念显示“已回收”；原文校验通过。此证据属于模块验收，不代表真实 LLM 三章创作验收。
- 截图已实际查看：`output/playwright/continuity-future-sep10-1440.png`、`continuity-history-sep10-1920.png`、`continuity-nonempty-arcs-sep10-1440.png`、`continuity-nonempty-clues-sep10-1920.png`。最终页面 console errors=0/warnings=0；早期 fixture 转发地址错误导致404，修正转发后重新验证。

## 未完成边界

1. Bible 项目只有 id/text，Planning 中人物字段是名称文本，不存在明确 Canon 实体引用。因此未来设计目前为全书展示，不能宣称某个人物的计划节点已经与实际节点关联。完整关联需要规划契约及其保存/导入导出链共同支持，不能按同名偷偷合并。
2. 现有 Canon arc/plot 值允许任意 JSON；本轮展示已有明确维度，不会替缺失的维度或计划回收章节编造值。独立的可编辑人物弧光计划模型尚不存在。
3. 完整写作台三章真实审查、确认、定稿、跨章状态更新及阅读导出仍未完成；不因本轮通过进入自动正文生成。
4. 测试尝试在同实体同时生成 `arc.goal`/`Arc.goal` 时发现既有投影唯一键的大小写不敏感约束会拒绝写入并回滚；不是只读查询造成。保留失败日志 `output/continuity-sep10-case-collision.log`（2库均清理），未改 schema。最终测试恢复合法 Canon fixture，继续验证字段大小写精确过滤；没有将不合法 fixture 的失败记成通过。

## 后续顺序

先补齐 Planning 对 Canon 实体的明确引用及人物计划节点的保存、确认、版本/导入导出边界，再做计划与实际节点关联验收；最后接续保留的第一章 R2 和完整三章流程。当前 E1 为只读展示与历史验收通过，整体 E1 尚未全部完成。

## 安全停止

三个子任务均结束，自有浏览器关闭，8000/8001/5173无监听。临时HTTP fixture进程被终止后没有执行 lifespan 清理，已通过本次专用事件ID和第三章全文双重核实唯一临时库归属，精确删除并复查不存在；其他既有测试库未动。收据 `output/continuity-sep10-fixture-cleanup.json`。本轮临时启动脚本已移除，测试与证据保留。最后产品GET确认第一章仍是原attempt、R2、awaiting_author、confirmation=null。没有提交或推送。
