from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
from itertools import count
import json

import pytest

from backend.domain.corpus import (
    FRAGMENTER_VERSION,
    INDEX_VERSION,
    NORMALIZER_VERSION,
    PARSER_VERSION,
)
from backend.http_errors import CorpusImportConflict, CorpusImportFailed
from backend.repositories.corpus import CorpusRepository
from backend.scripts.verify_corpus_import import build_receipt
from backend.services.corpus_import import CorpusImportService
from backend.services.corpus_import import _hash_document
from backend.tests.support.disposable_mysql import transaction_factory_for


pytestmark = [pytest.mark.mysql, pytest.mark.asyncio]


def _ids(prefix: int = 1):
    values = count(prefix)
    return lambda: f"{next(values):08d}-0000-0000-0000-000000000000"


def _clock(start: int = 1_720_000_000_000):
    values = count(start)
    return lambda: next(values)


def _service(disposable_mysql, root, repository=None, **versions):
    factory = transaction_factory_for(disposable_mysql.connection_config)
    return CorpusImportService(
        repository or CorpusRepository(), corpus_root=root,
        transaction_factory=factory, connection_factory=factory,
        clock=_clock(), **versions,
    )


async def _counts(session):
    result = {}
    for table in (
        "corpus_sources", "corpus_chapters", "corpus_fragments",
        "corpus_import_runs",
    ):
        row = await session.fetchone(f"SELECT COUNT(*) AS count FROM {table}")
        result[table] = row["count"]
    return result


async def test_import_is_idempotent_dedupes_analysis_identity_and_stores_relative_path(
    disposable_mysql, tmp_path
):
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "book.txt").write_bytes(
        "序章\n原创开场。\n第一章 风起\n原创正文。".encode("utf-8")
    )
    service = _service(disposable_mysql, root)

    first = await service.import_source("book.txt", "a" * 32)
    replay = await service.import_source("book.txt", "a" * 32)
    dedupe = await service.import_source("book.txt", "b" * 32)

    assert replay["id"] == first["id"]
    assert dedupe["corpus_source_id"] == first["corpus_source_id"]
    assert first["status"] == "succeeded"
    settled = await service._settle_failure(first, "CORPUS_PUBLICATION_FAILED")
    assert settled["status"] == "succeeded"
    assert settled["corpus_source_id"] == first["corpus_source_id"]
    assert await _counts(disposable_mysql.session) == {
        "corpus_sources": 1, "corpus_chapters": 2,
        "corpus_fragments": 2, "corpus_import_runs": 2,
    }
    stored = await disposable_mysql.session.fetchall(
        "SELECT relative_path FROM corpus_sources UNION ALL "
        "SELECT relative_path FROM corpus_import_runs"
    )
    assert {row["relative_path"] for row in stored} == {"book.txt"}
    assert str(root) not in repr(stored)


async def test_same_idempotency_key_with_different_request_conflicts(
    disposable_mysql, tmp_path
):
    (tmp_path / "one.txt").write_bytes(b"one")
    (tmp_path / "two.txt").write_bytes(b"two")
    service = _service(disposable_mysql, tmp_path)
    await service.import_source("one.txt", "k" * 32)

    with pytest.raises(CorpusImportConflict):
        await service.import_source("two.txt", "k" * 32)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("parser_version", PARSER_VERSION + "-next"),
        ("normalizer_version", NORMALIZER_VERSION + "-next"),
        ("fragmenter_version", FRAGMENTER_VERSION + "-next"),
        ("index_version", INDEX_VERSION + "-next"),
    ),
)
async def test_any_analysis_version_change_creates_new_immutable_revision(
    disposable_mysql, tmp_path, field, value
):
    (tmp_path / "book.txt").write_bytes("第一章\n内容".encode())
    baseline = _service(disposable_mysql, tmp_path)
    first = await baseline.import_source("book.txt", "a" * 32)
    changed = _service(disposable_mysql, tmp_path, **{field: value})

    second = await changed.import_source("book.txt", "b" * 32)

    assert second["corpus_source_id"] != first["corpus_source_id"]
    rows = await disposable_mysql.session.fetchall(
        "SELECT revision,source_hash,parser_version,normalizer_version,"
        "fragmenter_version,index_version FROM corpus_sources "
        "ORDER BY revision"
    )
    assert [row["revision"] for row in rows] == [1, 2]
    assert rows[0]["source_hash"] == rows[1]["source_hash"]
    assert rows[1][field] == value


async def test_publication_failure_rolls_back_every_published_row_and_marks_run_failed(
    disposable_mysql, tmp_path
):
    class FailingRepository(CorpusRepository):
        async def insert_fragment(self, session, row):
            await super().insert_fragment(session, row)
            raise RuntimeError("PRIVATE_BODY_SENTINEL")

    (tmp_path / "broken-publication.txt").write_bytes(
        "第一章\n只用于合成测试。".encode()
    )
    before = await _counts(disposable_mysql.session)
    service = _service(disposable_mysql, tmp_path, FailingRepository())

    with pytest.raises(CorpusImportFailed):
        await service.import_source("broken-publication.txt", "f" * 32)

    after = await _counts(disposable_mysql.session)
    assert after == {**before, "corpus_import_runs": before["corpus_import_runs"] + 1}
    run = await disposable_mysql.session.fetchone(
        "SELECT status,corpus_source_id,public_error_code FROM corpus_import_runs "
        "WHERE idempotency_key=%s",
        ("f" * 32,),
    )
    assert run == {
        "status": "failed", "corpus_source_id": None,
        "public_error_code": "CORPUS_PUBLICATION_FAILED",
    }
    assert "PRIVATE_BODY_SENTINEL" not in repr(run)


async def test_decode_failure_is_marked_in_separate_short_transaction(
    disposable_mysql, tmp_path
):
    (tmp_path / "invalid.txt").write_bytes(b"\x00binary")
    service = _service(disposable_mysql, tmp_path)

    with pytest.raises(CorpusImportFailed):
        await service.import_source("invalid.txt", "d" * 32)

    assert await _counts(disposable_mysql.session) == {
        "corpus_sources": 0, "corpus_chapters": 0, "corpus_fragments": 0,
        "corpus_import_runs": 1,
    }
    run = await disposable_mysql.session.fetchone(
        "SELECT status,public_error_code FROM corpus_import_runs"
    )
    assert run == {"status": "failed", "public_error_code": "CORPUS_PARSE_FAILED"}

    for _ in range(2):
        with pytest.raises(CorpusImportFailed) as replay:
            await service.import_source("invalid.txt", "d" * 32)
        assert replay.value.code == "CorpusImportFailed"
    assert (await _counts(disposable_mysql.session))["corpus_import_runs"] == 1


@pytest.mark.parametrize("persisted_status", ("reserved", "running"))
async def test_committed_incomplete_run_replay_resumes_and_converges_once(
    disposable_mysql, tmp_path, persisted_status
):
    raw = "第一章\n恢复处理。".encode()
    (tmp_path / "recover.txt").write_bytes(raw)
    service = _service(disposable_mysql, tmp_path)
    source_hash = sha256(raw).hexdigest()
    request_hash = _hash_document({
        "relativePath": "recover.txt",
        "sourceHash": source_hash,
        "versions": service.versions,
    })
    run_id = f"9000000{0 if persisted_status == 'reserved' else 1}-0000-0000-0000-000000000000"
    await disposable_mysql.session.execute(
        """INSERT INTO corpus_import_runs
           (id,idempotency_key,request_hash,relative_path,source_hash,status,
            corpus_source_id,public_error_code,parser_versions_json,
            created_at,completed_at)
           VALUES (%s,%s,%s,%s,%s,%s,NULL,NULL,%s,%s,NULL)""",
        (
            run_id, "c" * 32, request_hash, "recover.txt", source_hash,
            persisted_status,
            json.dumps(service.versions, sort_keys=True, separators=(",", ":")),
            1_720_000_000_000,
        ),
    )

    recovered, concurrent_replay = await asyncio.gather(
        service.import_source("recover.txt", "c" * 32),
        service.import_source("recover.txt", "c" * 32),
    )
    winner_replay = await service.import_source("recover.txt", "c" * 32)

    assert {
        recovered["id"], concurrent_replay["id"], winner_replay["id"]
    } == {run_id}
    assert {
        recovered["status"], concurrent_replay["status"],
        winner_replay["status"],
    } == {"succeeded"}
    assert {
        recovered["corpus_source_id"], concurrent_replay["corpus_source_id"],
        winner_replay["corpus_source_id"],
    } == {recovered["corpus_source_id"]}
    assert await _counts(disposable_mysql.session) == {
        "corpus_sources": 1, "corpus_chapters": 1,
        "corpus_fragments": 1, "corpus_import_runs": 1,
    }


async def test_file_read_occurs_outside_every_database_transaction(
    disposable_mysql, tmp_path
):
    source = tmp_path / "book.txt"
    source.write_bytes(b"synthetic")
    base_factory = transaction_factory_for(disposable_mysql.connection_config)
    active = False

    @asynccontextmanager
    async def tracked_factory():
        nonlocal active
        assert not active
        active = True
        try:
            async with base_factory() as session:
                yield session
        finally:
            active = False

    def reader(path):
        assert not active
        return path.read_bytes()

    service = CorpusImportService(
        CorpusRepository(), corpus_root=tmp_path,
        transaction_factory=tracked_factory, connection_factory=tracked_factory,
        file_reader=reader, id_factory=_ids(), clock=_clock(),
    )
    await service.import_source("book.txt", "o" * 32)


async def test_real_read_queries_and_verifier_are_bounded_and_consistent(
    disposable_mysql, tmp_path
):
    (tmp_path / "book.txt").write_bytes(
        "序章\n开场。\n第一章 起风\n".encode() + ("内容" * 700).encode()
    )
    service = _service(disposable_mysql, tmp_path)
    imported = await service.import_source("book.txt", "r" * 32)
    source_id = imported["corpus_source_id"]

    source = await service.get_source(source_id, 600)
    chapters = await service.list_chapters(source_id)
    fragments = await service.list_fragments(chapters[1]["id"], 0, 10)
    receipt = await build_receipt(disposable_mysql.session, source_id=source_id)

    assert 0 < len(source["preview"]) <= 600
    assert source["preview"].startswith("序章")
    assert len(chapters) == source["chapter_count"] == 2
    assert 1 <= len(fragments["items"]) <= 10
    assert receipt["relativePath"] == "book.txt"
    assert receipt["rawHash"] == source["source_hash"]
    assert receipt["chapterCount"] == 2
    assert receipt["fragmentCount"] == source["fragment_count"]
    assert receipt["firstByteStart"] == 0
    assert receipt["lastByteEnd"] == receipt["size"]


async def test_hash_verifier_selects_global_latest_version_with_timestamp_tie(
    disposable_mysql, tmp_path
):
    raw = "第一章\n相同原始字节。".encode()
    (tmp_path / "old-path.txt").write_bytes(raw)
    (tmp_path / "new-path.txt").write_bytes(raw)
    factory = transaction_factory_for(disposable_mysql.connection_config)
    old_ids = iter((
        "10000000-0000-0000-0000-000000000001",
        "10000000-0000-0000-0000-000000000002",
        "10000000-0000-0000-0000-000000000003",
    ))
    new_ids = iter((
        "20000000-0000-0000-0000-000000000001",
        "20000000-0000-0000-0000-000000000002",
        "20000000-0000-0000-0000-000000000003",
    ))
    old = CorpusImportService(
        CorpusRepository(), corpus_root=tmp_path,
        transaction_factory=factory, connection_factory=factory,
        id_factory=lambda: next(old_ids), clock=lambda: 1_720_000_000_000,
    )
    new = CorpusImportService(
        CorpusRepository(), corpus_root=tmp_path,
        transaction_factory=factory, connection_factory=factory,
        parser_version=PARSER_VERSION + "-next",
        id_factory=lambda: next(new_ids), clock=lambda: 1_720_000_000_000,
    )
    await old.import_source("old-path.txt", "1" * 32)
    latest = await new.import_source("new-path.txt", "2" * 32)

    receipt = await build_receipt(
        disposable_mysql.session, source_hash=sha256(raw).hexdigest()
    )

    assert receipt["relativePath"] == "new-path.txt"
    assert receipt["parserVersion"] == PARSER_VERSION + "-next"
    assert latest["corpus_source_id"].startswith("20000000-")
