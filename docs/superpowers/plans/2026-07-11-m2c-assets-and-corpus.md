# M2C Assets and Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one installation-wide reviewed style/experience package and a safe local `.txt` corpus pipeline with immutable revisions, hashes, chapter/fragment indexes, bounded APIs, and no raw novels in Git.

**Architecture:** Asset files are explicit reviewed source packages validated before any DB write; seeding appends revisions and atomically moves heads. Corpus import resolves only root-relative `.txt`, processes bytes outside the transaction, then atomically publishes source/chapter/fragment rows. One shared containment primitive protects both corpus paths and SPA fallback.

**Tech Stack:** Python 3.12, Pydantic, pathlib, FastAPI, aiomysql, MySQL 8.4, pytest, JSON asset manifests.

---

### Task 1: Strict asset package and validator

**Files:**
- Create: `backend/domain/assets.py`
- Create: `backend/tests/unit/test_asset_models.py`
- Create: `backend/tests/unit/test_asset_manifest.py`

- [ ] **Step 1: Write RED tests for package counts, fields, hashes, and duplicates**

```python
import pytest

from backend.domain.assets import AssetPackageError, validate_asset_package


def test_synthetic_asset_package_is_complete_and_distinct(reviewed_package):
    package = validate_asset_package(reviewed_package, mode="structural")
    assert package.package_version == "writer-core-v1.1.0"
    assert len(package.styles) == 8
    assert 40 <= len(package.experience_cards) <= 60
    assert {card.category for card in package.experience_cards} == {
        "plot_organization", "ensemble", "dialogue", "emotion", "interiority",
        "information_release", "pacing", "suspense",
    }
    assert len({item.content_hash for item in (*package.styles, *package.experience_cards)}) == len(package.styles) + len(package.experience_cards)


def test_prompt_payload_cannot_contain_source_text_fields(reviewed_package):
    reviewed_package["styles"][0]["payload"]["rawExcerpt"] = "forbidden"
    with pytest.raises(AssetPackageError):
        validate_asset_package(reviewed_package, mode="structural")
```

Define the `reviewed_package` fixture in the test file as a fully valid synthetic object with 8 minimal styles and 40 minimal cards covering all categories. The second test mutates only the forbidden field, proving the stable error is not caused by a missing file.

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py -q
```

Expected: asset domain/package files are absent.

- [ ] **Step 3: Implement strict models and deterministic manifest loading**

Define `StyleTemplateRevision`, `ExperienceCardRevision`, `AssetManifest`, and `AssetPackage` as frozen `extra="forbid"` Pydantic models. `mode="structural"` validates fields/counts/categories/hashes/duplicates/source leakage but permits candidate review status. `mode="release"` adds the requirement that every row carries reviewer, review time and `decision="approved"`. Validate child file SHA-256 before parsing; validate canonical content hashes after parsing; reject duplicate stable keys, normalized method/demo hashes, forbidden provenance fields in prompt payload and missing categories.

Every validated style contains reading experience, applicability, same standard-scene full example, separate full application example, narrative distance, rhythm, diction density, dialogue/subtext/voices, emotion/interiority, action/explanation/environment/body response, preferred techniques, risks and original anchor. Every validated experience card contains category, method, applicability, non-applicability, risks and original micro-demo. Review metadata stays in provenance, never prompt payload.

- [ ] **Step 4: Verify validator GREEN without DB writes**

```powershell
python -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py -q
```

Expected: synthetic package validation passes with no DB imports or writes.

- [ ] **Step 5: Commit validator structure, not unreviewed content**

```powershell
git add backend/domain/assets.py backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py
git commit -m "feat: define strict writer asset package"
```

### Task 2: Author the candidate asset pack and obtain human approval

**Files:**
- Create: `backend/assets/writer-core-v1.1.0/manifest.json`
- Create: `backend/assets/writer-core-v1.1.0/style_templates.json`
- Create: `backend/assets/writer-core-v1.1.0/experience_cards.json`
- Create: `docs/development/writer-core-m2-asset-review.md`
- Modify: `backend/tests/unit/test_asset_manifest.py`

- [ ] **Step 1: Build candidates from approved editorial inputs**

Use `WRITING_STYLE_STANDARDS.md`, `frontend/src/data/writingStyleStandards.js`, and the 28 original `sampleMicroDemoCards.v2_1/v2_2.json` only as editorial inputs. Deduplicate/merge/rewrite the old 46 provenance rows; never count them directly. Do not read or copy raw novels in this task.

The production style stable keys are fixed to:

```json
["direct-propulsive", "light-humorous", "immersive-ensemble", "restrained-suspense", "high-energy-growth", "emotion-relationship", "epic-civilization-building", "marketplace-wit-and-life"]
```

- [ ] **Step 2: Run the strict validator**

Add a production-package test that calls `load_asset_package(Path("backend/assets/writer-core-v1.1.0/manifest.json"), mode="structural")` and asserts the same count/category/hash invariants as the synthetic test.

```powershell
python -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py -q
```

Expected before human review: structural mode passes with exact 8 styles, 40–60 cards, all categories, all required examples, no duplicate normalized method/demo and no source fields in prompt payload. Release mode must still fail while any decision is candidate/rewrite/rejected.

- [ ] **Step 3: Present every style and card inventory for controller review**

Record one decision per stable key as `approved`, `rewrite`, or `rejected`, with a concise reason. The controller checks distinguishable reading experience, complete examples, method usefulness, category coverage, lack of disguised duplicates, no source-specific names/details, and no full QA rubric in prompt rules.

- [ ] **Step 4: Revise until every manifest entry is approved**

Update content hashes and child-file hashes after revisions. The review ledger records reviewer/time/decision but explicitly states that the ledger does not self-prove content quality.

Run the release gate after the last approval:

```powershell
python -c "from pathlib import Path; from backend.domain.assets import load_asset_package; p=load_asset_package(Path('backend/assets/writer-core-v1.1.0/manifest.json'), mode='release'); print(f'release_ready=true styles={len(p.styles)} cards={len(p.experience_cards)}')"
```

Expected: `release_ready=true`, all decisions approved and `database_writes=0`.

- [ ] **Step 5: Commit the approved content separately**

```powershell
git add backend/assets/writer-core-v1.1.0 docs/development/writer-core-m2-asset-review.md backend/tests/unit/test_asset_manifest.py
git commit -m "content: add reviewed M2 writing assets"
```

### Task 3: Immutable asset seeding and safe catalog APIs

**Files:**
- Create: `backend/repositories/assets.py`
- Create: `backend/services/assets.py`
- Create: `backend/scripts/seed_writer_assets.py`
- Create: `backend/routers/assets.py`
- Create: `backend/tests/unit/test_asset_recommendation.py`
- Create: `backend/tests/api/test_asset_routes.py`
- Create: `backend/tests/integration/test_asset_seeding.py`

- [ ] **Step 1: Write RED tests for idempotency, heads, and bounded responses**

Test first seed, same-manifest zero inserts, changed content new revision/head, old revision immutable, failure rollback, deterministic three-style recommendation, bounded examples, and absence of provenance/raw/source fields from API.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_asset_recommendation.py backend/tests/api/test_asset_routes.py -q
```

- [ ] **Step 3: Implement lock-insert-move-head seeding**

For each stable key: require release-mode validation, lock head, replay if head hash matches, otherwise insert immutable revision, archive the previous active revision, and move head in one transaction. The CLI supports only `--validate-only`, safe dry-run, and an execute mode requiring database-name confirmation. API list reads reviewed summaries; detail returns the complete approved same-scene/application examples subject to manifest field-length limits, never silently truncated while labeled complete.

Freeze routes as `GET /api/assets/style-templates`, `GET /api/assets/style-templates/{id}`, `GET /api/assets/experience-cards`, `GET /api/assets/experience-cards/{id}`, and `GET /api/projects/{pid}/asset-recommendations?engineOptionId=...`.

- [ ] **Step 4: Verify unit/API and Disposable MySQL GREEN**

```powershell
python -m pytest backend/tests/unit/test_asset_recommendation.py backend/tests/api/test_asset_routes.py -q
python -m pytest backend/tests/integration/test_asset_seeding.py -m mysql -q
```

- [ ] **Step 5: Commit asset persistence**

```powershell
git add backend/repositories/assets.py backend/services/assets.py backend/scripts/seed_writer_assets.py backend/routers/assets.py backend/tests/unit/test_asset_recommendation.py backend/tests/api/test_asset_routes.py backend/tests/integration/test_asset_seeding.py
git commit -m "feat: seed immutable writing assets"
```

### Task 4: Shared path containment and SPA fallback fix

**Files:**
- Create: `backend/security/paths.py`
- Modify: `backend/config.py`
- Create: `backend/tests/unit/test_corpus_paths.py`
- Create: `backend/tests/api/test_static_path_containment.py`

- [ ] **Step 1: Write traversal/reparse RED tests**

Cover absolute paths, `..`, mixed separators, percent-encoded traversal, `.txt.exe`, symlink/junction escape, case-insensitive Windows root behavior, and SPA reads outside `frontend/dist`.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_corpus_paths.py backend/tests/api/test_static_path_containment.py -q
```

- [ ] **Step 3: Implement one containment primitive**

```python
# backend/security/paths.py
from pathlib import Path, PurePath


class UnsafeLocalPath(ValueError):
    pass


def resolve_under_root(root: Path, relative: str, *, suffix: str | None = None) -> Path:
    candidate_input = PurePath(relative)
    if candidate_input.is_absolute() or ".." in candidate_input.parts:
        raise UnsafeLocalPath("path must remain relative to the configured root")
    resolved_root = Path(root).resolve(strict=True)
    resolved = (resolved_root / Path(relative)).resolve(strict=True)
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafeLocalPath("path escapes the configured root") from exc
    if suffix is not None and resolved.suffix.casefold() != suffix.casefold():
        raise UnsafeLocalPath(f"path must end with {suffix}")
    if not resolved.is_file():
        raise UnsafeLocalPath("path must identify a regular file")
    return resolved
```

Add a separately validated `CORPUS_ROOT` config value that is never included in the MySQL connector dict. Add a pure `resolve_spa_file(frontend_dist, decoded_path)` helper that uses the same containment primitive. The later M2BC join task wires it into `backend/main.py`; this parallel branch does not edit global app registration.

- [ ] **Step 4: Verify GREEN and existing secret config tests**

```powershell
python -m pytest backend/tests/unit/test_corpus_paths.py backend/tests/api/test_static_path_containment.py backend/tests/unit/test_config.py -q
```

- [ ] **Step 5: Commit the shared safety boundary**

```powershell
git add backend/security/paths.py backend/config.py backend/tests/unit/test_corpus_paths.py backend/tests/api/test_static_path_containment.py backend/tests/unit/test_config.py
git commit -m "fix: contain corpus and static file paths"
```

### Task 5: Pure corpus decode, chapter, fragment, and index pipeline

**Files:**
- Create: `backend/domain/corpus.py`
- Create: `backend/tests/unit/test_corpus_decoding.py`
- Create: `backend/tests/unit/test_corpus_parser.py`
- Create: `backend/tests/unit/test_corpus_fragmenter.py`

- [ ] **Step 1: Generate byte fixtures under `tmp_path` and write RED tests**

Tests write small original synthetic text at runtime in UTF-8, UTF-8 BOM, and GB18030, with Chinese multibyte characters, CRLF/LF, preface whitespace and chapter headings. Assert SHA-256 over raw bytes, deterministic encoding, monotonic half-open byte/character ranges, and for every chapter: decode the exact `raw_bytes[start:end]` with the detected encoding, apply the named normalizer, and obtain exactly `normalized_text`. Gaps are allowed only when their decoded normalized value is empty. Assert deterministic fragments, strict index metadata, invalid bytes failure, and no committed `.txt` fixture.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_corpus_decoding.py backend/tests/unit/test_corpus_parser.py backend/tests/unit/test_corpus_fragmenter.py -q
```

- [ ] **Step 3: Implement pure versioned transforms**

Expose constants `PARSER_VERSION`, `NORMALIZER_VERSION`, `FRAGMENTER_VERSION`, `INDEX_VERSION`, `PREVIEW_DEFAULT_CHARS=600`, `PREVIEW_MAX_CHARS=1200`, `FRAGMENT_PAGE_DEFAULT=10`, `FRAGMENT_PAGE_MAX=20`, and `FRAGMENT_PREVIEW_CHARS=240`. `decode_source(raw: bytes)` tries UTF-8 BOM, strict UTF-8, then strict GB18030. `parse_chapters` retains exact half-open byte and normalized-char boundaries and explicitly accounts for BOM/newline normalization. `fragment_chapter` emits bounded, non-overlapping stable fragments. Each strict index payload is exactly `{schemaVersion, fragmentId, chapterId, contentHash, normalizerVersion}`; it contains no normalized text, raw text, source path or absolute path. The searchable DB index references `corpus_fragments.id/content_hash` and indexes the existing `normalized_text` column without storing a second copy. No pure function reads a path or writes DB.

- [ ] **Step 4: Run focused tests GREEN**

Run Step 2. Expected: all pass, same input/version yields identical hashes and boundaries.

- [ ] **Step 5: Commit pure corpus domain**

```powershell
git add backend/domain/corpus.py backend/tests/unit/test_corpus_decoding.py backend/tests/unit/test_corpus_parser.py backend/tests/unit/test_corpus_fragmenter.py
git commit -m "feat: parse and fragment local corpus text"
```

### Task 6: Atomic corpus import and bounded APIs

**Files:**
- Create: `backend/repositories/corpus.py`
- Create: `backend/services/corpus_import.py`
- Create: `backend/routers/corpus.py`
- Create: `backend/scripts/verify_corpus_import.py`
- Create: `backend/tests/unit/test_corpus_discovery.py`
- Create: `backend/tests/unit/test_verify_corpus_import.py`
- Create: `backend/tests/api/test_corpus_routes.py`
- Create: `backend/tests/integration/test_corpus_import.py`

- [ ] **Step 1: Write idempotency/rollback/API RED tests**

Test bounded discovery plus same key/request replay, same key/different request conflict, same source hash+same four analysis versions dedupe, identical bytes with any parser/normalizer/fragmenter/index version change creating a new immutable source revision, source+chapters+fragments atomic publication, injected failure zero published rows, relative-path-only storage, and no root/full-book API. Preview tests require default 600/max 1200 characters, reject `previewChars>1200` with 422, default 10/max 20 fragments, exactly at most 240 preview characters per fragment and at most 4800 preview characters across the response; client parameters cannot raise those server constants. The read-only verifier receipt exposes relative path, raw hash, encoding, size, chapter/fragment counts, first/last byte+char bounds, all four versions and import status—never absolute path or text.

Discovery tests require a fixed maximum 200 entries/page and return only `relativePath`, byte size and stable preflight status for eligible `.txt`; skipped non-txt, unreadable, traversal and reparse entries appear only as reason counts. Root/absolute paths never appear.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_corpus_discovery.py backend/tests/unit/test_verify_corpus_import.py backend/tests/api/test_corpus_routes.py -q
```

- [ ] **Step 3: Implement transaction-outside parsing and transaction-inside publication**

Discovery enumerates only direct/approved recursive `.txt` entries under the configured resolved root, applies containment to every result, sorts by normalized relative path, and paginates at at most 200. Import has three phases: (1) containment plus read/hash, (2) short transaction reserve/replay of the import run, then commit, (3) transaction-outside decode/parse/fragment. Decode/parse failure opens a separate transaction to mark the run failed safely; success opens one publication transaction inserting immutable source revision, chapters, fragments/index and marking succeeded. Any publication failure rolls back all published rows and records only a safe failed run. API responses return source name, relative identifier, short hash, encoding, state and counts; preview is bounded and no download route exists.

`verify_corpus_import.py` accepts a database name plus source ID/hash, uses SELECT statements only, and emits the bounded fields asserted above. Unit tests inject a session and assert DDL/DML verbs and secret/path/text sentinels are absent from both SQL and receipt.

Freeze corpus routes as bounded `GET /api/corpus/discovery?cursor=&limit=`, `POST /api/corpus/imports`, `GET /api/corpus/imports/{import_id}`, `GET /api/corpus/sources`, `GET /api/corpus/sources/{source_id}`, `GET /api/corpus/sources/{source_id}/chapters`, and bounded `GET /api/corpus/chapters/{chapter_id}/fragments`.

- [ ] **Step 4: Verify API and MySQL GREEN**

```powershell
python -m pytest backend/tests/unit/test_corpus_discovery.py backend/tests/unit/test_verify_corpus_import.py backend/tests/api/test_corpus_routes.py -q
python -m pytest backend/tests/integration/test_corpus_import.py -m mysql -q
if (-not $env:APPROVED_M2_PLAN_COMMIT) { throw 'APPROVED_M2_PLAN_COMMIT is required' }
$newRawText = @(git diff --name-only "$env:APPROVED_M2_PLAN_COMMIT...HEAD" -- '*.txt' '*.TXT' '*.epub' '*.mobi')
if ($newRawText.Count -gt 0) { throw "New tracked raw-book extension requires explicit rejection/review: $($newRawText -join ', ')" }
```

Expected: tests exit 0 and no baseline-new `.txt/.TXT/.epub/.mobi` exists. Execution must set `APPROVED_M2_PLAN_COMMIT` to the recorded plan commit; an absent value is a hard precondition failure, not an empty diff.

- [ ] **Step 5: Commit and run the M2C checkpoint**

```powershell
git add backend/repositories/corpus.py backend/services/corpus_import.py backend/routers/corpus.py backend/scripts/verify_corpus_import.py backend/tests/unit/test_corpus_discovery.py backend/tests/unit/test_verify_corpus_import.py backend/tests/api/test_corpus_routes.py backend/tests/integration/test_corpus_import.py
git commit -m "feat: import and index local corpus"
python -m pytest backend/tests/unit/test_asset_models.py backend/tests/unit/test_asset_manifest.py backend/tests/unit/test_corpus_paths.py backend/tests/unit/test_corpus_decoding.py backend/tests/unit/test_corpus_parser.py backend/tests/unit/test_corpus_fragmenter.py -q
git diff --check
```

Stop for asset-content and code review. Do not import a real novel or seed the product DB until M2E's explicit L4/product checkpoints.
