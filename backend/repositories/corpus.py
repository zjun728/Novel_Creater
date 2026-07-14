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
            "SELECT id,idempotency_key,request_hash,relative_path,source_hash,"
            "status,corpus_source_id,public_error_code,parser_versions_json,"
            "created_at,completed_at FROM corpus_import_runs "
            f"WHERE idempotency_key=%s{lock}",
            (idempotency_key,),
        )

    async def find_import_by_id(self, session, import_id: str):
        return await session.fetchone(
            "SELECT id,idempotency_key,request_hash,relative_path,source_hash,"
            "status,corpus_source_id,public_error_code,parser_versions_json,"
            "created_at,completed_at FROM corpus_import_runs WHERE id=%s",
            (import_id,),
        )

    async def insert_import(self, session, row: Mapping[str, object]) -> None:
        await session.execute(
            """INSERT INTO corpus_import_runs
               (id,idempotency_key,request_hash,relative_path,source_hash,status,
                corpus_source_id,public_error_code,parser_versions_json,
                created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,%s,%s,NULL)""",
            (
                row["id"], row["idempotency_key"], row["request_hash"],
                row["relative_path"], row["source_hash"], row["status"],
                _json(row["versions"]), row["created_at"],
            ),
        )

    async def mark_import_succeeded(
        self, session, import_id: str, source_id: str, completed_at: int
    ) -> None:
        affected = await session.execute(
            "UPDATE corpus_import_runs SET status='succeeded',"
            "corpus_source_id=%s,public_error_code=NULL,completed_at=%s "
            "WHERE id=%s AND status IN ('reserved','running')",
            (source_id, completed_at, import_id),
        )
        if affected != 1:
            raise RuntimeError("corpus import success transition was rejected")

    async def mark_import_failed(
        self, session, import_id: str, error_code: str, completed_at: int
    ) -> None:
        affected = await session.execute(
            "UPDATE corpus_import_runs SET status='failed',"
            "corpus_source_id=NULL,public_error_code=%s,completed_at=%s "
            "WHERE id=%s AND status IN ('reserved','running')",
            (error_code, completed_at, import_id),
        )
        if affected != 1:
            raise RuntimeError("corpus import failure transition was rejected")

    async def find_analysis_source(
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
            """SELECT id,source_key,revision,relative_path,title,author,
                      source_hash,file_size,encoding,parser_version,
                      normalizer_version,fragmenter_version,index_version,status
               FROM corpus_sources
               WHERE source_hash=%s AND parser_version=%s
                 AND normalizer_version=%s AND fragmenter_version=%s
                 AND index_version=%s FOR UPDATE""",
            (
                source_hash, parser_version, normalizer_version,
                fragmenter_version, index_version,
            ),
        )

    async def list_source_revisions_for_update(self, session, source_key: str):
        return await session.fetchall(
            "SELECT id,revision,source_hash,parser_version,normalizer_version,"
            "fragmenter_version,index_version FROM corpus_sources "
            "WHERE source_key=%s ORDER BY revision FOR UPDATE",
            (source_key,),
        )

    async def insert_source(self, session, row: Mapping[str, object]) -> None:
        await session.execute(
            """INSERT INTO corpus_sources
               (id,source_key,revision,relative_path,title,author,source_hash,
                file_size,encoding,parser_version,normalizer_version,
                fragmenter_version,index_version,status,public_error_code,
                imported_at,analyzed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                       'analyzed',NULL,%s,%s)""",
            tuple(row[key] for key in (
                "id", "source_key", "revision", "relative_path", "title",
                "author", "source_hash", "file_size", "encoding",
                "parser_version", "normalizer_version", "fragmenter_version",
                "index_version", "imported_at", "analyzed_at",
            )),
        )

    async def insert_chapter(self, session, row: Mapping[str, object]) -> None:
        await session.execute(
            """INSERT INTO corpus_chapters
               (id,corpus_source_id,chapter_order,title,raw_byte_start,
                raw_byte_end,normalized_char_start,normalized_char_end,
                normalized_text,content_hash,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            tuple(row[key] for key in (
                "id", "corpus_source_id", "chapter_order", "title",
                "raw_byte_start", "raw_byte_end", "normalized_char_start",
                "normalized_char_end", "normalized_text", "content_hash",
                "created_at",
            )),
        )

    async def insert_fragment(self, session, row: Mapping[str, object]) -> None:
        await session.execute(
            """INSERT INTO corpus_fragments
               (id,corpus_chapter_id,fragment_order,chapter_char_start,
                chapter_char_end,normalized_text,content_hash,index_payload,
                analysis_version,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["id"], row["corpus_chapter_id"], row["fragment_order"],
                row["chapter_char_start"], row["chapter_char_end"],
                row["normalized_text"], row["content_hash"],
                _json(row["index_payload"]), row["analysis_version"],
                row["created_at"],
            ),
        )

    async def list_sources(self, session, *, limit: int = 200):
        return await session.fetchall(
            """SELECT s.id,s.title,s.relative_path,s.source_hash,s.encoding,
                      s.status,COUNT(DISTINCT c.id) AS chapter_count,
                      COUNT(DISTINCT f.id) AS fragment_count
               FROM corpus_sources s
               LEFT JOIN corpus_chapters c ON c.corpus_source_id=s.id
               LEFT JOIN corpus_fragments f ON f.corpus_chapter_id=c.id
               WHERE s.status='analyzed'
               GROUP BY s.id,s.title,s.relative_path,s.source_hash,s.encoding,s.status
               ORDER BY s.imported_at DESC,s.id LIMIT %s""",
            (limit,),
        )

    async def find_source(self, session, source_id: str, preview_chars: int):
        return await session.fetchone(
            """SELECT s.id,s.title,s.relative_path,s.source_hash,s.encoding,
                      s.status,COUNT(DISTINCT c.id) AS chapter_count,
                      COUNT(DISTINCT f.id) AS fragment_count,
                      COALESCE((
                        SELECT LEFT(c2.normalized_text,%s)
                        FROM corpus_chapters c2
                        WHERE c2.corpus_source_id=s.id
                        ORDER BY c2.chapter_order,c2.id LIMIT 1
                      ),'') AS preview
               FROM corpus_sources s
               LEFT JOIN corpus_chapters c ON c.corpus_source_id=s.id
               LEFT JOIN corpus_fragments f ON f.corpus_chapter_id=c.id
               WHERE s.id=%s AND s.status='analyzed'
               GROUP BY s.id,s.title,s.relative_path,s.source_hash,s.encoding,s.status""",
            (preview_chars, source_id),
        )

    async def list_chapters(self, session, source_id: str, *, limit: int = 200):
        return await session.fetchall(
            """SELECT id,chapter_order,title,raw_byte_start,raw_byte_end,
                      normalized_char_start,normalized_char_end,content_hash
               FROM corpus_chapters WHERE corpus_source_id=%s
               ORDER BY chapter_order,id LIMIT %s""",
            (source_id, limit),
        )

    async def source_exists(self, session, source_id: str) -> bool:
        row = await session.fetchone(
            "SELECT id FROM corpus_sources WHERE id=%s AND status='analyzed'",
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
