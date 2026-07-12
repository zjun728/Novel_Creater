"""Session-bound persistence for recoverable contract drafts and previews."""

from __future__ import annotations

from backend.repositories.project_lifecycle import lock_active_project, read_active_project


_PROVIDER_READY = """provider.lifecycle_status='active' AND provider.enabled=1
  AND provider.provider_type IS NOT NULL AND TRIM(provider.provider_type)<>''
  AND provider.model_name IS NOT NULL AND TRIM(provider.model_name)<>''
  AND provider.base_url IS NOT NULL AND TRIM(provider.base_url)<>''
  AND provider.api_key IS NOT NULL AND TRIM(provider.api_key)<>''"""


class ContractRepository:
    async def read_project(self, session, project_id: str):
        return await read_active_project(session, project_id)

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

    async def insert_draft(self, session, row: dict) -> None:
        await session.execute(
            """INSERT INTO project_contract_drafts
               (project_id,id,base_head_revision,seed_revision_id,seed_hash,
                engine_option_id,draft_json,content_hash,draft_version,
                created_at,updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["project_id"], row["id"], row["base_head_revision"],
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
               SET seed_revision_id=%s,seed_hash=%s,engine_option_id=%s,
                   draft_json=%s,content_hash=%s,draft_version=%s,updated_at=%s
               WHERE project_id=%s AND draft_version=%s""",
            (
                row["seed_revision_id"], row["seed_hash"],
                row["engine_option_id"], row["draft_json"],
                row["content_hash"], row["draft_version"], row["updated_at"],
                row["project_id"], expected_version,
            ),
        )
        return changed == 1

    async def read_selected_seed(self, session, project_id: str):
        return await session.fetchone(
            """SELECT selected.seed_id,selected.seed_revision_id,
                      selected.seed_hash,revision.payload_json
               FROM project_selected_seeds selected
               JOIN creative_seed_revisions revision
                 ON revision.project_id=selected.project_id
                AND revision.id=selected.seed_revision_id
               WHERE selected.project_id=%s""",
            (project_id,),
        )

    async def read_seed_revision(
        self, session, project_id: str, revision_id: str
    ):
        return await session.fetchone(
            """SELECT seed_id,id AS seed_revision_id,content_hash AS seed_hash,
                      payload_json
               FROM creative_seed_revisions
               WHERE project_id=%s AND id=%s""",
            (project_id, revision_id),
        )

    async def read_engine_option(self, session, project_id: str, option_id: str):
        return await session.fetchone(
            """SELECT option.id,option.project_id,option.batch_id,
                      option.payload_json,option.content_hash,batch.status,
                      batch.seed_revision_id,batch.seed_hash
               FROM story_engine_options option
               JOIN story_engine_batches batch
                 ON batch.project_id=option.project_id
                AND batch.id=option.batch_id
               WHERE option.project_id=%s AND option.id=%s""",
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
        lock_clause = " FOR UPDATE" if lock else ""
        rows = await session.fetchall(
            f"""SELECT revision.revision,revision.id AS binding_revision_id,
                       revision.content_hash,
                       head.revision AS head_revision,
                       head.binding_revision_id AS head_binding_revision_id,
                       head.content_hash AS head_hash,
                       item.task_key,item.resolution_status,item.provider_id,
                       item.provider_name_snapshot,item.model_name_snapshot,
                       CASE WHEN {_PROVIDER_READY} THEN 1 ELSE 0 END
                         AS provider_ready
                FROM project_model_binding_revisions revision
                JOIN project_model_binding_heads head
                  ON head.project_id=revision.project_id
                JOIN project_model_binding_items item
                  ON item.binding_revision_id=revision.id
                LEFT JOIN provider_profiles provider ON provider.id=item.provider_id
                WHERE revision.project_id=%s AND {revision_predicate}
                ORDER BY FIELD(item.task_key,'seed','planning','writing','audit',
                  'summary','extraction','polish','market'){lock_clause}""",
            args,
        )
        if not rows:
            return None
        first = rows[0]
        return {
            key: first[key] for key in (
                "revision", "binding_revision_id", "content_hash",
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

    async def read_style_revision(self, session, asset_id: str):
        return await session.fetchone(
            """SELECT asset.id,asset.stable_key,asset.revision,asset.name,
                      asset.payload_json,asset.content_hash,asset.status,
                      head.style_template_id AS head_id,
                      head.revision AS head_revision,head.content_hash AS head_hash
               FROM style_templates asset
               LEFT JOIN style_template_heads head
                 ON head.stable_key=asset.stable_key
               WHERE asset.id=%s""",
            (asset_id,),
        )

    async def read_experience_revision(self, session, asset_id: str):
        return await session.fetchone(
            """SELECT asset.id,asset.stable_key,asset.revision,asset.title,
                      asset.payload_json,asset.content_hash,asset.status,
                      head.experience_card_id AS head_id,
                      head.revision AS head_revision,head.content_hash AS head_hash
               FROM experience_cards asset
               LEFT JOIN experience_card_heads head
                 ON head.stable_key=asset.stable_key
               WHERE asset.id=%s""",
            (asset_id,),
        )

    async def read_corpus_revision(self, session, asset_id: str):
        return await session.fetchone(
            """SELECT source.id,source.source_key,source.revision,
                      source.source_hash,source.status,source.title,source.author,
                      latest.id AS head_id,latest.revision AS head_revision,
                      latest.source_hash AS head_hash
               FROM corpus_sources source
               LEFT JOIN corpus_sources latest
                 ON latest.source_key=source.source_key
                AND latest.revision=(
                  SELECT MAX(candidate.revision) FROM corpus_sources candidate
                  WHERE candidate.source_key=source.source_key)
               WHERE source.id=%s""",
            (asset_id,),
        )

    async def read_confirmed_snapshot(self, session, project_id: str):
        current = await session.fetchone(
            """SELECT head.revision,creation.seed_revision_id,creation.seed_hash,
                      creation.content_json AS creation_json,
                      creation.content_hash AS creation_hash,
                      style.merged_style_json AS style_json,
                      style.likes_json,style.dislikes_json,
                      style.content_hash AS style_hash,
                      engine.engine_option_id,engine.engine_hash,
                      creation.binding_revision_id,
                      binding.revision AS binding_revision,
                      creation.binding_hash,
                      style.id AS style_contract_id,
                      creation.id AS creation_contract_id
               FROM project_contract_heads head
               JOIN creation_contracts creation
                 ON creation.project_id=head.project_id
                AND creation.id=head.creation_contract_id
               JOIN style_contracts style
                 ON style.project_id=head.project_id
                AND style.id=head.style_contract_id
               JOIN creation_contract_engine_refs engine
                 ON engine.project_id=creation.project_id
                AND engine.creation_contract_id=creation.id
               JOIN project_model_binding_revisions binding
                 ON binding.project_id=creation.project_id
                AND binding.id=creation.binding_revision_id
               WHERE head.project_id=%s AND head.revision>0""",
            (project_id,),
        )
        if current is None:
            return None
        style_refs = await session.fetchall(
            """SELECT role,style_template_id AS id,asset_revision AS revision,
                      asset_hash AS contentHash
               FROM style_contract_template_refs WHERE style_contract_id=%s
               ORDER BY sort_order""",
            (current["style_contract_id"],),
        )
        cards = await session.fetchall(
            """SELECT experience_card_id AS id,asset_revision AS revision,
                      asset_hash AS contentHash
               FROM creation_contract_experience_refs
               WHERE creation_contract_id=%s ORDER BY sort_order""",
            (current["creation_contract_id"],),
        )
        sources = await session.fetchall(
            """SELECT corpus_source_id AS id,source_revision AS revision,
                      source_hash AS contentHash,selection_mode AS selectionMode
               FROM creation_contract_corpus_refs
               WHERE creation_contract_id=%s ORDER BY sort_order""",
            (current["creation_contract_id"],),
        )
        return dict(current) | {
            "style_refs": tuple(style_refs),
            "experience_card_refs": tuple(cards),
            "corpus_source_refs": tuple(sources),
        }
