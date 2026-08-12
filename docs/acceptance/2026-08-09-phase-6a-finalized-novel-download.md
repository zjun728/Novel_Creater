# Phase 6A Finalized Novel Download Acceptance

## 结论与范围

Phase 6A 已在随机 Disposable MySQL、真实 FastAPI/Vue 链和可见浏览器操作边界下验收。
作者可以从活动项目概览或归档项目只读页，按整本、分卷或单章下载已定稿正文，格式限定为
UTF-8 TXT 或 Markdown。

本阶段只接受 finalized TXT/Markdown download with disposable local data。项目备份、项目导入、
完整 Phase 6、真实 Provider 质量和产品数据库 readiness 均未验收。

## 闭合的不变量

- 下载权威只来自 `final_chapters` 及其钉住的 ChapterSession、Outline revision 和 Planning
  revision；不读取当前 head、WorkingDraft、Candidate 或 Provider。
- 所有 pinned id/revision/hash、Planning 节点内容 hash、Outline 内容 hash 和最终正文 SHA-256
  均重新核验；缺失、漂移或损坏统一 fail closed，公开错误不回显内部标识或正文。
- selector 只允许 book、volume 或 chapter 三种互斥范围；格式只允许 txt 或 markdown。输出按
  全局章序确定性排序，统一 LF、无 BOM、单末尾换行，并受 128 MiB 上限约束。
- HTTP 只新增 options 和 download 两条 GET route；query 拒绝额外字段和冲突组合；响应使用
  attachment、`private, no-store` 和 `nosniff`，文件名同时提供安全 ASCII fallback 与 UTF-8 名称。
- 前端 binary 请求与既有 JSON 请求隔离；外部取消、30 秒超时、listener/timer、object URL 和
  single-owner operation 生命周期闭合。活动与归档项目共用一个次级下载面板。
- 下载期间 operation overlay、Vue Router guard 和 `beforeunload` 同时阻断离页；无确认、取消、
  正文预览、下载历史、后台 job 或通用 workflow。
- 自动验收不调用真实 Provider，不读取产品数据库，不新增 schema/migration，不记录正文 body、
  DSN、密钥或 Provider 原文。

## Fresh focused evidence

- `python -m pytest -q backend/tests/unit/test_novel_downloads.py backend/tests/unit/test_novel_download_repository.py backend/tests/unit/test_novel_download_service.py backend/tests/api/test_novel_download_routes.py backend/tests/api/test_route_inventory.py`：`43 passed`，exit `0`。
- `python -m pytest -q backend/tests/integration/test_novel_download_repository_mysql.py`：`2 passed`；
  disposable database `created=2 cleaned=2 remaining=0`，exit `0`。
- `node --test frontend/tests/unit/appFeedback.test.mjs frontend/tests/unit/novelDownloadApi.test.mjs frontend/tests/unit/novelDownloadController.test.mjs frontend/tests/unit/novelDownloadPanel.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs`：`49/49 passed`，exit `0`。
- `node --test scripts/tests/phase6aBrowserContract.test.mjs`：`2/2 passed`，exit `0`。
- `npm run test:browser:phase6a`：visible UI scenario `1/1 passed`。真实 TXT/Markdown 文件字节包含
  两章定稿且顺序正确，不包含未保存、WorkingDraft 或 Candidate sentinel；归档后下载仍可用；
  held local response 下 overlay 可见且产品导航被阻断。
- Browser runner 报告 disposable DB、API/Vite/deny-proxy process、3 个 owned ports、temp、
  artifacts、downloads 和 Vite `deps_temp` residue 均为 `0`；outbound/Provider calls `0`，
  product DB reads/writes `0/0`。
- `npm --prefix frontend run build`：Vite build passed；`python -m py_compile
  backend/scripts/prepare_phase6a_browser_db.py` 与 `git diff --check` exit `0`。

## 首因历史

- Runner contract 首次 RED：Phase 6A scripts/config/spec 尚不存在；最小 wiring 后 `2/2`。
- 首次 runner 启动失败于 database preparation：未向子进程传递 `TEST_MYSQL_*`；补齐显式测试
  环境后进入 fixture。
- 两章真实定稿 fixture 首次失败于第二章仍期望 Canon revision `0`；第一章提交已把权威推进为
  revision `1`，修正 expected authority 后通过。
- 首次浏览器运行在归档页模糊文本断言超时；改用归档视图明确标记后通过。
- 规格审查发现未保存 sentinel 只被排除、未真实进入 UI；同一场景改为在仍打开的第 3 章可见
  编辑器输入并确认“未暂存”，随后从可见项目链接打开的概览页下载，实际字节继续排除该值。

以上失败均先定位单一首因后受控复跑；没有放宽产品校验、绕过 UI 或读取产品数据库。

## Review 与延期项

- 最终 specification review：`Critical/Important/Minor = 0/0/2`，仅既知延期 Minor。
- 最终 quality review：`Critical/Important/Minor = 0/0/2`，批准。
- 已知非阻断 Minor：若依赖的 `operationStore.finish()` 自身抛错，controller 的 busy/in-flight
  清理可能被跳过；options load 期间 dispose 后，已销毁实例的 `loading` 可能保持 true。
- Browser runner 的更广泛出站拦截、全窗口 runtime 观测、fixture 私有 helper 解耦和 cleanup
  故障注入属于非 active-path 测试加固，按精简策略延期，不回流 Phase 6A。

## 资源与控制面账本

- 最终独立审计：owned Python/Node/browser process `0`、owned listen port `0`、Phase6A temp
  root `0`、`novel_creator_test_%` database `0`、schema/migration changes `0`、job/workflow
  changes `0`。
- 产品工作树在 `0de6402` 后 clean；本阶段未 push。
- 一次 Task 5 子任务曾误在禁止的 `D:\Projects\Novel_Creater` checkout 中只新增两条 RED
  测试到 `frontend/tests/unit/appFeedback.test.mjs`，未改生产代码。该 checkout 不属于本验收分支；
  依据控制面禁令未在此清理，仍需用户另行明确授权后处理。

## 后续边界

下一切片是 Phase 6B：确定性、无密钥的项目备份包。Phase 6B 不新增通用 job/workflow，
不恢复 Provider 配置，也不自动匹配 Provider。Phase 6C 才负责严格预检和原子导入为新项目。

