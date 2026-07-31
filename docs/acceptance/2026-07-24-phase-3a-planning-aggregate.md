# Phase 3A Planning Aggregate Foundation 验收

状态：Phase 3A 已完成独立规格与质量审查；2026-07-24 fresh 串行门禁通过。

## 验收身份

- 工作分支：`codex/phase3-story-planning`
- 门禁运行 HEAD：`2fd928c827f07dde73e89d8e3200e3ae8f6bd7d4`
- 基线：`main` 的 `f11faad531f04250f2a987390a468dfd14bf06a3`
- 源码 Schema：`writer-core-v1.5.0`

门禁在 Task 10 未提交工作树中运行。该 HEAD 是 Task 9 的代码链末；本报告、
Task 10 修复及其测试随后一起提交。

## 已验收能力

- Planning Aggregate 以不可变 revision、稳定节点身份和 canonical hash 保存
  Volume、Plot、StoryBlock、Stage 与 SceneTask。
- Planning Draft 只有显式保存才写入；确认使用幂等请求、完整 CAS 和事务回滚，
  历史 revision 不覆盖。
- Planning revision 精确绑定选定种子、创作契约、风格契约和创作圣经的
  12 项 generation 身份。
- 已确认 A → 切换 B → 再选 A 时，旧 Planning 只保留为历史，不展示、
  不克隆、不重新成为当前计划；新 Draft 为空并从物理 Head N 继续追加
  N+1、parent=N。
- Chapter Outline 精确绑定 Planning ID/revision/hash、Canon 与 Projection。
- ChapterSession 在创建或命中既有会话时，都重新验证当前 Planning generation、
  Planning Head、Outline、Canon 和 Projection；旧 Outline/Session 不能绕过
  当前权威。
- 公共 Planning/Outline 输入只接受冻结的 camelCase 字段；不提供 snake_case
  兼容别名。公共 DTO 不输出 generation 内部字段、数据库 JSON 或密钥。
- `writer-core-v1.5.0` 只支持当前 schema 的同版本开发重置；不迁移 v1.1/v1.4，
  不恢复旧 Planning 表、旧 Store 或旧生成链。

## 独立审查

- 规格审查：`Critical 0 / Important 0 / Minor 0`
- 质量审查：`Critical 0 / Important 0 / Minor 0`

审查中发现并修复：

- 已确认 Planning Head 原先缺少当前 Seed/Contract/Bible generation fence；
  现已封住 A → B → A 复活路径。
- ChapterSession 的既有会话快速返回原先可能先于当前权威校验；现已移到完整
  Planning/Outline/Canon/Projection 门禁之后。
- Planning/Outline 原先因 `populate_by_name` 接受第二套 snake_case 输入；
  现只保留 camelCase 公共协议。
- 跨代际后，同键同指纹的成功确认回放曾错误比较当前 basis；现只读取首次请求
  钉住的不可变 revision/hash，零写入且不推进 Head。
- 未批准的 `head.status` 公共字段已撤回，Head 响应仍为冻结的三个字段。

## Fresh 最终门禁

以下命令严格串行；前一项退出码为 `0` 后才启动下一项：

### `npm test`

- Python unit / API：`2353 passed, 6 skipped, 0 failed`
- 根级 Node 合同：`191 passed, 0 skipped, 0 failed`
- 前端 unit：`365 passed, 0 skipped, 0 failed`

### `npm run test:integration`

- Disposable MySQL integration：`300 passed, 0 failed`
- 数据库：`created=299, cleaned=299, remaining=0`
- pytest 耗时：`1028.11s`
- 结束后独立查询 `novel_creator_test_%`：`remaining=0`

### `npm run build`

- Vite：`2937 modules transformed`
- 构建结果：exit `0`

### `git diff --check`

- 结果：exit `0`
- whitespace errors：`0`
- 仅出现 Git 的工作区 LF/CRLF 转换提示，不属于 diff error。

## 门禁期间修复的旧接线残留

- `configure_local_mysql.py` 曾导入 Task 9 已删除的 reset 私有能力函数，导致
  `npm test` 收集失败。能力检查现由配置脚本自行拥有，严格验证 MySQL
  8.0.16≤version<9、合法版本后缀、0900 collation、JSON exact int 1 和
  CHECK count exact int；未恢复旧 helper 或兼容 alias。
- 两个 archived seed integration 测试仍按旧三参数调用正式定稿夹具。现只补入
  Disposable MySQL `connection_config`，继续经过正式 Planning → Outline →
  ChapterSession → Canon → Finalization → FinalChapter 测试链；未放宽夹具签名。

上述修复分别经过 RED → GREEN，并在进入最终 fresh 门禁前完成独立规格与质量
复审至 `0/0/0`。

## 隔离与未评估边界

- Provider calls：`0`
- Product DB reads/writes：`0/0`
- 外部网站访问：`0`
- 产品服务启动：`0`
- 自动门禁只使用随机命名 Disposable MySQL 8；未停止用户正常 MySQL 服务。
- API、日志、报告和测试输出均未导出明文 API key。
- 未评估：Phase 3B–3D、Real Provider、Product DB、Content Quality

Phase 3A 的通过只证明规划聚合地基、代际围栏、事务和正式测试链；不授予
Phase 3 全阶段、真实模型、产品数据库、正文生成或小说内容质量 Ready。

## 2026-07-31 authority amendment

The A->B->A seed-selection behavior recorded above was valid for the superseded
Phase 3A contract only. It is not current product authority. The first confirmed
Seed is now terminal under
`docs/superpowers/specs/2026-07-31-immutable-boundaries-revision-design.md`;
new acceptance must prove that a second selection is refused.
