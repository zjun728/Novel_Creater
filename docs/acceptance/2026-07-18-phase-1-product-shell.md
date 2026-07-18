# Phase 1 产品壳层与项目生命周期验收

- 日期：`2026-07-18`
- 分支：`codex/product-shell-lifecycle`
- 验收代码快照：`dd40cf2e452243c6c8085fd486a3831b6e059796`
- 阶段：Phase 1
- 证据边界：No-Provider、Disposable MySQL 8、真实浏览器

## 1. 验收结论

Phase 1 通过发布门禁。正式产品壳层和项目生命周期可以通过真实 Vue 页面、FastAPI
和 disposable MySQL 8 完成。

本结论不表示完整产品重构、完整写作闭环、正式产品数据库、真实 Provider 或小说内容质量
已经验收。Phase 2–7 仍未完成。

## 2. 代码与 Schema

- 验收提交：`dd40cf2e452243c6c8085fd486a3831b6e059796`
- Schema version：`writer-core-v1.2.0`
- Manifest：
  `6164f0f57d3acd59dcab054549d634a4138b82a18962f145140fd56f0244ab4b`
- 测试数据库命名契约：`^novel_creator_test_[a-f0-9]{32}$`
- Provider/model calls：`0`
- Product DB reads/writes：`0/0`

测试前只输出四项 `TEST_MYSQL_*` 变量是否存在，结果均为 `True`；未输出任何变量值。

## 3. 发布门禁

| 命令 | Exit | 结果 |
| --- | ---: | --- |
| `npm test` | 0 | Python `1398 passed, 3 skipped`；scripts `185 passed`；frontend `184 passed` |
| `npm run test:integration` | 0 | `154 passed`；`created=153`、`cleaned=153`、`remaining=0` |
| `npm run test:browser:product-shell` | 0 | 真实浏览器生命周期用例通过 |
| `npm --prefix frontend run build` | 0 | `2855 modules transformed` |
| `git diff --check` | 0 | 无 whitespace error |

集成和浏览器测试没有连接产品数据库。每个浏览器场景获得新的随机测试库；runner 只启动、
观察和清理自己拥有的后端、Vite、进程树、动态端口和测试库。

## 4. 真实浏览器行为证据

### 项目生命周期

真实页面完成并核验：

1. 打开 `/projects`；
2. 新建项目，表单只有“项目名称”；
3. 普通 Enter 只发出一次创建请求；
4. 点击卡片空白区域不导航；
5. “打开项目”进入 canonical overview URL；
6. 刷新后恢复项目标题、上下文和面包屑；
7. 重命名后活动项目页展示服务端返回标题；
8. 归档不弹 Dialog，并显示带“撤销”的 Toast；
9. 撤销后项目回到活动列表；
10. 再次归档后在已归档页恢复，返回活动 overview；
11. 已归档页绑定并提交当前 `lifecycle_revision`；
12. 永久删除第一次取消不发 DELETE；
13. 第二次确认只发一个 DELETE，请求在途时 Dialog 不可 Escape、关闭或重复提交；
14. 删除后 canonical overview 呈现项目不存在页面；
15. 注入一次确定性 500 后呈现可恢复错误和“重试”。

写操作按 HTTP method、path、status 和 count 精确白名单核验。除场景显式注入的
404/500 外，page error、console error 和 request failure 必须为空；未放宽
`requestFailures === []`。

### 对话框、键盘与焦点

- 打开 teleported 名称 Dialog 后，应用 shell 为 inert，唯一输入框获得焦点。
- composition Enter 与 legacy IME key code `229` 均不提交、不破坏输入法组合。
- 真实 Tab/Shift+Tab 只在输入、取消、提交之间循环，不能进入 inert shell。
- Escape 关闭后，焦点回到原“新建项目”触发器。
- 永久删除确认处于 pending 时，两个动作都禁用且只保留一个请求。

### 全局操作遮罩

- 阻断操作开始后，只有 shell inert；overlay 是可聚焦的 sibling 并获得焦点。
- 键盘导航、`router.push()` 和浏览器 Back 都保持当前路由。
- 结束同一个 operation token 后恢复先前焦点，并恢复三种导航。
- notice 与两个 blocker 重叠、乱序结束时，最新 blocker 在自己的 token 结束前始终有效；
  blocker 清空后再显示最新 notice。

## 5. 数据一致性与删除边界

- 项目写作状态与 `archived_at` 分离。
- archive、restore、permanent delete 使用 `lifecycle_revision` CAS。
- 归档项目在后端写服务统一被拒绝，不能依赖前端按钮状态保护。
- 项目私有实体使用项目域复合外键和级联所有权；跨项目来源使用 `SET NULL`；
  Provider、风格、经验卡和语料等共享资产不随项目删除。
- 永久删除活动、忙碌、缺失或 revision 过期项目均返回稳定领域错误。
- 并发锁顺序和相同 revision 双操作由真实 MySQL 事务测试覆盖。

## 6. 路由与旧实现清单

- 生产实现中的旧字面路由 `/project/...`：`0`
- 生产实现中的旧字面路由 `/writer/...`：`0`
- `deleteProject`：`0`
- `projects.delete`：`0`
- `ProjectService.delete`：`0`

文本搜索仍会命中 `@/components/writer/...` 组件导入；它是源码目录，不是 URL 路由，
不计入退役路由。

## 7. 明文秘密边界

- Provider 列表、创建、更新响应统一通过 `provider_public`。
- 公共结果不含 `apiKey`、`api_key`、`baseURL` 或 `base_url`。
- 只返回 `hasKey` 和 `hasBaseURL` 等布尔配置状态。
- 序列化器会删除嵌套同义秘密字段，并用当前行的实际秘密值扫描其余字符串。
- 浏览器证据对响应、页面文本、console、page error、request failure 和运行日志执行
  环境敏感值扫描；任一命中都会使验收失败。

## 8. 未触碰的外部状态

- 未调用任何 Provider 或模型。
- 未启动、读取、写入或重建产品数据库。
- 未清理其他 worktree、历史证据或用户已有服务。
- 未打印或写入数据库密码、API Key、Base URL、DSN 或 Authorization。

源码 Schema 已升级至 v1.2，但这不等于产品数据库已经升级。产品服务下一次按 v1.2
正式启动前，需要单独明确批准开发数据库重建；正常应用启动不得自动执行 DDL。

## 9. 已知后续范围

- Phase 2：Creative Assets、Provider/模型默认规则、市场来源、种子、契约、圣经。
- Phase 3：分卷、情节、故事块、小纲和规划/事实分层。
- Phase 4：WorkingDraft Integrity、自动暂存、只读流式模式、改写/扩写/压缩、
  候选、对比和融合。
- Phase 5：质量审核、单次 ChangeSet 提取、Canon 冲突、整体确认、原子定稿。
- Phase 6：小说下载、安全备份、预检和导入。
- Phase 7：产品数据库、真实 Provider、自由浏览器探索和《典镇山河》前 30 章人工验收。

既有 `ChapterWriterView` 仍是临时最小路径。它没有获得完整写作闭环或内容质量 Ready。
