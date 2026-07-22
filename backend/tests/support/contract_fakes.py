from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from copy import deepcopy

from backend.domain.json_contracts import canonical_hash, canonical_json
from backend.domain.model_bindings import TASK_KEYS, BindingItem, BindingRevision
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
                "selection_revision": 7,
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
                "selection_revision": 7,
                "seed_revision_id": "seed-revision-1",
                "seed_hash": seed_hash,
                "payload_json": canonical_json(engine_payload),
                "content_hash": engine_hash,
            }
        }
        binding_items = tuple(BindingItem(
            task_key=task,
            resolution_status="bound",
            provider_id=f"provider-{task}",
            provider_name_snapshot=f"Provider {task}",
            model_name_snapshot=f"model-{task}",
        ) for task in TASK_KEYS)
        binding_hash = canonical_hash(BindingRevision(
            project_id="p1", revision=3, items=binding_items,
        ))
        self.binding = {
            "project_id": "p1",
            "revision": 3,
            "binding_revision_id": "binding-revision-3",
            "content_hash": binding_hash,
            "items": tuple(
                {
                    **item.model_dump(mode="python"),
                    "item_hash": canonical_hash(item),
                    "provider_ready": 1,
                }
                for item in binding_items
            ),
        }
        self.binding_revisions = {
            "binding-revision-3": self.binding,
        }
        self.binding_head = {
            "head_revision": 3,
            "head_binding_revision_id": "binding-revision-3",
            "head_hash": binding_hash,
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
                "revision_id": "source-revision-5",
                "source_key": "authorized-work",
                "revision": 5,
                "source_hash": "e" * 64,
                "status": "analyzed",
                "title": "授权作品",
                "author": "作者",
                "head_id": "source-revision-5",
                "head_revision": 5,
                "head_hash": "e" * 64,
            }
        }
        self.fragments = {
            "fragment-1": {
                "source_id": "source-1",
                "source_revision_id": "source-revision-5",
                "source_revision": 5,
                "source_hash": "e" * 64,
                "source_archived_at": None,
                "source_head_revision_id": "source-revision-5",
                "source_head_revision": 5,
                "source_head_hash": "e" * 64,
                "source_status": "analyzed",
                "chapter_id": "chapter-1",
                "fragment_id": "fragment-1",
                "fragment_hash": "f" * 64,
                "fragment_char_start": 0,
                "fragment_char_end": 200,
                "chapter_char_start": 10,
                "chapter_char_end": 110,
                "normalized_text": "县志在雨里翻开，墨迹正慢慢改写县令的死期。" * 4,
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
        self.confirmed_revisions: dict[tuple[str, int], dict] = {}
        self.confirmation_requests: dict[tuple[str, str], dict] = {}
        self.creation_contracts: dict[str, dict] = {}
        self.style_contracts: dict[str, dict] = {}
        self.engine_refs: dict[str, dict] = {}
        self.style_refs: list[dict] = []
        self.experience_refs: list[dict] = []
        self.corpus_refs: list[dict] = []
        self.corpus_fragment_refs: list[dict] = []
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

    async def lock_contract_head(self, session, project_id):
        self.events.append("lock-contract-head")
        return await self.read_contract_head(session, project_id)

    async def read_confirmation_request(self, session, project_id, key):
        return deepcopy(self.confirmation_requests.get((project_id, key)))

    async def insert_confirmation_request(self, session, row):
        key = (row["project_id"], row["idempotency_key"])
        if key in self.confirmation_requests:
            return False
        self.confirmation_requests[key] = deepcopy(row) | {"status": "reserved"}
        return True

    async def insert_creation_contract(self, session, row):
        if row["id"] in self.creation_contracts:
            return False
        self.creation_contracts[row["id"]] = deepcopy(row)
        return True

    async def insert_style_contract(self, session, row):
        if row["id"] in self.style_contracts:
            return False
        self.style_contracts[row["id"]] = deepcopy(row)
        return True

    async def insert_engine_ref(self, session, row):
        self.engine_refs[row["creation_contract_id"]] = deepcopy(row)
        return True

    async def insert_style_refs(self, session, rows):
        self.style_refs.extend(deepcopy(rows))
        return True

    async def insert_experience_refs(self, session, rows):
        self.experience_refs.extend(deepcopy(rows))
        return True

    async def insert_corpus_refs(self, session, rows):
        self.corpus_refs.extend(deepcopy(rows))
        return True

    async def insert_corpus_fragment_refs(self, session, rows):
        self.corpus_fragment_refs.extend(deepcopy(rows))
        return True

    async def cas_contract_head(self, session, row):
        current = self.heads.get(row["project_id"])
        if current is None or current["revision"] != row["base_revision"]:
            return False
        self.heads[row["project_id"]] = {
            "project_id": row["project_id"], "revision": row["revision"],
            "creation_contract_id": row["creation_contract_id"],
            "style_contract_id": row["style_contract_id"],
            "creation_hash": row["creation_hash"], "style_hash": row["style_hash"],
        }
        return True

    async def delete_draft_cas(self, session, project_id, version, content_hash):
        row = self.drafts.get(project_id)
        if row is None or row["draft_version"] != version or row["content_hash"] != content_hash:
            return False
        del self.drafts[project_id]
        return True

    async def succeed_confirmation_request(self, session, row):
        key = (row["project_id"], row["idempotency_key"])
        request = self.confirmation_requests.get(key)
        if request is None or request["status"] != "reserved" or request["request_hash"] != row["request_hash"]:
            return False
        request.update(deepcopy(row) | {
            "status": "succeeded", "result_revision": row["result_revision"],
        })
        creation = self.creation_contracts[row["creation_contract_id"]]
        style = self.style_contracts[row["style_contract_id"]]
        engine = self.engine_refs[row["creation_contract_id"]]
        creation_payload = json.loads(creation["content_json"])
        binding_ref = creation_payload.get("modelBindingRef")
        corpus_refs = tuple(
            ref for ref in self.corpus_refs
            if ref["creation_contract_id"] == creation["id"]
        )
        snapshot = {
            "project_id": row["project_id"],
            "revision": row["result_revision"],
            "selection_revision": creation["selection_revision"],
            "seed_id": creation["seed_id"],
            "seed_revision_id": creation["seed_revision_id"],
            "seed_hash": creation["seed_hash"],
            "engine_option_id": engine["engine_option_id"],
            "engine_hash": engine["engine_hash"],
            "engine_batch_id": self.engines[engine["engine_option_id"]]["batch_id"],
            "binding_revision_id": creation["binding_revision_id"],
            "binding_revision": (
                int(binding_ref["revision"]) if binding_ref else None
            ),
            "binding_hash": creation["binding_hash"],
            "creation_hash": creation["content_hash"],
            "style_hash": style["content_hash"],
            "creation_json": creation["content_json"],
            "style_json": style["merged_style_json"],
            "likes_json": style["likes_json"],
            "dislikes_json": style["dislikes_json"],
            "style_contract_id": style["id"],
            "creation_contract_id": creation["id"],
            "reference_manifest_json": creation["reference_manifest_json"],
            "reference_manifest_hash": creation["reference_manifest_hash"],
            "style_refs": tuple({
                "role": ref["role"], "id": ref["style_template_id"],
                "revision": ref["asset_revision"], "contentHash": ref["asset_hash"],
            } for ref in self.style_refs if ref["style_contract_id"] == style["id"]),
            "experience_card_refs": tuple({
                "id": ref["experience_card_id"], "revision": ref["asset_revision"],
                "contentHash": ref["asset_hash"],
            } for ref in self.experience_refs if ref["creation_contract_id"] == creation["id"]),
            "corpus_source_refs": tuple({
                "id": ref["corpus_source_id"],
                "revisionId": next(
                    source_ref["revisionId"]
                    for source_ref in creation_payload["corpusSourceRefs"]
                    if source_ref["id"] == ref["corpus_source_id"]
                ),
                "revision": ref["source_revision"],
                "contentHash": ref["source_hash"],
                "selectionMode": ref["selection_mode"],
                "pinnedHistoricalRevision": next(
                    source_ref["pinnedHistoricalRevision"]
                    for source_ref in creation_payload["corpusSourceRefs"]
                    if source_ref["id"] == ref["corpus_source_id"]
                ),
                "fragments": tuple({
                    "chapterId": fragment["corpus_chapter_id"],
                    "fragmentId": fragment["corpus_fragment_id"],
                    "fragmentHash": fragment["fragment_hash"],
                    "chapterCharStart": fragment["chapter_char_start"],
                    "chapterCharEnd": fragment["chapter_char_end"],
                    "referenceUse": fragment["reference_use"],
                } for fragment in self.corpus_fragment_refs
                  if fragment["creation_contract_id"] == creation["id"]
                  and fragment["corpus_source_id"] == ref["corpus_source_id"]),
            } for ref in corpus_refs),
            "corpus_fragment_refs": tuple({
                "sourceId": ref["corpus_source_id"],
                "chapterId": ref["corpus_chapter_id"],
                "fragmentId": ref["corpus_fragment_id"],
                "fragmentHash": ref["fragment_hash"],
                "chapterCharStart": ref["chapter_char_start"],
                "chapterCharEnd": ref["chapter_char_end"],
                "referenceUse": ref["reference_use"],
            } for ref in self.corpus_fragment_refs
              if ref["creation_contract_id"] == creation["id"]),
        }
        self.confirmed[row["project_id"]] = snapshot
        self.confirmed_revisions[(
            row["project_id"], row["result_revision"]
        )] = snapshot
        return True

    async def list_contract_revisions(self, session, project_id, limit):
        rows = [
            {"revision": row["revision"]}
            for row in self.creation_contracts.values()
            if row["project_id"] == project_id
        ]
        return sorted(rows, key=lambda row: row["revision"], reverse=True)[:limit]

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

    async def read_seed_revision(self, session, project_id, revision_id, *, lock=False):
        row = self.seed_revisions.get(revision_id)
        return deepcopy(row) if project_id == "p1" and row else None

    async def read_engine_option(self, session, project_id, option_id, *, lock=False):
        row = self.engines.get(option_id)
        return deepcopy(row) if row and row["project_id"] == project_id else None

    async def read_binding_snapshot(
        self, session, project_id, binding_revision_id=None
    ):
        if project_id != "p1":
            return None
        revision_id = binding_revision_id or self.binding_head.get(
            "head_binding_revision_id"
        )
        if revision_id is None:
            return None
        revision = self.binding_revisions.get(revision_id)
        return deepcopy(revision | self.binding_head) if revision else None

    async def lock_binding_snapshot(self, session, project_id):
        return await self.read_binding_snapshot(session, project_id)

    async def read_style_revision(self, session, asset_id, *, lock=False):
        if lock:
            self.events.append(f"lock-asset:style:{asset_id}")
        return deepcopy(self.styles.get(asset_id))

    async def read_experience_revision(self, session, asset_id, *, lock=False):
        if lock:
            self.events.append(f"lock-asset:experience:{asset_id}")
        return deepcopy(self.cards.get(asset_id))

    async def read_corpus_revision(
        self, session, asset_id, revision_id=None, *, lock=False
    ):
        if lock:
            self.events.append(f"lock-asset:corpus:{asset_id}")
        return deepcopy(self.sources.get(asset_id))

    async def read_corpus_fragments(
        self, session, source_id, revision_id, fragment_ids, *, lock=False
    ):
        if lock:
            self.events.append(f"lock-fragments:{source_id}:{revision_id}")
        return tuple(
            deepcopy(self.fragments[fragment_id])
            for fragment_id in fragment_ids
            if fragment_id in self.fragments
            and self.fragments[fragment_id]["source_id"] == source_id
            and self.fragments[fragment_id]["source_revision_id"] == revision_id
        )

    async def read_confirmed_snapshot(self, session, project_id, revision=None):
        stored = (
            self.confirmed.get(project_id)
            if revision is None
            else self.confirmed_revisions.get((project_id, revision))
        )
        if stored is None and revision is not None:
            current = self.confirmed.get(project_id)
            stored = (
                current
                if current is not None and current["revision"] == revision
                else None
            )
        if stored is None:
            return None
        snapshot = deepcopy(stored)
        binding = self.binding_revisions.get(snapshot["binding_revision_id"])
        snapshot["binding_items"] = deepcopy((binding or {}).get("items") or ())
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
            for fragment_ref in ref["fragments"]:
                fragment = self.fragments.get(fragment_ref["fragmentId"])
                fragment_ref["actualContentHash"] = (
                    fragment["fragment_hash"] if fragment else None
                )
        for ref in snapshot["corpus_fragment_refs"]:
            fragment = self.fragments.get(ref["fragmentId"])
            ref["actualContentHash"] = (
                fragment["fragment_hash"] if fragment else None
            )
        return snapshot


class ContractHarness:
    def __init__(self, *, failpoint=lambda _stage: None):
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
            failpoint=failpoint,
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
        "schemaVersion": "contract-draft-v2",
        "draftStage": "assets",
        "engineOptionId": engine["id"],
        "engineHash": engine["content_hash"],
        "channelProfileKey": "web-fiction",
        "genreProfileKey": "eastern-fantasy",
        "qualityCharterVersion": "writer-core-quality-v1",
        "targetTotalWords": 1_000_000,
        "expectedVolumeCount": 8,
        "expectedChapterCount": 400,
        "chapterWordRangePreference": (2_500, 3_500),
        "prohibitedDirections": ("不写无代价升级",),
        "authorNotes": "人物选择优先于设定展示。",
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
            "id": source["id"], "revisionId": source["revision_id"],
            "revision": source["revision"],
            "contentHash": source["source_hash"], "selectionMode": "author",
            "fragments": ({
                "chapterId": "chapter-1",
                "fragmentId": "fragment-1",
                "fragmentHash": "f" * 64,
                "chapterCharStart": 10,
                "chapterCharEnd": 110,
                "referenceUse": "style",
            },),
            "pinnedHistoricalRevision": False,
        },),
        "likes": ("选择有代价",),
        "dislikes": ("空泛升级",),
    }
    values.update(overrides)
    return values
