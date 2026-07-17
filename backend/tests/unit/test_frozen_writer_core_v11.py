from __future__ import annotations

import pytest

from backend.tests.support.frozen_writer_core_v11 import (
    initialize_frozen_writer_core_v11,
)


@pytest.mark.asyncio
async def test_frozen_v11_initializer_rejects_non_disposable_before_session_use():
    class NoSQLSession:
        def __init__(self):
            self.calls = []

        async def execute(self, sql, args=None):
            self.calls.append((sql, args))
            raise AssertionError("non-disposable target reached SQL")

    session = NoSQLSession()

    with pytest.raises(RuntimeError, match="Refusing non-disposable database"):
        await initialize_frozen_writer_core_v11(session, "novel_creator")

    assert session.calls == []
