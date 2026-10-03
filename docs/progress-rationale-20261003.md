# NC-PROGRESS-RATIONALE-20261003：任务状态判断依据展示与作者修正

## 完成范围与必要性

从干净 `b6ba8c207f54ae4cd8646a0092744ecf26a973b3` 开始，HEAD 与 origin/main 相同，未发现相同改动。原页面只展示进度状态、排除操作和 evidence 原文范围，作者无法核对／修正 `StoryProgressEvent.evidence.rationale` 中把“正文未展示执行”写成“世界中未发生”的判断。

现有 frontend `finalizationEvidence` DTO 已保留 rationale；后端 `EvidenceLocation` 要求非空字符串、最多 500 个 Unicode 字符，`FinalizationService.correct` 已校验上下文／摘录／版本，追加 `author_correction` 修订并更新当前版本。因此**产品代码只改 `FinalizationPanel.vue`，无需修改后端服务、接口、持久化模式或模型配置**。另补前端组件／DTO及后端纯内存服务／领域测试，更新本记录和项目状态。

## 界面与保存约定

- 在原故事进度条目中预填“任务状态判断依据”文本框，保留原任务状态、原文片段和排除入口。提示其用于说明本次正文支持的进度，**不是新增世界事实**；正文没有展示某动作表示本次正文不足以确认，不能据此断言世界中没有发生。作者按需修正已有理由，不增加每章必填表或新流程。
- 更新函数仅修改所选 event 的 `evidence.rationale`。id、targetType／targetId、status、startScalar／endScalar／excerptHash／confidence 及其他事实不随理由变化。既有“保存修正 → 读取新版本 → 作者确认”路径和预期版本／hash 不变；后端追加历史，不覆盖原修订。
- 沿用 `editable` 权限，已确认、失效、取消、失败、禁用、正文过期、正在操作、已定稿及恢复待核对时不可编辑。原文定位仍可查看。可访问名称直接传给 Naive UI 的原生 textarea。
- 空白／超过 500 个 Unicode 字符时显示局部错误，保留输入、不截断、不自动修剪；既有未完成字段保护阻止保存／确认。仅展示或输入相同理由不创建修订；已有理由有效时不要求作者另填。
- 保存成功但 GET 失败时复用上一轮恢复保护，理由草稿仍可见，禁止重复写入；“刷新核对修正”读回权威版本。明确拒绝后的同版本读取仍保留本地草稿。没有自动重试、改状态、自动排除或修改证据位置。

## 最终有效验证

各组分别统计，不累计红测／重跑，也不代表模型判断语义已解决：

| 验证 | 最终结果 | 证据边界 |
|---|---|---|
| 前端控制器、面板、DTO、原文证据、事实补录专项 | **92 项通过**，0 失败／跳过 | 实际 Vue 响应式、编译组件、现有 UI／fetch 替身；含上一轮保存恢复邻近回归 |
| 后端 EvidenceLocation 与 finalization service 专项 | **59 项通过** | 现有纯内存 repository／transaction／provider 替身，无数据库／远程模型；理由修订追加历史、新 hash、旧 pin／无关任务／错误摘录拒绝有效 |
| Playwright 隔离浏览器证据核对 | **23 项通过** | 实际面板＋Naive UI＋生产前端 controller／API DTO；服务为本轮回环内存夹具，不是正式后端或数据库 |

```powershell
node --test frontend/tests/unit/finalizationController.test.mjs frontend/tests/unit/finalizationPanel.test.mjs frontend/tests/unit/finalizationApi.test.mjs frontend/tests/unit/finalizationEvidence.test.mjs frontend/tests/unit/addCanonFact.test.mjs
python -m pytest backend/tests/unit/test_finalization_domain.py backend/tests/unit/test_finalization_service.py -q
```

新增测试确认理由显示、仅改理由的完整 payload 对比、保存／读取／确认、无改动、空值与 500 字／500 emoji 边界、超限输入不截断、九类禁用状态、明确保存拒绝后保留、成功保存但重读失败恢复。服务测试确认原 R1 对象未变、R2 为 author_correction、新 hash 不同、旧修订／hash／失效／已确认状态拒绝；错误 excerptHash 与无关 targetId 也不能因只改理由而绕过。

浏览器只在本轮独占回环端口 4001 使用虚构 QA 数据。按页面操作完成预填查看、空白保护、理由编辑、一次保存、故意丢失后续 GET（503）、点击核对恢复、整页重载及一次明确确认；总计 **7 次产品路径请求：5 GET、1 修正 POST、1 确认 POST**。只读 inspect／故障控制是夹具诊断操作，不计为作者操作。保存后的完整 payload 与原值比较仅一处 rationale 不同；确认携带 R2／hash，确认后理由只读；R1 extraction 原历史和 R2 author_correction 均保留。没有定稿、生成或模型端点调用。

最终浏览器初始加载及重载后无意外 console 错误；中途故障注入的单次 503 完整保留。组件画面截图已查看，字段／限制提示／待核对只读显示正常。组件测试的 Vite middleware 在 after 关闭，浏览器会话和本轮 HTTP／HMR 服务也已关闭。

## 原始失败与记录

本机 `output/progress-rationale-20261003` 保留 baseline、专项日志、浏览器精确输入／输出／请求／历史及验证结果；截图／快照在 `output/playwright/progress-rationale-20261003`。不提交原始业务材料或 output 文件。

- 修改前 40 项中新增六个组件测试因理由输入缺失失败，DTO 测试已通过；红测保留。后续 40 项通过不与最终 92 项重复累计。
- 后端首次新增 fixture 遗漏既有 assertionOperator／valueCardinality，第二次使用了不支持的 `set`，均是测试夹具错误；未改契约放行。补齐既有 `equals` 后七个新增服务测试及最终 59 项通过，前两份失败日志保留。
- 首次浏览器夹具关闭 HMR 导致开发 websocket 错误，未计通过；按进程命令行和 owner nonce 核实后，只结束本轮自有 Node 进程，保留原始快照／日志。最终服务将 HMR 绑定同一本轮端口，正常启动／收尾。一次初始 DOM 观测选中了事实 textarea，未用作理由验收证据；一次整页重载后旧 CLI 元素 ref 不再有效，没有提交请求，更新快照后只确认一次。这些操作记录均保留，不隐藏为首轮全部成功。

## 保护与交付边界

前后 SHA256 比较 **1747 个受保护文件未变化**：包括除本轮明确允许修改的七个文件外的已跟踪文件、本地 `.env*`、上轮任务终点／语义候选／保存恢复证据、十／十五章备份包。正式数据库和小说未访问／写入，远程模型请求 0，模型配置未修改；Canon、规划、证据校验、版本／冲突／原子定稿保护、取消恢复与作者裁决实现不变。后端服务测试证明既有受限路径，不声称重新验收真实数据库事务或历史备份往返。

本轮不接入自动第二遍候选，不修旧 Canon／主题字段／跨实体归属，不改模型提示或追加章节。理由仍由作者核对，不自动证明语义正确；未做真实后端／数据库浏览器链路、全量构建／回归或模型质量验收。草稿保留继续限当前挂载页面，未新增强制关闭后的持久化或跨版本合并规则。

仅提交界面、四个专项测试文件及记录／状态。精确提交、远端和工作区核对回执见本机 `closeout.json` 及最终回复。资源已收尾，提交推送后停止，等待独立审核。
