# Vite 测试缓存隔离设计

## 1. 问题与证据

前端单元测试会在各 Git worktree 的 `frontend/node_modules/.vite` 下遗留大量
`deps_temp_*` 目录。已确认：

- `projectBibleView.test.mjs` 有 10 处 Vite `createServer` 调用；
- 这 10 处调用未关闭依赖自动发现；
- 每次完整测试恰好新增 10 个 `deps_temp_*` 目录；
- 其他已检查的 Vite 单元测试服务器均设置了
  `optimizeDeps: { noDiscovery: true }`。

因此，本次修复针对的是测试基础设施中的单一遗漏，不涉及产品运行时缓存、
业务数据或数据库。

## 2. 目标

统一 `projectBibleView` 测试中的 Vite SSR 服务器创建方式，并强制关闭依赖自动
发现，使测试运行后不再产生可累积的 `deps_temp_*` 临时目录。

验收以可观察结果为准：

1. `projectBibleView` 单元测试连续运行两轮均通过；
2. 每轮运行后新增的 `deps_temp_*` 目录数量均为 0；
3. 前端单元测试保持通过；
4. 不依赖测试结束后的全局缓存清理来掩盖泄漏。

## 3. 设计

### 3.1 单一测试服务器入口

为 `projectBibleView` 测试建立一个统一的 Vite SSR 测试服务器辅助入口，替换
现有 10 处直接 `createServer` 调用。

该入口固定设置：

- `configFile: false`；
- `server.middlewareMode: true`；
- `server.hmr: false`；
- `server.ws: false`；
- `appType: "custom"`；
- `logLevel: "error"`；
- 现有 Vue 插件与路径别名；
- `optimizeDeps: { noDiscovery: true }`。

调用方只传入测试确实需要变化的参数，不能意外重新开启依赖自动发现。

### 3.2 保持现有生命周期

服务器关闭方式和现有 `try/finally` 语义保持不变。修复不引入后台常驻进程，
也不增加对共享 `.vite` 目录的删除逻辑。

### 3.3 持久回归保护

增加一个小范围、可执行的测试合同，证明：

- `projectBibleView` 的 Vite 测试服务器都经过统一入口创建；
- 统一入口生成的配置包含 `optimizeDeps.noDiscovery === true`。

回归保护只覆盖本次根因，不建立针对整个仓库源码的大范围正则清单。

## 4. TDD 与验证

实施时先建立 RED 证据：

1. 确认测试缓存基线为空；
2. 运行 `projectBibleView.test.mjs`；
3. 证明当前实现会新增 10 个 `deps_temp_*` 目录。

随后实现统一入口并进入 GREEN：

1. 清理本次测试拥有的缓存基线；
2. 连续两次运行 `projectBibleView.test.mjs`；
3. 每次核对新增 `deps_temp_*` 为 0；
4. 运行新增的回归合同；
5. 运行完整前端单元测试；
6. 执行 `git diff --check`。

若仍出现缓存残留，验证应明确失败并保留证据，不自动清扫其他测试或 worktree
的目录。

## 5. 边界与非目标

本次仅修改 `projectBibleView` 测试基础设施及其回归测试：

- 不修改生产 Vite 配置；
- 不修改产品 UI、API、Store、数据库或生成链路；
- 不升级 Vite；
- 不重构其余 13 个相关测试文件；
- 不增加通用缓存清理器；
- 不删除源码、历史证据或用户文件。

如后续发现其他测试入口也产生同类残留，应以新的可复现证据单独处理，而不是
扩大本次修复范围。
