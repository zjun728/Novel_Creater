from __future__ import annotations

import pytest

from backend.domain.provider_policy import GENERATION_PROVIDER_TYPE
from backend.repositories.chapter_sessions import ChapterSessionRepository
from backend.repositories.contracts import ContractRepository
from backend.repositories.model_bindings import AVAILABLE_PROVIDER_PREDICATE


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
        f"LOWER(TRIM(provider.provider_type))='{GENERATION_PROVIDER_TYPE}'"
        in sql
    )
    assert "provider.lifecycle_status='active'" in sql
    assert "provider.enabled=1" in sql
    for field in ("model_name", "base_url", "api_key"):
        assert f"TRIM(provider.{field})<>''" in sql
    assert "provider.provider_type IS NOT NULL" not in sql


@pytest.mark.asyncio
async def test_chapter_provider_resolution_accepts_only_generation_capable_type():
    session = RecordingSession()

    result = await ChapterSessionRepository().resolve_writing_provider(
        session, "project-1"
    )

    assert result is None
    sql, args = session.calls[0]
    assert (
        f"LOWER(TRIM(p.provider_type))='{GENERATION_PROVIDER_TYPE}'" in sql
    )
    assert "p.lifecycle_status='active'" in sql
    assert "p.enabled=1" in sql
    for field in ("model_name", "base_url", "api_key"):
        assert f"TRIM(p.{field})<>''" in sql
    assert "p.provider_type IS NOT NULL" not in sql
    assert args == ("project-1",)


def test_model_binding_sql_uses_the_canonical_generation_policy():
    sql = " ".join(AVAILABLE_PROVIDER_PREDICATE.split())

    assert f"LOWER(TRIM(provider_type))='{GENERATION_PROVIDER_TYPE}'" in sql
    assert "lifecycle_status='active'" in sql
    assert "enabled=1" in sql
    for field in ("model_name", "base_url", "api_key"):
        assert f"TRIM({field})<>''" in sql
