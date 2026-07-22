"""Session-bound SQL persistence for immutable corpus publications."""

from __future__ import annotations

from collections.abc import Mapping
import json


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


_REVISION_REFERENCE_COUNT_SQL = """
    (
      (SELECT COUNT(*) FROM creation_contract_corpus_refs contract_ref
        WHERE contract_ref.corpus_source_id={revision}.source_id
          AND contract_ref.source_revision={revision}.revision)
      +
      (SELECT COUNT(*) FROM creation_contract_corpus_fragment_refs fragment_ref
        WHERE fragment_ref.corpus_source_id={revision}.source_id
          AND fragment_ref.source_revision={revision}.revision)
      +
      (SELECT COUNT(*) FROM reference_uses reference_use
        JOIN corpus_chapters used_chapter
          ON used_chapter.id=reference_use.corpus_chapter_id
        WHERE used_chapter.corpus_source_id={revision}.source_id
          AND used_chapter.source_revision_id={revision}.id)
    )
"""


def _reference_count_sql(revision: str) -> str:
    return _REVISION_REFERENCE_COUNT_SQL.format(revision=revision)


class CorpusRepository:
    """Issue fixed, parameter-bound corpus SQL on caller-owned sessions."""

    async def lock_schema_guard(self, session) -> None:
        row = await session.fetchone(
            "SELECT singleton_id FROM schema_metadata "
            "WHERE singleton_id=%s FOR UPDATE",
            (1,),
        )
        if row is None:
            raise RuntimeError("corpus schema guard is unavailable")

    async def lock_source_deletion(self, session, source_id: str):
        return await session.fetchone(
            """SELECT source_id,expected_revision,status,tombstones_json,
                      created_at,updated_at
                 FROM corpus_source_deletions
                WHERE source_id=%s FOR UPDATE""",
            (source_id,),
        )

    async def list_pending_source_deletions(
        self, session, *, limit: int
    ):
        return await session.fetchall(
            """SELECT source_id,expected_revision,status,tombstones_json,
                      created_at,updated_at
                 FROM corpus_source_deletions
                WHERE status IN ('restore_pending','cleanup_pending')
                ORDER BY updated_at,source_id
                LIMIT %s""",
            (limit,),
        )

    async def upsert_source_deletion(
        self,
        session,
        *,
        source_id: str,
        expected_revision: int,
        status: str,
        tombstones,
        now: int,
    ) -> None:
        existing = await session.fetchone(
            "SELECT source_id FROM corpus_source_deletions WHERE source_id=%s",
            (source_id,),
        )
        if existing is None:
            await session.execute(
                """INSERT INTO corpus_source_deletions
                   (source_id,expected_revision,status,tombstones_json,
                    created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s)""",
                (
                    source_id,
                    expected_revision,
                    status,
                    _json(tuple(tombstones)),
                    now,
                    now,
                ),
            )
        else:
            await session.execute(
                """UPDATE corpus_source_deletions
                      SET expected_revision=%s,status=%s,tombstones_json=%s,
                          updated_at=%s
                    WHERE source_id=%s""",
                (
                    expected_revision,
                    status,
                    _json(tuple(tombstones)),
                    now,
                    source_id,
                ),
            )

    async def mark_source_deletion_succeeded(
        self,
        session,
        source_id: str,
        expected_revision: int,
        now: int,
    ) -> bool:
        changed = await session.execute(
            """UPDATE corpus_source_deletions
                  SET status='succeeded',updated_at=%s
                WHERE source_id=%s AND expected_revision=%s
                  AND status='cleanup_pending'""",
            (now, source_id, expected_revision),
        )
        return changed == 1

    async def cancel_source_deletion(
        self,
        session,
        source_id: str,
        expected_revision: int,
    ) -> bool:
        changed = await session.execute(
            """DELETE FROM corpus_source_deletions
                WHERE source_id=%s AND expected_revision=%s
                  AND status='restore_pending'""",
            (source_id, expected_revision),
        )
        return changed == 1

    async def find_import_by_key(
        self, session, idempotency_key: str, *, for_update: bool = False
    ):
        lock = " FOR UPDATE" if for_update else ""
        return await session.fetchone(
            "SELECT id,idempotency_key,request_hash,relative_path,"
            "content_hash AS source_hash,status,corpus_source_id,"
            "source_revision_id,source_revision,public_error_code,parser_versions_json,"
            "created_at,completed_at FROM corpus_import_runs "
            f"WHERE idempotency_key=%s{lock}",
            (idempotency_key,),
        )

    async def find_import_by_id(self, session, import_id: str):
        return await session.fetchone(
            "SELECT id,idempotency_key,request_hash,relative_path,"
            "content_hash AS source_hash,status,corpus_source_id,"
            "source_revision_id,source_revision,public_error_code,parser_versions_json,"
            "created_at,completed_at FROM corpus_import_runs WHERE id=%s",
            (import_id,),
        )

    async def insert_import(self, session, row: Mapping[str, object]) -> None:
        await session.execute(
            """INSERT INTO corpus_import_runs
               (id,idempotency_key,request_hash,relative_path,content_hash,status,
                corpus_source_id,source_revision_id,source_revision,
                public_error_code,parser_versions_json,
                created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,NULL,NULL,%s,%s,NULL)""",
            (
                row["id"], row["idempotency_key"], row["request_hash"],
                row["relative_path"], row["source_hash"], row["status"],
                _json(row["versions"]), row["created_at"],
            ),
        )

    async def insert_or_validate_blob(
        self,
        session,
        *,
        content_hash: str,
        byte_length: int,
        storage_key: str,
        created_at: int,
    ) -> None:
        await session.execute(
            """INSERT INTO corpus_blobs
               (content_hash,byte_length,storage_key,created_at)
               VALUES (%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE content_hash=corpus_blobs.content_hash""",
            (content_hash, byte_length, storage_key, created_at),
        )
        blob = await session.fetchone(
            """SELECT byte_length,storage_key FROM corpus_blobs
               WHERE content_hash=%s""",
            (content_hash,),
        )
        if blob != {
            "byte_length": byte_length,
            "storage_key": storage_key,
        }:
            raise RuntimeError("corpus blob registry collision")

    async def mark_import_succeeded(
        self, session, import_id: str, source_id: str,
        source_revision_id: str, source_revision: int, completed_at: int,
    ) -> None:
        affected = await session.execute(
            "UPDATE corpus_import_runs SET status='succeeded',"
            "corpus_source_id=%s,source_revision_id=%s,source_revision=%s,"
            "public_error_code=NULL,completed_at=%s "
            "WHERE id=%s AND status IN ('reserved','running')",
            (
                source_id, source_revision_id, source_revision,
                completed_at, import_id,
            ),
        )
        if affected != 1:
            raise RuntimeError("corpus import success transition was rejected")

    async def find_analysis_source(
        self,
        session,
        *,
        source_key: str,
        source_hash: str,
        parser_version: str,
        normalizer_version: str,
        fragmenter_version: str,
        index_version: str,
    ):
        return await session.fetchone(
            """SELECT source.id,source.source_key,revision.id AS revision_id,
                      revision.revision,revision.relative_path,
                      revision.display_name AS title,revision.author,
                      revision.content_hash AS source_hash,
                      revision.byte_length AS file_size,revision.encoding,
                      revision.parser_version,revision.normalizer_version,
                      revision.fragmenter_version,revision.index_version,
                      revision.status
               FROM corpus_source_revisions revision
               JOIN corpus_sources source ON source.id=revision.source_id
               WHERE source.source_key=%s
                 AND revision.content_hash=%s AND revision.parser_version=%s
                 AND revision.normalizer_version=%s
                 AND revision.fragmenter_version=%s
                 AND revision.index_version=%s FOR UPDATE""",
            (
                source_key, source_hash, parser_version, normalizer_version,
                fragmenter_version, index_version,
            ),
        )

    async def find_global_analysis_source(
        self,
        session,
        *,
        source_hash: str,
        parser_version: str,
        normalizer_version: str,
        fragmenter_version: str,
        index_version: str,
    ):
        return await session.fetchone(
            """SELECT source.id,source.source_key,revision.id AS revision_id,
                      revision.revision,revision.relative_path,
                      revision.display_name AS title,revision.author,
                      revision.reference_tags_json,revision.notes,
                      revision.content_hash AS source_hash,
                      revision.byte_length AS file_size,revision.encoding,
                      revision.parser_version,revision.normalizer_version,
                      revision.fragmenter_version,revision.index_version,
                      revision.status
               FROM corpus_source_revisions revision
               JOIN corpus_sources source ON source.id=revision.source_id
               WHERE source.archived_at IS NULL
                 AND revision.content_hash=%s AND revision.parser_version=%s
                 AND revision.normalizer_version=%s
                 AND revision.fragmenter_version=%s
                 AND revision.index_version=%s
               ORDER BY revision.imported_at DESC,source.id DESC,
                        revision.revision DESC
               LIMIT 1 FOR UPDATE""",
            (
                source_hash, parser_version, normalizer_version,
                fragmenter_version, index_version,
            ),
        )

    async def find_global_content_source(
        self, session, source_hash: str
    ):
        return await session.fetchone(
            """SELECT source.id AS source_id,source.source_key
               FROM corpus_source_revisions revision
               JOIN corpus_sources source ON source.id=revision.source_id
               WHERE source.archived_at IS NULL
                 AND revision.content_hash=%s
               ORDER BY revision.imported_at DESC,source.id DESC,
                        revision.revision DESC
               LIMIT 1 FOR UPDATE""",
            (source_hash,),
        )

    async def lock_source_revisions(self, session, source_id: str):
        return await session.fetchall(
            """SELECT source.id AS source_id,source.source_key,
                      source.archived_at,revision.id AS revision_id,
                      revision.revision,revision.content_hash AS source_hash,
                      revision.relative_path,revision.display_name AS title,
                      revision.reference_tags_json,revision.notes,
                      revision.parser_version,revision.normalizer_version,
                      revision.fragmenter_version,revision.index_version
               FROM corpus_sources source
               LEFT JOIN corpus_source_revisions revision
                 ON revision.source_id=source.id
               WHERE source.id=%s
               ORDER BY revision.revision FOR UPDATE""",
            (source_id,),
        )

    async def list_source_revisions_for_update(self, session, source_key: str):
        return await session.fetchall(
            """SELECT source.id AS source_id,revision.id AS revision_id,
                      revision.revision,revision.content_hash AS source_hash,
                      revision.parser_version,revision.normalizer_version,
                      revision.fragmenter_version,revision.index_version
               FROM corpus_sources source
               JOIN corpus_source_revisions revision
                 ON revision.source_id=source.id
               WHERE source.source_key=%s
               ORDER BY revision.revision FOR UPDATE""",
            (source_key,),
        )

    async def insert_source(self, session, row: Mapping[str, object]) -> None:
        if int(row["revision"]) == 1:
            await session.execute(
                """INSERT INTO corpus_sources
                   (id,source_key,archived_at,created_at,updated_at)
                   VALUES (%s,%s,NULL,%s,%s)""",
                (
                    row["id"], row["source_key"],
                    row["imported_at"], row["imported_at"],
                ),
            )
        await session.execute(
            """INSERT INTO corpus_source_revisions
               (id,source_id,revision,content_hash,relative_path,display_name,
                author,reference_tags_json,notes,provenance_json,byte_length,
                encoding,parser_version,normalizer_version,fragmenter_version,
                index_version,status,public_error_code,imported_at,analyzed_at,
                created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       'analyzed',NULL,%s,%s,%s)""",
            (
                *tuple(row[key] for key in (
                "revision_id", "id", "revision", "source_hash",
                "relative_path", "title", "author",
                )),
                _json(row["reference_tags"]),
                row["notes"],
                _json(row["provenance"]),
                *tuple(row[key] for key in (
                "file_size", "encoding",
                "parser_version", "normalizer_version", "fragmenter_version",
                "index_version", "imported_at", "analyzed_at", "imported_at",
                )),
            ),
        )
        if int(row["revision"]) == 1:
            await session.execute(
                """INSERT INTO corpus_source_heads
                   (source_id,revision_id,revision,content_hash,updated_at)
                   VALUES (%s,%s,%s,%s,%s)""",
                (
                    row["id"], row["revision_id"], row["revision"],
                    row["source_hash"], row["analyzed_at"],
                ),
            )
        else:
            affected = await session.execute(
                """UPDATE corpus_source_heads
                   SET revision_id=%s,revision=%s,content_hash=%s,updated_at=%s
                   WHERE source_id=%s AND revision=%s""",
                (
                    row["revision_id"], row["revision"], row["source_hash"],
                    row["analyzed_at"], row["id"], int(row["revision"]) - 1,
                ),
            )
            if affected != 1:
                raise RuntimeError("corpus source head transition was rejected")
            await session.execute(
                """UPDATE corpus_sources
                   SET archived_at=NULL,updated_at=%s WHERE id=%s""",
                (row["analyzed_at"], row["id"]),
            )

    async def insert_chapter(self, session, row: Mapping[str, object]) -> None:
        await session.execute(
            """INSERT INTO corpus_chapters
               (id,corpus_source_id,source_revision_id,source_revision,
                source_hash,chapter_order,title,raw_byte_start,
                raw_byte_end,normalized_char_start,normalized_char_end,
                normalized_text,content_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            tuple(row[key] for key in (
                "id", "corpus_source_id", "source_revision_id",
                "source_revision", "source_hash", "chapter_order", "title",
                "raw_byte_start", "raw_byte_end", "normalized_char_start",
                "normalized_char_end", "normalized_text", "content_hash",
                "created_at",
            )),
        )

    async def insert_fragment(self, session, row: Mapping[str, object]) -> None:
        await session.execute(
            """INSERT INTO corpus_fragments
               (id,corpus_source_id,corpus_chapter_id,fragment_order,chapter_char_start,
                chapter_char_end,normalized_text,content_hash,index_payload,
                analysis_version,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"], row["corpus_source_id"],
                row["corpus_chapter_id"], row["fragment_order"],
                row["chapter_char_start"], row["chapter_char_end"],
                row["normalized_text"], row["content_hash"],
                _json(row["index_payload"]), row["analysis_version"],
                row["created_at"],
            ),
        )

    async def list_library_sources(
        self,
        session,
        *,
        search: str,
        state: str,
        limit: int = 200,
    ):
        state_clause = {
            "active": "AND s.archived_at IS NULL",
            "archived": "AND s.archived_at IS NOT NULL",
            "all": "",
        }[state]
        search_clause = ""
        args: list[object] = []
        if search:
            search_clause = """
              AND (
                r.display_name LIKE %s
                OR r.relative_path LIKE %s
                OR r.notes LIKE %s
                OR CAST(r.reference_tags_json AS CHAR) LIKE %s
              )"""
            needle = f"%{search}%"
            args.extend((needle, needle, needle, needle))
        current_refs = _reference_count_sql("r")
        historical_refs = _reference_count_sql("historical")
        query = f"""
            SELECT s.id,r.id AS revision_id,r.revision,
                   r.display_name AS title,r.relative_path,
                   r.reference_tags_json,r.notes,
                   r.content_hash AS source_hash,r.encoding,r.status,
                   s.archived_at,r.imported_at,
                   COUNT(DISTINCT c.id) AS chapter_count,
                   COUNT(DISTINCT f.id) AS fragment_count,
                   {current_refs} AS reference_count,
                   COALESCE((
                     SELECT SUM({historical_refs})
                     FROM corpus_source_revisions historical
                     WHERE historical.source_id=s.id AND historical.id<>r.id
                   ),0) AS historical_reference_count
              FROM corpus_sources s
              JOIN corpus_source_heads h ON h.source_id=s.id
              JOIN corpus_source_revisions r
                ON r.source_id=s.id AND r.id=h.revision_id
              LEFT JOIN corpus_chapters c
                ON c.corpus_source_id=s.id AND c.source_revision_id=r.id
              LEFT JOIN corpus_fragments f ON f.corpus_chapter_id=c.id
             WHERE r.status='analyzed'
                   {state_clause}
                   {search_clause}
             GROUP BY s.id,r.id,r.revision,r.display_name,r.relative_path,
                      r.reference_tags_json,r.notes,r.content_hash,r.encoding,
                      r.status,s.archived_at,r.imported_at
             ORDER BY s.archived_at IS NOT NULL,r.imported_at DESC,s.id
             LIMIT %s"""
        args.append(limit)
        return await session.fetchall(query, tuple(args))

    async def list_sources(self, session, *, limit: int = 200):
        return await self.list_library_sources(
            session, search="", state="active", limit=limit
        )

    async def find_library_source(
        self, session, source_id: str, preview_chars: int
    ):
        current_refs = _reference_count_sql("r")
        historical_refs = _reference_count_sql("historical")
        return await session.fetchone(
            f"""SELECT s.id,r.id AS revision_id,r.revision,
                      r.display_name AS title,r.relative_path,
                      r.reference_tags_json,r.notes,
                      r.content_hash AS source_hash,r.encoding,r.status,
                      s.archived_at,r.imported_at,
                      COUNT(DISTINCT c.id) AS chapter_count,
                      COUNT(DISTINCT f.id) AS fragment_count,
                      {current_refs} AS reference_count,
                      COALESCE((
                        SELECT SUM({historical_refs})
                        FROM corpus_source_revisions historical
                        WHERE historical.source_id=s.id AND historical.id<>r.id
                      ),0) AS historical_reference_count,
                      COALESCE((
                        SELECT LEFT(c2.normalized_text,%s)
                        FROM corpus_chapters c2
                        WHERE c2.corpus_source_id=s.id
                          AND c2.source_revision_id=r.id
                        ORDER BY c2.chapter_order,c2.id LIMIT 1
                      ),'') AS preview
               FROM corpus_sources s
               JOIN corpus_source_heads h ON h.source_id=s.id
               JOIN corpus_source_revisions r
                 ON r.source_id=s.id AND r.id=h.revision_id
               LEFT JOIN corpus_chapters c
                 ON c.corpus_source_id=s.id AND c.source_revision_id=r.id
               LEFT JOIN corpus_fragments f ON f.corpus_chapter_id=c.id
               WHERE s.id=%s AND r.status='analyzed'
               GROUP BY s.id,r.id,r.revision,r.display_name,r.relative_path,
                        r.reference_tags_json,r.notes,r.content_hash,r.encoding,
                        r.status,s.archived_at,r.imported_at""",
            (preview_chars, source_id),
        )

    async def find_source(self, session, source_id: str, preview_chars: int):
        return await self.find_library_source(session, source_id, preview_chars)

    async def list_source_versions(
        self,
        session,
        source_id: str,
        *,
        before_revision: int | None,
        limit: int,
    ):
        refs = _reference_count_sql("r")
        cursor_clause = ""
        args: list[object] = [source_id]
        if before_revision is not None:
            cursor_clause = "AND r.revision<%s"
            args.append(before_revision)
        args.append(limit + 1)
        return await session.fetchall(
            f"""SELECT r.id,r.source_id,r.revision,r.content_hash AS source_hash,
                      r.display_name AS title,r.relative_path,
                      r.reference_tags_json,r.notes,r.encoding,r.status,
                      s.archived_at,r.imported_at,
                      {refs} AS reference_count,
                      (h.revision_id=r.id) AS is_current
                 FROM corpus_source_revisions r
                 JOIN corpus_sources s ON s.id=r.source_id
                 JOIN corpus_source_heads h ON h.source_id=s.id
                WHERE s.id=%s
                      {cursor_clause}
                ORDER BY r.revision DESC,r.id
                LIMIT %s""",
            tuple(args),
        )

    async def lock_library_source(self, session, source_id: str):
        return await session.fetchone(
            """SELECT s.id,h.revision,r.id AS revision_id,
                      r.content_hash AS source_hash,r.display_name AS title,
                      r.relative_path,r.reference_tags_json,r.notes,r.encoding,
                      r.status,s.archived_at
                 FROM corpus_sources s
                 JOIN corpus_source_heads h ON h.source_id=s.id
                 JOIN corpus_source_revisions r ON r.id=h.revision_id
                WHERE s.id=%s FOR UPDATE""",
            (source_id,),
        )

    async def archive_source(
        self, session, source_id: str, expected_revision: int, archived_at: int
    ) -> bool:
        changed = await session.execute(
            """UPDATE corpus_sources source
                  JOIN corpus_source_heads head ON head.source_id=source.id
                   SET source.archived_at=%s,source.updated_at=%s
                 WHERE source.id=%s AND source.archived_at IS NULL
                   AND head.revision=%s""",
            (archived_at, archived_at, source_id, expected_revision),
        )
        return changed == 1

    async def restore_source(
        self, session, source_id: str, expected_revision: int
    ) -> bool:
        changed = await session.execute(
            """UPDATE corpus_sources source
                  JOIN corpus_source_heads head ON head.source_id=source.id
                   SET source.archived_at=NULL,source.updated_at=head.updated_at
                 WHERE source.id=%s AND source.archived_at IS NOT NULL
                   AND head.revision=%s""",
            (source_id, expected_revision),
        )
        return changed == 1

    async def source_reference_counts(self, session, source_id: str):
        refs = _reference_count_sql("revision")
        return await session.fetchall(
            f"""SELECT revision.revision,{refs} AS reference_count
                  FROM corpus_source_revisions revision
                 WHERE revision.source_id=%s
                 ORDER BY revision.revision FOR UPDATE""",
            (source_id,),
        )

    async def lock_source_blobs(self, session, source_id: str):
        return await session.fetchall(
            """SELECT managed_blob.content_hash,managed_blob.byte_length,
                      managed_blob.storage_key
                 FROM corpus_blobs managed_blob
                WHERE managed_blob.content_hash IN (
                      SELECT revision.content_hash
                        FROM corpus_source_revisions revision
                       WHERE revision.source_id=%s
                )
                ORDER BY managed_blob.content_hash FOR UPDATE""",
            (source_id,),
        )

    async def delete_source(self, session, source_id: str) -> bool:
        await session.execute(
            "DELETE FROM corpus_import_runs WHERE corpus_source_id=%s",
            (source_id,),
        )
        await session.execute(
            """DELETE fragment FROM corpus_fragments fragment
                 JOIN corpus_chapters chapter
                   ON chapter.id=fragment.corpus_chapter_id
                WHERE chapter.corpus_source_id=%s""",
            (source_id,),
        )
        await session.execute(
            "DELETE FROM corpus_chapters WHERE corpus_source_id=%s",
            (source_id,),
        )
        await session.execute(
            "DELETE FROM corpus_source_heads WHERE source_id=%s",
            (source_id,),
        )
        await session.execute(
            "DELETE FROM corpus_source_revisions WHERE source_id=%s",
            (source_id,),
        )
        changed = await session.execute(
            "DELETE FROM corpus_sources WHERE id=%s AND archived_at IS NOT NULL",
            (source_id,),
        )
        return changed == 1

    async def delete_unreferenced_blobs(
        self, session, candidates
    ):
        deleted: list[dict] = []
        for candidate in candidates:
            changed = await session.execute(
                """DELETE FROM corpus_blobs
                    WHERE content_hash=%s
                      AND NOT EXISTS (
                        SELECT 1 FROM corpus_source_revisions revision
                         WHERE revision.content_hash=%s
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM corpus_import_runs import_run
                         WHERE import_run.content_hash=%s
                      )""",
                (
                    candidate["content_hash"],
                    candidate["content_hash"],
                    candidate["content_hash"],
                ),
            )
            if changed == 1:
                deleted.append(dict(candidate))
        return tuple(deleted)

    async def list_chapters(self, session, source_id: str, *, limit: int = 200):
        return await session.fetchall(
            """SELECT chapter.id,chapter.chapter_order,chapter.title,
                      chapter.raw_byte_start,chapter.raw_byte_end,
                      chapter.normalized_char_start,chapter.normalized_char_end,
                      chapter.content_hash
               FROM corpus_chapters chapter
               JOIN corpus_source_heads head
                 ON head.source_id=chapter.corpus_source_id
                AND head.revision_id=chapter.source_revision_id
               WHERE chapter.corpus_source_id=%s
               ORDER BY chapter_order,id LIMIT %s""",
            (source_id, limit),
        )

    async def source_exists(self, session, source_id: str) -> bool:
        row = await session.fetchone(
            """SELECT source.id FROM corpus_sources source
               JOIN corpus_source_heads head ON head.source_id=source.id
               JOIN corpus_source_revisions revision
                 ON revision.source_id=source.id AND revision.id=head.revision_id
               WHERE source.id=%s AND revision.status='analyzed'""",
            (source_id,),
        )
        return row is not None

    async def chapter_exists(self, session, chapter_id: str) -> bool:
        row = await session.fetchone(
            "SELECT id FROM corpus_chapters WHERE id=%s", (chapter_id,)
        )
        return row is not None

    async def list_fragments(
        self, session, chapter_id: str, *, after_order: int, limit: int
    ):
        return await session.fetchall(
            """SELECT id,fragment_order,chapter_char_start,chapter_char_end,
                      normalized_text,content_hash
               FROM corpus_fragments
               WHERE corpus_chapter_id=%s AND fragment_order>%s
               ORDER BY fragment_order,id LIMIT %s""",
            (chapter_id, after_order, limit + 1),
        )

    async def list_recommendation_fragments(
        self,
        session,
        *,
        after: tuple[str, int, int, str] | None,
        limit: int,
    ):
        """Return a bounded safe projection of active current corpus rows."""

        cursor_clause = ""
        params: tuple[object, ...] = (limit,)
        if after is not None:
            cursor_clause = """AND (
                source.id,chapter.chapter_order,
                fragment.fragment_order,fragment.id
            ) > (%s,%s,%s,%s)"""
            params = (*after, limit)
        return await session.fetchall(
            f"""SELECT source.id AS source_id,
                      revision.id AS source_revision_id,
                      revision.revision AS source_revision,
                      revision.content_hash AS source_hash,
                      revision.reference_tags_json,revision.display_name,
                      chapter.id AS chapter_id,chapter.title AS chapter_title,
                      chapter.chapter_order,
                      fragment.id AS fragment_id,
                      fragment.fragment_order,
                      fragment.content_hash AS fragment_hash,
                      fragment.chapter_char_start,fragment.chapter_char_end,
                      fragment.normalized_text
                 FROM corpus_sources source
                 JOIN corpus_source_heads head
                   ON head.source_id=source.id
                 JOIN corpus_source_revisions revision
                   ON revision.source_id=source.id
                  AND head.revision_id=revision.id
                  AND head.revision=revision.revision
                  AND head.content_hash=revision.content_hash
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
                  AND CHAR_LENGTH(fragment.normalized_text)>0
                  {cursor_clause}
                ORDER BY source.id,chapter.chapter_order,
                         fragment.fragment_order,fragment.id
                LIMIT %s""",
            params,
        )


__all__ = ("CorpusRepository",)
