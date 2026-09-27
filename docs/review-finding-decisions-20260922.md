# 审稿严重程度与逐条忽略实施记录

2026-09-22。承接上一批能力映射，用户明确要求“开始吧”。本批完成新报告分级、作者忽略 / 恢复持久化、有效意见透传、服务端确认与定稿保护，以及新增数据表的备份后增量升级。保留既有工作区修改，未提交或推送。

## 行为与契约

- 新质量报告每条必须提供 `severity: required | suggested | optional`。`required` 仅用于有原文证据、违反已确认事实或明确小纲约束的问题；`suggested` 为实质改善建议；`optional` 为不影响事实、连续性和章节交付的主观表达偏好。不按 dimension 猜测严重程度。新模型响应缺少分级时视为质量审查未完成，不能冒充分类成功。
- 历史报告仍可读取，缺少 severity 时保持原 JSON / 哈希，显示“旧报告未分级”，不能直接忽略；需要重新审查才能获得新分级。
- 仅 optional 条目提供“忽略此建议 / 恢复采用”。独立表 `review_finding_decisions` 绑定项目、审查、报告哈希，记录作者处理修订和忽略 ID 集合。原质量报告保持不可变。
- 新端点 `POST /projects/{project_id}/chapter-sessions/{session_id}/finalization/finding-decisions` 校验审查 ID、报告哈希、变更集修订 / 哈希和处理状态修订。复用项目锁、活动会话、候选正文、小纲 / 规划 / Canon 与未确认状态检查。忙碌、过期、已确认、已定稿或归档状态不能修改。
- 成功保存才更新界面，失败保留权威旧状态并提供重新读取；刷新后读取数据库状态。新的审查拥有新的处理状态，不继承旧忽略集合。
- `reviewReference.decisionsRevision` 参与操作幂等指纹及生成依据校验；旧六字段引用只在处理状态尚为 R0 时兼容。处理修订变化后旧引用被拒绝；启动、写回、停止采用部分稿时均复核。
- 整章调整由服务端过滤已忽略条目，完整传递剩余意见，不拼接到限长作者要求、不截断意见、不改报告原哈希。全部意见已忽略且无确定性阻断时禁止空意见生成。调整确认文案明确排除已忽略建议。
- 必须调整项禁止作者确认和定稿，服务端两个入口均检查，不能只绕过前端按钮；必须修改并重新审稿。确定性阻断不能忽略。原事实 / 进度变更确认路径继续保留。

## 验证

| 层次 | 证据与边界 |
| --- | --- |
| 后端回归 | `output/review-decisions-backend-final.txt` 首轮 228/229，唯一失败是新迁移测试仍引用旧辅助函数名；修正后所属迁移组 26/26（`review-decisions-upgrade-unit-final.txt`）。随后补直接定稿阻断测试，相关处理状态 / 调整 / 定稿 / 迁移组 45/45（`review-decisions-backend-last.txt`）。其他已通过未变化用例未重复跑 |
| 前端 | `output/review-decisions-frontend-final.txt` 55/55，包含分类、忽略 / 恢复按钮、必须调整禁用、保存失败保留旧状态、审稿引用和旧稿保护；`review-decisions-build.txt` 构建通过 |
| 真 MySQL 升级 | `output/review-decisions-migration-test-final.txt` 1/1。从固定 v1.15 manifest 增量升级，在自有测试库确认全部旧表行数及样本作者项目行保持一致；测试库清理 |
| 真实模型新分级 | `output/review-decisions-live-20260922/prepare-review.json`：使用现有绑定 `deepseek-v4-flash`，6 条意见（1 required、5 suggested）。真实 API 确认返回 409，见 `required-confirm-rejected.json`。没有宣称模型问题已全部修好 |
| 忽略持久化真实链路 | 模型这次没有 optional。独立新增一份受控审查（保留真实报告历史），通过生产服务写入 QA 数据；浏览器真实请求验证忽略 R1、刷新保留、恢复 R2、再次忽略 R3，旧 R0 请求 409，报告哈希不变。见 `controlled-review.json`、`browser-result.txt`、`decisions-sql-final.json`。该 optional 是测试样例，不冒充真实模型输出 |
| 有效意见与写回 | 在同一隔离库使用受控生成网关截获真实服务构造的提示词：已忽略的 optional ID / 建议不存在，6 条剩余意见完整保留；受控返回原正文，经真实工作稿事务写回为 R3，旧审稿 invalidated、候选保留。见 `generation-filter-evidence.json`、`generation-write-evidence.json`。此项不是新一次真实模型重写 |

上述后半表未带目录的文件均位于 `output/review-decisions-live-20260922/`。实际工作台浏览器截图：`output/playwright/review-decisions-ignored.png`。本批没有响应注入来伪造保存成功；受控审查及受控生成均明确标注。

测试过程中的修正：临时脚本曾使用系统默认编码读取 UTF-8、启动后未等服务就绪；受控生成网关初次缺少 stream 方法导致任务失败，原工作稿仍 R2。修正测试脚本后最终回执才计入通过。数据库结构探针初次直接使用随机库名被产品库存契约拒绝，后改用现有隔离测试逻辑名适配器，没有放宽生产校验。

## 产品库升级与保护

- 使用现有备份优先、固定历史 manifest / 结构指纹、MySQL 8.4 客户端校验、生命周期锁、DDL 后结构校验及元数据 CAS 的升级机制，新增 `upgrade_product_database_v116.py`。
- 正式目标仍为 `novel_creator_v113`。首次执行因 QA 服务持有生命周期锁而在备份 / DDL 前退出；只读确认原库仍完整 v1.15。关闭自有 QA 服务后正常升级，未绕过锁、未清空或重建产品库。
- 备份：`D:\NovelCreatorBackups\review-decisions-v116-20260922\phase7b-backup-226803cbf1ca4600ec5cf5ec7be8739e.sql`，5,705,524 字节，SHA-256 `c1611a20f52aa8d0b0f96c71aa34df5ee993f62a7e1380939f5cd67a50a10378`。保留备份，不将凭据或备份内容写进验收输出。
- 升级 v1.15 → v1.16，仅新增 1 张表（100 → 101）；脚本核对全部原表行数相同，新表 0 行。回执 `output/review-decisions-product-upgrade-final.txt`。
- 升级后只读核验 schema / manifest、历史已定稿审稿哈希仍可读取、源 QA 两章会话状态一致，新表无测试记录，见 `output/review-decisions-live-20260922/product-verification.json`。本批测试记录仅存在于独立库，现已清理。
- 自有浏览器、QA 服务及管理器均关闭，18000 / 15173 无监听；见 `stop-verification.json`、`stopped.json`、`database-cleaned.json`。当前批次安全停止。

## 仍保留的边界

本批补齐分级和忽略能力，不代表模型分级总是准确，也不代表所有意见都已解决。完整真实模型重写沿用前批证据；本批过滤后写回使用受控网关。自动故事块 / 阶段 / 任务、跨卷承接及逐页复核中其余差异仍未完成，不能称整套前端已按原型全部交付。
