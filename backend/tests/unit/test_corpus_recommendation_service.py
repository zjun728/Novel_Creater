from __future__ import annotations

from contextlib import asynccontextmanager

import pytest


HASH = "a" * 64


class FakeCorpusRecommendationRepository:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    async def list_recommendation_fragments(self, session, *, after, limit):
        self.calls.append((session, after, limit))
        start = 0
        if after is not None:
            start = next(
                index + 1
                for index, row in enumerate(self.rows)
                if (
                    row["source_id"], row["chapter_order"],
                    row["fragment_order"], row["fragment_id"],
                ) == after
            )
        return tuple(self.rows[start:start + limit])


def _row(index: int, *, tags="[]", source="无关书名", chapter="无关章节", text="无关正文"):
    return {
        "source_id": f"source-{index}",
        "source_revision_id": f"source-revision-{index}",
        "source_revision": 2,
        "source_hash": HASH,
        "reference_tags_json": tags,
        "display_name": source,
        "chapter_id": f"chapter-{index}",
        "chapter_title": chapter,
        "chapter_order": index,
        "fragment_id": f"fragment-{index}",
        "fragment_order": 1,
        "fragment_hash": f"{index:064x}",
        "chapter_char_start": index * 1_000,
        "chapter_char_end": index * 1_000 + len(text),
        "normalized_text": text,
    }


def _service(rows):
    from backend.services.corpus_recommendations import CorpusRecommendationService

    repository = FakeCorpusRecommendationRepository(rows)

    @asynccontextmanager
    async def connection():
        yield "read-session"

    return CorpusRecommendationService(
        repository,
        connection_factory=connection,
    ), repository


@pytest.mark.asyncio
async def test_candidates_match_tags_title_heading_and_nfkc_ngram_overlap():
    rows = (
        _row(1, tags='["边城制度"]'),
        _row(2, source="边城制度考"),
        _row(3, chapter="边城制度试行"),
        _row(4, text="旧城开始实行ＢＯＯＫ制度，众人记录每次修正。"),
        _row(5),
    )
    service, repository = _service(rows)

    candidates = await service.candidates(("边城制度", "book制度"))

    assert {item.fragment_id for item in candidates} == {
        "fragment-1", "fragment-2", "fragment-3", "fragment-4"
    }
    assert repository.calls == [("read-session", None, 500)]
    assert all(len(item.excerpt) <= 300 for item in candidates)
    assert sum(len(item.excerpt) for item in candidates) <= 4_000
    assert all(
        item.window_start < item.window_end
        and item.window_end <= rows[int(item.fragment_id.split("-")[1]) - 1][
            "chapter_char_end"
        ]
        for item in candidates
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "query", "body_hit"),
    (
        ("！" * 300 + "边城制度" + "继续试行。" * 80, "边城制度", "边城制度"),
        ("序" * 80 + " \t\r\n" * 100 + "边城制度" + "后" * 300, "边城制度", "边城制度"),
        ("㍿" * 100 + "边城制度" + "后" * 300, "株式会社边城制度", "边城制度"),
        (("A\u030a" * 300) + "边城制度" + "后" * 300, "边城制度", "边城制度"),
        ("！" * 300 + "银河边境" + "后" * 300, "银河航行", "银河"),
    ),
)
async def test_candidate_windows_map_normalized_hits_back_to_original_text(
    text,
    query,
    body_hit,
):
    row = _row(1, text=text)
    service, _ = _service((row,))

    candidate, = await service.candidates((query,))

    local_start = candidate.window_start - row["chapter_char_start"]
    local_end = candidate.window_end - row["chapter_char_start"]
    assert candidate.excerpt == text[local_start:local_end]
    assert body_hit in candidate.excerpt
    assert candidate.window_start == row["chapter_char_start"] + local_start
    assert candidate.window_end == row["chapter_char_start"] + local_end


@pytest.mark.asyncio
async def test_candidates_are_relevance_bounded_to_twenty_and_four_thousand_chars():
    rows = tuple(
        _row(
            index,
            tags='["边城制度"]',
            text=("边城制度逐步试行。" * 80),
        )
        for index in range(1, 40)
    )
    service, _ = _service(rows)

    candidates = await service.candidates(("边城制度",))

    assert len(candidates) == 20
    assert all(len(item.excerpt) <= 300 for item in candidates)
    assert sum(len(item.excerpt) for item in candidates) <= 4_000


@pytest.mark.asyncio
async def test_candidates_return_empty_when_no_search_dimension_overlaps():
    service, _ = _service((_row(1), _row(2)))

    assert await service.candidates(("星际航行",)) == ()


@pytest.mark.asyncio
async def test_candidates_scan_past_first_five_hundred_rows_for_unique_match():
    rows = tuple(_row(index) for index in range(1, 501)) + (
        _row(501, chapter="唯一命中的边城制度"),
    )
    service, repository = _service(rows)

    candidates = await service.candidates(("边城制度",))

    assert tuple(item.fragment_id for item in candidates) == ("fragment-501",)
    assert len(repository.calls) >= 2


class RecordingSession:
    def __init__(self):
        self.calls = []

    async def fetchall(self, sql, params=None):
        self.calls.append((sql, params))
        return []


@pytest.mark.asyncio
async def test_repository_reads_only_active_current_analyzed_fragments_without_paths():
    from backend.repositories.corpus import CorpusRepository

    session = RecordingSession()
    await CorpusRepository().list_recommendation_fragments(
        session,
        after=None,
        limit=500,
    )

    assert len(session.calls) == 1
    sql, params = session.calls[0]
    normalized = " ".join(sql.casefold().split())
    assert "source.archived_at is null" in normalized
    assert "revision.status='analyzed'" in normalized
    assert "head.revision_id=revision.id" in normalized
    assert "chapter.source_revision_id=revision.id" in normalized
    assert "limit %s" in normalized
    assert params == (500,)
    assert "storage_key" not in normalized
    assert "relative_path" not in normalized


@pytest.mark.asyncio
async def test_repository_uses_deterministic_keyset_without_offset_or_random_order():
    from backend.repositories.corpus import CorpusRepository

    session = RecordingSession()
    after = ("source-500", 500, 1, "fragment-500")

    await CorpusRepository().list_recommendation_fragments(
        session,
        after=after,
        limit=500,
    )

    sql, params = session.calls[0]
    normalized = " ".join(sql.casefold().split())
    assert "( source.id,chapter.chapter_order, fragment.fragment_order,fragment.id ) >" in normalized
    assert "order by source.id,chapter.chapter_order, fragment.fragment_order,fragment.id" in normalized
    assert "offset" not in normalized and "rand(" not in normalized
    assert params == (*after, 500)
