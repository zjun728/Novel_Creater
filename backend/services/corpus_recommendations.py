"""Read-only composition for bounded corpus recommendation candidates."""

from __future__ import annotations

from backend.domain.corpus_recommendations import CorpusCandidateCollector


_PAGE_SIZE = 500


class CorpusRecommendationService:
    def __init__(self, repository, *, connection_factory) -> None:
        self.repository = repository
        self._connection = connection_factory

    async def candidates(self, query_texts: tuple[str, ...]):
        collector = CorpusCandidateCollector(tuple(query_texts))
        after = None
        async with self._connection() as session:
            while True:
                rows = tuple(
                    await self.repository.list_recommendation_fragments(
                        session,
                        after=after,
                        limit=_PAGE_SIZE,
                    )
                )
                collector.add_rows(rows)
                if len(rows) < _PAGE_SIZE:
                    break
                last = rows[-1]
                next_after = (
                    str(last["source_id"]),
                    int(last["chapter_order"]),
                    int(last["fragment_order"]),
                    str(last["fragment_id"]),
                )
                if next_after == after:
                    raise ValueError("corpus recommendation cursor did not advance")
                after = next_after
        return collector.result()


__all__ = ("CorpusRecommendationService",)
