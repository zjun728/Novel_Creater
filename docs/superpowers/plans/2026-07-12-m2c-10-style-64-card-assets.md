# M2C 10-Style 64-Card Asset Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the reviewed Writer Core candidate package from 8 styles plus 48 experience cards to exactly 10 styles plus 64 cards, then obtain one explicit human approval and pass the release validator without touching a database or Provider.

**Architecture:** Keep the existing append-only JSON package as the editorial source of truth. Tighten the strict asset domain to the approved exact inventory, append two reusable style templates and sixteen narrowly scoped cards, and use one deterministic local builder to recalculate payload hashes and child-file hashes. All contract, tool, test and candidate changes remain uncommitted while the complete 74-asset inventory is reviewed; after explicit author approval, provenance is changed mechanically and one self-contained GREEN commit publishes the complete package.

**Tech Stack:** Python 3.12, Pydantic, canonical JSON/SHA-256, pytest, PowerShell, Git.

---

## Scope and file map

- `backend/domain/assets.py`: exact 10/64 inventory and twelve-category contract.
- `backend/tests/unit/test_asset_models.py`: strict model boundaries for the expanded category literal and exact tuple lengths.
- `backend/tests/unit/test_asset_manifest.py`: synthetic and production structural/release gates, baseline-content preservation, exact stable keys and category counts.
- `backend/scripts/rebuild_writer_asset_manifest.py`: fixed-root, no-DB builder/checker for payload hashes and child-file SHA-256 values.
- `backend/tests/unit/test_rebuild_writer_asset_manifest.py`: deterministic builder/checker tests under `tmp_path`.
- `backend/assets/writer-core-v1.1.0/style_templates.json`: append two candidate style revisions.
- `backend/assets/writer-core-v1.1.0/experience_cards.json`: append sixteen candidate card revisions.
- `backend/assets/writer-core-v1.1.0/manifest.json`: child-file hashes only.
- `docs/development/writer-core-m2-asset-review.md`: complete 10/64 inventory and human decisions.

This plan supersedes the 8-style and 40–60-card assumptions in Tasks 1–2 of `2026-07-11-m2c-assets-and-corpus.md`. It does not seed MySQL, register routes, import a novel, call a Provider, or implement Writer Prompt retrieval. The later recommendation service must select only 2–4 experience cards per generation; it must never inject all 64.

### Task 1: Tighten the package contract to exact 10/64

**Files:**
- Modify: `backend/domain/assets.py`
- Modify: `backend/tests/unit/test_asset_models.py`
- Modify: `backend/tests/unit/test_asset_manifest.py`

- [ ] **Step 1: Write RED tests for the approved inventory**

Replace synthetic inventory helpers with exact category counts:

```python
EXPECTED_CATEGORY_COUNTS = {
    "plot_organization": 6,
    "ensemble": 6,
    "dialogue": 6,
    "emotion": 6,
    "interiority": 6,
    "information_release": 6,
    "pacing": 6,
    "suspense": 6,
    "long_arc_continuity": 4,
    "progression_economy": 4,
    "character_arcs": 4,
    "action_conflict": 4,
}


def synthetic_categories() -> tuple[str, ...]:
    return tuple(
        category
        for category, count in EXPECTED_CATEGORY_COUNTS.items()
        for _ in range(count)
    )
```

Update `valid_values()` to create 10 styles and one card for each entry returned by `synthetic_categories()`. Add boundary tests that attempt 9/11 styles, 63/65 cards, a missing category, and a 5/3 split in any new category while preserving 64 total cards. Require the fixed public errors:

```python
with pytest.raises(AssetPackageError, match="exactly 10 styles"):
    validate_asset_package(changed, mode="structural")

with pytest.raises(AssetPackageError, match="exactly 64 experience cards"):
    validate_asset_package(changed, mode="structural")

with pytest.raises(AssetPackageError, match="approved category counts"):
    validate_asset_package(changed, mode="structural")
```

Before editing either candidate JSON file, add and run a raw-prefix preservation test that reads the current eight style rows and 48 card rows without passing through the future exact-count model:

```python
baseline = [
    {"stable_key": item["stable_key"], "content_hash": item["content_hash"]}
    for item in (*raw_styles[:8], *raw_cards[:48])
]
assert canonical_hash(baseline) == (
    "2db58bb3e5dbd0e5314ffaaaab5d0ea37dd332e6ded41f2975c300151d3dae05"
)
```

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
.\.venv-m2\Scripts\python.exe -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py -q
```

Expected: failures still mention 8 styles, 40–60 cards, or reject the four new category literals.

- [ ] **Step 3: Implement the exact domain contract**

Use one category-count constant shared by validation and tests:

```python
from types import MappingProxyType


AssetCategory = Literal[
    "plot_organization", "ensemble", "dialogue", "emotion", "interiority",
    "information_release", "pacing", "suspense", "long_arc_continuity",
    "progression_economy", "character_arcs", "action_conflict",
]
ASSET_CATEGORIES = get_args(AssetCategory)
ASSET_CATEGORY_COUNTS = MappingProxyType({
    "plot_organization": 6,
    "ensemble": 6,
    "dialogue": 6,
    "emotion": 6,
    "interiority": 6,
    "information_release": 6,
    "pacing": 6,
    "suspense": 6,
    "long_arc_continuity": 4,
    "progression_economy": 4,
    "character_arcs": 4,
    "action_conflict": 4,
})


class AssetPackage(_FrozenModel):
    manifest: AssetManifest
    styles: tuple[StyleTemplateRevision, ...] = Field(min_length=10, max_length=10)
    experience_cards: tuple[ExperienceCardRevision, ...] = Field(
        min_length=64, max_length=64
    )
```

In `validate_asset_package`, compare the calculated category counts with `ASSET_CATEGORY_COUNTS`; do not merely test set coverage. Change the fixed error messages to `exactly 10 styles`, `exactly 64 experience cards`, and `approved category counts`.

- [ ] **Step 4: Run the tests and verify GREEN**

```powershell
.\.venv-m2\Scripts\python.exe -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py -k "not production_candidate_manifest" -q
```

Expected: all focused synthetic tests pass. The existing production-package test is an explicitly tracked integration RED until Tasks 2–4 append the missing assets. Keep every change uncommitted and do not push while this RED exists.

- [ ] **Step 5: Record the uncommitted contract checkpoint**

```powershell
git diff --check
git status --short
```

Expected: only the declared M2C plan paths plus the pre-existing candidate package/review paths are dirty; the index is empty. Do not stage or commit.

### Task 2: Add the two missing reusable style templates

**Files:**
- Modify: `backend/assets/writer-core-v1.1.0/style_templates.json`
- Modify: `backend/tests/unit/test_asset_manifest.py`

- [ ] **Step 1: Extend the production-key RED assertion**

Set `PRODUCTION_STYLE_KEYS` to the existing eight keys plus:

```python
{
    "cautious-survival-accumulation",
    "austere-tragic-defiance",
}
```

Add assertions that the two new templates have distinct `reading_experience`, `rhythm`, `original_anchor`, and complete examples of at least 220 characters containing dialogue. Run the production test and expect it to fail because the JSON still has eight entries.

- [ ] **Step 2: Append `cautious-survival-accumulation` as a candidate**

Author one full `style-template-v1` object named `稳健求生积累型`. Its editorial contract is fixed:

| Field | Required mechanism |
|---|---|
| reading experience | preparation, probing, retreat and small gains feel competent and satisfying |
| rhythm | assess → small test → preserve exit → limited action → settle costs → compound advantage |
| dialogue/subtext | characters negotiate incomplete information and risk ownership, not just explain plans |
| interiority | compare risk, information and private attachments without turning into a spreadsheet |
| action | withdrawal, concealment and stopping loss can be successful outcomes |
| risks | paralysis by calculation, resource bookkeeping, permanent selfishness, repetitive caution |
| original anchor | survival and retained options are positive rewards, not failed heroism |

Both examples must be original scenes with desires, opposition, choice, consequence, differentiated voices and physical setting. They must not use names, objects, sects, incidents or wording identifiable with a source novel.

- [ ] **Step 3: Append `austere-tragic-defiance` as a candidate**

Author one full object named `冷峻悲情逆命型` with this fixed contract:

| Field | Required mechanism |
|---|---|
| reading experience | long pressure and irreversible loss harden a decision to resist an imposed ending |
| rhythm | cold pressure → deepened loss → hardened recognition → adverse decision → wounded payoff → quiet aftermath |
| dialogue/subtext | restraint, silence and changed forms of address carry what cannot be repaired |
| emotion/interiority | emotion accumulates through action and breaks only at a concrete decision point |
| action | victory retains injury, debt or relationship loss instead of erasing the price |
| risks | suffering for its own sake, universal cold faces, forced sacrifice, abstract philosophy replacing action |
| original anchor | defiance matters because the character knows and retains the cost |

Keep provenance exactly candidate/null/null. Do not imitate an author's syntax or copy source text.

- [ ] **Step 4: Recalculate only the two new payload hashes and verify focused content**

Use `canonical_hash(payload)` for each new `content_hash`. Run:

```powershell
.\.venv-m2\Scripts\python.exe -m pytest backend/tests/unit/test_asset_manifest.py -q
```

Expected at this checkpoint: tests may still fail only because the package has 48 rather than 64 cards; no style-key, schema, hash, duplicate or example-quality assertion fails.

- [ ] **Step 5: Keep the two candidate styles uncommitted**

```powershell
git diff --check
git diff --cached --name-only
```

Expected: cached diff is empty. Candidate style JSON remains in the working tree for later whole-package review.

### Task 3: Add long-arc and progression cards

**Files:**
- Modify: `backend/assets/writer-core-v1.1.0/experience_cards.json`
- Modify: `backend/tests/unit/test_asset_manifest.py`

- [ ] **Step 1: Add exact-key RED assertions**

Require these eight candidate stable keys and category counts of four each:

```python
LONG_ARC_KEYS = {
    "arc-block-chapter-delta",
    "arc-setup-serves-now-payoff-changes-choice",
    "arc-pressure-waves",
    "arc-aftermath-new-normal",
}
PROGRESSION_KEYS = {
    "progression-breakthrough-earned-options",
    "progression-resource-loop-cost",
    "progression-rank-changes-permission-risk",
    "progression-new-tier-new-problem",
}
```

- [ ] **Step 2: Author four `long_arc_continuity` cards**

Use these exact titles and method boundaries:

1. `故事块跨章，每章改变一项状态` — each chapter fulfils one local promise and changes block state; it must not force the entire block to close.
2. `伏笔先服务当前戏，回收时改变选择` — setup must work in the current scene; payoff changes interpretation or choice; the actual ledger remains Canon.
3. `长线压力要换来源并保留低谷` — pressure waves change source and include functional low points; it must not prescribe a fixed chapter count.
4. `高潮后建立带代价的新常态` — settle power, resources, relationship, injury and obligations without resetting consequences.

Each card needs at least one applicability, one non-applicability, one concrete risk and one original micro-demo that demonstrates the method rather than explaining it.

- [ ] **Step 3: Author four `progression_economy` cards**

Use these exact titles and boundaries:

1. `突破来自反馈、准备与旧能力组合` — the breakthrough opens a new option and is not a surprise gift.
2. `资源形成获取、转化、消耗、补给闭环` — a meaningful spend closes another route; actual inventory remains Canon.
3. `境界与身份同时改变权限和风险` — social access, attention and obligations change with power; the card contains no project-specific level table.
4. `新层级带来新类型问题` — escalation changes constraints or counterplay instead of only increasing enemy numbers.

- [ ] **Step 4: Recalculate the eight new content hashes and run focused tests**

```powershell
.\.venv-m2\Scripts\python.exe -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py -q
```

Expected: package count remains RED at 56 cards; all eight new objects individually validate and have unique normalized methods/demos.

- [ ] **Step 5: Keep the first card group uncommitted**

```powershell
git diff --check
git diff --cached --name-only
```

Expected: cached diff is empty. Do not publish a partial 56-card package.

### Task 4: Add character-arc and action-conflict cards

**Files:**
- Modify: `backend/assets/writer-core-v1.1.0/experience_cards.json`
- Modify: `backend/tests/unit/test_asset_manifest.py`

- [ ] **Step 1: Add exact-key RED assertions**

```python
CHARACTER_ARC_KEYS = {
    "character-antagonist-adapts-clock",
    "character-supporting-arc-changes-main",
    "character-growth-proved-under-old-trigger",
    "character-antagonist-offers-valid-alternative",
}
ACTION_CONFLICT_KEYS = {
    "action-competing-objectives",
    "action-exchange-changes-state",
    "action-finish-established-combination",
    "action-injury-cost-changes-tactics",
}
```

- [ ] **Step 2: Author four `character_arcs` cards**

1. `反派按自己的时钟行动并在受挫后改策` — no villain waiting for the protagonist; the actual clock belongs to Engine.
2. `配角的阶段选择反过来改变主线` — the choice follows the supporting character's own cost, not protagonist convenience.
3. `成长要在旧诱因重现时由新选择证明` — no narrator verdict or personality label.
4. `反派提出有诱惑力的有效替代方案` — the alternative must work for something the protagonist wants; disagreement retains moral and practical substance.

- [ ] **Step 3: Author four `action_conflict` cards**

1. `胜负之外同时争夺另一项目标` — rescue, concealment, delay, evidence or position prevents flat damage trading.
2. `每轮交锋改变位置、信息或资源` — repeated attacks without state change are compressed.
3. `终结手段来自前文建立的能力组合` — no unseeded finishing move.
4. `伤势与损耗持续改变后续战术` — actual wounds/resources remain Canon; avoid a repetitive injury checklist.

- [ ] **Step 4: Run the exact 10/64 structural gate**

```powershell
.\.venv-m2\Scripts\python.exe -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py -q
```

Expected: all tests pass in structural mode; release mode still fails with `ASSET_RELEASE_REVIEW_INCOMPLETE` because all 74 assets remain candidates.

- [ ] **Step 5: Keep the complete candidate package uncommitted**

```powershell
git diff --check
git diff --cached --name-only
```

Expected: cached diff is empty. The working tree now contains the complete candidate 10/64 content but no release commit.

### Task 5: Make hash rebuilding deterministic and assemble the candidate package

**Files:**
- Create: `backend/scripts/rebuild_writer_asset_manifest.py`
- Create: `backend/tests/unit/test_rebuild_writer_asset_manifest.py`
- Modify: `backend/assets/writer-core-v1.1.0/manifest.json`
- Modify: `backend/tests/unit/test_asset_manifest.py`

- [ ] **Step 1: Write RED tests for check/write behavior**

The script must expose a pure `rebuild_values(styles, cards, manifest)` and a fixed-package CLI with mutually exclusive `--check` and `--write`. Test under `tmp_path` that:

```python
rebuilt_styles, rebuilt_cards, rebuilt_manifest = rebuild_values(
    styles, cards, manifest
)
style_bytes = render_asset_json(rebuilt_styles)
card_bytes = render_asset_json(rebuilt_cards)
assert rebuilt_styles[0]["content_hash"] == canonical_hash(styles[0]["payload"])
assert rebuilt_cards[0]["content_hash"] == canonical_hash(cards[0]["payload"])
assert rebuilt_manifest["styles_file"]["sha256"] == sha256(style_bytes).hexdigest()
assert rebuilt_manifest["experience_cards_file"]["sha256"] == sha256(card_bytes).hexdigest()
```

`--check` returns nonzero if any content hash, child hash or JSON formatting differs and must not change file bytes or mtimes. `--write` must write temporary siblings, atomically replace each child file, and replace the manifest last; interruption can only leave a manifest/child hash mismatch that the loader rejects, never a falsely valid mixed package. A write followed by a second `--check` returns zero. Unknown arguments are rejected. The CLI must not accept arbitrary filesystem paths and must not import database modules.

- [ ] **Step 2: Verify RED**

```powershell
.\.venv-m2\Scripts\python.exe -m pytest backend/tests/unit/test_rebuild_writer_asset_manifest.py -q
```

Expected: module is absent.

- [ ] **Step 3: Implement the fixed-root builder**

Export `render_asset_json(value) -> bytes` and use `canonical_hash(row["payload"])`, UTF-8, `ensure_ascii=False`, `indent=2`, and exactly one trailing newline. In write mode, render all three files in memory, fsync temporary sibling files, atomically replace styles and cards, and replace manifest last; on any failure remove only remaining temporary files. In check mode, generate expected bytes in memory and compare without writing. Add an injected-failure test proving `load_asset_package` rejects any interrupted mixed state by SHA mismatch.

- [ ] **Step 4: Re-run the prefix preservation test before rebuilding**

The production test added in Task 1 already computes the aggregate identity of the unchanged prefix:

```python
baseline = [
    {"stable_key": item.stable_key, "content_hash": item.content_hash}
    for item in (*package.styles[:8], *package.experience_cards[:48])
]
assert canonical_hash(baseline) == (
    "2db58bb3e5dbd0e5314ffaaaab5d0ea37dd332e6ded41f2975c300151d3dae05"
)
```

This makes the expansion append-only. A deliberate rewrite of an existing candidate requires a separate content-review decision and updated baseline, not an incidental formatting pass.

- [ ] **Step 5: Rebuild and check the real candidate package**

```powershell
.\.venv-m2\Scripts\python.exe -m backend.scripts.rebuild_writer_asset_manifest --write
.\.venv-m2\Scripts\python.exe -m backend.scripts.rebuild_writer_asset_manifest --check
.\.venv-m2\Scripts\python.exe -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py backend/tests/unit/test_rebuild_writer_asset_manifest.py -q
```

Expected: exact 10 styles, 64 cards, category counts `6×8 + 4×4`, structural mode GREEN, release mode expected failure, and no file outside the package changes.

- [ ] **Step 6: Keep builder, manifest and tests uncommitted**

```powershell
git diff --check
git diff --cached --name-only
```

Expected: cached diff is empty. Structural validation is GREEN, release validation is still the expected approval failure, and no intermediate commit depends on untracked package files.

### Task 6: Complete content review and release approval

**Files:**
- Modify: `docs/development/writer-core-m2-asset-review.md`
- Modify provenance after explicit approval only: `backend/assets/writer-core-v1.1.0/style_templates.json`
- Modify provenance after explicit approval only: `backend/assets/writer-core-v1.1.0/experience_cards.json`
- Rebuild child hashes after explicit approval only: `backend/assets/writer-core-v1.1.0/manifest.json`
- Modify: `backend/tests/unit/test_asset_manifest.py`

- [ ] **Step 1: Expand the review ledger while keeping every entry candidate**

List all 10 styles and 64 cards. For each new key record title, category, one-sentence purpose, primary risk and `candidate`. Record controller review outcomes as retain/rewrite/reject without changing release provenance.

- [ ] **Step 2: Run two independent content reviews**

Reviewer A checks style/card distinction, demonstrated method, applicability boundary, risk and originality. Reviewer B checks male-serial usefulness, character fullness, dialogue/emotion quality, absence of source-specific names/plots, and whether any card belongs in Engine or Canon instead. Any rewrite is re-reviewed by both reviewers.

- [ ] **Step 3: Present the complete inventory to the author and stop**

Present the review ledger plus the two JSON files. Require one explicit human decision for the whole 74-asset release. Until the author says `整批批准`, keep every provenance object exactly:

```json
{"reviewer": null, "review_time": null, "decision": "candidate"}
```

Do not commit release content and do not seed any database while approval is absent.

- [ ] **Step 4: After explicit approval, apply provenance once and rebuild hashes**

Use one timezone-aware approval timestamp and reviewer identity `author`. Set all 74 decisions to `approved`, run the builder in write mode, then run it again in check mode. The content payloads must not change during this provenance-only step; provenance changes do not alter `content_hash`, but child-file SHA values do change.

- [ ] **Step 5: Run the release gate and full local regression**

```powershell
.\.venv-m2\Scripts\python.exe -c "from pathlib import Path; from backend.domain.assets import load_asset_package; p=load_asset_package(Path('backend/assets/writer-core-v1.1.0/manifest.json'), mode='release'); print(f'release_ready=true styles={len(p.styles)} cards={len(p.experience_cards)}')"
.\.venv-m2\Scripts\python.exe -m pytest backend/tests/unit backend/tests/api -q
git diff --check
```

Expected: `release_ready=true styles=10 cards=64`; all unit/API tests pass; no Provider or MySQL connection occurs.

- [ ] **Step 6: Create one self-contained approved asset release commit**

```powershell
git add backend/domain/assets.py backend/scripts/rebuild_writer_asset_manifest.py backend/assets/writer-core-v1.1.0 backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py backend/tests/unit/test_rebuild_writer_asset_manifest.py docs/development/writer-core-m2-asset-review.md
git diff --cached --check
git diff --cached --name-only
git commit -m "content: add reviewed M2 writing assets"
git status --short
```

Expected before commit: the cached file list is exactly the declared contract, builder, complete package, tests and review ledger—no unrelated dirty file. Expected after commit: those paths are clean and the commit passes from a fresh checkout without relying on untracked files. Continue with Task 3 of `2026-07-11-m2c-assets-and-corpus.md`, amended so deterministic experience-card recommendation returns between 2 and 4 unique cards and no Prompt path can request all 64.

## Final verification boundary

This plan is complete only when all of the following are true:

- Structural validator requires exact 10/64 and exact `6×8 + 4×4` category counts.
- The two new styles are reusable mechanisms, not imitations of source prose.
- All sixteen new cards are concrete local writing choices with applicability, non-applicability, risk and original demo.
- Existing 8/48 payload hashes remain unchanged.
- All 74 assets have one explicit author approval, reviewer and timezone-aware timestamp.
- Release validation passes; no database, Provider, raw novel, absolute path or secret is touched.
- Later runtime retrieval is explicitly bounded to 2–4 experience cards.
