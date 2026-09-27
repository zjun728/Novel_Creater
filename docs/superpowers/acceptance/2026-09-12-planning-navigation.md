# 2026-09-12 规划分区切换修复

用户实测恢复项目986f7ca9-f0f1-53b1-bc4e-d7a136dc021d发现分卷/情节线/故事块切换不改变内容。真实浏览器复现：URL已切换，active、无draft、有futurePlan状态下编辑器数量为0。根因为empty-draft与workspace-sheet使用v-if/v-else-if，建立草稿提示阻止已确认内容渲染；大段共用进度又占满首屏。

仅调整PlanningWorkspace.vue展示：已确认内容独立渲染，保留无草稿只读与建立修订工作稿入口；标题对应分区；实际正文进度改为可展开；已确认摘要不再提示工作稿不完整。没有修改路由、store、版本/数据结构或生成逻辑。

补充active/no-draft/futurePlan三分区真实SFC回归。相关42项通过，构建通过。真实浏览器侧栏3入口与页内3标签均显示对应内容，刷新和进度展开通过。1440×900截图planning-nav-fixed-1440.png，1920×1080截图planning-nav-fixed-1920.png均已查看。验证期间刷新后项目出现D1（本次自动化没有点击创建或任何业务写入）；保留共享项目状态，后截图展示已有草稿分区。测试有既有测试桩警告，但退出0且42项全过；初次新增测试错误假设故事块CSS类与其他编辑器相同，修正为具体分区标题断言后通过。

证据：output/planning-nav-tests.log、output/planning-nav-build.log、output/playwright/planning-nav-fixed-1440.png、output/playwright/planning-nav-fixed-1920.png。服务保留供用户查看。默认生成质量修复仍待实施。
