"""Session-bound SQL persistence for immutable corpus publications."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json


def _json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


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
            """INSERT INTO corpus_blobs
               (content_hash,byte_length,storage_key,created_at)
               VALUES (%s,%s,%s,%s)
               ON DUPLICATE KEY UPDATE content_hash=corpus_blobs.content_hash""",
            (
                row["source_hash"], row["byte_length"],
                f"sha256/{row['source_hash']}", row["created_at"],
            ),
        )
        blob = await session.fetchone(
            """SELECT byte_length,storage_key FROM corpus_blobs
               WHERE content_hash=%s""",
            (row["source_hash"],),
        )
        if blob != {
            "byte_length": row["byte_length"],
            "storage_key": f"sha256/{row['source_hash']}",
        }:
            raise RuntimeError("corpus blob registry collision")
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

    async def mark_import_failed(
        self, session, import_id: str, error_code: str, completed_at: int
    ) -> None:
        affected = await session.execute(
            "UPDATE corpus_import_runs SET status='failed',"
            "corpus_source_id=NULL,source_revision_id=NULL,source_revision=NULL,"
            "public_error_code=%s,completed_at=%s "
            "WHERE id=%s AND status IN ('reserved','running')",
            (error_code, completed_at, import_id),
        )
        if affected != 1:
            raise RuntimeError("corpus import failure transition was rejected")

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
               VALUES (%s,%s,%s,%s,%s,%s,%s,'[]','','{}',%s,%s,%s,%s,%s,%s,
                       'analyzed',NULL,%s,%s,%s)""",
            tuple(row[key] for key in (
                "revision_id", "id", "revision", "source_hash",
                "relative_path", "title", "author", "file_size", "encoding",
                "parser_version", "normalizer_version", "fragmenter_version",
                "index_version", "imported_at", "analyzed_at", "imported_at",
            )),
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
                "UPDATE corpus_sources SET updated_at=%s WHERE id=%s",
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

    async def list_sources(self, session, *, limit: int = 200):
        return await session.fetchall(
            """SELECT s.id,r.revision,r.display_name AS title,r.relative_path,
                      r.content_hash AS source_hash,r.encoding,r.status,
                      COUNT(DISTINCT c.id) AS chapter_count,
                      COUNT(DISTINCT f.id) AS fragment_count
               FROM corpus_sources s
               JOIN corpus_source_heads h ON h.source_id=s.id
               JOIN corpus_source_revisions r
                 ON r.source_id=s.id AND r.id=h.revision_id
               LEFT JOIN corpus_chapters c
                 ON c.corpus_source_id=s.id AND c.source_revision_id=r.id
               LEFT JOIN corpus_fragments f ON f.corpus_chapter_id=c.id
               WHERE r.status='analyzed'
               GROUP BY s.id,r.revision,r.display_name,r.relative_path,
                        r.content_hash,r.encoding,r.status
               ORDER BY r.imported_at DESC,s.id LIMIT %s""",
            (limit,),
        )

    async def find_source(self, session, source_id: str, preview_chars: int):
        return await session.fetchone(
            """SELECT s.id,r.revision,r.display_name AS title,r.relative_path,
                      r.content_hash AS source_hash,r.encoding,r.status,
                      COUNT(DISTINCT c.id) AS chapter_count,
                      COUNT(DISTINCT f.id) AS fragment_count,
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
                        r.content_hash,r.encoding,r.status""",
            (preview_chars, source_id),
        )

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


__all__ = ("CorpusRepository",)
