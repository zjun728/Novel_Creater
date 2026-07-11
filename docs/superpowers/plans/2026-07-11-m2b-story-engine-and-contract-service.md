# M2B Story Engine and Contract Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver auditable manual/Provider story-engine batches and append-only CreationContract/StyleContract draft, preview, confirmation, history, idempotency, and readiness APIs.

**Architecture:** A focused backend Gateway receives one frozen `seed` binding and performs at most one outbound attempt outside all DB transactions. Story-engine and contract services own idempotency/CAS/transaction orchestration; repositories contain only session-bound persistence. Provider tests use injected transports only—real Provider execution is reserved for M2E L5.

**Tech Stack:** Python 3.12, Pydantic, FastAPI, aiomysql, httpx MockTransport, MySQL 8.4, pytest.

---

### Task 1: Strict StoryEngine and contract domain contracts

**Files:**
- Create: `backend/domain/story_engines.py`
- Create: `backend/domain/contracts.py`
- Create: `backend/tests/unit/test_story_engine_domain.py`
- Create: `backend/tests/unit/test_contract_domain.py`

- [ ] **Step 1: Write RED tests for exact option shape and canonical preview**

```python
import pytest
from pydantic import ValidationError

from backend.domain.story_engines import StoryEngineOption, validate_three_options
from backend.domain.contracts import CreationContractPayload, StyleContractPayload


def engine(name: str, promise: str, loop: str, cost: str) -> StoryEngineOption:
    return StoryEngineOption(
        name=name, storyPromise=promise, protagonistDesire="掌握命运", sustainedPressure="权力围堵",
        growthDirection="从求生到建制", conflictLoop=loop,
        ensembleRoles=[{"role":"工匠集团","purpose":"技术落地"}],
        advantageAndCost=cost, satisfactionSources=["解决现实难题"],
        longFormVariation=["地方经营","朝堂博弈"], endingAnchor="建立可持续秩序",
        risks=["升级重复"], differentiation=f"{name} 的独有路径",
    )


def test_three_options_require_structural_difference():
    options = (
        engine("典籍权谋", "夺回典籍", "知识换权力", "暴露来历"),
        engine("工坊经营", "建立工坊", "产能换资源", "技术扩散"),
        engine("边地群像", "守住边城", "联盟换生存", "盟友反噬"),
    )
    validate_three_options(options)
    with pytest.raises(ValueError):
        validate_three_options((options[0], options[0].model_copy(update={"name":"改名"}), options[2]))
```

Add tests that CreationContract contains `qualityCharterVersion` but no rubric/checklist field; StyleContract requires primary style, allows one distinct secondary, and rejects unknown fields.

- [ ] **Step 2: Run focused tests and verify RED**

```powershell
python -m pytest backend/tests/unit/test_story_engine_domain.py backend/tests/unit/test_contract_domain.py -q
```

Expected: the two modules are missing.

- [ ] **Step 3: Implement strict frozen models and deterministic difference keys**

```python
# backend/domain/story_engines.py
from pydantic import BaseModel, ConfigDict, Field


class EnsembleRole(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    role: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=300)


class StoryEngineOption(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    storyPromise: str = Field(min_length=1, max_length=600)
    protagonistDesire: str = Field(min_length=1, max_length=300)
    sustainedPressure: str = Field(min_length=1, max_length=500)
    growthDirection: str = Field(min_length=1, max_length=500)
    conflictLoop: str = Field(min_length=1, max_length=600)
    ensembleRoles: tuple[EnsembleRole, ...] = Field(min_length=1)
    advantageAndCost: str = Field(min_length=1, max_length=600)
    satisfactionSources: tuple[str, ...] = Field(min_length=1)
    longFormVariation: tuple[str, ...] = Field(min_length=1)
    endingAnchor: str = Field(min_length=1, max_length=600)
    risks: tuple[str, ...] = Field(min_length=1)
    differentiation: str = Field(min_length=1, max_length=600)


def validate_three_options(options: tuple[StoryEngineOption, ...]) -> None:
    if len(options) != 3:
        raise ValueError("story engine batch requires exactly three options")
    signatures = {(o.storyPromise, o.conflictLoop, o.advantageAndCost, o.endingAnchor) for o in options}
    if len(signatures) != 3:
        raise ValueError("story engine options must differ in structural dimensions")
```

Implement `CreationContractPayload` and `StyleContractPayload` with the exact required JSON fields from approved spec section 5.7 and `extra="forbid"`.

- [ ] **Step 4: Run focused tests GREEN**

Run Step 2. Expected: all domain tests pass without DB/network activity.

- [ ] **Step 5: Commit domain contracts**

```powershell
git add backend/domain/story_engines.py backend/domain/contracts.py backend/tests/unit/test_story_engine_domain.py backend/tests/unit/test_contract_domain.py
git commit -m "feat: define story engine and creation contract domains"
```

### Task 2: Batch persistence, manual path, idempotency, and reconcile

**Files:**
- Create: `backend/repositories/story_engines.py`
- Create: `backend/services/story_engines.py`
- Create: `backend/routers/story_engines.py`
- Create: `backend/tests/support/story_engine_fakes.py`
- Create: `backend/tests/unit/test_story_engine_service.py`
- Create: `backend/tests/api/test_story_engine_routes.py`
- Create: `backend/tests/integration/test_story_engine_batches.py`

- [ ] **Step 1: Write RED tests for all legal transitions**

Test same-key/same-hash replay, same-key/different-hash conflict, manual NULL Provider fields, exactly three options, `reserved -> running -> succeeded|failed`, stale reserved to `failed/not_started`, stale running to `outcome_unknown`, terminal immutability, and reconcile gateway call count zero.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_story_engine_service.py backend/tests/api/test_story_engine_routes.py -q
```

- [ ] **Step 3: Implement one-attempt state orchestration**

```python
class StoryEngineConflict(RuntimeError):
    pass


class StoryEngineService:
    def __init__(self, transaction_factory, repository, gateway, clock, id_factory):
        self.transactions = transaction_factory
        self.repository = repository
        self.gateway = gateway
        self.clock = clock
        self.id_factory = id_factory

    async def reconcile(self, project_id: str, batch_id: str):
        async with self.transactions() as session:
            batch = await self.repository.lock_batch(session, project_id, batch_id)
            reserve_expired = batch["created_at"] + 300_000 <= self.clock()
            if batch["status"] == "reserved" and batch["attempt_id"] is None and reserve_expired:
                return await self.repository.mark_not_started(session, batch_id, self.clock())
            if batch["status"] == "running" and batch["lease_expires_at"] <= self.clock():
                return await self.repository.mark_unknown(session, batch_id, self.clock())
            return batch
```

Freeze `RESERVED_TIMEOUT_MS=300_000`, `PROVIDER_TIMEOUT_SECONDS=180`, and `RUNNING_LEASE_MS=240_000`. `create_manual_batch` validates and hashes all three options, reserves the idempotency record, inserts batch/options, and marks succeeded in one transaction. The Provider path reserves first but does not call the Gateway in this task. `mark_not_started` and every other transition use status/attempt CAS so reconcile cannot terminate a batch that concurrently entered running. Tests advance a fake clock and prove a live in-flight attempt cannot be reconciled before the Provider timeout plus 60-second margin.

Freeze story-engine routes as `POST /api/projects/{pid}/story-engine-batches`, `POST /api/projects/{pid}/story-engine-batches/manual`, `GET /api/projects/{pid}/story-engine-batches/{batch_id}`, and `POST /api/projects/{pid}/story-engine-batches/{batch_id}/reconcile`.

- [ ] **Step 4: Verify unit/API and Disposable MySQL GREEN**

```powershell
python -m pytest backend/tests/unit/test_story_engine_service.py backend/tests/api/test_story_engine_routes.py -q
python -m pytest backend/tests/integration/test_story_engine_batches.py -m mysql -q
```

Expected: transition and DB uniqueness tests pass; outbound call count remains zero.

- [ ] **Step 5: Commit persistence and manual workflow**

```powershell
git add backend/repositories/story_engines.py backend/services/story_engines.py backend/routers/story_engines.py backend/tests/support/story_engine_fakes.py backend/tests/unit/test_story_engine_service.py backend/tests/api/test_story_engine_routes.py backend/tests/integration/test_story_engine_batches.py
git commit -m "feat: persist auditable story engine batches"
```

### Task 3: Focused backend Provider Gateway

**Files:**
- Create: `backend/gateways/__init__.py`
- Create: `backend/gateways/story_engine_provider.py`
- Create: `backend/prompts/__init__.py`
- Create: `backend/prompts/story_engine.py`
- Create: `backend/tests/unit/test_story_engine_gateway.py`
- Create: `backend/tests/unit/test_story_engine_prompt.py`
- Modify: `backend/services/story_engines.py`

- [ ] **Step 1: Write transport-injected RED tests**

Use `httpx.MockTransport` to assert one OpenAI-compatible POST, frozen Provider/model, JSON mode, no DB transaction held during transport, strict response extraction, and public failures with no key/base URL. Assert unbound/deleted/disabled configuration performs zero transport calls. Prompt tests require only the frozen seed payload, channel/genre and strict three-option JSON contract; they reject corpus/source/style examples, full QA rubric, API/base URL fields and imports from old frontend prompts.

- [ ] **Step 2: Run and verify RED**

```powershell
python -m pytest backend/tests/unit/test_story_engine_prompt.py backend/tests/unit/test_story_engine_gateway.py backend/tests/unit/test_story_engine_service.py -q
```

- [ ] **Step 3: Implement the only outbound boundary**

```python
# backend/gateways/story_engine_provider.py
import asyncio
import httpx


class StoryEngineProviderGateway:
    def __init__(self, client_factory=None, timeout_seconds: float = 180.0):
        self.timeout_seconds = timeout_seconds
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=180.0, write=30.0, pool=15.0)
        ))

    async def generate(self, provider: dict, messages: list[dict]) -> str:
        base = provider["base_url"].rstrip("/")
        url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"
        body = {
            "model": provider["model_name"], "messages": messages,
            "temperature": float(provider["temperature"]),
            "max_tokens": int(provider["max_output_tokens"]),
            "response_format": {"type": "json_object"}, "stream": False,
        }
        async with asyncio.timeout(self.timeout_seconds):
            async with self.client_factory() as client:
                response = await client.post(
                    url, headers={"Authorization": f"Bearer {provider['api_key']}", "Content-Type": "application/json"}, json=body,
                )
        response.raise_for_status()
        payload = response.json()
        return payload["choices"][0]["message"]["content"]
```

The service must commit `running` plus `attempt_id/lease` before `generate()`, then open a new transaction to finalize. `asyncio.timeout(180)` is the total whole-call deadline; the 240-second lease is therefore at least 60 seconds longer than any in-process call. Any `TimeoutError` or `httpx.TransportError` after the attempt marker is conservatively `outcome_unknown`; an explicit HTTP error response or strict response/option parse rejection is `failed`; pre-attempt configuration rejection performs zero transport calls and marks a stable configuration failure. Tests freeze every classification. Any expired running attempt reconciles to unknown and is never replayed. Do not import `backend/routers/ai_proxy.py`.

`build_story_engine_messages(seed_snapshot, channel_profile, genre_profile)` returns a system instruction with the lightweight goal “故事具体、人物有欲望和代价、冲突能够长期变化” and a user JSON object containing only those three frozen inputs plus the exact StoryEngine field list. It explicitly requires one JSON object with an `options` array of length 3; it does not include corpus titles/text, style samples, complete quality rubric or negative anti-AI checklist.

- [ ] **Step 4: Verify fake transport and secret gates GREEN**

```powershell
python -m pytest backend/tests/unit/test_story_engine_prompt.py backend/tests/unit/test_story_engine_gateway.py backend/tests/unit/test_story_engine_service.py backend/tests/api/test_secret_error_redaction.py -q
```

Expected: transport count is exactly 0 or 1 per case; secret/base URL sentinel matches zero in public errors/log records.

- [ ] **Step 5: Commit the Gateway**

```powershell
git add backend/gateways/__init__.py backend/gateways/story_engine_provider.py backend/prompts/__init__.py backend/prompts/story_engine.py backend/services/story_engines.py backend/tests/unit/test_story_engine_prompt.py backend/tests/unit/test_story_engine_gateway.py backend/tests/unit/test_story_engine_service.py backend/tests/api/test_secret_error_redaction.py
git commit -m "feat: generate story engines through backend gateway"
```

### Task 4: Recoverable draft and deterministic preview

**Files:**
- Create: `backend/repositories/contracts.py`
- Create: `backend/services/contracts.py`
- Create: `backend/routers/contracts.py`
- Create: `backend/tests/support/contract_fakes.py`
- Create: `backend/tests/unit/test_contract_service.py`
- Create: `backend/tests/api/test_contract_routes.py`

- [ ] **Step 1: Write draft/preview RED tests**

Cover one draft per project, draft-version CAS, initial base head 0, clone from confirmed head, backend reload, exact seed/engine/style/card/source/binding hashes, quality charter version, no full rubric, and `contractReady=false` after seed/binding drift.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_contract_service.py backend/tests/api/test_contract_routes.py -q
```

- [ ] **Step 3: Implement draft save/clone/preview as separate commands**

`save_draft` is the only mutable contract operation and CAS-updates `draft_version`. `preview` is deterministic and read-only: it loads exact immutable refs, assembles strict payloads, computes hashes, and returns readiness reasons. `clone_current` copies the current head into a new draft with `base_head_revision=head.revision`.

Freeze contract routes as `GET|PUT /api/projects/{pid}/contract-draft`, `POST /api/projects/{pid}/contracts/preview`, `POST /api/projects/{pid}/contracts/confirm`, `GET /api/projects/{pid}/contracts/head`, `GET /api/projects/{pid}/contracts/history`, and `POST /api/projects/{pid}/contracts/clone`.

- [ ] **Step 4: Verify GREEN**

Run Step 2. Expected: API/service tests pass; confirmed contract/head row counts remain unchanged.

- [ ] **Step 5: Commit draft/preview**

```powershell
git add backend/repositories/contracts.py backend/services/contracts.py backend/routers/contracts.py backend/tests/support/contract_fakes.py backend/tests/unit/test_contract_service.py backend/tests/api/test_contract_routes.py
git commit -m "feat: persist creation contract drafts"
```

### Task 5: Atomic confirmation, history, API registration, and M2B checkpoint

**Files:**
- Modify: `backend/services/contracts.py`
- Modify: `backend/repositories/contracts.py`
- Modify: `backend/routers/contracts.py`
- Modify: `backend/tests/unit/test_contract_service.py`
- Modify: `backend/tests/api/test_contract_routes.py`
- Create: `backend/tests/integration/test_contract_confirmation.py`

- [ ] **Step 1: Write fail-point and concurrent-confirm RED tests**

Test head 0→1, two first confirms/one winner, eight bindings ready, exact asset heads/hashes, engine ref as canonical relationship, specialized refs, draft deletion, confirmation replay, same-key/different-hash 409, and rollback after every insertion/head/draft-delete fail point.

- [ ] **Step 2: Verify RED**

```powershell
python -m pytest backend/tests/unit/test_contract_service.py backend/tests/api/test_contract_routes.py -q
```

- [ ] **Step 3: Implement one confirmation transaction**

Lock project, selected seed, binding head, contract head and confirmation key. Validate every frozen revision/hash before inserts. Insert CreationContract, StyleContract, engine/style/experience/corpus refs, CAS head, delete draft, and mark confirmation succeeded in the same transaction. On replay return recorded IDs/revision; on hash mismatch raise conflict.

- [ ] **Step 4: Run complete M2B verification**

```powershell
python -m pytest backend/tests/unit/test_story_engine_domain.py backend/tests/unit/test_story_engine_service.py backend/tests/unit/test_story_engine_prompt.py backend/tests/unit/test_story_engine_gateway.py backend/tests/unit/test_contract_domain.py backend/tests/unit/test_contract_service.py -q
python -m pytest backend/tests/api/test_story_engine_routes.py backend/tests/api/test_contract_routes.py -q
python -m pytest backend/tests/integration/test_story_engine_batches.py backend/tests/integration/test_contract_confirmation.py -m mysql -q
git diff --check
```

Expected: all exit 0; no real Provider, product DB, browser or corpus file was touched.

- [ ] **Step 5: Commit and stop for review**

```powershell
git add backend/services/contracts.py backend/repositories/contracts.py backend/routers/contracts.py backend/tests/unit/test_contract_service.py backend/tests/api/test_contract_routes.py backend/tests/integration/test_contract_confirmation.py
git commit -m "feat: confirm creation contracts atomically"
```

Route tests instantiate the new routers in a local FastAPI test app; this parallel branch does not edit global `backend/main.py` or route inventory. Stop for code/spec review. M2B may merge alongside reviewed M2C only after both started from the same M2A checkpoint.
