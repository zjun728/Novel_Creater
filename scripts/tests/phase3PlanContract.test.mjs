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
  ] = await Promise.all([
    readProjectFile('CURRENT_PROJECT_STATE.md'),
    readProjectFile('PRODUCT_DEVELOPMENT_PLAN.md'),
    readProjectFile('DEVELOPMENT_LOG.md'),
    readProjectFile('STORY_QUALITY_CHARTER.md'),
  ]);

  const currentConclusion = readSection(currentState, '当前结论');
  assert.match(currentConclusion, /^- Canonical release branch：`main`。$/m);
  assert.match(
    currentConclusion,
    /^- Phase 2 验收链已进入 `main`，链末提交：\r?\n  `f11faad531f04250f2a987390a468dfd14bf06a3`。$/m,
  );
  assert.match(
    currentConclusion,
    /^- 当前完成阶段：\*\*Phase 2 Creative Foundation（创作地基）\*\*。$/m,
  );
  assert.match(
    currentConclusion,
    /^- 当前开发分支：`codex\/phase3-story-planning`。$/m,
  );
  assert.match(
    currentConclusion,
    /^- 当前工作：\*\*Phase 3 Story Planning（故事规划）\*\*。$/m,
  );
  assert.match(
    currentConclusion,
    /^- Product DB、Real Provider、Phase 4 Writer Loop、Phase 5 Finalization 和\r?\n  Content Quality 均未评估，不得据 Phase 2 门禁宣告 Ready。$/m,
  );

  const nextStep = readSection(currentState, '唯一下一步');
  assert.match(
    nextStep,
    /^按已批准的 Phase 3 设计和实施计划完成 \*\*Phase 3 Story Planning\*\*。当前先实施\r?\nPhase 3A Planning Aggregate Foundation；不得提前调用真实 Provider、读写产品\r?\n数据库，或把 Phase 4 写作环、Phase 5 定稿和内容质量标记为已完成。$/m,
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

  assert.doesNotMatch(storyQualityCharter, /split_unfinalized_content/);
  assert.ok(
    storyQualityCharter.includes(
      '允许当前未完成场景在合适的位置自然结束，并把剩余未来任务滚动到下一章。',
    ),
  );
});
