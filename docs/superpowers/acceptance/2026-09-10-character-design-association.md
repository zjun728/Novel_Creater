# 人物计划与实体关联验收（2026-09-10）

本轮完成此前剩余的人物计划与 Canon 人物明确关联、可编辑节点、保存确认及版本/包往返支持。按用户“当前任务完成后先安全停止”要求收口，未进入三章正文创作验收。

## 实现范围

- 在既有 Planning 聚合中增加可选 characterDesign：人物称谓、明确选择的本项目人物、计划节点及阶段/目标/信念/关系/能力/预计章节。支持节点增删排序、解除关联、未出场人物暂不绑定。
- 保存允许未完成工作稿；确认要求非空节点和有效变化维度。人物引用按项目、类型和 Canon 快照校验，不以同名推断身份。
- 确认前显示人物节点明细，确认后保留不可变历史。人物弧光页面按明确人物引用展示计划，并与正文已发生变化分开读取。计划节点不自动标记为已实现。
- 备份导出与导入重映射人物引用，节点本地 ID 保持，内容哈希重新计算；旧规划缺省字段保持省略，无新增表或迁移，不改写旧哈希。

## 验证证据

- 最终后端定向测试 47 passed，包括人物计划领域、包引用、连续性读取、真实 MySQL 规划生命周期 2 项、真实 ZIP 往返 1 项。日志：output/character-design-final-backend.log；created=3 / cleaned=3 / remaining=0。
- 最终前端 API、编辑器、控制器、未来设计 37 passed；规划真实 SFC 14 passed。日志：output/character-design-final-frontend.log、output/character-design-final-sfc.log。最新生产构建通过：output/character-design-final-build.log。
- 前序兼容回归：规划领域/服务 91 项、包图与安全 229 项、连续性后端 20 项通过；不将重叠用例累加为独立总数。
- 浏览器使用一次性真实 MySQL 和产品 Planning/Continuity 路由与服务，无请求拦截。实际建立修订工作稿，选择沈砚，输入“主动信任同伴”及五维内容，保存、预览、确认至 R3；切入人物弧光并刷新后关联计划保留，实际弧光仍为既有“独自追查”。
- 人工查看 PC 截图：output/playwright/character-design-confirm-1440.png、character-design-arcs-1440.png、character-design-arcs-1920.png。确认弹窗及人物计划内容可读。
- 浏览器夹具清理回执 output/character-design-browser-receipt.json：originalAuthorityUnchanged=true，ownedDatabasesRemoved=1，并保留确认后的节点内容。该快照核对既有 Canon、弧光及原规划，浏览器测试不等同于真实模型创作验收。

## 安全停止与后续边界

自有浏览器已关闭，临时后端优雅退出并删除自有库，Vite 已停止；8000、8001、5173 无监听。保留 MySQL 服务和用户已有修改，未提交或推送。临时启动脚本与停止文件已移除，测试日志、截图和回执保留。

产品 QA 第一章 R2 本轮未读取或修改；上轮核验状态为 awaiting_author / confirmation=null，不能把本轮夹具 R3 当成产品审查状态。未调用正文生成、作者审查确认或定稿。

此前列出的 E1 人物计划缺项已完成模块级验证。恢复后下一步是独立的真实三章作者全流程：从现有待审查状态继续，核验确认/定稿、跨章连续性、历史阅读与导出。整体产品全流程尚未验收完成。
