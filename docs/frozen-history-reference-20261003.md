# 候选冻结版本历史参考实施记录

## 范围与基线

- 本批：`NC-CANON-FROZEN-HISTORY-IMPLEMENT-20261003`。起始 `main`、`HEAD=origin/main=976100d865d0d2c8d8993bb86d1dee507201ce98`，工作区干净。按用户授权实施、专项验证、正常提交推送后停止，等待独立审核。
- 只增加作者事实核对的局部历史参考。复用 Canon 事件历史与 continuity 的“截至 R 最后已确认非 claim 状态”规则；没有建立第二套历史、字段注册表、模型复核或迁移体系。
- **不默认重建 Canon、不复算完整 canonHash/projectionHash，不声称完整冻结输入已复验。** 候选正文、保存 manifest/provenance 及 ChangeSet 的身份／hash 校验，只用于绑定本次局部参考。该功能提高人工可见性，未解决旧 Canon 复制、同实体字段新主题或跨实体归属的自动语义问题。

## 读取与边界

- 独立 GET：`/api/projects/{projectId}/chapter-sessions/{sessionId}/finalization/history-reference`。请求必须带 `attemptId/candidateId/candidateHash/canonRevision/expectedRevision/expectedRevisionHash`，响应返回同一组身份及局部条目。没有调用者可指定的实体／字段查询接口，也不能任意浏览旧 review。
- `FinalizationRepository.read_history_context` 读取该 session 最新已保存 attempt，关联保存 ChangeSet 版本及 hash、同项目／session 候选、冻结 Canon revision 是否存在。只读封装核对保存 manifest 的 hash 与项目／session／候选／冻结 revision，候选正文 hash、provenance 的 basis hash／revision／planning／outline pin，以及实际保存 ChangeSet hash。
- 不调用写入的 `_basis_is_valid`，不要求当前 Canon head 等于冻结 R。原 continuity reader 的当前同步 head 限制及原写入版本／hash／CURRENT head／事务／确认保护保持原代码。
- 查询键只取**已保存 ChangeSet** 的去重 `(entityId, 原始完整 fieldPath)`。全局和本批新实体返回 `not_applicable`；已存在实体先核对该项目与创建 revision，不返回未经历史验证的名称，界面使用 ID。
- 状态 SQL 先按同项目、二进制精确 entityId／完整路径、`revision_number<=R`、`confirmed`、非 `claim` 筛选，再按 revision／event_order 降序选最后来源。不用路径末词、章节时效、MAX(revision)、multi 并集或 JSON 子路径合并。第二条仅检查异常同序来源；异常来源不猜旧值。
- `present` 携带实际 JSON 值及来源 eventId／revision／eventOrder；`absent` 是合法读取后无该字段已确认状态；`unavailable` 是无法核实或读取失败。null、空串、空数组／对象、false、0、嵌套值保持原类型，只有 claim 时不能顶替状态。无最新 Canon fallback。
- 读取结束再次核对同一保存身份，遇并行保存或最新 attempt 改变拒绝响应。前端在项目／session／attempt／候选／冻结 R／保存版本 hash 切换或卸载后丢弃迟到结果。
- 生产 reader 使用现有 `read_only_transaction`。键数由既有 ChangeSet 最多 2048 条 Canon event 约束；设 K 为去重可查询键、E 为相关既有实体，最多两次保存上下文读取、E 次实体读取、K 次最多两行的状态读取。**本批只断言 SQL 与返回边界，没有真实 MySQL 执行计划、扫描量或延迟证明；LIMIT 不等于扫描行数。** 未更改数据库结构／索引。

## 页面与保存恢复

- 原事实卡增加三列“历史参考值／当前作者草稿值／本次冻结候选正文依据”，显示实体 ID 与完整路径、冻结 R 和局部来源 revision／eventOrder；长 JSON 可滚动且保留完整结构，小屏纵向排列。
- 当前值跟随作者草稿；正文依据沿现有 review candidateId+hash 定位候选及证据，未取正在编辑的其他正文。同键多条候选共享冻结参考，不将前一条候选冒充后一条旧值。
- 中性说明允许正常状态更新，不判错、不自动排除、不要求字段迁移、不新增确认门禁。作者继续使用原改值／类型、排除、现有补录和确认路径，关联实体／路径不可直接编辑及复杂值补录的现有限制保持。
- 独立 composable 只持有历史参考；自动读取、手动刷新、失败均不替换 review，不触碰作者草稿、确认选项、ChangeSet 或原保存状态。未保存新路径提示“尚未读取”，保存成功并正常重读后才纳入范围。
- POST 明确拒绝仍保留草稿；POST 已接受而 review GET 失败仍走“刷新核对修正”及原写入锁定。comparison 成功不能解除原待核对；review 成功而 comparison 失败只显示历史参考不可用。确认后编辑只读，刷新历史参考保留已展开的撤销确认选项。

## 最终有效验证

| 集合 | 结果 | 证据与实际边界 |
| --- | --- | --- |
| 后端专项 | 148 通过 | 新历史 reader 35、真实 FastAPI 路由＋reader／内存仓库 20，及已有 continuity、repository、finalization checks/service 回归；无真实数据库连接 |
| 前端相关专项 | 111 通过，0 失败／跳过 | helper、controller、Panel、API、evidence、现有补录；包括身份迟到、类型、输入保留、保存恢复及确认选项 |
| 隔离浏览器与证据核对 | 35 检查通过 | 实际 Vue Panel/controller/API＋独占 Node 内存 HTTP，正常 UI 改值／保存／恢复／确认／重载，1280／390 宽度截图与 DOM；不等同真实后端数据库往返 |

命令（每项只采用最后有效集合，不累计重跑）：

```text
python -m pytest backend/tests/unit/test_finalization_history.py backend/tests/api/test_finalization_history_routes.py backend/tests/unit/test_continuity_field_history.py backend/tests/unit/test_finalization_repository.py backend/tests/unit/test_finalization_checks.py backend/tests/unit/test_finalization_service.py -q
node --test frontend/tests/unit/finalizationHistory.test.mjs frontend/tests/unit/finalizationController.test.mjs frontend/tests/unit/finalizationPanel.test.mjs frontend/tests/unit/finalizationApi.test.mjs frontend/tests/unit/finalizationEvidence.test.mjs frontend/tests/unit/addCanonFact.test.mjs
python output/frozen-history-reference-20261003/verify-browser.py
```

- 后端／API覆盖精确实体及大小写完整路径、同 revision 顺序、claim/rejected/R 后排除、R0／无旧值／空值／嵌套 JSON、同键去重、全局／新实体、身份／manifest／basis／保存 hash 异常、并行保存和不可核实来源。SQL 通过 capture 断言参数化及精确路径筛选先于 LIMIT；不是数据库实际执行验收。
- 浏览器直接读取原 `output/pro-semantic-consistency-20261003/A-manifest.json` 与 `A1-first-extraction.json`，保留完整十五章正文 2310 个 Unicode 字符，候选 SHA256 `3d86b2b1e602da6c403b48fd212b2a9bf53b4d53607a5a27e2c91db0d033f19c`。ce-04 账料呈报→记工簿行踪、ce-09 瓶样分持→行踪对照、ce-02 同事项闸缝进度均展示准确原值、新值及对应正文；正常更新允许原确认。
- 上述浏览器历史值来自 manifest，但返回的历史 eventId／revision／eventOrder **为合成夹具元数据**，不能冒充原数据库来源证明。只选三项组成有效内存 ChangeSet，不重放其余模型输出，也没有修改原诊断材料。
- 只读场景把夹具 Canon head 标记 R14 推进到 R15，再刷新仍请求冻结 R14；全部为 GET，保存状态不变。独立保存场景保持 R14：第一次保存 422 拒绝；第二次保存接受 R2，随后 review 503，旧保存身份 comparison 409；“刷新核对修正”读回 R2 后 comparison 503；恢复 comparison，再通过页面确认 R2／hash，重载只读。R1 未变，R2 仅 ce-04.value 改动，其他身份／类型／证据／事实完整保留，未点定稿或真正撤销。
- 两个完成场景各 5／15 个产品 API 请求；失败／恢复明细保留。浏览器注入错误时的四个 HTTP 异常在操作快照保留；最终重载后 console 为 0 errors／0 warnings。没有将注入失败隐藏为始终成功。
- 原始有效日志、输入、inspect、失败／恢复 DOM、截图、`verification.json` 留在本机 `output/frozen-history-reference-20261003` 与 `output/playwright/frozen-history-reference-20261003`，不提交业务材料。

## 失败记录、保护与资源

- 红测包含尚未实现 reader／helper 的预期失败。中途失败均保留：后台新实体 fixture 与 event ID 重复；两处前端 fixture 断言误认既有撤销展开按钮／无效数字输入时的保存按钮；API fixture 将 missing-entity 断言放错用例。这些仅改夹具／断言，没有降低产品校验。最终有效集合全部通过。
- 浏览器初次启动只有 favicon 404，增加本轮隔离服务的 204 响应后重开。首次服务未以 tty 启动、stdin 已关闭，核对脚本绝对路径、owner nonce、端口所属 PID 后仅结束自有 PID18904；其读取快照留存。后续两次均 tty stdin 正常关闭，`resourcesClosed=true`。核对 PID18904/14672/35984 已不存在，自有端口6479/7031/10149无监听；未杀用户进程或占用常用端口。
- 浏览器证据汇总首版误读一个 DOM 文件的字段名产生 KeyError；按已保存 DOM 实际 `unavailable` 字段修正后 35 项通过，没有重跑产品流程或改产品代码凑通过。
- 起始保护清单覆盖 2881 个已有文件（跟踪文件、环境配置、相关既有原始材料与 zip）。最终仅明确产品／专项测试／状态文档改动，清单外变化必须为空。模型配置／提示词、Canon 归约、原 controller、Schema／数据库、原诊断与备份保持；正式数据库／小说访问与写入 0，项目模型调用 0。
- 未运行全量构建、全平台回归、真实 MySQL SQL 往返／性能测量或完整冻结快照重建；没有验收自动语义准确率。新增 API 的真实数据库集成及局部查询成本仍是明确未验证部分。
- 按既有授权正常提交推送 `main`；准确提交与远端／工作区回执见 Git 和本机 `closeout.json`。完成后停止，等待独立审核，不继续其他语义方案实施。
