from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS
from backend.tests.support.story_engine_fakes import option


SEED_PAYLOAD = {
    "title": "典镇山河",
    "genre": "东方奇幻",
    "logline": "少年以县志镇压黑潮。",
    "protagonist": "沈码",
    "desire": "让被抹去的乡民重获姓名。",
    "coreConflict": "修史会同时唤醒镇物。",
    "worldPressure": "黑潮上涨，王朝封存旧志。",
    "openingHook": "县志预写了新县令的死期。",
    "differentiation": "以地方志书写为力量体系。",
}


def style_asset(*, flavor: str, distance: str = "近距离第三人称") -> dict:
    return {
        "schema_version": "style-template-v1",
        "reading_experience": flavor,
        "narrative_distance": distance,
        "rhythm": "行动段短促，反思段舒展",
        "diction_density": "低修辞密度",
        "dialogue": "对白简短",
        "subtext": "冲突藏在回避中",
        "character_voices": "主角克制，县令锋利",
        "emotion": "以选择承载情绪",
        "interiority": "内心活动贴近当下感官",
        "action": "先写动作",
        "explanation": "动作后解释",
        "environment": "环境参与阻碍",
        "body_response": "压力通过呼吸与肌肉反应显现",
        "preferred_techniques": [flavor, "避免空泛抒情"],
        "risks": ["节奏可能过冷"],
    }


class MemoryContractRepository:
    def __init__(self):
        seed_hash = canonical_hash(SEED_PAYLOAD)
        engine_payload = option(1)
        engine_hash = canonical_hash(engine_payload)
        primary = style_asset(flavor="克制现实主义")
        secondary = style_asset(flavor="章回体悬念", distance="全知视角")
        card_payload = {"schemaVersion": "experience-card-v1", "rule": "让选择不可逆"}
        self.projects = {
            "p1": {"id": "p1", "status": "drafting"},
            "archived": {"id": "archived", "status": "archived"},
        }
        self.selected_seeds = {
            "p1": {
                "seed_id": "seed-1",
                "seed_revision_id": "seed-revision-1",
                "seed_hash": seed_hash,
                "payload_json": canonical_json(SEED_PAYLOAD),
            }
        }
        self.seed_revisions = {
            "seed-revision-1": dict(self.selected_seeds["p1"])
        }
        self.engines = {
            "engine-1": {
                "id": "engine-1",
                "project_id": "p1",
                "batch_id": "batch-1",
                "status": "succeeded",
                "seed_revision_id": "seed-revision-1",
                "seed_hash": seed_hash,
                "payload_json": canonical_json(engine_payload),
                "content_hash": engine_hash,
            }
        }
        self.binding = {
            "revision": 3,
            "binding_revision_id": "binding-revision-3",
            "content_hash": "b" * 64,
            "items": tuple(
                {
                    "task_key": task,
                    "resolution_status": "bound",
                    "provider_id": f"provider-{task}",
                    "provider_name_snapshot": f"Provider {task}",
                    "model_name_snapshot": f"model-{task}",
                    "provider_ready": 1,
                }
                for task in TASK_KEYS
            ),
        }
        self.binding_revisions = {
            "binding-revision-3": self.binding,
        }
        self.binding_head = {
            "head_revision": 3,
            "head_binding_revision_id": "binding-revision-3",
            "head_hash": "b" * 64,
        }
        self.styles = {
            "style-primary": self._asset_row(
                "style-primary", 2, primary, stable_key="restrained"
            ),
            "style-secondary": self._asset_row(
                "style-secondary", 4, secondary, stable_key="chapter-hook"
            ),
        }
        self.cards = {
            "card-1": self._asset_row(
                "card-1", 3, card_payload, stable_key="irreversible-choice"
            )
        }
        self.sources = {
            "source-1": {
                "id": "source-1",
                "source_key": "authorized-work",
                "revision": 5,
                "source_hash": "e" * 64,
                "status": "analyzed",
                "title": "授权作品",
                "author": "作者",
                "head_id": "source-1",
                "head_revision": 5,
                "head_hash": "e" * 64,
            }
        }
        self.heads = {
            "p1": {
                "project_id": "p1",
                "revision": 0,
                "creation_contract_id": None,
                "style_contract_id": None,
                "creation_hash": None,
                "style_hash": None,
            }
        }
        self.drafts: dict[str, dict] = {}
        self.confirmed: dict[str, dict] = {}
        self.write_count = 0
        self.events: list[str] = []

    @staticmethod
    def _asset_row(asset_id, revision, payload, *, stable_key):
        content_hash = canonical_hash(payload)
        return {
            "id": asset_id,
            "name": "克制现实" if asset_id == "style-primary" else "章回悬念",
            "stable_key": stable_key,
            "revision": revision,
            "payload_json": canonical_json(payload),
            "content_hash": content_hash,
            "status": "active",
            "head_id": asset_id,
            "head_revision": revision,
            "head_hash": content_hash,
        }

    async def read_project(self, session, project_id):
        row = self.projects.get(project_id)
        return dict(row) if row and row["status"] != "archived" else None

    async def lock_project(self, session, project_id):
        return await self.read_project(session, project_id)

    async def read_draft(self, session, project_id):
        row = self.drafts.get(project_id)
        return deepcopy(row) if row else None

    async def lock_draft(self, session, project_id):
        return await self.read_draft(session, project_id)

    async def read_contract_head(self, session, project_id):
        row = self.heads.get(project_id)
        return deepcopy(row) if row else None

    async def insert_draft(self, session, row):
        self.events.append("insert-draft")
        self.write_count += 1
        if row["project_id"] in self.drafts:
            raise AssertionError("one draft per project")
        self.drafts[row["project_id"]] = deepcopy(row)

    async def cas_update_draft(self, session, row, expected_version):
        self.events.append("cas-update-draft")
        current = self.drafts.get(row["project_id"])
        if current is None or current["draft_version"] != expected_version:
            return False
        self.write_count += 1
        self.drafts[row["project_id"]] = deepcopy(row)
        return True

    async def read_selected_seed(self, session, project_id):
        return deepcopy(self.selected_seeds.get(project_id))

    async def lock_selected_seed(self, session, project_id):
        self.events.append("lock-selected-seed")
        return await self.read_selected_seed(session, project_id)

    async def read_seed_revision(self, session, project_id, revision_id):
        row = self.seed_revisions.get(revision_id)
        return deepcopy(row) if project_id == "p1" and row else None

    async def read_engine_option(self, session, project_id, option_id):
        row = self.engines.get(option_id)
        return deepcopy(row) if row and row["project_id"] == project_id else None

    async def read_binding_snapshot(
        self, session, project_id, binding_revision_id=None
    ):
        if project_id != "p1":
            return None
        revision_id = binding_revision_id or self.binding_head[
            "head_binding_revision_id"
        ]
        revision = self.binding_revisions.get(revision_id)
        return deepcopy(revision | self.binding_head) if revision else None

    async def lock_binding_snapshot(self, session, project_id):
        return await self.read_binding_snapshot(session, project_id)

    async def read_style_revision(self, session, asset_id):
        return deepcopy(self.styles.get(asset_id))

    async def read_experience_revision(self, session, asset_id):
        return deepcopy(self.cards.get(asset_id))

    async def read_corpus_revision(self, session, asset_id):
        return deepcopy(self.sources.get(asset_id))

    async def read_confirmed_snapshot(self, session, project_id):
        stored = self.confirmed.get(project_id)
        if stored is None:
            return None
        snapshot = deepcopy(stored)
        binding = self.binding_revisions.get(snapshot["binding_revision_id"])
        seed = self.seed_revisions.get(snapshot["seed_revision_id"])
        engine = self.engines.get(snapshot["engine_option_id"])
        snapshot["actual_binding_hash"] = (
            binding["content_hash"] if binding else None
        )
        snapshot["actual_seed_hash"] = seed["seed_hash"] if seed else None
        snapshot["actual_engine_hash"] = (
            engine["content_hash"] if engine else None
        )
        for ref in snapshot["style_refs"]:
            asset = self.styles.get(ref["id"])
            ref["actualContentHash"] = (
                asset["content_hash"]
                if asset and asset["revision"] == ref["revision"] else None
            )
        for ref in snapshot["experience_card_refs"]:
            asset = self.cards.get(ref["id"])
            ref["actualContentHash"] = (
                asset["content_hash"]
                if asset and asset["revision"] == ref["revision"] else None
            )
        for ref in snapshot["corpus_source_refs"]:
            asset = self.sources.get(ref["id"])
            ref["actualContentHash"] = (
                asset["source_hash"]
                if asset and asset["revision"] == ref["revision"] else None
            )
        return snapshot


class ContractHarness:
    def __init__(self):
        from backend.services.contracts import ContractService

        self.repository = MemoryContractRepository()
        self._lock = asyncio.Lock()
        self.transaction_enter_count = 0
        self.connection_enter_count = 0
        ids = iter(f"draft-{number}" for number in range(1, 50))
        self.service = ContractService(
            self.repository,
            transaction_factory=self.transaction,
            connection_factory=self.connection,
            id_factory=lambda: next(ids),
            clock=lambda: 1_000_000,
        )

    @asynccontextmanager
    async def transaction(self):
        async with self._lock:
            snapshot = deepcopy(self.repository.__dict__)
            self.transaction_enter_count += 1
            try:
                yield object()
            except BaseException:
                self.repository.__dict__.clear()
                self.repository.__dict__.update(snapshot)
                raise

    @asynccontextmanager
    async def connection(self):
        self.connection_enter_count += 1
        yield object()


def draft_values(repository: MemoryContractRepository, **overrides):
    primary = repository.styles["style-primary"]
    secondary = repository.styles["style-secondary"]
    card = repository.cards["card-1"]
    source = repository.sources["source-1"]
    engine = repository.engines["engine-1"]
    values = {
        "schemaVersion": "contract-draft-v1",
        "engineOptionId": engine["id"],
        "engineHash": engine["content_hash"],
        "channelProfileKey": "web-fiction",
        "genreProfileKey": "eastern-fantasy",
        "qualityCharterVersion": "writer-core-quality-v1",
        "totalWordRange": (800_000, 1_200_000),
        "chapterCapacityPolicy": "每章推进一个不可逆选择",
        "primaryStyleRef": {
            "id": primary["id"], "revision": primary["revision"],
            "contentHash": primary["content_hash"],
        },
        "secondaryStyleRef": {
            "id": secondary["id"], "revision": secondary["revision"],
            "contentHash": secondary["content_hash"],
        },
        "experienceCardRefs": ({
            "id": card["id"], "revision": card["revision"],
            "contentHash": card["content_hash"],
        },),
        "corpusSourceRefs": ({
            "id": source["id"], "revision": source["revision"],
            "contentHash": source["source_hash"], "selectionMode": "author",
        },),
        "likes": ("选择有代价",),
        "dislikes": ("空泛升级",),
    }
    values.update(overrides)
    return values
