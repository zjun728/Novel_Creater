# 2026-09-12 从选题开始的默认用户全流程验收

用户要求重新从头串联完整流程。此轮不复用已确认的江夜行项目来冒充从零验收，使用QA-FULL-20260912-1846标识的新讨论、方向、候选和项目。现有真实模型配置不变；所有正文生成作者临时要求留空，合法必填创作意图/合同参数通过UI填写。仅常规PC尺寸。

顺序：市场证据查看/刷新 → 新讨论 → 保存方向与候选/版本 → 从候选创建项目 → 种子确认 → 创作契约与模型/风格 → 圣经/设定 → 卷、情节、人物计划、故事块与阶段任务 → 第一至三章小纲/写作/审查/定稿 → 事实/状态/弧光/线索/原文 → 正文下载/备份/恢复。每步以真实页面操作与后台只读回执对照，不用直接数据库填充业务状态。

18:55：QQ阅读男生人气榜刷新成功（18:47，20部）；附加到新讨论 `632c5ea0-6345-496f-aa58-79a62d89bd36`。真实AI返回原创方向与候选，页面保存“低玄东方工程探案：河工司秘录”与《闸匠河图》。候选V2仅规范题材为“东方奇幻 / 工程探案”，V1保留。指定V2创建项目 `5b34d499-8fe0-5878-91ed-b22405000f5d`（QA-FULL-20260912-1846-闸匠河图），页面显示来源版本2、种子修订1，完整内容核对后显式确认。正在创作契约生成三套发动机；尚未生成正文。

证据：`output/full-topic-discussion-first.json`、`output/playwright/full-topic-answer.yml`、`.playwright-cli/page-2026-09-12T10-50-29-289Z.yml`（V2建项弹窗）、`.playwright-cli/page-2026-09-12T10-53-38-280Z.yml`（新项目种子完整文档）。

19:04：发动机首次真实生成invalid_response，现有持久记录只有hash，不足以确定原因。临时只记录响应长度/finish_reason/校验错误类型，随后页面请求成功：finish_reason=stop、contentLength4092、completion_tokens3733（含reasoning1291）；三案通过原校验并保存甲案“闸谱：十二闸递进式工程探案”。这是重试恢复，不是根因修复；中间一次请求发生在自有后端重启完成前，ERR_CONNECTION_REFUSED属于验收操作问题，未到模型。诊断服务已退出，正常后端恢复（PID18760）。失败及诊断证据保留：`output/playwright/full-engine.yml`、`output/full-engine-diagnostic.jsonl`、`output/playwright/full-engine-retry.yml`。

八项模型绑定从现有默认项目复制并就绪，未改模型配置（`output/full-model-bindings.json`）。页面阅读直接推进型完整样例、选择主风格、真实临时风格试写完成、保存主风格引用；试写不入正式章节，likes/dislikes仍空。修复推荐返回4项却写死“4 / 3”的文案，改为动态“4个推荐”；相关前端67项通过，截图快照 `output/playwright/full-style-trial.yml` 包含已完成试写与新文案。正在正式资产范围加载；本轮未生成任何正式章节。

19:15：契约R1确认：12卷/120万字/400章/单章2500～3500，主风格直接推进型、无辅风格，经验卡/语料显式零选择，额外偏好及作者备注空。圣经无额外要求AI生成，作者对照采纳、保存D1、正式确认R1。设定库展示圣经11类未来设计，明确没有已定稿实体/事实；截图已实际查看（`output/playwright/full-settings-before-chapters.png`）。

规划AI无额外要求生成12卷/6情节线，尚不含故事块；通过可见表单添加沈砚人物计划1节点（尚未关联正文人物）、首卷故事块“试水裂缝与旧闸钉”、3阶段/3场景任务（试水止漏、材料复验、分工留证），保存及确认Planning R1。`output/full-planning-r1.json` 保存完整只读回执。第一章空白小纲已建立，正在无额外要求AI生成。

发现的非阻断问题：规划AI把群像焦点/相关人物输出为cast-shenyan等编码，编辑表单照原样显示，影响可读性，不能据此宣称前端所有细节已完善。圣经个别句子夹杂method英文，内容质量仍需作者校订。未为通过验收而修改原模型正文。前端本轮构建通过（`output/full-flow-frontend-build.log`）。

19:31：第一章默认正文3991字符（3144汉字），作者临时要求空、正文未人工改写。作者正常审查排除缺乏正文支持的背景事实及泛称别名，将尚未获得农人见证的末阶段/任务/故事块由完成改为推进，29处证据hash核验通过，R2确认并定稿成功。随后正式稿读取500，定位为manuscripts.py的Plot hash重构漏characterDesign，已补齐非空字段并保留旧数据兼容，无需迁移或重复定稿。62项稿件/下载/历史审查回归通过；实际单章及历史审查GET均200，页面已恢复定稿全文，正在第二章空补充要求小纲生成。证据：output/full-ch1-generated.json、full-ch1-review-r2.json、full-ch1-final-readback.json、output/playwright/full-ch1-restored.yml。

19:40：第二章默认小纲实际重复了首章全部止漏/取钉/复验场景，未采用，证据output/playwright/full-ch2-ai.yml。根因为小纲manifest只有规划与投影hash，无上一章正文及实际进度；子任务正在修复并回归。第一章已定稿正文hash与原生成完全一致。人物计划通过真实UI查找并关联ent-shenyan，确认Planning R2（0a10377f-7697-4ab2-b3b0-14fda7246dbf）；按人物筛选能显示关联的五维计划，正文事实不随计划改变。output/full-planning-r2-associated.json、output/playwright/full-shenyan-associated.yml、full-character-associated.png；截图已查看。弧光/线索暂无正式分类记录，发现提取提示未说明投影使用的arc.* / plot.*，已补充同一次提取的分类约定及证据/未来意图边界，14项现有提示测试通过，真实提取效果仍待后续章，不冒充完成。

19:44：小纲续写修复156项通过，旧manifest重放兼容、completed任务过滤、投影权威与正文hash校验、64KB边界均覆盖。实际R2上下文重建manifest21,891字节，仅保留分工留证末任务，上一章全文未截断。后端已重启正常服务（PID36072），真实UI重新生成第二章；作者补充要求仍空。第一章TXT实际HTTP200且包含精确原文，状态变化历史页面也已读取成功。分类提示经独立复核补齐同一线索(entityId/null,fieldPath)联合复用及主线/支线/人物线/未完成情节范围；不存在单独模型或新增事实权威。

19:56：第二章修复后AI小纲仅选末任务并接续第一章结尾；作者在正常小纲核对中纠正“藏记录位置只有苏桐知道”一句，补充要求栏仍空。正文默认生成2921字符，hash f61f5b793ce8295977803cf3c21b66eebbf2e99956a9c49e5e9823366f54ae27，未人工改写。审查质量报告有重复对话、节奏与收束等意见，全部保留，不把功能通过视为出版质量通过。提取出现arc.trust，但骡车线索仍只有普通记录/claim，自动分类尚不完整；作者R2排除错误油样“各两份”记录、修正弧光从零转变的夸大表述，并用p53–p54补录plot.muleCart待查线索，保留claim不当已证实事实。24处证据全部匹配，确认定稿后正文GET200、弧光1条/线索1条Canon R2，页面及原文依据读取成功。

通过正常滚动规划新建第二故事块“验前查料”，一阶段“账料对照”及一场景任务，明确旧钉/油样保管、现场材料与账目核对、听闻待查；设为当前活动块、保存并确认Planning R3。原首块事实进度保持不变，未手工伪造父块完成。第三章空补充要求小纲生成中。证据：output/full-ch2-generated.json、full-ch2-review-r2.json、full-ch2-final-readback.json、full-planning-r3.json；output/playwright/full-ch2-retry-result.yml、full-ch2-arc.yml、full-ch2-clue-source.yml、full-plan-r3-preview.yml。

20:05：第三章默认生成2181字符，hash30dce86869e01b6b5bdc12a440101196e542ba721221b8913584c1eff4a2bfc0，低于合同2500–3500目标，明确记为默认篇幅质量未通过，不通过重抽样或人工扩写掩盖。审查R2仅排除把旧骡车听闻再次当新章说法的重复项，保留第二章claim及待查状态；其余6条事实/1条任务、17处证据全部hash匹配。第三章提交409，事务未提交（currentChapter仍2），原因是模型ce-01…及sp-01短ID与第二章已持久化事件撞全库主键。已通过产品库只读SELECT确认已有这些ID均属于Canon R2。修复所有新事件/进度ID按既有UUID5公式加入项目与审查作用域，旧已提交重放提前读取存储结果，历史不迁移。8项单元通过，真实MySQL回归进行中，第三章待同一审查重试。第三章内容及短篇幅问题均保留原始证据。


20:06–20:20：事件ID作用域修复通过2项真实MySQL（2库清理remaining0），同一第三章审查重试定稿成功，Canon R3。三章正式稿与原始生成hash全部相同。实际UI下载TXT与ZIP，ZIP 488931字节、8项、CRC通过，SHA256 e9300be615b71ef37dd1b2083a2ef6cf9fbb64308d16f4a6228067a37f8ccdd9；TXT含三章完整精确原文。文件output/full-flow-three-chapters.txt及.zip，核验output/full-export-verification.json。

通过UI导入为QA-RESTORE-20260912-2007-闸匠河图（6d4f7233-7094-5251-b69c-1ee1b4af7525）。三章manuscript200/hash相同；Canon R3弧光、线索和来源证据通过，沈砚人物计划entityId正确重映射；恢复8项模型绑定unbound、源项目8项仍bound，符合不带提供方配置的备份契约。但历史审查三章GET409：导入attempt使用空上下文而quality保留原contextHash；修复为明确标注恢复来源的共享manifest，保留源摘要并绑定恢复项目/候选/报告，不声称还原原模型上下文，也不弱化读取校验。54项定向单测通过（首次默认TEMP权限导致27项setup error，改用独立output basetemp后完整54通过）。新增真实reader核验继续发现审查人物引用与正式Canon实体映射不一致，正在修复。因此此前仅包行数/状态/正文hash检查不足以宣布历史页面已通过。证据output/full-restore-readback.json、full-restored-associations.json。


最终验收：从原项目通过UI重新导出 `output/full-flow-three-chapters-history-fixed.zip`，488682字节、8项、CRC通过，SHA256 `d7a0e35c41bf7025788834147e55d721f52ca1ff068ee07d6c74cecd47c8bbd0`。包中已提交实体使用精确Canon身份，历史未提交且定义不同者保持局部身份；不存在按姓名猜配。旧包缺失精确身份关联，保留作为失败证据，不作为本轮可恢复交付包。

实际UI导入新项目 `986f7ca9-f0f1-53b1-bc4e-d7a136dc021d`（QA-RESTORE-FIXED-20260912-闸匠河图）成功。源/恢复项目三章manuscript与完整workbench review均HTTP200；三章3991/2921/2181字符与原始生成hash逐一一致。Canon R3人物弧光形成第2章/更新第3章、线索形成第2章、沈砚明确关联人物计划、两条原文证据verified均通过。恢复八项模型绑定为空，源项目八项仍bound。界面实际打开恢复第3章正文及定稿审查、人物计划与变化历史；1440×900审查弹窗及1920×1080弧光历史截图已查看。证据：`output/full-restore-fixed-verification.json`、`output/playwright/full-fixed-review3.yml`、`full-fixed-review3-1440.png`、`full-fixed-arc-history.yml`、`full-fixed-arc-history-1920.png`。

恢复修复验证：99项既有相关单元通过；新增5单元及2项真实MySQL通过，实际新包三章完整WorkbenchReviewReader均通过；增强后的常规新实体fixture再验证通过。隔离数据库全部清理remaining0，git diff --check通过。先前只核行数/状态/正文hash的恢复证据不足以覆盖历史页面，本次已补真实reader与真实UI。不直接修改产品业务库，不提交或推送代码；源QA和两个恢复QA保留供审阅，失败恢复项目6d4f…仅作故障证据。

本轮结论：已通过上述范围的真实三章功能闭环。生成质量仍未全面通过：统一页面字符口径下第一章3991超出、第三章2181不足合同2500–3500，第二章2921符合；第一章3144汉字不能用于掩盖页面计数不一致。质量报告保留重复对话、节奏、情节转折等意见；作者审查仍纠正错误事实/夸大弧光、补录有证据的待查线索，第二章小纲有一次正常人工事实纠正。三章正文临时要求均空且正文完全未人工改写，但这不等于无人审核或长篇质量稳定。AI规划部分cast编码可读性及发动机首次invalid_response根因尚未解决；后者仅重试恢复。选题榜单本次实测QQ阅读男生人气榜20部，不扩大为全部来源实测。未将所有可选编辑/异常分支视为本轮全部通过。
