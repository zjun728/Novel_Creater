"""Stateful Canon fakes for transaction-bound service unit tests."""

from __future__ import annotations

from contextlib import AbstractAsyncContextManager


class FakeCanonSession:
    pass


class FakeCanonTransaction(AbstractAsyncContextManager):
    def __init__(self, factory):
        self.factory = factory
        self.snapshot = None

    async def __aenter__(self):
        self.factory.enter_count += 1
        repository = self.factory.repository
        self.snapshot = {
            "state": {
                name: [dict(item) if isinstance(item, dict) else item for item in rows]
                for name, rows in repository.state.items()
            },
            "idempotent": dict(repository.idempotent),
            "head": repository.head,
            "projection_head": repository.projection_head,
            "head_hash": repository.head_hash,
        }
        return self.factory.session

    async def __aexit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.factory.commit_count += 1
            return False
        self.factory.rollback_count += 1
        repository = self.factory.repository
        repository.state = self.snapshot["state"]
        repository.idempotent = self.snapshot["idempotent"]
        repository.head = self.snapshot["head"]
        repository.projection_head = self.snapshot["projection_head"]
        repository.head_hash = self.snapshot["head_hash"]
        if self.factory.rollback_error is not None:
            raise BaseExceptionGroup(
                "transaction body failed and rollback also failed",
                [exc, self.factory.rollback_error],
            ) from exc
        return False


class FakeCanonTransactionFactory:
    def __init__(self, repository):
        self.repository = repository
        self.session = FakeCanonSession()
        self.enter_count = 0
        self.commit_count = 0
        self.rollback_count = 0
        self.rollback_error = None

    def __call__(self):
        return FakeCanonTransaction(self)


class FakeCanonRepository:
    def __init__(self):
        self.project = {"id": "project-1"}
        self.head = 0
        self.projection_head = 0
        self.head_hash = "0" * 64
        self.existing_entity_ids = set()
        self.alias_matches = {}
        self.active_events = []
        self.confirmed_events = []
        self.idempotent = {}
        self.calls = []
        self.write_calls = []
        self.fail_on = None
        self.state = {
            "revisions": [],
            "entities": [],
            "aliases": [],
            "events": [],
            "projections": [],
        }

    def _call(self, name, session, *args):
        self.calls.append((name, session, args))

    def _write(self, name, session, *args):
        self._call(name, session, *args)
        self.write_calls.append(name)
        if self.fail_on == name:
            raise RuntimeError(f"{name} failed")

    async def lock_project(self, session, project_id):
        self._call("lock_project", session, project_id)
        return self.project if project_id == self.project["id"] else None

    async def lock_head(self, session, project_id):
        self._call("lock_head", session, project_id)
        assert self.head == self.projection_head
        return self.head

    async def find_idempotent(self, session, project_id, key):
        self._call("find_idempotent", session, project_id, key)
        return self.idempotent.get((project_id, key))

    async def list_existing_entity_ids(self, session, project_id, entity_ids):
        self._call("list_existing_entity_ids", session, project_id, entity_ids)
        return tuple(sorted(self.existing_entity_ids.intersection(entity_ids)))

    async def list_alias_matches(self, session, project_id, normalized_alias):
        self._call("list_alias_matches", session, project_id, normalized_alias)
        return tuple(
            {"entity_id": entity_id, "normalized_alias": normalized_alias}
            for entity_id in sorted(self.alias_matches.get(normalized_alias, ()))
        )

    async def list_active_stable_events(self, session, project_id, scopes):
        self._call("list_active_stable_events", session, project_id, scopes)
        wanted = set(scopes)
        return tuple(
            event for event in self.active_events
            if (event.entity_id, event.field_path) in wanted
        )

    async def insert_revision(self, session, row):
        self._write("insert_revision", session, row)
        self.state["revisions"].append(dict(row))

    async def insert_entities(self, session, rows):
        self._write("insert_entities", session, rows)
        self.state["entities"].extend(dict(row) for row in rows)

    async def insert_aliases(self, session, rows):
        self._write("insert_aliases", session, rows)
        self.state["aliases"].extend(dict(row) for row in rows)

    async def insert_events(self, session, rows):
        self._write("insert_events", session, rows)
        self.state["events"].extend(dict(row) for row in rows)

    async def list_confirmed_events(self, session, project_id):
        self._call("list_confirmed_events", session, project_id)
        inserted = []
        for row in self.state["events"]:
            if row["confirmation_status"] != "confirmed":
                continue
            inserted.append({key: row[key] for key in (
                "id", "revision_number", "event_order", "entity_id",
                "fact_kind", "field_path", "value", "confirmation_status",
                "evidence",
            )})
        return tuple(self.confirmed_events) + tuple(inserted)

    async def replace_projections(self, session, project_id, bundle):
        self._write("replace_projections", session, project_id, bundle)
        self.state["projections"] = [bundle]

    async def set_revision_content_hash(self, session, revision_id, content_hash):
        self._write("set_revision_content_hash", session, revision_id, content_hash)
        for row in self.state["revisions"]:
            if row["id"] == revision_id:
                row["content_hash"] = content_hash
                self.idempotent[(row["project_id"], row["idempotency_key"])] = {
                    "id": row["id"],
                    "revision_number": row["revision_number"],
                    "content_hash": content_hash,
                }
                return
        raise AssertionError("revision not inserted")

    async def advance_heads(self, session, project_id, revision, content_hash):
        self._write("advance_heads", session, project_id, revision, content_hash)
        self.head = revision
        self.projection_head = revision
        self.head_hash = content_hash
