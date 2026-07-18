"""Versioned model-provider binding use cases."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from backend.domain.json_contracts import canonical_hash
from backend.domain.model_bindings import TASK_KEYS, BindingItem, BindingRevision
from backend.gateways.provider_connection import SUPPORTED_PROVIDER_TYPES
from backend.http_errors import (
    BindingConflict,
    BindingNotFound,
    BindingProviderUnavailable,
)
from backend.security.provider_secrets import (
    normalize_provider_secrets,
    sanitize_provider_secret_text,
)


def _redact_display(value: str, secrets: tuple[str, ...]) -> str:
    return sanitize_provider_secret_text(value, secrets)


def provider_is_available(row: Mapping, *, prefix: str = "") -> bool:
    """Single readiness predicate shared by initialize, replace, and status."""

    def value(name):
        return row.get(f"{prefix}{name}")

    return (
        value("lifecycle_status") == "active"
        and int(value("enabled") or 0) == 1
        and isinstance(value("provider_type"), str)
        and value("provider_type").strip().casefold()
        in SUPPORTED_PROVIDER_TYPES
        and all(
            isinstance(value(field), str) and bool(value(field).strip())
            for field in ("model_name", "base_url", "api_key")
        )
    )


@dataclass(frozen=True)
class BindingResult:
    project_id: str
    revision: int
    content_hash: str
    source_project_id: str | None
    items: tuple[BindingItem, ...]
    binding_complete: bool
    binding_ready: bool
    reasons: tuple[str, ...]
    redaction_values: tuple[str, ...] = ()


class ModelBindingService:
    def __init__(self, repository, *, transaction_factory, connection_factory=None):
        self.repository = repository
        self.transaction_factory = transaction_factory
        self.connection_factory = connection_factory

    async def lock_project_creation(self, session) -> None:
        await self.repository.lock_project_creation_guard(session)

    @staticmethod
    def _bound_item(task_key: str, provider: Mapping) -> BindingItem:
        secrets = normalize_provider_secrets(
            (provider.get("api_key"), provider.get("base_url"))
        )

        return BindingItem(
            task_key=task_key,
            resolution_status="bound",
            provider_id=provider["id"],
            provider_name_snapshot=_redact_display(provider["name"], secrets),
            model_name_snapshot=_redact_display(provider["model_name"], secrets),
        )

    @staticmethod
    def _unbound_item(task_key: str) -> BindingItem:
        return BindingItem(
            task_key=task_key,
            resolution_status="unbound",
            provider_id=None,
            provider_name_snapshot=None,
            model_name_snapshot=None,
        )

    async def _write_revision(
        self,
        session,
        *,
        project_id: str,
        revision: int,
        items: tuple[BindingItem, ...],
        source_project_id: str | None,
        insert_head: bool,
        expected_revision: int | None = None,
    ) -> BindingRevision:
        domain_revision = BindingRevision(
            project_id=project_id, revision=revision, items=items
        )
        content_hash = canonical_hash(domain_revision)
        revision_id = self.repository.id_factory()
        now = self.repository.clock()
        await self.repository.insert_revision(
            session,
            {
                "id": revision_id,
                "project_id": project_id,
                "revision": revision,
                "content_hash": content_hash,
                "source_project_id": source_project_id,
                "created_at": now,
            },
        )
        await self.repository.insert_items(
            session,
            revision_id,
            tuple(
                {**item.model_dump(mode="json"), "item_hash": canonical_hash(item)}
                for item in items
            ),
        )
        head = {
            "project_id": project_id,
            "revision": revision,
            "binding_revision_id": revision_id,
            "content_hash": content_hash,
            "updated_at": now,
        }
        if insert_head:
            await self.repository.insert_head(session, head)
        elif not await self.repository.compare_and_swap_head(
            session, head, expected_revision=expected_revision
        ):
            raise BindingConflict()
        return domain_revision

    async def initialize_project(self, session, project_id: str) -> None:
        previous_project = await self.repository.lock_previous_project(
            session, project_id
        )
        source_project_id = previous_project["id"] if previous_project else None
        previous_rows = (
            await self.repository.lock_current_rows(session, source_project_id)
            if source_project_id else []
        )
        previous_by_task = {
            row["task_key"]: row.get("provider_id") for row in previous_rows
        }
        candidates = await self.repository.list_available_providers(session)
        locked_providers = await self.repository.lock_providers(
            session, {row["id"] for row in candidates}
        )
        available = sorted(
            (row for row in locked_providers if provider_is_available(row)),
            key=lambda row: (
                int(row["sort_order"]), int(row["created_at"]), row["id"]
            ),
        )
        available_by_id = {row["id"]: row for row in available}
        fallback = available[0] if available else None
        items = []
        for task_key in TASK_KEYS:
            provider = available_by_id.get(previous_by_task.get(task_key)) or fallback
            items.append(
                self._bound_item(task_key, provider)
                if provider else self._unbound_item(task_key)
            )
        await self._write_revision(
            session,
            project_id=project_id,
            revision=1,
            items=tuple(items),
            source_project_id=source_project_id,
            insert_head=True,
        )

    def _connection(self):
        if self.connection_factory is None:
            raise RuntimeError("read connection factory is not configured")
        return self.connection_factory()

    @staticmethod
    def _from_rows(project_id: str, rows) -> BindingResult:
        if not rows:
            raise BindingNotFound()
        items = tuple(
            BindingItem(
                task_key=row["task_key"],
                resolution_status=row["resolution_status"],
                provider_id=row.get("provider_id"),
                provider_name_snapshot=row.get("provider_name_snapshot"),
                model_name_snapshot=row.get("model_name_snapshot"),
            )
            for row in rows
        )
        keys = tuple(item.task_key for item in items)
        complete = keys == TASK_KEYS
        reasons = []
        if not complete:
            reasons.append("binding_incomplete")
        for item, row in zip(items, rows):
            if item.resolution_status != "bound":
                reasons.append(f"task_unbound:{item.task_key}")
                continue
            if not provider_is_available(row, prefix="current_"):
                reasons.append(f"provider_unavailable:{item.task_key}")
            else:
                current_secrets = normalize_provider_secrets(
                    (
                        row.get("current_api_key"),
                        row.get("current_base_url"),
                    )
                )
                current_model = _redact_display(
                    row.get("current_model_name") or "", current_secrets
                )
                if current_model != item.model_name_snapshot:
                    reasons.append(f"model_snapshot_mismatch:{item.task_key}")
        ready = complete and not reasons
        first = rows[0]
        redaction_values = normalize_provider_secrets(
            value
            for row in rows
            for value in (
                row.get("current_api_key"), row.get("current_base_url")
            )
        )
        return BindingResult(
            project_id=project_id,
            revision=int(first["revision"]),
            content_hash=first["content_hash"],
            source_project_id=first.get("source_project_id"),
            items=items,
            binding_complete=complete,
            binding_ready=ready,
            reasons=tuple(reasons),
            redaction_values=redaction_values,
        )

    async def get_current(self, project_id: str) -> BindingResult:
        async with self._connection() as session:
            if await self.repository.read_project(session, project_id) is None:
                raise BindingNotFound()
            rows = await self.repository.read_current_rows(session, project_id)
        return self._from_rows(project_id, rows)

    async def get_status(self, project_id: str) -> BindingResult:
        return await self.get_current(project_id)

    async def replace_all(
        self,
        project_id: str,
        expected_revision: int,
        mapping: Mapping[str, str | None],
    ) -> BindingResult:
        if set(mapping) != set(TASK_KEYS) or len(mapping) != len(TASK_KEYS):
            raise BindingProviderUnavailable()
        async with self.transaction_factory() as session:
            if await self.repository.lock_project(session, project_id) is None:
                raise BindingNotFound()
            current = await self.repository.lock_current_rows(session, project_id)
            if not current:
                raise BindingNotFound()
            if int(current[0]["revision"]) != expected_revision:
                raise BindingConflict()
            requested_ids = {provider_id for provider_id in mapping.values() if provider_id}
            providers = await self.repository.lock_providers(session, requested_ids)
            providers_by_id = {row["id"]: row for row in providers}
            if any(
                provider_id not in providers_by_id
                or not provider_is_available(providers_by_id[provider_id])
                for provider_id in requested_ids
            ):
                raise BindingProviderUnavailable()
            items = tuple(
                self._bound_item(task_key, providers_by_id[mapping[task_key]])
                if mapping[task_key] is not None
                else self._unbound_item(task_key)
                for task_key in TASK_KEYS
            )
            await self._write_revision(
                session,
                project_id=project_id,
                revision=expected_revision + 1,
                items=items,
                source_project_id=None,
                insert_head=False,
                expected_revision=expected_revision,
            )
            rows = await self.repository.read_current_rows(session, project_id)
        return self._from_rows(project_id, rows)
