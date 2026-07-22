"""Session-bound persistence for immutable global writing assets."""

from __future__ import annotations

import json
import re
from typing import Literal

from backend.repositories.project_lifecycle import (
    lock_active_project,
    read_active_project,
)


AssetType = Literal["style", "card"]
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


_TABLES = {
    "style": {
        "revision": "style_templates",
        "head": "style_template_heads",
        "id_column": "style_template_id",
        "label_column": "name",
    },
    "card": {
        "revision": "experience_cards",
        "head": "experience_card_heads",
        "id_column": "experience_card_id",
        "label_column": "title",
    },
}


def _tables(asset_type: AssetType) -> dict[str, str]:
    try:
        return _TABLES[asset_type]
    except KeyError as exc:
        raise ValueError("unsupported asset type") from exc


class AssetRepository:
    """Issue only fixed SQL for style/card revision and head operations."""

    async def lock_schema_guard(self, session) -> None:
        row = await session.fetchone(
            "SELECT singleton_id FROM schema_metadata "
            "WHERE singleton_id=1 FOR UPDATE"
        )
        if row is None:
            raise RuntimeError("asset seed schema guard is unavailable")

    async def read_project(self, session, project_id: str):
        return await read_active_project(session, project_id)

    async def read_selected_seed(self, session, project_id: str):
        return await session.fetchone(
            """SELECT selected.seed_id, selected.selection_revision,
                      selected.seed_revision_id,
                      r.revision AS seed_revision,
                      selected.seed_hash, r.content_hash AS revision_hash,
                      r.payload_json
               FROM project_selected_seeds selected
               JOIN creative_seed_revisions r
                 ON r.project_id=selected.project_id
                AND r.seed_id=selected.seed_id
                AND r.id=selected.seed_revision_id
               WHERE selected.project_id=%s""",
            (project_id,),
        )

    async def read_engine_option(
        self,
        session,
        project_id: str,
        engine_option_id: str,
    ):
        return await session.fetchone(
            """SELECT o.id, o.project_id, o.payload_json, o.content_hash,
                      b.status AS batch_status, b.selection_revision, b.seed_id,
                      b.seed_revision_id, b.seed_hash
               FROM story_engine_options o
               JOIN story_engine_batches b
                 ON b.project_id=o.project_id AND b.id=o.batch_id
               WHERE o.project_id=%s AND o.id=%s""",
            (project_id, engine_option_id),
        )

    async def read_contract_draft(
        self,
        session,
        project_id: str,
        engine_option_id: str,
    ):
        return await session.fetchone(
            """SELECT engine_option_id,selection_revision,seed_hash,
                      draft_json,content_hash
               FROM project_contract_drafts
               WHERE project_id=%s AND engine_option_id=%s""",
            (project_id, engine_option_id),
        )

    async def list_active_revisions(self, session, asset_type: AssetType):
        tables = _tables(asset_type)
        category = "NULL AS category" if asset_type == "style" else "r.category"
        return await session.fetchall(
            f"SELECT r.id,r.stable_key,r.revision,"
            f"r.{tables['label_column']} AS label,{category},"
            "r.payload_json,r.provenance_json,r.content_hash,r.status "
            f"FROM {tables['head']} h JOIN {tables['revision']} r "
            f"ON r.stable_key=h.stable_key AND r.id=h.{tables['id_column']} "
            "AND r.revision=h.revision AND r.content_hash=h.content_hash "
            "WHERE r.status='active' ORDER BY r.stable_key ASC"
        )

    async def list_current_revisions(self, session, asset_type: AssetType):
        """Read only current heads, including an explicitly archived head."""

        tables = _tables(asset_type)
        category = "NULL AS category" if asset_type == "style" else "r.category"
        return await session.fetchall(
            f"SELECT r.id,r.stable_key,r.revision,"
            f"r.{tables['label_column']} AS label,{category},"
            "r.payload_json,r.provenance_json,r.content_hash,r.status "
            f"FROM {tables['head']} h JOIN {tables['revision']} r "
            f"ON r.stable_key=h.stable_key AND r.id=h.{tables['id_column']} "
            "AND r.revision=h.revision AND r.content_hash=h.content_hash "
            "WHERE r.status IN ('active','archived') "
            "ORDER BY r.stable_key ASC"
        )

    async def fetch_revision_by_id(
        self,
        session,
        asset_type: AssetType,
        revision_id: str,
    ):
        tables = _tables(asset_type)
        category = "NULL AS category" if asset_type == "style" else "r.category"
        return await session.fetchone(
            f"SELECT r.id,r.stable_key,r.revision,"
            f"r.{tables['label_column']} AS label,{category},r.payload_json,"
            "r.provenance_json,r.content_hash,r.status "
            f"FROM {tables['head']} h JOIN {tables['revision']} r "
            f"ON r.stable_key=h.stable_key AND r.id=h.{tables['id_column']} "
            "AND r.revision=h.revision AND r.content_hash=h.content_hash "
            "WHERE r.id=%s AND r.status IN ('active','archived')",
            (revision_id,),
        )

    async def list_heads(
        self,
        session,
        asset_type: AssetType,
        *,
        for_update: bool,
    ):
        tables = _tables(asset_type)
        lock = " FOR UPDATE" if for_update else ""
        return await session.fetchall(
            f"SELECT h.stable_key,h.{tables['id_column']} AS id,"
            f"h.revision,h.content_hash FROM {tables['head']} h "
            f"ORDER BY h.stable_key ASC{lock}"
        )

    async def fetch_revision(
        self,
        session,
        asset_type: AssetType,
        stable_key: str,
        revision: int,
    ):
        tables = _tables(asset_type)
        category = "NULL AS category" if asset_type == "style" else "category"
        return await session.fetchone(
            f"SELECT id,stable_key,revision,{tables['label_column']} AS label,"
            f"{category},payload_json,provenance_json,content_hash,status "
            f"FROM {tables['revision']} WHERE stable_key=%s AND revision=%s",
            (stable_key, revision),
        )

    async def list_revisions_for_key(
        self,
        session,
        asset_type: AssetType,
        stable_key: str,
        *,
        for_update: bool,
    ):
        table = _tables(asset_type)["revision"]
        lock = " FOR UPDATE" if for_update else ""
        return await session.fetchall(
            "SELECT id,stable_key,revision,content_hash,status "
            f"FROM {table} WHERE stable_key=%s ORDER BY revision ASC{lock}",
            (stable_key,),
        )

    async def insert_revision(
        self,
        session,
        asset_type: AssetType,
        row: dict,
    ) -> None:
        tables = _tables(asset_type)
        if asset_type == "style":
            sql = (
                "INSERT INTO style_templates "
                "(id,stable_key,revision,name,payload_json,provenance_json,"
                "content_hash,status,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            args = (
                row["id"], row["stable_key"], row["revision"], row["label"],
                row["payload_json"], row["provenance_json"], row["content_hash"],
                row["status"], row["created_at"],
            )
        else:
            sql = (
                "INSERT INTO experience_cards "
                "(id,stable_key,revision,title,category,payload_json,"
                "provenance_json,content_hash,status,created_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            )
            args = (
                row["id"], row["stable_key"], row["revision"], row["label"],
                row["category"], row["payload_json"], row["provenance_json"],
                row["content_hash"], row["status"], row["created_at"],
            )
        await session.execute(sql, args)

    async def archive_revision(
        self,
        session,
        asset_type: AssetType,
        revision_id: str,
    ) -> int:
        table = _tables(asset_type)["revision"]
        return await session.execute(
            f"UPDATE {table} SET status='archived' "
            "WHERE id=%s AND status='active'",
            (revision_id,),
        )

    async def insert_head(
        self,
        session,
        asset_type: AssetType,
        row: dict,
    ) -> None:
        tables = _tables(asset_type)
        await session.execute(
            f"INSERT INTO {tables['head']} "
            f"(stable_key,{tables['id_column']},revision,content_hash,updated_at) "
            "VALUES (%s,%s,%s,%s,%s)",
            (
                row["stable_key"], row["id"], row["revision"],
                row["content_hash"], row["updated_at"],
            ),
        )

    async def move_head(
        self,
        session,
        asset_type: AssetType,
        row: dict,
        *,
        expected: dict,
    ) -> int:
        tables = _tables(asset_type)
        return await session.execute(
            f"UPDATE {tables['head']} SET {tables['id_column']}=%s,"
            "revision=%s,content_hash=%s,updated_at=%s "
            f"WHERE stable_key=%s AND {tables['id_column']}=%s "
            "AND revision=%s AND content_hash=%s",
            (
                row["id"], row["revision"], row["content_hash"],
                row["updated_at"], row["stable_key"], expected["id"],
                expected["revision"], expected["content_hash"],
            ),
        )

    async def lock_recommendation_project(self, session, project_id: str):
        return await lock_active_project(session, project_id, nowait=True)

    async def lock_recommendation_request(
        self,
        session,
        project_id: str,
        idempotency_key: str,
    ):
        return await session.fetchone(
            """SELECT * FROM asset_recommendation_requests
                WHERE project_id=%s AND idempotency_key=%s FOR UPDATE""",
            (project_id, idempotency_key),
        )

    async def lock_recommendation_inputs(
        self,
        session,
        project_id: str,
        engine_option_id: str,
    ) -> dict:
        binding = await session.fetchone(
            """SELECT head.binding_revision_id,
                      head.content_hash AS binding_hash,
                      item.resolution_status,item.provider_id,
                      item.model_name_snapshot,
                      provider.id AS current_provider_id,
                      provider.provider_type,provider.model_name,
                      provider.revision AS provider_profile_revision,
                      provider.base_url,provider.api_key,provider.enabled,
                      provider.lifecycle_status,provider.temperature,
                      provider.max_output_tokens
                 FROM project_model_binding_heads head
                 JOIN project_model_binding_items item
                   ON item.binding_revision_id=head.binding_revision_id
                  AND item.task_key='seed'
                 LEFT JOIN provider_profiles provider
                   ON provider.id=item.provider_id
                WHERE head.project_id=%s FOR UPDATE""",
            (project_id,),
        )
        selected = await session.fetchone(
            """SELECT selected.seed_id,selected.selection_revision,
                      selected.seed_revision_id,
                      revision.revision AS seed_revision,
                      selected.seed_hash,
                      revision.content_hash AS revision_hash,
                      revision.payload_json
                 FROM project_selected_seeds selected
                 JOIN creative_seed_revisions revision
                   ON revision.project_id=selected.project_id
                  AND revision.seed_id=selected.seed_id
                  AND revision.id=selected.seed_revision_id
                WHERE selected.project_id=%s FOR UPDATE""",
            (project_id,),
        )
        engine = await session.fetchone(
            """SELECT engine_option.id,engine_option.project_id,
                      engine_option.payload_json,engine_option.content_hash,
                      batch.status AS batch_status,
                      batch.selection_revision,batch.seed_id,
                      batch.seed_revision_id,batch.seed_hash
                 FROM story_engine_options engine_option
                 JOIN story_engine_batches batch
                   ON batch.project_id=engine_option.project_id
                  AND batch.id=engine_option.batch_id
                WHERE engine_option.project_id=%s
                  AND engine_option.id=%s FOR UPDATE""",
            (project_id, engine_option_id),
        )
        draft = await session.fetchone(
            """SELECT engine_option_id,selection_revision,seed_hash,
                      draft_json,content_hash
                 FROM project_contract_drafts
                WHERE project_id=%s AND engine_option_id=%s FOR UPDATE""",
            (project_id, engine_option_id),
        )
        styles = await self.list_active_revisions(session, "style")
        cards = await self.list_active_revisions(session, "card")
        provider = None
        if binding is not None:
            provider = {
                "id": binding.get("current_provider_id"),
                "provider_type": binding.get("provider_type"),
                "model_name": binding.get("model_name"),
                "revision": binding.get("provider_profile_revision"),
                "base_url": binding.get("base_url"),
                "api_key": binding.get("api_key"),
                "enabled": binding.get("enabled"),
                "lifecycle_status": binding.get("lifecycle_status"),
                "temperature": binding.get("temperature"),
                "max_output_tokens": binding.get("max_output_tokens"),
            }
        return {
            "selected": selected,
            "engine": engine,
            "draft": draft,
            "binding_revision_id": (
                binding.get("binding_revision_id") if binding else None
            ),
            "binding_hash": binding.get("binding_hash") if binding else None,
            "resolution_status": (
                binding.get("resolution_status") if binding else None
            ),
            "provider_id": binding.get("provider_id") if binding else None,
            "model_name_snapshot": (
                binding.get("model_name_snapshot") if binding else None
            ),
            "provider": provider,
            "styles": styles,
            "cards": cards,
        }

    async def insert_recommendation_request(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO asset_recommendation_requests
               (id,project_id,idempotency_key,request_hash,status,attempt_id,
                result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,'running',%s,NULL,NULL,%s,NULL)""",
            (
                row["id"], row["project_id"], row["idempotency_key"],
                row["request_hash"], row["attempt_id"], row["created_at"],
            ),
        )

    async def insert_failed_recommendation_request(
        self,
        session,
        row: dict,
    ) -> None:
        await session.execute(
            """INSERT INTO asset_recommendation_requests
               (id,project_id,idempotency_key,request_hash,status,attempt_id,
                result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,'failed',NULL,NULL,%s,%s,%s)""",
            (
                row["id"], row["project_id"], row["idempotency_key"],
                row["request_hash"], row["public_error_code"],
                row["created_at"], row["completed_at"],
            ),
        )

    async def insert_recommendation_attempt(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO asset_recommendation_attempts
               (id,project_id,selection_revision,binding_revision_id,
                binding_hash,input_manifest_json,input_manifest_hash,status,
                result_json,result_hash,public_error_code,created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'running',
                       NULL,NULL,NULL,%s,NULL)""",
            (
                row["id"], row["project_id"], row["selection_revision"],
                row["binding_revision_id"], row["binding_hash"],
                row["input_manifest_json"], row["input_manifest_hash"],
                row["created_at"],
            ),
        )

    async def read_recommendation_attempt(
        self,
        session,
        project_id: str,
        attempt_id: str,
    ):
        return await session.fetchone(
            """SELECT * FROM asset_recommendation_attempts
                WHERE project_id=%s AND id=%s FOR UPDATE""",
            (project_id, attempt_id),
        )

    async def fail_recommendation(self, session, **values) -> None:
        attempt_changed = await session.execute(
            """UPDATE asset_recommendation_attempts
                  SET status='failed',result_json=NULL,result_hash=NULL,
                      public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND id=%s AND status='running'""",
            (
                values["public_error_code"], values["completed_at"],
                values["project_id"], values["attempt_id"],
            ),
        )
        request_changed = await session.execute(
            """UPDATE asset_recommendation_requests
                  SET status='failed',attempt_id=%s,result_hash=NULL,
                      public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND idempotency_key=%s
                  AND status='running' AND attempt_id=%s""",
            (
                values["attempt_id"], values["public_error_code"],
                values["completed_at"],
                values["project_id"], values["idempotency_key"],
                values["attempt_id"],
            ),
        )
        if attempt_changed != 1 or request_changed != 1:
            raise RuntimeError(
                "asset recommendation terminal write must remain atomic"
            )

    async def mark_recommendation_outcome_unknown(self, session, **values) -> None:
        attempt_changed = await session.execute(
            """UPDATE asset_recommendation_attempts
                  SET status='outcome_unknown',result_json=NULL,result_hash=NULL,
                      public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND id=%s AND status='running'""",
            (
                values["public_error_code"], values["completed_at"],
                values["project_id"], values["attempt_id"],
            ),
        )
        request_changed = await session.execute(
            """UPDATE asset_recommendation_requests
                  SET status='outcome_unknown',result_hash=NULL,
                      public_error_code=%s,completed_at=%s
                WHERE project_id=%s AND idempotency_key=%s
                  AND status='running' AND attempt_id=%s""",
            (
                values["public_error_code"], values["completed_at"],
                values["project_id"], values["idempotency_key"],
                values["attempt_id"],
            ),
        )
        if attempt_changed != 1 or request_changed != 1:
            raise RuntimeError(
                "asset recommendation unknown outcome write must remain atomic"
            )

    async def cleanup_cancelled_recommendation(self, session, **values) -> bool:
        request = await session.fetchone(
            """SELECT status,attempt_id FROM asset_recommendation_requests
                WHERE project_id=%s AND idempotency_key=%s
                  AND request_hash=%s FOR UPDATE""",
            (
                values["project_id"], values["idempotency_key"],
                values["request_hash"],
            ),
        )
        if request is None or not request.get("attempt_id"):
            raise RuntimeError(
                "asset recommendation cancellation request is missing"
            )
        attempt = await session.fetchone(
            """SELECT status FROM asset_recommendation_attempts
                WHERE project_id=%s AND id=%s FOR UPDATE""",
            (values["project_id"], request["attempt_id"]),
        )
        if attempt is None:
            raise RuntimeError(
                "asset recommendation cancellation attempt is missing"
            )
        request_status = request["status"]
        attempt_status = attempt["status"]
        if request_status == "running" and attempt_status == "running":
            await self.mark_recommendation_outcome_unknown(
                session,
                project_id=values["project_id"],
                idempotency_key=values["idempotency_key"],
                attempt_id=request["attempt_id"],
                public_error_code=values["public_error_code"],
                completed_at=values["completed_at"],
            )
            return True
        if (
            request_status in {"succeeded", "failed", "outcome_unknown"}
            and attempt_status == request_status
        ):
            return False
        raise RuntimeError("asset recommendation cancellation state diverged")

    @staticmethod
    def _json_document(value: object) -> dict:
        if isinstance(value, (bytes, bytearray)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            value = json.loads(value)
        if not isinstance(value, dict):
            raise ValueError("recommendation manifest is invalid")
        return value

    @staticmethod
    def _strict_style_ref(value: object, *, hash_key: str):
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {
            "id", "revision", hash_key
        }:
            raise ValueError("selected style reference is invalid")
        revision_id = value["id"]
        revision = value["revision"]
        content_hash = value[hash_key]
        if (
            not isinstance(revision_id, str)
            or not 1 <= len(revision_id) <= 36
            or type(revision) is not int
            or revision <= 0
            or not isinstance(content_hash, str)
            or _HASH_PATTERN.fullmatch(content_hash) is None
        ):
            raise ValueError("selected style reference is invalid")
        return revision_id, revision, content_hash

    @classmethod
    def _manifest_style_facts(cls, manifest: dict) -> dict:
        values = manifest.get("selectedStyles")
        if not isinstance(values, list) or len(values) > 2:
            raise ValueError("selected style manifest is invalid")
        facts = {"primary": None, "secondary": None}
        for value in values:
            if not isinstance(value, dict) or set(value) != {
                "role", "id", "revision", "hash"
            }:
                raise ValueError("selected style manifest is invalid")
            role = value["role"]
            if role not in facts or facts[role] is not None:
                raise ValueError("selected style manifest is invalid")
            facts[role] = cls._strict_style_ref(
                {
                    "id": value["id"],
                    "revision": value["revision"],
                    "hash": value["hash"],
                },
                hash_key="hash",
            )
        return facts

    @classmethod
    def _draft_style_facts(cls, draft: object) -> dict:
        if draft is None:
            return {"primary": None, "secondary": None}
        document = cls._json_document(draft["draft_json"])
        fields = {
            "primary": "primaryStyleRef",
            "secondary": "secondaryStyleRef",
        }
        if not set(fields.values()).issubset(document):
            raise ValueError("selected style draft is invalid")
        return {
            role: cls._strict_style_ref(
                document[field],
                hash_key="contentHash",
            )
            for role, field in fields.items()
        }

    async def _asset_candidate_facts(self, session, manifest: dict) -> dict:
        candidates = manifest.get("assetCandidates")
        if not isinstance(candidates, list) or len(candidates) > 100:
            return {}
        facts = {}
        for asset_type, tables in (
            ("style", _TABLES["style"]),
            ("experience_card", _TABLES["card"]),
        ):
            expected = [
                item for item in candidates
                if isinstance(item, dict) and item.get("type") == asset_type
            ]
            if not expected:
                continue
            placeholders = ",".join("%s" for _ in expected)
            rows = await session.fetchall(
                f"""SELECT revision.id,revision.revision,
                           revision.content_hash
                      FROM {tables['head']} head
                      JOIN {tables['revision']} revision
                        ON revision.stable_key=head.stable_key
                       AND revision.id=head.{tables['id_column']}
                       AND revision.revision=head.revision
                       AND revision.content_hash=head.content_hash
                     WHERE revision.status='active'
                       AND revision.id IN ({placeholders}) FOR UPDATE""",
                tuple(item["id"] for item in expected),
            )
            facts.update({
                (asset_type, row["id"]): (
                    int(row["revision"]), row["content_hash"]
                )
                for row in rows
            })
        return facts

    async def _corpus_candidate_facts(self, session, manifest: dict) -> dict:
        candidates = manifest.get("corpusCandidates")
        if not isinstance(candidates, list) or len(candidates) > 20:
            return {}
        if not candidates:
            return {}
        placeholders = ",".join("%s" for _ in candidates)
        rows = await session.fetchall(
            f"""SELECT source.id AS source_id,
                       revision.id AS source_revision_id,
                       revision.revision AS source_revision,
                       revision.content_hash AS source_hash,
                       chapter.id AS chapter_id,fragment.id AS fragment_id,
                       fragment.content_hash AS fragment_hash,
                       fragment.chapter_char_start,fragment.chapter_char_end
                  FROM corpus_sources source
                  JOIN corpus_source_heads head ON head.source_id=source.id
                  JOIN corpus_source_revisions revision
                    ON revision.source_id=source.id
                   AND revision.id=head.revision_id
                   AND revision.revision=head.revision
                   AND revision.content_hash=head.content_hash
                  JOIN corpus_chapters chapter
                    ON chapter.corpus_source_id=source.id
                   AND chapter.source_revision_id=revision.id
                   AND chapter.source_revision=revision.revision
                   AND chapter.source_hash=revision.content_hash
                  JOIN corpus_fragments fragment
                    ON fragment.corpus_source_id=source.id
                   AND fragment.corpus_chapter_id=chapter.id
                 WHERE source.archived_at IS NULL
                   AND revision.status='analyzed'
                   AND fragment.id IN ({placeholders}) FOR UPDATE""",
            tuple(item["fragmentId"] for item in candidates),
        )
        return {
            row["fragment_id"]: (
                row["source_id"], row["source_revision_id"],
                int(row["source_revision"]), row["source_hash"],
                row["chapter_id"], row["fragment_hash"],
                int(row["chapter_char_start"]),
                int(row["chapter_char_end"]),
            )
            for row in rows
        }

    async def _publication_inputs_match(self, session, values) -> bool:
        manifest = self._json_document(values["input_manifest"])
        selection = await session.fetchone(
            """SELECT selection_revision,seed_revision_id,seed_hash
                 FROM project_selected_seeds
                WHERE project_id=%s FOR UPDATE""",
            (values["project_id"],),
        )
        binding = await session.fetchone(
            """SELECT binding_revision_id,content_hash
                 FROM project_model_binding_heads
                WHERE project_id=%s FOR UPDATE""",
            (values["project_id"],),
        )
        engine_manifest = manifest["engine"]
        engine = await session.fetchone(
            """SELECT engine_option.id,engine_option.content_hash,
                      batch.selection_revision,batch.seed_revision_id,
                      batch.seed_hash,batch.status
                 FROM story_engine_options engine_option
                 JOIN story_engine_batches batch
                   ON batch.project_id=engine_option.project_id
                  AND batch.id=engine_option.batch_id
                WHERE engine_option.project_id=%s
                  AND engine_option.id=%s FOR UPDATE""",
            (values["project_id"], engine_manifest["id"]),
        )
        draft = await session.fetchone(
            """SELECT draft_json FROM project_contract_drafts
                WHERE project_id=%s AND engine_option_id=%s FOR UPDATE""",
            (values["project_id"], engine_manifest["id"]),
        )
        asset_candidates = manifest.get("assetCandidates")
        corpus_candidates = manifest.get("corpusCandidates")
        asset_facts = await self._asset_candidate_facts(session, manifest)
        corpus_facts = await self._corpus_candidate_facts(session, manifest)
        try:
            selected_styles_match = (
                self._manifest_style_facts(manifest)
                == self._draft_style_facts(draft)
            )
        except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
            selected_styles_match = False
        asset_candidates_match = bool(
            isinstance(asset_candidates, list)
            and len(asset_facts) == len(asset_candidates)
            and all(
                asset_facts.get((item["type"], item["id"]))
                == (int(item["revision"]), item["hash"])
                for item in asset_candidates
            )
        )
        corpus_candidates_match = bool(
            isinstance(corpus_candidates, list)
            and len(corpus_facts) == len(corpus_candidates)
            and all(
                (
                    facts := corpus_facts.get(item["fragmentId"])
                ) is not None
                and facts[:6] == (
                    item["sourceId"], item["sourceRevisionId"],
                    int(item["sourceRevision"]), item["sourceHash"],
                    item["chapterId"], item["fragmentHash"],
                )
                and facts[6] <= int(item["windowStart"])
                and int(item["windowStart"]) < int(item["windowEnd"])
                and int(item["windowEnd"]) <= facts[7]
                for item in corpus_candidates
            )
        )
        return bool(
            selection is not None
            and int(selection["selection_revision"])
            == int(manifest["selection"]["revision"])
            and selection["seed_revision_id"]
            == manifest["selection"]["seedRevisionId"]
            and selection["seed_hash"] == manifest["selection"]["hash"]
            and binding is not None
            and binding["binding_revision_id"]
            == manifest["binding"]["revisionId"]
            and binding["content_hash"] == manifest["binding"]["hash"]
            and engine is not None
            and engine["id"] == engine_manifest["id"]
            and engine["content_hash"] == engine_manifest["hash"]
            and engine["status"] == "succeeded"
            and int(engine["selection_revision"])
            == int(manifest["selection"]["revision"])
            and engine["seed_revision_id"]
            == manifest["selection"]["seedRevisionId"]
            and engine["seed_hash"] == manifest["selection"]["hash"]
            and selected_styles_match
            and asset_candidates_match
            and corpus_candidates_match
        )

    async def publish_recommendation(self, session, **values) -> bool:
        attempt = await session.fetchone(
            """SELECT status FROM asset_recommendation_attempts
                WHERE project_id=%s AND id=%s FOR UPDATE""",
            (values["project_id"], values["attempt_id"]),
        )
        matches = False
        if attempt is not None and attempt["status"] == "running":
            try:
                matches = await self._publication_inputs_match(session, values)
            except (KeyError, TypeError, ValueError, UnicodeError):
                matches = False
        if not matches:
            await self.fail_recommendation(
                session,
                project_id=values["project_id"],
                idempotency_key=values["idempotency_key"],
                attempt_id=values["attempt_id"],
                public_error_code="ASSET_RECOMMENDATION_UNAVAILABLE",
                completed_at=values["completed_at"],
            )
            return False
        attempt_changed = await session.execute(
            """UPDATE asset_recommendation_attempts
                  SET status='succeeded',result_json=%s,result_hash=%s,
                      public_error_code=NULL,completed_at=%s
                WHERE project_id=%s AND id=%s AND status='running'""",
            (
                values["result_json"], values["result_hash"],
                values["completed_at"], values["project_id"],
                values["attempt_id"],
            ),
        )
        request_changed = await session.execute(
            """UPDATE asset_recommendation_requests
                  SET status='succeeded',attempt_id=%s,result_hash=%s,
                      public_error_code=NULL,completed_at=%s
                WHERE project_id=%s AND idempotency_key=%s
                  AND status='running' AND attempt_id=%s AND request_hash=%s""",
            (
                values["attempt_id"], values["result_hash"],
                values["completed_at"], values["project_id"],
                values["idempotency_key"], values["attempt_id"],
                values["request_hash"],
            ),
        )
        if attempt_changed != 1 or request_changed != 1:
            raise RuntimeError(
                "asset recommendation publication must remain atomic"
            )
        return True
