"""Read-only bounded receipt for a published corpus source."""

from __future__ import annotations

import argparse
import asyncio
import json
import re

import aiomysql

from backend.config import MYSQL_CONFIG, require_mysql_config
from backend.database import DatabaseSession


_DATABASE_NAME = re.compile(r"[A-Za-z0-9_]+\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


async def build_receipt(
    session, *, source_id: str | None = None, source_hash: str | None = None
) -> dict[str, object]:
    """Return an allowlisted receipt using one SELECT and no body columns."""

    if (source_id is None) == (source_hash is None):
        raise ValueError("exactly one source selector is required")
    if source_hash is not None and _HASH.fullmatch(source_hash) is None:
        raise ValueError("source hash must be 64 lowercase hexadecimal characters")
    column = "s.id" if source_id is not None else "s.source_hash"
    selector = source_id if source_id is not None else source_hash
    row = await session.fetchone(
        f"""SELECT s.relative_path,s.source_hash,s.encoding,s.file_size,
                    s.parser_version,s.normalizer_version,s.fragmenter_version,
                    s.index_version,s.status,
                    (SELECT COUNT(*) FROM corpus_chapters c
                      WHERE c.corpus_source_id=s.id) AS chapter_count,
                    (SELECT COUNT(*) FROM corpus_fragments f
                      JOIN corpus_chapters c ON c.id=f.corpus_chapter_id
                      WHERE c.corpus_source_id=s.id) AS fragment_count,
                    (SELECT MIN(c.raw_byte_start) FROM corpus_chapters c
                      WHERE c.corpus_source_id=s.id) AS first_byte_start,
                    (SELECT MAX(c.raw_byte_end) FROM corpus_chapters c
                      WHERE c.corpus_source_id=s.id) AS last_byte_end,
                    (SELECT MIN(c.normalized_char_start) FROM corpus_chapters c
                      WHERE c.corpus_source_id=s.id) AS first_char_start,
                    (SELECT MAX(c.normalized_char_end) FROM corpus_chapters c
                      WHERE c.corpus_source_id=s.id) AS last_char_end
             FROM corpus_sources s WHERE {column}=%s
             ORDER BY s.imported_at DESC,s.id DESC LIMIT 1""",
        (selector,),
    )
    if row is None:
        raise LookupError("corpus source not found")
    return {
        "relativePath": row["relative_path"],
        "rawHash": row["source_hash"],
        "encoding": row["encoding"],
        "size": int(row["file_size"]),
        "chapterCount": int(row["chapter_count"]),
        "fragmentCount": int(row["fragment_count"]),
        "firstByteStart": row["first_byte_start"],
        "lastByteEnd": row["last_byte_end"],
        "firstCharStart": row["first_char_start"],
        "lastCharEnd": row["last_char_end"],
        "parserVersion": row["parser_version"],
        "normalizerVersion": row["normalizer_version"],
        "fragmenterVersion": row["fragmenter_version"],
        "indexVersion": row["index_version"],
        "status": row["status"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    selectors = parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--source-id")
    selectors.add_argument("--source-hash")
    return parser


async def _run(args) -> dict[str, object]:
    if _DATABASE_NAME.fullmatch(args.database) is None:
        raise RuntimeError("database name contains unsupported characters")
    config = require_mysql_config(MYSQL_CONFIG)
    connection = await aiomysql.connect(
        host=config["host"], port=config["port"], user=config["user"],
        password=config["password"], db=args.database, charset="utf8mb4",
        autocommit=True,
    )
    try:
        return await build_receipt(
            DatabaseSession(connection),
            source_id=args.source_id,
            source_hash=args.source_hash,
        )
    finally:
        connection.close()


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    receipt = asyncio.run(_run(args))
    print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
