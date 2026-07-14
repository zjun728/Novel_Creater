from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy

from backend.domain.json_contracts import canonical_json
from backend.domain.story_engines import StoryEngineOption


def option(number: int, *, suffix: str = "") -> StoryEngineOption:
    marker = f"{number}{suffix}"
    return StoryEngineOption(
        name=f"方案 {marker}",
        storyPromise=f"承诺 {marker}",
        protagonistDesire=f"欲望 {marker}",
        sustainedPressure=f"压力 {marker}",
        growthDirection=f"成长 {marker}",
        conflictLoop=f"循环 {marker}",
        ensembleRoles=({"role": f"角色 {marker}", "purpose": f"作用 {marker}"},),
        advantageAndCost=f"优势代价 {marker}",
        satisfactionSources=(f"爽点 {marker}",),
        longFormVariation=(f"变化 {marker}",),
        endingAnchor=f"结局 {marker}",
        risks=(f"风险 {marker}",),
        differentiation=f"差异 {marker}",
    )


def three_options(*, suffix: str = "") -> tuple[StoryEngineOption, ...]:
    return tuple(option(number, suffix=suffix) for number in range(1, 4))


class FakeClock:
    def __init__(self, now: int = 1_000_000):
        self.now = now

    def __call__(self) -> int:
        return self.now

    def advance(self, milliseconds: int) -> None:
        self.now += milliseconds


class CountingGateway:
    def __init__(self):
        self.calls = 0

    async def generate(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Task 2 must not call the provider gateway")


class MemoryStoryEngineRepository:
    def __init__(self):
        self.projects = {"p1": {"id": "p1", "status": "drafting"}}
        self.seed = {
            "seed_id": "seed-1",
            "seed_revision_id": "seed-revision-1",
            "seed_hash": "a" * 64,
            "payload_json": canonical_json(
                {
                    "title": "冻结标题",
                    "genre": "玄幻",
                    "logline": "少年为守住家园踏上征途",
                    "protagonist": "出身边城的少年",
                    "desire": "保护家人与证明自己",
                    "coreConflict": "力量的代价不断侵蚀初心",
                    "worldPressure": "宗门与王朝争夺边境资源",
                    "openingHook": "家园在选拔当夜遭到袭击",
                    "differentiation": "每次变强都必须公开放弃一种关系",
                }
            ),
            "project_genre": "男频玄幻",
        }
        self.bindings = {
            "seed": {
                "binding_revision_id": "binding-revision-1",
                "binding_hash": "b" * 64,
                "provider_id": "provider-seed",
                "model_name_snapshot": "seed-model",
                "resolution_status": "bound",
            },
            "planning": {
                "binding_revision_id": "binding-revision-1",
                "binding_hash": "b" * 64,
                "provider_id": "provider-planning",
                "model_name_snapshot": "planning-model",
            },
        }
        self.providers = {
            "provider-seed": {
                "id": "provider-seed",
                "provider_type": "openai-compatible",
                "model_name": "seed-model",
                "base_url": "https://provider.example/v1",
                "api_key": "KEY_SENTINEL",
                "temperature": 0.456,
                "max_output_tokens": 4_321,
                "enabled": 1,
                "lifecycle_status": "active",
            }
        }
        self.batches: dict[str, dict] = {}
        self.options: dict[str, list[dict]] = {}
        self.events: list[str] = []
        self.fail_option_order: int | None = None
        self.on_lock_provider_connection = None

    async def lock_project(self, session, project_id):
        self.events.append("lock-project")
        row = self.projects.get(project_id)
        if row is None or row["status"] == "archived":
            return None
        return dict(row)

    async def read_project(self, session, project_id):
        self.events.append("read-project")
        row = self.projects.get(project_id)
        if row is None or row["status"] == "archived":
            return None
        return dict(row)

    async def lock_selected_seed(self, session, project_id):
        self.events.append("lock-seed")
        return dict(self.seed) if project_id == "p1" else None

    async def lock_seed_binding(self, session, project_id):
        self.events.append("lock-binding")
        binding = self.bindings.get("seed")
        if project_id != "p1" or not binding:
            return None
        result = dict(binding)
        provider = self.providers.get(result.get("provider_id"))
        result["temperature"] = provider.get("temperature") if provider else None
        result["max_output_tokens"] = (
            provider.get("max_output_tokens") if provider else None
        )
        return result

    async def lock_provider_connection(self, session, provider_id):
        self.events.append("lock-provider")
        if self.on_lock_provider_connection is not None:
            self.on_lock_provider_connection()
        provider = self.providers.get(provider_id)
        if provider is None:
            return None
        return {
            key: provider[key]
            for key in (
                "id",
                "provider_type",
                "model_name",
                "base_url",
                "api_key",
                "enabled",
                "lifecycle_status",
            )
        }

    async def lock_batch_by_key(self, session, project_id, idempotency_key):
        self.events.append("lock-key")
        for row in self.batches.values():
            if row["project_id"] == project_id and row["idempotency_key"] == idempotency_key:
                return dict(row)
        return None

    async def insert_batch(self, session, row):
        self.events.append("insert-batch")
        self.batches[row["id"]] = dict(row)
        self.options[row["id"]] = []

    async def insert_options(self, session, rows):
        for row in rows:
            self.events.append(f"insert-option:{row['option_order']}")
            if self.fail_option_order == row["option_order"]:
                raise RuntimeError("synthetic option failure")
            self.options[row["batch_id"]].append(dict(row))

    async def read_batch(self, session, project_id, batch_id):
        row = self.batches.get(batch_id)
        return dict(row) if row and row["project_id"] == project_id else None

    async def list_options(self, session, project_id, batch_id):
        row = self.batches.get(batch_id)
        if row is None or row["project_id"] != project_id:
            return []
        return [dict(item) for item in self.options[batch_id]]

    async def cas_start_attempt(self, session, project_id, batch_id, row):
        batch = self.batches.get(batch_id)
        if not batch or batch["project_id"] != project_id:
            return False
        if batch["status"] != "reserved" or batch["attempt_id"] is not None:
            return False
        if batch["provider_id"] is None or batch["model_name_snapshot"] is None:
            return False
        batch["status"] = "running"
        batch.update(row)
        return True

    async def cas_succeed_attempt(self, session, project_id, batch_id, attempt_id, row):
        batch = self.batches.get(batch_id)
        if not batch or batch["project_id"] != project_id:
            return False
        if batch["status"] != "running" or batch["attempt_id"] != attempt_id:
            return False
        batch["status"] = "succeeded"
        batch.update({**row, "raw_response_text": None})
        return True

    async def cas_fail_attempt(self, session, project_id, batch_id, attempt_id, row):
        batch = self.batches.get(batch_id)
        if not batch or batch["project_id"] != project_id:
            return False
        if batch["status"] != "running" or batch["attempt_id"] != attempt_id:
            return False
        batch["status"] = "failed"
        batch.update({**row, "raw_response_text": None})
        return True

    async def cas_fail_configuration(self, session, project_id, batch_id, row):
        batch = self.batches.get(batch_id)
        if not batch or batch["project_id"] != project_id:
            return False
        if batch["status"] != "reserved" or batch["attempt_id"] is not None:
            return False
        batch["status"] = "failed"
        batch.update({**row, "public_error_code": "provider_configuration"})
        return True

    async def cas_unknown_attempt(
        self, session, project_id, batch_id, attempt_id, row
    ):
        batch = self.batches.get(batch_id)
        if not batch or batch["project_id"] != project_id:
            return False
        if batch["status"] != "running" or batch["attempt_id"] != attempt_id:
            return False
        batch["status"] = "outcome_unknown"
        batch.update({**row, "public_error_code": "outcome_unknown"})
        return True

    async def cas_reconcile_reserved(self, session, project_id, batch_id, row, stale_before):
        batch = self.batches.get(batch_id)
        if not batch or batch["project_id"] != project_id:
            return False
        if batch["status"] != "reserved" or batch["attempt_id"] is not None:
            return False
        if batch["created_at"] > stale_before:
            return False
        batch["status"] = "failed"
        row = {**row, "public_error_code": "not_started"}
        batch.update(row)
        return True

    async def cas_reconcile_running(self, session, project_id, batch_id, row, now):
        batch = self.batches.get(batch_id)
        if not batch or batch["project_id"] != project_id:
            return False
        if batch["status"] != "running" or batch["attempt_id"] != row["attempt_id"]:
            return False
        if batch["lease_expires_at"] > now:
            return False
        batch["status"] = "outcome_unknown"
        row = {**row, "public_error_code": "outcome_unknown"}
        batch.update(row)
        return True


class StoryEngineHarness:
    def __init__(self, *, now: int = 1_000_000):
        from backend.services.story_engines import StoryEngineService

        self.repository = MemoryStoryEngineRepository()
        self.clock = FakeClock(now)
        self.gateway = CountingGateway()
        self.transaction_active = 0
        self.transaction_enter_count = 0
        self._transaction_lock = asyncio.Lock()
        ids = iter(f"00000000-0000-0000-0000-{number:012d}" for number in range(1, 100))
        self.service = StoryEngineService(
            self.repository,
            transaction_factory=self.transaction,
            connection_factory=self.connection,
            id_factory=lambda: next(ids),
            clock=self.clock,
            provider_gateway=self.gateway,
        )

    @asynccontextmanager
    async def transaction(self):
        async with self._transaction_lock:
            snapshot = deepcopy(self.repository.__dict__)
            self.transaction_active += 1
            self.transaction_enter_count += 1
            try:
                yield object()
            except BaseException:
                self.repository.__dict__.clear()
                self.repository.__dict__.update(snapshot)
                raise
            finally:
                self.transaction_active -= 1

    @asynccontextmanager
    async def connection(self):
        yield object()
