# 普通前端入口的 CORS 端口契约补齐

编号：`NC-AUDIT-20261002-2020-CORS-ENTRY`。这是 `f18606e43cd814cc47fd3ffb50b26aa7b681ab48` 收尾后的兼容性补项；开始时 HEAD＝origin/main，工作区干净。没有重复上一轮语义实验或生成章节。

## 原因与最小修复

已安装 Vite 的 dev 默认 5173、preview 默认 4173，未设 strictPort 时占用会尝试下一端口。此前普通 npm／bat 入口没有固定严格端口，后端默认只允许两个 5173 来源，因而 preview 或回退后的 dev 页面能打开但 API 不获跨源读取许可。上一轮配置十九个隔离 runner 并未覆盖这些普通入口。

仅调整 `frontend/vite.config.js`：`server` 和 `preview` 都设为 `port: 5173, strictPort: true`。普通入口现在统一如下：

| 入口 | 来源与行为 |
| --- | --- |
| `npm --prefix frontend run dev`，或 frontend 目录下 `npm run dev` | `http://127.0.0.1:5173` |
| `start_frontend.bat` 的固定 npm／PATH npm 两个分支 | 复用 dev 脚本和同一配置，仍为 `http://127.0.0.1:5173` |
| `npm --prefix frontend run preview`，或 frontend 目录下 `npm run preview` | 使用已有构建，来源改为 `http://127.0.0.1:5173` |
| 端口已占用 | 明确报 `Port 5173 is already in use` 并退出；不静默回退，不结束占用进程 |

dev 与 preview 默认使用同一端口，不能同时启动；需要并行时显式指定另一个端口，并配对后端来源。未修改 npm／bat 启动脚本、后端默认来源、正式配置或既有 runner。

例如，自定义前端端口：

```powershell
npm --prefix frontend run dev -- --port 15273
# 或使用已有构建预览：
npm --prefix frontend run preview -- --port 15273
```

对应的隔离后端控制台须在启动前设置精确来源：

```powershell
$env:CORS_ALLOWED_ORIGINS = 'http://127.0.0.1:15273'
python -m uvicorn backend.main:app --host 127.0.0.1 --port 18100
```

该变量替换默认来源列表，修改后需重启对应后端；若需多个来源，使用明确的逗号分隔列表。自定义端口仍继承 strictPort，不恢复任意端口正则或自动信任 Origin。

## 针对性验收

1. 新增 `scripts/tests/frontendPortContract.test.mjs`，读取实际 npm 脚本及 bat 两个分支参数，用**当前安装的 Vite resolveConfig**核对 dev／preview／bat 最终来源和严格端口，并与后端默认列表对应；另核对显式端口覆盖仍生效。修复前 5 项均失败，保留红测；修复后全部通过。没有监听 5173／4173 重现，也没有直接执行会暂停的完整 bat。
2. 新回归及现有 product-shell／Phase7B 环境契约合计 **67 项通过**。这是相关切片，不是十九个完整数据库／浏览器场景重跑；runner 本身未改，显式端口仍覆盖新默认。
3. 原 CORS 边界专项 **32 项通过**：默认允许来源、显式隔离来源、同源及未配置／外部／伪装／null 来源保持原边界。后端使用 TestClient 和无数据库项目列表服务，没有启动正式库。
4. 使用已安装 Vite CLI、生产配置加仅隔离 cacheDir 的测试覆盖，实际执行受控端口下的 dev／preview，**10 项 HTTP／启动核对通过**：两者占用时均退出码 1、清楚报错、没有尝试后续端口，占用服务保持原样；显式 dev／preview 在自己的端口提供 HTML；preview 返回既有 `dist/index.html`；对应显式来源的 API GET／预检通过；未配置来源 GET 没有允许头、预检 400。

实际 CLI 验证通过 `--port` 使用自有端口 14826、14859—14862；正常入口的默认 5173 来源由真实配置解析验证。没有占用用户常用的 5173、5174、4173、4174、8000、18100 或 15273，没有杀用户进程。HTTP HTML 请求不执行应用 JS；API 使用真实生产 CORS 中间件和项目 GET 路由，项目列表服务隔离且 lifespan 关闭，未访问正式数据库或模型。此为端口／访问边界验证，不是新的页面业务验收。

精确命令：

```text
node --test scripts/tests/frontendPortContract.test.mjs
node --test scripts/tests/frontendPortContract.test.mjs scripts/tests/phase7bBrowserContract.test.mjs scripts/tests/productShellSuite.test.mjs
python -m pytest backend/tests/api/test_cors_boundary.py -q --basetemp=output/cors-entry-20261002-2020/pytest-cors
node output/cors_entry_live_20261002.mjs
```

没有重建前端：生产视图及打包配置未变，沿用已有构建进行 preview 验证，并逐文件核对构建哈希不变。没有全量回归、MySQL／模型／语义实验或新章节操作。

## 保护与收尾

证据保留在 `output/cors-entry-20261002-2020/`：`baseline.json`、`port-contract-red.txt`、`port-contract-final.txt`、`cors-tests.txt`、`live-verification.json`、占用／正常启动日志、`resource-cleanup.json`、`protection-and-cleanup.json`、`git-closeout.json`。

首次记录 baseline 时已经加入本轮回归文件，其 worktree 字段准确反映当时状态；入口修改前的源文件和已有构建哈希保留，开始前干净状态另有首次 Git 核对。已有 npm／bat、后端 CORS、十九个 runner 和整个构建逐项保留。自有 Vite、无数据库 API、端口占用服务均已结束，所用端口无残留监听。保留上一轮全部十五章包和语义失败证据，不改正式小说或模型配置。

保护检查首检因 Windows 路径分隔符未正确排除唯一获准修改的 Vite 配置而失败；差异只有该配置。修正检查器为 Path 对象比较后，其他源文件、runner 和构建文件／清单均保持。首检失败与差异记录保留，未放宽产品校验，也未把检查器失败隐去。

按既有授权正常提交推送 main；准确起止提交、远端一致性及干净工作区见本批 `git-closeout.json`。本补项只关闭普通入口遗漏，不改变上一轮“模型语义仍需人工核对”的结论。
