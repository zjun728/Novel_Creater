"""Transactional Provider profile commands and private connection projection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import time
from typing import Any
from uuid import uuid4

import aiomysql

from backend.gateways.provider_connection import SUPPORTED_PROVIDER_TYPES
from backend.http_errors import PublicDomainError
from backend.security.provider_secrets import (
    PUBLIC_SECRET_COLLISION_MESSAGE,
    normalize_provider_secrets,
    provider_public_fields_contain_secret,
    sanitize_provider_public_value,
)
from backend.serializers.provider import (
    ProviderConnectionPublicResult,
    ProviderPublicProfile,
    provider_public_profile,
)


class ProviderProfileNotFound(PublicDomainError):
    status_code = 404
    code = "provider_not_found"
    message = "Provider 不存在"


class ProviderProfileConflict(PublicDomainError):
    status_code = 409
    code = "provider_conflict"
    message = "Provider 配置已变化，请刷新后重试"


class ProviderIdempotencyConflict(PublicDomainError):
    status_code = 409
    code = "provider_idempotency_conflict"
    message = "幂等键已用于不同的 Provider 操作"


class ProviderMutationResultUnavailable(PublicDomainError):
    status_code = 409
    code = "provider_result_superseded"
    message = "Provider 操作结果已被后续修改取代，请刷新"


class ProviderPublicSecretCollision(PublicDomainError):
    status_code = 422
    code = "provider_public_secret_collision"
    message = PUBLIC_SECRET_COLLISION_MESSAGE


class ProviderTypeUnsupported(PublicDomainError):
    status_code = 422
    code = "provider_type_unsupported"
    message = "Unsupported Provider type"


class ProviderMutationRetryableConflict(PublicDomainError):
    status_code = 409
    code = "provider_mutation_retryable_conflict"
    message = "Provider mutation conflicted; retry the request"
    retryable = True


@dataclass(frozen=True)
class ProviderCreateCommand:
    name: str
    provider_type: str
    model: str
    base_url: str
    api_key: str
    enabled: bool
    sort_order: int
    stream: bool
    max_context_tokens: int
    max_output_tokens: int
    temperature: float
    top_p: float
    supports_json: bool
    supports_streaming: bool
    notes: str
    thinking: dict | None
    idempotency_key: str


@dataclass(frozen=True)
class ProviderUpdateCommand:
    provider_id: str
    expected_revision: int
    idempotency_key: str
    changes: Mapping[str, Any]


@dataclass(frozen=True)
class ClearProviderApiKeyCommand:
    provider_id: str
    expected_revision: int
    idempotency_key: str


@dataclass(frozen=True)
class DeleteProviderCommand:
    provider_id: str
    expected_revision: int
    idempotency_key: str


class SqlProviderProfileRepository:
    """Every query uses a caller-owned connection or transaction session."""

    async def list_profiles(self, session):
        return await session.fetchall(
            """SELECT * FROM provider_profiles
               WHERE lifecycle_status<>'deleted'
               ORDER BY sort_order,created_at,id"""
        )

    async def lock_create_guard(self, session) -> None:
        row = await session.fetchone(
            """SELECT singleton_id FROM schema_metadata
               WHERE singleton_id=1 FOR UPDATE"""
        )
        if row is None:
            raise RuntimeError("provider mutation guard is unavailable")

    async def lock_create_request(self, session, idempotency_key: str):
        return await session.fetchone(
            """SELECT id AS request_id,provider_id,idempotency_key,request_hash,
                      mutation_kind,expected_revision,status,result_revision,
                      public_error_code,created_at,completed_at
               FROM provider_profile_mutation_requests
               WHERE idempotency_key=%s AND mutation_kind='create'
               ORDER BY created_at,id LIMIT 1 FOR UPDATE""",
            (idempotency_key,),
        )

    async def lock_mutation_request(
        self, session, provider_id: str, idempotency_key: str
    ):
        return await session.fetchone(
            """SELECT id AS request_id,provider_id,idempotency_key,request_hash,
                      mutation_kind,expected_revision,status,result_revision,
                      public_error_code,created_at,completed_at
               FROM provider_profile_mutation_requests
               WHERE provider_id=%s AND idempotency_key=%s FOR UPDATE""",
            (provider_id, idempotency_key),
        )

    async def lock_profile(self, session, provider_id: str):
        return await session.fetchone(
            "SELECT * FROM provider_profiles WHERE id=%s FOR UPDATE",
            (provider_id,),
        )

    async def read_profile(self, session, provider_id: str):
        return await session.fetchone(
            "SELECT * FROM provider_profiles WHERE id=%s",
            (provider_id,),
        )

    async def read_connection_profile(self, session, provider_id: str):
        return await session.fetchone(
            """SELECT provider_type,model_name,base_url,api_key,enabled,
                      lifecycle_status
               FROM provider_profiles WHERE id=%s""",
            (provider_id,),
        )

    async def insert_profile(self, session, row: Mapping[str, Any]) -> None:
        await session.execute(
            """INSERT INTO provider_profiles
               (id,name,provider_type,model_name,base_url,api_key,enabled,
                sort_order,stream,max_context_tokens,max_output_tokens,
                temperature,top_p,supports_json,supports_streaming,notes,
                thinking,lifecycle_status,revision,deleted_at,created_at,
                updated_at)
               VALUES
               (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s)""",
            (
                row["id"],
                row["name"],
                row["provider_type"],
                row["model_name"],
                row["base_url"],
                row["api_key"],
                row["enabled"],
                row["sort_order"],
                row["stream"],
                row["max_context_tokens"],
                row["max_output_tokens"],
                row["temperature"],
                row["top_p"],
                row["supports_json"],
                row["supports_streaming"],
                row["notes"],
                _json_database_value(row.get("thinking")),
                row["lifecycle_status"],
                row["revision"],
                row["deleted_at"],
                row["created_at"],
                row["updated_at"],
            ),
        )

    async def compare_and_swap_profile(
        self,
        session,
        provider_id: str,
        expected_revision: int,
        changes: Mapping[str, Any],
    ) -> bool:
        columns = tuple(changes)
        assignments = ",".join(f"{column}=%s" for column in columns)
        values = [
            _json_database_value(changes[column])
            if column == "thinking"
            else changes[column]
            for column in columns
        ]
        changed = await session.execute(
            f"""UPDATE provider_profiles SET {assignments}
                WHERE id=%s AND revision=%s""",
            (*values, provider_id, expected_revision),
        )
        return changed == 1

    async def insert_mutation_request(
        self, session, request: Mapping[str, Any]
    ) -> None:
        await session.execute(
            """INSERT INTO provider_profile_mutation_requests
               (id,provider_id,idempotency_key,request_hash,mutation_kind,
                expected_revision,status,result_revision,public_error_code,
                created_at,completed_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                request["id"],
                request["provider_id"],
                request["idempotency_key"],
                request["request_hash"],
                request["mutation_kind"],
                request["expected_revision"],
                request["status"],
                request["result_revision"],
                request["public_error_code"],
                request["created_at"],
                request["completed_at"],
            ),
        )


def _json_database_value(value):
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _fingerprint(kind: str, value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"kind": kind, **value},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _mysql_error_number(error: BaseException) -> int | None:
    args = getattr(error, "args", ())
    return args[0] if args and isinstance(args[0], int) else None


_PUBLIC_PROFILE_COLUMNS = (
    "name",
    "provider_type",
    "model_name",
    "notes",
    "thinking",
)
_PUBLIC_PROFILE_LIMITS = {
    "name": {"max_chars": 120},
    "provider_type": {"max_chars": 64},
    "model_name": {"max_chars": 160},
    "notes": {"max_utf8_bytes": 65_535},
}


def _sanitize_profile_public_column(column, value, secrets):
    return sanitize_provider_public_value(
        value,
        secrets,
        **_PUBLIC_PROFILE_LIMITS.get(column, {}),
    )


def _raise_on_public_secret_collision(value, secrets) -> None:
    if provider_public_fields_contain_secret(value, secrets):
        raise ProviderPublicSecretCollision()


class ProviderProfileService:
    _UPDATE_COLUMNS = {
        "name": "name",
        "model": "model_name",
        "baseURL": "base_url",
        "apiKey": "api_key",
        "enabled": "enabled",
        "sortOrder": "sort_order",
        "stream": "stream",
        "maxContextTokens": "max_context_tokens",
        "maxOutputTokens": "max_output_tokens",
        "temperature": "temperature",
        "topP": "top_p",
        "supportsJSON": "supports_json",
        "supportsStreaming": "supports_streaming",
        "notes": "notes",
        "thinking": "thinking",
    }
    _BOOLEAN_COLUMNS = {
        "enabled",
        "stream",
        "supports_json",
        "supports_streaming",
    }
    _CONNECTION_MESSAGES = {
        "connected": "连接成功",
        "provider_timeout": "连接超时",
        "provider_unreachable": "无法连接 Provider",
        "provider_rejected": "Provider 拒绝连接",
        "provider_unconfigured": "Provider 未配置",
        "provider_unsupported": "不支持的 Provider 类型",
        "provider_failed": "连接测试失败",
    }

    def __init__(
        self,
        repository,
        *,
        transaction_factory,
        connection_factory,
        connection_gateway,
        id_factory=None,
        clock=None,
    ):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory
        self.connection_gateway = connection_gateway
        self.id_factory = id_factory or (lambda: str(uuid4()))
        self.clock = clock or (lambda: int(time.time() * 1000))

    async def list_profiles(self) -> list[ProviderPublicProfile]:
        async with self.connection_factory() as session:
            rows = await self.repository.list_profiles(session)
        return [provider_public_profile(row) for row in rows]

    async def _recover(
        self,
        session,
        request: Mapping[str, Any],
        *,
        kind: str,
        request_hash: str,
        expected_revision: int,
        row: Mapping[str, Any] | None = None,
    ):
        if (
            request["mutation_kind"] != kind
            or request["request_hash"] != request_hash
            or int(request["expected_revision"]) != expected_revision
            or request["status"] != "succeeded"
        ):
            raise ProviderIdempotencyConflict()
        if row is None:
            row = await self.repository.read_profile(
                session, request["provider_id"]
            )
        if (
            row is None
            or int(row["revision"]) != int(request["result_revision"])
        ):
            raise ProviderMutationResultUnavailable()
        return row

    async def _record_success(
        self,
        session,
        *,
        provider_id: str,
        idempotency_key: str,
        request_hash: str,
        kind: str,
        expected_revision: int,
        result_revision: int,
        now: int,
    ) -> None:
        await self.repository.insert_mutation_request(
            session,
            {
                "id": self.id_factory(),
                "provider_id": provider_id,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "mutation_kind": kind,
                "expected_revision": expected_revision,
                "status": "succeeded",
                "result_revision": result_revision,
                "public_error_code": None,
                "created_at": now,
                "completed_at": now,
            },
        )

    async def create(
        self, command: ProviderCreateCommand
    ) -> ProviderPublicProfile:
        provider_type = command.provider_type.strip()
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ProviderTypeUnsupported()
        secrets = normalize_provider_secrets(
            (command.api_key, command.base_url)
        )
        _raise_on_public_secret_collision(
            {
                "name": command.name.strip(),
                "provider_type": provider_type,
                "model_name": command.model.strip(),
                "notes": command.notes,
                "thinking": command.thinking,
            },
            secrets,
        )
        fingerprint_values = asdict(command)
        fingerprint_values.pop("idempotency_key")
        request_hash = _fingerprint("create", fingerprint_values)
        try:
            async with self.transaction_factory() as session:
                lock_guard = getattr(
                    self.repository, "lock_create_guard", None
                )
                if lock_guard is not None:
                    await lock_guard(session)
                previous = await self.repository.lock_create_request(
                    session, command.idempotency_key
                )
                if previous is not None:
                    row = await self._recover(
                        session,
                        previous,
                        kind="create",
                        request_hash=request_hash,
                        expected_revision=0,
                    )
                    return provider_public_profile(row)
                now = self.clock()
                provider_id = self.id_factory()
                api_key = command.api_key.strip()
                base_url = command.base_url.strip()
                row = {
                    "id": provider_id,
                    "name": command.name.strip(),
                    "provider_type": provider_type,
                    "model_name": command.model.strip(),
                    "base_url": base_url,
                    "api_key": api_key,
                    "enabled": int(command.enabled),
                    "sort_order": command.sort_order,
                    "stream": int(command.stream),
                    "max_context_tokens": command.max_context_tokens,
                    "max_output_tokens": command.max_output_tokens,
                    "temperature": command.temperature,
                    "top_p": command.top_p,
                    "supports_json": int(command.supports_json),
                    "supports_streaming": int(command.supports_streaming),
                    "notes": command.notes,
                    "thinking": command.thinking,
                    "lifecycle_status": "active",
                    "revision": 1,
                    "deleted_at": None,
                    "created_at": now,
                    "updated_at": now,
                }
                await self.repository.insert_profile(session, row)
                await self._record_success(
                    session,
                    provider_id=provider_id,
                    idempotency_key=command.idempotency_key,
                    request_hash=request_hash,
                    kind="create",
                    expected_revision=0,
                    result_revision=1,
                    now=now,
                )
                return provider_public_profile(row)
        except aiomysql.OperationalError as error:
            if _mysql_error_number(error) in {1205, 1213}:
                raise ProviderMutationRetryableConflict() from None
            raise

    async def update(
        self, command: ProviderUpdateCommand
    ) -> ProviderPublicProfile:
        changes = dict(command.changes)
        for secret_field in ("apiKey", "baseURL"):
            value = changes.get(secret_field)
            if not isinstance(value, str) or not value.strip():
                changes.pop(secret_field, None)
        submitted_secrets = normalize_provider_secrets(
            (changes.get("apiKey"), changes.get("baseURL"))
        )
        _raise_on_public_secret_collision(
            {
                key: value
                for key, value in changes.items()
                if key in {"name", "model", "notes", "thinking"}
            },
            submitted_secrets,
        )
        request_hash = _fingerprint(
            "update",
            {
                "provider_id": command.provider_id,
                "expected_revision": command.expected_revision,
                "changes": changes,
            },
        )
        row = await self._mutate(
            provider_id=command.provider_id,
            expected_revision=command.expected_revision,
            idempotency_key=command.idempotency_key,
            kind="update",
            request_hash=request_hash,
            change_builder=lambda current, now: self._update_changes(
                current, changes, now
            ),
        )
        return provider_public_profile(row)

    def _update_changes(self, current, incoming, now):
        provider_type = (
            str(current.get("provider_type") or "").strip().casefold()
        )
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            raise ProviderTypeUnsupported()
        changes = {}
        for public_name, value in incoming.items():
            column = self._UPDATE_COLUMNS[public_name]
            if column in {"api_key", "base_url", "name", "model_name"}:
                value = value.strip()
            if column in self._BOOLEAN_COLUMNS:
                value = int(value)
            changes[column] = value
        next_key = changes.get("api_key", current.get("api_key"))
        next_url = changes.get("base_url", current.get("base_url"))
        submitted_secrets = normalize_provider_secrets(
            (changes.get("api_key"), changes.get("base_url"))
        )
        secrets = normalize_provider_secrets(
            (
                current.get("api_key"),
                current.get("base_url"),
                next_key,
                next_url,
            )
        )
        _raise_on_public_secret_collision(
            {
                column: changes[column]
                for column in _PUBLIC_PROFILE_COLUMNS
                if column in changes
            },
            secrets,
        )
        _raise_on_public_secret_collision(
            {
                column: current.get(column)
                for column in _PUBLIC_PROFILE_COLUMNS
                if column not in changes
            },
            submitted_secrets,
        )
        for column in _PUBLIC_PROFILE_COLUMNS:
            value = changes.get(column, current.get(column))
            sanitized = _sanitize_profile_public_column(
                column, value, secrets
            )
            if sanitized != value or column in changes:
                changes[column] = sanitized
        configured = bool(
            isinstance(next_key, str)
            and next_key.strip()
            and isinstance(next_url, str)
            and next_url.strip()
        )
        changes["lifecycle_status"] = "active" if configured else "unconfigured"
        if not configured:
            changes["enabled"] = 0
        changes["deleted_at"] = None
        changes["revision"] = int(current["revision"]) + 1
        changes["updated_at"] = now
        return changes

    async def clear_api_key(
        self, command: ClearProviderApiKeyCommand
    ) -> ProviderPublicProfile:
        request_hash = _fingerprint(
            "clear_key",
            {
                "provider_id": command.provider_id,
                "expected_revision": command.expected_revision,
            },
        )
        row = await self._mutate(
            provider_id=command.provider_id,
            expected_revision=command.expected_revision,
            idempotency_key=command.idempotency_key,
            kind="clear_key",
            request_hash=request_hash,
            change_builder=lambda current, now: {
                "api_key": "",
                "enabled": 0,
                "lifecycle_status": "unconfigured",
                "deleted_at": None,
                "revision": int(current["revision"]) + 1,
                "updated_at": now,
            },
        )
        return provider_public_profile(row)

    async def delete(
        self, command: DeleteProviderCommand
    ) -> ProviderPublicProfile:
        request_hash = _fingerprint(
            "delete",
            {
                "provider_id": command.provider_id,
                "expected_revision": command.expected_revision,
            },
        )
        row = await self._mutate(
            provider_id=command.provider_id,
            expected_revision=command.expected_revision,
            idempotency_key=command.idempotency_key,
            kind="delete",
            request_hash=request_hash,
            change_builder=lambda current, now: {
                "api_key": "",
                "base_url": "",
                "enabled": 0,
                "lifecycle_status": "deleted",
                "deleted_at": now,
                "revision": int(current["revision"]) + 1,
                "updated_at": now,
            },
        )
        return provider_public_profile(row)

    async def _mutate(
        self,
        *,
        provider_id: str,
        expected_revision: int,
        idempotency_key: str,
        kind: str,
        request_hash: str,
        change_builder,
    ):
        try:
            async with self.transaction_factory() as session:
                current = await self.repository.lock_profile(
                    session, provider_id
                )
                if current is None:
                    raise ProviderProfileNotFound()
                previous = await self.repository.lock_mutation_request(
                    session, provider_id, idempotency_key
                )
                if previous is not None:
                    return await self._recover(
                        session,
                        previous,
                        kind=kind,
                        request_hash=request_hash,
                        expected_revision=expected_revision,
                        row=current,
                    )
                if current["lifecycle_status"] == "deleted":
                    raise ProviderProfileNotFound()
                if int(current["revision"]) != expected_revision:
                    raise ProviderProfileConflict()
                now = self.clock()
                changes = change_builder(current, now)
                redaction_values = normalize_provider_secrets(
                    (current.get("api_key"), current.get("base_url"))
                )
                for column in _PUBLIC_PROFILE_COLUMNS:
                    value = changes.get(column, current.get(column))
                    sanitized = _sanitize_profile_public_column(
                        column, value, redaction_values
                    )
                    if sanitized != value:
                        changes[column] = sanitized
                if not await self.repository.compare_and_swap_profile(
                    session, provider_id, expected_revision, changes
                ):
                    raise ProviderProfileConflict()
                await self._record_success(
                    session,
                    provider_id=provider_id,
                    idempotency_key=idempotency_key,
                    request_hash=request_hash,
                    kind=kind,
                    expected_revision=expected_revision,
                    result_revision=changes["revision"],
                    now=now,
                )
                return {**current, **changes}
        except aiomysql.OperationalError as error:
            if _mysql_error_number(error) in {1205, 1213}:
                raise ProviderMutationRetryableConflict() from None
            raise

    async def test_connection(
        self, provider_id: str
    ) -> ProviderConnectionPublicResult:
        async with self.connection_factory() as session:
            row = await self.repository.read_connection_profile(
                session, provider_id
            )
        if row is None or row["lifecycle_status"] == "deleted":
            raise ProviderProfileNotFound()
        provider_type = (
            str(row.get("provider_type") or "").strip().casefold()
        )
        if provider_type not in SUPPORTED_PROVIDER_TYPES:
            return self._connection_result(
                ok=False, code="provider_unsupported", latency_ms=0
            )
        if (
            row["lifecycle_status"] != "active"
            or not isinstance(row.get("api_key"), str)
            or not row["api_key"].strip()
            or not isinstance(row.get("base_url"), str)
            or not row["base_url"].strip()
        ):
            return self._connection_result(
                ok=False, code="provider_unconfigured", latency_ms=0
            )
        private_projection = {
            "provider_type": provider_type,
            "model_name": row["model_name"],
            "base_url": row["base_url"],
            "api_key": row["api_key"],
        }
        try:
            result = await self.connection_gateway.test_connection(
                private_projection
            )
        except Exception:
            return self._connection_result(
                ok=False, code="provider_failed", latency_ms=0
            )
        code = result.get("code")
        if code not in self._CONNECTION_MESSAGES:
            code = "provider_failed"
        return self._connection_result(
            ok=result.get("ok") is True and code == "connected",
            code=code,
            latency_ms=result.get("latencyMs"),
        )

    def _connection_result(
        self, *, ok: bool, code: str, latency_ms
    ) -> ProviderConnectionPublicResult:
        try:
            bounded_latency = min(30_000, max(0, int(latency_ms)))
        except (TypeError, ValueError, OverflowError):
            bounded_latency = 0
        return ProviderConnectionPublicResult(
            ok=ok,
            code=code,
            latency_ms=bounded_latency,
            public_message=self._CONNECTION_MESSAGES[code],
        )
