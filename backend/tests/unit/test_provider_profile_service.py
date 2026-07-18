from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import is_dataclass
import json

import aiomysql
import pytest

from backend.http_errors import PublicDomainError
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    sanitize_provider_secret_text,
)
from backend.serializers.provider import provider_public_profile
from backend.services.provider_profiles import (
    ClearProviderApiKeyCommand,
    DeleteProviderCommand,
    ProviderCreateCommand,
    ProviderIdempotencyConflict,
    ProviderProfileConflict,
    ProviderProfileService,
    ProviderUpdateCommand,
)


SECRET = "saved-provider-secret"
PRIVATE_URL = "https://saved-provider.example/v1"
OVERLAPPING_KEY = "https"
OVERLAPPING_URL = "https://secret.internal.example/v1"
OVERLAPPING_HOST = "secret.internal.example"
FORBIDDEN_KEYS = {
    "apikey",
    "baseurl",
    "authorization",
    "token",
    "password",
}
PUBLIC_PROFILE_KEYS = {
    "id",
    "name",
    "providerType",
    "model",
    "enabled",
    "sortOrder",
    "stream",
    "maxContextTokens",
    "maxOutputTokens",
    "temperature",
    "topP",
    "supportsJSON",
    "supportsStreaming",
    "notes",
    "thinking",
    "hasKey",
    "hasBaseURL",
    "lifecycleStatus",
    "revision",
    "ready",
    "createdAt",
    "updatedAt",
}


def assert_public_profile(value):
    assert is_dataclass(value)
    assert not hasattr(value, "api_key")
    assert not hasattr(value, "base_url")
    payload = value.to_dict()

    def visit(item):
        if isinstance(item, dict):
            for key, nested in item.items():
                normalized = str(key).casefold().replace("_", "").replace("-", "")
                assert normalized not in FORBIDDEN_KEYS
                visit(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(payload)
    rendered = json.dumps(payload, ensure_ascii=False)
    assert SECRET not in rendered
    assert PRIVATE_URL not in rendered
    return payload


def assert_stable_public_schema_without_secret_value(value, secret):
    payload = assert_public_profile(value)
    assert set(payload) == PUBLIC_PROFILE_KEYS

    def visit_values(item):
        if isinstance(item, dict):
            for nested in item.values():
                visit_values(nested)
        elif isinstance(item, (list, tuple)):
            for nested in item:
                visit_values(nested)
        elif isinstance(item, str):
            assert item != secret

    visit_values(payload)


def provider_row(**overrides):
    row = {
        "id": "provider-1",
        "name": "Provider One",
        "provider_type": "openai-compatible",
        "model_name": "model-one",
        "base_url": PRIVATE_URL,
        "api_key": SECRET,
        "enabled": 1,
        "sort_order": 0,
        "stream": 1,
        "max_context_tokens": 200_000,
        "max_output_tokens": 4096,
        "temperature": 0.8,
        "top_p": 0.9,
        "supports_json": 1,
        "supports_streaming": 1,
        "notes": "",
        "thinking": None,
        "lifecycle_status": "active",
        "revision": 4,
        "deleted_at": None,
        "created_at": 10,
        "updated_at": 20,
    }
    row.update(overrides)
    return row


def test_provider_secret_normalization_is_deduplicated_and_longest_first():
    host = "secret.internal.example"
    url = f"https://{host}/v1"

    secrets = normalize_provider_secrets(
        ("", f" {host} ", url, url, None)
    )

    assert secrets == (url, host)
    assert sanitize_provider_secret_text(url, secrets) == "[REDACTED]"


@pytest.mark.parametrize("structural_secret", ["enabled", "revision"])
def test_public_dto_preserves_trusted_schema_keys_that_equal_secrets(
    structural_secret,
):
    row = provider_row(api_key=structural_secret)

    profile = provider_public_profile(row)

    assert profile.enabled is True
    assert profile.revision == 4
    assert profile.to_dict()["enabled"] is True
    assert profile.to_dict()["revision"] == 4


class MemoryProviderRepository:
    def __init__(self, rows=None):
        self.profiles = {
            row["id"]: dict(row)
            for row in ([provider_row()] if rows is None else rows)
        }
        self.requests = {}
        self.events = []

    async def list_profiles(self, session):
        self.events.append("list_profiles")
        return [
            dict(row)
            for row in self.profiles.values()
            if row["lifecycle_status"] != "deleted"
        ]

    async def lock_create_request(self, session, idempotency_key):
        self.events.append("lock_create_request")
        for request in self.requests.values():
            if (
                request["mutation_kind"] == "create"
                and request["idempotency_key"] == idempotency_key
            ):
                return dict(request)
        return None

    async def lock_mutation_request(self, session, provider_id, idempotency_key):
        self.events.append("lock_mutation_request")
        request = self.requests.get((provider_id, idempotency_key))
        return dict(request) if request else None

    async def lock_profile(self, session, provider_id):
        self.events.append("lock_profile")
        row = self.profiles.get(provider_id)
        return dict(row) if row else None

    async def read_profile(self, session, provider_id):
        self.events.append("read_profile")
        row = self.profiles.get(provider_id)
        return dict(row) if row else None

    async def read_connection_profile(self, session, provider_id):
        self.events.append("read_connection_profile")
        row = self.profiles.get(provider_id)
        return dict(row) if row else None

    async def insert_profile(self, session, row):
        self.events.append("insert_profile")
        self.profiles[row["id"]] = dict(row)

    async def compare_and_swap_profile(
        self, session, provider_id, expected_revision, changes
    ):
        self.events.append("compare_and_swap_profile")
        row = self.profiles.get(provider_id)
        if row is None or row["revision"] != expected_revision:
            return False
        row.update(changes)
        return True

    async def insert_mutation_request(self, session, request):
        self.events.append("insert_mutation_request")
        key = (request["provider_id"], request["idempotency_key"])
        self.requests[key] = dict(request)


class FakeGateway:
    def __init__(self, result=None):
        self.result = result or {
            "ok": True,
            "code": "connected",
            "latencyMs": 12,
            "publicMessage": "连接成功",
        }
        self.providers = []

    async def test_connection(self, provider):
        self.providers.append(dict(provider))
        return dict(self.result)


class Harness:
    def __init__(self, rows=None):
        self.repository = MemoryProviderRepository(rows)
        self.gateway = FakeGateway()
        self.events = []
        self.ids = iter(("generated-provider-id", "request-id-1", "request-id-2"))
        self.times = iter((100, 101, 102, 103, 104, 105))

        @asynccontextmanager
        async def transaction():
            self.events.append("transaction_enter")
            try:
                yield object()
            except BaseException:
                self.events.append("transaction_rollback")
                raise
            else:
                self.events.append("transaction_commit")

        @asynccontextmanager
        async def connection():
            self.events.append("connection_enter")
            try:
                yield object()
            finally:
                self.events.append("connection_exit")

        self.service = ProviderProfileService(
            self.repository,
            transaction_factory=transaction,
            connection_factory=connection,
            connection_gateway=self.gateway,
            id_factory=lambda: next(self.ids),
            clock=lambda: next(self.times),
        )


def create_command(**overrides):
    values = {
        "name": "Created",
        "provider_type": "openai-compatible",
        "model": "model-created",
        "base_url": PRIVATE_URL,
        "api_key": SECRET,
        "enabled": True,
        "sort_order": 0,
        "stream": True,
        "max_context_tokens": 200_000,
        "max_output_tokens": 4096,
        "temperature": 0.8,
        "top_p": 0.9,
        "supports_json": True,
        "supports_streaming": True,
        "notes": "",
        "thinking": None,
        "idempotency_key": "create-request-key-0001",
    }
    values.update(overrides)
    return ProviderCreateCommand(**values)


@pytest.mark.asyncio
async def test_create_is_revisioned_and_idempotent_in_one_transaction():
    harness = Harness(rows=[])

    created = await harness.service.create(create_command())
    replay = await harness.service.create(create_command())

    assert created == replay
    assert_public_profile(created)
    assert created.revision == 1
    assert created.lifecycle_status == "active"
    assert len(harness.repository.profiles) == 1
    request = next(iter(harness.repository.requests.values()))
    assert request["mutation_kind"] == "create"
    assert request["expected_revision"] == 0
    assert request["result_revision"] == 1
    assert harness.repository.events.count("insert_profile") == 1
    assert harness.events == [
        "transaction_enter",
        "transaction_commit",
        "transaction_enter",
        "transaction_commit",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("structural_secret", ["enabled", "revision"])
async def test_create_preserves_trusted_public_dto_schema_keys(
    structural_secret,
):
    harness = Harness(rows=[])

    created = await harness.service.create(
        create_command(api_key=structural_secret)
    )

    assert created.enabled is True
    assert created.revision == 1
    assert created.to_dict()["enabled"] is True
    assert created.to_dict()["revision"] == 1
    assert harness.events[-1] == "transaction_commit"
    assert harness.repository.events.count("insert_profile") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("private_column", ["api_key", "base_url"])
@pytest.mark.parametrize(
    "structural_secret", ["enabled", "revision", "provider"]
)
async def test_structural_secret_values_preserve_schema_across_every_profile_path(
    private_column, structural_secret
):
    private_overrides = {private_column: structural_secret}

    listed_harness = Harness(
        rows=[provider_row(**private_overrides)]
    )
    listed = (await listed_harness.service.list_profiles())[0]

    create_harness = Harness(rows=[])
    create_overrides = {
        "api_key" if private_column == "api_key" else "base_url":
        structural_secret
    }
    created = await create_harness.service.create(
        create_command(**create_overrides)
    )

    update_harness = Harness(
        rows=[provider_row(**private_overrides)]
    )
    update_command = ProviderUpdateCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key=(
            f"update-structural-{private_column}-{structural_secret}"
        ),
        changes={"model": "model-two"},
    )
    updated = await update_harness.service.update(update_command)
    update_replay = await update_harness.service.update(update_command)

    clear_harness = Harness(
        rows=[provider_row(**private_overrides)]
    )
    clear_command = ClearProviderApiKeyCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key=(
            f"clear-structural-{private_column}-{structural_secret}"
        ),
    )
    cleared = await clear_harness.service.clear_api_key(clear_command)
    clear_replay = await clear_harness.service.clear_api_key(clear_command)

    delete_harness = Harness(
        rows=[provider_row(**private_overrides)]
    )
    delete_command = DeleteProviderCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key=(
            f"delete-structural-{private_column}-{structural_secret}"
        ),
    )
    deleted = await delete_harness.service.delete(delete_command)
    delete_replay = await delete_harness.service.delete(delete_command)

    for profile in (
        listed,
        created,
        updated,
        update_replay,
        cleared,
        clear_replay,
        deleted,
        delete_replay,
    ):
        assert_stable_public_schema_without_secret_value(
            profile, structural_secret
        )


@pytest.mark.asyncio
async def test_create_preserves_legitimate_short_key_public_substrings():
    harness = Harness(rows=[])
    command = create_command(
        name="Alpha Provider",
        provider_type="openai-compatible",
        model="claude",
        base_url="https://provider.example/v1",
        api_key="a",
        notes="aaaa remains ordinary public text",
        thinking={"a-key": "a value"},
    )

    created = await harness.service.create(command)

    assert_public_profile(created)
    stored = harness.repository.profiles[created.id]
    assert stored["api_key"] == "a"
    assert stored["name"] == command.name
    assert stored["provider_type"] == command.provider_type
    assert stored["model_name"] == command.model
    assert stored["notes"] == command.notes
    assert stored["thinking"] == command.thinking


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsupported_type", ["anthropic", "unsupported-native"]
)
async def test_create_rejects_unsupported_provider_type_without_writes(
    unsupported_type,
):
    harness = Harness(rows=[])

    with pytest.raises(PublicDomainError) as caught:
        await harness.service.create(
            create_command(provider_type=unsupported_type)
        )

    assert caught.value.status_code == 422
    assert caught.value.code == "provider_type_unsupported"
    assert SECRET not in caught.value.message
    assert PRIVATE_URL not in caught.value.message
    assert not harness.repository.profiles
    assert not harness.repository.requests
    assert not harness.repository.events


@pytest.mark.asyncio
async def test_overlapping_key_and_url_are_longest_first_in_public_dtos():
    contaminated = provider_row(
        api_key=OVERLAPPING_KEY,
        base_url=OVERLAPPING_URL,
        notes=f"private endpoint {OVERLAPPING_URL}",
        thinking={"endpoint": OVERLAPPING_URL},
    )
    harness = Harness(rows=[contaminated])

    listed = await harness.service.list_profiles()

    rendered = json.dumps(listed[0].to_dict(), ensure_ascii=False)
    assert OVERLAPPING_URL not in rendered
    assert OVERLAPPING_HOST not in rendered
    assert "[REDACTED]://secret" not in rendered


@pytest.mark.asyncio
async def test_update_blank_secrets_preserves_them_and_increments_revision():
    harness = Harness()

    result = await harness.service.update(
        ProviderUpdateCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="update-request-key-0001",
            changes={"apiKey": "   ", "baseURL": "", "model": "model-two"},
        )
    )

    assert_public_profile(result)
    stored = harness.repository.profiles["provider-1"]
    assert stored["api_key"] == SECRET
    assert stored["base_url"] == PRIVATE_URL
    assert stored["model_name"] == "model-two"
    assert result.revision == 5
    assert result.lifecycle_status == "active"


@pytest.mark.asyncio
async def test_update_rejects_public_field_containing_saved_secret():
    harness = Harness()
    original = dict(harness.repository.profiles["provider-1"])

    with pytest.raises(PublicDomainError) as caught:
        await harness.service.update(
            ProviderUpdateCommand(
                provider_id="provider-1",
                expected_revision=4,
                idempotency_key="update-secret-collision-0001",
                changes={"notes": f"public {SECRET} collision"},
            )
        )

    assert caught.value.status_code == 422
    assert caught.value.code == "provider_public_secret_collision"
    assert SECRET not in caught.value.message
    assert harness.repository.profiles["provider-1"] == original
    assert "compare_and_swap_profile" not in harness.repository.events
    assert not harness.repository.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["a", " a "])
async def test_create_rejects_canonical_public_short_secret_collision(name):
    harness = Harness(rows=[])

    with pytest.raises(PublicDomainError) as caught:
        await harness.service.create(
            create_command(api_key="a", name=name)
        )

    assert caught.value.status_code == 422
    assert caught.value.code == "provider_public_secret_collision"
    assert caught.value.message == (
        "Provider public fields cannot contain private configuration"
    )
    assert harness.events == []
    assert not harness.repository.profiles
    assert not harness.repository.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["update", "clear", "delete"])
async def test_mutations_scrub_overlapping_url_before_key_and_replay(kind):
    contaminated = provider_row(
        api_key=OVERLAPPING_KEY,
        base_url=OVERLAPPING_URL,
        notes=f"private endpoint {OVERLAPPING_URL}",
        thinking={"endpoint": OVERLAPPING_URL},
    )
    harness = Harness(rows=[contaminated])
    if kind == "update":
        command = ProviderUpdateCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="update-overlap-request-0001",
            changes={"model": "model-two"},
        )
        mutate = harness.service.update
    elif kind == "clear":
        command = ClearProviderApiKeyCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="clear-overlap-request-0001",
        )
        mutate = harness.service.clear_api_key
    else:
        command = DeleteProviderCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="delete-overlap-request-0001",
        )
        mutate = harness.service.delete

    first = await mutate(command)
    replay = await mutate(command)

    for profile in (first, replay):
        rendered = json.dumps(profile.to_dict(), ensure_ascii=False)
        assert OVERLAPPING_URL not in rendered
        assert OVERLAPPING_HOST not in rendered
        assert "[REDACTED]://secret" not in rendered
    stored = json.dumps(
        {
            "notes": harness.repository.profiles["provider-1"]["notes"],
            "thinking": harness.repository.profiles["provider-1"]["thinking"],
        },
        ensure_ascii=False,
    )
    assert OVERLAPPING_URL not in stored
    assert OVERLAPPING_HOST not in stored


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary_secret", ["12345678", "123456789"])
async def test_existing_repeated_boundary_collision_fails_closed_without_growth(
    boundary_secret,
):
    harness = Harness(
        rows=[
            provider_row(
                api_key=boundary_secret,
                name=boundary_secret * (120 // len(boundary_secret)),
                notes=boundary_secret * (65_535 // len(boundary_secret)),
            )
        ]
    )

    cleared = await harness.service.clear_api_key(
        ClearProviderApiKeyCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="clear-boundary-request-0001",
        )
    )

    stored = harness.repository.profiles["provider-1"]
    assert cleared.name == "[REDACTED]"
    assert cleared.notes == "[REDACTED]"
    assert stored["name"] == "[REDACTED]"
    assert stored["notes"] == "[REDACTED]"
    assert len(stored["name"]) <= 120
    assert len(stored["notes"].encode("utf-8")) <= 65_535


@pytest.mark.asyncio
async def test_clear_key_is_atomic_idempotent_and_preserves_private_base_url():
    harness = Harness()
    command = ClearProviderApiKeyCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key="clear-request-key-0001",
    )

    cleared = await harness.service.clear_api_key(command)
    replay = await harness.service.clear_api_key(command)

    assert cleared == replay
    assert_public_profile(cleared)
    stored = harness.repository.profiles["provider-1"]
    assert stored["api_key"] == ""
    assert stored["base_url"] == PRIVATE_URL
    assert cleared.enabled is False
    assert cleared.has_key is False
    assert cleared.has_base_url is True
    assert cleared.lifecycle_status == "unconfigured"
    assert cleared.revision == 5
    assert harness.repository.events.count("compare_and_swap_profile") == 1
    request = harness.repository.requests[
        ("provider-1", "clear-request-key-0001")
    ]
    assert request["mutation_kind"] == "clear_key"
    assert request["result_revision"] == 5


async def destructive_mutation_twice(harness, kind):
    if kind == "clear":
        command = ClearProviderApiKeyCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="clear-secret-key-request-0001",
        )
        mutate = harness.service.clear_api_key
    else:
        command = DeleteProviderCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="delete-secret-key-request-0001",
        )
        mutate = harness.service.delete
    return await mutate(command), await mutate(command)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["clear", "delete"])
async def test_destructive_mutations_sanitize_secret_mapping_keys_before_replay(
    kind,
):
    thinking = {
        "apiKeyContainer": {SECRET: f"api value {SECRET}"},
        "baseURLContainer": {
            PRIVATE_URL: f"url value {PRIVATE_URL}",
        },
        "safe": {"ordinary": "visible"},
    }
    harness = Harness(rows=[provider_row(thinking=thinking)])

    first, replay = await destructive_mutation_twice(harness, kind)

    expected = {
        "apiKeyContainer": {"[REDACTED]": "api value [REDACTED]"},
        "baseURLContainer": {
            "[REDACTED]": "url value [REDACTED]",
        },
        "safe": {"ordinary": "visible"},
    }
    for profile in (first, replay):
        assert_public_profile(profile)
        assert profile.thinking == expected
    assert harness.repository.profiles["provider-1"]["thinking"] == expected
    assert harness.repository.events.count("compare_and_swap_profile") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["clear", "delete"])
async def test_destructive_mutations_fail_closed_on_secret_key_collision(kind):
    thinking = {
        "collision": {
            SECRET: "api entry",
            PRIVATE_URL: "url entry",
        },
        "safe": {"ordinary": "visible"},
    }
    harness = Harness(rows=[provider_row(thinking=thinking)])

    first, replay = await destructive_mutation_twice(harness, kind)

    expected = {
        "collision": {},
        "safe": {"ordinary": "visible"},
    }
    for profile in (first, replay):
        assert_public_profile(profile)
        assert profile.thinking == expected
    assert harness.repository.profiles["provider-1"]["thinking"] == expected
    assert harness.repository.events.count("compare_and_swap_profile") == 1


@pytest.mark.asyncio
async def test_soft_delete_is_the_only_command_that_wipes_key_and_base_url():
    harness = Harness()

    deleted = await harness.service.delete(
        DeleteProviderCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="delete-request-key-0001",
        )
    )

    assert_public_profile(deleted)
    stored = harness.repository.profiles["provider-1"]
    assert stored["api_key"] == ""
    assert stored["base_url"] == ""
    assert stored["deleted_at"] is not None
    assert deleted.enabled is False
    assert deleted.lifecycle_status == "deleted"
    assert deleted.revision == 5


@pytest.mark.asyncio
async def test_revision_and_idempotency_conflicts_do_not_write():
    harness = Harness()
    with pytest.raises(ProviderProfileConflict):
        await harness.service.clear_api_key(
            ClearProviderApiKeyCommand(
                provider_id="provider-1",
                expected_revision=3,
                idempotency_key="clear-request-key-0001",
            )
        )
    assert "compare_and_swap_profile" not in harness.repository.events

    first = ClearProviderApiKeyCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key="clear-request-key-0002",
    )
    await harness.service.clear_api_key(first)
    with pytest.raises(ProviderIdempotencyConflict):
        await harness.service.clear_api_key(
            ClearProviderApiKeyCommand(
                provider_id="provider-1",
                expected_revision=5,
                idempotency_key="clear-request-key-0002",
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["update", "clear", "delete"])
async def test_mutations_lock_provider_before_idempotency_request(kind):
    harness = Harness()
    if kind == "update":
        command = ProviderUpdateCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="update-lock-order-0001",
            changes={"model": "model-two"},
        )
        mutate = harness.service.update
    elif kind == "clear":
        command = ClearProviderApiKeyCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="clear-lock-order-0001",
        )
        mutate = harness.service.clear_api_key
    else:
        command = DeleteProviderCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="delete-lock-order-0001",
        )
        mutate = harness.service.delete

    await mutate(command)

    events = harness.repository.events
    assert events.index("lock_profile") < events.index(
        "lock_mutation_request"
    )
    assert events.index("lock_mutation_request") < events.index(
        "compare_and_swap_profile"
    )
    assert events.index("compare_and_swap_profile") < events.index(
        "insert_mutation_request"
    )


@pytest.mark.asyncio
async def test_delete_replay_locks_deleted_provider_before_request_and_recovers():
    harness = Harness()
    command = DeleteProviderCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key="delete-replay-lock-order-0001",
    )
    first = await harness.service.delete(command)
    start = len(harness.repository.events)

    replay = await harness.service.delete(command)

    assert replay == first
    replay_events = harness.repository.events[start:]
    assert replay_events[:2] == [
        "lock_profile",
        "lock_mutation_request",
    ]
    assert "compare_and_swap_profile" not in replay_events


@pytest.mark.asyncio
@pytest.mark.parametrize("number", [1205, 1213])
@pytest.mark.parametrize("operation", ["create", "mutate"])
async def test_retryable_mysql_lock_errors_map_to_fixed_provider_409(
    number, operation
):
    harness = Harness(rows=[] if operation == "create" else None)
    error = aiomysql.OperationalError(
        number, f"unsafe lock detail {SECRET} {PRIVATE_URL}"
    )
    if operation == "create":
        async def fail_lock_create_guard(session):
            raise error

        harness.repository.lock_create_guard = fail_lock_create_guard
        invoke = lambda: harness.service.create(create_command())
    else:
        async def fail_lock_profile(session, provider_id):
            raise error

        harness.repository.lock_profile = fail_lock_profile
        command = ClearProviderApiKeyCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="clear-lock-error-0001",
        )
        invoke = lambda: harness.service.clear_api_key(command)

    with pytest.raises(PublicDomainError) as caught:
        await invoke()

    assert caught.value.status_code == 409
    assert caught.value.code == "provider_mutation_retryable_conflict"
    assert caught.value.retryable is True
    assert SECRET not in caught.value.message
    assert PRIVATE_URL not in caught.value.message
    assert harness.events[-1] == "transaction_rollback"


@pytest.mark.asyncio
async def test_provider_mutation_does_not_catch_integrity_errors_generically():
    harness = Harness()
    error = aiomysql.IntegrityError(
        1062, f"unsafe duplicate {SECRET} {PRIVATE_URL}"
    )

    async def fail_lock_profile(session, provider_id):
        raise error

    harness.repository.lock_profile = fail_lock_profile
    command = ClearProviderApiKeyCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key="clear-integrity-error-0001",
    )

    with pytest.raises(aiomysql.IntegrityError) as caught:
        await harness.service.clear_api_key(command)

    assert caught.value is error
    assert harness.events[-1] == "transaction_rollback"


@pytest.mark.asyncio
async def test_connection_uses_saved_private_projection_after_read_scope_closes():
    harness = Harness()

    result = await harness.service.test_connection("provider-1")

    assert is_dataclass(result)
    assert result.to_dict() == {
        "ok": True,
        "code": "connected",
        "latencyMs": 12,
        "publicMessage": "连接成功",
    }
    assert harness.events == ["connection_enter", "connection_exit"]
    assert harness.gateway.providers == [
        {
            "provider_type": "openai-compatible",
            "model_name": "model-one",
            "base_url": PRIVATE_URL,
            "api_key": SECRET,
        }
    ]


@pytest.mark.asyncio
async def test_connection_preserves_fixed_unsupported_provider_result():
    harness = Harness(
        rows=[provider_row(provider_type="anthropic")]
    )

    result = await harness.service.test_connection("provider-1")

    assert result.to_dict() == {
        "ok": False,
        "code": "provider_unsupported",
        "latencyMs": 0,
        "publicMessage": "不支持的 Provider 类型",
    }
    assert SECRET not in str(result)
    assert PRIVATE_URL not in str(result)
    assert harness.gateway.providers == []


@pytest.mark.asyncio
async def test_update_rejects_existing_unsupported_provider_without_write():
    harness = Harness(
        rows=[provider_row(provider_type="anthropic")]
    )

    with pytest.raises(PublicDomainError) as caught:
        await harness.service.update(
            ProviderUpdateCommand(
                provider_id="provider-1",
                expected_revision=4,
                idempotency_key="update-anthropic-unsupported-0001",
                changes={"model": "claude-new"},
            )
        )

    assert caught.value.status_code == 422
    assert caught.value.code == "provider_type_unsupported"
    assert "compare_and_swap_profile" not in harness.repository.events
    assert not harness.repository.requests


def test_existing_unsupported_provider_is_never_ready():
    profile = provider_public_profile(
        provider_row(provider_type="anthropic")
    )

    assert profile.ready is False


@pytest.mark.asyncio
async def test_all_profile_reads_and_mutations_return_typed_public_projections():
    contaminated = provider_row(
        name=f"Provider {SECRET}",
        notes=f"Notes {PRIVATE_URL}",
        thinking={"authorization": SECRET, "safe": "visible"},
    )

    listed_harness = Harness(rows=[contaminated])
    listed = await listed_harness.service.list_profiles()

    create_harness = Harness(rows=[])
    created = await create_harness.service.create(
        create_command(
            name="Created Provider",
            notes="Public notes",
            thinking={"mode": "safe"},
        )
    )

    update_harness = Harness(rows=[contaminated])
    updated = await update_harness.service.update(
        ProviderUpdateCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="update-public-request-0001",
            changes={"model": "model-two"},
        )
    )

    clear_harness = Harness(rows=[contaminated])
    clear_command = ClearProviderApiKeyCommand(
        provider_id="provider-1",
        expected_revision=4,
        idempotency_key="clear-public-request-0001",
    )
    cleared = await clear_harness.service.clear_api_key(clear_command)
    replayed = await clear_harness.service.clear_api_key(clear_command)

    delete_harness = Harness(rows=[contaminated])
    deleted = await delete_harness.service.delete(
        DeleteProviderCommand(
            provider_id="provider-1",
            expected_revision=4,
            idempotency_key="delete-public-request-0001",
        )
    )

    for profile in [*listed, created, updated, cleared, replayed, deleted]:
        assert_public_profile(profile)
