# Novel Creator 真实流程长篇测试报告

- 时间：2026-06-10T06:29:27.210Z - 2026-06-10T06:33:39.521Z
- 项目：写作标准验收200万_20260610062933
- 项目地址：http://127.0.0.1:5173/project/389e6bbd-ebbd-4c97-9792-a2d138258b03
- 目标规模：2000000 字 / 400 章
- 使用模型：联通云-kimi-k2.6 / kimi-k2.6 / sk-sp-...VS1o
- 检查：5/6 通过
- 浏览器控制台错误：0
- 项目处理：null

## 生成与数据量
- 热点数据：102
- 方向建议：0
- 种子：0
- 初始设定候选：0
- 已确认设定：0
- 章节骨架：0
- 已定稿章节：0
- 记忆事实：0
- 章节设定变更：0
- 纠偏任务：0
- 章节字数：
- 审稿结构化失败：0

## 多章一致性验收
- 尚未执行

## 检查项
- [x] 后端服务已由脚本启动
- [x] 前端服务已由脚本启动
- [x] 模型配置已读取：联通云-kimi-k2.6 / kimi-k2.6 / sk-sp-...VS1o
- [x] 已新建 200 万字规模项目：写作标准验收200万_20260610062933 / 400 章
- [x] 选题雷达有热点数据：items=102
- [ ] 真实流程测试执行失败：TimeoutError: The operation was aborted due to timeout
    at node:internal/deps/undici/undici:16416:13
    at process.processTicksAndRejections (node:internal/process/task_queues:103:5)
    at async chat (file:///D:/Projects/Novel_Creater/tmp/run_realistic_longform_flow.mjs:269:19)
    at async chatJson (file:///D:/Projects/Novel_Creater/tmp/run_realistic_longform_flow.mjs:301:17)
    at async runMarketAndSeed (file:///D:/Projects/Novel_Creater/tmp/run_realistic_longform_flow.mjs:739:27)
    at async main (file:///D:/Projects/Novel_Creater/tmp/run_realistic_longform_flow.mjs:2431:24)

## 主要观察
- LLM 请求失败，第 1/3 次后重试：LLM 429: Concurrency limit exceeded
- LLM 请求失败，第 2/3 次后重试：LLM 429: Concurrency limit exceeded

## 页面耗时

## 截图

## 浏览器控制台错误
- 无