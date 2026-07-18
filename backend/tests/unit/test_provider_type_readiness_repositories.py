from __future__ import annotations

import pytest

from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.contracts import ContractRepository


class RecordingSession:
    def __init__(self):
        self.calls = []

    async def fetchall(self, sql, args=None):
        self.calls.append((" ".join(sql.split()), args))
        return []

    async def fetchone(self, sql, args=None):
        self.calls.append((" ".join(sql.split()), args))
        return None


@pytest.mark.asyncio
async def test_contract_readiness_accepts_only_generation_capable_type():
    session = RecordingSession()

    await ContractRepository().read_binding_snapshot(session, "project-1")

    sql, _ = session.calls[0]
    assert (
        "LOWER(TRIM(provider.provider_type))='openai-compatible'" in sql
    )
    assert "provider.provider_type IS NOT NULL" not in sql


@pytest.mark.asyncio
async def test_chapter_provider_resolution_accepts_only_generation_capable_type():
    session = RecordingSession()

    result = await ChapterSessionRepository().resolve_writing_provider(
        session, "project-1"
    )

    assert result is None
    sql, args = session.calls[0]
    assert "LOWER(TRIM(p.provider_type))='openai-compatible'" in sql
    assert "p.provider_type IS NOT NULL" not in sql
    assert args == ("project-1",)
