# M2 Reset Seed Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the guarded one-time M1-to-M2 reset so the exact historical thirteen-field M1 seeds are integrity-checked and deterministically converted into the current nine-field seed contract without adding runtime compatibility.

**Architecture:** Keep source-version handling inside `reset_writer_core_data.py`, with distinct M1 and M2 seed mappers. The M1 mapper validates the historical envelope hash and status convention before creating a current `SeedPayload`; the M2 mapper remains strict to current JSON, hash, and candidate status. Update the real disposable-MySQL fixture to reproduce the actual M1 representation and prove dry-run, execute, and M2 no-op in sequence.

**Tech Stack:** Python 3.12, Pydantic v2, pytest/pytest-asyncio, aiomysql, MySQL 8 disposable schemas, existing canonical JSON/hash helpers.

---

### Task 1: Freeze the real M1 seed contract in unit tests

**Files:**
- Modify: `backend/tests/unit/test_reset_writer_core_data.py`

- [ ] **Step 1: Import the separate current-state mapper**

Extend the reset-script import list with the function that Task 2 will add:

```python
from backend.scripts.reset_writer_core_data import (
    # existing imports remain
    _map_m1_seed,
    _map_v11_seed,
)
```

- [ ] **Step 2: Add exact historical fixture builders**

Add these helpers next to `_seed_payload`:

```python
M1_PREMISE_FIELDS = (
    "genre", "logline", "protagonist", "desire", "coreConflict",
    "worldPressure", "openingHook", "emotionalPromise",
    "differentiation", "styleTarget", "source", "riskNotes",
    "endingAnchor",
)


def _m1_premise(title):
    return {
        "genre": "历史穿越",
        "logline": f"{title}的测试梗概",
        "protagonist": "测试主角",
        "desire": "完成目标",
        "coreConflict": "守住唯一事实源",
        "worldPressure": "时间窗口收紧",
        "openingHook": "一页异常典籍出现",
        "emotionalPromise": "读者看见普通人逐步改变时代",
        "differentiation": "只用于重建测试",
        "styleTarget": "通俗、具体、以故事推进",
        "source": "user",
        "riskNotes": "避免设定堆砌",
        "endingAnchor": "",
    }


def _m1_seed_row(title="典镇山河", **changes):
    premise = _m1_premise(title)
    row = {
        "id": "seed",
        "project_id": "project",
        "title": title,
        "premise_json": canonical_json(premise),
        "content_hash": canonical_hash({"title": title, "premise": premise}),
        "status": "selected" if title == "典镇山河" else "candidate",
        "created_at": 1,
    }
    row.update(changes)
    return row
```

- [ ] **Step 3: Replace the false M1 nine-field success test**

Replace `test_seed_mapping_preserves_exact_validated_nine_field_payload` with:

```python
def test_m1_seed_mapping_converts_exact_historical_envelope_to_current_payload():
    row = _m1_seed_row()

    mapped = _map_m1_seed(row, "project")

    expected = SeedPayload(
        title="典镇山河",
        **{
            field: _m1_premise("典镇山河")[field]
            for field in (
                "genre", "logline", "protagonist", "desire",
                "coreConflict", "worldPressure", "openingHook",
                "differentiation",
            )
        },
    )
    assert mapped["payload_json"] == canonical_json(expected)
    assert mapped["content_hash"] == canonical_hash(expected)
    assert mapped["status"] == "candidate"
    assert set(json.loads(mapped["payload_json"])) == set(SeedPayload.model_fields)
    assert not set(json.loads(mapped["payload_json"])) & {
        "emotionalPromise", "styleTarget", "source", "riskNotes",
        "endingAnchor",
    }
```

- [ ] **Step 4: Add closed-source and status failure tests**

Add focused tests that each call `_map_m1_seed` and expect
`ResetValidationError`:

```python
@pytest.mark.parametrize(
    "mutate",
    (
        lambda premise: premise.pop("riskNotes"),
        lambda premise: premise.__setitem__("legacyExtra", "forbidden"),
        lambda premise: premise.__setitem__("source", 1),
        lambda premise: premise.__setitem__("openingHook", ""),
    ),
)
def test_m1_seed_mapping_rejects_non_exact_or_invalid_historical_premise(mutate):
    premise = _m1_premise("典镇山河")
    mutate(premise)
    row = _m1_seed_row(
        premise_json=canonical_json(premise),
        content_hash=canonical_hash({
            "title": "典镇山河",
            "premise": premise,
        }),
    )

    with pytest.raises(ResetValidationError):
        _map_m1_seed(row, "project")


def test_m1_seed_mapping_rejects_historical_envelope_hash_mismatch():
    with pytest.raises(ResetValidationError, match="content_hash"):
        _map_m1_seed(_m1_seed_row(content_hash="0" * 64), "project")


@pytest.mark.parametrize("premise_json", ("[]", "null"))
def test_m1_seed_mapping_rejects_non_object_json(premise_json):
    with pytest.raises(ResetValidationError, match="historical object"):
        _map_m1_seed(
            _m1_seed_row(
                premise_json=premise_json,
                content_hash="0" * 64,
            ),
            "project",
        )


def test_m1_seed_mapping_rejects_oversized_retained_field():
    premise = _m1_premise("典镇山河")
    premise["openingHook"] = "x" * 2001
    row = _m1_seed_row(
        premise_json=canonical_json(premise),
        content_hash=canonical_hash({
            "title": "典镇山河",
            "premise": premise,
        }),
    )
    with pytest.raises(ResetValidationError, match="current SeedPayload"):
        _map_m1_seed(row, "project")


@pytest.mark.parametrize(
    ("title", "status"),
    (
        ("典镇山河", "candidate"),
        ("永乐长明", "selected"),
        ("文渊山海", "archived"),
    ),
)
def test_m1_seed_mapping_rejects_wrong_historical_status(title, status):
    with pytest.raises(ResetValidationError, match="status"):
        _map_m1_seed(_m1_seed_row(title, status=status), "project")
```

- [ ] **Step 5: Add the strict M2 readback test**

```python
def test_v11_seed_mapping_accepts_only_current_payload_and_candidate_status():
    payload = _seed_payload("典镇山河")
    current = {
        "id": "seed",
        "project_id": "project",
        "title": payload.title,
        "premise_json": canonical_json(payload),
        "content_hash": canonical_hash(payload),
        "status": "candidate",
        "created_at": 1,
    }

    mapped = _map_v11_seed(current, "project")
    assert mapped["payload_json"] == canonical_json(payload)

    with pytest.raises(ResetValidationError):
        _map_v11_seed(_m1_seed_row(), "project")
    with pytest.raises(ResetValidationError, match="candidates"):
        _map_v11_seed({**current, "status": "selected"}, "project")
```

- [ ] **Step 6: Route current test-state construction through the current mapper**

In `_foundation_state_values`, replace the mapper used for the current
nine-field fixture:

```python
seeds.append(_map_v11_seed({
    "id": f"seed-{index}",
    "project_id": "project",
    "title": title,
    "premise_json": canonical_json(payload),
    "content_hash": canonical_hash(payload),
    "status": "candidate",
    "created_at": 1,
}, "project"))
```

This helper represents current M2 insertion/report state and must never use the
historical M1 mapper.

- [ ] **Step 7: Run the new tests and verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_reset_writer_core_data.py -q -k "m1_seed_mapping or v11_seed_mapping"
```

Expected: collection fails because `_map_v11_seed` does not exist, or the
historical M1 success case fails because `_map_m1_seed` rejects the
thirteen-field payload.

- [ ] **Step 8: Commit the red contract**

```powershell
git add backend/tests/unit/test_reset_writer_core_data.py
git commit -m "test: reproduce M1 seed reset contract"
```

### Task 2: Separate the M1 conversion from strict M2 readback

**Files:**
- Modify: `backend/scripts/reset_writer_core_data.py`
- Test: `backend/tests/unit/test_reset_writer_core_data.py`

- [ ] **Step 1: Define the closed field sets**

Add beside `_M1_SEED_COLUMNS`:

```python
_M1_PREMISE_FIELDS = frozenset({
    "genre", "logline", "protagonist", "desire", "coreConflict",
    "worldPressure", "openingHook", "emotionalPromise",
    "differentiation", "styleTarget", "source", "riskNotes",
    "endingAnchor",
})
_M2_RETAINED_PREMISE_FIELDS = (
    "genre", "logline", "protagonist", "desire", "coreConflict",
    "worldPressure", "openingHook", "differentiation",
)
```

- [ ] **Step 2: Extract one current mapped-row builder**

Add a private helper that receives already validated identity values and a
current `SeedPayload`:

```python
def _mapped_seed(
    *,
    seed_id: str,
    owner_id: str,
    title: str,
    payload: SeedPayload,
    created_at: int,
) -> dict[str, object]:
    return {
        "id": seed_id,
        "project_id": owner_id,
        "title": title,
        "status": "candidate",
        "payload_json": canonical_json(payload),
        "content_hash": canonical_hash(payload),
        "created_at": created_at,
        "updated_at": created_at,
    }
```

- [ ] **Step 3: Implement exact historical M1 conversion**

Replace the current `_map_m1_seed` body with logic equivalent to:

```python
def _map_m1_seed(row, project_id):
    seed_id = _identifier(row["id"], "seed.id")
    owner_id = _identifier(row["project_id"], "seed.project_id")
    if owner_id != project_id:
        raise ResetValidationError("M1 requested seed belongs to another project")
    title = _text(row["title"], "seed.title", max_length=200)
    try:
        decoded = (
            json.loads(row["premise_json"])
            if isinstance(row["premise_json"], str)
            else row["premise_json"]
        )
    except (TypeError, ValueError):
        raise ResetValidationError(
            "M1 seed premise_json is not the exact historical object"
        ) from None
    if (
        type(decoded) is not dict
        or set(decoded) != _M1_PREMISE_FIELDS
        or any(type(decoded[field]) is not str for field in _M1_PREMISE_FIELDS)
    ):
        raise ResetValidationError(
            "M1 seed premise_json is not the exact historical object"
        )
    historical_hash = canonical_hash({"title": title, "premise": decoded})
    if row["content_hash"] != historical_hash:
        raise ResetValidationError(
            "M1 seed content_hash does not match the historical envelope"
        )
    expected_status = "selected" if title == SELECTED_SEED_TITLE else "candidate"
    if _text(row["status"], "seed.status", max_length=24) != expected_status:
        raise ResetValidationError("M1 seed status does not match its selection role")
    try:
        payload = SeedPayload(
            title=title,
            **{
                field: decoded[field]
                for field in _M2_RETAINED_PREMISE_FIELDS
            },
        )
    except (TypeError, ValueError):
        raise ResetValidationError(
            "M1 seed retained fields are not a valid current SeedPayload"
        ) from None
    return _mapped_seed(
        seed_id=seed_id,
        owner_id=owner_id,
        title=title,
        payload=payload,
        created_at=_integer(row["created_at"], "seed.created_at"),
    )
```

Do not include decoded premise values in exception messages or logs.

- [ ] **Step 4: Implement strict current M2 readback**

Add `_map_v11_seed(row, project_id)` using the current nine-field validation,
canonical hash check, and `status == "candidate"` check:

```python
def _map_v11_seed(row, project_id):
    seed_id = _identifier(row["id"], "seed.id")
    owner_id = _identifier(row["project_id"], "seed.project_id")
    if owner_id != project_id:
        raise ResetValidationError("M2 requested seed belongs to another project")
    title = _text(row["title"], "seed.title", max_length=200)
    try:
        decoded = (
            json.loads(row["premise_json"])
            if isinstance(row["premise_json"], str)
            else row["premise_json"]
        )
        payload = SeedPayload.model_validate(decoded)
    except (TypeError, ValueError):
        raise ResetValidationError(
            "M2 seed payload is not a valid current SeedPayload"
        ) from None
    if payload.title != title:
        raise ResetValidationError("M2 seed title and payload disagree")
    if row["content_hash"] != canonical_hash(payload):
        raise ResetValidationError("M2 seed content_hash does not match payload")
    if _text(row["status"], "seed.status", max_length=24) != "candidate":
        raise ResetValidationError("M2 seed identities must remain candidates")
    return _mapped_seed(
        seed_id=seed_id,
        owner_id=owner_id,
        title=title,
        payload=payload,
        created_at=_integer(row["created_at"], "seed.created_at"),
    )
```

- [ ] **Step 5: Route M2 readback only through the current mapper**

In `_load_v11_preserved_state`, replace:

```python
seeds = tuple(_map_m1_seed(row, str(project["id"])) for row in seed_rows)
```

with:

```python
seeds = tuple(_map_v11_seed(row, str(project["id"])) for row in seed_rows)
```

The M1 loader continues to call only `_map_m1_seed`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```powershell
python -m pytest backend/tests/unit/test_reset_writer_core_data.py -q -k "seed_mapping"
```

Expected: all selected mapping tests pass.

- [ ] **Step 7: Run the complete reset unit module**

Run:

```powershell
python -m pytest backend/tests/unit/test_reset_writer_core_data.py -q
```

Expected: exit `0`, no failures.

- [ ] **Step 8: Commit the mapper implementation**

```powershell
git add backend/scripts/reset_writer_core_data.py backend/tests/unit/test_reset_writer_core_data.py
git commit -m "fix: map exact M1 seeds into M2"
```

### Task 3: Reconcile the real disposable-MySQL reset fixture

**Files:**
- Modify: `backend/tests/integration/test_milestone2_product_rebuild.py`

- [ ] **Step 1: Add an exact M1 premise builder**

Keep `seed_payload` for current-state assertions and add:

```python
def m1_seed_premise(title):
    current = seed_payload(title)
    return {
        "genre": current.genre,
        "logline": current.logline,
        "protagonist": current.protagonist,
        "desire": current.desire,
        "coreConflict": current.coreConflict,
        "worldPressure": current.worldPressure,
        "openingHook": current.openingHook,
        "emotionalPromise": "读者看见普通人逐步改变时代",
        "differentiation": current.differentiation,
        "styleTarget": "通俗、具体、以故事推进",
        "source": "user",
        "riskNotes": "避免设定堆砌",
        "endingAnchor": "",
    }
```

- [ ] **Step 2: Make the M1 fixture reproduce product data**

Replace the seed insert loop with:

```python
for seed_id, title in SEEDS:
    premise = m1_seed_premise(title)
    historical_hash = canonical_hash({
        "title": title,
        "premise": premise,
    })
    status = "selected" if title == "典镇山河" else "candidate"
    await session.execute(
        "INSERT INTO creative_seeds VALUES (%s,%s,%s,%s,%s,%s,1)",
        (
            seed_id,
            PROJECT_ID,
            title,
            canonical_json(premise),
            historical_hash,
            status,
        ),
    )
```

- [ ] **Step 3: Assert the target contains only current seed facts**

After the first execute and before the verifier closes, query:

```python
rows = await session.fetchall(
    "SELECT s.status,r.payload_json,r.content_hash "
    "FROM creative_seeds s "
    "JOIN creative_seed_heads h ON h.seed_id=s.id "
    "JOIN creative_seed_revisions r ON r.id=h.revision_id "
    "ORDER BY s.id"
)
assert {row["status"] for row in rows} == {"candidate"}
for row in rows:
    payload = json.loads(row["payload_json"])
    assert set(payload) == set(SeedPayload.model_fields)
    assert row["content_hash"] == canonical_hash(payload)
```

The existing verifier assertion must still prove the single selected seed is
`典镇山河`.

- [ ] **Step 4: Run the real disposable-MySQL rebuild test**

Run:

```powershell
python -m pytest backend/tests/integration/test_milestone2_product_rebuild.py::test_exact_m1_rebuilds_to_fresh_m2_then_execute_is_idempotent_noop -q -m mysql
```

Expected: one pass; the fixture database is automatically dropped.

- [ ] **Step 5: Run the complete product rebuild integration module**

Run:

```powershell
python -m pytest backend/tests/integration/test_milestone2_product_rebuild.py -q -m mysql
```

Expected: exit `0`; all disposable databases cleaned.

- [ ] **Step 6: Commit the real-data integration coverage**

```powershell
git add backend/tests/integration/test_milestone2_product_rebuild.py
git commit -m "test: verify real M1 seed rebuild"
```

### Task 4: Repository verification and review handoff

**Files:**
- Verify: `backend/scripts/reset_writer_core_data.py`
- Verify: `backend/tests/unit/test_reset_writer_core_data.py`
- Verify: `backend/tests/integration/test_milestone2_product_rebuild.py`
- Verify: `docs/superpowers/specs/2026-07-17-m2-reset-seed-mapping-design.md`

- [ ] **Step 1: Run the focused regression set**

```powershell
python -m pytest backend/tests/unit/test_reset_writer_core_data.py backend/tests/integration/test_milestone2_product_rebuild.py -q
```

Expected: exit `0`.

- [ ] **Step 2: Run the repository deterministic gate**

```powershell
npm test
```

Expected: exit `0`.

- [ ] **Step 3: Run the M2 integration gate**

```powershell
npm run test:integration
```

Expected: exit `0`, with zero remaining disposable databases.

- [ ] **Step 4: Check the final diff**

```powershell
git diff --check main...HEAD
git status --short
git diff --stat main...HEAD
git diff main...HEAD -- backend/scripts/reset_writer_core_data.py backend/tests/unit/test_reset_writer_core_data.py backend/tests/integration/test_milestone2_product_rebuild.py
```

Confirm:

- no router, runtime service, schema, frontend, or Provider-call path changed;
- no raw premise, API key, Base URL, password, DSN, notes, or thinking value is
  emitted;
- M1 and M2 seed mappers are separate;
- only the exact five retired M1 fields are discarded;
- product DB execution has not occurred.

- [ ] **Step 5: Obtain two independent reviews**

Request:

1. specification review against
   `docs/superpowers/specs/2026-07-17-m2-reset-seed-mapping-design.md`;
2. code-quality/security-boundary review of `main...HEAD`.

P0/P1/P2 findings must be fixed and the affected test gates rerun before
integration.

- [ ] **Step 6: Hand off to the product-control thread**

Report exact commit IDs, test counts, review verdicts, and that the product
database remains unchanged. The product-control thread then merges the branch,
reruns the guarded product dry-run, and presents the allowlisted receipt for a
separate destructive execute confirmation.
