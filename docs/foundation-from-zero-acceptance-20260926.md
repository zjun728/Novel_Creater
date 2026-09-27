# 2026-09-26 从零创作基础真实流程验收

本轮前端交接及明确补项已获独立审计结项。本次继续补齐此前未覆盖的真实链路：空白讨论 → 候选种子 → 创建项目 → 确认种子 → 契约 → 圣经 → 首次规划 → 权威第一章工作台。

## 环境与边界

所有业务写入位于一次性隔离库 `novel_creator_test_b6fb67d58bc54ed8aa30373821d35824`，使用实际应用、MySQL 和既有启用模型 `deepseek-v4-flash`。正式库只读取得模型连接配置，未修改正式小说、模型配置或语料。初始项目、种子、契约、圣经修订、规划修订计数全部为零，见 `output/foundation-live-20260926/ready.json`。

准备项仅含已发布的风格／经验资产包、模型连接和市场来源目录；没有预填种子、契约、圣经或规划，没有注入模型结果。作者输入创意、容量、偏好和禁止方向均通过界面填写。验收项目为 `QA-从零创作-弯钉汛`，ID `ac7cdf98-14f7-5179-b3fa-586033a8d30d`。

## 实际经过与证据

证据目录：`output/foundation-live-20260926/`。截图：`output/playwright/foundation-*-20260926.png`。

| 环节 | 实际结果 | 主要原始证据 |
| --- | --- | --- |
| 直接 AI 讨论 | 从空白讨论开始，无推荐和市场资料；实际模型返回方向及完整候选种子 | `blank-discussion-start.txt`、`after-seed.json` |
| 默认模型恢复 | 初始未配置应用默认模型时阻断发送；页面配置保存并返回后原输入保留，重发成功 | `discussion-current.txt`、`default-model-recovery.txt` |
| 市场推荐支路 | 安装已发布来源目录后真实抓取、分析，产生三条建议，展示来源；建议入口带上下文，随后直接讨论入口仍为空白 | `market-source-installed.txt`、`market-discussion-context.txt`、`direct-after-recommendation.txt` |
| 候选转项目与确认种子 | 实际保存方向、候选种子，创建唯一项目，页面确认并刷新，再继续契约 | `seed-before-confirm.txt`、`seed-confirmed-engine-started.txt`、`after-seed.json` |
| 契约 | 真实生成三套发动机，采用“弯钉汛·签收链”；真实风格推荐及临时试写，采用沉浸群像型与一张经验卡；作者设置 9 万字／3 卷／30 章、偏好和禁止方向；完整预览、签印 R1、刷新读回 | `after-style.json`、`style-preview.txt`、`style-trial-started.txt`、`capacity-prohibitions-saved.txt`、`contract-confirm-dialog.txt`、`bible-generation-started.txt` |
| 圣经 | 真实模型基于已确认契约生成完整建议；页面核对原空白与建议内容，采纳、保存、确认 R1，刷新只读 | `bible-proposal.txt`、`bible-confirm-preview.txt`、`bible-confirmed-planning-open.txt` |
| 首次规划 | 首次失败，补充简洁范围与格式要求后成功；3 卷、5 条情节线、1 故事块、3 阶段、9 任务；对比后确认 R1 | `planning-failure.json`、`planning-retry-started.txt`、`planning-confirm-preview.txt` |
| 工作台承接 | 点击“确认采用并继续”实际进入 `/workbench/chapters/1`；权威状态为第 1 章，下一步准备小纲，未确认小纲时禁止生成正文 | `first-chapter-workbench.txt`、`final-state.json`、`verification.json` |

契约至圣经、圣经至规划通过已有项目导航进入；没有宣称新增了自动跳转按钮。只读 SQL/API 与最终断言核对：唯一项目、种子哈希贯穿契约、规划输入承接种子、三项正式修订均 R1、一次规划失败及一次成功、权威下一步一致。

## 发现并修复的界面遗漏

工作台的收窄侧栏未隐藏项目模块与分组标题，文字挤成竖排。`frontend/src/components/layout/Sidebar.vue` 补齐已有收窄规则：模块标签复用视觉隐藏类，分组显示单字标记，收窄入口提供完整悬停名称并保留无障碍名称。未修改后端或重设计页面。

实际浏览器验证收窄菜单正常、分组可展开、无横向溢出，并核对宽屏展开状态。修复前后截图分别为 `foundation-first-chapter-20260926.png`、`foundation-first-chapter-fixed-20260926.png`；回执 `sidebar-fixed.txt`、`sidebar-expanded.txt`。

相关导航测试 **26/26**，前端构建通过：`frontend-navigation-tests.txt`、`frontend-build.txt`。本批没有后端源码变更，未重复累计此前后端测试数量。

## 失败、重试与验收限制

- 首次规划持久化为 `PlanningProviderFailed`，失败未发布内容，空白工作稿与确认版本保留。第二次由页面补充要求后成功。公共错误不足以区分网络、模型输出和格式校验，不能声称根因已查明或首次必然成功。
- 初始空市场来源目录与未配置应用默认模型均出现明确提示；补齐运行前置后继续，没有伪造市场结果。
- 部分操作脚本错误等待了不存在的路由片段、样式类、保存后组件卸载或签印提示；实际服务端成功后先核对状态再继续，没有重复创建项目。一次保存后过早刷新触发离开保护，阻塞响应处理并出现超时；数据库已保存，经刷新核对恢复。原始失败文件保留，不把脚本超时算作产品流程通过证据。
- 本次范围止于第一章工作台，小纲、正文、审稿、定稿与跨卷没有在这个从零项目上继续执行。此前另一批的真实写作闭环仍是独立证据，不能拼接成同一个项目“从零到完结”的验收。
- 一次成功链路不证明长期稳定性、所有模型成功率、文学质量或全页面逐像素一致。服务端主动同步修复、稿件排序、已确认基础回看布局等明确后置项保持后置。

## 收尾

保留既有未提交修改，未提交或推送。验收结束后关闭本次浏览器和自有 18000／15173 运行时，由隔离库上下文清理本次数据库；以 `stopped.json`、`database-cleaned.json` 和 `cleanup-verification.json` 为最终回执。原始结果、截图和日志保留。
