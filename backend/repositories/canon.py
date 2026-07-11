"""SQL persistence for immutable Canon revisions and derived projections."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
import time
from uuid import uuid4

from backend.domain.canon import CanonEventInput, thaw_json
from backend.services.projections import GLOBAL_PROJECTION_KEY, ProjectionBundle


_HASH = re.compile(r"[0-9a-f]{64}\Z")


class CanonDataCorruption(RuntimeError):
    """Persisted Canon and projection state violates required invariants."""


def _json(value: object) -> str:
    return json.dumps(
        thaw_json(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _decoded(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value


class CanonRepository:
    """Every runtime method is bound to its caller's database session."""

    def __init__(self, *, id_factory=None, clock=None):
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: int(time.time() * 1000))

    async def lock_head(self, session, project_id: str) -> int:
        row = await session.fetchone(
            """SELECT canon_revision_number, projection_revision_number, content_hash
               FROM projection_heads WHERE project_id=%s FOR UPDATE""",
            (project_id,),
        )
        if row is None:
            raise CanonDataCorruption("project projection head is missing")
        canon = row.get("canon_revision_number")
        projection = row.get("projection_revision_number")
        content_hash = row.get("content_hash")
        if type(canon) is not int or canon < 0 or projection != canon:
            raise CanonDataCorruption("Canon and projection heads are inconsistent")
        if not isinstance(content_hash, str) or not _HASH.fullmatch(content_hash):
            raise CanonDataCorruption("projection head hash is invalid")
        return canon

    async def find_idempotent(self, session, project_id: str, key: str):
        return await session.fetchone(
            """SELECT id, revision_number, content_hash FROM canon_revisions
               WHERE project_id=%s AND idempotency_key=%s""",
            (project_id, key),
        )

    async def list_existing_entity_ids(
        self, session, project_id: str, entity_ids: Sequence[str],
    ) -> tuple[str, ...]:
        if not entity_ids:
            return ()
        placeholders = ",".join(("%s",) * len(entity_ids))
        rows = await session.fetchall(
            f"SELECT id FROM canon_entities WHERE project_id=%s AND id IN ({placeholders})",
            (project_id, *entity_ids),
        )
        return tuple(row["id"] for row in rows)

    async def list_alias_matches(self, session, project_id: str, normalized_alias: str):
        return await session.fetchall(
            """SELECT entity_id, normalized_alias FROM entity_aliases
               WHERE project_id=%s AND normalized_alias=%s ORDER BY entity_id""",
            (project_id, normalized_alias),
        )

    async def list_active_stable_events(
        self, session, project_id: str, scopes: Sequence[tuple[str, str]],
    ) -> tuple[CanonEventInput, ...]:
        if not scopes:
            return ()
        clauses = " OR ".join("(entity_id=%s AND field_path=%s)" for _ in scopes)
        args = [project_id]
        for entity_id, field_path in scopes:
            args.extend((entity_id, field_path))
        rows = await session.fetchall(
            f"""SELECT entity_id, fact_kind, field_path, value_json, evidence_json,
                       effective_start_chapter, effective_end_chapter,
                       confirmation_status, assertion_operator, value_cardinality
                FROM canon_events
                WHERE project_id=%s AND fact_kind='stable_definition'
                  AND confirmation_status='confirmed' AND ({clauses})
                ORDER BY revision_number, event_order, id""",
            tuple(args),
        )
        return tuple(self._canon_event(row) for row in rows)

    @staticmethod
    def _canon_event(row: Mapping[str, object]) -> CanonEventInput:
        return CanonEventInput(
            entity_id=row["entity_id"], fact_kind=row["fact_kind"],
            field_path=row["field_path"], value=_decoded(row["value_json"]),
            evidence=_decoded(row["evidence_json"]),
            effective_start_chapter=row["effective_start_chapter"],
            effective_end_chapter=row["effective_end_chapter"],
            confirmation_status=row["confirmation_status"],
            assertion_operator=row["assertion_operator"],
            value_cardinality=row["value_cardinality"],
        )

    async def insert_revision(self, session, row: Mapping[str, object]) -> None:
        await session.execute(
            """INSERT INTO canon_revisions
               (id, project_id, revision_number, parent_revision_number,
                idempotency_key, source_type, source_id, content_hash, created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            tuple(row[key] for key in (
                "id", "project_id", "revision_number", "parent_revision_number",
                "idempotency_key", "source_type", "source_id", "content_hash",
                "created_at",
            )),
        )

    async def insert_entities(self, session, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            await session.execute(
                """INSERT INTO canon_entities
                   (id, project_id, entity_type, canonical_name, normalized_name,
                    created_revision, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                tuple(row[key] for key in (
                    "id", "project_id", "entity_type", "canonical_name",
                    "normalized_name", "created_revision", "created_at",
                )),
            )

    async def insert_aliases(self, session, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            await session.execute(
                """INSERT INTO entity_aliases
                   (id, project_id, entity_id, alias, normalized_alias,
                    created_revision, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                tuple(row[key] for key in (
                    "id", "project_id", "entity_id", "alias", "normalized_alias",
                    "created_revision", "created_at",
                )),
            )

    async def insert_events(self, session, rows: Sequence[Mapping[str, object]]) -> None:
        for row in rows:
            await session.execute(
                """INSERT INTO canon_events
                   (id, project_id, revision_id, revision_number, event_order,
                    entity_id, fact_kind, field_path, value_json, evidence_json,
                    effective_start_chapter, effective_end_chapter,
                    assertion_operator, value_cardinality, confirmation_status,
                    created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    row["id"], row["project_id"], row["revision_id"],
                    row["revision_number"], row["event_order"], row["entity_id"],
                    row["fact_kind"], row["field_path"], _json(row["value"]),
                    _json(row["evidence"]), row["effective_start_chapter"],
                    row["effective_end_chapter"], row["assertion_operator"],
                    row["value_cardinality"], row["confirmation_status"],
                    row["created_at"],
                ),
            )

    async def list_confirmed_events(self, session, project_id: str):
        rows = await session.fetchall(
            """SELECT id, revision_number, event_order, entity_id, fact_kind,
                      field_path, value_json, confirmation_status, evidence_json
               FROM canon_events
               WHERE project_id=%s AND confirmation_status='confirmed'
               ORDER BY revision_number, event_order, id""",
            (project_id,),
        )
        return tuple({
            "id": row["id"], "revision_number": row["revision_number"],
            "event_order": row["event_order"], "entity_id": row["entity_id"],
            "fact_kind": row["fact_kind"], "field_path": row["field_path"],
            "value": _decoded(row["value_json"]),
            "confirmation_status": row["confirmation_status"],
            "evidence": _decoded(row["evidence_json"]),
        } for row in rows)

    async def replace_projections(
        self, session, project_id: str, bundle: ProjectionBundle,
    ) -> None:
        for table in (
            "current_state_projections", "memory_views", "arc_projections",
            "plot_thread_projections",
        ):
            await session.execute(f"DELETE FROM {table} WHERE project_id=%s", (project_id,))
        created_at = self._clock()
        for entity_id, fields in bundle.current_state.items():
            for field_path, payload in fields.items():
                await session.execute(
                    """INSERT INTO current_state_projections
                       (id, project_id, revision_number, entity_id, field_path,
                        payload_json, content_hash, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (self._id_factory(), project_id, bundle.revision, entity_id,
                     field_path, _json(payload), bundle.content_hash, created_at),
                )
        for subject_key, payload in bundle.memories.items():
            entity_id = None if subject_key == GLOBAL_PROJECTION_KEY else subject_key
            await session.execute(
                """INSERT INTO memory_views
                   (id, project_id, entity_id, subject_key, payload_json,
                    revision_number, content_hash, created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (self._id_factory(), project_id, entity_id, subject_key,
                 _json(payload), bundle.revision, bundle.content_hash, created_at),
            )
        for entity_id, fields in bundle.arcs.items():
            for field_path, payload in fields.items():
                await session.execute(
                    """INSERT INTO arc_projections
                       (id, project_id, revision_number, entity_id, arc_key,
                        payload_json, content_hash, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (self._id_factory(), project_id, bundle.revision, entity_id,
                     field_path, _json(payload), bundle.content_hash, created_at),
                )
        for subject_key, fields in bundle.plot_threads.items():
            entity_id = None if subject_key == GLOBAL_PROJECTION_KEY else subject_key
            for field_path, payload in fields.items():
                await session.execute(
                    """INSERT INTO plot_thread_projections
                       (id, project_id, entity_id, subject_key, field_path,
                        payload_json, revision_number, content_hash, created_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (self._id_factory(), project_id, entity_id, subject_key,
                     field_path, _json(payload), bundle.revision,
                     bundle.content_hash, created_at),
                )

    async def set_revision_content_hash(
        self, session, revision_id: str, content_hash: str,
    ) -> None:
        affected = await session.execute(
            "UPDATE canon_revisions SET content_hash=%s WHERE id=%s",
            (content_hash, revision_id),
        )
        if affected != 1:
            raise CanonDataCorruption("Canon revision hash update affected no row")

    async def advance_heads(
        self, session, project_id: str, revision: int, content_hash: str,
    ) -> None:
        affected = await session.execute(
            """UPDATE projection_heads
               SET canon_revision_number=%s, projection_revision_number=%s,
                   content_hash=%s, updated_at=%s WHERE project_id=%s""",
            (revision, revision, content_hash, self._clock(), project_id),
        )
        if affected != 1:
            raise CanonDataCorruption("projection head update affected no row")
