import asyncio
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import routers.providers as providers  # noqa: E402


async def main():
    assert providers.DEFAULT_TASK_PROVIDER_NAME == "deepseek-v4-flash"
    assert providers.DEFAULT_TASK_MODEL_NAME == "deepseek-v4-flash"

    original_fetchone = providers.fetchone
    original_execute = providers.execute
    original_get_bindings = providers.get_bindings

    calls = []

    async def fake_fetchone(sql, args=()):
        if "FROM provider_profiles" in sql and "model=%s" in sql:
            assert args == ("deepseek-v4-flash", "deepseek-v4-flash")
            return {
                "id": "provider-default",
                "name": "deepseek-v4-flash",
                "model": "deepseek-v4-flash",
                "updated_at": 123,
            }
        if "FROM task_model_bindings" in sql:
            return {
                "id": "binding-old",
                "project_id": "old-project",
                "source_project_title": "旧项目",
                "updated_at": 100,
                **{field: "provider-old" for field in providers.MODEL_BINDING_FIELDS},
            }
        return None

    async def fake_execute(sql, args=()):
        calls.append((sql, list(args)))

    async def fake_get_bindings(pid):
        return {"projectId": pid}

    providers.fetchone = fake_fetchone
    providers.execute = fake_execute
    providers.get_bindings = fake_get_bindings
    try:
        await providers.inherit_latest_task_model_bindings("new-project")
    finally:
        providers.fetchone = original_fetchone
        providers.execute = original_execute
        providers.get_bindings = original_get_bindings

    assert calls, "inherit should insert task model bindings"
    inserted_args = calls[0][1]
    mapped_provider_ids = inserted_args[2:10]
    assert mapped_provider_ids == ["provider-default"] * 8
    assert inserted_args[10] == "old-project", "source project metadata may remain historical"


asyncio.run(main())
print("default model binding contract tests passed")
