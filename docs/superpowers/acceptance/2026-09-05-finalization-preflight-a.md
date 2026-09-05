# 定稿审查预检 A 验证记录

- 日期：2026-09-05。
- 基线：`main@cde7f2e79fa180be1596ea87c337460602e1bc9d`。
- 分支：`codex/finalization-preflight`；隔离工作树 `.worktrees/finalization-preflight`。
- 范围：用户批准的 A。B（已确认审查恢复）、真实模型验收、P0-E/F 均不在本次实现范围。

## 行为

新审查在作者确认前验证规划补丁实际能否应用。历史定稿小纲和当前小纲引用的分卷、故事块、阶段、场景任务共用一套保护规则，受保护集合纳入冻结上下文；历史钉住的小纲缺失或损坏时拒绝继续，模型调用后的上下文变化使审查失效。

原始提取结果先通过身份、revision/hash、正文证据及完整 Planning 试算。合法但针对受保护节点的补丁转为可见的非权威建议，保留 ID、目标、证据和完整建议值；建议不会改写规划。转换后再验证，超消息长度或集合容量时整次准备失败。事实、实际进度和合法未来补丁保留。

作者修正和确认复用最终提交的纯 Planning 计算逻辑，错误类型或字段长度在确认前拒绝。旧审查缺少新增冻结依据时，不补写旧 manifest，返回固定的重新审查提示。最终提交仍保留保护。

界面允许在未确认时移除单项规划补丁，必须保存新修订后才能确认；保存失败保留本地草稿。已确认、忙碌和已定稿时禁止移除。未增加已确认审查的取消或恢复入口。

## 验证

| 门禁 | 结果 |
| --- | --- |
| 最小失败测试 | 后端原缺口 9 个失败；未来补丁类型/长度 6 个失败；前端原缺口 5 个失败；Phase 5 测试入口 2 个失败，均先复现后修复 |
| 后端全量 unit/API | 6114 passed，17 skipped，退出码 0 |
| 脚本单元测试 | 457 passed，0 failed |
| 前端全量单元测试 | 1137 passed，0 failed |
| 生产构建 | Vite 8.0.13，3043 modules，退出码 0 |
| Disposable MySQL | 既有仓储 SQL/原子提交 2 项通过；新增 prepare→suggestion→confirm→commit/replay 1 项通过，所有测试库已清理 |
| 正式 Phase 5 浏览器 | 1/1 通过；UI 转建议、删除另一未来补丁、保存 R2、确认、原子定稿；数据库后置条件通过 |
| 独立审查 | 规范初审发现未来补丁未完整试算，修复后复审通过；代码质量审查 Ready；测试入口补充审查 Ready |

主要命令（均在隔离工作树执行）：

```powershell
$env:PYTHON = 'D:/Software/Python/Python312/python.exe'
node scripts/run-tests.mjs unit
npm --prefix frontend run build
python -m pytest backend/tests/integration/test_finalization_repository_mysql.py backend/tests/integration/test_atomic_finalization_mysql.py backend/tests/integration/test_finalization_preflight_mysql.py -q
node scripts/run-tests.mjs browser-phase5
git diff --check
```

MySQL 只向现有隔离测试框架提供 `TEST_MYSQL_*` 服务器配置；库名由框架随机生成并校验。新增集成夹具最初缺少绑定显示快照及使用旧 Provider 类型，已修正为满足现行契约的模拟配置后通过。Phase 5 旧 CLI 最初缺少运行时配置初始化，现按既有 Phase 8A 模式在 CLI 生命周期内安装配置，关闭池后清除；未改变产品服务的配置行为。

正式浏览器报告：测试数据库、进程、端口、临时目录、浏览器产物和 Vite 缓存残留均为 0；真实 Provider 调用 0，产品数据库读写 0/0。

## 集成与现场边界

本次仅在隔离分支本地提交，尚未合并 main 或推送。主目录接管文档及独立推荐提示修复工作树保留。

原 QA 项目已确认 R2 的审查没有恢复；其定稿失败现场、工作稿和候选未修改。不能据本次模拟模型门禁宣称真实内容质量、跨章承接或连续三章验收通过。下一步先确定 A 的本地集成，再单独决定是否批准 B。
