from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import importlib
from itertools import count
import json
import os

import pytest

from backend.domain.corpus import (
    FRAGMENTER_VERSION,
    INDEX_VERSION,
    NORMALIZER_VERSION,
    PARSER_VERSION,
)
from backend.http_errors import CorpusImportConflict, CorpusImportFailed
from backend.http_errors import (
    CorpusLifecycleConflict,
    CorpusPermanentDeleteForbidden,
)
from backend.repositories.corpus import CorpusRepository
from backend.security.paths import managed_corpus_blob_path
from backend.repositories.contracts import ContractRepository
from backend.scripts.verify_corpus_import import build_receipt
from backend.services.corpus_import import CorpusImportService
from backend.services.corpus_import import _hash_document
from backend.services.corpus_library import CorpusLibraryService
from backend.services.contracts import ConfirmContracts, ContractService, SaveContractDraft
from backend.tests.integration.test_contract_drafts import (
    PROJECT,
    SOURCE,
    _bootstrap as bootstrap_contract,
    _draft as contract_draft,
)
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
    managed_root = root / ".managed-corpus"
    managed_root.mkdir(exist_ok=True)
    return CorpusImportService(
        repository or CorpusRepository(), corpus_root=root,
        managed_root=managed_root,
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
    assert await _counts(disposable_mysql.session) == {
        "corpus_sources": 1, "corpus_chapters": 2,
        "corpus_fragments": 2, "corpus_import_runs": 2,
    }
    listed = await service.list_sources()
    detail = await service.get_source(first["corpus_source_id"], 120)
    assert len(listed) == 1
    assert listed[0]["revision"] == detail["revision"] == 1
    assert listed[0]["source_hash"] == detail["source_hash"] == sha256(
        (root / "book.txt").read_bytes()
    ).hexdigest()
    stored = await disposable_mysql.session.fetchall(
        "SELECT relative_path FROM corpus_source_revisions UNION ALL "
        "SELECT relative_path FROM corpus_import_runs"
    )
    assert {row["relative_path"] for row in stored} == {"book.txt"}
    assert str(root) not in repr(stored)


async def test_identical_bytes_default_to_one_source_and_explicit_distinct_choice_shares_blob(
    disposable_mysql, tmp_path,
):
    raw = "第一章\n同一份内容可以属于两个独立逻辑来源。".encode("utf-8")
    (tmp_path / "source-a.txt").write_bytes(raw)
    (tmp_path / "source-b.txt").write_bytes(raw)
    service = _service(disposable_mysql, tmp_path)

    first = await service.import_source("source-a.txt", "a" * 32)
    second = await service.import_source("source-b.txt", "b" * 32)
    distinct = await service.import_source(
        "source-b.txt",
        "c" * 32,
        create_distinct_source=True,
        display_name="显式独立来源",
    )

    assert second["corpus_source_id"] == first["corpus_source_id"]
    assert second["source_revision_id"] == first["source_revision_id"]
    assert distinct["corpus_source_id"] != first["corpus_source_id"]
    counts = {}
    for table_name in (
        "corpus_blobs",
        "corpus_sources",
        "corpus_source_revisions",
        "corpus_source_heads",
    ):
        row = await disposable_mysql.session.fetchone(
            f"SELECT COUNT(*) AS count FROM {table_name}"
        )
        counts[table_name] = row["count"]
    assert counts == {
        "corpus_blobs": 1,
        "corpus_sources": 2,
        "corpus_source_revisions": 2,
        "corpus_source_heads": 2,
    }
    rows = await disposable_mysql.session.fetchall(
        """SELECT revision.source_id,revision.content_hash,head.revision_id
             FROM corpus_source_revisions revision
             JOIN corpus_source_heads head
               ON head.source_id=revision.source_id
              AND head.revision_id=revision.id
            ORDER BY revision.source_id"""
    )
    assert len(rows) == 2
    assert {row["content_hash"] for row in rows} == {sha256(raw).hexdigest()}


async def test_changed_bytes_and_search_metadata_create_immutable_revision_without_changing_blob_identity_rules(
    disposable_mysql, tmp_path,
):
    source = tmp_path / "book.txt"
    source.write_text("第一章\n旧内容。", encoding="utf-8")
    service = _service(disposable_mysql, tmp_path)
    first = await service.import_source(
        "book.txt",
        "m" * 32,
        display_name="  北境\u3000卷  ",
        reference_tags=(" 玄幻 ", "战争", "玄幻"),
        notes="  第一行\r\n第二行  ",
    )

    source.write_text("第一章\n新内容。", encoding="utf-8")
    second = await service.import_source(
        "book.txt",
        "n" * 32,
        source_id=first["corpus_source_id"],
        display_name="北境 卷",
        reference_tags=("玄幻", "战争"),
        notes="第一行\n第二行",
    )

    assert second["corpus_source_id"] == first["corpus_source_id"]
    rows = await disposable_mysql.session.fetchall(
        """SELECT revision,content_hash,display_name,reference_tags_json,notes
             FROM corpus_source_revisions
            WHERE source_id=%s ORDER BY revision""",
        (first["corpus_source_id"],),
    )
    assert [row["revision"] for row in rows] == [1, 2]
    assert rows[0]["content_hash"] != rows[1]["content_hash"]
    assert {row["display_name"] for row in rows} == {"北境 卷"}
    assert all(json.loads(row["reference_tags_json"]) == ["玄幻", "战争"] for row in rows)
    assert all(row["notes"] == "第一行\n第二行" for row in rows)
    head = await disposable_mysql.session.fetchone(
        "SELECT revision,content_hash FROM corpus_source_heads WHERE source_id=%s",
        (first["corpus_source_id"],),
    )
    assert head == {
        "revision": 2,
        "content_hash": rows[1]["content_hash"],
    }
    blob_count = await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM corpus_blobs"
    )
    assert blob_count["count"] == 2


async def test_metadata_only_changes_create_immutable_revisions_on_the_same_blob(
    disposable_mysql, tmp_path,
):
    (tmp_path / "book.txt").write_text(
        "第一章\n相同正文。", encoding="utf-8"
    )
    service = _service(disposable_mysql, tmp_path)
    first = await service.import_source(
        "book.txt", "p" * 32, display_name="初版", notes="第一条编目"
    )
    second = await service.import_source(
        "book.txt",
        "q" * 32,
        source_id=first["corpus_source_id"],
        display_name="修订编目",
        reference_tags=("节奏",),
        notes="第二条编目",
    )
    third = await service.import_source(
        "book.txt",
        "r" * 32,
        display_name="默认复用后的编目",
        notes="第三条编目",
    )

    assert second["corpus_source_id"] == first["corpus_source_id"]
    assert third["corpus_source_id"] == first["corpus_source_id"]
    assert second["source_revision"] == 2
    assert third["source_revision"] == 3
    rows = await disposable_mysql.session.fetchall(
        """SELECT revision,content_hash,display_name,reference_tags_json,notes
             FROM corpus_source_revisions WHERE source_id=%s
             ORDER BY revision""",
        (first["corpus_source_id"],),
    )
    assert [row["display_name"] for row in rows] == [
        "初版", "修订编目", "默认复用后的编目",
    ]
    assert len({row["content_hash"] for row in rows}) == 1
    assert json.loads(rows[1]["reference_tags_json"]) == ["节奏"]
    assert rows[1]["notes"] == "第二条编目"
    assert (
        await disposable_mysql.session.fetchone(
            "SELECT COUNT(*) AS count FROM corpus_blobs"
        )
    )["count"] == 1


async def test_explicit_source_reimport_of_older_content_creates_new_head_revision(
    disposable_mysql, tmp_path,
):
    source = tmp_path / "cycle.txt"
    raw_a = "第一章\n版本 A。".encode()
    raw_b = "第一章\n版本 B。".encode()
    source.write_bytes(raw_a)
    importer = _service(disposable_mysql, tmp_path)
    first = await importer.import_source("cycle.txt", "a1" * 16)
    source.write_bytes(raw_b)
    second = await importer.import_source(
        "cycle.txt",
        "b2" * 16,
        source_id=first["corpus_source_id"],
    )
    source.write_bytes(raw_a)
    third = await importer.import_source(
        "cycle.txt",
        "c3" * 16,
        source_id=first["corpus_source_id"],
    )

    revisions = await disposable_mysql.session.fetchall(
        """SELECT revision,content_hash
             FROM corpus_source_revisions
            WHERE source_id=%s ORDER BY revision""",
        (first["corpus_source_id"],),
    )
    head = await disposable_mysql.session.fetchone(
        """SELECT revision,content_hash FROM corpus_source_heads
            WHERE source_id=%s""",
        (first["corpus_source_id"],),
    )
    blobs = await disposable_mysql.session.fetchone(
        "SELECT COUNT(*) AS count FROM corpus_blobs"
    )

    assert second["source_revision"] == 2
    assert third["source_revision"] == 3
    assert [row["revision"] for row in revisions] == [1, 2, 3]
    assert [row["content_hash"] for row in revisions] == [
        sha256(raw_a).hexdigest(),
        sha256(raw_b).hexdigest(),
        sha256(raw_a).hexdigest(),
    ]
    assert head == {
        "revision": 3,
        "content_hash": sha256(raw_a).hexdigest(),
    }
    assert blobs == {"count": 2}


async def test_changed_bytes_without_source_id_create_a_new_logical_source_even_for_same_label(
    disposable_mysql, tmp_path,
):
    source = tmp_path / "book.txt"
    source.write_text("第一章\n旧正文。", encoding="utf-8")
    service = _service(disposable_mysql, tmp_path)
    first = await service.import_source("book.txt", "v" * 32)
    source.write_text("第一章\n新正文。", encoding="utf-8")
    second = await service.import_source("book.txt", "w" * 32)

    assert second["corpus_source_id"] != first["corpus_source_id"]
    assert second["source_revision"] == 1
    assert (
        await disposable_mysql.session.fetchone(
            "SELECT COUNT(*) AS count FROM corpus_sources"
        )
    )["count"] == 2


async def test_import_never_uses_a_source_label_to_restore_an_archived_source(
    disposable_mysql, tmp_path,
):
    source = tmp_path / "book.txt"
    source.write_text("第一章\n旧正文。", encoding="utf-8")
    importer = _service(disposable_mysql, tmp_path)
    first = await importer.import_source("book.txt", "x" * 32)
    factory = transaction_factory_for(disposable_mysql.connection_config)
    library = CorpusLibraryService(
        CorpusRepository(),
        managed_root=tmp_path / ".managed-corpus",
        transaction_factory=factory,
        connection_factory=factory,
        clock=_clock(1_900_000_020_000),
    )
    await library.archive(first["corpus_source_id"], 1)
    source.write_text("第一章\n新正文。", encoding="utf-8")

    with pytest.raises(CorpusLifecycleConflict):
        await importer.import_source(
            "book.txt",
            "y" * 32,
            source_id=first["corpus_source_id"],
        )
    replacement = await importer.import_source("book.txt", "z" * 32)
    assert replacement["corpus_source_id"] != first["corpus_source_id"]
    archived = await disposable_mysql.session.fetchone(
        "SELECT archived_at FROM corpus_sources WHERE id=%s",
        (first["corpus_source_id"],),
    )
    assert archived["archived_at"] is not None


async def test_imported_reads_survive_original_file_move_or_delete(
    disposable_mysql, tmp_path,
):
    source = tmp_path / "book.txt"
    raw = ("第一章\n" + "托管内容。" * 200).encode("utf-8")
    source.write_bytes(raw)
    service = _service(disposable_mysql, tmp_path)
    imported = await service.import_source("book.txt", "g" * 32)
    source.unlink()

    detail = await service.get_source(imported["corpus_source_id"], 1200)
    chapters = await service.list_chapters(imported["corpus_source_id"])
    fragments = await service.list_fragments(chapters[0]["id"], 0, 20)
    managed = (
        tmp_path
        / ".managed-corpus"
        / "sha256"
        / sha256(raw).hexdigest()[:2]
        / sha256(raw).hexdigest()
    )

    assert managed.read_bytes() == raw
    assert detail["preview"].startswith("第一章")
    assert fragments["items"][0]["normalized_text"].startswith("第一章")


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

    assert second["corpus_source_id"] == first["corpus_source_id"]
    rows = await disposable_mysql.session.fetchall(
        "SELECT revision,content_hash AS source_hash,parser_version,"
        "normalizer_version,fragmenter_version,index_version "
        "FROM corpus_source_revisions "
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
    assert after == before
    source_rows = await disposable_mysql.session.fetchone(
        """SELECT
             (SELECT COUNT(*) FROM corpus_source_revisions) AS revisions,
             (SELECT COUNT(*) FROM corpus_source_heads) AS heads"""
    )
    assert source_rows == {"revisions": 0, "heads": 0}
    finalized = tuple(
        (tmp_path / ".managed-corpus" / "sha256").rglob(
            sha256((tmp_path / "broken-publication.txt").read_bytes()).hexdigest()
        )
    )
    assert len(finalized) == 1
    assert finalized[0].read_bytes() == (
        tmp_path / "broken-publication.txt"
    ).read_bytes()

    recovered = _service(disposable_mysql, tmp_path)
    result = await recovered.import_source("broken-publication.txt", "r" * 32)
    assert result["status"] == "succeeded"
    assert len(tuple((tmp_path / ".managed-corpus" / "sha256").rglob(
        sha256((tmp_path / "broken-publication.txt").read_bytes()).hexdigest()
    ))) == 1


async def test_decode_failure_is_marked_in_separate_short_transaction(
    disposable_mysql, tmp_path
):
    (tmp_path / "invalid.txt").write_bytes(b"\x00binary")
    service = _service(disposable_mysql, tmp_path)

    with pytest.raises(CorpusImportFailed):
        await service.import_source("invalid.txt", "d" * 32)

    rows = await disposable_mysql.session.fetchone(
        """SELECT
             (SELECT COUNT(*) FROM corpus_sources) AS sources,
             (SELECT COUNT(*) FROM corpus_source_revisions) AS revisions,
             (SELECT COUNT(*) FROM corpus_source_heads) AS heads"""
    )
    assert rows == {"sources": 0, "revisions": 0, "heads": 0}
    staging = tmp_path / ".managed-corpus" / ".staging"
    assert not staging.exists() or not tuple(staging.iterdir())


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
        "sourceId": None,
        "createDistinctSource": False,
        "displayName": "recover",
        "referenceTags": (),
        "notes": "",
        "metadataExplicit": False,
    })
    run_id = f"9000000{0 if persisted_status == 'reserved' else 1}-0000-0000-0000-000000000000"
    await disposable_mysql.session.execute(
        """INSERT INTO corpus_blobs
           (content_hash,byte_length,storage_key,created_at)
           VALUES (%s,%s,%s,%s)""",
        (
            source_hash,
            len(raw),
            f"sha256/{source_hash[:2]}/{source_hash}",
            1_720_000_000_000,
        ),
    )
    await disposable_mysql.session.execute(
        """INSERT INTO corpus_import_runs
           (id,idempotency_key,request_hash,relative_path,content_hash,status,
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

    managed_root = tmp_path / ".managed-corpus"
    managed_root.mkdir()
    service = CorpusImportService(
        CorpusRepository(), corpus_root=tmp_path, managed_root=managed_root,
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
        "10000000-0000-0000-0000-000000000004",
    ))
    new_ids = iter((
        "20000000-0000-0000-0000-000000000001",
        "20000000-0000-0000-0000-000000000002",
        "20000000-0000-0000-0000-000000000003",
        "20000000-0000-0000-0000-000000000004",
    ))
    managed_root = tmp_path / ".managed-corpus"
    managed_root.mkdir()
    old = CorpusImportService(
        CorpusRepository(), corpus_root=tmp_path, managed_root=managed_root,
        transaction_factory=factory, connection_factory=factory,
        id_factory=lambda: next(old_ids), clock=lambda: 1_720_000_000_000,
    )
    new = CorpusImportService(
        CorpusRepository(), corpus_root=tmp_path, managed_root=managed_root,
        transaction_factory=factory, connection_factory=factory,
        parser_version=PARSER_VERSION + "-next",
        id_factory=lambda: next(new_ids), clock=lambda: 1_720_000_000_000,
    )
    first = await old.import_source("old-path.txt", "1" * 32)
    latest = await new.import_source("new-path.txt", "2" * 32)

    receipt = await build_receipt(
        disposable_mysql.session, source_hash=sha256(raw).hexdigest()
    )

    assert receipt["relativePath"] == "new-path.txt"
    assert receipt["parserVersion"] == PARSER_VERSION + "-next"
    assert latest["corpus_source_id"] == first["corpus_source_id"]


async def test_real_lifecycle_is_cas_idempotent_reference_protected_and_deletes_only_archived_unreferenced_source(
    disposable_mysql, tmp_path,
):
    factory = transaction_factory_for(disposable_mysql.connection_config)
    facts = await bootstrap_contract(disposable_mysql.session)
    ids = iter(
        f"95000000-0000-0000-0000-{number:012d}" for number in range(1, 100)
    )
    contract_service = ContractService(
        ContractRepository(),
        transaction_factory=factory,
        connection_factory=factory,
        id_factory=lambda: next(ids),
        clock=lambda: 1_900_000_001_000,
    )
    saved = await contract_service.save_draft(
        SaveContractDraft(PROJECT, 0, contract_draft(facts))
    )
    await contract_service.confirm(
        ConfirmContracts(
            PROJECT, "corpus-reference-confirm", saved.draft_version,
            saved.content_hash,
        )
    )
    managed_root = tmp_path / ".managed-corpus"
    managed_root.mkdir()
    library = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=factory,
        connection_factory=factory,
        clock=lambda: 1_900_000_002_000,
    )

    archived = await library.archive(SOURCE, expected_revision=1)
    archive_replay = await library.archive(SOURCE, expected_revision=1)
    versions = await library.list_versions(SOURCE, cursor=None, limit=50)
    assert archived["archived_at"] == archive_replay["archived_at"]
    assert sum(
        row["reference_count"] for row in versions["items"]
    ) >= 1
    with pytest.raises(
        importlib.import_module(
            "backend.http_errors"
        ).CorpusPermanentDeleteForbidden
    ):
        await library.permanently_delete(
            SOURCE,
            expected_revision=1,
            confirm_permanent_delete=True,
        )
    await library.restore(SOURCE, expected_revision=1)
    await library.restore(SOURCE, expected_revision=1)

    (tmp_path / "unreferenced.txt").write_text(
        "第一章\n可安全删除的合成语料。", encoding="utf-8"
    )
    imported = await _service(disposable_mysql, tmp_path).import_source(
        "unreferenced.txt", "u" * 32
    )
    unreferenced_id = imported["corpus_source_id"]
    await library.archive(unreferenced_id, expected_revision=1)
    await library.permanently_delete(
        unreferenced_id,
        expected_revision=1,
        confirm_permanent_delete=True,
    )
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM corpus_sources WHERE id=%s", (unreferenced_id,)
    ) is None
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM corpus_sources WHERE id=%s", (SOURCE,)
    ) == {"id": SOURCE}


async def test_permanent_delete_removes_only_the_last_shared_blob_reference(
    disposable_mysql, tmp_path,
):
    raw = "第一章\n共享 blob 的两个逻辑来源。".encode()
    (tmp_path / "a.txt").write_bytes(raw)
    (tmp_path / "b.txt").write_bytes(raw)
    importer = _service(disposable_mysql, tmp_path)
    first = await importer.import_source("a.txt", "7" * 32)
    second = await importer.import_source(
        "b.txt",
        "8" * 32,
        create_distinct_source=True,
        display_name="独立来源",
    )
    content_hash = sha256(raw).hexdigest()
    managed_root = tmp_path / ".managed-corpus"
    blob_path = managed_corpus_blob_path(managed_root, content_hash)
    assert blob_path.read_bytes() == raw
    factory = transaction_factory_for(disposable_mysql.connection_config)
    library = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=factory,
        connection_factory=factory,
        clock=_clock(1_900_000_010_000),
    )

    await library.archive(first["corpus_source_id"], 1)
    await library.permanently_delete(
        first["corpus_source_id"], 1, True
    )
    assert blob_path.read_bytes() == raw
    assert await disposable_mysql.session.fetchone(
        "SELECT content_hash FROM corpus_blobs WHERE content_hash=%s",
        (content_hash,),
    ) == {"content_hash": content_hash}

    await library.archive(second["corpus_source_id"], 1)
    await library.permanently_delete(
        second["corpus_source_id"], 1, True
    )
    assert not blob_path.exists()
    assert await disposable_mysql.session.fetchone(
        "SELECT content_hash FROM corpus_blobs WHERE content_hash=%s",
        (content_hash,),
    ) is None
    assert not (managed_root / ".deleting").exists()


async def test_import_publish_and_permanent_delete_share_cross_worker_guard(
    disposable_mysql, tmp_path,
):
    raw = "第一章\n发布和永久删除必须跨 worker 串行。".encode()
    (tmp_path / "old.txt").write_bytes(raw)
    (tmp_path / "new.txt").write_bytes(raw)
    initial = _service(disposable_mysql, tmp_path)
    old = await initial.import_source("old.txt", "g" * 32)
    factory = transaction_factory_for(disposable_mysql.connection_config)
    managed_root = tmp_path / ".managed-corpus"
    library = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=factory,
        connection_factory=factory,
        clock=_clock(1_900_000_020_000),
    )
    await library.archive(old["corpus_source_id"], 1)

    guard_entered = asyncio.Event()
    release_import = asyncio.Event()

    class PausingRepository(CorpusRepository):
        async def lock_schema_guard(self, session):
            await super().lock_schema_guard(session)
            guard_entered.set()
            await release_import.wait()

    importer = _service(
        disposable_mysql, tmp_path, repository=PausingRepository()
    )
    import_task = asyncio.create_task(
        importer.import_source("new.txt", "h" * 32)
    )
    await asyncio.wait_for(guard_entered.wait(), timeout=2)
    delete_task = asyncio.create_task(
        library.permanently_delete(old["corpus_source_id"], 1, True)
    )
    try:
        done, _ = await asyncio.wait({delete_task}, timeout=0.15)
        assert not done, "delete bypassed the database publication guard"
    finally:
        release_import.set()
    imported, _ = await asyncio.gather(import_task, delete_task)

    content_hash = sha256(raw).hexdigest()
    assert managed_corpus_blob_path(managed_root, content_hash).read_bytes() == raw
    assert await disposable_mysql.session.fetchone(
        "SELECT content_hash FROM corpus_blobs WHERE content_hash=%s",
        (content_hash,),
    ) == {"content_hash": content_hash}
    assert await disposable_mysql.session.fetchone(
            """SELECT revision.id
                 FROM corpus_source_revisions revision
                 JOIN corpus_blobs managed_blob
                   ON managed_blob.content_hash=revision.content_hash
                WHERE revision.source_id=%s""",
        (imported["corpus_source_id"],),
    ) is not None


async def test_committed_delete_cleanup_is_persisted_and_replayed(
    disposable_mysql, tmp_path, monkeypatch,
):
    raw = "第一章\n提交后的清理失败可以安全重放。".encode()
    (tmp_path / "cleanup.txt").write_bytes(raw)
    imported = await _service(disposable_mysql, tmp_path).import_source(
        "cleanup.txt", "i" * 32
    )
    factory = transaction_factory_for(disposable_mysql.connection_config)
    managed_root = tmp_path / ".managed-corpus"
    library = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=factory,
        connection_factory=factory,
        clock=_clock(1_900_000_030_000),
    )
    await library.archive(imported["corpus_source_id"], 1)
    original_finish = library._finish_blob_deletions
    attempts = 0

    def fail_once(moves):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("synthetic cleanup failure")
        return original_finish(moves)

    monkeypatch.setattr(library, "_finish_blob_deletions", fail_once)
    first = await library.permanently_delete(
        imported["corpus_source_id"], 1, True
    )
    pending = await disposable_mysql.session.fetchone(
        """SELECT status FROM corpus_source_deletions
            WHERE source_id=%s""",
        (imported["corpus_source_id"],),
    )
    recovered = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=factory,
        connection_factory=factory,
        clock=_clock(1_900_000_031_000),
    )
    visible = await recovered.list_sources(state="all")
    succeeded = await disposable_mysql.session.fetchone(
        """SELECT status FROM corpus_source_deletions
            WHERE source_id=%s""",
        (imported["corpus_source_id"],),
    )

    assert first == {"cleanup_pending": True}
    assert pending == {"status": "cleanup_pending"}
    assert all(
        row["id"] != imported["corpus_source_id"] for row in visible
    )
    assert succeeded == {"status": "succeeded"}
    assert not (managed_root / ".deleting").exists()


async def test_rollback_restore_failure_is_persisted_and_danger_retry_repairs_it(
    disposable_mysql, tmp_path, monkeypatch,
):
    raw = "第一章\n回滚恢复失败也保留可重放状态。".encode()
    (tmp_path / "restore.txt").write_bytes(raw)
    imported = await _service(disposable_mysql, tmp_path).import_source(
        "restore.txt", "j" * 32
    )
    real_factory = transaction_factory_for(
        disposable_mysql.connection_config
    )
    transaction_count = 0

    @asynccontextmanager
    async def fail_first_commit():
        nonlocal transaction_count
        transaction_count += 1
        current = transaction_count
        async with real_factory() as session:
            yield session
            if current == 2:
                raise RuntimeError("synthetic commit failure")

    managed_root = tmp_path / ".managed-corpus"
    library = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=real_factory,
        connection_factory=real_factory,
        clock=_clock(1_900_000_040_000),
    )
    await library.archive(imported["corpus_source_id"], 1)
    library.transaction_factory = fail_first_commit
    original_restore = library._restore_blob_deletions
    attempts = 0

    def fail_once(moves):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise OSError("synthetic restore failure")
        return original_restore(moves)

    monkeypatch.setattr(library, "_restore_blob_deletions", fail_once)
    with pytest.raises(CorpusLifecycleConflict):
        await library.permanently_delete(
            imported["corpus_source_id"], 1, True
        )
    pending = await disposable_mysql.session.fetchone(
        """SELECT status FROM corpus_source_deletions
            WHERE source_id=%s""",
        (imported["corpus_source_id"],),
    )
    source = await disposable_mysql.session.fetchone(
        "SELECT id FROM corpus_sources WHERE id=%s",
        (imported["corpus_source_id"],),
    )
    replay = await library.permanently_delete(
        imported["corpus_source_id"], 1, True
    )

    assert pending == {"status": "restore_pending"}
    assert source == {"id": imported["corpus_source_id"]}
    assert replay == {"cleanup_pending": False}
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM corpus_sources WHERE id=%s",
        (imported["corpus_source_id"],),
    ) is None
    assert not (managed_root / ".deleting").exists()


async def test_partial_multi_blob_staging_restore_failure_is_replayable(
    disposable_mysql, tmp_path, monkeypatch,
):
    source_path = tmp_path / "multi.txt"
    source_path.write_text("第一章\n第一版。", encoding="utf-8")
    importer = _service(disposable_mysql, tmp_path)
    first = await importer.import_source("multi.txt", "k" * 32)
    source_path.write_text("第一章\n第二版。", encoding="utf-8")
    await importer.import_source(
        "multi.txt",
        "l" * 32,
        source_id=first["corpus_source_id"],
    )
    factory = transaction_factory_for(disposable_mysql.connection_config)
    managed_root = tmp_path / ".managed-corpus"
    library = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=factory,
        connection_factory=factory,
        clock=_clock(1_900_000_050_000),
    )
    await library.archive(first["corpus_source_id"], 2)

    original_replace = os.replace
    attempts = 0

    def fail_second_stage_and_first_restore(source, target):
        nonlocal attempts
        attempts += 1
        if attempts in (2, 3):
            raise OSError("synthetic partial staging/restore failure")
        return original_replace(source, target)

    monkeypatch.setattr(
        importlib.import_module("backend.services.corpus_library").os,
        "replace",
        fail_second_stage_and_first_restore,
    )
    with pytest.raises(CorpusLifecycleConflict):
        await library.permanently_delete(
            first["corpus_source_id"], 2, True
        )
    pending = await disposable_mysql.session.fetchone(
        """SELECT status,tombstones_json
             FROM corpus_source_deletions WHERE source_id=%s""",
        (first["corpus_source_id"],),
    )
    source = await disposable_mysql.session.fetchone(
        "SELECT id FROM corpus_sources WHERE id=%s",
        (first["corpus_source_id"],),
    )

    assert pending["status"] == "restore_pending"
    assert len(json.loads(pending["tombstones_json"])) == 2
    assert source == {"id": first["corpus_source_id"]}

    replay = await library.permanently_delete(
        first["corpus_source_id"], 2, True
    )
    completed = await disposable_mysql.session.fetchone(
        """SELECT status,tombstones_json
             FROM corpus_source_deletions WHERE source_id=%s""",
        (first["corpus_source_id"],),
    )
    assert replay == {"cleanup_pending": False}
    completed_tombstones = json.loads(completed["tombstones_json"])
    assert completed["status"] == "succeeded"
    assert len(completed_tombstones) == 2
    assert len({
        item["tombstoneName"] for item in completed_tombstones
    }) == 2
    assert await disposable_mysql.session.fetchone(
        "SELECT id FROM corpus_sources WHERE id=%s",
        (first["corpus_source_id"],),
    ) is None
    assert not (managed_root / ".deleting").exists()


async def test_hard_stop_after_partial_move_recovers_from_durable_intent_on_refresh(
    disposable_mysql, tmp_path, monkeypatch,
):
    source_path = tmp_path / "hard-stop.txt"
    source_path.write_text("第一章\n硬终止前版本。", encoding="utf-8")
    importer = _service(disposable_mysql, tmp_path)
    first = await importer.import_source("hard-stop.txt", "d4" * 16)
    source_path.write_text("第一章\n硬终止后版本。", encoding="utf-8")
    await importer.import_source(
        "hard-stop.txt",
        "e5" * 16,
        source_id=first["corpus_source_id"],
    )
    factory = transaction_factory_for(disposable_mysql.connection_config)
    managed_root = tmp_path / ".managed-corpus"
    library = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=factory,
        connection_factory=factory,
        clock=_clock(1_900_000_060_000),
    )
    await library.archive(first["corpus_source_id"], 2)
    original_replace = os.replace
    attempts = 0

    def stop_after_first_move(source, target):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise SystemExit("synthetic hard stop")
        return original_replace(source, target)

    monkeypatch.setattr(
        importlib.import_module("backend.services.corpus_library").os,
        "replace",
        stop_after_first_move,
    )
    with pytest.raises(SystemExit, match="synthetic hard stop"):
        await library.permanently_delete(
            first["corpus_source_id"], 2, True
        )
    pending = await disposable_mysql.session.fetchone(
        """SELECT status,tombstones_json
             FROM corpus_source_deletions WHERE source_id=%s""",
        (first["corpus_source_id"],),
    )
    source = await disposable_mysql.session.fetchone(
        "SELECT id FROM corpus_sources WHERE id=%s",
        (first["corpus_source_id"],),
    )

    assert pending["status"] == "restore_pending"
    assert len(json.loads(pending["tombstones_json"])) == 2
    assert source == {"id": first["corpus_source_id"]}

    recovered = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=factory,
        connection_factory=factory,
        clock=_clock(1_900_000_061_000),
    )
    visible = await recovered.list_sources(state="all")
    completed = await disposable_mysql.session.fetchone(
        """SELECT status FROM corpus_source_deletions
            WHERE source_id=%s""",
        (first["corpus_source_id"],),
    )
    assert all(row["id"] != first["corpus_source_id"] for row in visible)
    assert completed == {"status": "succeeded"}
    assert not (managed_root / ".deleting").exists()


async def test_prepared_delete_is_cancelled_when_source_eligibility_drifts(
    disposable_mysql, tmp_path,
):
    (tmp_path / "drift.txt").write_text(
        "第一章\n删除准备后资格发生变化。", encoding="utf-8"
    )
    imported = await _service(disposable_mysql, tmp_path).import_source(
        "drift.txt", "f6" * 16
    )
    factory = transaction_factory_for(disposable_mysql.connection_config)
    managed_root = tmp_path / ".managed-corpus"
    library = CorpusLibraryService(
        CorpusRepository(),
        managed_root=managed_root,
        transaction_factory=factory,
        connection_factory=factory,
        clock=_clock(1_900_000_070_000),
    )
    source_id = imported["corpus_source_id"]
    await library.archive(source_id, 1)
    await library._prepare_deletion(source_id, 1)
    await disposable_mysql.session.execute(
        """UPDATE corpus_sources SET archived_at=NULL
            WHERE id=%s""",
        (source_id,),
    )

    with pytest.raises(CorpusPermanentDeleteForbidden):
        await library.permanently_delete(source_id, 1, True)

    assert await disposable_mysql.session.fetchone(
        """SELECT status FROM corpus_source_deletions
            WHERE source_id=%s""",
        (source_id,),
    ) is None
    visible = await library.list_sources(state="all")
    assert [row["id"] for row in visible] == [source_id]
