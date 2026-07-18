# Provider Callability Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every Provider readiness and generation surface accept only active, enabled, exact `openai-compatible` profiles with nonblank model, base URL, and API key, without imposing secret-scanning length thresholds.

**Architecture:** Add a pure domain policy module containing the canonical supported type and mapping predicate. Python consumers call that predicate directly; SQL repositories interpolate only the canonical type constant while retaining their repository-specific aliases and query shapes. Story generation composes the shared readiness result with its existing frozen-model and generation-config checks.

**Tech Stack:** Python 3.12, pytest, FastAPI/Pydantic, MySQL SQL repositories, Node/Vite verification.

---

### Task 1: Prove the current policy divergence

**Files:**
- Modify: `backend/tests/unit/test_story_engine_service.py`
- Modify: `backend/tests/unit/test_model_binding_service.py`
- Modify: `backend/tests/unit/test_provider_type_readiness_repositories.py`

- [ ] **Step 1: Add failing story-generation tests**

Add tests that set the fake Provider API key to `"short"` and require a successful fake-gateway call for `openai-compatible`, then set `provider_type` to `"openai"` and require `provider_configuration` with zero gateway calls.

- [ ] **Step 2: Add failing cross-surface policy tests**

Use the same Provider mappings to assert the public DTO, binding predicate, and story callability agree. Assert repository SQL contains the canonical generation type and the nonblank model/base/key conditions.

- [ ] **Step 3: Verify RED**

Run:

```powershell
python -m pytest backend/tests/unit/test_story_engine_service.py backend/tests/unit/test_model_binding_service.py backend/tests/unit/test_provider_type_readiness_repositories.py -q
```

Expected: the short-key story case fails without calling the gateway, the legacy `openai` story case unexpectedly calls the gateway, and the new domain policy import is unavailable.

### Task 2: Introduce and propagate the canonical policy

**Files:**
- Create: `backend/domain/provider_policy.py`
- Modify: `backend/gateways/provider_connection.py`
- Modify: `backend/routers/providers.py`
- Modify: `backend/serializers/provider.py`
- Modify: `backend/services/model_bindings.py`
- Modify: `backend/services/provider_profiles.py`
- Modify: `backend/services/story_engines.py`
- Modify: `backend/repositories/model_bindings.py`
- Modify: `backend/repositories/contracts.py`
- Modify: `backend/repositories/chapter_sessions.py`

- [ ] **Step 1: Implement the pure policy**

Define:

```python
GENERATION_PROVIDER_TYPE = "openai-compatible"
SUPPORTED_PROVIDER_TYPES = frozenset({GENERATION_PROVIDER_TYPE})

def provider_type_is_supported(value: object) -> bool:
    return isinstance(value, str) and value.strip().casefold() in SUPPORTED_PROVIDER_TYPES

def provider_is_generation_ready(row: Mapping, *, prefix: str = "") -> bool:
    def value(name: str):
        return row.get(f"{prefix}{name}")

    return (
        value("lifecycle_status") == "active"
        and int(value("enabled") or 0) == 1
        and provider_type_is_supported(value("provider_type"))
        and all(
            isinstance(value(field), str) and bool(value(field).strip())
            for field in ("model_name", "base_url", "api_key")
        )
    )
```

- [ ] **Step 2: Reuse it in Python surfaces**

Replace gateway-owned type policy imports and duplicated DTO/binding/story conditions with domain policy imports. Keep story generation's model-snapshot equality and generation-config validation as additional checks. Do not change response secret scanning.

- [ ] **Step 3: Reuse the canonical type in SQL**

Interpolate `GENERATION_PROVIDER_TYPE` into model-binding, contract, and chapter repository SQL. Preserve active/enabled and nonblank model/base/key predicates.

- [ ] **Step 4: Verify GREEN**

Run the focused command from Task 1 and require all selected tests to pass.

### Task 3: Verify release behavior and commit

**Files:**
- Verify all files above.

- [ ] **Step 1: Run affected tests**

```powershell
python -m pytest backend/tests/unit/test_story_engine_service.py backend/tests/unit/test_provider_profile_service.py backend/tests/unit/test_provider_connection_gateway.py backend/tests/unit/test_model_binding_service.py backend/tests/unit/test_provider_type_readiness_repositories.py backend/tests/api/test_provider_redaction.py backend/tests/api/test_model_binding_routes.py -q
```

- [ ] **Step 2: Run relevant and full integration**

```powershell
python -m pytest backend/tests/integration/test_story_engine_batches.py backend/tests/integration/test_contract_drafts.py backend/tests/integration/test_contract_confirmation.py backend/tests/integration/test_model_binding_revisions.py -m mysql -q
npm run test:integration
```

Require disposable MySQL cleanup to report zero remaining schemas.

- [ ] **Step 3: Run release gates**

```powershell
npm test
npm --prefix frontend run build
python -m compileall -q backend
git diff --check
```

- [ ] **Step 4: Complete internal review**

Review the staged diff for policy duplication, reverse layer imports, short-secret callability regressions, legacy-type execution, and unintended Task 3 changes.

- [ ] **Step 5: Commit**

```powershell
git add backend docs/superpowers/plans/2026-07-19-provider-callability-policy.md
git commit -m "fix: unify provider callability policy"
```
