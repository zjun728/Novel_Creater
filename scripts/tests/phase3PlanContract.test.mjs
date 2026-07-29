import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const readProjectFile = (path) =>
  readFile(new URL(`../../${path}`, import.meta.url), 'utf8');

const phase3bPlan =
  'docs/superpowers/plans/2026-07-24-phase-3b-volumes-and-plots.md';
const phase3cPlan =
  'docs/superpowers/plans/2026-07-26-phase-3c-story-blocks-and-outlines.md';

const readSection = (document, heading) => {
  const marker = `## ${heading}`;
  const start = document.indexOf(marker);
  assert.notEqual(start, -1, `missing section: ${marker}`);
  const next = document.indexOf('\n## ', start + marker.length);
  return document.slice(start, next === -1 ? document.length : next);
};

const readTask = (document, heading) => {
  const marker = `### ${heading}`;
  const start = document.indexOf(marker);
  assert.notEqual(start, -1, `missing task: ${marker}`);
  const next = document.indexOf('\n### ', start + marker.length);
  return document.slice(start, next === -1 ? document.length : next);
};

const assertHasLine = (document, expected) => {
  assert.ok(
    document.split(/\r?\n/).includes(expected),
    `missing exact line: ${expected}`,
  );
};

const normalizeWhitespace = (document) => document.replace(/\s+/g, ' ').trim();

const normalizePhase3cMarkdown = (document) =>
  document
    .replace(/\r\n?/g, '\n')
    .split('\n')
    .map((line) => line.replace(/[ \t]+$/g, ''))
    .join('\n')
    .replace(/\n+$/, '');

const phase3cAcceptanceSections = [
  '元数据',
  '验收结论',
  '已交付链路',
  '独立审查',
  'Fresh 最终门禁',
  '隔离与未评估边界',
  '下一步',
];

const phase3cAcceptanceTitle =
  '# Phase 3C Story Blocks and Chapter Outlines 验收报告';

const phase3cAcceptanceMetadata = `## 元数据

- 验收日期：\`2026-07-30\`
- 基线：\`main@59d80d739ef39a09bcd54e1888e4e4da90a98fa3\`
- 交付分支：\`codex/phase3c-story-blocks-outlines\`
- Fresh package gates 的功能代码 HEAD：\`056520c1f270fdf8f3888be2713647fff03bf2b8\`
- 源码 Schema：\`writer-core-v1.5.0\`；Phase 3C 无 Schema 变更、migration 或 compatibility。
- acceptance commit 不反向改写自身 SHA。`;

const phase3cAcceptanceConclusion = `## 验收结论

Phase 3C 的 Story Blocks and Chapter Outlines 交付范围通过自动门禁。作者可以在
正式 UI 中完成 Planning 故事块层级，手工或显式使用 AI 准备下一权威章节的小纲，
确认后进入唯一且正确钉住的 ChapterSession。

- Planning 权威保持唯一 \`planning-v1\` 聚合与唯一 \`planningStore\`；第三个 Planning tab 交付 StoryBlock/Stage/SceneTask。
- Planning 不含 target chapter count、completed 或 manual actual progress 字段。
- Outline 支持手工 Draft、save CAS、confirm、history 与 fake 外部边界 AI；AI 不确认 Outline，也不创建 ChapterSession。
- authority drift 会 supersede 迟到结果；权威 chapter 算法决定当前章节；每项目最多一个 drafting Session。
- 已存在 Session 保留旧 Planning/Outline pins，并支持幂等重放。
- Overview、Outline、Session 与 Writer 只使用 backend \`targetPath\` 和权威 chapter；Writer 只读 Outline 摘要并从空 WorkingDraft 进入。

本报告只授予上述 Phase 3C 自动验收，不把门禁外推为 Phase 3 总验收、内容质量、
真实模型、产品数据库、正式正文写作或产品 Ready。`;

const phase3cAcceptanceDelivery = `## 已交付链路

### 唯一 Planning 聚合

\`\`\`text
ProjectPlanningView
-> PlanningWorkspace third tab
-> one planningStore
-> canonical planning-v1 aggregate
-> StoryBlock / Stage / SceneTask
\`\`\`

StoryBlock、Stage 与 SceneTask 使用现有 Planning Draft/Revision/Head 和稳定身份。
它们不绑定目标章节数，不把 \`completed\` 或作者手工实际进度写入未来计划。

### ChapterOutline

\`\`\`text
manual Draft or explicit AI request
-> save CAS
-> confirm
-> immutable history
-> current confirmed Outline
\`\`\`

手工路径在模型未就绪时仍可工作。AI 路径只在作者明确请求后越过 production
gateway 边界；自动验收在该外部边界使用严格 fake。AI 结果只装入精确 Draft，
不会自动确认 Outline 或创建 ChapterSession；上游 authority 漂移时迟到 operation
保留为 superseded 证据而不覆盖作者内容。

### 权威章节与可靠写作入口

若项目已有 active drafting Session，权威章节就是该 Session 的章节；否则若有
最大 final 章节，权威章节为其加一；否则为第一章。每个项目最多存在一个 drafting
Session。匹配同一 authority 的请求幂等返回既有 Session，且既有 Session 保留创建
时的旧 Planning/Outline pins。

Overview、Outline、Session 与 Writer 不在浏览器计算下一章节；它们使用后端返回的
\`targetPath\` 和权威章节。Writer 只读展示当前 Outline 摘要，并从空 WorkingDraft
进入；这不是正式三栏写作 UX 或正文生成。`;

const phase3cAcceptanceReview = `## 独立审查

- 交付代码顺序规格审查最终：\`Critical 0 / Important 0 / Minor 0\`
- 交付代码顺序质量审查最终：\`Critical 0 / Important 0 / Minor 0\`
- M1 follow-up 最终：\`Critical 0 / Important 0 / Minor 0\`
- pinned-session follow-up 最终：\`Critical 0 / Important 0 / Minor 0\`
- Task 12 验收文档与事实合同规格审查最终：\`C/I/M 0/0/0\`
- Task 12 验收文档与事实合同质量审查最终：\`C/I/M 0/0/0\`

Task 12 规格/质量审查只覆盖本次五文件 Task 12 包，不外推为任何未评估产品能力
Ready。`;

const phase3cAcceptanceFreshEvidence = `## Fresh 最终门禁

Focused gates 和第三次从头 final 五门禁均为本交付代码 HEAD 的 fresh 证据。
五门禁严格串行执行，前一项成功后才开始后一项。

### Focused gates

- Focused Python：exit \`0\`；\`250 passed, 0 skipped, 0 failed\`；\`71.10s\`。
- Focused Python Disposable MySQL：\`created=24, cleaned=24, remaining=0\`。
- Focused Node：exit \`0\`；\`144/144 passed, 0 failed, 0 skipped\`；duration \`1990.3702ms\`。

### \`npm run test:browser:phase3c\`

- 命令：\`npm run test:browser:phase3c\`；exit \`0\`。
- UI-only scenarios：\`7 passed, 0 failed, 0 skipped\`。
- 场景：\`manual / gateway / supersession / archived / missing-upstream / canon-mismatch / wrong-chapter\`。
- Browser Disposable MySQL aggregate：\`created=7, cleaned=7, remaining=0\`。
- 每场 owned process / port / temp / cache：\`0/0/0/0\`。
- Browser HTTP：\`allowed=37029, forbidden=0\`。
- deny proxy：\`HTTP=0, CONNECT=0\`。
- Browser Real Provider calls：\`0\`。
- Browser Product DB reads/writes：\`0/0\`。
- Browser live website access：\`0\`。
- UI bypass 禁令命中：\`0\`。
- Browser secret scan findings：\`0\`。

### \`npm test\`

- 命令：\`npm test\`；exit \`0\`。
- Python：\`2814 passed, 6 skipped, 0 failed\`；\`46.06s\`。
- root Node：\`243/243 passed, 0 failed, 0 skipped\`；duration \`5013.793ms\`。
- frontend Node：\`522/522 passed, 0 failed, 0 skipped\`；duration \`11141.5774ms\`。

### \`npm run test:integration\`

- 命令：\`npm run test:integration\`；exit \`0\`。
- integration：\`342 passed, 0 failed, 0 skipped\`；\`1015.78s\`。
- Integration Disposable MySQL：\`created=341, cleaned=341, remaining=0\`。
- 独立 \`information_schema\` residual：\`0\`。

### \`npm run build\`

- 命令：\`npm run build\`；exit \`0\`。
- Vite \`8.1.5\`：\`2956 modules transformed\`；built in \`982ms\`。

### \`git diff --check\`

- 命令：\`git diff --check\`；exit \`0\`；whitespace errors \`0\`。

### 最终清理

- 最终独立 cleanup：owned process \`0\`、port \`0\`、Phase 3C temp roots \`0\`、Vite \`deps_temp\` \`0\`、test DB \`0\`。`;

const phase3cAcceptanceIsolation = `## 隔离与未评估边界

- 自动验收未调用真实 Provider、产品数据库或 live 网站。
- API、log、report 与 artifact 不含明文 key、Authorization、password/DSN、prompt、manifest、raw provider output 或 corpus text。
- Phase 3D：Future Plan/Actual Progress/Canon Projection 同 revision 只读组合及 Phase 3 总验收。
- 正式三栏写作 UX、streamed 正文生成、candidate comparison/fusion、AI 味/冲突审核、Canon extraction/finalization、Real Provider readiness、Product DB readiness、novel-content quality acceptance 均未评估。
- 自动验收不构成内容质量或产品 Ready。`;

const phase3cAcceptanceNextStep = `## 下一步

唯一下一步是 **Phase 3D Future Plan / Actual Progress / Canon Projection**：完成同 revision 只读组合与 Phase 3 总验收。`;

const phase3cAcceptanceDocument = [
  phase3cAcceptanceTitle,
  phase3cAcceptanceMetadata,
  phase3cAcceptanceConclusion,
  phase3cAcceptanceDelivery,
  phase3cAcceptanceReview,
  phase3cAcceptanceFreshEvidence,
  phase3cAcceptanceIsolation,
  phase3cAcceptanceNextStep,
].join('\n\n');

const assertPhase3cAcceptanceContract = (acceptance) => {
  const actualSections = Array.from(
    acceptance.matchAll(/^## (.+)$/gm),
    ([, heading]) => heading.trimEnd(),
  );
  assert.deepEqual(
    actualSections,
    phase3cAcceptanceSections,
    'acceptance must contain exactly the seven canonical H2 sections in order',
  );

  const metadata = readSection(acceptance, '元数据');
  const conclusion = readSection(acceptance, '验收结论');
  const delivery = readSection(acceptance, '已交付链路');
  const review = readSection(acceptance, '独立审查');
  const freshEvidence = readSection(acceptance, 'Fresh 最终门禁');
  const isolation = readSection(acceptance, '隔离与未评估边界');
  const nextStep = readSection(acceptance, '下一步');

  assert.equal(
    normalizePhase3cMarkdown(metadata),
    normalizePhase3cMarkdown(phase3cAcceptanceMetadata),
    'metadata must match the exact canonical section',
  );
  assert.equal(
    normalizePhase3cMarkdown(conclusion),
    normalizePhase3cMarkdown(phase3cAcceptanceConclusion),
    'the conclusion must remain the exact Phase 3C grant and disclaimer',
  );

  assert.equal(
    normalizePhase3cMarkdown(delivery),
    normalizePhase3cMarkdown(phase3cAcceptanceDelivery),
    'delivery must match the exact canonical section',
  );
  assert.equal(
    normalizePhase3cMarkdown(review),
    normalizePhase3cMarkdown(phase3cAcceptanceReview),
    'independent review must contain exactly six review facts and the five-file non-extrapolation boundary',
  );
  assert.equal(
    normalizePhase3cMarkdown(freshEvidence),
    normalizePhase3cMarkdown(phase3cAcceptanceFreshEvidence),
    'Fresh final gates must match the exact canonical section',
  );
  assert.equal(
    normalizePhase3cMarkdown(isolation),
    normalizePhase3cMarkdown(phase3cAcceptanceIsolation),
    'isolation must contain only the exact no-call, no-secret, and unassessed boundaries',
  );
  assert.equal(
    normalizePhase3cMarkdown(nextStep),
    normalizePhase3cMarkdown(phase3cAcceptanceNextStep),
    'Phase 3D must remain the only next step',
  );
  assert.equal(
    normalizePhase3cMarkdown(acceptance),
    normalizePhase3cMarkdown(phase3cAcceptanceDocument),
    'acceptance must contain only the canonical H1 and seven canonical sections',
  );
};

const assertPhase3cPlanContract = (plan) => {
  const frozenDecisions = readSection(plan, 'Frozen decisions');
  const fileMap = readSection(plan, 'File map');
  const browserGate = readTask(
    plan,
    'Task 11: Add the formal Phase 3C browser gate',
  );

  for (const [sectionName, section, phrases] of [
    [
      'Frozen decisions',
      frozenDecisions,
      [
        'codex/phase3c-story-blocks-outlines',
        'no schema change',
        'StoryBlock',
        'authoritative chapter',
      ],
    ],
    ['File map', fileMap, ['chapterOutlineController']],
    [
      'Task 11: Add the formal Phase 3C browser gate',
      browserGate,
      ['npm run test:browser:phase3c'],
    ],
  ]) {
    const normalizedSection = normalizeWhitespace(section).toLowerCase();

    for (const phrase of phrases) {
      assert.ok(
        normalizedSection.includes(phrase.toLowerCase()),
        `${sectionName} must include: ${phrase}`,
      );
    }
  }
};

test('Phase 3B detailed plan freezes its delivery and safety contract', async () => {
  const plan = await readProjectFile(phase3bPlan);
  const frozenDecisions = readSection(plan, 'Frozen decisions');
  const task1 = readTask(plan, 'Task 1: Freeze the Phase 3B Contract');
  const task3 = readTask(
    plan,
    'Task 3: Add Attempt, Lease, and Fencing Persistence',
  );
  const task9 = readTask(plan, 'Task 9: Add the Formal Phase 3B Browser Gate');

  assertHasLine(
    frozenDecisions,
    '- Delivery branch: `codex/phase3b-volumes-plots`.',
  );
  assertHasLine(
    frozenDecisions,
    '- Phase 3A already owns the final `planning-v1` aggregate and v1.5 tables. Phase 3B makes no schema change and adds no migration or compatibility path.',
  );
  assertHasLine(
    task3,
    '- [ ] **Step 3: Implement against `planning_generation_attempts`**',
  );
  assertHasLine(
    frozenDecisions,
    '- Short-lived Vite test servers keep optimizeDeps.noDiscovery enabled, and package gates require the final deps_temp_* residue count to equal zero.',
  );
  assertHasLine(task9, 'npm run test:browser:phase3b');

  assertHasLine(
    frozenDecisions,
    '- The two routes use one `planningStore` and one `PlanningWorkspace.vue`; no `planningV2Store`, `volumeStore`, `plotStore`, `PlanningWorkspaceV2`, compatibility alias, or archived duplicate component is allowed.',
  );
  assertHasLine(
    frozenDecisions,
    '- AI generation never confirms a Planning revision, writes Canon, opens a ChapterSession, or calls a real Provider during automated acceptance.',
  );
  assertHasLine(
    frozenDecisions,
    '- Clicking “AI 生成规划” is the author’s explicit authorization to load the result into that exact saved Draft snapshot. If the Draft, project lifecycle, basis, head, binding, or fencing token changes before publish, the attempt is retained as succeeded/superseded evidence and does not change the Draft. There is no second “load result” API or button.',
  );
  assert.ok(
    normalizeWhitespace(task1).includes(
      'The contract must also reject `planningV2Store`, `PlanningWorkspaceV2`, `volumeStore`, `plotStore`, a real Provider, product database use, and a separate result-load endpoint.',
    ),
    'Task 1 must explicitly reject the forbidden implementation alternatives',
  );
});

test('Phase 3C completion facts are current and Phase 3D is the only next step', async () => {
  const [
    currentState,
    productPlan,
    developmentLog,
    storyQualityCharter,
    phase3aAcceptance,
    phase3bAcceptance,
    phase3cAcceptance,
  ] = await Promise.all([
    readProjectFile('CURRENT_PROJECT_STATE.md'),
    readProjectFile('PRODUCT_DEVELOPMENT_PLAN.md'),
    readProjectFile('DEVELOPMENT_LOG.md'),
    readProjectFile('STORY_QUALITY_CHARTER.md'),
    readProjectFile(
      'docs/acceptance/2026-07-24-phase-3a-planning-aggregate.md',
    ),
    readProjectFile(
      'docs/acceptance/2026-07-24-phase-3b-volumes-plots.md',
    ),
    readProjectFile(
      'docs/acceptance/2026-07-26-phase-3c-story-blocks-outlines.md',
    ),
  ]);

  const currentConclusion = readSection(currentState, '当前结论');
  assert.match(currentConclusion, /^- Canonical release branch：`main`。$/m);
  assert.match(
    currentConclusion,
    /^- Phase 2 验收链已进入 `main`，链末提交：\r?\n  `f11faad531f04250f2a987390a468dfd14bf06a3`。$/m,
  );
  assert.match(
    currentConclusion,
    /^- 当前完成交付包：\*\*Phase 3C Story Blocks and Chapter Outlines\*\*。$/m,
  );
  assert.match(
    currentConclusion,
    /^- 当前开发分支：`codex\/phase3c-story-blocks-outlines`。$/m,
  );
  assert.match(
    currentConclusion,
    /^- Phase 3C 交付基线：`main@59d80d739ef39a09bcd54e1888e4e4da90a98fa3`。$/m,
  );
  assert.match(
    currentConclusion,
    /^- Fresh package gates 的功能代码 HEAD：`056520c1f270fdf8f3888be2713647fff03bf2b8`。$/m,
  );
  assert.match(
    currentConclusion,
    /^- 当前自动证据边界：Real Provider calls `0`、严格 fake gateway、\r?\n  Disposable MySQL 8、UI-only 真实浏览器。$/m,
  );
  assert.match(
    currentConclusion,
    /^- Phase 3D、Product DB、Real Provider、正式 Writer Loop、Finalization 和\r?\n  Content Quality 均未评估，不得据 Phase 3C 门禁宣告 Ready。$/m,
  );

  const nextStep = readSection(currentState, '唯一下一步');
  assert.match(
    nextStep,
    /^建设并验收 \*\*Phase 3D Future Plan \/ Actual Progress \/ Canon Projection\*\*：在同一\r?\nPlanning revision 上只读组合 Future Plan、Actual Progress 与 Canon Projection，\r?\n并完成 Phase 3 总验收。继续复用当前 `planning-v1` 聚合、唯一 `planningStore`\r?\n和正式产品链；自动门禁继续禁止真实 Provider、产品数据库和 live 网站。$/m,
  );

  const schemaBoundary = readSection(currentState, '当前 Schema 与数据库边界');
  assert.match(
    schemaBoundary,
    /^- 当前开发分支 committed 源码 Schema：`writer-core-v1\.5\.0`。$/m,
  );
  assert.match(
    schemaBoundary,
    /^- 产品数据库现存 Schema 未读取、未重建、未验证。$/m,
  );
  assert.match(
    schemaBoundary,
    /^- Phase 3C 没有 Schema 变更、迁移或兼容路径。$/m,
  );

  const productPlanLines = productPlan.split(/\r?\n/);
  assert.ok(
    productPlanLines.includes(
      '| Phase 2 | 创作资产、Provider/模型设置、市场来源、选题与种子、契约、圣经、模型继承与资产冻结 | 已完成门禁 |',
    ),
  );
  assert.ok(
    productPlanLines.includes(
      '| Phase 3 | 分卷、情节、故事块、小纲、已发生事实与未来计划 | 3A/3B/3C 已完成，3D 下一步 |',
    ),
  );
  assert.ok(
    productPlanLines.includes(
      '- Phase 3C 已完成 StoryBlock/Stage/SceneTask、ChapterOutline Draft/save CAS/confirm/history、权威章节号、单一 drafting Session 与可靠 Writer 入口。',
    ),
  );
  assert.ok(
    productPlanLines.includes(
      '- Phase 3D 是唯一下一步：Future Plan/Actual Progress/Canon Projection 同 revision 只读组合及 Phase 3 总验收。',
    ),
  );

  const phase2Log = readSection(
    developmentLog,
    '2026-07-23 Phase 2 Creative Foundation 完成',
  );
  assert.match(
    phase2Log,
    /^- Phase 2 acceptance chain 进入 canonical `main` 后的链末提交：`f11faad`。$/m,
  );

  const phase3aLog = readSection(
    developmentLog,
    '2026-07-24 Phase 3A Planning Aggregate Foundation 完成',
  );
  assert.match(phase3aLog, /^- 规格审查和质量审查最终均为 `0\/0\/0`。$/m);
  assert.match(phase3aLog, /^- Product DB reads\/writes：`0\/0`；Provider calls：`0`。$/m);

  const phase3bLog = readSection(
    developmentLog,
    '2026-07-26 Phase 3B Volumes and Plots 完成',
  );
  assert.match(
    phase3bLog,
    /^- Task 10 验收文档与事实合同规格审查：`Critical 0 \/ Important 0 \/ Minor 0`。$/m,
  );
  assert.match(
    phase3bLog,
    /^- Task 10 验收文档与事实合同质量审查：`Critical 0 \/ Important 0 \/ Minor 0`。$/m,
  );
  assert.match(
    phase3bLog,
    /^- Product DB reads\/writes：`0\/0`；Real Provider calls：`0`；Live website\r?\n  access：`0`；任何公共响应、日志、报告和 artifact 均未输出明文 API key。$/m,
  );

  const phase3cLog = readSection(
    developmentLog,
    '2026-07-30 Phase 3C Story Blocks and Chapter Outlines 完成',
  );
  assert.match(
    phase3cLog,
    /^- 分支：`codex\/phase3c-story-blocks-outlines`；交付基线：`main@59d80d739ef39a09bcd54e1888e4e4da90a98fa3`；功能代码 HEAD：`056520c1f270fdf8f3888be2713647fff03bf2b8`。$/m,
  );
  assert.match(
    phase3cLog,
    /^- 交付代码顺序规格\/质量、M1 follow-up 与 pinned-session follow-up 的最终\r?\n  `Critical\/Important\/Minor` 均为 `0\/0\/0`。$/m,
  );
  assert.match(
    phase3cLog,
    /^- Task 12 验收文档与事实合同规格审查最终：`C\/I\/M 0\/0\/0`；质量审查最终：`C\/I\/M 0\/0\/0`；只覆盖本次五文件 Task 12 包，不外推为任何未评估产品能力 Ready。$/m,
  );
  assert.match(
    phase3cLog,
    /^- Fresh focused gates：Python `250 passed, 0 skipped, 0 failed`；Node `144\/144 passed, 0 failed, 0 skipped`。$/m,
  );
  assert.match(
    phase3cLog,
    /^- 第三次从头 final 五门禁全部 exit `0`；browser `7` 场景，完整 Python `2814 passed, 6 skipped, 0 failed`，root Node `243\/243`，frontend Node `522\/522`，integration `342 passed`，build `2956 modules transformed`，whitespace errors `0`。$/m,
  );
  assert.match(
    phase3cLog,
    /^- Real Provider calls `0`；Product DB reads\/writes `0\/0`；live website `0`；secret scan findings `0`。$/m,
  );
  assert.match(
    phase3cLog,
    /^- Phase 3D 是唯一下一步；正式写作、Finalization、真实 Provider、产品数据库与小说内容质量仍未评估。$/m,
  );

  assert.match(
    phase3aAcceptance,
    /^- 工作分支：`codex\/phase3-story-planning`$/m,
  );
  assert.match(
    phase3aAcceptance,
    /^- 门禁运行 HEAD：`2fd928c827f07dde73e89d8e3200e3ae8f6bd7d4`$/m,
  );
  assert.match(
    phase3aAcceptance,
    /^- Python unit \/ API：`2353 passed, 6 skipped, 0 failed`$/m,
  );
  assert.match(
    phase3aAcceptance,
    /^- 根级 Node 合同：`191 passed, 0 skipped, 0 failed`$/m,
  );
  assert.match(
    phase3aAcceptance,
    /^- 前端 unit：`365 passed, 0 skipped, 0 failed`$/m,
  );
  assert.match(
    phase3aAcceptance,
    /^- Disposable MySQL integration：`300 passed, 0 failed`$/m,
  );
  assert.match(
    phase3aAcceptance,
    /^- 数据库：`created=299, cleaned=299, remaining=0`$/m,
  );
  assert.match(phase3aAcceptance, /^- Vite：`2937 modules transformed`$/m);
  assert.match(
    phase3aAcceptance,
    /^- 规格审查：`Critical 0 \/ Important 0 \/ Minor 0`$/m,
  );
  assert.match(
    phase3aAcceptance,
    /^- 质量审查：`Critical 0 \/ Important 0 \/ Minor 0`$/m,
  );
  assert.match(phase3aAcceptance, /^- Provider calls：`0`$/m);
  assert.match(phase3aAcceptance, /^- Product DB reads\/writes：`0\/0`$/m);
  assert.match(
    phase3aAcceptance,
    /^- 未评估：Phase 3B–3D、Real Provider、Product DB、Content Quality$/m,
  );

  assert.match(
    phase3bAcceptance,
    /^> 分支：`codex\/phase3b-volumes-plots`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^> Fresh package gates 的功能代码 HEAD：`e3c7d18b23fa`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- Python Planning unit\/API：`193 passed, 0 failed`；exit `0`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- Node\/Frontend focused contracts：`59 passed, 0 failed`；exit `0`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- Task 10 验收文档与事实合同规格审查：`Critical 0 \/ Important 0 \/ Minor 0`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- Task 10 验收文档与事实合同质量审查：`Critical 0 \/ Important 0 \/ Minor 0`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- Browser API bypass：`0`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- owned process \/ port \/ temp root \/ Vite `deps_temp_\*`：`0`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- secret scan findings：`0`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- Python unit \/ API：`2542 passed, 6 skipped, 0 failed`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- 根级 Node 合同：`216 passed, 0 skipped, 0 failed`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- 前端 unit：`415 passed, 0 skipped, 0 failed`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- Disposable MySQL integration：`317 passed, 0 failed`$/m,
  );
  assert.match(
    phase3bAcceptance,
    /^- 数据库：`created=316, cleaned=316, remaining=0`$/m,
  );
  assert.match(phase3bAcceptance, /^- Vite：`2949 modules transformed`$/m);
  assert.match(phase3bAcceptance, /^- Real Provider calls：`0`$/m);
  assert.match(
    phase3bAcceptance,
    /^- Product DB reads\/writes：`0\/0`$/m,
  );
  assert.match(phase3bAcceptance, /^- Live website access：`0`$/m);

  assertPhase3cAcceptanceContract(phase3cAcceptance);

  assert.doesNotMatch(storyQualityCharter, /split_unfinalized_content/);
  assert.ok(
    storyQualityCharter.includes(
      '允许当前未完成场景在合适的位置自然结束，并把剩余未来任务滚动到下一章。',
    ),
  );
});

test('Phase 3C acceptance rejects malformed, extra, and duplicate H2 sections', () => {
  const invalidAcceptances = [
    {
      reason: 'H3 must not satisfy a missing canonical H2',
      acceptance: `
## 元数据
### 验收结论
## 已交付链路
## 独立审查
## Fresh 最终门禁
## 隔离与未评估边界
## 下一步
`,
    },
    {
      reason: 'an extra H2 must be rejected',
      acceptance: `
## 元数据
## 验收结论
## 已交付链路
## 独立审查
## 额外章节
## Fresh 最终门禁
## 隔离与未评估边界
## 下一步
`,
    },
    {
      reason: 'a duplicate H2 must be rejected',
      acceptance: `
## 元数据
## 验收结论
## 已交付链路
## 独立审查
## Fresh 最终门禁
## 隔离与未评估边界
## 下一步
## 下一步
`,
    },
  ];

  for (const { reason, acceptance } of invalidAcceptances) {
    assert.throws(
      () => assertPhase3cAcceptanceContract(acceptance),
      `acceptance H2 contract: ${reason}`,
    );
  }
});

test('Phase 3C acceptance preserves Markdown list and fence line structure', async () => {
  const acceptance = await readProjectFile(
    'docs/acceptance/2026-07-26-phase-3c-story-blocks-outlines.md',
  );
  const structurallyInvalidAcceptances = [
    acceptance.replace(
      '- 验收日期：`2026-07-30`\n- 基线：`main@59d80d739ef39a09bcd54e1888e4e4da90a98fa3`',
      '- 验收日期：`2026-07-30` - 基线：`main@59d80d739ef39a09bcd54e1888e4e4da90a98fa3`',
    ),
    acceptance.replace(
      '```text\nProjectPlanningView',
      '```text ProjectPlanningView',
    ),
  ];

  for (const invalidAcceptance of structurallyInvalidAcceptances) {
    assert.throws(
      () => assertPhase3cAcceptanceContract(invalidAcceptance),
      'acceptance must reject merged Markdown list and fence lines',
    );
  }
});

test('Phase 3C acceptance rejects forged or incorrect reviews and boundary overclaims', async () => {
  const acceptance = await readProjectFile(
    'docs/acceptance/2026-07-26-phase-3c-story-blocks-outlines.md',
  );
  const invalidAcceptances = [
    acceptance.replace(
      '## Fresh 最终门禁',
      '- Task 12 验收文档与事实合同规格审查最终：`C/I/M 0/0/0`\n\n## Fresh 最终门禁',
    ),
    acceptance.replace(
      '- Task 12 验收文档与事实合同质量审查最终：`C/I/M 0/0/0`',
      '- Task 12 验收文档与事实合同质量审查最终：`C/I/M 0/1/0`',
    ),
    acceptance.replace(
      '## Fresh 最终门禁',
      '- Task 12 验收文档与事实合同安全审查最终：`C/I/M 0/0/0`\n\n## Fresh 最终门禁',
    ),
    acceptance.replace(
      '## 已交付链路',
      'Phase 3 总验收、Phase 4、正式 Writer、Real Provider、Product DB 和 Content Quality 均已 Ready。\n\n## 已交付链路',
    ),
    acceptance.replace(
      '## 下一步',
      '- Phase 4 正式 Writer、Real Provider、Product DB 和 Content Quality 已完成。\n\n## 下一步',
    ),
    acceptance.replace(
      '## 独立审查',
      'Task 12 验收文档与事实合同已经独立审查并通过。\n\n## 独立审查',
    ),
    acceptance.replace(
      '## 独立审查',
      'Phase 3 总验收、Phase 4 正式 Writer、Real Provider、Product DB 和 Content Quality 已 Ready。\n\n## 独立审查',
    ),
    acceptance.replace(
      '## 隔离与未评估边界',
      'Task 12 文档审查通过；Phase 3/4、正式 Writer、Provider、DB 与 Content 均已 Ready。\n\n## 隔离与未评估边界',
    ),
    acceptance.replace(
      '# Phase 3C Story Blocks and Chapter Outlines 验收报告\n\n',
      '# Phase 3C Story Blocks and Chapter Outlines 验收报告\n\n未受合同约束的前置正文。\n\n',
    ),
  ];

  for (const invalidAcceptance of invalidAcceptances) {
    assert.throws(
      () => assertPhase3cAcceptanceContract(invalidAcceptance),
      'acceptance must reject forged, duplicate, or incorrect reviews and positive boundary overclaims',
    );
  }
});

test('Phase 3C contract rejects Task 1 examples without semantic sections', () => {
  const task1OnlyPlan = `
### Task 1: Freeze the Phase 3C Contract

- Delivery branch: \`codex/phase3c-story-blocks-outlines\`.
- Phase 3C makes no schema change.
- StoryBlock
- chapterOutlineController
- authoritative chapter
- npm run test:browser:phase3c
`;

  assert.throws(
    () => assertPhase3cPlanContract(task1OnlyPlan),
    /missing section: ## Frozen decisions/,
    'Task 1 examples must not satisfy the Phase 3C semantic contract',
  );
});

test('Phase 3C detailed plan freezes its delivery and safety contract', async () => {
  const runtimeFiles = [
    'frontend/src/stores/planningStore.js',
    'frontend/src/application/planning/planningWorkspaceController.js',
    'frontend/src/components/planning/PlanningWorkspace.vue',
    'frontend/src/views/ProjectPlanningView.vue',
    'frontend/src/router/projectRoutes.js',
  ];
  const [plan, ...runtimeSources] = await Promise.all([
    readProjectFile(phase3cPlan),
    ...runtimeFiles.map(readProjectFile),
  ]);
  const runtime = runtimeSources.join('\n');

  assertPhase3cPlanContract(plan);

  for (const forbiddenRuntimeSymbol of [
    'planningV2Store',
    'chapterOutlineStore',
    'storyBlockStore',
    'PlanningWorkspaceV2',
    '/planning/initial',
  ]) {
    assert.doesNotMatch(
      runtime,
      new RegExp(forbiddenRuntimeSymbol, 'i'),
      `runtime must not contain: ${forbiddenRuntimeSymbol}`,
    );
  }
});
