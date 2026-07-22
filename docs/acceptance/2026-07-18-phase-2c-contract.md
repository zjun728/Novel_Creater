# Phase 2C 故事发动机与创作契约验收

状态：Task 6 的 focused browser / unit / integration 证据与最终五门禁已于
2026-07-23 fresh 通过。

## 验收边界

- `@manual` 与 `@gateway` 分别使用新建的 Disposable MySQL 数据库、临时
  root、随机项目 ID 和 runner 独占端口，两个场景不共享产品状态。
- manual 场景在独立事务中禁用全部 Provider，证明完整契约可在 no-model
  状态下由作者手动完成。
- gateway 场景只连接 runner-owned `127.0.0.1` fake OpenAI-compatible
  gateway。fake server、FastAPI 与 Vite 均由同一 lifecycle 登记、健康检查并
  反向清理；未访问真实 Provider 或其他外部模型端点。
- fake gateway 只接受正式 story-engine、style-trial 和 asset-ranking prompt；
  未知路径、未知请求类型、畸形请求与错误凭据均 fail closed。append-only
  ledger 只记录固定请求类型，不保存 Authorization、prompt、body 或原始响应。
- FastAPI 测试进程在导入产品应用前安装 HTTPX 出站边界：manual 没有任何允许
  目标；gateway 只允许 runner-owned `127.0.0.1` 精确端口上的
  `/v1/chat/completions`。独立违规 ledger 只允许固定
  `forbidden-outbound` 类型，不保存 URL、header、body、prompt 或响应。
- 浏览器运行时审计会拒绝 console、非预期 HTTP、页面异常、请求失败，以及请求
  /响应 header 或 body 读取失败。唯一控制流例外是当前项目尚无草稿时的精确
  `GET /contract-draft` 404 与 Chromium 固定公共 console 文本；两者必须关联且
  严格计数为 manual `1` 次、gateway `2` 次，未知场景直接失败。

## Fresh 浏览器行为证据

- `@manual`：通过。通过真实 UI 导入合成语料、创建并选定种子、手动填写三套
  故事发动机、明确选择主/次风格、经验卡和一个语料片段范围，填写容量与禁止
  方向，预览并一次确认完整契约；历史抽屉显示完整冻结身份。
- `@gateway`：通过。通过真实 UI 取得且只显示三套正式故事发动机方案，选择一
  案，从完整风格库选择主风格，运行一次临时风格试写，在低置信推荐为空后仍从
  完整经验库和语料库手动选择，填写容量，预览并确认 R1。
- gateway 确认后通过 UI 新建并选择 B（选择代次 R2），再重新选择 A（R3）。
  返回主页面后不显示“当前生效的创作契约”，而是从当前选择进入故事发动机
  第一步；历史入口仍可打开。历史 R1 显示人类文案“种子选择代次已改变”，
  不显示内部码 `selection_revision_changed`，且“调整未来设计”保持禁用；
  旧契约没有因重新选择同一个 A 而复活。
- gateway ledger：story-engine `1`、style-trial `1`、asset-ranking `2`。
  两次 asset-ranking 不是重试：第一次基于尚未冻结风格的发动机草稿，第二次
  基于已冻结主风格的新 recommendation fingerprint。两次均由 fake gateway
  返回 `0.20` 低置信结果，产品均降级为空推荐并保留完整手动浏览入口。
- 独立 outbound ledger：`@manual` 的 `forbidden-outbound=0`；`@gateway` 的
  `forbidden-outbound=0`。两个值都在浏览器完成后、场景清理前由 runner 读取并
  fail-closed 验证。

## Fresh focused 结果

- `frontend/tests/unit/projectContractView.test.mjs`：`31 passed`；
  `frontend/tests/unit/creationAssetStore.test.mjs`：`8 passed`。
- `scripts/tests/phase2cSuite.test.mjs`：`17 passed`；中立 runtime observer：
  `13 passed`。
- 中立 product runner 与 product-shell / Phase 2A / Phase 2B / Phase 2C
  runner 合同：`79 passed`；四个正式 runner 不再保有本地 command、server
  start/wait/stop 或 close/drain 生命周期副本。
- asset recommendation gateway / service、story-engine gateway、style-trial
  prompt 与 contract service 聚焦：`240 passed`。
- 真实 Disposable MySQL A → B → A contract history integration：`1 passed`；
  `created=1 cleaned=1 remaining=0`。
- 本轮前端组件、正式 runner、runtime 与 server log 联合回归：`136 passed`；
  server log observer 单组：`5 passed`。
- runner syntax 与本轮 focused `git diff --check`：通过。
- 浏览器旁路 API、生产临时诊断标记、不安全 ledger 写入扫描：均为 `0`。

## Fresh 清理证据

- `novel_creator_test_%` Disposable MySQL 数据库：`0`
- `%TEMP%/novel-creator-phase2c-*` 临时 root：`0`
- 当前工作树关联的 runner-owned Node / Python 子进程：`0`
- 真实 Provider 调用：`0`

## 最终五门禁（通过）

首次串行执行在 `npm test` 暴露旧 M2 L5 verifier 漏读六个关系投影字段后立即
停止。该 verifier 合同漂移经 TDD 修复并独立复审为
`Critical 0 / Important 0 / Minor 0`；随后从第一条命令重新开始，以下五条按顺序
fresh 通过：

- [x] `npm run test:browser:phase2c`：exit `0`；完成后临时 root `0`、
  runner-owned Node / Python 进程 `0`、`novel_creator_test_%` 数据库 `0`。
- [x] `npm test`：exit `0`；Python `2085 passed, 6 skipped`；Node scripts
  `174 passed`；frontend `268 passed`。
- [x] `npm run test:integration`：exit `0`；`256 passed`；Disposable MySQL
  `created=255 cleaned=255 remaining=0`；独立清理复核的临时 root、owned 进程和
  测试数据库也均为 `0`。
- [x] `npm run build`：exit `0`；Vite `2928 modules transformed`，production
  build 成功。
- [x] `git diff --check`：exit `0`；仅有 Windows checkout 的 LF/CRLF 转换提示，
  无 whitespace error。
