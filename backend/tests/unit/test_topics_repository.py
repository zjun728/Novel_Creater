from __future__ import annotations

import pytest

from backend.domain.topics import TopicEvidenceRef, TopicFailure


class ScriptedSession:
    def __init__(self, *, rows=(), batches=(), changes=()):
        self.rows = list(rows)
        self.batches = list(batches)
        self.changes = list(changes)
        self.calls: list[tuple[str, str, tuple[object, ...] | None]] = []

    async def fetchone(self, sql, args=None):
        self.calls.append(("fetchone", sql, args))
        if not self.rows:
            raise AssertionError("unexpected fetchone call")
        return self.rows.pop(0)

    async def fetchall(self, sql, args=None):
        self.calls.append(("fetchall", sql, args))
        if not self.batches:
            raise AssertionError("unexpected fetchall call")
        return self.batches.pop(0)

    async def execute(self, sql, args=None):
        self.calls.append(("execute", sql, args))
        return self.changes.pop(0) if self.changes else 1


def _compact(sql: str) -> str:
    return " ".join(sql.lower().split())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "expected_table", "kwargs"),
    (
        ("list_discussions", "topic_discussions", {}),
        ("list_directions", "topic_directions", {}),
        ("list_candidates", "topic_candidates", {"status": "archived"}),
    ),
)
async def test_recent_lists_are_bounded_and_deterministic(
    method,
    expected_table,
    kwargs,
):
    from backend.repositories.topics import TopicRepository

    session = ScriptedSession(batches=([],))
    result = await getattr(TopicRepository(), method)(
        session,
        offset=-4,
        limit=999,
        **kwargs,
    )

    assert result == ()
    _, sql, args = session.calls[0]
    compact = _compact(sql)
    assert f"from {expected_table}" in compact
    assert "order by" in compact
    assert "updated_at desc" in compact
    assert "id desc" in compact
    assert "limit %s offset %s" in compact
    assert args[-2:] == (100, 0)


@pytest.mark.asyncio
async def test_discussion_detail_orders_immutable_messages_and_decodes_requests():
    from backend.repositories.topics import TopicRepository

    session = ScriptedSession(
        rows=(
            {
                "id": "discussion-1",
                "title": "自由讨论",
                "status": "active",
                "created_at": 10,
                "updated_at": 30,
            },
        ),
        batches=(
            [
                {
                    "id": "message-1",
                    "discussion_id": "discussion-1",
                    "sequence_number": 1,
                    "role": "user",
                    "content_text": "我想写地方治理。",
                    "content_hash": "a" * 64,
                    "created_at": 10,
                }
            ],
            [
                {
                    "id": "request-1",
                    "discussion_id": "discussion-1",
                    "status": "succeeded",
                    "input_manifest_json": '{"evidence":[]}',
                    "result_json": '{"reply":"可以。"}',
                }
            ],
        ),
    )

    result = await TopicRepository().read_discussion(session, "discussion-1")

    assert result["discussion"]["id"] == "discussion-1"
    assert result["messages"][0]["content_text"] == "我想写地方治理。"
    assert result["requests"][0]["input_manifest"] == {"evidence": []}
    assert result["requests"][0]["result"] == {"reply": "可以。"}
    assert "order by sequence_number asc" in _compact(session.calls[1][1])
    assert "order by created_at asc,id asc" in _compact(session.calls[2][1])
    assert all("for update" not in _compact(call[1]) for call in session.calls)


@pytest.mark.asyncio
async def test_assistant_message_locks_its_succeeded_request_manifest():
    from backend.repositories.topics import TopicRepository

    session = ScriptedSession(rows=({
        "id": "request-1",
        "input_manifest_json": '{"evidence":[{"snapshotId":"snapshot-1","contentHash":"' + "a" * 64 + '"}]}',
    },))

    result = await TopicRepository().lock_succeeded_request_by_assistant_message(
        session,
        discussion_id="discussion-1",
        message_id="message-2",
    )

    assert result["input_manifest"]["evidence"][0]["snapshotId"] == "snapshot-1"
    _, sql, args = session.calls[0]
    assert "status='succeeded'" in _compact(sql)
    assert "assistant_message_id=%s" in _compact(sql)
    assert "for update" in _compact(sql)
    assert args == ("discussion-1", "message-2")


@pytest.mark.asyncio
async def test_json_decode_is_fail_closed():
    from backend.repositories.topics import TopicRepository

    session = ScriptedSession(
        rows=(
            {
                "id": "candidate-1",
                "status": "active",
                "current_version": 1,
                "created_at": 10,
                "updated_at": 10,
            },
        ),
        batches=(
            [
                {
                    "id": "version-1",
                    "candidate_id": "candidate-1",
                    "version": 1,
                    "payload_json": "[]",
                    "basis_json": "{}",
                }
            ],
        ),
    )

    with pytest.raises(ValueError, match="payload_json"):
        await TopicRepository().read_candidate(session, "candidate-1")


@pytest.mark.asyncio
async def test_candidate_detail_keeps_archived_history_newest_first():
    from backend.repositories.topics import TopicRepository

    session = ScriptedSession(
        rows=(
            {
                "id": "candidate-1",
                "status": "archived",
                "current_version": 2,
                "created_at": 10,
                "updated_at": 30,
            },
        ),
        batches=(
            [
                {
                    "id": "version-2",
                    "candidate_id": "candidate-1",
                    "version": 2,
                    "payload_json": '{"title":"典镇山河"}',
                    "basis_json": '{"messages":["message-2"]}',
                },
                {
                    "id": "version-1",
                    "candidate_id": "candidate-1",
                    "version": 1,
                    "payload_json": '{"title":"山河典吏"}',
                    "basis_json": '{"messages":["message-1"]}',
                },
            ],
        ),
    )

    result = await TopicRepository().read_candidate(session, "candidate-1")

    assert result["candidate"]["status"] == "archived"
    assert [item["version"] for item in result["versions"]] == [2, 1]
    assert result["versions"][0]["payload"] == {"title": "典镇山河"}
    assert "where candidate_id=%s" in _compact(session.calls[1][1])
    assert "order by version desc" in _compact(session.calls[1][1])


@pytest.mark.asyncio
async def test_lock_methods_are_the_only_reads_that_request_row_locks():
    from backend.repositories.topics import TopicRepository

    session = ScriptedSession(
        rows=(
            {"id": "discussion-1"},
            {"id": "direction-1", "current_version": 2},
            {"id": "candidate-1", "current_version": 3, "status": "active"},
            {"id": "version-3", "payload_json": "{}", "basis_json": "{}"},
        )
    )
    repository = TopicRepository()

    await repository.lock_discussion(session, "discussion-1")
    await repository.lock_direction(session, "direction-1")
    await repository.lock_candidate(session, "candidate-1")
    await repository.lock_candidate_version(
        session,
        candidate_id="candidate-1",
        version=3,
        content_hash="c" * 64,
    )

    assert all("for update" in _compact(call[1]) for call in session.calls)
    assert session.calls[-1][2] == ("candidate-1", 3, "c" * 64)


@pytest.mark.asyncio
async def test_snapshot_locks_preserve_caller_order_and_require_exact_hashes():
    from backend.repositories.topics import TopicRepository

    refs = (
        TopicEvidenceRef(snapshotId="snapshot-b", contentHash="b" * 64),
        TopicEvidenceRef(snapshotId="snapshot-a", contentHash="a" * 64),
    )
    session = ScriptedSession(
        batches=(
            [
                {
                    "id": "snapshot-a",
                    "source_id": "source-a",
                    "content_hash": "a" * 64,
                    "platform": "qidian",
                    "entry_count": 1,
                },
                {
                    "id": "snapshot-b",
                    "source_id": "source-b",
                    "content_hash": "b" * 64,
                    "platform": "fanqie",
                    "entry_count": 2,
                },
            ],
            [
                {
                    "source_id": "source-a",
                    "snapshot_id": "snapshot-a",
                    "rank_number": 1,
                    "title": "甲榜作品",
                    "author": "甲作者",
                    "category": "玄幻",
                    "public_metrics_json": '{"readers":123}',
                },
                {
                    "source_id": "source-b",
                    "snapshot_id": "snapshot-b",
                    "rank_number": 1,
                    "title": "乙榜作品一",
                    "author": "乙作者一",
                    "category": "都市",
                    "public_metrics_json": {"heat": 456},
                },
                {
                    "source_id": "source-b",
                    "snapshot_id": "snapshot-b",
                    "rank_number": 2,
                    "title": "乙榜作品二",
                    "author": "乙作者二",
                    "category": "悬疑",
                    "public_metrics_json": "{}",
                },
            ],
        )
    )

    result = await TopicRepository().lock_snapshot_evidence(session, refs)

    assert [item["id"] for item in result] == ["snapshot-b", "snapshot-a"]
    assert result[0]["entries"] == (
        {
            "rank": 1,
            "title": "乙榜作品一",
            "author": "乙作者一",
            "category": "都市",
            "public_metrics": {"heat": 456},
        },
        {
            "rank": 2,
            "title": "乙榜作品二",
            "author": "乙作者二",
            "category": "悬疑",
            "public_metrics": {},
        },
    )
    assert result[1]["entries"][0]["public_metrics"] == {"readers": 123}
    assert all("work_url" not in entry for item in result for entry in item["entries"])

    _, snapshots_sql, snapshots_args = session.calls[0]
    _, entries_sql, entries_args = session.calls[1]
    assert "for update" in _compact(snapshots_sql)
    assert snapshots_args == ("snapshot-a", "snapshot-b")
    assert "from market_snapshot_entries" in _compact(entries_sql)
    assert "order by snapshot_id asc,rank_number asc" in _compact(entries_sql)
    assert "limit %s for update" in _compact(entries_sql)
    assert "work_url" not in _compact(entries_sql)
    assert entries_args == ("snapshot-a", "snapshot-b", 201)

    mismatch = ScriptedSession(
        batches=([{"id": "snapshot-a", "content_hash": "f" * 64}],)
    )
    with pytest.raises(TopicFailure) as raised:
        await TopicRepository().lock_snapshot_evidence(mismatch, refs[1:])
    assert raised.value.code == "TOPIC_NOT_FOUND"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "entries",
    (
        (),
        (
            {
                "source_id": "wrong-source",
                "snapshot_id": "snapshot-a",
                "rank_number": 1,
                "title": "作品",
                "author": "作者",
                "category": "玄幻",
                "public_metrics_json": "{}",
            },
        ),
    ),
)
async def test_snapshot_locks_fail_closed_on_incomplete_or_cross_source_entries(
    entries,
):
    from backend.repositories.topics import TopicRepository

    ref = TopicEvidenceRef(snapshotId="snapshot-a", contentHash="a" * 64)
    session = ScriptedSession(
        batches=(
            [
                {
                    "id": "snapshot-a",
                    "source_id": "source-a",
                    "content_hash": "a" * 64,
                    "entry_count": 1,
                }
            ],
            list(entries),
        )
    )

    with pytest.raises(TopicFailure) as raised:
        await TopicRepository().lock_snapshot_evidence(session, (ref,))

    assert raised.value.code == "TOPIC_NOT_FOUND"


@pytest.mark.asyncio
async def test_snapshot_locks_require_public_metrics_to_decode_as_an_object():
    from backend.repositories.topics import TopicRepository

    ref = TopicEvidenceRef(snapshotId="snapshot-a", contentHash="a" * 64)
    session = ScriptedSession(
        batches=(
            [
                {
                    "id": "snapshot-a",
                    "source_id": "source-a",
                    "content_hash": "a" * 64,
                    "entry_count": 1,
                }
            ],
            [
                {
                    "source_id": "source-a",
                    "snapshot_id": "snapshot-a",
                    "rank_number": 1,
                    "title": "作品",
                    "author": "作者",
                    "category": "玄幻",
                    "public_metrics_json": "[]",
                }
            ],
        )
    )

    with pytest.raises(ValueError, match="public_metrics_json"):
        await TopicRepository().lock_snapshot_evidence(session, (ref,))


@pytest.mark.asyncio
async def test_snapshot_locks_reject_unbounded_evidence_before_querying():
    from backend.repositories.topics import TopicRepository

    refs = tuple(
        TopicEvidenceRef(
            snapshotId=f"snapshot-{index}",
            contentHash=f"{index}" * 64,
        )
        for index in range(5)
    )
    session = ScriptedSession()

    with pytest.raises(TopicFailure) as raised:
        await TopicRepository().lock_snapshot_evidence(session, refs)

    assert raised.value.code == "TOPIC_NOT_FOUND"
    assert session.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("second_hash", ("a" * 64, "b" * 64))
async def test_snapshot_locks_reject_duplicate_ids_before_querying(second_hash):
    from backend.repositories.topics import TopicRepository

    refs = (
        TopicEvidenceRef(snapshotId="snapshot-a", contentHash="a" * 64),
        TopicEvidenceRef(snapshotId="snapshot-a", contentHash=second_hash),
    )
    session = ScriptedSession()

    with pytest.raises(TopicFailure) as raised:
        await TopicRepository().lock_snapshot_evidence(session, refs)

    assert raised.value.code == "TOPIC_NOT_FOUND"
    assert session.calls == []


@pytest.mark.asyncio
async def test_snapshot_locks_probe_one_bounded_overflow_entry():
    from backend.repositories.topics import TopicRepository

    class LimitAwareSession(ScriptedSession):
        async def fetchall(self, sql, args=None):
            rows = await super().fetchall(sql, args)
            if "market_snapshot_entries" in sql:
                return rows[: args[-1]]
            return rows

    ref = TopicEvidenceRef(snapshotId="snapshot-a", contentHash="a" * 64)
    entries = [
        {
            "source_id": "source-a",
            "snapshot_id": "snapshot-a",
            "rank_number": rank,
            "title": f"作品{rank}",
            "author": f"作者{rank}",
            "category": "玄幻",
            "public_metrics_json": "{}",
        }
        for rank in range(1, 102)
    ]
    session = LimitAwareSession(
        batches=(
            [
                {
                    "id": "snapshot-a",
                    "source_id": "source-a",
                    "content_hash": "a" * 64,
                    "entry_count": 100,
                }
            ],
            entries,
        )
    )

    with pytest.raises(TopicFailure) as raised:
        await TopicRepository().lock_snapshot_evidence(session, (ref,))

    assert raised.value.code == "TOPIC_NOT_FOUND"
    assert session.calls[1][2] == ("snapshot-a", 101)


@pytest.mark.asyncio
async def test_identity_updates_use_compare_and_swap():
    from backend.repositories.topics import TopicRepository

    session = ScriptedSession(changes=(1, 0, 1))
    repository = TopicRepository()

    assert await repository.advance_direction(
        session,
        direction_id="direction-1",
        expected_version=1,
        version=2,
        updated_at=20,
    )
    assert not await repository.advance_candidate(
        session,
        candidate_id="candidate-1",
        expected_version=2,
        version=3,
        updated_at=30,
    )
    assert await repository.archive_candidate(
        session,
        candidate_id="candidate-1",
        expected_version=2,
        updated_at=40,
    )

    first = _compact(session.calls[0][1])
    second = _compact(session.calls[1][1])
    third = _compact(session.calls[2][1])
    assert "where id=%s and current_version=%s" in first
    assert "where id=%s and current_version=%s and status='active'" in second
    assert "set status='archived'" in third
    assert "where id=%s and current_version=%s and status='active'" in third


@pytest.mark.asyncio
async def test_handoff_idempotency_lookup_and_insert_are_session_bound():
    from backend.repositories.topics import TopicRepository

    receipt = {
        "id": "handoff-1",
        "candidate_id": "candidate-1",
        "candidate_version": 2,
        "candidate_hash": "c" * 64,
        "idempotency_key": "i" * 64,
        "request_hash": "r" * 64,
        "project_id": "project-1",
        "seed_id": "seed-1",
        "seed_revision_id": "seed-revision-1",
        "seed_revision": 1,
        "seed_hash": "s" * 64,
        "created_at": 50,
    }
    session = ScriptedSession(rows=(receipt,))
    repository = TopicRepository()

    found = await repository.lock_handoff_by_key(session, "i" * 64)
    await repository.insert_handoff(session, receipt)

    assert found == receipt
    assert "for update" in _compact(session.calls[0][1])
    assert session.calls[0][2] == ("i" * 64,)
    assert session.calls[1][0] == "execute"
    assert "insert into topic_project_handoffs" in _compact(session.calls[1][1])


@pytest.mark.asyncio
async def test_generation_inputs_separate_runtime_secret_from_safe_manifest():
    from backend.repositories.topics import TopicRepository

    provider = {
        "settings_revision": 4,
        "provider_id": "provider-1",
        "provider_name": "默认模型",
        "provider_type": "openai_compatible",
        "model_name": "writer-model",
        "base_url": "https://provider.example/v1",
        "api_key": "private-key",
        "enabled": 1,
        "lifecycle_status": "active",
        "max_context_tokens": 131072,
        "max_output_tokens": 16384,
        "temperature": "0.700",
        "top_p": "0.900",
        "supports_json": 1,
    }
    session = ScriptedSession(rows=(provider,))

    result = await TopicRepository().lock_generation_inputs(session)

    assert result["runtime"]["api_key"] == "private-key"
    assert result["runtime"]["base_url"] == "https://provider.example/v1"
    assert "api_key" not in result["manifest"]
    assert "base_url" not in result["manifest"]
    assert result["manifest"]["providerId"] == "provider-1"
    assert len(result["manifest"]["baseUrlHash"]) == 64
    assert result["manifest"]["generation"]["maxOutputTokens"] == 16384
    assert "for update" in _compact(session.calls[0][1])


@pytest.mark.asyncio
async def test_insert_methods_never_write_project_seed_selection():
    from backend.repositories.topics import TopicRepository

    session = ScriptedSession()
    repository = TopicRepository()
    await repository.insert_candidate_identity(
        session,
        {
            "id": "candidate-1",
            "status": "active",
            "current_version": 1,
            "created_at": 10,
            "updated_at": 10,
        },
    )
    await repository.insert_candidate_version(
        session,
        {
            "id": "version-1",
            "candidate_id": "candidate-1",
            "version": 1,
            "payload_json": "{}",
            "content_hash": "c" * 64,
            "discussion_id": "discussion-1",
            "basis_json": "{}",
            "basis_hash": "b" * 64,
            "idempotency_key": "i" * 64,
            "request_hash": "r" * 64,
            "created_at": 10,
        },
    )

    sql = " ".join(_compact(call[1]) for call in session.calls)
    assert "project_selected_seeds" not in sql
    assert "creative_seed" not in sql
