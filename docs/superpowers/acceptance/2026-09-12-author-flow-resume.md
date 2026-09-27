# 2026-09-12 真实作者流程恢复记录

第一章已通过正式 UI 确认并定稿，非模拟请求。项目 a95c9cd9-c3f0-5e5d-81f3-bc0fb7127a6a；attempt f74b7744-91b8-4140-99db-80123d315b05；采用原作者修正 R2，hash 67ac535c35aa03bb4a6ca4ee67f41f12647a283063ea34add3a6d04b4a032556。GET复核 committed，currentChapter=1，Canon revision=1。原候选与定稿正文SHA256一致，11条Canon事实及1条进度证据共12处全部逐段hash匹配；仅第一章scene_task完成，未提前完成父阶段。证据 output/author-sep12-ch1-receipt.json 与 author-sep12-ch1-authority.json。

第二章小纲入口正常，已建立空白本地工作稿；未保存、未采用、未创建第二章写作会话。点击AI生成前自动审批拒绝命令执行：认为具体外部目的地与发送的数据范围尚未获明确授权。请求未发出，没有规避重试。随后只读查明当前规划/写作/审查等八项模型绑定均为 deepseek-v4-flash，目的地主机 api.deepseek.com；没有读取或展示API密钥。

恢复所需授权：允许为该QA项目的真实三章验收，通过现有项目模型配置向 api.deepseek.com 发送生成/审查所需的创作规划、连续性上下文、章节正文及补充要求；不更换模型配置。

第二章作者补充要求（已在浏览器输入，未持久化；此处保留，恢复可重新填入）：严格承接已定稿第一章：铁牌仍在江越怀中，哥哥的鞋已烧毁，工钱已付出，右耳耳鸣未愈，子时旧泊位赴约。本章只关联既有第二章场景任务73aa586d-d2b2-4a2f-a1ed-8c7af1ca9e38，不重复第一章任务。无月雾夜，不带灯火；江越登船，靠小满转述口令，听见三短两长却遵守铁鹞子禁令，不回应。暗流中用浮草判断水势、与同伴撑篙脱险，先保全船再查信号。禁止确认哥哥在水下或已死，不恢复听力、不获得超能力，不提前揭露铁牌秘密。

完整三章验收仍未完成。保留本次所有证据与产品数据，不回滚已定稿第一章，不重新生成第一章或覆盖原作者修正。代码未修改，未提交/推送。

收尾核验：正式历史页面显示第一章已定稿，并提供继续第二章小纲链接。浏览器author-sep12已关闭，自有8000/5173无监听；MySQL保留运行。


## 同日恢复后的实际进展

已获用户明确允许使用现有 DeepSeek 配置，当前权限为完整访问。上文等待授权与停止服务均为较早断点。第二章已 committed，Canon R2；R2 审查 hash 2a3e517008e36b15fa2e7f6985dd1dcded730068ca9e6b27e2ba9ef48d2dd420。长审查事件 ID 映射为按项目/来源限定的稳定 UUID，保留原审查 payload/hash、实体 ID 和既有短 ID；27 项定向单测及 MySQL 检查通过，产品历史与来源可回读。

第三章开始后，用户指出临时补充要求不代表默认用户操作，主验收改为作者临时要求留空。首轮留空生成 operation 2241c9dc-b8e7-4b28-9804-47da4feedf38 提前解释铁牌秘密并扩大调查任务，判定质量失败；第一次通用约束修正后 operation 534f01d5-fefe-4163-882e-547dc0142da8 仍有铁牌信息泄露，未采用或定稿。原始工作稿分别保留于 output/author-sep12b-ch3-blank-session.json、author-sep12b-ch3-boundary-session.json。继续修复自动小纲执行边界和小纲/合同字数读取，不能以手动改文代替默认质量通过。


## 默认生成及三章闭环实际结果

第三章最终默认 operation 0f8fe0e8-a385-44dc-be87-6f8b6fb3c343，generate_new，authorInstruction=""。系统自动读取 Outline R1（hash 3cb0604f959e73f04e6b89ef489beb347ac605892b6cf68ea36a37b6b483fd2a），未发送旧工作稿正文作重写输入。最终3286 Unicode字符（2624汉字），符合产品当前字符计数口径的2800–3800范围；不是只统计汉字的口径。原稿、候选、定稿SHA256均为99127c82b1dacec07eb835cf3174b41b68aa9a6cf6cfe8fd1547e7edcfad3788，未人工改写。

第三章通过正式页面保存候选、准备审查、作者补录、保存R2、确认、定稿。审查R2 hash406a32f74a993a0c6527c5f5d52999f88790a13b69a551b5ac3e1c3d45f5ed8b，committed。补录arc.acceptingCompanionHelp仅记录p61–p68已发生的拉袖求助与同伴协助约定；未把未来计划当事实。共12条Canon和1条scene_task进度，13处原文证据全部匹配。三章仅各自scene_task完成，没有自动完成父阶段/故事块。

实测人物弧光显示首次形成/最近更新第3章、原文依据及来源章链接。1440×900与1920×1080截图已查看：output/playwright/third-arc-1440.png、third-arc-source-1920.png。三章历史review/manuscript GET均成功。第一章正文hash e0d1f3cd3e56342b20babf7c09ffa8c098e135454c86bfb8c8d9e6af5d462b62，第二章a5d8498cc4d9e0b750bf5019acdc785483bb83bd4f8546e984039fb46b68af5c，均保持原定稿不变。

修改：默认正文提示明确背景知情范围不等于本章披露范围，将小纲目标/逐场交付/禁止事项/结尾边界自动列为执行边界；字数优先本章capacityPolicy，其次创作合同chapterWordRangePreference，局部润色不套用整章预算。界面明确临时要求可选、无需重复小纲，保留无障碍说明关联。相关后端60项、界面14项通过，前端构建通过。

质量边界：该章证明留空默认链路可以生成并完成真实定稿，不代表模型永远遵守规划；此前两版泄露秘密已判失败并保留。当前审查仍提示结尾偏弱、主动表态不足和表达问题，没有将自动审查建议全部采纳；特别是引入未选角色或额外悬念的建议不可直接当作规划指令。第1/2章有临时要求和作者修文，因此不是连续三章全留空质量样本。

## 导出恢复核验发现的问题

页面已成功下载整本novel.txt，核实包含三章完整定稿正文；页面也成功下载project-backup.zip，另保留output/author-sep12b-three-chapter.zip，591064字节，ZIP完整性及响应头SHA256匹配。最初500源于本机未配置MANAGED_CORPUS_ROOT；只读核实corpus_blobs和corpus_sources均0，显式配置D:/Novel_Creater_ManagedCorpus，现有数据库及CORPUS_ROOT字段未变。

真实多章备份又发现：Canon progress.value.targetId/fieldPath未按包内规划引用改写；Seed来源快照ID误当项目内ID；导入把共享投影hash误判重复。修复遵守引用完整性与原来源证据保留，未清空或改写生产QA历史。隔离MySQL进度回归覆盖真实提交长ID、导出、ZIP预检、发布计划及投影ID重映射，1 passed且测试库created1/cleaned1/remaining0；实际QA包预检仍在最后复核中。


### 备份预检与恢复计划补充

实际ZIP的read_verified_project_package已通过。投影摘要此前把多条记录共享bundle hash错误当成重复身份，已修正；实际摘要currentState27条、memory7条、plotThread3条各共享同一版本hash，属于正常记录。仍保留数量、排序、哈希格式与规范序列化验证。

build_publication_plan随后发现同一候选的10次审查重试无法用candidate唯一匹配quality，且失败attempt无revision。不能据预检通过就宣称实际导入可用；正在补精确质量报告关联和失败历史保持。三章定稿数据没有参与回滚或清理。


## 最终闭环结果（同日18:40后）

备份恢复阻塞全部闭合。最新文件 output/author-sep12b-three-chapter-history-fixed.zip，594091字节，SHA256 cb8bd5ac07b6e9bc5a021e4928ecc5b5f4fd53318a7a7f4f5c393d1db83b8cd4。重载正式后端后，对该包API预检200；正式前端重新点击创建项目备份，下载文件与该包SHA256一致。旧591064字节文件只保留失败过程证据，不作为交付恢复包。

导出新增精确qualityReportLogicalId；导入验证报告属于相应章节、候选及内容，恢复时保留failed/cancelled/invalidated及空quality/空revision历史，保持确认信息与Planning/Outline哈希引用。旧缺精确关联且同一候选多报告的备份继续拒绝猜配，应使用重新导出的新包。

read_verified_project_package与build_publication_plan对实际新包均通过，46批发布计划、3章、12次审查（failed7/committed3/cancelled2）。实际包在隔离MySQL完成真实publish并逐条核对重映射后的quality_report_id/current_revision，逐章content_hash一致。另一个自包含重复审查测试覆盖failed无quality/无revision，恢复后再导出通过。最新两项2 passed / 27.71s，created2/cleaned2/remaining0；生产QA未导入、未回滚。

验证分组（有交叉，不相加）：默认正文及网关60项；作者输入界面14项、前端构建通过；长审查ID27项含真实MySQL；进度导出93项、导入90项、来源证据初批133项；进度真实MySQL1项（created1/cleaned1/remaining0）；来源与reader补充23项；投影哈希5项；最终审查历史相关125项与恢复MySQL2项。diff check通过。关键证据：author-sep12b-default-final-receipt.json、author-sep12b-three-chapter-receipt.json、author-sep12b-backup-publication-plan.json、author-sep12b-backup-final-preflight.json、author-sep12b-backup-download-receipt.json。

本轮交付范围是三章作者操作链路、默认留空生成的一章真实样本、事实/弧光来源及导出恢复。生成质量仍由作者审阅；审查建议不等于应当照做的规划。未宣称所有模块或长篇质量已全面验收，未提交/推送。最新用户要求持续推进，因此当前本地8000/5173与author-sep12c浏览器保留供查看，MySQL保留；不再沿用早前安全停止断点。
