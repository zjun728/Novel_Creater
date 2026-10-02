# NC-PRO-FOLLOWUP-20261003 A：回环来源规范化

本项从 `9c2298ee347cd26821ffe9c84e31be6e4d0cd77a` 的干净 `main` 开始，独立提交。仅改变 `backend/config.py` 的 CORS 配置序列化及专项测试；不改变来源主机集合、认证、客户端协议、正式配置或 Vite 端口契约。用户跨日授权仅替代上一批试验的截止时间。

## 原因与最小修复

原解析接受部分非规范写法，却把原字符串交给精确匹配中间件，导致正常浏览器的序列化 Origin 不匹配。专项测试先复现 **9 失败、48 通过**，失败原始日志保存在 `output/pro-followup-20261003/cors-red.log`。

在校验仍限定 HTTP(S) 的 `localhost`、`127.0.0.1`、`[::1]` 后，主机转小写、端口转十进制、去掉 HTTP 80 / HTTPS 443 默认端口，再去重。额外校验 authority 的完整语法，拒绝尾随字符、非 ASCII 端口、凭据、通配符和其他主机表示；没有扩大回环主机集合。

| 配置 | 实际保存且与 Chromium URL Origin 相同 |
|---|---|
| `http://LOCALHOST:5173` | `http://localhost:5173` |
| `http://localhost:80` | `http://localhost` |
| `https://localhost:443` | `https://localhost` |
| `http://127.0.0.1:05173` | `http://127.0.0.1:5173` |
| `http://[::1]:80` | `http://[::1]` |

默认仍为两个 HTTP 5173 来源；显式设置仍替换默认，空字符串仍禁止跨源，非法设置仍令应用创建失败。Vite dev、preview 和 bat 仍固定 5173 且 `strictPort`，自定义端口仍需配对后端显式来源。

## 最终验证与边界

- **58 项 CORS 专项测试通过**：规范化及去重、IPv6、恶意和未配置来源、GET、POST 的 Authorization＋JSON 预检、同源及非法配置实际导入应用失败。默认检查主动隔离宿主 CORS 环境；最终命令故意带入另一个宿主来源验证这一隔离。
- **19 项隔离 Chromium / HTTP 检查通过**：7 组 URL 序列化，实际前导零端口页面 Origin、JS GET 读取、实际带 Authorization＋JSON 的 POST 及预检、未配置来源 JS 拒绝、拒绝 POST 未到达 echo、同源读与四个拒绝预检。Authorization 是无凭据的测试字符串，echo 只在内存中返回原请求，不接触正式写入接口。
- **5 项已安装 Vite 解析检查通过**：普通 dev / preview、bat 两分支和显式端口，保持允许来源及 `strictPort`。没有重新占用常用端口测试或重跑上批已保存的受控占用检查。
- **3 项环境传播检查通过**，并静态核对 19 个 runner：共享和 shell 两个实际白名单不允许宿主 CORS 值进入 base；phase3 在完整 environment 后设置 `viteUrl`；phase7b 实际最终表达式也最后覆盖；其他后续 spread 的 mysql / database / provider fixture 无 CORS 属性。不能仅因来源字段前置就报错，故未修改 runner，也未运行 19 套完整验收。静态入口及源文件哈希见 `runner-origin-static.json`。

证据目录：`output/pro-followup-20261003/`；截图：`output/playwright/pro-followup-20261003/same-origin.png`。浏览器和隔离服务均使用本轮自有临时端口，生命周期关闭；后端数据库／模型 lifespan 关闭，projects 列表服务替换为不访问数据库的读取，正式数据库与模型没有被 A 调用。

首次浏览器脚本读取自有 ledger 时，被生产 SPA GET catch-all 抢先匹配，出现 `TypeError: ledger.some is not a function`。只调整隔离脚本自有路由的注册顺序，保留首版脚本、失败日志及关闭回执；没有调整产品路由。此前只读核对还有一次旧字段名 `chapterSummary` 的 `KeyError`，实际字段为 `summary`，及不存在文件／Windows glob 路径的读取错误；均未触发业务或模型调用，不作为产品缺陷。

本项不证明 CORS 是认证、不保证本机进程隔离，也没有部署 TLS 或绑定默认 80／443／IPv6 监听来验证网络服务；这些来源的浏览器序列化与中间件许可由参数化测试和 Chromium `URL.origin` 共同验证。
