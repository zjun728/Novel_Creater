from __future__ import annotations

import asyncio
from copy import deepcopy
import json

import pytest
from pymysql.err import OperationalError

from backend.domain.bibles import BiblePayload
from backend.domain.contracts import CreationContractPayload
from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.planning import (
    DraftPlanningAggregate,
    normalize_planning_aggregate,
)
from backend.domain.seeds import (
    SeedPayload,
    build_seed_provenance,
    seed_revision_document,
)
from backend.domain.story_engines import StoryEngineOption
from backend.gateways.planning_provider import PlanningProviderError
from backend.http_errors import ProjectArchived, PublicDomainError
from backend.prompts.planning import (
    PLANNING_MAX_PROMPT_BYTES,
    PLANNING_STORY_CONTEXT_MAX_BYTES,
    build_planning_messages,
)


NOW = 2_000_000_000_000
SENSITIVE_PLANNING_KEYS = (
    "sk-TestSentinel123456",
    "sk_TestSentinel123456",
    "ghp_TestSentinel12345678901234567890",
    "gho_TestSentinel12345678901234567890",
    "ghu_TestSentinel12345678901234567890",
    "ghs_TestSentinel12345678901234567890",
    "ghr_TestSentinel12345678901234567890",
    "github_pat_TestSentinel1234567890",
    "AKIAABCDEFGHIJKLMNOP",
    "ASIA1234567890ABCDEF",
    "AIzaTestSentinel12345678901234567890123",
    "Authorization-Bearer-TestSentinel",
    "bearer.TestSentinel",
    "apiKey-TestSentinel",
    "api_key.TestSentinel",
    "access-token-TestSentinel",
    "TOKEN-TestSentinel",
    "planning.secret.attempt",
    "PASSWORD:TestSentinel",
    "passwd-TestSentinel",
    "credential_TestSentinel",
    "DSN.TestSentinel",
    "planning%2Dencoded",
)


def _draft_payload(title: str = "旧卷") -> dict[str, object]:
    return {
        "activeStoryBlockRef": None,
        "volumes": [
            {
                "clientNodeKey": "volume-1",
                "order": 1,
                "title": title,
                "coreChange": "主角从逃亡转为立足。",
                "mainPressure": "追兵逼近。",
                "ensembleFocus": ["主角", "同伴"],
                "forbiddenEvents": ["不可提前揭示幕后人"],
            }
        ],
        "plots": [
            {
                "clientNodeKey": "plot-1",
                "order": 1,
                "title": "立足主线",
                "plotType": "main",
                "storyQuestion": "主角如何活下来？",
                "futureDirection": "从逃亡转为主动布局。",
                "expectedPayoff": "建立据点。",
                "relatedCharacters": ["主角"],
            }
        ],
        "storyBlocks": [],
    }


def _persisted_draft(title: str = "旧卷"):
    identifiers = iter(("volume-id", "plot-id"))
    return normalize_planning_aggregate(
        DraftPlanningAggregate.model_validate(_draft_payload(title)),
        previous_confirmed=None,
        previous_draft=None,
        id_factory=identifiers.__next__,
    )


def _empty_persisted_draft():
    return normalize_planning_aggregate(
        DraftPlanningAggregate.model_validate(
            {
                "activeStoryBlockRef": None,
                "volumes": [],
                "plots": [],
                "storyBlocks": [],
            }
        ),
        previous_confirmed=None,
        previous_draft=None,
        id_factory=lambda: pytest.fail("empty Planning allocated an ID"),
    )


def _confirmed_story_basis() -> dict[str, object]:
    seed = SeedPayload.model_validate({
        "title": "雾港守灯人",
        "genre": "海洋奇幻",
        "logline": "失忆守灯人必须在潮灾前修复会吞噬记忆的古灯。",
        "protagonist": "岑遥，一名谨慎而固执的守灯人。",
        "desire": "保住港城，也找回被古灯夺走的家人记忆。",
        "coreConflict": "每次点亮古灯都会救人，也会抹去一段私人记忆。",
        "worldPressure": "潮灾逼近，港务议会要求永久封存古灯。",
        "openingHook": "古灯在无人点火时照出了明日沉没的街区。",
        "differentiation": "以记忆作为航海与守城力量的不可逆代价。",
    }, strict=True)
    provenance = build_seed_provenance(
        kind="manual",
        snapshots=(),
        analysis=None,
        inspiration_attempt=None,
        public_notes=("PK-challenge 与 sk-placeholder 都是正常小说术语。",),
    )
    seed_hash = canonical_hash(seed)
    engine = StoryEngineOption.model_validate(
        {
            "name": "潮灯记忆循环",
            "storyPromise": "每次守城都迫使人物在共同记忆与私人关系间选择。",
            "protagonistDesire": "岑遥既要保住港城，也要保住家人的记忆。",
            "sustainedPressure": "潮线、议会封禁与记忆损耗持续收紧。",
            "growthDirection": "从独自承担代价转向建立共同记忆制度。",
            "conflictLoop": "预测潮灾、点灯救援、失去记忆、关系追责。",
            "ensembleRoles": (
                {"role": "记忆记录者", "purpose": "保存证据并挑战主角的隐瞒。"},
            ),
            "advantageAndCost": "古灯能照见灾害路径，但每次使用都会抹去私人记忆。",
            "satisfactionSources": ("灾害谜题被验证", "关系账本逐步兑现"),
            "longFormVariation": ("街区救援", "港城权力斗争", "远海灯塔联盟"),
            "endingAnchor": "岑遥公开记忆账本，让全城共同承担最后一次点灯。",
            "risks": ("失忆代价重复",),
            "differentiation": "记忆既是力量燃料，也是关系连续性的证据。",
        },
        strict=True,
    )
    contract = CreationContractPayload.model_validate({
        "schemaVersion": "creation-contract-v1",
        "channelProfileKey": "web-fiction",
        "genreProfileKey": "ocean-fantasy",
        "qualityCharterVersion": "writer-core-quality-v1",
        "selectionRevision": 1,
        "selectedSeed": seed,
        "seedRevisionId": "seed-revision-1",
        "seedHash": seed_hash,
        "selectedEngine": engine,
        "engineOptionId": "engine-option-1",
        "engineHash": canonical_hash(engine),
        "primaryStyleRef": {
            "id": "style-primary",
            "revision": 2,
            "contentHash": "c" * 64,
        },
        "secondaryStyleRef": None,
        "experienceCardRefs": (),
        "corpusSourceRefs": (
            {
                "id": "source-1",
                "revisionId": "source-revision-1",
                "revision": 1,
                "contentHash": "d" * 64,
                "selectionMode": "author",
                "fragments": (
                    {
                        "chapterId": "chapter-1",
                        "fragmentId": "fragment-1",
                        "fragmentHash": "e" * 64,
                        "chapterCharStart": 0,
                        "chapterCharEnd": 120,
                        "referenceUse": "structure",
                    },
                ),
                "pinnedHistoricalRevision": True,
            },
        ),
        "targetTotalWords": 1_200_000,
        "expectedVolumeCount": 10,
        "expectedChapterCount": 420,
        "chapterWordRangePreference": (2_800, 3_600),
        "prohibitedDirections": (
            "不得用无代价失忆逆转解决冲突。",
            "不得提前揭示古灯起源。",
        ),
        "authorNotes": "人物关系选择必须先于设定说明。",
        "modelBindingRef": None,
    }, strict=True)
    bible = BiblePayload.model_validate({
        "premiseAndPromise": "守护共同记忆需要人物主动承担无法撤销的私人代价。",
        "worldRules": (
            {"id": "world-1", "text": "古灯只能交换记忆，不能凭空创造力量。"},
            {"id": "world-2", "text": "潮线每天推进一次，退潮不会恢复已失记忆。"},
        ),
        "powerOrProgressionSystem": "角色通过掌握灯谱扩大照明范围，但代价随范围增长。",
        "protagonist": "岑遥会优先救人，却害怕再次忘记最亲近的人。",
        "coreCast": (
            {"id": "cast-1", "text": "陆弦负责记录岑遥失去的记忆，也隐瞒自己的交易。"},
        ),
        "factions": (
            {"id": "faction-1", "text": "港务议会在安全与控制古灯之间摇摆。"},
        ),
        "longTermConflicts": (
            {"id": "conflict-1", "text": "救城次数越多，岑遥越难确认自己为何而战。"},
        ),
        "relationshipDynamics": (
            {"id": "relation-1", "text": "岑遥与陆弦的信任取决于是否公开记忆账本。"},
        ),
        "toneAndNarrativeBoundaries": "保持克制，不用旁白替人物消解选择代价。",
        "continuityGuardrails": (
            {"id": "guard-1", "text": "任何记忆恢复都必须有此前保存的外部记录。"},
        ),
        "openDesignQuestions": (
            {"id": "question-1", "text": "议会中谁最早知道古灯的真实代价？"},
        ),
    }, strict=True)
    return {
        "seed_hash": seed_hash,
        "creation_hash": canonical_hash(contract),
        "bible_hash": canonical_hash(bible),
        "seed_content_json": canonical_json(
            seed_revision_document(seed, provenance)
        ),
        "creation_content_json": canonical_json(contract),
        "bible_content_json": canonical_json(bible),
    }


def _worst_case_story_basis() -> dict[str, object]:
    seed = SeedPayload.model_validate(
        {
            field: "种" * 2_000
            for field in (
                "title",
                "genre",
                "logline",
                "protagonist",
                "desire",
                "coreConflict",
                "worldPressure",
                "openingHook",
                "differentiation",
            )
        },
        strict=True,
    )
    provenance = build_seed_provenance(
        kind="manual",
        snapshots=(),
        analysis=None,
        inspiration_attempt=None,
        public_notes=("只用于证明正式修订文档不会泄露来源元数据。",),
    )
    engine = StoryEngineOption.model_validate(
        {
            "name": "潮" * 2_000,
            "storyPromise": "诺" * 2_000,
            "protagonistDesire": "愿" * 2_000,
            "sustainedPressure": "压" * 2_000,
            "growthDirection": "长" * 2_000,
            "conflictLoop": "冲" * 2_000,
            "ensembleRoles": tuple(
                {
                    "role": "角" * 2_000,
                    "purpose": "责" * 2_000,
                }
                for _ in range(20)
            ),
            "advantageAndCost": "代" * 2_000,
            "satisfactionSources": tuple("爽" * 2_000 for _ in range(20)),
            "longFormVariation": tuple("变" * 2_000 for _ in range(20)),
            "endingAnchor": "终" * 2_000,
            "risks": tuple("险" * 2_000 for _ in range(20)),
            "differentiation": "异" * 2_000,
        },
        strict=True,
    )
    seed_hash = canonical_hash(seed)
    contract = CreationContractPayload.model_validate(
        {
            "schemaVersion": "creation-contract-v1",
            "channelProfileKey": "web-fiction",
            "genreProfileKey": "fantasy",
            "qualityCharterVersion": "quality-v1",
            "selectionRevision": 1,
            "selectedSeed": seed,
            "seedRevisionId": "seed-revision-1",
            "seedHash": seed_hash,
            "selectedEngine": engine,
            "engineOptionId": "engine-option-1",
            "engineHash": canonical_hash(engine),
            "primaryStyleRef": {
                "id": "style-primary",
                "revision": 1,
                "contentHash": "c" * 64,
            },
            "secondaryStyleRef": None,
            "experienceCardRefs": (),
            "corpusSourceRefs": (),
            "targetTotalWords": 100_000_000,
            "expectedVolumeCount": 1_000,
            "expectedChapterCount": 100_000,
            "chapterWordRangePreference": (1, 100_000),
            "prohibitedDirections": tuple(
                "禁" * 2_000 for _ in range(20)
            ),
            "authorNotes": "注" * 2_000,
            "modelBindingRef": None,
        },
        strict=True,
    )

    def bible_items(prefix: str, character: str):
        return tuple(
            {
                "id": f"{prefix}-{index:02d}",
                "text": character * 4_000,
            }
            for index in range(20)
        )

    bible = BiblePayload.model_validate(
        {
            "premiseAndPromise": "旨" * 4_000,
            "worldRules": bible_items("world", "界"),
            "powerOrProgressionSystem": "力" * 4_000,
            "protagonist": "主" * 4_000,
            "coreCast": bible_items("cast", "人"),
            "factions": bible_items("faction", "派"),
            "longTermConflicts": bible_items("conflict", "争"),
            "relationshipDynamics": bible_items("relation", "系"),
            "toneAndNarrativeBoundaries": "调" * 4_000,
            "continuityGuardrails": bible_items("guard", "护"),
            "openDesignQuestions": bible_items("question", "问"),
        },
        strict=True,
    )
    return {
        "seed_hash": seed_hash,
        "creation_hash": canonical_hash(contract),
        "bible_hash": canonical_hash(bible),
        "seed_content_json": canonical_json(
            seed_revision_document(seed, provenance)
        ),
        "creation_content_json": canonical_json(contract),
        "bible_content_json": canonical_json(bible),
    }


class TransactionTracker:
    def __init__(self):
        self.active = 0
        self.entries = 0

    def factory(self):
        tracker = self

        class Transaction:
            async def __aenter__(self):
                tracker.active += 1
                tracker.entries += 1
                return object()

            async def __aexit__(self, exc_type, exc, tb):
                tracker.active -= 1
                return False

        return Transaction()


class FakePlanningRepository:
    def __init__(self):
        content = _persisted_draft()
        story_basis = _confirmed_story_basis()
        self.project = {"id": "p1", "archived_at": None}
        self.basis = {
            "selection_revision": 1,
            "seed_id": "seed-1",
            "seed_revision_id": "seed-revision-1",
            "seed_hash": story_basis["seed_hash"],
            "contract_revision": 2,
            "creation_contract_id": "creation-1",
            "creation_hash": story_basis["creation_hash"],
            "style_contract_id": "style-1",
            "style_hash": "3" * 64,
            "chapter_capacity_policy": '{"chapterWordRangePreference":[3000,5000]}',
            "bible_revision": 3,
            "bible_revision_id": "bible-1",
            "bible_hash": story_basis["bible_hash"],
            "seed_content_json": story_basis["seed_content_json"],
            "creation_content_json": story_basis["creation_content_json"],
            "bible_content_json": story_basis["bible_content_json"],
        }
        self.head = {
            "project_id": "p1",
            "revision": 0,
            "planning_revision_id": None,
            "content_hash": None,
            "content_json": None,
        }
        self.draft = {
            "id": "draft-1",
            "project_id": "p1",
            "active_slot": 1,
            "base_head_revision": 0,
            "draft_revision": 1,
            **{
                key: value
                for key, value in self.basis.items()
                if key != "chapter_capacity_policy"
            },
            "content_json": canonical_json(
                content.model_dump(mode="json", by_alias=True)
            ),
            "content_hash": content.content_hash,
            "source_attempt_id": None,
            "status": "active",
        }
        self.binding = {
            "binding_revision_id": "binding-1",
            "binding_revision": 1,
            "binding_hash": "5" * 64,
            "binding_task_key": "planning",
            "resolution_status": "bound",
            "provider_id": "provider-1",
            "model_name_snapshot": "deepseek-v4-flash",
            "id": "provider-1",
            "provider_type": "openai-compatible",
            "model_name": "deepseek-v4-flash",
            "base_url": "https://provider.invalid/v1",
            "api_key": "TEST_ONLY_PRIVATE_KEY",
            "enabled": 1,
            "lifecycle_status": "active",
            "revision": 1,
            "temperature": 0.6,
            "max_context_tokens": 100_000,
            "max_output_tokens": 8_192,
        }
        self.attempts: dict[str, dict] = {}
        self.load_calls = 0
        self.lock_order: list[str] = []
        self.lock_operation_reads = 0
        self.plain_operation_reads = 0
        self.plain_key_reads = 0

    async def lock_active_project(self, _session, project_id):
        self.lock_order.append("project")
        if self.project["archived_at"] is not None:
            raise ProjectArchived()
        if project_id != "p1":
            return None
        return self.project

    async def read_project_any(self, _session, project_id):
        return self.project if project_id == "p1" else None

    async def read_current_basis(self, _session, project_id):
        self.lock_order.append("basis")
        return self.basis if project_id == "p1" else None

    async def lock_planning_head(self, _session, project_id):
        self.lock_order.append("head")
        return self.head if project_id == "p1" else None

    async def read_draft(self, _session, project_id, draft_id):
        self.lock_order.append("draft")
        if project_id == "p1" and draft_id == self.draft["id"]:
            return self.draft
        return None

    async def lock_planning_binding(self, _session, project_id):
        self.lock_order.append("binding")
        return self.binding if project_id == "p1" else None

    async def lock_generation_attempt_by_key(
        self, _session, project_id, idempotency_key
    ):
        self.lock_order.append("idempotency")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["project_id"] == project_id
                and row["idempotency_key"] == idempotency_key
            ),
            None,
        )

    async def read_generation_attempt_by_key(
        self, _session, project_id, idempotency_key
    ):
        self.plain_key_reads += 1
        self.lock_order.append("idempotency-read")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["project_id"] == project_id
                and row["idempotency_key"] == idempotency_key
            ),
            None,
        )

    async def lock_generation_attempt(
        self, _session, project_id, operation_id
    ):
        self.lock_operation_reads += 1
        self.lock_order.append("operation")
        row = self.attempts.get(operation_id)
        return row if row and row["project_id"] == project_id else None

    async def read_generation_attempt(
        self, _session, project_id, operation_id
    ):
        self.plain_operation_reads += 1
        row = self.attempts.get(operation_id)
        return row if row and row["project_id"] == project_id else None

    async def lock_active_generation_attempt(self, _session, draft_id):
        self.lock_order.append("active")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["draft_id"] == draft_id
                and row["status"] == "pending"
                and row["active_slot"] == 1
            ),
            None,
        )

    async def read_active_generation_attempt(self, _session, draft_id):
        self.lock_order.append("active-read")
        return next(
            (
                row
                for row in self.attempts.values()
                if row["draft_id"] == draft_id
                and row["status"] == "pending"
                and row["active_slot"] == 1
            ),
            None,
        )

    async def next_fencing_token(self, _session, draft_id):
        self.lock_order.append("token")
        tokens = [
            row["fencing_token"]
            for row in self.attempts.values()
            if row["draft_id"] == draft_id
        ]
        return max(tokens, default=0) + 1

    async def insert_generation_attempt(self, _session, row):
        self.attempts[row["operation_id"]] = {
            **deepcopy(row),
            "active_slot": 1,
            "status": "pending",
            "failure_code": None,
            "result_content_json": None,
            "result_content_hash": None,
            "loaded_draft_revision": None,
            "loaded_at": None,
        }
        return True

    async def supersede_generation_attempt(
        self,
        _session,
        *,
        project_id,
        operation_id,
        fencing_token,
        updated_at,
    ):
        row = self.attempts.get(operation_id)
        if not self._owns(row, project_id, fencing_token):
            return False
        row.update(status="superseded", active_slot=None, updated_at=updated_at)
        return True

    async def fail_generation_attempt(
        self,
        _session,
        *,
        project_id,
        operation_id,
        fencing_token,
        failure_code,
        updated_at,
    ):
        row = self.attempts.get(operation_id)
        if not self._owns(row, project_id, fencing_token):
            return False
        row.update(
            status="failed",
            active_slot=None,
            failure_code=failure_code,
            updated_at=updated_at,
        )
        return True

    async def load_generation_result_into_draft(
        self,
        _session,
        *,
        project_id,
        draft_id,
        expected_revision,
        expected_hash,
        operation_id,
        fencing_token,
        content_json,
        content_hash,
        loaded_at,
    ):
        self.load_calls += 1
        row = self.attempts.get(operation_id)
        if (
            not self._owns(row, project_id, fencing_token)
            or self.draft["id"] != draft_id
            or self.draft["draft_revision"] != expected_revision
            or self.draft["content_hash"] != expected_hash
        ):
            return False
        loaded_revision = expected_revision + 1
        self.draft.update(
            draft_revision=loaded_revision,
            content_json=content_json,
            content_hash=content_hash,
            source_attempt_id=row["id"],
        )
        row.update(
            status="succeeded",
            active_slot=None,
            result_content_json=content_json,
            result_content_hash=content_hash,
            loaded_draft_revision=loaded_revision,
            loaded_at=loaded_at,
            updated_at=loaded_at,
        )
        return True

    @staticmethod
    def _owns(row, project_id, token):
        return (
            row is not None
            and row["project_id"] == project_id
            and row["status"] == "pending"
            and row["active_slot"] == 1
            and row["fencing_token"] == token
        )


class FakeGateway:
    def __init__(self, output=None, *, tracker=None, hook=None):
        self.output = output or _draft_payload("AI 新卷")
        self.tracker = tracker
        self.hook = hook
        self.calls = []

    async def generate(
        self, *, provider, model_name, manifest, author_instructions
    ):
        if self.tracker is not None:
            assert self.tracker.active == 0
        self.calls.append(
            {
                "provider": dict(provider),
                "model_name": model_name,
                "manifest": manifest,
                "author_instructions": author_instructions,
            }
        )
        if self.hook is not None:
            self.hook()
        if isinstance(self.output, BaseException):
            raise self.output
        return deepcopy(self.output)


class BlockingGateway(FakeGateway):
    def __init__(self, *, tracker):
        super().__init__(tracker=tracker)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(self, **kwargs):
        assert self.tracker.active == 0
        self.calls.append(kwargs)
        self.entered.set()
        await self.release.wait()
        return deepcopy(self.output)


class SettlementBarrierRepository(FakePlanningRepository):
    def __init__(self):
        super().__init__()
        self.settlement_entered = asyncio.Event()
        self.release_settlement = asyncio.Event()
        self.block_next_operation_lock = True

    async def lock_generation_attempt(
        self, session, project_id, operation_id
    ):
        if self.block_next_operation_lock:
            self.block_next_operation_lock = False
            self.settlement_entered.set()
            await self.release_settlement.wait()
        return await super().lock_generation_attempt(
            session, project_id, operation_id
        )


class CoordinationFailureRepository(FakePlanningRepository):
    def __init__(self, stage, code):
        super().__init__()
        self.stage = stage
        self.code = code

    def _raise(self):
        raise OperationalError(
            self.code,
            "RAW_DATABASE_COORDINATION_SENTINEL",
        )

    async def lock_active_project(self, session, project_id):
        if self.stage == "reserve":
            self._raise()
        return await super().lock_active_project(session, project_id)

    async def read_generation_attempt(
        self, session, project_id, operation_id
    ):
        if self.stage == "get":
            self._raise()
        return await super().read_generation_attempt(
            session, project_id, operation_id
        )

    async def lock_generation_attempt(
        self, session, project_id, operation_id
    ):
        if self.stage == "settlement":
            self._raise()
        return await super().lock_generation_attempt(
            session, project_id, operation_id
        )


class ExhaustingExpiredRepository(FakePlanningRepository):
    def __init__(self):
        super().__init__()
        self.reserve_reads = 0
        self.settles = 0
        self._add_expired(1)

    def _add_expired(self, number):
        self.attempts[f"expired-operation-{number}"] = {
            "id": f"expired-row-{number}",
            "project_id": "p1",
            "draft_id": "draft-1",
            "operation_id": f"expired-operation-{number}",
            "idempotency_key": f"expired-key-{number}",
            "request_fingerprint": f"{number:x}".rjust(64, "0"),
            "binding_revision_id": "binding-1",
            "binding_revision": 1,
            "binding_hash": "5" * 64,
            "provider_id": "provider-1",
            "model_name_snapshot": "deepseek-v4-flash",
            "fencing_token": number,
            "lease_expires_at": NOW - 1,
            "input_manifest_json": "{}",
            "input_manifest_hash": "7" * 64,
            "status": "pending",
            "active_slot": 1,
            "failure_code": None,
            "loaded_draft_revision": None,
        }

    async def read_active_generation_attempt(self, session, draft_id):
        self.reserve_reads += 1
        return await super().read_active_generation_attempt(
            session, draft_id
        )

    async def supersede_generation_attempt(self, session, **kwargs):
        changed = await super().supersede_generation_attempt(
            session, **kwargs
        )
        if changed:
            self.settles += 1
            if self.settles < 3:
                self._add_expired(self.settles + 1)
        return changed


def _service(
    repository=None,
    gateway=None,
    tracker=None,
    *,
    clock=lambda: NOW,
):
    from backend.services.planning_generation import PlanningGenerationService

    repository = repository or FakePlanningRepository()
    tracker = tracker or TransactionTracker()
    gateway = gateway or FakeGateway(tracker=tracker)
    identifiers = iter(
        [
            "attempt-row-1",
            "operation-1",
            "generated-volume-1",
            "generated-plot-1",
            "attempt-row-2",
            "operation-2",
            "generated-volume-2",
            "generated-plot-2",
        ]
    )
    return (
        PlanningGenerationService(
            repository,
            provider_gateway=gateway,
            transaction_factory=tracker.factory,
            id_factory=identifiers.__next__,
            clock=clock,
        ),
        repository,
        gateway,
        tracker,
    )


def _command(key="generate-1", *, instructions="强化群像"):
    from backend.services.planning_generation import GeneratePlanningDraft

    content = _persisted_draft()
    return GeneratePlanningDraft(
        project_id="p1",
        draft_id="draft-1",
        draft_revision=1,
        draft_hash=content.content_hash,
        idempotency_key=key,
        author_instructions=instructions,
    )


@pytest.mark.asyncio
async def test_success_uses_two_short_transactions_and_atomically_loads_exact_draft():
    service, repository, gateway, tracker = _service()

    result = await service.generate(_command())

    assert result.status == "succeeded"
    assert result.loaded is True
    assert result.loaded_draft_revision == 2
    assert result.model.provider_id == "provider-1"
    assert result.model.model_name == "deepseek-v4-flash"
    assert repository.draft["source_attempt_id"] == "attempt-row-1"
    assert repository.load_calls == 1
    assert len(gateway.calls) == 1
    assert tracker.entries == 2
    assert tracker.active == 0
    assert repository.lock_order[:8] == [
        "project",
        "basis",
        "head",
        "draft",
        "binding",
        "idempotency-read",
        "active-read",
        "token",
    ]
    assert repository.lock_order[8:14] == [
        "project",
        "basis",
        "head",
        "draft",
        "binding",
        "operation",
    ]


@pytest.mark.asyncio
async def test_empty_draft_gateway_manifest_uses_frozen_confirmed_story_basis():
    repository = FakePlanningRepository()
    empty = _empty_persisted_draft()
    repository.draft.update(
        content_json=canonical_json(
            empty.model_dump(mode="json", by_alias=True)
        ),
        content_hash=empty.content_hash,
    )
    gateway = FakeGateway()
    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
    )
    command = _command()
    command = type(command)(
        project_id=command.project_id,
        draft_id=command.draft_id,
        draft_revision=command.draft_revision,
        draft_hash=empty.content_hash,
        idempotency_key=command.idempotency_key,
        author_instructions=command.author_instructions,
    )

    result = await service.generate(command)

    assert result.status == "succeeded"
    assert len(gateway.calls) == 1
    manifest = gateway.calls[0]["manifest"].model_dump(
        mode="json",
        by_alias=True,
    )
    story = manifest["storyContext"]
    assert story == {
        "premise": "守护共同记忆需要人物主动承担无法撤销的私人代价。",
        "seed": {
            "title": "雾港守灯人",
            "genre": "海洋奇幻",
            "logline": "失忆守灯人必须在潮灾前修复会吞噬记忆的古灯。",
            "protagonist": "岑遥，一名谨慎而固执的守灯人。",
            "desire": "保住港城，也找回被古灯夺走的家人记忆。",
            "coreConflict": "每次点亮古灯都会救人，也会抹去一段私人记忆。",
            "worldPressure": "潮灾逼近，港务议会要求永久封存古灯。",
            "openingHook": "古灯在无人点火时照出了明日沉没的街区。",
            "differentiation": "以记忆作为航海与守城力量的不可逆代价。",
        },
        "engine": {
            "name": "潮灯记忆循环",
            "storyPromise": "每次守城都迫使人物在共同记忆与私人关系间选择。",
            "protagonistDesire": "岑遥既要保住港城，也要保住家人的记忆。",
            "sustainedPressure": "潮线、议会封禁与记忆损耗持续收紧。",
            "growthDirection": "从独自承担代价转向建立共同记忆制度。",
            "conflictLoop": "预测潮灾、点灯救援、失去记忆、关系追责。",
            "ensembleRoles": [
                {
                    "role": "记忆记录者",
                    "purpose": "保存证据并挑战主角的隐瞒。",
                }
            ],
            "advantageAndCost": (
                "古灯能照见灾害路径，但每次使用都会抹去私人记忆。"
            ),
            "satisfactionSources": ["灾害谜题被验证", "关系账本逐步兑现"],
            "longFormVariation": [
                "街区救援",
                "港城权力斗争",
                "远海灯塔联盟",
            ],
            "endingAnchor": (
                "岑遥公开记忆账本，让全城共同承担最后一次点灯。"
            ),
            "risks": ["失忆代价重复"],
            "differentiation": "记忆既是力量燃料，也是关系连续性的证据。",
        },
        "longFormCapacity": {
            "targetTotalWords": 1_200_000,
            "expectedVolumeCount": 10,
            "expectedChapterCount": 420,
            "chapterWordRangePreference": [2_800, 3_600],
        },
        "protagonist": "岑遥会优先救人，却害怕再次忘记最亲近的人。",
        "coreCharacters": [
            {
                "id": "cast-1",
                "text": "陆弦负责记录岑遥失去的记忆，也隐瞒自己的交易。",
            }
        ],
        "relationshipDynamics": [
            {
                "id": "relation-1",
                "text": "岑遥与陆弦的信任取决于是否公开记忆账本。",
            }
        ],
        "worldRules": [
            {
                "id": "world-1",
                "text": "古灯只能交换记忆，不能凭空创造力量。",
            },
            {
                "id": "world-2",
                "text": "潮线每天推进一次，退潮不会恢复已失记忆。",
            },
        ],
        "powerOrProgressionSystem": (
            "角色通过掌握灯谱扩大照明范围，但代价随范围增长。"
        ),
        "longTermConflicts": [
            {
                "id": "conflict-1",
                "text": "救城次数越多，岑遥越难确认自己为何而战。",
            }
        ],
        "toneAndNarrativeBoundaries": (
            "保持克制，不用旁白替人物消解选择代价。"
        ),
        "prohibitedDirections": [
            "不得用无代价失忆逆转解决冲突。",
            "不得提前揭示古灯起源。",
        ],
        "continuityGuardrails": [
            {
                "id": "guard-1",
                "text": "任何记忆恢复都必须有此前保存的外部记录。",
            }
        ],
        "authorNotes": "人物关系选择必须先于设定说明。",
    }
    assert manifest["draft"] == {
        "activeStoryBlockRef": None,
        "volumes": [],
        "plots": [],
        "storyBlocks": [],
    }
    persisted = next(iter(repository.attempts.values()))
    assert persisted["input_manifest_hash"] == canonical_hash(manifest)
    serialized = canonical_json(manifest)
    assert "基于已确认创作依据规划未来分卷与情节线" not in serialized
    assert all(
        marker not in serialized.casefold()
        for marker in (
            "api_key",
            "authorization",
            "raw_output",
            "raw_corpus",
            "corpusfragment",
            "_provenance",
            "publicnotes",
            "prompt",
        )
    )


@pytest.mark.asyncio
async def test_worst_case_story_basis_is_deterministically_budgeted_pre_gateway():
    from backend.services.planning_generation import (
        PlanningGenerationService,
    )

    repository = FakePlanningRepository()
    worst = _worst_case_story_basis()
    repository.basis.update(worst)
    repository.draft.update(worst)
    empty = _empty_persisted_draft()
    repository.draft.update(
        content_json=canonical_json(
            empty.model_dump(mode="json", by_alias=True)
        ),
        content_hash=empty.content_hash,
    )
    gateway = FakeGateway()
    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
    )
    original = _command()
    command = type(original)(
        project_id=original.project_id,
        draft_id=original.draft_id,
        draft_revision=original.draft_revision,
        draft_hash=empty.content_hash,
        idempotency_key=original.idempotency_key,
        author_instructions="续" * 4_000,
    )

    manifest_one = PlanningGenerationService._manifest(
        command,
        basis=repository.basis,
        draft=repository.draft,
    )
    manifest_two = PlanningGenerationService._manifest(
        command,
        basis=repository.basis,
        draft=repository.draft,
    )
    snapshot_one = manifest_one.model_dump(mode="json", by_alias=True)
    snapshot_two = manifest_two.model_dump(mode="json", by_alias=True)
    story = snapshot_one["storyContext"]
    story_bytes = len(canonical_json(story).encode("utf-8"))
    source_bytes = sum(
        len(repository.basis[key].encode("utf-8"))
        for key in (
            "seed_content_json",
            "creation_content_json",
            "bible_content_json",
        )
    )
    messages = build_planning_messages(
        manifest=manifest_one,
        author_instructions=command.author_instructions,
    )
    message_bytes = len(
        json.dumps(
            messages,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )

    assert source_bytes > PLANNING_STORY_CONTEXT_MAX_BYTES + 1
    assert story_bytes <= PLANNING_STORY_CONTEXT_MAX_BYTES
    assert message_bytes <= PLANNING_MAX_PROMPT_BYTES
    assert canonical_json(snapshot_one) == canonical_json(snapshot_two)
    assert canonical_hash(snapshot_one) == canonical_hash(snapshot_two)
    assert story["premise"]
    assert story["engine"]["storyPromise"]
    assert story["engine"]["sustainedPressure"]
    assert story["engine"]["conflictLoop"]
    assert story["engine"]["endingAnchor"]
    assert story["protagonist"]
    assert story["worldRules"][0]["text"]
    assert story["longTermConflicts"][0]["text"]
    assert story["continuityGuardrails"][0]["text"]
    assert story["longFormCapacity"] == {
        "targetTotalWords": 100_000_000,
        "expectedVolumeCount": 1_000,
        "expectedChapterCount": 100_000,
        "chapterWordRangePreference": [1, 100_000],
    }

    result = await service.generate(command)

    assert result.status == "succeeded"
    assert gateway.calls[0]["manifest"] == manifest_one
    persisted = next(iter(repository.attempts.values()))
    assert persisted["input_manifest_hash"] == canonical_hash(snapshot_one)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret",
    (
        "sk-proj-aB3dE5fG7hJ9kL2mN4pQ6rS8tU0vW2xY4zA6bC8dE0fG2hJ4",
        "sk%2Dproj%2DaB3dE5fG7hJ9kL2mN4pQ6rS8tU0vW2xY4zA6bC8dE0fG2hJ4",
    ),
)
async def test_over_budget_story_secret_is_rejected_before_compression(
    secret,
):
    from backend.services.planning_generation import (
        PlanningGenerationNotReady,
    )

    repository = FakePlanningRepository()
    worst = _worst_case_story_basis()
    contract = json.loads(worst["creation_content_json"])
    contract["authorNotes"] = ("注" * 1_000) + secret
    contract_hash = canonical_hash(contract)
    worst.update(
        creation_hash=contract_hash,
        creation_content_json=canonical_json(contract),
    )
    repository.basis.update(worst)
    repository.draft.update(worst)
    empty = _empty_persisted_draft()
    repository.draft.update(
        content_json=canonical_json(
            empty.model_dump(mode="json", by_alias=True)
        ),
        content_hash=empty.content_hash,
    )
    service, repository, gateway, tracker = _service(
        repository=repository,
    )
    original = _command()
    command = type(original)(
        project_id=original.project_id,
        draft_id=original.draft_id,
        draft_revision=original.draft_revision,
        draft_hash=empty.content_hash,
        idempotency_key=original.idempotency_key,
        author_instructions=original.author_instructions,
    )

    with pytest.raises(PlanningGenerationNotReady):
        await service.generate(command)

    assert repository.attempts == {}
    assert gateway.calls == []
    assert tracker.entries == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "secret",
    (
        "sk-proj-aB3dE5fG7hJ9kL2mN4pQ6rS8tU0vW2xY4zA6bC8dE0fG2hJ4",
        "sk%2Dproj%2DaB3dE5fG7hJ9kL2mN4pQ6rS8tU0vW2xY4zA6bC8dE0fG2hJ4",
        "sk%5Fproj%5FaB3dE5fG7hJ9kL2mN4pQ6rS8tU0vW2xY4zA6bC8dE0fG2hJ4",
        "rk-live-Z9yX8wV7uT6sR5qP4nM3kJ2hG1fD0cB9aA8",
        "pk_prod_9Z8Y7X6W5V4U3T2S1R0Q9P8N7M6L5K4J",
    ),
)
async def test_confirmed_story_secret_shape_is_rejected_before_gateway(
    secret,
):
    from backend.services.planning_generation import (
        PlanningGenerationNotReady,
    )

    repository = FakePlanningRepository()
    contract = json.loads(repository.basis["creation_content_json"])
    contract["authorNotes"] = secret
    contract_hash = canonical_hash(contract)
    repository.basis.update(
        creation_hash=contract_hash,
        creation_content_json=canonical_json(contract),
    )
    repository.draft["creation_hash"] = contract_hash
    service, repository, gateway, tracker = _service(
        repository=repository,
    )

    with pytest.raises(PlanningGenerationNotReady):
        await service.generate(_command())

    assert gateway.calls == []
    assert repository.attempts == {}
    assert tracker.entries == 1


@pytest.mark.asyncio
async def test_creation_contract_unknown_field_is_rejected_before_gateway():
    from backend.services.planning_generation import (
        PlanningGenerationNotReady,
    )

    repository = FakePlanningRepository()
    contract = json.loads(repository.basis["creation_content_json"])
    contract["legacyPlanningHint"] = "must not bypass the formal contract"
    contract_hash = canonical_hash(contract)
    repository.basis.update(
        creation_hash=contract_hash,
        creation_content_json=canonical_json(contract),
    )
    repository.draft["creation_hash"] = contract_hash
    service, repository, gateway, tracker = _service(
        repository=repository,
    )

    with pytest.raises(PlanningGenerationNotReady):
        await service.generate(_command())

    assert gateway.calls == []
    assert repository.attempts == {}
    assert tracker.entries == 1


@pytest.mark.asyncio
async def test_same_key_same_fingerprint_replays_without_gateway_call():
    service, _repository, gateway, _tracker = _service()
    first = await service.generate(_command())
    second = await service.generate(_command())

    assert second == first
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_same_key_different_fingerprint_conflicts_without_gateway_call():
    from backend.services.planning_generation import (
        PlanningGenerationIdempotencyConflict,
    )

    service, _repository, gateway, _tracker = _service()
    await service.generate(_command())

    with pytest.raises(PlanningGenerationIdempotencyConflict):
        await service.generate(_command(instructions="完全不同的要求"))

    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_same_key_expired_pending_replay_supersedes_without_hidden_retry():
    repository = FakePlanningRepository()
    tracker = TransactionTracker()
    gateway = BlockingGateway(tracker=tracker)
    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
        tracker=tracker,
    )
    first_call = asyncio.create_task(service.generate(_command()))
    await gateway.entered.wait()
    repository.attempts["operation-1"]["lease_expires_at"] = NOW - 1

    replay = await service.generate(_command())

    assert replay.status == "superseded"
    assert replay.loaded is False
    assert len(gateway.calls) == 1
    gateway.release.set()
    stale = await first_call
    assert stale.status == "superseded"
    assert repository.load_calls == 0


@pytest.mark.asyncio
async def test_one_unexpired_active_lease_rejects_another_key():
    from backend.services.planning_generation import PlanningGenerationConflict

    service, repository, gateway, _tracker = _service()
    repository.attempts["busy-operation"] = {
        "id": "busy-row",
        "project_id": "p1",
        "draft_id": "draft-1",
        "operation_id": "busy-operation",
        "idempotency_key": "busy-key",
        "request_fingerprint": "6" * 64,
        "binding_revision_id": "binding-1",
        "binding_revision": 1,
        "binding_hash": "5" * 64,
        "provider_id": "provider-1",
        "model_name_snapshot": "deepseek-v4-flash",
        "fencing_token": 1,
        "lease_expires_at": NOW + 1,
        "input_manifest_json": "{}",
        "input_manifest_hash": "7" * 64,
        "status": "pending",
        "active_slot": 1,
        "failure_code": None,
        "loaded_draft_revision": None,
    }

    with pytest.raises(PlanningGenerationConflict):
        await service.generate(_command("different-key"))

    assert gateway.calls == []


@pytest.mark.asyncio
async def test_public_model_summary_cannot_echo_provider_secret():
    from backend.services.planning_generation import (
        PlanningGenerationNotReady,
    )

    repository = FakePlanningRepository()
    repository.binding["model_name"] = repository.binding["api_key"]
    repository.binding["model_name_snapshot"] = repository.binding["api_key"]
    service, _repository, gateway, _tracker = _service(
        repository=repository
    )

    with pytest.raises(PlanningGenerationNotReady):
        await service.generate(_command())

    assert gateway.calls == []


@pytest.mark.asyncio
async def test_expired_lease_is_superseded_and_new_key_gets_higher_fence():
    service, repository, gateway, _tracker = _service()
    repository.attempts["expired-operation"] = {
        "id": "expired-row",
        "project_id": "p1",
        "draft_id": "draft-1",
        "operation_id": "expired-operation",
        "idempotency_key": "expired-key",
        "request_fingerprint": "6" * 64,
        "binding_revision_id": "binding-1",
        "binding_revision": 1,
        "binding_hash": "5" * 64,
        "provider_id": "provider-1",
        "model_name_snapshot": "deepseek-v4-flash",
        "fencing_token": 1,
        "lease_expires_at": NOW - 1,
        "input_manifest_json": "{}",
        "input_manifest_hash": "7" * 64,
        "status": "pending",
        "active_slot": 1,
        "failure_code": None,
        "loaded_draft_revision": None,
    }

    result = await service.generate(_command("fresh-key"))

    assert repository.attempts["expired-operation"]["status"] == "superseded"
    assert repository.attempts[result.operation_id]["fencing_token"] == 2
    assert result.loaded is True
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_gateway_failure_and_malformed_result_terminalize_without_loading():
    for output, code in (
        (PlanningProviderError("Planning provider failed"), "PlanningProviderFailed"),
        ({"not": "a planning draft"}, "PlanningProviderResultInvalid"),
    ):
        service, repository, gateway, _tracker = _service(
            gateway=FakeGateway(output)
        )

        result = await service.generate(_command())

        assert result.status == "failed"
        assert result.failure_code == code
        assert result.loaded is False
        assert repository.load_calls == 0
        assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("output", "failure_code"),
    (
        (
            PlanningProviderError("Planning provider failed"),
            "PlanningProviderFailed",
        ),
        ({"not": "a planning draft"}, "PlanningProviderResultInvalid"),
    ),
    ids=("provider-failure", "invalid-result"),
)
async def test_cancel_during_first_settlement_await_still_releases_owned_attempt(
    output,
    failure_code,
):
    repository = SettlementBarrierRepository()
    tracker = TransactionTracker()
    service, repository, _gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(output),
        tracker=tracker,
    )
    pending = asyncio.create_task(service.generate(_command()))
    await repository.settlement_entered.wait()

    pending.cancel()
    repository.release_settlement.set()
    with pytest.raises(asyncio.CancelledError):
        await pending

    attempt = repository.attempts["operation-1"]
    assert attempt["status"] == "failed"
    assert attempt["active_slot"] is None
    assert attempt["failure_code"] == failure_code
    assert repository.draft["draft_revision"] == 1
    assert repository.draft["source_attempt_id"] is None
    assert repository.load_calls == 0
    assert tracker.active == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel_count", (2, 4))
async def test_multiple_cancellations_wait_for_owned_settlement_and_leave_no_task(
    cancel_count,
):
    repository = SettlementBarrierRepository()
    tracker = TransactionTracker()
    service, repository, _gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(
            PlanningProviderError("Planning provider failed")
        ),
        tracker=tracker,
    )
    pending = asyncio.create_task(service.generate(_command()))
    await repository.settlement_entered.wait()

    for _ in range(cancel_count):
        pending.cancel()
        await asyncio.sleep(0)
        assert not pending.done()
    repository.release_settlement.set()
    with pytest.raises(asyncio.CancelledError):
        await pending
    await asyncio.sleep(0)

    attempt = repository.attempts["operation-1"]
    assert attempt["status"] == "failed"
    assert attempt["active_slot"] is None
    assert pending.cancelled() is True
    assert pending.cancelling() == cancel_count
    assert not [
        task
        for task in asyncio.all_tasks()
        if not task.done()
        and task.get_name() == "planning-generation-settlement"
    ]


@pytest.mark.asyncio
async def test_cancelled_wait_propagates_finished_settlement_failure_without_leak():
    service, _repository, _gateway, _tracker = _service()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def failing_settlement():
        entered.set()
        await release.wait()
        raise RuntimeError("SETTLEMENT_FAILURE_SENTINEL")

    pending = asyncio.create_task(
        service._await_settlement(failing_settlement())
    )
    await entered.wait()
    pending.cancel()
    await asyncio.sleep(0)
    pending.cancel()
    await asyncio.sleep(0)
    release.set()

    with pytest.raises(
        RuntimeError, match="^SETTLEMENT_FAILURE_SENTINEL$"
    ):
        await pending
    await asyncio.sleep(0)
    assert pending.cancelled() is False
    assert pending.cancelling() == 0
    assert not [
        task
        for task in asyncio.all_tasks()
        if not task.done()
        and task.get_name() == "planning-generation-settlement"
    ]


@pytest.mark.asyncio
async def test_author_save_during_generation_supersedes_without_loading():
    repository = FakePlanningRepository()

    def author_save():
        repository.draft["draft_revision"] += 1
        repository.draft["content_hash"] = "9" * 64

    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(hook=author_save),
    )

    result = await service.generate(_command())

    assert result.status == "superseded"
    assert result.loaded is False
    assert result.loaded_draft_revision is None
    assert repository.draft["draft_revision"] == 2
    assert repository.draft["content_hash"] == "9" * 64
    assert repository.load_calls == 0
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "persisted_manifest",
    ("{}", "{"),
    ids=("valid-but-tampered", "invalid-json"),
)
async def test_persisted_manifest_tamper_supersedes_without_loading(
    persisted_manifest,
):
    repository = FakePlanningRepository()

    def tamper_manifest():
        repository.attempts["operation-1"]["input_manifest_json"] = (
            persisted_manifest
        )

    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(hook=tamper_manifest),
    )

    result = await service.generate(_command())

    assert result.status == "superseded"
    assert result.loaded is False
    assert result.loaded_draft_revision is None
    assert repository.draft["draft_revision"] == 1
    assert repository.draft["source_attempt_id"] is None
    assert repository.load_calls == 0
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_publish_treats_lease_equal_to_now_as_expired():
    repository = FakePlanningRepository()
    current_time = [NOW]

    def reach_exact_expiry():
        current_time[0] = NOW + 240_000

    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(hook=reach_exact_expiry),
        clock=lambda: current_time[0],
    )

    result = await service.generate(_command())

    assert result.status == "superseded"
    assert result.loaded is False
    assert result.loaded_draft_revision is None
    assert repository.draft["draft_revision"] == 1
    assert repository.load_calls == 0
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "drift",
    ("project", "basis", "head", "binding", "provider"),
)
async def test_authority_drift_never_overwrites_draft(drift):
    repository = FakePlanningRepository()

    def mutate():
        if drift == "project":
            repository.project["archived_at"] = NOW
        elif drift == "basis":
            repository.basis["bible_hash"] = "8" * 64
        elif drift == "head":
            repository.head["revision"] = 1
        elif drift == "binding":
            repository.binding["binding_hash"] = "8" * 64
        else:
            repository.binding["revision"] = 2

    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=FakeGateway(hook=mutate),
    )

    result = await service.generate(_command())

    assert result.status == "superseded"
    assert result.loaded is False
    assert repository.draft["draft_revision"] == 1
    assert repository.load_calls == 0
    assert len(gateway.calls) == 1


@pytest.mark.asyncio
async def test_stale_fence_cannot_publish_after_expired_attempt_was_superseded():
    repository = FakePlanningRepository()
    tracker = TransactionTracker()
    gateway = BlockingGateway(tracker=tracker)
    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
        tracker=tracker,
    )

    pending = asyncio.create_task(service.generate(_command()))
    await gateway.entered.wait()
    attempt = repository.attempts["operation-1"]
    attempt.update(status="superseded", active_slot=None)
    gateway.release.set()
    result = await pending

    assert result.status == "superseded"
    assert result.loaded is False
    assert repository.load_calls == 0


@pytest.mark.asyncio
async def test_cancellation_releases_owned_lease_without_loading():
    repository = FakePlanningRepository()
    tracker = TransactionTracker()
    gateway = BlockingGateway(tracker=tracker)
    service, repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
        tracker=tracker,
    )
    pending = asyncio.create_task(service.generate(_command()))
    await gateway.entered.wait()

    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    assert repository.attempts["operation-1"]["status"] == "failed"
    assert repository.attempts["operation-1"]["failure_code"] == (
        "PlanningGenerationCancelled"
    )
    assert repository.load_calls == 0
    assert tracker.active == 0


@pytest.mark.asyncio
async def test_get_operation_is_pure_query_with_no_gateway_or_hidden_retry():
    service, _repository, gateway, tracker = _service()
    generated = await service.generate(_command())
    calls_before = len(gateway.calls)
    entries_before = tracker.entries
    lock_reads_before = _repository.lock_operation_reads
    plain_reads_before = _repository.plain_operation_reads

    observed = await service.get_operation("p1", generated.operation_id)

    assert observed == generated
    assert len(gateway.calls) == calls_before
    assert tracker.entries == entries_before + 1
    assert _repository.lock_operation_reads == lock_reads_before
    assert _repository.plain_operation_reads == plain_reads_before + 1


@pytest.mark.asyncio
async def test_get_operation_by_key_is_one_pure_read_with_no_hidden_work():
    service, repository, gateway, tracker = _service()
    generated = await service.generate(_command("recovery-key"))
    calls_before = len(gateway.calls)
    entries_before = tracker.entries
    key_reads_before = repository.plain_key_reads
    operation_reads_before = repository.plain_operation_reads
    lock_reads_before = repository.lock_operation_reads
    repository.lock_order.clear()

    observed = await service.get_operation_by_key("p1", "recovery-key")

    assert observed == generated
    assert repository.lock_order == ["idempotency-read"]
    assert tracker.entries == entries_before + 1
    assert repository.plain_key_reads == key_reads_before + 1
    assert repository.plain_operation_reads == operation_reads_before
    assert repository.lock_operation_reads == lock_reads_before
    assert len(gateway.calls) == calls_before


@pytest.mark.asyncio
async def test_get_operation_by_key_uses_one_fixed_safe_not_found():
    from backend.services.planning_generation import (
        PlanningGenerationOperationNotFound,
        PlanningGenerationRequestInvalid,
    )

    service, repository, gateway, tracker = _service()
    entries_before = tracker.entries

    with pytest.raises(PlanningGenerationOperationNotFound) as missing:
        await service.get_operation_by_key("p1", "missing-key")
    with pytest.raises(PlanningGenerationRequestInvalid) as invalid:
        await service.get_operation_by_key("p1", "bad/key")

    assert str(missing.value) == "Planning generation operation not found"
    assert str(invalid.value) == "Planning generation request is invalid"
    assert "missing-key" not in repr(missing.value)
    assert "bad/key" not in repr(invalid.value)
    assert repository.plain_key_reads == 1
    assert tracker.entries == entries_before + 1
    assert gateway.calls == []


@pytest.mark.asyncio
async def test_sensitive_keys_fail_before_repository_or_gateway_with_fixed_error():
    for key in SENSITIVE_PLANNING_KEYS:
        service, repository, gateway, tracker = _service()

        with pytest.raises(PublicDomainError) as generated:
            await service.generate(_command(key))
        with pytest.raises(PublicDomainError) as recovered:
            await service.get_operation_by_key("p1", key)

        for caught in (generated, recovered):
            assert caught.value.code == "PlanningGenerationRequestInvalid"
            assert str(caught.value) == "Planning generation request is invalid"
            assert key not in str(caught.value)
            assert key not in repr(caught.value)
        assert tracker.entries == 0
        assert repository.lock_order == []
        assert repository.plain_key_reads == 0
        assert gateway.calls == []


@pytest.mark.asyncio
async def test_ordinary_closed_key_remains_valid_for_generate_and_recovery():
    for key in (
        "planning-2026.07:attempt_1",
        "123e4567-e89b-12d3-a456-426614174000",
    ):
        service, _repository, _gateway, _tracker = _service()

        generated = await service.generate(_command(key))
        recovered = await service.get_operation_by_key("p1", key)

        assert recovered == generated


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stage", "code"),
    (("reserve", 1213), ("get", 1205), ("settlement", 3572)),
)
async def test_mysql_coordination_failures_map_to_one_safe_retryable_error(
    stage,
    code,
):
    from backend.services.planning_generation import (
        PlanningGenerationRetryable,
    )

    repository = CoordinationFailureRepository(stage, code)
    gateway = FakeGateway(
        PlanningProviderError("Planning provider failed")
    )
    service, _repository, gateway, _tracker = _service(
        repository=repository,
        gateway=gateway,
    )

    with pytest.raises(PlanningGenerationRetryable) as caught:
        if stage == "get":
            await service.get_operation("p1", "operation-1")
        else:
            await service.generate(_command())

    assert str(caught.value) == (
        "Planning state changed; retry this request safely."
    )
    assert caught.value.__cause__ is None
    assert "RAW_DATABASE_COORDINATION_SENTINEL" not in repr(caught.value)
    assert len(gateway.calls) == (1 if stage == "settlement" else 0)


@pytest.mark.asyncio
async def test_expired_reconciliation_exhaustion_is_safe_retryable():
    from backend.services.planning_generation import (
        PlanningGenerationRetryable,
    )

    repository = ExhaustingExpiredRepository()
    service, repository, gateway, _tracker = _service(
        repository=repository
    )

    with pytest.raises(PlanningGenerationRetryable) as caught:
        await service.generate(_command("new-request-key"))

    assert caught.value.status_code == 503
    assert caught.value.retryable is True
    assert str(caught.value) == (
        "Planning state changed; retry this request safely."
    )
    assert repository.reserve_reads == 3
    assert repository.settles == 3
    assert gateway.calls == []


def test_coordination_classifier_requires_all_explicit_mysql_leaves():
    from backend.services.planning_generation import (
        PlanningGenerationService,
    )

    direct = OperationalError(1213, "direct")
    pure_group = ExceptionGroup(
        "pure",
        [
            OperationalError(1205, "timeout"),
            ExceptionGroup(
                "nested",
                [OperationalError(3572, "nowait")],
            ),
        ],
    )
    mixed_group = ExceptionGroup(
        "mixed",
        [OperationalError(1213, "deadlock"), RuntimeError("bug")],
    )
    try:
        try:
            raise OperationalError(1213, "implicit")
        except OperationalError:
            raise RuntimeError("programming failure")
    except RuntimeError as error:
        implicit_context = error
    assert isinstance(implicit_context.__context__, OperationalError)

    assert PlanningGenerationService._is_coordination_failure(direct)
    assert PlanningGenerationService._is_coordination_failure(pure_group)
    assert not PlanningGenerationService._is_coordination_failure(
        mixed_group
    )
    assert not PlanningGenerationService._is_coordination_failure(
        implicit_context
    )


def test_public_result_has_no_secret_prompt_raw_manifest_or_dsn_fields():
    from dataclasses import fields

    from backend.services.planning_generation import PlanningOperationResult

    names = {field.name for field in fields(PlanningOperationResult)}
    assert names == {
        "operation_id",
        "status",
        "failure_code",
        "model",
        "loaded",
        "loaded_draft_revision",
    }
    assert not names.intersection(
        {"api_key", "prompt", "raw_output", "manifest", "dsn"}
    )
