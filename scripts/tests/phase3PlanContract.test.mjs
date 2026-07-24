import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const readProjectFile = (path) =>
  readFile(new URL(`../../${path}`, import.meta.url), 'utf8');

const readSection = (document, heading) => {
  const marker = `## ${heading}`;
  const start = document.indexOf(marker);
  assert.notEqual(start, -1, `missing section: ${marker}`);
  const next = document.indexOf('\n## ', start + marker.length);
  return document.slice(start, next === -1 ? document.length : next);
};

test('Phase 3 planning facts are current and the obsolete split action is retired', async () => {
  const [
    currentState,
    productPlan,
    developmentLog,
    storyQualityCharter,
    acceptance,
  ] = await Promise.all([
    readProjectFile('CURRENT_PROJECT_STATE.md'),
    readProjectFile('PRODUCT_DEVELOPMENT_PLAN.md'),
    readProjectFile('DEVELOPMENT_LOG.md'),
    readProjectFile('STORY_QUALITY_CHARTER.md'),
    readProjectFile(
      'docs/acceptance/2026-07-24-phase-3a-planning-aggregate.md',
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
    /^- 当前完成交付包：\*\*Phase 3A Planning Aggregate Foundation\*\*。$/m,
  );
  assert.match(
    currentConclusion,
    /^- 当前开发分支：`codex\/phase3-story-planning`。$/m,
  );
  assert.match(
    currentConclusion,
    /^- 当前工作：\*\*Phase 3B Volumes and Plots\*\*。$/m,
  );
  assert.match(
    currentConclusion,
    /^- Phase 3B–3D、Product DB、Real Provider、Phase 4 Writer Loop、Phase 5\r?\n  Finalization 和 Content Quality 均未评估，不得据 Phase 3A 门禁宣告 Ready。$/m,
  );

  const nextStep = readSection(currentState, '唯一下一步');
  assert.match(
    nextStep,
    /^从干净的 Phase 3A 提交继续实施 \*\*Phase 3B Volumes and Plots\*\*：交付手工与\r?\nAI Planning Draft、分卷\/情节线正式 API 和页面、项目导航及 archived\/superseded\r?\n只读历史。自动门禁继续禁止真实 Provider 和产品数据库。$/m,
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

  const productPlanLines = productPlan.split(/\r?\n/);
  assert.ok(
    productPlanLines.includes(
      '| Phase 2 | 创作资产、Provider/模型设置、市场来源、选题与种子、契约、圣经、模型继承与资产冻结 | 已完成门禁 |',
    ),
  );
  assert.ok(
    productPlanLines.includes(
      '| Phase 3 | 分卷、情节、故事块、小纲、已发生事实与未来计划 | 进行中 |',
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

  assert.match(
    acceptance,
    /^- 工作分支：`codex\/phase3-story-planning`$/m,
  );
  assert.match(
    acceptance,
    /^- 门禁运行 HEAD：`2fd928c827f07dde73e89d8e3200e3ae8f6bd7d4`$/m,
  );
  assert.match(
    acceptance,
    /^- Python unit \/ API：`2353 passed, 6 skipped, 0 failed`$/m,
  );
  assert.match(
    acceptance,
    /^- 根级 Node 合同：`191 passed, 0 skipped, 0 failed`$/m,
  );
  assert.match(
    acceptance,
    /^- 前端 unit：`365 passed, 0 skipped, 0 failed`$/m,
  );
  assert.match(
    acceptance,
    /^- Disposable MySQL integration：`300 passed, 0 failed`$/m,
  );
  assert.match(
    acceptance,
    /^- 数据库：`created=299, cleaned=299, remaining=0`$/m,
  );
  assert.match(acceptance, /^- Vite：`2937 modules transformed`$/m);
  assert.match(
    acceptance,
    /^- 规格审查：`Critical 0 \/ Important 0 \/ Minor 0`$/m,
  );
  assert.match(
    acceptance,
    /^- 质量审查：`Critical 0 \/ Important 0 \/ Minor 0`$/m,
  );
  assert.match(acceptance, /^- Provider calls：`0`$/m);
  assert.match(acceptance, /^- Product DB reads\/writes：`0\/0`$/m);
  assert.match(
    acceptance,
    /^- 未评估：Phase 3B–3D、Real Provider、Product DB、Content Quality$/m,
  );

  assert.doesNotMatch(storyQualityCharter, /split_unfinalized_content/);
  assert.ok(
    storyQualityCharter.includes(
      '允许当前未完成场景在合适的位置自然结束，并把剩余未来任务滚动到下一章。',
    ),
  );
});
