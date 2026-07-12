"""Session-bound persistence for immutable global writing assets."""

from __future__ import annotations

from typing import Literal

from backend.repositories.project_lifecycle import read_active_project


AssetType = Literal["style", "card"]


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
            """SELECT selected.seed_id, selected.seed_revision_id,
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
                      b.status AS batch_status, b.seed_id,
                      b.seed_revision_id, b.seed_hash
               FROM story_engine_options o
               JOIN story_engine_batches b
                 ON b.project_id=o.project_id AND b.id=o.batch_id
               WHERE o.project_id=%s AND o.id=%s""",
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

    async def fetch_revision_by_id(
        self,
        session,
        asset_type: AssetType,
        revision_id: str,
    ):
        tables = _tables(asset_type)
        category = "NULL AS category" if asset_type == "style" else "category"
        return await session.fetchone(
            f"SELECT id,stable_key,revision,"
            f"{tables['label_column']} AS label,{category},payload_json,"
            f"provenance_json,content_hash,status FROM {tables['revision']} "
            "WHERE id=%s AND status IN ('active','archived')",
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
