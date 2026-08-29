# Author-facing Planning Status 验收记录

日期：2026-08-29（Asia/Shanghai）
结论：新 HEAD 技术验收通过；Task4 gap spec reviewer 已为 Ready、0 findings；Final full quality review 已为 Approved、0 findings。

## 提交与范围

- Commit under test：`d9b6d873763cf0eae8d279792e09c457a4c27ce2`（`fix: preserve planning progress state precedence`）。
- 生产修复链：`d9ce429`（关闭作者状态验收缺口）、`0156b02`（对齐回归门禁）、`d9b6d87`（保证 Planning progress 的状态优先级，避免读取不应触达的后续状态）。
- 本轮只读访问项目 `474d110f-977c-4c82-bec4-464f30ec5a16`；未调用 Provider，未写入业务数据。
- 首次 Task4 验收在 `dae3e75` 后发现三项缺口：story-blocks 的无障碍属性泄露内部 revision 哨兵、Bible 历史抽屉关闭后未恢复触发按钮焦点、Bible 历史详情宽屏视觉出现横向溢出。`d9ce429` 修复产品行为，`0156b02` 对齐回归门禁；随后 final full quality review 发现 Planning progress state-precedence Important，`d9b6d87` 已修复。本轮在 exact 新 HEAD 上逐项重验通过。

## Fresh 自动化门禁

所有时间均为 UTC+08:00，均在 `D:\Projects\Novel_Creater`、HEAD `d9b6d87` 上重新执行。

| 门禁 | 开始—结束 | 结果 | 工具报告时长 | 墙钟时长 |
| --- | --- | --- | ---: | ---: |
| 5 文件组合：`node --test frontend/tests/unit/actualProgressPresentation.test.mjs frontend/tests/unit/planningWorkspaceSfc.test.mjs frontend/tests/unit/bibleStatusPresentation.test.mjs frontend/tests/unit/bibleWorkspaceController.test.mjs frontend/tests/unit/projectBibleView.test.mjs` | 17:12:59.509—17:13:05.710 | 80/80，通过；0 失败 | 6084.2897 ms | 6195 ms |
| `npm --prefix frontend run test:unit` | 17:13:11.514—17:13:26.200 | 938/938，通过；0 失败 | 14052.0101 ms | 14682 ms |
| `npm --prefix frontend run build` | 17:13:31.800—17:13:33.685 | 退出码 0；Vite 8.0.13；2996 modules | 1.06 s | 1882 ms |

写文档前的 `git diff --check`、`git diff --cached --check`、`git diff --check origin/main...HEAD` 均为退出码 0；工作树当时仅有未跟踪且未触碰的 `.review-worktrees/` 与本验收文档，tracked working diff 与暂存区均为空。新增的 4 个组合/全量测试覆盖 state-precedence 回归。

## 服务所有权与运行时

- 启动前 8000、5173 的 LISTEN 数均为 0；没有复用既有服务。
- 诊断中，计划所写 `.venv-m2` 解释器导入 `multipart` 失败；仓库 `start_backend.bat` 明确配置 `D:\Software\Python\Python312\python.exe`，该解释器可导入 `multipart` 与 `uvicorn`。单一根因判断是验收计划的运行时选择过期，并非产品配置运行时缺失依赖；未安装或修改依赖。
- Backend 使用仓库配置运行时和 `python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`，自有 PTY session `82636`；Frontend 使用 `npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173`，自有 PTY session `25867`。
- `/api/health` 与前端根页面均返回 200，且确认两个 session 仍存活后才进入浏览器验收。
- 浏览器完成后仅向上述两个 exact session 发送 Ctrl+C，并等待退出；清理后 8000、5173 的 LISTEN 数均为 0，未终止未知监听器。

## 浏览器环境与导航

- Playwright CLI headed named session：`afps-20260829-1730`；`npx` 可用；未创建 `@playwright/test` spec。
- CSS viewport `1440 × 900`，`visualViewport.scale === 1`；各关键页面及最终页面均无 document/body 横向溢出。
- 从下列第一个页面起步，随后通过可见页签进入另外两个 Planning 页面，再通过可见侧栏进入 Bible：
  - `/projects/474d110f-977c-4c82-bec4-464f30ec5a16/planning/volumes`
  - `/projects/474d110f-977c-4c82-bec4-464f30ec5a16/planning/plots`
  - `/projects/474d110f-977c-4c82-bec4-464f30ec5a16/planning/story-blocks`
  - `/projects/474d110f-977c-4c82-bec4-464f30ec5a16/bible`
- 所有可见导航均在可访问性 snapshot 后按可见 role/name locator 点击；重大页面变化后重新 snapshot，共 7 次 snapshot。监听器在首次业务导航前安装，并在同一次 headed CLI invocation 中覆盖全部导航与断言。

## 请求与错误 ledger

只记录分类、数量、method 与 status，不记录请求 body、secret 或业务内容。

- 业务 API 请求：11；method 为 `GET: 11`，其他 method 为 0。
- 路径分类各 1 次：health、project、planning、planning history、current chapter outlines、single chapter-outline history、Bible head、Bible draft、binding status、Bible history、single Bible history detail。
- Provider 路径请求：0。
- 外部 origin：0。
- Console error：0；page error：0。
- `status >= 400` 响应：0，状态分类为空。
- Request failure：0。

## Planning 非披露与只读呈现

从已加载的 Planning GET response 中仅在内存提取并比对以下 exact sentinel 类别：canon revision、projection revision、planning revision、target ID、field path、subject key、content hash、raw JSON token。本文及其他持久化日志不记录任何 sentinel 值。

| 页面 | heading / 作者摘要 | 哨兵与内部标题 | 行数 | 面板交互控件 | viewport / overflow |
| --- | --- | --- | ---: | ---: | --- |
| volumes | 均存在 | visible text、accessible names、`id`/`title`/`data-*` 中 0 命中；raw internal heading 0 | 3 | 0 | 1440×900、scale 1、无横向溢出 |
| plots | 均存在 | visible text、accessible names、`id`/`title`/`data-*` 中 0 命中；raw internal heading 0 | 3 | 0 | 1440×900、scale 1、无横向溢出 |
| story-blocks | 均存在 | Canon/Projection/revision 及全部 sentinel 类别在 visible text 与 a11y/结构属性中均 0 命中；raw internal heading 0 | 3 | 0 | 1440×900、scale 1、无横向溢出 |

story-blocks 的固定 ChapterOutline 作者状态存在，且不再把内部 revision 信息暴露给可见文本或无障碍属性。作者自行撰写、即使外观类似技术字符串的文本不作为内部泄露误判。

## Bible current / history / detail

- Current：eyebrow mode 为中文；确认基线提示存在；页面不显示内部 confirmed/raw current/superseded/unknown code。
- History：点击可见“修订历史”按钮并等待 GET；1 个 history row，所有状态均为中文。
- Detail：点击可见“查看详情”并等待 GET；详情存在，省略内部 confirmed reason，unknown fallback 不回显 raw code。
- Basis：12 个 basis 标签与 12 个对应值全部可见；basis hash/ID 明确不在本轮全局禁显范围内。
- 关闭：使用现有关闭按钮关闭 drawer 后，`document.activeElement` 精确恢复为“修订历史”按钮。
- 详情几何：document `1440/1440`、body `1440/1440`、history overlay `1440/1440`、history sheet `445/445`、history detail `389/389`、history basis `389/389`（均为 `clientWidth/scrollWidth`），所有相关容器 `scrollWidth <= clientWidth`。

## 宽屏视觉审核与临时产物

- Runner-owned 临时目录：`D:\Projects\Novel_Creater\output\playwright\author-facing-status-20260829-171631`。
- 在 Planning 作者摘要稳定后生成 `author-summary.png`，在 Bible history detail 稳定后生成 `bible-history-detail.png`。
- 两张 1440×900 截图均已用实际图像查看器审核：Planning 摘要无明显截断、重叠或溢出；Bible 抽屉、详情字段与标签无明显截断、重叠或横向溢出。
- 上述截图及本轮 helper 均标记为“已审核后删除”；三个固定文件逐一删除，确认目录为空后删除该新目录。CLI 本轮产生的 5 个可精确识别 snapshot 文件也已按固定路径逐一删除。清理时间：`2026-08-29T17:27:14.408+08:00`。未批量删除或触碰其他历史 `.playwright-cli` 产物。

## Review 记录

| 阶段 | SHA | Spec verdict | Quality verdict |
| --- | --- | --- | --- |
| Task1 | `fc08b15` | Ready，0 findings | Approved，0 findings |
| Task2 | `38759a1` | Ready，0 findings | Approved，0 findings |
| Task3 | `dae3e75` | Ready，0 findings | Approved，0 findings |
| Task4 gap | `d9b6d87` | Ready，0 findings | gap review 已完成 |
| Final full quality | `d9b6d87` | 不适用 | Approved，0 findings |

## 写入后最终门禁

- HEAD 仍为 `d9b6d873763cf0eae8d279792e09c457a4c27ce2`，分支为 `main`。
- `git diff --check`、`git diff --cached --check`、`git diff --check origin/main...HEAD` 均为退出码 0；验收文档另以 untracked-file 专用检查确认无 whitespace error。
- 暂存区与 tracked working diff 均为空；`git status --short` 仅列出未跟踪且未触碰的 `.review-worktrees/` 与本验收文档。
- 8000、5173 的 LISTEN 数仍均为 0；runner-owned 临时目录不存在。

## 非声明范围

本验收不声明：自动状态转换、完整 Bible 历史覆盖、mobile 或 200% zoom、Contract 404、Provider 行为、生成内容质量。
