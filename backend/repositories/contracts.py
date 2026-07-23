"""Session-bound persistence for recoverable contract drafts and previews."""

from __future__ import annotations

from backend.domain.provider_policy import GENERATION_PROVIDER_TYPE
from backend.repositories.project_lifecycle import (
    lock_active_project,
    read_active_project as _read_active_project,
    read_project as read_any_project,
)


_PROVIDER_READY = f"""provider.lifecycle_status='active' AND provider.enabled=1
  AND LOWER(TRIM(provider.provider_type))='{GENERATION_PROVIDER_TYPE}'
  AND provider.model_name IS NOT NULL AND TRIM(provider.model_name)<>''
  AND provider.base_url IS NOT NULL AND TRIM(provider.base_url)<>''
  AND provider.api_key IS NOT NULL AND TRIM(provider.api_key)<>''"""
_FOR_UPDATE = " FOR UPDATE"


class ContractRepository:
    async def read_project(self, session, project_id: str):
        return await read_any_project(session, project_id)

    async def read_active_project(self, session, project_id: str):
        return await _read_active_project(session, project_id)

    async def lock_project(self, session, project_id: str):
        return await lock_active_project(session, project_id)

    async def read_draft(self, session, project_id: str):
        return await session.fetchone(
            "SELECT * FROM project_contract_drafts WHERE project_id=%s",
            (project_id,),
        )

    async def lock_draft(self, session, project_id: str):
        return await session.fetchone(
            "SELECT * FROM project_contract_drafts WHERE project_id=%s FOR UPDATE",
            (project_id,),
        )

    async def read_contract_head(self, session, project_id: str):
        return await session.fetchone(
            "SELECT * FROM project_contract_heads WHERE project_id=%s",
            (project_id,),
        )

    async def lock_contract_head(self, session, project_id: str):
        return await session.fetchone(
            "SELECT * FROM project_contract_heads WHERE project_id=%s FOR UPDATE",
            (project_id,),
        )

    async def read_confirmation_request(
        self, session, project_id: str, idempotency_key: str
    ):
        return await session.fetchone(
            """SELECT * FROM contract_confirmation_requests
               WHERE project_id=%s AND idempotency_key=%s FOR UPDATE""",
            (project_id, idempotency_key),
        )

    async def insert_confirmation_request(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO contract_confirmation_requests
               (id,project_id,selection_revision,idempotency_key,request_hash,status,created_at)
               VALUES (%s,%s,%s,%s,%s,'reserved',%s)""",
            (row["id"], row["project_id"], row["selection_revision"],
             row["idempotency_key"],
             row["request_hash"], row["created_at"]),
        )
        return changed == 1

    async def insert_creation_contract(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO creation_contracts
               (id,project_id,revision,selection_revision,seed_id,seed_revision_id,seed_hash,
                binding_revision_id,binding_hash,channel_profile_key,
                genre_profile_key,quality_charter_version,total_word_min,
                total_word_max,chapter_capacity_policy,reference_manifest_json,
                reference_manifest_hash,content_json,content_hash,confirmed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       %s,%s,%s,%s)""",
            tuple(row[key] for key in (
                "id", "project_id", "revision", "selection_revision",
                "seed_id", "seed_revision_id",
                "seed_hash", "binding_revision_id", "binding_hash",
                "channel_profile_key", "genre_profile_key",
                "quality_charter_version", "total_word_min", "total_word_max",
                "chapter_capacity_policy", "reference_manifest_json",
                "reference_manifest_hash",
                "content_json", "content_hash", "confirmed_at",
            )),
        )
        return changed == 1

    async def insert_style_contract(self, session, row: dict) -> bool:
        changed = await session.execute(
            """INSERT INTO style_contracts
               (id,project_id,creation_contract_id,revision,merged_style_json,
                likes_json,dislikes_json,content_hash,confirmed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            tuple(row[key] for key in (
                "id", "project_id", "creation_contract_id", "revision",
                "merged_style_json", "likes_json", "dislikes_json",
                "content_hash", "confirmed_at",
            )),
        )
        return changed == 1

    async def insert_engine_ref(self, session, row: dict) -> bool:
        return await session.execute(
            """INSERT INTO creation_contract_engine_refs
               (creation_contract_id,project_id,engine_option_id,engine_hash)
               VALUES (%s,%s,%s,%s)""",
            tuple(row[key] for key in (
                "creation_contract_id", "project_id", "engine_option_id",
                "engine_hash",
            )),
        ) == 1

    async def insert_style_refs(self, session, rows: tuple[dict, ...]) -> bool:
        for row in rows:
            if await session.execute(
                """INSERT INTO style_contract_template_refs
                   (style_contract_id,role,style_template_id,asset_revision,
                    asset_hash,sort_order) VALUES (%s,%s,%s,%s,%s,%s)""",
                tuple(row[key] for key in (
                    "style_contract_id", "role", "style_template_id",
                    "asset_revision", "asset_hash", "sort_order",
                )),
            ) != 1:
                return False
        return True

    async def insert_experience_refs(self, session, rows: tuple[dict, ...]) -> bool:
        for row in rows:
            if await session.execute(
                """INSERT INTO creation_contract_experience_refs
                   (creation_contract_id,experience_card_id,asset_revision,
                    asset_hash,sort_order) VALUES (%s,%s,%s,%s,%s)""",
                tuple(row[key] for key in (
                    "creation_contract_id", "experience_card_id",
                    "asset_revision", "asset_hash", "sort_order",
                )),
            ) != 1:
                return False
        return True

    async def insert_corpus_refs(self, session, rows: tuple[dict, ...]) -> bool:
        for row in rows:
            if await session.execute(
                """INSERT INTO creation_contract_corpus_refs
                   (creation_contract_id,corpus_source_id,source_revision,
                    source_hash,selection_mode,sort_order)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                tuple(row[key] for key in (
                    "creation_contract_id", "corpus_source_id",
                    "source_revision", "source_hash", "selection_mode",
                    "sort_order",
                )),
            ) != 1:
                return False
        return True

    async def insert_corpus_fragment_refs(
        self, session, rows: tuple[dict, ...]
    ) -> bool:
        for row in rows:
            if await session.execute(
                """INSERT INTO creation_contract_corpus_fragment_refs
                   (creation_contract_id,corpus_source_id,source_revision,
                    source_hash,corpus_chapter_id,corpus_fragment_id,
                    fragment_hash,chapter_char_start,chapter_char_end,
                    reference_use,sort_order)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                tuple(row[key] for key in (
                    "creation_contract_id", "corpus_source_id",
                    "source_revision", "source_hash", "corpus_chapter_id",
                    "corpus_fragment_id", "fragment_hash",
                    "chapter_char_start", "chapter_char_end",
                    "reference_use", "sort_order",
                )),
            ) != 1:
                return False
        return True

    async def cas_contract_head(self, session, row: dict) -> bool:
        return await session.execute(
            """UPDATE project_contract_heads
               SET revision=%s,creation_contract_id=%s,style_contract_id=%s,
                   creation_hash=%s,style_hash=%s,updated_at=%s
               WHERE project_id=%s AND revision=%s""",
            (row["revision"], row["creation_contract_id"],
             row["style_contract_id"], row["creation_hash"], row["style_hash"],
             row["updated_at"], row["project_id"], row["base_revision"]),
        ) == 1

    async def delete_draft_cas(
        self, session, project_id: str, version: int, content_hash: str
    ) -> bool:
        return await session.execute(
            """DELETE FROM project_contract_drafts
               WHERE project_id=%s AND draft_version=%s AND content_hash=%s""",
            (project_id, version, content_hash),
        ) == 1

    async def succeed_confirmation_request(self, session, row: dict) -> bool:
        return await session.execute(
            """UPDATE contract_confirmation_requests
               SET status='succeeded',creation_contract_id=%s,
                   style_contract_id=%s,result_revision=%s,completed_at=%s
               WHERE project_id=%s AND idempotency_key=%s
                 AND request_hash=%s AND status='reserved'""",
            (row["creation_contract_id"], row["style_contract_id"],
             row["result_revision"], row["completed_at"], row["project_id"],
             row["idempotency_key"], row["request_hash"]),
        ) == 1

    async def list_contract_revisions(
        self,
        session,
        project_id: str,
        *,
        before_revision: int | None,
        limit: int,
    ):
        cursor_clause = ""
        args: list[object] = [project_id]
        if before_revision is not None:
            cursor_clause = " AND revision<%s"
            args.append(before_revision)
        args.append(limit + 1)
        return await session.fetchall(
            f"""SELECT revision FROM creation_contracts
                WHERE project_id=%s{cursor_clause}
                ORDER BY revision DESC LIMIT %s""",
            tuple(args),
        )

    async def insert_draft(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO project_contract_drafts
               (project_id,id,base_head_revision,selection_revision,seed_revision_id,seed_hash,
                engine_option_id,draft_json,content_hash,draft_version,
                created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["project_id"], row["id"], row["base_head_revision"],
                row["selection_revision"],
                row["seed_revision_id"], row["seed_hash"],
                row["engine_option_id"], row["draft_json"],
                row["content_hash"], row["draft_version"],
                row["created_at"], row["updated_at"],
            ),
        )

    async def cas_update_draft(
        self, session, row: dict, expected_version: int
    ) -> bool:
        changed = await session.execute(
            """UPDATE project_contract_drafts
               SET selection_revision=%s,seed_revision_id=%s,seed_hash=%s,engine_option_id=%s,
                   draft_json=%s,content_hash=%s,draft_version=%s,updated_at=%s
               WHERE project_id=%s AND draft_version=%s""",
            (
                row["selection_revision"], row["seed_revision_id"], row["seed_hash"],
                row["engine_option_id"], row["draft_json"],
                row["content_hash"], row["draft_version"], row["updated_at"],
                row["project_id"], expected_version,
            ),
        )
        return changed == 1

    async def read_selected_seed(self, session, project_id: str):
        return await session.fetchone(
            """SELECT selected.seed_id,selected.selection_revision,selected.seed_revision_id,
                      selected.seed_hash,revision.payload_json
               FROM project_selected_seeds selected
               JOIN creative_seed_revisions revision
                 ON revision.project_id=selected.project_id
                AND revision.id=selected.seed_revision_id
               WHERE selected.project_id=%s""",
            (project_id,),
        )

    async def lock_selected_seed(self, session, project_id: str):
        return await session.fetchone(
            """SELECT selected.seed_id,selected.selection_revision,selected.seed_revision_id,
                      selected.seed_hash,revision.payload_json
               FROM project_selected_seeds selected
               JOIN creative_seed_revisions revision
                 ON revision.project_id=selected.project_id
                AND revision.id=selected.seed_revision_id
               WHERE selected.project_id=%s FOR UPDATE""",
            (project_id,),
        )

    async def read_seed_revision(
        self, session, project_id: str, revision_id: str, *, lock: bool = False
    ):
        return await session.fetchone(
            f"""SELECT seed_id,id AS seed_revision_id,content_hash AS seed_hash,
                      payload_json
               FROM creative_seed_revisions
               WHERE project_id=%s AND id=%s{_FOR_UPDATE if lock else ''}""",
            (project_id, revision_id),
        )

    async def read_engine_option(
        self, session, project_id: str, option_id: str, *, lock: bool = False
    ):
        return await session.fetchone(
            f"""SELECT engine_option.id,engine_option.project_id,
                      engine_option.batch_id,engine_option.payload_json,
                      engine_option.content_hash,batch.status,
                      batch.selection_revision,
                      batch.seed_revision_id,batch.seed_hash
               FROM story_engine_options engine_option
               JOIN story_engine_batches batch
                 ON batch.project_id=engine_option.project_id
                AND batch.id=engine_option.batch_id
               WHERE engine_option.project_id=%s AND engine_option.id=%s
               {_FOR_UPDATE if lock else ''}""",
            (project_id, option_id),
        )

    async def _binding_snapshot(
        self, session, project_id: str, binding_revision_id=None, *, lock=False
    ):
        revision_predicate = (
            "revision.id=%s" if binding_revision_id is not None
            else "revision.id=head.binding_revision_id"
        )
        args = (
            (project_id, binding_revision_id)
            if binding_revision_id is not None else (project_id,)
        )
        base_select = f"""SELECT revision.project_id,revision.revision,
                       revision.id AS binding_revision_id,
                       revision.content_hash,
                       head.revision AS head_revision,
                       head.binding_revision_id AS head_binding_revision_id,
                       head.content_hash AS head_hash,
                       item.task_key,item.resolution_status,item.provider_id,
                       item.provider_name_snapshot,item.model_name_snapshot,
                       item.item_hash
                FROM project_model_binding_revisions revision
                JOIN project_model_binding_heads head
                  ON head.project_id=revision.project_id
                JOIN project_model_binding_items item
                  ON item.binding_revision_id=revision.id
                WHERE revision.project_id=%s AND {revision_predicate}
                ORDER BY FIELD(item.task_key,'seed','planning','writing','audit',
                  'summary','extraction','polish','market')"""
        if lock:
            # Lock project-owned rows first. Shared provider rows are then locked by
            # provider id, so reverse task mappings across projects cannot invert
            # the lock order.
            rows = await session.fetchall(f"{base_select} FOR UPDATE", args)
            provider_ids = tuple(sorted({
                row["provider_id"] for row in rows if row.get("provider_id")
            }))
            readiness = {}
            if provider_ids:
                providers = await session.fetchall(
                    f"""SELECT provider.id,
                               CASE WHEN {_PROVIDER_READY} THEN 1 ELSE 0 END
                                 AS provider_ready
                          FROM provider_profiles provider
                         WHERE provider.id IN ({','.join(['%s'] * len(provider_ids))})
                         ORDER BY provider.id FOR UPDATE""",
                    provider_ids,
                )
                readiness = {
                    row["id"]: int(row["provider_ready"]) for row in providers
                }
            rows = [
                dict(row) | {
                    "provider_ready": readiness.get(row.get("provider_id"), 0)
                }
                for row in rows
            ]
        else:
            rows = await session.fetchall(
                f"""SELECT snapshot.*,
                           CASE WHEN {_PROVIDER_READY} THEN 1 ELSE 0 END
                             AS provider_ready
                      FROM ({base_select}) snapshot
                      LEFT JOIN provider_profiles provider
                        ON provider.id=snapshot.provider_id
                     ORDER BY FIELD(snapshot.task_key,'seed','planning','writing',
                       'audit','summary','extraction','polish','market')""",
                args,
            )
        if not rows:
            return None
        first = rows[0]
        return {
            key: first[key] for key in (
                "project_id", "revision", "binding_revision_id", "content_hash",
                "head_revision", "head_binding_revision_id", "head_hash",
            )
        } | {"items": tuple(rows)}

    async def read_binding_snapshot(
        self, session, project_id: str, binding_revision_id=None
    ):
        return await self._binding_snapshot(
            session, project_id, binding_revision_id
        )

    async def lock_binding_snapshot(self, session, project_id: str):
        return await self._binding_snapshot(session, project_id, lock=True)

    async def read_style_revision(self, session, asset_id: str, *, lock=False):
        return await session.fetchone(
            f"""SELECT asset.id,asset.stable_key,asset.revision,asset.name,
                      asset.payload_json,asset.content_hash,asset.status,
                      head.style_template_id AS head_id,
                      head.revision AS head_revision,head.content_hash AS head_hash
               FROM style_templates asset
               LEFT JOIN style_template_heads head
                 ON head.stable_key=asset.stable_key
               WHERE asset.id=%s{_FOR_UPDATE if lock else ''}""",
            (asset_id,),
        )

    async def read_experience_revision(self, session, asset_id: str, *, lock=False):
        return await session.fetchone(
            f"""SELECT asset.id,asset.stable_key,asset.revision,asset.title,
                      asset.payload_json,asset.content_hash,asset.status,
                      head.experience_card_id AS head_id,
                      head.revision AS head_revision,head.content_hash AS head_hash
               FROM experience_cards asset
               LEFT JOIN experience_card_heads head
                 ON head.stable_key=asset.stable_key
               WHERE asset.id=%s{_FOR_UPDATE if lock else ''}""",
            (asset_id,),
        )

    async def read_corpus_revision(
        self,
        session,
        asset_id: str,
        revision_id: str | None = None,
        *,
        lock=False,
    ):
        revision_predicate = (
            "revision.id=%s" if revision_id is not None
            else "revision.id=head.revision_id"
        )
        args = (
            (asset_id, revision_id) if revision_id is not None else (asset_id,)
        )
        return await session.fetchone(
            f"""SELECT identity.id,identity.source_key,identity.archived_at,
                      revision.id AS revision_id,revision.revision,
                      revision.content_hash AS source_hash,revision.status,
                      revision.display_name AS title,revision.author,
                      head.revision_id AS head_id,
                      head.revision AS head_revision,
                      head.content_hash AS head_hash
               FROM corpus_sources identity
               LEFT JOIN corpus_source_heads head ON head.source_id=identity.id
               JOIN corpus_source_revisions revision
                 ON revision.source_id=identity.id
               WHERE identity.id=%s AND {revision_predicate}
               {_FOR_UPDATE if lock else ''}""",
            args,
        )

    async def read_corpus_fragments(
        self,
        session,
        source_id: str,
        revision_id: str,
        fragment_ids: tuple[str, ...],
        *,
        lock=False,
    ):
        if not fragment_ids:
            return ()
        return tuple(await session.fetchall(
            f"""SELECT source.id AS source_id,
                       revision.id AS source_revision_id,
                       revision.revision AS source_revision,
                       revision.content_hash AS source_hash,
                       source.archived_at AS source_archived_at,
                       head.revision_id AS source_head_revision_id,
                       head.revision AS source_head_revision,
                       head.content_hash AS source_head_hash,
                       revision.status AS source_status,
                       chapter.id AS chapter_id,
                       fragment.id AS fragment_id,
                       fragment.content_hash AS fragment_hash,
                       fragment.chapter_char_start AS fragment_char_start,
                       fragment.chapter_char_end AS fragment_char_end,
                       fragment.normalized_text
                FROM corpus_sources source
                JOIN corpus_source_revisions revision
                  ON revision.source_id=source.id AND revision.id=%s
                LEFT JOIN corpus_source_heads head ON head.source_id=source.id
                JOIN corpus_chapters chapter
                  ON chapter.corpus_source_id=source.id
                 AND chapter.source_revision_id=revision.id
                JOIN corpus_fragments fragment
                  ON fragment.corpus_source_id=source.id
                 AND fragment.corpus_chapter_id=chapter.id
                WHERE source.id=%s
                  AND fragment.id IN ({','.join(['%s'] * len(fragment_ids))})
                ORDER BY fragment.id{_FOR_UPDATE if lock else ''}""",
            (revision_id, source_id, *fragment_ids),
        ))

    async def read_contract_asset_references(
        self,
        session,
        *,
        style_ids: tuple[str, ...],
        experience_ids: tuple[str, ...],
        corpus_revision_refs: tuple[tuple[str, str], ...],
        fragment_refs: tuple[tuple[str, str, str], ...],
    ):
        """Bulk-read the immutable references used by read-only head readiness."""

        styles = ()
        if style_ids:
            styles = tuple(await session.fetchall(
                f"""SELECT asset.id,asset.stable_key,asset.revision,asset.name,
                           asset.payload_json,asset.content_hash,asset.status,
                           head.style_template_id AS head_id,
                           head.revision AS head_revision,
                           head.content_hash AS head_hash
                    FROM style_templates asset
                    LEFT JOIN style_template_heads head
                      ON head.stable_key=asset.stable_key
                    WHERE asset.id IN ({','.join(['%s'] * len(style_ids))})
                    ORDER BY asset.id""",
                style_ids,
            ))

        experiences = ()
        if experience_ids:
            experiences = tuple(await session.fetchall(
                f"""SELECT asset.id,asset.stable_key,asset.revision,asset.title,
                           asset.payload_json,asset.content_hash,asset.status,
                           head.experience_card_id AS head_id,
                           head.revision AS head_revision,
                           head.content_hash AS head_hash
                    FROM experience_cards asset
                    LEFT JOIN experience_card_heads head
                      ON head.stable_key=asset.stable_key
                    WHERE asset.id IN ({','.join(['%s'] * len(experience_ids))})
                    ORDER BY asset.id""",
                experience_ids,
            ))

        corpora = ()
        if corpus_revision_refs:
            pairs = ",".join(["(%s,%s)"] * len(corpus_revision_refs))
            corpus_args = tuple(
                value
                for identity in corpus_revision_refs
                for value in identity
            )
            corpora = tuple(await session.fetchall(
                f"""SELECT identity.id,identity.source_key,identity.archived_at,
                           revision.id AS revision_id,revision.revision,
                           revision.content_hash AS source_hash,revision.status,
                           revision.display_name AS title,revision.author,
                           head.revision_id AS head_id,
                           head.revision AS head_revision,
                           head.content_hash AS head_hash
                    FROM corpus_sources identity
                    LEFT JOIN corpus_source_heads head
                      ON head.source_id=identity.id
                    JOIN corpus_source_revisions revision
                      ON revision.source_id=identity.id
                    WHERE (identity.id,revision.id) IN ({pairs})
                    ORDER BY identity.id,revision.id""",
                corpus_args,
            ))

        fragments = ()
        if fragment_refs:
            triples = ",".join(["(%s,%s,%s)"] * len(fragment_refs))
            fragment_args = tuple(
                value
                for identity in fragment_refs
                for value in identity
            )
            fragments = tuple(await session.fetchall(
                f"""SELECT source.id AS source_id,
                           revision.id AS source_revision_id,
                           revision.revision AS source_revision,
                           revision.content_hash AS source_hash,
                           source.archived_at AS source_archived_at,
                           head.revision_id AS source_head_revision_id,
                           head.revision AS source_head_revision,
                           head.content_hash AS source_head_hash,
                           revision.status AS source_status,
                           chapter.id AS chapter_id,
                           fragment.id AS fragment_id,
                           fragment.content_hash AS fragment_hash,
                           fragment.chapter_char_start AS fragment_char_start,
                           fragment.chapter_char_end AS fragment_char_end,
                           fragment.normalized_text
                    FROM corpus_sources source
                    JOIN corpus_source_revisions revision
                      ON revision.source_id=source.id
                    LEFT JOIN corpus_source_heads head
                      ON head.source_id=source.id
                    JOIN corpus_chapters chapter
                      ON chapter.corpus_source_id=source.id
                     AND chapter.source_revision_id=revision.id
                    JOIN corpus_fragments fragment
                      ON fragment.corpus_source_id=source.id
                     AND fragment.corpus_chapter_id=chapter.id
                    WHERE (source.id,revision.id,fragment.id) IN ({triples})
                    ORDER BY source.id,revision.id,fragment.id""",
                fragment_args,
            ))

        return {
            "styles": styles,
            "experiences": experiences,
            "corpora": corpora,
            "fragments": fragments,
        }

    async def read_confirmed_snapshot(
        self, session, project_id: str, revision: int | None = None
    ):
        revision_clause = " AND creation.revision=%s" if revision is not None else ""
        args = (project_id, revision) if revision is not None else (project_id,)
        current = await session.fetchone(
            f"""SELECT creation.project_id,creation.revision,
                      creation.selection_revision,creation.seed_id,
                      creation.seed_revision_id,creation.seed_hash,
                      creation.channel_profile_key,
                      creation.genre_profile_key,
                      creation.quality_charter_version,
                      creation.total_word_min,creation.total_word_max,
                      creation.chapter_capacity_policy,
                      creation.content_json AS creation_json,
                      creation.content_hash AS creation_hash,
                      creation.reference_manifest_json,
                      creation.reference_manifest_hash,
                      style.merged_style_json AS style_json,
                      style.likes_json,style.dislikes_json,
                      style.content_hash AS style_hash,
                      engine.engine_option_id,engine.engine_hash,
                      option_actual.batch_id AS engine_batch_id,
                      option_actual.content_hash AS actual_engine_hash,
                      seed_actual.content_hash AS actual_seed_hash,
                      creation.binding_revision_id,
                      binding.revision AS binding_revision,
                      creation.binding_hash,
                      binding.content_hash AS actual_binding_hash,
                      style.id AS style_contract_id,
                      creation.id AS creation_contract_id
               FROM creation_contracts creation
               JOIN style_contracts style
                 ON style.project_id=creation.project_id
                AND style.creation_contract_id=creation.id
               JOIN creation_contract_engine_refs engine
                 ON engine.project_id=creation.project_id
                AND engine.creation_contract_id=creation.id
               LEFT JOIN project_model_binding_revisions binding
                 ON binding.project_id=creation.project_id
                AND binding.id=creation.binding_revision_id
               LEFT JOIN creative_seed_revisions seed_actual
                 ON seed_actual.project_id=creation.project_id
                AND seed_actual.id=creation.seed_revision_id
               LEFT JOIN story_engine_options option_actual
                 ON option_actual.project_id=creation.project_id
                AND option_actual.id=engine.engine_option_id
               WHERE creation.project_id=%s{revision_clause}
               ORDER BY creation.revision DESC LIMIT 1""",
            args,
        )
        if current is None:
            return None
        style_refs = await session.fetchall(
            """SELECT ref.role,ref.style_template_id AS id,
                      ref.asset_revision AS revision,ref.asset_hash AS contentHash,
                      asset.content_hash AS actualContentHash
               FROM style_contract_template_refs ref
               LEFT JOIN style_templates asset
                 ON asset.id=ref.style_template_id
                AND asset.revision=ref.asset_revision
               WHERE ref.style_contract_id=%s
               ORDER BY sort_order""",
            (current["style_contract_id"],),
        )
        cards = await session.fetchall(
            """SELECT ref.experience_card_id AS id,
                      ref.asset_revision AS revision,ref.asset_hash AS contentHash,
                      asset.content_hash AS actualContentHash
               FROM creation_contract_experience_refs ref
               LEFT JOIN experience_cards asset
                 ON asset.id=ref.experience_card_id
                AND asset.revision=ref.asset_revision
               WHERE ref.creation_contract_id=%s ORDER BY sort_order""",
            (current["creation_contract_id"],),
        )
        sources = await session.fetchall(
            """SELECT ref.corpus_source_id AS id,
                      asset.id AS revisionId,
                      ref.source_revision AS revision,ref.source_hash AS contentHash,
                      ref.selection_mode AS selectionMode,
                       asset.content_hash AS actualContentHash
               FROM creation_contract_corpus_refs ref
                LEFT JOIN corpus_source_revisions asset
                  ON asset.source_id=ref.corpus_source_id
                 AND asset.revision=ref.source_revision
               WHERE ref.creation_contract_id=%s ORDER BY sort_order""",
            (current["creation_contract_id"],),
        )
        fragments = await session.fetchall(
            """SELECT ref.corpus_source_id AS sourceId,
                      ref.corpus_chapter_id AS chapterId,
                      ref.corpus_fragment_id AS fragmentId,
                      ref.fragment_hash AS fragmentHash,
                      ref.chapter_char_start AS chapterCharStart,
                      ref.chapter_char_end AS chapterCharEnd,
                      ref.reference_use AS referenceUse,
                      fragment.content_hash AS actualContentHash
               FROM creation_contract_corpus_fragment_refs ref
               LEFT JOIN corpus_fragments fragment
                 ON fragment.corpus_source_id=ref.corpus_source_id
                AND fragment.corpus_chapter_id=ref.corpus_chapter_id
                AND fragment.id=ref.corpus_fragment_id
               WHERE ref.creation_contract_id=%s ORDER BY sort_order""",
            (current["creation_contract_id"],),
        )
        binding = (
            await self.read_binding_snapshot(
                session, project_id, current["binding_revision_id"]
            )
            if current["binding_revision_id"] is not None else None
        )
        return dict(current) | {
            "style_refs": tuple(style_refs),
            "experience_card_refs": tuple(cards),
            "corpus_source_refs": tuple(sources),
            "corpus_fragment_refs": tuple(fragments),
            "binding_items": tuple((binding or {}).get("items") or ()),
        }
